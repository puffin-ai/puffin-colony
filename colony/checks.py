"""colony fast-check, colony check and colony ci: test in proportion to the change, keep every check fast or in the
background, watch runs live, never run the same check on the same code twice, and start CI on any commit.

Proportional tests. `[checks] scope` says what a check runs. "related", the default once `[checks] related` names a
command, runs the tests for the changed code and the repo's guard tests, `[checks] guards`, beside `[project]
fast_check` for the areas the change touches. "areas", the default without `related`, runs the check command for
those areas, as Colony always did. "full" runs `[project] checks` for every area, which `--full` asks for on
`colony fast-check`, `colony check run` and `colony batch`. A test belongs to a changed file by its name (test_x.py,
x_test.go, x.test.ts, x.spec.tsx, XTest.java, x_spec.rb), by `[checks] tests`, or because it is the change itself
(related_tests). A change to code that no test names, with no guard and no fast check to cover it, runs the area's
check command instead, so a change never goes unchecked.

Budgets. Each kind of check has a time budget in seconds, `[checks] budgets`: `fast` for `colony fast-check`,
`checks` for `colony check run` and a batch round, `full` for the full suite. A command follows a run's output up to
its budget, then leaves it running in the background and returns, so no one waits past it. `[checks] caps` stops a run
past its cap. Each run lives on this computer, under ~/.colony/<project>/checks/runs/: its state and its whole
output, which `colony check status` and `colony check watch` read at any time.

Slots. A background run holds one slot of the `tests` lock while its check runs, and the lock has as many slots as
test runs this computer runs at once (capacity.limits), so a busy computer runs fewer checks at a time. It holds one
slot of each `[checks] locks` lock too, such as a shared test database, the same locks `colony lock` takes. A run
that finds no free slot waits in the background, and its state says so (run_locks).

Live. A run marks its first failure the moment a line shows one (failure_sign), and every command that follows it
prints that line at once; `--until-failure` returns right there, so fixing starts while the rest runs. A batch round
marks its first failure in its state.json, which `colony status` prints (watch_log).

No repeated runs. Each result is kept in a ledger by the code it ran on, a git tree that holds the checkout's
uncommitted and new files too, and by the command and the check env file (ledger_key). A pass on the same code with
the same command is reused, and `--again` runs it anyway. A run of the same check on the same code that is already
going is joined, not started twice, and a newer run in the same checkout cancels the older one, which the newer code
made pointless.

CI. `colony ci [<ref>]` starts the project's CI on a commit, with `[ci] start` or, by default, a push of the commit to
a branch of its own, then watches the code host's checks on that commit, which every CI vendor reports, prints each
as it ends and the first failure at once, cancels the runs on older commits of the same branch, and posts a summary
on the commit's pull request, or on the commit itself (run_ci). It names no CI vendor's workflow.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from colony import batch, cli, folders, portable

SCOPES = ("related", "areas", "full")
KINDS = ("fast", "checks", "full")  # the kinds of check a budget or a cap names
BUDGETS = {"fast": 300, "checks": 300, "full": 0}  # seconds a command follows a run before it leaves it running
RUNNING = ("starting", "running")
ENDED = ("pass", "fail", "not run", "cancelled", "stopped")
RUNNING_EXIT = 3  # a command's exit code when its run goes on in the background past the budget
NOT_RUN_EXIT = batch.NOT_RUN_EXIT
POLL = 0.2  # seconds between two looks at a run's output and state
START_GRACE = 30  # seconds a run may stay "starting" before a reader counts it as stopped
LEDGER_KEPT = 500  # the newest results the ledger keeps
RUNS_KEPT = 50  # the newest ended runs whose files stay
FAILURES_KEPT = 20  # the failure lines a run's state keeps
HOME: Path | None = None  # where Colony keeps its state; None is ~/.colony. Tests point it at a temporary folder.
SLEEP = time.sleep
# A line that shows a test or a step failed, as it streams: pytest's FAILED or ERROR line in either order and its
# progress line with an F or E, a JS runner's FAIL or ×, go's `--- FAIL:`, cargo's `... FAILED`, TAP's `not ok`,
# make's `***`, npm's `npm ERR!`, and a repo check script's `FAIL <step>` line.
FAILURE_SIGNS = re.compile(
    r"^\s*(?:FAILED|ERROR)\s+\S+\.py(?:::|\s|$)"
    r"|^\s*\S+\.py::\S+\s+(?:FAILED|ERROR)\b"
    r"|^\S+\.py\s+[.sxXFE]*[FE][.sxXFE]*(?:\s+\[\s*\d+%\])?\s*$"
    r"|^\s*(?:FAIL(?:ED)?|✗|×|✕|not ok)\s+\S"
    r"|^\s*--- FAIL:"
    r"|^test \S+ \.\.\. FAILED"
    r"|^\S*make(?:\[\d+\])?: \*\*\*"
    r"|npm ERR!")
TEST_NAME = re.compile(r"^(?:test_.+\.py|.+_test\.\w+|.+\.(?:test|spec)\.[cm]?[jt]sx?|.+Tests?\.\w+|.+_spec\.rb)$")
SUBJECT = re.compile(r"^test_|_test$|\.(?:test|spec)$|Tests?$|_spec$")
# What a CI check's conclusion means: a pass, a skip, a cancel, or else a failure.
PASSED, SKIPPED = ("success", "neutral"), ("skipped",)
CI_PENDING = ("queued", "in_progress", "waiting", "pending", "requested", "action_required")
CI_DEFAULTS = {"start": "", "branch": "colony-ci/{short}", "post": True, "cancel_superseded": True,
               "poll_seconds": 20, "start_minutes": 10, "wait_minutes": 120}
RUNNER = ("import sys; sys.path.insert(0, sys.argv[1]); from colony import checks; "
          "sys.exit(checks.runner(sys.argv[2]))")


class Plan(NamedTuple):
    """What a check runs: its command (None when the change needs none), the check areas it runs (None when the repo
    names none), the tests it picked for the change, and the changed files no test names."""

    cmd: str | None
    areas: list[str] | None
    tests: list[str]
    untested: list[str]


# Settings


def settings(config: dict) -> dict:
    """`[checks]`'s proportional-test, budget and reuse keys, each with its default (see the module's docstring)."""
    table = config.get("checks") or {}
    related = table.get("related") or ""
    return {"scope": table.get("scope") or ("related" if related else "areas"), "related": related,
            "guards": table.get("guards") or [], "tests": dict(table.get("tests") or {}),
            "budgets": {**BUDGETS, **(table.get("budgets") or {})}, "caps": dict(table.get("caps") or {}),
            "reuse": table.get("reuse", True), "failure": table.get("failure") or "", "locks": table.get("locks") or []}


def ci_settings(config: dict) -> dict:
    """`[ci]`, each key with its default."""
    return {**CI_DEFAULTS, **(config.get("ci") or {})}


CI_FIELDS = {"short", "sha"}  # what [ci] branch may name: the commit, so each one gets a branch of its own
CI_BRANCH = re.compile(r"^(?!-)(?!.*(?:\.\.|//|@\{|\.lock(?:/|$)|/\.))[A-Za-z0-9_.][A-Za-z0-9_./-]*(?<![./])$")


def ci_branch(config: dict, sha: str, root: Path | None = None) -> str:
    """`[ci] branch` filled in for a commit: the branch `colony ci` pushes the commit to, and later deletes. It must
    name the commit with {short} or {sha}, and nothing else, make a plain branch name, and never be a protected branch
    (branches.protected: the base, the default branch, [safety] protect and the long-lived branches), which Colony
    would otherwise move and then delete."""
    import string

    from colony import branches

    pattern = ci_settings(config)["branch"]
    if not isinstance(pattern, str):
        raise cli.ColonyError('[ci] branch is a branch name with {short} or {sha} in it, such as "colony-ci/{short}"')
    try:
        fields = [(name, spec, conversion) for _, name, spec, conversion in string.Formatter().parse(pattern)
                  if name is not None]
    except ValueError:
        raise cli.ColonyError(f"[ci] branch {pattern!r} has braces that don't pair") from None
    named = {name for name, _, _ in fields}
    if not named & CI_FIELDS:
        raise cli.ColonyError(f"[ci] branch {pattern!r} needs {{short}} or {{sha}}, so each commit gets a branch of its "
                              'own, such as "colony-ci/{short}"')
    if named - CI_FIELDS or any(spec or conversion for _, spec, conversion in fields):
        odd = sorted(named - CI_FIELDS) or [next(name for name, spec, conversion in fields if spec or conversion)]
        raise cli.ColonyError(f"[ci] branch takes {{short}} and {{sha}} alone, not {{{odd[0]}}} or a format of them")
    name = pattern.format(short=sha[:9], sha=sha)
    if not CI_BRANCH.fullmatch(name):
        raise cli.ColonyError(f"[ci] branch makes {name}, which is no plain branch name")
    import fnmatch

    held = next((p for p in branches.protected(config, root) if fnmatch.fnmatchcase(name, p)), "")
    if held:
        raise cli.ColonyError(f"[ci] branch makes {name}, a protected branch ({held}), which `colony ci` would move and "
                              "then delete: name a branch of its own, such as colony-ci/{short}")
    return name


def delete_ci_branch(root: Path, made: str, sha: str) -> None:
    """Delete the branch `colony ci` made, only while origin's copy still holds the commit it pushed (a lease), so a
    branch someone moved since is left alone."""
    batch._run(["git", "push", f"--force-with-lease=refs/heads/{made}:{sha}", "origin", f":refs/heads/{made}"], root,
               check=False)


def check_budget(config: dict, kind: str) -> float:
    """How long a check of this kind blocks before it goes on in the background: [checks] budgets, and never more
    than a profile's tests.time_cap_minutes. 0, never blocking, is already the strictest."""
    from colony import profile

    seconds = float(settings(config)["budgets"].get(kind, 0))
    cap = profile.limit(config, "tests.time_cap_minutes")
    return min(seconds, cap * 60) if seconds and cap is not None else seconds


