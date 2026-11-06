# Modes

Colony runs in one of three modes. Setup's first question picks it, and it lives in `.colony/colony.toml` as `mode` in `[project]`: `"hack"`, `"solo"` or `"startup"`.

- **Hack** is for a team that builds something in hours or a weekend. Each person runs a lead on their own machine, the leads talk on one pinned issue, and work ships after the fast check. The guide is [hackathon.md](hackathon.md).
- **Solo** is for one person on a small project: one lead, builders, the checks and a reviewer.
- **Startup** is the whole system, for a company's whole life cycle. The rest of these docs describe it.

A config with no `mode` counts as `startup`, so a repo set up before modes works as it did.

## What each mode turns on

| | Hack | Solo | Startup |
| --- | --- | --- | --- |
| For | A team, for hours or a weekend | One person, a small project | A company's whole life cycle |
| Leads | One per person, as peers, each named `<login>-lead` | One | One per person, with a digest |
| Builders | Optional. Each person's lead may open them | Yes | Yes |
| Messages | One pinned board issue, with `@login` and `@all` mentions, and the prompt hook | Lines on cards, and the prompt hook | Lines on cards, the coordination issue, and the digest |
| Owner table | Yes, per person, in `AGENTS.md` | No | Optional |
| Gate | The fast check only. `colony merge <branch>` merges into the base after a passing fast check, when setup's yes allows it. `--review` adds one reviewer before the demo | The checks and a reviewer. The browser walk is optional | The checks, a reviewer and the walk, until 0 problems are open |
| Knowledge vault, specs, research, card board, retro | No | Off, and each can be turned on | Yes |
| Rules | A hack core of about 300 words: honesty, ownership and board duties | `lean` | `lean`, `puffin` or `own` |
| Setup asks | The team's logins and names, who owns which folders, the base branch (default `main`), whether agents may merge after the fast check (default yes), and the demo time | The base branch, and the rules | Up to 5 questions, as in [how-it-works.md](how-it-works.md#2-setup-the-first-time) |

**Two boards.** In Hack, "the board" is the pinned issue `Board: <project>`, where every message goes. In Solo and Startup, the board is the GitHub Project that tracks cards, which this table calls the card board.

## Hack

**On:**
- **Leads as peers.** Each person runs `colony` on their own machine and gets a lead named `<login>-lead`. No lead is in charge of another. Each works in its person's folders from the owner table in `AGENTS.md`.
- **The board issue.** Setup opens an issue titled `Board: <project>`, pins it, and writes its number to `[messages] board`. Every line goes there, not to cards. A post starts with `[<name>'s <agent>]`, such as `[Serdar's Claude]`, and `colony post` adds that prefix itself.
- **Addresses.** A post reaches a session when it starts with `for <name>:`, contains `@<login>` for the session's person, or contains `@all`. A post for a person goes to their lead.
- **The prompt hook.** When you send your lead a prompt, the hook first prints the new posts addressed to it.
- **The fast check gate.** `colony merge <branch>` merges the branch into the base and pushes it after a passing fast check, when `[gate] merge_after_fast_check = true`. Otherwise it opens a PR. `colony batch --review --name <n>`, with no `--card`, has one fresh reviewer read the demo build, for the last hour before the demo.
- **`tools/board`.** Setup copies a small shell script into the repo, so Codex or any agent with `gh` can read and post on the board in the same format.

**Off:** the knowledge vault, specs, research, the card board, the browser walk and the retro. The rules are a short hack core, not a preset.

## Solo

**On:** one lead, builders, cards, the checks and a reviewer, the prompt hook, and the `lean` rules. The browser walk is optional.

**Off:** the knowledge vault, specs, research, the card board and the retro. Each can be turned on later: the keys are in `colony/modes/solo.toml`, and your `colony.toml` overrides any of them.

## Startup

**On:** everything. The knowledge vault, tiers, specs, research, the card board, your Needs issue, the gate with its reviewer and browser walk until 0 problems are open, the digest, lead to lead lines, and the retro. The owner table is optional. See [how-it-works.md](how-it-works.md) and [cycle.md](cycle.md).

## The defaults files

Each mode's defaults are a TOML file in the installed package:

| File | Holds |
| --- | --- |
| `colony/modes/hack.toml` | Hack's defaults |
| `colony/modes/solo.toml` | Solo's defaults |
| `colony/modes/startup.toml` | Startup's defaults, which are Colony's settings from before modes |

Colony reads the mode's file first, then your repo's `.colony/colony.toml`. Any key in your file wins. To change one default, add its key to your `colony.toml` and commit it. Every key is in [configuration.md](configuration.md).

## Switching later

1. Change `mode` in `[project]` of `.colony/colony.toml`, and commit it, so every machine reads the same mode.
2. Restart each lead: end its session and run `colony` again.

The new mode's defaults apply at once. The switch doesn't make what setup makes for a mode, such as the board issue, the owner table, `tools/board`, the card board or the vault. For those:

- **Run setup again.** Move `.colony/colony.toml` out of the repo, run `colony`, pick the new mode, and merge its setup PR. Setup keeps your `CLAUDE.md`, `AGENTS.md` and hooks. Then copy back any key you had changed by hand.
- **Or add one piece by hand.** `colony board init` makes the card board. For a board issue, open one titled `Board: <project>`, pin it with `gh issue pin <number>`, and write `board = <number>` under `[messages]`.

Out of Hack, `colony merge` no longer pushes the base, and work goes through pull requests again. The board issue stays as the record; `gh issue unpin <number>` unpins it.
