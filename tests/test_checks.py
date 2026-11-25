"""Tests for colony fast-check, colony check and colony ci (checks.py), and the checks a batch runs: tests in proportion
to the change, time budgets and background runs, live first failures, reuse of a pass on the same code, and CI on any
commit. They use temporary git repositories, a stub `gh` and short shell commands."""

import json
import os
import re
import time
from argparse import Namespace
from pathlib import Path

import pytest

from colony import batch, capacity, checks, cli
from test_batch import batch_args, commit, config, git, repo, stubs  # noqa: F401  (fixtures)


def fast_args(**values):
    """The args the parser makes for `colony fast-check`."""
    return Namespace(**{"full": False, "again": False, "wait": None, "until_failure": False, "dry_run": False,
                        **values})


def run_args(**values):
    """The args the parser makes for `colony check run`."""
    return Namespace(**{"scope": None, "full": False, "ref": None, "again": False, "wait": None,
                        "until_failure": False, "dry_run": False, **values})


LAYOUT = {"src/board.py": "b\n", "tests/test_board.py": "t\n", "tests/test_arch.py": "g\n", "tests/conftest.py": "c\n",
          "tests/fixtures/data.json": "{}\n", "web/src/week.ts": "w\n", "web/src/week.test.ts": "t\n",
          "web/src/other/week.test.ts": "t\n", "docs/guide.md": "d\n"}


@pytest.fixture
def card(repo, config, monkeypatch, tmp_path):
    """A repo whose main holds source files, their tests and a guard test, with a builder's card branch checked out,
    and a config in the related scope: `[checks] related` echoes the tests it gets to ../ran.txt, and the fast check
    echoes its areas to ../quick.txt."""
    commit(repo, LAYOUT, "layout")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "-b", "builder-1/7", "main")
    monkeypatch.chdir(repo)
    config["checks"] = {"areas": {"web": ["web/"], "py": ["src/", "tests/"]}, "skip": ["docs/"],
                        "related": "echo ran {tests} >> ../ran.txt", "guards": ["tests/test_arch.py"]}
    config["project"]["fast_check"] = "echo quick {areas} >> ../quick.txt"
    return repo


def lines(path: Path) -> list[str]:
    return path.read_text().splitlines() if path.exists() else []


# Task 40: test in proportion to the change


def test_a_test_belongs_to_a_file_by_its_name_in_every_common_shape():
    assert {checks.subject(p) for p in ("tests/test_board.py", "board_test.go", "web/Board.spec.ts", "src/board.py",
                                        "BoardTest.java", "board_spec.rb", "src/board.test.tsx")} == {"board"}
    assert checks.subject("src/contest.py") == "contest"  # a lowercase "test" ending is part of the name
    assert all(checks.is_test_file(p) for p in ("tests/test_a.py", "a_test.go", "a.test.ts", "a.spec.mjs", "ATest.java"))
    assert not any(checks.is_test_file(p) for p in ("tests/conftest.py", "src/contest.py", "src/latest.ts"))


def test_the_tests_for_a_change_are_its_named_tests_its_own_tests_and_a_helpers_folder(card, config):
    tests, untested = checks.related_tests(config, card, ["src/board.py"])
    assert (tests, untested) == (["tests/test_board.py"], [])
    # The test beside the file wins over one further down; a changed test is its own test.
    tests, _ = checks.related_tests(config, card, ["web/src/week.ts", "tests/test_arch.py"])
    assert tests == ["tests/test_arch.py", "web/src/week.test.ts"]
    # A test's helper or fixture runs the nearest folder that holds tests; docs count for nothing.
    assert checks.related_tests(config, card, ["tests/fixtures/data.json", "docs/guide.md"]) == (["tests"], [])
    assert checks.related_tests(config, card, ["setup.cfg"]) == ([], ["setup.cfg"])
    config["checks"]["tests"] = {"setup.cfg": ["tests/test_arch.py"]}
    assert checks.related_tests(config, card, ["setup.cfg"]) == (["tests/test_arch.py"], [])


def test_the_related_command_gets_the_tests_and_the_guards_and_each_area_its_own_from_its_folder(card, config):
    steps, tests, untested = checks.related_steps(config, card, ["src/board.py"])
    assert steps == ["echo ran tests/test_board.py tests/test_arch.py >> ../ran.txt"] and untested == []
    config["checks"]["related"] = {"web": {"run": "npx vitest run {tests}", "in": "web"},
                                   "py": "uv run pytest {tests}"}
    config["checks"]["guards"] = {"py": ["tests/test_arch.py"]}
    steps, _, _ = checks.related_steps(config, card, ["web/src/week.ts"])
    assert steps == ["cd web && npx vitest run src/week.test.ts"]  # the py guards wait for a py change
    steps, _, _ = checks.related_steps(config, card, ["web/src/week.ts", "src/board.py"])
    assert steps == ["cd web && npx vitest run src/week.test.ts", "uv run pytest tests/test_board.py tests/test_arch.py"]
    # An area with no related command of its own runs its area's check command, as before.
    del config["checks"]["related"]["web"]
    del config["project"]["fast_check"]
    plan = checks.scoped(config, card, ["web/src/week.ts", "src/board.py"], ["web", "py"], "check {areas}", "related")
    assert plan.cmd == checks.compose(["uv run pytest tests/test_board.py tests/test_arch.py", "check web"])
    assert checks.compose(["a", "b"]) == "rc=0; ( a ) || rc=$?; ( b ) || rc=$?; exit $rc"
    assert checks.compose(["a"]) == "a"


