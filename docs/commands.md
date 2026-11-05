# Commands

You type `colony`, and `colony join <name>` when the lead asks. The agents and the hooks run the rest. Every command finds the repo with `git rev-parse --show-toplevel`, so it works from any folder in the clone. `colony <command> --help` prints its flags.

## Sessions

| Command | What it does |
| --- | --- |
| `colony` | Runs setup when the repo has no `.colony/colony.toml`, and opens your lead every time after. |
| `colony join <name>` | Opens a builder on this computer, after saying what it lacks: a clone, the `claude` login, or `gh auth`. |
| `colony open <name>` | Opens a builder on this computer, in cmux or as a background session. The lead runs it. |
| `colony research "<question>"` | Opens a researcher on one question, with `.colony/prompts/researcher.md` as its first prompt. The lead runs it. |
| `colony spec "<feature>"` | Opens the spec agent on a FEATURE, with `.colony/prompts/spec.md` as its first prompt. The lead runs it. |
| `colony tools [tool …]` | Prints the tools setup offers, each with its default, or writes the named ones: `playwright`, `context7`, `role-skills`, `starter-skills`, `relay`, `ui-design`, `test-first`. Setup runs it. |

## Lines

| Command | What it does |
| --- | --- |
| `colony wait [--waiting-on N,N]` | Waits for the lines addressed to `$COLONY_SESSION`, prints them, and exits. The lead's `--waiting-on` names the cards whose `done` lines come at once. |
| `colony post <card> <name> "<sentence>" [--urgent]` | Posts `for <name>: <sentence> (from <you>)` on a card, through the transport. `--urgent` starts the sentence with `urgent:`. |
| `colony say <lead-name> "<sentence>"` | A lead's line for another lead, such as `burak-lead`, on the `Colony: coordination` issue. |

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
| `colony status [--name <n>]` | Shows a batch's round, open problems, walk, running steps and minutes. Without `--name`, the newest batch. |
| `colony stats --card N[=BRANCH] … [--base B]` | Prints each card's predicted and actual minutes and tokens, as a table with a total row. |
| `colony retro --name <batch>` | Runs the retro agent on a batch's reports, and opens a PR when it finds a lesson. |

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
| `--version` | `colony` | Prints the version. |

`handover` and `say` refuse to run outside the lead's session. `needs` runs from any session and signs its line with `$COLONY_SESSION`. `post` and `wait` need `$COLONY_SESSION`.
