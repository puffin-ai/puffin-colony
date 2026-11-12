#!/usr/bin/env python3
"""Puffin Colony's wait guard: refuse a Bash call that waits in the foreground, so a session never blocks on a poll.

Claude Code runs it before each Bash call, with the call as JSON on stdin. Exit code 2 refuses the call, and stderr
names the way to wait instead: run_in_background, or `colony wait`. `colony hooks install` copies this file into a
repo's .colony/hooks/ and adds it to .claude/settings.json. Standard library only, and it imports nothing of Colony's,
so it runs with any python3.

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
rewrites the base too; when git config can't say, such a push is refused. A plain push that names no refspec is
refused only when git config forces, deletes or mirrors a protected branch through it. The guard reads git config
before the line runs, so after a command on the same line that can change it or the branch checked out, such as `git
checkout` or `cd`, a forced push names its branch. `@` is HEAD, the branch checked out. A force push rewrites the
branch every teammate builds on, and makes each of them rebase. A plain push, and a forced push of tags alone, pass.
A line whose quoting it can't read is refused whenever it holds `git` and `push`: run such a push on its own.
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


def base_branch(cwd: str) -> str:
    """[project] base from the repo's .colony/colony.toml, else main."""
    places = [os.environ.get("CLAUDE_PROJECT_DIR", ""), cwd, str(Path(__file__).resolve().parents[2])]
    for place in places:
        path = Path(place) / ".colony" / "colony.toml" if place else None
        if path is None or not path.is_file():
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        project = re.split(r"^\s*\[(?!project\])", text.split("[project]", 1)[-1], maxsplit=1, flags=re.M)[0]
        found = BASE.search(project)
        return found[1] if found else "main"
    return "main"


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


def protected_branches(cwd: str) -> list[str]:
    """The branches no push may rewrite: the base, and the repo's default branch when it is another one."""
    return list(dict.fromkeys([base_branch(cwd), default_branch(cwd)]))


def long_options(word: str) -> set[str]:
    """The git push options a --word names: the one it spells out, else each one it is a prefix of. Git refuses a
    prefix of several, so reading it as each of them refuses nothing git would run."""
    name = word[2:].partition("=")[0]
    if name in PUSH_OPTIONS:
        return {name}
    if name.startswith("no-"):  # a negation takes no value, and forces or deletes nothing
        return set()
    return {option for option in PUSH_OPTIONS if option.startswith(name)}


def reached(target: str, protected: list[str]) -> str:
    """The protected branch a refspec's destination names, or matches when it is a pattern such as refs/heads/*, or
    "". Git reads a destination such as heads/main as refs/heads/main, and its * matches across slashes, as fnmatch's
    does."""
    for branch in protected:
        if any(fnmatch.fnmatchcase(name, target) for name in (branch, f"heads/{branch}", f"refs/heads/{branch}")):
            return branch
    return ""


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


def push_rewrites(arguments: list[str], protected: list[str], cwd: str,
                  overrides: list[tuple[str, str | None]] | None = None, changed: str = "") -> str:
    """Why a `git push` with these arguments, the words after `push`, rewrites or deletes a protected branch, or "".
    overrides are the line's -c settings before `push`, and None for a --config-env one, whose value can't be seen.
    changed names what on the line can change the branch checked out or git config before this push runs."""
    force = delete = everything = mirror = prune = tags = repo = False
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
            if "=" in word:
                remote = word.partition("=")[2] if named == {"repo"} else remote
            elif named and named <= PUSH_VALUE_OPTIONS:
                value_of = "repo" if named == {"repo"} else "other"
        else:
            letters, option, value = word[1:].partition("o")  # -o takes the rest as its value, as in -odeploy
            force, delete = force or "f" in letters, delete or "d" in letters
            value_of = "push-option" if option and not value else ""
    if mirror:
        return "`git push --mirror` overwrites every branch on the remote"
    if force and everything:
        return f"a force push of every branch rewrites {' and '.join(protected)}"
    if prune and everything:
        return f"`--prune` with every branch deletes {' or '.join(protected)} where no local branch has its name"
    # Git takes the first word as the repository even with --repo, which names only a default. With --repo the
    # guard reads that word as a refspec too, so a push is refused when either reading reaches a protected branch.
    refspecs = [(spec, "") for spec in positional[1:] + (positional[:1] if repo else [])]
    if len(positional) <= 1 and not tags:
        # No refspec: git pushes what remote.<name>.mirror, remote.<name>.push or push.default says, and with --tags
        # only tags. When the guard can't tell what that is, a plain push passes, and any other is refused.
        how = "deletes" if delete else "force-pushes" if force else "can delete" if prune else ""
        if changed and how:
            return f"this push names no refspec, and {changed} on this line can change which branches it {how}"
        config = None if changed else push_config(cwd, overrides or [])
        found = None
        if config is not None:
            branch = current_branch(cwd)
            setting = lambda key: (config.get(key) or [""])[-1]  # noqa: E731
            remote = (positional[0] if positional else remote) or setting(f"branch.{branch}.pushremote") or \
                setting("remote.pushdefault") or setting(f"branch.{branch}.remote") or "origin"
            if setting(f"remote.{remote}.mirror").lower() not in FALSE:
                return f"remote.{remote}.mirror makes this push a `--mirror` push, which overwrites every branch"
            found = default_refspecs(config, remote, branch)
        if found is None and how:
            return f"this push names no refspec, and git config can't say which branches it {how}"
        refspecs += [(spec, found[1]) for spec in found[0]] if found else []
    for spec, via in refspecs:
        target, how = refspec_target(spec, force, delete, prune)
        if how and target in ("HEAD", "@"):  # @ is git's short name for HEAD
            if changed:
                return f"this push {how} HEAD, and {changed} on this line can change which branch that is"
            target = current_branch(cwd)
        branch = reached(target, protected) if how else ""
        if branch:
            return f"this push {how} {branch}" + (f", through {via}" if via else "")
    return ""


