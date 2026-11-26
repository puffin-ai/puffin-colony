# Changelog

## 0.7.0, 2026-11-25

The run-lessons upgrade: 85 changes learned from one long run with several leads, orchestrators and many helpers. A session now starts from your standing orders without onboarding. Helpers open by live account readings and the computer's room. The watch knows a session that waits on purpose. Colony recovers what a crash or a sleep stopped, and every merge waits for your yes.

Changes to know before you upgrade:

- Agents merge into nothing by default. `[safety] merge_into` lists the branches they may merge pull requests into, and it counts only once it is on GitHub's default branch. A project whose leads merge into an integration branch must list it.
- The push guard allows one form of push alone, on a line of its own: `git push -u origin HEAD:refs/heads/<branch>`. Every other push is refused, and so is a kill by name or pattern, such as `pkill` or `killall`. Close a session with `colony stop <name>`.
- You approve a helper's command at your own terminal, with `colony approve`. No approval travels through GitHub.
- Worktrees go in `.worktrees` inside the repo by default, and Colony makes them nowhere else. Your own settings go in `.colony/colony.local.toml`, and `colony upgrade` migrates old settings.
- Every account is used by its room and reset times, in one ranking: `[pool] order = "pace"`, the new default, puts the account with the most weekly room left an hour until its reset first, a soft aim so no week goes to waste; `"reset"`, the old default, still ranks by the soonest reset. A lead's own account takes its place there, one fewer than its cap and only while the lead keeps 10% of each window; `[pool] share_lead_accounts = true` drops those limits. Each session runs at most `[subagents] max_running` subagents, 2 by default. Builders run only as helpers.
- `colony release` freezes the integration branch while the release is checked, lists every unreleased pull request, and brings the release back through a pull request instead of a merge.

Standing orders and starting a session (profiles.md, boot.md, decisions.md):

- Standing orders at three levels: your personal profile, which follows you into every repo, the team's `.colony/team.toml`, and settings for one session. The stricter rule wins when two disagree. `colony profile` shows each order and where it came from, and `colony prefer` adds, lists and removes rules, including a correction you made.
- Setup asks its questions once, and can import preferences from your agent tool's memory after you confirm each one. The personal profile is never committed, and no profile holds a secret.
- The startup routine runs by itself: it loads the orders and the last handover, refreshes the project summary, checks the live leads, pull requests, cards, accounts and the computer, then prints a short briefing and its next step. A handover is saved whenever a session ends, crashes or compacts.
- Named modes, such as `colony mode orchestrator` or `unattended`, switch a bundle of orders on with one word. A one-sentence request becomes a plan of task groups with owners and done-when results. Every helper starts with its lead's orders.
- A lead asks you only through `colony ask`, with a full explanation, and records your answer word for word. Topics not to raise, and a daily spending budget, bind every session.

Capacity (capacity.md):

- A policy for the team's pool of accounts, from any provider: which to use first, when to switch, and how many helpers each runs. `colony helpers <n> --open` opens helpers in waves, by live readings, and plans around each account's reset. `colony accounts` lists and finds accounts.
- Colony reads the computer's cores, memory, disk and load, and sets how many helpers, test runs and builds run at once. `colony lock` guards what can't be shared, such as one test database.
- A session stopped by a usage limit wakes when the limit resets, and after a sleep the helpers that stopped start again. `colony services` checks every service the team relies on, and the lead hears when one fails.

Messages (messages.md):

- `colony wait --follow` keeps running, one wait per session. Start lines are re-sent until acknowledged, a nudge wakes an idle recipient, unread lines come back after a compaction, and a line to an unknown name is refused. Leads on every computer see and message each other, and notes travel as attachments.

Watching (watch.md):

- The team watch knows a session that waits on purpose (`colony intent`), so it raises no false "stuck" alerts. Helpers report on a rhythm, cards show progress against their predictions, and helper chatter is folded. A watchdog keeps watching when every session has stopped, and a status page opens on a phone.

Safety and recovery (safety.md):

- `colony crash-report` says when each session stopped and the likely cause, and `colony resume` reopens every session that was alive before, on its own account and in its own folder. A background command stopped from outside, such as a session's `colony wait`, is named to its session so it starts again. `colony safety protect` turns on a GitHub ruleset for the protected branches.

Checks (checks.md):

- Checks run in proportion to the change, each within a time budget, and a slow one runs in the background while work goes on. Results stream as they arrive, a passing result is reused for the same commit, and `colony ci` starts CI on any commit and posts its results.

Folders (folders.md):

- One lead registry for every copy of the repo. A lead lends folders for a card, borrows from another, and frees those of a lead gone silent. Every command follows the configured check settings.

