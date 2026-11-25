"""Tests for colony/recover.py: the session ledger the hooks keep, the background tasks a long command marks, the Stop
hook's note when one stopped, `colony crash-report` and `colony resume`."""
import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from colony import cli, guards, recover, stop, wait
from conftest import stub_path

CONFIG = """\
[project]
name = "demo"
repo = "acme/demo"
base = "dev"
worktrees = "~/trees"
checks = "make check"
[accounts.first]
config_dir = "~/first"
person = "ana"
[accounts.second]
config_dir = "~/second"
person = "ana"
[roles]
lead = { model = "m", effort = "high" }
builder = { model = "m", effort = "medium" }
reviewer = { model = "m", effort = "high" }
walker = { model = "m", effort = "medium" }
fixer = { model = "m", effort = "medium" }
[gate]
rubric = ["bugs"]
max_rounds = 3
walk = true
[budget]
provider_dollars = 0
"""
NOW = time.time()


@pytest.fixture
def config(tmp_path, monkeypatch):
    """A host repo with the demo config, a temporary HOME with both account folders, and no claude on PATH."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", stub_path(tmp_path / "bin"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
    host = tmp_path / "host"
    host.mkdir()
    subprocess.run(["git", "init", "-q", str(host)], check=True)
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(CONFIG)
    monkeypatch.chdir(host)
    monkeypatch.setattr(recover, "boot_time", lambda: None)
    return cli.load_config()


def as_session(monkeypatch, name: str, claude: str = "", lead: str = "", account_dir: str = "") -> None:
    """Run what follows as the Colony session `name`, in the Claude Code session `claude`."""
    monkeypatch.setenv(cli.SESSION_ENV, name)
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    for key, value in ((wait.LEAD_ENV, lead), (cli.CLAUDE_SESSION_ENV, claude), ("CLAUDE_CONFIG_DIR", account_dir)):
        if value:
            monkeypatch.setenv(key, value)
        else:
            monkeypatch.delenv(key, raising=False)


def hook(monkeypatch, run, config, event: dict) -> tuple[int, str]:
    """Run a hook as Claude Code would, with its event on stdin; its exit code and what it printed."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = run(config, argparse.Namespace())
    return code, out.getvalue()


def entry(config, name: str) -> dict:
    return wait.read_json(recover.ledger_path("demo", name), None)


@pytest.fixture
def no_github(monkeypatch):
    """The prompt hook reads no GitHub and posts nothing."""
    monkeypatch.setattr(guards, "read_unread", lambda config, args, me: [])
    monkeypatch.setattr(guards, "post", lambda config, to, sentence, sender: 0)


def test_the_hooks_keep_a_sessions_ledger_with_its_ids_folder_and_last_sign_of_life(config, monkeypatch, tmp_path,
                                                                                      no_github):
    as_session(monkeypatch, "builder-2", "c-1", lead="ana-main-lead", account_dir=str(tmp_path / "second"))
    transcript = tmp_path / "second" / "projects" / "x" / "c-1.jsonl"
    start = {"hook_event_name": "SessionStart", "session_id": "c-1", "transcript_path": str(transcript),
             "cwd": str(tmp_path / "host"), "source": "startup"}
    assert hook(monkeypatch, guards.unread, config, start)[0] == 0
    held = entry(config, "builder-2")
    assert held["id"] == "c-1" and held["folder"] == str(tmp_path / "host") and held["transcript"] == str(transcript)
    assert (held["session"], held["lead"], held["person"], held["account"]) == ("builder-2", "ana-main-lead", "ana",
                                                                                "second")
    prompt = {"hook_event_name": "UserPromptSubmit", "session_id": "c-1", "prompt": "the token is sk-secret",
              "cwd": str(tmp_path)}
    hook(monkeypatch, guards.unread, config, prompt)
    text = recover.ledger_path("demo", "builder-2").read_text()
    assert "sk-secret" not in text and json.loads(text)["folder"] == str(tmp_path / "host")  # the start folder stays
    hook(monkeypatch, guards.stopped, config, {"error": "rate_limit"})
    hook(monkeypatch, guards.ended, config, {"reason": "other"})
    held = entry(config, "builder-2")
    assert (held["error"], held["reason"]) == ("rate_limit", "other") and held["ended"] >= held["error_at"]
    # The session comes back: SessionStart clears the facts of its last stop.
    hook(monkeypatch, guards.unread, config, {**start, "source": "resume"})
    assert not {"error", "reason", "ended"} & set(entry(config, "builder-2"))
    # A new conversation under the same name starts the file afresh.
    hook(monkeypatch, guards.unread, config, {**start, "session_id": "c-2"})
    assert entry(config, "builder-2")["id"] == "c-2"