def validate(config: dict) -> None:
    """Refuse `[checks]` and `[ci]` settings this version can't run, naming the key in one line."""
    s, areas = settings(config), batch.check_areas(config)
    if s["scope"] not in SCOPES:
        raise cli.ColonyError(f"[checks] scope is {', '.join(map(repr, SCOPES))}, not {s['scope']!r}")
    if s["scope"] == "related" and not s["related"]:
        raise cli.ColonyError('[checks] scope = "related" needs [checks] related, the command that runs the tests '
                              "for a change")
    related = s["related"]
    if related and not isinstance(related, (str, dict)):
        raise cli.ColonyError("[checks] related is a command, or a table of check areas and their commands")
    entries = related.items() if isinstance(related, dict) else [("", related)] if related else []
    for name, entry in entries:
        where = f"[checks] related.{name}" if name else "[checks] related"
        if name and name not in areas:
            raise cli.ColonyError(f"{where}: [checks] areas names no area {name!r}")
        run = entry.get("run", "") if isinstance(entry, dict) else entry
        if not isinstance(run, str) or ("{tests}" not in run and "{files}" not in run):
            raise cli.ColonyError(f"{where} needs {{tests}} or {{files}} in its command, where the paths go")
    guards = s["guards"]
    if isinstance(guards, dict):
        for name in guards:
            if name not in areas:
                raise cli.ColonyError(f"[checks] guards.{name}: [checks] areas names no area {name!r}")
    elif not isinstance(guards, list):
        raise cli.ColonyError("[checks] guards is a list of test paths, or a table of check areas and their lists")
    for key in ("budgets", "caps"):
        for kind, value in s[key].items():
            if kind not in KINDS:
                raise cli.ColonyError(f"[checks] {key} names {kind!r}: the kinds are {', '.join(KINDS)}")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise cli.ColonyError(f"[checks] {key}.{kind} is a number of seconds, 0 or more")
    locks = s["locks"]
    from colony import capacity

    if not isinstance(locks, list) or not all(isinstance(n, str) and capacity.NAME.fullmatch(n) for n in locks):
        raise cli.ColonyError("[checks] locks is a list of lock names in lowercase letters, digits, dots and dashes, "
                              'such as ["test-db"]')
    if s["failure"]:
        try:
            re.compile(s["failure"])
        except re.error as e:
            raise cli.ColonyError(f"[checks] failure is not a regular expression: {e}") from None
    ci = ci_settings(config)
    for key in ("poll_seconds", "start_minutes", "wait_minutes"):
        if not isinstance(ci[key], (int, float)) or isinstance(ci[key], bool) or ci[key] <= 0:
            raise cli.ColonyError(f"[ci] {key} is a number above 0")
    ci_branch(config, "0" * 40)  # its shape and protection, on a sample commit; start_ci checks the real one


# Picking the tests for a change


def is_test_file(path: str) -> bool:
    """Whether a path is a test by its name, such as test_board.py, board_test.go or week.test.tsx."""
    return bool(TEST_NAME.match(PurePosixPath(path).name))


def in_test_folder(path: str) -> bool:
    """Whether a path sits in a test folder, such as tests/ or __tests__/, as batch.TEST_PATH reads it."""
    return bool(batch.TEST_PATH.search(path))


def subject(path: str) -> str:
    """What a file is about: its name without its folder, its extension and any test mark, in lowercase, so
    tests/test_board.py, board_test.go, Board.spec.ts and src/board.py all give `board`."""
    name = PurePosixPath(path).name
    stem = re.sub(r"(\.[cm]?[jt]sx?|\.\w+)$", "", name)
    return SUBJECT.sub("", stem).lower()


def nearness(source: str, test: str) -> tuple[int, int]:
    """How near a test is to a source file: the leading folders they share, then the fewer folders the test sits
    below those, so a test beside the file beats one in a folder further down."""
    depth = 0
    test_parts = PurePosixPath(test).parent.parts
    for x, y in zip(PurePosixPath(source).parent.parts, test_parts):
        if x != y:
            break
        depth += 1
    return depth, depth - len(test_parts)


def tracked(root: Path) -> list[str]:
    """The files git tracks in a checkout, plus its new untracked ones, as paths from its top."""
    files = batch._git(root, "ls-files", check=False).splitlines()
    files += batch._git(root, "ls-files", "--others", "--exclude-standard", check=False).splitlines()
    return list(dict.fromkeys(path for path in files if path))


def expand(patterns, files: list[str], root: Path) -> list[str]:
    """Each pattern as the paths it names: a glob becomes the files it matches, and any other entry, a file, a
    folder or a test id such as tests/test_a.py::test_b, stays as it is when its file or folder exists."""
    found = []
    for pattern in patterns:
        if any(c in pattern for c in "*?["):
            found += [path for path in files if batch.matches(path, [pattern])]
        elif (root / pattern.split("::")[0]).exists():
            found.append(pattern)
    return list(dict.fromkeys(found))


def guard_paths(config: dict, files: list[str], root: Path) -> list[str]:
    """`[checks] guards` as paths: a list for the whole repo, or a table of check areas and their lists."""
    guards = settings(config)["guards"]
    patterns = [p for group in guards.values() for p in group] if isinstance(guards, dict) else guards
    return expand(patterns, files, root)


def related_tests(config: dict, root: Path, changed: list[str], extra=()) -> tuple[list[str], list[str]]:
    """The tests for a change, and the changed files no test names. A changed test is its own test; a changed file
    in a test folder that is not a test, such as conftest.py or a helper, runs its folder; a code file runs the tests
    `[checks] tests` maps it to, and those whose subject is its own (subject), the nearest ones when several folders
    hold one. `extra` adds tests, such as the ones a round before failed. Paths under `[checks] skip` count for
    nothing. The guards come apart (guard_paths)."""
    files = tracked(root)
    by_subject: dict[str, list[str]] = {}
    holders = set()  # the folders that hold a test, at any depth below them
    for path in files:
        if is_test_file(path):
            by_subject.setdefault(subject(path), []).append(path)
            holders.update(str(folder) for folder in PurePosixPath(path).parents if str(folder) != ".")
    skip, mapped = (config.get("checks") or {}).get("skip") or [], settings(config)["tests"]
    picked, untested = [*expand(extra, files, root)], []
    for path in changed:
        if batch.matches(path, skip):
            continue
        if is_test_file(path):
            if (root / path).exists():
                picked.append(path)
            continue
        if in_test_folder(path):
            # A test's helper, fixture or conftest.py: the nearest folder above it that holds tests runs.
            folder = next((str(f) for f in PurePosixPath(path).parents if str(f) in holders), "")
            if folder:
                picked.append(folder)
            else:
                untested.append(path)
            continue
        found = expand([t for pattern, tests in mapped.items() if batch.matches(path, [pattern]) for t in tests],
                       files, root)
        named = by_subject.get(subject(path), [])
        if named:
            best = max(nearness(path, test) for test in named)
            found += [test for test in named if nearness(path, test) == best]
        if found:
            picked += found
        else:
            untested.append(path)
    return sorted(dict.fromkeys(picked)), untested


