"""Structural tests for the scale-only / IDE components (ROADMAP §6).

These components require external toolchains (Go, Rust, the VS Code extension
host) that are intentionally NOT part of default CI, so we validate their
skeletons structurally — files exist, declare the right module/package metadata,
and stay thin over `/v1` without duplicating Python runtime semantics. The real
`go build` / `cargo test` / VS Code checks run only where those toolchains exist.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and (parent / "components").exists():
            return parent
    raise AssertionError("repo root not found")


ROOT = _repo_root()


def test_go_trace_collector_skeleton_exists():
    base = ROOT / "components" / "go-trace-collector"
    go_mod = (base / "go.mod").read_text()
    main_go = (base / "main.go").read_text()
    assert "module github.com/MicroYui/mem-trace/components/go-trace-collector" in go_mod
    # Thin gateway: forwards to the runtime /v1/events, never interprets events.
    assert "/v1/events" in main_go
    assert "package main" in main_go
    assert (base / "README.md").exists()


def test_rust_profile_analyzer_skeleton_exists():
    base = ROOT / "components" / "rust-profile-analyzer"
    cargo = (base / "Cargo.toml").read_text()
    main_rs = (base / "src" / "main.rs").read_text()
    assert 'name = "rust-profile-analyzer"' in cargo
    assert "fn main()" in main_rs
    assert "latency_ms" in main_rs  # aggregates profiler phase latencies
    assert "#[cfg(test)]" in main_rs  # ships unit tests
    assert (base / "README.md").exists()


def test_vscode_extension_is_thin_over_sdk():
    base = ROOT / "packages" / "vscode-extension"
    import json

    pkg = json.loads((base / "package.json").read_text())
    assert pkg["engines"]["vscode"]
    assert pkg["dependencies"]["@memtrace/sdk"] == "workspace:*"
    command_ids = {c["command"] for c in pkg["contributes"]["commands"]}
    assert {"memtrace.retrieveContext", "memtrace.showRunTimeline", "memtrace.inspectAccess"} <= command_ids
    source = (base / "src" / "extension.ts").read_text()
    assert 'from "@memtrace/sdk"' in source  # thin over the SDK / HTTP /v1


@pytest.mark.parametrize(
    "rel",
    [
        "components/go-trace-collector/main.go",
        "components/rust-profile-analyzer/src/main.rs",
        "packages/vscode-extension/package.json",
    ],
)
def test_scale_components_ship_no_obvious_secrets(rel):
    import re

    text = (ROOT / rel).read_text()
    assert not re.search(r"sk-[A-Za-z0-9]{12,}", text)
    assert "BEGIN PRIVATE KEY" not in text