def test_each_scope_runs_its_own_command_and_a_change_no_test_covers_falls_back_to_its_areas(card, config):
    project = config["project"]
    project["checks"] = "full {areas}"
    config["checks"]["all"] = "all"
    plan = checks.scoped(config, card, ["src/board.py"], ["py"], project["checks"], "related")
    assert plan.cmd == ("rc=0; ( echo quick py >> ../quick.txt ) || rc=$?; ( echo ran tests/test_board.py "
                        "tests/test_arch.py >> ../ran.txt ) || rc=$?; exit $rc")
    assert checks.scoped(config, card, ["src/board.py"], ["py"], project["checks"], "areas").cmd == "full py"
    assert checks.scoped(config, card, ["src/board.py"], ["py"], project["checks"], "full").cmd == "full all"
    assert checks.scoped(config, card, ["docs/guide.md"], [], project["checks"], "related").cmd is None
    # No fast check and no guard: code that no test names runs its area's checks, so it never goes unchecked.
    del project["fast_check"]
    config["checks"]["guards"] = []
    plan = checks.scoped(config, card, ["setup.cfg"], ["web", "py"], project["checks"], "related")
    assert plan.cmd == "full all" and plan.untested == ["setup.cfg"]


def test_a_builders_fast_check_runs_the_tests_for_its_change_and_the_guards_beside_the_fast_check(card, config, capsys,
                                                                                                  tmp_path):
    commit(card, {"src/board.py": "b2\n"}, "the card")
    assert checks.run_fast_check(config, fast_args()) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[-1].startswith("fast check: passed for py: ")
    assert lines(tmp_path / "quick.txt") == ["quick py"]
    assert lines(tmp_path / "ran.txt") == ["ran tests/test_board.py tests/test_arch.py"]
    # --full, as the person asked: the full suite for every area, and nothing else. Its budget is 0 by default,
    # so it goes on in the background at once.
    config["project"]["checks"] = "echo full {areas} >> ../full.txt"
    assert checks.run_fast_check(config, fast_args(full=True)) == checks.RUNNING_EXIT
    run = checks.all_runs(config)[0]["id"]
    assert checks.check_watch(config, Namespace(run_id=run, until_failure=False)) == 0
    assert lines(tmp_path / "full.txt") == ["full web py"] and len(lines(tmp_path / "ran.txt")) == 1


def test_a_change_no_test_names_says_so_and_a_docs_only_change_runs_nothing(card, config, capsys, tmp_path):
    commit(card, {"setup.cfg": "x\n"}, "config")
    assert checks.run_fast_check(config, fast_args()) == 0
    out = capsys.readouterr().out
    assert "note: no test names setup.cfg; the guards and the fast check cover it" in out
    assert lines(tmp_path / "ran.txt") == ["ran tests/test_arch.py"]
    git(card, "checkout", "-q", "-b", "builder-1/8", "main")
    commit(card, {"docs/guide.md": "more\n"}, "docs")
    assert checks.run_fast_check(config, fast_args()) == checks.NOT_RUN_EXIT
    assert capsys.readouterr().out.splitlines() == ["fast check: not run, the change touches no check area"]