def _quoted(paths) -> str:
    """Paths for a shell command line, each quoted."""
    return " ".join(shlex.quote(path) for path in paths)


def related_steps(config: dict, root: Path, changed: list[str], extra=()) -> tuple[list[str], list[str], list[str]]:
    """The commands that run the tests for a change and the guards (`[checks] related`, filled in), the tests picked,
    and the changed files no test names. With one command, every path goes to it. With a table of check areas, each
    area gets the paths in it, and an entry `{ run, in }` runs in its folder with the paths from there. A command
    runs only when a placeholder it holds has paths."""
    related = settings(config)["related"]
    if not related:
        return [], [], []
    tests, untested = related_tests(config, root, changed, extra)
    files = tracked(root)
    guards = guard_paths(config, files, root)
    skip = (config.get("checks") or {}).get("skip") or []
    changed_now = [p for p in changed if not batch.matches(p, skip) and (root / p).exists()]
    entries = related.items() if isinstance(related, dict) else [("", related)]
    areas, steps = batch.check_areas(config), []
    for name, entry in entries:
        run, folder = (entry.get("run", ""), entry.get("in", "")) if isinstance(entry, dict) else (entry, "")
        mine = (lambda p: batch.matches(p, areas[name])) if name else (lambda p: True)
        prefix = folder.rstrip("/") + "/" if folder else ""

        def local(paths):
            return [p[len(prefix):] or "." for p in paths if mine(p) and p.startswith(prefix)]

        # An area's guards run when the change touches the area; with one command, every time.
        named_guards = settings(config)["guards"]
        if isinstance(named_guards, dict) and name:
            own = expand(named_guards.get(name, []), files, root)
        else:
            own = guards
        touched = not name or any(mine(p) for p in changed_now + tests)
        step_tests = list(dict.fromkeys(local(tests) + (local(own) if touched else [])))
        step_files = local(changed_now)
        if not (("{tests}" in run and step_tests) or ("{files}" in run and step_files)):
            continue
        command = run.replace("{tests}", _quoted(step_tests)).replace("{files}", _quoted(step_files))
        steps.append(f"cd {shlex.quote(folder)} && {command}" if folder else command)
    return steps, list(dict.fromkeys(tests + guards)), untested


def compose(steps: list[str]) -> str:
    """One shell command that runs each step in turn, every one even after a failure, and fails when any failed.
    One step runs as it is."""
    if len(steps) == 1:
        return steps[0]
    return "rc=0; " + " ".join(f"( {step} ) || rc=$?;" for step in steps) + " exit $rc"


def scoped(config: dict, root: Path, changed: list[str], areas: list[str] | None, base: str, scope: str,
           extra=()) -> Plan:
    """The check for a change in a scope (see the module's docstring). `base` is the command the "areas" scope runs
    for `areas`, such as `[project] checks` or `[project] fast_check`; "full" runs `[project] checks` for every area.
    "related" runs `[project] fast_check` for the areas, when it is set, then the tests for the change and the
    guards; when nothing covers a code change that no test names, it runs `base` for the areas instead. The command
    is None when the change touches no check area."""
    project = config["project"]
    if scope == "full":
        return Plan(batch.every_area(config, project["checks"]), list(batch.check_areas(config)) or None, [], [])
    if areas == []:
        return Plan(None, [], [], [])
    if scope == "areas" or not settings(config)["related"]:
        return Plan(batch.check_command(config, base, areas), areas, [], [])
    steps, tests, untested = related_steps(config, root, changed, extra)
    related = settings(config)["related"]
    if isinstance(related, dict) and areas:
        # An area the change touches that names no related command runs its own check command, as before.
        uncovered = [name for name in areas if name not in related]
        if uncovered:
            steps.append(batch.check_command(config, base, uncovered))
    quick = project.get("fast_check")
    if quick:
        steps = [batch.check_command(config, quick, areas), *steps]
    if not steps and (untested or not changed):
        steps = [batch.check_command(config, base, areas)]
    return Plan(compose(steps) if steps else None, areas, tests, untested)


def fast_plan(config: dict, root: Path, scope: str | None = None) -> Plan:
    """A builder's fast check for its branch's change (batch.branch_changes), in the scope `[checks] scope` names,
    or `scope`. The "areas" scope runs `[project] fast_check`, else `[project] checks`, as Colony always did."""
    scope = scope or settings(config)["scope"]
    base = batch.fast_check(config["project"])
    areas_named = bool(batch.check_areas(config))
    if scope == "areas" and ("{areas}" not in base or not areas_named):
        return Plan(base, None, [], [])
    changed = batch.branch_changes(root, config["project"]["base"])
    areas = batch.areas_of(config, changed) if areas_named else None
    return scoped(config, root, changed, areas, base, scope)


# The code a check ran on, and the ledger of results


def colony_home(config: dict) -> Path:
    """Where this computer keeps the project's check runs and ledger: ~/.colony/<project>/checks."""
    top = HOME if HOME is not None else Path.home() / f".{cli.NAME}"
    return top / config["project"]["name"] / "checks"


def code_id(root: Path) -> tuple[str, str, bool]:
    """The checkout's commit, the git tree of its files as they are now, uncommitted and new files included, and
    whether it holds any change past its commit. The tree is written with a copy of the checkout's index, so the
    checkout's own index never changes."""
    commit = batch._git(root, "rev-parse", "HEAD")
    if not batch._git(root, "status", "--porcelain", check=False):
        return commit, batch._git(root, "rev-parse", "HEAD^{tree}"), False
    index = Path(batch._git(root, "rev-parse", "--git-path", "index"))
    index = index if index.is_absolute() else root / index
    handle, copy = tempfile.mkstemp(prefix="colony-index-")
    os.close(handle)
    try:
        if index.exists():
            shutil.copyfile(index, copy)
        env = {**os.environ, "GIT_INDEX_FILE": copy}
        subprocess.run(["git", "add", "-A"], cwd=root, env=env, capture_output=True, check=True)
        tree = subprocess.run(["git", "write-tree"], cwd=root, env=env, capture_output=True, text=True,
                              check=True).stdout.strip()
    finally:
        os.unlink(copy)
    return commit, tree, True


def env_digest(config: dict, root: Path) -> str:
    """A digest of `[project] check_env_file`'s text, so a changed env file never reuses a result; empty without
    one. The values themselves are never kept."""
    found = batch.env_file(config, root)
    return hashlib.sha256(found.read_bytes()).hexdigest()[:16] if found else ""


def ledger_key(tree: str, command: str, env: str = "") -> str:
    """The ledger's key for one check on one code: its tree, its command and its env file's digest."""
    return hashlib.sha256(f"{tree}\0{command}\0{env}".encode()).hexdigest()[:24]


@contextlib.contextmanager
def _locked(folder: Path):
    """Hold this project's ledger lock, so one process at a time changes the ledger."""
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "ledger.lock", "w") as handle, portable.lock(handle):
        yield


def read_json(path: Path, default):
    """A JSON file's value, or `default` when it is missing or unreadable."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path: Path, value) -> None:
    """Write a value as JSON, whole, so a reader never sees half of it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}")
    part.write_text(json.dumps(value, indent=1))
    os.replace(part, path)


def ledger_path(folder: Path) -> Path:
    """The ledger's file in a project's checks folder."""
    return folder / "ledger.json"


def record(folder: Path, key: str, entry: dict) -> None:
    """Keep one result in the ledger, the newest LEDGER_KEPT of them."""
    with _locked(folder):
        found = read_json(ledger_path(folder), {})
        found = found if isinstance(found, dict) else {}
        found[key] = {**entry, "at": entry.get("at") or time.time()}
        if len(found) > LEDGER_KEPT:
            found = dict(sorted(found.items(), key=lambda item: item[1].get("at", 0))[-LEDGER_KEPT:])
        write_json(ledger_path(folder), found)


def lookup(folder: Path, key: str) -> dict | None:
    """One result the ledger keeps, or None."""
    found = read_json(ledger_path(folder), {})
    entry = found.get(key) if isinstance(found, dict) else None
    return entry if isinstance(entry, dict) else None


def reusable_pass(config: dict, key: str) -> dict | None:
    """The ledger's pass for this key, when `[checks] reuse` is on, else None."""
    if not settings(config)["reuse"]:
        return None
    entry = lookup(colony_home(config), key)
    return entry if entry and entry.get("result") == "pass" else None


def clock(at: float) -> str:
    """A time as HH:MM, or with its date when it is not today."""
    when = time.localtime(at)
    return time.strftime("%H:%M" if time.strftime("%Y-%m-%d", when) == time.strftime("%Y-%m-%d") else "%Y-%m-%d %H:%M",
                         when)


