# Commands

You open a session and say hi, and run `colony join` on a computer you lend. The agents and the hooks run the rest. Every command finds the repo with `git rev-parse --show-toplevel`, so it works from any folder in the clone. `colony <command> --help` prints its flags.

## Sessions

| Command | What it does |
| --- | --- |
| `colony` | In a terminal: runs setup when the repo has no `.colony/colony.toml`, and opens your lead every time after. Inside a Claude Code session, which the line setup adds to `CLAUDE.md` asks for: that session becomes the lead, with no new session. With no lead alive it leads `<person>-main-lead` over the whole repo; with leads alive it lists them and their folders, and asks you only "What's mine?". Without a config, it sets Colony up in that session. It opens no second lead while one's heartbeat is fresh. |
| `colony claim <stream> [folder …]` | This session becomes the lead `<person>-<stream>-lead` over the folders, which no live lead may hold already. No folders: the rest of the repo. It writes `.colony/leads.toml`, the heartbeat and the status comment. Inside Claude Code it keeps the session's identity in `~/.colony/sessions/<session id>.json`, readable by you alone, so later commands and hooks run as the lead with nothing before them; elsewhere it prints the env line to put before each command. |
| `colony whoami [--json]` | This session's name, kind (lead or helper), lead, person and stream, the middle of a lead name such as `ana-engine-lead`, from `$COLONY_SESSION`, `$COLONY_LEAD` and `$COLONY_PERSON`. A repo's own tools read `--json`. |
| `colony who` | Every live lead and helper, across people and computers: name, person, computer, account, folders, and each account's 5-hour and weekly room with reset times. A status older than 15 minutes counts as gone. |
| `colony setup [--print]` | Runs setup in this terminal, as `colony` does the first time. `--print` prints the setup prompt instead, for a session already open to follow. |
| `colony skill-install [--config-dir <dir>]` | Copies the `colony-setup` skill into a Claude settings folder, `$CLAUDE_CONFIG_DIR` or `~/.claude` by default, so a session in any repo can set Colony up. |
| `colony join [<lead>]` | Lends this computer to one of your leads, as a helper under the next free builder name, after saying what it lacks: a clone, the `claude` login, or `gh auth`. With one live lead it joins that one; with several it asks once, or `colony join engine` names it. Inside a Claude Code session, as when you type "join" in the app, that session becomes the helper. |
| `colony helpers <n> [--open \| --paste]` | The lead needs `n` helpers. Alone, it prints the question the lead asks you every time, "Open them myself, or you paste?", with your last answer as the default, kept in the git-ignored `.colony/local.toml`. `--open` opens them on this computer: cmux windows when the lead runs in a terminal or cmux, else background sessions. `--paste` prints one `colony join <lead>` per helper for any computer. |
| `colony view` | Opens a cmux workspace for every running Colony session on this computer, attached on its own account, so background sessions show in cmux. Run it in a cmux terminal. |
| `colony open <name>` | Opens a helper for the lead that runs it, in cmux or as a background session. |
| `colony image <n> <file>` | The lead saves an image the person pasted for card `n` under `.colony/images/<n>/` on the card's branch, `card/<n>`, pushes it, and says so on the card, so helpers on other computers see it. It works in a throwaway worktree. |
| `colony take <n>` | A helper takes card `n`, marking it In progress with itself as Helper. It refuses a card outside its lead's folders. |
| `colony research "<question>"` | Opens a researcher on one question, with `.colony/prompts/researcher.md` as its first prompt. The lead runs it. |
| `colony spec "<feature>"` | Opens the spec agent on a FEATURE, with `.colony/prompts/spec.md` as its first prompt. The lead runs it. |
| `colony tools [tool …]` | Prints the tools setup offers, each with its default, or writes the named ones: `playwright`, `context7`, `role-skills`, `starter-skills`, `ui-design`, `test-first`. Setup runs it. |

## Lines

