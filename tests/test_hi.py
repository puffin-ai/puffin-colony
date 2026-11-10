"""Tests for the roles rule: every session a person types into is a lead (plain `colony` inside it, `colony claim`), helpers belong to
one lead (`colony join`, `colony take`), presence across computers (status comments, `colony who`), the leads'
heartbeats, and the accounts' usage, resets and order."""
import argparse
import json
import multiprocessing
import shlex
import subprocess
import time
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path

import pytest

from conftest import stub_path
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
config_dir = "~/.claude-work"
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
    monkeypatch.setenv("PATH", stub_path(tmp_path / 'bin'))
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
        self.unreadable = ""  # set: reading the comments fails with this error
        self.down = ""  # set: every gh call fails with this error
        monkeypatch.setattr(presence, "where", lambda config: 5)
        monkeypatch.setattr(wait, "gh", self.gh)

    def add(self, status: presence.Status) -> None:
        self.comments.append({"id": 100 + len(self.comments), "body": presence.body(status)})

    def gh(self, *args: str) -> str:
        self.calls.append(args)
        if self.down:
            raise wait.GhError(self.down)
        if args[:2] == ("api", "--paginate"):
            if self.unreadable:
                raise wait.GhError(self.unreadable)
            if "--jq" in args:  # one comment per line, as gh prints `--jq '.[]'`
                return "".join(json.dumps(comment) + "\n" for comment in self.comments)
            return json.dumps(self.comments)
        if args[:3] == ("api", "-X", "PATCH"):
            number = int(args[3].rsplit("/", 1)[-1])
            next(c for c in self.comments if c["id"] == number)["body"] = args[5].removeprefix("body=")
            return "{}"
        if args[:2] == ("issue", "list"):
            return json.dumps([{"number": 5, "title": wait.COORDINATION}])
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


def hi(capsys, monkeypatch=None) -> str:
    """Plain `colony` inside a Claude Code session."""
    import os
    os.environ["CLAUDECODE"] = "1"
    try:
        assert cli.main([]) == 0
    finally:
        del os.environ["CLAUDECODE"]
    return capsys.readouterr().out


# A session a person opens is a lead


def test_colony_in_a_session_with_no_config_runs_setup_in_that_session(host, capsys):
    out = hi(capsys)
    assert "not set up in this repo, since .colony/colony.toml is missing. Set it up in this session" in out
    assert "You are setting up Puffin Colony in this repository." in out  # the setup prompt itself, to follow here


def test_colony_in_a_terminal_opens_setup_or_a_lead_session_instead(host, capsys, monkeypatch):
    opened = []
    monkeypatch.setattr(cli, "setup", lambda args: opened.append("setup") or 0)
    monkeypatch.setattr(cli, "lead", lambda config, args: opened.append("lead") or 0)
    assert cli.main([]) == 0
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(CONFIG)
    assert cli.main([]) == 0
    assert opened == ["setup", "lead"]


def test_colony_hi_is_no_longer_a_command():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["hi"])


