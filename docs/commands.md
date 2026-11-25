# Commands

You open a session and say hi, and run `colony join` on a computer you lend. The agents and the hooks run the rest. Every command finds the repo with `git rev-parse --show-toplevel`, so it works from any folder in the clone. `colony <command> --help` prints its flags.

## Sessions

| Command | What it does |
| --- | --- |
| `colony` | In a terminal: runs setup when the repo has no `.colony/colony.toml`, and opens your lead every time after. Inside a Claude Code session, which the line setup adds to `CLAUDE.md` asks for: that session becomes the lead, with no new session. With no lead alive it leads `<person>-main-lead` over the whole repo; with leads alive it lists them and their folders, and asks you only "What's mine?". Without a config, it sets Colony up in that session. It opens no second lead while one's heartbeat is fresh. |
| `colony claim <stream> [path …]`, `colony claim --add\|--release <path> …` | This session becomes the lead `<person>-<stream>-lead` over the paths, which no live lead may hold already: folders, such as `web/`, and single files, such as `src/app.ts`, so two leads can share a folder file by file. `--add` takes more paths for the lead this session holds, and `--release` gives some back; the other leads hear each, on the board in Hack and on the coordination issue in Startup. No folders: the rest of the repo, which one live lead holds at a time, so a second claim with no folders is refused while the first lives and acts. A live lead's folders are refused too, unless that lead is silent, when the claim takes them and tells it. It writes the clone's registry, which every worktree reads and nothing commits, the heartbeat and the status comment. See [folders.md](folders.md). Inside Claude Code it keeps the session's identity in `~/.colony/sessions/<session id>.json`, readable by you alone, so later commands and hooks run as the lead with nothing before them; elsewhere it prints the env line to put before each command. |
| `colony whoami [--json]` | This session's name, kind (lead or helper), lead, person and stream, the middle of a lead name such as `ana-engine-lead`, from `$COLONY_SESSION`, `$COLONY_LEAD` and `$COLONY_PERSON`. A repo's own tools read `--json`. |
| `colony who` | Every live lead and helper, across people and computers: name, person, computer, account, folders, loans and borrows, a lead that has been silent, and each account's 5-hour and weekly room with reset times. A status older than 15 minutes counts as gone, and one gone past `[leads] drop_after_hours` is no longer listed. |
| `colony setup [--print]` | Runs setup in this terminal, as `colony` does the first time. `--print` prints the setup prompt instead, for a session already open to follow. |
| `colony skill-install [--config-dir <dir>]` | Copies the `colony-setup` skill into a Claude settings folder, `$CLAUDE_CONFIG_DIR` or `~/.claude` by default, so a session in any repo can set Colony up. |
| `colony join [<lead>]` | Lends this computer to one of your leads, as a helper under the next free builder name, after saying what it lacks: a clone, the `claude` login, or `gh auth`. With one live lead it joins that one; with several it asks once, or `colony join engine` names it. Inside a Claude Code session, as when you type "join" in the app, that session becomes the helper. |
| `colony helpers <n> [--open \| --paste]` | The lead needs `n` helpers. Alone, it prints the question the lead asks you every time, "Open them myself, or you paste?", with your last answer as the default, kept in the git-ignored `.colony/local.toml`. `--open` opens them on this computer: cmux windows when the lead runs in a terminal or cmux, else background sessions. Before a background session opens, it checks that this account has answered Claude Code's one-time question about the repo's `.mcp.json` servers, which a background session would wait on unseen; when it hasn't, it stops and names the step for you, and changes no setting. `--paste` prints one `colony join <lead>` per helper for any computer. `--open` opens them in waves of `[pool] wave` (3), each on an account under its cap of busy helpers, `[pool] max_busy` (3), on a live lead's own account only when no other has room, only where it lasts until the account's reset, and only while this computer has room; the rest open in the background, one wave every `[pool] wave_seconds`, or right after the soonest reset when none fits before it. See [capacity.md](capacity.md#helpers-in-waves). |
| `colony view` | Opens a cmux workspace for every running Colony session on this computer, attached on its own account, so background sessions show in cmux. Run it in a cmux terminal. |
| `colony open <name>` | Opens a helper for the lead that runs it, in cmux or as a background session, on an account under its cap of busy helpers, never on a live lead's own account while you have others (unless `[pool] share_lead_accounts`), and only where it lasts until the account's reset. It refuses, saying why, when no account takes it, unless `--account` names one. |
| `colony image <n> <file>` | The lead saves an image the person pasted for card `n` under `.colony/images/<n>/` on the card's branch, `card/<n>`, pushes it, and says so on the card, so helpers on other computers see it. It works in a throwaway worktree. |
| `colony take <n>` | A helper takes card `n`, marking it In progress with itself as Helper. It refuses a card outside its lead's folders, read from the lead's status on any computer, unless another lead lent those paths for this card; a helper of the lead that holds the rest of the repo takes cards outside every other live lead's folders, and a lead with neither folders nor the rest takes none. It prints the `git worktree add` command that makes the card's worktree, `<worktrees>/<project>-<helper>-<n>` on the branch `<helper>/<n>`, from the card's image branch when it has one. It refuses a card whose `Waits for:` cards haven't landed, and names them. |
| `colony research "<question>"` | Opens a researcher on one question, with `.colony/prompts/researcher.md` as its first prompt. The lead runs it. |
| `colony spec "<feature>"` | Opens the spec agent on a FEATURE, with `.colony/prompts/spec.md` as its first prompt. The lead runs it. |
| `colony fix-links [--dry-run]` | Windows only. Turns on git's `core.symlinks`, and turns every symbolic link git wrote as a one-line text file back into a link, in the repo and all its worktrees. It replaces only an untouched stub, whose text is still the link's target, keeps and names an edited one, and prints the counts. It needs Developer Mode, and changes nothing without it. `colony` and `colony join` say in one line when a repo needs it. On macOS and Linux it does nothing. |
| `colony tools [tool …]` | Prints the tools setup offers, each with its default, or writes the named ones: `playwright`, `context7`, `role-skills`, `starter-skills`, `ui-design`, `test-first`. Setup runs it. |

