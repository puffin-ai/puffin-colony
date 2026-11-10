"""Tests for `colony merge <branch>`: real git repositories (a bare origin, the person's clone and a teammate's clone)
and a stand-in `gh` that logs its calls, so nothing reaches GitHub."""
import json
import re
import os
import subprocess
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest

from colony import cli, merge

GH_STUB = """#!{python}
import json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
args = sys.argv[1:]
with open(here / "gh-calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["pr", "list"]:
    sys.stdout.write((here / "open-prs.json").read_text() if (here / "open-prs.json").exists() else "[]")
else:
    sys.stdout.write("https://github.com/acme/demo/pull/7\\n")
"""
HACK = """
[project]
mode = "hack"
name = "demo"
repo = "acme/demo"
worktrees = "{worktrees}"
checks = "false"
fast_check = "{fast_check}"
[accounts.ana]
config_dir = "~/.claude"
person = "ana"
[messages]
board = 12
[gate]
merge_after_fast_check = {allowed}
"""
STARTUP = """
[project]
name = "demo"
repo = "acme/demo"
base = "main"
worktrees = "{worktrees}"
checks = "false"
fast_check = "{fast_check}"
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
merge_after_fast_check = {allowed}
[budget]
provider_dollars = 0
"""
PASSES = "grep -q good a.txt"
# A check that fails only on a change holding "bad", printing what a test runner prints, rule lines last.
BRANCH_FAILS = ("if grep -qs bad a.txt b.txt; then echo 'FAIL src/a.test.ts > reads a'; echo ' Tests  1 failed | 4 passed';"
                " echo '⎯⎯⎯⎯⎯⎯⎯⎯'; exit 1; fi; echo ' Tests  5 passed'")


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
    """The repositories, the stand-in gh's calls, and the config for each test."""

    def __init__(self, tmp: Path, clone: Path, origin: Path, teammate: Path, bin_dir: Path):
        self.tmp, self.clone, self.origin, self.teammate, self.bin = tmp, clone, origin, teammate, bin_dir

    def config(self, fast_check: str = PASSES, allowed: bool = True, template: str = HACK) -> dict:
        """A hack config (or the template's), loaded as the command line loads it."""
        path = self.tmp / "colony.toml"
        path.write_text(template.format(worktrees=(self.tmp / "wt").as_posix(), fast_check=fast_check.replace('"', '\\"'),
                                        allowed=str(allowed).lower()))
        return cli.load_config(path)

    def gh_calls(self) -> list[list[str]]:
        """Each call the stand-in gh got."""
        log = self.bin / "gh-calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def origin_main(self) -> str:
        """The base's commit on origin."""
        return git(self.origin, "rev-parse", "main")

    def on_origin_main(self, path: str) -> str:
        """A file's text on origin's base."""
        return git(self.origin, "show", f"main:{path}")

    def branch(self, name: str, files: dict) -> None:
        """Make a local branch off main with one commit, and go back to main."""
        git(self.clone, "checkout", "-q", "-b", name, "main")
        commit(self.clone, files, name)
        git(self.clone, "checkout", "-q", "main")


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A bare origin with main, the person's clone (the command runs in it), a teammate's clone, a temporary HOME,
    and the stand-in gh first on PATH."""
    (tmp_path / "gitconfig").write_text("")
    for key, value in {"GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.test",
                       "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.test"}.items():
        monkeypatch.setenv(key, value)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH_STUB.replace("{python}", sys.executable))
    (bin_dir / "gh").chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    origin, clone, teammate = tmp_path / "origin.git", tmp_path / "repo", tmp_path / "teammate"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(clone))
    commit(clone, {"a.txt": "start\n", "b.txt": "b\n"}, "base")
    git(clone, "remote", "add", "origin", str(origin))
    git(clone, "push", "-q", "origin", "main")
    git(tmp_path, "clone", "-q", str(origin), str(teammate))
    monkeypatch.chdir(clone)
    return World(tmp_path, clone, origin, teammate, bin_dir)


def land(config, branch, dry_run=False):
    """Run `colony merge <branch>`."""
    return merge.run(config, Namespace(branch=branch, dry_run=dry_run))


def test_a_passing_fast_check_lands_the_branch_on_the_base(world, capsys):
    world.branch("ana/login", {"a.txt": "good\n"})
    assert land(world.config(), "ana/login") == 0
    assert capsys.readouterr().out.startswith("merged ana/login into main at ")
    assert world.on_origin_main("a.txt") == "good"
    git(world.clone, "merge-base", "--is-ancestor", "ana/login", "origin/main")  # the branch's commit is on the base
    assert git(world.origin, "log", "-1", "--format=%P", "main").count(" ") == 1  # a merge commit, --no-ff
    assert git(world.origin, "log", "-1", "--format=%s", "main") == "Merge ana/login into main"
    # The last good build goes on the board, after the board's comment count is read; it addresses no one.
    head = world.origin_main()
    assert world.gh_calls() == [["api", "repos/acme/demo/issues/12"],
                                ["issue", "comment", "12", "--repo", "acme/demo", "--body",
                                 f"[ana's Claude] [merged] ana/login → main {head[:7]}, fast check passed"]]


def test_a_second_merge_reuses_the_merge_worktree(world, capsys):
    world.branch("ana/login", {"a.txt": "good\n"})
    world.branch("ana/notes", {"b.txt": "notes\n"})
    config = world.config()
    assert land(config, "ana/login") == 0
    (world.tmp / "wt" / "demo-merge" / "left-over.txt").write_text("from the last check\n")
    assert land(config, "ana/notes") == 0
    assert world.on_origin_main("a.txt") == "good" and world.on_origin_main("b.txt") == "notes"
    assert not (world.tmp / "wt" / "demo-merge" / "left-over.txt").exists()


def test_a_failing_fast_check_opens_a_pr_and_leaves_the_base(world, capsys):
    world.branch("ana/broken", {"a.txt": "bad\n"})
    before = world.origin_main()
    assert land(world.config(fast_check=BRANCH_FAILS), "ana/broken") == 1
    out = capsys.readouterr().out
    assert "not merged: the fast check failed twice on the merged result: Tests 1 failed | 4 passed" in out
    assert out.strip().endswith("Pull request: https://github.com/acme/demo/pull/7")
    assert world.origin_main() == before
    assert git(world.origin, "rev-parse", "ana/broken") == git(world.clone, "rev-parse", "ana/broken")  # pushed
    create = [call for call in world.gh_calls() if call[:2] == ["pr", "create"]]
    assert len(create) == 1
    args = create[0]
    assert (args[args.index("--base") + 1], args[args.index("--head") + 1]) == ("main", "ana/broken")
    body = args[args.index("--body") + 1]
    assert "the fast check failed twice on the merged result: Tests 1 failed | 4 passed" in body
    assert "full log" not in body  # a path on this computer means nothing on GitHub


def test_a_failed_check_names_its_failing_tests_and_keeps_the_whole_log(world, capsys):
    world.branch("ana/broken", {"a.txt": "bad\n"})
    land(world.config(fast_check=BRANCH_FAILS), "ana/broken")
    out = capsys.readouterr().out
    assert "failing: FAIL src/a.test.ts > reads a" in out and "⎯" not in out
    log = Path(re.search(r"full log: (\S+\.log)", out)[1])
    assert "Tests  1 failed | 4 passed" in log.read_text()


def test_a_check_that_fails_once_then_passes_lands_and_names_the_flaky_test(world, capsys):
    ran = (world.tmp / "ran").as_posix()
    flaky = f"if [ -f {ran} ]; then echo 'Tests 5 passed'; else touch {ran}; echo 'FAIL src/t.test.ts > timer'; exit 1; fi"
    world.branch("ana/login", {"a.txt": "good\n"})
    assert land(world.config(fast_check=flaky), "ana/login") == 0
    out = capsys.readouterr().out
    assert "the fast check passed on its second run (Tests 5 passed)" in out
    assert "FAIL src/t.test.ts > timer" in out and "flaky" in out
    assert world.on_origin_main("a.txt") == "good"


def test_a_base_that_fails_on_its_own_opens_no_pr_and_warns_the_team_once(world, capsys):
    always = "echo 'FAIL src/old.test.ts > was red'; echo 'Tests 1 failed'; exit 1"
    world.branch("ana/login", {"a.txt": "good\n"})
    config = world.config(fast_check=always)
    assert land(config, "ana/login") == 1
    out = capsys.readouterr().out
    assert "main itself fails the fast check" in out and "ana/login is not to blame" in out
    assert not any(call[:2] == ["pr", "create"] for call in world.gh_calls())
    posts = [call for call in world.gh_calls() if call[:2] == ["issue", "comment"]]
    assert len(posts) == 1 and "@all urgent: main " in posts[0][-1] and "src/old.test.ts" in posts[0][-1]
    assert land(config, "ana/login") == 1  # the same red base: no second post
    assert len([call for call in world.gh_calls() if call[:2] == ["issue", "comment"]]) == 1


def test_a_base_colony_landed_green_is_never_checked_again(world, capsys):
    runs = world.tmp / "runs"
    config = world.config(fast_check=f"echo run >> {runs.as_posix()}; " + BRANCH_FAILS)
    world.branch("ana/login", {"a.txt": "good\n"})
    world.branch("ana/broken", {"b.txt": "bad\n"})
    assert land(config, "ana/login") == 0
    assert land(config, "ana/broken") == 1
    assert runs.read_text().count("run") == 3  # one pass, then two failing runs, and no run of the base


def test_a_conflict_opens_a_pr_and_leaves_the_base(world, capsys):
    world.branch("ana/clash", {"a.txt": "good, from ana\n"})
    commit(world.teammate, {"a.txt": "from the teammate\n"}, "teammate")
    git(world.teammate, "push", "-q", "origin", "main")
    before = world.origin_main()
    assert land(world.config(), "ana/clash") == 1
    assert "merging it into main conflicts in a.txt" in capsys.readouterr().out
    assert world.origin_main() == before
    assert any(call[:2] == ["pr", "create"] for call in world.gh_calls())


def test_an_open_pr_for_the_branch_is_reused(world, capsys):
    world.branch("ana/broken", {"a.txt": "bad\n"})
    (world.bin / "open-prs.json").write_text('[{"url": "https://github.com/acme/demo/pull/3"}]')
    assert land(world.config(fast_check=BRANCH_FAILS), "ana/broken") == 1
    assert capsys.readouterr().out.strip().endswith("Pull request: https://github.com/acme/demo/pull/3")
    assert not any(call[:2] == ["pr", "create"] for call in world.gh_calls())


def test_the_base_moving_under_the_check_is_merged_again_and_never_forced(world, capsys):
    world.branch("ana/login", {"a.txt": "good\n"})
    marker = world.tmp / "moved"
    marker, teammate = marker.as_posix(), world.teammate.as_posix()  # a shell command's paths, in TOML too
    teammate_push = (f'if [ ! -f "{marker}" ]; then touch "{marker}"; echo more > "{teammate}/c.txt"; '
                     f'git -C "{teammate}" add c.txt; git -C "{teammate}" commit -qm teammate; '
                     f'git -C "{teammate}" push -q origin main; fi; {PASSES}')
    assert land(world.config(fast_check=teammate_push), "ana/login") == 0
    assert capsys.readouterr().out.startswith("merged ana/login into main at ")
    assert world.on_origin_main("c.txt") == "more"  # the teammate's commit stays on the base
    assert world.on_origin_main("a.txt") == "good"


def test_a_base_that_keeps_moving_asks_for_another_merge_and_opens_no_pr(world, capsys, monkeypatch):
    world.branch("ana/login", {"a.txt": "good\n"})
    monkeypatch.setattr(merge, "TRIES", 1)
    teammate = world.teammate.as_posix()  # a shell command's path, in TOML too
    teammate_push = (f'echo more >> "{teammate}/c.txt"; git -C "{teammate}" add c.txt; '
                     f'git -C "{teammate}" commit -qm teammate; git -C "{teammate}" push -q origin main; '
                     f'{PASSES}')
    assert land(world.config(fast_check=teammate_push), "ana/login") == 1
    out = capsys.readouterr().out
    assert "main moved on 1 times while the fast check ran: run `colony merge ana/login` again" in out
    assert not any(call[:2] == ["pr", "create"] for call in world.gh_calls())  # a collision is no reason for a PR


def test_a_branch_already_on_the_base_has_nothing_to_push(world, capsys):
    git(world.clone, "branch", "ana/same", "main")
    before = world.origin_main()
    assert land(world.config(), "ana/same") == 0
    assert "ana/same is already in main: nothing to push" in capsys.readouterr().out
    assert world.origin_main() == before
    assert world.gh_calls() == []  # nothing landed, so the board hears nothing


def test_a_board_that_refuses_the_line_never_fails_a_landed_merge(world, capsys):
    world.branch("ana/login", {"a.txt": "good\n"})
    (world.bin / "gh").write_text("#!/bin/sh\necho 'HTTP 502' >&2\nexit 1\n")
    assert land(world.config(), "ana/login") == 0
    assert world.on_origin_main("a.txt") == "good"
    assert "the branch landed, and the board didn't get the line" in capsys.readouterr().err


def test_origins_copy_wins_when_the_local_branch_is_behind(world, capsys):
    world.branch("ana/login", {"a.txt": "start, then\n"})
    git(world.clone, "push", "-q", "origin", "ana/login")
    git(world.teammate, "fetch", "-q", "origin")
    git(world.teammate, "checkout", "-q", "-b", "ana/login", "origin/ana/login")
    commit(world.teammate, {"a.txt": "good\n"}, "finished on the other computer")
    git(world.teammate, "push", "-q", "origin", "ana/login")
    assert land(world.config(), "ana/login") == 0
    assert world.on_origin_main("a.txt") == "good"


@pytest.mark.parametrize("template, allowed, why", [
    (HACK, False, "[gate] merge_after_fast_check is false, so a person merges it"),
    (STARTUP, True, "startup mode lands work through pull requests and `colony batch`"),  # a yes counts in hack only
])
def test_merging_off_or_another_mode_opens_a_pr_without_merging(world, capsys, template, allowed, why):
    world.branch("ana/login", {"a.txt": "good\n"})
    before = world.origin_main()
    config = world.config(allowed=allowed, template=template)
    assert land(config, "ana/login") == 0
    assert capsys.readouterr().out == f"pull request: https://github.com/acme/demo/pull/7 ({why})\n"
    assert world.origin_main() == before
    assert not (world.tmp / "wt" / "demo-merge").exists()
    assert git(world.origin, "rev-parse", "ana/login") == git(world.clone, "rev-parse", "ana/login")


def test_dry_run_prints_the_plan_and_runs_nothing(world, capsys):
    world.branch("ana/login", {"a.txt": "good\n"})
    before = world.origin_main()
    assert land(world.config(), "ana/login", dry_run=True) == 0
    out = capsys.readouterr().out
    for text in ("colony merge ana/login: dry run, nothing runs.", f"in {world.tmp / 'wt' / 'demo-merge'}, at origin/main",
                 "git merge --no-ff --no-edit ana/login", f"the fast check: $ {PASSES}",
                 "when it passes: $ git push origin HEAD:refs/heads/main",
                 "gh pr create --repo acme/demo --base main --head ana/login"):
        assert text in out, text
    assert "--force" not in out
    assert world.origin_main() == before and world.gh_calls() == []
    assert not (world.tmp / "wt").exists()


def test_a_folder_in_the_way_of_the_merge_worktree_is_never_touched(world):
    world.branch("ana/login", {"a.txt": "good\n"})
    mine = world.tmp / "wt" / "demo-merge"
    mine.mkdir(parents=True)
    (mine / "notes.txt").write_text("mine\n")
    with pytest.raises(cli.ColonyError, match="is in the way: it is not this repo's merge worktree"):
        land(world.config(), "ana/login")
    assert (mine / "notes.txt").read_text() == "mine\n"


@pytest.mark.parametrize("branch, error", [
    ("main", "merge needs a branch to land on main, other than main itself"),
    ("origin/main", "other than main itself"),
    ("--force", "other than main itself"),
    ("ana/nothing", "ana/nothing is neither a local branch nor on origin"),
])
def test_merge_needs_a_branch_that_exists_and_is_not_the_base(world, branch, error):
    with pytest.raises(cli.ColonyError, match=error):
        land(world.config(), branch)
    assert world.gh_calls() == []


def test_merge_is_a_command_on_the_command_line():
    args = cli.build_parser().parse_args(["merge", "ana/login", "--dry-run"])
    assert (args.branch, args.dry_run, args.run) == (["ana/login"], True, cli.merge)


SYNC = HACK.replace('fast_check = "{fast_check}"\n',
                    'fast_check = "{fast_check}"\ngenerated = ["gen/*"]\nregen = "echo rebuilt > gen/out.txt"\n')


def sync(config, branch):
    """Run `colony sync <branch>`."""
    return merge.sync(config, Namespace(branch=branch))


def test_sync_rebuilds_a_conflict_only_in_generated_files(world, capsys):
    (world.clone / "gen").mkdir()
    commit(world.clone, {"gen/out.txt": "start\n"}, "generated")
    git(world.clone, "push", "-q", "origin", "main")
    world.branch("lead/integration", {"gen/out.txt": "the branch's build\n", "b.txt": "the branch\n"})
    git(world.teammate, "pull", "-q")
    commit(world.teammate, {"gen/out.txt": "the base's build\n", "a.txt": "the base\n"}, "teammate")
    git(world.teammate, "push", "-q", "origin", "main")
    assert sync(world.config(template=SYNC), "lead/integration") == 0
    assert "taking origin/main's side of gen/out.txt and running regen" in capsys.readouterr().out
    assert git(world.clone, "show", "lead/integration:gen/out.txt") == "rebuilt"
    assert git(world.clone, "show", "lead/integration:a.txt") == "the base"
    assert git(world.clone, "show", "lead/integration:b.txt") == "the branch"
    git(world.clone, "merge-base", "--is-ancestor", "origin/main", "lead/integration")



def test_sync_passes_untracked_files_by_and_leaves_them_out_of_its_commit(world, capsys):
    (world.clone / "gen").mkdir()
    commit(world.clone, {"gen/out.txt": "start\n"}, "generated")
    git(world.clone, "push", "-q", "origin", "main")
    world.branch("lead/integration", {"gen/out.txt": "the branch's build\n"})
    held = world.tmp / "held"
    git(world.clone, "worktree", "add", "-q", str(held), "lead/integration")
    (held / ".colony" / "reports" / "b1").mkdir(parents=True)
    (held / ".colony" / "reports" / "b1" / "review-1.md").write_text("open: 0\n")
    git(world.teammate, "pull", "-q", "origin", "main")
    commit(world.teammate, {"gen/out.txt": "the base's build\n"}, "teammate")
    git(world.teammate, "push", "-q", "origin", "main")
    assert sync(world.config(template=SYNC), "lead/integration") == 0
    assert "running regen" in capsys.readouterr().out
    assert git(held, "status", "--porcelain") == "?? .colony/"
    assert ".colony" not in git(world.clone, "ls-tree", "-r", "--name-only", "lead/integration")
    (held / "gen" / "out.txt").write_text("a tracked change\n")
    with pytest.raises(cli.ColonyError, match="has uncommitted changes"):
        sync(world.config(template=SYNC), "lead/integration")

def test_sync_stops_on_a_conflict_outside_the_generated_files(world, capsys):
    world.branch("lead/integration", {"a.txt": "from the branch\n"})
    before = git(world.clone, "rev-parse", "lead/integration")
    commit(world.teammate, {"a.txt": "from the teammate\n"}, "teammate")
    git(world.teammate, "push", "-q", "origin", "main")
    assert sync(world.config(template=SYNC), "lead/integration") == 1
    assert "conflicts outside the generated paths, in a.txt" in capsys.readouterr().out
    assert git(world.clone, "rev-parse", "lead/integration") == before
    assert git(world.tmp / "wt" / "demo-merge", "status", "--porcelain") == ""  # the merge was aborted


def test_sync_is_a_command_on_the_command_line():
    args = cli.build_parser().parse_args(["sync", "lead/integration"])
    assert (args.branch, args.run) == ("lead/integration", cli.sync)


ENV_HACK = HACK.replace('fast_check = "{fast_check}"\n', 'fast_check = "{fast_check}"\ncheck_env_file = ".env.local"\n')


def test_a_merge_from_a_helpers_worktree_reads_the_env_file_of_the_main_checkout(world, capsys, monkeypatch):
    world.branch("ana/login", {"a.txt": "good\n"})
    (world.clone / ".env.local").write_text("CHECK_TOKEN=yes\n")  # untracked, so no worktree has a copy
    helper = world.tmp / "ana-login"
    git(world.clone, "worktree", "add", "-q", str(helper), "ana/login")
    monkeypatch.chdir(helper)
    config = world.config(fast_check='test "$CHECK_TOKEN" = yes && grep -q good a.txt', template=ENV_HACK)
    assert land(config, "ana/login") == 0, capsys.readouterr()
    assert world.on_origin_main("a.txt") == "good"


def test_an_env_file_nowhere_says_where_it_looked(world, monkeypatch):
    world.branch("ana/login", {"a.txt": "good\n"})
    config = world.config(template=ENV_HACK)
    with pytest.raises(cli.ColonyError, match=r"check_env_file names \.env\.local, which is in neither"):
        land(config, "ana/login")


def test_a_landed_merge_removes_the_clean_worktrees_of_merged_branches(world, capsys, monkeypatch):
    trees = world.tmp / "wt"
    world.branch("ana/login", {"a.txt": "good\n"})
    world.branch("ana/notes", {"b.txt": "notes\n"})
    world.branch("ana/wip", {"b.txt": "wip\n"})
    for name in ("ana/login", "ana/notes", "ana/wip"):
        git(world.clone, "worktree", "add", "-q", str(trees / f"demo-{name.replace('/', '-')}"), name)
    world.branch("ana/old", {"c.txt": "old\n"})
    old = world.tmp / "ana-old"  # one made beside the clone, as the playbook once said
    git(world.clone, "worktree", "add", "-q", str(old), "ana/old")
    (trees / "demo-ana-wip" / "draft.txt").write_text("not committed\n")
    git(world.clone, "worktree", "add", "-q", "-b", "ana/fresh", str(trees / "demo-ana-fresh"), "main")  # just begun
    config = world.config(fast_check="true")
    assert land(config, "ana/old") == 0
    assert land(config, "ana/login") == 0
    monkeypatch.chdir(trees / "demo-ana-notes")  # the helper merging from its own folder keeps it
    assert land(config, "ana/notes") == 0
    out = capsys.readouterr().out
    assert not (trees / "demo-ana-login").exists() and not old.exists()
    assert (trees / "demo-ana-notes").exists()  # the folder the command runs in
    assert (trees / "demo-ana-wip").exists()  # unmerged, and holding uncommitted work
    assert (trees / "demo-ana-fresh").exists()  # clean, and its tip is on main, but no merge took it: a task just begun
    assert world.clone.exists() and (trees / "demo-merge").exists()
    assert "removed the worktree" in out


def at_a_terminal(monkeypatch, answer="off", login="ana"):
    """The person at their own terminal: stdin is a terminal, they type `answer`, and gh is signed in as `login`."""
    monkeypatch.setattr(merge.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)
    monkeypatch.setattr(merge, "terminal_login", lambda: login)


def test_the_person_can_switch_the_fast_check_off_and_on_and_the_board_hears_each(world, capsys, monkeypatch):
    at_a_terminal(monkeypatch)
    config = world.config(fast_check="false")
    assert merge.gate(config, Namespace(state="off")) == 0
    world.branch("ana/login", {"a.txt": "good\n"})
    assert land(config, "ana/login") == 0
    out = capsys.readouterr().out
    assert "the fast check is off: ana switched it off at " in out
    posts = [call[-1] for call in world.gh_calls() if call[:2] == ["issue", "comment"]]
    assert "@all gate: ana switched the fast check off" in posts[0]
    assert posts[-1].endswith(", fast check off")
    assert merge.gate(config, Namespace(state="on")) == 0
    assert "@all gate: ana switched the fast check back on" in world.gh_calls()[-1][-1]
    world.branch("ana/notes", {"b.txt": "notes\n"})
    assert land(config, "ana/notes") == 1  # the check runs again, and `false` fails


def test_only_the_person_at_a_terminal_switches_the_check_off_never_an_agent(world, monkeypatch):
    config = world.config()
    monkeypatch.setattr(merge.sys.stdin, "isatty", lambda: False, raising=False)  # an agent's shell call
    with pytest.raises(cli.ColonyError, match="only your person switches the fast check off"):
        merge.gate(config, Namespace(state="off"))
    at_a_terminal(monkeypatch)
    monkeypatch.setenv("COLONY_SESSION", "lead")  # a terminal, but a Colony session's
    with pytest.raises(cli.ColonyError, match="only your person switches the fast check off"):
        merge.gate(config, Namespace(state="off"))
    monkeypatch.delenv("COLONY_SESSION")
    at_a_terminal(monkeypatch, answer="yes")  # anything but `off` keeps it on
    assert merge.gate(config, Namespace(state="off")) == 1 and merge.gate_off(config) is None
    with pytest.raises(cli.ColonyError, match="hack mode"):
        merge.gate(world.config(template=STARTUP), Namespace(state="off"))


def test_a_switched_off_check_comes_back_on_by_itself_after_four_hours(world, monkeypatch):
    at_a_terminal(monkeypatch)
    config = world.config()
    assert merge.gate(config, Namespace(state="off")) == 0
    held = merge.gate_off(config)
    assert held and 4 * 3600 - 60 < held["until"] - time.time() <= 4 * 3600
    wait_module = merge.wait
    wait_module.write_json(merge.gate_path(config), {**held, "until": time.time() - 1})
    assert merge.gate_off(config) is None


def test_a_slow_fast_check_gets_a_note_once_a_day(world, capsys, monkeypatch):
    monkeypatch.setattr(merge, "SLOW_CHECK_SECONDS", 0)
    world.branch("ana/login", {"a.txt": "good\n"})
    world.branch("ana/notes", {"b.txt": "notes\n"})
    config = world.config()
    assert land(config, "ana/login") == 0
    assert "note: the fast check took" in capsys.readouterr().out
    assert land(config, "ana/notes") == 0
    assert "note: the fast check took" not in capsys.readouterr().out


def test_a_check_env_that_names_a_remote_database_gets_a_note_with_its_host_alone(world, capsys):
    world.branch("ana/login", {"a.txt": "good\n"})
    (world.clone / ".env.local").write_text("DATABASE_URL=postgres://app:s3cret@ep-cool-1.neon.tech/db\n"
                                            "TEST_DB=postgres://localhost:5432/test\n")
    assert land(world.config(template=ENV_HACK), "ana/login") == 0
    out = capsys.readouterr().out
    assert "note: the fast check's env names a database on ep-cool-1.neon.tech" in out
    assert "s3cret" not in out and "localhost" not in out


# The team's merge turn: one merge at a time across every computer, held on origin

LOCK = "refs/colony/merge-lock"


def hold_the_turn(world, who="bo", branch="bo/export", age_seconds=0) -> str:
    """Another computer holds the team's merge turn: its marker commit on origin's lock ref."""
    env = dict(os.environ)
    if age_seconds:
        stamp = f"{int(time.time()) - age_seconds} +0000"
        env.update(GIT_COMMITTER_DATE=stamp, GIT_AUTHOR_DATE=stamp)
    tree = subprocess.run(["git", "hash-object", "-w", "-t", "tree", "--stdin"], cwd=world.teammate, input="",
                          capture_output=True, text=True, check=True).stdout.strip()
    sha = subprocess.run(["git", "commit-tree", tree, "-m", f"colony merge turn: {who} {branch}"], cwd=world.teammate,
                         env=env, capture_output=True, text=True, check=True).stdout.strip()
    git(world.teammate, "push", "-q", "origin", f"{sha}:{LOCK}")
    return sha


def turn_on_origin(world) -> str:
    return subprocess.run(["git", "rev-parse", "--verify", "--quiet", LOCK], cwd=world.origin,
                          capture_output=True, text=True).stdout.strip()


def test_a_merge_waits_for_the_teams_turn_and_gives_it_back(world, capsys, monkeypatch):
    hold_the_turn(world)
    naps = []

    def nap(seconds):
        naps.append(seconds)
        git(world.origin, "update-ref", "-d", LOCK)  # the other computer's merge finishes
    monkeypatch.setattr(merge, "SLEEP", nap)
    world.branch("ana/login", {"a.txt": "good\n"})
    assert land(world.config(), "ana/login") == 0
    out = capsys.readouterr().out
    assert "waiting for the team's merge turn: bo is merging bo/export" in out and naps == [merge.LOCK_POLL]
    assert turn_on_origin(world) == ""  # given back


def test_a_turn_held_past_its_time_is_taken_over(world, capsys, monkeypatch):
    hold_the_turn(world, age_seconds=3 * 3600)
    monkeypatch.setattr(merge, "SLEEP", lambda seconds: pytest.fail("a stale turn needs no wait"))
    world.branch("ana/login", {"a.txt": "good\n"})
    assert land(world.config(), "ana/login") == 0
    assert "took over the team's merge turn from bo" in capsys.readouterr().out
    assert turn_on_origin(world) == ""


def test_the_turn_is_given_back_when_the_merge_fails(world, capsys):
    world.branch("ana/broken", {"a.txt": "bad\n"})
    assert land(world.config(fast_check=BRANCH_FAILS), "ana/broken") == 1
    assert turn_on_origin(world) == ""


def test_several_branches_land_together_with_one_check(world, capsys):
    runs = world.tmp / "runs"
    config = world.config(fast_check=f"echo run >> {runs.as_posix()}; " + PASSES)
    world.branch("ana/login", {"a.txt": "good\n"})
    world.branch("ana/notes", {"b.txt": "notes\n"})
    assert merge.run(config, Namespace(branch=["ana/login", "ana/notes"], dry_run=False)) == 0
    assert runs.read_text().count("run") == 1
    assert world.on_origin_main("a.txt") == "good" and world.on_origin_main("b.txt") == "notes"
    posts = [call[-1] for call in world.gh_calls() if call[:2] == ["issue", "comment"]]
    assert len(posts) == 2 and "[merged] ana/login" in posts[0] and "[merged] ana/notes" in posts[1]
    assert cli.build_parser().parse_args(["merge", "a/1", "b/2"]).branch == ["a/1", "b/2"]


def test_several_branches_that_fail_together_land_one_at_a_time(world, capsys):
    world.branch("ana/login", {"a.txt": "good\n"})
    world.branch("ana/broken", {"b.txt": "bad\n"})
    assert merge.run(world.config(fast_check=BRANCH_FAILS), Namespace(branch=["ana/login", "ana/broken"],
                                                                     dry_run=False)) == 1
    out = capsys.readouterr().out
    assert "ana/login and ana/broken together: the fast check failed" in out and "so each lands alone" in out
    assert world.on_origin_main("a.txt") == "good"  # the good one landed alone
