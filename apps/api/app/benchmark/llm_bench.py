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
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import get_settings
from app.memory.llm_extractor import LLMExtractionProvider
from app.memory.writer import write_from_user_message
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    AgentEvent,
    BranchStatus,
    EventRole,
    EventType,
    FinishStepRequest,
    MemoryItem,
    MemoryStatus,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    RiskFlags,
    RollbackRequest,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
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
# Scenario 5: failed-branch isolation (memory written via real LLM extraction)
# --------------------------------------------------------------------------- #
async def scenario_failed_branch(provider: LLMExtractionProvider) -> ScenarioResult:
    ws = "bench_failbranch"
    rt = _runtime(provider, ws)
    run = await rt.start_run(StartRunRequest(session_id="s_fb", task="run tests", workspace_id=ws))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    # Project constraint extracted by the real LLM.
    await _say(rt, run.run_id, s1.step_id, "这个项目使用 Bun，不用 Node.js")
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                           status=StepStatus.completed, summary="confirmed Bun"))
    # Plan A: npm fails -> tool evidence memory on a branch that gets rolled back.
    sf = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging"))
    await rt.write_event(WriteEventRequest(run_id=run.run_id, step_id=sf.step_id, role=EventRole.tool,
                                           event_type=EventType.tool_call, tool_name="bash", content="npm test"))
    await rt.write_event(WriteEventRequest(run_id=run.run_id, step_id=sf.step_id, role=EventRole.tool,
                                           event_type=EventType.tool_result, status="failed",
                                           content="Tried npm test but it failed because npm was unavailable."))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=sf.step_id,
                                           status=StepStatus.failed, error_message="npm unavailable"))
    await rt.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=sf.step_id, reason="npm unavailable"))
    # Plan B: recovery (bun).
    s3 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging",
                                              recovery_from_step_id=sf.step_id, goal="run tests with bun"))
    ctx = await rt.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s3.step_id,
                         query="How do I run the test suite? I tried npm test.",
                         strategy=RetrievalStrategy.variant_2)
    )
    text = _ctx_text(ctx)
    # The failed npm branch evidence must NOT be recalled; Bun constraint should be.
    contaminated = "npm" in text and "fail" in text
    keeps_bun = "bun" in text
    passed = not contaminated and keeps_bun
    return ScenarioResult(
        name="failed_branch_isolation",
        passed=passed,
        summary=f"failed npm branch contaminated context={contaminated}; bun kept={keeps_bun}",
        details={"context_blocks": [b.content for b in ctx.context_blocks]},
    )


# --------------------------------------------------------------------------- #
# Scenario 6: cross-workspace isolation
# --------------------------------------------------------------------------- #
async def scenario_workspace_isolation(provider: LLMExtractionProvider) -> ScenarioResult:
    ws = "bench_ws_main"
    other_ws = "bench_ws_other"
    # Shared repo so both workspaces live in one store; retrieval must still isolate.
    repo = InMemoryRepository()
    rt = MemoryRuntime(repo, default_workspace_id=ws, extraction_provider=provider)

    # Competing constraint seeded in a DIFFERENT workspace via real LLM extraction.
    orun = await rt.start_run(StartRunRequest(session_id="s_other", task="other", workspace_id=other_ws))
    os1 = await rt.start_step(StartStepRequest(run_id=orun.run_id, intent="planning"))
    await _say(rt, orun.run_id, os1.step_id, "这个项目使用 Deno")
    await rt.finish_step(FinishStepRequest(run_id=orun.run_id, step_id=os1.step_id, status=StepStatus.completed))

    run = await rt.start_run(StartRunRequest(session_id="s_main", task="run tests", workspace_id=ws))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await _say(rt, run.run_id, s1.step_id, "这个项目使用 Bun，不用 Node.js")
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                           status=StepStatus.completed, summary="confirmed Bun"))
    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging", goal="choose runtime"))
    ctx = await rt.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s2.step_id,
                         query="Which runtime should I use, deno or bun?",
                         strategy=RetrievalStrategy.variant_2)
    )
    text = _ctx_text(ctx)
    leaks_deno = "deno" in text
    keeps_bun = "bun" in text
    passed = not leaks_deno and keeps_bun
    return ScenarioResult(
        name="workspace_isolation",
        passed=passed,
        summary=f"other-workspace deno leaked={leaks_deno}; own bun kept={keeps_bun}",
        details={"context_blocks": [b.content for b in ctx.context_blocks]},
    )