def test_a_batch_in_the_related_scope_checks_the_tests_for_its_cards_and_then_the_tests_that_failed(repo, config,
                                                                                                  stubs, tmp_path,
                                                                                                  capsys):
    commit(repo, {"tests/test_a.py": "t\n", "tests/test_guard.py": "g\n"}, "tests")
    git(repo, "push", "-q", "origin", "main")
    config["gate"].update(review=False, walk=False)
    config["project"]["checks"] = "echo full >> ../full.txt"
    config["checks"] = {"related": "echo related {tests} >> ../related.txt; if grep -qx a1 a.txt && ! grep -q fixed "
                                   "b.txt; then echo 'FAILED tests/test_a.py::test_x'; exit 1; fi",
                        "guards": ["tests/test_guard.py"]}
    assert batch.run_batch(config, batch_args(repo, "11=card/a")) == 0
    wt = Path(config["project"]["worktrees"])
    ran = lines(wt / "related.txt")
    # Round 1: card/a's a.txt and gen/api.json; round 2: the fix's b.txt, and the test that failed. The start commit
    # ran the round 1 command once, to see the failure isn't there already.
    assert ran == ["related tests/test_a.py tests/test_guard.py"] * 2 + \
        ["related tests/test_a.py::test_x tests/test_guard.py"]
    assert not (wt / "full.txt").exists()
    state = json.loads((wt / "demo-batch-b1" / ".colony" / "reports" / "b1" / "state.json").read_text())
    assert state["rounds"][0]["failed_tests"] == ["tests/test_a.py::test_x"]
    assert state["first_failures"]["1"]["line"] == "FAILED tests/test_a.py::test_x"
    assert "- no test names `gen/api.json`" in (wt / "demo-batch-b1" / ".colony" / "reports" / "b1" /
                                                "checks-1.md").read_text()
    # --full, as the person asked: the full suite every round, and no related tests.
    args = batch_args(repo, "11=card/a")
    args.name, args.full = "b2", True
    assert batch.run_batch(config, args) == 0
    assert lines(wt / "full.txt") == ["full"] and len(lines(wt / "related.txt")) == 3


# Task 41: every check fast or in the background, with a budget and a cap


def test_a_check_past_its_budget_goes_on_in_the_background_and_its_state_is_readable_at_any_time(card, config, capsys,
                                                                                              tmp_path):
    del config["checks"]
    config["project"]["fast_check"] = "echo started; sleep 2; echo finished >> ../done.txt"
    began = time.monotonic()
    assert checks.run_fast_check(config, fast_args(wait=0.5)) == checks.RUNNING_EXIT
    assert time.monotonic() - began < 2
    line = capsys.readouterr().out.splitlines()[-1]
    assert line.startswith("fast check: running in the background past its 0 s budget, so work goes on: "
                           "`colony check watch fast-")
    run = checks.running(config)[0]["id"]
    assert checks.check_status(config, Namespace(run_id=None, limit=8)) == 0
    assert f"{run}: fast check running after" in capsys.readouterr().out
    assert checks.check_watch(config, Namespace(run_id=run, until_failure=False)) == 0
    out = capsys.readouterr().out
    assert "finished" not in out and out.splitlines()[-1] == "fast check: passed: started"
    assert lines(tmp_path / "done.txt") == ["finished"]


def test_a_budget_of_zero_leaves_the_run_in_the_background_at_once_and_a_cap_stops_it(card, config, capsys):
    del config["checks"]
    config["project"]["fast_check"] = "sleep 20"
    config["checks"] = {"budgets": {"fast": 0}, "caps": {"fast": 1}}
    began = time.monotonic()
    assert checks.run_fast_check(config, fast_args()) == checks.RUNNING_EXIT
    assert time.monotonic() - began < 1.5
    run = checks.running(config)[0]["id"]
    assert checks.check_watch(config, Namespace(run_id=run, until_failure=False)) == 1
    assert capsys.readouterr().out.splitlines()[-1] == "fast check: failed, stopped past its cap of 1 s: no output"
    assert time.monotonic() - began < 10


def test_a_batch_round_past_its_cap_is_stopped_and_stops_the_batch(repo, config, stubs, capsys):
    config["gate"].update(review=False, walk=False)
    config["project"]["checks"] = "sleep 20"
    config["checks"] = {"caps": {"checks": 1}}
    began = time.monotonic()
    assert batch.run_batch(config, batch_args(repo, "11=card/a")) == 1
    assert "round 1's checks ran past their cap of 1 s and were stopped" in capsys.readouterr().out
    assert time.monotonic() - began < 15


# Task 42: watch runs live, and learn of the first failure at once


def test_a_line_that_shows_a_failure_is_known_as_it_streams():
    for line in ("FAILED tests/test_a.py::test_b - AssertionError", "tests/test_a.py::test_b FAILED [ 50%]",
                 "tests/test_a.py ..F..                                          [ 40%]", " × src/a.test.ts > reads",
                 "FAIL src/a.test.ts", "--- FAIL: TestReads (0.00s)", "test reads ... FAILED", "not ok 3 reads",
                 "make: *** [lint] Error 1", "npm ERR! Test failed.", "FAIL pytest (9s), exit 1"):
        assert checks.failure_sign(line), line
    for line in ("PASSED tests/test_a.py::test_b", "tests/test_a.py .....  [100%]", "=== 1 failed, 3 passed ===",
                 "Tests  0 failed | 12 passed", "ok 3 reads", "no failures here"):
        assert not checks.failure_sign(line), line
    assert checks.failure_sign("BROKE: the build", r"^BROKE:")


