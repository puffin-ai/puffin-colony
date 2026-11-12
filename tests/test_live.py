"""Tests for colony/live.py: which commit is live, from GitHub's deployments or a `live:` line on the board, and which
merges on the base aren't live yet."""
import json
import subprocess
from argparse import Namespace

import pytest

from colony import cli, live, transport, wait

CONFIG = {"project": {"name": "demo", "repo": "acme/demo", "base": "main", "mode": "hack"},
          "accounts": {"ana": {"config_dir": "~/.claude", "person": "ana"}}, "messages": {"board": 7},
          "people": {"logins": ["ana", "ben"]}}


def git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_the_live_commit_is_githubs_newest_successful_production_deployment(monkeypatch):
    answers = {
        "repos/acme/demo/deployments?per_page=20": [
            {"id": 3, "sha": "c" * 40, "environment": "Production", "created_at": "2026-11-08T10:09:00Z"},
            {"id": 2, "sha": "b" * 40, "environment": "Preview", "created_at": "2026-11-08T10:05:00Z"},
            {"id": 1, "sha": "a" * 40, "environment": "Production", "created_at": "2026-11-08T10:00:00Z"}],
        "repos/acme/demo/deployments/3/statuses?per_page=1": [{"state": "failure", "environment_url": ""}],
        "repos/acme/demo/deployments/1/statuses?per_page=1": [
            {"state": "success", "environment_url": "https://myapp.example", "created_at": "2026-11-08T10:03:00Z"}],
    }
    monkeypatch.setattr(wait, "gh", lambda *args: json.dumps(answers[args[1]]))
    found = live.from_deployments(CONFIG)
    assert (found.sha, found.url, found.at) == ("a" * 40, "https://myapp.example", "2026-11-08T10:03:00Z")
    assert found.source == "GitHub's Production deployment"


def test_a_live_line_on_the_board_names_a_deploy_github_doesnt_know():
    comments = [{"body": "[Ben's Claude] @all live: 1a2b3c4d is live on https://myapp.example (from ben-main-lead)",
                 "created_at": "2026-11-08T11:00:00Z"},
                {"body": "[Ben's Claude] @all live is a word in a sentence", "created_at": "2026-11-08T11:05:00Z"}]
    found = live.from_board(comments)
    assert (found.sha, found.url, found.at, found.source) == ("1a2b3c4d", "https://myapp.example",
                                                              "2026-11-08T11:00:00Z", "a live: line on the board")


def test_the_merges_on_the_base_that_arent_live_are_named_by_branch(tmp_path):
    repo = tmp_path / "repo"
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    for key, value in (("user.name", "Test"), ("user.email", "t@example.test")):
        git(repo, "config", key, value)
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    for branch in ("ana/login", "ben/export"):
        git(repo, "checkout", "-q", "-b", branch, "main")
        (repo / f"{branch.replace('/', '-')}.txt").write_text("x\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", branch)
        git(repo, "checkout", "-q", "main")
        git(repo, "merge", "-q", "--no-ff", "-m", f"Merge {branch} into main", branch)
        if branch == "ana/login":
            deployed = git(repo, "rev-parse", "HEAD")
    assert live.not_live(repo, "main", deployed) == ["ben/export"]
    assert live.not_live(repo, "main", git(repo, "rev-parse", "HEAD")) == []


