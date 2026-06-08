"""Rule-based memory writer + secret protection tests."""
from __future__ import annotations

from app.memory import secrets, writer
from app.memory.writer import detect_risk_flags
from app.runtime.models import (
    AgentEvent,
    AgentStep,
    BranchStatus,
    EventRole,
    EventType,
    MemoryType,
    StepStatus,
)


def _user_event(content: str) -> AgentEvent:
    return AgentEvent(
        workspace_id="ws", run_id="r", step_id="s", role=EventRole.user,
        event_type=EventType.message, content=content,
    )


def _tool_event(content: str, status: str) -> AgentEvent:
    return AgentEvent(
        workspace_id="ws", run_id="r", step_id="s", role=EventRole.tool,
        event_type=EventType.tool_result, status=status, content=content,
    )


def test_positive_and_negative_project_constraints():
    results = writer.write_from_user_message(_user_event("这个项目使用 Bun，不用 Node.js"))
    keys = {r.memory.key: r.memory.value for r in results}
    assert keys.get("project.runtime") == "bun"
    assert keys.get("project.runtime.excluded") == "nodejs"


def test_english_uses_constraint():
    results = writer.write_from_user_message(_user_event("This project uses Bun and should not use Node.js"))
    keys = {r.memory.key: r.memory.value for r in results}
    assert keys.get("project.runtime") == "bun"
    assert keys.get("project.runtime.excluded") == "nodejs"


def test_explicit_correction_supersedes_old_key():
    results = writer.write_from_user_message(_user_event("不是 Node.js，是 Bun"))
    assert len(results) == 1
    r = results[0]
    assert r.memory.key == "project.runtime"
    assert r.memory.value == "bun"
    assert ("project.runtime", "workspace") in r.supersede_keys


def test_tool_evidence_failed_branch_and_risk():
    mem = writer.write_from_tool_result(
        _tool_event("Tried running tests with npm test, but it failed because npm was unavailable.", "failed")
    )
    assert mem.memory_type == MemoryType.tool_evidence
    assert mem.branch_status == BranchStatus.failed
    assert mem.risk_score >= 0.3


def test_tool_evidence_success_completed_branch():
    mem = writer.write_from_tool_result(_tool_event("bun test success", "success"))
    assert mem.branch_status == BranchStatus.completed


def test_finish_step_working_state_memory():
    step = AgentStep(workspace_id="ws", run_id="r", status=StepStatus.completed, intent="debug")
    mem = writer.write_from_finish_step(step, summary="all good")
    assert mem.memory_type == MemoryType.working_state
    assert mem.branch_status == BranchStatus.completed
    assert "all good" in mem.content


def test_risk_flags_detect_destructive_and_production():
    flags = detect_risk_flags("run git push --force to production")
    assert flags.destructive_command is True
    assert flags.production_env is True
    assert flags.tool_sensitive is True


def test_secret_detection_and_redaction():
    text = "here is the key sk-abcdefgh12345678ijklmnop and a token"
    assert secrets.contains_secret(text) is True
    red = secrets.redact(text)
    assert "sk-abcdefgh12345678ijklmnop" not in red
    assert "[REDACTED]" in red


def test_non_secret_passes_through():
    assert secrets.contains_secret("just run bun test") is False
