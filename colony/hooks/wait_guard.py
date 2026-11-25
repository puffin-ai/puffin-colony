#!/usr/bin/env python3
"""Puffin Colony's wait guard: refuse a Bash call that waits in the foreground, so a session never blocks on a poll.
The same script holds the push guard, the kill guard and the merge guard, described below.

Claude Code runs it before each Bash call, with the call as JSON on stdin. Exit code 2 refuses the call, and stderr
names the way to wait instead: run_in_background, or `colony wait`. `colony hooks install` copies this file into a
repo's .colony/hooks/ and adds it to .claude/settings.json. Standard library only, and it imports nothing of Colony's,
so it runs with any python3, 3.9 and later.

In the foreground it refuses a sleep longer than MAX_SLEEP_SECONDS; a while, until, for or select loop that sleeps;
an endless `while true`, `while :` or `until false` loop; watch, `gh pr checks --watch` and `gh run watch`; and a
`python -c` program that sleeps long or sleeps in a loop. A call made with run_in_background passes, and so does a
command, loop or group the line ends with &. A `wait` on the jobs the same line started passes, and those jobs'
waits become its own, so `sleep 600 & wait` is refused. A sleep whose length it can't read, such as `sleep $DELAY`,
passes. It drops here-document bodies first, because a body is text a command reads, not a command; the push, kill
and merge guards below read bodies as commands, so no here-document the guard misreads can hide one. A line whose
quoting Python's shlex can't read, such as a $(...) holding quotes inside a double-quoted word, which the shell reads
fine, passes too, unless its plain text holds a sleep over MAX_SLEEP_SECONDS.

The push guard lets a `git push` run, in every mode and even in the background, only in one form, with its
destination in full, and refuses every other: `git push [-u] [--force-with-lease] [--dry-run] <remote>
HEAD:refs/heads/<branch>`, or a plain local branch in place of HEAD (-q and -v may join it, since they change only
what git prints). A full destination makes git apply no refmap and ignore push.default and the upstream. The remote
is a plain name this clone's `git remote` lists, with no remote.<name>.push or remote.<name>.mirror in its git config,
whose push address, after its pushurl and git's pushInsteadOf, is the repo it fetches from. The branch is a plain
branch name, never a protected one: the base, `[project] base` in .colony/colony.toml (main when
unset), the repo's default branch, origin's HEAD (main when git can't say), and `[safety] protect`. For HEAD, the
branch checked out must not be protected either, and nothing earlier on the line may change it. A push is refused
whatever its words when its line sets a GIT_, HOME or XDG_CONFIG_HOME variable, moves it to another folder (a cd, `git
-C`, `env -C`, `sudo -D`), points git elsewhere (`-c`, --config-env, --git-dir, --work-tree), or runs a `git config`,
`git branch` or `git remote` before it: working out where git then pushes is a guess, and the guard doesn't guess.
Land work on a protected branch through a pull request. A line whose quoting it can't read is refused whenever it
holds `git` and `push`: run such a push on its own.

The kill guard refuses, in every mode and even in the background, a kill by pattern or by name: pkill, killall,
skill, `fuser -k`, `taskkill /IM` and PowerShell's `Stop-Process -Name`, and a `kill` whose process ids come from a
search of the running processes on the same line, such as `kill $(pgrep -f x)`, `pgrep x | xargs kill` or a loop over
`ps` output. It also refuses `kill -1`, `kill 0` and a negative id, which signal every process or a whole group. A
pattern matches more than anyone means: on macOS, `pkill -f "colony wait" -U $(id -u) -n` reads each word after the
pattern as one more pattern, and ended every Claude Code session on the computer. A kill of numbers, job specs such
as %1, or `$!` passes. A session closes another by name with `colony stop <name>`.

The merge guard refuses a merge the person hasn't allowed. A `gh pr merge`, and a GitHub tool's merge of a pull
request, pass only when the pull request is in this repo, origin's, and its base is a branch `[safety] merge_into`
allows; a `gh api` call that merges is refused, since `gh pr merge` is the way the guard can check. A GitHub tool that
commits straight onto a protected branch name is refused unless `merge_into` allows it in this repo.

What the person allows comes from the code host, never from a file or a ref on this computer, which an agent can
edit: a merge_into pattern counts only when the working copy names it and so does the colony.toml on the default
branch of the pull request's repo, read with `gh api`, and only when that repo is origin's, as git reads origin's
address after its url rewrites. When GitHub can't be read, nothing is allowed. The guard refuses what rewrites that
picture: `git update-ref` or `symbolic-ref` on refs/remotes/, a fetch into refs/remotes/ by hand, `git remote
set-head` with a branch, `set-url`, `rename` or `remove` of origin, `git config --edit`, and config that changes a
remote's URL, fetch or push refspec or mirror, a URL rewrite, an include, push.default, remote.pushDefault, or a
branch's merge, remote or pushRemote.

Both follow a push or merge wherever a line hides it: `sh -c`, `eval`, sudo, git and gh aliases, and refuse an xargs or
a shell alias that builds one. Beside that, a line whose raw text names a kill, a `git push` or a gh merge anywhere
must be one plain command of that kind, with no other command, substitution, here-document, eval or `sh -c` around
it, no `;`, `&`, `|`, `$'`, `$"` or backslash in its raw text, and that one match at its very start, since quoting
the shell reads otherwise can hide one; text that only names one is refused too, with the advice
to write it to a file.
A `gh pr merge` that shares its line with a cd, a wrapper that moves it, or a GH_ or GIT_ variable is refused,
since the pull request checked may not be the one merged.

A hook stops an agent's honest mistakes, never a determined one: an agent that can edit .claude/settings.json, this
script or .git/config by hand can get past it. The real lock is the code host's branch protection, which `colony
safety protect` turns on.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path, PurePath
from urllib.parse import quote

MAX_SLEEP_SECONDS = 10  # a short pause, such as the seconds a server takes to start, stays allowed
LOOPS = {"while", "until", "for", "select"}
ENDLESS = {"while": {"true", ":"}, "until": {"false"}}  # a loop condition that never ends the loop
KEYWORDS = {"!", "if", "then", "else", "elif", "fi", "do", "esac", "in"}  # words that can stand before a command
# Each wrapper runs the command after it: the options that take the next word as their value, and the number of
# plain words before the command.
WRAPPERS: dict[str, tuple[frozenset[str], int]] = {
    "command": (frozenset(), 0),
    "env": (frozenset({"-u", "--unset", "-C", "--chdir"}), 0),
    "exec": (frozenset({"-a"}), 0),
    "nice": (frozenset({"-n", "--adjustment"}), 0),
    "nohup": (frozenset(), 0),
    "stdbuf": (frozenset({"-i", "-o", "-e"}), 0),
    "time": (frozenset({"-f", "-o"}), 0),
    "timeout": (frozenset({"-s", "--signal", "-k", "--kill-after"}), 1),
}
SHELLS = {"sh", "bash", "zsh", "dash"}
PYTHON = re.compile(r"^python(\d+(\.\d+)?)?$")
PYTHON_SLEEP = re.compile(r"\bsleep\(\s*([^)]*?)\s*\)")
PYTHON_LOOP = re.compile(r"\b(while|for)\b")
GH_REPO_FLAGS = {"-R", "--repo"}
# A here-document's operator, - for <<-, and its delimiter: in single quotes, in double quotes, or bare (split_heredocs
# skips <<<, a here-string, which has no body).
HEREDOC = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|\\?([A-Za-z0-9_][A-Za-z0-9_.-]*))")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
DURATION = re.compile(r"^(\d+(?:\.\d*)?|\.\d+)([smhd]?)$")
UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
# The shell's operators, longest first. shlex reads a run of punctuation as one token, such as `);` after a $(...),
# so tokens() splits a run into these.
OPERATORS = ("&&", "||", ";;", "|&", ">>", "<<", ">&", "<&", "&>", ">|", "(", ")", ";", "&", "|", "<", ">")
PUNCTUATION = set("();<>|&")
RAW_SLEEP = re.compile(r"(?<![\w.-])sleep\s+([0-9.]+[smhd]?)(?![\w.])")
RAW_GIT = re.compile(r"git")  # in a line shlex can't read, any git with a push is refused (pushes())
# The plain-line rule: a line whose raw text names a push, a gh merge or a kill (RAW_KILL) anywhere must be one plain
# command of that kind, which the guard's own reading then checks; quoting, a substitution or a here-document can
# otherwise hide one from that reading.
RAW_PUSH = re.compile(r"(?<![\w.-])git\b[^\n;&|]*?\spush(?=\s|$|[;&|)'\"])")
RAW_MERGE = re.compile(r"(?<![\w.-])gh\b[^\n;&|]*?\s(?:pr\s+merge(?=\s|$|[;&|)'\"])|api\s[^\n;&|]*?"
                       r"(?:/merges?\b|mergePullRequest|enablePullRequestAutoMerge|mergeBranch))")
NOT_PLAIN = ("\n", "$(", "`", "<<", "<(", ">(")  # raw text a plain command never holds
# Raw characters a plain command never holds either: each separates commands, or starts quoting ($'...', $"...", a
# backslash) that the guard's reader may read otherwise than the shell, and so hide a separator.
NOT_PLAIN_CHARACTERS = (";", "&", "|", "$'", '$"', "\\")
PLAIN_STEP = {"push": "run the push as its own plain command", "merge": "run the pull request step as its own plain "
              "command", "kill": "run the kill as its own plain command, by its exact process id"}
LIST_SEPARATORS = {";", "&&", "||", ";;"}
PIPES = {"|", "|&"}
BACKGROUND = "&"
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
                     "--attr-source", "--shallow-file"}  # git's, before `push`
# Commands that can change the branch checked out, git config or the folder for a later push on the same line, which
# the guard reads before the line runs.
LINE_CHANGES_GIT = {"checkout", "switch", "config", "branch", "remote", "symbolic-ref"}
LINE_CHANGES = {"cd", "pushd", "popd"}
GIT_VARIABLE = re.compile(r"^(GIT_\w*|HOME|XDG_CONFIG_HOME)(=|$)")  # where git finds its repo and its config
BASE = re.compile(r'^\s*base\s*=\s*"([^"]+)"', re.M)
# The push guard's allow-list: the only words a push may hold besides its remote and branch. Each changes nothing about
# what is pushed or where: -u records the upstream, --force-with-lease rewrites only a branch of the agent's own, a
# dry run pushes nothing, and the rest change what git prints.
PUSH_FLAGS = {"-u", "--set-upstream", "--force-with-lease", "--dry-run", "-n", "-q", "--quiet", "-v", "--verbose"}
REMOTE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$")  # a remote's plain name: no slash, no URL, no path
# A plain branch name, as git check-ref-format allows one, without globs, refs/, HEAD or a leading dash.
BRANCH = re.compile(r"^(?!-)(?!refs/)(?!HEAD$)(?!.*(?:\.\.|//|@\{|\.lock(?:/|$)|/\.))"
                    r"[A-Za-z0-9_.][A-Za-z0-9_./-]*(?<![./])$")
# The way out for text that only names a push, a merge or a kill, such as a commit message: a file. It is no way out
# for a command: the guard reads a script a line runs (scripts), and a GraphQL query read from a file (api_merge).
TEXT_ADVICE = (" If these words are only text, such as a commit message or a pull request body that names them, write "
               "the text to a file with your file tool and pass the file, as `git commit -F <file>` and `gh pr create "
               "--body-file <file>` do. A push, a merge or a kill moved into a file or a script is still refused: run "
               "it as its own plain command.")
FILE_LIMIT = 1_000_000  # bytes of a script or a query file the guard reads; a longer one it can't check
PUSH_REFUSAL = ("push guard: refused, {reason}. A push takes one form alone: `git push [-u] [--force-with-lease] "
                "[--dry-run] <remote> HEAD:refs/heads/<branch>`, or `<local branch>:refs/heads/<branch>` in place of "
                "HEAD, where the remote is one this clone names, with no push refspec or mirror in its git config, "
                "whose push and fetch addresses are one repo, and the branch is your own, never {branches}. Land "
                "work on those through a pull request (in Hack, `colony merge <branch>`), or ask your person."
                + TEXT_ADVICE)
REFUSAL = ("wait guard: refused, {reason}. A foreground wait blocks the session. Start the command with "
           "run_in_background and carry on, or start `colony wait` with run_in_background and act on its lines.")

# The kill guard
PATTERN_KILLERS = {"pkill", "killall", "killall5", "skill"}  # each signals every process a name or pattern matches
# The programs that look running processes up by name or pattern, whose output a kill must never take as its ids.
SEARCHES = re.compile(r"(?<![\w.-])(?:pgrep|pidof|pkill|ps|lsof|fuser|tasklist|wmic|get-process|gps)(?![\w-])", re.I)
ELEVATORS = {"sudo": frozenset({"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "--user", "--group", "--host",
                                "--prompt", "--chdir", "--close-from", "--role", "--type", "--other-user"}),
             "doas": frozenset({"-u", "-C"})}
POWERSHELLS = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
KILLERS = {*PATTERN_KILLERS, "kill", "taskkill", "fuser", "powershell", "pwsh"}  # what a kill's plain line may run
POWERSHELL_KILL = re.compile(r"\b(?:stop-process|spps)\b[^;|]*\s-(?:name|processname)\b"
                             r"|\|\s*(?:stop-process|spps|kill)\b"
                             r"|\.kill\(\)", re.I)
REDIRECTIONS = {">", ">>", "<", "<<", ">&", "<&", "&>", ">|"}
RAW_KILL = re.compile(r"(?<![\w.-])(?:pkill|killall|killall5|skill|taskkill|fuser|stop-process|spps)(?![\w-])"
                      r"|(?<![\w.-])kill\b[^;&|\n]*(?:\$\(|`)|\bxargs\b[^;&|\n]*\bkill\b", re.I)
KILL_REFUSAL = ("kill guard: refused, {reason}. A kill by name or pattern can end every Claude Code session, the "
                "terminal app and the background tasks on this computer. Close a Colony session by its name with "
                "`colony stop <name>`. For any other process, find the one you mean, check it with "
                "`ps -p <pid> -o pid=,command=`, and kill that number alone: `kill <pid>`."
                + TEXT_ADVICE)

# The merge guard
SAFETY = "safety"  # the colony.toml table that holds merge_into and protect
GH_TIMEOUT = 20  # seconds the guard gives `gh pr view` to say which branch a pull request merges into
HOLDS_REF = "refs/colony/holds"  # origin's merge freeze and red holds, which `colony freeze` and `colony health` keep
PR_MERGE_VALUE_OPTIONS = {"-t", "--subject", "-b", "--body", "-F", "--body-file", "--match-head-commit", "-A",
                          "--author-email"}
GH_API_VALUE_OPTIONS = {"-X", "--method", "-H", "--header", "-f", "--raw-field", "-F", "--field", "--input", "-q",
                        "--jq", "-t", "--template", "--hostname", "-p", "--preview", "--cache"}
GH_API_FIELDS = {"-f", "--raw-field", "-F", "--field", "--input"}
GRAPHQL_MERGE = re.compile(r"\b(?:mergePullRequest|enablePullRequestAutoMerge|mergeBranch)\b")
MCP_PR_MERGES = {"merge_pull_request", "merge_merge_request", "merge_pr"}  # a GitHub tool's name after its server's
MCP_COMMITS = {"push_files", "create_or_update_file", "delete_file"}  # tools that commit straight onto a branch
TOML_ITEM = re.compile(r"\s+|#[^\n]*|,|\"((?:[^\"\\\n]|\\.)*)\"|'([^'\n]*)'|\]")
TABLE_HEADER = re.compile(r"^[ \t]*\[\[?[ \t]*[A-Za-z0-9_.\"' -]+\]\]?[ \t]*(?:#.*)?$", re.M)
# origin's URL as git config holds it: its host and owner/name, from https://, ssh:// or git@host: forms.
ORIGIN = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^@/\s]+@)?([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)(?::\d+)?[:/]"
                    r"([^/\s]+/[^/\s]+?)(?:\.git)?/?$")
PR_URL = re.compile(r"^(https?://[^/\s]+/[^/\s]+/[^/\s]+)/pull/\d+")
# The settings that say where origin is, what a fetch writes into refs/remotes/, and where a push goes, which the
# guard reads, with the includes that can set them.
REMOTE_KEYS = re.compile(r"^(?:remote\.[^\s]+\.(?:url|pushurl|fetch|push|mirror)|url\.[^\s]+\.(?:insteadof"
                         r"|pushinsteadof)|push\.default|remote\.pushdefault"
                         r"|branch\.[^\s]+\.(?:merge|remote|pushremote)|include\.path|includeif\.[^\s]+\.path)$", re.I)
CONFIG_WRITES = {"--add", "--replace-all", "--unset", "--unset-all", "--rename-section", "--remove-section", "-e",
                 "--edit"}
CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "-l", "--list", "--get-color",
                "--get-colorbool"}
# git's own commands, which no alias can shadow; any other word after `git` may be an alias, which the guard expands.
GIT_COMMANDS = frozenset((
    "add", "am", "apply", "archive", "bisect", "blame", "branch", "bundle", "cat-file", "check-ignore", "checkout",
    "cherry", "cherry-pick", "clean", "clone", "commit", "config", "count-objects", "describe", "diff", "difftool",
    "fetch", "for-each-ref", "format-patch", "fsck", "gc", "grep", "hash-object", "help", "init", "log", "ls-files",
    "ls-remote", "ls-tree", "maintenance", "merge", "merge-base", "mergetool", "mv", "name-rev", "notes", "prune",
    "pull", "push", "range-diff", "rebase", "reflog", "remote", "replace", "reset", "restore", "rev-list",
    "rev-parse", "revert", "rm", "shortlog", "show", "show-branch", "show-ref", "sparse-checkout", "stash", "status",
    "submodule", "switch", "symbolic-ref", "tag", "update-index", "update-ref", "var", "version", "whatchanged",
    "worktree"))
GH_COMMANDS = frozenset((
    "agent-task", "alias", "api", "attestation", "auth", "browse", "cache", "codespace", "completion", "config",
    "copilot", "extension", "gist", "gpg-key", "help", "issue", "label", "org", "pr", "preview", "project", "release",
    "repo", "ruleset", "run", "search", "secret", "ssh-key", "status", "variable", "version", "workflow"))
GH_VARIABLE = re.compile(r"^(GH_\w*|GITHUB_\w*|HOME|XDG_CONFIG_HOME)(=|$)")  # where gh finds its repo, host and config
DEPTH = 4  # nested shells, evals and aliases the guard follows before it refuses
FOLDER_OPTIONS = ("-C", "-D", "--chdir", "--git-dir", "--work-tree")  # a wrapper's options that move a command
MERGE_REFUSAL = ("merge guard: refused, {reason}. No agent merges or pushes into a branch without the person's yes: "
                 "push your own branch and open a pull request for the person to merge (in Hack, `colony merge "
                 "<branch>`). The person allows merges into a branch with `merge_into` under [safety] in "
                 ".colony/colony.toml, on the repo's default branch on GitHub."
                 + TEXT_ADVICE)


def sleep_seconds(arguments: list[str]) -> float | None:
    """How long a sleep with these arguments waits, or None when its length can't be read."""
    if not arguments:
        return None
    total = 0.0
    for word in arguments:
        match = DURATION.match(word)
        if match is None:
            return None
        total += float(match[1]) * UNIT_SECONDS[match[2]]
    return total


