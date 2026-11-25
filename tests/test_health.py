"""Tests for `colony health`: real git repositories (a bare origin with a main branch, and the lead's clone, where the
command runs), a stand-in `gh` that answers the merged pull requests from a file, and the code host's checks, the
check runs and the posts stood in for, so nothing reaches GitHub and no suite runs."""
import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from colony import board, checks, cli, freeze, health, tidy, transport, wait

GH_STUB = """#!{python}
import json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
args = sys.argv[1:]
with open(here / "gh-calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["pr", "list"]:
    path = here / f"prs-{args[args.index('--state') + 1]}-{args[args.index('--base') + 1]}.json"
    sys.stdout.write(path.read_text() if path.exists() else "[]")
"""
CONFIG = """
[project]
name = "demo"
repo = "acme/demo"
base = "main"
worktrees = "{worktrees}"
checks = "uv run pytest"
[people]
logins = ["ana", "bob"]
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


def git(cwd, *args) -> str:
    """Run git in cwd and return its output."""
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, files: dict, message: str) -> str:
    """Write the files, commit them, and return the commit."""
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


class World:
    """The repositories, the code host's checks by commit, the stand-in gh's answers, the board's Lead fields and
    each line posted."""

    def __init__(self, tmp: Path, clone: Path, origin: Path, bin_dir: Path):
        self.tmp, self.clone, self.origin, self.bin = tmp, clone, origin, bin_dir
        self.ci: dict[str, list[dict]] = {}  # the code host's checks on each commit
        self.cards: dict[int, str] = {}  # the board's Lead field by card
        self.said: list[tuple[str, str]] = []  # each line posted: to, line

    def config(self, extra: str = "") -> dict:
        path = self.tmp / "colony.toml"
        path.write_text(CONFIG.format(worktrees=(self.tmp / "wt").as_posix(), extra=extra))
        return cli.load_config(path)

    def answer(self, name: str, value) -> None:
        (self.bin / name).write_text(json.dumps(value))

    def gh_calls(self) -> list[list[str]]:
        log = self.bin / "gh-calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def push(self, files: dict, message: str) -> str:
        """Commit the files on main and push it to origin, as a merged pull request would land."""
        sha = commit(self.clone, files, message)
        git(self.clone, "push", "-q", "origin", "main")
        return sha

    def holds(self) -> list[dict]:
        return freeze.read(self.clone)[1]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A bare origin whose main holds a test and the file it covers, the lead's clone (the command runs in it), a
    temporary HOME, the stand-in gh first on PATH, and the code host's checks, the board and the posts stood in."""
    (tmp_path / "gitconfig").write_text("")
    for key, value in {"GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.test",
                       "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.test"}.items():
        monkeypatch.setenv(key, value)
    for key in (cli.SESSION_ENV, "COLONY_LEAD", "COLONY_PERSON"):
        monkeypatch.delenv(key, raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH_STUB.replace("{python}", sys.executable))
    (bin_dir / "gh").chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(checks, "HOME", None)
    origin, clone = tmp_path / "origin.git", tmp_path / "repo"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(clone))
    commit(clone, {"src/engine.py": "x = 1\n", "tests/test_engine.py": "def test_one(): pass\n",
                   "README.md": "demo\n"}, "start")
    git(clone, "remote", "add", "origin", str(origin))
    git(clone, "push", "-q", "origin", "main")
    monkeypatch.chdir(clone)
    made = World(tmp_path, clone, origin, bin_dir)
    monkeypatch.setattr(checks, "ci_state", lambda repo, sha: made.ci.get(sha, []))
    monkeypatch.setattr(board, "find_board", lambda config: {"number": 1, "id": "B", "url": ""})
    monkeypatch.setattr(board, "items", lambda found: [{"number": n, "fields": {"lead": lead}}
                                                       for n, lead in made.cards.items()])
    monkeypatch.setattr(wait, "coordination_issue", lambda repo, name: 5)
    monkeypatch.setattr(tidy, "keep_short", lambda config, number: number)
    monkeypatch.setattr(transport, "send", lambda config, to, line, card=None: made.said.append((to, line)) or 5)
    monkeypatch.setattr(health, "SLEEP", lambda seconds: pytest.fail("the watch slept, but no test asked it to"))
    return made


def run(config, action="run", **values) -> int:
    """`colony health <action>` with the flags given, the others left unset."""
    args = {"branch": None, "source": None, "dry_run": False, "every": None, "rounds": None, **values}
    return health.run(config, Namespace(action=action, **args))


