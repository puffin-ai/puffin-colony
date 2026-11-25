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

`colony hooks install` merges Colony's hooks into `.claude/settings.json`, and keeps every hook and setting already there. Run it again to bring Colony's hooks up to date. `--dry-run` shows what it would write.

| Hook | When it runs | What it does |
| --- | --- | --- |
| The wait guard | Before every Bash call | Refuses a foreground sleep over 10 seconds, a loop that sleeps, an endless loop, `watch`, `gh run watch` and `gh pr checks --watch`. Its message says to use `run_in_background` or `colony wait`. A command sent to the background passes. |
| The push guard | Before every Bash call, in the background too | Refuses a push that force-pushes, deletes or mirrors a protected branch: the base, the repo's default branch, and `[safety] protect`. |
| The merge guard | Before every Bash call, and before a GitHub tool merges a pull request or commits onto a branch | Refuses what lands work on a branch without your yes. See [The merge guard](#the-merge-guard). |
| The kill guard | Before every Bash call, in the background too | Refuses a kill by name or pattern. See [The kill guard](#the-kill-guard). |
| `colony hooks asking` | When a builder waits on a permission pop-up | Posts `urgent: <builder> waits for a person's approval on <computer>` for its lead, at most once per 10 minutes. It drops the pop-up's text, which could quote a command, a path or a token. |
| `colony hooks stopped` | When a turn ends on an error | Posts `<session> stopped on an error (<code>) at <time>` for its lead, or for the person when the lead stops. It names the error's code word only, never its text. |
| `colony hooks ended` | When a session ends | Notes in the session ledger when it ended and Claude Code's reason, so the crash report can tell a person's exit from a signal or a crash. |
| `colony hooks tasks` | When a turn ends | Stamps the session ledger. When one of this session's background commands, such as its `colony wait`, stopped without finishing, it keeps the session going once with a note to start it again. See [Recovery](#recovery). |

In Hack and Solo, a prompt hook also runs when you send a prompt. It prints the lines `colony wait` saved for this session, then empties that list. It makes no network call while the wait runs, and otherwise one ETag-cached `gh api` call at most every 30 seconds.

A posting hook's line that `gh` can't post waits in `~/.colony/<project>/outbox.json`. The next hook run, or the next poll of any wait on the computer, posts it first, so it is never lost. A line behind others still waiting goes to the end, so the lines keep their order. The prompt hook also prints one line, at most once a day per session, when the session runs without `CLAUDE_CODE_RETRY_WATCHDOG=1`.

The wait guard is a standalone script, copied to `.colony/hooks/wait_guard.py`, and runs with any `python3` from 3.9 on. The push, merge and kill guards live in the same script, and run in every session in the repo, your own among them. The other hooks run only in a Colony session, one with `$COLONY_SESSION` set, and do nothing in your own sessions.

### The merge guard

No agent merges into any branch, or pushes into a protected one, without your yes. By default agents open pull requests, and you merge them. The guard refuses:

- `gh pr merge`, including `--auto`, unless the pull request's base branch is one `[safety] merge_into` names. To check, it asks `gh pr view` for the base. With `merge_into` empty, the default, it refuses every one without asking.
- A GitHub tool that merges a pull request, such as the GitHub MCP server's `merge_pull_request`, by the same rule.
- A `gh api` call that merges: a `PUT` to `pulls/<n>/merge`, a `POST` to `merges`, or a GraphQL `mergePullRequest`. Only `gh pr merge` may merge, because the guard can check its base.
- A plain `git push` that updates a protected branch, such as `git push origin main`, `git push` with `main` checked out, or `git push origin HEAD:main`, unless `merge_into` names that branch. A push of your own branch, a tag or a dry run passes.
- A GitHub tool that commits straight onto a protected branch of this repo, such as `push_files` or `create_or_update_file` with `branch` set to the base.

The protected branches are the base, the repo's default branch (origin's `HEAD`), and the branches and patterns in `[safety] protect`. That makes the default safe in any repo, whatever its branches are called. A force push, a deletion or a mirror push of a protected branch stays refused even when `merge_into` names it.

To let agents merge into a branch, such as an integration branch `dev`, add it to `[safety] merge_into` in `.colony/colony.toml` and merge that change into the base. The guard reads `merge_into` from two copies: the one on `origin/<base>`, which you merged, and the working copy. It allows a branch only when both name it. So an agent can't allow itself a merge by editing its own copy, and a branch you take out of your copy is refused at once. A clone with no `origin` reads the working copy alone. Hack's `colony merge <branch>` doesn't go through the guard: it follows `[gate] merge_after_fast_check`, which setup asks you.

A local `git merge` changes nothing on GitHub until a push, and the guard checks that push, so a lead can still merge cards into its batch worktree.

### The kill guard

A kill by name or pattern matches more than anyone means. On macOS, `pkill -f "colony wait" -U $(id -u) -n` reads each word after the pattern as one more pattern, and in one real run it ended every Claude Code session, the terminal app's helpers and every background task on the computer. The kill guard refuses:

- `pkill`, `killall`, `killall5` and `skill`, in any form, with `sudo`, `timeout` or `xargs` in front, or inside `bash -c` and `eval`;
- `fuser -k`, `taskkill /IM` or `/FI`, and PowerShell's `Stop-Process -Name` or a pipe into `Stop-Process`;
- a `kill` whose process ids come from a search of the running processes on the same line, such as `kill $(pgrep -f x)`, `pgrep x | xargs kill`, `kill -9 $(lsof -ti :3000)` or a loop over `ps` output;
- `kill -1`, `kill 0` and a negative id such as `kill -- -4242`, which signal every process you own or a whole process group.

It lets a kill of one known process run: a number, such as `kill 4242`, a job such as `kill %1`, `$!`, or an id from a file, such as `kill $(cat server.pid)`.

To close a finished Colony session, run `colony stop <name>`, which finds the session by its name in `claude agents` and ends that one process. For any other process, find the one you mean, check it with `ps -p <pid> -o pid=,command=`, and kill that number alone.

## Recovery

A crash, a kill or a sleeping laptop can stop many sessions at once. Colony keeps enough on the computer to say what stopped, why, and to bring it back.

**The session ledger.** Each Colony session keeps one file, `~/.colony/<project>/sessions/<name>.json`, which its own hooks write: its Claude Code session id, the folder it started in, its transcript's path, its account, person and lead, and when it last showed life. The session's start, each prompt and the end of each turn stamp it. A turn that ends on an error adds the error's code word, the end of the session adds Claude Code's reason, and `colony stop` adds that it stopped the session on purpose. The ledger holds Colony's own fields alone, never a prompt, a command or a token.

**`colony crash-report`** reads the ledger, `claude agents` and the end of each transcript. For each session of the last 24 hours, `[recover] within_hours`, it says whether it runs, stopped on purpose, or stopped unexpectedly, when it last showed life and what showed it: a hook, its transcript, its `colony wait` or its heartbeat. For an unexpected stop it names the likely cause, the strongest first:

- the computer started again after the session's last sign of life;
- some session ran a kill by name or pattern within two minutes before it;
- it stopped within 90 seconds of other sessions, so one event stopped them all;
- its last turn ended on a usage limit, a sign-in failure or another API error;
- Claude Code ended it with no exit by its person, as a signal or a closed window does;
- it stopped during a tool call, which may have ended it.

**`colony resume`** reopens each session that stopped unexpectedly, leads first, with `claude --resume <id>`: the same conversation, on the account that holds it, with its role's settings, in the folder it started in, in cmux or the background. Its first line says it was restarted, when, the likely cause, and what to start again. It reopens each session once, and leaves one stopped on purpose unless you name it. `--dry-run` shows each command first.

**Background commands.** A long command a session runs in the background, `colony wait`, `batch`, `fast-check`, `merge` or `retro`, keeps a file, `~/.colony/<project>/tasks/<pid>.json`, while it runs, and removes it when it ends, on an error too. A file whose process is gone means something stopped the command from outside: the agent tool, a kill or a crash. At the end of the owning session's next turn, the Stop hook keeps the session going once, with a note to start the command again, so a session never sits without its `colony wait`. The crash report lists such commands too.

**Services.** List the local services your work needs in `[recover] services`, each with a check and a command that starts it again. The crash report names each one whose check fails, and `colony resume` runs its restart command, then its check again. See [configuration.md](configuration.md#recover).

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