def split_heredocs(command: str) -> tuple[str, bool]:
    """The command line without the bodies of its here-documents, and whether every body ended at its terminator.

    A `<<` opens a here-document only where the shell reads commands: outside single and double quotes and comments,
    or inside a $(...) or `...`, even one within double quotes, as in git commit -m "$(cat <<'EOF' ... EOF)". So text
    that only looks like one, such as "<<EOF" in quotes, never hides the lines after it. A body starts on the line
    after its opener's and ends at a line that is its delimiter exactly, after leading tabs alone for <<-. A body
    that never ends counts as not ended, and its lines stay in the text."""
    out: list[str] = []
    pending: list[tuple[str, bool]] = []  # each opened here-document's delimiter, and whether it is <<-
    stack: list[str] = []  # the quotes and substitutions the scan is inside
    at, size, word_start = 0, len(command), True
    while at < size:
        char, top = command[at], stack[-1] if stack else ""
        if top == "'":
            stack.pop() if char == "'" else None
            out.append(char)
            at += 1
            continue
        if top == "((":  # arithmetic, where << shifts bits
            if command.startswith("))", at):
                stack.pop()
                out.append("))")
                at += 2
            else:
                out.append(char)
                at += 1
            continue
        if char == "\\":
            out.append(command[at:at + 2])
            at += 2
            word_start = False
            continue
        if top == '"':
            if command.startswith("$((", at):
                stack.append("((")
                out.append("$((")
                at += 3
                continue
            if command.startswith("$(", at):
                stack.append("$(")
                out.append("$(")
                at += 2
                continue
            if char == '"':
                stack.pop()
            elif char == "`":
                stack.append("`")
            out.append(char)
            at += 1
            continue
        if char == "\n" and pending:  # the bodies start on the next line, one after another
            out.append(char)
            at += 1
            while pending:
                delimiter, tabs = pending.pop(0)
                while True:
                    if at >= size:
                        return command, False  # no terminator: nothing counts as a body
                    end = command.find("\n", at)
                    end = size if end == -1 else end
                    line, at = command[at:end], end + 1
                    if (line.lstrip("\t") if tabs else line) == delimiter:
                        break
            word_start = True
            continue
        if char == "#" and word_start:  # a comment, to the end of its line
            end = command.find("\n", at)
            end = size if end == -1 else end
            out.append(command[at:end])
            at = end
            continue
        if command.startswith("<<<", at):  # a here-string, which has no body
            out.append("<<<")
            at += 3
            word_start = False
            continue
        arithmetic = 3 if command.startswith("$((", at) else 2 if command.startswith("((", at) and word_start else 0
        if arithmetic:
            stack.append("((")
            out.append(command[at:at + arithmetic])
            at += arithmetic
            continue
        opener = HEREDOC.match(command, at) if command.startswith("<<", at) else None
        if opener:
            delimiter = next(part for part in (opener[2], opener[3], opener[4]) if part is not None)
            pending.append((delimiter, opener[1] == "-"))
            out.append(opener[0])
            at = opener.end()
            word_start = False
            continue
        if char in "'\"":
            stack.append(char)
        elif char == "`":
            stack.pop() if top == "`" else stack.append("`")
        elif command.startswith("$(", at):
            stack.append("$(")
            out.append("$(")
            at += 2
            word_start = True
            continue
        elif char == "(":
            stack.append("(")
        elif char == ")" and top in ("$(", "("):
            stack.pop()
        out.append(char)
        at += 1
        word_start = char in " \t\n;&|()"
    return "".join(out), not pending


