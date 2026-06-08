---
name: update-project-state
description: Use when the user changes requirements, finishes a session, resumes work, or asks to update project memory.
---

## Goal

Keep `.ai/PROJECT_STATE.md` and related project memory files current.

## Required Reading

Read:
- `.ai/PROJECT_STATE.md`
- `.ai/REQUIREMENTS.md`
- `.ai/IMPLEMENTATION_PLAN.md`
- `.ai/OPEN_QUESTIONS.md`

## Procedure

1. Identify the latest user intent.
2. Update `.ai/PROJECT_STATE.md` with:
   - current goal
   - current progress
   - completed work
   - next steps
   - open risks
   - last updated date
3. Update `.ai/REQUIREMENTS.md` if the active task changed.
4. Update `.ai/DECISIONS.md` if a durable decision was made.
5. Update `.ai/PITFALLS.md` if a reusable warning was discovered.
6. Do not rewrite stable design summaries unless the user changed the design.

## Rules

- PROJECT_STATE is a current snapshot, not a chat log.
- Keep old history only when it helps future work.
- Prefer concise bullet points.