@AGENTS.md

# Claude Code Notes

- Do not import all `.ai/` files by default; load only the required project memory files for the task.
- At the start of a new session, when the user wants to resume or asks for current progress (e.g. "继续"、"现在做什么"、"resume"), use the `resume-project` skill to load the right memory files and report state + next action.
- Use project skills for repeatable workflows such as syncing design docs, planning implementation slices, reviewing agent architecture, updating project state, and preparing coding tasks.
- Prefer small, testable implementation slices once the design questions in `.ai/OPEN_QUESTIONS.md` are resolved.