def without_heredoc_bodies(command: str) -> str:
    """The command line without the bodies of its here-documents (split_heredocs)."""
    return split_heredocs(command)[0]


def raw_text(command: str) -> str:
    """The text a guard scans in a line whose quoting can't be read: the line without its here-documents' bodies
    when each one ended at its terminator, else the whole line, so a body that may be no body hides nothing."""
    text, ended = split_heredocs(command)
    return text if ended else command


def python_waits(code: str) -> list[str]:
    """Why a `python -c` program waits: a sleep in a loop, or a long sleep."""
    sleeps = PYTHON_SLEEP.findall(code)
    if not sleeps:
        return []
    if PYTHON_LOOP.search(code):
        return ["a Python loop that sleeps polls in the foreground"]
    found = []
    for argument in sleeps:
        seconds = sleep_seconds([argument])
        if seconds is not None and seconds > MAX_SLEEP_SECONDS:
            found.append(f"a Python sleep({argument}) waits {seconds:g} seconds in the foreground")
    return found


def without_repo_flag(arguments: list[str]) -> list[str]:
    """gh's arguments without --repo and its value, so the command's words can be matched."""
    kept: list[str] = []
    skip = False
    for word in arguments:
        if skip:
            skip = False
        elif word in GH_REPO_FLAGS:
            skip = True
        elif not word.startswith("--repo="):
            kept.append(word)
    return kept


def program_words(words: list[str]) -> list[str]:
    """One simple command's words from the program it runs, past assignments, keywords and wrappers."""
    index = 0
    while index < len(words):
        word = words[index]
        if ASSIGNMENT.match(word) or word in KEYWORDS:
            index += 1
            continue
        name = PurePath(word).name
        if name not in WRAPPERS:
            break
        value_options, plain_words = WRAPPERS[name]
        index += 1
        while index < len(words) and words[index].startswith("-"):
            index += 2 if words[index] in value_options else 1
        index += plain_words
    return words[index:]


def command_waits(words: list[str], in_loop: bool) -> list[str]:
    """Why one simple command waits in the foreground. waits() reads a `wait`, since it knows the line's jobs."""
    program = program_words(words)
    if not program:
        return []
    name, arguments = PurePath(program[0]).name, program[1:]
    if name == "sleep":
        if in_loop:
            return ["a loop that sleeps polls in the foreground"]
        seconds = sleep_seconds(arguments)
        if seconds is not None and seconds > MAX_SLEEP_SECONDS:
            return [f"`{' '.join(program)}` waits {seconds:g} seconds in the foreground"]
    elif PYTHON.match(name):
        return [reason for i, word in enumerate(arguments[:-1]) if word == "-c"
                for reason in python_waits(arguments[i + 1])]
    elif name == "watch":
        return ["watch reruns a command in the foreground"]
    elif name == "gh":
        arguments = without_repo_flag(arguments)
        if arguments[:2] == ["pr", "checks"] and any(w == "--watch" or w.startswith("--watch=") for w in arguments):
            return ["`gh pr checks --watch` waits on the checks in the foreground"]
        if arguments[:2] == ["run", "watch"]:
            return ["`gh run watch` waits on the run in the foreground"]
    elif name in SHELLS:
        return [reason for i, word in enumerate(arguments[:-1]) if word.startswith("-") and "c" in word.lstrip("-")
                for reason in waits(arguments[i + 1], in_loop)]
    elif name == "eval":
        return waits(" ".join(arguments), in_loop)
    return []


class Frame:
    """An open loop or group, with the waits found in it so far."""

    def __init__(self, kind: str, keyword: str = "") -> None:
        self.kind = kind
        self.keyword = keyword  # a loop's while, until, for or select
        self.in_condition = kind == "loop"  # a loop reads its condition until `do`
        self.found: list[str] = []
        self.pipeline: list[str] = []  # the waits of the pipeline being read, dropped if it ends with &
        self.words: list[str] = []


def operators(run: str) -> list[str]:
    """A run of punctuation, such as `);` or `)|`, as the shell's operators in it."""
    found = []
    while run:
        operator = next((op for op in OPERATORS if run.startswith(op)), run[0])
        found.append(operator)
        run = run[len(operator):]
    return found


