"""Tests for `colony release`: real git repositories (a bare origin with a base and a release branch, and the lead's
clone) and a stand-in `gh` that answers from files and logs its calls, so nothing reaches GitHub."""
import json
import os
import subprocess
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest

from colony import board, checks, cli, freeze, release, tidy, transport, wait

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
elif args[:2] == ["pr", "merge"] and (here / f"fail-merge-{args[2]}").exists():
    sys.stderr.write("could not change the pull request\\n")
    sys.exit(1)
elif args[:2] == ["pr", "create"] and (here / "fail-create").exists():
    sys.stderr.write("could not create the pull request\\n")
    sys.exit(1)
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
"""
NO_FREEZE = "[release]\nfreeze = false\n"


def git(cwd, *args) -> str:
    """Run git in cwd and return its output."""
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, files: dict, message: str, removed=()) -> str:
    """Write the files, remove the ones named, commit, and return the commit."""
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    for name in removed:
        (repo / name).unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


class World:
    """The repositories, the stand-in gh's answers and calls, and the config for each test."""

    def __init__(self, tmp: Path, clone: Path, origin: Path, bin_dir: Path):
        self.tmp, self.clone, self.origin, self.bin = tmp, clone, origin, bin_dir
        self.cards: dict[int, str] = {}  # the board's Lead field by card
        self.said: list[tuple[str, str, int]] = []  # each line posted: to, line, pull requests opened before it
        self.ci: list[dict] = []  # the code host's checks on any commit

    def config(self, release_branch: str = "prod", extra: str = "") -> dict:
        path = self.tmp / "colony.toml"
        path.write_text(CONFIG.format(release=release_branch, worktrees=(self.tmp / "wt").as_posix()) + extra)
        return cli.load_config(path)

    def answer(self, name: str, value) -> None:
        (self.bin / name).write_text(json.dumps(value))

    def gh_calls(self) -> list[list[str]]:
        log = self.bin / "gh-calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def created(self) -> list[list[str]]:
        return [call for call in self.gh_calls() if call[:2] == ["pr", "create"]]

    def body(self) -> str:
        [create] = self.created()
        return create[create.index("--body") + 1]

    def on_main(self, sha: str) -> str:
        """The commit, pushed to origin's main as the batch merges would."""
        git(self.clone, "push", "-q", "origin", "main")
        return sha

    def holds(self) -> list[dict]:
        return freeze.read(self.clone)[1]


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
    monkeypatch.setattr(checks, "HOME", tmp_path / ".colony")
    origin, clone = tmp_path / "origin.git", tmp_path / "repo"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(clone))
    commit(clone, {"a.txt": "start\n", "tests/test_a.py": "def test_a(): pass\n",
                   "tests/test_old.py": "def test_old(): pass\n"}, "base")
    git(clone, "remote", "add", "origin", str(origin))
    git(clone, "push", "-q", "origin", "main", "main:prod")
    monkeypatch.chdir(clone)
    made = World(tmp_path, clone, origin, bin_dir)
    monkeypatch.setattr(board, "find_board", lambda config: {"number": 1, "id": "B", "url": ""})
    monkeypatch.setattr(board, "items", lambda found: [{"number": n, "fields": {"lead": lead}}
                                                       for n, lead in made.cards.items()])
    monkeypatch.setattr(wait, "coordination_issue", lambda repo, name: 5)
    monkeypatch.setattr(tidy, "keep_short", lambda config, number: number)
    monkeypatch.setattr(transport, "send", lambda config, to, line, card=None:
                        made.said.append((to, line, len(made.created()))) or 5)
    monkeypatch.setattr(checks, "ci_state", lambda repo, sha: made.ci)
    return made


def run(config, after=False, dry_run=False, **flags):
    return release.run(config, Namespace(after=after, dry_run=dry_run, **flags))


def merged_pr(number: int, sha: str, head: str, cards=(), body: str = "", login: str = "ana") -> dict:
    return {"number": number, "title": f"demo: batch {number}", "url": f"https://github.com/acme/demo/pull/{number}",
            "headRefName": head, "author": {"login": login}, "mergeCommit": {"oid": sha},
            "body": "## Cards\n" + "\n".join(f"- Closes #{n}, from `x`" for n in cards) + body}


