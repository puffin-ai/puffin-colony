# Skills

Applies to every session, at its start and with each new request, and to the reviewer, who checks the skills a batch claims to have applied.

## Select skills

- The agent must compare each new request with the table below and the skills in `.claude/skills/`, and must read each matching `SKILL.md` before the work. It should pick the smallest set that covers the task.
- The agent must use the repo's copy of a skill when the repo and the personal folder both hold one by that name.
- When the host can't invoke skills, the agent must read the selected `SKILL.md` files directly.

| Task | Skill |
| --- | --- |
| A session opened without a task, or a repo with no `.colony/colony.toml` | `colony-setup` |
| You are the lead, a builder, the reviewer, or the walker | `colony-lead`, `colony-builder`, `colony-reviewer`, `colony-walker` |
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
| A new screen, or a redesign of one | `frontend-design`, when setup installed it, after the web app's essentials |
| A library call you aren't sure of | no skill: `docs.md` |

## Discover missing skills

- The agent must send a capability gap to the lead as a question with its default, and the lead must install or update a skill only with the person's yes, after reading the skill's source.
- No agent may install a skill that hands work to agents outside the colony, opens issues or pull requests on its own, writes its own docs folder, adds a dependency, or brings a second component library.

## Apply the repo's rules

- Where a skill disagrees with the core, an area's essentials, or a rule, the repo's rule wins.
- For a new screen or a redesign, the agent must read the pages that own the behavior before it applies a design skill, and must keep accepted design apart from experiments.

## Report actual use

- The agent must name the skills it applied, apart from those it only read or installed, and must keep the checks it ran apart from the outcomes it didn't verify.

## Why it exists

An agent that skips selection repeats work a skill covers, and one that loads every skill spends its attention on text that doesn't apply.

## What is exempt

Instructions already read in the session, and skills whose triggers don't apply.
