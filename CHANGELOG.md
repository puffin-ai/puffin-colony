# Changelog

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
