"""In-process candidate buffer (P2: candidate buffer / idle flush).

Implements the deterministic, dependency-free version of the architecture.md §8.1
write path: when extraction is ``buffered``, an event's raw form is already
persisted by the runtime, and a lightweight *candidate* (the event id, grouped by
session) is appended here. Extraction is then deferred until an explicit or lazy
flush at a natural window boundary (retrieve_context / finish_step), matching the
``buffered`` mode in architecture.md §12.1.

This keeps the hot write path cheap (no inline extraction) while staying fully
deterministic for the demo/benchmark — there is no Redis, no background worker,
and no timing dependence. The buffer is ephemeral: it only holds event ids
(grouping by session), so losing it never loses an unrecoverable fact (the raw
events remain in PostgreSQL).
"""
from __future__ import annotations

from app.runtime.models import AgentEvent


class CandidateBuffer:
    """Session-keyed FIFO buffer of candidate events awaiting extraction.

    Order is preserved per session so flush replays events in the order they were
    written (extraction rules like dedup/conflict resolution are order-sensitive).
    """

    def __init__(self) -> None:
        self._by_session: dict[str, list[AgentEvent]] = {}

    def _key(self, event: AgentEvent) -> str:
        # Group by session; fall back to run when an event has no session so a
        # session-less event is still buffered (and flushable) under a stable key.
        return event.session_id or event.run_id

    def append(self, event: AgentEvent) -> None:
        """Append a candidate event to its session's pending queue."""
        self._by_session.setdefault(self._key(event), []).append(event.model_copy(deep=True))

    def pending(self, session_id: str) -> list[AgentEvent]:
        """Return (a copy of) the pending events for a session, in write order."""
        return [e.model_copy(deep=True) for e in self._by_session.get(session_id, [])]

    def size(self, session_id: str) -> int:
        return len(self._by_session.get(session_id, []))

    def total_size(self) -> int:
        return sum(len(v) for v in self._by_session.values())

    def drain(self, session_id: str) -> list[AgentEvent]:
        """Remove and return all pending events for a session, in write order.

        Draining before extraction makes flush idempotent: a second flush of an
        already-drained session finds nothing to process.
        """
        return self._by_session.pop(session_id, [])

    def sessions(self) -> list[str]:
        return list(self._by_session.keys())


__all__ = ["CandidateBuffer"]
