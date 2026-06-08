---
name: prepare-coding-task
description: Use before starting actual implementation in a pre-code project to confirm scope, framework, module boundaries, and first files to create.
---

## Goal

Prepare a concrete coding task from the project design without overbuilding.

## Required Reading

Read:
- `.ai/PROJECT_BRIEF.md`
- `.ai/MVP_SCOPE.md`
- `.ai/ARCHITECTURE_SUMMARY.md`
- `.ai/IMPLEMENTATION_PLAN.md`
- `.ai/REQUIREMENTS.md`
- `.ai/OPEN_QUESTIONS.md`
- `AGENTS.md`

## Output

Before coding, produce:
1. The exact task to implement
2. Why this is the next correct task
3. What will be created
4. What will not be created
5. Data model or interface sketch
6. Test plan
7. Rollback or simplification path
8. Questions that block implementation

## Rules

- Do not implement if the language/framework/package manager is still undecided.
- Do not create a large scaffold unless the MVP requires it.
- Prefer a minimal foundation that can grow.
- Prefer interfaces and data models before advanced runtime behavior.