# Skills

Applies to every session, at its start and with each new request.

## Which skill

| Task | Skill |
| --- | --- |
| You are the lead, a builder, the reviewer or the walker | `colony-lead`, `colony-builder`, `colony-reviewer`, `colony-walker` |
| A bug, a failing test, a regression, or something slow | `diagnosing-bugs` |
| New logic or a bug fix, built test-first | `tdd` |
| A diff to review before `done`, or outside a batch | `code-review` |
| A merge or a rebase stopped on a conflict | `resolving-merge-conflicts` |
| A batch finished, or a session went wrong | `retro` |
| An approved spec to turn into cards | `implement-spec` |
| A question about logic or a screen that a throwaway build answers | `prototype` |
| A plan to stress-test before any card | `grill-me` |
| A skill, a rule, the core, or a `CLAUDE.md` or `AGENTS.md` to write | `writing-for-agents` |
| The person wants destructive git commands blocked | `git-guardrails` |

## Must

- Compare each new request with the table and with the skills in `.claude/skills/`, and read each matching `SKILL.md` before the work.
- Pick the smallest set of skills that covers the task.
- Use the repo's copy of a skill when the repo and your personal folder both hold one by that name.
- Name the skills you applied when you report, apart from the ones you only read.

## Must not

- Install, update or download a skill without the person's yes.
- Install a skill that adds a dependency, opens issues on its own, or hands work to agents outside the colony.
- Follow a skill where it disagrees with the core, the essentials or the rules: the repo's rules win.