# --------------------------------------------------------------------------- #
# Scenario 7: stale memory rejection
# --------------------------------------------------------------------------- #
async def scenario_stale_rejection(provider: LLMExtractionProvider) -> ScenarioResult:
    ws = "bench_stale"
    rt = _runtime(provider, ws)
    run = await rt.start_run(StartRunRequest(session_id="s_stale", task="call users API", workspace_id=ws))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await _say(rt, run.run_id, s1.step_id, "这个项目使用 Bun")
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                           status=StepStatus.completed, summary="confirmed Bun"))
    # Inject an expired, highly-relevant episodic memory (gate must drop as stale).
    await rt._repo.add_memory(  # noqa: SLF001 - bench seeding harness
        MemoryItem(
            workspace_id=ws, run_id=run.run_id, memory_type=MemoryType.episodic,
            content="Use the legacy API endpoint /v1/old-users to fetch the users list.",
            summary="legacy API endpoint /v1/old-users",
            branch_status=BranchStatus.completed,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging", goal="call users API"))
    ctx = await rt.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s2.step_id,
                         query="Which API endpoint should I call to fetch the users list?",
                         strategy=RetrievalStrategy.variant_2)
    )
    text = _ctx_text(ctx)
    stale_leaked = "old-users" in text
    passed = not stale_leaked
    return ScenarioResult(
        name="stale_rejection",
        passed=passed,
        summary=f"stale /v1/old-users leaked into context={stale_leaked} (expect False)",
        details={"context_blocks": [b.content for b in ctx.context_blocks]},
    )


# --------------------------------------------------------------------------- #
# Scenario 8: tool-call safety (destructive command memory must be gated)
# --------------------------------------------------------------------------- #
async def scenario_tool_safety(provider: LLMExtractionProvider) -> ScenarioResult:
    ws = "bench_toolsafe"
    rt = _runtime(provider, ws)
    run = await rt.start_run(StartRunRequest(session_id="s_tool", task="deploy", workspace_id=ws))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await _say(rt, run.run_id, s1.step_id, "这个项目使用 Bun")
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                           status=StepStatus.completed, summary="confirmed Bun"))
    # Inject a dangerous tool-evidence memory (risk flags set); gate must block it.
    await rt._repo.add_memory(  # noqa: SLF001 - bench seeding harness
        MemoryItem(
            workspace_id=ws, run_id=run.run_id, memory_type=MemoryType.tool_evidence,
            content="Previously deployed with: git push --force to production",
            summary="git push --force to production",
            branch_status=BranchStatus.completed,
            risk_flags=RiskFlags(tool_sensitive=True, destructive_command=True, production_env=True),
        )
    )
    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging", goal="deploy"))
    ctx = await rt.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s2.step_id,
                         query="How did we deploy and push to production with force last time?",
                         strategy=RetrievalStrategy.variant_2)
    )
    text = _ctx_text(ctx)
    leaked = "--force" in text or "push --force" in text
    passed = not leaked
    return ScenarioResult(
        name="tool_safety",
        passed=passed,
        summary=f"destructive 'git push --force' leaked into context={leaked} (expect False)",
        details={"context_blocks": [b.content for b in ctx.context_blocks]},
    )


# --------------------------------------------------------------------------- #
# Runner / reporting
# --------------------------------------------------------------------------- #
_SCENARIOS = [
    scenario_memory_override,
    scenario_scale_retrieval,
    scenario_llm_vs_rule,
    scenario_nl_extraction,
    scenario_failed_branch,
    scenario_workspace_isolation,
    scenario_stale_rejection,
    scenario_tool_safety,
]


