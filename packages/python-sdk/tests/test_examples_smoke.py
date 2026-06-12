from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[3]


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