## Folders and worktrees

Who leads which folders, on every computer, and where worktrees go. See [folders.md](folders.md).

| Command | What it does |
| --- | --- |
| `colony leads` | Who holds which folders on every computer, the one lead that holds the rest of the repo, each loan, borrow and open ask, the silent leads, and the leads this computer's registry holds that aren't alive. It drops the ones gone past `[leads] drop_after_hours` (72) first, and names them. |
| `colony lend <lead> <path> … --card N [--card N …]`, `colony lend <lead> --end [--card N]` | A lead lends paths it holds to another lead for the named cards, so that lead's helpers may take them; the other lead hears it in a line, and every computer sees the loan in the status comment. `--end` takes back the loans to that lead, for the named cards or all. |
| `colony borrow <path> … --card N`, `colony borrow --check`, `colony borrow --return [--card N]` | A lead asks the lead that holds the paths to lend them for the named cards, with a line that says how. A silent lead's paths, one whose session has done nothing for `[leads] silent_minutes` (120), are borrowed at once, and it hears so. An open ask is borrowed once its holder goes silent: the lead's wait settles it, and `--check` does now. `--return` gives back what was borrowed. |
| `colony worktree add <name> <start> [-b <branch> \| --detach] [--dry-run]` | Makes the worktree `<worktrees>/<project>-<name>` at `<start>`, fetching first for an `origin/` start, and prints its folder. It refuses a name that would leave the folder. |
| `colony worktree path [<name>]` | Prints the worktrees folder, or one worktree's folder, for a command such as `git -C "$(colony worktree path next-1)" merge …`. |
| `colony worktree check` | Names each worktree outside `[project] worktrees`, with the `git worktree move` command that moves it in, and ends with 1 when there is one. |

## Config

