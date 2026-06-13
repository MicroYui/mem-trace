"""P1 benchmark runner tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import app.benchmark.runner as benchmark_runner
from app.benchmark.cases import ALL_STRATEGIES, BenchmarkCase, SeedResult
from app.benchmark.evaluator import CaseMetrics, contaminated, decide_action, evaluate_case
from app.benchmark.runner import (
    _acceptance,
    _restore_workspace_memories,
    _run_case,
    _snapshot_workspace_memories,
    _summarize,
    run_benchmark,
)
from app.config import get_settings
from app.providers.base import ProviderKind
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    FinishStepRequest,
    CompactionKind,
    CompactionProvider,
    ContextBlock,
    ContextCompactionLog,
    MemoryItem,
    MemoryType,
    MemoryContext,
    RetainedFact,
    StartRunRequest,
    StartStepRequest,
    RetrievalStrategy,
    StepStatus,
)
from app.runtime.repository import InMemoryRepository


async def test_run_benchmark_writes_markdown_and_json_reports(tmp_path):
    report = await run_benchmark(output_dir=tmp_path)

    assert len(report["cases"]) == 13
    assert {c["case_id"] for c in report["cases"]} == {
        "case_1_project_preference",
        "case_2_failed_branch",
        "case_3_workspace_isolation",
        "case_4_tool_safety",
        "case_5_explicit_correction",
        "case_6_completed_run_reuse",
        "case_7_stale_rejection",
        "case_8_no_memory_baseline",
        "case_9_over_budget_compaction",
        "case_10_avoid_repeating_failed_attempt",
        "case_11_sanitized_failed_destructive_attempt",
        "case_12_reflection_retention",
        "case_13_compaction_retains_negative_lesson",
    }
    assert len(report["results"]) == 78  # 13 cases x 6 strategies

    json_path = tmp_path / "benchmark_results.json"
    md_path = tmp_path / "benchmark_report.md"
    assert json_path.exists()
    assert md_path.exists()

    saved = json.loads(json_path.read_text())
    assert saved["summary"]["variant_2"]["cross_workspace_leakage_rate"] == 0
    assert saved["summary"]["variant_2"]["tool_sensitive_blocked_rate"] == 1
    assert saved["summary"]["variant_2"]["compaction_trigger_rate"] > 0
    assert saved["summary"]["variant_2"]["constraint_retention_hit_rate"] == 1
    assert saved["summary"]["variant_2"]["unsafe_compaction_leakage_rate"] == 0
    assert saved["summary"]["variant_2"]["avg_compression_ratio"] > 0
    assert saved["summary"]["variant_2"]["positive_contamination_rate"] == 0
    assert saved["summary"]["variant_2"]["negative_lesson_retained_rate"] == 1
    assert saved["summary"]["variant_2"]["correct_action_rate"] == 1
    assert saved["summary"]["variant_2"]["unsafe_negative_leakage_rate"] == 0
    assert saved["summary"]["variant_2"]["sanitized_notice_rate"] == 1
    assert saved["summary"]["variant_2"]["compaction_negative_lesson_retained_rate"] == 1
    assert saved["summary"]["variant_2"]["compaction_retained_negative_unsafe_leakage_rate"] == 0
    assert (
        saved["summary"]["variant_2"]["failed_branch_contamination_rate"]
        < saved["summary"]["baseline_1"]["failed_branch_contamination_rate"]
    )
    md = md_path.read_text()
    assert "failed_branch_contamination_rate" in md
    assert "compaction_negative_lesson_retained_rate" in md
    assert "compaction_retained_negative_unsafe_leakage_rate" in md
    assert "retained_negative_evidence_count" in md


async def test_run_benchmark_meets_mvp_acceptance(tmp_path):
    report = await run_benchmark(output_dir=tmp_path)
    acc = report["acceptance"]
    assert acc["passed"] is True
    assert acc["checks"]["variant_2_contamination_below_baseline_1"] is True
    assert acc["checks"]["variant_2_zero_cross_workspace_leakage"] is True
    assert acc["checks"]["variant_2_blocks_tool_sensitive"] is True
    assert acc["checks"]["variant_2_reuses_procedural_memory"] is True
    assert acc["checks"]["variant_2_excludes_superseded_memory"] is True
    assert acc["checks"]["variant_2_excludes_stale_memory"] is True
    assert acc["checks"]["variant_2_succeeds_where_no_memory_baseline_fails"] is True
    assert acc["checks"]["variant_2_retains_constraints_under_compaction"] is True
    assert acc["checks"]["variant_2_learns_from_failure_without_repeating"] is True
    assert acc["checks"]["variant_2_sanitizes_destructive_failure_without_leakage"] is True
    assert acc["checks"]["variant_2_retains_negative_lesson_under_compaction"] is True


async def test_acceptance_includes_reflection_and_long_context_checks(tmp_path):
    report = await run_benchmark(output_dir=tmp_path)
    acc = report["acceptance"]
    assert acc["checks"]["variant_3_retains_high_value_memory_under_budget"] is True
    assert acc["checks"]["long_context_shows_token_bloat"] is True
    assert acc["passed"] is True
    assert report["summary"]["variant_3"]["reflection_retention_hit_rate"] == 1
    assert report["summary"]["variant_2"]["reflection_retention_hit_rate"] == 0
    overhead = {s: report["summary"][s]["avg_memory_token_overhead"] for s in report["strategies"]}
    assert overhead["long_context"] == max(overhead.values())


async def test_compaction_retains_negative_lesson_case_and_acceptance(tmp_path):
    report = await run_benchmark(output_dir=tmp_path)

    assert len(report["cases"]) == 13
    assert {c["case_id"] for c in report["cases"]} >= {"case_13_compaction_retains_negative_lesson"}
    assert len(report["results"]) == 78  # 13 cases x 6 strategies
    assert report["acceptance"]["checks"]["variant_2_retains_negative_lesson_under_compaction"] is True

    row = next(
        r
        for r in report["results"]
        if r["case_id"] == "case_13_compaction_retains_negative_lesson"
        and r["strategy"] == "variant_2"
    )
    assert row["positive_contamination"] == 0
    assert row["retained_negative_evidence_count"] > 0
    assert row["unsafe_negative_leakage"] == 0
    # This success comes from existing positive/project context. Retained
    # negative evidence is compaction metadata only and must not be required as
    # prompt input for the deterministic action to remain correct.
    assert row["task_success"] == 1


def test_compaction_retains_negative_lesson_acceptance_requires_present_case_row():
    summary = {
        "variant_2": {
            "compaction_negative_lesson_retained_rate": 1.0,
            "compaction_retained_negative_unsafe_leakage_rate": 0.0,
        }
    }

    acceptance = _acceptance(summary, results=[])

    assert acceptance["checks"]["variant_2_retains_negative_lesson_under_compaction"] is False


def test_compaction_retains_negative_lesson_acceptance_requires_case_specific_scoring_flags():
    summary = {
        "variant_2": {
            "compaction_negative_lesson_retained_rate": 1.0,
            "compaction_retained_negative_unsafe_leakage_rate": 0.0,
        }
    }
    row = CaseMetrics(
        case_id="case_13_compaction_retains_negative_lesson",
        strategy="variant_2",
        task_success=1,
        positive_contamination=0,
        retained_negative_evidence_count=1,
        retained_negative_evidence_count_present=1,
        compaction_negative_lesson_retained=1,
        compaction_negative_lesson_retained_present=1,
        compaction_retained_negative_unsafe_leakage=0,
        compaction_retained_negative_unsafe_leakage_present=1,
    )

    acceptance = _acceptance(summary, results=[row])

    assert acceptance["checks"]["variant_2_retains_negative_lesson_under_compaction"] is False


def test_long_context_token_bloat_acceptance_requires_variant_2_comparator():
    acceptance = _acceptance(
        {"long_context": {"avg_memory_token_overhead": 100.0}},
        results=[],
    )

    assert acceptance["checks"]["long_context_shows_token_bloat"] is False


def test_reflection_acceptance_requires_case_12_present_rows():
    summary = {
        "variant_2": {"reflection_retention_hit_rate": 0.0},
        "variant_3": {"reflection_retention_hit_rate": 1.0},
    }

    acceptance = _acceptance(summary, results=[])

    assert acceptance["checks"]["variant_3_retains_high_value_memory_under_budget"] is False


def test_all_strategies_uses_six_strategy_benchmark_order():
    assert [strategy.value for strategy in ALL_STRATEGIES] == [
        "baseline_0",
        "long_context",
        "baseline_1",
        "variant_1",
        "variant_2",
        "variant_3",
    ]


async def test_run_benchmark_persists_cases_and_results(tmp_path):
    repo = InMemoryRepository()

    await run_benchmark(output_dir=tmp_path, repo=repo)

    cases = await repo.list_benchmark_cases()
    results = await repo.list_benchmark_results()
    assert len(cases) == 13
    assert len(results) == 78
    assert {r.strategy for r in results} == {
        "baseline_0",
        "long_context",
        "baseline_1",
        "variant_1",
        "variant_2",
        "variant_3",
    }
    assert any(
        r.case_id == "case_4_tool_safety" and r.strategy == "variant_2"
        and r.metrics["tool_sensitive_blocked"] == 1
        for r in results
    )
    assert any(
        r.case_id == "case_9_over_budget_compaction" and r.strategy == "variant_2"
        and r.metrics["constraint_retention_hit"] == 1
        and r.metrics["unsafe_compaction_leakage"] == 0
        for r in results
    )
    assert any(
        r.case_id == "case_10_avoid_repeating_failed_attempt" and r.strategy == "variant_2"
        and r.metrics["positive_contamination"] == 0
        and r.metrics["negative_lesson_retained"] == 1
        and r.metrics["correct_action"] == 1
        for r in results
    )
    assert any(
        r.case_id == "case_10_avoid_repeating_failed_attempt" and r.strategy == "variant_1"
        and r.metrics["negative_lesson_retained"] == 0
        for r in results
    )
    assert any(
        r.case_id == "case_11_sanitized_failed_destructive_attempt" and r.strategy == "variant_2"
        and r.metrics["unsafe_negative_leakage"] == 0
        and r.metrics["sanitized_notice_present"] == 1
        for r in results
    )
    assert any(
        r.case_id == "case_12_reflection_retention" and r.strategy == "variant_3"
        and r.metrics["reflection_retention_hit"] == 1
        for r in results
    )
    assert any(
        r.case_id == "case_13_compaction_retains_negative_lesson" and r.strategy == "variant_2"
        and r.metrics["positive_contamination"] == 0
        and r.metrics["retained_negative_evidence_count"] > 0
        and r.metrics["unsafe_negative_leakage"] == 0
        and r.metrics["task_success"] == 1
        for r in results
    )


async def test_run_benchmark_persists_eval_records(tmp_path):
    repo = InMemoryRepository()

    await run_benchmark(output_dir=tmp_path, repo=repo)

    eval_cases = await repo.list_eval_cases()
    eval_runs = await repo.list_eval_runs()
    assert len(eval_cases) == 13
    assert len(eval_runs) == 1
    eval_run = eval_runs[0]
    assert eval_run.name == "deterministic_benchmark"
    assert eval_run.status == "completed"
    assert eval_run.config["strategies"] == [
        "baseline_0",
        "long_context",
        "baseline_1",
        "variant_1",
        "variant_2",
        "variant_3",
    ]
    assert eval_run.config["acceptance"]["passed"] is True
    assert eval_run.finished_at is not None

    results = await repo.list_eval_results(eval_run_id=eval_run.eval_run_id)
    assert len(results) == 78  # 13 cases x 6 strategies
    assert {r.eval_case_id for r in eval_cases} >= {
        "case_12_reflection_retention",
        "case_13_compaction_retains_negative_lesson",
    }
    assert all(r.passed is True for r in results)
    assert any(
        r.eval_case_id == "case_12_reflection_retention"
        and str(r.strategy) in ("RetrievalStrategy.variant_3", "variant_3")
        and r.metrics["reflection_retention_hit"] == 1
        for r in results
    )


async def test_run_benchmark_eval_persistence_is_repeatable(tmp_path):
    repo = InMemoryRepository()

    first = await run_benchmark(output_dir=tmp_path / "a", repo=repo)
    second = await run_benchmark(output_dir=tmp_path / "b", repo=repo)

    # case_ids are stable -> upserted; each run appends a fresh run + its results.
    assert first["acceptance"]["passed"] is True
    assert second["acceptance"]["passed"] is True
    deterministic_first = {
        strategy: {
            key: value for key, value in fields.items()
            if key not in {"avg_retrieval_latency_ms", "avg_gate_latency_ms"}
        }
        for strategy, fields in first["summary"].items()
    }
    deterministic_second = {
        strategy: {
            key: value for key, value in fields.items()
            if key not in {"avg_retrieval_latency_ms", "avg_gate_latency_ms"}
        }
        for strategy, fields in second["summary"].items()
    }
    assert deterministic_first == deterministic_second
    assert len(await repo.list_eval_cases()) == 13
    assert len(await repo.list_eval_runs()) == 2
    assert len(await repo.list_eval_results()) == 156  # 2 runs x 78


async def test_workspace_memory_snapshot_restores_all_mutable_retrieval_fields():
    repo = InMemoryRepository()
    mem = await repo.add_memory(MemoryItem(
        workspace_id="ws_snap",
        memory_type=MemoryType.episodic,
        content="snapshot target",
        access_count=1,
        trust_score=0.7,
        freshness_score=0.8,
    ))
    snapshot = await _snapshot_workspace_memories(repo, "ws_snap")

    stored = (await repo.list_memories(workspace_id="ws_snap"))[0]
    stored.access_count = 9
    stored.trust_score = 0.1
    stored.freshness_score = 0.2
    stored.last_accessed_at = datetime.now(timezone.utc)
    await repo.update_memory(stored)

    await _restore_workspace_memories(repo, "ws_snap", snapshot)
    restored = (await repo.list_memories(workspace_id="ws_snap"))[0]
    assert restored.memory_id == mem.memory_id
    assert restored.access_count == 1
    assert restored.trust_score == 0.7
    assert restored.freshness_score == 0.8
    assert restored.last_accessed_at is None


async def test_workspace_memory_restore_rejects_new_memories_created_after_snapshot():
    repo = InMemoryRepository()
    await repo.add_memory(MemoryItem(workspace_id="ws_snap", memory_type=MemoryType.episodic, content="original"))
    snapshot = await _snapshot_workspace_memories(repo, "ws_snap")
    await repo.add_memory(MemoryItem(workspace_id="ws_snap", memory_type=MemoryType.episodic, content="polluting new memory"))

    with pytest.raises(RuntimeError, match="created during benchmark retrieval"):
        await _restore_workspace_memories(repo, "ws_snap", snapshot)


async def test_workspace_memory_restore_rejects_snapshot_memories_missing_from_workspace():
    repo = InMemoryRepository()
    mem = await repo.add_memory(MemoryItem(workspace_id="ws_snap", memory_type=MemoryType.episodic, content="original"))
    snapshot = await _snapshot_workspace_memories(repo, "ws_snap")
    moved = mem.model_copy(update={"workspace_id": "ws_other"})
    await repo.update_memory(moved)

    with pytest.raises(RuntimeError, match="missing from benchmark workspace snapshot"):
        await _restore_workspace_memories(repo, "ws_snap", snapshot)


async def test_run_case_restores_access_counts_before_each_strategy(monkeypatch):
    repo = InMemoryRepository()
    observed_counts: list[int] = []

    async def seed(rt: MemoryRuntime, ws: str) -> SeedResult:
        run = await rt.start_run(StartRunRequest(session_id="s", task="snapshot fairness", workspace_id=ws))
        s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="seed"))
        await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id, status=StepStatus.completed))
        await repo.add_memory(MemoryItem(
            workspace_id=ws,
            run_id=run.run_id,
            memory_type=MemoryType.episodic,
            content="snapshot target memory",
            access_count=5,
        ))
        s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="retrieve"))
        return SeedResult(run.run_id, s2.step_id, "snapshot target", ws)

    original_retrieve = MemoryRuntime.retrieve_context

    async def recording_retrieve(self: MemoryRuntime, request):
        memories = await repo.list_memories(workspace_id="ws_case")
        target = next(mem for mem in memories if mem.content == "snapshot target memory")
        observed_counts.append(target.access_count)
        return await original_retrieve(self, request)

    monkeypatch.setattr(benchmark_runner, "ALL_STRATEGIES", [RetrievalStrategy.baseline_1, RetrievalStrategy.baseline_1])
    monkeypatch.setattr(MemoryRuntime, "retrieve_context", recording_retrieve)

    await _run_case(BenchmarkCase("case_access_restore", "Access restore", "Fairness isolation", seed), "ws_case", repo=repo)

    assert observed_counts == [5, 5]


async def test_run_case_forces_explicit_deterministic_provider_registry(monkeypatch):
    repo = InMemoryRepository()
    captured_snapshots: list[dict] = []
    deterministic_registry = benchmark_runner.deterministic_provider_registry()
    registry_calls = 0

    def deterministic_registry_spy():
        nonlocal registry_calls
        registry_calls += 1
        return deterministic_registry

    async def seed(rt: MemoryRuntime, ws: str) -> SeedResult:
        run = await rt.start_run(StartRunRequest(session_id="s", task="provider isolation", workspace_id=ws))
        step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="retrieve"))
        await repo.add_memory(MemoryItem(workspace_id=ws, memory_type=MemoryType.episodic, content="provider marker"))
        return SeedResult(run.run_id, step.step_id, "provider marker", ws)

    original_init = MemoryRuntime.__init__

    def recording_init(self, *args, **kwargs):
        registry = kwargs.get("provider_registry")
        assert registry is not None
        captured_snapshots.append(registry.snapshot())
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(benchmark_runner, "ALL_STRATEGIES", [RetrievalStrategy.variant_2])
    monkeypatch.setattr(benchmark_runner, "deterministic_provider_registry", deterministic_registry_spy)
    monkeypatch.setattr(MemoryRuntime, "__init__", recording_init)

    await _run_case(BenchmarkCase("case_provider_isolation", "Provider isolation", "Provider isolation", seed), "ws_provider", repo=repo)

    assert registry_calls == 1
    assert captured_snapshots
    snapshot = captured_snapshots[0]
    assert snapshot[ProviderKind.embedding.value]["provider_id"] == "embedding.deterministic_hash.v1"
    assert snapshot[ProviderKind.embedding.value]["deterministic"] is True
    assert snapshot[ProviderKind.summarizer.value]["provider_id"] == "summarizer.rule.v1"
    assert snapshot[ProviderKind.judge.value]["provider_id"] == "judge.noop.v1"
    assert ProviderKind.extraction.value not in snapshot


async def test_benchmark_policy_snapshot_records_deterministic_providers_under_real_env(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("MEMTRACE_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("MEMTRACE_EMBEDDING_API_KEY", "sk-test-should-not-render")
    monkeypatch.setenv("MEMTRACE_LLM_SUMMARIZER_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_LLM_API_KEY", "sk-test-should-not-render")

    repo = InMemoryRepository()

    async def seed(rt: MemoryRuntime, ws: str) -> SeedResult:
        run = await rt.start_run(StartRunRequest(session_id="s", task="provider policy", workspace_id=ws))
        step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="retrieve"))
        await repo.add_memory(MemoryItem(workspace_id=ws, memory_type=MemoryType.episodic, content="provider marker"))
        return SeedResult(run.run_id, step.step_id, "provider marker", ws)

    monkeypatch.setattr(benchmark_runner, "ALL_STRATEGIES", [RetrievalStrategy.variant_2])

    try:
        await _run_case(BenchmarkCase("case_provider_policy", "Provider policy", "Provider policy", seed), "ws_provider", repo=repo)
    finally:
        get_settings.cache_clear()

    access_logs = await repo.list_access_logs(workspace_id="ws_provider")
    assert len(access_logs) == 1
    providers = access_logs[0].policy_snapshot["providers"]
    assert providers["embedding"]["provider_id"] == "embedding.deterministic_hash.v1"
    assert providers["embedding"]["deterministic"] is True
    assert providers["summarizer"]["provider_id"] == "summarizer.rule.v1"
    assert providers["summarizer"]["deterministic"] is True
    assert "judge" not in providers
    assert "sk-test-should-not-render" not in json.dumps(access_logs[0].policy_snapshot, sort_keys=True)


def test_evaluator_keeps_negative_evidence_out_of_positive_contamination_and_action():
    ctx = MemoryContext(
        access_id="acc_failure_learning",
        context_blocks=[
            ContextBlock(type="project_memory", content="This project uses Bun."),
            ContextBlock(
                type="avoided_attempts",
                source="negative_evidence",
                content="AVOIDED — a previous attempt failed; do NOT re-execute: npm test failed.",
            ),
        ],
        profile={},
        warnings=[],
    )

    assert contaminated(ctx) is False
    assert decide_action(ctx) == "bun test"

    metrics = evaluate_case(
        case_id="case_10_avoid_repeating_failed_attempt",
        strategy=RetrievalStrategy.variant_2,
        ctx=ctx,
        access=None,
        profile_events=[],
        negative_lesson_markers=["npm"],
        failure_learning_case=True,
    )

    assert metrics.positive_contamination == 0
    assert metrics.negative_lesson_retained == 1
    assert metrics.correct_action == 1


def test_evaluator_scores_sanitized_negative_notice_without_raw_marker_leakage():
    ctx = MemoryContext(
        access_id="acc_sanitized_failure",
        context_blocks=[
            ContextBlock(
                type="avoided_attempts",
                source="negative_evidence",
                content="A previous failed attempt involved a destructive operation and has been redacted. Do not repeat destructive operations of this kind.",
            ),
        ],
        profile={},
        warnings=[],
    )

    metrics = evaluate_case(
        case_id="case_11_sanitized_failed_destructive_attempt",
        strategy=RetrievalStrategy.variant_2,
        ctx=ctx,
        access=None,
        profile_events=[],
        unsafe_negative_markers=["rm -rf", "--force", "git push --force"],
        sanitized_failure_case=True,
    )

    assert metrics.unsafe_negative_leakage == 0
    assert metrics.sanitized_notice_present == 1


def test_evaluator_scores_reflection_retention_hit_from_marker_presence():
    ctx_hit = MemoryContext(
        access_id="acc_ref_hit",
        context_blocks=[ContextBlock(type="episodic", content="users service RETAIN-CRITICAL-FACT")],
        profile={},
        warnings=[],
    )
    ctx_miss = MemoryContext(
        access_id="acc_ref_miss",
        context_blocks=[ContextBlock(type="episodic", content="users service reference note")],
        profile={},
        warnings=[],
    )

    hit = evaluate_case(
        case_id="case_12_reflection_retention",
        strategy=RetrievalStrategy.variant_3,
        ctx=ctx_hit,
        access=None,
        profile_events=[],
        reflection_marker="retain-critical-fact",
        reflection_case=True,
    )
    miss = evaluate_case(
        case_id="case_12_reflection_retention",
        strategy=RetrievalStrategy.variant_2,
        ctx=ctx_miss,
        access=None,
        profile_events=[],
        reflection_marker="retain-critical-fact",
        reflection_case=True,
    )

    assert hit.reflection_retention_hit_present == 1
    assert hit.reflection_retention_hit == 1
    assert miss.reflection_retention_hit == 0


def test_compaction_retention_metric_uses_durable_log_facts_when_context_is_truncated():
    ctx = MemoryContext(
        access_id="acc_eval",
        context_blocks=[ContextBlock(type="project_memory", content="This project uses Bun.")],
        warnings=["context budget exceeded: omitted 2 blocks"],
        profile={},
    )
    logs = [
        ContextCompactionLog(
            access_id="acc_eval",
            workspace_id="ws_eval",
            kind=CompactionKind.budget_notice,
            provider=CompactionProvider.rule,
            pre_tokens=40,
            post_tokens=10,
            dropped_block_count=2,
            compression_ratio=0.25,
            retained_facts=[
                RetainedFact(key="project.database", value="postgres"),
                RetainedFact(key="endpoint.current", value="/v2/users"),
            ],
        )
    ]

    metrics = evaluate_case(
        case_id="case_9_over_budget_compaction",
        strategy=RetrievalStrategy.variant_2,
        ctx=ctx,
        access=None,
        profile_events=[],
        compaction_positive_constraints=[
            "project.runtime=bun",
            "project.database=postgres",
            "endpoint.current=/v2/users",
        ],
        unsafe_compaction_markers=["secret_token"],
        compaction_logs=logs,
    )

    assert metrics.constraint_retention_hit == 1
    assert metrics.compaction_triggered == 1
    assert metrics.compression_ratio == 0.25


def test_compaction_acceptance_requires_triggered_compaction():
    summary = {
        "baseline_0": {"task_success_rate": 0.0},
        "baseline_1": {"failed_branch_contamination_rate": 1.0, "stale_memory_injection_rate": 1.0},
        "variant_2": {
            "failed_branch_contamination_rate": 0.0,
            "cross_workspace_leakage_rate": 0.0,
            "tool_sensitive_blocked_rate": 1.0,
            "procedural_reuse_hit_rate": 1.0,
            "superseded_injection_rate": 0.0,
            "stale_memory_injection_rate": 0.0,
            "task_success_rate": 1.0,
            "compaction_trigger_rate": 0.0,
            "constraint_retention_hit_rate": 1.0,
            "unsafe_compaction_leakage_rate": 0.0,
        },
    }

    acceptance = _acceptance(summary, results=[])

    assert acceptance["checks"]["variant_2_retains_constraints_under_compaction"] is False
    assert acceptance["passed"] is False


def test_acceptance_requires_present_rows_for_failure_learning_checks():
    summary = {
        "baseline_1": {"failed_branch_contamination_rate": 1.0, "stale_memory_injection_rate": 1.0},
        "variant_2": {
            "failed_branch_contamination_rate": 0.0,
            "cross_workspace_leakage_rate": 0.0,
            "tool_sensitive_blocked_rate": 1.0,
            "procedural_reuse_hit_rate": 1.0,
            "superseded_injection_rate": 0.0,
            "stale_memory_injection_rate": 0.0,
            "compaction_trigger_rate": 1.0,
            "constraint_retention_hit_rate": 1.0,
            "unsafe_compaction_leakage_rate": 0.0,
            # These rates look passing, but without case_10/case_11 rows they
            # must not satisfy acceptance.
            "positive_contamination_rate": 0.0,
            "negative_lesson_retained_rate": 1.0,
            "correct_action_rate": 1.0,
            "unsafe_negative_leakage_rate": 0.0,
            "sanitized_notice_rate": 1.0,
        },
    }
    results = [
        CaseMetrics(case_id="case_8_no_memory_baseline", strategy="baseline_0", task_success=0),
        CaseMetrics(case_id="case_8_no_memory_baseline", strategy="variant_2", task_success=1),
        CaseMetrics(case_id="case_3_workspace_isolation", strategy="variant_2", cross_workspace_leakage=0, cross_workspace_leakage_present=1),
        CaseMetrics(case_id="case_4_tool_safety", strategy="variant_2", tool_sensitive_blocked=1, tool_sensitive_present=1),
        CaseMetrics(case_id="case_6_completed_run_reuse", strategy="variant_2", procedural_reuse_hit=1, procedural_reuse_present=1),
        CaseMetrics(case_id="case_5_explicit_correction", strategy="variant_2", superseded_injection=0, superseded_injection_present=1),
        CaseMetrics(case_id="case_7_stale_rejection", strategy="baseline_1", stale_memory_injection=1, stale_memory_injection_present=1),
        CaseMetrics(case_id="case_7_stale_rejection", strategy="variant_2", stale_memory_injection=0, stale_memory_injection_present=1),
        CaseMetrics(case_id="case_9_over_budget_compaction", strategy="variant_2", compaction_triggered=1, compaction_triggered_present=1, constraint_retention_hit=1, constraint_retention_hit_present=1, unsafe_compaction_leakage=0, unsafe_compaction_leakage_present=1),
    ]

    acceptance = _acceptance(summary, results=results)

    assert acceptance["checks"]["variant_2_learns_from_failure_without_repeating"] is False
    assert acceptance["checks"]["variant_2_sanitizes_destructive_failure_without_leakage"] is False
    assert acceptance["passed"] is False


def test_acceptance_requires_present_rows_for_zero_leakage_checks():
    summary = {
        "baseline_1": {"failed_branch_contamination_rate": 1.0, "stale_memory_injection_rate": 1.0},
        "variant_2": {
            "failed_branch_contamination_rate": 0.0,
            "cross_workspace_leakage_rate": 0.0,
            "tool_sensitive_blocked_rate": 1.0,
            "procedural_reuse_hit_rate": 1.0,
            "superseded_injection_rate": 0.0,
            "stale_memory_injection_rate": 0.0,
            "compaction_trigger_rate": 1.0,
            "constraint_retention_hit_rate": 1.0,
            "unsafe_compaction_leakage_rate": 0.0,
            "positive_contamination_rate": 0.0,
            "negative_lesson_retained_rate": 1.0,
            "correct_action_rate": 1.0,
            "unsafe_negative_leakage_rate": 0.0,
            "sanitized_notice_rate": 1.0,
        },
    }
    results = [
        CaseMetrics(case_id="case_8_no_memory_baseline", strategy="baseline_0", task_success=0),
        CaseMetrics(case_id="case_8_no_memory_baseline", strategy="variant_2", task_success=1),
        # Deliberately omit case_3 cross_workspace_leakage_present row while
        # summary says the leakage rate is zero.
        CaseMetrics(case_id="case_4_tool_safety", strategy="variant_2", tool_sensitive_blocked=1, tool_sensitive_present=1),
        CaseMetrics(case_id="case_6_completed_run_reuse", strategy="variant_2", procedural_reuse_hit=1, procedural_reuse_present=1),
        CaseMetrics(case_id="case_5_explicit_correction", strategy="variant_2", superseded_injection=0, superseded_injection_present=1),
        CaseMetrics(case_id="case_7_stale_rejection", strategy="baseline_1", stale_memory_injection=1, stale_memory_injection_present=1),
        CaseMetrics(case_id="case_7_stale_rejection", strategy="variant_2", stale_memory_injection=0, stale_memory_injection_present=1),
        CaseMetrics(case_id="case_9_over_budget_compaction", strategy="variant_2", compaction_triggered=1, compaction_triggered_present=1, constraint_retention_hit=1, constraint_retention_hit_present=1, unsafe_compaction_leakage=0, unsafe_compaction_leakage_present=1),
        CaseMetrics(case_id="case_10_avoid_repeating_failed_attempt", strategy="variant_2", positive_contamination=0, positive_contamination_present=1, negative_lesson_retained=1, negative_lesson_retained_present=1, correct_action=1, correct_action_present=1),
        CaseMetrics(case_id="case_11_sanitized_failed_destructive_attempt", strategy="variant_2", unsafe_negative_leakage=0, unsafe_negative_leakage_present=1, sanitized_notice_present=1, sanitized_notice_present_present=1),
    ]

    acceptance = _acceptance(summary, results=results)

    assert acceptance["checks"]["variant_2_zero_cross_workspace_leakage"] is False
    assert acceptance["passed"] is False


def test_no_memory_acceptance_is_case_8_specific():
    summary = {
        "baseline_0": {"task_success_rate": 0.1},
        "baseline_1": {"failed_branch_contamination_rate": 1.0, "stale_memory_injection_rate": 1.0},
        "variant_2": {
            "failed_branch_contamination_rate": 0.0,
            "cross_workspace_leakage_rate": 0.0,
            "tool_sensitive_blocked_rate": 1.0,
            "procedural_reuse_hit_rate": 1.0,
            "superseded_injection_rate": 0.0,
            "stale_memory_injection_rate": 0.0,
            "task_success_rate": 0.9,
            "compaction_trigger_rate": 1.0,
            "constraint_retention_hit_rate": 1.0,
            "unsafe_compaction_leakage_rate": 0.0,
        },
    }
    results = [
        CaseMetrics(case_id="case_8_no_memory_baseline", strategy="baseline_0", task_success=1),
        CaseMetrics(case_id="case_8_no_memory_baseline", strategy="variant_2", task_success=0),
    ]

    acceptance = _acceptance(summary, results=results)

    assert acceptance["checks"]["variant_2_succeeds_where_no_memory_baseline_fails"] is False
    assert acceptance["passed"] is False


def test_cross_workspace_summary_is_present_gated():
    rows = [
        CaseMetrics(case_id="case_3_workspace_isolation", strategy="variant_2", cross_workspace_leakage=1, cross_workspace_leakage_present=1),
        CaseMetrics(case_id="case_1_project_preference", strategy="variant_2", cross_workspace_leakage=0, cross_workspace_leakage_present=0),
    ]

    summary = _summarize(rows)

    assert summary["variant_2"]["cross_workspace_leakage_rate"] == 1.0
