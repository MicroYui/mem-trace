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

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Optional

from app.memory import secrets, summarizer, writer
from app.memory import llm_extractor, resolver
from app.memory.candidate_buffer import CandidateBuffer
from app.memory.key_ontology import canonical_memory_key, same_memory_key_identity
from app.memory.llm_extractor import ExtractionProvider
from app.config import get_settings
from app.memory.summarizer_provider import (
    RuleSummarizerProvider,
    SummarizeRequest,
    SummarizeResult,
    SummarizerProvider,
)
from app.observability.metrics import build_observability_summary
from app.observability.replay import RetrievalReplayService
from app.observability.reports import write_observability_report
from app.observability.trace_bundle import (
    TraceBundle,
    TraceBundleValidation,
    export_access_bundle,
    export_run_bundle,
    validate_bundle_schema,
)
from app.providers.base import ProviderKind
from app.providers.registry import ProviderRegistry
from app.retrieval.controller import RetrievalController
from app.retrieval.packer import estimate_tokens as _estimate_history_tokens
from app.retrieval.similarity import stable_embedding
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
    EmbeddingStatus,
    ExtractionMode,
    FinishStepRequest,
    FinishStepResult,
    FlushResult,
    MemoryContext,
    MemoryItem,
    MemoryStatus,
    ObservabilitySummary,
    ObservabilityReportRequest,
    ObservabilityReportResult,
    ReplayRetrievalResult,
    RetrievalRequest,
    RollbackRequest,
    RollbackResult,
    RunReplayResult,
    RunStatus,
    Sensitivity,
    StartRunRequest,
    StartStepRequest,
    StateNode,
    StateNodeStatus,
    StateNodeType,
    StepStatus,
    WriteEventRequest,
    WriteEventResult,
    CompactionProvider,
    CompactionKind,
    ContextBlock,
    PendingCompactionLog,
    ProfilePhase,
    Provenance,
    RetainedFact,
)
from app.runtime.repository import EMBED_DIM, Repository


def _now() -> datetime:
    return datetime.now(timezone.utc)


logger = logging.getLogger(__name__)


class RunNotFoundError(Exception):
    pass


class StepNotFoundError(Exception):
    pass


class StateTreeError(Exception):
    """Raised when the execution state tree is structurally inconsistent."""
    pass


