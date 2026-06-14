from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[3]


def _example_subprocess_env() -> dict[str, str]:
    python_paths = [str(ROOT / "apps" / "api"), str(ROOT / "packages" / "python-sdk" / "src")]
    if existing := os.environ.get("PYTHONPATH"):
        python_paths.append(existing)
    return {**os.environ, "PYTHONPATH": os.pathsep.join(python_paths)}


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_simple_agent_example_prints_contamination_contrast(capsys) -> None:
    module = _load_module(ROOT / "examples" / "simple_agent" / "main.py", "simple_agent_example")

    result = await module.main()
    output = capsys.readouterr().out

    assert result["baseline_action"] == "npm test"
    assert result["variant_2_action"] == "bun test"
    assert result["contamination_eliminated"] is True
    assert "baseline_1 action: npm test" in output
    assert "variant_2 action: bun test" in output
    assert "contamination eliminated: true" in output.lower()


async def test_langgraph_adapter_example_runs_or_skips_cleanly(capsys) -> None:
    module = _load_module(
        ROOT / "examples" / "langgraph_adapter" / "main.py", "langgraph_adapter_example"
    )

    result = await module.main()
    output = capsys.readouterr().out.lower()

    assert result["status"] in {"ran", "skipped"}
    if result["status"] == "skipped":
        assert result["reason"] == "langgraph_not_installed"
        assert "pip install memtrace-sdk[langgraph]" in output
    else:
        assert result["event_source"] == "langgraph_adapter"
        assert result["step_status"] == "completed"
        assert "langgraph adapter example completed" in output


def test_dogfood_coding_agent_scenario_outputs_safe_recovery() -> None:
    result = subprocess.run(
        [sys.executable, "examples/dogfood/coding_agent.py"],
        cwd=ROOT,
        env=_example_subprocess_env(),
        check=True,
        text=True,
        capture_output=True,
    )

    assert "variant_2 avoids npm: true" in result.stdout
    assert "recovery command: bun test" in result.stdout


def test_dogfood_multi_session_scenario_retrieves_project_constraint() -> None:
    result = subprocess.run(
        [sys.executable, "examples/dogfood/multi_session_constraints.py"],
        cwd=ROOT,
        env=_example_subprocess_env(),
        check=True,
        text=True,
        capture_output=True,
    )

    assert "session_2_retrieved_project_runtime: Bun" in result.stdout


def test_dogfood_destructive_failure_scenario_sanitizes_raw_command() -> None:
    result = subprocess.run(
        [sys.executable, "examples/dogfood/destructive_failure.py"],
        cwd=ROOT,
        env=_example_subprocess_env(),
        check=True,
        text=True,
        capture_output=True,
    )

    assert "destructive_failure_sanitized: true" in result.stdout
    assert "rm -rf" not in result.stdout + result.stderr


def test_release_readiness_smoke_script_runs_canonical_no_network_demo() -> None:
    result = subprocess.run(
        ["bash", "scripts/smoke-release-readiness.sh"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    output = result.stdout.lower()
    assert "baseline_1 action: npm test" in result.stdout
    assert "variant_2 action: bun test" in result.stdout
    assert "contamination eliminated: true" in output
    assert "release readiness smoke passed" in output