Releases (releases.md):

- The release pull request's description is written from the merged work: what changed, migrations, tests removed or changed, and check results. A merge freeze binds every person's leads. `colony release --only` releases a chosen part, and `colony branches --sync` keeps the long-lived branches in step. `colony health` keeps the shared branch green, `colony step` hands the person tested steps, and `colony plain check` keeps status messages plain.

Cards and testing (cycle.md, testing.md):

- `colony card new` names cards that plan to touch the same files. A card can wait for others and starts when they land, and an idle lead picks up its next queued card. A helper's changed files come from its diff, and finished cards close whatever branch they merged into. Testers reuse the accounts and fixtures you prepared, and share one findings list across computers.

Upgrading: `colony upgrade` refreshes the launcher, the wait guard, the hooks and the role skills, and migrates `.colony/colony.toml` with `colony config migrate`. Uncommitted edits of `.colony/colony.toml` stop it: `colony config local --from-edits` moves them into `.colony/colony.local.toml` first. `.colony/playbook.md`, `.colony/core.md` and `tools/board` are copies setup filled in, so copy them again from the package for the new rules, and fill in their placeholders as setup did. A project whose leads merge into an integration branch adds it to `[safety] merge_into`, on the default branch, before the new pin reaches its sessions.

## 0.6.0, 2026-11-12

Hack mode holds up through a long day with several people, each with a lead on their own computer: leads see each other reliably, merges queue across computers, the demo has a clock, and everyone knows what is live. The parts that help every mode now work in every mode. A builder's fast check runs for its card's area, `colony tidy` clears finished worktrees, and the push guard reads a push the way git does.

Fixed:

- `colony who` said "Helpers: none alive" whenever a post held `] [`, such as `colony merge`'s own `[merged]` line, so a helper stuck at a permission prompt went unseen. Status comments are now read one per line, and when GitHub can't be read, `who` says unknown, never none.
- The wait guard refused ordinary commands: joined operators such as `);`, and `$(...)` with quotes inside. It now splits them, and lets a line it can't read run, unless that line holds a `git push`.
- The 300-character limit counted the `for <to>: … (from <sender>)` around a sentence, so a sentence under the limit could be refused. It counts the sentence alone. `colony post` and `colony say` take several sentences as one comment, and a lead may send `stop:`.
- A relative `check_env_file` is found in the repo's main checkout when a worktree has no copy.
- Hack worktrees went next to the repo, where they piled up in the person's folder. They now go in `[project] worktrees`, helpers are granted only that folder, and `colony merge` removes a clean worktree once its branch lands.
- One `colony wait` listens per session: a newer one wins, and the older one says so. Lines a board move copies wake no one.
- `tools/board` posts are signed `(from <name>)`, so a lead's own posts don't wake it. A `for <name>:` line reaches that session alone, and `colony post all` means `@all`.
- A settings folder two people share is labeled by its person, and `--dry-run` posts nothing.
- `colony merge` names the failing tests, keeps each run's whole output in `~/.colony/<project>/merge-logs/`, runs a failed check once more, and tells a base that fails on its own apart from the branch.
- `colony --dry-run` and `colony claim --dry-run` in a repo with no live lead claimed the lead: they wrote the heartbeat, `.colony/leads.toml` and a status comment. They now say `would lead <name> ... Nothing ran.` and write nothing. The hack docs name the lead `<login>-main-lead`.
- A helper's first `colony wait` read back only the last hour, so a start line its lead posted earlier, while the helper waited on a prompt, never reached it. The first wait in each Claude Code session now looks further back for the newest start line its lead signed for it that it hasn't answered.
- Two named leads on one computer shared one listener file, so the second lead's wait stopped the first. Each lead's listener now carries its own name.

Hack mode:

- The lead reads gathered lines every 2 minutes. `urgent:`, `blocked:`, `question:` and the person's own lines still come at once.
- Setup asks the demo time, `[hack] demo`, with no default. `colony who` and `colony status` print the time left first, and the team lead's wait posts `@all freeze: only fixes from now` an hour before it.
- `colony merge` runs the fast check once, and notes a check that takes over 90 seconds. The person, at their own terminal, can switch the check off with `colony gate off` until the demo, for 4 hours at most.
- One merge runs at a time across every computer of the team: a merge takes the team's turn, a marker commit on origin's `refs/colony/merge-lock`. Several branches land with one check, and each alone when that fails.
- The hack rules let the person trade checks for speed, put building first, and make "be quiet" mean quiet.
- `colony handoff @<login>` hands this person's open branches and claimed paths to another person's lead.

Every mode:

