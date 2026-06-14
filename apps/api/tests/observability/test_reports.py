"""Phase 3-A Issue 7 observability report tests."""
from __future__ import annotations

import json
import subprocess
import sys

import httpx
import pytest
from fastapi import FastAPI

from app.api.deps import get_runtime
from app.api.routes import router
from app.observability.reports import write_observability_report
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    CompactionKind,
    CompactionProvider,
    ContextCompactionLog,
    MaintenanceOperation,
    MaintenanceRunRecord,
    MaintenanceTaskAttemptRecord,
    MemoryItem,
    MemoryType,
    ObservabilityReportRequest,
    RetainedNegativeEvidence,
    RetainedFact,
    RetrievalRequest,
    RetrievalStrategy,
    SchedulerRunStatus,
    SchedulerTaskStatus,
    StartRunRequest,
    StartStepRequest,
)
from app.runtime.repository import InMemoryRepository


def _app_for(runtime: MemoryRuntime) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return app


async def _seed_observable_access(runtime: MemoryRuntime, repo: InMemoryRepository) -> tuple[str, str]:
    run = await runtime.start_run(
        StartRunRequest(session_id="s_report", task="choose package manager", workspace_id="ws_report")
    )
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="choose test command"))
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_report",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.runtime",
            value="bun",
            content="This project uses Bun; run bun test for tests",
            branch_status=BranchStatus.completed,
        )
    )
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_report",
            run_id=run.run_id,
            memory_type=MemoryType.tool_evidence,
            key="tool.command.failed",
            value="npm test",
            content="npm test failed on a rolled back branch",
            branch_status=BranchStatus.rolled_back,
        )
    )
    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="which test command should I run, bun test or npm test?",
            strategy=RetrievalStrategy.variant_2,
            token_budget=128,
            top_k=5,
        )
    )
    return run.run_id, ctx.access_id


@pytest.mark.asyncio
async def test_report_writer_outputs_three_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_report")
    _, access_id = await _seed_observable_access(runtime, repo)

    result = await write_observability_report(
        repo,
        runtime._retrieval,  # noqa: SLF001 - Issue 7 report writer unit test uses runtime-owned controller
        ObservabilityReportRequest(workspace_id="ws_report", output_dir="reports", include_replay=True),
    )

    json_path = tmp_path / result.json_path
    markdown_path = tmp_path / result.markdown_path
    html_path = tmp_path / result.html_path
    assert json_path.exists()
    assert markdown_path.exists()
    assert html_path.exists()
    assert result.summary.access_count == 1

    payload = json.loads(json_path.read_text())
    assert payload["summary"]["workspace_id"] == "ws_report"
    assert payload["accesses"][0]["access_id"] == access_id
    assert payload["accesses"][0]["metrics"]["failed_branch_rejected"] == 1.0
    assert payload["accesses"][0]["context_block_count"] >= 1
    assert payload["replays"][0]["access_id"] == access_id