def release_pr(number: int = 19, head: str = "main") -> dict:
    return {"number": number, "url": f"https://github.com/acme/demo/pull/{number}", "headRefName": head}


# Opening the release pull request


def test_release_opens_one_pr_into_the_release_branch_listing_every_unreleased_pull_request(world, capsys):
    shipped = commit(world.clone, {"a.txt": "shipped\n"}, "batch 10")
    git(world.clone, "push", "-q", "origin", "main", "main:prod")  # batch 10 went out in the last release
    fresh = world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    other = world.on_main(commit(world.clone, {"c.txt": "by hand\n"}, "a hand-made pr"))
    world.answer("prs-merged-main.json", [merged_pr(12, fresh, "demo/batch-two", cards=(41, 42)),
                                          merged_pr(11, other, "ana/hand-made"),
                                          merged_pr(10, shipped, "demo/batch-one", cards=(40,))])
    assert run(world.config(extra=NO_FREEZE)) == 0
    assert capsys.readouterr().out.strip() == "release pull request: https://github.com/acme/demo/pull/20"
    [create] = world.created()
    assert (create[create.index("--base") + 1], create[create.index("--head") + 1]) == ("prod", "main")
    assert create[create.index("--title") + 1] == "demo: release main into prod (#11, #12)"
    body = world.body()
    assert body.startswith("Releases `main` into `prod`: 2 pull requests.")
    assert "- #11 demo: batch 11, from @ana" in body and "- #12 demo: batch 12, from @ana" in body
    assert "#10" not in body
    assert body.rstrip().endswith("Assisted-by: claude-code:m")


def test_an_open_release_pr_is_reused(world, capsys):
    world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    world.answer("prs-open-prod.json", [release_pr(19)])
    assert run(world.config()) == 0
    assert capsys.readouterr().out.strip() == "release pull request: https://github.com/acme/demo/pull/19"
    assert world.created() == [] and world.holds() == []


def test_an_open_pr_into_the_release_branch_from_another_branch_is_not_the_release(world):
    world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    world.answer("prs-open-prod.json", [release_pr(18, head="ana/hotfix")])
    assert run(world.config(extra=NO_FREEZE)) == 0
    assert len(world.created()) == 1


def test_nothing_to_release_when_the_release_branch_holds_the_base(world, capsys):
    assert run(world.config()) == 0
    assert capsys.readouterr().out.strip() == "prod already holds main: nothing to release"
    assert world.created() == [] and world.holds() == []


def test_release_needs_a_release_branch_other_than_the_integration_branch(world):
    with pytest.raises(cli.ColonyError, match=r"set \[project\] release"):
        run(world.config(release_branch=""))
    with pytest.raises(cli.ColonyError, match="the integration branch itself"):
        run(world.config(release_branch="main"))


def test_the_release_branch_defaults_to_origins_default_branch(world, capsys):
    git(world.origin, "symbolic-ref", "HEAD", "refs/heads/prod")  # origin's default branch is prod, not main
    world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    assert run(world.config(release_branch="", extra=NO_FREEZE)) == 0
    [create] = world.created()
    assert (create[create.index("--base") + 1], create[create.index("--head") + 1]) == ("prod", "main")


def test_an_integration_branch_other_than_the_base_is_what_a_release_carries(world):
    git(world.clone, "checkout", "-q", "-b", "develop")
    commit(world.clone, {"b.txt": "on develop\n"}, "batch 12")
    git(world.clone, "push", "-q", "origin", "develop")
    config = world.config(extra=NO_FREEZE)
    config["project"]["integration"] = "develop"
    assert run(config) == 0
    [create] = world.created()
    assert create[create.index("--head") + 1] == "develop"
    assert world.body().startswith("Releases `develop` into `prod`")


def test_a_helper_may_not_release(world, monkeypatch):
    monkeypatch.setenv(cli.SESSION_ENV, "builder")
    with pytest.raises(cli.ColonyError, match="never a helper"):
        run(world.config())


# The description


