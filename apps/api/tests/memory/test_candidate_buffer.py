"""Unit tests for the pure candidate buffer (P2: candidate buffer / idle flush)."""
from __future__ import annotations

from app.memory.candidate_buffer import CandidateBuffer
from app.runtime.models import AgentEvent, EventRole, EventType


def _ev(session_id, run_id, content) -> AgentEvent:
    return AgentEvent(
        workspace_id="ws",
        session_id=session_id,
        run_id=run_id,
        step_id="step1",
        role=EventRole.user,
        event_type=EventType.message,
        content=content,
    )


def test_append_and_size_grouped_by_session():
    buf = CandidateBuffer()
    buf.append(_ev("s1", "r1", "a"))
    buf.append(_ev("s1", "r1", "b"))
    buf.append(_ev("s2", "r2", "c"))
    assert buf.size("s1") == 2
    assert buf.size("s2") == 1
    assert buf.total_size() == 3
    assert set(buf.sessions()) == {"s1", "s2"}


def test_pending_preserves_write_order_and_does_not_drain():
    buf = CandidateBuffer()
    buf.append(_ev("s1", "r1", "first"))
    buf.append(_ev("s1", "r1", "second"))
    pending = buf.pending("s1")
    assert [e.content for e in pending] == ["first", "second"]
    # pending is non-destructive
    assert buf.size("s1") == 2


def test_drain_returns_in_order_and_empties_session():
    buf = CandidateBuffer()
    buf.append(_ev("s1", "r1", "first"))
    buf.append(_ev("s1", "r1", "second"))
    drained = buf.drain("s1")
    assert [e.content for e in drained] == ["first", "second"]
    assert buf.size("s1") == 0
    # second drain is a no-op (idempotent)
    assert buf.drain("s1") == []


def test_drain_unknown_session_is_empty():
    buf = CandidateBuffer()
    assert buf.drain("nope") == []


def test_session_falls_back_to_run_when_no_session_id():
    buf = CandidateBuffer()
    buf.append(_ev(None, "r1", "a"))
    assert buf.size("r1") == 1