@pytest.mark.asyncio
async def test_markdown_report_contains_access_id_and_quality_sections(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_report")
    _, access_id = await _seed_observable_access(runtime, repo)

    result = await runtime.write_observability_report(
        ObservabilityReportRequest(workspace_id="ws_report", output_dir="reports", include_replay=True)
    )

    markdown = (tmp_path / result.markdown_path).read_text()
    assert "# MemTrace Observability Report" in markdown
    assert "## Quality Signals" in markdown
    assert "## Safety Signals" in markdown
    assert "## Replay Drift" in markdown
    assert f"/v1/replay/access/{access_id}" in markdown


@pytest.mark.asyncio
async def test_html_report_is_static_and_contains_summary_tables(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_report")
    _, access_id = await _seed_observable_access(runtime, repo)

    result = await runtime.write_observability_report(
        ObservabilityReportRequest(workspace_id="ws_report", output_dir="reports", include_replay=True)
    )

    html = (tmp_path / result.html_path).read_text()
    assert "<title>MemTrace Observability Report</title>" in html
    assert "<script" not in html.lower()
    assert "https://" not in html
    assert "Strategy Breakdown" in html
    assert "Quality &amp; Safety" in html
    assert f"/v1/replay/access/{access_id}" in html
    assert "<details>" in html


@pytest.mark.asyncio
async def test_report_json_is_deterministic_enough_for_assertions(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_report")
    run_id, access_id = await _seed_observable_access(runtime, repo)

    first = await runtime.write_observability_report(
        ObservabilityReportRequest(workspace_id="ws_report", run_id=run_id, output_dir="reports", include_replay=False)
    )
    first_payload = json.loads((tmp_path / first.json_path).read_text())
    second = await runtime.write_observability_report(
        ObservabilityReportRequest(workspace_id="ws_report", run_id=run_id, output_dir="reports", include_replay=False)
    )
    second_payload = json.loads((tmp_path / second.json_path).read_text())

    assert first_payload == second_payload
    assert first_payload["summary"]["run_id"] == run_id
    assert first_payload["accesses"] == [
        {
            "access_id": access_id,
            "run_id": run_id,
            "query": "which test command should I run, bun test or npm test?",
            "strategy": "variant_2",
            "metrics": first_payload["accesses"][0]["metrics"],
            "critical_drift_count": 0,
            "context_block_count": first_payload["accesses"][0]["context_block_count"],
        }
    ]
    assert first_payload["replays"] == []


@pytest.mark.asyncio
async def test_report_includes_compaction_section_with_retained_facts(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_report")
    run = await runtime.start_run(
        StartRunRequest(session_id="s_report_compaction", task="choose stack", workspace_id="ws_report")
    )
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="choose stack"))
    for key, value in [
        ("project.runtime", "bun"),
        ("project.database", "postgres"),
        ("endpoint.current", "/v2/users"),
    ]:
        await repo.add_memory(
            MemoryItem(
                workspace_id="ws_report",
                run_id=run.run_id,
                memory_type=MemoryType.project,
                key=key,
                value=value,
                content=f"{key}={value}",
                branch_status=BranchStatus.completed,
            )
        )
    for i in range(6):
        await repo.add_memory(
            MemoryItem(
                workspace_id="ws_report",
                run_id=run.run_id,
                memory_type=MemoryType.episodic,
                content=f"benign verbose observation {i} about previous API debugging that can be omitted",
                branch_status=BranchStatus.completed,
            )
        )
    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="which DB/runtime/endpoint should I use?",
            strategy=RetrievalStrategy.variant_2,
            token_budget=18,
            top_k=10,
        )
    )
    assert await repo.list_compaction_logs(access_id=ctx.access_id)

    result = await runtime.write_observability_report(
        ObservabilityReportRequest(workspace_id="ws_report", output_dir="reports", include_replay=True)
    )

    payload = json.loads((tmp_path / result.json_path).read_text())
    assert payload["compactions"]
    retained = payload["compactions"][0]["retained_facts"]
    assert {f"{fact['key']}={fact['value']}" for fact in retained} >= {
        "project.database=postgres",
        "endpoint.current=/v2/users",
    }
    markdown = (tmp_path / result.markdown_path).read_text()
    html = (tmp_path / result.html_path).read_text()
    assert "## Compaction" in markdown
    assert "project.database=postgres" in markdown
    assert "<h2>Compaction</h2>" in html
    assert "endpoint.current=/v2/users" in html