def passed(name="tests") -> list[dict]:
    return [{"name": name, "state": "pass", "url": ""}]


def failed(name: str) -> list[dict]:
    return [{"name": "lint", "state": "pass", "url": ""}, {"name": name, "state": "fail", "url": "https://ci/1"}]


def merged_pr(number: int, sha: str, author: str = "ana", cards=()) -> dict:
    return {"number": number, "title": f"demo: change {number}", "url": f"https://github.com/acme/demo/pull/{number}",
            "headRefName": f"demo/batch-{number}", "author": {"login": author}, "mergeCommit": {"oid": sha},
            "body": "## Cards\n" + "\n".join(f"- Closes #{n}, from `x`" for n in cards)}


def seed_ledger(config: dict, key: str, **entry) -> None:
    """Keep one check result in this computer's ledger, as a finished check run does."""
    checks.record(checks.colony_home(config), key, {"kind": "full", **entry})


def tree_of(world: World, sha: str) -> str:
    return git(world.clone, "rev-parse", f"{sha}^{{tree}}")


# Settings


def test_settings_default_to_auto_hourly_and_the_integration_branch_with_landings_paused(world):
    assert health.settings(world.config(), world.clone) == {"source": "auto", "every_minutes": 60.0,
                                                            "branches": ["main"], "pause": True}


def test_the_default_shared_branch_is_the_integration_branch_and_the_table_sets_each_key(world):
    config = world.config()
    config["project"]["integration"] = "develop"
    assert health.settings(config)["branches"] == ["develop"]
    found = health.settings(world.config('[health]\nbranches = ["main", "staging"]\npause = false\nsource = "ci"\n'
                                         "every_minutes = 15\n"))
    assert found == {"source": "ci", "every_minutes": 15.0, "branches": ["main", "staging"], "pause": False}


@pytest.mark.parametrize("table, match", [
    ('source = "nightly"', r"\[health\] source is"),
    ("every_minutes = 0", r"\[health\] every_minutes is a number of minutes above 0"),
    ("every_minutes = true", r"\[health\] every_minutes is a number of minutes above 0"),
    ('branches = "main"', r"\[health\] branches is a list of branch names"),
    ('branches = [""]', r"\[health\] branches is a list of branch names"),
])
def test_settings_refuse_values_it_cannot_use(world, table, match):
    with pytest.raises(cli.ColonyError, match=match):
        health.settings(world.config(f"[health]\n{table}\n"))


# The verdict on one commit


def test_the_ci_verdict_is_red_with_the_failing_names_pending_green_or_none(world):
    config = world.config()
    world.ci = {"a": failed("unit"), "b": [*passed(), {"name": "e2e", "state": "pending", "url": ""}],
                "c": [*passed(), {"name": "docs", "state": "skipped", "url": ""}]}
    assert health.ci_verdict(config, "a") == ("red", ["unit"])
    assert health.ci_verdict(config, "b") == ("pending", [])
    assert health.ci_verdict(config, "c") == ("green", [])
    assert health.ci_verdict(config, "d") == ("none", [])


def test_the_ci_source_says_none_when_no_ci_reported_and_runs_nothing_here(world, monkeypatch):
    config = world.config()
    monkeypatch.setattr(checks, "check_run", lambda *a: pytest.fail("the ci source ran the suite here"))
    head = git(world.clone, "rev-parse", "HEAD")
    assert health.verdict(config, world.clone, head, "ci") == ("none", [], "CI")


def test_auto_reads_the_full_suite_here_when_ci_reported_nothing(world):
    config = world.config()
    head = git(world.clone, "rev-parse", "HEAD")
    seed_ledger(config, "k1", result="pass", tree=tree_of(world, head), command="uv run pytest", commit=head)
    assert health.verdict(config, world.clone, head, "auto") == ("green", [], "the full suite here")
    world.ci[head] = failed("unit")
    assert health.verdict(config, world.clone, head, "auto") == ("red", ["unit"], "CI")


