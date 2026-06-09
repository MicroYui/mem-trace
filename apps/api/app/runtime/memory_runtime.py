"""MemoryRuntime facade.

Single public boundary over repository + state tree + memory writer + retrieval.
Orchestrates the hot path: start_run -> start_step -> write_event* ->
finish_step / rollback_branch -> retrieve_context.

State-tree invariants enforced here:
- start_step creates the state node immediately.
- recovery steps attach to the failed step's parent node (not the failed node).
- events get a strictly increasing run-local sequence_no.
- rollback marks the failed node + descendants rolled_back and flips related
  memories to branch_status=rolled_back while preserving failure_reason.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.memory import secrets, summarizer, writer
from app.memory import resolver
from app.memory.candidate_buffer import CandidateBuffer
from app.retrieval.controller import RetrievalController
from app.runtime import state_tree
from app.runtime.models import (
    AgentEvent,
    AgentRun,
    AgentStep,
    BranchStatus,
    CompleteRunRequest,
    CompleteRunResult,
    DashboardTables,
    EventType,
    ExtractionMode,
    FinishStepRequest,
    FinishStepResult,
    FlushResult,
    MemoryContext,
    MemoryItem,
    MemoryStatus,
    RetrievalRequest,
    RollbackRequest,
    RollbackResult,
    RunStatus,
    StartRunRequest,
    StartStepRequest,
    StateNode,
    StateNodeType,
    StepStatus,
    WriteEventRequest,
    WriteEventResult,
)
from app.runtime.repository import Repository


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RunNotFoundError(Exception):
    pass


class StepNotFoundError(Exception):
    pass


class MemoryRuntime:
    def __init__(
        self,
        repo: Repository,
        *,
        default_workspace_id: str = "ws_default",
        token_budget: int = 512,
        extraction_mode: ExtractionMode = ExtractionMode.sync,
    ):
        self._repo = repo
        self._default_ws = default_workspace_id
        self._retrieval = RetrievalController(repo, default_token_budget=token_budget)
        # Default freshness/latency policy (architecture.md §12.1). ``sync``
        # keeps the demo/benchmark inline-extracting; ``buffered`` defers
        # extraction to a flush. A per-event override can still force sync.
        self._extraction_mode = extraction_mode
        self._buffer = CandidateBuffer()

    # ------------------------------------------------------------------ #
    # Run / step / event lifecycle
    # ------------------------------------------------------------------ #
    async def start_run(self, request: StartRunRequest) -> AgentRun:
        ws = request.workspace_id or self._default_ws
        run = AgentRun(
            workspace_id=ws,
            session_id=request.session_id,
            task=request.task,
            status=RunStatus.running,
            metadata=request.metadata,
        )
        await self._repo.add_run(run)
        root = state_tree.make_root_node(workspace_id=ws, run_id=run.run_id, goal=request.task)
        await self._repo.add_state_node(root)
        return run

    async def start_step(self, request: StartStepRequest) -> AgentStep:
        run = await self._repo.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)

        nodes = {n.node_id: n for n in await self._repo.list_state_nodes(run.run_id)}
        node_type = StateNodeType.step
        branch_reason: dict = {}
        parent_node: Optional[StateNode] = None

        if request.recovery_from_step_id:
            node_type = StateNodeType.recovery
            failed_step = await self._repo.get_step(request.recovery_from_step_id)
            if failed_step is None:
                raise StepNotFoundError(request.recovery_from_step_id)
            failed_node = nodes.get(failed_step.state_node_id) if failed_step.state_node_id else None
            if failed_node is not None:
                parent_node = state_tree.recovery_parent(failed_node, nodes)
            branch_reason = {
                "type": "recovery",
                "recovery_from_step_id": request.recovery_from_step_id,
            }
            if failed_node is not None and failed_node.failure_reason:
                branch_reason["rollback_reason"] = failed_node.failure_reason
        elif request.parent_step_id:
            parent_step = await self._repo.get_step(request.parent_step_id)
            if parent_step and parent_step.state_node_id:
                parent_node = nodes.get(parent_step.state_node_id)

        if parent_node is None:
            parent_node = self._find_root(nodes.values())
        if parent_node is None:
            raise RunNotFoundError(f"no root node for run {run.run_id}")

        step = AgentStep(
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            parent_step_id=request.parent_step_id,
            recovery_from_step_id=request.recovery_from_step_id,
            intent=request.intent,
            status=StepStatus.active,
            metadata=request.metadata,
        )
        node = state_tree.make_step_node(
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            step_id=step.step_id,
            parent=parent_node,
            node_type=node_type,
            goal=request.goal or request.intent,
            branch_reason=branch_reason,
        )
        step.state_node_id = node.node_id
        await self._repo.add_state_node(node)
        await self._repo.add_step(step)
        return step

    async def write_event(self, request: WriteEventRequest) -> WriteEventResult:
        run = await self._repo.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)
        step = await self._repo.get_step(request.step_id)
        if step is None:
            raise StepNotFoundError(request.step_id)

        seq = await self._repo.next_sequence_no(run.run_id)

        # Secret protection: redact content; do not create retrievable memory.
        content = request.content
        redaction_status = "none"
        is_secret = secrets.contains_secret(content)
        if is_secret:
            content = secrets.redact(content)
            redaction_status = "redacted"

        event = AgentEvent(
            workspace_id=run.workspace_id,
            session_id=run.session_id,
            run_id=run.run_id,
            step_id=step.step_id,
            state_node_id=step.state_node_id,
            sequence_no=seq,
            role=request.role,
            event_type=request.event_type,
            content=content,
            redaction_status=redaction_status,
            tool_name=request.tool_name,
            status=request.status,
            token_input=request.token_input,
            token_output=request.token_output,
            latency_ms=request.latency_ms,
            metadata=request.metadata,
        )
        await self._repo.add_event(event)

        created_ids: list[str] = []
        buffered = False
        if not is_secret:
            # Secret events never produce retrievable memory and are never
            # buffered. For non-secret events, honor the effective extraction
            # mode: inline (sync) or defer to a flush (buffered).
            effective_mode = request.extraction_mode or self._extraction_mode
            if effective_mode == ExtractionMode.buffered:
                self._buffer.append(event)
                buffered = True
            else:
                created_ids = await self._apply_write_rules(event)

        # cache event id on the state node (denormalized; best-effort)
        if step.state_node_id:
            node = await self._repo.get_state_node(step.state_node_id)
            if node is not None:
                node.raw_event_ids.append(event.event_id)
                node.updated_at = _now()
                await self._repo.update_state_node(node)

        return WriteEventResult(event=event, created_memory_ids=created_ids, buffered=buffered)

    async def finish_step(self, request: FinishStepRequest) -> FinishStepResult:
        step = await self._repo.get_step(request.step_id)
        if step is None:
            raise StepNotFoundError(request.step_id)

        # finish_step is a natural window boundary: lazily flush any buffered
        # candidates for this run's session so the step's working-state memory
        # is written on top of an already-extracted buffer (architecture.md §12.1).
        run = await self._repo.get_run(step.run_id)
        if run is not None:
            await self._flush_session(run.session_id)

        step.status = request.status
        step.error_message = request.error_message
        step.finished_at = _now()
        step.updated_at = _now()
        await self._repo.update_step(step)

        node = await self._repo.get_state_node(step.state_node_id) if step.state_node_id else None
        if node is not None:
            state_tree.apply_finish(node, request.status)
            if request.status == StepStatus.failed and request.error_message:
                node.failure_reason = request.error_message
            if request.summary:
                node.summary = request.summary
            await self._repo.update_state_node(node)

        created_ids: list[str] = []
        mem = writer.write_from_finish_step(step, summary=request.summary)
        await self._repo.add_memory(mem)
        created_ids.append(mem.memory_id)

        return FinishStepResult(
            step=step,
            state_node=node if node is not None else StateNode(workspace_id=step.workspace_id, run_id=step.run_id),
            created_memory_ids=created_ids,
        )

    async def rollback_branch(self, request: RollbackRequest) -> RollbackResult:
        step = await self._repo.get_step(request.step_id)
        if step is None:
            raise StepNotFoundError(request.step_id)

        # Flush before rolling back: in buffered mode the branch's memories may
        # still be pending extraction. Materializing them first lets rollback
        # flip them to rolled_back, keeping failed-branch isolation identical to
        # sync mode (otherwise a later flush would resurrect them as completed).
        run = await self._repo.get_run(request.run_id)
        if run is not None:
            await self._flush_session(run.session_id)

        all_nodes = await self._repo.list_state_nodes(request.run_id)
        by_id = {n.node_id: n for n in all_nodes}
        target_node = by_id.get(step.state_node_id) if step.state_node_id else None

        rolled_node_ids: list[str] = []
        rolled_step_ids: list[str] = []

        if target_node is not None:
            affected_nodes = [target_node] + state_tree.descendants(target_node.node_id, all_nodes)
            for n in affected_nodes:
                state_tree.apply_rollback(n, reason=request.reason)
                await self._repo.update_state_node(n)
                rolled_node_ids.append(n.node_id)
                if n.step_id:
                    s = await self._repo.get_step(n.step_id)
                    if s is not None:
                        s.status = StepStatus.rolled_back
                        s.updated_at = _now()
                        await self._repo.update_step(s)
                        rolled_step_ids.append(s.step_id)
        else:
            step.status = StepStatus.rolled_back
            await self._repo.update_step(step)
            rolled_step_ids.append(step.step_id)

        # flip related memories to rolled_back
        affected_mem_ids: list[str] = []
        node_id_set = set(rolled_node_ids)
        for mem in await self._repo.list_memories(run_id=request.run_id):
            if mem.source_state_node_id in node_id_set or mem.source_state_node_id == step.state_node_id:
                mem.branch_status = BranchStatus.rolled_back
                mem.updated_at = _now()
                await self._repo.update_memory(mem)
                affected_mem_ids.append(mem.memory_id)

        return RollbackResult(
            rolled_back_step_ids=rolled_step_ids,
            rolled_back_node_ids=rolled_node_ids,
            affected_memory_ids=affected_mem_ids,
        )

    async def complete_run(self, request: CompleteRunRequest) -> CompleteRunResult:
        """Cold-path: mark the run finished and sediment durable memory.

        Summarizes the run's active path into a completed-run episodic memory and
        (for successful runs) a reusable procedural memory, so a later similar
        run can recall the approach that worked. This is intentionally NOT on the
        hot retrieve path. Re-running it supersedes the prior same-key summaries
        for this run so the operation is idempotent (no duplicates).
        """
        run = await self._repo.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)

        # Drain any pending buffered candidates before summarizing so the run
        # summary / procedural memory reflect every written event.
        await self._flush_session(run.session_id)

        run.status = request.status
        run.finished_at = _now()
        run.updated_at = _now()
        await self._repo.update_run(run)

        nodes = await self._repo.list_state_nodes(run.run_id)
        memories = await self._repo.list_memories(workspace_id=run.workspace_id)

        result = summarizer.build_run_summary(
            run=run, nodes=nodes, memories=memories, summary=request.summary
        )

        created_ids: list[str] = []
        # Supersede any prior summary/procedural memories for THIS run so a
        # re-run of the cold path does not accumulate duplicates.
        for mem in result.created:
            await self._supersede_run_summary_key(run.workspace_id, mem.key)
            await self._repo.add_memory(mem)
            created_ids.append(mem.memory_id)

        return CompleteRunResult(
            run=run,
            summary_memory_id=result.episodic.memory_id,
            procedural_memory_id=result.procedural.memory_id if result.procedural else None,
            created_memory_ids=created_ids,
        )

    async def retrieve_context(self, request: RetrievalRequest) -> MemoryContext:
        run = await self._repo.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)
        # Lazy flush: extraction is deferred in buffered mode, so before reading
        # context we drain this session's buffer so freshly-written events are
        # reflected in the retrieved memory (architecture.md §12.1 "lazy").
        await self._flush_session(run.session_id)
        ws = request.workspace_id or run.workspace_id
        return await self._retrieval.retrieve(request, workspace_id=ws)

    async def flush_session(self, session_id: str) -> FlushResult:
        """Force extraction of all buffered candidates for a session.

        Backs ``POST /v1/sessions/{session_id}/flush`` (architecture.md §6 /
        explicit flush). Safe to call in any mode: with an empty buffer it is a
        no-op. Draining before extraction makes repeated flushes idempotent.
        """
        events = self._buffer.drain(session_id)
        created: list[str] = []
        for event in events:
            created.extend(await self._apply_write_rules(event))
        return FlushResult(
            session_id=session_id,
            processed_event_count=len(events),
            created_memory_ids=created,
        )

    async def _flush_session(self, session_id: str) -> list[str]:
        """Lazy-flush a session at a window boundary; returns created ids."""
        return (await self.flush_session(session_id)).created_memory_ids

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    async def _apply_write_rules(self, event: AgentEvent) -> list[str]:
        created: list[str] = []
        if event.event_type == EventType.message and event.role.value == "user":
            for result in writer.write_from_user_message(event):
                # Explicit correction retires the old key first (decisive); the
                # resolver then dedups/reconciles the incoming against whatever
                # same-identity actives remain.
                await self._supersede_keys(event.workspace_id, result.supersede_keys)
                created_id = await self._resolve_and_persist(event.workspace_id, result.memory)
                if created_id is not None:
                    created.append(created_id)
        elif event.event_type == EventType.tool_result:
            mem = writer.write_from_tool_result(event)
            if mem is not None:
                await self._repo.add_memory(mem)
                created.append(mem.memory_id)
        return created

    async def _resolve_and_persist(self, workspace_id: str, incoming: MemoryItem) -> Optional[str]:
        """Dedup/merge + conflict-resolve ``incoming`` against same-identity actives.

        Returns the new memory id if a fresh row was added, or ``None`` when the
        incoming write was folded into an existing memory (deduped).
        """
        existing = await self._same_identity_actives(workspace_id, incoming)
        result = resolver.resolve(incoming, existing)
        for mem in result.updates:
            await self._repo.update_memory(mem)
        if result.add is not None:
            await self._repo.add_memory(result.add)
            return result.add.memory_id
        return None

    async def _same_identity_actives(
        self, workspace_id: str, incoming: MemoryItem
    ) -> list[MemoryItem]:
        if incoming.key is None:
            return []
        out: list[MemoryItem] = []
        for mem in await self._repo.list_memories(workspace_id=workspace_id):
            if (
                mem.status == MemoryStatus.active
                and mem.memory_id != incoming.memory_id
                and mem.key == incoming.key
                and mem.scope.value == incoming.scope.value
            ):
                out.append(mem)
        return out

    async def _supersede_keys(self, workspace_id: str, keys: list[tuple[str, str]]) -> None:
        if not keys:
            return
        wanted = set(keys)
        for mem in await self._repo.list_memories(workspace_id=workspace_id):
            if mem.status != MemoryStatus.active or mem.key is None:
                continue
            if (mem.key, mem.scope.value) in wanted:
                mem.status = MemoryStatus.superseded
                mem.updated_at = _now()
                await self._repo.update_memory(mem)

    async def _supersede_run_summary_key(self, workspace_id: str, key: Optional[str]) -> None:
        """Supersede prior active memories with the same summary/procedural key.

        Keys are run-scoped (e.g. ``run.summary.<run_id>``), so this only ever
        affects re-summarization of the SAME run, keeping complete_run idempotent
        without disturbing other runs' memories.
        """
        if not key:
            return
        for mem in await self._repo.list_memories(workspace_id=workspace_id):
            if mem.status == MemoryStatus.active and mem.key == key:
                mem.status = MemoryStatus.superseded
                mem.updated_at = _now()
                await self._repo.update_memory(mem)

    @staticmethod
    def _find_root(nodes) -> Optional[StateNode]:
        for n in nodes:
            if n.node_type == StateNodeType.root:
                return n
        return None

    # ------------------------------------------------------------------ #
    # Read models
    # ------------------------------------------------------------------ #
    async def get_timeline(self, run_id: str) -> list[AgentEvent]:
        return await self._repo.list_events(run_id)

    async def get_state_tree(self, run_id: str) -> list[StateNode]:
        return await self._repo.list_state_nodes(run_id)

    async def get_steps(self, run_id: str) -> list[AgentStep]:
        return await self._repo.list_steps(run_id)

    async def get_profile(self, run_id: str) -> list:
        return await self._repo.list_profile_events(run_id=run_id)

    async def list_memories(
        self, *, workspace_id: Optional[str] = None, run_id: Optional[str] = None
    ) -> list[MemoryItem]:
        return await self._repo.list_memories(workspace_id=workspace_id, run_id=run_id)

    async def dashboard_tables(self, *, workspace_id: Optional[str] = None) -> DashboardTables:
        """Return minimal table payload for the P1 dashboard/API view."""
        runs = await self._repo.list_runs(workspace_id=workspace_id)
        accesses = await self._repo.list_access_logs(workspace_id=workspace_id)
        profile_events = await self._repo.list_profile_events()
        cases = await self._repo.list_benchmark_cases()
        results = await self._repo.list_benchmark_results()
        return DashboardTables(
            runs=runs,
            accesses=accesses,
            profile_events=profile_events,
            benchmark_cases=cases,
            benchmark_results=results,
            benchmark_summary=_benchmark_summary_from_records(results),
        )

    async def inspect_access(self, access_id: str):
        """Rebuild the full retrieval story for GET /v1/access/{access_id}.

        candidates/gate_decisions come from persisted gate logs joined with
        memory content; context_blocks are re-derived from accepted memories.
        """
        from app.runtime.models import (
            AccessInspection,
            GateDecisionType,
            GateDecisionView,
        )
        from app.retrieval.packer import pack_context

        access = await self._repo.get_access_log(access_id)
        if access is None:
            return None
        gate_logs = await self._repo.list_gate_logs(access_id)

        views: list[GateDecisionView] = []
        accepted_mems: list[MemoryItem] = []
        for g in gate_logs:
            mem = await self._repo.get_memory(g.memory_id)
            content = mem.content if mem else ""
            views.append(
                GateDecisionView(
                    memory_id=g.memory_id,
                    content=content,
                    layer=g.layer,
                    decision=g.decision,
                    reject_reason=g.reject_reason,
                    relevance_score=g.relevance_score,
                    state_match_score=g.state_match_score,
                    freshness_score=g.freshness_score,
                    trust_score=g.trust_score,
                    risk_score=g.risk_score,
                    final_score=g.final_score,
                    branch_status=mem.branch_status if mem else None,
                )
            )
            if g.decision in (GateDecisionType.accept, GateDecisionType.degrade, GateDecisionType.warn) and mem:
                accepted_mems.append(mem)

        accepted_mems.sort(
            key=lambda m: next((v.final_score for v in views if v.memory_id == m.memory_id), 0.0),
            reverse=True,
        )
        active_node = None
        active_path: list = []
        if access.run_id:
            active_node, _, active_path = await self._retrieval._load_active_state(access.run_id)
        blocks, _ = pack_context(
            active_node=active_node,
            accepted=accepted_mems,
            token_budget=access.token_budget or 512,
            active_path=active_path,
        )
        profile = self._retrieval._profile_summary(access)
        return AccessInspection(
            access_id=access.access_id,
            query=access.query,
            task_intent=access.task_intent,
            retrieval_strategy=access.retrieval_strategy,
            candidates=views,
            gate_decisions=views,
            context_blocks=blocks,
            profile=profile,
        )


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _benchmark_summary_from_records(results) -> dict[str, dict[str, float]]:
    by_strategy: dict[str, list] = {}
    for row in results:
        by_strategy.setdefault(row.strategy, []).append(row.metrics)
    summary: dict[str, dict[str, float]] = {}
    for strategy, rows in by_strategy.items():
        summary[strategy] = {
            "task_success_rate": _avg([float(r.get("task_success", 0)) for r in rows]),
            "correct_active_path_hit_rate": _avg([float(r.get("correct_active_path_hit", 0)) for r in rows]),
            "failed_branch_contamination_rate": _avg([float(r.get("failed_branch_contamination", 0)) for r in rows]),
            "stale_memory_injection_rate": _avg([float(r.get("stale_memory_injection", 0)) for r in rows]),
            "cross_workspace_leakage_rate": _avg([float(r.get("cross_workspace_leakage", 0)) for r in rows]),
            "tool_sensitive_blocked_rate": _avg([
                float(r.get("tool_sensitive_blocked", 0)) for r in rows if r.get("tool_sensitive_present")
            ]),
            "procedural_reuse_hit_rate": _avg([
                float(r.get("procedural_reuse_hit", 0)) for r in rows if r.get("procedural_reuse_present")
            ]),
        }
    return summary


__all__ = ["MemoryRuntime", "RunNotFoundError", "StepNotFoundError"]
