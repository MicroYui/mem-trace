from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.benchmark.runner import run_benchmark
from app.demo.run_demo import _render_markdown as render_demo_markdown
from app.demo.run_demo import run_demo
from app.observability.reports import main as observability_reports_main


@pytest.mark.asyncio
async def test_demo_and_benchmark_reports_are_reproducible(tmp_path: Path) -> None:
    demo = await run_demo(use_sql=False)
    (tmp_path / "demo_report.json").write_text(
        json.dumps(demo, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (tmp_path / "demo_report.md").write_text(render_demo_markdown(demo), encoding="utf-8")

    benchmark = await run_benchmark(output_dir=tmp_path)

    assert demo["summary"]["contamination_eliminated"] is True
    assert benchmark["acceptance"]["passed"] is True
    assert (tmp_path / "demo_report.md").exists()
    assert (tmp_path / "demo_report.json").exists()
    assert (tmp_path / "benchmark_report.md").exists()
    assert (tmp_path / "benchmark_results.json").exists()


def test_observability_report_entrypoint_writes_expected_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    observability_reports_main(["--output-dir", "reports"])

    assert (tmp_path / "reports" / "observability_report.json").exists()
    assert (tmp_path / "reports" / "observability_report.md").exists()
    assert (tmp_path / "reports" / "observability_report.html").exists()


def test_readme_documents_existing_reproducibility_entrypoints() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    required_snippets = [
        "./scripts/reproduce.sh",
        "uv run python -m app.demo.run_demo",
        "uv run python -m app.benchmark.runner",
        "uv run python -m app.observability.reports",
        "docker-compose.yml",
        "/v1/replay/access/{access_id}",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in readme]
    assert missing == []


def test_reproduce_script_rejects_output_outside_reports() -> None:
    result = subprocess.run(
        ["./scripts/reproduce.sh", "tmpout"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "must be reports or a relative path under reports/" in result.stderr
