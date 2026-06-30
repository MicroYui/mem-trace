"""Dedup-identity test: the CLI reuses the shared context helpers.

The CLI demo previously kept a private byte-for-byte copy of `decide_action` /
`contaminated`. It now imports them from `memtrace_sdk.context_actions`, which
re-exports the single source of truth in `app.runtime.context_actions`.
"""
from __future__ import annotations

from memtrace_sdk import cli, context_actions


def test_cli_reuses_shared_context_actions() -> None:
    assert cli._decide_action is context_actions.decide_action
    assert cli._contaminated is context_actions.contaminated


def test_sdk_context_actions_match_runtime_source() -> None:
    from app.runtime import context_actions as runtime_actions

    assert context_actions.decide_action is runtime_actions.decide_action
    assert context_actions.contaminated is runtime_actions.contaminated
    assert context_actions.positive_blocks is runtime_actions.positive_blocks
