"""Tests for the roles rule: every session a person opens is a lead (`colony hi`, `colony claim`), helpers belong to
one lead (`colony join`, `colony take`), presence across computers (status comments, `colony who`), the leads'
heartbeats, and the accounts' usage, resets and drain."""
import argparse
import json
import multiprocessing
import subprocess
import time
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path

import pytest

from colony import cli, presence, wait

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
    for key in (cli.SESSION_ENV, cli.PERSON_ENV, wait.TOKEN_ENV, wait.LEAD_ENV, "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
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


class GitHub:
    """Stand-in status comments: `read` returns them, and `keep`'s writes land here instead of GitHub."""

    def __init__(self, monkeypatch):
        self.comments: list[dict] = []
        self.calls: list[tuple] = []
        monkeypatch.setattr(presence, "where", lambda config: 5)
        monkeypatch.setattr(wait, "gh", self.gh)

    def add(self, status: presence.Status) -> None:
        self.comments.append({"id": 100 + len(self.comments), "body": presence.body(status)})

    def gh(self, *args: str) -> str:
        self.calls.append(args)
        if args[:2] == ("api", "--paginate"):
            return json.dumps(self.comments)
        if args[:3] == ("api", "-X", "PATCH"):
            number = int(args[3].rsplit("/", 1)[-1])
            next(c for c in self.comments if c["id"] == number)["body"] = args[5].removeprefix("body=")
            return "{}"
        if args[0] == "api":
            self.comments.append({"id": 100 + len(self.comments), "body": args[3].removeprefix("body=")})
            return json.dumps({"id": self.comments[-1]["id"]})
        return json.dumps({"body": "Folders: apps/web/"})


@pytest.fixture
def github(monkeypatch):
    return GitHub(monkeypatch)


def lead(name="ana-engine-lead", folders=(), computer="PC-2", at=None, person="ana") -> presence.Status:
    return presence.Status(name, "lead", person=person, computer=computer, account="admin", folders=list(folders),
                           at=time.time() if at is None else at)


def hi(capsys) -> str:
    assert cli.main(["hi"]) == 0
    return capsys.readouterr().out


# A session a person opens is a lead


def test_hi_in_a_repo_with_no_config_runs_setup_in_this_session(host, capsys):
    out = hi(capsys)
    assert "not set up in this repo, since .colony/colony.toml is missing" in out
    assert "Load the colony-setup skill, or run `colony setup --print`" in out


def test_setup_print_prints_the_filled_setup_prompt(host, capsys):
    assert cli.main(["setup", "--print"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("You are setting up Puffin Colony in this repository.") and "{package}" not in out


def test_the_pointer_line_setup_writes_sends_a_plain_hi_to_colony_hi():
    prompt = cli.fill_names(cli.package_file("prompts", "setup.md"))
    assert prompt.count("run `colony hi` first and do what it prints.") == 2


def test_a_new_chat_with_no_lead_alive_becomes_the_main_lead_without_a_question(home, config, github, capsys,
                                                                                monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude-admin"))
    out = hi(capsys)
    assert "this session leads ana-main-lead, over the whole repo" in out
    beat = json.loads((home / ".colony" / "demo" / "ana-main-lead.heartbeat").read_text())
    assert beat["session"] == "ana-main-lead" and beat["account"] == "admin"
    assert f"COLONY_SESSION=lead COLONY_LEAD=ana-main-lead COLONY_PERSON=ana {wait.TOKEN_ENV}={beat['token']}" in out
    assert "?" not in out.split("Next:")[1]  # it asks the person nothing about what it is
    assert presence.registry()["ana-main-lead"] == {"person": "ana", "folders": []}
    assert presence.parse(github.comments[0]["body"]).name == "ana-main-lead"  # its status comment


def test_a_new_chat_beside_a_live_lead_is_a_lead_too_and_asks_only_whats_mine(home, config, github, capsys):
    github.add(lead(folders=["apps/api/"]))
    out = hi(capsys)
    assert "- ana-engine-lead (ana, PC-2): apps/api/" in out
    assert 'ask the person only "What\'s mine?"' in out and "avoiding apps/api/" in out
    assert "builder" not in out.lower().split("next:")[1]  # it never offers to be a builder
    assert not list((home / ".colony" / "demo").glob("*.heartbeat"))  # it claims nothing before the answer


def test_a_second_lead_avoids_the_first_ones_folders(home, config, github, capsys):
    github.add(lead(folders=["apps/api/"]))
    with pytest.raises(cli.ColonyError, match="apps/api/db/ overlaps apps/api/ of ana-engine-lead"):
        cli.claim(config, argparse.Namespace(stream="data", folders=["apps/api/db"], person=None))
    assert cli.claim(config, argparse.Namespace(stream="web", folders=["apps/web"], person=None)) == 0
    assert "This session leads ana-web-lead, over apps/web/." in capsys.readouterr().out
    assert presence.registry()["ana-web-lead"]["folders"] == ["apps/web/"]


def test_a_lead_name_alive_on_another_computer_is_refused(home, config, github):
    github.add(lead(name="ana-web-lead", computer="PC-2"))
    with pytest.raises(cli.ColonyError, match="ana-web-lead is alive on another computer"):
        cli.claim(config, argparse.Namespace(stream="web", folders=[], person=None))


def test_a_stale_status_counts_as_gone(home, config, github, capsys):
    github.add(lead(folders=["apps/api/"], at=time.time() - presence.STATUS_STALE - 1))
    out = hi(capsys)
    assert "this session leads ana-main-lead" in out  # the stale lead is not alive, so this one takes the repo
    assert cli.main(["who"]) == 0
    assert "Gone, no status in 15 minutes: ana-engine-lead" in capsys.readouterr().out


def test_a_session_colony_opened_stays_a_helper_and_never_asks(home, config, capsys, monkeypatch):
    monkeypatch.setenv(cli.SESSION_ENV, "builder-3")
    out = hi(capsys)
    assert "This session is builder-3, which colony opened, and is a helper, for good" in out
    assert "never asks the person anything" in out
    assert not list((home / ".colony").rglob("*.heartbeat"))


def test_colony_opens_a_lead_whose_first_prompt_runs_colony_hi(home, config, capsys):
    assert cli.lead(config, argparse.Namespace(person="ana", here=True, dry_run=True)) == 0
    assert "'Run `colony hi` and do what it prints" in capsys.readouterr().out


# Helpers belong to one lead


def join(config, lead=None, **flags):
    args = argparse.Namespace(lead=lead, person="ana", account=None, here=True, dry_run=True, in_session=False)
    vars(args).update(flags)
    return cli.join(config, args)


def test_join_with_one_lead_joins_it_under_the_next_free_name(home, config, github, capsys):
    github.add(lead(folders=["apps/api/"]))
    github.add(presence.Status("builder-1", "helper", person="ana", lead="ana-engine-lead", at=time.time()))
    join(config, in_session=True)
    out = capsys.readouterr().out
    assert "This session is builder-2, a helper of ana-engine-lead" in out
    assert "COLONY_SESSION=builder-2 COLONY_LEAD=ana-engine-lead COLONY_PERSON=ana" in out
    assert "Never ask the person anything" in out


def test_join_asks_once_which_lead_when_there_are_two(home, config, github, capsys, monkeypatch):
    github.add(lead(folders=["apps/api/"]))
    github.add(lead(name="ana-web-lead", folders=["apps/web/"]))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    asked = []
    monkeypatch.setattr("builtins.input", lambda text: asked.append(text) or "web")
    join(config, in_session=True)
    assert len(asked) == 1 and "1. ana-engine-lead: apps/api/" in asked[0] and "2. ana-web-lead: apps/web/" in asked[0]
    assert "a helper of ana-web-lead" in capsys.readouterr().out


def test_join_lead_skips_the_question(home, config, github, capsys, monkeypatch):
    github.add(lead(folders=["apps/api/"]))
    github.add(lead(name="ana-web-lead", folders=["apps/web/"]))
    monkeypatch.setattr("builtins.input", lambda text: pytest.fail("join <lead> asked"))
    join(config, lead="engine", in_session=True)
    assert "a helper of ana-engine-lead" in capsys.readouterr().out


def test_join_with_two_leads_and_no_terminal_names_them_instead_of_guessing(home, config, github):
    github.add(lead(folders=["apps/api/"]))
    github.add(lead(name="ana-web-lead", folders=["apps/web/"]))
    with pytest.raises(cli.ColonyError, match="you have 2 live leads, so name one"):
        join(config, in_session=True)


def test_join_with_no_lead_alive_says_to_say_hi_first(home, config, github):
    with pytest.raises(cli.ColonyError, match="open a session in the repo and say hi first"):
        join(config, in_session=True)


def test_a_helper_refuses_a_card_outside_its_leads_folders(home, config, github, monkeypatch):
    from colony import board

    presence.write_registry({"ana-engine-lead": {"person": "ana", "folders": ["apps/api/"]}})
    monkeypatch.setenv(cli.SESSION_ENV, "builder-1")
    monkeypatch.setenv(wait.LEAD_ENV, "ana-engine-lead")
    taken = []
    monkeypatch.setattr(board, "set_fields", lambda config, card, pairs: taken.append((card, pairs)))
    with pytest.raises(cli.ColonyError, match="touches apps/web/, outside ana-engine-lead's folders"):
        cli.take(config, argparse.Namespace(card=12))
    assert taken == []
    presence.write_registry({"ana-engine-lead": {"person": "ana", "folders": ["apps/"]}})
    assert cli.take(config, argparse.Namespace(card=12)) == 0
    assert taken == [(12, [("Status", "In progress"), ("Helper", "builder-1")])]


def test_a_helper_of_the_rest_refuses_a_card_in_another_leads_folders(home, config, github, monkeypatch):
    github.add(lead(name="ana-web-lead", folders=["apps/web/"]))
    monkeypatch.setenv(cli.SESSION_ENV, "builder-1")
    monkeypatch.setenv(wait.LEAD_ENV, "ana-main-lead")
    with pytest.raises(cli.ColonyError, match="touches apps/web/, which ana-web-lead holds"):
        cli.take(config, argparse.Namespace(card=12))


def test_a_helper_takes_only_its_own_leads_lines(home, monkeypatch):
    monkeypatch.setenv(wait.LEAD_ENV, "ana-engine-lead")
    me = wait.builder_session({"project": {}}, "builder-1")
    assert me.leads == frozenset({"ana-engine-lead"})
    assert wait.taken("for builder-1: start: #4 (from ana-engine-lead)", me, "4")
    assert not wait.taken("for builder-1: start: #4 (from ana-web-lead)", me, "4")


# Presence: one status comment per session, edited in place


def test_a_status_comment_round_trips_and_addresses_no_one():
    status = lead(folders=["apps/api/"])
    text = presence.body(status)
    assert presence.parse(text, 7).folders == ["apps/api/"] and presence.parse(text, 7).comment == 7
    assert not wait.taken(text, wait.lead_session({"project": {"name": "demo"}}, "ana-web-lead"), "5")


def test_keep_edits_the_one_comment_in_place_every_five_minutes(home, config, github):
    state: dict = {}
    status = lead(name="ana-main-lead")
    assert presence.keep(config, status, state, now=1000.0)
    assert not presence.keep(config, status, state, now=1000.0 + presence.STATUS_EVERY - 1)
    assert presence.keep(config, status, state, now=1000.0 + presence.STATUS_EVERY)
    assert len(github.comments) == 1 and any(call[:3] == ("api", "-X", "PATCH") for call in github.calls)
    fresh: dict = {}  # a new session of the same name finds the old comment instead of adding one
    presence.keep(config, status, fresh, now=5000.0)
    assert len(github.comments) == 1 and fresh["status_id"] == state["status_id"]


def test_who_lists_every_live_lead_and_helper_across_computers(home, config, github, capsys):
    github.add(lead(folders=["apps/api/"], person="burak", name="burak-engine-lead", computer="Burak-PC"))
    github.add(presence.Status("builder-2", "helper", person="burak", lead="burak-engine-lead", computer="Burak-PC",
                               account="work", room=["work: 5h 10%"], at=time.time()))
    wait.beat("demo", "serdar-lead", "admin", "")  # a lead from before names, on this computer
    assert cli.main(["who"]) == 0
    out = capsys.readouterr().out
    assert "- burak-engine-lead: burak on Burak-PC, account admin" in out and "Folders: apps/api/." in out
    assert "- builder-2 (helper of burak-engine-lead): burak on Burak-PC, account work" in out
    assert "Room: work: 5h 10%." in out
    assert "- serdar-lead:" in out


def test_status_names_each_lead_on_this_computer_with_account_and_heartbeat_age(home, config, capsys):
    assert cli.main(["status"]) == 1
    assert "lead: none running on this computer (no heartbeat)" in capsys.readouterr().out
    wait.beat("demo", "ana-engine-lead", "admin", "t", now=time.time() - 30, named=True)
    wait.beat("demo", "serdar-lead", "main", "", now=time.time() - 3 * 3600)
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "lead: ana-engine-lead on account admin, heartbeat 30 s ago" in out
    assert "lead: none running as serdar-lead on this computer (its heartbeat is 3 h old)" in out


# The heartbeat is the lock on one lead's name


def heartbeat(home: Path, name="lead") -> dict:
    return json.loads((home / ".colony" / "demo" / f"{name}.heartbeat").read_text())


def test_two_sessions_never_hold_the_same_lead_while_its_heartbeat_is_fresh(home):
    first = wait.beat("demo", "ana-lead", "main", "aaaaaaaaaaaa")
    with pytest.raises(wait.LeadTaken, match="ana-lead on account main holds the lead"):
        wait.beat("demo", "ana-lead", "admin", "bbbbbbbbbbbb")
    again = wait.beat("demo", "ana-lead", "main", "aaaaaaaaaaaa", now=first["at"] + 15)
    assert again["at"] == first["at"] + 15 and heartbeat(home)["token"] == "aaaaaaaaaaaa"


def test_named_leads_keep_their_own_heartbeats_side_by_side(home):
    wait.beat("demo", "ana-engine-lead", "main", "aaaaaaaaaaaa", named=True)
    wait.beat("demo", "ana-web-lead", "admin", "bbbbbbbbbbbb", named=True)
    assert heartbeat(home, "ana-engine-lead")["token"] == "aaaaaaaaaaaa"
    assert heartbeat(home, "ana-web-lead")["token"] == "bbbbbbbbbbbb"


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
    workers = [context.Process(target=_claim, args=(str(home), f"{n:012}", start, results)) for n in range(6)]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(30)
    won = [token for token in (results.get(timeout=5) for _ in workers) if token]
    assert len(won) == 1 and heartbeat(home)["token"] == won[0]


def test_a_lead_from_before_names_keeps_its_wait_and_heartbeat(home, monkeypatch):
    """The live lead runs with COLONY_SESSION=lead and no COLONY_LEAD: nothing about it changes."""
    calls = []
    monkeypatch.setattr(wait, "wait", lambda *args, **kwargs: calls.append((args, kwargs)) or 0)
    monkeypatch.setattr(wait.shutil, "which", lambda name: "/bin/gh")
    monkeypatch.setattr(wait, "coordination_issue", lambda repo, project: 5)
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    config = {"project": {"repo": "acme/demo", "name": "demo"}, "features": {"board": False}}
    assert wait.run(config, argparse.Namespace(person=None, waiting_on=None)) == 0
    assert heartbeat(home)["session"] == "ana-lead" and calls[0][0][-1] is None  # no status comment
    assert wait.lead_session(config, "ana-lead").names == frozenset({"lead", "ana-lead"})
    wait.beat("demo", "ana-lead", "other", "theirs000000", now=time.time() + wait.HEARTBEAT_FRESH)
    with pytest.raises(wait.LeadTaken):
        wait.run(config, argparse.Namespace(person=None, waiting_on=None))


def test_the_wait_loop_beats_and_keeps_the_status_at_each_poll(home, monkeypatch):
    beats, statuses = [], []
    monkeypatch.setattr(wait, "poll", lambda repo, state, me: state["pending"].append(["for lead: hi", True]))
    me = wait.Session(name=cli.LEAD, names=frozenset({cli.LEAD}))
    assert wait.wait("acme/demo", "demo", me, heartbeat=lambda: beats.append(1),
                     status=lambda: statuses.append(1)) == 0
    assert beats == [1] and statuses == [1]


def test_a_heartbeat_that_fails_to_write_never_stops_the_wait(home, monkeypatch, capsys):
    def broken():
        raise OSError("disk full")
    monkeypatch.setattr(wait, "poll", lambda repo, state, me: state["pending"].append(["for lead: hi", True]))
    me = wait.Session(name=cli.LEAD, names=frozenset({cli.LEAD}))
    assert wait.wait("acme/demo", "demo", me, heartbeat=broken) == 0
    assert "the heartbeat was not written: disk full" in capsys.readouterr().err


# Accounts: 5-hour and weekly usage, resets, and drain


def usage(home: Path, folder: str, five=None, week=None, week_resets_in=timedelta(days=3)) -> str:
    path = home / folder
    path.mkdir(exist_ok=True)
    windows = {}
    later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    if five is not None:
        windows["five_hour"] = {"utilization": five, "resets_at": later}
    if week is not None:
        windows["seven_day"] = {"utilization": week,
                                "resets_at": (datetime.now(timezone.utc) + week_resets_in).isoformat()}
    if windows:
        (path / ".claude.json").write_text(json.dumps({"cachedUsageUtilization": {"utilization": windows}}))
    return str(path)


def accounts(home, *specs, **project):
    return {"project": project, "accounts": {name: {"config_dir": usage(home, name, **kw), "person": "ana"}
                                            for name, kw in specs}}


def test_the_weekly_window_counts_as_much_as_the_five_hour_one(home):
    config = accounts(home, ("a", {"five": 10, "week": 95}), ("b", {"five": 50, "week": 20}))
    assert cli.pick_account(config, "ana")[0] == "b"  # a's week is full


def test_an_account_with_no_reading_ranks_after_known_room_and_before_full(home):
    config = accounts(home, ("full", {"five": 95}), ("unknown", {}), ("room", {"five": 60}))
    assert cli.pick_account(config, "ana")[0] == "room"
    config = accounts(home, ("full", {"five": 95}), ("unknown", {}))
    assert cli.pick_account(config, "ana")[0] == "unknown"


def test_drain_spends_the_week_that_resets_soonest_first_until_90(home):
    specs = (("roomy", {"five": 5, "week": 10, "week_resets_in": timedelta(days=6)}),
             ("expiring", {"five": 40, "week": 70, "week_resets_in": timedelta(hours=20)}))
    assert cli.pick_account(accounts(home, *specs), "ana")[0] == "roomy"
    assert cli.pick_account(accounts(home, *specs, drain=True), "ana")[0] == "expiring"
    full = (specs[0], ("expiring", {"five": 40, "week": 91, "week_resets_in": timedelta(hours=20)}))
    assert cli.pick_account(accounts(home, *full, drain=True), "ana")[0] == "roomy"


def test_the_room_text_names_both_windows_and_their_resets(home):
    folder = usage(home, "admin", five=40, week=63)
    text = cli.room_text("admin", folder)
    assert text.startswith("admin: 5h 40% (resets ") and ", week 63% (resets " in text and text.endswith(" UTC)")
    assert cli.room_text("x", usage(home, "x")) == "x: no reading"


# The setup skill


def test_skill_install_copies_the_setup_skill_into_a_settings_folder(home, capsys):
    folder = home / ".claude-admin"
    folder.mkdir()
    assert cli.main(["skill-install", "--config-dir", str(folder)]) == 0
    copied = folder / "skills" / "colony-setup" / "SKILL.md"
    assert copied.read_text() == (PACKAGE / "skills" / "colony-setup" / "SKILL.md").read_text()
