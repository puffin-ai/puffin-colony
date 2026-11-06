"""Tests for `colony release`: real git repositories (a bare origin with a base and a release branch, and the lead's
clone) and a stand-in `gh` that answers from files and logs its calls, so nothing reaches GitHub."""
import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from colony import cli, release

GH_STUB = """#!{python}
import json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
args = sys.argv[1:]
with open(here / "gh-calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\\n")
def answer(name):
    path = here / name
    sys.stdout.write(path.read_text() if path.exists() else "[]")
if args[:2] == ["pr", "list"]:
    answer(f"prs-{args[args.index('--state') + 1]}-{args[args.index('--base') + 1]}.json")
elif args[:2] == ["run", "list"]:
    answer("runs.json")
elif args[:2] == ["run", "view"]:
    answer("run.json")
elif args[:2] == ["run", "watch"]:
    pass
else:
    sys.stdout.write("https://github.com/acme/demo/pull/20\\n")
"""
CONFIG = """
[project]
name = "demo"
repo = "acme/demo"
base = "main"
release = "{release}"
deploy_workflow = "deploy.yml"
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
"""


def git(cwd, *args) -> str:
    """Run git in cwd and return its output."""
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, files: dict, message: str) -> str:
    """Write the files, commit them, and return the commit."""
    for name, text in files.items():
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


