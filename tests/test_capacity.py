"""Tests for capacity: the account pool's policy, helpers in waves under each account's cap, waking a session when
its usage limit resets, service checks, the account a session really runs on, this computer's limits, named locks,
and starting again what stopped while the computer slept."""
import argparse
import io
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import stub_path
from colony import capacity, cli, guards, presence, wait

CONFIG = """
[project]
name = "demo"
repo = "acme/demo"
base = "main"
worktrees = "~/trees"
checks = "make check"
[accounts.main]
config_dir = "~/main"
person = "ana"
[accounts.team]
config_dir = "~/team"
person = "ana"
[accounts.spare]
config_dir = "~/spare"
person = "ana"
[people.ana]
accounts = ["main", "team", "spare"]
[roles]
lead = { model = "m", effort = "high" }
builder = { model = "m", effort = "medium" }
reviewer = { model = "m", effort = "high" }
walker = { model = "m", effort = "medium" }
fixer = { model = "m", effort = "medium" }
[gate]
rubric = ["bugs"]
max_rounds = 3
walk = false
[budget]
provider_dollars = 0
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A temporary HOME with the three account folders, a PATH with a stub folder and no real claude or gh."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", stub_path(tmp_path / "bin"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    for name in ("main", "team", "spare"):
        (tmp_path / name).mkdir()
    return tmp_path


@pytest.fixture
def host(home, monkeypatch):
    """A git repo with this file's config, run from inside it."""
    repo = home / "host"
    (repo / ".colony").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".colony" / "colony.toml").write_text(CONFIG)
    monkeypatch.chdir(repo)
    return repo


def load(extra: str = "") -> dict:
    """The config, with `extra` TOML added at its end."""
    path = Path.cwd() / ".colony" / "colony.toml"
    path.write_text(CONFIG + extra)
    return cli.load_config(path)


def usage(folder: Path, five=None, week=None, five_resets_in=timedelta(hours=2), week_resets_in=timedelta(days=3)):
    """Save a usage reading in an account folder, as Claude Code does."""
    now = datetime.now(timezone.utc)
    windows = {}
    if five is not None:
        windows["five_hour"] = {"utilization": five, "resets_at": (now + five_resets_in).isoformat()}
    if week is not None:
        windows["seven_day"] = {"utilization": week, "resets_at": (now + week_resets_in).isoformat()}
    (folder / ".claude.json").write_text(json.dumps({"cachedUsageUtilization": {"utilization": windows}}))


def stub(home: Path, name: str, body: str) -> Path:
    """A fake command on PATH, a shell script; returns its log file, which `$LOG` names."""
    folder = home / "bin"
    folder.mkdir(exist_ok=True)
    log = folder / f"{name}.log"
    (folder / name).write_text(f'#!/bin/sh\nLOG="{log}"\n{body}\n')
    (folder / name).chmod(0o755)
    return log


# 5. The account pool's policy


def test_the_pool_takes_the_soonest_weekly_reset_by_default_and_the_listed_order_when_asked(host):
    usage(host.parent / "main", five=10, week=10, week_resets_in=timedelta(days=6))
    usage(host.parent / "team", five=10, week=10, week_resets_in=timedelta(hours=5))
    assert cli.pick(load(), "ana")[0] == "team"
    assert cli.pick(load('[pool]\norder = "listed"\n'), "ana")[0] == "main"


def test_the_pools_thresholds_decide_when_a_session_switches_account(host):
    usage(host.parent / "main", five=75, week=10, five_resets_in=timedelta(minutes=30))
    usage(host.parent / "team", five=10, week=10)
    assert cli.pick(load('[pool]\norder = "listed"\n'), "ana")[0] == "main"
    assert cli.pick(load('[pool]\norder = "listed"\nout_at = 70\n'), "ana")[0] == "team"


def test_a_reserved_account_is_never_picked_but_still_opens_when_named(host):
    for name in ("main", "team", "spare"):
        usage(host.parent / name, five=0, week=0)
    usage(host.parent / "spare", five=0, week=0, week_resets_in=timedelta(hours=1))  # the soonest reset
    config = load('[pool]\nreserve = ["spare"]\n')
    assert cli.pick(config, "ana")[0] != "spare"
    assert cli.pick_with_room(config, "ana", skip={"main", "team"}) is None
    named = argparse.Namespace(account="spare", person="ana")
    assert cli.choose_account_why(config, named)[:2] == ("spare", str(host.parent / "spare"))
    with pytest.raises(cli.ColonyError, match="reserve"):
        cli.pick(load('[pool]\nreserve = ["main", "team", "spare"]\n'), "ana")


