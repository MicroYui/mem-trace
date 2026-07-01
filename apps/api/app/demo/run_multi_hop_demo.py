"""Deterministic multi-hop iterative retrieval demo (ROADMAP §4, default-off).

The single most legible before/after of MemTrace's optional advanced retrieval:

  - One-shot retrieval finds only what the query literally names.
  - Enabling ONE hop reconstructs a complementary fact linked ONLY through a
    shared entity (``service.gateway``) that the query never mentions — and that
    recovered fact flips the agent's downstream action.

This is the "not just vector RAG" thesis made concrete: the load-bearing fact
(``x-tenant``) is reachable from the query only by following an entity the query
does not contain. Runs the SAME seed twice (hops=0 vs hops=1) over an in-memory
repository; deterministic, lexical-only, no network / LLM / DB.

The feature is default-off and byte-identical at hops=0, so the deterministic
benchmark stays 16/16 and replay snapshots are unchanged. This demo sets the
env var only inside its own process and clears the settings cache on exit.

Usage:
    uv run python -m app.demo.run_multi_hop_demo             # writes reports/multi_hop_demo_report.{md,json}
    uv run python -m app.demo.run_multi_hop_demo --out DIR
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.retrieval.controller import RetrievalController
from app.runtime.models import (
    MemoryItem,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
)
from app.runtime.repository import InMemoryRepository

WORKSPACE = "ws_multi_hop_demo"
RUN_ID = "run_multi_hop_demo"
STEP_ID = "step_multi_hop_demo"
# The query names auth-flow routing but NOT the gateway/tenant entities.
QUERY = "Where is request routing configured?"
TOKEN_BUDGET = 512
# The load-bearing fact only reachable by following the shared entity cue.
LOAD_BEARING_MARKER = "x-tenant"
DISTRACTOR_MARKER = "dark color theme"


def _mem(memory_id: str, content: str) -> MemoryItem:
    # episodic (NOT project): project memories are force-included as always
    # relevant, so a project m_b would leak into the single-pass base and the
    # before/after would collapse. Episodic memories only surface on real signal.
    return MemoryItem(
        memory_id=memory_id,
        workspace_id=WORKSPACE,
        memory_type=MemoryType.episodic,
        content=content,
        summary=content[:60],
    )


async def _seed(repo: InMemoryRepository) -> None:
    # m_a answers the query AND references service.gateway (the hop cue).
    await repo.add_memory(
        _mem("m_gateway", "Request routing is handled by the service.gateway component.")
    )
    # m_b shares NO token with the query except via service.gateway; it carries
    # the load-bearing x-tenant fact and is reachable ONLY through the hop.
    await repo.add_memory(
        _mem("m_tenant", "service.gateway must attach the x-tenant header before forwarding upstream.")
    )
    # m_c is a distractor: no shared token, no shared entity — must never surface.
    await repo.add_memory(
        _mem("m_theme", "The dashboard sidebar renders a dark color theme.")
    )


def _decide_route_action(context_text: str) -> str:
    """Deterministic downstream action over the packed context (no LLM)."""
    if LOAD_BEARING_MARKER in context_text:
        return "route with x-tenant header"
    return "route without x-tenant header"


async def _run_config(*, hops: int, token_budget: int = TOKEN_BUDGET) -> dict:
    """Seed the same memories and retrieve once with the given hop count."""
    os.environ["MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS"] = str(hops)
    # Lexical-only keeps the demo fully deterministic and self-explaining.
    os.environ["MEMTRACE_RETRIEVAL_USE_VECTOR"] = "false"
    get_settings.cache_clear()

    repo = InMemoryRepository()
    await _seed(repo)
    controller = RetrievalController(repo)
    request = RetrievalRequest(
        run_id=RUN_ID,
        step_id=STEP_ID,
        query=QUERY,
        strategy=RetrievalStrategy.variant_2,
        token_budget=token_budget,
        top_k=10,
    )
    trace = await controller.trace(request, workspace_id=WORKSPACE)

    candidates = [
        {
            "memory_id": c.memory.memory_id,
            "hop": c.hop,
            "relevance": round(c.relevance_score, 4),
            "content": c.memory.content,
        }
        for c in trace.candidates
    ]
    accepted_ids = [m.memory_id for m in trace.accepted_memories]
    context_blocks = [
        {"type": b.type, "tokens": b.tokens, "content": b.content}
        for b in trace.context_blocks
    ]
    context_text = " ".join(b["content"] or "" for b in context_blocks)
    retrieval_phase = trace.phase_profile.get("retrieval", {})
    snapshot = trace.access_record.policy_snapshot or {}
    retrieval_policy = snapshot.get("retrieval", {}) if isinstance(snapshot, dict) else {}

    return {
        "hops": hops,
        "token_budget": token_budget,
        "candidates": candidates,
        "accepted_memory_ids": accepted_ids,
        "context_blocks": context_blocks,
        "final_action": _decide_route_action(context_text),
        "load_bearing_fact_present": LOAD_BEARING_MARKER in context_text,
        "distractor_leaked": DISTRACTOR_MARKER in context_text,
        "hop_surfaced_memory_ids": [c["memory_id"] for c in candidates if c["hop"] > 0],
        # Public proof markers surfaced through the normal pipeline:
        "profile_multi_hop_candidate_count": retrieval_phase.get("metadata", {}).get(
            "multi_hop_candidate_count"
        ),
        # policy snapshot omits the key entirely when the feature is off (byte-stability).
        "policy_multi_hop_hops": retrieval_policy.get("multi_hop_hops"),
    }


async def run_multi_hop_demo() -> dict:
    saved = {
        k: os.environ.get(k)
        for k in ("MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS", "MEMTRACE_RETRIEVAL_USE_VECTOR")
    }
    try:
        single_pass = await _run_config(hops=0)
        multi_hop = await _run_config(hops=1)
        # Belt-and-suspenders proof that the hop respects the token budget.
        budget_bounded = await _run_config(hops=1, token_budget=1)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

    summary = {
        "single_pass_action": single_pass["final_action"],
        "multi_hop_action": multi_hop["final_action"],
        # The core payoff: the linked fact is recovered only when hops are on.
        "linked_fact_recovered": (
            not single_pass["load_bearing_fact_present"]
            and multi_hop["load_bearing_fact_present"]
        ),
        "hop_surfaced_memory_ids": multi_hop["hop_surfaced_memory_ids"],
        "distractor_leaked": multi_hop["distractor_leaked"],
        # Enabling the hop budget-bounds cleanly: hop skipped under a tiny budget.
        "budget_bounded": budget_bounded["hop_surfaced_memory_ids"] == [],
        # Default-off byte-stability: multi_hop_hops absent OFF, present ON.
        "policy_multi_hop_hops_off": single_pass["policy_multi_hop_hops"],
        "policy_multi_hop_hops_on": multi_hop["policy_multi_hop_hops"],
        "action_changed": single_pass["final_action"] != multi_hop["final_action"],
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query": QUERY,
        "workspace_id": WORKSPACE,
        "configs": {
            "single_pass": single_pass,
            "multi_hop": multi_hop,
            "multi_hop_tiny_budget": budget_bounded,
        },
        "summary": summary,
    }


def _render_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# MemTrace Multi-Hop Retrieval Demo",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Workspace: `{report['workspace_id']}`",
        f"- Query: `{report['query']}`  *(names routing, NOT the gateway/tenant entities)*",
        "",
        "The query never mentions `service.gateway` or `x-tenant`. A single pass",
        "finds only the memory that literally answers the query; enabling one hop",
        "follows the shared `service.gateway` entity to reconstruct the linked",
        "`x-tenant` fact — which flips the agent's action.",
        "",
    ]
    for key, title in (("single_pass", "Single pass — MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS=0"),
                       ("multi_hop", "One hop — MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS=1")):
        c = report["configs"][key]
        lines += [
            f"## {title}",
            "",
            f"- Final action: **{c['final_action']}**",
            f"- Load-bearing `x-tenant` fact present: **{c['load_bearing_fact_present']}**",
            f"- Distractor leaked: {c['distractor_leaked']}",
            f"- policy_snapshot.retrieval.multi_hop_hops: `{c['policy_multi_hop_hops']}`",
            f"- profile hop-surfaced candidate count: `{c['profile_multi_hop_candidate_count']}`",
            "",
            "| memory_id | hop | relevance | content |",
            "|---|---|---|---|",
        ]
        for cand in c["candidates"]:
            content = (cand["content"] or "").replace("|", "\\|")[:64]
            lines.append(
                f"| `{cand['memory_id']}` | {cand['hop']} | {cand['relevance']:.4f} | {content} |"
            )
        lines += ["", "Packed context blocks:", ""]
        for b in c["context_blocks"]:
            content = (b["content"] or "")[:90]
            lines.append(f"- `{b['type']}` ({b['tokens']} tok): {content}")
        lines.append("")

    lines += [
        "## Summary",
        "",
        f"- single-pass action: `{s['single_pass_action']}`",
        f"- multi-hop action:  `{s['multi_hop_action']}`",
        f"- **linked fact recovered by the hop: {s['linked_fact_recovered']}**",
        f"- hop-surfaced memories: {s['hop_surfaced_memory_ids']}",
        f"- distractor leaked: {s['distractor_leaked']}",
        f"- budget-bounded (hop skipped under a 1-token budget): {s['budget_bounded']}",
        f"- multi_hop_hops in policy snapshot: off=`{s['policy_multi_hop_hops_off']}` on=`{s['policy_multi_hop_hops_on']}`",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="MemTrace multi-hop retrieval demo")
    parser.add_argument("--out", default="reports", help="output directory")
    args = parser.parse_args()

    report = asyncio.run(run_multi_hop_demo())
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "multi_hop_demo_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    (out_dir / "multi_hop_demo_report.md").write_text(_render_markdown(report))

    s = report["summary"]
    print(f"single_pass_action = {s['single_pass_action']}")
    print(f"multi_hop_action   = {s['multi_hop_action']}")
    print(f"linked_fact_recovered = {s['linked_fact_recovered']}")
    print(f"distractor_leaked = {s['distractor_leaked']}  budget_bounded = {s['budget_bounded']}")
    print(f"reports written to {out_dir}/multi_hop_demo_report.md and multi_hop_demo_report.json")


if __name__ == "__main__":
    main()