def test_the_description_names_migrations_and_removed_or_changed_tests(world):
    twelve = world.on_main(commit(world.clone, {"db/migrations/0002_add_week.sql": "create table week();\n",
                                                "tests/test_a.py": "def test_a(): assert True\n",
                                                "tests/test_new.py": "def test_new(): pass\n"},
                                  "batch 12", removed=["tests/test_old.py"]))
    thirteen = world.on_main(commit(world.clone, {"c.txt": "plain\n"}, "batch 13"))
    world.answer("prs-merged-main.json", [
        merged_pr(13, thirteen, "demo/batch-three", body="\n\n## Removed tests\n- test_slow was flaky, so it went\n"
                                                         "\n## Migrations\nNone\n"),
        merged_pr(12, twelve, "demo/batch-two")])
    assert run(world.config(extra=NO_FREEZE)) == 0
    body = world.body()
    assert "## Migrations\n- #12: `db/migrations/0002_add_week.sql` (new)\n\n" in body
    assert ("## Tests removed or changed\n- #12: removed `tests/test_old.py`; changed `tests/test_a.py`; 1 new test "
            "file\n- #13: its description says:\n  - From its description: test_slow was flaky, so it went\n") in body


def test_the_description_says_none_when_no_migration_or_test_changed(world):
    twelve = world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    world.answer("prs-merged-main.json", [merged_pr(12, twelve, "demo/batch-two")])
    assert run(world.config(extra=NO_FREEZE)) == 0
    body = world.body()
    assert "## Migrations\nNone.\n" in body and "## Tests removed or changed\nNone.\n" in body


def test_release_migrations_name_the_projects_own_migration_paths(world):
    twelve = world.on_main(commit(world.clone, {"db/changes/0002.rb": "add week\n"}, "batch 12"))
    world.answer("prs-merged-main.json", [merged_pr(12, twelve, "demo/batch-two")])
    assert run(world.config(extra='[release]\nfreeze = false\nmigrations = ["db/changes/*"]\n')) == 0
    assert "## Migrations\n- #12: `db/changes/0002.rb` (new)\n" in world.body()


def test_release_migrations_must_be_a_list_of_paths(world):
    world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    with pytest.raises(cli.ColonyError, match=r"\[release\] migrations is a list"):
        run(world.config(extra='[release]\nmigrations = "db/*"\n'))


def test_the_description_lists_commits_with_no_pull_request_but_not_merges_that_only_bring_the_release_back(world):
    git(world.clone, "fetch", "-q", "origin")
    git(world.clone, "checkout", "-q", "-b", "hotfix", "origin/prod")
    commit(world.clone, {"fix.txt": "a fix made on prod\n"}, "hotfix on prod")
    git(world.clone, "push", "-q", "origin", "hotfix:prod")
    git(world.clone, "checkout", "-q", "main")
    direct = world.on_main(commit(world.clone, {"d.txt": "pushed straight to main\n",
                                                "migrations/0003.sql": "alter table week;\n"}, "a direct push"))
    git(world.clone, "merge", "-q", "--no-ff", "-m", "bring prod back", "origin/prod")
    world.on_main("")
    assert run(world.config(extra=NO_FREEZE)) == 0
    body = world.body()
    assert body.startswith("Releases `main` into `prod`: 0 pull requests and 1 other commit.")
    assert f"- `{direct[:7]}` a direct push (no pull request)" in body
    assert "bring prod back" not in body
    assert "- The commits with no pull request: `migrations/0003.sql` (new)" in body


def test_the_description_shows_the_code_hosts_checks_and_this_computers_runs_on_the_release_head(world):
    head = world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    world.ci = [{"name": "build", "state": "fail", "url": "https://ci.example/1"},
                {"name": "lint", "state": "pass", "url": ""}]
    config = world.config(extra=NO_FREEZE)
    tree = git(world.clone, "rev-parse", f"{head}^{{tree}}")
    ledger = checks.ledger_path(checks.colony_home(config))
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({"k": {"result": "pass", "kind": "full", "commit": head, "tree": tree,
                                        "command": "pytest -q", "line": "12 passed", "at": time.time()},
                                  "other": {"result": "fail", "kind": "full", "commit": "f" * 40, "tree": "other",
                                            "command": "pytest -q", "line": "1 failed", "at": time.time()}}))
    assert run(config) == 0
    body = world.body()
    assert f"## Checks on `{head[:9]}`\n- On the code host, failed: 1 of 2 checks, 1 passed.\n" in body
    assert "  - build failed: https://ci.example/1\n" in body
    assert "- On this computer, `pytest -q` passed at " in body and ": 12 passed" in body
    assert "1 failed" not in body


