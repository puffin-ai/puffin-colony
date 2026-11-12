"""colony batch and colony status: take a batch of finished cards through checks, review, walk and fixes to one pull request.

The command line in cli.py calls `run_batch(config, args)` and `batch_status(config, args)` with the dict
`load_config` returns. The args read are `name`, `card` (a list of `N=BRANCH`), `from_branch` and `dry_run`, and the
optional `account`, `person`, `review` and `repo`. The account rules and the repository root come from cli.py. Each
batch's reports go to `.colony/reports/<batch>/` in its worktree, and land on the batch branch.

The mode's [gate] keys shape the gate: `check` is "full" ([project] checks) or "fast" ([project] fast_check alone,
hack mode's), `review` runs a fresh reviewer each round (`--review` adds it when false), and `walk` walks the changed
screens. Startup and solo run the full checks and the reviewer, and solo walks only when `walk` is true; hack runs the
fast check alone. `[gate] paid_checks`, a command whose model calls cost money, runs once in the round that otherwise
passes, only while `[budget] provider_dollars` is above 0 (paid_checks). `colony batch --fast` runs the full checks
once, with no reviewer, walk or fixers, and opens the pull request when they pass, with `gate: fast` in its body.

Fast batches. With `[checks] areas`, a round runs only the areas its change touched, through `{areas}` in the check
command, and a round after a fix adds the areas that failed (round_areas). A failing test whose output names a timeout
or a time limit runs once more by itself with `[checks] rerun`, and counts only when it fails again (rerun_timeouts).
The walk runs only when the change touches `[gate] walk_paths`, and walks only the screens the changed files feed
(`[walk] screens`), with the browser `[walk] browser` names. minutes.md records the minutes each skip saved. A batch
runs at most MAX_ROUNDS rounds: after the last, each finding still open becomes a card the pull request lists, while
failing checks still stop it (carry_over). An agent that hits its account's rate limit, a 429 that lasts
RATE_LIMIT_GRACE seconds or a message that gives up on it, is stopped and its step runs again on the person's next
account with room (run_agent). Ctrl-C or SIGTERM stops every agent, check and rerun the batch has running, each in its
own process group, and ends the batch at once (stop_on_signal).

In hack mode, `colony batch --review --name <n>` with no `--card` reviews the demo build: one fresh reviewer reads
origin/<base> as it stands, beside the fast check, with no fixers, and one line on the board gives the open count and
the report's link (review_demo). Every batch that runs ends with `colony tidy` (tidy_at_end).
"""

from __future__ import annotations

import concurrent.futures as futures
import fnmatch
import json
import os
import queue
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from colony import cli, portable

REPORTS = f"{cli.DIR}/reports"  # each batch's reports folder, inside its worktree
RISKS_PLACE = "- the batch's risk list, from `colony tier` at each round's head"  # a dry run's stand-in
PROVIDER_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")
OPEN = re.compile(r"open:\s*(\d+)\b", re.I)
WALK = re.compile(r"walk:\s*(pass|fail)\b", re.I)
FINDING = re.compile(r"^\s*(?:[-*]|\d+[.)])?\s*`?(?P<path>[^\s`:]+):(?P<line>\d+)(?:[-–:]\d+)*`?\s*(?:—|–|--?)\s*(?P<text>\S.*)$")
FIXED = re.compile(r"^\W*fixed\b|\bfixed\W*$", re.I)
IMAGE = re.compile(r"\.(png|jpe?g|webp|gif)\b", re.I)
PYTEST_FAILED = re.compile(r"\b(?:FAILED|ERROR)\s+(\S+?\.py)::(\S+)")  # a failed test, or one that errored
PYTEST_ERROR = re.compile(r"\s*ERROR\s+[^\s:]+\.py(::|\s+-\s|\s*$)")  # a test that errored, such as in collection
JS_FAILED = re.compile(r"(?:\bFAIL\b|×|✗)\s+(\S+\.(?:test|spec)\.[cm]?[jt]sx?)(?:\s*>\s*(.+))?")
SPENT = re.compile(r"^\s*spent:\s*\$?(\d+(?:\.\d+)?)\s*$", re.I | re.M)  # a paid check's report of its dollars
MINUTE = re.compile(r"^(\d{1,2}:\d{2})\s+(\S+)\s+(\d+(?:\.\d+)?)(?:\s+\$(\d+(?:\.\d+)?))?")
SAVED = re.compile(r"^(\d{1,2}:\d{2})\s+saved\s+(\S+)\s+(\d+(?:\.\d+)?)(?:\s+\$(\d+(?:\.\d+)?))?")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's empty tree: a diff from it holds every file
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|e2e)/|(^|/)test_[^/]*\.py$|_test\.py$|\.(test|spec)\.[cm]?[jt]sx?$")
MAX_ROUNDS = 3  # the most rounds a batch runs; [gate] max_rounds may lower it
TIMING = re.compile(r"time\s?out|timed out|time limit|deadline exceeded", re.I)  # a failure the load may have caused
SECTION = re.compile(r"^\s*([=_-])\1{2,}(.*?)[=_-]*\s*$")  # a section header, such as `=== short test summary info ===`
DETAIL = re.compile(r"^\s*(E\s|→|\w*Error\b)")  # a failure's detail line: pytest's `E`, vitest's `→`, an `Error:`
# A sign of a failure that names no test: make's `*** [lint] Error 1`, a compiler's `error:` or `error TS2322`, npm's
# `npm ERR!`, or a Python traceback.
FAILURE_SIGNAL = re.compile(r"^\S*make(\[\d+\])?: \*\*\*|\berror(\[\w+\])?:|\berror TS\d+|\bError \d+\b|npm ERR!|"
                            r"Traceback \(most recent call last\)", re.I)
DURATION = re.compile(r"\d+(\.\d+)?m?s\b")  # a duration in a check's line, such as 3s or 120ms, which varies by run
RERUN_MAX = 10  # a run with more failing tests than this reruns none of them
RERUN_SECONDS = 600  # one test's rerun past this counts as failed again
RATE_LIMIT = re.compile(r"rate_limit_error|exceed your account's rate limit|\brate[ _]limit(ed)?\b", re.I)
# A Claude subscription's limit, as Claude Code words it at the start of its message: "You've hit your limit · resets
# 3pm", "Claude AI usage limit reached|<time>", "5-hour limit reached ∙ resets 3pm".
SUBSCRIPTION_LIMIT = re.compile(r"^\W*(you['’]ve hit your (\w+ )?limit\b|(claude (ai )?)?usage limit reached\b|"
                                r"[\w -]{0,30}\blimit reached\b.{0,80}\bresets?\b)", re.I)
RATE_LIMIT_GRACE = 300  # seconds an agent may wait on its account's rate limit before the step moves accounts
STALL_SECONDS = 1200  # an agent that prints nothing this long has hung, and its run ends as failed
BROWSERS = ("playwright", "agent-browser")  # [walk] browser


class Finding(NamedTuple):
    """One problem for a fixer: the file it is in (empty when unknown), its line (0 when unknown), what is wrong, and
    who found it (review, walk or checks; empty from the parsers, which gate fills in)."""

    path: str
    line: int
    text: str
    source: str = ""


class Stop(Exception):
    """A stop rule fired; the message says why."""


# Pure helpers


def fill(template: str, **values) -> str:
    """Replace each `{name}` in a prompt template with its value, raising KeyError for a placeholder with no value."""

    def value(match: re.Match) -> str:
        if match[1] not in values:
            raise KeyError(f"the template needs a value for {{{match[1]}}}")
        return str(values[match[1]])

    return re.sub(r"\{(\w+)\}", value, template)


def classify_conflict(paths, generated_globs) -> str:
    """Class a merge conflict as "generated" when every conflicted path matches a generated glob, else "other"."""
    paths = list(paths)
    if paths and all(any(fnmatch.fnmatchcase(p, g) for g in generated_globs) for p in paths):
        return "generated"
    return "other"


def _first_line(text: str) -> str:
    """Return a report's first non-blank line, without Markdown emphasis or heading marks around it."""
    return next((line.strip().strip("`*# ") for line in text.splitlines() if line.strip()), "")


def parse_open(text: str) -> int | None:
    """Read `open: N`, the confirmed problems still open, from a review report's first line, or None when it is not there."""
    match = OPEN.match(_first_line(text))
    return int(match[1]) if match else None


def parse_walk(text: str) -> str | None:
    """Read `walk: pass` or `walk: fail` from a walk report's first line, or None when it is not there."""
    match = WALK.match(_first_line(text))
    return match[1].lower() if match else None


def parse_findings(text: str) -> list[Finding]:
    """Read each `path:line — what is wrong — …` line of a review report, leaving out earlier findings marked fixed."""
    found, seen = [], set()
    for raw in text.splitlines():
        match = FINDING.match(raw)
        if not match:
            continue
        path, body = match["path"].strip("*"), match["text"].strip()
        if ("/" not in path and "." not in path) or FIXED.search(body) or (path, match["line"]) in seen:
            continue
        seen.add((path, match["line"]))
        found.append(Finding(path, int(match["line"]), body))
    return found


def parse_walk_failures(text: str) -> list[Finding]:
    """Read each `flow — what happened — screenshot — likely file` line of a walk report, using the likely file as the path."""
    found = []
    for raw in text.splitlines()[1:]:
        parts = [part.strip(" `*-") for part in re.split(r"\s+[—–]\s+", raw.strip())]
        if len(parts) < 3 or not any(IMAGE.search(part) for part in parts):
            continue
        place = re.fullmatch(r"([^\s:]+?)(?::(\d+))?", parts[-1])
        if place and not IMAGE.search(parts[-1]) and ("/" in place[1] or "." in place[1]):
            found.append(Finding(place[1], int(place[2] or 0), raw.strip()))
        else:
            found.append(Finding("", 0, raw.strip()))
    return found


def parse_check_failures(output: str) -> list[Finding]:
    """Read each failing test name from a check run's output, or one finding naming the failed checks when none parses."""
    found, seen = [], set()
    for raw in output.splitlines():
        if match := PYTEST_FAILED.search(raw):
            finding = Finding(match[1], 0, f"failing test {match[1]}::{match[2]}")
        elif match := JS_FAILED.search(raw):
            finding = Finding(match[1], 0, f"failing test {match[1]}" + (f" > {match[2].strip()}" if match[2] else ""))
        else:
            continue
        if finding.text not in seen:
            seen.add(finding.text)
            found.append(finding)
    if not found:
        fails = [line.strip() for line in output.splitlines() if line.startswith("FAIL")]
        last = [line.strip() for line in output.splitlines() if line.strip()][-1:]
        found.append(Finding("", 0, "checks failed: " + "; ".join(fails[:5] or last or ["no output"])))
    return found


def owner_of(path: str, card_branches, repo, base: str | None = None) -> str:
    """Name the card whose branch made the newest commit to path since base, falling back to the first card.

    base defaults to the point all the card branches share.
    """
    branches = dict(card_branches)
    cards = list(branches)
    if not path or len(cards) < 2:
        return cards[0]
    base = base or _git(repo, "merge-base", "--octopus", *branches.values(), check=False)
    best, newest = cards[0], -1
    for card, branch in branches.items():
        stamp = _git(repo, "log", "-1", "--format=%ct", f"{base}..{branch}", "--", path, check=False)
        if stamp.isdigit() and int(stamp) > newest:
            best, newest = card, int(stamp)
    return best


