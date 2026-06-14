"""Alembic migration schema tests for Phase 3-A persistence."""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.storage.orm import (
    AccessLogORM,
    AdminActionAuditORM,
    ApiKeyORM,
    Base,
    ContextCompactionORM,
    EvalCaseORM,
    EvalResultORM,
    EvalRunORM,
    MemoryLifecycleAuditORM,
    MemoryConflictORM,
    MemoryORM,
    MemoryRetentionSignalORM,
    MemoryVersionORM,
    MaintenanceRunORM,
    MaintenanceTaskAttemptORM,
    QuotaLimitORM,
)


ROOT = Path(__file__).resolve().parents[4]
MIGRATION_PATH = ROOT / "migrations" / "versions" / "0004_phase3a_observability.py"
COMPACTION_MIGRATION_PATH = ROOT / "migrations" / "versions" / "0005_context_compaction.py"
HARDENING_MIGRATION_PATH = ROOT / "migrations" / "versions" / "0006_security_consistency_hardening.py"
I7_MIGRATION_PATH = ROOT / "migrations" / "versions" / "0007_i7_retained_negative_evidence.py"
LIFECYCLE_MIGRATION_PATH = ROOT / "migrations" / "versions" / "0008_phase4_lifecycle.py"
RETENTION_MIGRATION_PATH = ROOT / "migrations" / "versions" / "0009_memory_retention_signals.py"
VERSIONS_CONFLICTS_MIGRATION_PATH = ROOT / "migrations" / "versions" / "0010_memory_versions_conflicts.py"
GOVERNANCE_MIGRATION_PATH = ROOT / "migrations" / "versions" / "0011_governance.py"
MAINTENANCE_ADMIN_MIGRATION_PATH = ROOT / "migrations" / "versions" / "0012_maintenance_admin_governance.py"


def _migration_files() -> list[Path]:
    return sorted((ROOT / "migrations" / "versions").glob("*.py"))


def _add_column_blocks(source: str) -> list[str]:
    return _call_blocks(source, "op.add_column(")


def _op_execute_blocks(source: str) -> list[str]:
    return _call_blocks(source, "op.execute(")


def _call_blocks(source: str, needle: str) -> list[str]:
    blocks: list[str] = []
    start = 0
    while True:
        idx = source.find(needle, start)
        if idx == -1:
            return blocks
        pos = idx + len(needle)
        depth = 1
        quote: str | None = None
        escaped = False
        while pos < len(source) and depth > 0:
            char = source[pos]
            if quote is not None:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            else:
                if char in {'"', "'"}:
                    quote = char
                elif char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
            pos += 1
        blocks.append(source[idx:pos])
        start = pos


