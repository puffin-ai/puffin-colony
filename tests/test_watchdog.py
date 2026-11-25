"""Tests for the watchdog, which watches the team when every session has stopped, and for the status page it keeps."""
import os
import plistlib
import subprocess
import sys
import time
import types
from argparse import Namespace
from pathlib import Path

import pytest

from colony import capacity, cli, guards, portable, presence, progress, recover, statuspage, wait, watch, watchdog

CONFIG = {"project": {"name": "demo", "repo": "acme/demo"}, "accounts": {}, "people": {"logins": ["ana"]}}
S = watch.Settings(page=False)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def pulse(name, ago, kind="helper", lead="ana-main-lead", session="", active_ago=None, **intent):
    """A session's pulse on this computer, written `ago` seconds ago, and its intent."""
    now = time.time()
    wait.write_json(watch.pulse_path("demo", name), {"name": name, "kind": kind, "lead": lead, "at": now - ago,
                                                     "session": session or f"id-{name}", "started": now - 3600,
                                                     "active": now - (active_ago if active_ago is not None else ago)})
    if intent:
        watch.set_intent("demo", name, intent.pop("intent"), intent.pop("why", ""), now=now - ago)


@pytest.fixture
def woken(home, monkeypatch):
    """The sessions running here, idle, and each wake the watchdog sends, which reaches them."""
    calls = []
    agents = [{"name": f"demo-{name}", "sessionId": f"id-{name}", "state": "idle", "kind": "background",
               "config_dir": str(home)} for name in ("builder-2", "builder-3", "builder-4", "ana-main-lead")]
    monkeypatch.setattr(cli, "running_sessions", lambda config: agents)

    def wake(config, name, agent, prompt, dry_run=False):
        calls.append((name, prompt))
        return "started again in the background, under its own id"
    monkeypatch.setattr(capacity, "wake", wake)
    return calls


@pytest.fixture
def posted(monkeypatch):
    lines = []
    monkeypatch.setattr(guards, "post", lambda config, to, sentence, sender: lines.append((to, sentence, sender)) or 0)
    return lines


def test_a_stopped_wait_is_started_again_once_unless_its_session_said_it_is_done(woken, posted):
    pulse("builder-2", ago=10 * 60)
    pulse("builder-3", ago=10 * 60, intent="done")
    pulse("builder-4", ago=30)
    held: dict = {}
    lines = watchdog.tick(CONFIG, S, held)
    assert woken == [("builder-2", capacity.STOPPED_PROMPT)]
    assert lines == ["builder-2: its wait had stopped; started again in the background, under its own id"]
    assert watchdog.tick(CONFIG, S, held) == [] and len(woken) == 1  # once per stretch


def dead_pid() -> int:
    """The id of a process that has ended."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def task_file(pid: int, command: str, session: str, label: str) -> Path:
    """A background task's file as recover.tracked writes it while a colony command runs."""
    path = recover.folder("demo", recover.TASKS) / f"{pid}.json"
    wait.write_json(path, {"pid": pid, "command": command, "label": label, "session": session,
                           "claude": f"id-{session}", "started": time.time() - 600})
    return path


def test_a_background_task_stopped_from_outside_is_named_to_its_session(woken, posted):
    """The safety and watch join: the watchdog reads the task files recover keeps (recover.stopped_tasks), tells the
    idle session the line its own Stop hook would give it (recover.restart_line), and drops the file (recover.forget),
    so that hook doesn't tell it again."""
    batch = task_file(dead_pid(), "batch", "builder-3", "colony batch --name b1")
    stopped_wait = task_file(dead_pid(), "wait", "builder-4", "colony wait")
    running = task_file(os.getpid(), "fast-check", "builder-2", "colony fast-check")
    lines = watchdog.tick(CONFIG, S, {})
    [(name, prompt)] = woken  # a stopped wait is the pulse's to find, and a running task is no one's
    assert name == "builder-3" and prompt.startswith("Your background `colony batch --name b1`, started ")
    assert prompt.endswith("Run `colony status --name b1` to see where it stopped, then start it again.")
    assert lines[0].startswith("builder-3: its background colony batch --name b1 had stopped; started again")
    assert not batch.exists() and stopped_wait.exists() and running.exists()