def test_setup_print_prints_the_filled_setup_prompt(host, capsys):
    assert cli.main(["setup", "--print"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("You are setting up Puffin Colony in this repository.") and "{package}" not in out


def test_the_pointer_line_setup_writes_sends_a_plain_hi_to_colony_hi():
    prompt = cli.fill_names(cli.package_file("prompts", "setup.md"))
    assert prompt.count("run `colony` first and do what it prints.") == 2


def test_a_new_chat_with_no_lead_alive_becomes_the_main_lead_without_a_question(home, config, github, capsys,
                                                                                monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude-work"))
    out = hi(capsys)
    assert "this session leads ana-main-lead, over the whole repo" in out
    beat = json.loads((home / ".colony" / "demo" / "ana-main-lead.heartbeat").read_text())
    assert beat["session"] == "ana-main-lead" and beat["account"] == "admin"
    assert f"COLONY_SESSION=lead COLONY_LEAD=ana-main-lead COLONY_PERSON=ana {wait.TOKEN_ENV}={beat['token']}" in out
    assert "?" not in out.split("Next:")[1]  # it asks the person nothing about what it is
    assert presence.registry()["ana-main-lead"] == {"person": "ana", "folders": []}
    assert presence.parse(github.comments[0]["body"]).name == "ana-main-lead"  # its status comment



def test_a_dry_run_names_the_lead_it_would_claim_and_claims_nothing(home, config, github, capsys):
    import os
    os.environ["CLAUDECODE"] = "1"
    try:
        assert cli.main(["--dry-run"]) == 0
    finally:
        del os.environ["CLAUDECODE"]
    assert "this session would lead ana-main-lead, over the whole repo. Nothing ran." in capsys.readouterr().out
    assert not (home / ".colony" / "demo").exists()  # no heartbeat
    assert not presence.registry() and not github.comments  # no registry entry, no status comment
    assert cli.claim(config, argparse.Namespace(stream="web", folders=["apps/web"], person=None, dry_run=True)) == 0
    assert "This session would lead ana-web-lead, over apps/web/. Nothing ran." in capsys.readouterr().out
    assert not presence.registry() and not github.comments

def test_a_quiet_lead_person_hears_only_conversation_and_what_they_must_act_on(home, host, config, github, capsys):
    (host / ".colony" / "colony.toml").write_text(CONFIG + "\n[people.ana]\nquiet_lead = true\n")
    assert "ana wants a quiet lead ([people.ana] quiet_lead = true): act on notifications silently" in hi(capsys)


def test_a_lead_keeps_the_person_posted_by_default(home, config, github, capsys):
    assert not cli.quiet_lead(config, "ana")
    assert "quiet lead" not in hi(capsys)


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


def test_a_lead_session_colony_opened_claims_its_name_when_it_runs_colony(home, config, github, capsys, monkeypatch):
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    assert "this session leads ana-main-lead" in hi(capsys)


def test_a_session_colony_opened_stays_a_helper_and_never_asks(home, config, capsys, monkeypatch):
    monkeypatch.setenv(cli.SESSION_ENV, "builder-3")
    out = hi(capsys)
    assert "This session is builder-3, which colony opened, and is a helper, for good" in out
    assert "never asks the person anything" in out
    assert not list((home / ".colony").rglob("*.heartbeat"))


def test_colony_opens_a_lead_whose_first_prompt_runs_colony_hi(home, config, capsys):
    assert cli.lead(config, argparse.Namespace(person="ana", here=True, dry_run=True)) == 0
    assert "'Run `colony` and do what it prints" in capsys.readouterr().out


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
    assert presence.parse(github.comments[-1]["body"]).name == "builder-2"  # it claimed the name at once
    assert "COLONY_SESSION=builder-2 COLONY_LEAD=ana-engine-lead COLONY_PERSON=ana" in out
    assert "Never ask the person anything" in out


def test_join_tells_its_lead_with_a_joined_line_the_leads_wait_wakes_on(home, config, github):
    github.add(lead(folders=["apps/api/"]))
    join(config, in_session=True)
    line = "for ana-engine-lead: joined: builder-1 (from builder-1)"
    assert ("issue", "comment", "5", "--repo", config["project"]["repo"], "--body", line) in github.calls
    assert wait.taken(line, wait.lead_session(config, "ana-engine-lead"), "5") == [(line, True)]


def test_join_asks_once_which_lead_when_there_are_two(home, config, github, capsys, monkeypatch):
    github.add(lead(folders=["apps/api/"]))
    github.add(lead(name="ana-web-lead", folders=["apps/web/"]))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    asked = []
    monkeypatch.setattr("builtins.input", lambda text: asked.append(text) or "web")
    join(config, in_session=True)
    assert len(asked) == 1 and "1. ana-engine-lead: apps/api/" in asked[0] and "2. ana-web-lead: apps/web/" in asked[0]
    assert "a helper of ana-web-lead" in capsys.readouterr().out


def test_a_pasted_join_inside_a_session_connects_with_no_further_step(home, config, github, capsys, monkeypatch):
    github.add(lead(folders=["apps/api/"]))
    monkeypatch.setenv("CLAUDECODE", "1")
    join(config, lead="ana-engine-lead", dry_run=False)  # no --in-session: being in a session is enough
    out = capsys.readouterr().out
    assert "This session is builder-1, a helper of ana-engine-lead" in out and "Opening" not in out
    assert presence.parse(github.comments[-1]["body"]).lead == "ana-engine-lead"


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


def whoami(config, *flags):
    parser = argparse.ArgumentParser()
    presence.add_commands(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["whoami", *flags])
    return args.run(config, args)


def test_whoami_names_a_helpers_session_lead_person_and_stream(home, config, monkeypatch, capsys):
    monkeypatch.setenv(cli.SESSION_ENV, "builder-2")
    monkeypatch.setenv(wait.LEAD_ENV, "ana-engine-lead")
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    assert whoami(config) == 0
    assert capsys.readouterr().out == ("session: builder-2\nkind: helper\nlead: ana-engine-lead\nperson: ana\n"
                                       "stream: engine\n")
    assert whoami(config, "--json") == 0
    assert json.loads(capsys.readouterr().out) == {"session": "builder-2", "kind": "helper", "lead": "ana-engine-lead",
                                                   "person": "ana", "stream": "engine"}


def test_whoami_for_a_lead_from_before_lead_names_has_no_stream(home, config, monkeypatch, capsys):
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    assert whoami(config, "--json") == 0
    assert json.loads(capsys.readouterr().out) == {"session": "lead", "kind": "lead", "lead": "ana-lead",
                                                   "person": "ana", "stream": ""}
    monkeypatch.delenv(cli.SESSION_ENV)
    with pytest.raises(cli.ColonyError, match="COLONY_SESSION is not set"):
        whoami(config)


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


def test_a_post_holding_brackets_never_breaks_the_status_read(home, config, github):
    github.add(lead(name="sam-main-lead", person="sam"))
    github.comments.append({"id": 900, "body": "[Sam's Claude] [merged] sam/x → dev 1a2b3c4, fast check passed"})
    assert [status.name for status in presence.read(config)] == ["sam-main-lead"]


def test_a_status_is_posted_fresh_when_the_old_comments_cant_be_read(home, config, github):
    github.unreadable = "gh api failed: HTTP 502"
    state: dict = {}
    assert presence.keep(config, lead(name="ana-main-lead"), state, now=1000.0)
    assert len(github.comments) == 1 and state["status_id"] == github.comments[0]["id"]


def test_who_says_unknown_instead_of_none_when_github_was_not_read(home, config, github, capsys):
    github.unreadable = "gh api failed: HTTP 502"
    assert cli.main(["who"]) == 0
    out, err = capsys.readouterr()
    assert "Helpers: unknown, because GitHub was not read." in out and "none alive" not in out
    assert "GitHub was not read" in err


def test_the_status_keeper_warns_once_per_error_not_at_every_poll(home, config, github, capsys):
    github.down = "gh api failed: check your internet connection or https://githubstatus.com"
    run = presence.keeper(config, argparse.Namespace(person=None), "ana-main-lead", "lead")
    run(), run(), run()
    assert capsys.readouterr().err.count("the status comment was not kept") == 1
    github.down = "gh api failed: HTTP 401"
    run()
    assert "HTTP 401" in capsys.readouterr().err


def test_who_lists_every_live_lead_and_helper_across_computers(home, config, github, capsys):
    github.add(lead(folders=["apps/api/"], person="sam", name="sam-engine-lead", computer="Sam-PC"))
    github.add(presence.Status("builder-2", "helper", person="sam", lead="sam-engine-lead", computer="Sam-PC",
                               account="work", room=["work: 5h 10%"], at=time.time()))
    wait.beat("demo", "ana-lead", "admin", "")  # a lead from before names, on this computer
    assert cli.main(["who"]) == 0
    out = capsys.readouterr().out
    assert "- sam-engine-lead: sam on Sam-PC, account admin" in out and "Folders: apps/api/." in out
    assert "- builder-2 (helper of sam-engine-lead): sam on Sam-PC, account work" in out
    assert "Room: work: 5h 10%." in out
    assert "- ana-lead: ana on " in out


def test_status_names_each_lead_on_this_computer_with_account_and_heartbeat_age(home, config, capsys):
    assert cli.main(["status"]) == 1
    assert "lead: none running on this computer (no heartbeat)" in capsys.readouterr().out
    wait.beat("demo", "ana-engine-lead", "admin", "t", now=time.time() - 30, named=True)
    wait.beat("demo", "ana-lead", "main", "", now=time.time() - 3 * 3600)
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "lead: ana-engine-lead on account admin, heartbeat 30 s ago" in out
    assert "lead: none running as ana-lead on this computer (its heartbeat is 3 h old)" in out


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


# Accounts: each person's order, 5-hour and weekly use with their resets, and the last resort


def usage(home: Path, folder: str, five=None, week=None, week_resets_in=timedelta(days=3),
          five_resets_in=timedelta(hours=2)) -> str:
    path = home / folder
    path.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    windows = {}
    if five is not None:
        windows["five_hour"] = {"utilization": five, "resets_at": (now + five_resets_in).isoformat()}
    if week is not None:
        windows["seven_day"] = {"utilization": week, "resets_at": (now + week_resets_in).isoformat()}
    if windows:
        (path / ".claude.json").write_text(json.dumps({"cachedUsageUtilization": {"utilization": windows}}))
    return str(path)


def accounts(home, *specs, last=()):
    """Ana's shape: [people.ana] accounts in order, and last_resort."""
    found = {name: {"config_dir": usage(home, name, **kw), "person": "ana"} for name, kw in [*specs, *last]}
    order = [name for name, _ in specs]
    return {"project": {}, "accounts": found,
            "people": {"ana": {"accounts": order, "last_resort": [name for name, _ in last]}}}


def test_use_it_or_lose_it_the_soonest_weekly_reset_with_room_comes_first(home):
    config = accounts(home, ("team", {"five": 5, "week": 10, "week_resets_in": timedelta(days=5)}),
                      ("admin", {"five": 40, "week": 70, "week_resets_in": timedelta(hours=20)}),
                      ("ana", {"five": 0, "week": 0, "week_resets_in": timedelta(days=6)}))
    name, _, why = cli.pick(config, "ana")
    assert name == "admin" and why == "admin: weekly resets in 19 h, 30% left; 5h 40% used, resets in 1 h"


def test_a_tie_on_the_weekly_reset_goes_to_the_most_five_hour_room(home):
    same = timedelta(days=2)
    config = accounts(home, ("team", {"five": 60, "week": 10, "week_resets_in": same}),
                      ("admin", {"five": 20, "week": 10, "week_resets_in": same}))
    assert cli.pick(config, "ana")[0] == "admin"


def test_out_of_five_hour_room_or_near_it_with_a_far_reset_is_skipped(home):
    config = accounts(home, ("team", {"five": 97, "week": 10, "week_resets_in": timedelta(hours=1)}),
                      ("admin", {"five": 85, "week": 10, "week_resets_in": timedelta(hours=2),
                                 "five_resets_in": timedelta(hours=3)}),
                      ("ana", {"five": 50, "week": 10}))
    assert cli.pick(config, "ana")[0] == "ana"
    near_reset = accounts(home, ("admin", {"five": 85, "week": 10, "five_resets_in": timedelta(minutes=20)}),
                          ("ana", {"five": 10, "week": 10, "week_resets_in": timedelta(days=6)}))
    assert cli.pick(near_reset, "ana")[0] == "admin"  # near its limit, but the reset is minutes off


def test_a_full_week_is_skipped(home):
    config = accounts(home, ("team", {"five": 0, "week": 97, "week_resets_in": timedelta(hours=1)}),
                      ("admin", {"five": 0, "week": 50}))
    assert cli.pick(config, "ana")[0] == "admin"


def test_an_account_with_no_reading_ranks_after_known_room_in_the_persons_order(home):
    config = accounts(home, ("team", {}), ("admin", {"five": 60, "week": 50}))
    assert cli.pick(config, "ana")[0] == "admin"
    config = accounts(home, ("team", {}), ("admin", {"five": 99}))
    name, _, why = cli.pick(config, "ana")
    assert name == "team" and "no saved reading" in why


def test_the_last_resort_is_used_only_when_no_other_account_has_room(home):
    config = accounts(home, ("team", {"five": 99}), ("admin", {"five": 50, "week": 10}),
                      last=[("engineering", {"five": 0, "week": 0, "week_resets_in": timedelta(hours=1)})])
    assert cli.pick(config, "ana")[0] == "admin"  # engineering resets sooner, but it is the last resort
    config = accounts(home, ("team", {"five": 99}), ("admin", {"week": 99}),
                      last=[("engineering", {"five": 0, "week": 0})])
    name, _, why = cli.pick(config, "ana")
    assert name == "engineering" and why.endswith("(last resort)")


def test_every_account_out_of_room_names_the_first_and_says_why(home):
    config = accounts(home, ("team", {"five": 99}), ("admin", {"five": 98}))
    name, _, why = cli.pick(config, "ana")
    assert name == "team" and why.startswith("every account is out of room, so team, the first")


def test_a_session_prints_why_its_account_was_picked(home, config, capsys):
    usage(home, ".claude-work", five=10, week=40, week_resets_in=timedelta(hours=30))
    cli.lead(config, argparse.Namespace(person="ana", here=True, dry_run=True, account=None))
    assert "why: admin: weekly resets in 29 h, 60% left; 5h 10% used" in capsys.readouterr().out


def test_the_person_comes_from_the_gh_login_through_people(home, monkeypatch):
    config = {"accounts": {"a": {"config_dir": "x", "person": "ana"}, "b": {"config_dir": "y", "person": "sam"}},
              "people": {"ana": {"login": "ana-gh"}}}
    monkeypatch.setattr(cli, "git_user", lambda: set())
    monkeypatch.setattr(cli, "gh_login", lambda: "ana-gh")
    assert cli.default_person(config) == "ana"


def test_the_room_text_names_both_windows_and_their_resets(home):
    folder = usage(home, "admin", five=40, week=63)
    text = cli.room_text("admin", folder)
    assert text.startswith("admin: 5h 40% (resets ") and ", week 63% (resets " in text and text.endswith(" UTC)")
    assert cli.room_text("x", usage(home, "x")) == "x: no reading"


# The setup skill


def test_skill_install_copies_the_setup_skill_into_a_settings_folder(home, capsys):
    folder = home / ".claude-work"
    folder.mkdir()
    assert cli.main(["skill-install", "--config-dir", str(folder)]) == 0
    copied = folder / "skills" / "colony-setup" / "SKILL.md"
    assert copied.read_text() == (PACKAGE / "skills" / "colony-setup" / "SKILL.md").read_text()


# Opening helpers: ask every time, with the last answer as the default; colony view


def helpers(config, count=2, **flags):
    args = argparse.Namespace(count=count, open=False, paste=False, person="ana", account=None, dry_run=True)
    vars(args).update(flags)
    return cli.helpers(config, args)


def test_the_lead_asks_open_or_paste_every_time_with_the_last_answer_as_the_default(home, config, github, capsys,
                                                                                   monkeypatch):
    monkeypatch.setenv(wait.LEAD_ENV, "ana-main-lead")
    helpers(config)
    out = capsys.readouterr().out
    assert '"I need 2 helpers. Open them myself on main, or you paste?" [Open them] [I\'ll paste]' in out
    helpers(config, paste=True)
    out = capsys.readouterr().out
    assert out.count("  colony join ana-main-lead\n") == 2
    assert "helpers_answer" in (config_path := cli.local_path()).read_text() and config_path.exists()
    assert "local.toml" in (cli.local_path().parent / ".gitignore").read_text()
    helpers(config)  # asked again, now with the last answer first
    assert "[I'll paste] [Open them]" in capsys.readouterr().out


def test_open_them_opens_each_helper_for_this_lead_under_free_names(home, config, github, capsys, monkeypatch):
    monkeypatch.setenv(wait.LEAD_ENV, "ana-main-lead")
    monkeypatch.setattr(cli, "cmux_usable", lambda: False)
    helpers(config, open=True)
    out = capsys.readouterr().out
    assert "demo-builder-1" in out and "demo-builder-2" in out
    assert "paste this into any cmux terminal: colony view" in out
    assert 'helpers_answer = "open"' in cli.local_path().read_text()


def test_colony_view_builds_one_cmux_command_per_running_session(home, config, capsys, monkeypatch):
    (home / ".claude-work").mkdir()
    (home / ".claude").mkdir()
    listed = {str(home / ".claude-work"): [{"id": "aa11", "name": "demo-lead", "cwd": "/r"},
                                             {"id": "bb22", "name": "demo-builder-1", "cwd": "/r"},
                                             {"id": "cc33", "name": "other-project-lead", "cwd": "/x"}],
              str(home / ".claude"): [{"id": "dd44", "name": "demo-builder-2", "cwd": "/r"}]}

    def run(argv, **kwargs):
        folder = kwargs["env"].get("CLAUDE_CONFIG_DIR", str(home / ".claude"))
        return subprocess.CompletedProcess(argv, 0, json.dumps(listed[folder]), "")
    monkeypatch.setattr(cli.subprocess, "run", run)
    commands = cli.view_commands(config)
    assert [c[3] for c in commands] == ["demo-builder-2", "demo-lead", "demo-builder-1"] or \
        sorted(c[3] for c in commands) == ["demo-builder-1", "demo-builder-2", "demo-lead"]
    assert len(commands) == 3  # one per running Colony session, none for another project
    admin = next(c for c in commands if c[3] == "demo-lead")
    assert admin[-1] == shlex.join(["env", f"CLAUDE_CONFIG_DIR={home / '.claude-work'}", "claude", "attach", "aa11"])
    default = next(c for c in commands if c[3] == "demo-builder-2")
    assert default[-1] == "claude attach dd44"  # the default folder stays unset, or the login is lost


# A pasted image goes on the card's branch


def test_a_pasted_image_lands_on_the_cards_branch_for_every_helper(home, host, config, monkeypatch, capsys):
    remote = home / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "dev", str(remote)], check=True)
    for step in (["remote", "add", "origin", str(remote)], ["commit", "-q", "--allow-empty", "-m", "start"],
                 ["push", "-q", "origin", "HEAD:dev"]):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *step], cwd=host, check=True)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    comments = []
    monkeypatch.setattr(wait, "gh", lambda *args: comments.append(args) or "")
    picture = home / "Screenshot 1.png"
    picture.write_bytes(b"\x89PNG fake")
    config["project"]["worktrees"] = str(home / "trees")
    assert cli.image(config, argparse.Namespace(card=12, file=str(picture))) == 0
    shown = subprocess.run(["git", "--git-dir", str(remote), "show", "card/12:.colony/images/12/Screenshot-1.png"],
                           capture_output=True, check=True).stdout
    assert shown == b"\x89PNG fake"
    assert "on the branch `card/12`" in comments[0][-1]
    assert not (host / ".colony" / "images").exists()  # the lead's own checkout is untouched
    assert not (home / "trees" / "demo-image-12").exists()  # the throwaway worktree is gone
    with pytest.raises(cli.ColonyError, match="is not an image file"):
        cli.image(config, argparse.Namespace(card=12, file=str(home / "notes.txt")))


