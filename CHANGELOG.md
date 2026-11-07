# Changelog

## 0.5.0, 2026-11-07

Fast batches: a round checks and walks only what changed, a batch runs at most 3 rounds, and a rate limit moves a step to the next account instead of hanging it.

- With `[checks] areas`, a round runs only the check areas its change touched, through `{areas}` in `[project] checks`; a round after a fix adds the areas that failed. A change only under `[checks] skip` skips the checks. `[project] web_checks` is gone: a colony.toml that still has it is refused with a line naming `[checks] areas`.
- A failing test whose output names a timeout or a time limit runs once more by itself with `[checks] rerun`, and counts only when it fails again. Pytest's `ERROR path::test` lines now count as failing tests.
- The walk runs only when the change touches `walk_paths`, walks only the screens `[walk] screens` says the changed files feed, and can drive the `agent-browser` CLI with `[walk] browser = "agent-browser"`, with no MCP server loaded.
- `minutes.md` and the PR's minutes table show what each skipped or narrowed check run and walk saved, against `[checks] minutes` and `[walk] minutes` and `cost`.
- A batch runs at most 3 rounds. After the last, each review or walk finding still open becomes a card, and the PR opens listing them; failing checks still stop it.
- Agents stream their events, and Colony watches them: a step whose account hits its rate limit stops within 2 minutes and runs again on the person's next account with room, and the batch stops naming the account when none has room. An agent silent for 20 minutes is stopped as failed.

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
