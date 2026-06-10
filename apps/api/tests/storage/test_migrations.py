"""Alembic migration schema tests for Phase 3-A persistence."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from app.storage.orm import AccessLogORM, Base, EvalCaseORM, EvalResultORM, EvalRunORM


ROOT = Path(__file__).resolve().parents[4]
MIGRATION_PATH = ROOT / "migrations" / "versions" / "0004_phase3a_observability.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0004_phase3a_observability", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_orm_metadata_contains_access_top_k_and_eval_tables():
    assert AccessLogORM.__table__.c.top_k.default.arg == 10
    assert Base.metadata.tables["eval_cases"] is EvalCaseORM.__table__
    assert Base.metadata.tables["eval_runs"] is EvalRunORM.__table__
    assert Base.metadata.tables["eval_results"] is EvalResultORM.__table__

    assert EvalCaseORM.__table__.c.eval_case_id.primary_key
    assert EvalRunORM.__table__.c.workspace_id.index is True
    assert EvalResultORM.__table__.c.eval_run_id.index is True
    assert EvalResultORM.__table__.c.eval_case_id.index is True
    assert EvalResultORM.__table__.c.run_id.index is True
    assert EvalResultORM.__table__.c.access_id.index is True


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
