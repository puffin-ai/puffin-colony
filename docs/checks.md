# Checks

Colony tests less and watches more. A check runs the tests for what changed, not the whole suite. A slow check goes on in the background while work continues. Its first failure shows the moment it appears. A check that already passed on the same code never runs again. And `colony ci` starts the project's CI on any commit and posts the result where the team sees it.

All of this lives in `colony/checks.py`. Its settings are `[checks]` and `[ci]` in [configuration.md](configuration.md#checks), and its commands are in [commands.md](commands.md#checks).

## Why

In one long run, a team of leads and helpers ran the full suite far more often than it needed to. Each run took about 25 minutes. People waited on runs, learned of a failure only when a whole run ended, tested the same commit again and again, and started and watched CI by hand. The rules below remove each of those costs.

## Test in proportion to the change

`[checks] scope` says what a check runs. It has three values.

| Scope | What a check runs | When it is the default |
| --- | --- | --- |
| `related` | The tests for the changed code, plus the repo's guard tests, beside `[project] fast_check` for the areas the change touches | Once `[checks] related` names a command |
| `areas` | The check command for the areas the change touches, as Colony always did | Without `[checks] related` |
| `full` | `[project] checks` for every area: the full suite | Never. `--full` asks for it, as at release time or when the person asks |

So a repo that sets nothing new keeps checking the way it did.

**How Colony finds the tests for a change.** For each changed file:

- A changed test is its own test.
- A changed file in a test folder that is not a test, such as `conftest.py`, a helper or a fixture, runs the nearest folder above it that holds tests.
- A code file runs the tests named after it: `test_board.py`, `board_test.go`, `board.test.ts`, `Board.spec.tsx`, `BoardTest.java` or `board_spec.rb` for `board.py` or `Board.tsx`. When several folders hold one, the nearest wins.
- `[checks] tests` maps any other file to its tests, such as `{ "setup.cfg" = ["tests/"] }`.
- A file under `[checks] skip`, such as a docs page, counts for nothing.

**Guard tests** are the tests that protect the whole repo, such as architecture or import-boundary tests. `[checks] guards` lists them, and they run with every related check. As a table of check areas, each area's guards run when the change touches that area.

**The command.** `[checks] related` is the command that runs the tests. `{tests}` in it takes the tests Colony found and the guards. `{files}` takes the changed files themselves, for a runner that finds the tests itself, such as `vitest related {files}` or `jest --findRelatedTests {files}`. In a repo with several apps, give each check area its own command, and its own folder with `in`:

```toml
[checks]
areas = { web = ["apps/web/"], api = ["apps/api/"] }
related = { web = { run = "npx vitest run {tests}", in = "apps/web" }, api = "uv run pytest {tests}" }
guards = { api = ["apps/api/tests/test_architecture.py"] }
```

With `in`, the paths start from that folder, so the web command above gets `src/week.test.ts`.

**Nothing goes unchecked.** A changed file that no test names is listed, as `note: no test names <file>`, and in the batch's `checks-<round>.md`. When no fast check, no guard and no test covers a code change, the check runs the area's check command instead, as the `areas` scope would.

**In a batch.** Each round runs the related check for that round's change. A round after a fix also runs the tests that failed in the round before, so the fix is proven. `colony batch --full` runs the full suite every round. A fixer's prompt names the related check for its findings' files.

## Every check fast, or in the background

Each kind of check has a time budget in seconds, `[checks] budgets`:

| Kind | Used by | Default |
| --- | --- | --- |
| `fast` | `colony fast-check` | 300 |
| `checks` | `colony check run`, and a batch round | 300 |
| `full` | `--full`, the full suite | 0 |

A command follows its check's output up to the budget. Past it, the command returns and the check goes on in the background, so no one waits. A budget of 0 sends the check to the background at once, which is why the full suite never holds anyone up. `--wait <seconds>` sets the budget for one run.

A check that returns early ends on this line, and exits 3:

```text
fast check: running in the background past its 300 s budget, so work goes on: `colony check watch fast-…` follows it, and `colony check status` shows it
```

`[checks] caps` stops a run past its cap, in seconds, and counts it as failed. Without a cap, a run goes on until it ends. A batch round past its cap stops the batch. Every command that runs a check follows the same settings: `colony merge` runs the fast check for the merged change in `[checks] scope` and stops it past the `fast` cap, a batch whose gate runs the fast check stops its round past the `fast` cap, and a batch's run on its start commit and its reruns stop at the round's cap.

Each run lives on this computer, under `~/.colony/<project>/checks/runs/`: its state, and its whole output in a log. `colony check status` lists the runs, the running ones first, with how long each has run against its budget and its first failure. `colony status` lists the running ones too. Colony keeps the newest 50 ended runs.

## Watch runs live

A check's output streams to the command that follows it, line by line. The moment a line shows a failure, the run marks it as its first failure, and every command that follows the run prints it at once:

```text
colony: first failure, 42 s in: FAILED tests/test_board.py::test_moves
```

`--until-failure` returns right there, with exit 1, and leaves the rest running, so fixing starts while the other tests run. `colony check watch <run> --until-failure` does the same for a run already going.

A line shows a failure when it is pytest's `FAILED` or `ERROR` line, a pytest progress line with an `F` or `E`, a JS runner's `FAIL` or `×` line, go's `--- FAIL:`, cargo's `... FAILED`, TAP's `not ok`, make's `***`, npm's `npm ERR!`, or a check script's `FAIL <step>` line. `[checks] failure` adds the repo's own sign, as a regular expression.

In a batch, the round's first failing line goes into `state.json`, and the batch prints it as it comes. `colony status` shows it: `checks, round 1: first failure at 10:42: …`.

## No repeated runs

Colony keeps each result in a ledger, `~/.colony/<project>/checks/ledger.json`, by:

- the code it ran on: a git tree that holds the checkout's uncommitted and new files too, so the same files give the same tree whatever the commit;
- the command, with its areas and tests filled in;
- a digest of `[project] check_env_file`, so a changed env file runs again. The values are never kept.

A pass on the same code with the same command is reused, and says so: `fast check: passed …: (reused: it passed on this same code at 10:03 …)`. `--again` runs it anyway, and `[checks] reuse = false` turns reuse off. A check that failed always runs again when you ask for it.

Two more rules keep runs from piling up:

- **Join, don't repeat.** When the same check on the same code is already running, a second command joins that run and follows it.
- **Cancel what newer code made pointless.** A new run in the same checkout, of the same kind, on other code, cancels the older one.

A batch reuses a pass for its head's code, and the answer of its start-commit check, which tells whether a failure was there before the cards. So a second batch from the same start never runs that check again.

## CI on any commit

```sh
colony ci [<ref>]
```

It works with any CI. Colony reads the code host's checks on the commit, which every CI reports, and names no workflow.

1. **It skips what already ran.** When CI already passed on the commit, it says so and stops. When checks already run there, it watches them instead of starting new ones. `--again` starts it anyway.
2. **It starts CI.** `[ci] start` is the command that starts your CI, with `{sha}`, `{short}`, `{branch}` and `{repo}` filled in, such as `gh workflow run ci.yml --ref {branch}`. Without it, Colony pushes the commit to a branch of its own, `[ci] branch` (`colony-ci/<short sha>`), which starts any CI that runs on a push, unless a branch on origin already holds the commit. It deletes that branch once CI ends.
3. **It cancels what the commit made pointless.** Runs on older commits of the same branch, ones the commit builds on, are cancelled through `gh run cancel`. Runs on other commits are left alone. `[ci] cancel_superseded = false` turns this off.
4. **It watches live.** Every `[ci] poll_seconds`, it reads the commit's check runs and statuses, prints each check as it ends, and prints the first failure at once. `--until-failure` returns there. It stops watching after `[ci] wait_minutes`, and says how to start CI when no check shows within `[ci] start_minutes`.
5. **It posts the result where the team sees it.** On the commit's open pull request, else on the commit itself, or on a card with `--issue <n>`: the result, a table of every check with its link, and the first failure. `--no-post` or `[ci] post = false` posts nothing.

It keeps the result in the ledger, so `colony check status` shows CI on the checkout's commit beside its own checks.

## Exit codes

| Code | `colony fast-check`, `colony check run`, `colony check watch`, `colony ci` |
| --- | --- |
| 0 | Passed, or reused a pass |
| 1 | Failed, or failing at its first failure with `--until-failure` |
| 2 | Not run: the change touches no check area, or the output only says NOT RUN |
| 3 | Still running in the background past its budget |