def test_a_failure_reading_the_stopped_tasks_never_stops_the_watchdog(woken, posted, monkeypatch, capsys):
    def unreadable(config):
        raise OSError("the tasks folder can't be read")

    monkeypatch.setattr(recover, "stopped_tasks", unreadable)
    assert watchdog.stopped_tasks(CONFIG) == []
    assert watchdog.tick(CONFIG, S, {}) == [] and woken == []
    assert "watchdog: the stopped tasks were not read: the tasks folder can't be read" in capsys.readouterr().err


def test_a_lead_idle_too_long_has_its_person_mentioned_once(woken, posted):
    pulse("ana-main-lead", ago=30, kind="lead", lead="", active_ago=(20 + 60 + 5) * 60)
    held: dict = {}
    lines = watchdog.tick(CONFIG, S, held)
    assert posted == [("ana-main-lead", "urgent: ana-main-lead has done nothing for 1 h 25 min, with no helper busy and "
                                        "no reason given; @ana, please look at its window on its computer", "colony")]
    assert lines == ["ana-main-lead: has done nothing for 1 h 25 min, with no helper busy and no reason given; its "
                     "person was told on GitHub"]
    watchdog.tick(CONFIG, S, held)
    assert len(posted) == 1


def test_a_lead_whose_helper_works_is_not_idle(woken, posted):
    pulse("ana-main-lead", ago=30, kind="lead", lead="", active_ago=3 * 3600)
    pulse("builder-2", ago=30, active_ago=60, intent="working", why="#41")
    watchdog.tick(CONFIG, S, {})
    assert posted == []


def test_the_leads_wait_part_runs_only_while_no_leads_wait_runs_here(home, monkeypatch):
    monkeypatch.setattr(cli, "running_sessions", lambda config: [])
    monkeypatch.setattr(capacity, "limited", lambda config: {"builder-2": {"account": "main"}})
    monkeypatch.setattr(capacity, "wake_due", lambda config, now: ["builder-2: account main's usage limit reset"])
    assert watchdog.tick(CONFIG, S, {}) == ["builder-2: account main's usage limit reset"]
    monkeypatch.setattr(presence, "local", lambda config, now=None: [presence.Status("ana-main-lead", "lead")])
    assert watchdog.tick(CONFIG, S, {}) == []


def test_one_watchdog_runs_per_project_and_its_heartbeat_goes_with_it(home, monkeypatch, capsys):
    monkeypatch.setattr(watchdog, "tick", lambda config, s, held, now=None: ["did one pass"])
    args = Namespace(stay=False, once=True)
    assert watchdog.run(CONFIG, args) == 0
    assert "did one pass" in capsys.readouterr().out
    assert not watchdog.path("demo").exists()  # the heartbeat goes when it ends
    watchdog.lock_path("demo").parent.mkdir(parents=True, exist_ok=True)
    with open(watchdog.lock_path("demo"), "a") as handle, portable.lock(handle, block=False):
        wait.write_json(watchdog.path("demo"), {"pid": 4242, "at": time.time()})
        assert watchdog.running(CONFIG)["pid"] == 4242
        assert watchdog.run(CONFIG, args) == 0
        assert capsys.readouterr().out == "A colony watchdog already runs for demo on this computer.\n"
    assert watchdog.running(CONFIG) is None


def test_the_leads_wait_starts_a_watchdog_only_inside_claude_code_and_not_too_often(home, monkeypatch):
    started = []
    monkeypatch.setattr(watchdog, "start", lambda config, stay=False: started.append(config) or True)
    watchdog.ensure(CONFIG, watch.Settings())
    assert started == []  # outside Claude Code
    monkeypatch.setattr(cli, "in_claude_code", lambda: True)
    watchdog.ensure(CONFIG, watch.Settings(watchdog=False))
    watchdog.ensure(CONFIG, watch.Settings())
    watchdog.ensure(CONFIG, watch.Settings())
    assert len(started) == 1