- `colony who` and `colony status` print what is live, from GitHub's deployments to `[project] deploy_environment` or a `colony live <sha>` line, and what landed on the base since: merges, pull requests and squashed pull requests by name, and a count of other commits. Outside hack mode the line shows only once a deploy is known.
- The lead's wait warns when a helper's call has waited on a prompt for 10 minutes, and when the computer slept. On a Mac it keeps the computer awake while the lead runs. `colony who` shows each helper's folder, branch and any call that waits.
- A lead's identity is kept for its Claude Code session in `~/.colony/sessions/<id>.json`, readable by you alone, so commands and hooks run as the lead with no env line and no token.
- Claims take single files as well as folders, and `colony claim --add` and `--release` change them while leading. `colony stop` stops this project's sessions on this computer, but never one with uncommitted work unless `--force`. The other leads hear both, except in solo mode.
- `colony say --private` sends a line through `[messages] private_repo`, a private repo the team owns, and leaves only a pointer on a public board. `colony private` reads it.
- `colony share <file>` puts a file on the `colony-shared` branch and posts its link. `colony need` asks another lead for something and tracks it until `--done`.
- Every wait on a computer shares one read of GitHub, and a wait sleeps through GitHub's rate limit instead of failing.
- When a batch's checks fail, they run once more on the batch's start commit alone. A failure that shows there too goes to no fixer, and when it is the only one left, the batch stops and says to fix the base or the checks' setup.
- `colony batch` notes a check database on another computer, as `colony merge` does.
- The playbook's Lead section says the person comes first, what to do with the watchdog's alarms, and when to use `colony need` and `colony share`.
- `colony fast-check` runs `[project] fast_check` for the check areas the branch changes, and ends on one line for the done line: passed, failed or not run. A check that ran nothing counts as not run, in `colony batch`'s rounds too, never as a pass.
- `colony take <n>` prints the command that makes the card's worktree in `[project] worktrees`, which may now be relative. `colony tidy` removes the clean worktree of each finished card, batch, fix and retro, and the merge worktree when no merge runs.
- `colony helpers --open` and any background launch stop before opening a session that would wait on Claude Code's question about the repo's `.mcp.json` servers, and name the one-time step. A stale card whose helper waits on a prompt says so, with the `claude attach` command that answers it.
- Each role loads only its own lines: the lines only a builder or only the lead uses moved from each preset's core into the `colony-builder` and `colony-lead` skills.
- On Windows, git writes a symbolic link as a one-line text file when it can't make links, so a linked rule or skill never loads. `colony` and `colony join` say so, and `colony fix-links` turns each untouched stub back into a link in the repo and every worktree.

Security:

- Status comments and `live:` lines count only from the team's logins, or, with none set, from someone with access to the repo. Each field is checked.
- The push guard refuses a line it can't read when that line holds a `git push`.
- The push guard reads a push as git does: a shortened option such as `--del`, `--prune` and patterns such as `+refs/heads/*:refs/heads/*`, both readings of the first word after `--repo`, and, for a push that names no refspec, what `remote.<name>.push`, `remote.<name>.mirror` or `push.default` sends, such as every branch with `push.default=matching`. When git config can't say, or a command earlier on the line such as `git checkout` can change it, a forced push must name its branch.
- Only the person, at their own terminal, can switch the fast check off. No agent can.
- A private line goes out only after GitHub says, at that moment, that its repo is private.
- `colony share` asks for `--public` on a public repo, and refuses links, files that hold secrets, and files in folders such as `.ssh`.

Upgrading: `colony upgrade` refreshes the hooks and the role skills. `.colony/playbook.md`, `.colony/core.md` and `tools/board` are copies setup filled in, so copy them again from the package for the new rules, and fill in their placeholders as setup did. `[hack] deploy_environment` still counts.

## 0.5.0, 2026-11-07

Fast batches: a round checks and walks only what changed, a batch runs at most 3 rounds, and a rate limit moves a step to the next account instead of hanging it. Hack mode gets what a dry run of a two-person team found.

