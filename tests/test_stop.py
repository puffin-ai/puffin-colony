"""Tests for colony/stop.py: `colony stop` ends this project's sessions on this computer, never the one running it nor
one with uncommitted work unless forced, and `colony handoff @<login>` hands a person's open work to another lead."""
import subprocess
from argparse import Namespace

import pytest

from colony import cli, presence, stop, transport

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
def sessions(tmp_path, monkeypatch):
    """Four sessions of this project on this computer: this one, a background helper, an interactive helper, and one
    whose folder holds uncommitted work."""
    clean, dirty = tmp_path / "clean", tmp_path / "dirty"
    for folder in (clean, dirty):
        git(tmp_path, "init", "-q", str(folder))
    (dirty / "draft.txt").write_text("not committed\n")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "me-0000")
    listed = [{"kind": "interactive", "name": "demo-ana-main-lead", "pid": 11, "sessionId": "me-0000", "cwd": str(clean)},
              {"kind": "background", "name": "demo-staff", "id": "bg1", "sessionId": "s1", "cwd": str(clean),
               "config_dir": "~/.claude"},
              {"kind": "interactive", "name": "demo-board", "pid": 22, "sessionId": "s2", "cwd": str(clean)},
              {"kind": "background", "name": "demo-auth", "id": "bg3", "sessionId": "s3", "cwd": str(dirty),
               "config_dir": "~/.claude"}]
    monkeypatch.setattr(cli, "running_sessions", lambda config: listed)
    stopped = []
    monkeypatch.setattr(stop, "stop_background", lambda agent: stopped.append(agent["name"]))
    monkeypatch.setattr(stop, "stop_interactive", lambda agent: stopped.append(agent["name"]))
    return stopped


def test_stop_ends_this_projects_sessions_here_but_this_one_and_one_with_uncommitted_work(sessions, board, capsys):
    assert stop.stop(CONFIG, Namespace(names=[], force=False)) == 1
    assert sessions == ["demo-staff", "demo-board"]
    out = capsys.readouterr().out
    assert "kept demo-auth: its folder" in out and "uncommitted" in out and "--force" in out
    assert board == ["@all demo-staff and demo-board stopped on " + presence.computer() + "; demo-auth kept, with "
                     "uncommitted work"]


def test_stop_tells_the_other_leads_in_startup_mode_and_no_one_in_solo_mode(sessions, board):
    # In startup mode several people run leads, and their leads read the coordination issue; solo has one person.
    for mode, heard in (("startup", 1), ("solo", 0)):
        board.clear()
        config = {**CONFIG, "project": {**CONFIG["project"], "mode": mode}}
        stop.stop(config, Namespace(names=["staff"], force=False))
        assert len(board) == heard
    stop.stop({**CONFIG, "project": {**CONFIG["project"], "mode": "startup"}}, Namespace(names=["staff"], force=False))
    assert board == ["@all demo-staff stopped on " + presence.computer()]


def test_stop_names_sessions_and_force_takes_one_with_uncommitted_work(sessions, board):
    assert stop.stop(CONFIG, Namespace(names=["auth"], force=True)) == 0
    assert sessions == ["demo-auth"]
    with pytest.raises(cli.ColonyError, match="no session named nobody"):
        stop.stop(CONFIG, Namespace(names=["nobody"], force=False))


def test_handoff_names_the_open_work_releases_the_claims_and_tells_the_other_lead(tmp_path, monkeypatch, board,
                                                                                  capsys):
    monkeypatch.setattr(stop, "open_work", lambda root, config, login: [
        "ana/ops (3 commits, at 1a2b3c4)", "ana/pdf (1 commit, at 5d6e7f8, never pushed: push it first)"])
    monkeypatch.setattr(cli, "repo_root", lambda: tmp_path)
    monkeypatch.setenv("COLONY_PERSON", "ana")
    monkeypatch.setenv("COLONY_LEAD", "ana-main-lead")
    monkeypatch.setattr(presence, "registry", lambda: {"ana-main-lead": {"person": "ana", "folders": ["src/ops/"]},
                                                       "ben-main-lead": {"person": "ben", "folders": ["server/"]}})
    written = []
    monkeypatch.setattr(presence, "write_registry", lambda leads: written.append(leads))
    assert stop.handoff(CONFIG, Namespace(to="@ben")) == 0
    assert written == [{"ben-main-lead": {"person": "ben", "folders": ["server/"]}}]
    assert board == ["@ben handoff: ana-main-lead stops, and its work is yours: ana/ops (3 commits, at 1a2b3c4); "
                     "ana/pdf (1 commit, at 5d6e7f8, never pushed: push it first). Its paths are free: src/ops/. Ask "
                     "@ben, not ana-main-lead, from now on"]
    assert "never pushed" in capsys.readouterr().out
    with pytest.raises(cli.ColonyError, match="hand work to another person's lead"):
        stop.handoff(CONFIG, Namespace(to="@ana"))


def test_open_work_lists_a_persons_unmerged_branches_and_the_unpushed_ones(tmp_path):
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(clone))
    for key, value in (("user.name", "T"), ("user.email", "t@example.test")):
        git(clone, "config", key, value)
    (clone / "a.txt").write_text("a\n")
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", "base")
    git(clone, "remote", "add", "origin", str(origin))
    git(clone, "push", "-q", "origin", "main")
    for branch, push in (("ana/ops", True), ("ana/pdf", False), ("ben/api", True), ("ana/done", True)):
        git(clone, "checkout", "-q", "-b", branch, "main")
        if branch != "ana/done":
            (clone / f"{branch.replace('/', '-')}.txt").write_text("x\n")
            git(clone, "add", "-A")
            git(clone, "commit", "-qm", branch)
        if push:
            git(clone, "push", "-q", "origin", branch)
    git(clone, "checkout", "-q", "main")
    git(clone, "fetch", "-q", "origin")
    found = stop.open_work(clone, CONFIG, "ana")
    assert [line.split(" (", 1)[0] for line in found] == ["ana/ops", "ana/pdf"]
    assert "never pushed" in found[1] and "never pushed" not in found[0]