@pytest.mark.parametrize("table, message", [
    ('order = "random"', 'order is "reset" or "listed"'),
    ('reserve = ["nobody"]', "reserve names 'nobody'"),
    ("max_busy = 0", "max_busy is a whole number"),
    ("out_at = 120", "out_at is a number from 1 to 100"),
    ("drain = true", "no key 'drain'"),
])
def test_a_wrong_pool_setting_is_named_in_one_line(host, table, message):
    with pytest.raises(cli.ColonyError, match=message):
        capacity.policy(load(f"[pool]\n{table}\n"))


def test_an_account_whose_usage_command_prints_its_windows_is_judged_like_any_other(home):
    reading = {"five_hour": {"utilization": 99, "resets_at": (datetime.now(timezone.utc) + timedelta(hours=1))
                             .isoformat()}}
    script = home / "usage.py"
    script.write_text(f"import json\nprint(json.dumps({reading!r}))\n")
    config = {"accounts": {"other": {"config_dir": str(home / "team"), "person": "ana", "provider": "other",
                                     "usage_command": f"{sys.executable} {script}"},
                           "main": {"config_dir": str(home / "main"), "person": "ana"}},
              "people": {"ana": {"accounts": ["other", "main"]}}}
    capacity._readings.clear()
    tier, _, why = capacity.judge(config, "other", datetime.now(timezone.utc))
    assert tier == 2 and "out of 5-hour room" in why
    assert cli.pick(config, "ana")[0] == "main"


# 6. Helpers in waves, each account under its cap


def running(name: str, folder: Path, kind="background", state="idle", session="s-1", **more) -> dict:
    """One session as `claude agents --json` lists it, with the folder cli.running_sessions adds."""
    return {"id": name[-1], "name": f"demo-{name}", "kind": kind, "state": state, "sessionId": session,
            "config_dir": str(folder), "cwd": str(folder), **more}


def test_busy_counts_each_accounts_helpers_here_and_on_other_computers_once(home):
    config = {"project": {"name": "demo"}, "accounts": {"main": {"config_dir": str(home / "main"), "person": "ana"},
                                                        "team": {"config_dir": str(home / "team"), "person": "ana"}}}
    alive = [presence.Status("builder-1", "helper", account="main"), presence.Status("ana-main-lead", "lead",
                                                                                    account="main")]
    here = [running("builder-1", home / "team"), running("builder-2", home / "team"), running("lead", home / "main")]
    counts = capacity.busy(config, alive, here)
    assert counts == {"main": {"builder-1"}, "team": {"builder-2"}}  # builder-1's status names its account


def test_a_helper_opens_on_an_account_under_its_cap(host, monkeypatch):
    config = load('[pool]\nmax_busy = 2\norder = "listed"\n[accounts.main.x]\n'.replace("[accounts.main.x]\n", ""))
    config["accounts"]["team"]["max_busy"] = 1
    args = argparse.Namespace(person="ana", account=None)
    counts = {"main": {"builder-1", "builder-2"}, "team": set(), "spare": set()}
    assert capacity.helper_account(config, args, counts)[0] == "team"
    counts["team"].add("builder-3")
    name, _, why = capacity.helper_account(config, args, counts)
    assert name == "spare" and why.endswith("helpers 0 of 2")
    counts["spare"] |= {"builder-4", "builder-5"}
    assert capacity.helper_account(config, args, counts) is None


def wave_world(monkeypatch, room=10, here=()):
    """Stand-ins for what a wave reads and does: no live statuses, the running sessions `here`, a computer with
    `room` helpers to open, and the launches it makes."""
    opened = []
    monkeypatch.setattr(presence, "everyone", lambda config: ([], [], ""))
    monkeypatch.setattr(cli, "running_sessions", lambda config: list(here))
    monkeypatch.setattr(capacity, "limits", lambda config, running=0: {"open_now": room, "why": [], "helpers": 4})
    monkeypatch.setattr(cli, "launch", lambda config, args, name, role, prompt: opened.append((name, args.account))
                        or 0)
    monkeypatch.setattr(cli, "cmux_usable", lambda: True)
    return opened


def test_helpers_open_the_first_wave_now_and_leave_the_rest_to_a_background_run(host, monkeypatch, capsys):
    config = load("[pool]\nwave = 2\nwave_seconds = 90\n")
    opened, spawned = wave_world(monkeypatch), []
    monkeypatch.setattr(capacity, "spawn", lambda argv, log: spawned.append(argv))
    args = argparse.Namespace(count=5, open=True, paste=False, person="ana", account=None, dry_run=False)
    assert cli.helpers(config, args) == 0
    assert [name for name, _ in opened] == ["builder-1", "builder-2"]
    assert spawned[0][2:] == [cli.NAME, "open-later", "3", "--taken", "builder-1,builder-2", "--person", "ana"]
    assert "3 more helpers open in 2 later waves, 2 every 90 s" in capsys.readouterr().out


