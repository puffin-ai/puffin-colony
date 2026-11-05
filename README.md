# Puffin Colony

Puffin Colony turns Claude Code into your team's whole software life cycle, behind one command. You talk to a lead agent. It writes the cards, opens builders, merges their work, and runs every batch through checks, a fresh reviewer and a browser walk until 0 problems stay open. Then it opens one pull request for you to merge.

It needs Python 3.11 or later, `git`, `gh` and `claude`, and uses `cmux` when it's installed. It has no dependencies of its own.

## Install

From a clone of this repo:

```sh
uv tool install .        # or: pipx install .
```

## The one command

Run it anywhere inside your repo:

```sh
colony
```

- **The first time**, when the repo has no `.colony/colony.toml`, it starts setup. That's a Claude session that reads the repo: its stack, its test, lint and typecheck commands, CI, default branch, and any `CLAUDE.md` or `AGENTS.md`. Then it asks at most 5 questions, each with a default:
  1. Who is on the team, and which Claude accounts (settings folders) does each one use?
  2. Which branch do PRs go to?
  3. Which rules: `lean`, `puffin` or `own`?
  4. Any spend limit on model calls in the app's own evals? Default $0.
  5. Anything agents must never do here?

  It writes `.colony/colony.toml`, `.colony/rules/` and `.colony/playbook.md` with your commands filled in. It asks before it adds one pointer line to `CLAUDE.md`, then opens a PR with all of it. `colony --dry-run` shows the plan.
- **Every time after that**, it opens your lead on whichever of your accounts has the most room. It opens in a new cmux workspace, or right here with `--here`. `--dry-run` prints the command and the names of the env variables it sets, never their values.

Your repo keeps everything Colony writes in `.colony/`, and each batch's reports go in `.colony/reports/<batch>/`.

## Presets

- `lean` (default): six short, generic rule files: coding, testing, security, performance, accessibility and git.
- `puffin`: Puffin's own engineering rules and area files, listed in `colony/presets/puffin/manifest.txt`. It works only inside Puffin's repo until Puffin Colony is public.
- `own`: no new rules. Your `CLAUDE.md` and `AGENTS.md` are the rules.

## More builders on other computers

The lead opens up to `max_builders` builders on your computer. For more, it prints a line like `colony join builder-5`. Run that line in a clone on any computer or account that has Colony installed. The first time, it tells you what's missing: the clone, the `claude` login, or `gh auth`.

## What you do

Talk to the lead. Answer the few things it can't decide: money, secrets, deleting data, new dependencies. Merge the pull request. The lead and the builders handle everything else themselves, using `colony open`, `wait`, `batch` and `status`. You never need to run those yourself.

## Develop

```sh
uv run --with pytest pytest -q tests
```

The design is in [docs/design.md](docs/design.md).