class World:
    """The repositories, the stand-in gh's answers and calls, and the config for each test."""

    def __init__(self, tmp: Path, clone: Path, origin: Path, bin_dir: Path):
        self.tmp, self.clone, self.origin, self.bin = tmp, clone, origin, bin_dir

    def config(self, release_branch: str = "prod") -> dict:
        path = self.tmp / "colony.toml"
        path.write_text(CONFIG.format(release=release_branch, worktrees=self.tmp / "wt"))
        return cli.load_config(path)

    def answer(self, name: str, value) -> None:
        (self.bin / name).write_text(json.dumps(value))

    def gh_calls(self) -> list[list[str]]:
        log = self.bin / "gh-calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def created(self) -> list[list[str]]:
        return [call for call in self.gh_calls() if call[:2] == ["pr", "create"]]

    def on_main(self, sha: str) -> str:
        """The commit, pushed to origin's main as the batch merges would."""
        git(self.clone, "push", "-q", "origin", "main")
        return sha


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A bare origin whose main and prod start equal, the lead's clone (the command runs in it), a temporary HOME,
    and the stand-in gh first on PATH."""
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
    origin, clone = tmp_path / "origin.git", tmp_path / "repo"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(clone))
    commit(clone, {"a.txt": "start\n"}, "base")
    git(clone, "remote", "add", "origin", str(origin))
    git(clone, "push", "-q", "origin", "main", "main:prod")
    monkeypatch.chdir(clone)
    return World(tmp_path, clone, origin, bin_dir)


def run(config, after=False, dry_run=False):
    return release.run(config, Namespace(after=after, dry_run=dry_run))


def merged_pr(number: int, sha: str, head: str, cards=()) -> dict:
    return {"number": number, "title": f"demo: batch {number}", "url": f"https://github.com/acme/demo/pull/{number}",
            "headRefName": head, "author": {"login": "ana"}, "mergeCommit": {"oid": sha},
            "body": "## Cards\n" + "\n".join(f"- Closes #{n}, from `x`" for n in cards)}


def test_release_opens_one_pr_into_the_release_branch_listing_the_unreleased_batches(world, capsys):
    shipped = commit(world.clone, {"a.txt": "shipped\n"}, "batch 10")
    git(world.clone, "push", "-q", "origin", "main", "main:prod")  # batch 10 went out in the last release
    fresh = world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    other = world.on_main(commit(world.clone, {"c.txt": "by hand\n"}, "a hand-made pr"))
    world.answer("prs-merged-main.json", [merged_pr(12, fresh, "demo/batch-two", cards=(41, 42)),
                                          merged_pr(11, other, "ana/hand-made"),
                                          merged_pr(10, shipped, "demo/batch-one", cards=(40,))])
    assert run(world.config()) == 0
    assert capsys.readouterr().out.strip() == "release pull request: https://github.com/acme/demo/pull/20"
    [create] = world.created()
    assert (create[create.index("--base") + 1], create[create.index("--head") + 1]) == ("prod", "main")
    assert create[create.index("--title") + 1] == "demo: release main into prod (#12)"
    body = create[create.index("--body") + 1]
    assert "- #12 demo: batch 12" in body and "#10" not in body and "#11" not in body
    assert body.rstrip().endswith("Assisted-by: claude-code:m")


def test_an_open_release_pr_is_reused(world, capsys):
    world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    world.answer("prs-open-prod.json", [{"url": "https://github.com/acme/demo/pull/19"}])
    assert run(world.config()) == 0
    assert capsys.readouterr().out.strip() == "release pull request: https://github.com/acme/demo/pull/19"
    assert world.created() == []


def test_nothing_to_release_when_the_release_branch_holds_the_base(world, capsys):
    assert run(world.config()) == 0
    assert capsys.readouterr().out.strip() == "prod already holds main: nothing to release"
    assert world.created() == []


def test_release_needs_a_release_branch_other_than_the_base(world):
    with pytest.raises(cli.ColonyError, match=r"set \[project\] release"):
        run(world.config(release_branch=""))
    with pytest.raises(cli.ColonyError, match="the base itself"):
        run(world.config(release_branch="main"))


def test_after_refuses_while_the_release_pr_is_open(world):
    world.answer("prs-open-prod.json", [{"url": "https://github.com/acme/demo/pull/20"}])
    with pytest.raises(cli.ColonyError, match="is still open: a person merges it first"):
        run(world.config(), after=True)
    assert git(world.origin, "rev-parse", "main") == git(world.origin, "rev-parse", "prod")


def test_after_merges_the_release_back_and_watches_the_deploy_to_its_end(world, capsys):
    git(world.clone, "fetch", "-q", "origin")
    git(world.clone, "checkout", "-q", "-b", "hotfix", "origin/prod")
    fix = commit(world.clone, {"fix.txt": "a fix made on prod\n"}, "hotfix")
    git(world.clone, "push", "-q", "origin", "hotfix:prod")
    git(world.clone, "checkout", "-q", "main")
    world.on_main(commit(world.clone, {"b.txt": "after the release\n"}, "next batch"))
    world.answer("prs-merged-prod.json", [{"url": "https://github.com/acme/demo/pull/20"}])
    world.answer("runs.json", [{"databaseId": 7, "headSha": fix, "status": "in_progress", "conclusion": "",
                                "url": "https://github.com/acme/demo/actions/runs/7"}])
    world.answer("run.json", {"status": "completed", "conclusion": "success", "url": "x"})
    assert run(world.config(), after=True) == 0
    out = capsys.readouterr().out
    assert "merged origin/prod back into main at " in out
    assert out.strip().endswith("deploy.yml ended: success.")
    git(world.origin, "merge-base", "--is-ancestor", fix, "main")  # the release's fix is back on the base
    assert ["run", "watch", "7", "--repo", "acme/demo", "--exit-status"] in world.gh_calls()


def test_after_reports_a_failed_deploy(world, capsys):
    prod = git(world.origin, "rev-parse", "prod")
    world.answer("prs-merged-prod.json", [{"url": "https://github.com/acme/demo/pull/20"}])
    world.answer("runs.json", [{"databaseId": 8, "headSha": prod, "status": "completed", "conclusion": "failure"}])
    assert run(world.config(), after=True) == 1
    out = capsys.readouterr().out
    assert "main already holds origin/prod: nothing to merge back" in out
    assert out.strip().endswith("deploy.yml ended: failure.")