def fast_gate(config: dict) -> bool:
    """Whether the gate runs the fast check alone, `[gate] check = "fast"` (hack mode's), instead of the full checks."""
    return config["gate"]["check"] == "fast"


def fast_check(project: dict) -> str:
    """The fast check's command: [project] fast_check, else the full checks."""
    return project.get("fast_check") or project["checks"]


def provider_dollars(config: dict) -> float:
    """The dollars the app's own checks may spend on model calls, [budget] provider_dollars, 0 when unset."""
    return float(config.get("budget", {}).get("provider_dollars") or 0)


def trailer(config: dict) -> str:
    """The line every commit and pull request the runners make ends with: [project] trailer, else the fixer's
    Assisted-by line."""
    return config["project"].get("trailer") or f"Assisted-by: claude-code:{config['roles']['fixer']['model']}"


def main_checkout(root: Path) -> Path | None:
    """The repo's main checkout, which every worktree of it shares: the folder that holds its .git."""
    run = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True, text=True)
    if run.returncode or not run.stdout.strip():
        return None
    common = Path(run.stdout.strip())
    common = common if common.is_absolute() else (root / common).resolve()
    return common.parent if common.name == ".git" else None


def env_file(config: dict, root: Path) -> Path | None:
    """[project] check_env_file: an absolute path, else the file in `root`, else in the repo's main checkout, since
    a worktree, such as a helper's or the merge's, has no copy of an untracked file such as .env.local. None when
    the setting is empty; a ColonyError when no such file is found."""
    named = config["project"].get("check_env_file")
    if not named:
        return None
    path = Path(named).expanduser()
    main = main_checkout(root)
    places = [path] if path.is_absolute() else list(dict.fromkeys([root / path, *([main / path] if main else [])]))
    found = next((place for place in places if place.is_file()), None)
    if found is None:
        raise cli.ColonyError(f"[project] check_env_file names {named}, which is in neither "
                              f"{' nor '.join(str(place.parent) for place in places)}: put it there, or clear the "
                              "setting")
    return found


def checks_env(config: dict, root: Path) -> dict:
    """The environment for the checks: check_env_file's values (env_file) added, and provider keys dropped at a zero
    budget."""
    env = dict(os.environ)
    if (found := env_file(config, root)) is not None:
        for line in found.read_text().splitlines():
            key, sep, value = line.strip().removeprefix("export ").partition("=")
            if sep and key and not key.startswith("#"):
                env[key.strip()] = value.strip().strip("'\"")
    if not config.get("budget", {}).get("provider_dollars"):
        for key in PROVIDER_KEYS:
            env.pop(key, None)
    return env


def minutes_table(lines) -> str:
    """Sum `HH:MM step minutes [$cost]` lines per kind of step (the name before its first dash) into a Markdown table,
    then the `HH:MM saved step minutes [$cost]` lines the same way below the total, as what the skipped and narrowed
    steps saved."""
    if isinstance(lines, str):
        lines = lines.splitlines()
    rows: dict[str, list[float]] = {}
    saved: dict[str, list[float]] = {}
    for line in lines:
        match = SAVED.match(line.strip()) or MINUTE.match(line.strip())
        if match:
            row = (saved if match.re is SAVED else rows).setdefault(match[2].split("-")[0], [0, 0.0, 0.0])
            row[0] += 1
            row[1] += float(match[3])
            row[2] += float(match[4] or 0)
    table = ["| Step | Runs | Minutes | Cost |", "| --- | ---: | ---: | ---: |"]
    table += [f"| {kind} | {runs:.0f} | {mins:.1f} | ${cost:.2f} |" for kind, (runs, mins, cost) in rows.items()]
    totals = [sum(row[i] for row in rows.values()) for i in range(3)]
    table.append(f"| **total** | {totals[0]:.0f} | {totals[1]:.1f} | ${totals[2]:.2f} |")
    if saved:
        table += [f"| saved: {kind} | {runs:.0f} | {mins:.1f} | ${cost:.2f} |" for kind, (runs, mins, cost) in saved.items()]
        totals = [sum(row[i] for row in saved.values()) for i in range(3)]
        table.append(f"| **saved** | {totals[0]:.0f} | {totals[1]:.1f} | ${totals[2]:.2f} |")
    return "\n".join(table)


# Shelling out


def _run(cmd: list[str], cwd, check: bool = True, env=None) -> subprocess.CompletedProcess:
    """Run one command given as a list and capture its text output; raise Stop when check is set and it fails."""
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if check and proc.returncode:
        raise Stop(f"`{shlex.join(cmd[:3])}` failed: {(proc.stderr or proc.stdout).strip()[-600:]}")
    return proc


def _git(cwd, *args: str, check: bool = True) -> str:
    """Run one git command in cwd and return its stripped output."""
    return _run(["git", *args], cwd, check).stdout.strip()


def matches(path: str, patterns) -> bool:
    """Say whether a path matches any pattern: a glob when it holds `*`, `?` or `[`, else a path prefix."""
    return any(fnmatch.fnmatchcase(path, p) if any(c in p for c in "*?[") else path.startswith(p) for p in patterns)


def _touches(paths: list[str], patterns: list[str]) -> bool:
    """Say whether any path matches any of the patterns (matches)."""
    return any(matches(path, patterns) for path in paths)


def check_areas(config: dict) -> dict[str, list[str]]:
    """`[checks] areas`: each check area's name and the paths that are its, in the file's order; empty when unset."""
    return dict(config.get("checks", {}).get("areas") or {})


def areas_of(config: dict, paths) -> list[str]:
    """The check areas a change to `paths` touches, in `[checks] areas` order. A path under `[checks] skip` touches
    none, such as a docs page; a path no area names touches every area, so an unknown file never goes unchecked."""
    areas, skip, touched = check_areas(config), config.get("checks", {}).get("skip") or [], set()
    for path in paths:
        if matches(path, skip):
            continue
        mine = {name for name, patterns in areas.items() if matches(path, patterns)}
        touched |= mine or set(areas)
    return [name for name in areas if name in touched]


def check_command(config: dict, cmd: str, areas: list[str] | None) -> str:
    """The check command with `{areas}` filled in: `[checks] all` when every area runs and it is set, else the areas'
    names joined by spaces. A command without `{areas}`, or a batch with no areas (None), runs as it is."""
    if areas is None or "{areas}" not in cmd:
        return cmd
    every = config.get("checks", {}).get("all") or ""
    words = every if every and set(areas) == set(check_areas(config)) else " ".join(areas)
    return cmd.replace("{areas}", words)


def every_area(config: dict, cmd: str) -> str:
    """A check command run for every check area (check_command), as the demo review, a retro and hack mode's merge
    run it."""
    return check_command(config, cmd, list(check_areas(config)))


# A check's output that only says NOT RUN ran nothing: a NOT RUN line, and no line that reports a check that ran, such
# as a PASS or FAIL line, TAP's ok or not ok, or a test runner's `12 passed`.
NOT_RUN = re.compile(r"^\W*NOT RUN\b", re.M)
RAN = re.compile(r"^\W*(PASS|PASSED|FAIL|FAILED|ERROR|ok|not ok)\b|\b\d+ (passed|failed)\b", re.M)
NOT_RUN_EXIT = 2  # `colony fast-check`'s exit code when nothing was checked
ONLY_NOT_RUN = "its output only says NOT RUN: "  # starts the result line of a check run that checked nothing


def ran_nothing(output: str) -> bool:
    """Whether a check's output only says NOT RUN, so the check counts as not run even when it exited 0."""
    return bool(NOT_RUN.search(output)) and not RAN.search(output)


def branch_changes(root: Path, base: str) -> list[str]:
    """The files a branch changes against origin/<base>: its commits since it forked, its uncommitted edits and its
    new untracked files, as paths from the repo's top."""
    fork = _git(root, "merge-base", f"origin/{base}", "HEAD")
    changed = _git(root, "diff", "--name-only", fork).splitlines()
    changed += _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({path for path in changed if path})


def fast_check_command(config: dict, root: Path) -> tuple[str, list[str] | None]:
    """A builder's fast check, `[project] fast_check`, with `{areas}` filled from the areas its branch changes
    (areas_of), and those areas: [] when the change touches none, such as a docs-only card, and None when the command
    names no areas, so it runs as it is."""
    cmd = fast_check(config["project"])
    if "{areas}" not in cmd or not check_areas(config):
        return cmd, None
    areas = areas_of(config, branch_changes(root, config["project"]["base"]))
    return (check_command(config, cmd, areas) if areas else cmd), areas


