# How it works

Puffin Colony runs one loop: you ask, a lead plans, builders build, a gate checks, and you merge one pull request. This page walks through it step by step and names the command or file behind each step.

## The pieces

| Piece | What it is |
| --- | --- |
| **You** | The person. You talk to your lead, answer what it can't decide, and merge. |
| **The lead** | One interactive Claude Code session per person. It plans, hands out work, merges, and runs the gate. |
| **Builders** | Interactive Claude Code sessions, each with a name such as `builder-2`. Each builds one card at a time on its own branch. |
| **Cards** | GitHub issues titled `<builder>: <what>`, each with up to 3 done-when results and the folders it touches. |
| **Lines** | One-sentence issue comments, `for <name>: … (from <name>)`, that the agents use to talk. See [messages.md](messages.md). |
| **The gate** | `colony batch`. It runs the full checks, a fresh reviewer, a browser walk and fixers, round by round, until 0 problems are open. |
| **The PR** | One pull request per batch, into your base branch, for you to merge. |

Everything Colony writes into your repo lives in `.colony/` at its root. Every command finds that root with `git rev-parse --show-toplevel`, so you can run it from any folder in the clone.

## 1. Install

```sh
uv tool install git+https://github.com/Puffin-Calendar/puffin-colony
```

Colony needs Python 3.11 or later, `git`, `gh` and `claude`. It uses `cmux` when it is on your PATH. It has no Python dependencies of its own.

## 2. Setup, the first time

Run `colony` in a repo that has no `.colony/colony.toml`. It starts an interactive Claude Code session in this terminal, whose first message is the setup prompt from the installed package.

