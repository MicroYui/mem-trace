"""Public re-export of the shared ``MemoryContext`` interpretation helpers.

Mirrors :mod:`memtrace_sdk.types`: the SDK intentionally depends on the core
``app.runtime`` tier, so the CLI demo can reuse the same deterministic context
reading (positive vs negative blocks, contamination, implied action) as the
runtime and benchmark instead of keeping a private copy.
"""

from app.runtime.context_actions import (
    contaminated,
    decide_action,
    negative_blocks,
    positive_blocks,
)

__all__ = ["positive_blocks", "negative_blocks", "contaminated", "decide_action"]
