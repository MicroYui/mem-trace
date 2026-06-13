from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.runtime.models import MemoryScope, MemoryType


PROJECT_RUNTIME = "project.runtime"
PROJECT_RUNTIME_EXCLUDED = "project.runtime.excluded"
PROJECT_PACKAGE_MANAGER = "project.package_manager"


class MemoryKeyCardinality(str, Enum):
    single = "single"
    multi = "multi"


@dataclass(frozen=True, slots=True)
class MemoryKeySpec:
    key: str
    memory_type: MemoryType
    scope: MemoryScope
    cardinality: MemoryKeyCardinality
    description: str
    aliases: tuple[str, ...] = ()
    excluded_key: str | None = None
    prompt_examples: tuple[str, ...] = ()
    allow_free_form_children: bool = False
    llm_extractable: bool = True


@dataclass(frozen=True, slots=True)
class MemoryKeyNormalization:
    key: str
    spec: MemoryKeySpec | None
    free_form: bool
    changed: bool
    warning: str | None = None


KEY_SPECS: tuple[MemoryKeySpec, ...] = (
    MemoryKeySpec(
        key=PROJECT_RUNTIME,
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="JavaScript/runtime choice such as bun/node/deno",
        aliases=("project.js_runtime", "project.node_runtime"),
        excluded_key=PROJECT_RUNTIME_EXCLUDED,
        prompt_examples=("bun", "node", "deno"),
    ),
    MemoryKeySpec(
        key=PROJECT_RUNTIME_EXCLUDED,
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.multi,
        description="Umbrella execution-tool exclusions for the current MVP, including runtimes and package managers the project should not use; split package-manager exclusions later only if product semantics require it",
        prompt_examples=("npm", "node", "deno"),
    ),
    MemoryKeySpec(
        key=PROJECT_PACKAGE_MANAGER,
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="JavaScript package manager choice",
        aliases=("project.pkg_manager",),
        prompt_examples=("npm", "pnpm", "yarn", "bun"),
    ),
    MemoryKeySpec(
        key="project.language",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="Primary programming language",
        aliases=("project.lang",),
        excluded_key="project.language.excluded",
        prompt_examples=("python", "go", "typescript"),
    ),
    MemoryKeySpec(
        key="project.language.excluded",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.multi,
        description="Programming languages the project should not use",
    ),
    MemoryKeySpec(
        key="project.database",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="Primary database",
        excluded_key="project.database.excluded",
        prompt_examples=("postgres", "mysql", "sqlite"),
    ),
    MemoryKeySpec(
        key="project.database.excluded",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.multi,
        description="Databases the project should not use",
    ),
    MemoryKeySpec(
        key="project.test_framework",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="Preferred test framework",
        prompt_examples=("pytest", "vitest", "jest"),
    ),
    MemoryKeySpec(
        key="project.test_command",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="Preferred test command",
        prompt_examples=("uv run pytest -q", "bun test"),
    ),
    MemoryKeySpec(
        key="project.formatting",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="Formatting or linting tool",
        prompt_examples=("ruff", "prettier", "black"),
    ),
    MemoryKeySpec(
        key="tool.command.failed",
        memory_type=MemoryType.tool_evidence,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.multi,
        description="Failed tool command evidence; run-local identity is carried by MemoryItem.run_id/source ids because MemoryScope has no run enum",
        llm_extractable=False,
    ),
    MemoryKeySpec(
        key="endpoint.current",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="Current endpoint for a capability",
    ),
    MemoryKeySpec(
        key="endpoint.deprecated",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.multi,
        description="Deprecated endpoint marker",
    ),
    MemoryKeySpec(
        key="user.preference.*",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.multi,
        description="Explicit user preference namespace for safe free-form child keys",
        allow_free_form_children=True,
    ),
)