def test_a_named_lead_keeps_its_ledger_under_its_lead_name_and_a_session_outside_colony_keeps_none(config,
                                                                                                    monkeypatch,
                                                                                                    no_github):
    as_session(monkeypatch, "lead", "c-9", lead="ana-main-lead")
    hook(monkeypatch, guards.unread, config, {"hook_event_name": "SessionStart", "session_id": "c-9"})
    assert entry(config, "ana-main-lead")["session"] == "lead"
    monkeypatch.delenv(cli.SESSION_ENV)
    hook(monkeypatch, guards.ended, config, {"reason": "other"})
    assert sorted(path.name for path in recover.folder("demo", recover.LEDGER).glob("*.json")) == ["ana-main-lead.json"]


def test_a_long_command_marks_its_task_while_it_runs_and_drops_the_mark_when_it_ends(config, monkeypatch):
    as_session(monkeypatch, "builder-2", "c-1")
    seen = []

    def run(config, args):
        seen.append(recover.tasks(config))
        raise cli.ColonyError("gh is not on PATH")

    args = argparse.Namespace(command="batch", name="2026-11-24", run=run, dry_run=False)
    monkeypatch.setattr(cli, "build_parser", lambda: type("P", (), {"parse_args": lambda self, argv: args})())
    assert cli.main(["batch"]) == 2  # the command's error ends it, and its mark goes with it
    [[task]] = seen
    assert (task["pid"], task["session"], task["claude"]) == (os.getpid(), "builder-2", "c-1")
    assert task["label"] == "colony batch --name 2026-11-24"
    assert recover.tasks(config) == []
    for command in ("post", "status"):  # quick commands keep no mark
        with recover.tracked(config, argparse.Namespace(command=command)):
            assert recover.tasks(config) == []


def dead_pid() -> int:
    """The id of a process that has ended."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def write_task(config, pid: int, command: str = "wait", session: str = "builder-2", claude: str = "c-1",
               label: str = "colony wait") -> None:
    wait.write_json(recover.folder("demo", recover.TASKS) / f"{pid}.json",
                    {"pid": pid, "command": command, "label": label, "session": session, "claude": claude,
                     "started": NOW - 600})


def test_the_stop_hook_tells_a_session_once_to_start_again_a_task_that_something_killed(config, monkeypatch,
                                                                                        no_github):
    as_session(monkeypatch, "builder-2", "c-1")
    write_task(config, os.getpid(), "fast-check", label="colony fast-check")  # still running
    write_task(config, dead_pid())  # killed
    write_task(config, dead_pid(), "batch", label="colony batch --name nov-24")
    write_task(config, dead_pid(), session="builder-3", claude="c-3")  # another session's
    code, out = hook(monkeypatch, guards.tasks, config, {"hook_event_name": "Stop", "stop_hook_active": False})
    assert code == 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "Your background `colony wait`" in decision["reason"] and "run_in_background" in decision["reason"]
    assert "`colony status --name nov-24`" in decision["reason"]
    assert entry(config, "builder-2")["seen"] >= NOW  # each turn's end is a sign of life
    assert hook(monkeypatch, guards.tasks, config, {"hook_event_name": "Stop"})[1] == ""  # shown once
    assert [task["session"] for task in recover.stopped_tasks(config)] == ["builder-3"]
    as_session(monkeypatch, "builder-3", "c-3")
    assert hook(monkeypatch, guards.tasks, config, {"stop_hook_active": True})[1] == ""  # never twice in one turn
    assert len(recover.stopped_tasks(config)) == 1


def test_a_wait_the_session_replaced_needs_no_note(config, monkeypatch, no_github):
    as_session(monkeypatch, "builder-2", "c-1")
    write_task(config, dead_pid())  # the wait it stopped itself
    write_task(config, os.getpid())  # the one it started in its place
    assert hook(monkeypatch, guards.tasks, config, {"hook_event_name": "Stop"})[1] == ""
    assert recover.stopped_tasks(config) == []


def iso(at: float) -> str:
    return datetime.fromtimestamp(at, timezone.utc).isoformat().replace("+00:00", "Z")


def transcript(path: Path, *entries: dict) -> str:
    """A transcript of these entries, last written when its last entry was."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item) + "\n" for item in entries))
    last = recover.stamp(entries[-1]["timestamp"])
    os.utime(path, (last, last))
    return str(path)


