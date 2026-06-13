from __future__ import annotations

from app.memory.key_ontology import (
    PROJECT_PACKAGE_MANAGER,
    PROJECT_RUNTIME,
    PROJECT_RUNTIME_EXCLUDED,
    MemoryKeyCardinality,
    canonical_key_specs,
    is_single_valued_key,
    normalize_memory_key,
    render_llm_extraction_key_prompt,
)
from app.runtime.models import MemoryType


def test_package_manager_is_distinct_canonical_key_from_runtime():
    normalized = normalize_memory_key("project.package_manager")
    assert normalized.key == PROJECT_PACKAGE_MANAGER
    assert normalized.changed is False
    assert normalized.free_form is False
    assert normalized.spec is not None


def test_runtime_alias_normalizes_to_canonical_runtime_key():
    normalized = normalize_memory_key("project.js_runtime")
    assert normalized.key == PROJECT_RUNTIME
    assert normalized.changed is True
    assert normalized.free_form is False
    assert normalized.spec is not None


def test_runtime_cardinality_and_excluded_cardinality():
    assert is_single_valued_key(PROJECT_RUNTIME) is True
    assert is_single_valued_key(PROJECT_PACKAGE_MANAGER) is True
    assert is_single_valued_key("project.pkg_manager") is True
    excluded = normalize_memory_key(PROJECT_RUNTIME_EXCLUDED)
    assert excluded.spec is not None
    assert excluded.spec.cardinality == MemoryKeyCardinality.multi
    assert is_single_valued_key(PROJECT_RUNTIME_EXCLUDED) is False


def test_unknown_key_without_free_form_is_rejected():
    normalized = normalize_memory_key("project.unknown_concept")
    assert normalized.spec is None
    assert normalized.free_form is False
    assert normalized.warning == "unknown memory key requires free_form=true"


def test_safe_free_form_key_is_allowed_under_known_prefix():
    normalized = normalize_memory_key("user.preference.editor", free_form=True)
    assert normalized.key == "user.preference.editor"
    assert normalized.spec is not None
    assert normalized.spec.key == "user.preference.*"
    assert normalized.spec.memory_type.value == "project"
    assert normalized.spec.scope.value == "workspace"
    assert normalized.free_form is True
    assert normalized.warning is None


def test_secret_like_free_form_key_is_rejected():
    normalized = normalize_memory_key("project.api_key", free_form=True)
    assert normalized.spec is None
    assert normalized.free_form is False
    assert normalized.warning == "unsafe free-form memory key"


def test_secret_like_free_form_key_with_dash_is_rejected():
    for key in ("project.api-key", "project.private-key", "user.preference.password-hint"):
        normalized = normalize_memory_key(key, free_form=True)
        assert normalized.spec is None
        assert normalized.free_form is False
        assert normalized.warning == "unsafe free-form memory key"


def test_free_form_wildcard_key_is_rejected():
    normalized = normalize_memory_key("project.*", free_form=True)
    assert normalized.spec is None
    assert normalized.free_form is False
    assert normalized.warning == "unsafe free-form memory key"


def test_prompt_rendering_is_stable_and_uses_canonical_keys():
    prompt = render_llm_extraction_key_prompt()
    assert '"project.runtime"' in prompt
    assert '"project.package_manager"' in prompt
    assert prompt.index('"project.runtime"') < prompt.index('"project.runtime.excluded"')
    assert "user.preference.*" in prompt
    assert '"tool.command.failed"' not in prompt


def test_canonical_key_specs_cover_controlled_schema_contract():
    specs = {spec.key: spec for spec in canonical_key_specs()}

    for key in (
        PROJECT_RUNTIME,
        PROJECT_RUNTIME_EXCLUDED,
        PROJECT_PACKAGE_MANAGER,
        "project.test_command",
        "project.database",
        "tool.command.failed",
        "endpoint.current",
        "endpoint.deprecated",
        "user.preference.*",
    ):
        assert key in specs

    assert specs[PROJECT_RUNTIME].cardinality == MemoryKeyCardinality.single
    assert specs[PROJECT_PACKAGE_MANAGER].cardinality == MemoryKeyCardinality.single
    assert specs["project.test_command"].cardinality == MemoryKeyCardinality.single
    assert specs["project.database"].cardinality == MemoryKeyCardinality.single
    assert specs["endpoint.current"].cardinality == MemoryKeyCardinality.single

    assert specs[PROJECT_RUNTIME_EXCLUDED].cardinality == MemoryKeyCardinality.multi
    assert specs["endpoint.deprecated"].cardinality == MemoryKeyCardinality.multi
    assert specs["tool.command.failed"].cardinality == MemoryKeyCardinality.multi
    assert specs["user.preference.*"].cardinality == MemoryKeyCardinality.multi

    assert specs["tool.command.failed"].memory_type == MemoryType.tool_evidence
    assert specs["tool.command.failed"].llm_extractable is False