_BY_KEY = {spec.key: spec for spec in KEY_SPECS if not spec.key.endswith(".*")}
_ALIASES = {alias: spec.key for spec in KEY_SPECS for alias in spec.aliases}
_WILDCARD_SPECS = tuple(spec for spec in KEY_SPECS if spec.allow_free_form_children and spec.key.endswith(".*"))
_WILDCARD_PREFIXES = tuple(spec.key[:-1] for spec in KEY_SPECS if spec.allow_free_form_children and spec.key.endswith("*"))
_SAFE_FREE_FORM_PREFIXES = ("project.", "user.preference.", "endpoint.")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_][a-z0-9_\-]*)+$")
_SECRET_KEY_TERMS = (
    "api_key",
    "apikey",
    "access_key",
    "password",
    "passwd",
    "token",
    "secret",
    "private_key",
    "credential",
)


def canonical_key_specs() -> tuple[MemoryKeySpec, ...]:
    return KEY_SPECS


def normalize_memory_key(key: str, *, free_form: bool = False) -> MemoryKeyNormalization:
    cleaned = (key or "").strip().lower()
    canonical = _ALIASES.get(cleaned, cleaned)
    spec = _BY_KEY.get(canonical)
    if spec is not None:
        return MemoryKeyNormalization(key=spec.key, spec=spec, free_form=False, changed=spec.key != key)
    if not free_form:
        return MemoryKeyNormalization(
            key=canonical,
            spec=None,
            free_form=False,
            changed=canonical != key,
            warning="unknown memory key requires free_form=true",
        )
    if not _is_safe_free_form_key(canonical):
        return MemoryKeyNormalization(
            key=canonical,
            spec=None,
            free_form=False,
            changed=canonical != key,
            warning="unsafe free-form memory key",
        )
    return MemoryKeyNormalization(key=canonical, spec=_wildcard_spec_for(canonical), free_form=True, changed=canonical != key)


def _wildcard_spec_for(key: str) -> MemoryKeySpec | None:
    for spec in _WILDCARD_SPECS:
        if key.startswith(spec.key[:-1]):
            return spec
    return None


def canonical_memory_key(key: str | None) -> str | None:
    if key is None:
        return None
    return normalize_memory_key(key, free_form=True).key


def same_memory_key_identity(left: str | None, right: str | None) -> bool:
    return canonical_memory_key(left) == canonical_memory_key(right)


def is_single_valued_key(key: str | None) -> bool:
    if not key:
        return False
    normalized = normalize_memory_key(key, free_form=False)
    return normalized.spec is not None and normalized.spec.cardinality == MemoryKeyCardinality.single


def render_llm_extraction_key_prompt() -> str:
    lines: list[str] = []
    for spec in sorted((item for item in KEY_SPECS if item.llm_extractable), key=lambda item: item.key):
        aliases = f" aliases: {', '.join(spec.aliases)}." if spec.aliases else ""
        examples = f" examples: {', '.join(spec.prompt_examples)}." if spec.prompt_examples else ""
        excluded = f" excluded key: {spec.excluded_key}." if spec.excluded_key else ""
        lines.append(
            f'- "{spec.key}" ({spec.cardinality.value}, {spec.memory_type.value}, {spec.scope.value}): '
            f"{spec.description}.{aliases}{excluded}{examples}"
        )
    lines.append('- Unknown durable concepts require "free_form": true and must use a safe dotted key under project.*, endpoint.*, or user.preference.*.')
    return "\n".join(lines)


def _is_safe_free_form_key(key: str) -> bool:
    if not _KEY_RE.match(key):
        return False
    secret_check_key = key.replace("-", "_")
    if any(term in secret_check_key for term in _SECRET_KEY_TERMS):
        return False
    return key.startswith(_SAFE_FREE_FORM_PREFIXES) or key.startswith(_WILDCARD_PREFIXES)


__all__ = [
    "KEY_SPECS",
    "PROJECT_PACKAGE_MANAGER",
    "PROJECT_RUNTIME",
    "PROJECT_RUNTIME_EXCLUDED",
    "MemoryKeyCardinality",
    "MemoryKeyNormalization",
    "MemoryKeySpec",
    "canonical_key_specs",
    "canonical_memory_key",
    "is_single_valued_key",
    "normalize_memory_key",
    "render_llm_extraction_key_prompt",
    "same_memory_key_identity",
]
