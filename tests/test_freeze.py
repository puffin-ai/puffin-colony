"""Tests for `colony freeze` and the merge freeze on origin's refs/colony/holds: real git repositories (a bare
origin, the lead's clone and a teammate's clone), so every hold travels through a real push, and a stand-in `gh`
that logs its calls, so nothing reaches GitHub."""
import json
import os
import subprocess
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest

from colony import cli, freeze, merge, transport

GH_STUB = """#!{python}
import json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
with open(here / "gh-calls.jsonl", "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
sys.stdout.write("[]" if sys.argv[1:3] == ["pr", "list"] else "https://github.com/acme/demo/pull/7\\n")
"""
STARTUP = """
[project]
name = "demo"
repo = "acme/demo"
base = "main"
worktrees = "{worktrees}"
checks = "false"
[accounts.ana]
config_dir = "~/.claude"
person = "ana"
[roles]
lead = {{ model = "m", effort = "high" }}
builder = {{ model = "m", effort = "medium" }}
reviewer = {{ model = "m", effort = "high" }}
walker = {{ model = "m", effort = "medium" }}
fixer = {{ model = "m", effort = "medium" }}
[gate]
rubric = ["bugs"]
max_rounds = 5
walk = false
[budget]
provider_dollars = 0
{extra}
"""
HACK = """
[project]
mode = "hack"
name = "demo"
repo = "acme/demo"
worktrees = "{worktrees}"
checks = "false"
fast_check = "grep -q good a.txt"
[accounts.ana]
config_dir = "~/.claude"
person = "ana"
[messages]
board = 12
[gate]
merge_after_fast_check = true
"""


def git(cwd, *args) -> str:
    """Run git in cwd and return its output."""
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, files: dict, message: str) -> None:
    """Write the files and commit them."""
    for name, text in files.items():
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