def test_the_first_failure_shows_at_once_and_until_failure_returns_while_the_rest_runs(card, config, capsys):
    del config["checks"]
    config["project"]["fast_check"] = "echo 'FAILED tests/test_board.py::test_moves'; sleep 4; exit 1"
    began = time.monotonic()
    assert checks.run_fast_check(config, fast_args(until_failure=True)) == 1
    assert time.monotonic() - began < 3
    out = capsys.readouterr().out
    assert "colony: first failure, " in out and " in: FAILED tests/test_board.py::test_moves" in out
    assert out.splitlines()[-1].startswith("fast check: failing, first failure: FAILED tests/test_board.py::test_moves;"
                                           " the rest runs on in the background")
    state = checks.running(config)[0]
    assert state["first_failure"] == "FAILED tests/test_board.py::test_moves"
    assert checks.check_cancel(config, Namespace(run_id=None, all=True)) == 0
    assert checks.load(checks.run_files(checks.runs_dir(config), state["id"])[0])["status"] == "cancelled"


def test_colony_status_shows_a_batch_rounds_first_failure_and_the_running_checks(repo, config, stubs, capsys):
    config["gate"].update(review=False, walk=False, max_rounds=1)
    config["project"]["checks"] = "echo 'FAILED tests/test_db.py::test_x'; grep -qx a1 a.txt && exit 1; exit 0"
    assert batch.run_batch(config, batch_args(repo, "11=card/a")) == 1
    assert "round 1's checks: first failure at" in capsys.readouterr().out
    assert batch.batch_status(config, Namespace(name="b1", repo=str(repo))) == 0
    assert "checks, round 1: first failure at " in capsys.readouterr().out


# Checks and capacity: a background run takes a tests slot, and the locks [checks] names


def test_a_background_run_holds_a_tests_slot_and_each_checks_lock_and_its_command_sees_them(card, config, capsys):
    del config["checks"]
    config["checks"] = {"locks": ["test-db"]}
    config["locks"] = {"test-db": {"slots": 2}}
    config["project"]["fast_check"] = 'echo "slots $COLONY_LOCK_SLOT_TESTS $COLONY_LOCK_SLOT_TEST_DB"'
    assert checks.run_fast_check(config, fast_args()) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "fast check: passed: slots 0 0"
    run = checks.all_runs(config)[0]
    assert run["locks"] == [["test-db", 2], ["tests", capacity.slots(config, "tests")]]
    assert run["slots"] == {"test-db": 0, "tests": 0} and "waiting" not in run
    assert capacity.holders("tests") == [] and capacity.holders("test-db") == []  # freed when the run ended


def test_a_run_with_no_free_tests_slot_waits_in_the_background_then_runs_when_one_frees(card, config, capsys):
    del config["checks"]
    config["locks"] = {"tests": {"slots": 1}}
    config["project"]["fast_check"] = "echo ran"
    with capacity.hold("tests", 1, 0, {"session": "builder-2", "command": "pytest"}):
        assert checks.run_fast_check(config, fast_args(wait=0.5)) == checks.RUNNING_EXIT
        assert "waiting for a free slot of tests" in capsys.readouterr().out.splitlines()[-1]
        assert checks.check_status(config, Namespace(run_id=None, limit=8)) == 0
        assert "waiting for a free slot of tests" in capsys.readouterr().out
        run = checks.running(config)[0]["id"]
    assert checks.check_watch(config, Namespace(run_id=run, until_failure=False)) == 0
    out = capsys.readouterr().out
    assert "colony: waited " in out and " for a free slot of tests" in out
    assert out.splitlines()[-1] == "fast check: passed: ran"


def test_a_run_cancelled_while_it_waits_for_a_slot_ends_cancelled_and_never_runs(card, config, capsys, tmp_path):
    del config["checks"]
    config["locks"] = {"tests": {"slots": 1}}
    config["project"]["fast_check"] = "echo ran >> ../ran.txt"
    with capacity.hold("tests", 1, 0, {"session": "builder-2", "command": "pytest"}):
        assert checks.run_fast_check(config, fast_args(wait=0.3)) == checks.RUNNING_EXIT
        run = checks.running(config)[0]["id"]
        assert checks.check_cancel(config, Namespace(run_id=run, all=False)) == 0
        assert checks.check_watch(config, Namespace(run_id=run, until_failure=False)) == 1
    assert capsys.readouterr().out.splitlines()[-1] == "fast check: cancelled: cancelled by hand"
    assert lines(tmp_path / "ran.txt") == []