def run_fast_check(config: dict, args) -> int:
    """`colony fast-check`: run a builder's fast check for the areas its branch changes, and end on one line for the
    done line: `fast check: passed …`, `fast check: failed …`, or `fast check: not run …` when the change touches no
    check area or the output only says NOT RUN (ran_nothing). It exits 0, 1, or NOT_RUN_EXIT."""
    root = cli.repo_root()
    cmd, areas = fast_check_command(config, root)
    named = f" for {' '.join(areas)}" if areas else ""
    if areas == []:
        print("fast check: not run, the change touches no check area")
        return NOT_RUN_EXIT
    print(f"$ {cmd}", flush=True)
    if args.dry_run:
        return 0
    command, shell, env = portable.shell(cmd, checks_env(config, root))
    proc = subprocess.Popen(command, shell=shell, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace")
    output = []
    for line in proc.stdout:
        sys.stdout.write(line)
        output.append(line)
    code = proc.wait()
    text = "".join(output)
    last = next((line.strip() for line in reversed(output) if line.strip()), "no output")
    if code:
        print(f"fast check: failed{named}, exit {code}: {last}")
        return 1
    if ran_nothing(text):
        print(f"fast check: not run{named}, {ONLY_NOT_RUN}{last}")
        return NOT_RUN_EXIT
    print(f"fast check: passed{named}: {last}")
    return 0


def test_id(finding: Finding) -> str:
    """The test a check finding names, as its output named it (`path::name` for pytest, the file for a JS runner), or
    an empty string for a finding that names no test."""
    text = finding.text.removeprefix("failing test ")
    return "" if text == finding.text else text.split(" > ")[0]


def indent(line: str) -> int:
    """How far a line is indented."""
    return len(line) - len(line.lstrip())


def failure_lines(output: str) -> tuple[list[str], dict[int, list[int]], list[str]]:
    """Read a check run's output: its lines; each line that names a failing test (parse_check_failures' patterns),
    with the detail lines under it; and the section header each line sits in, or "". A test's detail lines follow it,
    indented deeper or marked as details (DETAIL), up to a blank line, a section header or the next test line, such as
    pytest's `E   Failed: Timeout` or vitest's `→ Test timed out in 5000ms.`"""
    lines = output.splitlines()
    tests = [i for i, line in enumerate(lines) if PYTEST_FAILED.search(line) or JS_FAILED.search(line)]
    headers, header, depth = [], "", 0
    for line in lines:
        if section := SECTION.match(line):
            header, depth = section[2].strip(), indent(line)
        elif line.strip() and indent(line) < depth:
            header, depth = "", 0  # a line further out ends the section
        headers.append(header)
    blocks = {}
    for i in tests:
        block = []
        for j in range(i + 1, len(lines)):
            line = lines[j]
            if PYTEST_FAILED.search(line) or JS_FAILED.search(line) or not line.strip() or \
                    SECTION.match(line) or not (indent(line) > indent(lines[i]) or DETAIL.match(line)):
                break
            block.append(j)
        blocks[i] = block
    return lines, blocks, headers


def other_failures(output: str, tests: set[str]) -> list[str]:
    """The failures in a check run's output that none of `tests` explains: each top-level `FAIL <step>` line whose
    indented lines below it name none of them, each test runner `ERROR` line, and each failure signal outside the
    failing tests' own lines (FAILURE_SIGNAL), such as make's `*** [lint] Error 1`. Output that names no failing test
    and no `FAIL` step can't be accounted for, so it counts as a failure of its own."""
    lines, blocks, _ = failure_lines(output)
    own = {i for test, block in blocks.items() for i in (test, *block)}
    found, block, head = [], [], None

    def close() -> None:
        if head is not None and not any(test in line for line in [head, *block] for test in tests):
            found.append(head.strip())

    for i, line in enumerate(lines):
        if PYTEST_ERROR.match(line) and not any(test in line for test in tests):
            found.append(line.strip())
        elif i not in own and not line.startswith(("FAIL", "PASS")) and FAILURE_SIGNAL.search(line):
            found.append(line.strip())
        if line[:1].isspace() or not line.strip():
            block.append(line)
            continue
        close()
        head, block = (line, []) if line.startswith("FAIL") else (None, [])
    close()
    if not blocks and not any(line.startswith("FAIL") for line in lines):
        found.append("the output names no failing test or step")
    return list(dict.fromkeys(found))


def should_walk(settings: dict, rounds: list[dict], changed: list[str]) -> bool:
    """Say whether this round walks: when the last walk failed, or the change touches walk_paths.

    Once a walk has passed, a later round walks only when its change touches a screen file under walk_paths, one
    ending in a screen_suffixes entry (".tsx" and ".css" by default), so a fix that only moves code does not wait
    on a second walk of the same screens.
    """
    if not settings.get("walk"):
        return False
    if rounds and rounds[-1]["walk"] == "fail":
        return True
    paths = settings.get("walk_paths") or [""]
    if any(x["walk"] == "pass" for x in rounds):
        suffixes = tuple(settings.get("screen_suffixes") or (".tsx", ".css"))
        changed = [path for path in changed if path.endswith(suffixes)]
    return _touches(changed, paths)


def walk_browser(config: dict) -> str:
    """The walker's browser, `[walk] browser`: "playwright" (Playwright MCP, the default) or "agent-browser" (the
    agent-browser CLI)."""
    name = config.get("walk", {}).get("browser") or BROWSERS[0]
    if name not in BROWSERS:
        raise cli.ColonyError(f"[walk] browser is {' or '.join(map(repr, BROWSERS))}, not {name!r}")
    return name


def walk_screens(config: dict, changed: list[str]) -> tuple[list[str], list[str]]:
    """The screens a round's changed files feed, and the changed screen files no screen claims. A changed file is a
    screen file when it is under `[gate] walk_paths` (every file when that is empty); `[walk] screens` maps each
    screen to the paths that feed it."""
    paths = config["gate"].get("walk_paths") or [""]
    screens = dict(config.get("walk", {}).get("screens") or {})
    files = [path for path in changed if matches(path, paths)]
    fed = [name for name, patterns in screens.items() if any(matches(path, patterns) for path in files)]
    loose = [path for path in files if not any(matches(path, patterns) for patterns in screens.values())]
    return fed, loose


def screens_text(config: dict, changed: list[str]) -> str:
    """The walker prompt's line on what to walk: the screens the changed files feed (walk_screens), and the changed
    files no screen claims, for the walker to trace to their screens. Every other screen stays unwalked."""
    fed, loose = walk_screens(config, changed)
    lines = []
    if fed:
        lines.append("Walk only these screens, which this round's changed files feed: " + ", ".join(fed) + ".")
    if loose:
        shown = ", ".join(f"`{path}`" for path in loose[:30]) + (f" and {len(loose) - 30} more" if len(loose) > 30 else "")
        lines.append(("Also walk" if fed else "Walk only") + " the screens that use these changed files: " + shown + ".")
    if not lines:
        lines.append("This round changed no screen file: walk only the flows a previous walk failed.")
    return " ".join(lines) + " Leave every other screen unwalked."


def browser_text(config: dict, reports: Path, name: str) -> str:
    """The walker prompt's line on how to drive the browser, for `[walk] browser`."""
    if walk_browser(config) == "agent-browser":
        session = f"colony-walk-{re.sub(r'[^A-Za-z0-9-]', '-', name)}"
        return ("Drive the browser with the `agent-browser` CLI through Bash, and no other browser tool. Run "
                "`agent-browser skills get core` once first for its commands. Pass `--session " + session + "` on "
                "every command. Set the phone size with `agent-browser set device \"iPhone 14\"` (touch input) and "
                "desktop with `set viewport 1280 800`, the theme with `set media dark` or `set media light`, and save "
                f"screenshots under {reports}/walk-shots/. Run `agent-browser --session {session} close` at the end.")
    return "Drive the browser through the Playwright MCP tools."


def claude_cmd(config: dict, role: str, prompt: str, add_dirs=()) -> list[str]:
    """Build the headless `claude -p` command for one role, with its model, effort and optional agent. It streams its
    events as JSON lines, which run_agent watches for a rate limit. A walker on agent-browser loads no MCP servers and
    may run `agent-browser` without asking."""
    settings = config["roles"][role]
    cmd = ["claude", "-p", prompt, "--model", settings["model"], "--effort", settings["effort"],
           "--permission-mode", "auto", "--output-format", "stream-json", "--verbose"]
    if settings.get("agent"):
        cmd += ["--agent", settings["agent"]]
    if role == "walker" and walk_browser(config) == "agent-browser":
        cmd += ["--strict-mcp-config", "--allowedTools", "Bash(agent-browser:*)"]
    for folder in add_dirs:
        cmd += ["--add-dir", str(folder)]
    return cmd


def _result(stdout: str) -> dict:
    """Read the result a headless claude run prints: the last `{"type": "result", …}` line of its stream, or an
    empty dict when it printed none."""
    found = {}
    for line in stdout.splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            found = data
    return found


def rate_limit_sign(line: str) -> str | None:
    """What one line of a headless claude run says about its account's rate limit: "limited" when the run has given up
    on it, its message carries `"error": "rate_limit"`, or its subscription's limit is reached (SUBSCRIPTION_LIMIT),
    "waiting" when it is retrying after a 429 or the account's window is rejected, "moving" when the run made
    progress, and None for a line that says neither. Only Claude Code's own events count, never a tool's output, so a
    file that mentions rate limits never trips it."""
    try:
        data = json.loads(line)
    except ValueError:
        return "limited" if RATE_LIMIT.search(line) or SUBSCRIPTION_LIMIT.search(line) else None
    if not isinstance(data, dict):
        return None
    kind = data.get("type")
    if kind == "system" and data.get("subtype") == "api_retry":
        return "waiting" if data.get("error_status") == 429 or "rate_limit" in str(data.get("error")) else None
    if data.get("error") == "rate_limit":  # Claude Code's mark on a message that gave up on the limit
        return "limited"
    if kind == "rate_limit_event":
        return "waiting" if (data.get("rate_limit_info") or {}).get("status") == "rejected" else "moving"
    if kind == "result":
        text = str(data.get("result", ""))
        error = data.get("is_error") and (RATE_LIMIT.search(f"{text} {data.get('errors', '')}") or
                                          SUBSCRIPTION_LIMIT.search(text))
        return "limited" if error else None
    if kind == "assistant":
        content = (data.get("message") or {}).get("content") or []
        text = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
        if SUBSCRIPTION_LIMIT.search(text):
            return "limited"
        if text.startswith("API Error") and RATE_LIMIT.search(text):
            return "waiting"
        return "moving"
    return "moving" if kind in ("user", "stream_event") else None


# One batch


@dataclass
class Batch:
    """One batch run: its config, cards, names, paths and running state."""

    config: dict
    name: str
    cards: dict[str, str]
    start: str
    root: Path
    account: tuple[str, str]
    dry: bool = False
    review: bool = True
    checks_only: bool = False  # `colony batch --fast`: the full checks once, with no reviewer, walk or fixers
    sender: str = ""  # the demo review's signature on its board line, the lead's `<login>-main-lead`
    person: str = ""  # whose accounts a rate-limited step moves to (switch_account)
    limited: set = field(default_factory=set)  # the accounts that hit their rate limit in this batch
    lock: threading.RLock = field(default_factory=threading.RLock)
    procs: set = field(default_factory=set)  # the agents, checks and reruns running now, each in its own group
    stopping: bool = False  # Ctrl-C or SIGTERM came: every running process is being stopped (stop_on_signal)
    state: dict = field(default_factory=lambda: {"round": 0, "running": {}, "rounds": [], "paid_spent": 0.0,
                                                       "switches": []})

    @classmethod
    def from_args(cls, config: dict, args) -> Batch:
        """Work out the batch from the parsed command line, refusing a bad name or card."""
        name = getattr(args, "name", None) or ""
        if not re.fullmatch(r"[\w.-]+", name):
            raise SystemExit(f"colony batch needs --name made of letters, digits, dots and dashes, got {name!r}")
        cards = {}
        for item in getattr(args, "card", None) or []:
            number, sep, branch = item.partition("=")
            if not sep or not number.strip("# ") or not branch.strip():
                raise SystemExit(f"--card wants N=BRANCH, got {item!r}")
            cards[number.strip("# ")] = branch.strip()
        demo = not cards and cli.mode(config) == "hack" and bool(getattr(args, "review", False))
        if not cards and not demo:
            raise SystemExit("colony batch needs at least one --card N=BRANCH (in hack mode, --review alone reviews "
                             "the demo build)")
        if demo and getattr(args, "from_branch", None):
            raise SystemExit("colony batch --review with no --card reviews origin/<base> as it stands: drop --from")
        start = getattr(args, "from_branch", None) or f"origin/{config['project']['base']}"
        review = bool(config["gate"]["review"] or getattr(args, "review", False))
        checks_only = bool(getattr(args, "fast", False))
        if checks_only and demo:
            raise SystemExit("colony batch --fast takes cards: --review alone reviews the demo build")
        if checks_only:
            config = {**config, "gate": {**config["gate"], "check": "full", "walk": False, "max_rounds": 1}}
            review = False
        check_settings(config)
        account = _account(config, args)
        b = cls(config, name, cards, start, _root(config, args), account,
                bool(getattr(args, "dry_run", False)), review, checks_only, person=_person(config, args, account[0]))
        if demo:
            from colony import wait

            b.sender = wait.lead_name(config, args)
        return b

    @property
    def demo(self) -> bool:
        """Whether this is hack mode's demo review: no cards, one reviewer on origin/<base> as it stands."""
        return not self.cards

    def __post_init__(self) -> None:
        """Work out the names and paths every step uses.

        project and tag are the config's [project] table and short name; branch is the batch branch; wt is its
        worktree, where the checks run and the reports live; walk_wt is the walker's second worktree; reports is
        the round files' folder; trailer is the line every commit the run makes or asks for ends with.
        """
        self.project = self.config["project"]
        self.tag = self.project["name"]
        self.branch = f"{self.tag}/batch-{self.name}"
        self.worktrees = Path(self.project["worktrees"]).expanduser()
        self.wt = self.worktrees / f"{self.tag}-batch-{self.name}"
        self.walk_wt = self.worktrees / f"{self.tag}-batch-{self.name}-walk"
        self.reports = self.wt / REPORTS / self.name
        self.trailer = trailer(self.config)

    def fix_names(self, card: str, r: int) -> tuple[str, Path]:
        """The fix branch and worktree for one card in one round."""
        return f"{self.tag}/fix-{self.name}-{card}-r{r}", self.worktrees / f"{self.tag}-fix-{self.name}-{card}-r{r}"

    def git(self, *args: str, check: bool = True) -> str:
        """Run git in the batch worktree."""
        return _git(self.wt, *args, check=check)

    def agent_env(self) -> dict:
        """The environment for headless agents: the picked account, and no API key, so runs use the account.

        The default settings folder leaves CLAUDE_CONFIG_DIR unset, since Claude Code ties a login to its value.
        """
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDE_CONFIG_DIR")}
        if not cli.is_default_dir(self.account[1]):
            env["CLAUDE_CONFIG_DIR"] = self.account[1]
        return env

    def check_env(self) -> dict:
        """The environment for the checks (checks_env)."""
        return checks_env(self.config, self.root)

    def track(self, proc: subprocess.Popen, on: bool = True) -> None:
        """Count a process the batch started with portable.own_group as running, or as ended. One that starts while
        the batch is stopping on a signal is stopped at once."""
        with self.lock:
            if not on:
                self.procs.discard(proc)
                return
            self.procs.add(proc)
            stopping = self.stopping
        if stopping:
            portable.stop_group(proc)

    def save(self) -> None:
        """Write state.json for `colony status`."""
        with self.lock:
            if self.reports.is_dir():
                (self.reports / "state.json").write_text(json.dumps(self.state, indent=2))

    def running(self, step: str, on: bool) -> None:
        """Mark a step as running or ended in state.json."""
        with self.lock:
            if on:
                self.state["running"][step] = time.strftime("%H:%M")
            else:
                self.state["running"].pop(step, None)
            self.save()

    def minute(self, step: str, minutes: float, cost=None, clock: str | None = None) -> None:
        """Append `HH:MM step minutes [$cost]` to minutes.md."""
        line = f"{clock or time.strftime('%H:%M')} {step} {minutes:.1f}" + (f" ${cost:.2f}" if cost is not None else "")
        with self.lock, (self.reports / "minutes.md").open("a") as out:
            out.write(line + "\n")

    def saved(self, step: str, minutes: float, cost=None) -> None:
        """Append `HH:MM saved step minutes [$cost]` to minutes.md: what a skipped or narrowed step saved."""
        if minutes > 0 or (cost or 0) > 0:
            self.minute(f"saved {step}", max(minutes, 0.0), None if cost is None else max(cost, 0.0))

    def shell(self, step: str, cmd: str, cwd: Path) -> None:
        """Run one of the config's shell commands (regen, install) as a timed step; stop the run when it fails."""
        started, clock = time.time(), time.strftime("%H:%M")
        self.running(step, True)
        command, shell, env = portable.shell(cmd, self.check_env())
        proc = subprocess.run(command, shell=shell, cwd=cwd, env=env, capture_output=True, text=True)
        self.running(step, False)
        self.minute(step, (time.time() - started) / 60, clock=clock)
        if proc.returncode:
            raise Stop(f"{step} exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[-600:]}")

    def install(self, cwd: Path) -> None:
        """Install packages in a new worktree when the config names an install command."""
        if self.project.get("install"):
            self.shell("install", self.project["install"], cwd)


def _root(config: dict, args=None) -> Path:
    """The host repository: --repo when given, else the checkout the command runs in."""
    return Path(getattr(args, "repo", None) or cli.repo_root()).expanduser()


def _person(config: dict, args, account: str) -> str:
    """Whose accounts the batch moves between when one hits its rate limit: --person, else the session's
    COLONY_PERSON, else cli.default_person, else the person the batch's account belongs to."""
    try:
        return cli.person_of(config, args)
    except cli.ColonyError:
        return config["accounts"][account]["person"]


def check_settings(config: dict) -> None:
    """Refuse a colony.toml whose checks or walk settings this version can't run: `[project] web_checks`, which
    `[checks] areas` replaced, `{areas}` in a check command with no areas named, and an unknown `[walk] browser`."""
    project = config["project"]
    if project.get("web_checks"):
        raise SystemExit("[project] web_checks is gone: name each check area's paths in [checks] areas, and put "
                         "{areas} in [project] checks where the area names go")
    if not check_areas(config) and any("{areas}" in (project.get(key) or "") for key in ("checks", "fast_check")):
        raise SystemExit("[project] checks has {areas}, but [checks] areas names none: add the areas and their paths")
    try:
        walk_browser(config)
    except cli.ColonyError as e:
        raise SystemExit(str(e)) from None


def _account(config: dict, args) -> tuple[str, str]:
    """Pick the agents' account as (name, config_dir), as cli.choose_account does: --account, else the person's
    accounts with room, the soonest weekly reset first, then their last-resort accounts.

    The person is --person, else the session's COLONY_PERSON, else cli.default_person.
    """
    return cli.choose_account(config, args)


# Prompts


def _cards_text(b: Batch) -> str:
    """List the cards with their branches for a prompt."""
    return ", ".join(f"#{n} (`{ref}`)" for n, ref in b.cards.items())


def risk_list(b: Batch, head: str) -> str:
    """The batch's risk list from the base to `head`, the reviewer's attention list (cycle.risk_text), or a line that
    says why it couldn't be read: the list guides the review and never stops a batch."""
    from colony import cycle

    try:
        return cycle.risk_text(b.config, f"origin/{b.project['base']}", head, b.wt)
    except cli.ColonyError as e:
        return f"- the risk list could not be read ({str(e).splitlines()[0][:200]}): read every changed path with care"


def reviewer_prompt(b: Batch, r: int, head: str, prev: dict | None, risks: str) -> str:
    """Fill the reviewer template for round r, reviewing from the base, or from the previous round's head, with the
    batch's risk list (risk_list) as its attention list."""
    gate = b.config["gate"]
    earlier = b.reports / f"review-{r - 1}.md"
    previous = "" if prev is None else f"This is round {r}. The previous report is {earlier}: mark each of its findings fixed or open."
    if b.demo:  # the demo build as it stands: its whole tree, against the empty tree
        diff_range, cards = f"{EMPTY_TREE} HEAD", (f"none. This review reads the demo build, origin/{b.project['base']} "
                                                   "as it stands: put what would break the demo first")
    else:
        diff_range = f"origin/{b.project['base']}...HEAD" if prev is None else f"{prev['head']}..HEAD"
        cards = _cards_text(b)
    return fill(cli.package_file("prompts", "reviewer.md"), project=b.tag, checkout=b.wt, branch=b.branch, head=head,
                diff_range=diff_range,
                generated=", ".join(f"`{g}`" for g in b.project.get("generated", [])), cards=cards,
                previous=previous, risks=risks,
                rubric="\n".join(f"{i}. {item}" for i, item in enumerate(gate["rubric"], 1)),
                rules=", ".join(f"`{rule}`" for rule in gate.get("rules", [])), report=b.reports / f"review-{r}.md")


def walker_prompt(b: Batch, r: int, head: str, changed: list[str]) -> str:
    """Fill the walker template for round r: the screens the round's `changed` files feed (screens_text), the
    browser to drive (browser_text), and the previous walk report when there is one."""
    earlier = b.reports / f"walk-{r - 1}.md"
    previous = f"The previous walk report is {earlier}: walk its failed flows first." if r > 1 and earlier.exists() else ""
    return fill(cli.package_file("prompts", "walker.md"), walk_checkout=b.walk_wt, head=head, busy=b.wt,
                cards=_cards_text(b), screens=screens_text(b.config, changed), previous=previous,
                browser=browser_text(b.config, b.reports, b.name), report=b.reports / f"walk-{r}.md")


def fixer_prompt(b: Batch, r: int, items: list[Finding], checkout: Path, branch: str) -> str:
    """Fill the fixer template with one card's findings, and the gate's check: the fast check for a fast gate, else
    the full checks, each for the check areas its findings' files are in (areas_of)."""
    lines = []
    for f in items:
        place = f"{f.path}:{f.line} — " if f.path and f.line else f"{f.path} — " if f.path else ""
        lines.append(f"- {place}{f.text}")
    cmd = fast_check(b.project) if fast_gate(b.config) else b.project["checks"]
    paths = [f.path for f in items]
    areas = areas_of(b.config, paths) if paths and all(paths) else list(check_areas(b.config))
    checks = check_command(b.config, cmd, areas or list(check_areas(b.config)))
    return fill(cli.package_file("prompts", "fixer.md"), project=b.tag, checkout=checkout, branch=branch, round=r,
                batch=b.name, reports=b.reports, findings="\n".join(lines), checks=checks, trailer=b.trailer)


# The run


def watch_agent(proc: subprocess.Popen, log: Path) -> tuple[str, str]:
    """Copy a headless claude run's stream to `log` as it comes, and say how the run ended: "done" when it exited,
    "limited" when its account hit the rate limit (rate_limit_sign): at once when the run gives up on it, or after
    RATE_LIMIT_GRACE seconds of retrying with no progress, and "stalled" after STALL_SECONDS with no line at all. A
    limited or stalled run is stopped with every process it started. Returns (the stream, how it ended)."""
    lines: queue.Queue = queue.Queue()

    def read() -> None:
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    kept: list[str] = []
    waiting = None  # when the run began waiting on the rate limit
    heard = time.monotonic()
    with log.open("w") as out:
        while True:
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                line = ""
            now = time.monotonic()
            if line is None:
                proc.wait()
                return "".join(kept), "done"
            how = ""
            if line:
                out.write(line)
                out.flush()
                kept.append(line)
                heard = now
                sign = rate_limit_sign(line)
                if sign == "limited":
                    how = "limited"
                elif sign == "waiting":
                    waiting = waiting or now
                elif sign == "moving":
                    waiting = None
            if not how and waiting is not None and now - waiting >= RATE_LIMIT_GRACE:
                how = "limited"
            if not how and now - heard >= STALL_SECONDS:
                how = "stalled"
            if how:
                portable.stop_group(proc)
                return "".join(kept), how


def switch_account(b: Batch, name: str, step: str) -> None:
    """Move the batch off an account that hit its rate limit: mark it limited, and when the batch still runs on it,
    take the person's next account with room (cli.pick_with_room). Stop the batch when none has room."""
    with b.lock:
        b.limited.add(name)
        if b.account[0] != name:  # another step moved the batch already
            return
        found = cli.pick_with_room(b.config, b.person, skip=b.limited)
        if found is None:
            raise Stop(f"{step} hit the rate limit on the account {name}, and no other account of {b.person}'s has "
                       f"room: run it again once {name} resets, or add an account")
        b.account = found[0], found[1]
        b.state["switches"].append({"step": step, "from": name, "to": found[0], "at": time.strftime("%H:%M")})
        b.save()
    print(f"colony batch {b.name}: {step} hit the rate limit on {name}; it runs again on {found[2]}")


def run_agent(b: Batch, role: str, prompt: str, cwd: Path, step: str, report: Path | None = None,
              parse=None, add_dirs=()) -> dict:
    """Run one headless claude session, watching its stream (watch_agent), and record its minutes and cost. It runs
    once more when it fails, stalls or leaves no valid report. When its account hits the rate limit, it runs again
    on the next account with room (switch_account), and that run is not one of its two tries."""
    cmd = claude_cmd(b.config, role, prompt, add_dirs)
    attempt, label = 1, step
    while True:
        account = b.account[0]
        started, clock = time.time(), time.strftime("%H:%M")
        b.running(label, True)
        proc = subprocess.Popen(cmd, cwd=cwd, env=b.agent_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace", **portable.own_group())
        b.track(proc)
        try:
            stdout, how = watch_agent(proc, b.reports / f"{label}.jsonl")
        finally:
            b.track(proc, on=False)
        b.running(label, False)
        data = _result(stdout)
        b.minute(label, data.get("duration_ms", (time.time() - started) * 1000) / 60000, data.get("total_cost_usd"), clock)
        if how == "limited":
            switch_account(b, account, step)
            label = f"{step}{'-retry' if attempt == 2 else ''}-{b.account[0]}"
            continue
        ok = how == "done" and proc.returncode == 0 and not data.get("is_error")
        if ok and report is not None:
            ok = report.exists() and (parse is None or parse(report.read_text()) is not None)
        if ok:
            return data
        if attempt == 2:
            why = f"stalled, silent {STALL_SECONDS // 60} minutes" if how == "stalled" else f"exit {proc.returncode}"
            raise Stop(f"{step} failed twice ({why}); its log is {b.reports / f'{label}.jsonl'}")
        attempt, label = 2, f"{step}-retry"


def merge_into_batch(b: Batch, ref: str) -> None:
    """Merge a branch into the batch with --no-ff, taking its side of a generated-only conflict and running regen."""
    proc = _run(["git", "merge", "--no-ff", "--no-edit", ref], b.wt, check=False)
    if proc.returncode == 0:
        return
    paths = b.git("diff", "--name-only", "--diff-filter=U").splitlines()
    if classify_conflict(paths, b.project.get("generated", [])) != "generated":
        b.git("merge", "--abort", check=False)
        raise Stop(f"merging {ref} conflicts outside the generated paths: {', '.join(paths) or proc.stderr.strip()}")
    try:
        b.git("checkout", "--theirs", "--", *paths)
        if b.project.get("regen"):
            b.shell("regen", b.project["regen"], b.wt)
        b.git("add", "-A", "--", ".", f":(exclude){REPORTS}/{b.name}")
        b.git("commit", "--no-edit")
    except Stop:
        b.git("merge", "--abort", check=False)
        raise


def assemble(b: Batch) -> None:
    """Make the batch branch in its own worktree from the start point and merge each card branch into it."""
    started, clock = time.time(), time.strftime("%H:%M")
    _git(b.root, "fetch", "origin")
    for card, branch in b.cards.items():
        local = _run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], b.root, check=False)
        remote = _run(["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], b.root, check=False)
        if local.returncode and remote.returncode:
            raise Stop(f"card #{card}'s branch {branch} is neither a local branch nor on origin")
        b.cards[card] = branch if local.returncode == 0 else f"origin/{branch}"
    _git(b.root, "worktree", "add", "--no-track", "-b", b.branch, str(b.wt), b.start)
    b.reports.mkdir(parents=True, exist_ok=True)
    b.state.update(batch=b.name, branch=b.branch, cards=b.cards)
    for ref in b.cards.values():
        merge_into_batch(b, ref)
    b.minute("assemble", (time.time() - started) / 60, clock=clock)
    b.install(b.wt)


def walk_round(b: Batch, r: int, head: str, changed: list[str]) -> dict:
    """Move the walk worktree to the round's head, making it the first time, and run the walker there on the screens
    the round's `changed` files feed; return its run's result (run_agent)."""
    if b.walk_wt.exists():
        _git(b.walk_wt, "checkout", "--detach", head)
    else:
        _git(b.root, "worktree", "add", "--detach", str(b.walk_wt), head)
        b.install(b.walk_wt)
    return run_agent(b, "walker", walker_prompt(b, r, head, changed), b.walk_wt, f"walk-r{r}", b.reports / f"walk-{r}.md",
                     parse_walk, add_dirs=[b.reports])


def round_areas(b: Batch, prev: dict | None, changed: list[str]) -> list[str] | None:
    """The check areas a round runs, in `[checks] areas` order: the areas its change touches (areas_of), and after a
    fix round also the areas whose checks failed in that round; the demo review checks every area. None when the
    batch names no areas, so the whole check command runs every round."""
    every = list(check_areas(b.config))
    if not every or b.demo:
        return every or None
    areas = set(areas_of(b.config, changed)) | set((prev or {}).get("failed_areas") or [])
    return [name for name in every if name in areas]


def failed_areas(b: Batch, ran: list[str] | None, failures: list[Finding]) -> list[str]:
    """The areas among `ran` that a round's check failures are in: each failing file's areas, and every area that
    ran for a failure that names no file or a file no area claims."""
    if not ran:
        return []
    hit = set()
    for f in failures:
        path = _resolve(b, f.path) if f.path else ""
        mine = set(areas_of(b.config, [path])) & set(ran) if path else set()
        hit |= mine or set(ran)
    return [name for name in ran if name in hit]


def timing_tests(output: str, tests: list[str]) -> list[str]:
    """The failing tests a timeout or a time limit explains: each test with at least one reason, every one of which
    names a timeout or a time limit (TIMING). A test's reasons are what follows ` - ` on its own lines, its detail
    lines (failure_lines), and the section header its line sits in when that header names a time limit. A test with
    no reason is never a timing failure."""
    if not TIMING.search(output):
        return []
    lines, blocks, headers = failure_lines(output)
    picked = []
    for test in tests:
        reasons = []
        for i, block in blocks.items():
            if test not in lines[i]:
                continue
            if " - " in lines[i]:
                reasons.append(lines[i].split(" - ", 1)[1])
            reasons += [lines[j] for j in block]
            if TIMING.search(headers[i]):
                reasons.append(headers[i])
        if reasons and all(TIMING.search(reason) for reason in reasons):
            picked.append(test)
    return picked


def rerun_timeouts(b: Batch, r: int, output: str, failures: list[Finding], log: Path) -> tuple[list[Finding], list[str]]:
    """Run each failing test a timeout or a time limit may explain (timing_tests) once more by itself with
    `[checks] rerun`, its `{test}` filled in, appending each run to the round's log. Returns the findings that still
    count and the tests that passed alone. Nothing reruns without `[checks] rerun`, or past RERUN_MAX failing tests."""
    cmd = b.config.get("checks", {}).get("rerun")
    tests = [test_id(f) for f in failures if test_id(f)]
    if not cmd or not tests or len(tests) > RERUN_MAX:
        return failures, []
    timed = timing_tests(output, tests)
    if not timed:
        return failures, []
    step, cleared = f"rerun-r{r}", []
    started, clock = time.time(), time.strftime("%H:%M")
    b.running(step, True)
    with log.open("a") as out:
        for test in timed:
            out.write(f"\n=== colony: {test}, once more by itself ===\n")
            out.flush()
            command, shell, env = portable.shell(cmd.replace("{test}", shlex.quote(test)), b.check_env())
            proc = subprocess.Popen(command, shell=shell, cwd=b.wt, env=env, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=subprocess.STDOUT, **portable.own_group())
            b.track(proc)
            try:
                code = proc.wait(timeout=RERUN_SECONDS)
            except subprocess.TimeoutExpired:
                portable.stop_group(proc)
                code = None
            finally:
                b.track(proc, on=False)
            out.write(f"=== colony: {test} {'passed alone' if code == 0 else 'failed again'} ===\n")
            out.flush()
            if code == 0:
                cleared.append(test)
    b.running(step, False)
    b.minute(step, (time.time() - started) / 60, clock=clock)
    return [f for f in failures if test_id(f) not in cleared], cleared


def run_checks(b: Batch, r: int, cmd: str, proc: subprocess.Popen, log: Path, started: float, clock: str):
    """Wait for the round's background checks, rerun the tests a timeout may have failed (rerun_timeouts), and write
    checks-<r>.md; return (passed, result line, failures, the run's minutes before any rerun). The checks pass after
    a failed run when every failing test passed alone and the output shows no other failure (other_failures). A run
    that exits 0 but only says NOT RUN (ran_nothing) blocks nothing, and its line starts ONLY_NOT_RUN, so the round
    and the pull request say the checks did not run."""
    code = proc.wait()
    b.track(proc, on=False)
    minutes = (time.time() - started) / 60
    b.running(f"checks-r{r}", False)
    b.minute(f"checks-r{r}", minutes, clock=clock)
    output = log.read_text(errors="replace")
    last = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), "no output")
    failures, cleared = ([], []) if code == 0 else rerun_timeouts(b, r, output, parse_check_failures(output), log)
    passed = code == 0
    if cleared and not failures:
        others = other_failures(output, set(cleared))
        passed = not others
        failures = [Finding("", 0, "checks failed: " + "; ".join(others[:5]))] if others else []
    if passed and code == 0 and ran_nothing(output):
        last = f"{ONLY_NOT_RUN}{last}"
    status = ("not run" if last.startswith(ONLY_NOT_RUN) else "pass") if passed else "fail"
    summary = [f"checks: {status}", "", f"`{cmd}` exited {code}: {last}", ""]
    alone = [f"- passed alone on a rerun, so not counted: {test}" for test in cleared]
    (b.reports / f"checks-{r}.md").write_text("\n".join(summary + alone + [f"- {f.text}" for f in failures]) + "\n")
    return passed, last, failures, minutes


