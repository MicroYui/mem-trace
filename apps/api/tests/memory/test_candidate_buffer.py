"""Unit tests for candidate buffer implementations."""
from __future__ import annotations

import json

from app.memory.candidate_buffer import CandidateBuffer
from app.memory.redis_candidate_buffer import RedisCandidateBuffer
from app.runtime.models import AgentEvent, EventRole, EventType


def _ev(session_id, run_id, content, *, workspace_id="ws") -> AgentEvent:
    return AgentEvent(
        workspace_id=workspace_id,
        session_id=session_id,
        run_id=run_id,
        step_id="step1",
        role=EventRole.user,
        event_type=EventType.message,
        content=content,
    )


async def test_append_and_size_grouped_by_session():
    buf = CandidateBuffer()
    await buf.append(_ev("s1", "r1", "a"))
    await buf.append(_ev("s1", "r1", "b"))
    await buf.append(_ev("s2", "r2", "c"))
    assert await buf.size("s1") == 2
    assert await buf.size("s2") == 1
    assert await buf.total_size() == 3
    assert set(await buf.sessions()) == {"s1", "s2"}


async def test_pending_preserves_write_order_and_does_not_drain():
    buf = CandidateBuffer()
    await buf.append(_ev("s1", "r1", "first"))
    await buf.append(_ev("s1", "r1", "second"))
    pending = await buf.pending("s1")
    assert [e.content for e in pending] == ["first", "second"]
    assert await buf.size("s1") == 2


async def test_pending_and_drain_return_deep_copies():
    buf = CandidateBuffer()
    await buf.append(_ev("s1", "r1", "first"))

    pending = await buf.pending("s1")
    pending[0].content = "mutated"
    assert [e.content for e in await buf.pending("s1")] == ["first"]

    drained = await buf.drain("s1")
    drained[0].content = "mutated again"
    await buf.append(_ev("s1", "r1", "second"))
    assert [e.content for e in await buf.pending("s1")] == ["second"]


async def test_drain_returns_in_order_and_empties_session():
    buf = CandidateBuffer()
    await buf.append(_ev("s1", "r1", "first"))
    await buf.append(_ev("s1", "r1", "second"))
    drained = await buf.drain("s1")
    assert [e.content for e in drained] == ["first", "second"]
    assert await buf.size("s1") == 0
    assert await buf.drain("s1") == []


async def test_drain_unknown_session_is_empty():
    buf = CandidateBuffer()
    assert await buf.drain("nope") == []


async def test_session_falls_back_to_run_when_no_session_id():
    buf = CandidateBuffer()
    await buf.append(_ev(None, "r1", "a"))
    assert await buf.size("r1") == 1


async def test_workspace_filter_preserves_session_flush_compatibility():
    buf = CandidateBuffer()
    await buf.append(_ev("s1", "r1", "a", workspace_id="ws1"))
    await buf.append(_ev("s1", "r2", "b", workspace_id="ws2"))
    await buf.append(_ev("s2", "r3", "c", workspace_id="ws1"))

    assert [e.content for e in await buf.pending("s1", workspace_id="ws1")] == ["a"]
    assert await buf.total_size(workspace_id="ws1") == 2
    assert set(await buf.sessions(workspace_id="ws1")) == {"s1", "s2"}

    drained = await buf.drain("s1")
    assert [e.content for e in drained] == ["a", "b"]
    assert await buf.total_size() == 1


class FakeAsyncRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.sets: dict[str, set[str]] = {}

    async def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.lists.get(key, [])
        return list(items[start:] if end == -1 else items[start : end + 1])

    async def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    async def delete(self, key: str) -> None:
        self.lists.pop(key, None)

    async def sadd(self, key: str, value: str) -> None:
        self.sets.setdefault(key, set()).add(value)

    async def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    async def srem(self, key: str, value: str) -> None:
        if key in self.sets:
            self.sets[key].discard(value)

    async def lpop(self, key: str):
        items = self.lists.get(key, [])
        if not items:
            return None
        return items.pop(0)

    async def lpush(self, key: str, value: str | bytes) -> None:
        stored = value.decode("utf-8") if isinstance(value, bytes) else value
        self.lists.setdefault(key, []).insert(0, stored)


async def test_redis_buffer_keys_do_not_include_event_content():
    redis = FakeAsyncRedis()
    buf = RedisCandidateBuffer(redis)

    await buf.append(_ev("session", "run", "secret content should not be in key", workspace_id="ws"))

    all_keys = [*redis.lists, *redis.sets]
    assert all("secret content" not in key for key in all_keys)
    assert all(":ws:session" not in key for key in all_keys)
    assert len(redis.lists) == 1