def test_stop_ends_the_watchdog_by_its_exact_process_id(home, monkeypatch, capsys):
    killed = []
    monkeypatch.setattr(watchdog, "running", lambda config: {"pid": 4242})
    monkeypatch.setattr(watchdog.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(cli, "repo_root", lambda: home)
    assert watchdog.stop(CONFIG) == 0
    assert killed == [(4242, watchdog.signal.SIGTERM)]
    assert capsys.readouterr().out.startswith("Stopped the watchdog, process 4242.")


@pytest.mark.parametrize("system", ["darwin", "linux"])
def test_install_has_the_computer_keep_it_running_and_uninstall_undoes_it(home, monkeypatch, capsys, system):
    ran = []
    monkeypatch.setattr(watchdog, "RUN", lambda argv, **kw: ran.append(argv) or types.SimpleNamespace(returncode=0))
    monkeypatch.setattr(cli, "repo_root", lambda: home)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert watchdog.install(CONFIG, Namespace(dry_run=True), system=system) == 0
    file = watchdog.service_files(CONFIG, system)[0]
    assert not file.exists() and ran == []
    assert watchdog.install(CONFIG, Namespace(dry_run=False), system=system) == 0
    text = file.read_text()
    if system == "darwin":
        plist = plistlib.loads(text.encode())
        assert plist["KeepAlive"] is True and plist["ProgramArguments"][-3:] == ["watchdog", "run", "--stay"]
        assert ran == [["launchctl", "load", "-w", str(file)]]
    else:
        assert "Restart=always" in text and "watchdog run --stay" in text
        assert ran[-1] == ["systemctl", "--user", "enable", "--now", "com.colony.watchdog.demo.service"]
    assert "PATH" in text and "TOKEN" not in text
    assert watchdog.uninstall(CONFIG, Namespace(dry_run=False), system=system) == 0
    assert not file.exists() and ran[-1] == watchdog.service_files(CONFIG, system)[3][-1]


def test_install_says_what_to_do_on_a_system_it_does_not_know(home, monkeypatch):
    monkeypatch.setattr(cli, "repo_root", lambda: home)
    with pytest.raises(cli.ColonyError, match="knows macOS and Linux"):
        watchdog.install(CONFIG, Namespace(dry_run=False), system="win32")


# The status page


def team_and_cards():
    now = time.time()
    team = {"builder-2": watch.Member("builder-2", "helper", "ana-main-lead", seen=now, active=now - 25 * 60),
            "builder-3": watch.Member("builder-3", "helper", "ana-main-lead", seen=now, intent="working", why="#41",
                                      since=now - 600, report="tests | pass", reported_at=now - 120, active=now),
            "ana-main-lead": watch.Member("ana-main-lead", "lead", seen=now, intent="holding",
                                          why="merges until the release checks pass", since=now - 60)}
    cards = [progress.Card(41, "dark mode switch", "In progress", "builder-3", "ana-main-lead", "S", 20.0,
                           now - 30 * 60)]
    return team, cards, now


def test_the_status_page_shows_what_needs_a_look_the_cards_and_each_session():
    team, cards, now = team_and_cards()
    text = statuspage.render(CONFIG, team, S, now, cards)
    assert text.startswith("# demo: team status\n")
    assert "- idle: builder-2 (25 min) has done nothing" in text
    assert "| #41 | builder-3 | In progress | 20 min | 30 min, past its prediction | dark mode switch |" in text
    assert "| builder-3 | ana-main-lead | working | #41 | 2 min ago: tests \\| pass | - |" in text
    assert "| ana-main-lead | - | holding | merges until the release checks pass |" in text
    assert statuspage.digest(text) == statuspage.digest(statuspage.render(CONFIG, team, S, now + 30, cards))


def test_the_status_page_is_made_once_pinned_and_written_only_when_it_changed(home, monkeypatch):
    calls = []

    def gh(*args):
        calls.append(args[:2] if args[0] != "api" else ("api", args[2]))
        if args[:2] == ("issue", "list"):
            return "[]"
        if args[:2] == ("issue", "create"):
            return "https://github.com/acme/demo/issues/9\n"
        return "{}"
    monkeypatch.setattr(wait, "gh", gh)
    now = time.time()
    assert statuspage.publish(CONFIG, "# page\nUpdated 10:00\nA\n", now=now) == "https://github.com/acme/demo/issues/9"
    assert calls == [("issue", "list"), ("issue", "create"), ("issue", "pin"), ("api", "PATCH")]
    statuspage.publish(CONFIG, "# page\nUpdated 10:05\nA\n", now=now + 60)
    assert len(calls) == 4  # only the stamp changed
    statuspage.publish(CONFIG, "# page\nUpdated 10:06\nB\n", now=now + 120)
    statuspage.publish(CONFIG, "# page\nUpdated 10:40\nB\n", now=now + 120 + statuspage.REFRESH)
    statuspage.publish(CONFIG, "# page\nUpdated 10:40\nB\n", now=now + 121 + statuspage.REFRESH, force=True)
    assert calls[4:] == [("api", "PATCH")] * 3


def test_the_watchdog_keeps_the_page_only_when_asked_and_not_too_often(home, monkeypatch):
    written = []
    monkeypatch.setattr(statuspage, "publish", lambda config, text, force=False, now=None: written.append(text) or "u")
    monkeypatch.setattr(watch, "team_now", lambda config, now: ({}, ""))
    monkeypatch.setattr(progress, "cards_or_note", lambda config: ([], "Progress: no board."))
    now = time.time()
    assert statuspage.keep(CONFIG, watch.Settings(page=False), now) == "" and written == []
    statuspage.keep(CONFIG, watch.Settings(), now)
    statuspage.keep(CONFIG, watch.Settings(), now + 60)
    assert len(written) == 1 and "Progress: no board." in written[0]
    statuspage.keep(CONFIG, watch.Settings(), now + 6 * 60)
    assert len(written) == 2


def test_a_lead_whose_own_wait_saw_a_busy_helper_on_another_computer_is_not_idle(woken, posted):
    pulse("ana-main-lead", ago=30, kind="lead", lead="", active_ago=3 * 3600)
    held = wait.read_json(watch.pulse_path("demo", "ana-main-lead"), {})
    wait.write_json(watch.pulse_path("demo", "ana-main-lead"), {**held, "busy": ["builder-9"]})
    watchdog.tick(CONFIG, S, {})
    assert posted == []


def test_the_watchdog_belongs_to_no_session(monkeypatch):
    for name in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_PID", "COLONY_SESSION", "COLONY_LEAD",
                 "COLONY_LEAD_TOKEN"):
        monkeypatch.setenv(name, "x")
    env = watchdog.own_env()
    assert not [name for name in env if name.startswith("COLONY_") or name.startswith("CLAUDECODE")]
    assert "CLAUDE_CODE_SESSION_ID" not in env and "CLAUDE_PID" not in env and env["PATH"]


def test_colony_watch_shows_each_session_and_what_is_worth_a_look(home, monkeypatch, capsys):
    team, cards, now = team_and_cards()
    monkeypatch.setattr(watch, "team_now", lambda config, now: (team, ""))
    monkeypatch.setattr(progress, "cards_or_note", lambda config: (cards, None))
    assert watch.watch_command(CONFIG, Namespace(json=False, page=False, folded=False)) == 0
    out = capsys.readouterr().out
    assert "- ana-main-lead: holding, merges until the release checks pass." in out
    assert "- builder-3 (helper of ana-main-lead): working, #41. Last report 2 min ago: tests | pass." in out
    assert "- idle: builder-2 (25 min) has done nothing" in out
    assert "Progress: 0 done, 0 in review, 1 in progress, 0 to do." in out