def failure_key(finding: Finding) -> str:
    """What makes two runs' failures the same one: the test it names, else its text without durations."""
    return test_id(finding) or DURATION.sub("", finding.text)


def start_failures(b: Batch, r: int, cmd: str) -> tuple[str, set[str]]:
    """The batch's start commit, and the failures `cmd` shows there alone, without the cards, each as failure_key:
    none when it passes there, or when the install fails there, which tells nothing. It runs once per command in a
    batch, in a worktree of its own that it removes after, and state.json keeps the answer."""
    sha = b.git("merge-base", "HEAD", b.start)
    known = b.state.setdefault("start_checks", {})
    if cmd in known:
        return sha, set(known[cmd])
    wt = b.worktrees / f"{b.tag}-batch-{b.name}-start"
    step, started, clock = f"start-checks-r{r}", time.time(), time.strftime("%H:%M")
    b.running(step, True)
    try:
        if wt.exists():
            _git(b.root, "worktree", "remove", "--force", str(wt))
        _git(b.root, "worktree", "add", "--detach", str(wt), sha)
        try:
            b.install(wt)
        except Stop:
            return sha, set()
        log = b.reports / f"checks-start-{r}.log"
        with log.open("wb") as out:
            command, shell, env = portable.shell(cmd, b.check_env())
            proc = subprocess.Popen(command, shell=shell, cwd=wt, env=env, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=subprocess.STDOUT, **portable.own_group())
            b.track(proc)
            try:
                code = proc.wait()
            finally:
                b.track(proc, on=False)
        failing = {failure_key(f) for f in parse_check_failures(log.read_text(errors="replace"))} if code else set()
    finally:
        _git(b.root, "worktree", "remove", "--force", str(wt), check=False)
        b.running(step, False)
        b.minute(step, (time.time() - started) / 60, clock=clock)
    known[cmd] = sorted(failing)
    b.save()
    return sha, failing


