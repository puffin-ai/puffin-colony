# Safety

Colony gives agents real work in your repo. They read code, run commands, start your stack, commit and push. This page says what Colony never does, what its agents ask you first, and what you should know before your first batch.

Some guarantees are locks in Colony's code. Some are hooks Claude Code runs on every session. Others are rules the agents follow. This page keeps them apart.

## Locks in the code

- **It never pushes to your base branch.** A batch makes one push, naming its own branch in full: `refs/heads/<project>/batch-<name>`. It refuses to push any branch that is the base branch or doesn't start with `<project>/batch-`. The retro pushes only `<project>/retro-<batch>`, under the same check. Fixers commit and never push. Setup pushes only `colony/setup`. The one exception is Hack's `colony merge <branch>`: it pushes the base only when `[gate] merge_after_fast_check = true` and the fast check passed on the merged result, never force-pushes, and opens a PR otherwise.
- **It never prints env values.** `--dry-run` prints the names of the variables it would set, never their values. The values in `check_env_file` go only into the checks' environment.
- **A line never carries a secret.** `colony post`, `colony say` and the hooks refuse a line that holds a token's shape, or the value of an env variable whose name says it is a key, token, secret or password.
- **The gate's agents never bill an API key.** The reviewer, walker, fixers and retro run with `ANTHROPIC_API_KEY` removed from their environment, so they always run on your Claude Code login. The lead and builders drop it too, unless `use_api_key = true`.
- **Your checks get no provider keys at a zero budget.** While `provider_dollars` is 0, the checks run without `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`, so your app's own evals can't spend.
- **A batch can't loop for ever.** It stops after `max_rounds`, when the checks fail the same way twice in a row, when a fixer commits nothing, or when an agent fails twice.
- **Removed tests are shown.** The PR body lists every test file the batch deletes, so a test can't vanish without you seeing it. `colony tier` puts a deleted test, a skip mark or a new suppression on the risk list.
- **Only the lead asks you.** `colony needs`, `colony handover` and `colony say` refuse to run outside the lead's session.
- **Setup reads settings folders by name only.** It never reads the files inside them.

## Hooks

`colony hooks install` merges three hooks into `.claude/settings.json`, and keeps every hook and setting already there. Run it again to bring Colony's hooks up to date. `--dry-run` shows what it would write.

| Hook | When it runs | What it does |
| --- | --- | --- |
| The wait guard | Before every Bash call | Refuses a foreground sleep over 10 seconds, a loop that sleeps, an endless loop, `watch`, `gh run watch` and `gh pr checks --watch`. Its message says to use `run_in_background` or `colony wait`. A command sent to the background passes. |
| `colony hooks asking` | When a builder waits on a permission pop-up | Posts `urgent: <builder> waits for a person's approval on <computer>` for its lead, at most once per 10 minutes. It drops the pop-up's text, which could quote a command, a path or a token. |
| `colony hooks stopped` | When a turn ends on an error | Posts `<session> stopped on an error (<code>) at <time>` for its lead, or for the person when the lead stops. It names the error's code word only, never its text. |

In Hack and Solo, a prompt hook also runs when you send a prompt. It prints the lines `colony wait` saved for this session, then empties that list. It makes no network call while the wait runs, and otherwise one ETag-cached `gh api` call at most every 30 seconds.

A posting hook's line that `gh` can't post waits in `~/.colony/<project>/outbox.json`. The next hook run, or the next poll of any wait on the computer, posts it first, so it is never lost. A line behind others still waiting goes to the end, so the lines keep their order. The prompt hook also prints one line, at most once a day per session, when the session runs without `CLAUDE_CODE_RETRY_WATCHDOG=1`.

The wait guard is a standalone script, copied to `.colony/hooks/wait_guard.py`, and runs with any `python3`. The two posting hooks run only in a Colony session, one with `$COLONY_SESSION` set, and do nothing in your own sessions.

## The suppressions ledger

`colony suppressions` counts each kind of lint and type suppression in each tracked file: `# noqa`, `# type: ignore`, `eslint-disable`, `@ts-expect-error`, `@ts-ignore`, skipped tests, `nolint`, `#[allow(...)]`, `@SuppressWarnings` and more. `# NOQA` counts as `# noqa`, since ruff and flake8 read it in any case, and a stylesheet counts the type and test-skip kinds a script does. It compares the counts with `.colony/suppressions.json`.

- A count above the record fails, with the reminder that no agent weakens a check to make it pass.
- A count below the record fails too, until `colony suppressions --update` lowers the record. The record only shrinks: `--update` never raises a count or adds a file.

Setup writes the first record and adds `&& colony suppressions` to your `checks`, so every batch runs it.

## Rules the agents follow

**The core** in `.colony/core.md` loads in every session. Its duties: report each check's real result, quote the output behind every success claim, never weaken a check, keep secrets out of output, and add no dependency or spend without your yes. See [presets.md](presets.md#the-three-levels).

**The stop list.** No agent does these without your yes:

- spend money: paid services, or model calls above the budget;
- show, copy or move a secret: keys, tokens, passwords, `.env` values;
- delete data: databases, issues, or files and branches that aren't its own;
- add, remove or upgrade a dependency;
- merge into the base branch, or push to it, except through `colony merge` in Hack, when setup's yes allowed it.

A builder that meets one sends it to the lead as a question. Only the lead asks you, on your Needs issue, with its own pick as the default.

The core and the stop list are instructions, not locks: a model can still get one wrong. The locks and hooks above, and the second locks below, are there for that case.

## What the agents can do

- **The reviewer, walker, fixers and retro** run headless with `claude -p --permission-mode auto`. That is Claude Code's auto mode, where a classifier approves or blocks each action instead of asking you. Each works in its own worktree. The reviewer is told to change nothing, the walker to leave the batch's worktree alone, and fixers not to push.
- **The lead, builders, researcher and spec agent** run interactive, under the role's `permission_mode`, `auto` by default, and your own Claude Code permission settings. They inherit the shell you start `colony` from.
- **The researcher and the spec agent** change no app code, and work on their own `research/` or `spec/` branch.
- **Every interactive session starts with Remote Control**, under a title such as `myapp-lead`, so you can follow it from your Claude account.

## Second locks you should add

- **Protect your base branch on GitHub.** Require a pull request and a review. Then even a mistaken push is refused. In Hack, that also refuses `colony merge`'s push, so either leave the base open for the event or set `merge_after_fast_check = false`.
- **Start `colony` from a shell without `ANTHROPIC_API_KEY`.**
- **Keep `.env` files and `check_env_file` out of git.**
- **Run `--dry-run` first,** for setup and for your first batch.
- **Read the PR's "Removed tests" section** before you merge.

## What leaves your machine

- **Code and prompts go to Anthropic,** the same as in any Claude Code session.
- **Cards, lines, the board, your Needs issue and PRs go to GitHub.** On a public repo they are public, so keep secrets and personal data out of them.
- **The batch reports are committed** to the batch branch: the review, walk and check summaries, the minutes and the PR body. The raw logs stay local.
- **The researcher fetches public pages** to cite them, and pays for no source.
- **Context7,** when you accept it, sends library lookups to its service. Playwright runs on your machine.

## Accounts

Colony uses your Claude Code login. Most teams list one account per person in `colony.toml`. Spreading one person's work across several seats may conflict with [Anthropic's terms](https://www.anthropic.com/legal), so check them before you list more than one for yourself.