@pytest.mark.asyncio
async def test_report_filters_compaction_rows_and_escapes_markdown(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_report")
    run_id, access_id = await _seed_observable_access(runtime, repo)
    await repo.add_compaction_log(
        ContextCompactionLog(
            access_id=access_id,
            workspace_id="ws_report",
            run_id=run_id,
            kind=CompactionKind.budget_notice,
            provider=CompactionProvider.rule,
            pre_tokens=20,
            post_tokens=5,
            dropped_block_count=1,
            compression_ratio=0.25,
            retained_facts=[RetainedFact(key="project.pipe", value="bun|safe\nvalue<script>![x](https://evil.test/pixel)")],
        )
    )
    await repo.add_compaction_log(
        ContextCompactionLog(
            access_id=access_id,
            workspace_id="ws_other",
            run_id=run_id,
            kind=CompactionKind.budget_notice,
            provider=CompactionProvider.rule,
            pre_tokens=100,
            post_tokens=100,
            dropped_block_count=99,
            compression_ratio=1.0,
            retained_facts=[RetainedFact(key="wrong.workspace", value="must-not-render")],
        )
    )

    result = await runtime.write_observability_report(
        ObservabilityReportRequest(workspace_id="ws_report", output_dir="reports", include_replay=True)
    )

    payload = json.loads((tmp_path / result.json_path).read_text())
    assert len(payload["compactions"]) == 1
    assert payload["compactions"][0]["retained_facts"][0]["key"] == "project.pipe"
    markdown = (tmp_path / result.markdown_path).read_text()
    assert "must-not-render" not in markdown
    assert "project.pipe=bun\\|safe<br>value&lt;script&gt;\\!\\[x\\]\\(https://evil.test/pixel\\)" in markdown
    assert "![x](https://evil.test/pixel)" not in markdown


@pytest.mark.asyncio
async def test_report_redacts_query_and_compaction_payloads(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_report")
    run = await runtime.start_run(
        StartRunRequest(session_id="s_report_secret", task="secret report", workspace_id="ws_report")
    )
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="secret query"))
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_report",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.runtime",
            value="bun",
            content="This project uses Bun",
            branch_status=BranchStatus.completed,
        )
    )
    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="debug Authorization: Bearer sk-1234567890abcdef password is hunter2",
            strategy=RetrievalStrategy.variant_2,
        )
    )
    await repo.add_compaction_log(
        ContextCompactionLog(
            access_id=ctx.access_id,
            workspace_id="ws_report",
            run_id=run.run_id,
            kind=CompactionKind.budget_notice,
            provider=CompactionProvider.rule,
            pre_tokens=40,
            post_tokens=10,
            dropped_block_count=1,
            compression_ratio=0.25,
            summary_text="summary kept sk-1234567890abcdef and password hunter2",
            retained_facts=[RetainedFact(key="project.api_key", value="short-secret")],
            warnings=["warning Authorization: Bearer sk-1234567890abcdef"],
        )
    )

    result = await runtime.write_observability_report(
        ObservabilityReportRequest(workspace_id="ws_report", output_dir="reports", include_replay=True)
    )

    payload = json.loads((tmp_path / result.json_path).read_text())
    serialized = json.dumps(payload, ensure_ascii=False) + (tmp_path / result.markdown_path).read_text() + (tmp_path / result.html_path).read_text()
    assert "short-secret" not in serialized
    for marker in ("sk-1234567890abcdef", "hunter2", "Authorization: Bearer"):
        assert marker not in serialized


