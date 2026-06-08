---
name: plan-implementation-slice
description: Use when selecting the next small implementation task from the design documents and .ai project memory.
---

## Goal

Turn the current project design into a small, testable, low-risk implementation slice.

## Required Reading

Before planning, read:
- `.ai/PROJECT_BRIEF.md`
- `.ai/MVP_SCOPE.md`
- `.ai/ARCHITECTURE_SUMMARY.md`
- `.ai/IMPLEMENTATION_PLAN.md`
- `.ai/PROJECT_STATE.md`
- `.ai/OPEN_QUESTIONS.md`

## Output

Produce:
1. Recommended next slice
2. Why this slice should come first
3. Files or modules likely to be created
4. Data structures or interfaces needed
5. Minimal acceptance criteria
6. Tests needed
7. Risks
8. Out-of-scope items
9. Whether user confirmation is required before coding

## Rules

- Prefer foundation slices before advanced features.
- Prefer vertical slices that can be tested end-to-end.
- Do not start with UI, optimization, distributed deployment, or advanced memory ranking unless MVP requires it.
- If the design is unclear, recommend a clarification or a small prototype instead of inventing architecture.