| Command | What it does |
| --- | --- |
| `colony wait [--waiting-on N,N]` | Waits for the lines addressed to `$COLONY_SESSION`, prints them, and exits. The lead's `--waiting-on` names the cards whose `done` lines come at once. |
| `colony post [<card>] <name> "<sentence>" ["<sentence>" ...] [--urgent]` | Posts `for <name>: <sentence> (from <you>)` on a card, through the transport. A first word that is a number, such as `41` or `#41`, is the card; in Hack it is optional. Several sentences go out as one comment, one line each, so all of them land or none does. Each sentence is at most 300 characters, not counting what Colony adds around it. `--urgent` starts each sentence with `urgent:`. In Hack, the comment goes to the board issue, starting with `[<name>'s <agent>]`. It refuses a builder's line that isn't `done`, `question:`, `blocked:` or `urgent:`, and a lead's line to a builder that isn't `start:`, `answer:`, `stop:` or `urgent:`. |
| `colony say <lead-name> "<sentence>" [--urgent]` | A lead's line for another lead, such as `sam-lead`, on the `Colony: coordination` issue, or on the board in Hack. It is free text, at most 300 characters a sentence, one or several, and waits for the other lead's digest; `--urgent` starts it with `urgent:`, so it arrives at once. |

Both take `@<login>` as the recipient, which reaches that person's lead, and `@all` in the sentence reaches every session. A lead's line for `@<login>` or `@all` is free text. A line is addressed to a session when it starts with `for <name>:`, contains `@<login>` for the session's person, or contains `@all`.

## The cycle

| Command | What it does |
| --- | --- |
| `colony tier [--base B] [--head H] [--feature] [--why]` | Prints TINY, SMALL or FEATURE for a branch's diff, then its risk list. `--why` prints each reason, and `--feature` forces FEATURE. |
| `colony needs "<question>" --default "<x>" [--person p]` | The lead posts a decision, with its default, on the person's `Needs <Person>` issue. |
| `colony card new "<title>" --body … --size S\|M\|L [--lead <name>]` | Makes a card and puts it on the board as To do, with its Lead and Size. It refuses at the lead's `[limits] open_cards_per_lead` open cards (10), and on a duplicate of an open card, naming its number. |
| `colony idea "<one line>"` | Appends a dated line to the future-work register, `<vault>/future-work.md`, or `.colony/future-work.md` with no vault. An idea is never an issue. |
| `colony board init` | Makes the GitHub Project for the cards, with its five fields, Status, Lead, Helper, Size and Last update, or finds it and adds any of them it lacks. |
| `colony board set <card> Field=value …` | Adds the card to the board and sets its fields. It stamps Last update, an empty value clears a field, and it refuses a field outside the five. |
| `colony tidy [--dry-run]` | Closes or moves to future-work each card with no update for 7 days, rotates the coordination and Needs issues at 200 comments, archives items Done for 7 days, turns on delete-branch-on-merge, and removes closed cards' clean worktrees. Prints the counts before and after. `--dry-run` prints the plan and changes nothing. Every `colony batch` ends with it. |
| `colony handover --decisions … --open … --next …` | The lead posts its handover on the coordination issue, and prints the command for a fresh lead. |
| `colony handover --read` | Prints this lead's last handover. |
| `colony batch --name <n> --card N=BRANCH …` | Takes the cards through the gate loop to one PR, whose body says `Closes #N` for each card, then runs `colony tidy`. Each round checks only the areas and walks only the screens its change touched. After at most 3 rounds, each finding still open becomes a card the PR lists; failing checks stop it. A step whose account hits its rate limit runs again on the person's next account with room. `--from <branch>` builds on another branch than `origin/<base>`. |
| `colony batch --fast --name <n> --card N=BRANCH …` | Opt-in, for a batch the person wants shipped quickly. Runs the full checks once, with no reviewer, walk or fixers, opens the PR when they pass, and writes `gate: fast` in its body. When the checks fail it stops, and opens no PR. The default gate is unchanged. |
| `colony status [--name <n>]` | Shows this computer's lead, with its name, account and heartbeat age, then a batch's round, open problems, walk, running steps and minutes. Without `--name`, the newest batch. |
| `colony stats --card N[=BRANCH] … [--base B]` | Prints each card's predicted and actual minutes and tokens, as a table with a total row. |
| `colony retro --name <batch>` | Runs the retro agent on a batch's reports, and opens a PR when it finds a lesson. |