async def _run_one_endpoint(provider: LLMExtractionProvider) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for fn in _SCENARIOS:
        try:
            results.append(await fn(provider))
        except Exception as exc:  # surface, don't hide
            results.append(ScenarioResult(
                name=fn.__name__.replace("scenario_", ""),
                passed=False,
                summary=f"ERROR: {type(exc).__name__}: {exc}",
            ))
    return results


async def run_bench(output_dir: str = "reports") -> dict[str, Any]:
    endpoints = _resolve_endpoints()
    if not endpoints:
        raise SystemExit(
            "No LLM endpoint configured. Either set MEMTRACE_LLM_API_KEY (single "
            "endpoint, optionally with MEMTRACE_LLM_BASE_URL / MEMTRACE_LLM_MODEL), "
            "or set MEMTRACE_LLM_BENCH_ENDPOINTS to a JSON list of "
            '{"name","api_key","base_url","model"} objects for a multi-endpoint '
            "portability comparison."
        )

    endpoint_payloads: list[dict[str, Any]] = []
    for ep in endpoints:
        provider = LLMExtractionProvider(
            api_key=ep["api_key"],
            base_url=ep.get("base_url", "https://api.openai.com/v1"),
            model=ep.get("model", "gpt-4o-mini"),
            timeout_s=ep.get("timeout_ms", 60000) / 1000,
            max_tokens=ep.get("max_tokens", 512),
            use_json_response_format=ep.get("use_json_response_format", False),
        )
        results = await _run_one_endpoint(provider)
        endpoint_payloads.append({
            "name": ep.get("name") or ep.get("model"),
            "base_url": ep.get("base_url", "https://api.openai.com/v1"),
            "model": ep.get("model", "gpt-4o-mini"),
            "passed": all(r.passed for r in results),
            "results": [r.as_dict() for r in results],
        })

    payload = {
        "multi_endpoint": len(endpoint_payloads) > 1,
        "passed": all(e["passed"] for e in endpoint_payloads),
        "endpoints": endpoint_payloads,
    }

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "llm_bench_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "llm_bench_report.md").write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def _resolve_endpoints() -> list[dict[str, Any]]:
    """Resolve one or more endpoints to bench.

    Priority: MEMTRACE_LLM_BENCH_ENDPOINTS (JSON list of
    {name, api_key, base_url, model, ...}) for a portability comparison; else a
    single endpoint from the standard MEMTRACE_LLM_* settings.
    """
    raw = os.environ.get("MEMTRACE_LLM_BENCH_ENDPOINTS")
    if raw:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [e for e in parsed if isinstance(e, dict) and e.get("api_key")]
    settings = get_settings()
    if settings.llm_api_key:
        return [{
            "name": settings.llm_model,
            "api_key": settings.llm_api_key,
            "base_url": settings.llm_base_url,
            "model": settings.llm_model,
            "timeout_ms": settings.llm_timeout_ms,
            "max_tokens": settings.llm_max_tokens,
            "use_json_response_format": settings.llm_use_json_response_format,
        }]
    return []


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Real-LLM Extraction Bench", ""]
    overall = "PASS ✅" if payload["passed"] else "FAIL ❌"
    scope = "multi-endpoint" if payload.get("multi_endpoint") else "single endpoint"
    lines.append(f"- Scope: {scope} ({len(payload['endpoints'])} endpoint(s))")
    lines.append(f"- Overall: {overall}")
    lines.append("")
    for ep in payload["endpoints"]:
        ep_mark = "PASS ✅" if ep["passed"] else "FAIL ❌"
        lines.append(f"## {ep['name']} — {ep_mark}")
        lines.append(f"- Endpoint: `{ep['base_url']}` model `{ep['model']}`")
        lines.append("")
        lines.append("| Scenario | Result | Summary |")
        lines.append("|---|---|---|")
        for r in ep["results"]:
            mark = "PASS" if r["passed"] else "FAIL"
            lines.append(f"| {r['name']} | {mark} | {r['summary']} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Real-LLM extraction validation bench")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    payload = asyncio.run(run_bench(args.output_dir))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
