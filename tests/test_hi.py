"""Tests for a session the person opens with a plain hi: `colony hi`, the lead's heartbeat that claims and locks the
lead, `colony setup --print`, `colony skill-install`, and the lead line in `colony status`."""
import argparse
import json
import multiprocessing
import subprocess
import sys
import time
from importlib import resources
from pathlib import Path

import pytest

from colony import cli, wait

PACKAGE = Path(str(resources.files("colony")))
CONFIG = """
[project]
name = "demo"
repo = "acme/demo"
base = "dev"
worktrees = "~/trees"
checks = "make check"
[accounts.main]
config_dir = "~/.claude"
person = "ana"
[accounts.admin]
config_dir = "~/.claude-admin"
person = "ana"
[roles]
lead = { model = "m", effort = "high" }
builder = { model = "m", effort = "medium" }
reviewer = { model = "m", effort = "high" }
walker = { model = "m", effort = "medium" }
fixer = { model = "m", effort = "medium" }
[gate]
rubric = ["bugs"]
max_rounds = 5
walk = true
[budget]
provider_dollars = 0
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A temporary HOME, a PATH with a stub folder and no real claude or gh, and no session env."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")
    for key in (cli.SESSION_ENV, cli.PERSON_ENV, wait.TOKEN_ENV, "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    return tmp_path


@pytest.fixture
def host(home, monkeypatch):
    """A fresh git repo to run in, with no .colony folder yet."""
    repo = home / "host"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.chdir(repo)
    return repo.resolve()


@pytest.fixture
def config(host):
    """A two-account config for ana, written to .colony/colony.toml and loaded."""
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(CONFIG)
    return cli.load_config()


def heartbeat(home: Path) -> dict:
    """The lead's heartbeat file, read."""
    return json.loads((home / ".colony" / "demo" / "lead.heartbeat").read_text())


def hi(capsys) -> str:
    """Run `colony hi` and return what it printed."""
    assert cli.main(["hi"]) == 0
    return capsys.readouterr().out


# Not set up


def test_hi_in_a_repo_with_no_config_sets_colony_up_in_this_session(host, capsys):
    out = hi(capsys)
    assert "Puffin Colony: not set up in this repo, since .colony/colony.toml is missing." in out
    assert "Load the colony-setup skill, or run `colony setup --print`" in out
    assert not (host.parent / ".colony").exists()  # it claims nothing


