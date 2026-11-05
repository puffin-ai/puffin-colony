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
passes. It drops here-document bodies first, because a body is text a command reads, not a command.
"""
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import PurePath

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
LIST_SEPARATORS = {";", "&&", "||", ";;"}
PIPES = {"|", "|&"}
BACKGROUND = "&"
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


def waits(command: str, in_loop: bool = False) -> list[str]:
    """A reason for each foreground wait a command line holds, or none when it never waits in the foreground."""
    lexer = shlex.shlex(without_heredoc_bodies(command).replace("\n", ";"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as error:
        return [f"the command's quoting could not be read ({error})"]
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
    for token in tokens:
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


def main() -> int:
    """Read the hook's call from stdin: exit 2 with the reasons for a foreground wait, else 0."""
    try:
        tool_input = json.load(sys.stdin)["tool_input"]
        command = tool_input["command"]
        if not isinstance(command, str):
            raise TypeError("the command is not text")
    except (ValueError, KeyError, TypeError):
        return 0  # a call the guard can't read runs, and Claude Code's own checks still apply to it
    if tool_input.get("run_in_background") is True:
        return 0
    found = waits(command)
    if not found:
        return 0
    sys.stderr.write(REFUSAL.format(reason="; ".join(dict.fromkeys(found))) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