def pushes(command: str, cwd: str) -> list[str]:
    """A reason for each `git push` in the command line that force-pushes or deletes the base branch. A line whose
    quoting can't be read is refused whenever its text holds `git` and `push` anywhere: the guard can't tell what
    such a push does, and quotes can hide a force flag from any plain-text search."""
    try:
        line = tokens(command)
    except ValueError:
        if RAW_GIT.search(command) and "push" in command:
            return ["this line's quoting could not be read and it holds a git push, so run the push as a command "
                    "of its own"]
        return []
    found, words = [], []
    changed = ""  # the first command on the line that can change what a later push reads, such as `git checkout`
    for token in [*line, ";"]:
        if token and set(token) <= set(";&|(){}<>"):
            program = program_words(words)
            before = words[:len(words) - len(program)]  # assignments and wrappers, such as env GIT_DIR=x
            variables = [word.partition("=")[0] for word in before if GIT_VARIABLE.match(word)]
            words = []
            name = PurePath(program[0]).name if program else ""
            if name != "git":
                if name in LINE_CHANGES or (not program and variables) or (
                        name in ("export", "unset") and any(GIT_VARIABLE.match(word) for word in program[1:])):
                    changed = changed or f"`{name or variables[0]}`"
                continue
            index, here, overrides = 1, cwd, []
            own = f"`{variables[0]}`" if variables else ""  # a variable set for this command alone
            if any(word in ("-C", "--chdir") or word.startswith("--chdir=") for word in before):
                own = own or "`env --chdir`"  # env runs the command in another folder
            while index < len(program) and program[index].startswith("-"):
                option, value = program[index], program[index + 1] if index + 1 < len(program) else ""
                if option == "-C" and value:
                    here = os.path.join(cwd, value)
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
                reason = push_rewrites(program[index + 1:], protected_branches(here), here, overrides, changed or own)
                if reason:
                    found.append(reason)
            elif command in LINE_CHANGES_GIT:
                changed = changed or f"`git {command}`"
        else:
            words.append(token)
    return found


def main() -> int:
    """Read the hook's call from stdin: exit 2 with the reasons for a foreground wait or a push that rewrites the
    base, else 0."""
    try:
        call = json.load(sys.stdin)
        tool_input = call["tool_input"]
        command = tool_input["command"]
        if not isinstance(command, str):
            raise TypeError("the command is not text")
    except (ValueError, KeyError, TypeError):
        return 0  # a call the guard can't read runs, and Claude Code's own checks still apply to it
    if "push" in command:
        cwd = str(call.get("cwd") or os.getcwd())
        rewrites = pushes(command, cwd)
        if rewrites:
            branches = protected_branches(cwd)
            sys.stderr.write(PUSH_REFUSAL.format(reason="; ".join(dict.fromkeys(rewrites)),
                                                 branches=" and ".join(branches),
                                                 them="them" if len(branches) > 1 else "it") + "\n")
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
