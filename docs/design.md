# Puffin Colony: a small framework for an AI dev team in your repo

Puffin Colony turns Claude Code into a team's whole software development life cycle, behind one command, `colony`. It installs as the Python package `puffin-colony`. The names live in constants at the top of `colony/cli.py` (`NAME`, `DISPLAY`, `DIR`).

## Layout

- **The package**, `colony/`: `cli.py` (the command line), `batch.py` (the gate loop), `wait.py` (the line watcher), and its data, read with `importlib.resources`: `prompts/`, `presets/`, `playbook.md` (the template) and `colony.toml.example`.
- **A host repo** keeps everything Colony writes in `.colony/` at its root: `colony.toml`, `rules/`, `playbook.md` (filled in), and each batch's reports in `.colony/reports/<batch>/`. Every command finds the root with `git rev-parse --show-toplevel`. A repo with no `.colony/colony.toml` gets setup.

## The one command

`colony`, with no arguments, is all a person types.

- **The first time** (the repo has no `.colony/colony.toml`), it runs setup. Setup opens an interactive Claude session with the package's `prompts/setup.md`. That session reads the repo, asks at most 5 questions, writes the files below, and opens a PR with them.
- **Every time after that**, it opens the lead agent. It picks the person's account with the most room, sets `COLONY_SESSION=lead`, `COLONY_PERSON`, `CLAUDE_CONFIG_DIR` (left unset for `~/.claude`) and the retry settings, and starts `claude --remote-control <project>-lead` with the first prompt "Read .colony/playbook.md, Lead section, and start." It opens in a new cmux workspace when cmux is on PATH, otherwise right here.
- **`colony join <name>`** is the line the lead prints for another computer or account. It opens a builder named `<name>` on that machine's account with the most room, with the first prompt "Read .colony/playbook.md, Builder section. You are <name>. Start the wait." On first use on that machine it says what is missing: a clone, the `claude` login, or `gh auth`.

The lead and the builders use these internal subcommands. A person never needs them:
- `colony batch …`: the gate loop, as before
- `colony status`
- `colony wait`: the line watcher, below
- `colony open <name>`: opens a builder here, in cmux, on the account with the most room

## What setup writes into the repo

| File | What it holds |
| --- | --- |
| `.colony/colony.toml` | Accounts and people, base branch, check commands, generated paths and regen, install command, rubric, rule files, budget, preset name |
| `.colony/rules/*.md` | The rules from the chosen preset, with paths filled in for this stack. Each is one short file. |
| `.colony/playbook.md` | The SDLC for the lead and the builders (below), with this project's commands filled in |
| A pointer in `CLAUDE.md` (or `AGENTS.md`) | One line: "This repo runs Puffin Colony: read .colony/playbook.md." Setup adds it only after asking, and creates the file if neither exists. |