async def test_redis_buffer_encodes_key_segments_and_set_members():
    redis = FakeAsyncRedis()
    buf = RedisCandidateBuffer(redis)

    await buf.append(_ev("s:password=hunter2", "run", "safe", workspace_id="ws:tenant"))

    rendered = json.dumps({"list_keys": sorted(redis.lists), "sets": {key: sorted(value) for key, value in redis.sets.items()}})
    assert "ws:tenant" not in rendered
    assert "password=hunter2" not in rendered
    assert await buf.sessions(workspace_id="ws:tenant") == ["s:password=hunter2"]


async def test_redis_buffer_stores_only_post_redaction_event_json():
    redis = FakeAsyncRedis()
    buf = RedisCandidateBuffer(redis)

    await buf.append(_ev("session", "run", "my key is [REDACTED]", workspace_id="ws"))

    stored = next(iter(redis.lists.values()))[0]
    decoded = json.loads(stored)
    assert decoded["content"] == "my key is [REDACTED]"
    assert "sk-raw-secret" not in stored
    assert "password=hunter2" not in stored
    assert "WriteEventRequest" not in stored


async def test_redis_buffer_drains_all_workspaces_for_session_when_workspace_omitted():
    redis = FakeAsyncRedis()
    buf = RedisCandidateBuffer(redis)
    await buf.append(_ev("s1", "r1", "a", workspace_id="ws1"))
    await buf.append(_ev("s1", "r2", "b", workspace_id="ws2"))

    drained = await buf.drain("s1")

    assert [event.content for event in drained] == ["a", "b"]
    assert await buf.total_size() == 0


class BytesFakeAsyncRedis(FakeAsyncRedis):
    async def lrange(self, key: str, start: int, end: int) -> list[bytes]:
        return [value.encode("utf-8") for value in await super().lrange(key, start, end)]

    async def smembers(self, key: str) -> set[bytes]:
        return {value.encode("utf-8") for value in await super().smembers(key)}

    async def lpop(self, key: str):
        value = await super().lpop(key)
        return value.encode("utf-8") if value is not None else None


async def test_redis_buffer_handles_default_bytes_responses():
    redis = BytesFakeAsyncRedis()
    buf = RedisCandidateBuffer(redis)
    await buf.append(_ev("s1", "r1", "a", workspace_id="ws1"))

    assert [event.content for event in await buf.pending("s1")] == ["a"]
    assert await buf.sessions() == ["s1"]
    assert [event.content for event in await buf.drain("s1")] == ["a"]


class AppendDuringDrainRedis(FakeAsyncRedis):
    def __init__(self) -> None:
        super().__init__()
        self.inject_key: str | None = None
        self.inject_value: str | None = None
        self.injected = False

    async def lpop(self, key: str):
        value = await super().lpop(key)
        if value is not None and not self.injected and key == self.inject_key and self.inject_value is not None:
            self.injected = True
            await self.rpush(key, self.inject_value)
        return value


async def test_redis_buffer_drain_does_not_drop_concurrent_append():
    redis = AppendDuringDrainRedis()
    buf = RedisCandidateBuffer(redis)
    await buf.append(_ev("s1", "r1", "first", workspace_id="ws1"))
    redis.inject_key = buf._session_key("ws1", "s1")  # noqa: SLF001 - test fake injects at Redis boundary
    redis.inject_value = _ev("s1", "r2", "second", workspace_id="ws1").model_dump_json()

    drained = await buf.drain("s1", workspace_id="ws1")

    assert [event.content for event in drained] == ["first", "second"]
    assert await buf.total_size() == 0


class FailingOnceLpopRedis(FakeAsyncRedis):
    def __init__(self) -> None:
        super().__init__()
        self.fail_after_first = True
        self._popped = 0

    async def lpop(self, key: str):
        if self.fail_after_first and self._popped == 1:
            raise RuntimeError("transient lpop failure")
        value = await super().lpop(key)
        if value is not None:
            self._popped += 1
        return value


async def test_redis_buffer_restores_indexes_and_popped_values_when_drain_fails():
    redis = FailingOnceLpopRedis()
    buf = RedisCandidateBuffer(redis)
    await buf.append(_ev("s1", "r1", "first", workspace_id="ws1"))
    await buf.append(_ev("s1", "r2", "second", workspace_id="ws1"))

    try:
        await buf.drain("s1", workspace_id="ws1")
    except RuntimeError as exc:
        assert "transient lpop failure" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("drain should surface the transient failure")

    redis.fail_after_first = False
    drained = await buf.drain("s1", workspace_id="ws1")

    assert [event.content for event in drained] == ["first", "second"]
    assert await buf.total_size() == 0