- With `[checks] areas`, a round runs only the check areas its change touched, through `{areas}` in `[project] checks`; a round after a fix adds the areas that failed. A change only under `[checks] skip` skips the checks. `[project] web_checks` is gone: a colony.toml that still has it is refused with a line naming `[checks] areas`.
- A failing test whose output names a timeout or a time limit runs once more by itself with `[checks] rerun`, and counts only when it fails again. Only a test whose every failure reason names a timeout or a time limit reruns, and a test with no reason never does. The round passes on its reruns only when nothing else in the output failed: a failed step, a test runner's `ERROR`, or a sign such as make's `*** [lint] Error 1` or a compiler's `error:`. Pytest's `ERROR path::test` lines now count as failing tests.
- The walk runs only when the change touches `walk_paths`, walks only the screens `[walk] screens` says the changed files feed, and can drive the `agent-browser` CLI with `[walk] browser = "agent-browser"`, with no MCP server loaded.
- `minutes.md` and the PR's minutes table show what each skipped or narrowed check run and walk saved, against `[checks] minutes` and `[walk] minutes` and `cost`.
- A batch runs at most 3 rounds. After the last, each review or walk finding still open becomes a card, and the PR opens listing them; failing checks still stop it.
- Agents stream their events, and Colony watches them: a step whose account hits its rate limit, a 429 that lasts 5 minutes or a Claude subscription's "You've hit your limit", runs again on the person's next account with room, and the batch stops naming the account when none has room. An agent silent for 20 minutes is stopped as failed.
- Ctrl-C, or SIGTERM, stops a batch with every agent, check and rerun it has running, each of which runs in its own process group.

Hack mode, from the dry run:

- A board at 300 comments (`[limits] board_comments`) moves to a fresh pinned `Board: <project>` issue that links the old one. `tools/board` follows it, and its reads stay incremental. When two posts move the board at once, the lowest fresh board is kept and the other closes with a link to it. A move that stopped half-way is finished on the board it opened, and a reader follows the old board's closing note before it searches by title.
- `colony merge` posts `[merged] <branch> → <base> <short sha>, fast check passed` on the board after it pushes.
- The wait guard refuses a `git push` that would force-push, rewrite or delete the base or the repo's default branch, in every mode. A plain push and a forced push of tags alone still run.
- `BOARD_WAIT=off` stops a `while tools/board wait; do <agent>; done` loop. `tools/board wait` asks GitHub only for what came since its last check.
- `AGENTS.md` asks for a `Not verified:` line, `DEPLOY: <what>, <when>, rollback: <how>`, file claims and releases, and handoffs that name a commit.
- Fixed: the prompt hook stayed off GitHub for a minute after `colony wait` ended, so it missed new posts.
- Fixed: hack setup wrote the setup person's worktrees path into the shared config. Hack's default, `~/worktrees`, now applies.
- docs/hackathon.md: only the person who runs setup needs Colony. Teammates clone, run `gh auth login`, and open Claude Code.

## 0.4.0, 2026-11-06

Colony comes with the repo, pinned like a package: a teammate clones, opens Claude Code and logs in.

- The repo carries `.colony/bin/colony`, a launcher pinned to one Colony version, which `colony hooks install` writes. It installs that version from its GitHub tag through uv once per computer, and installs uv when the computer has none.
- The repo's hooks run the launcher, and a SessionStart hook puts `.colony/bin` first on the Bash tool's PATH through `CLAUDE_ENV_FILE`.
- At most once a day, the lead sees one line when a newer release than the pin exists, with a link to what changed. `colony upgrade` moves the pin and refreshes the copied files on a branch, ready for a PR.
- The plugin's `colony` hands a repo that carries Colony to its launcher, and its hooks step aside where the launcher runs them.

## 0.3.1, 2026-11-06

- With both the plugin and `colony hooks install`, each hook runs once: a plugin hook steps aside where the repo's own copy can run, so a helper's error or approval line reaches its lead once.
- docs/install.md gives the plugin's real install commands.

## 0.3.0, 2026-11-06

Colony installs as a Claude Code plugin from GitHub, and the lead hears from its helpers sooner.

- Colony is a Claude Code plugin: the repo is a marketplace with one plugin, `puffin-colony`, carrying Colony's skills and hooks, and a session without the `colony` command is told how to install it (#21, #22).
- Colony runs on Windows, with every Windows difference in `colony/portable.py` (#4).
- `colony batch --fast` runs the full checks once and opens the PR (#5).
- Paid checks run inside the provider budget, with their spend in the PR (#6).
- `colony release` and `colony release --after` take the base into the release branch and back (#7), and warn the other leads first (#11).
- A helper's `done` line moves its card to In review (#8).
- The lead gets a `done` line at once while no batch runs (#9).
- The lead's wait raises a helper opened with `open` or `join` that posts no status within 5 minutes (#10).
- Colony finds cmux inside the app when it is not on PATH (#12).
- A tester role checks a release on the deployed app (#13).
- `colony sync` merges the base into a branch and rebuilds generated files (#14).
- `colony stats --calibrate` prints the median minutes per size (#15).
- A person can ask for a quiet lead with `[people.<person>] quiet_lead` (#16).
- Builders write one test per done-when result and post done at once (#17).
- Each new session takes its role name in the app's sidebar (#18).
- `colony join` tells its lead with a joined line (#19).
- A helper's line for `lead` reaches its own lead, and `colony say` takes `--urgent` (#20).
