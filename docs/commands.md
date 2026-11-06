# Commands

You type `colony`, and `colony join <name>` when the lead asks. The agents and the hooks run the rest. Every command finds the repo with `git rev-parse --show-toplevel`, so it works from any folder in the clone. `colony <command> --help` prints its flags.

## Sessions

| Command | What it does |
| --- | --- |
| `colony` | Runs setup when the repo has no `.colony/colony.toml`, and opens your lead every time after. It opens no second lead while one's heartbeat is fresh. |
| `colony hi` | For a session you opened without a task, which the line setup adds to `CLAUDE.md` runs: with no `.colony/colony.toml`, it says to set Colony up in that session. With no lead running, it claims the lead for that session. With a lead running, it offers a builder's name, or help. A session `colony` opened keeps its role. |
| `colony setup [--print]` | Runs setup in this terminal, as `colony` does the first time. `--print` prints the setup prompt instead, for a session already open to follow. |
| `colony skill-install [--config-dir <dir>]` | Copies the `colony-setup` skill into a Claude settings folder, `$CLAUDE_CONFIG_DIR` or `~/.claude` by default, so a session in any repo can set Colony up. |
| `colony join <name>` | Opens a builder on this computer, after saying what it lacks: a clone, the `claude` login, or `gh auth`. |
| `colony open <name>` | Opens a builder on this computer, in cmux or as a background session. The lead runs it. |
| `colony research "<question>"` | Opens a researcher on one question, with `.colony/prompts/researcher.md` as its first prompt. The lead runs it. |
| `colony spec "<feature>"` | Opens the spec agent on a FEATURE, with `.colony/prompts/spec.md` as its first prompt. The lead runs it. |
| `colony tools [tool …]` | Prints the tools setup offers, each with its default, or writes the named ones: `playwright`, `context7`, `role-skills`, `starter-skills`, `ui-design`, `test-first`. Setup runs it. |

## Lines

| Command | What it does |
| --- | --- |
| `colony wait [--waiting-on N,N]` | Waits for the lines addressed to `$COLONY_SESSION`, prints them, and exits. The lead's `--waiting-on` names the cards whose `done` lines come at once. |
| `colony post <card> <name> "<sentence>" [--urgent]` | Posts `for <name>: <sentence> (from <you>)` on a card, through the transport. `--urgent` starts the sentence with `urgent:`. In Hack, the line goes to the board issue, starting with `[<name>'s <agent>]`. |
| `colony say <lead-name> "<sentence>"` | A lead's line for another lead, such as `burak-lead`, on the `Colony: coordination` issue, or on the board in Hack. |

Both take `@<login>` as the recipient, which reaches that person's lead, and `@all` in the sentence reaches every session. A line is addressed to a session when it starts with `for <name>:`, contains `@<login>` for the session's person, or contains `@all`.

## The cycle

| Command | What it does |
| --- | --- |
| `colony tier [--base B] [--head H] [--feature] [--why]` | Prints TINY, SMALL or FEATURE for a branch's diff, then its risk list. `--why` prints each reason, and `--feature` forces FEATURE. |
| `colony needs "<question>" --default "<x>" [--person p]` | The lead posts a decision, with its default, on the person's `Needs <Person>` issue. |
| `colony board init` | Makes the GitHub Project for the cards, with its fields, or finds it and adds any field it lacks. |
| `colony board set <card> Field=value …` | Adds the card to the board and sets its fields. It stamps Last update, and an empty value clears a field. |
| `colony handover --decisions … --open … --next …` | The lead posts its handover on the coordination issue, and prints the command for a fresh lead. |
| `colony handover --read` | Prints this lead's last handover. |
| `colony batch --name <n> --card N=BRANCH …` | Takes the cards through the gate loop to one PR. `--from <branch>` builds on another branch than `origin/<base>`. |
| `colony status [--name <n>]` | Shows this computer's lead, with its name, account and heartbeat age, then a batch's round, open problems, walk, running steps and minutes. Without `--name`, the newest batch. |
| `colony stats --card N[=BRANCH] … [--base B]` | Prints each card's predicted and actual minutes and tokens, as a table with a total row. |
| `colony retro --name <batch>` | Runs the retro agent on a batch's reports, and opens a PR when it finds a lesson. |

## Hack

| Command | What it does |
| --- | --- |
| `colony merge <branch>` | Hack only, with `[gate] merge_after_fast_check = true`. Fetches, merges the branch into the base locally, runs the fast check, and pushes the base only when the check passes. Otherwise it opens a PR. It never force-pushes. |

### `tools/board`

Not a `colony` command: a POSIX shell script that needs only `sh` and `gh`. Setup copies it to `tools/board` in Hack, so Codex or any agent can use the board. It writes the same post format as `colony post`.

| Command | What it does |
| --- | --- |
| `tools/board post "<text>"` | Posts on the board, starting with `[<name>'s <agent>]`. |
| `tools/board unread` | Prints every post by others since your last look, and marks the ones for you `, for you`. |
| `tools/board wait [--interval S]` | Waits for a post addressed to you, checking every `S` seconds, 30 by default. |
| `tools/board read [-n N]` | Prints the board's last posts, or the last `N`. |
| `tools/board whoami` | Prints who it posts as. |

See [hackathon.md](hackathon.md#codex-and-other-agents).

## Knowledge

| Command | What it does |
| --- | --- |
| `colony check-docs` | Runs the vault's checks, each in its mode, rewrites the decision log, and prints a count per check. |
| `colony check-docs --staged` | Checks only the staged pages, with the checks that read one page at a time. For a pre-commit hook. |
| `colony check-docs --strict` | Fails on the checks set to `warn` too. |
| `colony check-docs --index` | Only rewrites the decision log, `<vault>/decisions.md`. |

## Guards

| Command | What it does |
| --- | --- |
| `colony suppressions [--update]` | Counts lint and type suppressions in each file against `.colony/suppressions.json`, and fails when a count grows. `--update` lowers the record, and the first run writes it. |
| `colony hooks install` | Merges the wait guard and the two posting hooks into `.claude/settings.json`, keeping the hooks already there. |
| `colony hooks asking` | The Notification hook. Posts an urgent line for the lead when a builder waits on a permission pop-up. Claude Code runs it. |
| `colony hooks stopped` | The StopFailure hook. Posts a line when a turn ends on an error. Claude Code runs it. |

## Flags

| Flag | Where | What it does |
| --- | --- | --- |
| `--dry-run` | `colony`, `join`, `open`, `research`, `spec`, `batch`, `retro`, `tools`, `hooks install` | Prints the plan and runs nothing. A dry run shows env names, never their values. |
| `--here` | `colony`, `join`, `research`, `spec` | Opens in this terminal even when cmux takes commands. |
| `--person <name>` | `colony`, `join`, `open`, `research`, `spec`, `batch`, `retro`, and `needs` | Whose accounts to use, when `colony.toml` names several people. On `needs`, whose decision it is. |
| `--account <name>` | `colony`, `join`, `open`, `research`, `spec`, `batch` | The `[accounts.<name>]` table to run on, instead of the one Colony picks. |
| `--review` | `batch` | In Hack, adds one fresh reviewer to the fast check, for the last hour before the demo. |
| `--version` | `colony` | Prints the version. |

`handover` and `say` refuse to run outside the lead's session. `needs` runs from any session and signs its line with `$COLONY_SESSION`. `post` and `wait` need `$COLONY_SESSION`.
