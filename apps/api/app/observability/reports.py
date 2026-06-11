"""Static JSON/Markdown/HTML observability report generation."""
from __future__ import annotations

import argparse
import asyncio
import html
import json
from pathlib import Path
from typing import Any

from app.observability.metrics import build_access_observability_metrics, build_observability_summary
from app.observability.replay import RetrievalReplayService
from app.retrieval.controller import RetrievalController
from app.runtime.models import (
    ContextCompactionLog,
    MemoryAccessLog,
    MemoryGateLog,
    MemoryItem,
    ObservabilityReportRequest,
    ObservabilityReportResult,
    ObservabilitySummary,
    ReplayRetrievalResult,
)
from app.runtime.repository import Repository


_REPORT_BASENAME = "observability_report"


async def write_observability_report(
    repo: Repository,
    retrieval: RetrievalController,
    request: ObservabilityReportRequest,
) -> ObservabilityReportResult:
    """Write deterministic JSON/Markdown/HTML observability reports.

    The report is read-only: it aggregates persisted access/gate logs and, when
    requested, calls the side-effect-free replay service. It never writes
    access/gate/profile rows and never mutates memory access counters.
    """
    output_dir = _safe_output_dir(request.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = await build_observability_summary(repo, workspace_id=request.workspace_id, run_id=request.run_id)
    accesses = await _filtered_accesses(repo, workspace_id=request.workspace_id, run_id=request.run_id)
    replay_service = RetrievalReplayService(repo, retrieval)

    access_rows: list[dict[str, Any]] = []
    replays: list[ReplayRetrievalResult] = []
    compaction_rows: list[dict[str, Any]] = []
    for access in accesses:
        gate_logs = await repo.list_gate_logs(access.access_id)
        compaction_logs = [
            log
            for log in await repo.list_compaction_logs(access_id=access.access_id, workspace_id=access.workspace_id)
            if log.run_id == access.run_id
        ]
        compaction_rows.extend(_compaction_rows(access, compaction_logs))
        candidate_memories = await _candidate_memories(repo, gate_logs)
        accepted_memories = await _accepted_memories(repo, gate_logs)
        metrics = build_access_observability_metrics(access, gate_logs, candidate_memories, accepted_memories, compaction_logs)
        replay = await replay_service.replay_access(access.access_id) if request.include_replay else None
        if replay is not None:
            replays.append(replay)
        access_rows.append(
            {
                "access_id": access.access_id,
                "run_id": access.run_id,
                "query": access.query,
                "strategy": access.retrieval_strategy.value,
                "metrics": _sorted_metrics(metrics),
                "critical_drift_count": _critical_drift_count(replay),
                "context_block_count": _context_block_count(replay, access),
            }
        )

    payload: dict[str, Any] = {
        "summary": summary.model_dump(mode="json"),
        "accesses": access_rows,
        "compactions": compaction_rows,
        "replays": [replay.model_dump(mode="json") for replay in replays],
    }

    json_path = output_dir / f"{_REPORT_BASENAME}.json"
    markdown_path = output_dir / f"{_REPORT_BASENAME}.md"
    html_path = output_dir / f"{_REPORT_BASENAME}.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    markdown_path.write_text(_render_markdown(payload, summary, replays))
    html_path.write_text(_render_html(payload, summary, replays))

    return ObservabilityReportResult(
        json_path=_relative_posix(json_path),
        markdown_path=_relative_posix(markdown_path),
        html_path=_relative_posix(html_path),
        summary=summary,
    )


def _safe_output_dir(output_dir: str) -> Path:
    path = Path(output_dir)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe output_dir: must be a relative path under reports/")
    if not path.parts or path.parts[0] != "reports":
        raise ValueError("unsafe output_dir: must stay under reports/")
    current = Path.cwd()
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("unsafe output_dir: symlinks are not allowed under reports/")
    root = Path.cwd().resolve() / "reports"
    try:
        resolved = (Path.cwd() / path).resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError("unsafe output_dir: could not resolve path safely") from exc
    if resolved != root and root not in resolved.parents:
        raise ValueError("unsafe output_dir: resolved path escapes reports/")
    return path


async def _filtered_accesses(
    repo: Repository,
    *,
    workspace_id: str | None,
    run_id: str | None,
) -> list[MemoryAccessLog]:
    accesses = await repo.list_access_logs(workspace_id=workspace_id)
    if run_id is not None:
        accesses = [access for access in accesses if access.run_id == run_id]
    accesses.sort(key=lambda access: (access.created_at, access.access_id))
    return accesses


async def _candidate_memories(repo: Repository, gate_logs: list[MemoryGateLog]) -> list[MemoryItem]:
    memories: list[MemoryItem] = []
    for gate_log in gate_logs:
        memory = await repo.get_memory(gate_log.memory_id)
        if memory is not None:
            memories.append(memory)
    return memories


async def _accepted_memories(repo: Repository, gate_logs: list[MemoryGateLog]) -> list[MemoryItem]:
    memories: list[MemoryItem] = []
    for gate_log in gate_logs:
        if gate_log.decision.value not in {"accept", "degrade", "warn"}:
            continue
        memory = await repo.get_memory(gate_log.memory_id)
        if memory is not None:
            memories.append(memory)
    return memories


def _sorted_metrics(metrics: dict[str, float]) -> dict[str, float]:
    return {key: metrics[key] for key in sorted(metrics)}


def _md_text(value: Any) -> str:
    text = html.escape(str(value or ""), quote=False)
    for char in ("\\", "`", "*", "{", "}", "[", "]", "(", ")", "#", "+", "-", "!", "|"):
        text = text.replace(char, f"\\{char}")
    return text.replace("\r", "").replace("\n", "<br>")


def _critical_drift_count(replay: ReplayRetrievalResult | None) -> int:
    if replay is None:
        return 0
    return sum(1 for diff in replay.diffs if diff.severity == "critical")


def _context_block_count(replay: ReplayRetrievalResult | None, access: MemoryAccessLog) -> int:
    if replay is not None:
        return len(replay.replayed_context_blocks)
    return int(access.accepted_count)


def _compaction_rows(access: MemoryAccessLog, logs: list[ContextCompactionLog]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for log in sorted(logs, key=lambda item: (item.created_at, item.compaction_id)):
        rows.append(
            {
                "compaction_id": log.compaction_id,
                "access_id": access.access_id,
                "run_id": log.run_id,
                "kind": log.kind.value,
                "provider": log.provider.value,
                "pre_tokens": log.pre_tokens,
                "post_tokens": log.post_tokens,
                "dropped_block_count": log.dropped_block_count,
                "compression_ratio": log.compression_ratio,
                "summary_text": log.summary_text,
                "retained_facts": [fact.model_dump(mode="json") for fact in log.retained_facts],
                "source_memory_ids": list(log.source_memory_ids),
                "warnings": list(log.warnings),
            }
        )
    return rows


def _render_markdown(
    payload: dict[str, Any],
    summary: ObservabilitySummary,
    replays: list[ReplayRetrievalResult],
) -> str:
    lines = [
        "# MemTrace Observability Report",
        "",
        "## Summary",
        "",
        f"- Workspace: `{summary.workspace_id or 'all'}`",
        f"- Run: `{summary.run_id or 'all'}`",
        f"- Accesses: {summary.access_count}",
        f"- Candidates / Accepted / Rejected: {summary.candidate_count} / {summary.accepted_count} / {summary.rejected_count}",
        f"- Avg latency ms: {summary.avg_latency_ms}",
        f"- Avg actual tokens: {summary.avg_actual_tokens}",
        "",
        "## Strategy Breakdown",
        "",
        "| Strategy | Accesses | Avg Candidates | Avg Accepted | Avg Rejected | Risk Block Rate | Workspace Leakage Rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy, values in summary.by_strategy.items():
        lines.append(
            "| "
            + " | ".join(
                [
                    strategy,
                    str(values.get("access_count", 0)),
                    str(values.get("avg_candidate_count", 0.0)),
                    str(values.get("avg_accepted_count", 0.0)),
                    str(values.get("avg_rejected_count", 0.0)),
                    str(values.get("risk_block_rate", 0.0)),
                    str(values.get("workspace_leakage_rate", 0.0)),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Compaction",
            "",
            f"- Trigger rate: {summary.compaction_trigger_rate}",
            f"- Avg compression ratio: {summary.avg_compression_ratio}",
            f"- Total dropped blocks: {summary.total_dropped_blocks}",
            f"- History summaries: {summary.history_summary_count}",
            "",
            "| Access | Kind | Provider | Pre/Post Tokens | Dropped | Retained Facts |",
            "|---|---|---|---:|---:|---|",
        ]
    )
    for row in payload.get("compactions", []):
        facts = "; ".join(_md_text(f"{fact['key']}={fact['value']}") for fact in row.get("retained_facts", []))
        lines.append(
            f"| `{_md_text(row['access_id'])}` | {_md_text(row['kind'])} | {_md_text(row['provider'])} | "
            f"{row['pre_tokens']}/{row['post_tokens']} | {row['dropped_block_count']} | {facts} |"
        )
    if not payload.get("compactions"):
        lines.append("| none | - | - | 0/0 | 0 |  |")

    lines.extend(
        [
            "",
            "## Quality Signals",
            "",
            f"- Failed branch rejected: {summary.failed_branch_rejected}",
            f"- Failed branch injected: {summary.failed_branch_injected}",
            f"- Stale rejected: {summary.stale_rejected}",
            f"- Stale injected: {summary.stale_injected}",
            f"- Superseded injected: {summary.superseded_injected}",
            "",
            "## Safety Signals",
            "",
            f"- Tool-sensitive blocked: {summary.tool_sensitive_blocked}",
            f"- Destructive command blocked: {summary.destructive_command_blocked}",
            f"- Risk blocked: {summary.risk_blocked}",
            f"- Workspace mismatch rejected: {summary.workspace_mismatch_rejected}",
            f"- Workspace leakage: {summary.workspace_leakage}",
            "",
            "## Slowest Accesses",
            "",
            "| Access | Strategy | Latency ms | Tokens | Query |",
            "|---|---|---:|---:|---|",
        ]
    )
    slowest = sorted(
        payload["accesses"],
        key=lambda row: (row["metrics"].get("latency_ms", 0.0), row["access_id"]),
        reverse=True,
    )[:5]
    for row in slowest:
        lines.append(
            f"| `{_md_text(row['access_id'])}` | {_md_text(row['strategy'])} | {row['metrics'].get('latency_ms', 0.0)} | "
            f"{row['metrics'].get('actual_tokens', 0.0)} | {_md_text(row.get('query') or '')} |"
        )

    lines.extend(
        [
            "",
            "## Replay Drift",
            "",
            "| Access | Diff Count | Critical | Replay API |",
            "|---|---:|---:|---|",
        ]
    )
    replay_by_access = {replay.access_id: replay for replay in replays}
    for row in payload["accesses"]:
        replay = replay_by_access.get(row["access_id"])
        diff_count = len(replay.diffs) if replay else 0
        critical = _critical_drift_count(replay)
        lines.append(
            f"| `{_md_text(row['access_id'])}` | {diff_count} | {critical} | "
            f"`curl http://localhost:8000/v1/replay/access/{_md_text(row['access_id'])}` |"
        )

    lines.extend(["", "## Access Details", ""])
    for row in payload["accesses"]:
        lines.extend(
            [
                f"### `{_md_text(row['access_id'])}`",
                "",
                f"- Run: `{_md_text(row.get('run_id') or 'none')}`",
                f"- Strategy: `{_md_text(row['strategy'])}`",
                f"- Query: {_md_text(row.get('query') or '')}",
                f"- Context blocks: {row['context_block_count']}",
                f"- Replay: `curl http://localhost:8000/v1/replay/access/{_md_text(row['access_id'])}`",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def _render_html(
    payload: dict[str, Any],
    summary: ObservabilitySummary,
    replays: list[ReplayRetrievalResult],
) -> str:
    replay_by_access = {replay.access_id: replay for replay in replays}
    style = """
body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:32px;color:#1f2937;background:#f9fafb}
h1,h2{color:#111827}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.card{background:white;border:1px solid #e5e7eb;border-radius:10px;padding:14px}.value{font-size:24px;font-weight:700}table{border-collapse:collapse;width:100%;background:white;margin:12px 0 24px}th,td{border:1px solid #e5e7eb;padding:8px;text-align:left}th{background:#f3f4f6}code{background:#eef2ff;padding:2px 4px;border-radius:4px}details{background:white;border:1px solid #e5e7eb;border-radius:8px;margin:10px 0;padding:10px}.muted{color:#6b7280}
""".strip()
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>MemTrace Observability Report</title>",
        f"<style>{style}</style>",
        "</head>",
        "<body>",
        "<h1>MemTrace Observability Report</h1>",
        '<p class="muted">Static report generated from persisted retrieval observability logs.</p>',
        "<h2>Summary</h2>",
        '<div class="cards">',
    ]
    for label, value in [
        ("Workspace", summary.workspace_id or "all"),
        ("Run", summary.run_id or "all"),
        ("Accesses", summary.access_count),
        ("Candidates", summary.candidate_count),
        ("Accepted", summary.accepted_count),
        ("Rejected", summary.rejected_count),
    ]:
        parts.append(f'<div class="card"><div>{html.escape(str(label))}</div><div class="value">{html.escape(str(value))}</div></div>')
    parts.extend(['</div>', '<h2>Strategy Breakdown</h2>', '<table><tr><th>Strategy</th><th>Accesses</th><th>Avg Candidates</th><th>Risk Block Rate</th><th>Workspace Leakage Rate</th></tr>'])
    for strategy, values in summary.by_strategy.items():
        parts.append(
            "<tr>"
            f"<td>{html.escape(strategy)}</td>"
            f"<td>{values.get('access_count', 0)}</td>"
            f"<td>{values.get('avg_candidate_count', 0.0)}</td>"
            f"<td>{values.get('risk_block_rate', 0.0)}</td>"
            f"<td>{values.get('workspace_leakage_rate', 0.0)}</td>"
            "</tr>"
        )
    parts.extend(
        [
            "</table>",
            "<h2>Compaction</h2>",
            "<table><tr><th>Access</th><th>Kind</th><th>Provider</th><th>Pre/Post Tokens</th><th>Dropped</th><th>Retained Facts</th></tr>",
        ]
    )
    compactions = payload.get("compactions", [])
    if compactions:
        for row in compactions:
            facts = "; ".join(f"{fact['key']}={fact['value']}" for fact in row.get("retained_facts", []))
            parts.append(
                "<tr>"
                f"<td><code>{html.escape(row['access_id'])}</code></td>"
                f"<td>{html.escape(row['kind'])}</td>"
                f"<td>{html.escape(row['provider'])}</td>"
                f"<td>{row['pre_tokens']}/{row['post_tokens']}</td>"
                f"<td>{row['dropped_block_count']}</td>"
                f"<td>{html.escape(facts)}</td>"
                "</tr>"
            )
    else:
        parts.append("<tr><td>none</td><td>-</td><td>-</td><td>0/0</td><td>0</td><td></td></tr>")
    parts.extend(
        [
            "</table>",
            "<h2>Quality &amp; Safety</h2>",
            "<table><tr><th>Signal</th><th>Value</th></tr>",
        ]
    )
    for label, value in [
        ("failed_branch_rejected", summary.failed_branch_rejected),
        ("failed_branch_injected", summary.failed_branch_injected),
        ("stale_rejected", summary.stale_rejected),
        ("stale_injected", summary.stale_injected),
        ("tool_sensitive_blocked", summary.tool_sensitive_blocked),
        ("destructive_command_blocked", summary.destructive_command_blocked),
        ("risk_blocked", summary.risk_blocked),
        ("workspace_mismatch_rejected", summary.workspace_mismatch_rejected),
        ("workspace_leakage", summary.workspace_leakage),
        ("superseded_injected", summary.superseded_injected),
    ]:
        parts.append(f"<tr><td>{html.escape(label)}</td><td>{value}</td></tr>")
    parts.extend(["</table>", "<h2>Replay Drift</h2>", "<table><tr><th>Access</th><th>Diff Count</th><th>Critical</th><th>Replay API</th></tr>"])
    for row in payload["accesses"]:
        replay = replay_by_access.get(row["access_id"])
        replay_path = f"/v1/replay/access/{row['access_id']}"
        parts.append(
            "<tr>"
            f"<td><code>{html.escape(row['access_id'])}</code></td>"
            f"<td>{len(replay.diffs) if replay else 0}</td>"
            f"<td>{_critical_drift_count(replay)}</td>"
            f"<td><code>{html.escape(replay_path)}</code></td>"
            "</tr>"
        )
    parts.extend(["</table>", "<h2>Access Details</h2>"])
    for row in payload["accesses"]:
        replay_path = f"/v1/replay/access/{row['access_id']}"
        parts.extend(
            [
                "<details>",
                f"<summary><code>{html.escape(row['access_id'])}</code> — {html.escape(row['strategy'])}</summary>",
                f"<p><strong>Run:</strong> <code>{html.escape(str(row.get('run_id') or 'none'))}</code></p>",
                f"<p><strong>Query:</strong> {html.escape(str(row.get('query') or ''))}</p>",
                f"<p><strong>Context blocks:</strong> {row['context_block_count']}</p>",
                f"<p><strong>Replay API:</strong> <code>{html.escape(replay_path)}</code></p>",
                "</details>",
            ]
        )
    parts.extend(["</body>", "</html>"])
    return "\n".join(parts) + "\n"


def _relative_posix(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate a MemTrace observability report.")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--workspace-id", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--no-replay", action="store_true", help="Skip replay payloads in the generated JSON report.")
    args = parser.parse_args(argv)
    from app.retrieval.controller import RetrievalController
    from app.runtime.repository import InMemoryRepository

    repo = InMemoryRepository()
    retrieval = RetrievalController(repo)
    result = asyncio.run(
        write_observability_report(
            repo,
            retrieval,
            ObservabilityReportRequest(
                workspace_id=args.workspace_id,
                run_id=args.run_id,
                output_dir=args.output_dir,
                include_replay=not args.no_replay,
            ),
        )
    )
    print(result.model_dump_json())


if __name__ == "__main__":
    main()


__all__ = ["write_observability_report"]