def span(seconds: float) -> str:
    """A length of time in words, such as 45 s or 3m 10s."""
    seconds = int(seconds)
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60}m {seconds % 60:02d}s"


# Background runs


def failure_sign(line: str, extra: str = "") -> bool:
    """Whether one line of a check's output shows a failure as it streams (FAILURE_SIGNS), or matches `[checks]
    failure`, the repo's own sign."""
    return bool(FAILURE_SIGNS.search(line) or (extra and re.search(extra, line)))


def runs_dir(config: dict) -> Path:
    """The folder that holds this project's check runs on this computer."""
    return colony_home(config) / "runs"


def run_files(folder: Path, run_id: str) -> tuple[Path, Path, Path]:
    """A run's state, its whole output, and its cancel mark."""
    return folder / f"{run_id}.json", folder / f"{run_id}.log", folder / f"{run_id}.cancel"


def alive(pid) -> bool:
    """Whether a process is still running."""
    if not pid:
        return False
    if portable.WINDOWS:
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_pid_group(pid) -> None:
    """End a process started in its own group, and everything it started: SIGTERM, then SIGKILL 5 seconds later
    for what is left, on macOS and Linux; `taskkill /T /F` on Windows."""
    if not pid:
        return
    if portable.WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        return
    for sig, grace in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 0.0)):
        try:
            os.killpg(int(pid), sig)
        except (ProcessLookupError, PermissionError):
            return
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            try:
                os.killpg(int(pid), 0)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(0.1)


def load(path: Path) -> dict:
    """A run's state as a reader sees it: a run whose runner is gone without a result counts as stopped, or as
    cancelled when it was asked to stop."""
    state = read_json(path, {})
    if not isinstance(state, dict) or not state:
        return {}
    if state.get("status") in RUNNING:
        mark = Path(path).with_suffix(".cancel")
        gone = not alive(state.get("pid")) if state.get("pid") else time.time() - state.get("created", 0) > START_GRACE
        if gone:
            cancelled = mark.exists()
            state = {**state, "status": "cancelled" if cancelled else "stopped",
                     "why": mark.read_text().strip() if cancelled else "its runner ended without a result"}
    return state


def all_runs(config: dict) -> list[dict]:
    """Every run this computer keeps for the project, newest first."""
    folder = runs_dir(config)
    states = [load(path) for path in folder.glob("*.json")] if folder.is_dir() else []
    return sorted((s for s in states if s), key=lambda s: s.get("created", 0), reverse=True)


def running(config: dict) -> list[dict]:
    """The runs still going."""
    return [s for s in all_runs(config) if s.get("status") in RUNNING]


def find_run(config: dict, run_id: str) -> dict:
    """One run by its id, or the start of one; a ColonyError when none or several match."""
    found = [s for s in all_runs(config) if s["id"] == run_id] or \
        [s for s in all_runs(config) if s["id"].startswith(run_id)]
    if not found:
        raise cli.ColonyError(f"no check run {run_id!r} on this computer: `{cli.NAME} check status` lists them")
    if len(found) > 1 and found[0]["id"] != run_id:
        raise cli.ColonyError(f"{run_id!r} names {len(found)} runs: give more of its id")
    return found[0]


def cancel(config: dict, state: dict, why: str) -> None:
    """Stop a run: leave its cancel mark, which its runner reads, and end the check it runs."""
    folder = runs_dir(config)
    _, _, mark = run_files(folder, state["id"])
    mark.write_text(why + "\n")
    stop_pid_group(state.get("child"))


def tidy_runs(folder: Path) -> None:
    """Remove the files of ended runs past the newest RUNS_KEPT."""
    ended = []
    for path in folder.glob("*.json"):
        state = read_json(path, {})
        if isinstance(state, dict) and state.get("status") in ENDED:
            ended.append((state.get("created", 0), state.get("id", path.stem)))
    for _, run_id in sorted(ended)[:-RUNS_KEPT]:
        for path in run_files(folder, run_id):
            path.unlink(missing_ok=True)


def run_locks(config: dict) -> list[list]:
    """The locks a background run holds while its check runs, each with its slots: `tests`, as many as this computer
    runs at once (capacity.limits), and each `[checks] locks` lock, as `[locks.<name>] slots` says (capacity.slots)."""
    from colony import capacity

    return [[name, capacity.slots(config, name)] for name in sorted({"tests", *settings(config)["locks"]})]


def start(config: dict, root: Path, *, kind: str, label: str, command: str, key: str, commit: str, tree: str,
          env: dict, dirty: bool = False, areas=None, untested=(), pre: str = "", cleanup: dict | None = None,
          lane: str = "") -> dict:
    """Start a check run in the background, or join the one already running the same check on the same code. A run
    in the same lane, the same checkout and kind, on other code is cancelled first: the newer code made it pointless.
    The runner gets `env`, the checks' environment, which never goes into a file. Returns the run's state."""
    folder = runs_dir(config)
    folder.mkdir(parents=True, exist_ok=True)
    lane = lane or f"{Path(root).resolve()}|{kind}"
    for other in running(config):
        if other.get("key") == key:
            return {**other, "joined": True}
    for other in running(config):
        if other.get("lane") == lane:
            cancel(config, other, f"newer code, {tree[:9]}, replaced it")
            print(f"cancelled {other['id']}: newer code in the same checkout made it pointless", flush=True)
    tidy_runs(folder)
    run_id = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{tree[:7]}"
    n = 1
    while run_files(folder, run_id)[0].exists():
        n += 1
        run_id = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{tree[:7]}-{n}"
    path, log, _ = run_files(folder, run_id)
    caps = settings(config)["caps"]
    from colony import capacity

    state = {"id": run_id, "kind": kind, "label": label, "lane": lane, "root": str(root), "commit": commit,
             "tree": tree, "dirty": dirty, "key": key, "command": command, "areas": areas,
             "untested": list(untested), "pre": pre,
             "cleanup": cleanup, "status": "starting", "created": time.time(), "cap": caps.get(kind, 0),
             "failure_pattern": settings(config)["failure"], "ledger": str(colony_home(config)), "failures": [],
             "locks": run_locks(config), "locks_dir": str(capacity.locks_dir())}
    write_json(path, state)
    log.write_text("")
    package = str(Path(__file__).resolve().parent.parent)
    subprocess.Popen([sys.executable, "-c", RUNNER, package, str(path)], cwd=root, env=env,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     **portable.own_group())
    return state