def test_colony_live_posts_the_deploy_for_every_lead(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(transport, "send", lambda config, to, line, card=None: sent.append(line) or 7)
    assert live.post(CONFIG, Namespace(sha="1a2b3c4d5e", url="https://myapp.example")) == 0
    assert sent == ["@all live: 1a2b3c4d5e is live on https://myapp.example"]
    with pytest.raises(cli.ColonyError, match="a commit, such as 1a2b3c4"):
        live.post(CONFIG, Namespace(sha="main", url=""))


def test_a_live_line_counts_only_from_the_team_and_only_with_an_https_link(monkeypatch, tmp_path):
    monkeypatch.setattr(wait, "gh", lambda *args: "[]")  # GitHub records no deployment
    comments = [{"body": "@all live: 1a2b3c4 is live on https://myapp.example (from ben-main-lead)",
                 "created_at": "2026-11-08T11:00:00Z", "user": {"login": "ben"}},
                {"body": "@all live: 9f9f9f9 is live on https://evil.example (from eve-main-lead)",
                 "created_at": "2026-11-08T12:00:00Z", "user": {"login": "eve"}}]
    monkeypatch.setattr(live.presence, "read_comments", lambda config: comments)
    line = live.summary(CONFIG, tmp_path)
    assert line.startswith("Live: 1a2b3c4 on https://myapp.example") and "evil" not in line
    found = live.from_board([{"body": "@all live: 1a2b3c4 is live on javascript:alert(1)", "created_at": "x"}])
    assert found.url == ""


def new_repo(tmp_path):
    repo = tmp_path / "repo"
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    for key, value in (("user.name", "Test"), ("user.email", "t@example.test")):
        git(repo, "config", key, value)
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    return repo


def commit(repo, name: str, message: str) -> None:
    (repo / name).write_text(f"{name}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


def test_merges_through_pull_requests_and_squashes_are_named_and_other_commits_counted(tmp_path):
    # Outside hack mode work lands through GitHub's pull requests, whose merge commit says "Merge pull request #12
    # from <owner>/<branch>", or as one squashed commit that ends with "(#13)", never as "Merge <branch> into".
    repo = new_repo(tmp_path)
    deployed = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "ben/export")
    commit(repo, "export.txt", "Export CSV")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #12 from acme/ben/export\n\nExport CSV", "ben/export")
    commit(repo, "login.txt", "Add the login form (#13)")
    git(repo, "checkout", "-q", "-b", "fix")
    commit(repo, "fix.txt", "fix")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "fix")  # a local merge: "Merge branch 'fix'"
    commit(repo, "typo.txt", "Fix a typo")
    commit(repo, "readme.txt", "Update the readme")
    assert live.not_live(repo, "main", deployed) == ["#12 (ben/export)", "#13 (Add the login form)", "fix",
                                                     "2 other commits"]


def test_which_merges_arent_live_is_unknown_when_the_clone_lacks_the_deployed_commit(monkeypatch, tmp_path):
    repo = new_repo(tmp_path)
    assert live.not_live(repo, "main", "f" * 40) is None
    monkeypatch.setattr(wait, "gh", lambda *args: "[]")
    monkeypatch.setattr(live.presence, "read_comments", lambda config: [
        {"body": f"@all live: {'f' * 40} is live", "created_at": "x", "user": {"login": "ben"}}])
    line = live.summary(CONFIG, repo)
    assert "which merges aren't live is unknown: this clone lacks fffffff, so run `git fetch`" in line
    assert "everything merged" not in line


def test_the_deploy_environment_is_a_project_key_and_the_hack_key_still_counts():
    assert live.environment({"project": {"deploy_environment": "prod"}, "hack": {"deploy_environment": "x"}}) == "prod"
    assert live.environment({"project": {}, "hack": {"deploy_environment": "Live"}}) == "Live"
    assert live.environment({"project": {}}) == "Production"


def test_outside_hack_mode_the_live_line_shows_only_a_known_deploy(monkeypatch, tmp_path):
    startup = {**CONFIG, "project": {**CONFIG["project"], "mode": "startup"}}
    monkeypatch.setattr(live.presence, "read_comments", lambda config: [])
    monkeypatch.setattr(wait, "gh", lambda *args: "[]")  # no deploy anywhere, as for a library
    assert live.summary(startup, tmp_path) == ""
    assert live.summary(CONFIG, tmp_path).startswith("Live: unknown")  # hack mode always has a demo to deploy
    answers = {"repos/acme/demo/deployments?per_page=20": [{"id": 1, "sha": "a" * 40, "environment": "Production"}],
               "repos/acme/demo/deployments/1/statuses?per_page=1": [{"state": "success", "created_at": "t"}]}
    monkeypatch.setattr(wait, "gh", lambda *args: json.dumps(answers[args[1]]))
    assert live.summary(startup, new_repo(tmp_path)).startswith("Live: aaaaaaa, since t")
