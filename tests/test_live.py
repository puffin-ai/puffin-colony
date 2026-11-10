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