def test_a_dry_run_of_helpers_prints_the_wave_plan_and_starts_nothing(host, monkeypatch, capsys):
    config = load("[pool]\nwave = 2\n")
    wave_world(monkeypatch)
    monkeypatch.setattr(capacity, "spawn", lambda argv, log: pytest.fail("a dry run starts nothing"))
    args = argparse.Namespace(count=3, open=True, paste=False, person="ana", account=None, dry_run=True)
    assert cli.helpers(config, args) == 0
    assert "dry run: 1 more helper open in 1 later wave" in capsys.readouterr().out


def test_a_wave_opens_no_helper_while_the_computer_is_busy(host, monkeypatch):
    config = load()
    opened = wave_world(monkeypatch)
    monkeypatch.setattr(capacity, "limits", lambda config, running=0: {"open_now": 0, "why": ["load 9.0 on 8 cores"],
                                                                       "helpers": 4})
    args = argparse.Namespace(person="ana", account=None, dry_run=False)
    assert capacity.open_wave(config, args, 3, set()) == (0, "this computer is busy (load 9.0 on 8 cores)")
    assert opened == []


def test_the_later_waves_open_the_rest_and_give_up_with_a_line_when_no_room_comes(host, monkeypatch):
    config = load("[pool]\nwave = 2\n")
    waves, posted, clock = [2, 1], [], [1000.0]
    monkeypatch.setattr(capacity, "SLEEP", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(capacity.time, "time", lambda: clock[0])
    monkeypatch.setattr(capacity, "open_wave", lambda config, args, count, taken: (min(count, waves.pop(0)), "")
                        if waves else (0, "every account is at its cap of busy helpers"))
    monkeypatch.setattr(guards, "post", lambda config, to, sentence, sender: posted.append(sentence) or 0)
    args = argparse.Namespace(count=3, taken="builder-1", person="ana", account=None)
    assert capacity.open_later(config, args) == 0 and posted == []
    waves.clear()
    assert capacity.open_later(config, argparse.Namespace(count=2, taken="", person="ana", account=None)) == 1
    assert posted == ["urgent: 2 helpers did not open in 60 minutes: every account is at its cap of busy helpers"]


# 7. A usage limit that resets wakes the session


def test_a_limit_is_noted_with_its_accounts_reset_and_other_errors_are_not(host, monkeypatch):
    config = load()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(host.parent / "team"))
    usage(host.parent / "team", five=100, week=40, five_resets_in=timedelta(hours=2))
    assert not capacity.note_limited(config, "builder-2", "server_error")
    assert capacity.note_limited(config, "builder-2", "rate_limit")
    record = capacity.limited(config)["builder-2"]
    assert record["account"] == "team"
    assert abs(record["resets_at"] - (time.time() + 7200)) < 60


def test_the_stop_failure_hook_notes_a_limit(host, monkeypatch):
    config = load()
    monkeypatch.setenv(cli.SESSION_ENV, "builder-2")
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    monkeypatch.setattr(wait, "coordination_issue", lambda repo, project: 7)
    monkeypatch.setattr(wait, "gh", lambda *args: "")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"error": "rate_limit"})))
    assert guards.stopped(config, argparse.Namespace()) == 0
    assert "builder-2" in capacity.limited(config)


def test_a_limited_session_is_due_only_once_its_account_reset(home):
    config = {"project": {"name": "demo"}, "accounts": {"main": {"config_dir": str(home / "main"), "person": "ana"}}}
    usage(home / "main", five=100, five_resets_in=timedelta(hours=1))
    now = time.time()
    record = {"account": "main", "at": now, "resets_at": now + 3600}
    assert not capacity.is_due(config, record, now)
    assert capacity.is_due(config, record, now + 3600 + capacity.LIMIT_GRACE)
    unknown = {"account": "main", "at": now, "resets_at": None}
    assert not capacity.is_due(config, unknown, now + 60)  # with no known reset, wait before trying again


def test_a_helpers_own_wait_wakes_it_once_its_limit_reset(home, monkeypatch):
    config = {"project": {"name": "demo"}, "accounts": {"main": {"config_dir": str(home / "main"), "person": "ana"}}}
    monkeypatch.setattr(capacity, "start_follower", lambda config: False)
    past = time.time() - 600
    capacity.write_limited(config, {"builder-2": {"account": "main", "at": past - 3600, "resets_at": past}})
    check = capacity.helper_check(config, "builder-2", "ana-main-lead")
    lines = check({})
    assert lines == ["Your account main's usage limit has reset. Start `colony wait` in the background again, and "
                     "carry on from where you stopped."]
    assert capacity.limited(config) == {}


