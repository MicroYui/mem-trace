"""Real-LLM extraction validation bench (manual / opt-in, NOT part of CI).

Unlike ``app/benchmark/runner.py`` (deterministic, rule-based, used for MVP
acceptance), this bench drives the *real* ``LLMExtractionProvider`` against a
configured OpenAI-compatible endpoint to validate extraction quality and the
memory lifecycle end to end. It requires a live API key and network access.

Run::

    MEMTRACE_LLM_API_KEY=... \
    MEMTRACE_LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3 \
    MEMTRACE_LLM_MODEL=deepseek-v4-pro-260425 \
    uv run python -m app.benchmark.llm_bench --output-dir reports

Scenarios:
1. memory_override   — repeated conflicting preferences must supersede so only
   the latest single-valued value survives + is recalled.
2. scale_retrieval   — many distinct preferences across turns; a targeted query
   must surface the relevant memory within the token budget (top-k ranking).
3. llm_vs_rule       — same inputs through the real LLM vs the rule writer;
   compare normalized extracted (key,value) sets.
4. nl_extraction     — colloquial / indirect / multilingual phrasings the rule
   writer cannot parse; check the LLM still extracts a usable memory.

Each scenario emits a structured pass/fail with details; the bench writes
``reports/llm_bench_report.{json,md}`` and prints a summary. Network/LLM errors
are surfaced (this bench intentionally does NOT silently fall back, so a
degraded run is visible rather than mistaken for success).
"""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.config import get_settings
from app.memory.llm_extractor import LLMExtractionProvider
from app.memory.writer import write_from_user_message
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    AgentEvent,
    EventRole,
    EventType,
    MemoryStatus,
    RetrievalRequest,
    RetrievalStrategy,
    StartRunRequest,
    StartStepRequest,
    WriteEventRequest,
)
from app.runtime.repository import InMemoryRepository


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
@dataclass
class ScenarioResult:
    name: str
    passed: bool
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "summary": self.summary,
            "details": self.details,
        }


def _make_provider(settings) -> LLMExtractionProvider:
    return LLMExtractionProvider(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_s=settings.llm_timeout_ms / 1000,
        max_tokens=settings.llm_max_tokens,
        use_json_response_format=settings.llm_use_json_response_format,
    )


def _runtime(provider: LLMExtractionProvider, workspace_id: str) -> MemoryRuntime:
    return MemoryRuntime(
        InMemoryRepository(),
        default_workspace_id=workspace_id,
        extraction_provider=provider,
    )