def runner(state_path: str) -> int:
    """The background runner: run the run's install, when it has one, then its command, in their own process group,
    copying the output to the run's log as it comes and marking the first failure at once. It stops the check past
    the run's cap, or when its cancel mark appears, and keeps a conclusive result in the ledger. First it takes a slot
    of each of the run's locks (run_locks), waiting in the background while none is free; its cap counts from then."""
    from colony import capacity

    path = Path(state_path)
    state = read_json(path, {})
    _, log, mark = run_files(path.parent, state["id"])
    state.update(status="running", pid=os.getpid(), started=time.time())
    write_json(path, state)
    pattern = state.get("failure_pattern") or ""
    cap = float(state.get("cap") or 0)
    why, code, capped, slots, no_slot = "", 0, False, {}, False
    steps = [("install", state["pre"])] if state.get("pre") else []
    steps.append(("check", state["command"]))
    try:
        with log.open("a", errors="replace") as out, contextlib.ExitStack() as held:
            if state.get("locks"):
                state["waiting"] = ", ".join(name for name, _ in state["locks"])
                write_json(path, state)
                asked = time.time()
                note = {"pid": os.getpid(), "session": os.environ.get(cli.SESSION_ENV, ""), "command": state["command"]}
                try:
                    slots = held.enter_context(capacity.hold_all(state["locks"], capacity.LOCK_WAIT_MINUTES, note,
                                                                 Path(state.get("locks_dir") or capacity.locks_dir()),
                                                                 stop=mark.exists))
                except cli.ColonyError as e:
                    no_slot, why = True, f"found no free slot: {e}"
                state.pop("waiting", None)
                state.update(slots=slots, started=time.time())
                write_json(path, state)
                if slots and time.time() - asked >= 1:
                    out.write(f"colony: waited {span(time.time() - asked)} for a free slot of "
                              f"{', '.join(slots)}\n")
                    out.flush()
            for step, command in steps:
                if mark.exists() or no_slot:
                    break
                if step == "install":
                    out.write(f"colony: install: {command}\n")
                    out.flush()
                shell_cmd, use_shell, env = portable.shell(command, {**os.environ, **capacity.slot_env(slots)})
                proc = subprocess.Popen(shell_cmd, shell=use_shell, cwd=state["root"], env=env,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, errors="replace", **portable.own_group())
                state["child"] = proc.pid
                write_json(path, state)
                lines: queue.Queue = queue.Queue()

                def read(stream=proc.stdout) -> None:
                    for line in stream:
                        lines.put(line)
                    lines.put(None)

                threading.Thread(target=read, daemon=True).start()
                exited = None  # when the check's own process ended
                while True:
                    try:
                        line = lines.get(timeout=POLL)
                    except queue.Empty:
                        line = ""
                    if line is None:
                        break
                    if not line and proc.poll() is not None:
                        # A process the check left behind can hold its output open: stop waiting on it soon after.
                        exited = exited or time.monotonic()
                        if time.monotonic() - exited > 2:
                            portable.stop_group(proc)
                            break
                    if line:
                        out.write(line)
                        out.flush()
                        if step == "check" and failure_sign(line, pattern):
                            text = line.strip()[:300]
                            if not state.get("first_failure"):
                                state.update(first_failure=text, first_failure_at=time.time())
                            if len(state["failures"]) < FAILURES_KEPT:
                                state["failures"].append(text)
                            write_json(path, state)
                    if cap and not capped and time.time() - state["started"] > cap:
                        capped, why = True, f"stopped past its cap of {span(cap)}"
                        portable.stop_group(proc)
                    if mark.exists() and proc.poll() is None:
                        portable.stop_group(proc)
                code = proc.wait()
                if step == "install" and code:
                    why = f"the install failed, exit {code}"
                    break
                if capped:
                    break
    except Exception as e:  # the runner must leave a result, whatever went wrong
        why, code = f"the runner failed: {type(e).__name__}: {e}"[:300], code or 1
    text = log.read_text(errors="replace") if log.exists() else ""
    last = next((line.strip() for line in reversed(text.splitlines()) if line.strip()), "no output")
    if mark.exists():
        status, why = "cancelled", mark.read_text().strip()
    elif no_slot:
        status = "stopped"
    elif why or code:
        status = "fail"
    elif batch.ran_nothing(text):
        status = "not run"
    else:
        status = "pass"
    if status == "fail" and not state.get("first_failure"):
        state.update(first_failure=why or last, first_failure_at=time.time())
    state.update(status=status, exit=code, why=why, last=last[:300], ended=time.time(), child=None)
    if status in ("pass", "fail") and not capped and "install" not in why and "runner" not in why:
        keys = sorted({batch.failure_key(f) for f in batch.parse_check_failures(text)}) if status == "fail" else []
        record(Path(state["ledger"]), state["key"], {
            "result": status, "kind": state["kind"], "label": state["label"], "commit": state["commit"],
            "tree": state["tree"], "command": state["command"], "line": last[:300],
            "seconds": round(state["ended"] - state["started"], 1), "failures": keys})
    write_json(path, state)
    if state.get("cleanup"):
        subprocess.run(["git", "worktree", "remove", "--force", state["cleanup"]["path"]], cwd=state["cleanup"]["root"],
                       capture_output=True)
    return 0


def _echo(log: Path, pos: int, final: bool = False) -> int:
    """Print what a run's log gained since `pos`, whole lines only until the run ends; return the new position."""
    try:
        with log.open("rb") as f:
            f.seek(pos)
            data = f.read()
    except OSError:
        return pos
    if not final:
        cut = data.rfind(b"\n") + 1
        data = data[:cut]
    if data:
        sys.stdout.write(data.decode(errors="replace"))
        sys.stdout.flush()
    return pos + len(data)


def follow(config: dict, state: dict, budget: float | None = None, until_failure: bool = False,
           echo: bool = True) -> dict:
    """Follow a run: print its output as it comes (echo), and its first failure the moment the runner marks it.
    Return the run's state when it ends, at its first failure with `until_failure`, or when `budget` seconds pass
    (None follows it to the end). Ctrl-C cancels the run."""
    path, log, _ = run_files(runs_dir(config), state["id"])
    pos, began, told = 0, time.monotonic(), False
    try:
        while True:
            if echo:
                pos = _echo(log, pos)
            current = load(path) or state
            if current.get("first_failure") and not told:
                told = True
                at = current.get("first_failure_at", time.time()) - current.get("started", time.time())
                print(f"colony: first failure, {span(max(at, 0))} in: {current['first_failure']}", flush=True)
                if until_failure:
                    return current
            if current.get("status") not in RUNNING:
                if echo:
                    _echo(log, pos, final=True)
                return current
            if budget is not None and time.monotonic() - began >= budget:
                return current
            SLEEP(POLL)
    except KeyboardInterrupt:
        cancel(config, state, "Ctrl-C")
        print(f"\ncancelled {state['id']}", flush=True)
        raise


def result_line(label: str, state: dict, named: str = "") -> tuple[str, int]:
    """The line a run ends a command on, and its exit code: passed, failed, not run, or still running."""
    status = state.get("status")
    if status in RUNNING and state.get("first_failure"):
        return (f"{label}: failing{named}, first failure: {state['first_failure']}; the rest runs on in the "
                f"background: `{cli.NAME} check watch {state['id']}` follows it", 1)
    if status in RUNNING:
        budget = state.get("budget_seen")
        past = f" past its {span(budget)} budget" if budget else ""
        if state.get("waiting"):
            past += f", waiting for a free slot of {state['waiting']}"
        return (f"{label}: running in the background{named}{past}, so work goes on: `{cli.NAME} check watch "
                f"{state['id']}` follows it, and `{cli.NAME} check status` shows it", RUNNING_EXIT)
    last = state.get("last") or "no output"
    if status == "pass":
        return f"{label}: passed{named}: {last}", 0
    if status == "not run":
        return f"{label}: not run{named}, {batch.ONLY_NOT_RUN}{last}", NOT_RUN_EXIT
    if status == "cancelled":
        return f"{label}: cancelled{named}: {state.get('why') or 'asked to stop'}", 1
    if status == "stopped":
        return f"{label}: stopped{named}: {state.get('why') or 'its runner ended'}", 1
    why = state.get("why") or f"exit {state.get('exit')}"
    return f"{label}: failed{named}, {why}: {last}", 1


def run_scoped(config: dict, root: Path, plan: Plan, *, kind: str, label: str, args, pre: str = "",
               cleanup: dict | None = None, check_root: Path | None = None) -> int:
    """Run a planned check the way every command does: reuse a pass on the same code, else start it in the
    background or join the same run, follow it up to its budget, and end on its result line."""
    named = f" for {' '.join(plan.areas)}" if plan.areas else ""
    if plan.cmd is None:
        print(f"{label}: not run, the change touches no check area")
        return NOT_RUN_EXIT
    for path in plan.untested[:10]:
        print(f"note: no test names {path}; " + ("the guards and the fast check cover it" if
                                                  settings(config)["guards"] or config["project"].get("fast_check")
                                                  else "its area's checks run"))
    print(f"$ {plan.cmd}", flush=True)
    if getattr(args, "dry_run", False):
        return 0
    where = check_root or root
    env = batch.checks_env(config, where)
    commit, tree, dirty = code_id(root)
    key = ledger_key(tree, plan.cmd, env_digest(config, where))
    if not getattr(args, "again", False) and (hit := reusable_pass(config, key)):
        if cleanup:
            batch._git(Path(cleanup["root"]), "worktree", "remove", "--force", cleanup["path"], check=False)
        print(f"{label}: passed{named}: {hit.get('line', '')} (reused: it passed on this same code at "
              f"{clock(hit.get('at', 0))}, in {span(hit.get('seconds', 0))}; --again runs it anyway)")
        return 0
    state = start(config, root, kind=kind, label=label, command=plan.cmd, key=key, commit=commit, tree=tree, env=env,
                  dirty=dirty, areas=plan.areas, untested=plan.untested, pre=pre, cleanup=cleanup)
    if state.get("joined"):
        print(f"joining {state['id']}, which already runs this check on this same code", flush=True)
    wait = getattr(args, "wait", None)
    budget = check_budget(config, kind) if wait is None else float(wait)
    if budget == 0:  # a budget of 0 leaves the run in the background at once
        state = load(run_files(runs_dir(config), state["id"])[0]) or state
    else:
        state = follow(config, state, budget=budget, until_failure=getattr(args, "until_failure", False))
    state["budget_seen"] = budget
    line, code = result_line(label, state, named)
    print(line)
    return code