def test_a_session_whose_wait_runs_is_woken_with_a_line_from_its_lead(home, monkeypatch):
    config = {"project": {"name": "demo"}, "accounts": {"main": {"config_dir": str(home / "main"), "person": "ana"}}}
    capacity.remember_opened(config, "builder-2", "builder", "main", "ana", "ana-main-lead")
    wait.write_json(wait.state_path("demo", "builder-2"), {"polled_at": time.time()})
    posted = []
    monkeypatch.setattr(guards, "post", lambda config, to, sentence, sender: posted.append((to, sentence, sender)))
    how = capacity.wake(config, "builder-2", None, "carry on")
    assert how == "sent it a line, which its wait delivers"
    assert posted == [("builder-2", "urgent: carry on", "ana-main-lead")]


def test_an_idle_background_session_is_stopped_and_continued_under_its_own_id(host, monkeypatch):
    config = load()
    log = stub(host.parent, "claude", 'echo "${CLAUDE_CONFIG_DIR:-default}|$*" >> "$LOG"')
    capacity.remember_opened(config, "builder-2", "builder", "team", "ana", "ana-main-lead")
    agent = running("builder-2", host.parent / "team", session="abc-123")
    how = capacity.wake(config, "builder-2", agent, "carry on")
    assert how == "started again in the background, under its own id"
    stop, resume = log.read_text().splitlines()
    assert stop == f"{host.parent / 'team'}|stop 2"
    assert resume.startswith(f"{host.parent / 'team'}|--bg --resume abc-123 --model m --effort medium --settings ")
    assert '"COLONY_ACCOUNT": "team"' in resume and '"COLONY_LEAD": "ana-main-lead"' in resume
    assert resume.endswith("--permission-mode auto carry on")


def test_a_busy_session_and_one_at_a_prompt_are_left_alone(home):
    config = {"project": {"name": "demo"}, "accounts": {}}
    assert capacity.wake(config, "builder-2", running("builder-2", home, state="working"), "x").endswith("left alone")
    assert capacity.wake(config, "builder-2", running("builder-2", home, state="blocked"), "x").endswith("left alone")


# 9. Service checks


def test_services_hold_the_built_in_checks_and_the_teams_own(home):
    config = {"accounts": {"main": {"config_dir": str(home / "main"), "person": "ana"},
                           "gone": {"config_dir": str(home / "gone"), "person": "ana"}},
              "services": {"aws": {"command": "aws sts get-caller-identity", "fix": "aws sso login"}}}
    names = [s.name for s in capacity.services(config)]
    assert names == ["account main sign-in", "account main room", "github", "aws"]  # gone's folder isn't here
    config["services"]["builtin"] = False
    assert [s.name for s in capacity.services(config)] == ["aws"]


@pytest.mark.parametrize("table, message", [
    ({"fix": "x"}, "needs 'command'"),
    ({"command": "x", "expect": "("}, "expect is a regular expression"),
    ({"command": "x", "every": 5}, "no key 'every'"),
    ({"command": "x", "timeout": 0}, "timeout is a number"),
])
def test_a_wrong_service_table_is_named_in_one_line(table, message):
    with pytest.raises(cli.ColonyError, match=message):
        capacity.services({"accounts": {}, "services": {"builtin": False, "npm": table}})


def test_a_service_passes_by_its_exit_code_its_output_and_its_number_and_never_shows_the_output(home):
    py = sys.executable
    check = capacity.run_command
    assert check(capacity.Service("a", f"{py} -c 'print(\"Logged in\")'", expect="Logged in")) == (True, "")
    assert check(capacity.Service("a", f"{py} -c 'print(\"token sk-secret\")'", expect="Logged in")) == \
        (False, "its output lacks what `expect` names")
    assert check(capacity.Service("a", f"{py} -c 'import sys; sys.exit(3)'")) == (False, "it ended with 3")
    assert check(capacity.Service("a", f"{py} -c 'print(120)'", at_least=500)) == (False, "120 is under 500")
    assert check(capacity.Service("a", f"{py} -c 'print(4999)'", at_least=500)) == (True, "")
    assert check(capacity.Service("a", "no-such-command-here")) == (False, "its command was not found")
    assert check(capacity.Service("a", f"{py} -c 'import time; time.sleep(5)'", timeout=0.5)) == \
        (False, "it ran past 0.5 s")


def test_the_lead_hears_once_when_a_service_fails_and_once_when_it_passes_again(home, monkeypatch):
    config = {"accounts": {}, "services": {"builtin": False, "npm": {"command": "npm whoami", "fix": "npm login",
                                                                     "every_minutes": 1}}}
    results = iter([(False, "it ended with 1"), (False, "it ended with 1"), (True, "")])
    monkeypatch.setattr(capacity, "run_service", lambda config, service: next(results))
    held, now = {}, time.time()
    assert capacity.service_lines(config, held, now) == ["urgent: the check of npm failed: it ended with 1. To fix "
                                                         "it: npm login."]
    assert capacity.service_lines(config, held, now + 30) == []  # not due yet
    assert capacity.service_lines(config, held, now + 61) == []  # failing still: said once
    assert capacity.service_lines(config, held, now + 122) == ["the check of npm passes again"]


