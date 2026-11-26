# Decisions

A lead asks you only what you alone can decide, explains each question in full, and keeps every one in one place. It decides the rest itself and logs it. This page covers how a lead decides whether to ask, the list of topics it never raises, the budget, the one place for pending decisions, drafts you approve before they are built, and how your approval reaches the helpers. How much a lead decides alone is your standing order `decisions.autonomy` ([profiles.md](profiles.md)).

## Asking only real decisions

A lead asks you through one command:

```sh
colony ask "Keep the old settings page?" --default "no" --kind scope \
  --why "It gets 3 visits a week; dropping it removes one route and its tests." \
  --option "keep: nothing changes" --option "drop: one route less, and its tests"
```

Every question has a kind:

| Kind | What it is |
| --- | --- |
| `scope` | What is built: its goal, its size, or what is left out |
| `product` | A product or screen choice no doc settles |
| `stop` | An item on the stop list: spending, a secret, deleting data, a dependency, or a merge |
| `gate` | A draft you approve before it is built |
| `routine` | How to build it: anything a lead can settle from the code, the docs and the team's work |

Your `decisions.autonomy` and the kind decide what the lead does. **Hold** means the lead parks that work until you answer and goes on with other work. **Go** means it asks you and keeps working on its pick, and your answer wins. **Decide** means it doesn't ask: it takes its pick and logs it.

| Kind | `ask` | `routine` (the default) | `unattended` |
| --- | --- | --- | --- |
| `routine` | hold | decide | decide |
| `product` | hold | go | decide |
| `scope` | hold | go | go |
| `stop`, `gate` | hold | hold | hold |

So in the unattended mode a lead asks you only about scope, and a stop or gate question still always waits for your yes. With `decisions.without_answer = "default"`, a question past `decisions.answer_wait_minutes` takes the lead's pick for good; `colony decisions` says so, and the lead records it with `colony answer D<n> --took-default`. A stop or gate question never takes its pick.

## Checking the team's work first

Before a question reaches you, `colony ask` looks for what the team already has on it, and stops when it finds something:

- an earlier decision on this computer that asked the same question and has its answer;
- open issues and pull requests that match the question's words;
- a live lead whose folders the question names, which the lead asks first with `colony say`.

The lead reads what it found, and asks you only when that doesn't answer it, by running the same command again with `--checked`.

## Topics never raised, and the budget

`decisions.never_raise` is the list of topics a lead never raises with you. `colony never-raise "<topic>"` adds one to your personal profile, `--remove` takes it off, `--team` writes the team's list, and `colony never-raise` alone shows the list. A question about a topic on it is never asked: the lead decides it itself, and logs that it wasn't raised. When it needs your yes, a stop or gate question, it isn't done either, and waits until you raise it.

`budgets.dollars_per_day` is what a session may spend a day on paid services and model calls without your yes, 0 by default. `colony spend <dollars> "<what>"` checks a spend against what this computer's sessions spent today, and records it. Past the budget it ends with 1 and records nothing; the lead asks you with a `stop` question, and on your yes runs it again with `--approved D<n>`. Spends are kept in `~/.colony/<project>/spend.json`.

## One place for pending decisions

Every question goes on your `Needs <You>` issue as one line, `for <lead>: <You> decides: D<n>: <question> Default: <pick> (from <lead>)`, with its full explanation attached under it: the kind, why it needs you, each choice and what it means, the lead's pick, whether it holds the work, and how to answer. Answer with a comment `for <lead>: D<n> <your answer>`, or tell the lead in chat.

The lead records your answer exactly as you said it, every word and space: `colony answer D<n> "<your words>"`, with `--on-issue` when you answered there. The record goes on the same issue, so the issue holds every question and every answer. `colony decisions` lists what waits on you, with how long each has waited and what to do once one is past its wait; `--log` lists what the lead decided alone; `--all` lists every one; `--json` prints them for a script. The ledger lives in `~/.colony/<project>/decisions.json`, and the briefing a lead starts with names the oldest.

Other sessions, such as the spec agent and the researcher, still post their questions with `colony needs`. Only a lead runs `ask` and `answer`.

## Drafts first

Some work is drafted, shown to you, and built only after your yes: the kinds your `decisions.gates` names, such as new screens, and any task group made with `colony plan group … --draft`. The lead asks a `gate` question with the draft linked, and holds the build. When you answer, `colony answer` reads your words: a yes builds it, a no builds nothing of it, and anything unclear makes the lead ask once more. A group's yes is recorded with `colony plan approve <group> "<your words>"`.

## Approvals reach helpers

You give an approval yourself, at your own terminal. No agent can give one for you, and nothing posted on the code host carries one.

When a helper will need to run something you have said yes to, such as the staging migration, run this in your own terminal, outside any agent's session:

```sh
colony approve "Bash(make migrate-staging:*)" --for 4
```

It shows what it lets through, for whom and for how long, and asks you to type `yes`. From then until it expires, the PreToolUse hook lets a matching call of your leads and helpers on this computer through their permission check, so no helper waits on a permission question you already answered. Each helper's first prompt names the approvals that cover it.

- **Only at your own terminal.** `colony approve` refuses unless its input and output are an interactive terminal, and nothing in its environment says an agent's session runs it (`CLAUDECODE`, `COLONY_SESSION` or `CLAUDE_CODE_SESSION_ID`). An agent can list the approvals, `colony approve --list`, and never make or revoke one. A lead that needs one asks you to run the command.
- **On this computer only.** An approval lives in `~/.colony/<project>/approvals.json`, readable by you alone, and covers your own sessions here: your leads and their helpers, or with `--lead <lead>` one lead and its helpers, or with `--only <session>` named sessions. Another person's sessions on a shared computer never use it. A helper on another computer needs your approval there.
- **A rule** is `Bash(<command>)` for one exact command, `Bash(<command>:*)` for a command and its arguments, `WebFetch(domain:<domain>)` for one domain, or a file tool, `Edit`, `Write`, `MultiEdit`, `NotebookEdit` or `Read`, with a path pattern inside the repo, such as `Edit(docs/**)`. Only `Read`, `Glob`, `Grep` and `WebSearch`, which change nothing, may stand alone. Every other rule is refused: a tool with no argument, an MCP tool, a wildcard command, a path with `..`, `~` or `/` at its start. The hook checks each rule again, so a rule written into the file by hand that fails the check lets nothing through.
- **A Bash call matches only alone.** A command joined to others with `&&`, `;`, `|`, a redirect or `$(…)` never matches, so an approval can't carry another command through.
- **A path matches segment by segment.** The path is resolved against the session's folder, with its links followed, and must stay inside it. `*` matches within one folder level, and `**` across levels, so `Edit(docs/*)` covers `docs/a.md` but not `docs/deep/a.md`.
- **It only ever allows.** A guard that refuses a call, such as the wait guard or the merge guard, still refuses it: Claude Code takes a hook's refusal over its allow. A merge still needs its own yes, read from GitHub ([safety.md](safety.md)).
- **It lasts** 8 hours by default, at most 24 (`--for <hours>`). `colony approve --revoke A<n>`, at your terminal, ends one at once.

The terminal check stops an agent's command from approving, not an agent that sets out to get around it, such as one that edits the file itself: on your own computer, the file is as safe as your account. The hook costs nothing while no approval is live: it checks for `~/.colony/approvals.live` before it runs.
