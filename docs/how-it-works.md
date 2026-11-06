# How it works

Puffin Colony runs one loop: you ask, a lead plans, builders build, a gate checks, and you merge one pull request. Around the loop sit the knowledge vault, the tiers, the board and the learning step. This page walks through it step by step and names the command or file behind each step. [cycle.md](cycle.md) covers tiers, specs, research, the Needs issue, the board, handover, stats and retro in full.

This is Startup, the whole system. Hack and Solo turn parts of it off, and [Hack and Solo](#hack-and-solo) below says how they differ. [modes.md](modes.md) compares all three.

## The pieces

| Piece | What it is |
| --- | --- |
| **You** | The person. You talk to your lead, answer what it can't decide, and merge. |
| **The lead** | One interactive Claude Code session per person. It picks tiers, plans, hands out work, merges, and runs the gate. |
| **Builders** | Interactive Claude Code sessions, each with a name such as `builder-2`. Each builds one card at a time on its own branch. |
| **The spec agent and the researcher** | Sessions the lead opens with `colony spec` for a FEATURE and `colony research` for an unknown. They write pages in the vault, not code. |
| **Cards** | GitHub issues titled `<builder>: <what>`, each with up to 3 done-when results, the folders it touches, and a prediction. |
| **The board** | A GitHub Project that shows each card's Status, Builder, Tier, State and Last update. |
| **Lines** | One-sentence issue comments, `for <name>: … (from <name>)`, that the agents use to talk. See [messages.md](messages.md). |
| **Your Needs issue** | `Needs <you>`, where the lead posts each decision only you make, with its default. |
| **The gate** | `colony batch`. It runs the full checks, a fresh reviewer, a browser walk and fixers, round by round, until 0 problems are open. |
| **The PR** | One pull request per batch, into your base branch, for you to merge. |
| **The vault** | `knowledge/`, the typed pages that hold what the team decided, built and found out. See [knowledge.md](knowledge.md). |

Everything Colony writes into your repo lives in `.colony/` at its root, apart from the vault and the Claude Code files it merges into. Every command finds that root with `git rev-parse --show-toplevel`, so you can run it from any folder in the clone.

## 1. Install

```sh
uv tool install git+https://github.com/Puffin-Calendar/puffin-colony
```

Colony needs Python 3.11 or later, `git`, `gh` and `claude`. It uses `cmux` when it is on your PATH, and Agent Relay when a core runs on your computer. It has no Python dependencies of its own.

## 2. Setup, the first time

Run `colony` in a repo that has no `.colony/colony.toml`. It starts an interactive Claude Code session in this terminal, whose first message is the setup prompt from the installed package.

**It reads, without asking:**
- the stack, from `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `Gemfile`, `pom.xml` or whatever is there, and the app folders;
- the test, lint, typecheck, build and install commands, from those files, a Makefile and `.github/workflows/`. From them it picks a fast check, which a builder runs after each change, and a full check, which runs everything CI runs;
- generated files and the command that rebuilds them;
- the repo's `owner/name` and default branch, with `gh repo view`;
- every `CLAUDE.md` and `AGENTS.md`, whose rules stay;
- any docs folder, such as `docs/`, `wiki/` or a folder of decision records;
- whether your `gh` login has the project scope the board needs, from the scopes line of `gh auth status`;
- the Claude Code settings folders on this computer (`~/.claude` and any `~/.claude-*`), by name only, never their contents;
- your name, from `git config user.name`.

**It asks the mode first:** `hack`, `solo` or `startup`. The rest of this step is Startup's setup. Hack asks about the team, owners and the demo instead, and Solo asks only the base branch and the rules; see [modes.md](modes.md).

**Then it asks at most 5 questions,** in one message, each with a default:
1. Who is on the team, and which Claude accounts (settings folders) does each one use?
2. Which branch do PRs go to?
3. Which rules: `lean`, `puffin` or `own`?
4. Any spend limit on model calls inside the app's own evals? Default $0.
5. Anything agents must never do here?

Then it shows one yes-or-no list, each item with its default: the MCPs, the role and starter skills, instant messages through Agent Relay (yes when a core runs on this computer), the knowledge vault (at `knowledge/`, or your docs folder adopted in place), the hooks, the board, and the lines that load the core from `CLAUDE.md`.

**It writes:**

| File | What it holds |
| --- | --- |
| `.colony/colony.toml` | Your settings. See [configuration.md](configuration.md). |
| `.colony/core.md`, `<app>/AGENTS.md`, `.colony/rules/*.md` | The chosen preset in three levels: the core, each app's essentials, and the full rules. See [presets.md](presets.md). |
| `.colony/rules/project.md` | Your answers to question 5, as must-not lines. |
| `.colony/playbook.md` | The cycle the lead, the builders, the spec agent and the researcher follow, with your branch and commands filled in. |
| `.colony/prompts/spec.md`, `.colony/prompts/researcher.md` | The briefs the lead gives the spec agent and the researcher. |
| `knowledge/` | The vault: its folders and readmes, the 29 page types in `.types/`, and the decision log. See [knowledge.md](knowledge.md). |
| `.colony/hooks/wait_guard.py`, `.claude/settings.json` | The wait guard and the two posting hooks, merged in with yours. See [safety.md](safety.md#hooks). |
| `.colony/suppressions.json` | Today's count of lint and type suppressions per file, which may only shrink. |
| `.mcp.json`, `.claude/skills/` | The MCPs and skills you accept: Playwright for the walk, Context7 for library docs, the role skills and the starter skills. |
| `.claude/rules/` | Links to the knowledge rules, so each loads when an agent opens a matching file. |
| `CLAUDE.md` | After a yes, an `@.colony/core.md` import at the top and one line that points to the playbook. With only `AGENTS.md`, the lines go there. |

It also makes the board with `colony board init`, after a yes, and puts its link in the PR.

**It opens a PR.** It commits only those files on a `colony/setup` branch, with the message `chore: set up Puffin Colony`, pushes that branch, and opens a PR into your base branch. It never pushes to the base branch.

Merge the PR, pull, and run `colony` again. `colony --dry-run` shows the setup plan and runs nothing.

## 3. Your lead opens

After setup, `colony` opens your lead.

1. **It works out who you are:** `--person`, else `$COLONY_PERSON`, else the one person `colony.toml` names, else the person whose name matches your git user.
2. **It picks your account.** `--account <name>` names one. Otherwise `[project] prefer_account` wins while it has room. Otherwise, among your accounts (and any marked `person = "any"`), it prefers folders this computer has, then the lowest saved 5-hour usage. With no saved usage, the first account wins.
3. **It sets the session's environment:** `COLONY_SESSION=lead`, `COLONY_PERSON`, `CLAUDE_CONFIG_DIR` (left unset for `~/.claude`, since Claude Code ties a login to that value), the retry watchdog settings, and `CLAUDE_CODE_AUTO_COMPACT_WINDOW=250000`.
4. **It starts Claude Code:**
   ```sh
   claude --remote-control <project>-lead --model <lead model> --effort <lead effort> \
     --permission-mode auto "Read .colony/playbook.md, Lead section, and start."
   ```
   Remote Control lets you follow the session from the Claude apps under that title.
5. **It opens where it can.** It uses a new cmux workspace when cmux takes its commands (inside cmux). It uses this terminal when you run it at one, or when you pass `--here`. Otherwise, as when a lead opens builders from inside its own session, it starts a background Claude session under Remote Control. You follow that session in the Claude app, or with `claude attach <id>`.

The lead first runs `colony handover --read`. When an earlier lead left a handover, it carries on from its `next:` line.

`colony --dry-run` prints the command line and the env names, never their values, and runs nothing.

## 4. The lead sizes the request

You tell the lead what you want. It picks a tier before it writes a card:

- **TINY** and **SMALL** go straight to cards.
- **FEATURE** goes to the spec agent, which the lead opens with `colony spec "<feature>"`. It writes the requirements, design and tasks in the vault, and you approve the requirements on your Needs issue before any card is cut.
- **An unknown** goes to the researcher first, which the lead opens with `colony research "<question>"`. Its report ends with every finding as a rule, a check, or a decision for you.

The details are in [cycle.md](cycle.md#tiers).

## 5. The lead writes cards

```sh
gh issue create --title "builder-2: dark mode switch in settings" \
  --body "<task, done-when list, folders, and predicted: S, 20 min>"
colony board set 41 Status="To do" Tier=SMALL
```

Each card has up to 3 done-when results, the folders it touches, and a prediction line that `colony stats` compares with the actual time later. Cards that touch the same folders go to the same builder, which keeps conflicts down. When the lead knows the files, it names them, because finding code is a large part of a small change.

## 6. Builders build

**The lead opens builders as cards need them.** Up to `max_builders` (default 4) run on this machine:

```sh
colony open builder-2
```

`colony open` uses cmux when it can, and otherwise starts the builder as a background session you can follow in the Claude app. For more builders than one machine should run, the lead prints a `colony join <name>` line for you to paste on another computer. On first use there, `join` says what is missing: a clone of the repo, the `claude` login for the account it picked, or `gh auth`.

A builder's name is lowercase letters, digits, dots and dashes, such as `builder-2`, and it can't be `lead`. Each builder starts with:

```text
Read .colony/playbook.md, Builder section. You are builder-2. Start the wait.
```

**The lead hands out a card** with `colony post 41 builder-2 "start this card"`, and sets the card's Status, Builder, Branch and Account on the board.

**Each builder then:**
1. keeps `colony wait` running in the background all session;
2. sets `State=working` on the board, and keeps State and Last update current as it works;
3. makes the change in its own worktree and branch, `../builder-2-<card>` on `builder-2/<card>`, cut from `origin/<base>`;
4. runs the fast check and fixes what it reports;
5. writes a test for a bug fix or new logic (a style change needs none), and checks touch or layout work in a browser at phone width, 390×844;
6. updates the living spec and wiki pages the change makes stale, in the same commit;
7. commits, pushes its branch, and posts `colony post 41 lead "done, builder-2/41 pushed, <the fast check's last line>"`;
8. takes the next card at once.

Builders run at medium effort by default, write no reports, and ask no person anything. When unsure, a builder sends the lead a question with its own default and keeps building on that default.

## 7. The lead merges each done card

When a `done` line arrives, the lead runs `colony tier --head origin/<branch>`. When the branch prints a higher tier than its card, it raises the card's Tier. Then it sets the card to In review and merges that branch into the batch so far, so a conflict shows now and not at the end:

```sh
git fetch origin && git worktree add --detach ../next-<batch> origin/<base>    # first card of a batch
git fetch origin && git -C ../next-<batch> merge --no-ff --no-edit origin/<branch>
```

`<batch>` is today's date, such as `2026-11-05`, with `-2` for a second batch that day. On a conflict, the lead aborts the merge and asks the builder to merge the other branch into its own, resolve it, push, and post `done` again.

## 8. The gate loop

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

- **The checks.** The full `checks` run in the background, with `colony suppressions` among them. A round that changed no `backend_paths` file runs the lighter `web_checks` instead, once a full run has passed.
- **A fresh reviewer.** A new headless session reads the round's diff and checks it against the rubric and the rules, the core and the essentials among them. It reads the places on the risk list first, which `colony batch` takes from `colony tier` at the round's head. It must try to refute each finding before it reports it. Its report starts with `open: N`, the confirmed problems still open, and lists each one as `path:line — what is wrong — the rule it breaks — the smallest fix`. From round 2, it reviews only that round's diff and marks each earlier finding `fixed` or `open`.
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

## 9. The pull request

When a round passes, the batch:

1. writes the PR body to `pr.md` and commits the round reports;
2. pushes the batch branch, and only that branch;
3. opens a PR into your base branch, titled `<project>: batch <name> (#41, #42, #44)`.

The PR body holds the cards, open problems by round (such as `7 → 4 → 1 → 0`), a table of each round's open count, walk and checks, the check commands and their result lines, any test files the batch deletes, a minutes table that sums each kind of step's runs, minutes and cost, and a card stats table of each card's predicted and actual minutes and tokens.

The lead removes `../next-<batch>`, tells you the link, and keeps the other cards moving.

## 10. The batch teaches

After each batch, the lead runs two commands in the background:

- **`colony stats --card 41=builder-2/41 …`** prints the card stats table again: each card's predicted and actual minutes and tokens, read from its lines and its builder's transcripts. The lead uses it to predict the next cards better.
- **`colony retro --name 2026-11-05`** runs one agent on the batch's reports. Each lesson becomes a rule line plus a check, or a decision for you, in one PR. A note alone is never enough.

See [cycle.md](cycle.md#stats) for both.

## 11. You merge

The merge is yours. In Startup and Solo, Colony never merges into your base branch, and never pushes to it. When you merge, the lead sets the cards to Done. Hack is the one exception, below.

## Hack and Solo

### Hack

1. **Setup** asks the team's logins and names, who owns which folders, the base branch (default `main`), whether agents may merge after the fast check (default yes), and the demo time. It writes the owner table into `AGENTS.md` and a hack core of about 300 words as the rules. It opens the issue `Board: <project>`, pins it, and writes its number to `[messages] board`. It copies the board script to `tools/board`.
2. **Each person runs `colony`** on their own machine and gets a lead named `<login>-lead`. The leads are peers, and each may open builders. The lead and its builders follow the playbook's Hack section, which has no cards: the lead hands out tasks as lines on the board, and each builder lands its own branch with `colony merge`.
3. **Every line goes to the board,** not to cards. A post starts with `[<name>'s <agent>]`, such as `[Ana's Claude]`, and `colony post` adds the prefix. A post is addressed to a session when it starts with `for <name>:`, contains `@<login>` for the session's person, or contains `@all`. A post for a person goes to their lead.
4. **Posts reach the agent between prompts.** `colony wait` keeps the lines addressed to this session that it hasn't printed under `unread` in `~/.colony/<project>/<session>.json`. When you send a prompt, the prompt hook prints them, empties `unread`, and makes no network call. When `colony wait` isn't running, the hook makes one ETag-cached `gh api` call, at most once per 30 seconds. Where Agent Relay runs, a post also arrives at once.
5. **The gate is the fast check.** `colony merge <branch>` fetches, merges the branch into the base locally, and runs the fast check. It pushes the base only when the check passes and `[gate] merge_after_fast_check = true`. Otherwise it opens a PR. It never force-pushes. Before the demo, `colony batch --review` adds one fresh reviewer.

Codex and other agents take part through `tools/board`. The step-by-step guide is [hackathon.md](hackathon.md).

### Solo

Solo is one lead with cards and builders, as above, and a gate of the checks and a reviewer. The browser walk is optional. The knowledge vault, specs, research, the card board and the retro are off until you turn them on. The prompt hook shows the lead new lines when you send a prompt.

## Where things live

| Where | What |
| --- | --- |
| `.colony/colony.toml`, `.colony/core.md`, `.colony/rules/`, `.colony/playbook.md`, `.colony/prompts/` | Your settings, rules, playbook and briefs, committed by setup |
| `<app>/AGENTS.md` | Each app's essentials |
| `knowledge/` | The vault, its page types in `.types/`, and the decision log `decisions.md` |
| `.colony/suppressions.json`, `.colony/hooks/` | The suppressions record and the wait guard |
| `.claude/settings.json`, `.claude/skills/`, `.claude/rules/`, `.mcp.json` | The hooks, skills, rule links and MCPs, merged with yours |
| `.colony/reports/<batch>/` | Each batch's reports: `review-N.md`, `walk-N.md`, `checks-N.md`, `minutes.md`, `result.md`, `pr.md`, and `retro.md`. Only the `.md` files are committed. |
| `<worktrees>/<project>-batch-<batch>` | The batch worktree, where the checks run |
| `<worktrees>/<project>-batch-<batch>-walk` | The walker's worktree, detached at each round's head |
| `<worktrees>/<project>-fix-<batch>-<card>-r<round>` | A fixer's worktree, removed after its merge |
| `<worktrees>/<project>-retro-<batch>` | The retro agent's worktree |
| `../<builder>-<card>` | A builder's worktree |
| `../next-<batch>` | The lead's early-merge worktree |
| `tools/board` | Hack only: the board script for Codex and other agents |
| `~/.colony/<project>/<session>.json` | Each session's wait state: its read time, ETag and lines already seen, the lead's stale-card record, and `unread`, the lines the prompt hook prints next |

Every command, with one line each, is in [commands.md](commands.md).