def tokens(command: str, bodies: bool = True) -> list[str]:
    """The command line's words and operators, here-document bodies read as commands too, so no shell parsing the
    guard gets wrong can hide a line: the kill, push and merge guards read lines so. With `bodies` false, as the wait
    guard reads them, a here-document's body is left out (split_heredocs), which can hide nothing those guards
    guard. Raises ValueError when the quoting can't be read, or, without bodies, a here-document has no terminator
    line. Each newline stays before the `;` that stands for it, so a comment ends with its line, as the shell ends it,
    and never hides the lines after it."""
    text, ended = (command, True) if bodies else split_heredocs(command)
    if not ended:
        raise ValueError("a here-document has no terminator line")
    lexer = shlex.shlex(text.replace("\n", "\n;"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    found: list[str] = []
    for token in lexer:
        found += operators(token) if token and set(token) <= PUNCTUATION else [token]
    return found


def raw_sleeps(command: str) -> list[str]:
    """The long sleeps in a line whose quoting can't be read, found in its plain text."""
    found = []
    for argument in RAW_SLEEP.findall(raw_text(command)):
        seconds = sleep_seconds([argument])
        if seconds is not None and seconds > MAX_SLEEP_SECONDS:
            found.append(f"`sleep {argument}` waits {seconds:g} seconds in the foreground")
    return found


def waits(command: str, in_loop: bool = False) -> list[str]:
    """A reason for each foreground wait a command line holds, or none when it never waits in the foreground. A line
    whose quoting shlex can't read, such as a $(...) holding quotes inside a double-quoted word, which the shell
    reads fine, runs, unless its plain text holds a long sleep."""
    try:
        words = tokens(command, bodies=False)
    except ValueError:
        return raw_sleeps(command)
    stack = [Frame("top")]
    jobs: list[str] = []  # the waits of the jobs the line started in the background that no wait has blocked on yet

    def looping() -> bool:
        return in_loop or any(frame.kind == "loop" for frame in stack)

    def end_command() -> None:
        frame = stack[-1]
        if not frame.words:
            return
        program = program_words(frame.words)
        if frame.in_condition:
            if frame.words[0] == "do":
                frame.in_condition = False
            elif program and (name := PurePath(program[0]).name) in ENDLESS.get(frame.keyword, ()):
                frame.pipeline.append(f"an endless `{frame.keyword} {name}` loop polls in the foreground")
        if program and PurePath(program[0]).name == "wait":
            frame.pipeline += jobs  # a wait blocks on the line's jobs, so their waits become its own
            jobs.clear()
        else:
            frame.pipeline += command_waits(frame.words, looping())
        frame.words = []

    def end_pipeline(background: bool) -> None:
        end_command()
        frame = stack[-1]
        (jobs if background else frame.found).extend(frame.pipeline)
        frame.pipeline = []

    def close(kinds: set[str]) -> None:
        if len(stack) == 1 or stack[-1].kind not in kinds:
            return
        end_pipeline(background=False)
        closed = stack.pop()
        stack[-1].pipeline += closed.found  # the closed loop or group joins the parent's pipeline, so & covers it

    skip_next = False
    for token in words:
        frame = stack[-1]
        if skip_next:
            skip_next = False
        elif token in LIST_SEPARATORS:
            end_pipeline(background=False)
        elif token == BACKGROUND:
            end_pipeline(background=True)
        elif token in PIPES:
            end_command()
        elif set(token) <= set("<>&"):
            # A redirection names its file or descriptor in the next word, and a descriptor number before it, as
            # in 2>&1, reads as a word of its own.
            skip_next = True
            if frame.words and frame.words[-1].isdigit():
                frame.words.pop()
        elif not frame.words and token in LOOPS:
            stack.append(Frame("loop", token))
        elif not frame.words and token == "done":
            close({"loop"})
        elif token == "(" or (token == "{" and not frame.words):
            stack.append(Frame("group"))  # a subshell, a command substitution after its $, or a brace group
        elif token == ")" or (token == "}" and not frame.words):
            close({"group"})
        else:
            frame.words.append(token)
    while len(stack) > 1:
        close({stack[-1].kind})
    end_pipeline(background=False)
    return stack[0].found


def colony_toml(cwd: str) -> str:
    """The text of the repo's .colony/colony.toml: the one in $CLAUDE_PROJECT_DIR, else in cwd, else beside this
    script's copy, or "" when there is none."""
    places = [os.environ.get("CLAUDE_PROJECT_DIR", ""), cwd, str(Path(__file__).resolve().parents[2])]
    for place in places:
        path = Path(place) / ".colony" / "colony.toml" if place else None
        if path is None or not path.is_file():
            continue
        try:
            return path.read_text()
        except OSError:
            continue
    return ""


def project_base(text: str) -> str:
    """[project] base in a colony.toml's text, or ""."""
    project = re.split(r"^\s*\[(?!project\])", text.split("[project]", 1)[-1], maxsplit=1, flags=re.M)[0]
    found = BASE.search(project)
    return found[1] if found else ""


def base_branch(cwd: str) -> str:
    """[project] base from the repo's .colony/colony.toml, else main."""
    return project_base(colony_toml(cwd)) or "main"


def current_branch(cwd: str) -> str:
    """The branch checked out in cwd, or "" when git can't say."""
    try:
        run = subprocess.run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=cwd or None,
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return run.stdout.strip() if run.returncode == 0 else ""


def default_branch(cwd: str) -> str:
    """The repo's default branch, origin's HEAD as git remembers it, else main."""
    try:
        run = subprocess.run(["git", "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], cwd=cwd or None,
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return "main"
    found = run.stdout.strip().removeprefix("refs/remotes/origin/") if run.returncode == 0 else ""
    return found or "main"


def table(text: str, name: str) -> str:
    """The body of a TOML text's [name] table, up to the next table header, or "" when it has none."""
    for header in TABLE_HEADER.finditer(text):
        label = header[0].split("#", 1)[0].strip()
        if not label.startswith("[[") and label.strip("[] \t") == name:
            rest = text[header.end():]
            following = TABLE_HEADER.search(rest)
            return rest[:following.start()] if following else rest
    return ""


def strings(body: str, key: str) -> list[str] | None:
    """A TOML table body's array of strings under `key`: [] when the key is missing, None when it can't be read."""
    start = re.search(rf"^[ \t]*{re.escape(key)}[ \t]*=[ \t]*\[", body, re.M)
    if not start:
        return []
    found: list[str] = []
    at = start.end()
    while True:
        item = TOML_ITEM.match(body, at)
        if item is None:
            return None
        if item[0] == "]":
            return found
        if item[1] is not None:
            found.append(re.sub(r"\\(.)", r"\1", item[1]))
        elif item[2] is not None:
            found.append(item[2])
        at = item.end()


def committed_toml(cwd: str, branches: list[str]) -> str | None:
    """The colony.toml on origin's copy of a branch on this computer, for the first of `branches` that has one, read
    with git's replace refs ignored, or None. It only widens what the guard protects: a ref under refs/remotes/ lives
    on this computer, so it never decides what the person allows, which Allowance reads from the code host."""
    for branch in dict.fromkeys(branches):
        try:
            run = subprocess.run(["git", "--no-replace-objects", "show",
                                  f"refs/remotes/origin/{branch}:.colony/colony.toml"],
                                 cwd=cwd or None, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return None
        if run.returncode == 0:
            return run.stdout
    return None


def project_value(text: str, key: str) -> str:
    """A string key of a colony.toml's [project] table, such as integration, or ""."""
    found = re.search(rf'^[ \t]*{re.escape(key)}[ \t]*=[ \t]*"([^"\n]+)"', table(text, "project"), re.M)
    return found[1].strip() if found else ""


def long_lived(text: str) -> list[str]:
    """The project's other long-lived branches a colony.toml names, as branches.py reads them: [project] integration,
    [project] release and [release] long_lived."""
    named = [project_value(text, "integration"), project_value(text, "release")]
    return [*filter(None, named), *(strings(table(text, "release"), "long_lived") or [])]


def protected_branches(cwd: str) -> list[str]:
    """The branches no push may rewrite, and none may update without the person's yes: the base in the working copy
    and in origin's copy, the repo's default branch, and both copies' [safety] protect and long-lived branches
    ([project] integration and release, [release] long_lived)."""
    text = colony_toml(cwd)
    base, default = project_base(text) or "main", default_branch(cwd)
    extra = [*(strings(table(text, SAFETY), "protect") or []), *long_lived(text)]
    committed = committed_toml(cwd, [default, base])
    if committed is not None:
        extra += [*(strings(table(committed, SAFETY), "protect") or []), *filter(None, [project_base(committed)]),
                  *long_lived(committed)]
    return list(dict.fromkeys([base, default, *extra]))


def remote_url(cwd: str, remote: str, push: bool = True) -> str:
    """Where git really goes for `remote`, a remote's name or a URL: with its pushurl (for a push) and git's url
    rewrites applied, as `git remote get-url` and `git ls-remote --get-url` say, or "" when git can't say."""
    if not remote:
        return ""
    named = not any(mark in remote for mark in ":/\\") and not remote.startswith((".", "~"))
    argv = (["git", "remote", "get-url", *(["--push"] if push else []), remote] if named
            else ["git", "ls-remote", "--get-url", remote])
    try:
        run = subprocess.run(argv, cwd=cwd or None, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return run.stdout.strip().splitlines()[0] if run.returncode == 0 and run.stdout.strip() else ""


def repo_of(url: str) -> tuple[str, str]:
    """A repo URL's host and owner/name, such as ("github.com", "acme/demo"), or ("", "") for no repo on a code
    host, such as a folder."""
    found = ORIGIN.match(url.strip())
    return (found[1].lower(), found[2]) if found else ("", "")


def origin_repo(cwd: str) -> tuple[str, str]:
    """origin's host and owner/name, from where `git remote get-url origin` says it is, or ("", "") when origin is no
    repo on a code host, or there is none."""
    return repo_of(remote_url(cwd, "origin", push=False))


def same_repo(one: tuple[str, str], other: tuple[str, str]) -> bool:
    """Whether two (host, owner/name) pairs name one repo on a code host."""
    return bool(one[1]) and one[0] == other[0] and one[1].lower() == other[1].lower()


def host_toml(host: str, repo: str, ref: str = "") -> str | None:
    """The colony.toml on a branch of the repo on its code host, read with `gh api`, `ref` "" for the default branch,
    or None when gh can't read it."""
    path = f"repos/{repo}/contents/.colony/colony.toml" + (f"?ref={quote(ref, safe='')}" if ref else "")
    argv = ["gh", "api", *(["--hostname", host] if host and host != "github.com" else []),
            "-H", "Accept: application/vnd.github.raw", path]
    try:
        run = subprocess.run(argv, capture_output=True, text=True, timeout=GH_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout if run.returncode == 0 else None


class Allowance:
    """The branches the person allows merges and pushes into, at one destination: a remote's name or a repo's URL.
    A [safety] merge_into pattern counts only when the working copy names it and so does the colony.toml on the
    destination repo's default branch on its code host, which no agent may push to. It counts only when the
    destination really is origin's repo, after git's pushurl and url rewrites, so a push to any other URL or remote
    gets no yes. A ref or a file on this computer counts for nothing here, since an agent can rewrite one. The host
    is read once, and only when a branch the working copy names is asked about, so a push of an agent's own branch
    makes no network call. When the host can't be read, nothing is allowed."""

    def __init__(self, cwd: str, destination: str = "origin") -> None:
        self.cwd, self.destination = cwd, destination
        self.named = strings(table(colony_toml(cwd), SAFETY), "merge_into") or []
        self.trusted: list[str] | None = None

    def host_named(self) -> list[str]:
        """The merge_into patterns the copy on the destination's default branch names."""
        if self.trusted is None:
            self.trusted = []
            host, repo = repo_of(remote_url(self.cwd, self.destination))
            if same_repo((host, repo), origin_repo(self.cwd)):
                default = host_toml(host, repo)
                self.trusted = (strings(table(default, SAFETY), "merge_into") or []) if default is not None else []
        return self.trusted

    def permits(self, branch: str) -> bool:
        """Whether the person allows merges and pushes into this branch."""
        patterns = [pattern for pattern in self.named if fnmatch.fnmatchcase(branch, pattern)]
        return bool(patterns) and any(pattern in self.host_named() for pattern in patterns)


def permitted(branch: str, allowed: list[str]) -> bool:
    """Whether a list of merge_into patterns names this branch, as a name or a pattern such as release/*."""
    return any(fnmatch.fnmatchcase(branch, pattern) for pattern in allowed)


def branch_name(target: str) -> str:
    """A refspec's destination as a branch name: refs/heads/main and heads/main are main."""
    for prefix in ("refs/heads/", "heads/"):
        if target.startswith(prefix):
            return target[len(prefix):]
    return target


def reached(target: str, protected: list[str]) -> str:
    """The protected branch a refspec's destination names, or matches when it is a pattern such as refs/heads/*, or
    "". Git reads a destination such as heads/main as refs/heads/main, and its * matches across slashes, as fnmatch's
    does. A protected pattern, such as release/*, reaches each branch it matches."""
    for branch in protected:
        if any(mark in branch for mark in "*?["):
            if fnmatch.fnmatchcase(branch_name(target), branch):
                return branch_name(target)
        elif any(fnmatch.fnmatchcase(name, target) for name in (branch, f"heads/{branch}", f"refs/heads/{branch}")):
            return branch
    return ""


def config_key(key: str) -> str:
    """A config key the way git config prints it: the section and the name in lower case, a subsection as written."""
    section, _, rest = key.partition(".")
    subsection, dot, name = rest.rpartition(".")
    return f"{section.lower()}.{subsection}{dot}{name.lower()}"


def reaches(target: str, protected: list[str]) -> list[str]:
    """Every protected branch a refspec's destination names or matches, as reached finds each one."""
    return list(dict.fromkeys(found for branch in protected if (found := reached(target, [branch]))))


def git_alias(name: str, cwd: str, overrides: list[tuple[str, str | None]]) -> str | None:
    """What a git alias stands for: the line's own `-c alias.<name>=` value first, else git config's, "" for one a
    --config-env value sets, which the guard can't see, or None when `name` is no alias."""
    for key, value in reversed(overrides):
        if config_key(key) == f"alias.{name.lower()}":
            return "" if value is None else value
    try:
        run = subprocess.run(["git", "config", "--get", f"alias.{name}"], cwd=cwd or None, capture_output=True,
                             text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout.strip() if run.returncode == 0 else None


def config_target(arguments: list[str]) -> str:
    """The key a `git config` with these arguments writes, or "" when it only reads."""
    words, skip = [], False
    for word in arguments:
        if skip:
            skip = False
        elif word in ("-f", "--file", "--blob", "--type", "--default", "--comment"):
            skip = True
        elif not word.startswith("-"):
            words.append(word)
    if any(word in CONFIG_READS for word in arguments) or words[:1] in (["get"], ["list"]):
        return ""
    if words[:1] in (["set"], ["unset"]):
        return words[1] if len(words) > 1 else ""
    writes = any(word in CONFIG_WRITES for word in arguments) or len(words) > 1
    return words[0] if words and writes else ""


def forges(command: str, arguments: list[str], overrides: list[tuple[str, str | None]]) -> str:
    """Why a git command rewrites what the guard reads as origin's: a ref under refs/remotes/, origin's address, or
    what a fetch writes into refs/remotes/; "" for any other git command."""
    words = [word for word in arguments if not word.startswith("-")]
    if command in ("fetch", "pull", "remote") and any(REMOTE_KEYS.match(config_key(key)) for key, _ in overrides):
        return f"`git -c` changes where origin is, or what `git {command}` writes into refs/remotes/"
    if command in ("update-ref", "symbolic-ref") and any(word.startswith("refs/remotes/") for word in arguments):
        return f"`git {command}` rewrites a ref under refs/remotes/, which the guard reads as origin's"
    if command in ("fetch", "pull") and any("refs/remotes/" in word.partition(":")[2] for word in words if ":" in word):
        return f"`git {command}` writes into refs/remotes/ by hand, which the guard reads as origin's"
    if command == "remote" and words[:1] == ["set-head"] and len(words) >= 3:
        return "`git remote set-head` with a branch points origin's HEAD by hand, which the guard reads"
    if command == "remote" and words[:1] in (["set-url"], ["rename"], ["remove"], ["rm"]) and words[1:2] == ["origin"]:
        return f"`git remote {words[0]} origin` changes origin, which the guard reads to know this repo"
    if command == "config" and (any(word in ("-e", "--edit") for word in arguments) or words[:1] == ["edit"]):
        return "`git config --edit` can change where origin is, which the guard reads, so ask the person"
    if command == "config" and (key := config_target(arguments)) and REMOTE_KEYS.match(config_key(key)):
        return f"`git config {key}` changes where origin is, or what a fetch writes into refs/remotes/"
    return ""


def sequence(line: list[str]) -> list[tuple[list[str], str, str]]:
    """A line's simple commands in order, each as (its words, the operator before it, the operator after it), "" at
    the line's ends. A redirection's file and a descriptor number before it are left out, and so are a group's
    braces."""
    found: list[tuple[list[str], str, str]] = []
    words: list[str] = []
    before, skip = "", False
    for token in line:
        if skip:
            skip = False
        elif token in REDIRECTIONS:
            skip = True
            if words and words[-1].isdigit():
                words.pop()
        elif token and set(token) <= PUNCTUATION:
            if words:
                found.append((words, before, token))
                words = []
            before = token
        elif token not in ("{", "}"):
            words.append(token)
    return [*found, (words, before, "")] if words else found


def simple_commands(line: list[str]) -> list[list[str]]:
    """A line's simple commands, each as its words (sequence)."""
    return [words for words, _, _ in sequence(line)]


def run_program(words: list[str]) -> list[str]:
    """A simple command's program and its arguments, past program_words' assignments and wrappers, and past sudo or
    doas with their options."""
    program = program_words(words)
    while program and PurePath(program[0]).name in ELEVATORS:
        options, index = ELEVATORS[PurePath(program[0]).name], 1
        while index < len(program) and program[index].startswith("-"):
            index += 2 if program[index] in options else 1
        program = program_words(program[index:])
    return program


def shell_lines(name: str, arguments: list[str]) -> list[str]:
    """The command lines a shell's -c, or an eval, runs."""
    if name == "eval":
        return [" ".join(arguments)]
    return [arguments[i + 1] for i, word in enumerate(arguments[:-1])
            if word.startswith("-") and "c" in word.lstrip("-")]


def fed(arguments: list[str], program: str, known: frozenset[str], words: set[str]) -> str:
    """The subcommand of `program` an xargs line runs with words the guard can't see, when it is one of `words` or
    may be an alias, else ""."""
    names = [PurePath(word).name for word in arguments]
    if program not in names:
        return ""
    rest = [word for word in arguments[names.index(program) + 1:] if not word.startswith("-")]
    return next((word for word in rest if word in words), "") or (rest[0] if rest and rest[0] not in known else "")


def remotes(cwd: str) -> list[str]:
    """The remotes this clone names, as `git remote` lists them."""
    try:
        run = subprocess.run(["git", "remote"], cwd=cwd or None, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    return run.stdout.split() if run.returncode == 0 else []


def git_config(cwd: str, key: str) -> list[str]:
    """Every value git config holds for a key here, or ["?"] when git can't say, which counts as one."""
    try:
        run = subprocess.run(["git", "config", "--get-all", key], cwd=cwd or None, capture_output=True, text=True,
                             timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ["?"]
    return run.stdout.split("\n")[:-1] if run.returncode == 0 else [] if run.returncode == 1 else ["?"]


def one_repo(one: str, other: str) -> bool:
    """Whether two addresses git gives name one repo: the same owner/name on the same host, or the same address."""
    first, second = repo_of(one), repo_of(other)
    return same_repo(first, second) if first[1] or second[1] else bool(one) and one == other


def push_refusal(arguments: list[str], cwd: str, protected: list[str], changed: str = "") -> str:
    """Why a `git push` with these arguments, the words after `push`, takes no allowed form, or "". The allowed form
    is `[flags] <remote> <source>:refs/heads/<branch>`, with PUSH_FLAGS alone: a full destination, so git applies no
    refmap and no push.default. The source is HEAD or a plain branch name. The remote is one this clone names, with no
    remote.<name>.push or remote.<name>.mirror in its config, whose push address, after its pushurl and git's
    pushInsteadOf, is the repo it fetches from. The branch is a plain name that isn't protected. For HEAD, the branch
    checked out mustn't be protected either, and nothing before the push on its line (`changed`) may change it."""
    words = []
    for word in arguments:
        if word.startswith("-") and word != "-":
            if word not in PUSH_FLAGS:
                return f"`{word}` is not part of an allowed push"
        else:
            words.append(word)
    if len(words) != 2:
        return "this push names no remote and branch" if not words else \
            "a push names exactly one remote and one branch"
    remote, spec = words
    if not REMOTE_NAME.fullmatch(remote) or remote not in remotes(cwd):
        return f"`{remote}` is no remote this clone names"
    source, colon, destination = spec.partition(":")
    if not colon or not destination.startswith("refs/heads/"):
        return f"`{spec}` names no full destination, such as HEAD:refs/heads/<branch>"
    branch, head = destination[len("refs/heads/"):], source == "HEAD"
    if not source:
        return f"`{spec}` deletes {branch}"
    if not head and not BRANCH.fullmatch(source):
        return f"`{source}` is not HEAD or a plain branch name"
    if not BRANCH.fullmatch(branch):
        return f"`{destination}` is not a plain branch"
    if hit := reached(branch, protected):
        return f"{hit} is protected"
    for key in (f"remote.{remote}.push", f"remote.{remote}.mirror"):
        if git_config(cwd, key):
            return f"`{remote}` has {key} in git config, which can send a push elsewhere"
    if head:
        if changed:
            return f"{changed} on this line can change the branch HEAD names"
        current = current_branch(cwd)
        if not current:
            return "HEAD is no branch here"
        if hit := reached(current, protected):
            return f"{hit}, the branch checked out, is protected"
    fetch, push = remote_url(cwd, remote, push=False), remote_url(cwd, remote, push=True)
    if not fetch or not push:
        return f"git can't say where `{remote}` pushes"
    if not one_repo(fetch, push):
        return f"`{remote}` pushes to {push}, not to the repo it fetches from"
    return ""


def line_variable(line: list[str], pattern: re.Pattern) -> str:
    """The first variable a line sets that `pattern` names, before a command, alone, or through export, unset,
    declare, typeset or readonly, as `NAME`, or ""."""
    for words in simple_commands(line):
        program = run_program(words)
        head = words[:len(words) - len(program)]
        named = [word.partition("=")[0] for word in head if pattern.match(word)]
        name = PurePath(program[0]).name if program else ""
        if name in ("export", "unset", "declare", "typeset", "readonly"):
            named += [word.partition("=")[0] for word in program[1:] if pattern.match(word)]
        if named:
            return f"`{named[0]}`"
    return ""


def pushes(command: str, cwd: str, depth: int = 0, changed: str = "", moved: str = "") -> tuple[list[str], list[str]]:
    """A reason for each `git push` in the command line that takes none of the allowed forms (push_refusal), and one
    for each git command that rewrites what the guard reads as origin's (forges), or that the guard can't follow. It
    follows `sh -c`, `eval`, sudo and git aliases to the push. A push is refused whatever its words when its line
    sets a GIT_, HOME or XDG_CONFIG_HOME variable, moves it to another folder (a cd, `git -C`, `env -C`), or points
    git elsewhere (`-c`, --config-env, --git-dir, --work-tree): where git pushes is then the guard's guess, and the
    guard doesn't guess. `moved` carries such a change into a nested shell's line. A line whose quoting can't be read
    is refused whenever its text holds `git` and `push` anywhere."""
    try:
        line = tokens(command)
    except ValueError:
        if RAW_GIT.search(command) and "push" in command:
            return ["this line's quoting could not be read and it holds a git push, so run the push as a command "
                    "of its own"], []
        return [], []
    if depth > DEPTH:
        return ["this line nests shells, evals or aliases too deep for the guard to follow, so run it plainly"], []
    refused: list[str] = []
    updates: list[str] = []
    moved = moved or line_variable(line, GIT_VARIABLE)  # where git finds its repo and config, for the whole line
    for words in simple_commands(line):
        program = run_program(words)
        head = words[:len(words) - len(program)]  # assignments and wrappers, such as sudo -D or env -C
        name = PurePath(program[0]).name if program else ""
        wrapped = next((f"`{word.partition('=')[0]}`" for word in head
                        if word.partition("=")[0] in FOLDER_OPTIONS), "")
        if name == "git":
            index, overrides, elsewhere = 1, [], moved or wrapped
            expanded = 0
            while True:
                while index < len(program) and program[index].startswith("-"):
                    option, value = program[index], program[index + 1] if index + 1 < len(program) else ""
                    if option == "-c":
                        key, equals, setting = value.partition("=")
                        overrides.append((key, setting if equals else "true"))  # -c <key> alone sets it to true
                    elif option.startswith("--config-env"):  # --config-env=<key>=<variable>, or the pair as the value
                        overrides.append(((option.partition("=")[2] or value).rpartition("=")[0], None))
                    if option.partition("=")[0] in ("-C", "--git-dir", "--work-tree", "--config-env", "-c",
                                                    "--namespace", "--exec-path"):
                        elsewhere = elsewhere or f"`git {option.partition('=')[0]}`"
                    index += 2 if option in GIT_VALUE_OPTIONS else 1
                subcommand = program[index] if index < len(program) else ""
                if not subcommand or subcommand in GIT_COMMANDS:
                    break
                alias = git_alias(subcommand, cwd, overrides)
                if alias is None:  # an outside git-<name> program, unless this line can make it an alias
                    if changed or elsewhere:
                        updates.append(f"`git {subcommand}` may be an alias {changed or elsewhere} on this line "
                                       "defines, which the guard can't see")
                    break
                expanded += 1
                if not alias or expanded > DEPTH:
                    updates.append(f"the guard can't read what the git alias `{subcommand}` runs")
                    break
                if alias.startswith("!"):  # a shell alias: the guard reads the line it runs
                    found = pushes(f"{alias[1:]} {shlex.join(program[index + 1:])}", cwd, depth + 1, changed,
                                   elsewhere)
                    refused, updates = refused + found[0], updates + found[1]
                    break
                try:
                    program = [*program[:index], *shlex.split(alias), *program[index + 1:]]
                except ValueError:
                    updates.append(f"the guard can't read what the git alias `{subcommand}` runs")
                    break
            subcommand = program[index] if index < len(program) else ""
            if subcommand == "push":
                reason = (f"{elsewhere} on this line can change where git pushes" if elsewhere else
                          push_refusal(program[index + 1:], cwd, protected_branches(cwd), changed))
                if reason:
                    refused.append(reason)
            else:
                if reason := forges(subcommand, program[index + 1:], overrides):
                    updates.append(reason)
                if subcommand in LINE_CHANGES_GIT:  # refused or not, what it changes holds for the rest of the line
                    changed = changed or f"`git {subcommand}`"
                    if subcommand in ("config", "branch", "remote"):  # each can change where a later push goes
                        moved = moved or f"`git {subcommand}`"
        elif name in SHELLS or name == "eval":
            for inner in shell_lines(name, program[1:]):
                found = pushes(inner, cwd, depth + 1, changed, moved or wrapped)
                refused, updates = refused + found[0], updates + found[1]
            if name == "eval":  # it runs in this shell, so its cd or checkout carries on along the line
                changed = changed or "`eval`"
                moved = moved or "`eval`"
        elif name == "xargs" and (sub := fed(program[1:], "git", GIT_COMMANDS, {"push"})):
            updates.append(f"`xargs` runs `git {sub}` with words the guard can't see, so run it as a command of "
                           "its own")
        elif name == "alias" and any(re.search(r"\bgit\b.*\bpush\b", word) for word in program[1:]):
            updates.append("this line defines a shell alias that pushes, which the guard can't follow")
        elif name in LINE_CHANGES:
            changed, moved = changed or f"`{name}`", moved or f"`{name}`"
    return refused, updates


# The merge guard


def pr_target(target: str, repo: str, cwd: str) -> tuple[str, str, str]:
    """The branch a pull request merges into, the URL of the repo it is in, and its own branch, from `gh pr view`, or
    ("", "", "") when gh can't say. `target` is its number, URL or branch, "" for the branch checked out, and `repo`
    the --repo given, if any."""
    argv = ["gh", "pr", "view", *([target] if target else []), *(["--repo", repo] if repo else []),
            "--json", "baseRefName,url,headRefName", "--jq", '.baseRefName + " " + .url + " " + .headRefName']
    try:
        run = subprocess.run(argv, cwd=cwd or None, capture_output=True, text=True, timeout=GH_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return "", "", ""
    words = run.stdout.split() if run.returncode == 0 else []
    base, url, head = (words + ["", "", ""])[:3]
    found = PR_URL.match(url.strip())
    return (base, found[1], head) if base and found else ("", "", "")


def host_json(host: str, path: str) -> tuple[object, bool]:
    """One `gh api` read from the code host, as host_toml reads: (its JSON, False), or (None, True) when the host says
    it has no such thing (HTTP 404), or (None, False) when it can't be read."""
    argv = ["gh", "api", *(["--hostname", host] if host and host != "github.com" else []), path]
    try:
        run = subprocess.run(argv, capture_output=True, text=True, timeout=GH_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None, False
    if run.returncode:
        return None, "HTTP 404" in run.stderr
    try:
        return json.loads(run.stdout), False
    except ValueError:
        return None, False


def origin_holds(home: str) -> list[dict] | None:
    """The holds of the repo at the URL `home`, as freeze.py keeps them on its refs/colony/holds: the JSON in the
    message of the commit that ref points at. They are read from the code host with `gh api`, as Allowance reads the
    person's yes, never through git, whose remotes and URL rewrites an agent can change. [] when the repo has no
    holds ref; None when they can't be read."""
    host, repo = repo_of(home)
    if not repo:
        return None
    ref, missing = host_json(host, f"repos/{repo}/git/ref/{HOLDS_REF.removeprefix('refs/')}")
    if missing:
        return []
    sha = ref.get("object", {}).get("sha") if isinstance(ref, dict) and isinstance(ref.get("object"), dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", sha):
        return None
    commit, _ = host_json(host, f"repos/{repo}/git/commits/{sha}")
    message = commit.get("message") if isinstance(commit, dict) else None
    if not isinstance(message, str):
        return None
    _, _, body = message.partition("\n\n")
    try:
        holds = json.loads(body or "[]")
    except ValueError:
        holds = []  # as freeze.read reads it
    return [hold for hold in holds if isinstance(hold, dict)] if isinstance(holds, list) else []


def held_by(base: str, cwd: str) -> list[str]:
    """The branches whose holds pause a merge into `base`, as freeze.reaches says: the branch itself, and for the
    base, the integration branch too when it differs, which the working copy or origin's copy of colony.toml names."""
    text = colony_toml(cwd)
    committed = committed_toml(cwd, [default_branch(cwd), project_base(text) or "main"]) or ""
    bases = {project_base(text) or "main", *filter(None, [project_base(committed)])}
    if base not in bases:
        return [base]
    return list(dict.fromkeys([base, *filter(None, (project_value(text, "integration"),
                                                    project_value(committed, "integration")))]))


def hold_words(hold: dict) -> str:
    """One hold in words, as freeze.describe says it."""
    branch, kind = str(hold.get("branch", "?")), hold.get("kind")
    why = f" ({hold['why']})" if hold.get("why") else ""
    if kind == "red":
        return f"{branch} is red: it fails its checks{why}"
    reason = "for the release" if kind == "release" else "by hand"
    return f"{branch} is frozen {reason}{why}, by {hold.get('by') or 'someone'}"


def holds_refusal(base: str, head: str, cwd: str, which: str, home: str) -> str:
    """Why a merge into `base`, in the repo at the URL `home`, must wait for a live hold on it, the release freeze or
    a red hold, or "": a hold whose allow list names the pull request's branch or its card, `#<n>` from a branch such
    as ana/12, lets it through. When the holds can't be read, it waits too."""
    holds = origin_holds(home)
    if holds is None:
        return (f"origin's merge freeze, {HOLDS_REF}, could not be read, so the guard can't tell whether {base} is "
                "frozen or red: merge once origin can be reached")
    card = re.search(r"(?:^|/)(\d+)$", head)
    names = {head, f"#{card[1]}" if card else ""} - {""}
    reach, now = held_by(base, cwd), time.time()
    for hold in holds:
        until = hold.get("until") or 0
        ended = isinstance(until, (int, float)) and not isinstance(until, bool) and 0 < until <= now
        if not ended and hold.get("branch") in reach and not names & set(map(str, hold.get("allow") or [])):
            return (f"{which} merges into {base}, and {hold_words(hold)}: merges wait until the hold ends, unless "
                    "`colony freeze allow` names this pull request's branch or card")
    return ""


def pr_allowed(base: str, home: str, cwd: str, which: str = "this pull request", head: str = "") -> str:
    """Why merging a pull request, from the branch `head`, into `base`, in the repo at the URL `home`, isn't allowed,
    or "". The yes comes from that repo's own default branch, and only when it is origin's repo; then a live freeze
    or red hold on the base still makes it wait (holds_refusal)."""
    if not base:
        return f"`gh pr view` could not say which branch and repo {which} merges into"
    there, mine = repo_of(home), origin_repo(cwd)
    if not same_repo(there, mine):
        return (f"{which} is in {there[1] or home}, not in this repo's origin, "
                f"{mine[1] or 'which the guard cannot name'}")
    if Allowance(cwd, home).permits(base):
        return holds_refusal(base, head, cwd, which, home)
    return f"{which} merges into {base}, which [safety] merge_into on the repo's default branch doesn't name"


def pr_merge(arguments: list[str], repo: str, cwd: str) -> str:
    """Why a `gh pr merge` with these arguments, the words after `merge`, merges into a branch the person hasn't
    allowed, or ""."""
    target, skip = "", False
    for word in arguments:
        if skip:
            skip = False
        elif word in PR_MERGE_VALUE_OPTIONS:
            skip = True
        elif not word.startswith("-") and not target:
            target = word
    if not Allowance(cwd).named:
        return "`gh pr merge` merges a pull request, and [safety] merge_into allows no branch"
    base, home, head = pr_target(target, repo, cwd)
    return pr_allowed(base, home, cwd, head=head)


def file_bytes(name: str, cwd: str) -> bytes | None:
    """A file a call names, read as the shell finds it: from the call's folder, with ~ and $VARIABLES expanded, at
    most FILE_LIMIT bytes; None when it can't be read or is longer."""
    path = Path(os.path.expandvars(os.path.expanduser(name)))
    if not path.is_absolute():
        path = Path(cwd or ".") / path
    try:
        with open(path, "rb") as handle:
            data = handle.read(FILE_LIMIT + 1)
    except OSError:
        return None
    return data if len(data) <= FILE_LIMIT else None


def graphql_source(option: str, value: str) -> str | None:
    """Where a `gh api` field's value comes from: the file a `-F key=@file` or `--input file` names, "-" for standard
    input, or None for a value written on the line. `-f` sends its value as it is, @ or not."""
    if option == "--input":
        return value
    if option in ("-F", "--field"):
        _, _, given = value.partition("=")
        return given[1:] if given.startswith("@") else None
    return None


def api_merge(arguments: list[str], cwd: str = "") -> str:
    """Why a `gh api` call with these arguments, the words after `api`, merges through the API, or "". A GraphQL
    query read from a file is read from the call's folder; one from standard input, or from a file the guard can't
    read, is refused, since the guard can't see what it does."""
    method, path, values, option = "", "", [], ""
    for word in arguments:
        if option:
            method = word.upper() if option in ("-X", "--method") else method
            values += [(option, word)] if option in GH_API_FIELDS else []
            option = ""
        elif word in GH_API_VALUE_OPTIONS:
            option = word
        elif word.startswith("--method="):
            method = word.partition("=")[2].upper()
        elif word.startswith("-X"):
            method = word[2:].upper()
        elif word.startswith(("--field=", "--raw-field=", "--input=")):
            name, _, value = word.partition("=")
            values.append((name, value))
        elif word.startswith(("-f", "-F")) and len(word) > 2:
            values.append((word[:2], word[2:]))
        elif not word.startswith("-") and not path:
            path = word.strip("/")
    path = path.partition("?")[0]
    if re.search(r"(?:^|/)pulls/[^/]+/merge$", path) and method == "PUT":
        return "`gh api` merges a pull request, which only `gh pr merge` may do, so the guard can check its base"
    if re.search(r"(?:^|/)merges$", path) and (method == "POST" or (not method and values)):
        return "`gh api` merges a branch, which only `gh pr merge` may do, so the guard can check its base"
    if path != "graphql":
        return ""
    merges = ("`gh api graphql` merges a pull request, which only `gh pr merge` may do, so the guard can check its "
              "base")
    for given, value in values:
        source = graphql_source(given, value)
        if source is None:
            if GRAPHQL_MERGE.search(value):
                return merges
            continue
        if source in ("", "-"):
            return ("`gh api graphql` reads its query from standard input, which the guard can't read: write the "
                    "query on the line, or in a file it names")
        data = file_bytes(source, cwd)
        if data is None:
            return (f"`gh api graphql` reads its query from {source}, which the guard can't read from this folder, "
                    "so it can't check that the query merges nothing")
        if GRAPHQL_MERGE.search(data.decode("utf-8", errors="replace")):
            return f"{merges}: {source} holds a merge mutation"
    return ""


# Scripts: a push, a merge or a kill moved into a file the line runs as a script


SCRIPT_SOURCES = {"source", "."}  # the shell's own commands that run a file's lines
SHELL_VALUE_OPTIONS = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}  # a shell's options that take a value
STDIN_NAMES = {"-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"}  # a shell's script read from standard input
PIPES = {"|", "|&"}  # the operators that feed a command's standard input from the one before
SPECIAL_FILES = ("/dev/", "/proc/")  # files that read a stream, never a script the guard can read in full
# The first bytes of a real program: ELF, Mach-O (both byte orders, 32 and 64 bit, and fat), and Windows' PE. A file
# counts as one only with a zero byte on its first line too, as bash's own check asks before it runs a file as a
# script when the system can't run it as a program.
PROGRAM_MAGIC = (b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
                 b"\xca\xfe\xba\xbe", b"MZ")
SHELL_NO_SCRIPT = {"--version", "--help"}  # a shell asked only to describe itself runs no script
HELD = (("push", RAW_PUSH, "a `git push`"), ("merge", RAW_MERGE, "a gh merge"), ("kill", RAW_KILL, "a kill"))
# In a script's text the guard can't read as commands, what may run another script.
RAW_SCRIPT = re.compile(r"(?<![\w.-])(?:bash|sh|zsh|dash|source|eval)(?![\w-])|(?:^|[\s;&|(])\.\s|(?:^|[\s;&|(])\.{0,2}/")
NESTED = "nests shells, evals or scripts deeper than the guard follows, so run them plainly"
STDIN_REFUSAL = ("a shell on this line reads its script on standard input from something the guard can't read: save "
                 "the script to a file, read it, and run it as `sh <file>`")


def shell_segments(line: list[str]) -> list[tuple[list[str], str, str]]:
    """A line's simple commands as sequence() splits them, each with what a redirection gives its standard input,
    descriptor 0: the file after a `<`, or "<<" for what the guard can't read as a file, a here-document, a
    here-string, a copy of another descriptor (`<&3`, `0>&3`) or any other operator on descriptor 0, else ""; and the
    operator before it, such as | for a command fed by a pipe. A redirection of any other descriptor, such as
    `3< file` or `2> file`, leaves standard input be."""
    found: list[tuple[list[str], str, str]] = []
    words: list[str] = []
    given, before, skip, stdin = "", "", "", False
    for token in line:
        if skip:
            if stdin:
                given = token if skip == "<" else "<<"
            skip, stdin = "", False
        elif token in REDIRECTIONS or token.startswith("<<"):
            descriptor = int(words.pop()) if words and words[-1].isdigit() else None
            skip = token
            # Standard input changes when the redirection targets descriptor 0: any operator that names it, such as
            # `0>&3`, and an input one that names none. Only a plain `<` gives a file the guard can read.
            stdin = descriptor == 0 or (descriptor is None and token.startswith("<"))
        elif token and set(token) <= PUNCTUATION:
            if words:
                found.append((words, given, before))
            words, given, before = [], "", token
        elif token not in ("{", "}"):
            words.append(token)
    return [*found, (words, given, before)] if words else found


def folder_move(line: list[str]) -> str:
    """What on a line moves the folder a later command runs in, a cd, pushd or popd, or a wrapper's -C or --chdir;
    "" for none. A relative script after it runs from a folder the guard can't name."""
    for words in simple_commands(line):
        program = run_program(words)
        if program and PurePath(program[0]).name in LINE_CHANGES:
            return f"`{PurePath(program[0]).name}`"
        moving = [word for word in words[:len(words) - len(program)] if word.partition("=")[0] in FOLDER_OPTIONS]
        if moving:
            return f"`{moving[0].partition('=')[0]}`"
    return ""


def script_named(program: list[str]) -> tuple[str, bool]:
    """The file a simple command runs as a script, and whether a shell or source reads it rather than a program run by
    its path: a shell's first operand (`bash f`, `sh -e f`), `-` when it reads its script on standard input (no
    operand, `-`, or -s in its options), the file `source f` or `. f` reads, or a program named by its path (`./f`).
    ("", False) for none."""
    if not program:
        return "", False
    if PurePath(program[0]).name in SHELLS:
        if program[1:2] and program[1] in SHELL_NO_SCRIPT:  # only first: later, it is the script's own argument
            return "", True
        skip, ended = False, False
        for word in program[1:]:
            if skip:
                skip = False
            elif ended or not word.startswith(("-", "+")):
                return ("-" if word in STDIN_NAMES else word), True  # the first operand is the script
            elif word in ("-", "--"):
                ended = True  # the options end, and the next word is the script, whatever it looks like
            elif word in SHELL_VALUE_OPTIONS:
                skip = True
            elif word.startswith("-") and not word.startswith("--") and "s" in word[1:]:
                return "-", True  # -s: the script is standard input, and the operands only its arguments
        return "-", True
    if program[0] in SCRIPT_SOURCES:
        return (program[1] if len(program) > 1 else ""), True
    return (program[0], False) if "/" in program[0] else ("", False)


def script_text(name: str, cwd: str, read_by_shell: bool) -> str | None:
    """A script's text, read from the call's folder as the shell finds it, its zero bytes dropped; "" for a program
    run by its path that starts as a real program does (PROGRAM_MAGIC, with a zero byte on its first line); None when
    it is no regular file, can't be read, or is longer than FILE_LIMIT. A file a shell or source reads is always text
    to the guard, as it is to the shell, and so is a #! file."""
    path = Path(os.path.expandvars(os.path.expanduser(name)))
    path = path if path.is_absolute() else Path(cwd or ".") / path
    try:
        if name in STDIN_NAMES or str(path).startswith(SPECIAL_FILES) or not stat.S_ISREG(os.stat(path).st_mode):
            return None
        with open(path, "rb") as handle:
            data = handle.read(FILE_LIMIT + 1)
    except OSError:
        return None
    first = data.split(b"\n", 1)[0]
    if not read_by_shell and not data.startswith(b"#!") and data.startswith(PROGRAM_MAGIC) and b"\0" in first:
        return ""
    if len(data) > FILE_LIMIT:
        return None
    return data.replace(b"\0", b"").decode("utf-8", errors="replace")


def script_findings(name: str, cwd: str, depth: int, read_by_shell: bool) -> list[tuple[str, str]]:
    """(kind, what) for each push, merge or kill a script holds, or a script it runs in turn holds: what follows the
    script's name in a reason, such as "holds a `git push`". A script the guard can't read, and one that runs scripts
    deeper than DEPTH, gives kind merge."""
    text = script_text(name, cwd, read_by_shell)
    if text == "":
        return []
    if text is None:
        return [("merge", "can't be read from this folder as a regular file, so the guard can't check that it pushes, "
                          "merges or kills nothing: run it by a path the guard can read")]
    held = [(kind, f"holds {what}, which the guard can't check inside a script") for kind, pattern, what in HELD
            if pattern.search(text)]
    if held:
        return held
    try:
        tokens(text)
    except ValueError:  # its text can't be read as commands: refuse when it may run another script
        return [("merge", f"runs commands the guard can't read, and may run another script, so {NESTED}")] \
            if RAW_SCRIPT.search(text) else []
    if depth >= DEPTH:
        return [("merge", NESTED)] if scripts(text, cwd, DEPTH, probe=True) else []
    return [(kind, f"runs {inner}, which {what}" if inner else f"runs a line where {what}")
            for kind, inner, what in scripts(text, cwd, depth + 1)]


def fed_files(segments: list[tuple[list[str], str, str]], index: int, given: str, before: str) -> list[str] | None:
    """The files a shell reads its script from on standard input: the regular file a `<` gives it, or the files a
    plain `cat` before a pipe gives it. None when anything else feeds it: a here-document or here-string, which can
    expand to a file's text, process substitution, another program, or a cat of its own standard input."""
    if given:
        return None if given == "<<" else [given]
    if before not in PIPES or not index:
        return None
    words, cat_given, _ = segments[index - 1]
    feeder = run_program(words)
    files = [word for word in feeder[1:] if not word.startswith("-") or word == "-"]
    if not feeder or PurePath(feeder[0]).name != "cat" or cat_given or not files:
        return None
    return None if any(word in STDIN_NAMES or word.startswith(SPECIAL_FILES) for word in files) else files


def scripts(command: str, cwd: str, depth: int = 0, probe: bool = False) -> list[tuple[str, str, str]]:
    """(kind, script, what) for each script the line runs, through a shell's -c and eval too, that holds a push, a
    merge or a kill, or runs a script that does; script is "" when the reason names no file. Kind is push, merge or
    kill: the guard whose refusal it joins. A shell that reads its script on standard input is read from the regular
    files a `<` or a plain `cat` gives it, and refused when fed by anything else; a relative script after a folder
    change is refused. With `probe`, it only says whether the line runs any script or shell line at all."""
    try:
        line = tokens(command)
    except ValueError:
        return []
    found: list[tuple[str, str, str]] = []
    moved = folder_move(line)
    segments = shell_segments(line)
    for index, (words, given, before) in enumerate(segments):
        program = run_program(words)
        name = PurePath(program[0]).name if program else ""
        if name in SHELLS or name == "eval":
            inner = shell_lines(name, program[1:])
            if inner:
                if probe:
                    return [("merge", "", NESTED)]
                if depth >= DEPTH:
                    found.append(("merge", "", f"this line {NESTED}"))
                else:
                    found += [item for text in inner for item in scripts(text, cwd, depth + 1)]
                continue
        script, read_by_shell = script_named(program)
        if script and probe:
            return [("merge", "", NESTED)]
        files = [script] if script and script != "-" else []
        if script == "-":
            fed = fed_files(segments, index, given, before)
            if fed is None:
                found.append(("merge", "", STDIN_REFUSAL))
                continue
            files = fed
        for file in files:
            if moved and not Path(os.path.expandvars(os.path.expanduser(file))).is_absolute():
                found.append(("merge", file, f"runs from another folder: this line changes folder before it runs "
                                             f"({moved}), so the guard can't tell which file that is. Run the script "
                                             "by its full path, or run the cd as a command of its own first"))
                continue
            found += [(kind, file, what) for kind, what in script_findings(file, cwd, depth, read_by_shell)]
    return found


def gh_alias(name: str, cwd: str) -> str | None:
    """What a gh alias stands for, from `gh alias list`, or None when `name` is no alias."""
    try:
        run = subprocess.run(["gh", "alias", "list"], cwd=cwd or None, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in run.stdout.splitlines() if run.returncode == 0 else []:
        key, colon, value = line.partition(":")
        if colon and key.strip() == name:
            return value.strip().strip("'\"")
    return None


def context_change(line: list[str]) -> str:
    """What on a line can make a gh command act on another repo, host or folder than the one the guard checks: a cd,
    a wrapper that moves the command, such as `env -C` or `sudo -D`, or a GH_, GITHUB_ or GIT_ variable set or
    exported anywhere on it, since gh finds its repo through git; "" for none."""
    variable = line_variable(line, GH_VARIABLE) or line_variable(line, GIT_VARIABLE)
    for words in simple_commands(line):
        program = run_program(words)
        head = words[:len(words) - len(program)]
        name = PurePath(program[0]).name if program else ""
        if name in LINE_CHANGES:
            return f"`{name}`"
        moving = [word for word in head if word.partition("=")[0] in FOLDER_OPTIONS]
        if moving:
            return f"`{moving[0].partition('=')[0]}`"
    return variable


def gh_merges(command: str, cwd: str, depth: int = 0) -> list[str]:
    """A reason for each `gh` call on the line that merges a pull request into a branch [safety] merge_into doesn't
    allow, merges a pull request in another repo, merges through the API, or defines an alias that can merge. It
    follows `sh -c`, `eval`, sudo and gh aliases. A `gh pr merge` that shares its line with a cd, `env --chdir` or a
    GH_ variable is refused, since the pull request the guard checks may not be the one it merges. A line whose
    quoting can't be read is refused whenever it holds gh and merge."""
    try:
        line = tokens(command)
    except ValueError:
        if re.search(r"(?<![\w.-])gh(?![\w-])", command) and "merge" in command.lower():
            return ["this line's quoting could not be read and it holds a gh merge, so run the merge as a command of "
                    "its own"]
        return []
    if depth > DEPTH:
        return ["this line nests shells, evals or aliases too deep for the guard to follow, so run it plainly"]
    found = []
    context = context_change(line)
    for words in simple_commands(line):
        program = run_program(words)
        name = PurePath(program[0]).name if program else ""
        if name in SHELLS or name == "eval":
            found += [reason for inner in shell_lines(name, program[1:])
                      for reason in gh_merges(inner, cwd, depth + 1)]
            continue
        if name == "xargs" and (sub := fed(program[1:], "gh", GH_COMMANDS, {"merge", "api"})):
            found.append(f"`xargs` runs `gh` ({sub}) with words the guard can't see, so run it as a command of its own")
            continue
        if name == "alias" and any(re.search(r"\bgh\b.*\b(?:merge|api)\b", word) for word in program[1:]):
            found.append("this line defines a shell alias that merges, which the guard can't follow")
            continue
        if name not in ("gh", "gh.exe"):
            continue
        arguments = program[1:]
        repo = next((value for flag, value in zip(arguments, arguments[1:]) if flag in GH_REPO_FLAGS), "") or next(
            (word.partition("=")[2] for word in arguments if word.startswith("--repo=")), "")
        rest = without_repo_flag(arguments)
        for _ in range(DEPTH):  # a gh alias stands for the words it expands to
            if not rest or rest[0].startswith("-") or rest[0] in GH_COMMANDS:
                break
            alias = gh_alias(rest[0], cwd)
            if alias is None:
                break  # an extension, such as gh dash
            if alias.startswith("!"):
                found += gh_merges(f"{alias[1:]} {shlex.join(rest[1:])}", cwd, depth + 1)
                rest = []
                break
            try:
                rest = [*shlex.split(alias), *rest[1:]]
            except ValueError:
                found.append(f"the guard can't read what the gh alias `{rest[0]}` runs")
                rest = []
        if rest[:2] == ["alias", "set"] and any(re.search(r"\b(?:merge|api)\b|^!", word) for word in rest[2:]):
            found.append("`gh alias set` defines an alias that can merge, which the guard can't follow")
        elif rest[:2] == ["alias", "import"]:
            found.append("`gh alias import` can define aliases that merge, which the guard can't follow")
        elif rest[:2] == ["pr", "merge"] and "--disable-auto" not in rest:
            found.append(f"`gh pr merge` shares its line with {context}, so the pull request the guard checks may not "
                         "be the one it merges: run it on a line of its own, with --repo for another repo" if context
                         else pr_merge(rest[2:], repo, cwd))
        elif rest[:1] == ["api"]:
            found.append(api_merge(rest[1:], cwd))
    return [reason for reason in found if reason]


def tool_merges(tool: str, tool_input: dict, cwd: str) -> list[str]:
    """Why a GitHub tool's call, such as mcp__github__merge_pull_request, merges a pull request the person hasn't
    allowed, or commits straight onto a protected branch name. This repo is origin's, as `git remote get-url origin`
    says. A merge passes only in this repo, into a branch the person allows. A commit onto a protected branch name
    passes only in this repo, into an allowed branch, and is refused in any other repo; one that names no branch, or
    runs where origin can't be worked out, is refused."""
    action = tool.rsplit("__", 1)[-1]
    if action in MCP_PR_MERGES:
        if not Allowance(cwd).named:
            return [f"`{action}` merges a pull request, and [safety] merge_into allows no branch"]
        number = next((str(tool_input[key]) for key in ("pullNumber", "pull_number", "number", "pr_number")
                       if tool_input.get(key)), "")
        owner, name = tool_input.get("owner"), tool_input.get("repo")
        if not (number and owner and name):
            return [f"`{action}` names no pull request number, owner and repo for the guard to check"]
        base, home, head = pr_target(number, f"{owner}/{name}", cwd)
        reason = pr_allowed(base, home, cwd, f"pull request {number}", head)
        return [reason] if reason else []
    if action in MCP_COMMITS:
        owner, name, branch = tool_input.get("owner"), tool_input.get("repo"), str(tool_input.get("branch") or "")
        if not branch:
            return [f"`{action}` names no branch, so it commits onto the default branch"]
        mine = origin_repo(cwd)
        if not mine[1]:
            return [f"`{action}` commits onto {branch}, and the guard can't tell this repo from origin's URL to "
                    "check it"]
        held = reaches(branch, protected_branches(cwd))
        if not held:
            return []  # a branch of the agent's own
        there = (mine[0], f"{owner}/{name}") if owner and name else mine
        if not same_repo(there, mine):
            return [f"`{action}` commits onto {held[0]} in {there[1]}, which is not this repo's origin, {mine[1]}"]
        allowance = Allowance(cwd, f"https://{mine[0]}/{mine[1]}")
        refused = [b for b in held if not allowance.permits(b)]
        if refused:
            return [f"`{action}` commits straight onto {refused[0]}"]
        home = f"https://{mine[0]}/{mine[1]}"
        return [reason for b in held if (reason := holds_refusal(b, "", cwd, f"`{action}`", home))][:1]
    return []


# The kill guard


def kill_targets(arguments: list[str]) -> list[str] | None:
    """The process ids a `kill` with these arguments signals, past its signal option, or None for `kill -l`, which
    only lists the signals."""
    first = arguments[0] if arguments else ""
    if first in ("-l", "-L", "--list", "--table") or first.startswith("--list="):
        return None
    start = 2 if first in ("-s", "-n", "--signal") else 1 if first.startswith("-") and first != "-" else 0
    return [word for word in arguments[start:] if word != "--"]


def target_reason(word: str) -> str | None:
    """Why a kill target signals more than one chosen process: "" for an id over 1, a job such as %1, or $!; a
    reason for 0, 1, -1 or a negative group id; None for any other word, such as $pid, whose ids come from
    elsewhere."""
    if word.startswith("%") or word in ("$!", "${!}"):
        return ""
    if word.isdigit():
        number = int(word)
        return "" if number > 1 else "`kill 0` signals every process in this shell's group" if number == 0 else \
            "`kill 1` signals the system's first process"
    if word.startswith("-") and word[1:].isdigit():
        return ("`kill -1` signals every process you own, every Claude Code session among them" if word == "-1"
                else f"`kill {word}` signals the whole process group {word[1:]}")
    return None


def command_kills(program: list[str], searching: bool) -> list[str]:
    """Why one simple command, from its program on, kills by name or pattern. `searching` says the line looks
    running processes up, so a kill id that isn't a number can be a search's output."""
    if not program:
        return []
    name, arguments = PurePath(program[0]).name.lower(), program[1:]
    name = name[:-4] if name.endswith(".exe") else name
    if name in PATTERN_KILLERS:
        return [f"`{name}` signals every process its name or pattern matches"]
    if name == "kill":
        found = []
        for word in kill_targets(arguments) or []:
            reason = target_reason(word)
            if reason or (reason is None and searching):
                found.append(reason or "this `kill` takes its process ids from a search of the running processes")
        return found
    if name == "xargs":
        killer = next((PurePath(word).name for word in arguments if PurePath(word).name in {*PATTERN_KILLERS, "kill"}),
                      "")
        if killer in PATTERN_KILLERS:
            return [f"`{killer}` signals every process its name or pattern matches"]
        return ["`xargs kill` takes its process ids from a search of the running processes"] if killer and searching \
            else []
    if name == "fuser" and any(word == "--kill" or re.fullmatch(r"-[a-z]*k[a-z]*", word) for word in arguments):
        return ["`fuser -k` signals every process that uses a file or a port"]
    if name == "taskkill" and any(word.lstrip("/-").lower() in ("im", "fi") for word in arguments):
        return ["`taskkill /IM` or `/FI` ends every process its name or filter matches"]
    if name in POWERSHELLS and POWERSHELL_KILL.search(" ".join(arguments)):
        return ["PowerShell's `Stop-Process -Name`, or a pipe into it, ends every process the name or search matches"]
    if name in SHELLS:
        return [reason for i, word in enumerate(arguments[:-1]) if word.startswith("-") and "c" in word.lstrip("-")
                for reason in kills(arguments[i + 1])]
    if name == "eval":
        return kills(" ".join(arguments))
    return []


def kills(command: str) -> list[str]:
    """A reason for each kill by name or pattern a command line holds (see the module's docstring). A line whose
    quoting can't be read is refused whenever its plain text holds such a kill."""
    try:
        line = tokens(command)
    except ValueError:
        if RAW_KILL.search(command):
            return ["this line's quoting could not be read and it holds a kill, so run the kill as a command of its "
                    "own"]
        return []
    searching = bool(SEARCHES.search(command))
    found = [reason for words in simple_commands(line) for reason in command_kills(run_program(words), searching)]
    return list(dict.fromkeys(found))


def kind_of(program: list[str]) -> str:
    """What one simple command runs, of what the plain-line rule asks about: "push" for `git push`, "merge" for
    `gh pr merge` or `gh api`, "kill" for a kill command, else ""."""
    name = PurePath(program[0]).name.lower() if program else ""
    name = name[:-4] if name.endswith(".exe") else name
    if name == "git":
        index = 1
        while index < len(program) and program[index].startswith("-"):
            index += 2 if program[index] in GIT_VALUE_OPTIONS else 1
        return "push" if program[index:index + 1] == ["push"] else ""
    if name == "gh":
        rest = without_repo_flag(program[1:])
        return "merge" if rest[:2] == ["pr", "merge"] or rest[:1] == ["api"] else ""
    if name in KILLERS or (name == "xargs" and any(PurePath(word).name in {*PATTERN_KILLERS, "kill"}
                                                   for word in program[1:])):
        return "kill"
    return ""


def plain_line(command: str, kind: str, pattern: re.Pattern) -> str:
    """Why a line whose raw text names a `kind` ("push", "merge" or "kill"), as `pattern` finds it, is no plain command
    of that kind, or "". A plain line is one simple command, with no other command, operator, substitution,
    here-document or process substitution, alias or function definition, eval or `sh -c`. Its raw text holds none of
    NOT_PLAIN and NOT_PLAIN_CHARACTERS, and `pattern` finds exactly one match there, at its very start, so the
    command the raw text names is the one the parser reads. And the command it runs is of that kind, so the guard's
    own reading of it is the shell's."""
    raw = command.strip()
    if mark := next((mark for mark in NOT_PLAIN if mark in raw), ""):
        return {"\n": "a second line", "<<": "a here-document"}.get(mark, f"a `{mark}`")
    if mark := next((mark for mark in NOT_PLAIN_CHARACTERS if mark in raw), ""):
        return f"a `{mark}`"
    matches = list(pattern.finditer(raw))
    if len(matches) != 1:
        return f"{len(matches)} of them named in its text"
    if matches[0].start():
        return "words before it, such as a wrapper, an assignment or another command"
    try:
        line = tokens(command)
    except ValueError:
        return "quoting the guard can't read"
    if operator := next((token for token in line if token in OPERATORS and token not in REDIRECTIONS), ""):
        return f"a `{operator}` that joins it to other commands"
    commands = simple_commands(line)
    program = run_program(commands[0]) if len(commands) == 1 else []
    name = PurePath(program[0]).name if program else ""
    if name in ("eval", "alias", "function", *SHELLS) or kind_of(program) != kind:
        return f"`{name}` around it" if name in ("eval", "alias", "function", *SHELLS) else \
            "words that only name it, as text does"
    return ""


def main() -> int:
    """Read the hook's call from stdin: exit 2 with the reasons for a foreground wait, a push that rewrites a protected
    branch, a merge or push the person hasn't allowed, or a kill by name or pattern, else 0. A GitHub tool's call,
    which Claude Code sends here too, is read for a merge alone."""
    try:
        call = json.load(sys.stdin)
        tool_input = call["tool_input"]
        if not isinstance(tool_input, dict):
            raise TypeError("the input is not an object")
        tool = str(call.get("tool_name") or "Bash")
        cwd = str(call.get("cwd") or os.getcwd())
        if tool.startswith("mcp__"):
            merged = tool_merges(tool, tool_input, cwd)
            if merged:
                sys.stderr.write(MERGE_REFUSAL.format(reason="; ".join(dict.fromkeys(merged))) + "\n")
                return 2
            return 0
        command = tool_input["command"]
        if not isinstance(command, str):
            raise TypeError("the command is not text")
    except (ValueError, KeyError, TypeError):
        return 0  # a call the guard can't read runs, and Claude Code's own checks still apply to it
    rewrites: list[str] = []
    merged: list[str] = []
    killed: list[str] = []
    if "push" in command or re.search(r"(?<![\w.-])git(?![\w-])", command):
        rewrites, merged = pushes(command, cwd)
    if "merge" in command.lower() or re.search(r"(?<![\w.-])gh(?![\w-])", command):
        merged += gh_merges(command, cwd)
    lowered = command.lower()
    if any(word in lowered for word in ("kill", "fuser", "stop-process", "spps")):
        killed = kills(command)
    # A push, a merge or a kill moved into a script the line runs, which the guards' reading of the line can't see.
    for kind, script, what in scripts(command, cwd):
        {"push": rewrites, "merge": merged, "kill": killed}[kind].append(f"the script {script} {what}" if script
                                                                          else what)
    # The plain-line rule: a line that names a push, a gh merge or a kill anywhere is one plain command of that kind.
    for kind, pattern, reasons in (("push", RAW_PUSH, rewrites), ("merge", RAW_MERGE, merged),
                                   ("kill", RAW_KILL, killed)):
        if pattern.search(command) and (why := plain_line(command, kind, pattern)):
            what = {"push": "a `git push`", "merge": "a gh merge", "kill": "a kill"}[kind]
            reasons.append(f"this line names {what} with {why}: {PLAIN_STEP[kind]}")
    refusals = []
    if rewrites:
        branches = protected_branches(cwd)
        refusals.append(PUSH_REFUSAL.format(reason="; ".join(dict.fromkeys(rewrites)), branches=" and ".join(branches)))
    if merged:
        refusals.append(MERGE_REFUSAL.format(reason="; ".join(dict.fromkeys(merged))))
    if killed:
        refusals.append(KILL_REFUSAL.format(reason="; ".join(dict.fromkeys(killed))))
    if refusals:
        sys.stderr.write("\n".join(refusals) + "\n")
        return 2
    if tool_input.get("run_in_background") is True:
        return 0
    found = waits(command)
    if not found:
        return 0
    sys.stderr.write(REFUSAL.format(reason="; ".join(dict.fromkeys(found))) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