class MemoryRuntime:
    def __init__(
        self,
        repo: Repository,
        *,
        default_workspace_id: str = "ws_default",
        token_budget: int = 512,
        extraction_mode: ExtractionMode = ExtractionMode.sync,
        extraction_provider: Optional[ExtractionProvider] = None,
        summarizer_provider: Optional[SummarizerProvider] = None,
        provider_registry: Optional[ProviderRegistry] = None,
    ):
        settings = get_settings()
        self._repo = repo
        self._default_ws = default_workspace_id
        self._provider_registry = provider_registry
        self._embedding_dim = EMBED_DIM
        self._embedding_provider = (
            provider_registry.get(ProviderKind.embedding) if provider_registry is not None else None
        )
        registry_extraction_provider = (
            provider_registry.get(ProviderKind.extraction) if provider_registry is not None else None
        )
        registry_summarizer_provider = (
            provider_registry.get(ProviderKind.summarizer) if provider_registry is not None else None
        )
        # C3 summarizer seam. Always keep a deterministic provider available so
        # C4 can degrade to rule summaries without losing retained facts.
        self._summarizer_provider = summarizer_provider or registry_summarizer_provider or RuleSummarizerProvider()
        provider_snapshot = provider_registry.snapshot() if provider_registry is not None else None
        summarizer_capabilities = getattr(summarizer_provider, "capabilities", None) if summarizer_provider is not None else None
        if summarizer_capabilities is not None:
            provider_snapshot = dict(provider_snapshot or {})
            provider_snapshot[ProviderKind.summarizer.value] = summarizer_capabilities.snapshot()
        self._retrieval = RetrievalController(
            repo,
            default_token_budget=token_budget,
            provider_registry=provider_registry,
            provider_snapshot=provider_snapshot,
        )
        # Default freshness/latency policy (architecture.md §12.1). ``sync``
        # keeps the demo/benchmark inline-extracting; ``buffered`` defers
        # extraction to a flush. A per-event override can still force sync.
        self._extraction_mode = extraction_mode
        # Optional config-gated LLM extraction (P2). When set, user-message
        # extraction goes through the provider instead of the rule-based writer;
        # ``None`` (default) keeps the deterministic writer path.
        self._extraction_provider = extraction_provider if extraction_provider is not None else registry_extraction_provider
        self._compaction_enabled = settings.compaction_enabled
        self._compaction_history_token_threshold = settings.compaction_history_token_threshold
        self._compaction_summary_budget_tokens = settings.compaction_summary_budget_tokens
        self._compaction_timeout_ms = settings.compaction_timeout_ms
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
            if failed_step.run_id != run.run_id:
                raise StepNotFoundError(request.recovery_from_step_id)
            failed_node = nodes.get(failed_step.state_node_id) if failed_step.state_node_id else None
            if failed_node is not None:
                parent_node = state_tree.recovery_parent(failed_node, nodes)
                # A recovery node must attach to the failed node's parent. If the
                # failed node has a parent_id that cannot be resolved, the tree is
                # inconsistent; do NOT silently reattach to root (which would
                # misplace the recovery in a multi-level tree).
                if parent_node is None and failed_node.parent_id is not None:
                    raise StateTreeError(
                        f"recovery parent {failed_node.parent_id} not found for "
                        f"failed step {request.recovery_from_step_id}"
                    )
            branch_reason = {
                "type": "recovery",
                "recovery_from_step_id": request.recovery_from_step_id,
            }
            if failed_node is not None and failed_node.failure_reason:
                branch_reason["rollback_reason"] = failed_node.failure_reason
        elif request.parent_step_id:
            parent_step = await self._repo.get_step(request.parent_step_id)
            if parent_step is None or parent_step.run_id != run.run_id:
                raise StepNotFoundError(request.parent_step_id)
            if parent_step.state_node_id:
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
        if step.run_id != run.run_id:
            raise StepNotFoundError(request.step_id)

        state_node = None
        if step.state_node_id:
            state_node = await self._repo.get_state_node(step.state_node_id)
            if state_node is None or state_node.run_id != run.run_id:
                raise StateTreeError(f"state node not found for step: {step.step_id}")

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
            sequence_no=0,
            event_source=request.event_source,
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
        event = await self._repo.append_event(event)

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
        if state_node is not None:
            state_node.raw_event_ids.append(event.event_id)
            state_node.updated_at = _now()
            await self._repo.update_state_node(state_node)

        return WriteEventResult(event=event, created_memory_ids=created_ids, buffered=buffered)

    async def finish_step(self, request: FinishStepRequest) -> FinishStepResult:
        step = await self._repo.get_step(request.step_id)
        if step is None:
            raise StepNotFoundError(request.step_id)
        if step.run_id != request.run_id:
            raise StepNotFoundError(request.step_id)

        if not step.state_node_id:
            raise StateTreeError(f"state node not found for step: {step.step_id}")
        node = await self._repo.get_state_node(step.state_node_id)
        if node is None or node.run_id != request.run_id:
            raise StateTreeError(f"state node not found for step: {step.step_id}")

        run = await self._repo.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)

        # finish_step is a natural window boundary: lazily flush any buffered
        # candidates for this run's session so the step's working-state memory
        # is written on top of an already-extracted buffer (architecture.md §12.1).
        await self._flush_session(run.session_id)

        step.status = request.status
        step.error_message = request.error_message
        step.finished_at = _now()
        step.updated_at = _now()
        await self._repo.update_step(step)

        state_tree.apply_finish(node, request.status)
        if request.status == StepStatus.failed and request.error_message:
            node.failure_reason = request.error_message
        if request.summary:
            node.summary = request.summary
        await self._repo.update_state_node(node)

        created_ids: list[str] = []
        mem = writer.write_from_finish_step(step, summary=request.summary)
        await self._repo.add_memory(await self._prepare_embedding(mem))
        created_ids.append(mem.memory_id)

        return FinishStepResult(
            step=step,
            state_node=node,
            created_memory_ids=created_ids,
        )

    async def rollback_branch(self, request: RollbackRequest) -> RollbackResult:
        step = await self._repo.get_step(request.step_id)
        if step is None:
            raise StepNotFoundError(request.step_id)
        if step.run_id != request.run_id:
            raise StepNotFoundError(request.step_id)

        all_nodes = await self._repo.list_state_nodes(request.run_id)
        by_id = {n.node_id: n for n in all_nodes}
        if not step.state_node_id:
            raise StateTreeError(f"state node not found for rollback step: {step.step_id}")
        target_node = by_id.get(step.state_node_id)
        if target_node is None:
            raise StateTreeError(f"state node not found for rollback step: {step.step_id}")

        run = await self._repo.get_run(request.run_id)
        if run is None:
            raise RunNotFoundError(request.run_id)

        # Flush before rolling back: in buffered mode the branch's memories may
        # still be pending extraction. Materializing them first lets rollback
        # flip them to rolled_back, keeping failed-branch isolation identical to
        # sync mode (otherwise a later flush would resurrect them as completed).
        await self._flush_session(run.session_id)

        all_nodes = await self._repo.list_state_nodes(request.run_id)
        by_id = {n.node_id: n for n in all_nodes}
        target_node = by_id.get(step.state_node_id)
        if target_node is None:
            raise StateTreeError(f"state node not found for rollback step: {step.step_id}")

        rolled_node_ids: list[str] = []
        rolled_step_ids: list[str] = []

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

        # Flip related memories to rolled_back. Match by the set of rolled-back
        # node ids; in the degenerate case where the step's node is missing but
        # its id is known, still target that id so the step's memories are
        # flipped. We never match on a None node id (which would wrongly catch
        # every memory lacking a source node).
        affected_node_ids = set(rolled_node_ids)
        if not affected_node_ids and step.state_node_id:
            affected_node_ids.add(step.state_node_id)
        affected_mem_ids: list[str] = []
        if affected_node_ids:
            for mem in await self._repo.list_memories(run_id=request.run_id):
                if mem.source_state_node_id in affected_node_ids:
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
            await self._repo.add_memory(await self._prepare_embedding(mem))
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
        if request.step_id is not None:
            step = await self._repo.get_step(request.step_id)
            if step is None or step.run_id != run.run_id:
                raise StepNotFoundError(request.step_id)
        # Lazy flush: extraction is deferred in buffered mode, so before reading
        # context we drain this session's buffer so freshly-written events are
        # reflected in the retrieved memory (architecture.md §12.1 "lazy").
        await self._flush_session(run.session_id)
        ws = request.workspace_id or run.workspace_id
        prelude_blocks, pending_logs, prelude_warnings = await self._maybe_fold_history(request, workspace_id=ws)
        if prelude_blocks or pending_logs or prelude_warnings:
            return await self._retrieval.retrieve_with_prelude(
                request,
                workspace_id=ws,
                prelude_blocks=prelude_blocks,
                pending_compaction_logs=pending_logs,
                prelude_warnings=prelude_warnings,
            )
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
    async def _prepare_embedding(self, memory: MemoryItem) -> MemoryItem:
        """Populate memory embeddings through the runtime provider boundary.

        Repository.add_memory(...) still keeps deterministic ensure_embedding(...)
        as the final backfill for direct seeded memories, tests, backfills, and
        any future runtime path that misses this helper. Provider failures must
        never block memory writes; they degrade to the deterministic embedding.
        """
        if memory.embedding_vector is not None or not memory.content:
            return memory
        if self._embedding_provider is not None:
            try:
                vector = list(await self._embedding_provider.embed_text(memory.content))
                if len(vector) != self._embedding_dim:
                    raise ValueError(f"embedding dimension mismatch: expected {self._embedding_dim}, got {len(vector)}")
                if not all(isinstance(v, int | float) and math.isfinite(v) for v in vector):
                    raise ValueError("embedding provider returned non-finite vector")
                memory.embedding_vector = vector
                memory.embedding_status = EmbeddingStatus.embedded
                return memory
            except Exception:  # noqa: BLE001 - embedding provider failure degrades to deterministic fallback
                logger.warning("Embedding provider failed; using deterministic fallback", exc_info=True)
        memory.embedding_vector = stable_embedding(memory.content, self._embedding_dim)
        memory.embedding_status = EmbeddingStatus.embedded
        return memory

    async def _maybe_fold_history(
        self, request: RetrievalRequest, *, workspace_id: str
    ) -> tuple[list[ContextBlock], list[PendingCompactionLog], list[str]]:
        if not self._compaction_enabled or not request.run_id:
            return [], [], []
        try:
            return await asyncio.wait_for(
                self._fold_history_impl(request, workspace_id=workspace_id),
                timeout=max(1, self._compaction_timeout_ms) / 1000,
            )
        except Exception as exc:  # noqa: BLE001 - compaction must degrade to no-fold
            logger.warning("History compaction skipped for run %s", request.run_id, exc_info=True)
            return [], [], [f"history compaction skipped: {exc.__class__.__name__}"]

    async def _fold_history_impl(
        self, request: RetrievalRequest, *, workspace_id: str
    ) -> tuple[list[ContextBlock], list[PendingCompactionLog], list[str]]:
        nodes = await self._repo.list_state_nodes(request.run_id)
        if not nodes:
            return [], [], []
        active_ids = state_tree.active_path_node_ids(nodes)
        active_nodes = {
            node.node_id: node
            for node in nodes
            if node.node_id in active_ids and node.status not in {StateNodeStatus.failed, StateNodeStatus.rolled_back}
        }
        if not active_nodes:
            return [], [], []

        raw_blocks: list[ContextBlock] = []
        source_event_ids: list[str] = []
        source_state_node_ids: list[str] = []
        for event in await self._repo.list_events(request.run_id):
            if event.state_node_id not in active_nodes:
                continue
            if event.redaction_status != "none":
                continue
            if (event.status or "").lower() == "failed":
                continue
            if event.event_type in {EventType.tool_call, EventType.tool_result}:
                risk = writer.detect_risk_flags(event.content)
                if risk.tool_sensitive or risk.destructive_command:
                    continue
            content = event.content or ""
            if not content.strip():
                continue
            raw_blocks.append(
                ContextBlock(
                    type="episodic",
                    content=content,
                    source="active_history",
                    reason="active-path event selected for history compaction",
                    provenance=Provenance(
                        run_id=event.run_id,
                        step_id=event.step_id,
                        event_id=event.event_id,
                        state_node_id=event.state_node_id,
                    ),
                    tokens=_estimate_history_tokens(content),
                )
            )
            source_event_ids.append(event.event_id)
            if event.state_node_id:
                source_state_node_ids.append(event.state_node_id)

        pre_tokens = sum(block.tokens for block in raw_blocks)
        if pre_tokens < self._compaction_history_token_threshold:
            return [], [], []

        retained_facts, source_memory_ids = await self._history_retained_facts(
            workspace_id=workspace_id,
            run_id=request.run_id,
            active_state_node_ids=set(active_nodes),
        )
        source_event_ids = _dedupe([*source_event_ids, *(fact.provenance.event_id for fact in retained_facts if fact.provenance)])
        source_state_node_ids = _dedupe(
            [*source_state_node_ids, *(fact.provenance.state_node_id for fact in retained_facts if fact.provenance)]
        )
        request_payload = SummarizeRequest(
            blocks=raw_blocks,
            must_retain_facts=retained_facts,
            source_memory_ids=source_memory_ids,
            source_event_ids=source_event_ids,
            source_state_node_ids=source_state_node_ids,
            summary_budget_tokens=self._compaction_summary_budget_tokens,
            run_id=request.run_id,
            workspace_id=workspace_id,
            kind=CompactionKind.history_summary,
        )
        try:
            result = await asyncio.wait_for(
                self._summarizer_provider.summarize(request_payload),
                timeout=max(1, self._compaction_timeout_ms) / 1000,
            )
        except Exception as exc:  # noqa: BLE001 - compaction must degrade to no-fold
            logger.warning("History compaction skipped for run %s", request.run_id, exc_info=True)
            return [], [], [f"history compaction skipped: {exc.__class__.__name__}"]

        block = ContextBlock(
            type="history_summary",
            content=result.summary,
            source="context_compaction",
            reason="kind=history_summary",
            provenance=Provenance(run_id=request.run_id),
            tokens=result.post_tokens or _estimate_history_tokens(result.summary),
        )
        pending = PendingCompactionLog(
            kind=CompactionKind.history_summary,
            provider=result.provider,
            pre_tokens=result.pre_tokens or pre_tokens,
            post_tokens=block.tokens,
            dropped_block_count=result.omitted_count,
            compression_ratio=round(block.tokens / max(1, result.pre_tokens or pre_tokens), 6),
            summary_text=result.summary,
            retained_facts=list(result.retained_facts),
            source_memory_ids=list(result.source_memory_ids),
            source_event_ids=list(result.source_event_ids),
            source_state_node_ids=list(result.source_state_node_ids),
            warnings=list(result.warnings),
        )
        return [block], [pending], []

    async def _history_retained_facts(
        self, *, workspace_id: str, run_id: str, active_state_node_ids: set[str]
    ) -> tuple[list[RetainedFact], list[str]]:
        now = _now()
        facts: list[RetainedFact] = []
        memory_ids: list[str] = []
        retrievable = {MemoryStatus.active, MemoryStatus.pinned}
        for mem in await self._repo.list_memories(workspace_id=workspace_id, run_id=run_id):
            if mem.status not in retrievable:
                continue
            if mem.branch_status in {BranchStatus.failed, BranchStatus.rolled_back}:
                continue
            if mem.expires_at is not None and mem.expires_at < now:
                continue
            if mem.sensitivity == Sensitivity.secret or mem.risk_flags.contains_secret:
                continue
            if mem.risk_flags.tool_sensitive or mem.risk_flags.destructive_command:
                continue
            if mem.source_state_node_id not in active_state_node_ids:
                continue
            if not mem.key or mem.value is None:
                continue
            if not mem.key.startswith(("project.", "endpoint.", "profile.", "procedure.")):
                continue
            facts.append(
                RetainedFact(
                    key=mem.key,
                    value=str(mem.value),
                    source_memory_id=mem.memory_id,
                    provenance=Provenance(
                        run_id=mem.source_run_id or mem.run_id,
                        event_id=mem.source_event_id,
                        state_node_id=mem.source_state_node_id,
                    ),
                )
            )
            memory_ids.append(mem.memory_id)
        facts.sort(key=lambda fact: (fact.key, fact.value, fact.source_memory_id or ""))
        return facts, _dedupe(memory_ids)

    async def _extract_user_message(self, event: AgentEvent) -> list[writer.MemoryWriteResult]:
        """Config-gated extraction: LLM provider when injected, else rule writer.

        Both paths return the same ``MemoryWriteResult`` contract, so the
        downstream supersede + resolver persistence is identical. If the LLM
        provider raises (network/timeout/invalid JSON), we degrade to the
        deterministic rule writer so no memory is lost (architecture.md §12).
        """
        if self._extraction_provider is not None:
            try:
                candidates = await self._extraction_provider.extract(event)
                return llm_extractor.build_results(event, candidates)
            except Exception:
                logger.warning(
                    "LLM extraction failed for event %s; falling back to rule writer",
                    event.event_id,
                    exc_info=True,
                )
                return writer.write_from_user_message(event)
        return writer.write_from_user_message(event)

    async def _summarize(self, request: SummarizeRequest, *, deadline_ms: int) -> SummarizeResult:
        """Run the configured summarizer with deterministic fallback.

        C3 deliberately introduces only the provider seam. C4 will call this from
        rolling-history compaction; failures/timeouts must not erase retained
        constraints, so the fallback is always the rule provider.
        """
        try:
            return await asyncio.wait_for(
                self._summarizer_provider.summarize(request),
                timeout=max(1, deadline_ms) / 1000,
            )
        except Exception:
            logger.warning(
                "Context summarization failed for run %s; falling back to rule summarizer",
                request.run_id,
                exc_info=True,
            )
            fallback = await RuleSummarizerProvider().summarize(request)
            warnings = list(fallback.warnings)
            warnings.append("summarizer fallback: deterministic rule provider used")
            return fallback.model_copy(
                update={
                    "provider": CompactionProvider.fallback_rule,
                    "warnings": warnings,
                }
            )

    async def _apply_write_rules(self, event: AgentEvent) -> list[str]:
        created: list[str] = []
        if event.event_type == EventType.message and event.role.value == "user":
            for result in await self._extract_user_message(event):
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
                await self._repo.add_memory(await self._prepare_embedding(mem))
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
            await self._repo.add_memory(await self._prepare_embedding(result.add))
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
                and same_memory_key_identity(mem.key, incoming.key)
                and mem.scope.value == incoming.scope.value
            ):
                out.append(mem)
        return out

    async def _supersede_keys(self, workspace_id: str, keys: list[tuple[str, str]]) -> None:
        if not keys:
            return
        wanted = {(canonical_memory_key(key), scope) for key, scope in keys}
        for mem in await self._repo.list_memories(workspace_id=workspace_id):
            if mem.status != MemoryStatus.active or mem.key is None:
                continue
            if (canonical_memory_key(mem.key), mem.scope.value) in wanted:
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

    async def get_step(self, step_id: str) -> AgentStep | None:
        return await self._repo.get_step(step_id)

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
        eval_cases = await self._repo.list_eval_cases()
        eval_runs = await self._repo.list_eval_runs(workspace_id=workspace_id)
        eval_results = await self._repo.list_eval_results()
        if workspace_id is not None:
            eval_run_ids = {run.eval_run_id for run in eval_runs}
            eval_results = [result for result in eval_results if result.eval_run_id in eval_run_ids]
        observability_summary = await build_observability_summary(self._repo, workspace_id=workspace_id)
        return DashboardTables(
            runs=runs,
            accesses=accesses,
            profile_events=profile_events,
            benchmark_cases=cases,
            benchmark_results=results,
            eval_cases=eval_cases,
            eval_runs=eval_runs,
            eval_results=eval_results,
            observability_summary=observability_summary,
            benchmark_summary=_benchmark_summary_from_records(results),
        )

    async def replay_access(self, access_id: str) -> ReplayRetrievalResult | None:
        """Replay one persisted retrieval access without runtime side effects."""
        access = await self._repo.get_access_log(access_id)
        if access is None:
            return None
        if access.run_id is not None and await self._repo.get_run(access.run_id) is None:
            raise RunNotFoundError(access.run_id)
        return await RetrievalReplayService(self._repo, self._retrieval).replay_access(access_id)

    async def replay_run(self, run_id: str) -> RunReplayResult:
        """Replay every persisted retrieval access for a run without flushing buffers."""
        if await self._repo.get_run(run_id) is None:
            raise RunNotFoundError(run_id)
        return await RetrievalReplayService(self._repo, self._retrieval).replay_run(run_id)

    async def observability_summary(
        self, *, workspace_id: Optional[str] = None, run_id: Optional[str] = None
    ) -> ObservabilitySummary:
        """Return deterministic quality/safety counters from persisted retrieval logs."""
        return await build_observability_summary(self._repo, workspace_id=workspace_id, run_id=run_id)

    async def write_observability_report(
        self, request: ObservabilityReportRequest
    ) -> ObservabilityReportResult:
        """Generate static JSON/Markdown/HTML observability reports without side effects."""
        return await write_observability_report(self._repo, self._retrieval, request)

    async def export_trace_bundle(self, *, run_id: str, redacted: bool = True) -> TraceBundle:
        """Export a read-only trace bundle for one run.

        Bundles are redacted by default and are validation/debug artifacts only;
        they are intentionally not importable into production repositories.
        """
        return await export_run_bundle(self._repo, run_id, redacted=redacted)

    async def export_access_bundle(self, access_id: str, *, redacted: bool = True) -> TraceBundle:
        """Export a redacted trace bundle centered on one access log."""
        return await export_access_bundle(self._repo, access_id, redacted=redacted)

    def validate_trace_bundle(self, bundle: TraceBundle | dict) -> TraceBundleValidation:
        """Validate trace bundle schema/counts without writing repository data."""
        return validate_bundle_schema(bundle)

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
        from app.retrieval.gate import GateOutcome
        from app.retrieval.negative_evidence import build_negative_evidence, safe_observability_content
        from app.retrieval.packer import pack_context

        access = await self._repo.get_access_log(access_id)
        if access is None:
            return None
        gate_logs = await self._repo.list_gate_logs(access_id)

        views: list[GateDecisionView] = []
        accepted_mems: list[MemoryItem] = []
        outcomes = []
        memories_by_id: dict[str, MemoryItem] = {}
        missing_negative: list[str] = []
        for g in gate_logs:
            mem = await self._repo.get_memory(g.memory_id)
            content = safe_observability_content(mem, reject_reason=g.reject_reason)
            if mem is None and (
                g.decision == GateDecisionType.degrade
                or g.reject_reason in {"failed_branch_sanitized", "rolled_back_sanitized"}
            ):
                missing_negative.append(g.memory_id)
            if mem:
                memories_by_id[mem.memory_id] = mem
                outcomes.append(
                    GateOutcome(
                        memory=mem,
                        layer=g.layer,
                        decision=g.decision,
                        reject_reason=g.reject_reason,
                        relevance_score=g.relevance_score,
                        state_match_score=g.state_match_score,
                        freshness_score=g.freshness_score,
                        trust_score=g.trust_score,
                        risk_score=g.risk_score,
                        final_score=g.final_score,
                    )
                )
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
            if g.decision in (GateDecisionType.accept, GateDecisionType.warn) and mem:
                accepted_mems.append(mem)

        score_by_id = {v.memory_id: v.final_score for v in views}
        accepted_mems.sort(key=lambda m: (-score_by_id.get(m.memory_id, 0.0), m.memory_id))
        negative_evidence = build_negative_evidence(outcomes, memories_by_id, max_blocks=3)
        active_node = None
        active_path: list = []
        if access.run_id:
            active_node, _, active_path = await self._retrieval._load_active_state(access.run_id)
        pack_result = pack_context(
            active_node=active_node,
            accepted=accepted_mems,
            token_budget=access.token_budget or 512,
            active_path=active_path,
            negative_evidence=negative_evidence,
            compaction_notice_reserve_tokens=self._retrieval._compaction_notice_reserve_tokens,
        )
        blocks = pack_result.blocks
        profile = self._retrieval._profile_summary(access)
        warnings = [
            f"negative evidence source memory {memory_id} is missing; raw failed-attempt text was not reconstructed"
            for memory_id in missing_negative
        ]
        # candidates: the retrieved candidate pool ranked by relevance (the
        # gate's input view). gate_decisions: the per-candidate admission outcome
        # in gate-processing order (the gate's output view). Both derive from the
        # same gate logs (one per candidate) but expose distinct orderings/intent.
        candidates = sorted(views, key=lambda v: (-v.relevance_score, v.memory_id))
        return AccessInspection(
            access_id=access.access_id,
            query=access.query,
            task_intent=access.task_intent,
            retrieval_strategy=access.retrieval_strategy,
            candidates=candidates,
            gate_decisions=views,
            context_blocks=blocks,
            profile=profile,
            warnings=warnings,
            policy_version=access.policy_version,
            policy_hash=access.policy_hash,
            policy_snapshot=access.policy_snapshot,
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
            "stale_memory_injection_rate": _avg([
                float(r.get("stale_memory_injection", 0)) for r in rows if r.get("stale_memory_injection_present")
            ]),
            "cross_workspace_leakage_rate": _avg([
                float(r.get("cross_workspace_leakage", 0)) for r in rows if r.get("cross_workspace_leakage_present")
            ]),
            "tool_sensitive_blocked_rate": _avg([
                float(r.get("tool_sensitive_blocked", 0)) for r in rows if r.get("tool_sensitive_present")
            ]),
            "procedural_reuse_hit_rate": _avg([
                float(r.get("procedural_reuse_hit", 0)) for r in rows if r.get("procedural_reuse_present")
            ]),
            "superseded_injection_rate": _avg([
                float(r.get("superseded_injection", 0)) for r in rows if r.get("superseded_injection_present")
            ]),
            "constraint_retention_hit_rate": _avg([
                float(r.get("constraint_retention_hit", 0)) for r in rows if r.get("constraint_retention_hit_present")
            ]),
            "unsafe_compaction_leakage_rate": _avg([
                float(r.get("unsafe_compaction_leakage", 0)) for r in rows if r.get("unsafe_compaction_leakage_present")
            ]),
            "compaction_trigger_rate": _avg([
                float(r.get("compaction_triggered", 0)) for r in rows if r.get("compaction_triggered_present")
            ]),
            "avg_compression_ratio": _avg([
                float(r.get("compression_ratio", 0)) for r in rows if r.get("compression_ratio_present")
            ]),
            "positive_contamination_rate": _avg([
                float(r.get("positive_contamination", 0)) for r in rows if r.get("positive_contamination_present")
            ]),
            "negative_lesson_retained_rate": _avg([
                float(r.get("negative_lesson_retained", 0)) for r in rows if r.get("negative_lesson_retained_present")
            ]),
            "correct_action_rate": _avg([
                float(r.get("correct_action", 0)) for r in rows if r.get("correct_action_present")
            ]),
            "unsafe_negative_leakage_rate": _avg([
                float(r.get("unsafe_negative_leakage", 0)) for r in rows if r.get("unsafe_negative_leakage_present")
            ]),
            "sanitized_notice_rate": _avg([
                float(r.get("sanitized_notice_present", 0)) for r in rows if r.get("sanitized_notice_present_present")
            ]),
            "reflection_retention_hit_rate": _avg([
                float(r.get("reflection_retention_hit", 0)) for r in rows if r.get("reflection_retention_hit_present")
            ]),
            "avg_retrieval_latency_ms": _avg([float(r.get("retrieval_latency_ms", 0)) for r in rows]),
            "avg_gate_latency_ms": _avg([float(r.get("gate_latency_ms", 0)) for r in rows]),
            "avg_memory_token_overhead": _avg([float(r.get("actual_tokens", 0)) for r in rows]),
        }
    return summary


def _dedupe(values) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


__all__ = ["MemoryRuntime", "RunNotFoundError", "StepNotFoundError"]