def test_the_local_verdict_comes_from_the_ledger_by_tree_and_command_the_newest_first(world, monkeypatch):
    config = world.config()
    monkeypatch.setattr(checks, "check_run", lambda *a: pytest.fail("a kept result ran the suite again"))
    head = git(world.clone, "rev-parse", "HEAD")
    tree = tree_of(world, head)
    seed_ledger(config, "other-command", result="pass", tree=tree, command="uv run pytest tests/test_a.py", at=300)
    seed_ledger(config, "other-tree", result="pass", tree="0" * 40, command="uv run pytest", at=300)
    seed_ledger(config, "older", result="pass", tree=tree, command="uv run pytest", at=100)
    seed_ledger(config, "newer", result="fail", tree=tree, command="uv run pytest", at=200,
                failures=["tests/test_engine.py::test_one"], line="1 failed")
    assert health.local_verdict(config, world.clone, head) == ("red", ["tests/test_engine.py::test_one"])
    seed_ledger(config, "newest", result="fail", tree=tree, command="uv run pytest", at=250, line="2 failed")
    assert health.local_verdict(config, world.clone, head) == ("red", ["2 failed"])


def test_the_local_verdict_is_pending_while_a_run_of_the_suite_goes_on(world, monkeypatch):
    config = world.config()
    head = git(world.clone, "rev-parse", "HEAD")
    monkeypatch.setattr(checks, "running", lambda config: [{"tree": tree_of(world, head), "command": "uv run pytest"}])
    monkeypatch.setattr(checks, "check_run", lambda *a: pytest.fail("a second run started beside the first"))
    assert health.local_verdict(config, world.clone, head) == ("pending", [])


def test_the_local_verdict_starts_the_full_suite_in_the_background_on_the_commit(world, monkeypatch):
    config = world.config()
    head = git(world.clone, "rev-parse", "HEAD")
    started = []
    monkeypatch.setattr(checks, "check_run", lambda config, args: started.append(args) or checks.RUNNING_EXIT)
    assert health.local_verdict(config, world.clone, head, start=False) == ("none", [])
    assert started == []
    assert health.local_verdict(config, world.clone, head) == ("pending", [])
    [args] = started
    assert (args.full, args.ref, args.wait, args.again, args.dry_run) == (True, head, 0, False, False)


# Red, green and who hears it


def red_world(world: World) -> tuple[str, str, str, str]:
    """main passed at a first commit, then #12 (sam-lead's card) changed the engine and #13 (bob's, off the board)
    changed the readme; CI fails on the engine's test at #13's commit. Returns green, #12's, #13's commits, and the
    failure."""
    config = world.config()
    green = git(world.clone, "rev-parse", "HEAD")
    world.ci[green] = passed()
    assert run(config) == 0
    twelve = world.push({"src/engine.py": "x = 2\n"}, "demo: change 12")
    thirteen = world.push({"README.md": "demo, now with more\n"}, "demo: change 13")
    world.cards = {41: "sam-lead"}
    world.answer("prs-merged-main.json", [merged_pr(13, thirteen, author="Bob"),
                                          merged_pr(12, twelve, cards=(41,))])
    failure = "tests/test_engine.py::test_one"
    world.ci[thirteen] = failed(failure)
    return green, twelve, thirteen, failure


def test_a_red_head_holds_the_branch_and_tells_the_likely_causes_lead_and_every_lead(world, capsys):
    config = world.config()
    green, twelve, thirteen, failure = red_world(world)
    world.said.clear()
    assert run(config) == 1
    [held] = world.holds()
    assert (held["branch"], held["kind"], held["sha"], held["green"]) == ("main", "red", thirteen, green)
    assert held["by"] == "ana-lead" and held["until"] == 0
    [(to, line), (everyone, all_line)] = world.said
    assert to == "sam-lead" and line.startswith(f"for sam-lead: red: main fails its checks at {thirteen[:7]}")
    assert "your #12 (demo: change 12) is the likely cause, found by blame on the failing tests" in line
    assert line.endswith("(from ana-lead)")
    assert everyone == "@all" and "new landings pause until it passes, except named fixes" in all_line
    assert "the likely cause is #12 (sam-lead)" in all_line and "#13" not in all_line
    assert all(len(said) <= wait.MAX_LINE for _, said in world.said)
    out = capsys.readouterr().out
    assert f"main at {thirteen[:9]}: red (CI): {failure}" in out


def test_a_red_head_is_told_once_on_this_computer_and_on_any_other(world, capsys):
    config = world.config()
    red_world(world)
    assert run(config) == 1
    world.said.clear()
    assert run(config) == 1  # this computer remembers it told
    health.state_path(config).unlink()  # another computer: nothing remembered, but the hold on origin names the commit
    assert run(config) == 1
    assert world.said == []
    assert capsys.readouterr().out.count("every lead already heard that main is red at") == 2


