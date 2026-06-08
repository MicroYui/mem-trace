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

from app.memory import secrets, writer
from app.retrieval.controller import RetrievalController
from app.runtime import state_tree
from app.runtime.models import (
    AgentEvent,
    AgentRun,
    AgentStep,
    BranchStatus,
    EventType,
    FinishStepRequest,
    FinishStepResult,
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
    ):
        self._repo = repo
        self._default_ws = default_workspace_id
        self._retrieval = RetrievalController(repo, default_token_budget=token_budget)

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
        if not is_secret:
            created_ids = await self._apply_write_rules(event)

        # cache event id on the state node (denormalized; best-effort)
        if step.state_node_id:
            node = await self._repo.get_state_node(step.state_node_id)
            if node is not None:
                node.raw_event_ids.append(event.event_id)
                node.updated_at = _now()
                await self._repo.update_state_node(node)

        return WriteEventResult(event=event, created_memory_ids=created_ids)

    async def finish_step(self, request: FinishStepRequest) -> FinishStepResult:
        step = await self._repo.get_step(request.step_id)
        if step is None:
            raise StepNotFoundError(request.step_id)
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

    async def retrieve_context(self, request: RetrievalRequest) -> MemoryContext:
        run = await self._repo.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)
        ws = request.workspace_id or run.workspace_id
        return await self._retrieval.retrieve(request, workspace_id=ws)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    async def _apply_write_rules(self, event: AgentEvent) -> list[str]:
        created: list[str] = []
        if event.event_type == EventType.message and event.role.value == "user":
            for result in writer.write_from_user_message(event):
                await self._supersede_keys(event.workspace_id, result.supersede_keys)
                await self._repo.add_memory(result.memory)
                created.append(result.memory.memory_id)
        elif event.event_type == EventType.tool_result:
            mem = writer.write_from_tool_result(event)
            if mem is not None:
                await self._repo.add_memory(mem)
                created.append(mem.memory_id)
        return created

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
        if access.run_id:
            active_node, _ = await self._retrieval._load_active_state(access.run_id)
        blocks, _ = pack_context(
            active_node=active_node,
            accepted=accepted_mems,
            token_budget=access.token_budget or 512,
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


__all__ = ["MemoryRuntime", "RunNotFoundError", "StepNotFoundError"]