def test_the_description_says_how_to_run_the_checks_when_none_ran_yet(world):
    head = world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    assert run(world.config(extra=NO_FREEZE)) == 0
    assert (f"- No check has run on `{head[:9]}` yet. `colony ci {head[:9]}` starts CI on it, and `colony check run "
            f"--full --ref {head[:9]}` runs the full suite on this computer.") in world.body()


def test_print_prints_the_description_and_opens_nothing(world, capsys):
    twelve = world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    world.answer("prs-merged-main.json", [merged_pr(12, twelve, "demo/batch-two")])
    assert run(world.config(), print=True) == 0
    out = capsys.readouterr().out
    assert out.startswith("Releases `main` into `prod`: 1 pull request.") and "- #12 demo: batch 12" in out
    assert world.created() == [] and world.holds() == [] and world.said == []


def test_refresh_rewrites_the_open_release_prs_description_from_the_work_as_it_is_now(world, capsys):
    twelve = world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    world.answer("prs-merged-main.json", [merged_pr(12, twelve, "demo/batch-two")])
    world.answer("prs-open-prod.json", [release_pr(19)])
    world.ci = [{"name": "build", "state": "pass", "url": ""}]
    assert run(world.config(), refresh=True) == 0
    assert capsys.readouterr().out.strip() == "release pull request: https://github.com/acme/demo/pull/19"
    [edit] = [call for call in world.gh_calls() if call[:2] == ["pr", "edit"]]
    assert edit[2] == "19"
    assert "- #12 demo: batch 12" in edit[edit.index("--body") + 1]
    assert "On the code host, passed: all 1 checks." in edit[edit.index("--body") + 1]
    assert world.created() == []


def test_refresh_with_no_open_release_pr_says_so(world):
    world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    with pytest.raises(cli.ColonyError, match="no release pull request into prod is open"):
        run(world.config(), refresh=True)


def test_a_too_long_description_drops_the_quoted_notes_first_then_is_cut(world):
    config = world.config()
    found = release.branches.Names("main", "main", "prod", ())
    notes = {"migrations": [], "removed": [], "changed": [], "added": 0, "own_migrations": [],
             "own_tests": ["x" * 2000]}
    work = [{"number": n, "title": "t", "leads": ["@ana"], "notes": notes} for n in range(40)]
    carried = {"work": work, "left": [], "commits": [], "head": "a" * 40, "checks": ["- ok"], "partial": False,
               "commit_notes": {**notes, "own_tests": []}}
    text = release.body(config, found, carried, [])
    assert "From its description" not in text and "- #39: its description says:" in text
    many = [{**pr, "title": "y" * 2000} for pr in work]
    text = release.body(config, found, {**carried, "work": many}, [])
    assert len(text) <= release.BODY_MAX + 100 and text.rstrip().endswith("the description was too long)")


# Telling the other leads


def test_release_warns_the_other_leads_once_before_it_opens_the_pr(world):
    mine = world.on_main(commit(world.clone, {"b.txt": "mine\n"}, "batch 12"))
    sams = world.on_main(commit(world.clone, {"c.txt": "sam's\n"}, "batch 13"))
    bobs = world.on_main(commit(world.clone, {"d.txt": "bob's\n"}, "batch 14"))
    world.cards = {41: "ana-lead", 43: "sam-lead"}
    bob = merged_pr(14, bobs, "demo/batch-four", cards=(44,), login="Bob")  # no Lead on the board: by author
    world.answer("prs-merged-main.json", [bob,
                                          merged_pr(13, sams, "demo/batch-three", cards=(43,)),
                                          merged_pr(12, mine, "demo/batch-two", cards=(41,))])
    assert run(world.config(extra=NO_FREEZE)) == 0
    assert world.said == [("@all", "@all releasing main into prod now, which carries your work #13 (sam-lead), #14 "
                                   "(@bob): tell me at once if one must wait (from ana-lead)", 0)]
    body = world.body()
    assert "## Other leads' work\n- #13, from sam-lead\n- #14, from @bob\n" in body
    assert "#12, from" not in body