# Commands


def run_fast_check(config: dict, args) -> int:
    """`colony fast-check`: a builder's fast check for its branch's change, in the scope `[checks] scope` names, or
    the full suite with --full. It ends on one line for the done line, `fast check: passed …`, `failed …`,
    `not run …`, or `running in the background …` past its budget, and exits 0, 1, NOT_RUN_EXIT or RUNNING_EXIT."""
    validate(config)
    root = cli.repo_root()
    plan = fast_plan(config, root, "full" if getattr(args, "full", False) else None)
    return run_scoped(config, root, plan, kind="full" if getattr(args, "full", False) else "fast",
                      label="fast check", args=args)


def ref_worktree(config: dict, root: Path, sha: str) -> Path:
    """A detached worktree of its own for checking a commit, under `[project] worktrees`."""
    project = config["project"]
    base = Path(project["worktrees"]).expanduser() / f"{project['name']}-check-{sha[:9]}"
    path, n = base, 1
    while path.exists():
        n += 1
        path = base.with_name(f"{base.name}-{n}")
    batch._git(root, *folders.worktree_arguments(root, path, "--detach", start=sha))
    return path


def check_run(config: dict, args) -> int:
    """`colony check run`: the checks, `[project] checks`, in the scope `[checks] scope` names (or --scope, or
    --full), for this checkout's change, or for a commit (--ref) in a worktree of its own that goes away after."""
    validate(config)
    root = cli.repo_root()
    scope = "full" if args.full else (args.scope or settings(config)["scope"])
    kind = "full" if scope == "full" else "checks"
    project = config["project"]
    if not args.ref:
        changed = batch.branch_changes(root, project["base"])
        areas = batch.areas_of(config, changed) if batch.check_areas(config) else None
        plan = scoped(config, root, changed, areas, project["checks"], scope)
        return run_scoped(config, root, plan, kind=kind, label="checks", args=args)
    batch._git(root, "fetch", "origin", check=False)
    sha = batch._git(root, "rev-parse", "--verify", f"{args.ref}^{{commit}}")
    changed = batch._git(root, "diff", "--name-only", f"origin/{project['base']}...{sha}", check=False).splitlines()
    areas = batch.areas_of(config, changed) if batch.check_areas(config) else None
    plan = scoped(config, root, changed, areas, project["checks"], scope)
    if args.dry_run or plan.cmd is None:
        return run_scoped(config, root, plan, kind=kind, label="checks", args=args)
    wt = ref_worktree(config, root, sha)
    plan = scoped(config, wt, changed, areas, project["checks"], scope)
    print(f"checking {args.ref} at {sha[:9]} in {wt}, which goes away after")
    return run_scoped(config, wt, plan, kind=kind, label="checks", args=args, pre=project.get("install", ""),
                      cleanup={"root": str(root), "path": str(wt)}, check_root=root)


def status_lines(config: dict, limit: int = 8, running_only: bool = False) -> list[str]:
    """One line per check run on this computer, the running ones first, then the newest ended ones: what it checks,
    where, how long it has run against its budget, and its first failure."""
    lines = []
    runs = all_runs(config)
    shown = [s for s in runs if s.get("status") in RUNNING]
    shown += [] if running_only else [s for s in runs if s.get("status") not in RUNNING]
    for s in shown[:limit]:
        started = s.get("started") or s.get("created", time.time())
        took = (s.get("ended") or time.time()) - started
        allowed = check_budget(config, s.get("kind"))
        over = " (over its budget)" if s.get("status") in RUNNING and allowed and took > allowed else ""
        first = f", first failure: {s['first_failure']}" if s.get("first_failure") else ""
        why = f", {s['why']}" if s.get("why") and s.get("status") != "fail" else ""
        if s.get("waiting") and s.get("status") in RUNNING:
            why += f", waiting for a free slot of {s['waiting']}"
        lines.append(f"{s['id']}: {s.get('label', s.get('kind'))} {s.get('status')} after {span(took)}{over}, on "
                     f"{s.get('commit', '')[:9]}{' with changes' if s.get('tree') and s.get('dirty') else ''} in "
                     f"{s.get('root', '')}{first}{why}")
    return lines


def check_status(config: dict, args) -> int:
    """`colony check status [<run>]`: one run in full, or every run on this computer, then what the ledger knows of
    this checkout's code and the CI on its commit."""
    if args.run_id:
        state = find_run(config, args.run_id)
        for key in ("id", "label", "status", "commit", "tree", "root", "command", "first_failure", "why", "last"):
            if state.get(key):
                print(f"{key}: {state[key]}")
        for line in state.get("failures", [])[1:]:
            print(f"failure: {line}")
        print(f"log: {run_files(runs_dir(config), state['id'])[1]}")
        return 0
    lines = status_lines(config, limit=args.limit)
    print("\n".join(lines) if lines else "no check runs on this computer")
    try:
        root = cli.repo_root()
        commit, tree, dirty = code_id(root)
    except (cli.ColonyError, batch.Stop, subprocess.CalledProcessError):
        return 0
    found = read_json(ledger_path(colony_home(config)), {})
    found = found if isinstance(found, dict) else {}
    mine = [e for e in found.values() if isinstance(e, dict) and e.get("tree") == tree]
    for e in sorted(mine, key=lambda e: e.get("at", 0)):
        print(f"this code ({tree[:9]}{', with changes' if dirty else ''}): {e.get('label', e.get('kind'))} "
              f"{'passed' if e.get('result') == 'pass' else 'failed'} at {clock(e.get('at', 0))}: `{e.get('command')}`")
    ci = lookup(colony_home(config), ci_key(commit))
    if ci:
        print(f"CI on {commit[:9]}: {ci.get('line')} at {clock(ci.get('at', 0))}")
    return 0


def check_watch(config: dict, args) -> int:
    """`colony check watch <run>`: follow a run live to its end, or to its first failure with --until-failure, and
    end on its result line."""
    state = find_run(config, args.run_id)
    state = follow(config, state, until_failure=args.until_failure)
    line, code = result_line(state.get("label", "check"), state)
    print(line)
    return code


def check_cancel(config: dict, args) -> int:
    """`colony check cancel <run>|--all`: stop runs on this computer."""
    targets = running(config) if args.all else [find_run(config, args.run_id)] if args.run_id else []
    if not targets:
        print("no check run to cancel" if args.all else f"name a run, or --all: `{cli.NAME} check status` lists them")
        return 0 if args.all else 2
    for state in targets:
        if state.get("status") not in RUNNING:
            print(f"{state['id']} already ended: {state.get('status')}")
            continue
        cancel(config, state, "cancelled by hand")
        print(f"cancelled {state['id']}")
    return 0


# The batch's checks: the round's command, reuse, a live first failure


def round_plan(b, changed: list[str], areas: list[str] | None, extra=()) -> Plan:
    """A batch round's check: the full suite with `colony batch --full`, else the scope `[checks] scope` names, from
    the round's base command, `[project] fast_check` for a fast gate and `[project] checks` otherwise."""
    project = b.project
    base = batch.fast_check(project) if batch.fast_gate(b.config) else project["checks"]
    scope = "full" if getattr(b, "full", False) else settings(b.config)["scope"]
    root = b.wt if b.wt.exists() else b.root
    return scoped(b.config, root, changed, areas, base, scope, extra)


def commit_key(b, sha: str, cmd: str) -> tuple[str, str, str]:
    """The ledger key of a check on one commit of the batch, with the commit and its tree. A commit's tree leaves out
    the batch's round reports, which stay untracked until the end, so the same code gives the same key."""
    where = b.wt if b.wt.exists() else b.root
    commit = batch._git(where, "rev-parse", sha)
    tree = batch._git(where, "rev-parse", f"{commit}^{{tree}}")
    return ledger_key(tree, cmd, env_digest(b.config, b.root)), commit, tree


def keep(b, key: str, commit: str, tree: str, cmd: str, result: str, line: str, minutes: float,
         failures=()) -> None:
    """Keep a batch's conclusive check result in the ledger."""
    if result not in ("pass", "fail"):
        return
    record(colony_home(b.config), key, {"result": result, "kind": "checks", "label": f"batch {b.name}",
                                        "commit": commit, "tree": tree, "command": cmd, "line": line[:300],
                                        "seconds": round(minutes * 60, 1), "failures": sorted(failures)})