| Command | What it does |
| --- | --- |
| `colony config` | Shows the three layers the settings come from, the mode's defaults, `.colony/colony.toml` and this computer's `.colony/colony.local.toml`, the check scope and caps, the worktrees folder, and every note: a renamed or removed setting with its replacement, a worktrees folder outside the repo, stray worktrees, and a local file git tracks. See [configuration.md](configuration.md#layers). |
| `colony config migrate [--dry-run]` | Rewrites `.colony/colony.toml` for this version: a renamed setting moves to its new place, and a removed one is commented out with what replaces it. `colony upgrade` runs it. |
| `colony config local [--from-edits] [--dry-run]` | Makes `.colony/colony.local.toml`, this computer's own settings over the tracked file, and keeps it out of git. `--from-edits` moves the uncommitted edits of `.colony/colony.toml` into it and gives the tracked file back its committed text, so an upgrade or a pull never meets them. It refuses an edit that removes a key, which a layer can't express. |

## Lines

| Command | What it does |
| --- | --- |
| `colony wait [--waiting-on N,N] [--follow]` | Waits for the lines addressed to `$COLONY_SESSION`, prints them, and exits. The lead's `--waiting-on` names the cards whose `done` lines come at once. `--follow` keeps it running: it prints each line as it comes, flushed, and never exits on its lines, for an agent tool that streams a command's output. A new wait for a session stops the older one, by its exact process id. |
| `colony post [<card>] <name> "<sentence>" ["<sentence>" ...] [--urgent] [--attach <file> [--public]] [--nudge] [--allow-unknown]` | Posts `for <name>: <sentence> (from <you>)` on a card, through the transport. A first word that is a number, such as `41` or `#41`, is the card; in Hack it is optional. Several sentences go out as one comment, one line each, so all of them land or none does. Each sentence is at most 300 characters, or `[messages] max_line`, not counting what Colony adds around it. `--urgent` starts each sentence with `urgent:`. In Hack, the comment goes to the board issue, starting with `[<name>'s <agent>]`. It refuses a builder's line that isn't `done`, `question:`, `blocked:` or `urgent:`, and a lead's line to a builder that isn't `start:`, `answer:`, `stop:` or `urgent:`. |
| `colony say <lead-name> "<sentence>" [--urgent] [--attach <file> [--public]] [--nudge] [--allow-unknown]` | A lead's line for another lead, such as `sam-lead`, on the `Colony: coordination` issue, or on the board in Hack. It is free text, at most 300 characters a sentence, or `[messages] max_line`, one or several, and waits for the other lead's digest; `--urgent` starts it with `urgent:`, so it arrives at once. |
| `colony waits [--stop <pid> ...] [--stop-leftovers]` | Lists this computer's `colony wait`s: which session each waits for, whether it listens or is a leftover a newer wait replaced, and any `colony wait` no list names, such as one from an older Colony. `--stop` stops each named one by its exact process id, after checking it is a `colony wait`, and `--stop-leftovers` stops this project's leftovers. It never stops by a name pattern. On Windows it lists and stops none. |
| `colony nudge <name> [--card N] [--workspace REF]` | Types one short pointer into the session's cmux workspace on this computer, titled `<name>` or `<project>-<name>`, presses Enter, and reads the screen to confirm it was submitted, pressing Enter again up to three times. Says why when it can't: no cmux, no such workspace, or a draft or question in its prompt. |
| `colony ack` | Says this session acted on every line shown to it so far, so a compaction or a restart shows only newer ones again. |
| `colony redeliver` | Prints the lines shown to this session since its last `colony ack`, within `[messages] redeliver_minutes`. The SessionStart hook prints them by itself after a compaction or a restart. |

Both take `@<login>` as the recipient, which reaches that person's lead, and `@all` in the sentence reaches every session. A lead's line for `@<login>` or `@all` is free text. A line is addressed to a session when it starts with `for <name>:`, contains `@<login>` for the session's person, or contains `@all`.

Both also:

- print, on stderr, which thread each comment went to and its link, since the coordination issue moves to a fresh one when it fills;
- refuse a name no learned, live or registered session has, naming the nearest ones, unless `--allow-unknown`;
- refuse a named lead's line from a session that doesn't hold the lead's claim on this computer;
- refuse a sentence that names a path on this computer, such as `/tmp/x.md` or `~/x`, and take `--attach <file>`, or `-` for stdin, to put the file's text under the line on GitHub instead, checked as `colony share` checks a file; on a public repo it needs `--public`, or `say --private`;
- nudge the recipient's cmux workspace with `--nudge`, or as `[messages] nudge` says;
- add a hidden note naming the sending session, from an agent session; a lead's `start:` line's note asks the helper's wait to acknowledge it, and the lead's wait sends it again when it doesn't.

See [messages.md](messages.md#getting-every-line-through).

## The cycle

| Command | What it does |
| --- | --- |
| `colony tier [--base B] [--head H] [--feature] [--why]` | Prints TINY, SMALL or FEATURE for a branch's diff, then its risk list. `--why` prints each reason, and `--feature` forces FEATURE. |
| `colony needs "<question>" --default "<x>" [--person p] [--new-fixture]` | The lead posts a decision, with its default, on the person's `Needs <Person>` issue. It refuses a question about test accounts or test data while `.colony/fixtures.toml` holds some the person prepared, and names them; `--new-fixture` asks anyway, when none of them fits. |
| `colony card new "<title>" --body … --size S\|M\|L [--lead <name>] [--waits-for N,N]` | Makes a card and puts it on the board as To do, with its Lead and Size. It refuses at the lead's `[limits] open_cards_per_lead` open cards (10), and on a duplicate of an open card, naming its number. It prints an `overlap:` line for each open card that plans to touch the same folders or files, and `--waits-for` writes the card's `Waits for:` line, so it starts once those cards land. See [cycle.md](cycle.md#cards-that-touch-the-same-files). |
| `colony idea "<one line>"` | Appends a dated line to the future-work register, `<vault>/future-work.md`, or `.colony/future-work.md` with no vault. An idea is never an issue. |
| `colony board init` | Makes the GitHub Project for the cards, with its five fields, Status, Lead, Helper, Size and Last update, or finds it and adds any of them it lacks. |
| `colony board set <card> Field=value …` | Adds the card to the board and sets its fields. It stamps Last update, an empty value clears a field, and it refuses a field outside the five. |
| `colony tidy [--dry-run]` | Closes each finished card GitHub left open, as completed: one a merged pull request finishes on whatever branch it merged into, or whose Status is Done. Closes or moves to future-work each card with no update for 7 days, rotates the coordination and Needs issues at 200 comments, archives items Done for 7 days, turns on delete-branch-on-merge, and removes the clean worktrees of closed or merged cards and of ended batches, merges and retros, with the space freed. Prints the counts before and after. `--dry-run` prints the plan and the other worktrees' sizes and last commit dates, and changes nothing. Every `colony batch` ends with it. |
| `colony handover --decisions … --open … --next …` | The lead posts its handover on the coordination issue, and prints the command for a fresh lead. |
| `colony handover --read` | Prints this lead's last handover. |
| `colony batch --name <n> --card N=BRANCH …` | Takes the cards through the gate loop to one PR, whose body says `Closes #N` for each card, then runs `colony tidy`. Each round checks only the areas and walks only the screens its change touched. After at most 3 rounds, each finding still open becomes a card the PR lists; failing checks stop it. A step whose account hits its rate limit runs again on the person's next account with room. `--from <branch>` builds on another branch than `origin/<base>`. |
| `colony batch --fast --name <n> --card N=BRANCH …` | Opt-in, for a batch the person wants shipped quickly. Runs the full checks once, with no reviewer, walk or fixers, opens the PR when they pass, and writes `gate: fast` in its body. When the checks fail it stops, and opens no PR. The default gate is unchanged. |
| `colony status [--name <n>]` | Shows this computer's lead, with its name, account and heartbeat age, then a batch's round, open problems, walk, running steps and minutes. Without `--name`, the newest batch. |
| `colony stats --card N[=BRANCH] … [--base B]` | Prints each card's predicted and actual minutes and tokens, as a table with a total row. |
| `colony retro --name <batch>` | Runs the retro agent on a batch's reports, and opens a PR when it finds a lesson. |

## Checks

How each one works, and why, is in [checks.md](checks.md). Each command exits 0 on a pass, 1 on a failure, 2 when nothing was checked, and 3 when the check goes on in the background past its budget.

| Command | What it does |
| --- | --- |
| `colony fast-check [--full] [--again] [--wait S] [--until-failure]` | A builder's check after a change, in `[checks] scope`: in the related scope, the tests for the branch's change and the guard tests, beside `[project] fast_check` for the areas it touches; otherwise `[project] fast_check` for those areas. It ends on one line for the done line: `fast check: passed …`, `failed …`, `not run …`, or `running in the background …` past its `[checks] budgets` time. A pass on the same code is reused, unless `--again`. `--full` runs the full suite, in the background. `--until-failure` returns at the first failure, with the rest still running. |
| `colony check run [--scope S] [--full] [--ref R] [--again] [--wait S] [--until-failure]` | Runs `[project] checks` for this checkout's change in `[checks] scope`, or `--scope`, or the full suite with `--full`, with the same budget, reuse and live first failure. `--ref origin/main` checks a commit in a worktree of its own, which goes away after. |
| `colony check status [<run>]` | Lists the check runs on this computer, the running ones first: what each checks, for how long against its budget, and its first failure. Then what the ledger knows of this checkout's code, and CI on its commit. With a run's id, that run in full and its log's path. |
| `colony check watch <run> [--until-failure]` | Follows a run's output live to its end, or to its first failure, and ends on its result line. |
| `colony check cancel <run>\|--all` | Stops a run on this computer, or every running one. |
| `colony ci [<ref>] [--again] [--no-start] [--no-watch] [--until-failure] [--no-post] [--issue N]` | Starts the project's CI on a commit, HEAD by default, unless it already ran or passed there: with `[ci] start`, or a push of the commit to a branch of its own. It cancels the runs on older commits of the same branch, watches the code host's checks live and prints the first failure at once, and posts the result on the commit's pull request, else on the commit, or on card `N`. |
| `colony batch --full --name <n> --card N=BRANCH …` | Every round runs the full suite, whatever `[checks] scope` says, as the person asked. |

## Hack

| Command | What it does |
| --- | --- |
| `colony share <file> [--to @<login>] [--public]` | Commits the file under `shared/` on the `colony-shared` branch, which no one merges, pushes it, and posts its link on the board, so an agent on any computer reads it. It never shares a file that holds a secret's shape, in UTF-8 or UTF-16, nor a kind of file that holds secrets, such as `.env` or a `.pem`. On a public repo it shares only with `--public`. |
| `colony need [<lead\|@login> "<what>"] [--done N<n>]` | A lead asks another lead for something, `@<login> need: <what> [N<n>]`, which reaches that lead at once, and Colony remembers it. With no words it lists the open needs and their age, which `colony who` counts too; `--done N<n>` closes one and thanks the other lead. |
| `colony stop [<name> ...] [--force]` | Stops this project's Colony sessions on this computer, or the named ones: a background one with `claude stop`, which keeps its conversation, an interactive one with a terminate signal to the one process id `claude agents` lists for it. It is the safe way to close a session by name, where the kill guard refuses a kill by pattern. Never the session that runs it, and never one whose folder holds uncommitted work unless `--force`. The session ledger notes each stop as on purpose, so `colony resume` leaves it be. The other leads hear who stopped: on the board in Hack, on the coordination issue in Startup. Solo has one person, so no one is told. |
| `colony handoff @<login>` | Hack only. Hands this person's open work to another person's lead in one board line: each branch not yet in the base, with its commits and a warning when it was never pushed, and this lead's claimed paths, which it releases. |
| `colony say --private <lead-name\|@login> "<sentence>"`, `colony private` | On a public repo, a private line goes to the private board, an issue `Private board: <project>` in `[messages] private_repo`, a private repo the team owns, and the public board gets a pointer alone, with none of its words; `colony private` prints the private lines for this session. On a private repo, a private line goes on the board itself. |
| `colony live <sha> [--url <url>]` | Whoever deploys by hand posts `@all live: <sha> is live on <url>`, on the board in Hack and on the coordination issue otherwise, so every lead knows which commit is live. A deploy GitHub records, as Vercel's and Netlify's are, needs none: `colony who` and `colony status` read GitHub's deployments to `[project] deploy_environment`, and name what landed on the base since then, which isn't live yet: merges, pull requests and squashed pull requests by name, and a count of other commits. Outside Hack, they print the line only once a deploy is known. |
| `colony gate off\|on\|status` | Hack only. Your person switches the fast check off or on for `colony merge` on this computer, and the board hears it as an `@all gate:` line. Only the person switches it off, in their own terminal, outside any Colony session, typing `off` to confirm, so no agent can drop the gate by itself; it comes back on by itself at the demo time or after 4 hours, whichever comes first. Anyone may switch it back on. Off, a merge lands without the install and the check, and its `[merged]` line ends `fast check off`. |
| `colony merge <branch> [<branch> ...]` | Hack only, with `[gate] merge_after_fast_check = true`. It takes the team's merge turn on origin, `refs/colony/merge-lock`, so merges from every computer go one at a time, and waits while another merge holds it; a turn over 20 minutes old is taken over. Several branches land together with one check, and each alone when that fails. Fetches, merges the branch into the base locally, runs the fast check for the merged change in `[checks] scope`, as `colony fast-check` does, stopped past `[checks] caps` `fast`, and pushes the base only when the check passes. A failed check runs once more, so a flaky test never blocks a good branch. When it fails twice, the message names the test runner's summary and the failing tests, and the whole output stays in `~/.colony/<project>/merge-logs/`. When the base fails the check on its own, it opens no PR, since the branch is not to blame, and posts one `@all urgent:` line for that base commit. Otherwise it opens a PR. It never force-pushes. |
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
| `colony safety protect [--reviews <n>] [--dry-run]` | The person turns on the code host's own lock, which no agent can switch off from its computer, as it can a hook: one GitHub ruleset, `Puffin Colony: protected branches`, for the default branch, the base, the integration, release and `[release] long_lived` branches, and `[safety] protect`, leaving out Colony's own release branches, `<project>/release-*` and `<project>/sync-*`. It refuses a direct push, a force push and a deletion, and asks for a pull request with `--reviews` approvals from someone other than its author, 0 by default; a team where someone else reviews should pass 1. Run again, it brings the ruleset up to date. `--dry-run` prints the ruleset and runs nothing. GitHub refuses it on a private repo whose plan has no rulesets, and it says so. In Hack, it warns that `colony merge` can't push the base under it. |
| `colony upgrade [--to v<version>]` | On a new branch, moves the launcher's pin to the newest release (or the one named), has that release refresh the files Colony copied into the repo and migrate `.colony/colony.toml` (`colony config migrate`), and commits, ready for a PR. The refresh also lists `colony.local.toml` in `.colony/.gitignore`. Uncommitted edits of `.colony/colony.toml` stop it, with the command that moves them into the local file. |
| `colony hooks asking` | The Notification hook. Posts an urgent line for the lead when a builder waits on a permission pop-up. Claude Code runs it. |
| `colony hooks stopped` | The StopFailure hook. Posts a line when a turn ends on an error. Claude Code runs it. A line either hook can't post waits in `~/.colony/<project>/outbox.json` until the next hook or wait posts it. |
| `colony hooks ended` | The SessionEnd hook. Notes in the session ledger when the session ended and Claude Code's reason, one code word. Claude Code runs it. |
| `colony hooks tasks` | The Stop hook, at the end of each turn. Stamps the session ledger, and when a background command of this session's, such as its `colony wait`, stopped without finishing, keeps the session going once with a note to start it again. Claude Code runs it. |

## Recovery

See [safety.md](safety.md#recovery).

| Command | What it does |
| --- | --- |
| `colony crash-report [--within <hours>] [--json]` | For each session on this computer that showed life in the last `[recover] within_hours` (24): whether it runs, stopped on purpose, or stopped unexpectedly, its last sign of life and what showed it, and the likely cause, such as the computer starting again, a kill by pattern on some session's line just before, many sessions stopping within 90 seconds, a usage limit or another API error, a signal, or a tool call in flight. Then the background commands that stopped without finishing, and each service in `[recover] services` whose check fails. `--json` prints it as one JSON object. |
| `colony resume [<name> ...] [--within <hours>] [--dry-run]` | Reopens every session on this computer that stopped unexpectedly, leads first, each with `claude --resume <id>`, so it keeps its conversation, on the account that holds it, with its role's model, effort and permission mode, in the folder it started in, in cmux or the background. Its first line says it was restarted, when, the likely cause, and what to start again. Each session is reopened once; name sessions to choose them, such as one stopped on purpose. Then it runs the restart command of each `[recover] services` entry whose check fails. `--dry-run` prints each command and the env names, and opens nothing. |

## Standing orders

Your personal profile, the team profile and session settings: see [profiles.md](profiles.md). These commands work in any folder, and need a clone only for the team profile. `--team` writes `.colony/team.toml`, which takes effect when its pull request merges, and `--session` writes this session's own file. `--person <name>` picks whose profile, when `$COLONY_PERSON` is not set.

| Command | What it does |
| --- | --- |
| `colony profile show [--orders [--role lead\|helper]] [--team-only] [--json]` | Lists every order in force and where it came from: each setting with its source and how a disagreement between the team and you was settled, each rule with its ref, and the files read. `--orders` prints the standing-order text a session starts with. `--team-only` shows the team's orders alone, for work between people. Plain `colony profile` does the same as `show`. |
| `colony profile keys` | Prints every key a profile may hold, its kind, and what applies when the team's value and yours differ. |
| `colony profile setup [--set <key>=<value> …] [--defaults] [--again]` | The one-time questions that write your personal profile. In a terminal it asks them; in an agent's session it prints them for the lead to ask in one message, and `--set` or `--defaults` writes the answers. It never asks again unless `--again`. |
| `colony profile set <key> <value> [--team\|--session]`, `colony profile unset <key> [--team\|--session]` | Sets or removes one key. A list is comma-separated. It refuses an unknown key, a wrong value, a personal-only key in the team profile, and anything that looks like a secret. |
| `colony profile resolve <key> team\|mine` | Records your answer where the team's value and yours differ and neither is stricter, so you are asked once. It is asked again only when either side changes. |
| `colony profile import [--from <file>] [--accept <id>,…] [--decline <id>,…]` | Finds preferences in your agent tool's memory and instruction files and offers each one; nothing is added without your yes. A declined one is never offered again. |
| `colony profile init` | Writes `.colony/team.toml` with every team key commented out, and never overwrites one. Setup runs it. |
| `colony prefer add "<rule>" [--team\|--session] [--correction]` | Keeps a rule as a standing order, such as a correction you gave a lead. |
| `colony prefer list [--personal\|--team\|--session]` | Every rule in force, with its ref: `p3` is your third personal rule, `t1` the team's first, `s2` a session's. |
| `colony prefer remove <ref>` | Drops a rule by its ref. |

## Capacity

Accounts, usage limits, services, this computer, locks, and sleep. See [capacity.md](capacity.md).

| Command | What it does |
| --- | --- |
| `colony capacity [--json]` | This computer's cores, load, memory and free disk; how many helpers, test runs and builds it runs at once, and how many more helpers may open now; each of your accounts' room with how old its reading is, its helpers against its cap and its forecast, with `[pool] reserve` accounts and the accounts kept for a live lead marked; the sessions waiting for a usage limit to reset; and the locks held. It takes a live reading of every account first. `--json` prints one object for a script. |
| `colony services [--json]` | Runs every service check now: each account on this computer (signed in, with room), `gh auth status`, and each `[services.<name>]`. Prints `pass:` or `fail:` with why and how to fix it, never a command's output, and ends with 1 when one fails. |
| `colony lock <name> [--slots N] [--wait MINUTES] -- <command>` | Runs the command while holding the named lock on this computer, such as `test-db` for one shared test database. Another run waits for it, saying who holds it, up to `--wait` minutes (30). The command gets its slot in `$COLONY_LOCK_SLOT`. Slots come from `--slots`, `[locks.<name>] slots`, or for `tests` and `builds`, this computer's runs at once; else 1. It ends with the command's exit code. |
| `colony lock --list` | Names each held lock, who holds it, its command and for how long. |
| `colony wake [--after-sleep] [--dry-run]` | Wakes the sessions on this computer whose usage limit has reset, and the idle helpers whose wait stopped. `--after-sleep` also continues, under their own ids, the background helpers that ran before the computer slept and no longer run. `--dry-run` says what it would do. |
| `colony wake --follow` | Does the same every minute, and after a sleep, until no session waits for a limit to reset. The StopFailure hook, or a wait, starts it by itself when a limit is noted; one runs per project on each computer. |
| `colony open-later <n>` | The later waves of `colony helpers <n> --open`, which it starts in the background. When the helpers left fit on no account before its reset, its next wave starts right after the soonest reset. You don't run it yourself. |
| `colony accounts [--json]` | Every account in the pool: on this computer, whether it is signed in, its live usage and reset times, how old the reading is, its helpers against its cap, and its forecast, or that its folder is missing here; on other computers, as their status comments last showed them; then the new signed-in folders here that no account names. See [capacity.md](capacity.md#finding-accounts). |
| `colony accounts scan [--add] [--person <p>] [--json]` | Finds signed-in settings folders on this computer, where `[pool] scan_folders` looks, that no `[accounts.<name>]` table names, and offers to add each: it asks in a terminal, prints the `colony accounts add` command elsewhere, and adds them all with `--add`. |
| `colony accounts add <name> --dir <folder> [--person <p>] [--max-busy <n>]` | Writes an account, or this computer's folder for an account the team names, into this computer's own `.colony/colony.local.toml`, never the shared file. The config must still load with it, or nothing changes. |

## Starting a session and decisions

The startup routine, the project summary, modes, request intake, and what a lead asks you. See [boot.md](boot.md) and [decisions.md](decisions.md). `ask`, `answer` and `plan`, except `plan show`, refuse to run outside a lead's session, `approve` runs only at the person's own terminal, and a helper never switches or defines a mode.

| Command | What it does |
| --- | --- |
| `colony boot [--offline] [--json]` | The startup routine, which also runs by itself when a session becomes a lead and from the SessionStart hook: it loads the orders and the last handover, refreshes the project summary, reads the live leads on every computer, the open pull requests, your cards, the plan, the decisions that wait on you, and the computer's and accounts' room, and prints a briefing that names the active mode and ends on one next step: resume, or ask one question. `--offline` reads nothing from GitHub. |
| `colony summary [--rebuild] [--json]` | The project summary: what the project is, its areas with their files, languages and purpose, its checks, and what changed since this session last started. Built once, and refreshed from what changed; `--rebuild` builds it again. |
| `colony mode [<name> \| off] [--personal]` | Alone, lists the modes, yours, the team's and Colony's, and which is on. With a name, switches that mode on for this session, or with `--personal` for every session, and prints the new orders; `off` switches it off. |
| `colony mode show <name>` | What a mode sets. |
| `colony mode define <name> --set <key>=<value> … [--rule "<rule>" …] [--about "<what it is for>"] [--team]` | Writes a mode of your own to `modes/<name>.toml` in your user config folder, or with `--team` the team's `.colony/modes/<name>.toml`, for a pull request. |
| `colony plan new "<request>" [--show-first] [--replace]` | Starts a plan for one request, kept word for word, and says the team shape and limits from your orders. |
| `colony plan group <name> --folders <folder> … --done "<result>" … [--helpers <n>] [--draft]` | Adds or changes one task group: the folders it owns, which no other group shares, 1 to 3 done-when results, and its helpers, at most `team.helpers_per_lead`. `--draft` drafts it first. |
| `colony plan [show] [--of <lead>] [--group <name>] [--json]` | The plan and where each group stands. |
| `colony plan start [--approved "<words>"] [--dry-run]` | Starts the groups: one card each for a lead, one lead each for an orchestrator, at most `team.max_leads` at once. When the request or `intake.plan` asks to see the plan first, it shows it and starts only with `--approved`, the person's yes, kept word for word. |
| `colony plan done <group>`, `colony plan approve <group> "<words>"` | Marks a group done, or records the person's yes on a group's draft. |
| `colony orders [--publish]` | The standing orders this lead passes its helpers, with what the person approved for them; `--publish` posts them now for helpers on other computers. A helper sees the orders its lead gave it. |
| `colony ask "<question>" --default "<pick>" --kind scope\|product\|stop\|gate\|routine --why "<explanation>" [--why-file <file>] [--option "<choice>: <meaning>" …] [--checked] [--person <p>]` | The lead's one way to ask the person. A routine question, and others under `decisions.autonomy`, are decided and logged instead; a topic on the don't-raise list is never raised. It first looks for an earlier answer, matching issues and pull requests, and a lead whose folders the question names, and ends with 1 when it found one; `--checked` asks anyway. A question it asks goes on the Needs issue with its full explanation attached, and it says whether to hold the work or keep going on the pick. |
| `colony decisions [--log \| --all] [--json]` | The decisions that wait on the person, with their age and what to do past their wait; `--log` those decided alone; `--all` every one. |
| `colony answer <id> "<the person's words>" [--on-issue]`, `colony answer <id> --took-default \| --withdraw` | Records the person's answer exactly as they said it, on the Needs issue too; for a draft, says whether it reads as a yes or a no. `--took-default` records that no answer came in time and the pick stands, never for a stop or gate question; `--withdraw` takes the question back. |
| `colony never-raise ["<topic>"] [--remove] [--team]` | The topics never raised with the person: lists them, adds one to your personal profile, or takes one off. |
| `colony spend <dollars> "<what>" [--approved <id>]` | Checks a spend against today's `budgets.dollars_per_day` and records it. Past the budget it ends with 1, unless `--approved` names a decision the person said yes to. |
| `colony approve "<rule>" … [--for <hours>] [--lead <lead>] [--only <session> …]` | The person, at their own terminal: lets their leads and helpers on this computer run what each Claude Code permission rule covers, such as `Bash(npm run migrate:*)`, without a permission question, until it expires, 8 hours by default, at most 24. It refuses unless it runs at an interactive terminal outside any agent's session, and asks the person to type yes. A rule names its command, domain or path; a joined command never matches. |
| `colony approve --list`, `colony approve --revoke <id>` | The approvals in force, which any session may list, or, at the person's terminal, ends one at once. |
| `colony session-hook start\|compact\|end\|turn\|tool` | The startup, handover and approval hooks. Claude Code runs them. |

## Watch

What each session does and why, reports, progress, the watchdog and the status page. See [watch.md](watch.md).

| Command | What it does |
| --- | --- |
| `colony intent [working\|waiting\|holding\|done\|clear] ["<what>"] [--on <session>] [--for MINUTES]` | Says what this session does and why, so the watch flags it only when it is idle without a reason. `waiting` and `holding` need a reason. `--on` names the session you wait on, and `--for` when the wait should end. With no state, it prints the intent. `colony take` sets `working` by itself, and a helper's `done` line sets `waiting` for its next card. |
| `colony report "<one line of progress>" [--card N]` | A working session's report, at least every `[watch] report_minutes` (30). It goes out in the status comment, sets the intent to `working`, and stamps the card's Last update, for `--card` or the card the intent names. |
| `colony watch [--json]` | Every lead and helper with what it does and why, its last report and its helper agents; what is worth a look; the cards' progress; and each account on this computer with how old its reading is and its forecast. |
| `colony watch --page` | Writes the status page, the pinned `Colony: status` issue, now, and prints its link. |
| `colony watch --folded` | Prints the helper lines the lead's digest folded, the newest 100. |
| `colony progress [--all] [--json]` | Your cards, or every lead's with `--all`, with their minutes against their predictions, and when the work left ends with the helpers working at once. |
| `colony watchdog [status]` | Whether the watchdog runs for this project on this computer, its last pass, whether the computer starts it at login, its log, and the status page's link. |
| `colony watchdog start [--stay]`, `colony watchdog stop` | Starts the watchdog in the background, apart from every session, or stops it by its exact process id. The lead's wait starts it by itself when `[watch] watchdog` is on. Without `--stay`, it ends after `[watch] quit_hours` with no session alive here. |
| `colony watchdog install [--dry-run]`, `colony watchdog uninstall [--dry-run]` | Has the computer run the watchdog at login and again whenever it ends: a launchd agent on macOS, a systemd user unit on Linux. `uninstall` removes it. |
| `colony watchdog run [--stay] [--once]` | The watchdog itself, in the foreground. `--once` makes one pass and ends. |

## Housekeeping

Cards that overlap or wait for others, the lead's queue, and the files a branch changed, see [cycle.md](cycle.md#cards-that-touch-the-same-files); and the test accounts, fixtures and findings list that testers share, see [testing.md](testing.md).

| Command | What it does |
| --- | --- |
| `colony card overlaps` | Lists every pair of open cards that plan to touch the same paths, by their `Folders:` and `Files:` lines, and what each pair shares. A pair where one card waits for the other is left out. |
| `colony card waits <n> <cards>` | Sets the cards card `n` waits for, such as `12,13`, on its `Waits for:` line; `""` clears it. The card starts once they land, on whatever branch they merged into. |
| `colony card next [--start] [--helper <name>] [--lead <name>]` | The lead's queue: its To do cards whose wait is over, oldest first, then the ones that still wait and what for. `--start` hands the first ready card to a free helper, the one its title names when it is free, else the first free one, or `--helper`: it posts `start: this card` and sets Status and Helper. |
| `colony card files [<n>] [--branch <branch>] [--base <branch>]` | A branch's changed files, from `git diff` against where it left `origin/<base>`: HEAD's by default, with the files not committed and the commits not pushed. With a card, it also names the changed files outside the card's `Folders:` and `Files:` lines. A helper's `done` line carries the same list. |
| `colony fixtures [--json]`, `colony fixtures add account\|fixture <name> --what "…" [--where …] [--login …] [--secret-at …] [--how …] [--note …]`, `colony fixtures remove <name>` | Lists, records or drops the test accounts and fixtures the person prepared, in `.colony/fixtures.toml`, by reference only: what each one is, where it lives, its login name, and where its secret is kept. It refuses a value that looks like a secret. See [testing.md](testing.md#test-accounts-and-fixtures). |
| `colony findings open <release> [--card N …]` | Finds the release's findings issue, which every tester on every computer shares, or makes it with the cards the release's batches close. It prints the cards and the prepared test accounts and fixtures. See [testing.md](testing.md#the-findings-list). |
| `colony findings next <release> [--as <name>]` | Claims the next card that no tester holds and none has tested, and prints it. When two testers claim one card at once, the earlier claim wins and it tries the next. |
| `colony findings claim <release> <card> [--as <name>]`, `colony findings free <release> <card> [--as <name>]` | Claims one card by its number, or renews your own claim; or hands a card you hold back, untested. A claim with no result lapses after `[testers] claim_minutes` (60). |
| `colony findings report <release> <card> pass\|fail\|blocked "<what you saw>" [--as <name>]` | Records a card's result. A fail or a block needs what you saw. When every card has a result, it prints the `done` line for the lead. |
| `colony findings show <release>` | Brings the findings list up to date from every tester's comments, and prints it. |

## Releases and branch health

The release pull request, the merge freeze, the long-lived branches, the shared branch's health, steps for the person, and plain status messages. See [releases.md](releases.md). `release`, `freeze on|off|allow`, `branches` and `health run|watch` are for a lead or the person, never a helper. `release`, `branches`, `health run|watch` and `step add` take `--dry-run`.

| Command | What it does |
| --- | --- |
| `colony release` | Opens one pull request from the integration branch into the release branch, with a description drafted from the merged work: what changed, migrations, tests removed or changed, and the checks on its head. First it freezes the integration branch for every person's leads, and posts one `@all` line that says so and names each other lead whose work it carries. An open release pull request is reused. A person merges it. |
| `colony release --print` | Prints the drafted description and opens nothing. |
| `colony release --refresh` | Rewrites the open release pull request's description from the work and the checks as they are now. |
| `colony release --only <n> [--only <n> …]`, `colony release --lead <name>\|me` | Releases only those pull requests, or one lead's: it cuts `<project>/release-<date>` from the release branch, copies each chosen change onto it, oldest first, and opens the pull request from it. The rest stays for a later release, and nothing is frozen. A change that needs work left behind stops it, naming the files. |
| `colony release --after` | Once a person merged the release: lifts its freeze, opens a pull request that brings the release branch back into the integration branch and into each `[release] long_lived` branch that lacks it, then watches `[project] deploy_workflow` on the release branch until it ends, and exits with its result. |
| `colony freeze on [--branch B] [--why "…"] [--hours H] [--allow <name> …]` | Pauses landings on the integration branch, or `--branch`, for every person's leads: `colony merge` and `colony batch` refuse it, except named fixes. It ends by itself after `[release] freeze_hours` (12), or `--hours`. |
| `colony freeze off [--branch B] [--red]` | Lifts the freeze. `--red` lifts a red hold from `colony health` too, as for a false alarm. |
| `colony freeze allow <branch\|card number> … [--branch B]` | Names fixes that may land while the branch is held. |
| `colony freeze status [--branch B]` | What is held, on every branch or on one, with who, why and until when. |
| `colony freeze check [<name> …] [--branch B]` | Exits 0 when the named work may land on the branch, and 1 while a hold refuses it, for other tools. |
| `colony branches [--sync]` | How far each long-lived branch is from the release branch, and the commits that sit on one branch alone. `--sync` opens a pull request from `<project>/sync-<from>-into-<to>-<time>` into each one that lacks the release branch. Colony never pushes to a long-lived branch. |
| `colony health run [--branch B] [--source auto\|ci\|local]` | Looks at each shared branch's head once, from CI or the full suite here. On red, it tells the likely cause's lead, tells every lead, and pauses landings until it passes. On green, it lifts that pause. Exits 0 green, 1 red, 3 while the checks still run. |
| `colony health watch [--every MINUTES]` | Does the same every `[health] every_minutes` (60), and every 2 minutes while a run is going, as one lead's background command. |
| `colony health status [--branch B]` | What each shared branch last showed on this computer, and what is held. |
| `colony step add "<what>" [--run "<command>"] [--who <person\|@login\|anyone\|agent>] [--why "…"] [--check "<command>"] [--no-check] [--anyway]` | Hands a step only a person can take over. It tests the step first with `--check`, or the dry-run form of its command when Colony knows one, and never runs the step itself. A failing test stops it unless `--anyway`. It posts the step as one comment on the `Colony: person steps` issue, mentioning who does it, and prints one plain line to tell them. |
| `colony step list [--who <person>] [--all]` | The open person steps, or one person's, or every one with `--all`. |
| `colony step done <n> [--note "…"]` | Marks a step done, with who and when, by editing its comment. |
| `colony plain check "<message>"`, `colony plain check --file <path>\|-` | Names each thing in a message to the person that they may not understand, such as an arrow, a chat abbreviation, an internal code or an unexplained short form, with how to say it instead. Exits 1 when it finds one. |
| `colony plain templates [<name>]`, `colony plain fill <name> key=value …` | Prints the plain status templates, or fills one in and checks it. |

## Flags

| Flag | Where | What it does |
| --- | --- | --- |
| `--dry-run` | `colony`, `join`, `open`, `helpers`, `research`, `spec`, `batch`, `retro`, `tidy`, `tools`, `fix-links`, `hooks install`, `upgrade`, `wake`, `fast-check`, `check run`, `ci`, `resume`, `safety protect`, `watchdog install`, `watchdog uninstall`, `worktree add`, `config migrate`, `config local` | Prints the plan and runs nothing. A dry run shows env names, never their values. |
| `--here` | `colony`, `join`, `research`, `spec` | Opens in this terminal even when cmux takes commands. |
| `--person <name>` | `colony`, `join`, `open`, `research`, `spec`, `batch`, `retro`, and `needs` | Whose accounts to use, when `colony.toml` names several people. On `needs`, whose decision it is. |
| `--account <name>` | `colony`, `join`, `open`, `research`, `spec`, `batch` | The `[accounts.<name>]` table to run on, instead of the one Colony picks. |
| `--review` | `batch` | In Hack, adds one fresh reviewer to the fast check. With no `--card`, it reviews the demo build, `origin/<base>` as it stands, for the last hour before the demo. |
| `--version` | `colony` | Prints the version. |

`handover` and `say` refuse to run outside the lead's session. `needs` runs from any session and signs its line with `$COLONY_SESSION`. `post`, `wait`, `ack`, `redeliver`, `intent` and `report` need `$COLONY_SESSION`.