@pytest.mark.asyncio
async def test_report_includes_retained_negative_evidence_counts_and_sanitized_rows(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_report")
    run_id, access_id = await _seed_observable_access(runtime, repo)
    await repo.add_compaction_log(
        ContextCompactionLog(
            access_id=access_id,
            workspace_id="ws_report",
            run_id=run_id,
            kind=CompactionKind.budget_notice,
            provider=CompactionProvider.rule,
            pre_tokens=40,
            post_tokens=6,
            dropped_block_count=2,
            compression_ratio=0.15,
            retained_negative_evidence=[
                RetainedNegativeEvidence(
                    source_memory_id="mem_failed",
                    source_state_node_id="node_failed",
                    mode="sanitized_risk_notice",
                    risk_kind="destructive",
                    reason="failed_branch_sanitized",
                    safe_text="MALFORMED legacy row leaked rm -rf /prod with password=hunter2 Authorization: Bearer sk-1234567890abcdef",
                ),
                RetainedNegativeEvidence(
                    source_memory_id="mem_malformed_raw_risk",
                    source_state_node_id="node_failed_raw_risk",
                    mode="raw_failed_attempt",
                    risk_kind="destructive",
                    reason="failed_branch_degraded",
                    safe_text="Malformed raw retained row says kubectl delete namespace production",
                )
            ],
        )
    )

    result = await runtime.write_observability_report(
        ObservabilityReportRequest(workspace_id="ws_report", output_dir="reports", include_replay=True)
    )

    payload = json.loads((tmp_path / result.json_path).read_text())
    metrics = payload["accesses"][0]["metrics"]
    assert metrics["retained_negative_evidence_count"] == 2.0
    assert metrics["sanitized_retained_negative_evidence_count"] == 1.0
    assert payload["summary"]["retained_negative_evidence_count"] == 2
    assert payload["summary"]["sanitized_retained_negative_evidence_count"] == 1
    assert payload["compactions"][0]["retained_negative_evidence"][0]["risk_kind"] == "destructive"
    markdown = (tmp_path / result.markdown_path).read_text()
    html = (tmp_path / result.html_path).read_text()
    assert "Retained negative evidence" in markdown
    assert "Retained negative evidence" in html
    serialized = json.dumps(payload, ensure_ascii=False) + markdown + html
    assert "destructive operation" in serialized
    for marker in ("rm -rf", "/prod", "sk-", "password", "Authorization"):
        assert marker not in serialized
    assert "kubectl delete" not in serialized
    assert "namespace production" not in serialized


@pytest.mark.asyncio
async def test_report_endpoint_returns_paths_and_rejects_unsafe_output_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_report")
    await _seed_observable_access(runtime, repo)
    app = _app_for(runtime)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.post(
            "/v1/observability/reports",
            json={"workspace_id": "ws_report", "output_dir": "reports/api", "include_replay": True},
        )
        unsafe = await client.post(
            "/v1/observability/reports",
            json={"workspace_id": "ws_report", "output_dir": "../tmp", "include_replay": False},
        )

    assert ok.status_code == 200
    payload = ok.json()
    assert payload["json_path"] == "reports/api/observability_report.json"
    assert payload["markdown_path"] == "reports/api/observability_report.md"
    assert payload["html_path"] == "reports/api/observability_report.html"
    assert payload["summary"]["access_count"] == 1
    assert (tmp_path / payload["json_path"]).exists()

    assert unsafe.status_code == 400
    assert "unsafe output_dir" in unsafe.json()["detail"]


def test_reports_module_entrypoint_writes_empty_report(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "app.observability.reports", "--output-dir", "reports/cli"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "reports/cli/observability_report.json").exists()
    payload = json.loads((tmp_path / "reports/cli/observability_report.json").read_text())
    assert payload["summary"]["access_count"] == 0
    assert payload["accesses"] == []
    assert payload["replays"] == []


@pytest.mark.asyncio
async def test_report_writer_rejects_reports_symlink(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "reports").symlink_to(outside, target_is_directory=True)

    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_report")

    with pytest.raises(ValueError, match="unsafe output_dir"):
        await runtime.write_observability_report(ObservabilityReportRequest(output_dir="reports"))

    assert not (outside / "observability_report.json").exists()


@pytest.mark.asyncio
async def test_report_writer_rejects_symlink_loop_as_value_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reports").symlink_to(tmp_path / "reports", target_is_directory=True)

    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_report")

    with pytest.raises(ValueError, match="unsafe output_dir"):
        await runtime.write_observability_report(ObservabilityReportRequest(output_dir="reports"))


@pytest.mark.asyncio
async def test_report_includes_maintenance_summary(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_report")
    # A completed run plus a run with a failed attempt (redacted error_summary).
    await repo.add_maintenance_run(
        MaintenanceRunRecord(
            scheduler_run_id="msrun_ok",
            workspace_id="ws_report",
            operations=[MaintenanceOperation.score_memory],
            status=SchedulerRunStatus.completed,
        )
    )
    failed_run = await repo.add_maintenance_run(
        MaintenanceRunRecord(
            scheduler_run_id="msrun_bad",
            workspace_id="ws_report",
            operations=[MaintenanceOperation.dedup_memory],
            status=SchedulerRunStatus.failed,
        )
    )
    await repo.add_maintenance_task_attempt(
        MaintenanceTaskAttemptRecord(
            scheduler_run_id=failed_run.scheduler_run_id,
            workspace_id="ws_report",
            operation=MaintenanceOperation.dedup_memory,
            status=SchedulerTaskStatus.failed,
            error_summary="dedup_memory failed",
        )
    )

    result = await runtime.write_observability_report(
        ObservabilityReportRequest(workspace_id="ws_report", output_dir="reports", include_replay=False)
    )
    payload = json.loads((tmp_path / result.json_path).read_text())
    maintenance = payload["maintenance"]
    assert maintenance["run_count"] == 2
    assert maintenance["runs_by_status"] == {"completed": 1, "failed": 1}
    assert maintenance["recent_failed_attempts"] == [
        {
            "scheduler_run_id": "msrun_bad",
            "operation": "dedup_memory",
            "error_summary": "dedup_memory failed",
        }
    ]
    markdown = (tmp_path / result.markdown_path).read_text()
    assert "## Maintenance" in markdown
    assert "dedup_memory" in markdown
