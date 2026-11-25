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
| The push guard | Before every Bash call, in the background too | Lets a push run in two forms alone, onto a branch of the agent's own, and refuses every other. See [The push guard](#the-push-guard). |
| The merge guard | Before every Bash call, and before a GitHub tool merges a pull request or commits onto a branch | Refuses a merge you haven't allowed. See [The merge guard](#the-merge-guard). |
| The kill guard | Before every Bash call, in the background too | Refuses a kill by name or pattern. See [The kill guard](#the-kill-guard). |
| The subagent guard | Before every Agent call, in a Colony session | Refuses a subagent past `[subagents] max_running` (2) at once. See [The subagent guard](#the-subagent-guard). |
| `colony hooks asking` | When a builder waits on a permission pop-up | Posts `urgent: <builder> waits for a person's approval on <computer>` for its lead, at most once per 10 minutes. It drops the pop-up's text, which could quote a command, a path or a token. |
| `colony hooks stopped` | When a turn ends on an error | Posts `<session> stopped on an error (<code>) at <time>` for its lead, or for the person when the lead stops. It names the error's code word only, never its text. |
| `colony hooks ended` | When a session ends | Notes in the session ledger when it ended and Claude Code's reason, so the crash report can tell a person's exit from a signal or a crash. |
| `colony hooks tasks` | When a turn ends | Stamps the session ledger. When one of this session's background commands, such as its `colony wait`, stopped without finishing, it keeps the session going once with a note to start it again. See [Recovery](#recovery). |

In Hack and Solo, a prompt hook also runs when you send a prompt. It prints the lines `colony wait` saved for this session, then empties that list. It makes no network call while the wait runs, and otherwise one ETag-cached `gh api` call at most every 30 seconds.

A posting hook's line that `gh` can't post waits in `~/.colony/<project>/outbox.json`. The next hook run, or the next poll of any wait on the computer, posts it first, so it is never lost. A line behind others still waiting goes to the end, so the lines keep their order. The prompt hook also prints one line, at most once a day per session, when the session runs without `CLAUDE_CODE_RETRY_WATCHDOG=1`.

The prompt hook also shows a session its standing orders once when it starts, and any change to them since. For a lead, it adds a one-time reminder when its person has no personal profile yet, and a reminder to offer a correction as a standing order when the person's message reads like one. See [profiles.md](profiles.md#live-changes).

The wait guard is a standalone script, copied to `.colony/hooks/wait_guard.py`, and runs with any `python3` from 3.9 on. The push, merge and kill guards live in the same script, and run in every session in the repo, your own among them. The other hooks run only in a Colony session, one with `$COLONY_SESSION` set, and do nothing in your own sessions.

### The push guard

Working out exactly where git will push, through remotes, refmaps, `push.default`, upstreams, push URLs, URL rewrites, config and environment variables, is a game a guard loses. So the push guard allows one form of push, with its destination spelled out in full, and refuses every other:

```
git push [-u] [--force-with-lease] [--dry-run] <remote> HEAD:refs/heads/<branch>
git push [-u] [--force-with-lease] [--dry-run] <remote> <local branch>:refs/heads/<branch>
```

A builder pushes its branch as `git push -u origin HEAD:refs/heads/<branch>`. A full destination means git applies no refmap and ignores `push.default` and the upstream, so git config can't send the push to another branch.

- **The remote** is a plain name this clone's `git remote` lists, never a URL or a path, with no `remote.<name>.push` or `remote.<name>.mirror` in its git config, and its push address, after its `pushurl` and git's `pushInsteadOf`, is the repo it fetches from.
- **The branch** is a plain branch name, never a protected one: the base, the repo's default branch (origin's `HEAD`), or a branch or pattern in `[safety] protect`. For `HEAD`, the branch checked out must not be protected either, and nothing earlier on the line may change it.
- **Nothing else** joins them but `-q` and `-v`, which change only what git prints. A push is refused whatever its words when its line sets a `GIT_`, `HOME` or `XDG_CONFIG_HOME` variable, moves to another folder (`cd`, `git -C`, `env -C`, `sudo -D`, in any form the wrapper reads, such as `env -iC`, a prefix of `--chdir` such as `--c`, or a `-C` inside env's `-S` string), points git elsewhere (`git -c`, `--config-env`, `--git-dir`, `--work-tree`), or runs a `git config`, `git branch` or `git remote` before it.

So `git push --force`, `git push` alone, a short destination such as `git push origin feature`, `--all`, `--tags`, `--delete`, a `+` refspec and a push to a URL are all refused, and the message shows the allowed form. The merge guard also refuses a `git config` that sets a remote's push refspec or mirror, `push.default`, `remote.pushDefault`, or a branch's `merge`, `remote` or `pushRemote`. Work reaches a protected branch through a pull request, which you merge, or which an agent merges under the merge guard's rules. Hack's `colony merge <branch>` doesn't go through the guard: it follows `[gate] merge_after_fast_check`, which setup asks you.

### The merge guard

No agent merges into any branch without your yes. By default agents open pull requests, and you merge them. The guard refuses:

- `gh pr merge`, including `--auto`, unless the pull request is in this repo and its base branch is one `[safety] merge_into` allows. To check, it asks `gh pr view` for the base and the pull request's address. With `merge_into` empty, the default, it refuses every one without asking. Even then, it waits while the repo's `refs/colony/holds` holds a release freeze or a red hold on that branch, unless the hold names the pull request's branch or card ([releases.md](releases.md)), and while those holds can't be read. It reads them from GitHub with `gh api`, as it reads your yes, never through git, whose remotes an agent can change. Each GitHub read gets 10 seconds, and the guard's checks of one call get 50 seconds in all: past that, the call is refused, never let through. Claude Code waits 90 seconds for the guard's hook, longer than that, since it runs a call whose hook it stops.
- A GitHub tool that merges a pull request, such as the GitHub MCP server's `merge_pull_request`, by the same rule.
- A `gh api` call that merges: a `PUT` to `pulls/<n>/merge`, a `POST` to `merges`, or a GraphQL `mergePullRequest`. Only `gh pr merge` may merge, because the guard can check its base. A GraphQL query read from a file, with `-F query=@<file>` or `--input <file>`, is read from the call's folder and refused when it merges; one read from standard input, or from a file the guard can't read, is refused.
- A GitHub tool that commits straight onto a protected branch name, such as `push_files` or `create_or_update_file` with `branch` set to the base, or with no branch at all. In another repo than origin's, a protected branch name gets no yes.
- A command that changes what the guard reads as origin: `git update-ref` or `git symbolic-ref` on `refs/remotes/`, a fetch into `refs/remotes/` by hand, `git remote set-head` with a branch, `git remote set-url`, `rename` or `remove` of `origin`, `git config --edit`, and `git config` that changes a remote's URL, a fetch refspec, a URL rewrite or an include, and a `git -c` that reroutes a push. Ask the person to run these.

The protected branches are the base, the repo's default branch (origin's `HEAD`), the project's other long-lived branches, `[project] integration` and `release` and the branches in `[release] long_lived`, and the branches and patterns in `[safety] protect`. The guard reads each from both the working copy and origin's copy of colony.toml, so an edit of the working copy can't open one. A branch your project keeps for good but names nowhere, such as a `staging` branch Colony doesn't know about, is protected only once you add it to `[safety] protect`. A force push, a deletion or a mirror push of a protected branch stays refused even when `merge_into` names it.

**Where the yes comes from.** To let agents merge into a branch, such as an integration branch `dev`, add it to `[safety] merge_into` in `.colony/colony.toml`, and merge that change into the repo's default branch on GitHub. The guard counts a branch only when both the working copy and the copy on GitHub's default branch name it, and it reads GitHub's copy with `gh api`, never from a file or a ref on this computer, which an agent could edit. No other branch's copy counts, not even the base's, since an agent allowed to push there could write its own yes. When GitHub can't be read, as with `gh` signed out or offline, nothing is allowed. A branch you take out of your working copy is refused at once.

**Where origin is.** The guard knows this repo by where git says origin is, after git's URL rewrites, never by `[project] repo`. A yes holds only for a pull request in origin's repo, and comes from that repo's own default branch.

**Where a line hides a merge.** The guard follows `sh -c`, `eval`, `sudo`, and git and gh aliases to the command they run, and refuses an `xargs` or a shell alias that builds a push or a merge. A `gh pr merge` that shares its line with a `cd`, a wrapper that moves it, such as `env -C` or `sudo -D`, or a `GH_` or `GIT_` variable is refused: run it on a line of its own, with `--repo` for another repo.

**What it costs.** A merge into an allowed branch makes one `gh api` call, and a push makes none. The protected list itself comes from this computer: the working copy, origin's `HEAD` and origin's copy of colony.toml, so an agent that edits the working copy's `base` or `protect` can narrow it, though never below the default branch.

### What a hook can't do

The guards stop an agent's honest mistakes, and the easy ways around them. They can't stop an agent that sets out to get past them: one that edits `.claude/settings.json`, the guard script or `.git/config` by hand, or runs a program the guard never reads, such as a Python script or a make target, can switch them off. The guards do read a shell script a line runs, as `bash <file>`, `sh <file>`, `source <file>`, `. <file>` or `./<file>`, and the scripts it runs in turn, and refuse one that holds a push, a merge or a kill, or nests them deeper than they follow. A shell that reads its script on standard input is read from the regular file a `<` or a plain `cat <file> |` gives it, and refused when fed by anything else, such as `curl <url> | sh`, a here-document or process substitution: save the script, read it, and run it as `sh <file>`. A file run by its path, such as `./run.sh`, is read as shell commands when its `#!` line names a shell, or when it has none and isn't a compiled program; a `#!` that names another interpreter it knows, such as node or python, runs a program it doesn't read, so `./node_modules/.bin/tsc` runs, though a program whose text names a push, a merge or a kill is refused. A `#!` it doesn't know is read as shell commands. A file named with variables is read where the variables say. A name resolves only when the script sets it once, in its opening lines before any other command (comments and `set -eu` aside), to a plain value, or to one of the common idioms that name its own folder or its repo's top folder, and names it nowhere else but as `$name` or `${name}`. The idioms are `$(dirname "$0")` and `$(dirname "${BASH_SOURCE[0]}")`; either inside `$(cd … && pwd)` or `pwd -P`, with `>/dev/null 2>&1` or not, or wrapped in `realpath` or `readlink -f`; `$(dirname "$(realpath "$0")")`; and `$(git rev-parse --show-toplevel)`, the repo's top folder. So `DIR="$(cd "$(dirname "$0")" && pwd)"` then `source "$DIR/lib.sh"` runs. Any other value, such as a folder above the script's, stays refused; otherwise, for an upper-case name the script never binds and the shell doesn't set itself (`PWD` and `REPLY` are the shell's), it takes this computer's value, unless the line that ran the script sets or exports it. A name set in a branch, after its use, more than once, or bound in any other way, such as `read`, `printf -v`, `{name}>` or an assignment from a command, has no value the guard can know, and a file named with it is refused; so is any file named with a variable in a script that holds `eval`, a function, an alias, `declare`, `local`, `let`, arithmetic, an array element, or a command that binds a name made at run time, such as `read "$n"`. A file a script sources with `source` or `.` runs in the script's own shell, so the script's values hold past it only when the guard reads that file and finds nothing in it that may change them: it names none of them but to read them, holds none of the above but its own functions and `local`, sources nothing more, and steers nothing. Otherwise, or for a source the guard can't place, such as `builtin source`, no variable in the script resolves. A sourced file's `$0` is the script's that sourced it, so there only `${BASH_SOURCE[0]}` names the file's own folder. A typed line's `$0` is the shell's, so its `dirname "$0"` names no folder. The guard splits a script's lines as the shell does, at a newline alone: a script that holds another control character, such as a form feed or a carriage return, or a Unicode line separator, resolves no variable. A name glued to an option, such as `read -aX`, counts as a mention, and a script follows no value of its own when it, or the line that runs it, may change how it reads its lines: a script that sets `PATH` (zsh's `path` too, and the other search paths in either case), `IFS`, `HOME`, `LD_` or `DYLD_` names, or passes a function down (`BASH_FUNC_`, `export -f`), and a line that runs `env` with options or sets any name but a few that change no shell's reading, such as `CI` or `NODE_ENV`, since its `dirname` may not be the one the guard expects. The guard reads the names a line binds as the shell does, quotes taken off, so `export P"ATH"=x` binds `PATH`, and a name it can't read, such as `export "$n=x"`, leaves every variable unresolved. npm's and pnpm's launchers in `node_modules/.bin` run `"$basedir/node"` when that file is there and the `node` on your PATH when it isn't: the guard knows these launchers line for line, reads the file beside one when it is there, and lets the launcher run when it isn't, unless an earlier command on the line may write a file and none builds. Any command counts as a possible write but a short list that writes none, such as `cd`, `echo`, `rm` or `mkdir`. A program that doesn't exist yet runs when a build tool earlier on the same line makes it, as in `go build -o bin/app . && ./bin/app`; otherwise it is refused until it exists. After a plain `cd` or `pushd` to a folder named in full on the same line, a script is read from that folder; after a `cd` the guard can't follow, such as one with no folder, `~`, or with `CDPATH` or `HOME` set, a relative script is refused. These refusals come from the script guard, which says what it couldn't check and why; a push, merge or kill it finds inside a script is refused by that guard. Colony's own launcher, `.colony/bin/colony`, runs too: the guard knows the one line in it that installs uv. The guards know sh, bash, rbash, zsh, dash, ksh, mksh, oksh, loksh, pdksh, ash, yash, posh, csh, tcsh and fish, with a version too, such as bash5, and `busybox sh`. They read a script's text with the same reading as a typed line, so quotes such as `git "push"` hide nothing, and follow wrappers such as `timeout`, `nohup` and `env`, whose options they read as env does, `-S` strings included; an `env` they can't read is refused, and so is an `-S` string that holds a `#`, a `\` or a `$`, which env reads its own way (a `#` drops the rest of the string). A line where another program names a shell among its words, such as `caffeinate -i bash x.sh`, `xargs bash`, `find -exec bash`, `git rebase --exec 'bash x.sh'` or `ssh host bash x.sh`, is refused, since the guard can't tell whether it runs it, and so is a shell named anywhere in what `sed` or `awk` runs. Programs that only look at their words, such as `which bash` or `grep bash`, run. An agent also acts with your GitHub login, so GitHub can't tell its push or merge from yours.

**Known limits.** The script check reads the shell as the shell does in the common cases and refuses what it can't follow, but the shell has more corners than a guard can model, and every extra rule risks refusing ordinary work. These ways around the guards are known, and left to the real lock below:

- A program the guard doesn't read, such as a Python or node script, a make target or a build tool, can push, merge or kill.
- A program an earlier call put on PATH, such as a `git`, `dirname` or `uname` of its own, runs in place of the real one, and the guard reads the line as if it were the real one.
- An agent that edits the guard, `.claude/settings.json` or `.git/config` by hand can switch the guards off.
- A shell construct the script check reads differently from the shell. Reviews found these, which the guards don't follow:
  - the shell's own prefixes before a command that binds a name, such as `builtin export PATH=…`, or zsh's `noglob` or `-`;
  - quotes in the operands of a binding command other than `export`, `readonly`, `unset` and `env`, such as `read 'X'`, whose names the guard reads from the raw text;
  - zsh's `${name::=value}`, which always assigns, and parameter flags such as `${(P)name}`, which name a variable through another.
  - a `cd` in a file a script sources, which moves the script's later lines to another folder.

  When a review finds another such way around the guards, it goes on this list rather than into more guard code.

The real lock is on the code host: branch protection, or a ruleset, that refuses a direct push, a force push and a deletion on the base and the other protected branches, and asks for a pull request. When someone else on the team reviews, require their approval too, since GitHub never counts an author's own. `colony safety protect` turns that on for you through `gh api`, and `--dry-run` prints what it would set first. See [Second locks you should add](#second-locks-you-should-add).

A local `git merge` changes nothing on GitHub until a push, and the guard checks that push, so a lead can still merge cards into its batch worktree.

### The kill guard

A kill by name or pattern matches more than anyone means. On macOS, `pkill -f "colony wait" -U $(id -u) -n` reads each word after the pattern as one more pattern, and in one real run it ended every Claude Code session, the terminal app's helpers and every background task on the computer. The kill guard refuses:

- `pkill`, `killall`, `killall5` and `skill`, in any form, with `sudo`, `timeout` or `xargs` in front, or inside `bash -c` and `eval`;
- `fuser -k`, `taskkill /IM` or `/FI`, and PowerShell's `Stop-Process -Name` or a pipe into `Stop-Process`;
- a `kill` whose process ids come from a search of the running processes on the same line, such as `kill $(pgrep -f x)`, `pgrep x | xargs kill`, `kill -9 $(lsof -ti :3000)` or a loop over `ps` output;
- `kill -1`, `kill 0` and a negative id such as `kill -- -4242`, which signal every process you own or a whole process group.

It lets a kill of one known process run: a number, such as `kill 4242`, a job such as `kill %1`, or `$!`.

The kill, push and merge guards read every line of a command, a here-document's body too. Beside that, a line whose raw text names a kill, a `git push` or a `gh` merge anywhere must be one plain command of that kind: no `;`, `&`, `|`, second line, `$(`, backtick, here-document, `<(` or `>(`, no `$'`, `$"` or backslash, whose quoting the guard's reader may read otherwise than the shell, and no `eval`, `sh -c`, wrapper, assignment, alias or function around it. The raw text names exactly one, at the very start of the line, so the command it names is the one the guard reads. Even `2>&1` is refused on such a line. Quoting the shell reads otherwise can hide a command from the guard's reading, as a here-document body line such as `don't` can, and one plain command leaves nothing to hide. So run each push, each kill by its exact id, and each pull request step as its own plain command. Text that only names one is refused too, such as `grep -rn pkill`, `echo gh pr merge 5`, or a commit message that names `git push`. Write such text, such as a commit message or a pull request body, to a file with your file tool and pass the file (`git commit -F <file>`, `gh pr create --body-file <file>`), and search with your search tool; the refusal says so. That way out is for text alone: a push, a merge or a kill moved into a script or a query file is still refused. Only the wait guard skips here-document bodies, which hide nothing it guards.

To close a finished Colony session, run `colony stop <name>`, which finds the session by its name in `claude agents` and ends that one process. For any other process, find the one you mean, check it with `ps -p <pid> -o pid=,command=`, and kill that number alone.

### The subagent guard

Builders run as helpers Colony opens, never as subagents: a subagent runs on its session's own account, where Colony can't place it, cap it or count it, and enough of them inside a lead drain the lead's account and stop the whole team at once. See [capacity.md](capacity.md#builders-are-helpers-never-subagents).

The subagent guard runs before every Agent call (Task in older Claude Code versions) in a Colony session: one with `$COLONY_SESSION`, or one a person opened that `colony` or `colony claim` made a lead. It counts the subagents the session runs now from the files Claude Code keeps beside the session's transcript: one not marked finished, whose transcript moved in the last 15 minutes, still runs. A call it let through counts too until its subagent's files appear, since calls made side by side start before their files exist. Past `[subagents] max_running` (2), it refuses the call:

- a lead or an orchestrator hears that builders run as helpers, opened with `colony helpers <n> --open` or `colony open <name>`, and to keep a subagent for a quick search or a browser check;
- a helper hears to wait for one of its subagents to finish, or to do the piece itself.

It is a standalone script, copied to `.colony/hooks/agent_guard.py`, and runs with any `python3` from 3.9 on. It keeps the calls it let through in `~/.colony/subagents/<session id>.json`. Your own sessions, outside Colony, are never capped.

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

**Services.** List the local services your work needs as `[services.<name>]` tables, each with a check and a `restart` command that starts it again. They are the same tables `colony services` and the lead's wait check, judged the same way. The crash report names each one whose check fails, and `colony resume` runs its restart command, then its check again. See [configuration.md](configuration.md#services).

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

- **Protect your base branch on GitHub.** Require a pull request and a review. Then even a mistaken push is refused. `colony safety protect` sets a ruleset for the base, the default branch, the integration, release and `[release] long_lived` branches, and `[safety] protect`, which refuses direct, forced and deleting pushes; `--reviews 1` also asks for another person's approval. It leaves out the branches Colony itself pushes for a release, `<project>/release-*` and `<project>/sync-*`, whatever `[safety] protect` matches, and the freeze's holds are no branch, so a release still works under it. In Hack, that also refuses `colony merge`'s push, so either leave the base open for the event or set `merge_after_fast_check = false`.
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
