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
can't say): `--force`, `-f`, `--force-with-lease`, `--mirror`, a `+` refspec or a deletion. A force push rewrites the
branch every teammate builds on, and makes each of them rebase. A plain push, and a forced push of tags alone, pass.
"""
from __future__ import annotations

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
LIST_SEPARATORS = {";", "&&", "||", ";;"}
PIPES = {"|", "|&"}
BACKGROUND = "&"
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}  # git's, before `push`
PUSH_VALUE_OPTIONS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
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


def push_rewrites(arguments: list[str], protected: list[str], cwd: str) -> str:
    """Why a `git push` with these arguments, the words after `push`, rewrites or deletes a protected branch, or ""."""
    force = delete = everything = mirror = tags = False
    positional: list[str] = []
    skip = False
    for word in arguments:
        if skip:
            skip = False
        elif word in PUSH_VALUE_OPTIONS:
            skip = True
        elif word == "--force" or word.startswith("--force-with-lease"):
            force = True
        elif word == "--mirror":
            mirror = True
        elif word == "--delete":
            delete = True
        elif word in ("--all", "--branches"):
            everything = True
        elif word == "--tags":
            tags = True
        elif word.startswith("--"):
            continue
        elif word.startswith("-") and len(word) > 1:
            letters, option, value = word[1:].partition("o")  # -o takes the rest as its value, as in -odeploy
            force, delete, skip = force or "f" in letters, delete or "d" in letters, bool(option and not value)
        else:
            positional.append(word)
    if mirror:
        return "`git push --mirror` overwrites every branch on the remote"
    if force and everything:
        return f"a force push of every branch rewrites {' and '.join(protected)}"
    targets = []  # (the branch a refspec updates, how it rewrites it, or "")
    for spec in positional[1:]:
        plus, spec = spec.startswith("+"), spec.lstrip("+")
        source, colon, destination = spec.partition(":")
        deletes = delete or bool(colon and not source)
        how = "deletes" if deletes else "force-pushes" if force or plus else ""
        targets.append((destination if colon else source, how))
    if len(positional) <= 1 and not tags:  # no refspec: git pushes the branch checked out, or with --tags only tags
        targets.append(("HEAD", "deletes" if delete else "force-pushes" if force else ""))
    for target, how in targets:
        if target == "HEAD":
            target = current_branch(cwd)
        if how and target.removeprefix("refs/heads/") in protected:
            return f"this push {how} {target.removeprefix('refs/heads/')}"
    return ""


def pushes(command: str, cwd: str) -> list[str]:
    """A reason for each `git push` in the command line that force-pushes or deletes the base branch."""
    try:
        line = tokens(command)
    except ValueError:
        return []
    found, words = [], []
    for token in [*line, ";"]:
        if token and set(token) <= set(";&|(){}<>"):
            program = program_words(words)
            words = []
            if not program or PurePath(program[0]).name != "git":
                continue
            index, here = 1, cwd
            while index < len(program) and program[index].startswith("-"):
                if program[index] == "-C" and index + 1 < len(program):
                    here = os.path.join(cwd, program[index + 1])
                index += 2 if program[index] in GIT_VALUE_OPTIONS else 1
            if program[index:index + 1] == ["push"]:
                reason = push_rewrites(program[index + 1:], protected_branches(here), here)
                if reason:
                    found.append(reason)
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
