# Agent Instructions

This is a pre-code project driven by top-level design documents and `.ai/` project memory. Do not assume production code exists or invent unsupported requirements.

Before non-trivial work, read:

- `.ai/PROJECT_BRIEF.md`
- `.ai/MVP_SCOPE.md`
- `.ai/ARCHITECTURE_SUMMARY.md`
- `.ai/PROJECT_STATE.md`

The MVP (P0+P1+P2) is complete. For what remains to be done (future work, deferred features, tech debt, open decisions), read `docs/design/ROADMAP.md` — it is the authoritative backlog and maps every item back to `docs/design/architecture.md` / `docs/design/draft.md` / `.ai/` sources.

Before coding, also read `.ai/REQUIREMENTS.md` and confirm the current task is concrete enough to implement.

After meaningful work, update `.ai/PROJECT_STATE.md` with current state, changed files, and next recommended action. When you complete a `docs/design/ROADMAP.md` item or discover new future work, update `docs/design/ROADMAP.md` too.

Keep AGENTS.md concise and stable. Do not put transient task state, task checklists, or session notes here; use `.ai/PROJECT_STATE.md`, `.ai/OPEN_QUESTIONS.md`, or task-specific notes instead.