def split_on_start(b: Batch, r: int, cmd: str, failures: list[Finding]) -> tuple[list[Finding], list[Finding], str]:
    """Split a failing round's check findings into the cards' own and the ones the start commit shows alone
    (start_failures), note the latter in checks-<r>.md, and return both with the start commit. No fixer gets one the
    start commit shows: the cards are not to blame for it."""
    sha, there = start_failures(b, r, cmd)
    on_start = [f for f in failures if failure_key(f) in there]
    if on_start:
        with (b.reports / f"checks-{r}.md").open("a") as out:
            out.write("".join(f"- fails on {b.start} alone at {sha[:9]} too, so no fixer gets it: {f.text}\n"
                              for f in on_start))
    return [f for f in failures if f not in on_start], on_start, sha


def checks_yardstick(b: Batch) -> float | None:
    """The minutes a round's checks take with every area: `[checks] minutes`, else this batch's own run of them,
    else None."""
    named = b.config.get("checks", {}).get("minutes")
    return float(named) if named else b.state.get("every_area_minutes")


def record_saved(b: Batch, r: int, areas: list[str] | None, check_minutes: float, walk: bool, walked: dict | None) -> None:
    """Write what round r's narrowed checks and walk saved to minutes.md, against running every check area and the
    full walk each round: skipped checks save their yardstick (checks_yardstick), checks for some areas the yardstick
    less their minutes; a skipped walk saves `[walk] minutes` and `cost`, and a narrowed walk those less its own."""
    every = list(check_areas(b.config))
    if areas is not None and set(areas) != set(every):
        yardstick = checks_yardstick(b)
        if yardstick:
            b.saved(f"checks-r{r}", yardstick - (check_minutes if areas else 0))
    settings = b.config.get("walk", {})
    if b.config["gate"].get("walk") and settings.get("minutes"):
        minutes, cost = float(settings["minutes"]), settings.get("cost")
        if not walk:
            b.saved(f"walk-r{r}", minutes, cost)
        elif walked:
            spent = walked.get("total_cost_usd")
            b.saved(f"walk-r{r}", minutes - walked.get("duration_ms", 0) / 60000,
                    None if cost is None or spent is None else float(cost) - spent)