def test_suspects_are_every_pr_since_the_last_green_when_blame_finds_none(world):
    config = world.config()
    green, twelve, thirteen, _ = red_world(world)
    world.ci[thirteen] = failed("lint: line too long")
    world.said.clear()
    assert run(config) == 1
    told = [to for to, _ in world.said]
    assert told == ["sam-lead", "@bob", "@all"]
    assert "found by the pull requests merged since it last passed" in world.said[0][1]
    assert "the likely cause is #12 (sam-lead), #13 (@bob)" in world.said[-1][1]


def test_blame_names_the_pr_that_changed_the_failing_test_itself(world):
    config = world.config()
    one = world.push({"tests/test_engine.py": "def test_one(): assert False\n"}, "demo: change 20")
    two = world.push({"README.md": "other\n"}, "demo: change 21")
    landed = [{"number": 20, "title": "", "oid": one}, {"number": 21, "title": "", "oid": two}]
    assert [pr["number"] for pr in health.blamed(config, world.clone, landed, ["tests/test_engine.py"])] == [20]
    assert health.blamed(config, world.clone, landed, []) == []


def test_without_a_known_green_the_suspect_is_the_pr_the_head_merged(world):
    config = world.config()
    first = world.push({"README.md": "one\n"}, "demo: change 30")
    head = world.push({"README.md": "two\n"}, "demo: change 31")
    world.answer("prs-merged-main.json", [merged_pr(31, head), merged_pr(30, first)])
    found, how = health.suspects(config, world.clone, "main", head, "", ["lint"])
    assert [pr["number"] for pr in found] == [31]
    assert how == "the pull requests merged since it last passed" and found[0]["leads"] == ["@ana"]


def test_a_green_this_clone_lacks_bounds_nothing_so_the_suspect_is_the_pr_the_head_merged(world):
    """A regression test: a last green this clone lacks, as after a force push, once made every merged pull request
    a suspect."""
    config = world.config()
    first = world.push({"README.md": "one\n"}, "demo: change 30")
    head = world.push({"README.md": "two\n"}, "demo: change 31")
    world.answer("prs-merged-main.json", [merged_pr(31, head), merged_pr(30, first)])
    landed = health.landed_since(config, world.clone, "main", head, "f" * 40)
    assert [pr["number"] for pr in landed] == [31]


def test_failing_paths_reads_the_files_a_failure_names(world):
    assert health.failing_paths(["tests/test_a.py::test_b", "FAILED src/x.test.ts > adds", "lint", "a.py"]) == [
        "tests/test_a.py", "src/x.test.ts", "a.py"]


def test_a_green_head_lifts_the_red_hold_and_tells_every_lead_once(world, capsys):
    config = world.config()
    red_world(world)
    assert run(config) == 1
    fixed = world.push({"src/engine.py": "x = 1\n"}, "demo: the fix")
    world.ci[fixed] = passed()
    world.said.clear()
    assert run(config) == 0
    assert world.holds() == []
    [(to, line)] = world.said
    assert to == "@all" and line.startswith(f"@all green: main passes its checks again at {fixed[:7]}")
    assert health.remembered(config)["main"]["green"] == fixed
    world.said.clear()
    assert run(config) == 0
    assert world.said == []  # still green: nothing new to tell


def test_with_pause_off_a_red_head_holds_nothing_but_is_still_told(world):
    config = world.config("[health]\npause = false\n")
    green = git(world.clone, "rev-parse", "HEAD")
    world.ci[green] = passed()
    assert run(config) == 0
    head = world.push({"src/engine.py": "x = 3\n"}, "demo: change 40")
    world.answer("prs-merged-main.json", [merged_pr(40, head)])
    world.ci[head] = failed("tests/test_engine.py::test_one")
    assert run(config) == 1
    assert world.holds() == []
    assert [to for to, _ in world.said] == ["@ana", "@all"]
    assert "new landings pause" not in world.said[-1][1]
    world.said.clear()
    assert run(config) == 1
    assert world.said == []
    fixed = world.push({"src/engine.py": "x = 1\n"}, "demo: the fix")
    world.ci[fixed] = passed()
    assert run(config) == 0
    [(to, line)] = world.said
    assert to == "@all" and "passes its checks again" in line


def test_pending_checks_say_so_and_exit_running(world, capsys):
    config = world.config()
    head = git(world.clone, "rev-parse", "HEAD")
    world.ci[head] = [{"name": "unit", "state": "pending", "url": ""}]
    assert run(config) == checks.RUNNING_EXIT
    assert f"main at {head[:9]}: its checks are still running (CI)" in capsys.readouterr().out
    assert health.remembered(config)["main"]["verdict"] == "pending"