def _non_nullable_add_column_violations(source: str) -> list[str]:
    violations: list[str] = []
    for block in _add_column_blocks(source):
        if "nullable=False" not in block or "server_default" in block:
            continue
        column_match = re.search(r"sa\.Column\(\s*['\"]([^'\"]+)['\"]", block)
        column_name = column_match.group(1) if column_match else None
        if column_name and any(column_name in execute for execute in _op_execute_blocks(source)):
            continue
        violations.append(block)
    return violations


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0004_phase3a_observability", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_compaction_migration():
    spec = importlib.util.spec_from_file_location("migration_0005_context_compaction", COMPACTION_MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_hardening_migration():
    spec = importlib.util.spec_from_file_location("migration_0006_security_consistency_hardening", HARDENING_MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_i7_migration():
    spec = importlib.util.spec_from_file_location("migration_0007_i7_retained_negative_evidence", I7_MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_lifecycle_migration():
    spec = importlib.util.spec_from_file_location("migration_0008_phase4_lifecycle", LIFECYCLE_MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_retention_migration():
    spec = importlib.util.spec_from_file_location("migration_0009_memory_retention_signals", RETENTION_MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_versions_conflicts_migration():
    spec = importlib.util.spec_from_file_location("migration_0010_memory_versions_conflicts", VERSIONS_CONFLICTS_MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_governance_migration():
    spec = importlib.util.spec_from_file_location("migration_0011_governance", GOVERNANCE_MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_maintenance_admin_migration():
    spec = importlib.util.spec_from_file_location(
        "migration_0012_maintenance_admin_governance", MAINTENANCE_ADMIN_MIGRATION_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_orm_metadata_contains_access_top_k_and_eval_tables():
    assert AccessLogORM.__table__.c.top_k.default.arg == 10
    assert "policy_version" in AccessLogORM.__table__.c
    assert "policy_hash" in AccessLogORM.__table__.c
    assert "policy_snapshot" in AccessLogORM.__table__.c
    assert Base.metadata.tables["eval_cases"] is EvalCaseORM.__table__
    assert Base.metadata.tables["eval_runs"] is EvalRunORM.__table__
    assert Base.metadata.tables["eval_results"] is EvalResultORM.__table__

    assert EvalCaseORM.__table__.c.eval_case_id.primary_key
    assert EvalRunORM.__table__.c.workspace_id.index is True
    assert EvalResultORM.__table__.c.eval_run_id.index is True
    assert EvalResultORM.__table__.c.eval_case_id.index is True
    assert EvalResultORM.__table__.c.run_id.index is True
    assert EvalResultORM.__table__.c.access_id.index is True


def test_migrations_declare_revision_down_revision_and_downgrade_policy():
    for path in _migration_files():
        source = path.read_text()
        assert re.search(r"^revision(?:\s*:\s*[^=]+)?\s*=", source, re.MULTILINE), path.name
        assert re.search(r"^down_revision(?:\s*:\s*[^=]+)?\s*=", source, re.MULTILINE), path.name
        assert "def upgrade()" in source, path.name
        assert "def downgrade()" in source, path.name


def test_new_non_nullable_added_columns_have_defaults_or_backfill():
    for path in _migration_files():
        source = path.read_text()
        assert _non_nullable_add_column_violations(source) == [], path.name


def test_non_nullable_add_column_policy_checks_each_column_block():
    source = '''
def upgrade():
    op.add_column("safe", sa.Column("safe_col", sa.String(), nullable=False, server_default="x"))
    op.add_column("unsafe", sa.Column("unsafe_col", sa.String(), nullable=False))
'''
    unsafe = [block for block in _add_column_blocks(source) if "nullable=False" in block and "server_default" not in block]

    assert len(unsafe) == 1
    assert "unsafe_col" in unsafe[0]


def test_non_nullable_add_column_policy_does_not_accept_unrelated_op_execute():
    source = '''
def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("unsafe", sa.Column("unsafe_col", sa.String(), nullable=False))
'''

    violations = _non_nullable_add_column_violations(source)

    assert len(violations) == 1
    assert "unsafe_col" in violations[0]


@pytest.mark.postgres
def test_alembic_upgrade_head_against_optional_postgres_database():
    database_url = os.environ.get("MEMTRACE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("MEMTRACE_TEST_DATABASE_URL not set; migration declaration tests still run")

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env.setdefault("PYTHONPATH", "apps/api")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_orm_metadata_contains_unique_run_local_event_sequence_constraint():
    constraints = {
        constraint.name: tuple(constraint.columns.keys())
        for constraint in Base.metadata.tables["agent_events"].constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert constraints["uq_event_run_seq"] == ("run_id", "sequence_no")


def test_phase4_lifecycle_and_retention_orm_tables_match_plan():
    assert "lifecycle_metadata" in MemoryORM.__table__.c
    assert str(MemoryORM.__table__.c.lifecycle_metadata.server_default.arg) == "'{}'::jsonb"
    assert Base.metadata.tables["memory_lifecycle_audits"] is MemoryLifecycleAuditORM.__table__
    assert Base.metadata.tables["memory_retention_signals"] is MemoryRetentionSignalORM.__table__
    lifecycle_indexes = {index.name: tuple(column.name for column in index.columns) for index in MemoryLifecycleAuditORM.__table__.indexes}
    retention_indexes = {index.name: tuple(column.name for column in index.columns) for index in MemoryRetentionSignalORM.__table__.indexes}
    assert lifecycle_indexes["ix_memory_lifecycle_audits_workspace_memory_created"] == (
        "workspace_id",
        "memory_id",
        "created_at",
    )
    assert retention_indexes["ix_memory_retention_signals_workspace_reflection"] == (
        "workspace_id",
        "reflection_priority",
    )


def test_phase4_memory_versions_and_conflicts_orm_tables_match_plan():
    assert Base.metadata.tables["memory_versions"] is MemoryVersionORM.__table__
    assert Base.metadata.tables["memory_conflicts"] is MemoryConflictORM.__table__
    version_constraints = {
        constraint.name: tuple(constraint.columns.keys())
        for constraint in MemoryVersionORM.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert version_constraints["uq_memory_versions_memory_version_no"] == ("memory_id", "version_no")
    version_indexes = {index.name: tuple(column.name for column in index.columns) for index in MemoryVersionORM.__table__.indexes}
    conflict_indexes = {index.name: tuple(column.name for column in index.columns) for index in MemoryConflictORM.__table__.indexes}
    assert version_indexes["ix_memory_versions_workspace_memory_created"] == (
        "workspace_id",
        "memory_id",
        "created_at",
    )
    assert conflict_indexes["ix_memory_conflicts_workspace_status_created"] == (
        "workspace_id",
        "status",
        "created_at",
    )


def test_phase4_governance_api_key_orm_table_matches_plan():
    assert Base.metadata.tables["api_keys"] is ApiKeyORM.__table__
    assert ApiKeyORM.__table__.c.api_key_id.primary_key
    assert str(ApiKeyORM.__table__.c.roles.server_default.arg) == "'[]'::jsonb"
    constraints = {
        constraint.name: tuple(constraint.columns.keys())
        for constraint in ApiKeyORM.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert constraints["uq_api_keys_key_prefix"] == ("key_prefix",)
    indexes = {index.name: tuple(column.name for column in index.columns) for index in ApiKeyORM.__table__.indexes}
    assert indexes["ix_api_keys_key_prefix"] == ("key_prefix",)
    assert indexes["ix_api_keys_workspace_id"] == ("workspace_id",)
    assert indexes["ix_api_keys_principal_id"] == ("principal_id",)
    assert indexes["ix_api_keys_prefix_revoked"] == ("key_prefix", "revoked_at")


def test_madm_a_maintenance_admin_orm_tables_match_plan():
    assert Base.metadata.tables["maintenance_runs"] is MaintenanceRunORM.__table__
    assert Base.metadata.tables["maintenance_task_attempts"] is MaintenanceTaskAttemptORM.__table__
    assert Base.metadata.tables["admin_action_audits"] is AdminActionAuditORM.__table__
    assert Base.metadata.tables["quota_limits"] is QuotaLimitORM.__table__
    assert str(MaintenanceRunORM.__table__.c.summary.server_default.arg) == "'{}'::jsonb"
    assert str(MaintenanceRunORM.__table__.c.warnings.server_default.arg) == "'[]'::jsonb"
    assert str(MaintenanceTaskAttemptORM.__table__.c.result.server_default.arg) == "'{}'::jsonb"
    assert str(AdminActionAuditORM.__table__.c.audit_metadata.server_default.arg) == "'{}'::jsonb"
    attempt_constraints = {
        constraint.name: tuple(constraint.columns.keys())
        for constraint in MaintenanceTaskAttemptORM.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert attempt_constraints["uq_maintenance_task_attempts_run_operation"] == ("scheduler_run_id", "operation")
    quota_indexes = {index.name: tuple(column.name for column in index.columns) for index in QuotaLimitORM.__table__.indexes}
    assert quota_indexes["uq_quota_limits_workspace_unit"] == ("workspace_id", "unit")
    assert quota_indexes["uq_quota_limits_workspace_principal_unit"] == (
        "workspace_id",
        "principal_id",
        "unit",
    )
    assert QuotaLimitORM.__table__.indexes


def test_phase4_lifecycle_and_retention_migrations_declare_chain_and_operations():
    lifecycle = _load_lifecycle_migration()
    retention = _load_retention_migration()
    assert lifecycle.revision == "0008_phase4_lifecycle"
    assert lifecycle.down_revision == "0007_i7_retained_negative_evidence"
    assert retention.revision == "0009_memory_retention_signals"
    assert retention.down_revision == "0008_phase4_lifecycle"
    lifecycle_source = LIFECYCLE_MIGRATION_PATH.read_text()
    retention_source = RETENTION_MIGRATION_PATH.read_text()
    assert 'op.add_column(\n        "memory_items"' in lifecycle_source
    assert '"memory_lifecycle_audits"' in lifecycle_source
    assert "ix_memory_lifecycle_audits_workspace_memory_created" in lifecycle_source
    assert '"memory_retention_signals"' in retention_source
    assert "ix_memory_retention_signals_workspace_reflection" in retention_source


def test_phase4_versions_conflicts_migration_declares_chain_and_operations():
    migration = _load_versions_conflicts_migration()
    assert migration.revision == "0010_memory_versions_conflicts"
    assert migration.down_revision == "0009_memory_retention_signals"
    source = VERSIONS_CONFLICTS_MIGRATION_PATH.read_text()
    assert '"memory_versions"' in source
    assert '"memory_conflicts"' in source
    assert "uq_memory_versions_memory_version_no" in source
    assert "ix_memory_versions_workspace_memory_created" in source
    assert "ix_memory_conflicts_workspace_status_created" in source


def test_phase4_governance_migration_declares_chain_and_operations():
    migration = _load_governance_migration()
    assert migration.revision == "0011_governance"
    assert migration.down_revision == "0010_memory_versions_conflicts"
    source = GOVERNANCE_MIGRATION_PATH.read_text()
    assert '"api_keys"' in source
    assert "uq_api_keys_key_prefix" in source
    assert "ix_api_keys_key_prefix" in source
    assert "ix_api_keys_workspace_id" in source
    assert "ix_api_keys_principal_id" in source
    assert "ix_api_keys_prefix_revoked" in source
    assert "server_default=sa.text(\"'[]'::jsonb\")" in source


def test_madm_a_maintenance_admin_migration_declares_chain_and_operations():
    migration = _load_maintenance_admin_migration()
    assert migration.revision == "0012_maintenance_admin_governance"
    assert migration.down_revision == "0011_governance"
    source = MAINTENANCE_ADMIN_MIGRATION_PATH.read_text()
    assert '"maintenance_runs"' in source
    assert '"maintenance_task_attempts"' in source
    assert '"admin_action_audits"' in source
    assert '"quota_limits"' in source
    assert "uq_maintenance_task_attempts_run_operation" in source
    assert "uq_quota_limits_workspace_unit" in source
    assert "postgresql_where=sa.text(\"principal_id IS NULL\")" in source
    assert "uq_quota_limits_workspace_principal_unit" in source
    assert "postgresql_where=sa.text(\"principal_id IS NOT NULL\")" in source
    assert "server_default=sa.text(\"'{}'::jsonb\")" in source
    assert "server_default=sa.text(\"'[]'::jsonb\")" in source


def test_security_consistency_migration_adds_unique_run_local_event_sequence_index():
    migration = _load_hardening_migration()
    assert migration.revision == "0006_security_consistency_hardening"
    assert migration.down_revision == "0005_context_compaction"

    source = HARDENING_MIGRATION_PATH.read_text()
    assert "uq_agent_events_run_sequence_no" not in source
    assert "H5 sequence uniqueness is already enforced by 0001_initial" in source
    assert "op.create_unique_constraint" not in source
    assert "op.drop_constraint" not in source


def test_security_consistency_migration_adds_retrieval_policy_snapshot_columns():
    source = HARDENING_MIGRATION_PATH.read_text()
    assert 'op.add_column("memory_access_logs", sa.Column("policy_version", sa.String(), nullable=True))' in source
    assert 'op.add_column("memory_access_logs", sa.Column("policy_hash", sa.String(), nullable=True))' in source
    assert 'op.add_column("memory_access_logs", sa.Column("policy_snapshot", postgresql.JSONB(), nullable=True))' in source
    assert 'op.drop_column("memory_access_logs", "policy_snapshot")' in source
    assert 'op.drop_column("memory_access_logs", "policy_hash")' in source
    assert 'op.drop_column("memory_access_logs", "policy_version")' in source


def test_phase3a_migration_declares_expected_revision_and_schema_operations():
    migration = _load_migration()
    assert migration.revision == "0004_phase3a_observability"
    assert migration.down_revision == "0003_memory_superseded_by"

    source = MIGRATION_PATH.read_text()
    assert '"memory_access_logs"' in source
    assert 'sa.Column("top_k", sa.Integer(), nullable=False, server_default="10")' in source
    assert '"eval_cases"' in source
    assert '"eval_runs"' in source
    assert '"eval_results"' in source
    assert 'op.create_index("ix_eval_results_run_id", "eval_results", ["run_id"])' in source
    assert 'op.create_index("ix_eval_results_access_id", "eval_results", ["access_id"])' in source
    assert 'op.drop_index("ix_eval_results_access_id", table_name="eval_results")' in source
    assert 'op.drop_index("ix_eval_results_run_id", table_name="eval_results")' in source
    assert 'op.drop_table("eval_results")' in source
    assert 'op.drop_column("memory_access_logs", "top_k")' in source


def test_compaction_log_table_present_after_upgrade():
    assert Base.metadata.tables["context_compaction_logs"] is ContextCompactionORM.__table__
    assert ContextCompactionORM.__table__.c.compaction_id.primary_key
    assert ContextCompactionORM.__table__.c.access_id.index is True
    assert ContextCompactionORM.__table__.c.run_id.index is True
    assert ContextCompactionORM.__table__.c.retained_facts.default is not None
    assert ContextCompactionORM.__table__.c.retained_negative_evidence.default is not None
    assert str(ContextCompactionORM.__table__.c.retained_negative_evidence.server_default.arg) == "'[]'::jsonb"
    assert ContextCompactionORM.__table__.c.source_memory_ids.default is not None
    assert ContextCompactionORM.__table__.c.warnings.default is not None


def test_context_compaction_log_orm_indexes_match_migration_names():
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in ContextCompactionORM.__table__.indexes
    }
    assert indexes["ix_context_compaction_logs_access_id"] == ("access_id",)
    assert indexes["ix_context_compaction_logs_run_id"] == ("run_id",)
    assert indexes["ix_context_compaction_logs_workspace_created"] == ("workspace_id", "created_at")
    assert "ix_context_compaction_logs_workspace_id" not in indexes


def test_context_compaction_migration_declares_expected_revision_and_schema_operations():
    migration = _load_compaction_migration()
    assert migration.revision == "0005_context_compaction"
    assert migration.down_revision == "0004_phase3a_observability"

    source = COMPACTION_MIGRATION_PATH.read_text()
    assert '"context_compaction_logs",' in source
    assert 'sa.Column("compaction_id", sa.String(), nullable=False)' in source
    assert 'sa.Column("retained_facts", postgresql.JSONB(), nullable=False, server_default="[]")' in source
    assert 'op.create_index("ix_context_compaction_logs_access_id", "context_compaction_logs", ["access_id"])' in source
    assert 'op.create_index("ix_context_compaction_logs_workspace_created", "context_compaction_logs", ["workspace_id", "created_at"])' in source
    assert 'op.create_index("ix_context_compaction_logs_run_id", "context_compaction_logs", ["run_id"])' in source
    assert 'op.drop_index("ix_context_compaction_logs_workspace_created", table_name="context_compaction_logs")' in source
    assert 'op.drop_index("ix_context_compaction_logs_run_id", table_name="context_compaction_logs")' in source
    assert 'op.drop_index("ix_context_compaction_logs_access_id", table_name="context_compaction_logs")' in source
    assert 'op.drop_table("context_compaction_logs")' in source


def test_i7_migration_adds_retained_negative_evidence_jsonb_column():
    migration = _load_i7_migration()
    assert migration.revision == "0007_i7_retained_negative_evidence"
    assert migration.down_revision == "0006_security_consistency_hardening"

    source = I7_MIGRATION_PATH.read_text()
    assert '"context_compaction_logs",' in source
    assert '"retained_negative_evidence"' in source
    assert "postgresql.JSONB" in source
    assert "nullable=False" in source
    assert "server_default=sa.text(\"'[]'::jsonb\")" in source
    assert 'op.drop_column("context_compaction_logs", "retained_negative_evidence")' in source