async def _new_run_step(rt: MemoryRuntime, session_id: str) -> tuple[str, str]:
    run = await rt.start_run(StartRunRequest(session_id=session_id, task="bench"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    return run.run_id, step.step_id


async def _say(rt: MemoryRuntime, run_id: str, step_id: str, text: str) -> list[str]:
    res = await rt.write_event(
        WriteEventRequest(
            run_id=run_id, step_id=step_id, role=EventRole.user,
            event_type=EventType.message, content=text,
        )
    )
    return res.created_memory_ids


async def _active_values(rt: MemoryRuntime, workspace_id: str, key: str) -> list[str]:
    mems = await rt.list_memories(workspace_id=workspace_id)
    return [
        m.value
        for m in mems
        if m.key == key and m.status in (MemoryStatus.active, MemoryStatus.pinned) and m.value
    ]


def _ctx_text(ctx) -> str:
    return "\n".join(b.content for b in ctx.context_blocks).lower()


# --------------------------------------------------------------------------- #
# Scenario 1: memory override / conflict resolution
# --------------------------------------------------------------------------- #
async def scenario_memory_override(provider: LLMExtractionProvider) -> ScenarioResult:
    ws = "bench_override"
    rt = _runtime(provider, ws)
    run_id, step_id = await _new_run_step(rt, "s_override")

    # Three conflicting single-valued runtime preferences across turns.
    turns = [
        "这个项目用 npm 作为包管理器",
        "改主意了，不要用 npm，换成 pnpm",
        "最终决定：统一用 bun，别用 pnpm 了",
    ]
    for t in turns:
        await _say(rt, run_id, step_id, t)

    actives = await _active_values(rt, ws, "project.runtime")
    # Also check what a query recalls.
    ctx = await rt.retrieve_context(
        RetrievalRequest(run_id=run_id, step_id=step_id,
                         query="这个项目该用哪个包管理器跑测试？",
                         strategy=RetrievalStrategy.variant_2)
    )
    ctx_text = _ctx_text(ctx)
    recalls_bun = "bun" in ctx_text
    # "npm" was fully retired (never the final choice and not an explicit
    # exclusion), so it must not appear at all. "pnpm" may legitimately appear
    # inside a "should not use ..." exclusion clause, so we only flag it if it
    # leaks WITHOUT a negation context. Tokenize so "pnpm" doesn't match "npm".
    tokens = ctx_text.replace(",", " ").replace(".", " ").split()
    leaks_npm = any(tok == "npm" for tok in tokens)
    excluded_clause = "should not use" in ctx_text or "exclude" in ctx_text

    # Pass: exactly one active runtime value (bun); recall surfaces bun; the fully
    # retired "npm" never leaks; if "pnpm" appears it is only as an exclusion.
    passed = (
        len(actives) == 1
        and actives[0].lower() == "bun"
        and recalls_bun
        and not leaks_npm
        and ("pnpm" not in ctx_text or excluded_clause)
    )
    return ScenarioResult(
        name="memory_override",
        passed=passed,
        summary=(
            f"active project.runtime={actives} (expect ['bun']); "
            f"recall bun={recalls_bun}, npm_leaked={leaks_npm}, "
            f"pnpm_only_as_exclusion={('pnpm' not in ctx_text or excluded_clause)}"
        ),
        details={"turns": turns, "active_values": actives,
                 "context_blocks": [b.content for b in ctx.context_blocks]},
    )


# --------------------------------------------------------------------------- #
# Scenario 2: many memories + retrieval accuracy
# --------------------------------------------------------------------------- #
async def scenario_scale_retrieval(provider: LLMExtractionProvider) -> ScenarioResult:
    ws = "bench_scale"
    rt = _runtime(provider, ws)
    run_id, step_id = await _new_run_step(rt, "s_scale")

    # Many distinct preferences/constraints across turns.
    statements = [
        "项目统一用 bun 作为运行时",
        "代码格式化工具用 ruff",
        "数据库选 PostgreSQL，不要用 MySQL",
        "前端框架用 React 18",
        "测试框架用 pytest",
        "部署目标是 Kubernetes",
        "日志格式统一用 JSON",
        "API 风格遵循 RESTful",
        "Python 版本要求 3.12",
        "缓存层用 Redis",
        "消息队列用 Kafka",
        "CI 用 GitHub Actions",
    ]
    for s in statements:
        await _say(rt, run_id, step_id, s)

    total_mem = len(await rt.list_memories(workspace_id=ws))

    # Targeted queries: each should surface the relevant memory near the top.
    probes = [
        ("用哪个数据库？", "postgres"),
        ("代码怎么格式化？", "ruff"),
        ("缓存用什么？", "redis"),
        ("Python 用什么版本？", "3.12"),
    ]
    hits = []
    for query, expected in probes:
        ctx = await rt.retrieve_context(
            RetrievalRequest(run_id=run_id, step_id=step_id, query=query,
                             strategy=RetrievalStrategy.variant_2, token_budget=256)
        )
        text = _ctx_text(ctx)
        hit = expected.lower() in text
        hits.append({"query": query, "expected": expected, "hit": hit,
                     "blocks": len(ctx.context_blocks),
                     "tokens": ctx.profile.get("actual_tokens"),
                     "budget": ctx.profile.get("token_budget")})

    hit_count = sum(1 for h in hits if h["hit"])
    # Pass: stored a healthy number of memories AND most probes hit AND budget respected.
    budget_ok = all((h["tokens"] or 0) <= (h["budget"] or 0) for h in hits)
    passed = total_mem >= 8 and hit_count >= 3 and budget_ok
    return ScenarioResult(
        name="scale_retrieval",
        passed=passed,
        summary=(
            f"stored {total_mem} memories from {len(statements)} turns; "
            f"{hit_count}/{len(probes)} probes hit; budget_respected={budget_ok}"
        ),
        details={"statements": statements, "total_memories": total_mem, "probes": hits},
    )


# --------------------------------------------------------------------------- #
# Scenario 3: LLM vs rule extraction
# --------------------------------------------------------------------------- #
def _event(ws: str, text: str) -> AgentEvent:
    return AgentEvent(
        workspace_id=ws, run_id="r", step_id="s",
        role=EventRole.user, event_type=EventType.message, content=text,
    )


def _norm_pairs(pairs: list[tuple[str, str]]) -> set[tuple[str, str]]:
    return {(k.strip().lower(), v.strip().lower()) for k, v in pairs}


async def scenario_llm_vs_rule(provider: LLMExtractionProvider) -> ScenarioResult:
    ws = "bench_compare"
    inputs = [
        "这个项目使用 Bun，不用 Node.js",
        "改用 pnpm 作为包管理器",
        "代码格式化用 ruff",
    ]
    rows = []
    for text in inputs:
        ev = _event(ws, text)
        llm_cands = await provider.extract(ev)
        llm_pairs = _norm_pairs([(c.key, c.value) for c in llm_cands])
        rule_results = write_from_user_message(ev)
        rule_pairs = _norm_pairs(
            [(r.memory.key, r.memory.value) for r in rule_results
             if r.memory.key and r.memory.value]
        )
        rows.append({
            "input": text,
            "llm": sorted(f"{k}={v}" for k, v in llm_pairs),
            "rule": sorted(f"{k}={v}" for k, v in rule_pairs),
            "llm_nonempty": bool(llm_pairs),
        })

    llm_all_nonempty = all(r["llm_nonempty"] for r in rows)
    # Pass: LLM produced at least one candidate for every input (quality check);
    # we report rule output side by side for inspection rather than requiring equality.
    passed = llm_all_nonempty
    return ScenarioResult(
        name="llm_vs_rule",
        passed=passed,
        summary=f"LLM produced candidates for all {len(rows)} inputs={llm_all_nonempty}",
        details={"comparison": rows},
    )


# --------------------------------------------------------------------------- #
# Scenario 4: natural-language extraction (rule writer can't parse these)
# --------------------------------------------------------------------------- #
async def scenario_nl_extraction(provider: LLMExtractionProvider) -> ScenarioResult:
    ws = "bench_nl"
    # Colloquial / indirect / multilingual phrasings.
    inputs = [
        "别用 yarn 了，太慢，咱们以后都拿 bun 跑",
        "We should standardize on TypeScript for all new services",
        "数据库这块，能不能别再碰 MongoDB 了，老老实实 Postgres",
    ]
    rows = []
    for text in inputs:
        ev = _event(ws, text)
        llm_cands = await provider.extract(ev)
        rule_results = [
            r for r in write_from_user_message(ev)
            if r.memory.key and r.memory.value
        ]
        rows.append({
            "input": text,
            "llm": sorted(f"{c.key}={c.value}" for c in llm_cands),
            "llm_count": len(llm_cands),
            "rule_count": len(rule_results),
        })

    llm_extracted = sum(1 for r in rows if r["llm_count"] > 0)
    # Pass: LLM extracts something from a majority of colloquial inputs.
    passed = llm_extracted >= 2
    return ScenarioResult(
        name="nl_extraction",
        passed=passed,
        summary=f"LLM extracted from {llm_extracted}/{len(rows)} colloquial inputs",
        details={"rows": rows},
    )


# --------------------------------------------------------------------------- #
# Runner / reporting
# --------------------------------------------------------------------------- #
async def run_bench(output_dir: str = "reports") -> dict[str, Any]:
    settings = get_settings()
    if not settings.llm_api_key:
        raise SystemExit(
            "MEMTRACE_LLM_API_KEY is not set. This bench requires a live "
            "OpenAI-compatible endpoint. Set MEMTRACE_LLM_API_KEY (and optionally "
            "MEMTRACE_LLM_BASE_URL / MEMTRACE_LLM_MODEL) and re-run."
        )
    provider = _make_provider(settings)

    scenarios = [
        scenario_memory_override,
        scenario_scale_retrieval,
        scenario_llm_vs_rule,
        scenario_nl_extraction,
    ]
    results: list[ScenarioResult] = []
    for fn in scenarios:
        try:
            results.append(await fn(provider))
        except Exception as exc:  # surface, don't hide
            results.append(ScenarioResult(
                name=fn.__name__.replace("scenario_", ""),
                passed=False,
                summary=f"ERROR: {type(exc).__name__}: {exc}",
            ))

    payload = {
        "endpoint": {"base_url": settings.llm_base_url, "model": settings.llm_model},
        "passed": all(r.passed for r in results),
        "results": [r.as_dict() for r in results],
    }

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "llm_bench_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "llm_bench_report.md").write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Real-LLM Extraction Bench", ""]
    ep = payload["endpoint"]
    lines.append(f"- Endpoint: `{ep['base_url']}` model `{ep['model']}`")
    lines.append(f"- Overall: {'PASS ✅' if payload['passed'] else 'FAIL ❌'}")
    lines.append("")
    lines.append("| Scenario | Result | Summary |")
    lines.append("|---|---|---|")
    for r in payload["results"]:
        mark = "PASS" if r["passed"] else "FAIL"
        lines.append(f"| {r['name']} | {mark} | {r['summary']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Real-LLM extraction validation bench")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    payload = asyncio.run(run_bench(args.output_dir))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
