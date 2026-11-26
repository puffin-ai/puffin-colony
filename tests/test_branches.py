"""Tests for the project's long-lived branches and `colony branches`: real git repositories (a bare origin with an
integration branch, main, and a release branch, prod, and the lead's clone) and a stand-in `gh` that answers from
files and logs its calls, so nothing reaches GitHub."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from colony import branches, cli

GH_STUB = """#!{python}
import json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
args = sys.argv[1:]
with open(here / "gh-calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["pr", "list"]:
    path = here / f"prs-{args[args.index('--state') + 1]}-{args[args.index('--base') + 1]}.json"
    sys.stdout.write(path.read_text() if path.exists() else "[]")
else:
    sys.stdout.write("https://github.com/acme/demo/pull/30\\n")
"""
CONFIG = """
[project]
name = "demo"
repo = "acme/demo"
base = "main"
release = "{release}"
worktrees = "{worktrees}"
checks = "false"
{project_extra}
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
    """The repositories, the stand-in gh's answers and calls, and the config for each test."""

    def __init__(self, tmp: Path, clone: Path, origin: Path, bin_dir: Path):
        self.tmp, self.clone, self.origin, self.bin = tmp, clone, origin, bin_dir

    def config(self, release: str = "prod", project_extra: str = "", extra: str = "") -> dict:
        path = self.tmp / "colony.toml"
        path.write_text(CONFIG.format(release=release, worktrees=(self.tmp / "wt").as_posix(),
                                      project_extra=project_extra, extra=extra))
        return cli.load_config(path)

    def answer(self, name: str, value) -> None:
        (self.bin / name).write_text(json.dumps(value))

    def gh_calls(self) -> list[list[str]]:
        log = self.bin / "gh-calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def created(self) -> list[list[str]]:
        return [call for call in self.gh_calls() if call[:2] == ["pr", "create"]]

    def on(self, branch: str, files: dict, message: str) -> str:
        """A commit on origin's branch, made in the clone and pushed; the clone goes back to main after."""
        git(self.clone, "fetch", "-q", "origin")
        git(self.clone, "checkout", "-q", "-B", f"work-{branch}", f"origin/{branch}")
        sha = commit(self.clone, files, message)
        git(self.clone, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
        git(self.clone, "checkout", "-q", "main")
        git(self.clone, "fetch", "-q", "origin")
        return sha

    def tip(self, branch: str) -> str:
        """Origin's commit on a branch."""
        return git(self.origin, "rev-parse", f"refs/heads/{branch}")

    def holds(self, branch: str, sha: str) -> bool:
        """Whether origin's branch holds the commit."""
        return subprocess.run(["git", "merge-base", "--is-ancestor", sha, f"refs/heads/{branch}"],
                              cwd=self.origin).returncode == 0

    def sync_branches(self) -> list[str]:
        """Origin's branches that a sync pushed."""
        return git(self.origin, "for-each-ref", "--format=%(refname:short)", "refs/heads/demo/").split()


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A bare origin whose main and prod start equal, the lead's clone (the command runs in it), a temporary HOME,
    and the stand-in gh first on PATH."""
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
    origin, clone = tmp_path / "origin.git", tmp_path / "repo"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(clone))
    commit(clone, {"a.txt": "start\n"}, "base")
    git(clone, "remote", "add", "origin", str(origin))
    git(clone, "push", "-q", "origin", "main", "main:prod")
    git(clone, "fetch", "-q", "origin")
    monkeypatch.chdir(clone)
    return World(tmp_path, clone, origin, bin_dir)


def colony(config: dict, *argv: str) -> int:
    """Run one `colony branches …` command line, as the command line parses it."""
    args = cli.build_parser().parse_args(["branches", *argv])
    return args.run(config, args)


# Which branches are long-lived


def test_the_integration_branch_is_the_base_unless_set(world):
    assert branches.names(world.config()) == branches.Names("main", "main", "prod", ())
    assert branches.names(world.config(project_extra='integration = "dev"')).integration == "dev"


def test_the_release_branch_is_origins_default_branch_when_it_differs_from_the_integration_branch(world):
    config = world.config(release="")
    assert branches.names(config, world.clone).release == ""  # origin's default is main, the integration branch
    assert branches.names(config).release == ""  # with no clone to ask, there is none
    git(world.origin, "symbolic-ref", "HEAD", "refs/heads/prod")
    git(world.clone, "remote", "set-head", "origin", "--delete")  # newer git keeps origin/HEAD from a fetch
    assert branches.default_branch(world.clone) == "prod"  # as origin says
    assert branches.names(config, world.clone).release == "prod"
    git(world.clone, "remote", "set-head", "origin", "main")  # as this clone knows it, which comes first
    assert branches.default_branch(world.clone) == "main"


def test_long_lived_branches_leave_out_the_integration_and_release_branches(world):
    config = world.config(extra='[release]\nlong_lived = ["staging", "main", "prod", " qa ", "staging"]')
    assert branches.names(config).long_lived == ("staging", "qa")


@pytest.mark.parametrize("bad", ['"staging"', "[1]", '[""]'])
def test_long_lived_must_be_a_list_of_branch_names(world, bad):
    with pytest.raises(cli.ColonyError, match=r"\[release\] long_lived is a list of branch names"):
        branches.names(world.config(extra=f"[release]\nlong_lived = {bad}"))


def test_a_release_needs_a_release_branch_other_than_the_integration_branch(world):
    with pytest.raises(cli.ColonyError, match=r"set \[project\] release .* origin's default branch is main"):
        branches.release_names(world.config(release=""), world.clone)
    with pytest.raises(cli.ColonyError, match="the integration branch itself"):
        branches.release_names(world.config(release="main"), world.clone)
    assert branches.release_names(world.config(), world.clone).release == "prod"


def test_a_sync_branch_is_named_after_both_branches_made_safe():
    assert [branches.slug(b) for b in ("dev", "lead/x", "release/2.0", "///")] == ["dev", "lead-x", "release-2.0",
                                                                                  "branch"]
    assert branches.sync_prefix({"project": {"name": "demo"}}, "prod", "release/2.0") == \
        "demo/sync-prod-into-release-2.0"


# Bringing the release branch into a long-lived branch


def test_no_pull_request_when_the_target_already_holds_the_source(world):
    assert branches.sync_pr(world.config(), world.clone, "prod", "main") is None
    assert world.created() == [] and world.sync_branches() == []


def test_sync_opens_a_pull_request_from_a_branch_of_colonys_own_and_never_pushes_the_target(world):
    fix = world.on("prod", {"fix.txt": "a fix made on prod\n"}, "hotfix")
    work = world.on("main", {"b.txt": "next work\n"}, "next work")
    url = branches.sync_pr(world.config(), world.clone, "prod", "main", "The release merged.")
    assert url == "https://github.com/acme/demo/pull/30"
    assert world.tip("main") == work  # the target is untouched: a person merges the pull request
    [branch] = world.sync_branches()
    assert branch.startswith("demo/sync-prod-into-main-")
    assert world.holds(branch, fix) and world.holds(branch, work)
    assert git(world.origin, "log", "-1", "--format=%s", branch) == "Merge prod into main"
    [create] = world.created()
    assert (create[create.index("--base") + 1], create[create.index("--head") + 1]) == ("main", branch)
    assert create[create.index("--title") + 1] == "demo: bring prod into main"
    body = create[create.index("--body") + 1]
    assert body.startswith("This brings `prod` into `main`, so the two long-lived branches stay in step. The release "
                           "merged.")
    assert "## Conflicts" not in body and "A person merges this pull request." in body
    assert body.rstrip().endswith("Assisted-by: claude-code:m")


def test_an_open_sync_pull_request_that_holds_the_source_is_reused(world):
    world.on("prod", {"fix.txt": "a fix\n"}, "hotfix")
    git(world.clone, "push", "-q", "origin", "origin/prod:refs/heads/demo/sync-prod-into-main-1")
    git(world.clone, "fetch", "-q", "origin")
    world.answer("prs-open-main.json", [{"url": "https://github.com/acme/demo/pull/21",
                                         "headRefName": "demo/sync-prod-into-main-1"},
                                        {"url": "https://github.com/acme/demo/pull/22", "headRefName": "ana/other"}])
    before = world.tip("demo/sync-prod-into-main-1")
    assert branches.sync_pr(world.config(), world.clone, "prod", "main") == "https://github.com/acme/demo/pull/21"
    assert world.created() == [] and world.tip("demo/sync-prod-into-main-1") == before


def test_an_open_sync_pull_request_is_brought_up_to_the_newest_source(world):
    world.on("prod", {"fix.txt": "first fix\n"}, "first hotfix")
    git(world.clone, "push", "-q", "origin", "origin/prod:refs/heads/demo/sync-prod-into-main-1")
    world.answer("prs-open-main.json", [{"url": "https://github.com/acme/demo/pull/21",
                                         "headRefName": "demo/sync-prod-into-main-1"}])
    before = world.tip("demo/sync-prod-into-main-1")
    second = world.on("prod", {"fix2.txt": "second fix\n"}, "second hotfix")
    assert branches.sync_pr(world.config(), world.clone, "prod", "main") == "https://github.com/acme/demo/pull/21"
    assert world.created() == []
    assert world.holds("demo/sync-prod-into-main-1", second)
    assert world.holds("demo/sync-prod-into-main-1", before)  # on top of what it held: never forced


def test_a_conflict_pushes_the_source_alone_and_names_each_file_to_settle(world):
    world.on("prod", {"a.txt": "prod's line\n", "c.txt": "prod's c\n"}, "hotfix")
    world.on("main", {"a.txt": "main's line\n", "c.txt": "main's c\n"}, "work")
    before = world.tip("main")
    branches.sync_pr(world.config(), world.clone, "prod", "main")
    assert world.tip("main") == before
    [branch] = world.sync_branches()
    assert world.tip(branch) == world.tip("prod")
    body = world.created()[0][world.created()[0].index("--body") + 1]
    assert "## Conflicts\nMerging `prod` into `main` conflicts in these files, so this branch holds `prod` alone." \
        in body
    assert "- `a.txt`\n- `c.txt`\n" in body


def test_a_conflict_only_in_generated_files_takes_the_sources_side(world):
    config = world.config(project_extra='generated = ["gen/*"]')
    world.on("prod", {"gen/out.txt": "built on prod\n"}, "hotfix")
    work = world.on("main", {"gen/out.txt": "built on main\n"}, "work")
    branches.sync_pr(config, world.clone, "prod", "main")
    [branch] = world.sync_branches()
    assert world.holds(branch, work) and world.holds(branch, world.tip("prod"))
    assert git(world.origin, "show", f"{branch}:gen/out.txt") == "built on prod"
    assert "## Conflicts" not in world.created()[0][world.created()[0].index("--body") + 1]


def test_a_conflict_on_an_open_sync_pull_request_stops_with_the_files_to_settle(world):
    world.on("prod", {"fix.txt": "first fix\n"}, "first hotfix")
    git(world.clone, "push", "-q", "origin", "origin/prod:refs/heads/demo/sync-prod-into-main-1")
    world.answer("prs-open-main.json", [{"url": "https://github.com/acme/demo/pull/21",
                                         "headRefName": "demo/sync-prod-into-main-1"}])
    git(world.clone, "fetch", "-q", "origin")
    git(world.clone, "checkout", "-q", "-B", "settle", "origin/demo/sync-prod-into-main-1")
    commit(world.clone, {"a.txt": "settled by a person\n"}, "settle")
    git(world.clone, "push", "-q", "origin", "HEAD:refs/heads/demo/sync-prod-into-main-1")
    git(world.clone, "checkout", "-q", "main")
    before = world.tip("demo/sync-prod-into-main-1")
    world.on("prod", {"a.txt": "a second fix on prod\n"}, "second hotfix")
    with pytest.raises(cli.ColonyError, match=r"lacks the newest prod, and merging it in conflicts in a\.txt: settle "
                                              r"them on demo/sync-prod-into-main-1"):
        branches.sync_pr(world.config(), world.clone, "prod", "main")
    assert world.tip("demo/sync-prod-into-main-1") == before


# How far each long-lived branch is


def test_drift_counts_what_each_branch_lacks_and_what_sits_on_it_alone(world):
    config = world.config(extra='[release]\nlong_lived = ["staging", "qa"]')
    git(world.clone, "push", "-q", "origin", "origin/prod:refs/heads/staging")
    world.on("prod", {"fix.txt": "fix\n"}, "hotfix one")
    world.on("prod", {"fix2.txt": "fix\n"}, "hotfix two")
    world.on("main", {"b.txt": "work\n"}, "work on main")  # unreleased work is no drift on the integration branch
    world.on("staging", {"s.txt": "only here\n"}, "a staging-only change")
    found = branches.names(config, world.clone)
    assert branches.drift(world.clone, found) == [
        "main: lacks 2 commits of prod",
        "staging: lacks 2 commits of prod, and has 1 commit no other long-lived branch has, which conflict at release "
        "time",
        "qa: not on origin"]


def test_a_branch_in_step_holds_all_of_the_release_branch(world):
    assert branches.drift(world.clone, branches.names(world.config(), world.clone)) == ["main: holds all of prod"]


# colony branches


def test_colony_branches_prints_the_drift_and_opens_nothing(world, capsys):
    world.on("prod", {"fix.txt": "fix\n"}, "hotfix")
    assert colony(world.config()) == 0
    assert capsys.readouterr().out == "release: prod, integration: main\n  main: lacks 1 commit of prod\n"
    assert world.created() == []


def test_colony_branches_sync_opens_a_pull_request_into_each_branch_that_lacks_the_release(world, capsys):
    config = world.config(extra='[release]\nlong_lived = ["staging", "qa"]')
    git(world.clone, "push", "-q", "origin", "main:refs/heads/staging")
    world.on("prod", {"fix.txt": "fix\n"}, "hotfix")
    git(world.clone, "push", "-q", "origin", "origin/prod:refs/heads/main")  # main got the fix already
    assert colony(config, "--sync") == 0
    out = capsys.readouterr().out
    assert "main holds prod: nothing to bring" in out
    assert "staging: https://github.com/acme/demo/pull/30" in out
    [create] = world.created()
    assert create[create.index("--base") + 1] == "staging"


def test_colony_branches_dry_run_runs_nothing(world, capsys):
    config = world.config(extra='[release]\nlong_lived = ["staging"]')
    assert colony(config, "--sync", "--dry-run") == 0
    out = capsys.readouterr().out
    assert out.startswith("colony branches: dry run, nothing runs.\n  $ git fetch origin\n  release: prod, "
                          "integration: main, long-lived: staging\n")
    assert "open a pull request from demo/sync-prod-into-main-<time> into main when it lacks prod" in out
    assert "into staging when it lacks prod" in out
    assert world.gh_calls() == [] and world.sync_branches() == []


def test_a_forks_pull_request_named_like_a_sync_branch_is_never_reused(world):
    world.on("prod", {"fix.txt": "a fix\n"}, "hotfix")
    world.answer("prs-open-main.json", [{"url": "https://github.com/acme/demo/pull/21", "isCrossRepository": True,
                                         "headRefName": "demo/sync-prod-into-main-1"}])
    url = branches.sync_pr(world.config(), world.clone, "prod", "main")
    assert url == "https://github.com/acme/demo/pull/30"
    [create] = world.created()
    assert create[create.index("--head") + 1] != "demo/sync-prod-into-main-1"
