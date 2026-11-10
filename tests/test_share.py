"""Tests for colony/share.py: `colony share` puts a file on the colony-shared branch, which is never merged, for any
teammate's computer, and `colony need` asks another lead for something and tracks it until it is done."""
import subprocess
from argparse import Namespace

import pytest

from colony import cli, share, transport, wait

CONFIG = {"project": {"name": "demo", "repo": "acme/demo", "base": "main", "mode": "hack"},
          "accounts": {"ana": {"config_dir": "~/.claude", "person": "ana"}}, "messages": {"board": 7},
          "people": {"logins": ["ana", "ben"]}}


def git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def board(monkeypatch):
    sent = []
    monkeypatch.setattr(transport, "send", lambda config, to, line, card=None: sent.append(line) or 7)
    return sent


@pytest.fixture
def lead(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("COLONY_SESSION", "lead")
    monkeypatch.setenv("COLONY_LEAD", "ana-main-lead")
    monkeypatch.setenv("COLONY_PERSON", "ana")
    for key, value in {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "T",
                       "GIT_COMMITTER_EMAIL": "t@example.test"}.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def clone(tmp_path, monkeypatch, lead):
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(clone))
    (clone / "a.txt").write_text("a\n")
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", "base")
    git(clone, "remote", "add", "origin", str(origin))
    git(clone, "push", "-q", "origin", "main")
    monkeypatch.chdir(clone)
    monkeypatch.setattr(share, "is_public", lambda config: True)
    return origin


def test_a_shared_file_goes_on_the_never_merged_branch_and_the_board_gets_its_link(clone, tmp_path, board, capsys):
    notes = tmp_path / "spec.md"
    notes.write_text("# Spec\n")
    assert share.share(CONFIG, Namespace(file=str(notes), to="@ben")) == 0
    assert git(clone, "show", "colony-shared:shared/spec.md") == "# Spec"
    assert board == ["@ben shared: spec.md, https://github.com/acme/demo/blob/colony-shared/shared/"
                     "spec.md (from ana-main-lead)"]
    assert "acme/demo is public: anyone can read it" in capsys.readouterr().out
    (tmp_path / "more.md").write_text("more\n")
    assert share.share(CONFIG, Namespace(file=str(tmp_path / "more.md"), to="")) == 0  # the same branch grows
    assert git(clone, "ls-tree", "--name-only", "colony-shared", "shared/").split() == [
        "shared/more.md", "shared/spec.md"]


def test_a_file_holding_a_secret_is_never_shared(clone, tmp_path, board):
    key = tmp_path / "creds.txt"
    key.write_text("token ghp_" + "a" * 36 + "\n")
    with pytest.raises(cli.ColonyError, match="never shares a secret"):
        share.share(CONFIG, Namespace(file=str(key), to=""))
    assert board == []


def test_a_need_is_asked_tracked_and_closed(lead, board, capsys):
    assert share.need(CONFIG, Namespace(to="@ben", what=["POST /api/records with a creator claim"], done=None)) == 0
    assert board == ["@ben need: POST /api/records with a creator claim [N1] (from ana-main-lead)"]
    assert share.need(CONFIG, Namespace(to=None, what=[], done=None)) == 0
    assert "N1 from @ben, open 0 min: POST /api/records with a creator claim" in capsys.readouterr().out
    assert share.need(CONFIG, Namespace(to=None, what=[], done="N1")) == 0
    assert board[-1] == "@ben N1 is done, thanks: POST /api/records with a creator claim (from ana-main-lead)"
    share.need(CONFIG, Namespace(to=None, what=[], done=None))
    assert "No open need." in capsys.readouterr().out
    lead_session = wait.Session("lead", frozenset({"lead", "ben-main-lead"}), logins=frozenset({"ben"}))
    assert wait.taken("@ben need: the route [N2] (from ana-main-lead)", lead_session, "")[0][1]  # at once