## Hack

| Command | What it does |
| --- | --- |
| `colony gate off\|on\|status` | Hack only. Your person switches the fast check off or on for `colony merge` on this computer, and the board hears it as an `@all gate:` line. Only the person switches it off, in their own terminal, outside any Colony session, typing `off` to confirm, so no agent can drop the gate by itself; it comes back on by itself at the demo time, or after 4 hours without one. Anyone may switch it back on. Off, a merge lands without the install and the check, and its `[merged]` line ends `fast check off`. |
| `colony merge <branch> [<branch> ...]` | Hack only, with `[gate] merge_after_fast_check = true`. It takes the team's merge turn on origin, `refs/colony/merge-lock`, so merges from every computer go one at a time, and waits while another merge holds it; a turn over 20 minutes old is taken over. Several branches land together with one check, and each alone when that fails. Fetches, merges the branch into the base locally, runs the fast check, and pushes the base only when the check passes. A failed check runs once more, so a flaky test never blocks a good branch. When it fails twice, the message names the test runner's summary and the failing tests, and the whole output stays in `~/.colony/<project>/merge-logs/`. When the base fails the check on its own, it opens no PR, since the branch is not to blame, and posts one `@all urgent:` line for that base commit. Otherwise it opens a PR. It never force-pushes. |
| `colony batch --review --name <n>` | Hack only, with no `--card`, for the last hour before the demo. One fresh reviewer reads `origin/<base>` as it stands, the demo build, beside the fast check, and writes its report. No fixers run. It pushes the report on the branch `<project>/batch-<n>`, posts one `@all` line on the board with the open count and the report's link, and runs `colony tidy`. |

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
| `colony suppressions [--update]` | Counts lint and type suppressions in each file against `.colony/suppressions.json`, and fails when a count grows. `# noqa` counts in any case, and stylesheets count `@ts-ignore`, `@ts-expect-error` and skipped tests too. `--update` lowers the record, and the first run writes it. |
| `colony hooks install` | Merges Colony's hooks into `.claude/settings.json`, keeping the hooks already there, copies the wait guard, and writes `.colony/bin/colony`, the launcher pinned to the version that ran. |
| `colony upgrade [--to v<version>]` | On a new branch, moves the launcher's pin to the newest release (or the one named), has that release refresh the files Colony copied into the repo, and commits, ready for a PR. |
| `colony hooks asking` | The Notification hook. Posts an urgent line for the lead when a builder waits on a permission pop-up. Claude Code runs it. |
| `colony hooks stopped` | The StopFailure hook. Posts a line when a turn ends on an error. Claude Code runs it. A line either hook can't post waits in `~/.colony/<project>/outbox.json` until the next hook or wait posts it. |

## Flags

| Flag | Where | What it does |
| --- | --- | --- |
| `--dry-run` | `colony`, `join`, `open`, `research`, `spec`, `batch`, `retro`, `tidy`, `tools`, `hooks install`, `upgrade` | Prints the plan and runs nothing. A dry run shows env names, never their values. |
| `--here` | `colony`, `join`, `research`, `spec` | Opens in this terminal even when cmux takes commands. |
| `--person <name>` | `colony`, `join`, `open`, `research`, `spec`, `batch`, `retro`, and `needs` | Whose accounts to use, when `colony.toml` names several people. On `needs`, whose decision it is. |
| `--account <name>` | `colony`, `join`, `open`, `research`, `spec`, `batch` | The `[accounts.<name>]` table to run on, instead of the one Colony picks. |
| `--review` | `batch` | In Hack, adds one fresh reviewer to the fast check. With no `--card`, it reviews the demo build, `origin/<base>` as it stands, for the last hour before the demo. |
| `--version` | `colony` | Prints the version. |

`handover` and `say` refuse to run outside the lead's session. `needs` runs from any session and signs its line with `$COLONY_SESSION`. `post` and `wait` need `$COLONY_SESSION`.