def test_a_branch_not_on_origin_is_named_and_skipped(world, capsys):
    assert run(world.config(), branch="nope") == 0
    assert "nope: not on origin" in capsys.readouterr().out


# The command


def test_a_helper_may_not_run_or_watch_health(world, monkeypatch):
    monkeypatch.setenv(cli.SESSION_ENV, "builder-1")
    for action in ("run", "watch"):
        with pytest.raises(cli.ColonyError, match="never a helper"):
            run(world.config(), action)
    assert run(world.config(), "status") == 0


def test_the_watch_looks_again_soon_while_pending_and_after_every_minutes_once_settled(world, monkeypatch):
    config = world.config()
    head = git(world.clone, "rev-parse", "HEAD")
    answers = iter([[{"name": "unit", "state": "pending", "url": ""}], passed(), passed()])
    monkeypatch.setattr(checks, "ci_state", lambda repo, sha: next(answers))
    slept = []
    monkeypatch.setattr(health, "SLEEP", slept.append)
    assert run(config, "watch", rounds=3, every=5) == 0
    assert slept == [health.PENDING_SECONDS, 300]
    assert health.remembered(config)["main"] == {**health.remembered(config)["main"], "verdict": "green", "head": head}


def test_the_watch_waits_every_minutes_from_the_config(world, monkeypatch):
    config = world.config("[health]\nevery_minutes = 30\n")
    world.ci[git(world.clone, "rev-parse", "HEAD")] = passed()
    slept = []
    monkeypatch.setattr(health, "SLEEP", slept.append)
    assert run(config, "watch", rounds=2) == 0
    assert slept == [1800]


def test_the_watch_outlives_a_look_that_fails_and_looks_again_soon(world, monkeypatch, capsys):
    """A regression test: a look that failed, as when origin couldn't be reached, once ended the watch."""
    config = world.config()
    world.ci[git(world.clone, "rev-parse", "HEAD")] = passed()
    looks = iter([freeze.Unreadable("origin can't be reached"), cli.ColonyError("git fetch failed"), None])

    def check_branch(config, root, branch, args):
        problem = next(looks)
        if problem:
            raise problem
        return 0
    monkeypatch.setattr(health, "check_branch", check_branch)
    slept = []
    monkeypatch.setattr(health, "SLEEP", slept.append)
    assert run(config, "watch", rounds=3, every=5) == 0
    assert slept == [health.PENDING_SECONDS, health.PENDING_SECONDS]
    err = capsys.readouterr().err
    assert "this look failed, so the watch looks again in 2 minutes: origin can't be reached" in err
    assert "git fetch failed" in err


def test_run_stops_on_a_look_that_fails_with_a_plain_error(world, monkeypatch):
    monkeypatch.setattr(health, "check_branch", lambda *a: (_ for _ in ()).throw(freeze.Unreadable("no route")))
    with pytest.raises(cli.ColonyError, match="origin's merge freeze could not be read: no route"):
        run(world.config())


def test_a_setting_it_cannot_use_stops_the_watch_before_its_first_look(world, monkeypatch):
    monkeypatch.setattr(health, "SLEEP", lambda seconds: pytest.fail("the watch went on with a bad setting"))
    with pytest.raises(cli.ColonyError, match=r"\[health\] source is"):
        run(world.config('[health]\nsource = "nightly"\n'), "watch", branch="main")


def test_status_shows_what_each_branch_last_showed_and_what_is_held(world, capsys):
    config = world.config()
    assert run(config, "status") == 0
    assert capsys.readouterr().out.strip() == "main: not looked at on this computer yet: `colony health run`"
    green, _, thirteen, _ = red_world(world)
    assert run(config) == 1
    capsys.readouterr()
    assert run(config, "status") == 0
    out = capsys.readouterr().out
    assert f"main: red at {thirteen[:9]}, looked at " in out and f"last green {green[:9]}" in out
    assert f"held: main is red: it fails its checks at {thirteen[:7]}" in out


def test_dry_run_prints_the_plan_and_runs_nothing(world, capsys, monkeypatch):
    monkeypatch.setattr(checks, "check_run", lambda *a: pytest.fail("a dry run ran the suite"))
    assert run(world.config(), dry_run=True) == 0
    out = capsys.readouterr().out
    assert out.startswith("colony health: dry run, nothing runs.")
    assert "for main: read the verdict on the head commit from CI, else the full suite here" in out
    assert "the suite being `uv run pytest`" in out and "pause landings until it passes" in out
    assert world.gh_calls() == [] and world.said == [] and world.holds() == []
    assert not health.state_path(world.config()).exists()