def watch_log(log: Path, proc, on_first, pattern: str = "") -> threading.Thread:
    """Watch a check's log while its process runs, and call `on_first(line)` once, for the first line that shows a
    failure. The thread ends when the process does."""

    def watch() -> None:
        pos, rest = 0, b""
        while True:
            ended = proc.poll() is not None
            try:
                with log.open("rb") as f:
                    f.seek(pos)
                    data = f.read()
            except OSError:
                data = b""
            pos += len(data)
            rest += data
            *lines, rest = rest.split(b"\n")
            for raw in lines + ([rest] if ended and rest else []):
                line = raw.decode(errors="replace")
                if failure_sign(line, pattern):
                    on_first(line.strip()[:300])
                    return
            if ended:
                return
            time.sleep(POLL)

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return thread


def wait_capped(proc, cap: float) -> int | None:
    """Wait for a check, stopping it with everything it started past `cap` seconds (0 is no cap); None when stopped."""
    try:
        return proc.wait(timeout=cap or None)
    except subprocess.TimeoutExpired:
        portable.stop_group(proc)
        return None


# CI


def ci_key(sha: str) -> str:
    """The ledger key of CI's result on a commit."""
    return f"ci-{sha}"


def _gh(*args: str, input_text: str | None = None) -> str:
    """One gh command's output; a ColonyError when it fails."""
    try:
        run = subprocess.run(["gh", *args], capture_output=True, text=True, input=input_text, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise cli.ColonyError(f"gh {' '.join(args[:2])}: {e}") from None
    if run.returncode:
        raise cli.ColonyError(f"gh {' '.join(args[:2])} failed: {run.stderr.strip()[:200]}")
    return run.stdout


def _gh_json(*args: str, default=None):
    """One gh command's output read as JSON; `default` when it prints nothing."""
    text = _gh(*args).strip()
    return json.loads(text) if text else default


def ci_state(repo: str, sha: str) -> list[dict]:
    """Every check the code host knows on a commit, from any CI: its check runs and its commit statuses, each as
    {name, state, url}, the state pending, pass, fail, skipped or cancelled."""
    found = []
    runs = _gh_json("api", f"repos/{repo}/commits/{sha}/check-runs?per_page=100", default={}) or {}
    for run in runs.get("check_runs", []):
        conclusion = run.get("conclusion") or ""
        if run.get("status") != "completed":
            state = "pending"
        elif conclusion in PASSED:
            state = "pass"
        elif conclusion in SKIPPED:
            state = "skipped"
        elif conclusion == "cancelled":
            state = "cancelled"
        else:
            state = "fail"
        found.append({"name": run.get("name", "?"), "state": state, "url": run.get("html_url") or
                      run.get("details_url") or ""})
    combined = _gh_json("api", f"repos/{repo}/commits/{sha}/status", default={}) or {}
    for status in combined.get("statuses", []):
        state = {"success": "pass", "pending": "pending"}.get(status.get("state"), "fail")
        found.append({"name": status.get("context", "?"), "state": state, "url": status.get("target_url") or ""})
    return found


def remote_branches(root: Path, sha: str) -> list[str]:
    """The branches on origin whose tip is the commit."""
    out = batch._git(root, "for-each-ref", "--points-at", sha, "--format=%(refname)", "refs/remotes/origin",
                     check=False)
    names = [line.removeprefix("refs/remotes/origin/") for line in out.splitlines() if line]
    return [name for name in names if name != "HEAD"]


def start_ci(config: dict, root: Path, sha: str, branch: str) -> tuple[str, str]:
    """Start the project's CI on a commit: `[ci] start` filled in when it is set, else a push of the commit to a
    branch of its own, `[ci] branch`, unless a branch on origin already holds it at its tip. Returns what it did and
    the branch it made, if any."""
    ci, repo = ci_settings(config), config["project"]["repo"]
    made = ""
    values = {"sha": sha, "short": sha[:9], "repo": repo, "branch": branch}
    if ci["start"]:
        if "{branch}" in ci["start"] and not branch:
            made = values["branch"] = ci_branch(config, sha, root)
            batch._git(root, "push", "origin", f"{sha}:refs/heads/{made}")
        command = re.sub(r"\{(sha|short|repo|branch)\}", lambda m: shlex.quote(values[m[1]]), ci["start"])
        shell_cmd, use_shell, env = portable.shell(command, None)
        run = subprocess.run(shell_cmd, shell=use_shell, cwd=root, env=env, capture_output=True, text=True)
        if run.returncode:
            raise cli.ColonyError(f"[ci] start failed, exit {run.returncode}: "
                                  f"{(run.stderr or run.stdout).strip()[-300:]}")
        return f"started CI with `{command}`", made
    if branch:
        return f"{branch} holds {sha[:9]} on origin, so its push started CI", made
    made = ci_branch(config, sha, root)
    batch._git(root, "push", "origin", f"{sha}:refs/heads/{made}")
    return f"pushed {sha[:9]} to {made} on origin, which starts CI that runs on a push", made


def cancel_superseded(config: dict, root: Path, branch: str, sha: str) -> list[str]:
    """Cancel the CI runs on the branch for older commits, ones the commit descends from: the newer commit made them
    pointless. It reads the code host's own run list, which GitHub Actions keeps; other CI goes on untouched."""
    if not branch or not ci_settings(config)["cancel_superseded"]:
        return []
    repo = config["project"]["repo"]
    try:
        runs = _gh_json("run", "list", "--repo", repo, "--branch", branch, "--limit", "30", "--json",
                        "databaseId,headSha,status,url", default=[]) or []
    except cli.ColonyError:
        return []
    cancelled = []
    for run in runs:
        old = run.get("headSha") or ""
        if run.get("status") not in CI_PENDING or not old or old == sha:
            continue
        if batch._run(["git", "merge-base", "--is-ancestor", old, sha], root, check=False).returncode:
            continue  # not an older commit of this line, or not known here: leave it
        try:
            _gh("run", "cancel", str(run["databaseId"]), "--repo", repo)
        except cli.ColonyError as e:
            print(f"ci: could not cancel the run on {old[:9]}: {e}")
            continue
        cancelled.append(f"{old[:9]} ({run.get('url', run['databaseId'])})")
    return cancelled


def ci_summary(sha: str, checks: list[dict], first: dict | None, ended: bool) -> str:
    """The Markdown the team sees: the commit's CI result, each check with its link, and the first failure."""
    failed = [c for c in checks if c["state"] == "fail"]
    pending = [c for c in checks if c["state"] == "pending"]
    if failed:
        head = f"CI on `{sha[:9]}`: **failed**, {len(failed)} of {len(checks)} checks"
    elif pending:
        head = f"CI on `{sha[:9]}`: still running, {len(pending)} of {len(checks)} checks"
    else:
        head = f"CI on `{sha[:9]}`: **passed**, {len(checks)} checks"
    rows = []
    for c in checks:
        cell = f"[{c['state']}]({c['url']})" if c["url"] else c["state"]
        rows.append(f"| {c['name']} | {cell} |")
    lines = [head, "", "| Check | Result |", "| --- | --- |", *rows]
    if first:
        lines += ["", f"First failure: {first['name']}" + (f", {first['url']}" if first.get("url") else "")]
    if not ended:
        lines += ["", "The other checks were still running when this was posted."]
    return "\n".join(lines + ["", f"Posted by `{cli.NAME} ci`."]) + "\n"


def post_ci(config: dict, sha: str, text: str, issue: int | None = None) -> str:
    """Post the summary where the team sees it: on the card or issue named, else on the open pull request whose head
    is the commit, else on the commit itself. Returns where it went."""
    repo = config["project"]["repo"]
    if issue:
        _gh("issue", "comment", str(issue), "--repo", repo, "--body-file", "-", input_text=text)
        return f"issue #{issue}"
    pulls = _gh_json("api", f"repos/{repo}/commits/{sha}/pulls", default=[]) or []
    open_pr = next((p for p in pulls if p.get("state") == "open"), None)
    if open_pr:
        _gh("pr", "comment", str(open_pr["number"]), "--repo", repo, "--body-file", "-", input_text=text)
        return f"pull request #{open_pr['number']}"
    _gh("api", "-X", "POST", f"repos/{repo}/commits/{sha}/comments", "-f", f"body={text}")
    return f"commit {sha[:9]}"


def watch_ci(config: dict, sha: str, until_failure: bool = False, wait_minutes: float | None = None) \
        -> tuple[str, list[dict], dict | None]:
    """Watch the code host's checks on a commit: print each one as it ends, and the first failure at once. Returns
    how it ended, pass, fail, running (at the first failure with `until_failure`, or past the wait) or none (no
    check started), with the checks and the first failure."""
    ci, repo = ci_settings(config), config["project"]["repo"]
    began, seen, first, quiet, checks = time.monotonic(), {}, None, 0, []
    limit = 60 * (wait_minutes if wait_minutes is not None else ci["wait_minutes"])
    while True:
        try:
            checks = ci_state(repo, sha)
        except cli.ColonyError as e:
            print(f"ci: the code host didn't answer, trying again: {e}", flush=True)
            checks = checks or []
        for c in checks:
            key = (c["name"], c["url"])
            if c["state"] != "pending" and seen.get(key) != c["state"]:
                seen[key] = c["state"]
                print(f"ci {sha[:9]}: {c['name']} {c['state']}" + (f": {c['url']}" if c["state"] == "fail" else ""),
                      flush=True)
                if c["state"] == "fail" and first is None:
                    first = c
                    print(f"ci {sha[:9]}: first failure: {c['name']} {c['url']}", flush=True)
                    if until_failure:
                        return "running" if any(x["state"] == "pending" for x in checks) else "fail", checks, first
        elapsed = time.monotonic() - began
        if not checks and elapsed > 60 * ci["start_minutes"]:
            return "none", checks, first
        done = bool(checks) and not any(c["state"] == "pending" for c in checks)
        quiet = quiet + 1 if done else 0
        if quiet >= 2:  # two looks in a row with nothing pending, so a late job has had its chance to show
            return ("fail" if any(c["state"] == "fail" for c in checks) else "pass"), checks, first
        if elapsed > limit:
            return "running", checks, first
        SLEEP(ci["poll_seconds"])


def run_ci(config: dict, args) -> int:
    """`colony ci [<ref>]`: start CI on a commit, unless it already ran or passed there, cancel the runs it made
    pointless, watch its checks live, keep the result in the ledger, and post it where the team sees it."""
    validate(config)
    root = cli.repo_root()
    repo = config["project"]["repo"]
    ref = args.ref or "HEAD"
    batch._git(root, "fetch", "origin", check=False)
    sha = batch._git(root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    branches = remote_branches(root, sha)
    named = ref.removeprefix("origin/")
    branch = named if named in branches else (branches[0] if branches else "")
    if args.dry_run:
        ci = ci_settings(config)
        start_text = f"$ {ci['start']}" if ci["start"] else (f"none: {branch} holds it on origin" if branch else
                                                             f"$ git push origin {sha[:9]}:refs/heads/"
                                                             f"{ci['branch'].format(short=sha[:9], sha=sha)}")
        print(f"{cli.NAME} ci {sha[:9]}: dry run, nothing runs.\n  start: {start_text}\n  watch: the code host's "
              f"checks on {sha[:9]}, every {ci['poll_seconds']} s\n  post: "
              + ("on the commit's pull request, else on the commit" if ci["post"] and not args.no_post else "nothing"))
        return 0
    folder = colony_home(config)
    known = lookup(folder, ci_key(sha))
    if known and known.get("result") == "pass" and not args.again:
        print(f"ci: passed on {sha[:9]} already, at {clock(known.get('at', 0))}: {known.get('line')}; --again starts "
              "it once more")
        return 0
    existing = ci_state(repo, sha)
    made = ""
    if existing and not args.again:
        print(f"ci: {len(existing)} checks already run on {sha[:9]}, so none starts again; watching them")
    elif not args.no_start:
        did, made = start_ci(config, root, sha, branch)
        print(f"ci: {did}", flush=True)
        branch = branch or made
    for line in cancel_superseded(config, root, branch, sha):
        print(f"ci: cancelled the run on {line}: {sha[:9]} on {branch} made it pointless")
    if args.no_watch:
        print(f"ci: not watching; `{cli.NAME} ci {sha[:9]}` watches it")
        return 0
    how, checks, first = watch_ci(config, sha, until_failure=args.until_failure)
    if how == "none":
        if made:
            delete_ci_branch(root, made, sha)
        print(f"ci: no check started on {sha[:9]} within {ci_settings(config)['start_minutes']} minutes: set [ci] "
              "start to the command that starts your CI; {sha} and {branch} in it take the commit's")
        return 1
    text = ci_summary(sha, checks, first, ended=how in ("pass", "fail"))
    line = text.splitlines()[0].replace("**", "").replace("`", "")
    if how in ("pass", "fail"):
        record(folder, ci_key(sha), {"result": how, "kind": "ci", "label": "CI", "commit": sha, "tree": "",
                                     "command": f"{cli.NAME} ci", "line": line, "seconds": 0,
                                     "checks": [{"name": c["name"], "state": c["state"]} for c in checks]})
        if made:
            delete_ci_branch(root, made, sha)
    if ci_settings(config)["post"] and not args.no_post and (how in ("pass", "fail") or first):
        try:
            print(f"ci: posted on {post_ci(config, sha, text, args.issue)}")
        except cli.ColonyError as e:
            print(f"ci: the summary was not posted: {e}")
    print(f"ci: {line.removeprefix(f'CI on {sha[:9]}: ')}")
    return 0 if how == "pass" else RUNNING_EXIT if how == "running" and not first else 1


# The command line


def register(sub) -> None:
    """cli.py's route to this module: `fast-check`, `check` with its actions, and `ci`."""
    p = sub.add_parser("fast-check", help="a builder: run the fast check for this branch's change, the tests for the "
                                          "changed code and the guards in the related scope, and end on one line for "
                                          "the done line")
    p.add_argument("--full", action="store_true", help="run the full suite, [project] checks for every area, as the "
                                                       "person asked")
    p.add_argument("--again", action="store_true", help="run it even when it passed on this same code before")
    p.add_argument("--wait", type=float, metavar="SECONDS", help="follow it this long, instead of [checks] budgets")
    p.add_argument("--until-failure", action="store_true", help="return at the first failure, leaving the run going")
    p.add_argument("--dry-run", action="store_true", help="print the command and run nothing")
    p.set_defaults(run=run_fast_check)

    p = sub.add_parser("check", help="run the checks in proportion to the change, in the background past their budget, "
                                     "and see, watch or cancel the runs on this computer")
    actions = p.add_subparsers(dest="action", metavar="action", required=True)
    a = actions.add_parser("run", help="run [project] checks for this checkout's change in [checks] scope, or --full")
    a.add_argument("--scope", choices=SCOPES, help="what to run, instead of [checks] scope")
    a.add_argument("--full", action="store_true", help="the full suite: [project] checks for every area")
    a.add_argument("--ref", help="check this commit, in a worktree of its own that goes away after, such as "
                                 "origin/main")
    a.add_argument("--again", action="store_true", help="run it even when it passed on this same code before")
    a.add_argument("--wait", type=float, metavar="SECONDS", help="follow it this long, instead of [checks] budgets")
    a.add_argument("--until-failure", action="store_true", help="return at the first failure, leaving the run going")
    a.add_argument("--dry-run", action="store_true", help="print the command and run nothing")
    a.set_defaults(run=check_run)
    a = actions.add_parser("status", help="the check runs on this computer, and what is known of this code")
    a.add_argument("run_id", nargs="?", metavar="run", help="one run's id, or the start of it, to show in full")
    a.add_argument("--limit", type=int, default=8, help="how many runs to list")
    a.set_defaults(run=check_status)
    a = actions.add_parser("watch", help="follow a run live to its end, or --until-failure to its first failure")
    a.add_argument("run_id", metavar="run", help="the run's id, or the start of it")
    a.add_argument("--until-failure", action="store_true", help="return at the first failure, leaving the run going")
    a.set_defaults(run=check_watch)
    a = actions.add_parser("cancel", help="stop a check run on this computer")
    a.add_argument("run_id", nargs="?", metavar="run", help="the run's id, or the start of it")
    a.add_argument("--all", action="store_true", help="every running check of this project on this computer")
    a.set_defaults(run=check_cancel)

    p = sub.add_parser("ci", help="start the project's CI on a commit, watch its checks live, and post the result "
                                  "where the team sees it")
    p.add_argument("ref", nargs="?", help="the commit, a branch or a sha; HEAD by default")
    p.add_argument("--again", action="store_true", help="start it even when CI already ran or passed on the commit")
    p.add_argument("--no-start", action="store_true", help="only watch the checks already on the commit")
    p.add_argument("--no-watch", action="store_true", help="start it and return")
    p.add_argument("--until-failure", action="store_true", help="return at the first failing check")
    p.add_argument("--no-post", action="store_true", help="post nothing")
    p.add_argument("--issue", type=int, metavar="N", help="post the result on this card or issue")
    p.add_argument("--dry-run", action="store_true", help="print the plan and run nothing")
    p.set_defaults(run=run_ci)