def test_release_of_only_this_leads_work_posts_no_line_when_nothing_freezes(world):
    mine = world.on_main(commit(world.clone, {"b.txt": "mine\n"}, "batch 12"))
    by_hand = world.on_main(commit(world.clone, {"c.txt": "off the board\n"}, "batch 13"))
    world.cards = {41: "ana-lead"}
    world.answer("prs-merged-main.json", [merged_pr(13, by_hand, "demo/batch-three"),  # ana's login, no card
                                          merged_pr(12, mine, "demo/batch-two", cards=(41,))])
    assert run(world.config(extra=NO_FREEZE)) == 0
    assert world.said == []
    assert "Other leads" not in world.body()


def test_a_long_warning_drops_the_lead_names_to_stay_one_line(world):
    world.cards = {n: f"lead-number-{n}-lead" for n in range(100, 112)}
    theirs = [{"number": n, "leads": [world.cards[n]]} for n in world.cards]
    line = release.warning("main", "prod", theirs, "ana-lead")
    assert len(line) < wait.MAX_LINE and "#100, #101" in line and "lead-number" not in line


# The merge freeze


def test_release_freezes_the_integration_branch_for_every_lead_and_after_lifts_it(world, monkeypatch):
    world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    config = world.config()
    before = time.time()
    assert run(config) == 0
    [held] = world.holds()
    assert (held["branch"], held["kind"], held["by"]) == ("main", "release", "ana-lead")
    assert before + 12 * 3600 - 5 <= held["until"] <= time.time() + 12 * 3600 + 5
    [(to, line, opened)] = world.said
    assert to == "@all" and opened == 0
    assert f"main is frozen until {freeze.when(held['until'])}, so only named fixes land" in line
    with pytest.raises(cli.ColonyError, match="landing ana/fix on main is paused: main is frozen for the release"):
        freeze.guard_merge(config, world.clone, "main", ["ana/fix"])
    world.answer("prs-merged-prod.json", [release_pr(20)])
    world.answer("runs.json", [])
    world.said.clear()
    monkeypatch.setattr(release, "watch", lambda config, root, branch, sleep=None: 0)
    assert run(config, after=True) == 0
    assert world.holds() == []
    assert any("main is open again after the release" in line for _, line, _ in world.said)


def test_a_release_freeze_turns_off_auto_merge_into_the_frozen_branch_and_says_so(world):
    """Audit (seen but not reported, b): GitHub merges a pull request queued with auto-merge by itself once its checks
    pass, during a freeze too, past the merge guard, which checks a merge only when an agent asks for one. The
    release's freeze now turns auto-merge off on the open pull requests into the frozen branch, and its line says so."""
    world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    world.answer("prs-open-main.json", [{"number": 12, "autoMergeRequest": {"mergeMethod": "SQUASH"}},
                                        {"number": 13, "autoMergeRequest": None},
                                        {"number": 14, "autoMergeRequest": {"mergeMethod": "MERGE"}}])
    (world.bin / "fail-merge-14").write_text("")
    assert run(world.config()) == 0
    merges = [call for call in world.gh_calls() if call[:2] == ["pr", "merge"]]
    assert merges == [["pr", "merge", "12", "--repo", "acme/demo", "--disable-auto"],
                      ["pr", "merge", "14", "--repo", "acme/demo", "--disable-auto"]]
    [(to, line, _)] = world.said
    assert "so only named fixes land; auto-merge is off on #12 until you turn it back on; turn auto-merge off by hand " \
           "on #14" in line


def test_a_release_with_no_freeze_leaves_auto_merge_be(world):
    world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    world.answer("prs-open-main.json", [{"number": 12, "autoMergeRequest": {"mergeMethod": "SQUASH"}}])
    assert run(world.config(extra=NO_FREEZE)) == 0
    assert not [call for call in world.gh_calls() if call[:2] == ["pr", "merge"]]


def test_release_freeze_hours_and_freeze_off_come_from_the_release_settings(world):
    world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    assert run(world.config(extra="[release]\nfreeze_hours = 2\n")) == 0
    [held] = world.holds()
    assert abs(held["until"] - (time.time() + 2 * 3600)) < 10


