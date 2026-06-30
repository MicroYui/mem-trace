"""Deterministic task-intent ranking profiles (ROADMAP §4 / architecture §6.5).

The default retrieval blend treats every memory type alike. A coding agent's
*intent*, though, shifts what matters: while debugging, tool-evidence and the
current state matter most; while implementing, project constraints dominate.
``ranking_profiles`` map a task intent to a small set of per-memory-type score
multipliers so retrieval can re-weight candidates accordingly.

Everything here is deterministic and side-effect free. It is wired into the
controller behind a default-off setting
(``MEMTRACE_RETRIEVAL_RANKING_PROFILES_ENABLED=false``), so the default blend —
and benchmark/replay reproducibility — is unchanged until explicitly enabled.
The selected profile is recorded in the retrieval policy snapshot only when on.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RankingProfile:
    """A named set of per-``MemoryType``-value relevance multipliers."""

    name: str
    type_weights: dict[str, float] = field(default_factory=dict)

    def weight_for(self, memory_type_value: str) -> float:
        return self.type_weights.get(memory_type_value, 1.0)


DEFAULT_PROFILE = RankingProfile("default", {})

# Profiles keyed by intent. Multipliers are bounded and conservative so a profile
# re-ranks rather than swamps the base relevance signal.
_PROFILES: dict[str, RankingProfile] = {
    "debug": RankingProfile("debug", {"tool_evidence": 1.3, "working_state": 1.2, "project": 1.1}),
    "implement": RankingProfile("implement", {"project": 1.3, "procedural": 1.15}),
    "review": RankingProfile("review", {"episodic": 1.2, "procedural": 1.2}),
}

# Intent keyword triggers, checked in insertion order (deterministic).
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "debug": ("debug", "fix", "error", "bug", "fail", "crash", "trace", "broken"),
    "implement": ("implement", "build", "add", "feature", "create", "write", "develop", "scaffold"),
    "review": ("review", "explain", "understand", "summarize", "audit", "inspect"),
}


def select_profile(task_intent: str | None) -> RankingProfile:
    """Pick the ranking profile whose keywords match the task intent.

    Deterministic: the first profile (in ``_KEYWORDS`` insertion order) with a
    keyword substring in the lowercased intent wins; otherwise the default.
    """
    if not task_intent:
        return DEFAULT_PROFILE
    low = task_intent.lower()
    for name, keywords in _KEYWORDS.items():
        if any(keyword in low for keyword in keywords):
            return _PROFILES[name]
    return DEFAULT_PROFILE


__all__ = ["RankingProfile", "DEFAULT_PROFILE", "select_profile"]
