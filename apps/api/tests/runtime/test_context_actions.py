"""Unit + dedup-identity tests for the shared context-interpretation helpers.

These helpers were previously duplicated byte-for-byte across the benchmark
evaluator, the deterministic demo, and the SDK CLI. The identity assertions
below lock in the single-source-of-truth refactor so a divergent private copy
cannot silently reappear.
"""
from __future__ import annotations

from app.benchmark import evaluator
from app.demo import run_demo
from app.runtime.context_actions import (
    contaminated,
    decide_action,
    negative_blocks,
    positive_blocks,
)
from app.runtime.models import ContextBlock, MemoryContext


def _ctx(blocks: list[ContextBlock]) -> MemoryContext:
    return MemoryContext(access_id="acc_test", context_blocks=blocks)


def _project(content: str) -> ContextBlock:
    return ContextBlock(type="project_memory", content=content, source="memory")


def _negative(content: str) -> ContextBlock:
    return ContextBlock(type="avoided_attempts", content=content, source="negative_evidence")


def test_positive_blocks_excludes_negative_evidence() -> None:
    pos = _project("This project uses Bun.")
    neg = _negative("AVOIDED: npm test failed")
    ctx = _ctx([pos, neg])
    assert positive_blocks(ctx) == [pos]
    assert negative_blocks(ctx) == [neg]


def test_contaminated_only_counts_positive_failed_npm() -> None:
    # A failed npm lesson confined to negative evidence is NOT contamination.
    ctx = _ctx([_project("This project uses Bun."), _negative("npm test failed; avoid it")])
    assert contaminated(ctx) is False
    # The same failed npm text leaking into positive context IS contamination.
    leaked = _ctx([_project("Tried npm test but it failed because npm was unavailable.")])
    assert contaminated(leaked) is True


def test_decide_action_rules() -> None:
    assert decide_action(_ctx([_project("This project uses Bun.")])) == "bun test"
    assert decide_action(_ctx([_project("npm test failed earlier")])) == "npm test"
    assert decide_action(_ctx([_project("no runner hints here")])) == "unknown"


def test_evaluator_delegates_to_shared_helpers() -> None:
    # Single source of truth: the evaluator re-exports the shared callables.
    assert evaluator.decide_action is decide_action
    assert evaluator.contaminated is contaminated


def test_demo_delegates_to_shared_helpers() -> None:
    assert run_demo._decide_action is decide_action
    assert run_demo._contaminated is contaminated