def test_a_release_pr_that_fails_to_open_lifts_its_freeze(world):
    world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    (world.bin / "fail-create").write_text("")
    with pytest.raises(cli.ColonyError, match="could not create the pull request"):
        run(world.config())
    assert world.holds() == []
    assert "main is open again: the release pull request was not opened" in world.said[-1][1]


def test_unreadable_holds_stop_the_release_with_a_plain_error(world, monkeypatch):
    world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))

    def unreadable(root):
        raise freeze.Unreadable("origin can't be reached")
    monkeypatch.setattr(freeze, "read", unreadable)
    with pytest.raises(cli.ColonyError, match="merge freeze could not be read, so nothing was released"):
        run(world.config())
    assert world.created() == []


# A partial release


def test_only_releases_the_chosen_pull_requests_from_a_branch_of_their_own(world, capsys):
    twelve = world.on_main(commit(world.clone, {"b.txt": "twelve\n"}, "batch 12"))
    thirteen = world.on_main(commit(world.clone, {"c.txt": "thirteen\n"}, "batch 13"))
    world.answer("prs-merged-main.json", [merged_pr(13, thirteen, "demo/batch-three"),
                                          merged_pr(12, twelve, "demo/batch-two")])
    prod, main = git(world.origin, "rev-parse", "prod"), git(world.origin, "rev-parse", "main")
    assert run(world.config(), only=[13]) == 0
    branch = f"demo/release-{time.strftime('%Y-%m-%d')}"
    [create] = world.created()
    assert (create[create.index("--base") + 1], create[create.index("--head") + 1]) == ("prod", branch)
    assert create[create.index("--title") + 1] == "demo: release #13 into prod"
    assert git(world.origin, "show", f"{branch}:c.txt") == "thirteen"
    assert subprocess.run(["git", "cat-file", "-e", f"{branch}:b.txt"], cwd=world.origin).returncode != 0
    assert git(world.origin, "rev-parse", f"{branch}^") == prod
    assert (git(world.origin, "rev-parse", "prod"), git(world.origin, "rev-parse", "main")) == (prod, main)
    body = world.body()
    assert body.startswith("Releases a chosen part of `main` into `prod`: 1 pull request.")
    assert "## Left for a later release\n- #12 demo: batch 12, from @ana" in body
    assert world.holds() == []  # the integration branch isn't what goes out, so nothing is frozen


def test_a_second_partial_release_on_one_day_takes_the_next_name(world):
    twelve = world.on_main(commit(world.clone, {"b.txt": "twelve\n"}, "batch 12"))
    world.answer("prs-merged-main.json", [merged_pr(12, twelve, "demo/batch-two")])
    today = f"demo/release-{time.strftime('%Y-%m-%d')}"
    git(world.clone, "push", "-q", "origin", f"origin/prod:refs/heads/{today}")
    git(world.clone, "fetch", "-q", "origin")
    assert run(world.config(), only=[12]) == 0
    [create] = world.created()
    assert create[create.index("--head") + 1] == f"{today}-2"


def test_a_partial_release_pr_is_refreshed_from_its_own_chosen_work(world):
    twelve = world.on_main(commit(world.clone, {"b.txt": "twelve\n"}, "batch 12"))
    thirteen = world.on_main(commit(world.clone, {"c.txt": "thirteen\n"}, "batch 13"))
    world.answer("prs-merged-main.json", [merged_pr(13, thirteen, "demo/batch-three"),
                                          merged_pr(12, twelve, "demo/batch-two")])
    assert run(world.config(), only=[13]) == 0
    branch = f"demo/release-{time.strftime('%Y-%m-%d')}"
    world.answer("prs-open-prod.json", [release_pr(21, head=branch)])
    assert run(world.config(), refresh=True) == 0
    [edit] = [call for call in world.gh_calls() if call[:2] == ["pr", "edit"]]
    text = edit[edit.index("--body") + 1]
    assert "- #13 demo: batch 13" in text and "## Left for a later release\n- #12" in text