def test_setup_print_prints_the_filled_setup_prompt_and_opens_nothing(host, capsys):
    assert cli.main(["setup", "--print"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("You are setting up Puffin Colony in this repository.")
    assert "{package}" not in out and "{display}" not in out
    assert "Number the 5 questions" in out


def test_the_pointer_line_setup_writes_sends_a_plain_hi_to_colony_hi():
    prompt = cli.fill_names(cli.package_file("prompts", "setup.md"))
    line = ("This repo runs Puffin Colony: read .colony/playbook.md. When the person opens a session without a task, "
            "run `colony hi` first and do what it prints.")
    assert prompt.count(f"`` {line} ``") == 2  # in the pointer item and in step 8


# No lead running: claim


def test_hi_with_no_heartbeat_claims_the_lead_with_this_sessions_account(home, config, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude-admin"))
    out = hi(capsys)
    beat = heartbeat(home)
    assert beat["session"] == "ana-lead" and beat["account"] == "admin" and len(beat["token"]) == 12
    assert time.time() - beat["at"] < 5
    assert "so this session claimed the lead, on account admin." in out
    assert f"`COLONY_SESSION=lead COLONY_PERSON=ana {wait.TOKEN_ENV}={beat['token']}`" in out
    assert "load the colony-lead skill" in out and "`colony wait` in the background within 2 minutes" in out


def test_the_default_folder_is_its_own_account(home, config, capsys):
    hi(capsys)
    assert heartbeat(home)["account"] == "main"


def test_hi_takes_over_a_stale_heartbeat(home, config, capsys):
    wait.beat("demo", "ana-lead", "main", "old0token000", now=time.time() - wait.HEARTBEAT_FRESH - 1)
    out = hi(capsys)
    assert "this session claimed the lead" in out
    assert heartbeat(home)["token"] != "old0token000"


# A lead running: build or help


def test_hi_with_a_fresh_heartbeat_offers_builder_or_help_and_claims_nothing(home, config, capsys):
    held = wait.beat("demo", "ana-lead", "admin", "lead0token00")
    out = hi(capsys)
    assert "lead: ana-lead on account admin, heartbeat 0 s ago" in out
    assert "offer to be a builder, or to help" in out and "take the name builder-1" in out
    assert "`COLONY_SESSION=builder-1 COLONY_PERSON=ana`" in out
    assert heartbeat(home) == held


def test_hi_offers_the_first_builder_name_no_live_wait_holds(home, config, capsys):
    wait.beat("demo", "ana-lead", "admin", "lead0token00")
    wait.write_json(wait.state_path("demo", "builder-1"), {"polled_at": time.time()})
    wait.write_json(wait.state_path("demo", "builder-2"), {"polled_at": time.time() - 3600})
    assert "take the name builder-2" in hi(capsys)


def test_a_session_colony_opened_keeps_its_role_and_never_claims(home, config, capsys, monkeypatch):
    monkeypatch.setenv(cli.SESSION_ENV, "builder-3")
    out = hi(capsys)
    assert "This session is builder-3, which colony opened: follow the Builder section" in out
    assert not (home / ".colony" / "demo" / "lead.heartbeat").exists()


# The heartbeat is the lock


def test_a_second_lead_is_refused_while_the_first_ones_heartbeat_is_fresh(home):
    first = wait.beat("demo", "ana-lead", "main", "aaaaaaaaaaaa")
    with pytest.raises(wait.LeadTaken, match="ana-lead on account main holds the lead"):
        wait.beat("demo", "ana-lead", "admin", "bbbbbbbbbbbb")
    again = wait.beat("demo", "ana-lead", "main", "aaaaaaaaaaaa", now=first["at"] + 15)
    assert again["at"] == first["at"] + 15 and heartbeat(home)["token"] == "aaaaaaaaaaaa"


def test_a_heartbeat_at_two_minutes_is_stale_and_can_be_taken(home):
    wait.beat("demo", "ana-lead", "main", "aaaaaaaaaaaa", now=1000.0)
    with pytest.raises(wait.LeadTaken):
        wait.beat("demo", "ana-lead", "admin", "bbbbbbbbbbbb", now=1000.0 + wait.HEARTBEAT_FRESH - 1)
    wait.beat("demo", "ana-lead", "admin", "bbbbbbbbbbbb", now=1000.0 + wait.HEARTBEAT_FRESH)
    assert heartbeat(home)["token"] == "bbbbbbbbbbbb"


def _claim(home: str, token: str, start, results) -> None:
    """One process's claim of the lead, after the start signal, for the race test."""
    import os
    os.environ["HOME"] = home
    start.wait()
    try:
        wait.beat("demo", "ana-lead", "main", token)
        results.put(token)
    except wait.LeadTaken:
        results.put(None)


def test_of_many_sessions_claiming_at_once_exactly_one_holds_the_lead(home):
    context = multiprocessing.get_context("spawn")
    start, results = context.Event(), context.Queue()
    tokens = [f"{n:012}" for n in range(6)]
    workers = [context.Process(target=_claim, args=(str(home), token, start, results)) for token in tokens]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(30)
    won = [token for token in (results.get(timeout=5) for _ in workers) if token]
    assert len(won) == 1 and heartbeat(home)["token"] == won[0]


# The lead's wait writes the heartbeat


def test_the_leads_wait_beats_with_its_token_and_stops_when_another_lead_holds_it(home, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(wait, "wait", lambda *args, **kwargs: calls.append(kwargs or args) or 0)
    monkeypatch.setattr(wait.shutil, "which", lambda name: "/bin/gh")
    monkeypatch.setattr(wait, "coordination_issue", lambda repo, project: 5)
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    monkeypatch.setenv(wait.TOKEN_ENV, "mine00000000")
    config = {"project": {"repo": "acme/demo", "name": "demo"}, "features": {"board": False}}
    assert wait.run(config, argparse.Namespace(person=None, waiting_on=None)) == 0
    beat = heartbeat(home)
    assert beat["token"] == "mine00000000" and beat["session"] == "ana-lead" and beat["account"] == "default"
    wait.beat("demo", "ana-lead", "other", "theirs000000", now=time.time() + wait.HEARTBEAT_FRESH)
    with pytest.raises(wait.LeadTaken):
        wait.run(config, argparse.Namespace(person=None, waiting_on=None))
    assert len(calls) == 1  # the second wait stopped before its first poll


def test_the_wait_loop_beats_at_each_poll(home, monkeypatch):
    beats = []
    monkeypatch.setattr(wait, "poll", lambda repo, state, me, mark: state["pending"].append(["for lead: hi", True]))
    me = wait.Session(name=cli.LEAD, names=frozenset({cli.LEAD}))
    assert wait.wait("acme/demo", "demo", me, heartbeat=lambda: beats.append(1)) == 0
    assert beats == [1]


def test_a_heartbeat_that_fails_to_write_never_stops_the_wait(home, monkeypatch, capsys):
    def broken():
        raise OSError("disk full")
    monkeypatch.setattr(wait, "poll", lambda repo, state, me, mark: state["pending"].append(["for lead: hi", True]))
    me = wait.Session(name=cli.LEAD, names=frozenset({cli.LEAD}))
    assert wait.wait("acme/demo", "demo", me, heartbeat=broken) == 0
    assert "the heartbeat was not written: disk full" in capsys.readouterr().err


# `colony` opens no second lead, and `colony status` names the lead


def test_colony_refuses_to_open_a_second_lead(home, config, capsys):
    (home / "bin").mkdir()
    (home / "bin" / "claude").write_text("#!/bin/sh\nexit 0\n")
    (home / "bin" / "claude").chmod(0o755)
    wait.beat("demo", "ana-lead", "admin", "lead0token00")
    assert cli.main(["--here"]) == 2
    assert "a lead is running here, so colony opens no second one" in capsys.readouterr().err


def test_status_names_the_lead_its_account_and_heartbeat_age(home, config, capsys):
    assert cli.main(["status"]) == 1  # no batch yet
    assert "lead: none running on this computer (no heartbeat)" in capsys.readouterr().out
    wait.beat("demo", "ana-lead", "admin", "lead0token00", now=time.time() - 30)
    cli.main(["status"])
    assert "lead: ana-lead on account admin, heartbeat 30 s ago" in capsys.readouterr().out
    wait.beat("demo", "ana-lead", "admin", "lead0token00", now=time.time() - 3 * 3600)
    cli.main(["status"])
    assert "lead: none running on this computer (ana-lead's heartbeat is 3 h old)" in capsys.readouterr().out


# The setup skill


def test_skill_install_copies_the_setup_skill_into_a_settings_folder(home, capsys):
    folder = home / ".claude-admin"
    folder.mkdir()
    assert cli.main(["skill-install", "--config-dir", str(folder)]) == 0
    copied = folder / "skills" / "colony-setup" / "SKILL.md"
    assert copied.read_text() == (PACKAGE / "skills" / "colony-setup" / "SKILL.md").read_text()
    assert cli.main(["skill-install", "--config-dir", str(home / "missing")]) == 2


def test_the_setup_skill_triggers_on_a_plain_hi_and_runs_colony_hi():
    text = (PACKAGE / "skills" / "colony-setup" / "SKILL.md").read_text()
    assert "description: Set up Puffin Colony" in text and "says hi" in text
    assert "Run `colony hi`" in text and "`colony setup --print`" in text


def test_the_lead_and_builder_skills_trigger_on_a_session_hi_placed():
    lead = (PACKAGE / "skills" / "colony-lead" / "SKILL.md").read_text().split("\n")[2]
    builder = (PACKAGE / "skills" / "colony-builder" / "SKILL.md").read_text().split("\n")[2]
    assert "colony hi said this session claimed the lead" in lead
    assert "took colony hi's offer to build" in builder
