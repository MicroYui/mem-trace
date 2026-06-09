---
name: resume-project
description: Use at the start of a new session when the user wants to resume work, asks for current progress/status, or says things like "继续"、"接着做"、"现在做什么"、"resume"、"where were we". Loads the right project-memory files and reports current state plus the next action.
---

## Goal

Let a fresh session quickly recover full context (what this project is, what is
done, what is next) by reading a fixed, minimal set of files instead of guessing.

## Required Reading (in order)

1. `AGENTS.md` — working agreement and which memory files matter.
2. `.ai/PROJECT_STATE.md` — current snapshot: goal, done, verification, risks, next action.
3. `.ai/REQUIREMENTS.md` — the concrete current task and module map.
4. `.ai/IMPLEMENTATION_PLAN.md` — P0/P1/P2 plan and the suggested next coding task.
5. `.ai/OPEN_QUESTIONS.md` — unresolved decisions that may block the next slice.
6. `.ai/DECISIONS.md` and `.ai/PITFALLS.md` — only the latest ADRs / findings, for context. Skim, don't read in full unless needed.

Do NOT load `architecture.md`, `draft.md`, or the full `mvp.md` unless the task
specifically requires the original design docs. They are large; the `.ai/`
files already summarize them.

## Procedure

1. Read the files above.
2. Run, in parallel, to learn the real code state (not just the docs):
   - `git log --oneline -5`
   - `git status --short`
3. If a quick sanity check is cheap and relevant, note the documented test
   command (e.g. `cd apps/api && uv run pytest -q`) but do NOT run it unless the
   user asks or you are about to change code.
4. Report back concisely:
   - **当前状态**: one or two lines (e.g. "P0+P1+pgvector done, committed at `<sha>`, working tree clean").
   - **已完成**: the most recent milestone(s).
   - **下一步候选**: the options from IMPLEMENTATION_PLAN "Suggested Next Coding Task" / PROJECT_STATE "Next Recommended Action", with a recommendation.
   - **待决问题**: any open blocking questions from OPEN_QUESTIONS.
5. Ask the user which direction to take before starting non-trivial work.

## Rules

- Trust `.ai/PROJECT_STATE.md` as the authoritative snapshot; if it conflicts
  with the git log, flag the discrepancy rather than silently picking one.
- Keep the report short — lead with status and the next action, not a file dump.
- Reconcile docs with reality: if `git status` shows uncommitted changes the
  docs don't mention, surface that.
- Do not start coding or destructive actions during resume; this skill is for
  orientation and alignment only.
