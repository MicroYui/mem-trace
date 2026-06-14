from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _project(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]


def test_root_python_package_metadata_describes_current_platform() -> None:
    project = _project(ROOT / "pyproject.toml")

    assert project["name"] == "memtrace"
    assert "P0 MVP" not in project["description"]
    assert "state-aware memory runtime" in project["description"]
    assert project["license"] == "Apache-2.0"
    assert project["readme"] == "README.md"
    assert project["urls"] == {
        "Homepage": "https://github.com/MicroYui/mem-trace#readme",
        "Repository": "https://github.com/MicroYui/mem-trace",
        "Issues": "https://github.com/MicroYui/mem-trace/issues",
    }
    assert "Programming Language :: Python :: 3 :: Only" in project["classifiers"]
    assert "Topic :: Software Development :: Libraries :: Python Modules" in project["classifiers"]


def test_python_sdk_package_metadata_and_cli_entrypoint_are_release_ready() -> None:
    project = _project(ROOT / "packages" / "python-sdk" / "pyproject.toml")

    assert project["name"] == "memtrace-sdk"
    assert "Python SDK" in project["description"]
    assert "P0 MVP" not in project["description"]
    assert project["license"] == "Apache-2.0"
    assert project["readme"] == {
        "text": "Python SDK, CLI, and LangGraph adapter for the MemTrace trace-first, state-aware agent memory runtime. See the repository README for full documentation.",
        "content-type": "text/markdown",
    }
    assert "memtrace>=0.1.0,<0.2.0" in project["dependencies"]
    assert project["urls"] == {
        "Homepage": "https://github.com/MicroYui/mem-trace#readme",
        "Repository": "https://github.com/MicroYui/mem-trace",
        "Issues": "https://github.com/MicroYui/mem-trace/issues",
    }
    assert "Programming Language :: Python :: 3 :: Only" in project["classifiers"]
    assert project["scripts"] == {"memtrace": "memtrace_sdk.cli:main"}
