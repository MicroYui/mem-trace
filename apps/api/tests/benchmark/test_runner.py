"""P1 benchmark runner tests."""
from __future__ import annotations

import json

from app.benchmark.runner import run_benchmark
from app.runtime.repository import InMemoryRepository


async def test_run_benchmark_writes_markdown_and_json_reports(tmp_path):
    report = await run_benchmark(output_dir=tmp_path)

    assert len(report["cases"]) == 6
    assert {c["case_id"] for c in report["cases"]} == {
        "case_1_project_preference",
        "case_2_failed_branch",
        "case_3_workspace_isolation",
        "case_4_tool_safety",
        "case_5_explicit_correction",
        "case_6_completed_run_reuse",
    }
    assert len(report["results"]) == 24  # 6 cases x 4 strategies

    json_path = tmp_path / "benchmark_results.json"
    md_path = tmp_path / "benchmark_report.md"
    assert json_path.exists()
    assert md_path.exists()

    saved = json.loads(json_path.read_text())
    assert saved["summary"]["variant_2"]["cross_workspace_leakage_rate"] == 0
    assert saved["summary"]["variant_2"]["tool_sensitive_blocked_rate"] == 1
    assert (
        saved["summary"]["variant_2"]["failed_branch_contamination_rate"]
        < saved["summary"]["baseline_1"]["failed_branch_contamination_rate"]
    )
    assert "failed_branch_contamination_rate" in md_path.read_text()


async def test_run_benchmark_meets_mvp_acceptance(tmp_path):
    report = await run_benchmark(output_dir=tmp_path)
    acc = report["acceptance"]
    assert acc["passed"] is True
    assert acc["checks"]["variant_2_contamination_below_baseline_1"] is True
    assert acc["checks"]["variant_2_zero_cross_workspace_leakage"] is True
    assert acc["checks"]["variant_2_blocks_tool_sensitive"] is True
    assert acc["checks"]["variant_2_reuses_procedural_memory"] is True
    assert acc["checks"]["variant_2_excludes_superseded_memory"] is True


async def test_run_benchmark_persists_cases_and_results(tmp_path):
    repo = InMemoryRepository()

    await run_benchmark(output_dir=tmp_path, repo=repo)

    cases = await repo.list_benchmark_cases()
    results = await repo.list_benchmark_results()
    assert len(cases) == 6
    assert len(results) == 24
    assert {r.strategy for r in results} == {"baseline_0", "baseline_1", "variant_1", "variant_2"}
    assert any(
        r.case_id == "case_4_tool_safety" and r.strategy == "variant_2"
        and r.metrics["tool_sensitive_blocked"] == 1
        for r in results
    )
