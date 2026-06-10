---
name: sync-design-docs
description: Use when docs/design/architecture.md, docs/design/mvp.md, docs/design/draft.md, or other design documents changed and the project memory under .ai/ must be refreshed.
---

## Goal

Synchronize design documents into the structured project memory files under `.ai/`.

## Inputs

Read all relevant design documents:
- `docs/design/architecture.md`
- `docs/design/mvp.md`
- `docs/design/draft.md`
- any Markdown file related to architecture, roadmap, MVP, requirements, or implementation planning

Also read existing `.ai/` files before editing them.

## Procedure

1. Identify what changed in the design documents.
2. Update `.ai/PROJECT_BRIEF.md` only if the overall project goal changed.
3. Update `.ai/MVP_SCOPE.md` if MVP boundaries, features, acceptance criteria, or out-of-scope items changed.
4. Update `.ai/ARCHITECTURE_SUMMARY.md` if modules, data flow, storage, runtime behavior, or boundaries changed.
5. Update `.ai/IMPLEMENTATION_PLAN.md` if phases, task order, dependencies, or first implementation slice changed.
6. Update `.ai/OPEN_QUESTIONS.md` with unresolved contradictions or missing details.
7. Update `.ai/DECISIONS.md` only for durable architectural decisions.
8. Update `.ai/PROJECT_STATE.md` with the sync result and next suggested step.

## Rules

- Do not rewrite files unnecessarily.
- Do not bury conflicts; record them explicitly.
- Do not treat draft ideas as final decisions unless the documents clearly say so.
- Keep `.ai/` files concise and implementation-oriented.