def bash_call(at: float, command: str) -> dict:
    return {"type": "assistant", "timestamp": iso(at), "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": command}}]}}


def said(at: float, text: str = "done") -> dict:
    return {"type": "assistant", "timestamp": iso(at), "message": {"content": [{"type": "text", "text": text}]}}


def ledger(name: str, at: float, **fields) -> None:
    held = {"name": name, "session": name, "id": f"id-{name}", "account": "first", "seen": at, "person": "ana",
            **fields}
    wait.write_json(recover.ledger_path("demo", name), held)


@pytest.fixture
def crashed(config, tmp_path, monkeypatch):
    """A computer after a pattern kill: the lead ran pkill at T, which stopped it and two builders within a minute.
    Earlier, builder-4 hit its usage limit; builder-5 was stopped with colony stop; builder-6 was exited by its
    person; builder-7 runs; builder-8 stopped two days ago."""
    crash = NOW - 3600
    projects = tmp_path / "first" / "projects" / "-host"
    ledger("ana-main-lead", crash - 300, session="lead", lead="ana-main-lead",
           transcript=transcript(projects / "id-lead.jsonl", said(crash - 400),
                                 bash_call(crash, 'pkill -f "colony wait" -U $(id -u) -n')))
    ledger("builder-1", crash + 20, lead="ana-main-lead")
    ledger("builder-2", crash - 10, lead="ana-main-lead", ended=crash + 5, reason="other",
           transcript=transcript(projects / "id-b2.jsonl", bash_call(crash - 10, "npm test")))
    ledger("builder-4", crash - 7200, transcript=transcript(projects / "id-b4.jsonl", {
        **said(crash - 7200, "You've hit your session limit"), "isApiErrorMessage": True, "error": "rate_limit",
        "apiError": "usage_limit_reached"}))
    ledger("builder-5", crash - 900, stopped=crash - 900, stopped_by="ana-main-lead")
    ledger("builder-6", crash - 1200, ended=crash - 1200, reason="prompt_input_exit")
    ledger("builder-7", NOW - 5)
    ledger("builder-8", NOW - 2 * 86400)
    monkeypatch.setattr(recover, "listed_ids", lambda config: {"id-builder-7"})
    return crash


def test_the_crash_report_names_each_stop_its_last_sign_of_life_and_its_likely_cause(crashed, config, capsys):
    assert recover.crash_report(config, argparse.Namespace(within=None, json=False)) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].startswith("colony crash-report: this computer, the last 24 hours")
    assert "Stopped unexpectedly (4), which `colony resume` reopens:" in out
    lead = next(line for line in lines if line.startswith("- ana-main-lead"))
    assert f"last sign of life {recover.when(crashed)}, from its transcript" in lead
    assert 'Likely cause: ana-main-lead ran `pkill -f "colony wait" -U $(id -u) -n`' in lead
    assert "it stopped within 90 seconds of builder-2, builder-1" in lead
    b2 = next(line for line in lines if line.startswith("- builder-2 (helper of ana-main-lead)"))
    assert "a kill by name or pattern, just before" in b2 and "Claude Code ended it" in b2 and "(other)" in b2
    b4 = next(line for line in lines if line.startswith("- builder-4"))
    assert "Likely cause: its account hit a usage limit (rate_limit, usage_limit_reached)" in b4
    assert "Stopped on purpose (2):" in out
    assert f"- builder-5: `colony stop` by ana-main-lead at {recover.when(crashed - 900)}." in out
    assert "- builder-6: its person exited it." in out
    assert "Running (1): builder-7." in out
    assert "builder-8" not in out
    assert recover.crash_report(config, argparse.Namespace(within=72, json=False)) == 0
    assert "builder-8" in capsys.readouterr().out


def test_the_crash_report_names_a_restart_of_the_computer_and_prints_json(crashed, config, monkeypatch, capsys):
    monkeypatch.setattr(recover, "boot_time", lambda: crashed + 600)
    recover.crash_report(config, argparse.Namespace(within=None, json=True))
    report = json.loads(capsys.readouterr().out)
    by_name = {item["name"]: item for item in report["sessions"]}
    assert by_name["builder-4"]["cause"].startswith("the computer started again at ")
    assert by_name["builder-4"]["state"] == recover.UNEXPECTED and by_name["builder-7"]["state"] == recover.RUNNING
    assert report["tasks"] == [] and report["services"] == []


