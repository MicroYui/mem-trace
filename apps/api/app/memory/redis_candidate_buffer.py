"""Redis-backed async candidate buffer for post-redaction AgentEvent payloads."""
from __future__ import annotations

import base64
import uuid

from app.runtime.models import AgentEvent


class RedisCandidateBuffer:
    def __init__(self, redis_client, *, prefix: str = "memtrace:buffer") -> None:
        self._redis = redis_client
        self._prefix = prefix.rstrip(":")

    def _seg(self, value: str) -> str:
        return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")

    def _unseg(self, value: str | bytes) -> str:
        text = self._text(value)
        padding = "=" * (-len(text) % 4)
        return base64.urlsafe_b64decode(f"{text}{padding}".encode("ascii")).decode("utf-8")

    def _session_key(self, workspace_id: str, session_id: str) -> str:
        return f"{self._prefix}:data:{self._seg(workspace_id)}:{self._seg(session_id)}"

    def _index_key(self, session_id: str) -> str:
        return f"{self._prefix}:index:{self._seg(session_id)}"

    def _workspace_index_key(self, workspace_id: str) -> str:
        return f"{self._prefix}:workspace:{self._seg(workspace_id)}:sessions"

    def _all_sessions_key(self) -> str:
        return f"{self._prefix}:sessions"

    def _key(self, event: AgentEvent) -> tuple[str, str]:
        return event.workspace_id, event.session_id or event.run_id

    def _text(self, value: str | bytes) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else value

    async def append(self, event: AgentEvent) -> None:
        workspace_id, session_id = self._key(event)
        key = self._session_key(workspace_id, session_id)
        if hasattr(self._redis, "eval"):
            script = """
            redis.call('RPUSH', KEYS[1], ARGV[1])
            redis.call('SADD', KEYS[2], ARGV[2])
            redis.call('SADD', KEYS[3], ARGV[3])
            redis.call('SADD', KEYS[4], ARGV[3])
            return 1
            """
            await self._redis.eval(
                script,
                4,
                key,
                self._index_key(session_id),
                self._workspace_index_key(workspace_id),
                self._all_sessions_key(),
                event.model_dump_json(),
                self._seg(workspace_id),
                self._seg(session_id),
            )
            return
        await self._redis.rpush(key, event.model_dump_json())
        await self._redis.sadd(self._index_key(session_id), self._seg(workspace_id))
        await self._redis.sadd(self._workspace_index_key(workspace_id), self._seg(session_id))
        await self._redis.sadd(self._all_sessions_key(), self._seg(session_id))

    async def _workspaces_for_session(self, session_id: str, workspace_id: str | None) -> list[str]:
        if workspace_id is not None:
            return [workspace_id]
        return sorted(self._unseg(value) for value in await self._redis.smembers(self._index_key(session_id)))

    async def pending(self, session_id: str, workspace_id: str | None = None) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        for ws in await self._workspaces_for_session(session_id, workspace_id):
            values = await self._redis.lrange(self._session_key(ws, session_id), 0, -1)
            events.extend(AgentEvent.model_validate_json(self._text(value)) for value in values)
        events.sort(key=lambda event: (event.sequence_no, event.created_at, event.event_id))
        return [event.model_copy(deep=True) for event in events]

    async def drain(self, session_id: str, workspace_id: str | None = None) -> list[AgentEvent]:
        workspaces = await self._workspaces_for_session(session_id, workspace_id)
        events: list[AgentEvent] = []
        for ws in workspaces:
            drain_key = await self._detach_workspace_queue(ws, session_id)
            if drain_key is None:
                continue
            raw_values: list[str | bytes] = []
            try:
                while True:
                    value = await self._redis.lpop(drain_key)
                    if value is None:
                        break
                    raw_values.append(value)
                    events.append(AgentEvent.model_validate_json(self._text(value)))
                await self._redis.delete(drain_key)
            except Exception:
                await self._restore_workspace_queue(ws, session_id, drain_key, raw_values)
                raise
        return events

    async def _detach_workspace_queue(self, workspace_id: str, session_id: str) -> str | None:
        key = self._session_key(workspace_id, session_id)
        drain_key = f"{key}:draining:{uuid.uuid4().hex}"
        script = """
        local source = KEYS[1]
        local target = KEYS[2]
        local session_index = KEYS[3]
        local workspace_index = KEYS[4]
        local all_sessions = KEYS[5]
        local workspace_member = ARGV[1]
        local session_member = ARGV[2]
        if redis.call('EXISTS', source) == 1 then
            redis.call('RENAME', source, target)
        else
            target = ''
        end
        redis.call('SREM', session_index, workspace_member)
        redis.call('SREM', workspace_index, session_member)
        if redis.call('SCARD', session_index) == 0 then
            redis.call('SREM', all_sessions, session_member)
        end
        return target
        """
        if hasattr(self._redis, "eval"):
            target = await self._redis.eval(
                script,
                5,
                key,
                drain_key,
                self._index_key(session_id),
                self._workspace_index_key(workspace_id),
                self._all_sessions_key(),
                self._seg(workspace_id),
                self._seg(session_id),
            )
            target_text = self._text(target) if target else ""
            return target_text or None

        # Unit-test fake fallback. Real Redis uses the Lua branch above so the
        # empty-queue / concurrent-append / index-update window is atomic.
        if await self._redis.llen(key) == 0:
            await self._redis.srem(self._index_key(session_id), self._seg(workspace_id))
            await self._redis.srem(self._workspace_index_key(workspace_id), self._seg(session_id))
            if not await self._redis.smembers(self._index_key(session_id)):
                await self._redis.srem(self._all_sessions_key(), self._seg(session_id))
            return None
        await self._redis.srem(self._index_key(session_id), self._seg(workspace_id))
        await self._redis.srem(self._workspace_index_key(workspace_id), self._seg(session_id))
        if not await self._redis.smembers(self._index_key(session_id)):
            await self._redis.srem(self._all_sessions_key(), self._seg(session_id))
        return key

    async def _restore_workspace_queue(
        self,
        workspace_id: str,
        session_id: str,
        drain_key: str,
        raw_values: list[str | bytes],
    ) -> None:
        key = self._session_key(workspace_id, session_id)
        workspace_member = self._seg(workspace_id)
        session_member = self._seg(session_id)
        if hasattr(self._redis, "eval"):
            script = """
            local source = KEYS[1]
            local target = KEYS[2]
            local session_index = KEYS[3]
            local workspace_index = KEYS[4]
            local all_sessions = KEYS[5]
            local workspace_member = ARGV[1]
            local session_member = ARGV[2]
            for i = #ARGV, 3, -1 do
                redis.call('LPUSH', target, ARGV[i])
            end
            while redis.call('LLEN', target) > 0 do
                redis.call('LPUSH', source, redis.call('RPOP', target))
            end
            redis.call('DEL', target)
            redis.call('SADD', session_index, workspace_member)
            redis.call('SADD', workspace_index, session_member)
            redis.call('SADD', all_sessions, session_member)
            return 1
            """
            await self._redis.eval(
                script,
                5,
                key,
                drain_key,
                self._index_key(session_id),
                self._workspace_index_key(workspace_id),
                self._all_sessions_key(),
                workspace_member,
                session_member,
                *[self._text(value) for value in raw_values],
            )
            return
        for value in reversed(raw_values):
            if hasattr(self._redis, "lpush"):
                await self._redis.lpush(drain_key, value)
        await self._redis.sadd(self._index_key(session_id), workspace_member)
        await self._redis.sadd(self._workspace_index_key(workspace_id), session_member)
        await self._redis.sadd(self._all_sessions_key(), session_member)

    async def size(self, session_id: str, workspace_id: str | None = None) -> int:
        return len(await self.pending(session_id, workspace_id=workspace_id))

    async def total_size(self, workspace_id: str | None = None) -> int:
        total = 0
        if workspace_id is not None:
            for session_id in await self.sessions(workspace_id=workspace_id):
                total += await self.size(session_id, workspace_id=workspace_id)
            return total
        for session_id in await self.sessions():
            total += await self.size(session_id)
        return total

    async def sessions(self, workspace_id: str | None = None) -> list[str]:
        if workspace_id is not None:
            return sorted(self._unseg(value) for value in await self._redis.smembers(self._workspace_index_key(workspace_id)))
        return sorted(self._unseg(value) for value in await self._redis.smembers(self._all_sessions_key()))


__all__ = ["RedisCandidateBuffer"]