class World:
    """The repositories, the lines posted, and the config for each test."""

    def __init__(self, tmp: Path, clone: Path, origin: Path, teammate: Path):
        self.tmp, self.clone, self.origin, self.teammate = tmp, clone, origin, teammate
        self.said: list[tuple[str, str]] = []

    def config(self, template: str = STARTUP, extra: str = "") -> dict:
        """The config, loaded as the command line loads it."""
        path = self.tmp / "colony.toml"
        path.write_text(template.format(worktrees=(self.tmp / "wt").as_posix(), extra=extra))
        return cli.load_config(path)

    def holds_on_origin(self) -> list[dict]:
        """The holds as origin keeps them, read straight from the bare repository."""
        found = subprocess.run(["git", "log", "-1", "--format=%B", freeze.HOLDS_REF], cwd=self.origin,
                               capture_output=True, text=True)
        if found.returncode:
            return []
        return json.loads(found.stdout.partition("\n\n")[2])


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A bare origin with main, the lead's clone (the command runs in it), a teammate's clone, a temporary HOME, the
    stand-in gh first on PATH, and every posted line recorded instead of sent."""
    (tmp_path / "gitconfig").write_text("")
    for key, value in {"GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.test",
                       "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.test"}.items():
        monkeypatch.setenv(key, value)
    for key in (cli.SESSION_ENV, "COLONY_LEAD", cli.PERSON_ENV):
        monkeypatch.delenv(key, raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH_STUB.replace("{python}", sys.executable))
    (bin_dir / "gh").chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    origin, clone, teammate = tmp_path / "origin.git", tmp_path / "repo", tmp_path / "teammate"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(clone))
    commit(clone, {"a.txt": "start\n"}, "base")
    git(clone, "remote", "add", "origin", str(origin))
    git(clone, "push", "-q", "origin", "main")
    git(tmp_path, "clone", "-q", str(origin), str(teammate))
    monkeypatch.chdir(clone)
    made = World(tmp_path, clone, origin, teammate)
    monkeypatch.setattr(transport, "send", lambda config, to, line, card=None: made.said.append((to, line)) or 5)
    return made


def colony(config: dict, *argv: str) -> int:
    """Run one `colony freeze …` command line, as the command line parses it."""
    args = cli.build_parser().parse_args(["freeze", *argv])
    return args.run(config, args)


# The holds on origin


def test_a_hold_put_from_one_clone_is_read_from_another(world):
    freeze.put(world.clone, freeze.hold("freeze", "main", "ana-lead", "the release", time.time() + 3600))
    sha, holds = freeze.read(world.teammate)
    assert sha == git(world.origin, "rev-parse", freeze.HOLDS_REF)
    assert [(h["branch"], h["kind"], h["by"], h["why"]) for h in holds] == [("main", "freeze", "ana-lead",
                                                                             "the release")]
    assert git(world.origin, "log", "-1", "--format=%an", freeze.HOLDS_REF) == "Colony"  # never a person's name


def test_origin_with_no_holds_reads_as_none(world):
    assert freeze.read(world.clone) == ("", [])


def test_a_hold_ends_by_itself_at_its_until(world):
    now = time.time()
    freeze.put(world.clone, freeze.hold("freeze", "main", "ana-lead", "", now + 60))
    holds = freeze.read(world.clone)[1]
    assert freeze.on(holds, "main", now) and freeze.on(holds, "main", now + 61) == []
    red = freeze.hold("red", "main", "ana-lead", "")  # a red hold has no until: it stays until the branch passes
    assert not freeze.ended(red, now + 10 ** 9)


def test_a_change_drops_the_holds_whose_time_is_up(world):
    freeze.put(world.clone, freeze.hold("freeze", "main", "ana-lead", "", time.time() - 1))
    freeze.put(world.clone, freeze.hold("freeze", "dev", "ana-lead", "", time.time() + 3600))
    assert [h["branch"] for h in world.holds_on_origin()] == ["dev"]


def test_put_replaces_the_same_kind_on_the_same_branch_and_keeps_its_named_fixes(world):
    later = time.time() + 3600
    freeze.put(world.clone, freeze.hold("freeze", "main", "ana-lead", "first", later, allow=["ana/fix"]))
    freeze.put(world.clone, freeze.hold("release", "main", "ana-lead", "the release", later))
    freeze.put(world.clone, freeze.hold("freeze", "main", "bob-lead", "second", later, allow=["#12"]))
    holds = world.holds_on_origin()
    assert sorted(h["kind"] for h in holds) == ["freeze", "release"]
    [hand] = [h for h in holds if h["kind"] == "freeze"]
    assert (hand["by"], hand["why"], hand["allow"]) == ("bob-lead", "second", ["ana/fix", "#12"])


def test_lift_removes_only_the_kinds_named(world):
    later = time.time() + 3600
    for kind in ("freeze", "release", "red"):
        freeze.put(world.clone, freeze.hold(kind, "main", "ana-lead", "", later))
    freeze.put(world.clone, freeze.hold("freeze", "dev", "ana-lead", "", later))
    gone = freeze.lift(world.clone, "main", ("freeze", "release"))
    assert sorted(h["kind"] for h in gone) == ["freeze", "release"]
    assert sorted((h["branch"], h["kind"]) for h in world.holds_on_origin()) == [("dev", "freeze"), ("main", "red")]


def test_lifting_the_last_hold_removes_the_ref_from_origin(world):
    freeze.put(world.clone, freeze.hold("freeze", "main", "ana-lead", "", time.time() + 3600))
    freeze.lift(world.clone, "main", ("freeze",))
    assert git(world.origin, "for-each-ref", "refs/colony") == ""
    assert freeze.read(world.teammate) == ("", [])


def test_a_change_another_computer_beat_is_made_again_on_top_of_its_change(world, monkeypatch):
    real_read, raced = freeze.read, []

    def read_then_race(root):
        found = real_read(root)
        if root == world.clone and not raced:  # between this read and its push, the teammate puts a hold
            raced.append(True)
            freeze.put(world.teammate, freeze.hold("freeze", "dev", "bob-lead", "", time.time() + 3600))
        return found
    monkeypatch.setattr(freeze, "read", read_then_race)
    freeze.put(world.clone, freeze.hold("release", "main", "ana-lead", "", time.time() + 3600))
    assert raced
    assert sorted((h["branch"], h["by"]) for h in world.holds_on_origin()) == [("dev", "bob-lead"),
                                                                              ("main", "ana-lead")]


def test_a_change_beaten_every_time_gives_up(world, monkeypatch):
    real_read = freeze.read

    def always_raced(root):
        found = real_read(root)
        if root == world.clone:
            freeze.put(world.teammate, freeze.hold("freeze", "dev", "bob-lead", str(time.time()), time.time() + 3600))
        return found
    monkeypatch.setattr(freeze, "read", always_raced)
    with pytest.raises(cli.ColonyError, match=f"changed {freeze.TRIES} times"):
        freeze.put(world.clone, freeze.hold("release", "main", "ana-lead", "", time.time() + 3600))


def test_holds_on_an_origin_that_cannot_be_reached_are_unreadable(world, capsys):
    git(world.clone, "remote", "set-url", "origin", str(world.tmp / "gone.git"))
    with pytest.raises(freeze.Unreadable):
        freeze.read(world.clone)
    assert freeze.blocking(world.config(), world.clone, "main", [("ana/x",)]) == []  # nothing held
    assert "origin's merge freeze could not be read, so nothing is held" in capsys.readouterr().err


# What a hold lets through


def test_a_hold_lets_through_only_work_it_names_by_branch_or_card():
    held = freeze.hold("freeze", "main", "ana-lead", "", allow=["ana/fix", "#12"])
    assert freeze.allowed(held, [("ana/fix",)])
    assert freeze.allowed(held, [("bob/other", "#12")])
    assert not freeze.allowed(held, [("ana/fix",), ("bob/other", "#13")])  # every piece must be named
    assert not freeze.allowed(freeze.hold("freeze", "main", "ana-lead", ""), [("ana/fix",)])


def test_card_or_branch_names_a_card_by_its_number():
    assert [freeze.card_or_branch(n) for n in ("12", "#12", " ana/fix ")] == ["#12", "#12", "ana/fix"]


def test_refusal_says_who_holds_it_why_until_when_and_how_a_fix_gets_through(world):
    freeze.put(world.clone, freeze.hold("release", "main", "ana-lead", "releasing into prod", time.time() + 3600))
    with pytest.raises(cli.ColonyError) as refused:
        freeze.refuse(world.config(), world.clone, "main", [("bob/x",)], "landing bob/x on main")
    said = str(refused.value)
    assert said.startswith("landing bob/x on main is paused: main is frozen for the release (releasing into prod), "
                           "by ana-lead since ")
    assert ", until " in said and "`colony freeze allow bob/x`" in said
    freeze.refuse(world.config(), world.clone, "dev", [("bob/x",)], "landing bob/x on dev")  # dev isn't held


def test_a_red_hold_is_described_by_its_failing_commit():
    red = freeze.hold("red", "main", "ana-lead", "tests/test_a.py", sha="abc1234def")
    assert freeze.describe(red).startswith("main is red: it fails its checks at abc1234 (tests/test_a.py), since ")


# colony freeze on, off, allow, status and check


def test_freeze_on_holds_the_integration_branch_and_tells_every_lead(world, capsys):
    config = world.config()
    assert colony(config, "on", "--why", "a risky upgrade", "--hours", "2") == 0
    [held] = world.holds_on_origin()
    assert (held["branch"], held["kind"], held["by"], held["why"]) == ("main", "freeze", "ana-lead", "a risky upgrade")
    assert 7100 < held["until"] - held["since"] < 7300
    assert capsys.readouterr().out.startswith("froze main until ")
    [(to, line)] = world.said
    assert to == "@all" and line.startswith("@all freeze: main is frozen until ") and "(a risky upgrade)" in line


def test_freeze_on_lasts_freeze_hours_by_default(world):
    assert colony(world.config(extra="[release]\nfreeze_hours = 3"), "on") == 0
    [held] = world.holds_on_origin()
    assert 3 * 3600 - 100 < held["until"] - held["since"] < 3 * 3600 + 100


def test_freeze_check_exits_1_while_held_and_0_for_a_named_fix(world, capsys):
    config = world.config()
    assert colony(config, "check", "bob/x") == 0
    assert colony(config, "on", "--allow", "12") == 0
    assert colony(config, "check", "bob/x") == 1
    assert colony(config, "check", "12") == 0  # the card named when it froze
    assert colony(config, "allow", "bob/x") == 0
    assert colony(config, "check", "bob/x") == 0
    assert colony(config, "check", "--branch", "dev", "carl/y") == 0
    assert world.holds_on_origin()[0]["allow"] == ["#12", "bob/x"]
    assert world.said[-1][1].startswith("@all freeze: bob/x may land on main as a named fix")


def test_freeze_allow_with_nothing_held_says_so(world, capsys):
    assert colony(world.config(), "allow", "bob/x") == 0
    assert "nothing is frozen on main, so bob/x lands as usual" in capsys.readouterr().out
    assert world.said == []


def test_freeze_status_lists_what_is_held(world, capsys):
    config = world.config()
    assert colony(config, "status") == 0
    assert capsys.readouterr().out.strip() == "nothing is frozen: work lands as usual"
    freeze.put(world.clone, freeze.hold("freeze", "dev", "bob-lead", "", time.time() + 3600))
    assert colony(config, "status") == 0
    assert capsys.readouterr().out.startswith("dev is frozen by hand, by bob-lead since ")
    assert colony(config, "status", "--branch", "main") == 0
    assert capsys.readouterr().out.strip() == "nothing is frozen on main: work lands as usual"


def test_freeze_off_lifts_freezes_and_keeps_a_red_hold_unless_asked(world, capsys):
    config = world.config()
    later = time.time() + 3600
    freeze.put(world.clone, freeze.hold("release", "main", "ana-lead", "", later))
    freeze.put(world.clone, freeze.hold("red", "main", "ana-lead", ""))
    assert colony(config, "off") == 0
    assert [h["kind"] for h in world.holds_on_origin()] == ["red"]
    assert world.said[-1][1].startswith("@all freeze: main is open again")
    assert colony(config, "off") == 0
    assert "main held no freeze: nothing to lift" in capsys.readouterr().out
    assert colony(config, "off", "--red") == 0
    assert world.holds_on_origin() == []


def test_a_helper_may_not_freeze_lift_or_allow(world, monkeypatch):
    config = world.config()
    monkeypatch.setenv(cli.SESSION_ENV, "builder")
    for argv in (["on"], ["off"], ["allow", "bob/x"]):
        with pytest.raises(cli.ColonyError, match="never a helper"):
            colony(config, *argv)
    assert colony(config, "status") == 0 and colony(config, "check", "bob/x") == 0  # reading is fine
    assert world.holds_on_origin() == []


def test_freeze_hours_must_be_a_number_above_0(world):
    assert freeze.freeze_hours(world.config()) == freeze.FREEZE_HOURS
    for bad in ("0", "-1", "true", '"12"'):
        with pytest.raises(cli.ColonyError, match="freeze_hours is a number of hours above 0"):
            freeze.freeze_hours(world.config(extra=f"[release]\nfreeze_hours = {bad}"))


def test_an_unreachable_origin_stops_freeze_with_a_plain_error(world):
    git(world.clone, "remote", "set-url", "origin", str(world.tmp / "gone.git"))
    with pytest.raises(cli.ColonyError, match="origin's merge freeze could not be read"):
        colony(world.config(), "status")


# The guards in colony merge and colony batch


def test_a_hold_stops_colony_merge_before_it_lands_and_a_named_fix_lands(world):
    config = world.config(template=HACK)
    git(world.clone, "checkout", "-q", "-b", "ana/login", "main")
    commit(world.clone, {"a.txt": "good\n"}, "ana/login")
    git(world.clone, "checkout", "-q", "main")
    before = git(world.origin, "rev-parse", "main")
    freeze.put(world.clone, freeze.hold("freeze", "main", "bob-lead", "the release", time.time() + 3600))
    with pytest.raises(cli.ColonyError, match=r"landing ana/login on main is paused: main is frozen by hand"):
        merge.run(config, Namespace(branch="ana/login", dry_run=False))
    assert git(world.origin, "rev-parse", "main") == before
    assert not (world.tmp / "wt" / "demo-merge").exists()  # it stopped before the merge worktree
    freeze.put(world.clone, freeze.hold("freeze", "main", "bob-lead", "the release", time.time() + 3600,
                                        allow=["ana/login"]))
    assert merge.run(config, Namespace(branch="ana/login", dry_run=False)) == 0
    assert git(world.origin, "show", "main:a.txt") == "good"


def test_a_batch_is_refused_unless_every_card_is_a_named_fix(world):
    config = world.config()
    freeze.put(world.clone, freeze.hold("release", "main", "ana-lead", "", time.time() + 3600, allow=["#12"]))
    freeze.guard_batch(config, world.clone, "main", {"12": "ana/fix"})
    with pytest.raises(cli.ColonyError, match=r"a batch into main is paused: .* `colony freeze allow bob/x ana/fix`"):
        freeze.guard_batch(config, world.clone, "main", {"13": "bob/x", "12": "ana/fix"})
    freeze.guard_batch(config, world.clone, "dev", {"13": "bob/x"})  # another branch is not held