def gate(b: Batch, r: int, last: bool = False) -> list[Finding]:
    """Run round r's checks, review and walk in parallel, record them, and return the findings, each marked with its
    source (checks, review or walk).

    The checks are the fast check alone for a fast gate (fast_gate), else the full checks, for the round's check
    areas (round_areas); a round with no area to check skips them. The review runs when b.review is set, and the walk
    when should_walk says so. The paid checks run when the checks pass and nothing else is open, or in the `last`
    round when the checks pass. The round is done, and the findings empty, when the checks pass, the review reports
    `open: 0` or was skipped, and the walk passed or was skipped.
    """
    project, settings = b.project, b.config["gate"]
    head = b.git("rev-parse", "HEAD")
    prev = b.state["rounds"][-1] if b.state["rounds"] else None
    changed = b.git("diff", "--name-only", f"{prev['head']}..HEAD" if prev else f"origin/{project['base']}...HEAD").splitlines()
    areas = round_areas(b, prev, changed)
    cmd = check_command(b.config, fast_check(project) if fast_gate(b.config) else project["checks"], areas)
    walk = should_walk(settings, b.state["rounds"], changed)
    b.state["round"] = r
    log = b.reports / f"checks-{r}.log"
    started, clock = time.time(), time.strftime("%H:%M")
    proc = None
    if areas != []:
        b.running(f"checks-r{r}", True)
        with log.open("wb") as out:
            command, shell, env = portable.shell(cmd, b.check_env())
            proc = subprocess.Popen(command, shell=shell, cwd=b.wt, env=env, stdout=out, stderr=subprocess.STDOUT,
                                    **portable.own_group())
            b.track(proc)
    review_report, walk_report = b.reports / f"review-{r}.md", b.reports / f"walk-{r}.md"
    with futures.ThreadPoolExecutor(max_workers=2) as pool:
        review = pool.submit(run_agent, b, "reviewer", reviewer_prompt(b, r, head, prev, risk_list(b, head)), b.wt,
                             f"review-r{r}", review_report, parse_open) if b.review else None
        walking = pool.submit(walk_round, b, r, head, changed) if walk else None
        on_start, start_sha = [], ""
        if proc is None:
            passed, line, check_findings, check_minutes = True, "skipped: the change touches no check area", [], 0.0
            (b.reports / f"checks-{r}.md").write_text(f"checks: skipped\n\n{line}\n")
        else:
            passed, line, check_findings, check_minutes = run_checks(b, r, cmd, proc, log, started, clock)
            if not passed and check_findings and not b.checks_only and not b.demo:
                check_findings, on_start, start_sha = split_on_start(b, r, cmd, check_findings)
        if review:
            review.result()
        walked = walking.result() if walking else None
    if proc is not None and (areas is None or set(areas) == set(check_areas(b.config))):
        b.state.setdefault("every_area_minutes", check_minutes)
    record_saved(b, r, areas, check_minutes, walk, walked)
    review_text = review_report.read_text() if b.review else ""
    open_count = parse_open(review_text) if b.review else 0
    walk_text = walk_report.read_text() if walk else ""
    walk_result = parse_walk(walk_text) if walk else "skipped"
    signature = sorted(DURATION.sub("", f.text) for f in check_findings)
    checks = "skipped" if proc is None else "fail" if not passed else "not run" if line.startswith(ONLY_NOT_RUN) \
        else "pass"
    b.state["rounds"].append({"round": r, "head": head, "open": open_count if b.review else "skipped", "walk": walk_result,
                              "checks": checks, "checks_cmd": cmd if proc is not None else "", "checks_line": line,
                              "checks_signature": signature, "areas": areas,
                              "failed_areas": failed_areas(b, areas, check_findings),
                              "on_start": [f.text for f in on_start]})
    b.save()
    if not passed and on_start and not check_findings:
        names = ", ".join(test_id(f) or f.text for f in on_start[:3])
        raise Stop(f"every failing check also fails on {b.start} alone at {start_sha[:9]}, without the cards ({names}): "
                   f"the cards are not to blame, so no fixer runs. Fix {b.start}, or the checks' setup, then run the "
                   "batch again")
    if not passed and prev and prev["checks"] == "fail" and prev["checks_signature"] == signature:
        raise Stop(f"the checks failed the same way in rounds {r - 1} and {r}")
    findings = []
    if open_count:
        missing = Finding("", 0, f"the review counts {open_count} open problems; read {review_report}")
        findings += [f._replace(source="review") for f in parse_findings(review_text) or [missing]]
    if walk_result not in ("pass", "skipped"):
        failed = parse_walk_failures(walk_text) or [Finding("", 0, f"the walk failed; read {walk_report}")]
        findings += [f._replace(source="walk") for f in failed]
    if passed and (not findings or last):
        findings += [f._replace(source="checks") for f in paid_checks(b, r)]
    return findings + [f._replace(source="checks") for f in check_findings]


def paid_checks(b: Batch, r: int) -> list[Finding]:
    """Run `[gate] paid_checks` in round r, the round that otherwise passes, and return its failures as findings.

    It runs only when the command is set and `[budget] provider_dollars` is above 0. It gets the dollars the batch has
    left as COLONY_SPEND_CEILING, must stop at that ceiling, and must print `spent: $<dollars>` as its own total. The
    batch stops when it prints none, or when the batch's spend passes the budget.
    """
    cmd, budget = b.config["gate"].get("paid_checks"), provider_dollars(b.config)
    if not cmd or budget <= 0:
        return []
    left = budget - b.state["paid_spent"]
    if left <= 0:
        raise Stop(f"the paid checks have spent the whole ${budget:.2f} budget")
    env = {**b.check_env(), "COLONY_SPEND_CEILING": f"{left:.2f}"}
    log, step = b.reports / f"paid-checks-{r}.log", f"paid-checks-r{r}"
    started, clock = time.time(), time.strftime("%H:%M")
    b.running(step, True)
    with log.open("wb") as out:
        code = subprocess.run(cmd, shell=True, cwd=b.wt, env=env, stdout=out, stderr=subprocess.STDOUT).returncode
    b.running(step, False)
    b.minute(step, (time.time() - started) / 60, clock=clock)
    output = log.read_text(errors="replace")
    reported = SPENT.findall(output)
    if not reported:
        raise Stop(f"the paid checks printed no `spent: $<dollars>` line; their log is {log}")
    spent = float(reported[-1])
    b.state["paid_spent"] += spent
    b.state["rounds"][-1]["paid"] = {"cmd": cmd, "result": "pass" if code == 0 else "fail", "spent": spent,
                                     "ceiling": left}
    b.save()
    if b.state["paid_spent"] > budget:
        raise Stop(f"the paid checks spent ${b.state['paid_spent']:.2f}, past the ${budget:.2f} budget")
    return [] if code == 0 else parse_check_failures(output)


def paid_lines(b: Batch) -> list[str]:
    """The PR body's paid checks section: each round's run, with the dollars spent against its ceiling."""
    runs = [x for x in b.state["rounds"] if x.get("paid")]
    if not runs:
        return ["None: [gate] paid_checks is unset or [budget] provider_dollars is 0, so $0.00 spent."]
    lines = [f"- Round {x['round']}: `{x['paid']['cmd']}` {x['paid']['result']}, ${x['paid']['spent']:.2f} spent "
             f"of a ${x['paid']['ceiling']:.2f} ceiling" for x in runs]
    return lines + [f"- Total: ${b.state['paid_spent']:.2f} of the ${provider_dollars(b.config):.2f} budget"]


def _resolve(b: Batch, path: str) -> str:
    """Turn a finding's path into a repository path: drop the checkout prefix, and find a test path given from a subfolder."""
    path = path.removeprefix(str(b.wt) + "/")
    if not path or (b.wt / path).exists():
        return path
    hits = b.git("ls-files", "--", f":(glob)**/{path}", check=False).splitlines()
    return hits[0] if hits else path


