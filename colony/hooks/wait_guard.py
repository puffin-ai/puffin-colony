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
passes. It drops here-document bodies first, because a body is text a command reads, not a command. A line whose
quoting Python's shlex can't read, such as a $(...) holding quotes inside a double-quoted word, which the shell reads
fine, passes too, unless its plain text holds a sleep over MAX_SLEEP_SECONDS.

It also refuses, in every mode and even in the background, a `git push` that force-pushes or deletes the base branch,
`[project] base` in .colony/colony.toml (main when unset), or the repo's default branch, origin's HEAD (main when git
can't say): `--force`, `-f`, `--force-with-lease`, `--mirror`, a `+` refspec, a deletion, or `--prune` with a pattern
such as refs/heads/*, which it matches against those branches. It reads options as git does, so a prefix git accepts,
such as `--del`, counts as the whole option. A forced or deleting push that names no refspec updates what git config
says, `remote.<name>.push` or `push.default` with the line's own `-c` values, so with push.default=matching it
rewrites the base too; when git config can't say, such a push is refused. A plain push that names no refspec
rewrites a protected branch only when git config forces, deletes or mirrors it through it. The guard reads git config
before the line runs, so after a command on the same line that can change it or the branch checked out, such as `git
checkout` or `cd`, a forced push names its branch. `@` is HEAD, the branch checked out. A force push rewrites the
branch every teammate builds on, and makes each of them rebase. A forced push of tags alone passes. A line whose
quoting it can't read is refused whenever it holds `git` and `push`: run such a push on its own.

The kill guard refuses, in every mode and even in the background, a kill by pattern or by name: pkill, killall,
skill, `fuser -k`, `taskkill /IM` and PowerShell's `Stop-Process -Name`, and a `kill` whose process ids come from a
search of the running processes on the same line, such as `kill $(pgrep -f x)`, `pgrep x | xargs kill` or a loop over
`ps` output. It also refuses `kill -1`, `kill 0` and a negative id, which signal every process or a whole group. A
pattern matches more than anyone means: on macOS, `pkill -f "colony wait" -U $(id -u) -n` reads each word after the
pattern as one more pattern, and ended every Claude Code session on the computer. A kill of numbers, job specs such
as %1, `$!`, or ids from a file passes. A session closes another by name with `colony stop <name>`.

The merge guard refuses what lands work on a branch without the person's yes. A `gh pr merge`, and a GitHub tool's
merge of a pull request, pass only when the pull request's base is a branch `[safety] merge_into` names; a `gh api`
call that merges is refused, since `gh pr merge` is the way the guard can check. A plain `git push` that updates a
protected branch, and a GitHub tool that commits onto one, are refused unless `merge_into` names it. The protected
branches are the base, the repo's default branch and `[safety] protect`. The guard reads `merge_into` from the
colony.toml on origin's base, the copy the person merged, and from the working copy, and allows a branch only when
both name it, so an agent can't allow itself a merge by editing a file. A dry-run push passes.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path, PurePath

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
# A here-document's operator and its delimiter, quoted or not; <<< is a here-string, which has no body.
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
DURATION = re.compile(r"^(\d+(?:\.\d*)?|\.\d+)([smhd]?)$")
UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
# The shell's operators, longest first. shlex reads a run of punctuation as one token, such as `);` after a $(...),
# so tokens() splits a run into these.
OPERATORS = ("&&", "||", ";;", "|&", ">>", "<<", ">&", "<&", "&>", ">|", "(", ")", ";", "&", "|", "<", ">")
PUNCTUATION = set("();<>|&")
RAW_SLEEP = re.compile(r"(?<![\w.-])sleep\s+([0-9.]+[smhd]?)(?![\w.])")
RAW_GIT = re.compile(r"git")  # in a line shlex can't read, any git with a push is refused (pushes())
LIST_SEPARATORS = {";", "&&", "||", ";;"}
PIPES = {"|", "|&"}
BACKGROUND = "&"
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
                     "--attr-source", "--shallow-file"}  # git's, before `push`
# git push's long options, as `git push --git-completion-helper` lists them. Git reads a word that is a prefix of
# only one of them as that option, and refuses a prefix of several.
PUSH_OPTIONS = ("verbose", "quiet", "repo", "all", "branches", "mirror", "delete", "tags", "dry-run", "porcelain",
                "force", "force-with-lease", "force-if-includes", "recurse-submodules", "thin", "receive-pack",
                "exec", "set-upstream", "progress", "prune", "no-verify", "verify", "follow-tags", "signed",
                "atomic", "push-option", "ipv4", "ipv6")
PUSH_VALUE_OPTIONS = {"repo", "recurse-submodules", "receive-pack", "exec", "push-option"}  # take the next word
# The settings that choose what a push with no refspec updates, as git config prints their keys.
PUSH_CONFIG = (r"^(push\.default|remote\.pushdefault|remote\..+\.(push|mirror)|"
               r"branch\..+\.(remote|pushremote|merge))$")
FALSE = ("", "false", "no", "off", "0")  # the values git reads as false, and "" for a setting not there
# Commands that can change the branch checked out, git config or the folder for a later push on the same line, which
# the guard reads before the line runs.
LINE_CHANGES_GIT = {"checkout", "switch", "config", "branch", "remote", "symbolic-ref"}
LINE_CHANGES = {"cd", "pushd", "popd"}
GIT_VARIABLE = re.compile(r"^(GIT_\w*|HOME|XDG_CONFIG_HOME)(=|$)")  # where git finds its repo and its config
BASE = re.compile(r'^\s*base\s*=\s*"([^"]+)"', re.M)
PUSH_REFUSAL = ("push guard: refused, {reason}. Every teammate builds on {branches}: never force-push, rewrite or "
                "delete {them}. Push your own branch and land it with `colony merge <branch>`, or ask your person.")
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
POWERSHELL_KILL = re.compile(r"\b(?:stop-process|spps)\b[^;|]*\s-(?:name|processname)\b|\|\s*(?:stop-process|spps|kill)\b"
                             r"|\.kill\(\)", re.I)
REDIRECTIONS = {">", ">>", "<", "<<", ">&", "<&", "&>", ">|"}
RAW_KILL = re.compile(r"(?<![\w.-])(?:pkill|killall|killall5|skill|taskkill|fuser|stop-process|spps)(?![\w-])"
                      r"|(?<![\w.-])kill\b[^;&|\n]*(?:\$\(|`)|\bxargs\b[^;&|\n]*\bkill\b", re.I)
KILL_REFUSAL = ("kill guard: refused, {reason}. A kill by name or pattern can end every Claude Code session, the "
                "terminal app and the background tasks on this computer. Close a Colony session by its name with "
                "`colony stop <name>`. For any other process, find the one you mean, check it with "
                "`ps -p <pid> -o pid=,command=`, and kill that number alone: `kill <pid>`.")

# The merge guard
SAFETY = "safety"  # the colony.toml table that holds merge_into and protect
GH_TIMEOUT = 20  # seconds the guard gives `gh pr view` to say which branch a pull request merges into
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
REPO = re.compile(r'^\s*repo\s*=\s*"([^"]+)"', re.M)
MERGE_REFUSAL = ("merge guard: refused, {reason}. No agent merges or pushes into a branch without the person's yes: "
                 "push your own branch and open a pull request for the person to merge (in Hack, `colony merge "
                 "<branch>`). The person allows merges into a branch with `merge_into` under [safety] in "
                 ".colony/colony.toml, merged into the base.")


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


def without_heredoc_bodies(command: str) -> str:
    """The command line without the body lines of its here-documents."""
    kept: list[str] = []
    pending: list[str] = []
    for line in command.split("\n"):
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        kept.append(line)
        pending = [match[2] for match in HEREDOC.finditer(line)]
    return "\n".join(kept)


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


def tokens(command: str) -> list[str]:
    """The command line's words and operators. Raises ValueError when its quoting can't be read."""
    lexer = shlex.shlex(without_heredoc_bodies(command).replace("\n", ";"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    found: list[str] = []
    for token in lexer:
        found += operators(token) if token and set(token) <= PUNCTUATION else [token]
    return found


def raw_sleeps(command: str) -> list[str]:
    """The long sleeps in a line whose quoting can't be read, found in its plain text."""
    found = []
    for argument in RAW_SLEEP.findall(without_heredoc_bodies(command)):
        seconds = sleep_seconds([argument])
        if seconds is not None and seconds > MAX_SLEEP_SECONDS:
            found.append(f"`sleep {argument}` waits {seconds:g} seconds in the foreground")
    return found


def waits(command: str, in_loop: bool = False) -> list[str]:
    """A reason for each foreground wait a command line holds, or none when it never waits in the foreground. A line
    whose quoting shlex can't read, such as a $(...) holding quotes inside a double-quoted word, which the shell
    reads fine, runs, unless its plain text holds a long sleep."""
    try:
        words = tokens(command)
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
    """The colony.toml the person merged: the copy on origin's branch, for the first of `branches` that has one, or
    None when none does, as in a clone with no origin."""
    for branch in dict.fromkeys(branches):
        try:
            run = subprocess.run(["git", "show", f"refs/remotes/origin/{branch}:.colony/colony.toml"], cwd=cwd or None,
                                 capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return None
        if run.returncode == 0:
            return run.stdout
    return None


def guarded_branches(cwd: str) -> tuple[list[str], list[str]]:
    """The protected branches, and the patterns of the branches the person allows merges and pushes into.

    Protected: the base in the working copy and in the committed copy, the repo's default branch, and both copies'
    [safety] protect. Allowed: each [safety] merge_into pattern that both the working copy and the committed copy
    name, or the working copy's alone when no committed copy exists."""
    text = colony_toml(cwd)
    base, default = project_base(text) or "main", default_branch(cwd)
    here = table(text, SAFETY)
    allowed, extra = strings(here, "merge_into") or [], strings(here, "protect") or []
    committed = committed_toml(cwd, [base, default])
    if committed is not None:
        there = table(committed, SAFETY)
        named = strings(there, "merge_into") or []
        allowed = [pattern for pattern in allowed if pattern in named]
        extra += [*(strings(there, "protect") or []), *filter(None, [project_base(committed)])]
    return list(dict.fromkeys([base, default, *extra])), allowed


def protected_branches(cwd: str) -> list[str]:
    """The branches no push may rewrite, and none may update without the person's yes: the base, the repo's default
    branch, and [safety] protect."""
    return guarded_branches(cwd)[0]


def permitted(branch: str, allowed: list[str]) -> bool:
    """Whether [safety] merge_into names this branch, as a name or a pattern such as release/*."""
    return any(fnmatch.fnmatchcase(branch, pattern) for pattern in allowed)


def long_options(word: str) -> set[str]:
    """The git push options a --word names: the one it spells out, else each one it is a prefix of. Git refuses a
    prefix of several, so reading it as each of them refuses nothing git would run."""
    name = word[2:].partition("=")[0]
    if name in PUSH_OPTIONS:
        return {name}
    if name.startswith("no-"):  # a negation takes no value, and forces or deletes nothing
        return set()
    return {option for option in PUSH_OPTIONS if option.startswith(name)}


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


def local_branches(cwd: str, branches: list[str]) -> list[str]:
    """The ones of these branches, or patterns, that this clone has as local branches."""
    found = []
    for branch in branches:
        try:
            run = subprocess.run(["git", "for-each-ref", "--count=1", "--format=%(refname)", f"refs/heads/{branch}"],
                                 cwd=cwd or None, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if run.returncode == 0 and run.stdout.strip():
            found.append(branch)
    return found


def config_key(key: str) -> str:
    """A config key the way git config prints it: the section and the name in lower case, a subsection as written."""
    section, _, rest = key.partition(".")
    subsection, dot, name = rest.rpartition(".")
    return f"{section.lower()}.{subsection}{dot}{name.lower()}"


def push_config(cwd: str, overrides: list[tuple[str, str | None]]) -> dict[str, list[str]] | None:
    """The settings in PUSH_CONFIG, each key's values in order, with the line's own -c values last, as git reads
    them. None when git can't say, or when a --config-env value, which the guard can't see, sets one of them."""
    try:
        run = subprocess.run(["git", "config", "-z", "--get-regexp", PUSH_CONFIG], cwd=cwd or None,
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if run.returncode not in (0, 1):  # 1: none of them is set
        return None
    found: dict[str, list[str]] = {}
    for entry in filter(None, run.stdout.split("\0")):
        key, newline, value = entry.partition("\n")
        found.setdefault(key, []).append(value if newline else "true")  # a key with no value is true
    for key, value in overrides:
        key = config_key(key)
        if re.match(PUSH_CONFIG, key):
            if value is None:
                return None
            found.setdefault(key, []).append(value)
    return found


def default_refspecs(config: dict[str, list[str]], remote: str, branch: str) -> tuple[list[str], str] | None:
    """The refspecs a push with none of its own pushes to this remote from this branch ("" when none is checked
    out), and the setting they come from: remote.<remote>.push, else push.default. None when git can't say."""
    if specs := config.get(f"remote.{remote}.push"):
        return specs, f"remote.{remote}.push"
    mode = (config.get("push.default") or ["simple"])[-1]
    upstream = (config.get(f"branch.{branch}.merge") or [""])[-1]
    if mode == "nothing":
        return [], ""
    if mode == "matching":
        return [":"], "push.default=matching"
    if mode in ("simple", "current") and branch:  # simple pushes to an upstream only of the same name
        return [branch], ""
    if mode in ("upstream", "tracking") and branch and upstream:
        return [f"{branch}:{upstream}"], f"push.default={mode}"
    return None


def refspec_target(spec: str, force: bool, delete: bool, prune: bool) -> tuple[str, str]:
    """The branch or pattern a refspec updates on the remote, and how it rewrites it: "deletes", "force-pushes",
    "can delete", or "" when it does neither."""
    plus, spec = spec.startswith("+"), spec.lstrip("+")
    source, colon, destination = spec.partition(":")
    if spec == ":":  # every branch both sides have, as push.default=matching pushes
        source = destination = "refs/heads/*"
    target = destination if colon else source
    how = ("deletes" if delete or (colon and not source) else "force-pushes" if force or plus
           else "can delete" if prune and "*" in target else "")  # --prune deletes only through a pattern
    return target, how


REWRITE, UPDATE = "rewrite", "update"  # what push_rewrites found: a forced or deleting push, or a plain one


def push_rewrites(arguments: list[str], protected: list[str], cwd: str,
                  overrides: list[tuple[str, str | None]] | None = None, changed: str = "",
                  allowed: list[str] | None = None, created: str = "") -> tuple[str, str]:
    """Why a `git push` with these arguments, the words after `push`, rewrites, deletes or updates a protected branch:
    (REWRITE, why) when it force-pushes or deletes one, (UPDATE, why) when a plain push updates one that `allowed`,
    [safety] merge_into, doesn't name, else ("", ""). overrides are the line's -c settings before `push`, and None
    for a --config-env one, whose value can't be seen. changed names what on the line can change the branch checked
    out or git config before this push runs, and created the branch a `git checkout -b` on the line made and checked
    out when that was all it changed, which HEAD then names. A dry run updates nothing."""
    force = delete = everything = mirror = prune = tags = repo = dry = False
    positional: list[str] = []
    remote, value_of, options_end = "", "", False  # value_of: the option the next word is the value of
    for word in arguments:
        if value_of:
            remote, value_of = word if value_of == "repo" else remote, ""
        elif options_end or not word.startswith("-") or word == "-":
            positional.append(word)
        elif word == "--":
            options_end = True
        elif word.startswith("--"):
            named = long_options(word)
            force = force or bool(named & {"force", "force-with-lease"})
            delete, mirror, prune = delete or "delete" in named, mirror or "mirror" in named, prune or "prune" in named
            everything, repo = everything or bool(named & {"all", "branches"}), repo or "repo" in named
            tags = tags or named == {"tags"}  # tags alone pass, so only a word that can mean nothing else counts
            dry = dry or named == {"dry-run"}
            if "=" in word:
                remote = word.partition("=")[2] if named == {"repo"} else remote
            elif named and named <= PUSH_VALUE_OPTIONS:
                value_of = "repo" if named == {"repo"} else "other"
        else:
            letters, option, value = word[1:].partition("o")  # -o takes the rest as its value, as in -odeploy
            force, delete, dry = force or "f" in letters, delete or "d" in letters, dry or "n" in letters
            value_of = "push-option" if option and not value else ""
    if mirror:
        return REWRITE, "`git push --mirror` overwrites every branch on the remote"
    if force and everything:
        return REWRITE, f"a force push of every branch rewrites {' and '.join(protected)}"
    if prune and everything:
        return REWRITE, f"`--prune` with every branch deletes {' or '.join(protected)} where no local branch has its name"
    # The protected branches a plain push may not update: none in a dry run, which pushes nothing.
    guarded = [] if dry else [branch for branch in protected if not permitted(branch, allowed or [])]
    if everything and (held := local_branches(cwd, guarded)):
        return UPDATE, f"`git push --all` pushes every local branch, {' and '.join(held)} among them"
    # Git takes the first word as the repository even with --repo, which names only a default. With --repo the
    # guard reads that word as a refspec too, so a push is refused when either reading reaches a protected branch.
    refspecs = [(spec, "") for spec in positional[1:] + (positional[:1] if repo else [])]
    if len(positional) <= 1 and not tags and not everything:
        # No refspec: git pushes what remote.<name>.mirror, remote.<name>.push or push.default says, with --tags only
        # tags, and with --all every branch. When the guard can't tell what that is, a plain push passes, and any
        # other is refused.
        how = "deletes" if delete else "force-pushes" if force else "can delete" if prune else ""
        if changed and how:
            return REWRITE, f"this push names no refspec, and {changed} on this line can change which branches it {how}"
        if changed and guarded:
            return UPDATE, f"this push names no refspec, and {changed} on this line can change which branch it updates"
        config = None if changed else push_config(cwd, overrides or [])
        found = None
        if config is not None:
            branch = current_branch(cwd)
            setting = lambda key: (config.get(key) or [""])[-1]  # noqa: E731
            remote = (positional[0] if positional else remote) or setting(f"branch.{branch}.pushremote") or \
                setting("remote.pushdefault") or setting(f"branch.{branch}.remote") or "origin"
            if setting(f"remote.{remote}.mirror").lower() not in FALSE:
                return REWRITE, f"remote.{remote}.mirror makes this push a `--mirror` push, which overwrites every branch"
            found = default_refspecs(config, remote, branch)
        if found is None and how:
            return REWRITE, f"this push names no refspec, and git config can't say which branches it {how}"
        refspecs += [(spec, found[1]) for spec in found[0]] if found else []
    for spec, via in refspecs:
        target, how = refspec_target(spec, force, delete, prune)
        if target in ("HEAD", "@") and (how or guarded):  # @ is git's short name for HEAD
            if created:
                target = created
            elif changed:
                return (REWRITE if how else UPDATE), (f"this push {how or 'updates'} HEAD, and {changed} on this line "
                                                      "can change which branch that is")
            else:
                target = current_branch(cwd)
        through = f", through {via}" if via else ""
        if how and (branch := reached(target, protected)):
            return REWRITE, f"this push {how} {branch}{through}"
        if not how and target and (branch := reached(target, guarded)):
            return UPDATE, f"this push updates {branch}{through}"
    return "", ""


def new_branch(command: str, arguments: list[str]) -> str:
    """The branch a `git checkout -b` or `git switch -c` makes and checks out, or "" for any other checkout."""
    options = ("-b", "-B", "--orphan") if command == "checkout" else ("-c", "-C", "--create", "--force-create",
                                                                       "--orphan")
    for index, word in enumerate(arguments):
        if word in options and index + 1 < len(arguments):
            return arguments[index + 1]
        name, equals, value = word.partition("=")
        if equals and name in options:
            return value
    return ""


def moved_to(arguments: list[str], cwd: str, grouped: bool) -> str:
    """The folder a `cd` or `pushd` with these arguments moves to, when the guard can tell for sure: one plain word
    that names a folder, on a line with no subshell or substitution, whose `cd` could end inside it. Else ""."""
    words = [word for word in arguments if word != "--"]
    if grouped or len(words) != 1 or words[0] == "-" or any(mark in words[0] for mark in "$`*?[{"):
        return ""
    folder = os.path.join(cwd, os.path.expanduser(words[0]))
    return folder if os.path.isdir(folder) else ""


def pushes(command: str, cwd: str) -> tuple[list[str], list[str]]:
    """A reason for each `git push` in the command line that force-pushes or deletes a protected branch, and one for
    each that updates a protected branch the person hasn't allowed (push_rewrites). A line whose quoting can't be read
    is refused whenever its text holds `git` and `push` anywhere: the guard can't tell what such a push does, and
    quotes can hide a force flag from any plain-text search. A `cd` into a folder the guard can name moves where the
    rest of the line's pushes run."""
    try:
        line = tokens(command)
    except ValueError:
        if RAW_GIT.search(command) and "push" in command:
            return ["this line's quoting could not be read and it holds a git push, so run the push as a command "
                    "of its own"], []
        return [], []
    rewrites: list[str] = []
    updates: list[str] = []
    words: list[str] = []
    changed = ""  # the first command on the line that can change what a later push reads, such as `git checkout`
    created = ""  # the branch a `git checkout -b` made, while that is the line's only change
    where, grouped = cwd, "(" in line  # the folder the next command runs in, and whether the line holds a subshell
    for token in [*line, ";"]:
        if token and set(token) <= set(";&|(){}<>"):
            program = program_words(words)
            before = words[:len(words) - len(program)]  # assignments and wrappers, such as env GIT_DIR=x
            variables = [word.partition("=")[0] for word in before if GIT_VARIABLE.match(word)]
            words = []
            name = PurePath(program[0]).name if program else ""
            if name != "git":
                if name in ("cd", "pushd") and not variables and (folder := moved_to(program[1:], where, grouped)):
                    where = folder
                    created = ""  # a branch made before the move is another folder's
                elif name in LINE_CHANGES or (not program and variables) or (
                        name in ("export", "unset") and any(GIT_VARIABLE.match(word) for word in program[1:])):
                    changed, created = changed or f"`{name or variables[0]}`", ""
                continue
            index, here, overrides = 1, where, []
            own = f"`{variables[0]}`" if variables else ""  # a variable set for this command alone
            if any(word in ("-C", "--chdir") or word.startswith("--chdir=") for word in before):
                own = own or "`env --chdir`"  # env runs the command in another folder
            while index < len(program) and program[index].startswith("-"):
                option, value = program[index], program[index + 1] if index + 1 < len(program) else ""
                if option == "-C" and value:
                    here = os.path.join(where, value)
                elif option == "-c":
                    key, equals, setting = value.partition("=")
                    overrides.append((key, setting if equals else "true"))  # -c <key> alone sets it to true
                elif option.startswith("--config-env"):  # --config-env=<key>=<variable>, or the pair as the value
                    overrides.append(((option.partition("=")[2] or value).rpartition("=")[0], None))
                elif option.partition("=")[0] in ("--git-dir", "--work-tree"):
                    own = own or f"`{option.partition('=')[0]}`"
                index += 2 if option in GIT_VALUE_OPTIONS else 1
            command = program[index] if index < len(program) else ""
            if command == "push":
                protected, allowed = guarded_branches(here)
                kind, reason = push_rewrites(program[index + 1:], protected, here, overrides, changed or own, allowed,
                                             "" if own else created)
                if kind == REWRITE:
                    rewrites.append(reason)
                elif kind == UPDATE:
                    updates.append(reason)
            elif command in LINE_CHANGES_GIT:
                made = new_branch(command, program[index + 1:]) if command in ("checkout", "switch") else ""
                created = made if made and not changed and here == where else ""
                changed = changed or f"`git {command}`"
        else:
            words.append(token)
    return rewrites, updates


def simple_commands(line: list[str]) -> list[list[str]]:
    """A line's simple commands, each as its words, split at its separators, pipes and groups. A redirection's file,
    and a descriptor number before it, as in 2>/dev/null, are left out, and so are the braces of a group."""
    found: list[list[str]] = []
    words: list[str] = []
    skip = False
    for token in line:
        if skip:
            skip = False
        elif token in REDIRECTIONS:
            skip = True
            if words and words[-1].isdigit():
                words.pop()
        elif token and set(token) <= PUNCTUATION:
            if words:
                found.append(words)
            words = []
        elif token not in ("{", "}"):
            words.append(token)
    return [*found, words] if words else found


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


# The merge guard


def pr_base(target: str, repo: str, cwd: str) -> str:
    """The branch a pull request merges into, from `gh pr view`, or "" when gh can't say. `target` is its number, URL
    or branch, "" for the branch checked out, and `repo` the --repo given, if any."""
    argv = ["gh", "pr", "view", *([target] if target else []), *(["--repo", repo] if repo else []),
            "--json", "baseRefName", "--jq", ".baseRefName"]
    try:
        run = subprocess.run(argv, cwd=cwd or None, capture_output=True, text=True, timeout=GH_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ""
    return run.stdout.strip() if run.returncode == 0 else ""


def pr_merge(arguments: list[str], repo: str, cwd: str, allowed: list[str]) -> str:
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
    if not allowed:
        return "`gh pr merge` merges a pull request, and [safety] merge_into allows no branch"
    base = pr_base(target, repo, cwd)
    if not base:
        return "`gh pr view` could not say which branch this pull request merges into"
    if permitted(base, allowed):
        return ""
    return f"this pull request merges into {base}, which [safety] merge_into doesn't name"


def api_merge(arguments: list[str]) -> str:
    """Why a `gh api` call with these arguments, the words after `api`, merges through the API, or ""."""
    method, path, values, option = "", "", [], ""
    for word in arguments:
        if option:
            method = word.upper() if option in ("-X", "--method") else method
            values += [word] if option in GH_API_FIELDS else []
            option = ""
        elif word in GH_API_VALUE_OPTIONS:
            option = word
        elif word.startswith("--method="):
            method = word.partition("=")[2].upper()
        elif word.startswith("-X"):
            method = word[2:].upper()
        elif word.startswith(("--field=", "--raw-field=", "--input=")):
            values.append(word.partition("=")[2])
        elif word.startswith(("-f", "-F")) and len(word) > 2:
            values.append(word[2:])
        elif not word.startswith("-") and not path:
            path = word.strip("/")
    path = path.partition("?")[0]
    if re.search(r"(?:^|/)pulls/[^/]+/merge$", path) and method == "PUT":
        return "`gh api` merges a pull request, which only `gh pr merge` may do, so the guard can check its base"
    if re.search(r"(?:^|/)merges$", path) and (method == "POST" or (not method and values)):
        return "`gh api` merges a branch, which only `gh pr merge` may do, so the guard can check its base"
    if path == "graphql" and any(GRAPHQL_MERGE.search(value) for value in values):
        return "`gh api graphql` merges a pull request, which only `gh pr merge` may do, so the guard can check its base"
    return ""


def gh_merges(command: str, cwd: str) -> list[str]:
    """A reason for each `gh` call on the line that merges a pull request into a branch [safety] merge_into doesn't
    name, or merges through the API. A line whose quoting can't be read is refused whenever it holds gh and merge."""
    try:
        line = tokens(command)
    except ValueError:
        if re.search(r"(?<![\w.-])gh(?![\w-])", command) and "merge" in command.lower():
            return ["this line's quoting could not be read and it holds a gh merge, so run the merge as a command of "
                    "its own"]
        return []
    found = []
    for words in simple_commands(line):
        program = run_program(words)
        if not program or PurePath(program[0]).name not in ("gh", "gh.exe"):
            continue
        arguments = program[1:]
        repo = next((value for flag, value in zip(arguments, arguments[1:]) if flag in GH_REPO_FLAGS), "") or next(
            (word.partition("=")[2] for word in arguments if word.startswith("--repo=")), "")
        rest = without_repo_flag(arguments)
        if rest[:2] == ["pr", "merge"] and "--disable-auto" not in rest:
            found.append(pr_merge(rest[2:], repo, cwd, guarded_branches(cwd)[1]))
        elif rest[:1] == ["api"]:
            found.append(api_merge(rest[1:]))
    return [reason for reason in found if reason]


def this_repo(cwd: str) -> str:
    """This repo's owner/name in lower case: [project] repo, else origin's URL, else ""."""
    text = colony_toml(cwd)
    project = re.split(r"^\s*\[(?!project\])", text.split("[project]", 1)[-1], maxsplit=1, flags=re.M)[0]
    if found := REPO.search(project):
        return found[1].lower()
    try:
        run = subprocess.run(["git", "remote", "get-url", "origin"], cwd=cwd or None, capture_output=True, text=True,
                             timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    found = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", run.stdout.strip()) if run.returncode == 0 else None
    return found[1].lower() if found else ""


def tool_merges(tool: str, tool_input: dict, cwd: str) -> list[str]:
    """Why a GitHub tool's call, such as mcp__github__merge_pull_request, merges a pull request into a branch the
    person hasn't allowed, or commits straight onto a protected branch of this repo."""
    action = tool.rsplit("__", 1)[-1]
    if action in MCP_PR_MERGES:
        allowed = guarded_branches(cwd)[1]
        if not allowed:
            return [f"`{action}` merges a pull request, and [safety] merge_into allows no branch"]
        number = next((str(tool_input[key]) for key in ("pullNumber", "pull_number", "number", "pr_number")
                       if tool_input.get(key)), "")
        owner, name = tool_input.get("owner"), tool_input.get("repo")
        base = pr_base(number, f"{owner}/{name}" if owner and name else "", cwd) if number else ""
        if not base:
            return [f"`gh pr view` could not say which branch pull request {number or 'this'} merges into"]
        return [] if permitted(base, allowed) else [
            f"pull request {number} merges into {base}, which [safety] merge_into doesn't name"]
    if action in MCP_COMMITS:
        owner, name, branch = tool_input.get("owner"), tool_input.get("repo"), str(tool_input.get("branch") or "")
        mine = this_repo(cwd)
        if not branch or (mine and owner and name and f"{owner}/{name}".lower() != mine):
            return []
        protected, allowed = guarded_branches(cwd)
        hit = reached(branch, [b for b in protected if not permitted(b, allowed)])
        return [f"`{action}` commits straight onto {hit}"] if hit else []
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
    searching = bool(SEARCHES.search(without_heredoc_bodies(command)))
    found = [reason for words in simple_commands(line) for reason in command_kills(run_program(words), searching)]
    return list(dict.fromkeys(found))


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
    refusals, merged = [], []
    if "push" in command:
        rewrites, merged = pushes(command, cwd)
        if rewrites:
            branches = protected_branches(cwd)
            refusals.append(PUSH_REFUSAL.format(reason="; ".join(dict.fromkeys(rewrites)),
                                                branches=" and ".join(branches),
                                                them="them" if len(branches) > 1 else "it"))
    if "merge" in command.lower():
        merged += gh_merges(command, cwd)
    if merged:
        refusals.append(MERGE_REFUSAL.format(reason="; ".join(dict.fromkeys(merged))))
    lowered = command.lower()
    if any(word in lowered for word in ("kill", "fuser", "stop-process", "spps")):
        killed = kills(command)
        if killed:
            refusals.append(KILL_REFUSAL.format(reason="; ".join(killed)))
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
