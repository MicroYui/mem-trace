"""Rule-based memory writer + secret protection tests."""
from __future__ import annotations

from app.memory import secrets, writer
from app.memory.key_ontology import PROJECT_PACKAGE_MANAGER, PROJECT_RUNTIME, PROJECT_RUNTIME_EXCLUDED
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
    assert keys.get(PROJECT_RUNTIME) == "bun"
    assert keys.get(PROJECT_RUNTIME_EXCLUDED) == "nodejs"


def test_writer_uses_ontology_runtime_keys():
    results = writer.write_from_user_message(_user_event("这个项目使用 Bun，不用 Node.js"))
    keys = {r.memory.key: r.memory.value for r in results}
    assert keys[PROJECT_RUNTIME] == "bun"
    assert keys[PROJECT_RUNTIME_EXCLUDED] == "nodejs"


def test_writer_writes_package_manager_to_ontology_key():
    results = writer.write_from_user_message(_user_event("这个项目使用 pnpm"))
    keys = {r.memory.key: r.memory.value for r in results}
    assert keys[PROJECT_PACKAGE_MANAGER] == "pnpm"
    assert PROJECT_RUNTIME not in keys


def test_package_manager_correction_supersedes_package_manager_key():
    results = writer.write_from_user_message(_user_event("不是 npm，是 pnpm"))
    assert len(results) == 1
    assert results[0].memory.key == PROJECT_PACKAGE_MANAGER
    assert results[0].memory.value == "pnpm"
    assert (PROJECT_PACKAGE_MANAGER, "workspace") in results[0].supersede_keys


def test_package_manager_correction_to_bun_stays_package_manager_key():
    for text in ("不是 npm，是 bun", "不用 npm，用 bun"):
        results = writer.write_from_user_message(_user_event(text))
        assert len(results) == 1
        assert results[0].memory.key == PROJECT_PACKAGE_MANAGER
        assert results[0].memory.value == "bun"
        assert (PROJECT_PACKAGE_MANAGER, "workspace") in results[0].supersede_keys


def test_english_uses_constraint():
    results = writer.write_from_user_message(_user_event("This project uses Bun and should not use Node.js"))
    keys = {r.memory.key: r.memory.value for r in results}
    assert keys.get("project.runtime") == "bun"
    assert keys.get("project.runtime.excluded") == "nodejs"


def test_negative_only_constraint_is_not_misread_as_positive():
    """mvp.md §5.2: a bare "不用 X" / "不使用 X" must yield ONLY the excluded
    constraint, never a positive project.runtime=X."""
    for text in ("不用 Node.js", "不使用 Node.js"):
        results = writer.write_from_user_message(_user_event(text))
        keys = {r.memory.key: r.memory.value for r in results}
        assert keys.get("project.runtime.excluded") == "nodejs"
        assert "project.runtime" not in keys  # no false positive constraint


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


def test_secret_detection_covers_common_credential_formats():
    samples = [
        "token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        "google AIzaSyA1234567890abcdefghijklmnopqrstu",
        "slack " + "xox" + "b-1234567890-abcdefghijklmnop",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIBderaw\n-----END RSA PRIVATE KEY-----",
        "my password is hunter2",
        "-----BEGIN ENCRYPTED PRIVATE KEY-----\nMIIBderaw\n-----END ENCRYPTED PRIVATE KEY-----",
        "Authorization: Basic dXNlcjpwYXNzd29yZDEyMzQ=",
    ]
    for text in samples:
        assert secrets.contains_secret(text) is True, text
        assert "[REDACTED]" in secrets.redact(text), text


def test_negated_english_use_does_not_create_positive_runtime():
    """"should not use X" must not also produce a positive project.runtime=X."""
    results = writer.write_from_user_message(_user_event("This project should not use Node.js"))
    keys = {r.memory.key: r.memory.value for r in results}
    assert keys.get("project.runtime.excluded") == "nodejs"
    assert "project.runtime" not in keys


def test_negated_package_manager_does_not_create_positive_constraint():
    """"should not use npm" must not leave a self-contradictory package_manager=npm.

    `npm` normalizes to project.package_manager, so the negation guard must cover
    the package-manager controlled key too, not just project.runtime.
    """
    results = writer.write_from_user_message(_user_event("This project should not use npm"))
    keys = {r.memory.key: r.memory.value for r in results}
    assert keys.get(PROJECT_RUNTIME_EXCLUDED) == "npm"
    assert PROJECT_PACKAGE_MANAGER not in keys
    assert PROJECT_RUNTIME not in keys


def test_non_adjacent_chinese_negation_is_not_positive():
    """"不想用 X" expresses negation even though 不 and 用 are not adjacent."""
    results = writer.write_from_user_message(_user_event("我不想用 node"))
    keys = {r.memory.key: r.memory.value for r in results}
    assert keys.get(PROJECT_RUNTIME_EXCLUDED) == "nodejs"
    assert PROJECT_RUNTIME not in keys


def test_negative_constraint_is_deduplicated():
    """A single excluded token must yield exactly one excluded memory even when
    multiple negative patterns match the same phrase."""
    results = writer.write_from_user_message(_user_event("should not use node"))
    excluded = [r for r in results if r.memory.key == PROJECT_RUNTIME_EXCLUDED]
    assert len(excluded) == 1
    assert excluded[0].memory.value == "nodejs"


def test_finish_step_cancelled_is_rolled_back_branch():
    """A cancelled step's working-state memory must NOT enter the active branch."""
    step = AgentStep(workspace_id="ws", run_id="r", status=StepStatus.cancelled, intent="debug")
    mem = writer.write_from_finish_step(step, summary=None)
    assert mem.branch_status == BranchStatus.rolled_back


def test_finish_step_rolled_back_is_rolled_back_branch():
    step = AgentStep(workspace_id="ws", run_id="r", status=StepStatus.rolled_back, intent="debug")
    mem = writer.write_from_finish_step(step, summary=None)
    assert mem.branch_status == BranchStatus.rolled_back