def test_an_account_signed_out_or_out_of_room_fails_its_own_check(home):
    stub(home, "claude", 'echo \'{"loggedIn": false}\'')
    config = {"accounts": {"main": {"config_dir": str(home / "main"), "person": "ana"}}}
    sign_in, room = capacity.services(config)[:2]
    assert capacity.run_service(config, sign_in) == (False, "not signed in")
    assert "/login" in sign_in.fix
    stub(home, "claude", 'echo \'{"loggedIn": true}\'')
    usage(home / "main", five=99)
    assert capacity.run_service(config, sign_in) == (True, "")
    ok, why = capacity.run_service(config, room)
    assert not ok and why.startswith("out of 5-hour room") and room.fix.startswith("nothing: it resets by itself")


def test_colony_services_prints_each_result_and_fails_when_one_fails(host, monkeypatch, capsys):
    load('[services]\nbuiltin = false\n[services.ok]\ncommand = "true"\n[services.bad]\ncommand = "false"\n'
         'fix = "sign in again"\n')
    assert cli.main(["services"]) == 1
    assert capsys.readouterr().out.splitlines() == ["pass: ok", "fail: bad: it ended with 1. To fix it: sign in again."]


# 10. The account a session really runs on


def test_the_account_is_the_folder_that_holds_the_sessions_transcript_whatever_the_env_says(home, monkeypatch):
    """Regression: a session's account label followed $CLAUDE_CONFIG_DIR, which a background session can carry from
    another session, so `colony who` named the wrong account."""
    config = {"accounts": {"main": {"config_dir": str(home / "main"), "person": "ana"},
                           "team": {"config_dir": str(home / "team"), "person": "ana"}}}
    (home / "team" / "projects" / "-repo").mkdir(parents=True)
    (home / "team" / "projects" / "-repo" / "0f1e2d3c.jsonl").write_text("{}\n")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / "main"))
    assert cli.current_account(config) == "main"
    monkeypatch.setenv(cli.CLAUDE_SESSION_ENV, "0f1e2d3c")
    assert cli.current_account(config) == "team"


def test_a_folder_written_with_a_trailing_slash_or_through_a_link_is_the_same_account(home, monkeypatch):
    config = {"accounts": {"main": {"config_dir": str(home / "main"), "person": "ana"}}}
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / "main") + "/")
    assert cli.current_account(config) == "main"
    (home / "link").symlink_to(home / "main")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / "link"))
    assert cli.current_account(config) == "main"


def test_a_session_on_another_account_than_it_was_opened_on_or_on_a_reserved_one_is_named(home, monkeypatch):
    config = {"accounts": {"main": {"config_dir": str(home / "main"), "person": "ana"},
                           "spare": {"config_dir": str(home / "spare"), "person": "ana"}},
              "pool": {"reserve": ["spare"]}}
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / "main"))
    assert capacity.account_line(config, "builder-2") == ""
    monkeypatch.setenv(capacity.ACCOUNT_ENV, "spare")
    assert capacity.account_line(config, "builder-2") == ("urgent: builder-2 runs on account main, but was opened on "
                                                          "spare: stop it and open it again on spare")
    monkeypatch.delenv(capacity.ACCOUNT_ENV)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / "spare"))
    assert "which [pool] reserve keeps free" in capacity.account_line(config, "builder-2")


def test_a_session_opens_with_the_account_it_was_opened_on_and_colony_notes_it(host, monkeypatch, capsys):
    config = load()
    stub(host.parent, "claude", "exit 0")
    args = argparse.Namespace(person="ana", account="team", here=False, dry_run=False, name="builder-2")
    monkeypatch.setattr(cli, "where_to_open", lambda args: "background")
    assert cli.launch(config, args, "builder-2", "builder", "go") == 0
    assert capacity.read("demo", "opened")["builder-2"]["account"] == "team"
    assert cli.session_env("ana", "builder-2", str(host.parent / "team"), account="team")[capacity.ACCOUNT_ENV] == "team"


# 11. This computer