def test_without_claude_a_recent_sign_of_life_counts_as_running(crashed, config, monkeypatch):
    monkeypatch.setattr(recover, "listed_ids", lambda config: None)
    ledger("builder-9", time.time() - 30)
    states = {seen.name: seen.state for seen in recover.survey(config, 24)}
    assert states["builder-9"] == recover.RUNNING and states["builder-1"] == recover.UNEXPECTED


@pytest.fixture
def opened(monkeypatch):
    """Each session `colony resume` opens: its args and folder, recorded instead of a real launch."""
    calls = []

    def launch(config, args, session, role, prompt):
        calls.append({"session": session, "role": role, "prompt": prompt, "resume": args.resume,
                      "account": args.account, "lead": args.lead_name, "background": args.background,
                      "folder": os.getcwd()})
        return 0
    monkeypatch.setattr(cli, "launch", launch)
    return calls


def resume_args(*names, dry_run=False, within=None):
    return argparse.Namespace(names=list(names), dry_run=dry_run, within=within, command="resume")


def test_resume_reopens_each_session_that_stopped_unexpectedly_once_leads_first(crashed, config, opened, capsys):
    assert recover.resume(config, resume_args()) == 0
    assert [call["session"] for call in opened] == ["lead", "builder-1", "builder-2", "builder-4"]
    lead, first = opened[0], opened[1]
    assert (lead["role"], lead["resume"], lead["account"], lead["background"]) == ("lead", "id-ana-main-lead",
                                                                                   "first", True)
    assert "reopened this session with `colony resume`: it stopped unexpectedly after" in lead["prompt"]
    assert "takes your lead's heartbeat back" in lead["prompt"] and "colony crash-report" in lead["prompt"]
    assert (first["role"], first["lead"]) == ("builder", "ana-main-lead")
    assert "check your worktree with `git status`" in first["prompt"]
    opened.clear()
    assert recover.resume(config, resume_args()) == 0  # each one is reopened once
    assert opened == [] and "No session to reopen" in capsys.readouterr().out


def test_resume_by_name_reopens_one_stopped_on_purpose_and_keeps_a_running_one(crashed, config, opened, capsys):
    assert recover.resume(config, resume_args("demo-builder-5", "builder-7")) == 0
    assert [call["session"] for call in opened] == ["builder-5"]
    assert "it stopped after" in opened[0]["prompt"] and "`colony stop` by ana-main-lead" in opened[0]["prompt"]
    assert "kept builder-7: it runs" in capsys.readouterr().out
    with pytest.raises(cli.ColonyError, match="no session named nobody showed life here"):
        recover.resume(config, resume_args("nobody"))


def test_a_dry_run_reopens_nothing_and_marks_nothing(crashed, config, opened):
    recover.resume(config, resume_args(dry_run=True))
    assert len(opened) == 4
    assert not any("resumed" in entry(config, name) for name in ("builder-1", "builder-2"))


def test_resume_opens_in_the_folder_the_session_started_in_and_keeps_one_whose_account_is_gone(crashed, config, opened,
                                                                                               tmp_path, capsys):
    start = tmp_path / "elsewhere"
    start.mkdir()
    ledger("builder-1", crashed + 20, folder=str(start),
           transcript=str(tmp_path / "first" / "projects" / recover.slug(str(start.resolve())) / "x.jsonl"))
    ledger("builder-2", crashed + 30, account="gone", config_dir=str(tmp_path / "gone"))
    assert recover.resume(config, resume_args()) == 1
    assert {call["session"]: call["folder"] for call in opened}["builder-1"] == str(start.resolve())
    assert "builder-2" not in {call["session"] for call in opened}
    assert "kept builder-2: its settings folder" in capsys.readouterr().err


def test_resume_reopens_a_session_with_claude_resume_on_its_own_account(crashed, config, capsys, monkeypatch):
    monkeypatch.setattr(cli, "cmux_usable", lambda: False)
    assert recover.resume(config, resume_args("builder-1", dry_run=True)) == 0
    out = capsys.readouterr().out
    command = next(line for line in out.splitlines() if line.startswith("command: "))
    assert "claude --resume id-builder-1 --remote-control demo-builder-1 --model m --effort medium" in command
    assert "dry run: demo-builder-1 on account first, in a background session" in out