**It reads, without asking:**
- the stack, from `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `Gemfile`, `pom.xml` or whatever is there, and the source and test folders;
- the test, lint, typecheck, build and install commands, from those files, a Makefile and `.github/workflows/`. From them it picks a fast check, which a builder runs after each change, and a full check, which runs everything CI runs;
- generated files and the command that rebuilds them;
- the repo's `owner/name` and default branch, with `gh repo view`;
- every `CLAUDE.md` and `AGENTS.md`, whose rules stay;
- the Claude Code settings folders on this computer (`~/.claude` and any `~/.claude-*`), by name only, never their contents;
- your name, from `git config user.name`.

**It asks at most 5 questions,** in one message, each with a default:
1. Who is on the team, and which Claude accounts (settings folders) does each one use?
2. Which branch do PRs go to?
3. Which rules: `lean`, `puffin` or `own`?
4. Any spend limit on model calls inside the app's own evals? Default $0.
5. Anything agents must never do here?

**It writes:**

| File | What it holds |
| --- | --- |
| `.colony/colony.toml` | Your settings. See [configuration.md](configuration.md). |
| `.colony/rules/*.md` | The chosen preset's rules, with your paths and commands filled in. See [presets.md](presets.md). |
| `.colony/rules/project.md` | Your answers to question 5, as must-not lines. |
| `.colony/playbook.md` | The life cycle the lead and the builders follow, with your branch and commands filled in. |
| `.mcp.json`, `.claude/skills/` | The MCPs and skills you accept: Playwright for the walk and Context7 for library docs, and one skill per role. |
| One line in `CLAUDE.md` | `This repo runs Puffin Colony: read .colony/playbook.md.` It adds this only after a yes, and puts it in `AGENTS.md` when only that file exists. |

**It opens a PR.** It commits only those files on a `colony/setup` branch, with the message `chore: set up Puffin Colony`, pushes that branch, and opens a PR into your base branch. It never pushes to the base branch.

Merge the PR, pull, and run `colony` again. `colony --dry-run` shows the setup plan and runs nothing.

## 3. Your lead opens

After setup, `colony` opens your lead.

1. **It works out who you are:** `--person`, else `$COLONY_PERSON`, else the one person `colony.toml` names, else the person whose name matches your git user.
2. **It picks your account with the most room.** Among your accounts (and any marked `person = "any"`), it prefers folders this computer has, then the lowest saved 5-hour usage. With no saved usage, the first account wins.
3. **It sets the session's environment:** `COLONY_SESSION=lead`, `COLONY_PERSON`, `CLAUDE_CONFIG_DIR` (left unset for `~/.claude`, since Claude Code ties a login to that value), the retry watchdog settings, and `CLAUDE_CODE_AUTO_COMPACT_WINDOW=250000`.
4. **It starts Claude Code:**
   ```sh
   claude --remote-control <project>-lead --model <lead model> --effort <lead effort> \
     "Read .colony/playbook.md, Lead section, and start."
   ```
   Remote Control lets you follow the session from the Claude apps under that title.
5. **It opens where it can.** It uses a new cmux workspace when cmux takes its commands (inside cmux). It uses this terminal when you run it at one, or when you pass `--here`. Otherwise, as when a lead opens builders from inside its own session, it starts a background Claude session under Remote Control. You follow that session in the Claude app, or with `claude attach <id>`.

`colony --dry-run` prints the command line and the env names, never their values, and runs nothing.

## 4. The lead writes cards

You tell the lead what you want. It turns each request into cards:

```sh
gh issue create --title "builder-2: dark mode switch in settings" --body "<done-when list and folders>"
```

Each card has up to 3 done-when results and the folders it touches. Cards that touch the same folders go to the same builder, which keeps conflicts down. When the lead knows the files, it names them, because finding code is a large part of a small change.

## 5. Builders build

**The lead opens builders as cards need them.** Up to `max_builders` (default 4) run on this machine:

```sh
colony open builder-2
```

`colony open` uses cmux when it can, and otherwise starts the builder as a background session you can follow in the Claude app. For more builders than one machine should run, the lead prints a `colony join <name>` line for you to paste on another computer. On first use there, `join` says what is missing: a clone of the repo, the `claude` login for the account it picked, or `gh auth`.

A builder's name is lowercase letters, digits, dots and dashes, such as `builder-2`, and it can't be `lead`. Each builder starts with:

```text
Read .colony/playbook.md, Builder section. You are builder-2. Start the wait.
```

**The lead hands out a card** with a line on it: `for builder-2: start this card (from lead)`.

**Each builder then:**
1. keeps `colony wait` running in the background all session;
2. makes the change in its own worktree and branch, `../builder-2-<card>` on `builder-2/<card>`, cut from `origin/<base>`;
3. runs the fast check and fixes what it reports;
4. writes a test for a bug fix or new logic (a style change needs none), and checks touch or layout work in a browser at phone width, 390×844;
5. commits, pushes its branch, and posts `for lead: done, builder-2/41 pushed, <the fast check's last line> (from builder-2)`;
6. takes the next card at once.

Builders run at medium effort by default, write no reports, and start no subagents. They ask no person anything. When unsure, a builder sends the lead a question with its own default and keeps building on that default.

## 6. The lead merges each done card

When a `done` line arrives, the lead merges that branch into the batch so far, so a conflict shows now and not at the end:

```sh
git fetch origin && git worktree add --detach ../next-<batch> origin/<base>    # first card of a batch
git fetch origin && git -C ../next-<batch> merge --no-ff --no-edit origin/<branch>
```

`<batch>` is today's date, such as `2026-11-05`, with `-2` for a second batch that day. On a conflict, the lead aborts the merge and asks the builder to merge the other branch into its own, resolve it, push, and post `done` again.

## 7. The gate loop

Every 3 to 5 done cards, or when you ask, the lead runs the gate in the background:

```sh
colony batch --name 2026-11-05 --card 41=builder-2/41 --card 42=builder-3/42 --card 44=builder-2/44
```

`colony status --name 2026-11-05` shows the round, the open count, the walk, the steps running now, and the minutes so far. `colony batch --dry-run …` prints every branch, command and round-1 prompt, and runs nothing.

### Assemble

1. It fetches `origin` and finds each card's branch, locally or on `origin`.
2. It makes the batch branch `<project>/batch-<name>` in its own worktree under `worktrees`, from `origin/<base>` (or `--from <branch>`).
3. It merges each card with `--no-ff`. A conflict only in `generated` files takes the card's side and runs `regen`. Any other conflict stops the batch.
4. It runs `install` in the new worktree.

### Each round

Three things run in parallel:

- **The checks.** The full `checks` run in the background. A round that changed no `backend_paths` file runs the lighter `web_checks` instead, once a full run has passed.
- **A fresh reviewer.** A new headless session reads the round's diff and checks it against the rubric and the rules. It must try to refute each finding before it reports it. Its report starts with `open: N`, the confirmed problems still open, and lists each one as `path:line — what is wrong — the rule it breaks — the smallest fix`. From round 2, it reviews only that round's diff and marks each earlier finding `fixed` or `open`.
- **A browser walk.** A headless walker starts your stack from a second worktree and walks each card's flows at desktop 1280×800 and phone 390×844, with touch input on the phone, in light and dark. Its report starts with `walk: pass` or `walk: fail`. A round skips the walk when it changes none of the `walk_paths`, unless the last walk failed.

**A round passes** when the checks pass, the reviewer reports `open: 0`, and the walk passed or was skipped.

### Fix

Otherwise every finding becomes a fix item: each review finding, each failed walk flow, and each failing test the check output names. Each item goes to the card whose branch last changed its file. Each card with items gets one fixer, and the fixers run in parallel. Each fixer:

- works on its own branch, `<project>/fix-<batch>-<card>-r<round>`, cut from the batch head;
- fixes the code, adds a test that fails without the fix, and runs the checks;
- commits, and does not push.

The fix branches merge back into the batch, and the next round starts.

### Stop rules

A batch stops, and doesn't open a PR, when:
- the checks fail the same way in two rounds in a row;
- a fixer commits nothing;
- a merge conflicts outside the generated files;
- round `max_rounds` still has findings;
- an agent fails twice, or leaves no valid report twice.

On a stop, it commits its reports to the batch branch and prints `stopped: <why>`. The lead turns the cause into a card for the builder who owns it, and runs a new batch under the next name.

## 8. The pull request

When a round passes, the batch:

1. writes the PR body to `pr.md` and commits the round reports;
2. pushes the batch branch, and only that branch;
3. opens a PR into your base branch, titled `<project>: batch <name> (#41, #42, #44)`.

The PR body holds the cards, open problems by round (such as `7 → 4 → 1 → 0`), a table of each round's open count, walk and checks, the check commands and their result lines, any test files the batch deletes, and a minutes table that sums each kind of step's runs, minutes and cost.

The lead removes `../next-<batch>`, tells you the link, and keeps the other cards moving.

## 9. You merge

The merge is yours. Colony never merges into your base branch, and never pushes to it.

## Where things live

| Where | What |
| --- | --- |
| `.colony/colony.toml`, `.colony/rules/`, `.colony/playbook.md` | Your settings, rules and playbook, committed by setup |
| `.colony/reports/<batch>/` | Each batch's reports: `review-N.md`, `walk-N.md`, `checks-N.md`, `minutes.md`, `result.md`, `pr.md`. Only the `.md` files are committed, to the batch branch. |
| `<worktrees>/<project>-batch-<batch>` | The batch worktree, where the checks run |
| `<worktrees>/<project>-batch-<batch>-walk` | The walker's worktree, detached at each round's head |
| `<worktrees>/<project>-fix-<batch>-<card>-r<round>` | A fixer's worktree, removed after its merge |
| `../<builder>-<card>` | A builder's worktree |
| `../next-<batch>` | The lead's early-merge worktree |
| `~/.colony/<project>/<session>.json` | Each session's wait state: its read time, ETag and lines already seen |

## Commands

You type only `colony`, and `colony join <name>` when the lead asks. The agents run the rest.

| Command | What it does |
| --- | --- |
| `colony` | Setup the first time, then your lead |
| `colony join <name>` | A builder on this computer, after checking what it lacks |
| `colony open <name>` | A builder on this computer, in cmux or as a background session (the lead runs it) |
| `colony wait [--waiting-on N,N]` | Waits for the lines addressed to `$COLONY_SESSION`, prints them, and exits. The lead's `--waiting-on` names the cards whose `done` lines come at once. |
| `colony say <lead-name> "<sentence>"` | A lead's line for another lead, on the `Colony: coordination` issue |
| `colony batch --name <n> --card N=BRANCH …` | The gate loop, to one PR |
| `colony status [--name <n>]` | Where a batch stands; without `--name`, the newest batch |

| Flag | Where | What it does |
| --- | --- | --- |
| `--dry-run` | `colony`, `join`, `open`, `batch` | Prints the plan and runs nothing |
| `--here` | `colony`, `join` | Opens in this terminal even when cmux is on your PATH |
| `--person <name>` | `colony`, `join`, `open`, `batch` | Whose accounts to use, when `colony.toml` names several people |
| `--from <branch>` | `batch` | Builds the batch on this branch instead of `origin/<base>` |
| `--version` | `colony` | Prints the version |