Setup reads the repo and fills in what it can without asking: the stack (package.json, pyproject.toml, go.mod, …), the test, lint and typecheck commands, CI files, the default branch, and any existing CLAUDE.md or AGENTS.md (whose rules it keeps). Then it asks at most these 5 questions, each with a default:
1. Who is on the team, and which Claude accounts (settings folders) each one uses?
2. Which branch do PRs go to?
3. Which rules: `lean` (default), `puffin` (Puffin's full rule set), or `own` (only what the repo already has)?
4. Any spend limit on model calls inside the app's own evals? Default $0.
5. Anything agents must never do here?

## Presets (`colony/presets/<name>/` in the package)

- **`lean`**: about 6 short files, each under 400 words, generic and written fresh: `coding.md`, `testing.md` (a bug fix carries a regression test, new logic carries a test, a style change carries none), `security.md`, `performance.md`, `accessibility.md`, and `git.md` (branches, commits, PRs, never pushing to base).
- **`puffin`**: Puffin's engineering rules, generalized and shipped with Colony: frontend, backend and process rules, plus per-stack essentials (Next.js, FastAPI, generic) and a docs reading aid. It works in any repo. See docs/presets.md.
- **`own`**: no new rules. The repo's own CLAUDE.md and AGENTS.md are the rules.

## The playbook (`.colony/playbook.md`)

**Lead.** It talks with the person and runs the life cycle:
1. It turns each request into cards: GitHub issues titled `<builder>: <what>`, each with up to 3 done-when results and its folders.
2. It opens builders on demand. Up to `max_builders` (colony.toml, default 4) run on this machine through `colony open <name>`. For more, it prints `colony join <name>` for the person to paste on another computer.
3. It hands a card out with a line on the card, `for <builder>: start this card (from lead)`.
4. As each `done` line arrives, it merges that builder's branch into the batch branch.
5. Every few cards, or when the person asks, it runs `colony batch`, which loops until 0 open problems.
6. It tells the person the PR link, and asks only what it can't decide: money, secrets, deleting data, new dependencies, merging.

**Builder.** It builds fast:
1. Start `colony wait` in the background, all session.
2. Make the change on its own branch.
3. Run the fast check.
4. Write a test for a bug fix or for new logic. For touch or layout work, check it in a browser at phone width.
5. Commit, push its branch, and post one `done` line.
6. Take the next card at once.

It asks no person anything: it sends questions to the lead with its own default, and keeps building on that default.

**Lines.** Each line is a card comment of the form `for <name>: <one sentence> (from <name>)`, under 300 characters.

## `colony wait`

It polls the repo's issue comments with `gh api` every 15 seconds, using ETags, and prints the first lines addressed to `$COLONY_SESSION`. A builder's wait returns on the first line for it signed by the lead. The lead's wait returns on any line for it. Its state lives in `~/.colony/<project>/<session>.json`. It runs in about 100 lines of standard-library Python.

## The gate: 0 open problems

`colony batch` stays as before, with one change: the reviewer's report starts with `open: N`, the number of confirmed problems still open. The rubric becomes the reviewer's checklist, not a score. A batch is done when the checks pass, `open: 0` holds, and the walk passes or was skipped. The PR body lists open problems by round, such as 7 → 4 → 1 → 0.

## v2.1 additions (Serdar, 2026-11-05)

### The `puffin` preset is our whole engineering system, minus the product

Setup copies these into `.colony/rules/` and the area files, and rewrites Puffin-only names into the host's:
- **The rules.**
  - The frontend set: performance, full-stack, accessibility, coding, design-principles without the glass specifics, and testing.
  - The backend set: performance-service, security-and-privacy, database.
  - The process set: commits, pull-requests, writing.
- **The essentials.** An area file per app (`apps/<app>/AGENTS.md`), with numbered must-lines the way Puffin's web and backend files hold them. Setup writes the Next.js/TanStack lines for a Next.js app, the FastAPI/Pydantic lines for a Python service, and the generic lines otherwise.
- **The docs.** A reading aid that points to the installed framework docs: `node_modules/next/dist/docs/` for Next.js, and Context7 for any other library. It's for the reviewer and for a builder who is unsure.

### MCPs and skills

Setup offers a recommended set, each with a yes or no default. It writes the ones the person accepts into `.mcp.json` and `.claude/skills/`, and lists them in colony.toml:
- **MCPs:** Playwright (the walker's browser, yes) and Context7 (library docs, yes).
- **Skills:**
  - colony's own `colony-lead`, `colony-builder`, `colony-reviewer` and `colony-walker`, the playbook split per role (yes)
  - a UI design skill (ask)
  - a test-first skill (no)

Installing a package that adds a dependency asks the person first.

### Messages: a quiet lead, instant when it matters, and lead to lead

- A builder gets a line from its lead within about 15 seconds.
- The lead is interrupted less. Its wait gathers lines and returns every `lead_digest_minutes` (default 10). It returns at once on an `urgent:` line, a blocker, a builder's question that stops work, or a line from the person. A `done` line waits for the digest, unless the batch is waiting on it.
- **Leads talk to each other** on one coordination issue, `Colony: coordination`. Each lead's wait reads it too, with the same instant-on-urgent rule. So two people's leads, such as Serdar's and Burak's, can ask each other things, hand work across, or warn before a merge to the shared base branch.
- A transport setting (`transport = "github"`, the default, or `"relay"`) lets machines that run Agent Relay deliver lines instantly through it, with GitHub as the record.

### Speed, quality and tokens, built in

colony's defaults are today's measured lessons:
- **Rules load on demand.** An edit loads only its area's short file. Full rules are the reviewer's checklist. This cut 15K tokens and 14% of the cost per session.
- **Builders run at medium effort.** They run the fast check only, write no reports or screenshots, and start no subagents. The one exception is a browser check at phone width for touch or layout work, because fake-DOM tests missed 4 phone bugs today.
- **A card names the files** when the lead knows them. Finding code took about 40% of a tiny change's calls.
- **The reviewer is fresh each round,** and reviews only that round's diff plus the open list. The tests, the reviewer and the walk run in parallel. The backend suite is skipped when a round changed no backend file after a clean run.
- **Every step records its minutes and cost** in `minutes.md`, and the PR shows the totals.
- **The start env sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW=250000`,** the agent trial's recommendation.

## Rules for the code

- Python 3.11+ standard library only. Shell out to `git`, `gh`, `claude` and `cmux`.
- Never `shell=True`, except for config command strings.
- Never print env values, and never push to the base branch.
- No spend above the budget.
- Keep each file short and readable, with a docstring per function.