def test_resume_tells_a_session_which_of_its_tasks_stopped_and_starts_failed_services(crashed, config, opened,
                                                                                      tmp_path, capsys):
    write_task(config, dead_pid(), "batch", session="builder-1", claude="id-builder-1", label="colony batch --name b1")
    up = tmp_path / "db-up"
    config["recover"] = {"services": [{"name": "db", "check": f"test -f '{up}'", "restart": f"touch '{up}'"},
                                      {"name": "cache", "check": "false"}]}
    recover.crash_report(config, argparse.Namespace(within=None, json=False))
    out = capsys.readouterr().out
    assert "- builder-1's `colony batch --name b1`, started" in out
    assert "- db: `test -f" in out and "`colony resume` runs `touch" in out
    assert "- cache: `false` failed; it has no restart command" in out
    assert recover.resume(config, resume_args()) == 1  # the cache stays down
    note = next(call["prompt"] for call in opened if call["session"] == "builder-1")
    assert "Your background `colony batch --name b1`" in note and "`colony status --name b1`" in note
    assert up.exists() and recover.stopped_tasks(config) == []
    out = capsys.readouterr().out
    assert "db: started again with `touch" in out and "cache: its check `false` fails" in out


def test_colony_stop_notes_a_stop_on_purpose_and_signals_one_process_alone(config, monkeypatch):
    ledger("builder-3", NOW)
    monkeypatch.setattr(cli, "running_sessions", lambda config: [
        {"kind": "background", "name": "demo-builder-3", "id": "bg3", "sessionId": "id-builder-3"}])
    monkeypatch.setattr(stop, "stop_background", lambda agent: None)
    monkeypatch.setattr(stop, "uncommitted", lambda agent: False)
    as_session(monkeypatch, "lead", lead="ana-main-lead")
    config["project"]["mode"] = "solo"
    assert stop.stop(config, argparse.Namespace(names=["builder-3"], force=False)) == 0
    held = entry(config, "builder-3")
    assert held["stopped_by"] == "ana-main-lead" and held["stopped"] >= NOW
    for pid in (0, 1, -1, -4242):
        with pytest.raises(ValueError, match="is no single session's process id"):
            stop.stop_interactive({"pid": pid})


def test_alive_tells_a_running_process_from_an_ended_one():
    assert recover.alive(os.getpid())
    assert not recover.alive(dead_pid())
    for pid in (0, -1, None, True, "12"):
        assert not recover.alive(pid)


def test_the_transcripts_folder_is_named_after_the_folder_a_session_started_in():
    assert recover.slug("/Users/ana/Desktop/my.app") == "-Users-ana-Desktop-my-app"


def test_a_background_open_never_takes_this_terminal(monkeypatch):
    monkeypatch.setattr(cli, "cmux_usable", lambda: False)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    assert cli.where_to_open(argparse.Namespace(background=True, here=True)) == "background"
    assert cli.where_to_open(argparse.Namespace(here=False)) == "terminal"
    monkeypatch.setattr(cli, "cmux_usable", lambda: True)
    assert cli.where_to_open(argparse.Namespace(background=True)) == "cmux"


def test_register_routes_crash_report_and_resume():
    parser = argparse.ArgumentParser()
    recover.register(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["crash-report", "--within", "6", "--json"])
    assert (args.run, args.within, args.json) == (recover.crash_report, 6.0, True)
    args = parser.parse_args(["resume", "builder-2", "--dry-run"])
    assert (args.run, args.names, args.dry_run) == (recover.resume, ["builder-2"], True)


def test_a_session_name_that_isnt_one_never_becomes_a_ledger_file(config, monkeypatch):
    as_session(monkeypatch, "../../elsewhere", "c-1")
    assert recover.session_name() == ""
    recover.note_session(config, {"session_id": "c-1"}, "start")
    assert not recover.folder("demo", recover.LEDGER).exists()


def test_resume_keeps_a_session_the_ledger_holds_no_id_for(crashed, config, opened, capsys):
    ledger("builder-1", crashed + 20, id="")
    assert recover.resume(config, resume_args()) == 1
    assert "builder-1" not in {call["session"] for call in opened} and len(opened) == 3
    assert "kept builder-1: the ledger holds no Claude Code session id" in capsys.readouterr().err