def test_lead_releases_that_leads_pull_requests(world):
    twelve = world.on_main(commit(world.clone, {"b.txt": "twelve\n"}, "batch 12"))
    thirteen = world.on_main(commit(world.clone, {"c.txt": "thirteen\n"}, "batch 13"))
    world.cards = {41: "ana-lead", 43: "sam-lead"}
    world.answer("prs-merged-main.json", [merged_pr(13, thirteen, "demo/batch-three", cards=(43,)),
                                          merged_pr(12, twelve, "demo/batch-two", cards=(41,))])
    assert run(world.config(), lead="me") == 0
    [create] = world.created()
    assert create[create.index("--title") + 1] == "demo: release #12 into prod"
    assert world.said == []  # only this lead's work goes, so no other lead hears of it


def test_only_refuses_a_pull_request_that_is_not_unreleased_work(world):
    twelve = world.on_main(commit(world.clone, {"b.txt": "twelve\n"}, "batch 12"))
    world.answer("prs-merged-main.json", [merged_pr(12, twelve, "demo/batch-two")])
    with pytest.raises(cli.ColonyError, match="#99 is not unreleased work"):
        run(world.config(), only=[99])
    with pytest.raises(cli.ColonyError, match="no unreleased pull request is sam-lead's"):
        run(world.config(), lead="sam-lead")
    assert world.created() == []


def test_a_chosen_pull_request_that_needs_earlier_work_stops_and_names_its_files(world):
    twelve = world.on_main(commit(world.clone, {"a.txt": "one\n"}, "batch 12"))
    thirteen = world.on_main(commit(world.clone, {"a.txt": "two\n"}, "batch 13"))
    world.answer("prs-merged-main.json", [merged_pr(13, thirteen, "demo/batch-three"),
                                          merged_pr(12, twelve, "demo/batch-two")])
    prod = git(world.origin, "rev-parse", "prod")
    with pytest.raises(cli.ColonyError, match=r"#13 doesn't apply on prod without the work before it: it conflicts "
                                              r"in a\.txt"):
        run(world.config(), only=[13])
    assert git(world.origin, "rev-parse", "prod") == prod
    assert git(world.origin, "branch", "--list", "demo/release-*") == ""
    assert world.created() == []


# After the release


def test_after_refuses_while_the_release_pr_is_open(world):
    world.answer("prs-open-prod.json", [release_pr(20)])
    with pytest.raises(cli.ColonyError, match="is still open: a person merges it first"):
        run(world.config(), after=True)
    assert git(world.origin, "rev-parse", "main") == git(world.origin, "rev-parse", "prod")


def test_after_refuses_when_no_release_was_ever_merged(world):
    with pytest.raises(cli.ColonyError, match="no release pull request into prod was merged"):
        run(world.config(), after=True)


def test_after_opens_a_pr_that_brings_the_release_back_and_watches_the_deploy_to_its_end(world, capsys):
    git(world.clone, "fetch", "-q", "origin")
    git(world.clone, "checkout", "-q", "-b", "hotfix", "origin/prod")
    fix = commit(world.clone, {"fix.txt": "a fix made on prod\n"}, "hotfix")
    git(world.clone, "push", "-q", "origin", "hotfix:prod")
    git(world.clone, "checkout", "-q", "main")
    main = world.on_main(commit(world.clone, {"b.txt": "after the release\n"}, "next batch"))
    world.answer("prs-merged-prod.json", [release_pr(20)])
    world.answer("runs.json", [{"databaseId": 7, "headSha": fix, "status": "in_progress", "conclusion": "",
                                "url": "https://github.com/acme/demo/actions/runs/7"}])
    world.answer("run.json", {"status": "completed", "conclusion": "success", "url": "x"})
    assert run(world.config(), after=True) == 0
    out = capsys.readouterr().out
    assert "bring prod into main: https://github.com/acme/demo/pull/20 (a person merges it)" in out
    assert out.strip().endswith("deploy.yml ended: success.")
    assert git(world.origin, "rev-parse", "main") == main  # Colony never pushes to the integration branch itself
    [create] = world.created()
    head = create[create.index("--head") + 1]
    assert create[create.index("--base") + 1] == "main" and head.startswith("demo/sync-prod-into-main-")
    git(world.origin, "merge-base", "--is-ancestor", fix, head)  # the release's fix is on the pull request's branch
    git(world.origin, "merge-base", "--is-ancestor", main, head)
    assert ["run", "watch", "7", "--repo", "acme/demo", "--exit-status"] in world.gh_calls()


