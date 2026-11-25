"""Tests for spinning up the team: builders only as helpers, the lead's own account kept for it, the subagent guard,
live readings before every placement, planning around resets, and finding accounts (plan tasks 80 to 85)."""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import stub_path
from colony import cli, guards

PACKAGE = Path(__file__).resolve().parent.parent / "colony"
AGENT_GUARD = PACKAGE / "hooks" / "agent_guard.py"


def agent_guard():
    """The subagent guard script as a module."""
    spec = importlib.util.spec_from_file_location("colony_agent_guard", AGENT_GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 82. The subagent guard


@pytest.fixture
def session(tmp_path, monkeypatch):
    """A repo with a Colony config, a HOME, and a Claude Code transcript whose subagents folder the test fills."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    repo = tmp_path / "repo"
    (repo / ".colony").mkdir(parents=True)
    (repo / ".colony" / "colony.toml").write_text('[project]\nname = "demo"\n')
    transcript = tmp_path / "projects" / "demo" / "sid-1.jsonl"
    (transcript.with_suffix("") / "subagents").mkdir(parents=True)
    transcript.write_text("{}\n")
    return {"repo": repo, "transcript": transcript}


def subagent(session, agent: str, call: str, finished: bool = False, age: float = 0.0) -> None:
    """One subagent's files beside the session's transcript, as Claude Code writes them."""
    folder = session["transcript"].with_suffix("") / "subagents"
    meta = {"agentType": "general-purpose", "description": "a piece", "toolUseId": call,
            **({"finished": True} if finished else {})}
    (folder / f"agent-{agent}.meta.json").write_text(json.dumps(meta))
    log = folder / f"agent-{agent}.jsonl"
    log.write_text("{}\n")
    if age:
        os.utime(log, (time.time() - age, time.time() - age))


def call(session, tool="Agent", use="toolu_new", session_id="sid-1") -> dict:
    return {"tool_name": tool, "tool_use_id": use, "session_id": session_id, "cwd": str(session["repo"]),
            "transcript_path": str(session["transcript"]), "tool_input": {"description": "x", "prompt": "y"}}


def run_guard(payload: dict, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(AGENT_GUARD)], input=json.dumps(payload), capture_output=True,
                          text=True, env={"PATH": os.environ["PATH"], **env})


def test_the_subagent_guard_refuses_a_leads_call_past_the_cap_and_points_to_helpers(session):
    subagent(session, "a1", "toolu_1")
    subagent(session, "a2", "toolu_2")
    run = run_guard(call(session), {"HOME": str(session["repo"].parent), "COLONY_SESSION": "lead"})
    assert run.returncode == 2
    assert "already runs 2 subagents" in run.stderr and "[subagents] max_running = 2" in run.stderr
    assert "colony helpers <n> --open" in run.stderr and "colony open <name>" in run.stderr


def test_the_subagent_guard_lets_a_call_under_the_cap_run_and_ignores_other_tools(session):
    subagent(session, "a1", "toolu_1")
    env = {"HOME": str(session["repo"].parent), "COLONY_SESSION": "builder-1"}
    assert run_guard(call(session), env).returncode == 0
    subagent(session, "a2", "toolu_2")
    subagent(session, "a3", "toolu_3")
    assert run_guard(call(session, tool="Bash"), env).returncode == 0
    refused = run_guard(call(session, use="toolu_4"), env)
    assert refused.returncode == 2 and "wait for one of yours to finish" in refused.stderr
    assert "helpers <n> --open" not in refused.stderr  # a helper's refusal speaks to a helper


def test_a_session_outside_colony_is_never_capped(session):
    for n in range(4):
        subagent(session, f"a{n}", f"toolu_{n}")
    assert run_guard(call(session), {"HOME": str(session["repo"].parent)}).returncode == 0


def test_finished_and_long_quiet_subagents_no_longer_count(session, monkeypatch):
    guard = agent_guard()
    monkeypatch.setenv("COLONY_SESSION", "lead")
    subagent(session, "done", "toolu_1", finished=True)
    subagent(session, "dead", "toolu_2", age=(guard.STALE_MINUTES + 1) * 60)
    subagent(session, "live", "toolu_3")
    assert guard.decide(call(session)) == (True, "")


def test_calls_let_through_count_until_their_files_show_up(session, monkeypatch):
    """Calls made side by side start before Claude Code writes their files: the guard counts its own."""
    guard = agent_guard()
    monkeypatch.setenv("COLONY_SESSION", "lead")
    now = time.time()
    assert guard.decide(call(session, use="toolu_1"), now)[0]
    assert guard.decide(call(session, use="toolu_2"), now)[0]
    assert not guard.decide(call(session, use="toolu_3"), now)[0]
    subagent(session, "a1", "toolu_1", finished=True)  # the first one ran and finished
    assert guard.decide(call(session, use="toolu_3"), now + 1)[0]
    assert guard.decide(call(session, use="toolu_4"), now + guard.GRACE + 1)[0]  # the rest never started


def test_the_cap_comes_from_the_local_file_then_the_tracked_one(session, monkeypatch):
    guard = agent_guard()
    monkeypatch.setenv("COLONY_SESSION", "builder-2")
    repo = session["repo"]
    (repo / ".colony" / "colony.toml").write_text('[project]\nname = "demo"\n[subagents]\nmax_running = 0\n')
    allowed, refusal = guard.decide(call(session))
    assert not allowed and "max_running = 0" in refusal
    (repo / ".colony" / "colony.local.toml").write_text("[subagents]\nmax_running = 3  # mine\n")
    assert guard.cap(str(repo)) == 3


def test_the_cap_reads_without_tomllib_on_an_older_python(session, monkeypatch):
    guard = agent_guard()
    monkeypatch.setitem(sys.modules, "tomllib", None)  # `import tomllib` raises ImportError, as on Python 3.9
    text = '[project]\nname = "demo"\n\n[subagents]\n# a comment\nmax_running = 1  # one\n\n[watch]\nmax_running = 9\n'
    assert guard.cap_in(text) == 1
    assert guard.cap_in('[watch]\nmax_running = 9\n') is None


def test_a_lead_a_person_opened_is_known_by_its_saved_identity(session, monkeypatch):
    guard = agent_guard()
    sessions = session["repo"].parent / ".colony" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "sid-1.json").write_text(json.dumps({"COLONY_SESSION": "lead", "COLONY_LEAD": "ana-main-lead"}))
    subagent(session, "a1", "toolu_1")
    subagent(session, "a2", "toolu_2")
    allowed, refusal = guard.decide(call(session))
    assert not allowed and "A lead or an orchestrator never builds through subagents" in refusal


def test_colony_installs_the_subagent_guard_with_its_other_hooks(tmp_path, monkeypatch):
    entries = {(event, matcher, marker) for event, matcher, _, marker in guards.hook_entries()}
    assert ("PreToolUse", "Agent|Task", f"{cli.DIR}/hooks/agent_guard.py") in entries
    plugin = guards.plugin_hooks()["hooks"]["PreToolUse"]
    assert plugin[1]["matcher"] == "Agent|Task"
    assert '"${CLAUDE_PLUGIN_ROOT}/colony/hooks/agent_guard.py"' in plugin[1]["hooks"][0]["command"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    assert guards.install({}, argparse.Namespace(dry_run=False)) == 0
    assert (tmp_path / cli.DIR / "hooks" / "agent_guard.py").read_text() == AGENT_GUARD.read_text()
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert any(group.get("matcher") == "Agent|Task" for group in settings["hooks"]["PreToolUse"])


# The shared world for 81 to 85: three accounts of one person, from the capacity tests

from test_capacity import CONFIG, home, host, load, running  # noqa: E402,F401  (home and host are fixtures)
from colony import accounts, capacity, forecast, presence, statuspage, watch  # noqa: E402


def reading(folder: Path, five=None, week=None, five_resets_in=timedelta(hours=3), week_resets_in=timedelta(days=3),
            read_ago: float = 0.0, signed_in: bool = True) -> None:
    """Save a usage reading in an account folder as Claude Code does, with the time it was fetched."""
    now = datetime.now(timezone.utc)
    windows = {}
    if five is not None:
        windows["five_hour"] = {"utilization": five, "resets_at": (now + five_resets_in).isoformat()}
    if week is not None:
        windows["seven_day"] = {"utilization": week, "resets_at": (now + week_resets_in).isoformat()}
    state = {"cachedUsageUtilization": {"utilization": windows, "fetchedAtMs": (time.time() - read_ago) * 1000}}
    if signed_in:
        state["oauthAccount"] = {"accountUuid": "x"}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".claude.json").write_text(json.dumps(state))


def history(config: dict, name: str, points: list[tuple[float, float, int]], resets_in=timedelta(hours=3)) -> None:
    """Kept readings for an account: (minutes ago, 5-hour percent used, helpers) each, in one 5-hour window."""
    resets = (datetime.now(timezone.utc) + resets_in).timestamp()
    held = forecast.history(config)
    held[name] = [{"at": time.time() - ago * 60, "five_hour": [used, resets], "helpers": helpers}
                  for ago, used, helpers in points]
    capacity.wait.write_json(capacity.state(config["project"]["name"], forecast.HISTORY), held)


def ana(account=None) -> argparse.Namespace:
    return argparse.Namespace(person="ana", account=account)


# 81. The lead's own account is kept for it


def test_a_helper_never_opens_on_a_live_leads_own_account_unless_the_config_allows_it(host):
    for name in ("main", "team", "spare"):
        reading(host.parent / name, five=10, week=10)
    config = load('[pool]\norder = "listed"\n')
    leads = capacity.lead_accounts(config, [presence.Status("ana-main-lead", "lead", account="main")])
    assert leads == {"main": ["ana-main-lead"]}
    counts = {"main": set(), "team": set(), "spare": set()}
    assert capacity.helper_account(config, ana(), counts, leads)[0] == "team"
    shared = load('[pool]\norder = "listed"\nshare_lead_accounts = true\n')
    assert capacity.helper_account(shared, ana(), counts, leads)[0] == "main"
    assert capacity.helper_account(config, ana("main"), counts, leads)[0] == "main"  # --account still wins


def test_the_lead_that_runs_the_command_keeps_its_own_account(host, monkeypatch):
    config = load()
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(host.parent / "team"))
    assert capacity.lead_accounts(config, []) == {"team": ["lead"]}
    monkeypatch.setenv(cli.SESSION_ENV, "builder-1")
    assert capacity.lead_accounts(config, []) == {}


def test_a_leads_own_account_is_shared_only_when_it_is_the_persons_only_account(host, monkeypatch, capsys):
    """Review finding 7, the plan's task 81: helpers never open on a live lead's own account unless the person allows
    it in config. With several accounts and only the lead's with room, helpers wait; [pool] share_lead_accounts lets
    them in. With one account, its helpers share it, under a cap one lower, with one warning. (The rule a33bd72 set,
    sharing whenever no other account had room, no longer holds.)"""
    config = load("[pool]\nmax_busy = 1\n")
    here = [running("builder-1", host.parent / "team"), running("builder-2", host.parent / "spare")]
    monkeypatch.setattr(presence, "everyone",
                        lambda config: ([presence.Status("ana-main-lead", "lead", account="main")], [], ""))
    monkeypatch.setattr(cli, "running_sessions", lambda config: here)
    args = argparse.Namespace(name="builder-3", person="ana", account=None, dry_run=True, here=False)
    with pytest.raises(cli.ColonyError, match="main is kept for ana-main-lead, its own account.*share_lead_accounts"):
        cli.open_builder(config, args)
    assert "Warning" not in capsys.readouterr().out
    shared = load("[pool]\nmax_busy = 1\nshare_lead_accounts = true\n")
    args.account = None
    assert cli.open_builder(shared, args) == 0 and args.account == "main"  # the person allowed it
    alone = load("[pool]\nmax_busy = 1\n")
    alone["people"]["ana"]["accounts"] = ["main"]
    args.account = None
    assert cli.open_builder(alone, args) == 0 and args.account == "main"
    out = capsys.readouterr().out
    assert out.count("Warning: account main is ana-main-lead's own, and the only account you have") == 1
    assert "at most 1 at once" in out and "put this one in [pool] reserve" in out
    here.append(running("builder-3", host.parent / "main"))  # the lead's account at its lower cap: no more there
    args.account = None
    with pytest.raises(cli.ColonyError, match="main is ana-main-lead's own and runs 1 helpers, the most it takes"):
        cli.open_builder(alone, args)


def test_with_several_accounts_out_of_room_helpers_wait_for_the_soonest_reset_never_the_leads(host):
    """Review finding 7: with every other account out of room, a helper waits for the soonest reset, as open-later
    does for NO_FIT, rather than opening on the lead's own account or on an account out of room."""
    reading(host.parent / "main", five=10, week=10)
    for name in ("team", "spare"):
        reading(host.parent / name, five=97, week=10, five_resets_in=timedelta(hours=1))
    config = load('[pool]\norder = "listed"\n')
    found, why = capacity.place(config, ana(), {}, {"main": ["ana-main-lead"]})
    assert found is None and why.startswith(capacity.NO_FIT), why
    assert "team and spare are out of room until their windows reset" in why


def test_colony_capacity_marks_the_account_kept_for_a_lead(host, monkeypatch, capsys):
    config = load()
    reading(host.parent / "main", five=10, week=10)
    monkeypatch.setattr(presence, "everyone",
                        lambda config: ([presence.Status("ana-main-lead", "lead", account="main")], [], ""))
    monkeypatch.setattr(cli, "running_sessions", lambda config: [])
    assert capacity.show(config, argparse.Namespace(person="ana", json=False)) == 0
    out = capsys.readouterr().out
    assert "- main: 5h 10%" in out and "Kept for ana-main-lead, its own account: a helper opens here only when no " \
        "other account has room, at most 2 at once" in out


# 83. Live usage before every placement


def test_a_reading_past_its_staleness_limit_never_places_a_session(host):
    reading(host.parent / "main", five=0, week=0, read_ago=2 * 3600)  # looks empty, but it is two hours old
    reading(host.parent / "team", five=50, week=50)
    reading(host.parent / "spare", five=60, week=60)
    config = load('[pool]\norder = "listed"\n')
    tier, _, why = capacity.judge(config, "main", datetime.now(timezone.utc))
    assert tier == 1 and "its last reading is 2 h old, past [pool] stale_minutes (15)" in why
    assert cli.pick(config, "ana")[0] == "team"
    assert cli.pick(load('[pool]\norder = "listed"\nstale_minutes = 180\n'), "ana")[0] == "main"


def test_the_staleness_limit_is_never_shorter_than_a_readings_refresh(host):
    with pytest.raises(cli.ColonyError, match="stale_minutes is a number of at least 10"):
        capacity.policy(load("[pool]\nstale_minutes = 5\n"))


def test_every_room_line_says_how_old_its_reading_is(host):
    reading(host.parent / "main", five=40, week=63, read_ago=180)
    assert cli.room_text("main", str(host.parent / "main")).endswith(", read 3 min ago")


def test_the_watch_and_the_status_page_show_each_readings_age(host, monkeypatch):
    reading(host.parent / "main", five=40, week=63, read_ago=180)
    reading(host.parent / "team", five=10, week=10, read_ago=2 * 3600)
    config = load()
    lines = forecast.account_lines(config)
    assert lines[0].startswith("main: 5h 40% (resets ") and lines[0].endswith("read 3 min ago")
    assert "read 2 h ago: stale, past [pool] stale_minutes (15)" in lines[1] and lines[2] == "spare: no reading"
    page = statuspage.render(config, {}, watch.settings(config), time.time())
    assert "## Accounts" in page and "- main: 5h 40%" in page and ", read at " in page
    monkeypatch.setattr(watch, "team_now", lambda config, now: ({}, ""))
    monkeypatch.setattr("colony.progress.cards_or_note", lambda config: ([], "no board"))
    args = argparse.Namespace(json=False, page=False, folded=False)
    out = io_run(lambda: watch.watch_command(config, args))
    assert "Accounts on this computer:" in out and "- main: 5h 40%" in out and "read 3 min ago" in out


def io_run(command) -> str:
    """What a command prints."""
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        command()
    return buffer.getvalue()


# 84. Plan around resets


def test_the_burn_rate_comes_from_successive_readings_overall_and_per_helper(host):
    config = load()
    history(config, "main", [(50, 20, 2), (30, 30, 2), (0, 40, 2)])
    found = forecast.burn(forecast.history(config)["main"], "five_hour")
    assert round(found.rate) == 24 and found.helpers == 2 and round(found.per_helper) == 12
    history(config, "team", [(3, 20, 1), (0, 21, 1)])  # three minutes apart make no rate yet
    assert forecast.burn(forecast.history(config)["team"], "five_hour") is None


def test_a_helper_that_would_run_an_account_out_before_its_reset_opens_on_another(host):
    reading(host.parent / "main", five=60, week=10, five_resets_in=timedelta(hours=3))
    reading(host.parent / "team", five=10, week=10)
    config = load('[pool]\norder = "listed"\n')
    history(config, "main", [(40, 47, 2), (0, 60, 2)])  # about 20% an hour with 2 helpers
    counts = {"main": {"builder-1", "builder-2"}, "team": set(), "spare": set()}
    fit, why = forecast.fits(config, "main", 3)
    assert not fit and "3 helpers on main would run its 5-hour window out around" in why
    name, _, why = capacity.helper_account(config, ana(), counts, {})
    assert name == "team" and "it lasts to its 5-hour reset" in why


def test_helpers_that_fit_nowhere_wait_for_the_soonest_reset(host, monkeypatch):
    reading(host.parent / "main", five=70, week=10, five_resets_in=timedelta(hours=2))  # 2 helpers: 20% an hour
    config = load('[pool]\norder = "listed"\nwave = 1\nreserve = ["team", "spare"]\n')  # main alone takes helpers
    found, why = capacity.place(config, ana(), {"main": {"builder-1"}}, {})
    assert found is None and why.startswith(capacity.NO_FIT)
    resets = forecast.next_reset(config, "ana")
    slept, waves = [], [(0, why), (1, "")]
    monkeypatch.setattr(capacity, "SLEEP", slept.append)
    monkeypatch.setattr(capacity, "open_wave", lambda config, args, count, taken: waves.pop(0))
    assert capacity.open_later(config, argparse.Namespace(count=1, taken="", person="ana", account=None)) == 0
    assert slept[0] == 60  # the first wave of open-later, [pool] wave_seconds after the first one
    assert abs(slept[1] - (resets + capacity.LIMIT_GRACE - time.time())) < 5  # the next wave starts at the reset


def test_the_leads_wait_warns_ahead_in_plain_words_and_names_where_to_move_helpers(host, monkeypatch):
    reading(host.parent / "main", five=60, week=10, five_resets_in=timedelta(hours=3))
    reading(host.parent / "team", five=5, week=10)
    config = load()
    history(config, "main", [(40, 40, 3), (0, 60, 3)])  # 30% an hour with 3 helpers: out in about 70 minutes
    here = [running(f"builder-{n}", host.parent / "main") for n in (1, 2, 3)]
    monkeypatch.setattr(cli, "running_sessions", lambda config: here)
    monkeypatch.setattr(cli, "refresh_usage", lambda folders: None)
    held = {}
    assert forecast.lead_part(config, held) == []  # the first poll only starts the clock
    held["at"] -= forecast.OBSERVE_EVERY
    [line] = forecast.lead_part(config, held)
    assert line.startswith("account main runs out around ") and "and that window resets at " in line
    assert "(30% of its 5-hour window an hour, with 3 helpers here)" in line
    assert "move 2 helpers to team, which has room for them" in line and "--account team" in line
    held["at"] -= forecast.OBSERVE_EVERY
    assert forecast.lead_part(config, held) == []  # once a stretch


def test_colony_capacity_shows_each_accounts_forecast_beside_its_resets(host, monkeypatch, capsys):
    reading(host.parent / "main", five=60, week=10, five_resets_in=timedelta(hours=3))
    config = load()
    history(config, "main", [(40, 40, 2), (0, 60, 2)])
    monkeypatch.setattr(presence, "everyone", lambda config: ([], [], ""))
    monkeypatch.setattr(cli, "running_sessions", lambda config: [])
    assert capacity.show(config, argparse.Namespace(person="ana", json=False)) == 0
    out = capsys.readouterr().out
    assert "Forecast: 5-hour: runs out around " in out and "before it resets at " in out
    assert "15.0% an hour per busy helper, over 2.0 helpers" in out
    assert "Forecast: no forecast: no reading" in out  # team has none


# 85. Finding accounts


def settings_folder(home: Path, name: str, signed_in: bool = True) -> Path:
    folder = home / name
    reading(folder, five=5, week=5, signed_in=signed_in)
    return folder


def test_scan_offers_each_new_signed_in_folder_and_add_writes_only_the_local_layer(host, capsys):
    settings_folder(host.parent, ".claude-work")
    settings_folder(host.parent, ".claude-old", signed_in=False)
    config = load()
    tracked = (host / ".colony" / "colony.toml").read_text()
    assert cli.main(["accounts", "scan"]) == 0
    out = capsys.readouterr().out
    assert "~/.claude-work, signed in, in no [accounts.<name>] table" in out and ".claude-old" not in out
    assert "colony accounts add work --dir ~/.claude-work --person ana" in out
    assert cli.main(["accounts", "scan", "--add"]) == 0
    assert "Wrote the new account work, ~/.claude-work" in capsys.readouterr().out
    assert (host / ".colony" / "colony.toml").read_text() == tracked
    local = (host / ".colony" / "colony.local.toml").read_text()
    assert '[accounts.work]\nconfig_dir = "~/.claude-work"\nperson = "ana"' in local
    assert cli.load_config()["accounts"]["work"]["person"] == "ana"
    assert "[people.ana] accounts lists that person's accounts by name" in accounts.write_account(
        cli.load_config(), "work", "~/.claude-work")
    assert accounts.new_folders(cli.load_config()) == []


def test_add_sets_this_computers_folder_for_an_account_the_team_names(host):
    folder = settings_folder(host.parent, "elsewhere")
    config = load()
    message = accounts.write_account(config, "spare", str(folder))
    assert message.startswith("Wrote this computer's folder for spare, ~/elsewhere")
    assert cli.load_config()["accounts"]["spare"]["config_dir"] == str(folder)
    with pytest.raises(cli.ColonyError, match="is not a folder on this computer"):
        accounts.write_account(config, "x", "~/nowhere")


def test_the_briefing_flags_accounts_missing_signed_out_and_new(host):
    (host.parent / "spare").rmdir()
    reading(host.parent / "team", five=5, week=5, signed_in=False)
    settings_folder(host.parent, ".claude-work")
    [line] = accounts.briefing_lines(load())
    assert "signed out here: team" in line and "missing on this computer: spare" in line
    assert "new and signed in, not in the pool: ~/.claude-work" in line


def test_the_leads_wait_flags_an_account_that_left_and_a_new_folder_once(host):
    config = load()
    held = {}
    assert accounts.wait_lines(config, held) == []  # the first look notes, since the briefing named it all
    (host.parent / "spare").rmdir()
    settings_folder(host.parent, ".claude-work")
    held["at"] -= accounts.WAIT_EVERY
    lines = accounts.wait_lines(config, held)
    assert any(line.startswith("account spare's folder is no longer on this computer") for line in lines)
    assert any("a new signed-in settings folder is on this computer, ~/.claude-work" in line for line in lines)
    held["at"] -= accounts.WAIT_EVERY
    assert accounts.wait_lines(config, held) == []


def test_colony_accounts_lists_each_account_here_and_elsewhere(host, monkeypatch, capsys):
    reading(host.parent / "main", five=40, week=63, read_ago=60)
    (host.parent / "spare").rmdir()
    settings_folder(host.parent, ".claude-work")
    load()
    other = presence.Status("builder-9", "helper", computer="other-pc", at=time.time() - 120,
                            room=["team: 5h 10%, read 1 min ago"])
    monkeypatch.setattr(presence, "everyone", lambda config: ([other], [], ""))
    monkeypatch.setattr(cli, "running_sessions", lambda config: [])
    assert cli.main(["accounts"]) == 0
    out = capsys.readouterr().out
    assert "- main (ana): signed in. 5h 40%" in out and "read 1 min ago" in out and "Forecast:" in out
    assert "- spare (ana): not on this computer" in out and "accounts add spare --dir <folder>" in out
    assert "- other-pc, 2 min ago: team: 5h 10%, read 1 min ago." in out
    assert "New here, signed in, in no [accounts.<name>] table: ~/.claude-work" in out


def test_the_startup_briefing_flags_accounts_and_forecasts(host, monkeypatch):
    from colony import boot

    reading(host.parent / "main", five=60, week=10, five_resets_in=timedelta(hours=3))
    (host.parent / "spare").rmdir()
    config = load()
    history(config, "main", [(40, 40, 3), (0, 60, 3)])
    monkeypatch.setattr(cli, "running_sessions", lambda config: [])
    lines = boot.capacity_part(config, "ana")
    assert any(line.startswith("Accounts: main: 5h 60%") and "read " in line for line in lines)
    assert any("missing on this computer: spare" in line for line in lines)
    assert any(line.startswith("Forecast: main runs out around ") and "before its 5-hour window resets" in line
               for line in lines)


# 80. Builders run only as helpers


def section(text: str, heading: str) -> str:
    start = text.index(f"\n{heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else None]


def test_the_playbook_and_the_skills_say_builders_run_only_as_helpers():
    import tomllib

    playbook = (PACKAGE / "playbook.md").read_text()
    rules = section(playbook, "## Subagents")
    assert "Builders run only as helpers, never as subagents." in rules
    assert "`colony helpers <n> --open` or `colony open <name>`" in rules and "[subagents] max_running" in rules
    assert "**Speed.**" not in rules  # the old "subagents for speed" invitation is gone
    assert "only for two things:** a quick search" in rules
    assert "never to subagents of yours or theirs" in section(playbook, "## Orchestrator")
    assert "at least every 30 minutes" in section(playbook, "### Capacity")
    lead = (PACKAGE / "skills" / "colony-lead" / "SKILL.md").read_text()
    assert "Never start a subagent to build" in lead and "at least every 30 minutes" in lead
    builder = (PACKAGE / "skills" / "colony-builder" / "SKILL.md").read_text()
    assert "only for a quick search or a browser check" in builder and "for speed" not in builder
    orchestrator = tomllib.loads((PACKAGE / "modes" / "work" / "orchestrator.toml").read_text())
    assert any("Never start a subagent to build" in rule["text"] for rule in orchestrator["rules"])


def test_a_short_span_of_the_weekly_window_makes_no_rate_and_an_unstarted_window_raises_no_warning(host, monkeypatch):
    """Regression: usage comes in whole percents, so ten minutes of the weekly window read one step as 6% an hour;
    and a window not started has no reset time, whose guess moved on every look and repeated the warning."""
    config = load()
    week = (datetime.now(timezone.utc) + timedelta(days=3)).timestamp()
    held = {"main": [{"at": time.time() - 600, "seven_day": [40, week], "helpers": 1},
                     {"at": time.time(), "seven_day": [41, week], "helpers": 1}]}
    assert forecast.burn(held["main"], "seven_day") is None
    reading(host.parent / "main", five=0, week=10)
    path = host.parent / "main" / ".claude.json"
    state = json.loads(path.read_text())
    state["cachedUsageUtilization"]["utilization"]["five_hour"]["resets_at"] = None  # no window running yet
    path.write_text(json.dumps(state))
    history(config, "main", [(40, 0, 3), (0, 0, 3)])
    here = [running(f"builder-{n}", host.parent / "main") for n in (1, 2, 3)]
    monkeypatch.setattr(cli, "running_sessions", lambda config: here)
    monkeypatch.setattr(cli, "refresh_usage", lambda folders: None)
    found = forecast.outlook(config, "main", "five_hour", 3, running=0)
    assert found is not None and not found.known_reset
    looks = {"at": time.time() - forecast.OBSERVE_EVERY}
    assert forecast.lead_part(config, looks) == []
    assert forecast.risk_lines(config) == []


def test_with_one_account_its_helpers_share_it_under_a_cap_one_lower(host):
    """Most people have one AI account: its lead shares it with up to max_busy minus one helpers."""
    config = load("[pool]\nmax_busy = 3\n")
    config["people"]["ana"]["accounts"] = ["main"]  # main is the only account of ana's
    leads = {"main": ["ana-main-lead"]}
    name, _, why = capacity.place(config, ana(), {"main": {"builder-1"}}, leads)[0]
    assert name == "main" and why.startswith(capacity.SHARED) and "helpers 1 of 2" in why
    found, why = capacity.place(config, ana(), {"main": {"builder-1", "builder-2"}}, leads)
    assert found is None and why.startswith("main is ana-main-lead's own and runs 2 helpers")
    shared = load('[pool]\nshare_lead_accounts = true\n')
    shared["people"]["ana"]["accounts"] = ["main"]
    assert capacity.place(shared, ana(), {"main": {"builder-1", "builder-2"}}, leads)[0][0] == "main"  # the full cap


def test_a_shared_lead_account_takes_a_helper_only_while_the_lead_keeps_room(host):
    config = load()
    config["people"]["ana"]["accounts"] = ["main"]
    leads = {"main": ["ana-main-lead"]}
    reading(host.parent / "main", five=75, week=10, five_resets_in=timedelta(hours=1))
    # one helper and the lead at the 10% guess each: 20% an hour, from 75% to the lead's 85% in half an hour
    found, why = capacity.place(config, ana(), {}, leads)
    assert found is None and why.startswith(capacity.NO_FIT)
    assert "would leave the lead less than 10% of its 5-hour window before it resets" in why
    reading(host.parent / "main", five=40, week=10, five_resets_in=timedelta(hours=1))
    assert capacity.place(config, ana(), {}, leads)[0][0] == "main"


def test_the_pools_reserve_stays_strict_even_for_the_only_account(host):
    config = load('[pool]\nreserve = ["main"]\n')
    config["people"]["ana"]["accounts"] = ["main"]
    found, why = capacity.place(config, ana(), {}, {"main": ["ana-main-lead"]})
    assert found is None and why == capacity.AT_CAP


def test_a_leads_own_account_out_of_room_takes_no_helper(host):
    config = load()
    config["people"]["ana"]["accounts"] = ["main"]
    reading(host.parent / "main", five=97, week=10)
    found, why = capacity.place(config, ana(), {}, {"main": ["ana-main-lead"]})
    assert found is None and why.startswith("main is ana-main-lead's own account and out of room: wait for its reset")
