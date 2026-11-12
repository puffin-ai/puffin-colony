# Changelog

## Unreleased

Hack mode holds up through a long day with several people, each with a lead on their own computer: leads see each other reliably, merges queue across computers, the demo has a clock, and everyone knows what is live. The parts that help every mode now work in every mode.

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

Security:

- Status comments and `live:` lines count only from the team's logins, or, with none set, from someone with access to the repo. Each field is checked.
- The push guard refuses a line it can't read when that line holds a `git push`.
- The push guard reads a push as git does: a shortened option such as `--del`, `--prune` and patterns such as `+refs/heads/*:refs/heads/*`, both readings of the first word after `--repo`, and, for a forced push that names no refspec, what `remote.<name>.push` or `push.default` sends, such as every branch with `push.default=matching`. When git config can't say, it refuses that push.
- Only the person, at their own terminal, can switch the fast check off. No agent can.
- A private line goes out only after GitHub says, at that moment, that its repo is private.
- `colony share` asks for `--public` on a public repo, and refuses links, files that hold secrets, and files in folders such as `.ssh`.

Upgrading: `colony upgrade` refreshes the hooks and the role skills. `.colony/playbook.md`, the hack rules in `.colony/core.md` and `tools/board` are copies setup filled in, so copy them again from the package for the new rules. `[hack] deploy_environment` still counts.

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