def test_a_named_leads_card_line_reaches_its_own_helper(home, monkeypatch, capsys):
    posted = []
    monkeypatch.setattr("colony.transport.send", lambda config, to, line, card=None: posted.append(line) or card)
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    monkeypatch.setenv(wait.LEAD_ENV, "ana-engine-lead")
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    config = {"project": {"repo": "acme/demo", "name": "demo"}}
    wait.post(config, argparse.Namespace(card=12, to="builder-1", sentence="start: this card", urgent=False))
    assert posted == ["for builder-1: start: this card (from ana-engine-lead)"]
    monkeypatch.setenv(cli.SESSION_ENV, "builder-1")
    helper = wait.builder_session(config, "builder-1")
    assert wait.taken(posted[0], helper, "12")  # the helper takes it


def test_every_new_session_is_told_to_take_its_role_name_in_the_sidebar(home, config, github, capsys):
    rename = "Rename this session in the app's sidebar to {}, with the app's own rename tool when you have one"
    assert cli.main(["research", "Which queue?", "--dry-run", "--person", "ana"]) == 0
    assert rename.format("researcher") in capsys.readouterr().out.replace("'\"'\"'", "'")  # shlex quotes each '
    github.add(lead(name="ana-main-lead"))
    assert cli.main(["join", "--in-session", "--person", "ana"]) == 0
    assert rename.format("builder-1") in capsys.readouterr().out
    assert cli.main(["claim", "web", "--person", "ana"]) == 0
    assert rename.format("ana-web-lead") in capsys.readouterr().out