MEMINFO = "MemTotal:       16384000 kB\nMemFree:          512000 kB\nMemAvailable:    8192000 kB\n"
VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               65536.
Pages active:                            500000.
Pages inactive:                          131072.
Pages speculative:                         65536.
Pages wired down:                        200000.
"""


def test_memory_is_read_from_linux_meminfo_and_macos_vm_stat():
    total, available = capacity.parse_meminfo(MEMINFO)
    assert round(total, 1) == 15.6 and round(available, 1) == 7.8
    assert capacity.parse_vm_stat(VM_STAT) == 4.0
    assert capacity.parse_vm_stat("nothing") is None


def test_the_machine_is_read_with_the_standard_library_on_this_computer(home):
    found = capacity.machine({"project": {"worktrees": str(home / "trees")}})
    assert found.cores >= 1 and found.free_disk_gb is not None and found.free_disk_gb > 0
    if sys.platform in ("darwin", "linux"):
        assert found.memory_gb and found.free_memory_gb is not None and found.load is not None


def test_an_idle_computer_runs_up_to_its_caps_and_a_busy_one_scales_down():
    config = {"project": {"max_builders": 4}}
    idle = capacity.Machine(cores=8, memory_gb=16, free_memory_gb=12, free_disk_gb=100, load=1.0)
    room = capacity.limits(config, idle, running=1)
    assert (room["helpers"], room["open_now"], room["tests"], room["builds"], room["busy"]) == (4, 3, 3, 3, False)
    busy = capacity.Machine(cores=8, memory_gb=16, free_memory_gb=2.5, free_disk_gb=5, load=11.0)
    room = capacity.limits(config, busy, running=1)
    assert (room["open_now"], room["tests"], room["builds"], room["busy"]) == (0, 1, 1, True)
    assert room["why"] == ["load 11.0 on 8 cores", "2.5 GB memory free", "5.0 GB disk free"]
    small = capacity.limits({"project": {}, "machine": {"helper_gb": 3}}, capacity.Machine(4, 8, 7, 50, 0.0))
    assert small["helpers"] == 2  # (8 GB - 2 kept free) / 3 GB a helper


def test_a_wrong_machine_setting_is_named_in_one_line():
    with pytest.raises(cli.ColonyError, match="no key 'cpus'"):
        capacity.machine_policy({"machine": {"cpus": 4}})
    with pytest.raises(cli.ColonyError, match="max_tests is a whole number"):
        capacity.machine_policy({"machine": {"max_tests": 1.5}})


def test_the_lead_hears_when_the_computer_turns_busy_and_when_it_calms(monkeypatch):
    rooms = iter([{"busy": True, "why": ["load 9.0 on 8 cores"]}, {"busy": True, "why": []},
                  {"busy": False, "why": [], "open_now": 2, "tests": 3}])
    monkeypatch.setattr(capacity, "limits", lambda config: next(rooms))
    held = {}
    assert capacity.machine_line({}, held)[0].startswith("urgent: this computer is busy (load 9.0 on 8 cores)")
    assert capacity.machine_line({}, held) == []
    assert capacity.machine_line({}, held) == ["this computer has room again: 2 more helpers, 3 test runs at once"]


def test_colony_capacity_shows_the_computer_the_accounts_and_their_helpers(host, monkeypatch, capsys):
    load('[pool]\nreserve = ["spare"]\n')
    usage(host.parent / "main", five=40, week=63)
    monkeypatch.setattr(presence, "everyone", lambda config: ([presence.Status("builder-1", "helper",
                                                                                account="main")], [], ""))
    monkeypatch.setattr(cli, "running_sessions", lambda config: [])
    monkeypatch.setattr(capacity, "machine", lambda config: capacity.Machine(8, 16, 12, 100, 1.0))
    assert cli.main(["capacity", "--person", "ana"]) == 0
    out = capsys.readouterr().out
    assert "This computer: 8 cores, load 1.0; memory 16.0 GB, 12.0 GB free; disk 100.0 GB free." in out
    assert "At once: 4 helpers (0 running, 4 more now), 3 test runs, 3 builds." in out
    assert "- main: 5h 40% (resets " in out and "helpers 1 of 3 (builder-1)" in out
    assert "- spare: reserved, used only with --account." in out
    assert cli.main(["capacity", "--json", "--person", "ana"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["machine"]["tests"] == 3 and data["policy"]["reserve"] == ["spare"]


# 12. Locks


def test_a_lock_runs_its_command_with_its_slot_and_returns_its_exit_code(host, capfd):
    load()
    code = cli.main(["lock", "test-db", "--", sys.executable, "-c",
                     "import os, sys; print('slot', os.environ['COLONY_LOCK_SLOT']); sys.exit(3)"])
    assert code == 3 and capfd.readouterr().out == "slot 0\n"


def test_a_held_lock_makes_the_next_run_wait_then_names_its_holder(host, monkeypatch):
    config = load()
    monkeypatch.setattr(capacity, "SLEEP", lambda seconds: None)
    with capacity.hold("test-db", 1, 1, {"pid": 1, "session": "builder-1", "command": "pytest"}):
        args = argparse.Namespace(name="test-db", slots=None, wait=0, list=False, argv=["--", "true"])
        with pytest.raises(cli.ColonyError, match=r"stayed held for 0 minutes, by builder-1 \(pytest\)"):
            capacity.lock_command(config, args)
        assert [h["session"] for h in capacity.holders("test-db")] == ["builder-1"]
    assert capacity.holders("test-db") == []
    assert capacity.lock_command(config, argparse.Namespace(name="test-db", slots=None, wait=0, list=False,
                                                            argv=["--", "true"])) == 0


def test_a_lock_with_two_slots_lets_two_runs_hold_it_at_once(host, monkeypatch):
    config = load("[locks.port]\nslots = 2\n")
    monkeypatch.setattr(capacity, "SLEEP", lambda seconds: None)
    assert capacity.slots(config, "port") == 2 and capacity.slots(config, "other") == 1
    with capacity.hold("port", 2, 0, {"session": "builder-1"}) as first, \
            capacity.hold("port", 2, 0, {"session": "builder-2"}) as second:
        assert (first, second) == (0, 1)
        with pytest.raises(cli.ColonyError, match="stayed held"):
            with capacity.hold("port", 2, 0, {"session": "builder-3"}):
                pass


def test_the_tests_and_builds_locks_take_this_computers_runs_at_once(host, monkeypatch):
    config = load()
    monkeypatch.setattr(capacity, "machine", lambda config: capacity.Machine(8, 16, 12, 100, 1.0))
    assert capacity.slots(config, "tests") == 3 and capacity.slots(config, "builds") == 3


def test_lock_list_names_each_held_lock_and_drops_a_dead_holders_note(host, capsys):
    load()
    folder = capacity.locks_dir()
    folder.mkdir(parents=True)
    wait.write_json(folder / "old.0.json", {"session": "gone", "command": "x", "since": time.time()})
    (folder / "old.0.lock").write_text("")
    with capacity.hold("test-db", 1, 0, {"session": "builder-1", "command": "pytest"}):
        assert cli.main(["lock", "--list"]) == 0
    assert capsys.readouterr().out.startswith("test-db: builder-1 (pytest) for ")
    assert not (folder / "old.0.json").exists()


# 13. Sleep and wake


def test_a_sleep_is_the_wall_clock_running_ahead_of_the_awake_clock_and_a_restart_is_the_awake_clock_going_back():
    clock = {}
    assert capacity.slept(clock, wall=1000, awake=50) == 0
    assert capacity.slept(clock, wall=1060, awake=110) == 0
    assert capacity.slept(clock, wall=4660, awake=120) == 3590  # an hour asleep
    assert capacity.slept(clock, wall=4700, awake=5) == -1


def test_after_a_sleep_the_helpers_that_stopped_start_again(host, monkeypatch):
    config = load()
    log = stub(host.parent, "claude", 'echo "$*" >> "$LOG"')
    team = host.parent / "team"
    capacity.remember_seen(config, [running("builder-1", team, session="sid-1"),
                                    running("builder-2", team, kind="interactive", session="sid-2"),
                                    running("builder-3", team, session="sid-3"), running("lead", team)])
    wait.write_json(wait.state_path("demo", "builder-3"), {"polled_at": time.time() - 3600})
    monkeypatch.setattr(cli, "running_sessions", lambda config: [running("builder-3", team, session="sid-3")])
    lines = capacity.restart(config, capacity.SLEPT_PROMPT, reopen=True)
    assert lines[0] == "builder-1: no longer ran; started again in the background, under its own id"
    assert lines[1] == "builder-2: its window closed; open it again with `colony open builder-2`"
    assert lines[2] == "builder-3: its wait had stopped; started again in the background, under its own id"
    calls = log.read_text().splitlines()
    assert calls[0].startswith("--bg --resume sid-1 ") and calls[1] == "stop 3" and "--resume sid-3" in calls[2]
    assert set(capacity.read("demo", "seen")) == {"builder-3"}


def test_a_plain_wake_never_reopens_a_helper_that_was_stopped_on_purpose(host, monkeypatch):
    config = load()
    capacity.remember_seen(config, [running("builder-1", host.parent / "team", session="sid-1")])
    monkeypatch.setattr(cli, "running_sessions", lambda config: [])
    assert capacity.restart(config) == []
    capacity.remember_seen(config, [running("builder-1", host.parent / "team", session="sid-1")])
    capacity.forget_seen(config, ["builder-1"])
    assert capacity.restart(config, reopen=True) == []


def test_the_leads_wait_names_a_sleep_and_what_it_started_again(home, monkeypatch):
    config = {"project": {"name": "demo"}, "accounts": {}}
    monkeypatch.setattr(capacity, "restart", lambda config, prompt, reopen=False: ["builder-1: no longer ran; x"])
    check, waited = capacity.lead_check(config, "ana-main-lead"), {}
    assert check(waited) == []
    waited["capacity"]["clock"]["wall"] -= 3600  # the wall clock ran an hour ahead of the awake clock
    assert check(waited) == ["urgent: this computer slept for 60 minutes; builder-1: no longer ran; x"]


def test_wake_follow_runs_one_at_a_time_and_ends_when_no_limit_waits(host, monkeypatch, capsys):
    config = load()
    capacity.write_limited(config, {"builder-2": {"account": "main", "at": time.time() - 7200,
                                                  "resets_at": time.time() - 600}})
    monkeypatch.setattr(cli, "running_sessions", lambda config: [])
    monkeypatch.setattr(capacity, "SLEEP", lambda seconds: pytest.fail("nothing is left to wait for"))
    assert cli.main(["wake", "--follow"]) == 0
    assert "builder-2: account main's usage limit reset" in capsys.readouterr().out
    assert capacity.limited(config) == {}


def test_open_refuses_a_helper_when_every_account_is_at_its_cap(host, monkeypatch):
    config = load("[pool]\nmax_busy = 1\n")
    team = host.parent / "team"
    here = [running("builder-1", host.parent / "main"), running("builder-2", team), running("builder-3",
                                                                                            host.parent / "spare")]
    monkeypatch.setattr(presence, "everyone", lambda config: ([], [], ""))
    monkeypatch.setattr(cli, "running_sessions", lambda config: here)
    args = argparse.Namespace(name="builder-4", person="ana", account=None, dry_run=True, here=False)
    with pytest.raises(cli.ColonyError, match="every account is at its cap of busy helpers"):
        cli.open_builder(config, args)
    here.pop()  # builder-3 finished: spare has room under its cap
    assert cli.open_builder(config, args) == 0
    assert args.account == "spare"


def test_a_limit_noted_before_its_reading_was_fresh_learns_its_reset_from_the_next_reading(home, monkeypatch):
    config = {"project": {"name": "demo"}, "accounts": {"main": {"config_dir": str(home / "main"), "person": "ana"}}}
    monkeypatch.setattr(cli, "running_sessions", lambda config: [])
    capacity.write_limited(config, {"builder-2": {"account": "main", "at": time.time() - 3600, "resets_at": None}})
    usage(home / "main", five=100, five_resets_in=timedelta(hours=2))
    assert capacity.wake_due(config) == []
    assert abs(capacity.limited(config)["builder-2"]["resets_at"] - (time.time() + 7200)) < 60


def test_a_helper_colony_stop_ended_is_never_opened_again_after_a_sleep(host, monkeypatch):
    from colony import stop, transport

    config = load()
    agent = running("builder-1", host.parent / "team", session="sid-1")
    capacity.remember_seen(config, [agent])
    monkeypatch.setattr(cli, "running_sessions", lambda config: [agent])
    monkeypatch.setattr(stop, "stop_background", lambda agent: None)
    monkeypatch.setattr(stop, "uncommitted", lambda agent: False)
    monkeypatch.setattr(transport, "send", lambda config, to, line, card=None: 7)
    assert stop.stop(config, argparse.Namespace(names=["builder-1"], force=False)) == 0
    assert capacity.read("demo", "seen") == {}


def test_a_named_leads_limit_wakes_it_with_a_line_it_takes_from_colony(home, monkeypatch):
    config = {"project": {"name": "demo"}, "accounts": {"main": {"config_dir": str(home / "main"), "person": "ana"}}}
    monkeypatch.setenv(wait.LEAD_ENV, "ana-main-lead")
    monkeypatch.setattr(cli, "running_sessions", lambda config: [])
    assert capacity.note_limited(config, cli.LEAD, "rate_limit")
    record = capacity.limited(config)["ana-main-lead"]
    record["at"], record["resets_at"] = time.time() - 7200, time.time() - 600
    capacity.write_limited(config, {"ana-main-lead": record})
    wait.write_json(wait.state_path("demo", "ana-main-lead"), {"polled_at": time.time()})
    posted = []
    monkeypatch.setattr(guards, "post", lambda config, to, sentence, sender: posted.append((to, sender)))
    assert capacity.wake_due(config)[0].endswith("sent it a line, which its wait delivers")
    assert posted == [("ana-main-lead", "colony")]  # a lead skips the lines it signed itself
    lead = wait.Session("lead", frozenset({"ana-main-lead"}))
    assert wait.taken("for ana-main-lead: urgent: carry on (from colony)", lead, "5") == \
        [("for ana-main-lead: urgent: carry on (from colony)", True)]