def fix_card(b: Batch, r: int, card: str, items: list[Finding], head: str) -> tuple[str, Path]:
    """Cut one card's fix branch from the batch head, run its fixer there, and return the branch once it holds a commit."""
    branch, path = b.fix_names(card, r)
    _git(b.root, "worktree", "add", "-b", branch, str(path), head)
    b.install(path)
    run_agent(b, "fixer", fixer_prompt(b, r, items, path, branch), path, f"fix-r{r}-{card}", add_dirs=[b.reports])
    if _git(path, "rev-list", "--count", f"{head}..HEAD") == "0":
        raise Stop(f"the fixer for #{card} in round {r} committed nothing")
    return branch, path


def fix_round(b: Batch, r: int, findings: list[Finding]) -> None:
    """Route the findings to their cards, run one fixer per card in parallel, and merge every fix branch into the batch."""
    head = b.git("rev-parse", "HEAD")
    groups: dict[str, list[Finding]] = {}
    for f in findings:
        f = f._replace(path=_resolve(b, f.path))
        groups.setdefault(owner_of(f.path, b.cards, b.wt, b.start), []).append(f)
    with futures.ThreadPoolExecutor(max_workers=len(groups)) as pool:
        jobs = [pool.submit(fix_card, b, r, card, items, head) for card, items in groups.items()]
    for branch, path in [job.result() for job in jobs]:
        merge_into_batch(b, branch)
        _git(b.root, "worktree", "remove", "--force", str(path))


def carry_over(b: Batch, r: int, findings: list[Finding]) -> list[str]:
    """Make each finding the last round leaves open into a card of its own (tidy.make_card), uncapped and sized S,
    for the batch's lead, and return the pull request's lines for them: the new card, the open issue it duplicates,
    or why no card was made. Hack mode has no cards, so its lines list the findings alone."""
    from types import SimpleNamespace

    from colony import tidy, wait

    lead = wait.lead_name(b.config, SimpleNamespace(person=b.person))
    lines = []
    for f in findings:
        place = f"{f.path}:{f.line}" if f.path and f.line else f.path
        what = f"{f.source or 'review'}: " + (f"`{place}` — " if place else "") + f.text
        if wait.hack(b.config):
            lines.append(f"- {what}")
            continue
        words = re.sub(r"\s+", " ", f.text).strip()
        title = f"Batch {b.name} left open: " + (words if len(words) <= 70 else words[:69].rstrip() + "…")
        body = "\n".join([f"Colony batch `{b.name}` ran its {r} rounds and left this {f.source or 'review'} finding "
                          f"open on `{b.branch}`, whose pull request lists this card.", "",
                          f"- {(f'`{place}` — ' if place else '') + f.text}", "",
                          f"The round reports are in `{REPORTS}/{b.name}/` on that branch.", "", "## Done when", "",
                          "- The finding above is fixed, or shown not to be a problem, with a test where it is "
                          "promised behavior."])
        try:
            lines.append(f"- #{tidy.make_card(b.config, title, body, 'S', lead, capped=False)} {what}")
        except tidy.Duplicate as e:
            lines.append(f"- #{e.number}, already open: {what}")
        except (cli.ColonyError, OSError) as e:
            lines.append(f"- no card made ({str(e).splitlines()[0][:160] if str(e) else type(e).__name__}): {what}")
    b.state["carried"] = lines
    b.save()
    return lines


def commit_reports(b: Batch, result: str) -> None:
    """Write result.md and commit the batch's Markdown reports to the batch branch."""
    if not b.reports.is_dir():
        return
    b.state["result"] = result
    b.save()
    rounds = [f"- Round {x['round']}: open {x['open']}, walk {x['walk']}, checks {x['checks']}" for x in b.state["rounds"]]
    carried = b.state.get("carried", [])
    rounds += ["", "Left open, now cards:", *carried] if carried else []
    (b.reports / "result.md").write_text("\n".join([f"result: {result}", "", *rounds]) + "\n")
    b.git("add", "--", *sorted(str(p.relative_to(b.wt)) for p in b.reports.glob("*.md")))
    if _run(["git", "diff", "--cached", "--quiet"], b.wt, check=False).returncode:
        b.git("commit", "-m", f"docs(colony): batch {b.name} reports\n\n{b.trailer}")


def removed_tests(b: Batch) -> list[str]:
    """List the test files the batch deletes, from `git diff --name-status` against the base."""
    out = b.git("diff", "--name-status", f"origin/{b.project['base']}...HEAD")
    return [line.split("\t")[1] for line in out.splitlines() if line.startswith("D") and TEST_PATH.search(line.split("\t")[1])]


def card_stats(b: Batch) -> str:
    """The cards' predicted and actual minutes and tokens (cycle.stats_table), or a line that says why they couldn't
    be read: the table informs the PR and never stops it."""
    from colony import cycle

    try:
        return cycle.stats_table(b.config, dict(b.cards), root=b.root)
    except (cli.ColonyError, OSError, ValueError, KeyError, TypeError) as e:
        return f"The card stats could not be read: {str(e).splitlines()[0][:200] if str(e) else type(e).__name__}."


def checks_line(x: dict) -> str:
    """One round's line in the PR body's checks section: its command and result, or why it skipped them."""
    if x["checks"] == "skipped":
        return f"- Round {x['round']}: skipped, {x['checks_line'].removeprefix('skipped: ')}"
    return f"- Round {x['round']}: `{x['checks_cmd']}` {x['checks']}: {x['checks_line']}"


def pr_body(b: Batch) -> str:
    """The pull request body: the cards, each as `Closes #N` so the merge closes it, the findings the last round left
    open as cards of their own (carry_over), the open problems by round, the check results, the account switches, the
    removed tests, the minutes, and the card stats."""
    rounds, carried, switches = b.state["rounds"], b.state.get("carried", []), b.state.get("switches", [])
    minutes = (b.reports / "minutes.md").read_text().splitlines() if (b.reports / "minutes.md").exists() else []
    return "\n".join([
        *(["gate: fast", ""] if b.checks_only else []),
        "## Cards", *[f"- Closes #{n}, from `{ref}`" for n, ref in b.cards.items()], "",
        *(["## Left open, now cards", f"Round {len(rounds)}, the last, left these open; the merge leaves them open.",
           *carried, ""] if carried else []),
        "## Open problems by round", " → ".join(str(x["open"]) for x in rounds), "",
        "| Round | Open | Walk | Checks |", "| --- | --- | --- | --- |",
        *[f"| {x['round']} | {x['open']} | {x['walk']} | {x['checks']} |" for x in rounds], "",
        "## Checks", *[checks_line(x) for x in rounds], "",
        "## Paid checks", *paid_lines(b), "",
        *(["## Account switches", *[f"- {s['at']} {s['step']} hit the rate limit on {s['from']}, and ran again on "
                                    f"{s['to']}" for s in switches], ""] if switches else []),
        "## Removed tests", *([f"- `{p}`" for p in removed_tests(b)] or ["None."]), "",
        "## Minutes", minutes_table(minutes), "",
        "## Card stats", card_stats(b), "",
        f"The round reports are in `{REPORTS}/{b.name}/`.", "", b.trailer, ""])


def push_cmd(b: Batch) -> list[str]:
    """The one push the runner makes: the batch branch, never the base."""
    return ["git", "push", "-u", "origin", f"refs/heads/{b.branch}:refs/heads/{b.branch}"]


def pr_cmd(b: Batch, body: Path) -> list[str]:
    """The `gh pr create` command for the batch."""
    return ["gh", "pr", "create", "--repo", b.project["repo"], "--base", b.project["base"], "--head", b.branch,
            "--title", f"{b.tag}: batch {b.name} (" + ", ".join(f"#{n}" for n in b.cards) + ")", "--body-file", str(body)]


def open_pr(b: Batch) -> str:
    """Commit the reports, push the batch branch, and open its pull request into the base; return the PR's address."""
    if b.branch == b.project["base"] or not b.branch.startswith(f"{b.tag}/batch-"):
        raise Stop(f"refusing to push {b.branch}")
    body = b.reports / "pr.md"
    body.write_text(pr_body(b))
    commit_reports(b, "done")
    _run(push_cmd(b), b.wt)
    return _run(pr_cmd(b, body), b.wt).stdout.strip()


def planned_changes(b: Batch) -> list[str]:
    """The files the cards change against the start, for a dry run's walker prompt: each card branch's diff, read
    without fetching, and empty when git can't read it."""
    changed: list[str] = []
    for ref in b.cards.values():
        for name in (ref, f"origin/{ref}"):
            try:
                proc = _run(["git", "diff", "--name-only", f"{b.start}...{name}"], b.root, check=False)
            except OSError:
                return changed
            if proc.returncode == 0:
                changed += [path for path in proc.stdout.splitlines() if path not in changed]
                break
    return changed


def plan(b: Batch) -> str:
    """Describe the run without running it: the branches, the commands, and round 1's prompts filled in."""
    project, settings = b.project, b.config["gate"]
    head = "<batch head>"
    generated = ", ".join(project.get("generated", []))
    fix_branch, fix_path = b.fix_names(next(iter(b.cards)), 1)
    lines = [f"colony batch {b.name}: dry run, nothing runs. Agents run as {b.account[0]}.", "", "Branches:",
             f"  batch  {b.branch} from {b.start}, in {b.wt}",
             *[f"  card   #{n} {ref}" for n, ref in b.cards.items()],
             f"  walk   detached worktree {b.walk_wt} at each round's head",
             f"  fix    {b.tag}/fix-{b.name}-<card>-r<round>, cut from the batch head, one per card with findings",
             f"  pr     {b.branch} into {project['base']}", "", "Commands:",
             "  $ git fetch origin",
             "  $ " + shlex.join(["git", "worktree", "add", "--no-track", "-b", b.branch, str(b.wt), b.start]),
             *["  $ " + shlex.join(["git", "merge", "--no-ff", "--no-edit", ref]) for ref in b.cards.values()],
             f"  a conflict only in {generated}: take the card's side, then $ {project.get('regen', '')}"]
    if project.get("install"):
        lines.append(f"  in each new worktree: $ {project['install']}")
    fast, areas, checks = fast_gate(b.config), check_areas(b.config), b.config.get("checks", {})
    cmd = fast_check(project) if fast else project["checks"]
    what = "the fast check" if fast else "checks"
    if areas:
        lines += [f"  {what}, in the background, for the areas a round touches: $ {check_command(b.config, cmd, ['<areas>'])}",
                  "    areas: " + "; ".join(f"{name} = {', '.join(paths)}" for name, paths in areas.items())
                  + (f"; every area: {checks['all']}" if checks.get("all") else "")
                  + (f"; a change only under {', '.join(checks['skip'])} runs none" if checks.get("skip") else ""),
                  "    round 1 runs the areas the cards change; a later round the areas that failed and the areas its "
                  "fixes touched"]
    else:
        lines.append(f"  {what}, in the background: $ {cmd}")
    if checks.get("rerun"):
        lines.append(f"  a failing test whose output names a timeout or a time limit runs once more by itself: "
                     f"$ {checks['rerun']}")
    if not b.checks_only:
        lines.append(f"  a round whose checks fail runs them once more on {b.start} alone, without the cards: a failure "
                     "there too goes to no fixer, and stops the batch when it is the only one left")
    if settings.get("paid_checks") and provider_dollars(b.config) > 0:
        lines.append(f"  paid checks, once in the round that otherwise passes, with COLONY_SPEND_CEILING at most "
                     f"${provider_dollars(b.config):.2f}: $ {settings['paid_checks']}")
    if b.review:
        lines.append("  reviewer: $ " + shlex.join(claude_cmd(b.config, "reviewer", "<reviewer prompt>")))
    if settings.get("walk"):
        lines.append("  walker, when a round touches " + ", ".join(settings.get("walk_paths") or ["any file"])
                     + f", on {walk_browser(b.config)}: $ "
                     + shlex.join(claude_cmd(b.config, "walker", "<walker prompt>", [b.reports])))
    done = ["the fast check passes" if fast else "checks pass", *(["open: 0"] if b.review else []),
            "walk pass or skipped"]
    rounds = min(int(settings.get("max_rounds", MAX_ROUNDS)), MAX_ROUNDS)
    if b.checks_only:
        lines.append("  no reviewer, walk or fixers: --fast stops when the checks fail")
    else:
        lines.append("  fixers, in parallel: $ " + shlex.join(claude_cmd(b.config, "fixer", "<fixer prompt>", [b.reports])))
    lines += [f"  rounds: at most {rounds}; done at {', '.join(done)}"
              + ("" if b.checks_only else f"; after round {rounds}, each finding still open becomes a card and the PR "
                 "opens, unless the checks fail"),
              "  an agent on a rate-limited account runs again on the person's next account with room",
              "  done: $ " + shlex.join(push_cmd(b)),
              "        $ " + shlex.join(pr_cmd(b, b.reports / "pr.md")), "", "Prompts for round 1:", ""]
    if b.review:
        lines += ["--- reviewer", reviewer_prompt(b, 1, head, None, RISKS_PLACE).rstrip(), ""]
    if settings.get("walk"):
        lines += ["--- walker", walker_prompt(b, 1, head, planned_changes(b)).rstrip(), ""]
    if b.checks_only:
        return "\n".join(lines).rstrip()
    example = [Finding("<path>", 1, "<each finding routed to this card>")]
    lines += [f"--- fixer, for card #{next(iter(b.cards))}", fixer_prompt(b, 1, example, fix_path, fix_branch).rstrip()]
    return "\n".join(lines)