def test_after_reports_a_failed_deploy(world, capsys):
    prod = git(world.origin, "rev-parse", "prod")
    world.answer("prs-merged-prod.json", [release_pr(20)])
    world.answer("runs.json", [{"databaseId": 8, "headSha": prod, "status": "completed", "conclusion": "failure"}])
    assert run(world.config(), after=True) == 1
    out = capsys.readouterr().out
    assert "main already holds prod: nothing to bring back" in out
    assert out.strip().endswith("deploy.yml ended: failure.")


def test_after_brings_the_release_into_each_long_lived_branch_that_lacks_it(world, capsys):
    git(world.clone, "push", "-q", "origin", "main:staging", "main:qa")
    git(world.clone, "fetch", "-q", "origin")
    git(world.clone, "checkout", "-q", "-b", "hotfix", "origin/prod")
    commit(world.clone, {"fix.txt": "a fix made on prod\n"}, "hotfix")
    git(world.clone, "push", "-q", "origin", "hotfix:prod", "hotfix:qa")  # qa holds the release already
    git(world.clone, "checkout", "-q", "main")
    world.answer("prs-merged-prod.json", [release_pr(20)])
    config = world.config(extra='[release]\nlong_lived = ["staging", "qa", "gone"]\n')
    config["project"]["deploy_workflow"] = ""
    assert run(config, after=True) == 0
    out = capsys.readouterr().out
    bases = [call[call.index("--base") + 1] for call in world.created()]
    assert bases == ["main", "staging"]
    assert "qa already holds prod: nothing to bring back" in out
    assert "gone is not on origin, so nothing was brought into it" in out
    assert out.strip().endswith("No [project] deploy_workflow is set, so there is no deploy to watch.")


# The plan


def test_dry_run_prints_each_plan_and_runs_nothing(world, capsys):
    config = world.config(extra='[release]\nlong_lived = ["staging"]\n')
    assert run(config, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "freeze main for every person's leads for 12 hours" in out
    assert "$ gh pr create --repo acme/demo --base prod --head main" in out
    assert run(config, dry_run=True, after=True) == 0
    out = capsys.readouterr().out
    assert "lift the release's merge freeze on main" in out
    assert "open a pull request from demo/sync-prod-into-staging-<time> into staging" in out
    assert run(config, dry_run=True, only=[12]) == 0
    out = capsys.readouterr().out
    assert "cut demo/release-<date> from origin/prod, and copy #12 onto it" in out and "freeze" not in out
    assert world.gh_calls() == [] and world.holds() == []


# Only the repo's own pull requests, and no secret in the description


def test_a_forks_pull_request_named_after_the_integration_branch_is_never_the_release(world):
    world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    world.answer("prs-open-prod.json", [release_pr(18) | {"isCrossRepository": True}])
    world.answer("prs-merged-prod.json", [release_pr(17) | {"isCrossRepository": True}])
    with pytest.raises(cli.ColonyError, match="no release pull request into prod is open"):
        run(world.config(), refresh=True)
    with pytest.raises(cli.ColonyError, match="no release pull request into prod was merged"):
        run(world.config(), after=True)
    assert run(world.config(extra=NO_FREEZE)) == 0
    assert len(world.created()) == 1 and not [call for call in world.gh_calls() if call[:2] == ["pr", "edit"]]


def test_a_check_command_that_holds_a_secret_stays_out_of_the_description(world):
    head = world.on_main(commit(world.clone, {"b.txt": "fresh\n"}, "batch 12"))
    config = world.config(extra=NO_FREEZE)
    token = "ghp_" + "a" * 36
    ledger = checks.ledger_path(checks.colony_home(config))
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({"k": {"result": "pass", "kind": "full", "commit": head, "tree": "",
                                        "command": f"GH_TOKEN={token} pytest -q", "line": "12 passed",
                                        "at": time.time()}}))
    assert run(config) == 0
    body = world.body()
    assert token not in body
    assert "- On this computer, a check whose command looked like it held a secret, so it stays out, passed" in body
