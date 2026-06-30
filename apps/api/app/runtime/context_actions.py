"""Shared, dependency-light interpretation of a packed ``MemoryContext``.

The benchmark evaluator, the deterministic demo, and the SDK CLI all need the
same deterministic reading of a packed context: which blocks are positive
(prompt) context versus warning-only negative evidence, whether a failed-branch
``npm`` memory leaked into positive context (contamination), and the naive test
command implied by the context (mvp.md §10.3).

This lives in ``app.runtime`` — the DTO tier the SDK already depends on through
``memtrace_sdk.types`` — so the CLI can reuse it without importing the heavier
``app.benchmark`` package, giving a single source of truth instead of three
byte-identical copies.
"""
from __future__ import annotations

from app.runtime.models import ContextBlock, MemoryContext


def positive_blocks(ctx: MemoryContext) -> list[ContextBlock]:
    """Blocks that form positive prompt context (excludes negative evidence)."""
    return [
        block
        for block in ctx.context_blocks
        if block.type != "avoided_attempts" and block.source != "negative_evidence"
    ]


def negative_blocks(ctx: MemoryContext) -> list[ContextBlock]:
    """Blocks that are warning-only negative evidence (avoided attempts)."""
    return [
        block
        for block in ctx.context_blocks
        if block.type == "avoided_attempts" or block.source == "negative_evidence"
    ]


def contaminated(ctx: MemoryContext) -> bool:
    """failed_branch_contamination: a failed ``npm`` memory reached positive context."""
    return any(
        "npm" in block.content.lower() and "failed" in block.content.lower()
        for block in positive_blocks(ctx)
    )


def decide_action(ctx: MemoryContext) -> str:
    """Pick the test command implied by the packed context (mvp.md §10.3).

    A surviving failed-branch ``npm`` memory leads a naive agent back to ``npm``;
    only when no failed npm evidence is present does the Bun constraint win.
    """
    if contaminated(ctx):
        return "npm test"
    text = " ".join(block.content.lower() for block in positive_blocks(ctx))
    if "bun" in text:
        return "bun test"
    return "unknown"


__all__ = ["positive_blocks", "negative_blocks", "contaminated", "decide_action"]