def test_a_batch_rounds_checks_hold_a_tests_slot_and_a_round_with_none_free_stops_the_batch(repo, config, stubs,
                                                                                           capsys, tmp_path,
                                                                                           monkeypatch):
    config["gate"].update(review=False, walk=False)
    config["project"]["checks"] = f'echo "slot $COLONY_LOCK_SLOT_TESTS" >> {tmp_path / "slot.txt"}'
    assert batch.run_batch(config, batch_args(repo, "11=card/a")) == 0
    assert lines(tmp_path / "slot.txt") == ["slot 0"]
    assert capacity.holders("tests") == []
    config["locks"] = {"tests": {"slots": 1}}
    monkeypatch.setattr(capacity, "LOCK_WAIT_MINUTES", 0)
    monkeypatch.setattr(capacity, "SLEEP", lambda seconds: None)
    with capacity.hold("tests", 1, 0, {"session": "builder-2", "command": "pytest"}):
        assert batch.run_batch(config, Namespace(**{**vars(batch_args(repo, "12=card/b")), "name": "b2"})) == 1
    assert "round 1's checks found no free slot: the lock tests stayed held for 0 minutes, by builder-2 (pytest)" \
        in capsys.readouterr().out
    assert lines(tmp_path / "slot.txt") == ["slot 0"]


# Task 43: no repeated runs


def test_a_pass_on_the_same_code_is_reused_and_new_code_or_a_new_env_runs_again(card, config, capsys, tmp_path):
    del config["checks"]
    config["project"]["fast_check"] = "echo run >> ../count.txt"
    env = tmp_path / "check.env"
    env.write_text("A=1\n")
    config["project"]["check_env_file"] = str(env)
    assert checks.run_fast_check(config, fast_args()) == 0
    assert checks.run_fast_check(config, fast_args()) == 0
    assert "(reused: it passed on this same code at " in capsys.readouterr().out.splitlines()[-1]
    assert lines(tmp_path / "count.txt") == ["run"]
    assert checks.run_fast_check(config, fast_args(again=True)) == 0
    env.write_text("A=2\n")
    assert checks.run_fast_check(config, fast_args()) == 0
    (card / "src" / "board.py").write_text("an edit not yet committed\n")
    assert checks.run_fast_check(config, fast_args()) == 0
    assert lines(tmp_path / "count.txt") == ["run"] * 4
    git(card, "commit", "-qam", "the edit")  # the same code, now committed: its pass holds
    assert checks.run_fast_check(config, fast_args()) == 0
    assert lines(tmp_path / "count.txt") == ["run"] * 4


def test_the_same_check_on_the_same_code_is_joined_and_newer_code_cancels_the_older_run(card, config, capsys,
                                                                                         tmp_path):
    del config["checks"]
    config["project"]["fast_check"] = "echo run >> ../count.txt; sleep 2"
    assert checks.run_fast_check(config, fast_args(wait=0)) == checks.RUNNING_EXIT
    first = checks.running(config)[0]["id"]
    assert checks.run_fast_check(config, fast_args(wait=0)) == checks.RUNNING_EXIT
    assert f"joining {first}, which already runs this check on this same code" in capsys.readouterr().out
    (card / "new.txt").write_text("newer code\n")
    assert checks.run_fast_check(config, fast_args()) == 0
    out = capsys.readouterr().out
    assert f"cancelled {first}: newer code in the same checkout made it pointless" in out
    older = checks.load(checks.run_files(checks.runs_dir(config), first)[0])
    assert older["status"] == "cancelled" and older["why"].startswith("newer code, ")
    assert lines(tmp_path / "count.txt") == ["run", "run"]


def test_a_later_batch_on_the_same_code_reuses_the_checks_and_the_start_commits_result(repo, config, stubs, tmp_path):
    config["gate"].update(review=False, walk=False)
    config["project"]["checks"] = ("echo run >> ../count.txt; grep -qx a1 a.txt || exit 0; echo 'FAILED "
                                   "tests/test_db.py::test_x'; exit 1")
    config["gate"]["max_rounds"] = 1
    assert batch.run_batch(config, batch_args(repo, "11=card/a")) == 1  # fails, and the start commit runs once
    wt = Path(config["project"]["worktrees"])
    assert lines(wt / "count.txt") == ["run", "run"]
    args = batch_args(repo, "11=card/a")
    args.name = "b2"
    assert batch.run_batch(config, args) == 1
    # The failing round runs again, since only a pass is reused; the start commit's answer is reused.
    assert lines(wt / "count.txt") == ["run"] * 3
    config["project"]["checks"] = "echo run >> ../count.txt"
    for name in ("b3", "b4"):
        args.name = name
        assert batch.run_batch(config, args) == 0
    assert lines(wt / "count.txt") == ["run"] * 4  # b4 reused b3's pass on the same code
    body = (wt / "demo-batch-b4" / ".colony" / "reports" / "b4" / "pr.md").read_text()
    assert "- Round 1: `echo run >> ../count.txt` pass: reused: passed on this same code at " in body


def test_check_run_checks_a_commit_in_its_own_worktree_that_goes_away_after(card, config, capsys, tmp_path):
    config["checks"]["all"] = "all"
    config["project"]["checks"] = f"echo full {{areas}} >> {(tmp_path / 'full.txt').as_posix()}"
    assert checks.check_run(config, run_args(full=True, ref="origin/main")) == checks.RUNNING_EXIT
    run = checks.all_runs(config)[0]
    assert checks.check_watch(config, Namespace(run_id=run["id"], until_failure=False)) == 0
    assert lines(tmp_path / "full.txt") == ["full all"]
    assert not Path(run["root"]).exists()