def report_link(b: Batch) -> str:
    """The address of round 1's review report on the pushed batch branch."""
    return f"https://github.com/{b.project['repo']}/blob/{b.branch}/{REPORTS}/{b.name}/review-1.md"


def demo_plan(b: Batch) -> str:
    """Describe hack mode's demo review without running it."""
    lines = [f"colony batch {b.name}: dry run, nothing runs. The demo review runs as {b.account[0]}.", "",
             "  $ git fetch origin",
             "  $ " + shlex.join(["git", "worktree", "add", "--no-track", "-b", b.branch, str(b.wt), b.start]),
             f"  the fast check, in the background: $ {fast_check(b.project)}",
             "  one fresh reviewer: $ " + shlex.join(claude_cmd(b.config, "reviewer", "<reviewer prompt>")),
             "  no fixers: the demo build has no cards",
             "  then: $ " + shlex.join(push_cmd(b)),
             f"  and one line on the board, from {b.sender}: @all <the open count>, report: {report_link(b)}",
             f"  then: $ {cli.NAME} tidy", "", "--- reviewer",
             reviewer_prompt(b, 1, "<origin/" + b.project["base"] + ">", None, RISKS_PLACE).rstrip()]
    return "\n".join(lines)


def review_demo(b: Batch) -> int:
    """Hack mode's `colony batch --review --name <n>` with no cards: one fresh reviewer reads origin/<base> as it
    stands, beside the fast check, and writes its report. No fixers run. The report goes up on the batch branch, and
    one line on the board gives the open count and the report's link."""
    from colony import transport, wait

    try:
        assemble(b)
        gate(b, 1)
        last = b.state["rounds"][-1]
        commit_reports(b, f"reviewed: open {last['open']}, fast check {last['checks']}")
        _run(push_cmd(b), b.wt)
    except (Stop, OSError) as stop:
        print(f"colony batch {b.name} stopped: {stop}\nReports: {b.reports}")
        return 1
    head = last["head"][:7]
    sentence = (f"demo build {head} reviewed: open: {last['open']}, fast check {last['checks']}, "
                f"report: {report_link(b)}")
    print(f"colony batch {b.name}: reviewed origin/{b.project['base']} at {head}: open {last['open']}. "
          f"{report_link(b)}")
    try:
        line = wait.checked(wait.compose(f"@{wait.ALL}", sentence, b.sender), sentence)
        number = transport.send(b.config, f"@{wait.ALL}", line)
    except (cli.ColonyError, OSError) as e:
        print(f"colony batch {b.name}: the board line was not posted: {e}")
        return 1
    print(f"#{number} {line}")
    return 0


def tidy_at_end(b: Batch) -> None:
    """Run `colony tidy` once the batch has run. Tidy never changes the batch's result: a failure prints and goes on."""
    from colony import tidy

    try:
        tidy.run_tidy(b.config, b.root)
    except (cli.ColonyError, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
        print(f"colony batch {b.name}: tidy did not run: {e}")


def note_remote_database(b: Batch) -> None:
    """Note, at most once a day, a database the checks' env names on another computer: every check run writes to
    it, this batch's and its base check's among them, and a shared one slows as runs pile up."""
    from colony import merge  # merge imports this module, so it comes in here

    if hosts := merge.remote_databases(b.check_env()):
        merge.note_once(b.config, "database", f"the checks' env names a database on {', '.join(hosts)}, which isn't on "
                        "this computer: every check run writes to it, this batch's among them, and a shared one slows "
                        "as runs pile up; give the checks a database of their own")


def run_rounds(b: Batch) -> int:
    """Assemble the cards, then gate and fix round by round, at most MAX_ROUNDS rounds, until the PR opens or a stop
    rule fires. When the last round passes its checks with findings still open, each becomes a card (carry_over) and
    the PR opens listing them; failing checks in the last round stop the batch."""
    rounds = min(int(b.config["gate"].get("max_rounds", MAX_ROUNDS)), MAX_ROUNDS)
    try:
        assemble(b)
        note_remote_database(b)
        for r in range(1, rounds + 1):
            findings = gate(b, r, last=r == rounds)
            if not findings:
                print(f"colony batch {b.name}: done in round {r}. {open_pr(b)}")
                return 0
            if b.checks_only:
                raise Stop(f"the full checks failed, and --fast runs no fixers: {findings[0].text}")
            if r == rounds:
                failing = [f for f in findings if f.source == "checks"]
                if failing:
                    raise Stop(f"round {r} of {rounds} still fails its checks ({failing[0].text}), and a failing "
                               "check blocks the pull request")
                carry_over(b, r, findings)
                print(f"colony batch {b.name}: round {r} of {rounds} left {len(findings)} findings open, now cards "
                      f"the pull request lists. {open_pr(b)}")
                return 0
            fix_round(b, r, findings)
    except (Stop, OSError) as stop:
        try:
            commit_reports(b, f"stopped: {stop}")
        except Stop as also:
            print(f"colony batch {b.name}: the reports could not be committed: {also}")
        print(f"colony batch {b.name} stopped: {stop}\nReports: {b.reports}")
        return 1
    return 1


def stop_on_signal(b: Batch) -> dict:
    """Make Ctrl-C and SIGTERM stop the batch: each agent, check and rerun runs in its own process group, so the
    terminal's Ctrl-C never reaches them. The handler stops every group the batch has running (b.procs), then exits at
    once, 130 on Ctrl-C and 143 on SIGTERM, without waiting on the threads that watch them. Returns the handlers it
    replaced, for signal.signal to put back."""

    def stop(signum, frame) -> None:
        with b.lock:
            b.stopping = True
            running = list(b.procs)
        portable.stop_groups(running)
        print(f"\ncolony batch {b.name}: stopped by {signal.Signals(signum).name}, with the {len(running)} processes it "
              f"had running. Reports: {b.reports}", flush=True)
        sys.stderr.flush()
        os._exit(128 + signum)

    return {signum: signal.signal(signum, stop) for signum in (signal.SIGINT, signal.SIGTERM)}


def run_batch(config: dict, args) -> int:
    """Run `colony batch`: the rounds for the cards (run_rounds), or in hack mode with no cards the demo review
    (review_demo), then `colony tidy` (tidy_at_end). Ctrl-C stops every agent the batch has running (stop_on_signal)."""
    b = Batch.from_args(config, args)
    if b.dry:
        print(demo_plan(b) if b.demo else plan(b))
        return 0
    if b.wt.exists() or _git(b.root, "branch", "--list", b.branch):
        print(f"colony batch {b.name}: {b.branch} or {b.wt} already exists; pick another --name")
        return 1
    replaced = stop_on_signal(b) if threading.current_thread() is threading.main_thread() else {}
    try:
        result = review_demo(b) if b.demo else run_rounds(b)
        tidy_at_end(b)
    finally:
        for signum, handler in replaced.items():
            signal.signal(signum, handler)
    return result


def _find_reports(config: dict, name: str | None, args=None) -> Path | None:
    """Find a batch's reports folder, in its worktree or the repository; without a name, the newest one."""
    tag, worktrees = config["project"]["name"], Path(config["project"]["worktrees"]).expanduser()
    root = _root(config, args)
    if name:
        candidates = [worktrees / f"{tag}-batch-{name}" / REPORTS / name, root / REPORTS / name]
    else:
        candidates = sorted([*worktrees.glob(f"{tag}-batch-*/{REPORTS}/*"), *(root / REPORTS).glob("*")],
                            key=lambda p: p.stat().st_mtime, reverse=True)
    return next((p for p in candidates if p.is_dir()), None)


def _latest(folder: Path, prefix: str) -> tuple[int, str]:
    """Return the highest round number and text among a folder's `<prefix>-<r>.md` files, or (0, "")."""
    found = [(int(m[1]), p) for p in folder.glob(f"{prefix}-*.md") if (m := re.fullmatch(rf"{prefix}-(\d+)\.md", p.name))]
    if not found:
        return 0, ""
    r, path = max(found)
    return r, path.read_text()


def batch_status(config: dict, args) -> int:
    """Run `colony status`: print the batch's round, last open count and walk, the steps running now, and the minutes so far."""
    folder = _find_reports(config, getattr(args, "name", None), args)
    if folder is None:
        print("colony status: no batch reports found")
        return 1
    state = json.loads((folder / "state.json").read_text()) if (folder / "state.json").exists() else {}
    review_round, review = _latest(folder, "review")
    walk_round_, walk = _latest(folder, "walk")
    open_count = parse_open(review)
    print(f"batch {folder.name}: round {max(state.get('round', 0), review_round)}, "
          f"open {'none yet' if open_count is None else f'{open_count} (round {review_round})'}, "
          f"walk {f'{parse_walk(walk)} (round {walk_round_})' if walk else 'none yet'}")
    running = state.get("running", {})
    print("running: " + (", ".join(f"{step} since {clock}" for step, clock in running.items()) or "nothing"))
    if state.get("result"):
        print(f"result: {state['result']}")
    minutes = folder / "minutes.md"
    print(minutes_table(minutes.read_text()) if minutes.exists() else "no minutes yet")
    return 0
