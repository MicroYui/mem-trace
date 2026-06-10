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
    MemoryItem,
    MemoryType,
    ObservabilityReportRequest,
    RetrievalRequest,
    RetrievalStrategy,
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