# Task 44: CI on any commit, from any CI vendor, posted where the team sees it


GH_STUB = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
entry = {"args": args}
if "--body-file" in args:
    entry["stdin"] = sys.stdin.read()
with open(os.environ["GH_LOG"], "a") as log:
    log.write(json.dumps(entry) + "\n")
plan = json.load(open(os.environ["GH_PLAN"]))
counts_path = os.environ["GH_PLAN"] + ".counts"
counts = json.load(open(counts_path)) if os.path.exists(counts_path) else {}
line = " ".join(args)
for pattern, answers in plan.items():
    if pattern in line:
        n = counts.get(pattern, 0)
        counts[pattern] = n + 1
        json.dump(counts, open(counts_path, "w"))
        answer = answers[min(n, len(answers) - 1)]
        print(answer if isinstance(answer, str) else json.dumps(answer))
        sys.exit(0)
'''


@pytest.fixture
def gh(tmp_path, monkeypatch, repo):
    """A stub gh that answers from a plan, {pattern in its args: [answers, one per call, the last repeating]}, and
    logs each call; returns a function that sets the plan and one that reads the calls."""
    folder = tmp_path / "gh-bin"
    folder.mkdir()
    (folder / "gh").write_text(GH_STUB)
    (folder / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GH_LOG", str(tmp_path / "gh.log"))
    monkeypatch.setenv("GH_PLAN", str(tmp_path / "gh-plan.json"))
    monkeypatch.setattr(checks, "SLEEP", lambda seconds: None)
    monkeypatch.chdir(repo)

    def plan(answers: dict) -> None:
        (tmp_path / "gh-plan.json").write_text(json.dumps(answers))
        (tmp_path / "gh-plan.json.counts").unlink(missing_ok=True)

    def calls() -> list[dict]:
        log = tmp_path / "gh.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return plan, calls


def ci_args(**values):
    """The args the parser makes for `colony ci`."""
    return Namespace(**{"ref": None, "again": False, "no_start": False, "no_watch": False, "until_failure": False,
                        "no_post": False, "issue": None, "dry_run": False, **values})


def check(name, status="completed", conclusion="success", url=""):
    return {"name": name, "status": status, "conclusion": conclusion if status == "completed" else None,
            "html_url": url or f"https://ci.example/{name}"}


def test_ci_starts_on_a_commit_no_branch_holds_watches_it_live_and_posts_on_its_pull_request(repo, config, gh, capsys):
    plan, calls = gh
    commit(repo, {"a.txt": "local\n"}, "not pushed yet")
    sha = git(repo, "rev-parse", "HEAD")
    plan({"check-runs": [{"check_runs": []}, {"check_runs": [check("lint"), check("tests", "in_progress")]},
                         {"check_runs": [check("lint"), check("tests", conclusion="failure")]}],
          "/status": [{"statuses": []}], "/pulls": [[{"number": 7, "state": "open"}]], "run list": [[]],
          "pr comment": [""]})
    assert checks.run_ci(config, ci_args()) == 1
    out = capsys.readouterr().out
    assert f"ci: pushed {sha[:9]} to colony-ci/{sha[:9]} on origin, which starts CI that runs on a push" in out
    assert out.index(f"ci {sha[:9]}: lint pass") < out.index(f"ci {sha[:9]}: first failure: tests "
                                                             "https://ci.example/tests")
    assert "ci: posted on pull request #7" in out and out.splitlines()[-1] == "ci: failed, 1 of 2 checks"
    posted = next(c for c in calls() if c["args"][:2] == ["pr", "comment"])
    assert posted["args"][2] == "7" and posted["stdin"].startswith(f"CI on `{sha[:9]}`: **failed**, 1 of 2 checks")
    assert "| tests | [fail](https://ci.example/tests) |" in posted["stdin"]
    # The branch it pushed is gone once CI ended, and the ledger keeps the result.
    assert git(repo.parent / "origin.git", "branch", "--list", "colony-ci/*") == ""
    assert checks.lookup(checks.colony_home(config), checks.ci_key(sha))["result"] == "fail"


def test_ci_already_on_a_commit_is_watched_not_started_and_a_pass_is_never_watched_twice(repo, config, gh, capsys):
    plan, calls = gh
    sha = git(repo, "rev-parse", "HEAD")
    plan({"check-runs": [{"check_runs": [check("build")]}],
          "/status": [{"statuses": [{"context": "ci/other-vendor", "state": "success", "target_url": "u"}]}],
          "/pulls": [[]], "run list": [[]], "/comments": [""]})
    assert checks.run_ci(config, ci_args()) == 0
    out = capsys.readouterr().out
    assert f"ci: 2 checks already run on {sha[:9]}, so none starts again; watching them" in out
    assert "ci: posted on commit" in out and out.splitlines()[-1] == "ci: passed, 2 checks"
    assert any(c["args"][:3] == ["api", "-X", "POST"] for c in calls())
    assert git(repo.parent / "origin.git", "branch", "--list", "colony-ci/*") == ""  # nothing pushed
    before = len(calls())
    assert checks.run_ci(config, ci_args()) == 0
    assert f"ci: passed on {sha[:9]} already, at " in capsys.readouterr().out
    assert len(calls()) == before


def test_ci_cancels_the_runs_on_older_commits_of_the_branch_and_leaves_the_rest(repo, config, gh):
    plan, calls = gh
    older = git(repo, "rev-parse", "HEAD")
    commit(repo, {"a.txt": "newer\n"}, "newer")
    newer = git(repo, "rev-parse", "HEAD")
    plan({"run list": [[{"databaseId": 1, "headSha": older, "status": "in_progress", "url": "u1"},
                        {"databaseId": 2, "headSha": "f" * 40, "status": "in_progress", "url": "u2"},
                        {"databaseId": 3, "headSha": older, "status": "completed", "url": "u3"},
                        {"databaseId": 4, "headSha": newer, "status": "queued", "url": "u4"}]],
          "run cancel": [""]})
    assert checks.cancel_superseded(config, repo, "main", newer) == [f"{older[:9]} (u1)"]
    assert [c["args"][:3] for c in calls() if c["args"][:2] == ["run", "cancel"]] == [["run", "cancel", "1"]]
    config["ci"] = {"cancel_superseded": False}
    assert checks.cancel_superseded(config, repo, "main", newer) == []


def test_ci_starts_with_the_projects_own_command_and_until_failure_returns_at_the_first_failing_check(
        repo, config, gh, capsys, tmp_path):
    plan, calls = gh
    sha = git(repo, "rev-parse", "HEAD")
    config["ci"] = {"start": f"echo {{sha}} {{branch}} > {(tmp_path / 'started.txt').as_posix()}"}
    plan({"check-runs": [{"check_runs": []},
                         {"check_runs": [check("tests", conclusion="failure"), check("e2e", "in_progress")]}],
          "/status": [{"statuses": []}], "/pulls": [[{"number": 9, "state": "open"}]], "run list": [[]],
          "pr comment": [""]})
    assert checks.run_ci(config, ci_args(until_failure=True)) == 1
    assert (tmp_path / "started.txt").read_text() == f"{sha} main\n"
    out = capsys.readouterr().out
    assert f"ci {sha[:9]}: first failure: tests" in out
    posted = next(c for c in calls() if c["args"][:2] == ["pr", "comment"])["stdin"]
    assert "The other checks were still running when this was posted." in posted
    assert checks.lookup(checks.colony_home(config), checks.ci_key(sha)) is None  # not over, so nothing kept


def test_ci_says_how_to_start_it_when_no_check_ever_shows(repo, config, gh, capsys):
    plan, _ = gh
    commit(repo, {"a.txt": "local\n"}, "not pushed yet")
    config["ci"] = {"start_minutes": 0.0001}
    plan({"check-runs": [{"check_runs": []}], "/status": [{"statuses": []}], "run list": [[]]})
    assert checks.run_ci(config, ci_args(no_post=True)) == 1
    assert "set [ci] start to the command that starts your CI" in capsys.readouterr().out
    assert git(repo.parent / "origin.git", "branch", "--list", "colony-ci/*") == ""


@pytest.mark.parametrize("pattern, message", [
    ("ci", "needs {short} or {sha}"), ("staging", "needs {short} or {sha}"),
    ("ci/{branch}-{short}", "takes {short} and {sha} alone, not {branch}"),
    ("ci/{short!r}", "takes {short} and {sha} alone"), ("ci/{short:>12}", "takes {short} and {sha} alone"),
    ("ci/{short", "braces"), ("-ci/{short}", "no plain branch name"), ("ci..{short}", "no plain branch name"),
])
def test_a_ci_branch_that_names_no_commit_or_is_no_plain_branch_is_refused(config, pattern, message):
    """Regression: `colony ci` pushed to, then deleted, whatever [ci] branch named, unchecked, so `branch = "staging"`
    moved staging to a helper's commit and then deleted it; and a pattern with {branch} crashed with a KeyError."""
    config["ci"] = {"branch": pattern}
    with pytest.raises(cli.ColonyError, match=re.escape(message)):
        checks.validate(config)


def test_a_ci_branch_that_a_protected_pattern_or_long_lived_branch_covers_is_refused(config):
    config["ci"] = {"branch": "ci/{short}"}
    checks.validate(config)
    config["safety"] = {"protect": ["ci/*"]}
    with pytest.raises(cli.ColonyError, match="a protected branch"):
        checks.validate(config)
    config["safety"] = {}
    config["ci"] = {"branch": "{short}"}
    config["release"] = {"long_lived": ["0000000*"]}
    with pytest.raises(cli.ColonyError, match="a protected branch"):
        checks.ci_branch(config, "0" * 40)


def test_ci_deletes_its_branch_only_while_origin_still_holds_the_commit_it_pushed(repo, config, gh, monkeypatch):
    """Regression: `colony ci` deleted its branch on origin with a plain --delete, whatever it held by then. It now
    deletes with a lease on the commit it pushed, so a branch someone moved since is left alone."""
    plan, _ = gh
    plan({"check-runs": [{"check_runs": []}], "/status": [{"statuses": []}], "run list": [[]]})
    commit(repo, {"a.txt": "local\n"}, "not pushed yet")
    sha = git(repo, "rev-parse", "HEAD")
    made, origin = f"colony-ci/{sha[:9]}", repo.parent / "origin.git"

    def moved(config, sha, until_failure=False):
        commit(repo, {"a.txt": "moved\n"}, "someone else's commit")
        git(repo, "push", "-q", "--force", "origin", f"HEAD:refs/heads/{made}")
        return "none", [], None
    monkeypatch.setattr(checks, "watch_ci", moved)
    assert checks.run_ci(config, ci_args(no_post=True, ref=sha)) == 1
    assert git(origin, "rev-parse", f"refs/heads/{made}") == git(repo, "rev-parse", "HEAD")  # left alone
    # A branch still at the commit it pushed is deleted: test_ci_says_how_to_start_it_when_no_check_ever_shows.


def test_a_profiles_time_cap_shortens_a_checks_budget_the_stricter_wins(config):
    """Regression: tests.time_cap_minutes in a profile only became a sentence in the prompts, while a check's budget,
    how long it blocks before it goes on in the background, came from [checks] budgets alone."""
    from colony import profile

    config["checks"] = {"budgets": {"full": 600, "fast": 30}}
    assert (checks.check_budget(config, "full"), checks.check_budget(config, "fast")) == (600, 30)
    (profile.config_home() / profile.PERSONAL_FILE).parent.mkdir(parents=True, exist_ok=True)
    (profile.config_home() / profile.PERSONAL_FILE).write_text("[tests]\ntime_cap_minutes = 2\n")
    assert (checks.check_budget(config, "full"), checks.check_budget(config, "fast")) == (120, 30)
    config["checks"] = {"budgets": {"full": 0}}
    assert checks.check_budget(config, "full") == 0  # never blocking is already stricter than any cap


# Settings and the command line


@pytest.mark.parametrize("table, message", [
    ({"checks": {"scope": "some"}}, "[checks] scope is 'related', 'areas', 'full', not 'some'"),
    ({"checks": {"scope": "related"}}, "needs [checks] related"),
    ({"checks": {"related": "pytest"}}, "[checks] related needs {tests} or {files}"),
    ({"checks": {"related": {"nope": "pytest {tests}"}}}, "[checks] areas names no area 'nope'"),
    ({"checks": {"budgets": {"slow": 3}}}, "[checks] budgets names 'slow'"),
    ({"checks": {"caps": {"full": -1}}}, "[checks] caps.full is a number of seconds"),
    ({"checks": {"failure": "("}}, "[checks] failure is not a regular expression"),
    ({"checks": {"locks": ["Test DB"]}}, "[checks] locks is a list of lock names"),
    ({"ci": {"poll_seconds": 0}}, "[ci] poll_seconds is a number above 0"),
])
def test_the_settings_refuse_what_this_version_cant_run(config, table, message):
    with pytest.raises(cli.ColonyError, match=__import__("re").escape(message)):
        checks.validate({**config, **table})
    checks.validate(config)  # the defaults pass: no [checks] or [ci] table at all


def test_the_command_line_routes_check_and_ci_and_the_old_settings_keep_their_meaning(config):
    parser = cli.build_parser()
    watch = parser.parse_args(["check", "watch", "fast-1", "--until-failure"])
    assert watch.run is checks.check_watch and watch.run_id == "fast-1"
    assert parser.parse_args(["check", "status"]).run is checks.check_status
    assert parser.parse_args(["ci", "origin/main", "--no-post"]).run is checks.run_ci
    assert parser.parse_args(["fast-check", "--full"]).run is checks.run_fast_check
    assert parser.parse_args(["batch", "--name", "x", "--card", "1=a", "--full"]).full is True
    # A config with no [checks] related keeps the areas scope, the way Colony always checked.
    assert checks.settings(config)["scope"] == "areas"
    assert checks.settings({**config, "checks": {"related": "pytest {tests}"}})["scope"] == "related"
