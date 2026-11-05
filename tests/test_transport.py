"""Tests for colony/transport.py: a stand-in `agent-relay-probe` and `gh` on PATH log their calls and play back canned
answers, and a real Unix socket stands in for the Agent Relay core, so nothing reaches a real relay or GitHub."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from argparse import Namespace
from importlib import resources
from pathlib import Path

import pytest

from colony import cli, transport, wait

STUB = """#!{python}
import json, pathlib, sys, time
here = pathlib.Path(__file__).resolve().parent
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with open(here / "calls.jsonl", "a") as log:
    log.write(json.dumps([name, *args]) + "\\n")
answers = sorted(here.glob(name + "-*.json"))
if answers:
    answer = json.loads(answers[0].read_text())
    answers[0].unlink()
    time.sleep(answer.get("sleep", 0))
    sys.stdout.write(answer.get("out", ""))
    sys.stderr.write(answer.get("err", ""))
    sys.exit(answer.get("code", 0))
if name == "gh":
    sys.stdout.write("https://github.com/acme/demo/issues/12#issuecomment-1\\n")
else:
    to = args[args.index("--to") + 1]
    sys.stdout.write(json.dumps({"ok": True, "data": {"to": to, "message_id": "m1", "conversation_id": "c1"}}))
"""
PROBE = "agent-relay-probe"
GITHUB = {"project": {"repo": "acme/demo", "name": "demo"}}
RELAY = {**GITHUB, "messages": {"transport": "relay"}}
START = "for builder-1: start this card (from lead)"


class World:
    """The stand-ins: queue an answer for gh or the probe, then read the calls each got."""

    def __init__(self, home: Path, bin_dir: Path, core: str):
        self.home, self.bin, self.core, self.count = home, bin_dir, core, 0

    @property
    def probe(self) -> str:
        return str(self.bin / PROBE)

    def answer(self, name: str, **answer) -> None:
        """Queue the next answer of `name`: its out, err, exit code and a sleep before it."""
        self.count += 1
        (self.bin / f"{name}-{self.count:03}.json").write_text(json.dumps(answer))

    def calls(self, name: str) -> list[list[str]]:
        """The arguments of each call `name` got."""
        log = self.bin / "calls.jsonl"
        lines = log.read_text().splitlines() if log.exists() else []
        return [call[1:] for call in map(json.loads, lines) if call[0] == name]


@pytest.fixture
def core():
    """A listening Unix socket in a short folder, as a running core's would be."""
    folder = tempfile.mkdtemp(prefix="relay-")
    path = os.path.join(folder, "relay.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(64)
    yield path
    server.close()
    shutil.rmtree(folder)


@pytest.fixture
def world(tmp_path, monkeypatch, core):
    """A temporary HOME whose relay-socket pointer names the core, and the stand-in probe and gh first on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("gh", PROBE):
        (bin_dir / name).write_text(STUB.replace("{python}", sys.executable))
        (bin_dir / name).chmod(0o755)
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("COLONY_PERSON", "serdar")
    pointer = tmp_path / transport.POINTER
    pointer.parent.mkdir(parents=True)
    pointer.write_text(f"{core}\n")
    return World(tmp_path, bin_dir, core)


def delivered(monkeypatch, body: str, me: wait.Session, card: int = 12) -> tuple[list, list]:
    """What a relay wait for `me` gathers from one comment with this body, and what it marks seen."""
    found = {"id": 1, "issue_url": f"https://api.github.com/repos/acme/demo/issues/{card}", "body": body,
             "updated_at": "2026-11-05T10:00:00Z"}
    monkeypatch.setattr(wait, "gh_get", lambda path, etag: (200, etag, [found]))
    state = {"since": "2026-11-05T09:00:00Z", "pending": []}
    wait.poll("acme/demo", state, me, transport.MARK)
    return state["pending"], state["seen"]


# Finding the core


@pytest.mark.parametrize("route", ["pointer", "claude rules", "codex rules"])
def test_relay_available_finds_the_probe_and_the_socket_as_the_skill_says(world, route):
    elsewhere = world.home / "elsewhere" / PROBE  # the rules name their own probe, not the one on PATH
    elsewhere.parent.mkdir()
    shutil.copy(world.bin / PROBE, elsewhere)
    if route != "pointer":
        (world.home / transport.POINTER).unlink()
    if route == "claude rules":
        settings = world.home / ".claude" / "settings.json"
        settings.parent.mkdir()
        rules = [f"Bash({elsewhere} relay send --socket '{world.core}' *)",
                 f"Bash({elsewhere} relay agents --socket '{world.core}')"]
        settings.write_text(json.dumps({"permissions": {"allow": rules}}))
    if route == "codex rules":
        rules = world.home / ".codex" / "rules" / "agent-relay.rules"
        rules.parent.mkdir(parents=True)
        rules.write_text(f'prefix_rule(\n    pattern = ["{elsewhere}", "relay", "agents", "--socket", "{world.core}"],\n'
                         '    decision = "allow",\n)\n')
    probe = world.probe if route == "pointer" else str(elsewhere)
    assert transport.find_relay() == (probe, world.core)
    assert transport.relay_available()
    assert world.calls(PROBE) == []  # finding the core runs nothing


@pytest.mark.parametrize("missing", ["socket", "listener", "probe"])
def test_relay_available_is_false_without_a_running_core(world, monkeypatch, missing):
    if missing == "socket":
        (world.home / transport.POINTER).unlink()  # and no core's socket at the usual places in this HOME
    if missing == "listener":  # a socket file left behind by a core that stopped
        stopped = os.path.join(tempfile.mkdtemp(prefix="relay-"), "relay.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(stopped)
        server.close()
        (world.home / transport.POINTER).write_text(stopped)
    if missing == "probe":
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert not transport.relay_available()


# Sending


def test_a_relay_send_runs_the_probe_with_the_skills_arguments_and_marks_the_record(world):
    assert transport.send(RELAY, "Builder-1", START, card=12) == 12
    assert world.calls(PROBE) == [["relay", "send", "--socket", world.core, "--to", "builder-1",
                                   "--body", f"#12 {START}"]]
    assert world.calls("gh") == [["issue", "comment", "12", "--repo", "acme/demo", "--body", f"{START}\n{transport.MARK}"]]


def test_say_sends_an_urgent_line_for_another_lead_through_the_relay(world, monkeypatch, capsys):
    (world.home / ".colony" / "demo").mkdir(parents=True)
    (world.home / ".colony" / "demo" / "lead-coordination.json").write_text("5")
    monkeypatch.setenv("COLONY_SESSION", "lead")
    assert wait.say(RELAY, Namespace(person=None, to="burak-lead", sentence="urgent: I merge dev in 10 minutes")) == 0
    line = "for burak-lead: urgent: I merge dev in 10 minutes (from serdar-lead)"
    assert capsys.readouterr().out == f"#5 {line}\n"
    assert world.calls(PROBE) == [["relay", "send", "--socket", world.core, "--to", "burak-lead", "--body", f"#5 {line}"]]
    assert world.calls("gh") == [["issue", "comment", "5", "--repo", "acme/demo", "--body", f"{line}\n{transport.MARK}"]]


@pytest.mark.parametrize("to, line, card, waiting, at_once", [
    ("builder-1", START, 12, [], True),
    ("builder-1", "for builder-1: can you look? (from builder-2)", 12, [], False),  # a builder takes only the lead's
    ("lead", "for lead: done, builder-1/41 pushed (from builder-1)", 41, [41], True),
    ("lead", "for lead: done, builder-1/42 pushed (from builder-1)", 42, [41], False),  # waits for the digest
    ("lead", "for lead: blocked: the test database won't start (from builder-1)", 41, [], True),
    ("burak-lead", "for burak-lead: can your builders take #12? (from serdar-lead)", 5, [], False),
])
def test_the_relay_carries_only_a_line_the_receiving_wait_prints_at_once(world, to, line, card, waiting, at_once):
    (world.home / ".colony" / "demo").mkdir(parents=True)
    (world.home / ".colony" / "demo" / "lead-waiting.json").write_text(json.dumps(waiting))
    transport.send(RELAY, to, line, card=card)
    assert bool(world.calls(PROBE)) is at_once
    assert world.calls("gh")[0][-1] == (f"{line}\n{transport.MARK}" if at_once else line)


@pytest.mark.parametrize("config, core_runs, note", [
    (GITHUB, True, ""),
    (RELAY, False, "no Agent Relay core is running on this computer"),
])
def test_without_the_relay_the_line_goes_by_github_alone(world, capsys, config, core_runs, note):
    if not core_runs:
        (world.home / transport.POINTER).unlink()
    assert transport.send(config, "builder-1", START, card=12) == 12
    assert world.calls(PROBE) == []
    assert world.calls("gh") == [["issue", "comment", "12", "--repo", "acme/demo", "--body", START]]
    err = capsys.readouterr().err
    assert (note in err and "goes by GitHub alone" in err) if note else err == ""


@pytest.mark.parametrize("answer, why", [
    ({"out": '{"ok":false,"error":{"code":"address_not_found"}}', "code": 1}, "address_not_found"),
    ({"err": "error: unrecognized subcommand 'send'", "code": 2}, "unrecognized subcommand"),
    ({"out": "not json"}, "not json"),
    ({"sleep": 3}, "timed out"),
])
def test_a_relay_failure_falls_back_to_github_without_losing_the_line(world, monkeypatch, capsys, answer, why):
    monkeypatch.setattr(transport, "TIMEOUT", 0.5)
    world.answer(PROBE, **answer)
    assert transport.send(RELAY, "builder-1", START, card=12) == 12
    assert len(world.calls(PROBE)) == 1
    body = world.calls("gh")[0][-1]
    assert body == START  # no mark, so the wait delivers it
    assert why in capsys.readouterr().err
    pending, _ = delivered(monkeypatch, body, wait.Session("builder-1", frozenset({"builder-1"})))
    assert pending == [[f"#12 {START}", True]]


def test_a_line_delivered_both_ways_is_acted_on_once(world, monkeypatch):
    transport.send(RELAY, "builder-1", START, card=12)
    body = world.calls("gh")[0][-1]
    builder = wait.Session("builder-1", frozenset({"builder-1"}))
    pending, seen = delivered(monkeypatch, body, builder)
    assert world.calls(PROBE)[0][-1] == f"#12 {START}"  # the relay carried it, in the form the wait prints
    assert pending == [] and seen == [f"1:{START}"]  # and the wait took the record's copy without printing it


def test_github_failing_after_the_relay_says_the_relay_delivered_it(world):
    world.answer("gh", err="HTTP 502", code=1)
    with pytest.raises(wait.GhError, match="the relay delivered the line, but GitHub kept no record of it"):
        transport.send(RELAY, "builder-1", START, card=12)
    assert len(world.calls(PROBE)) == 1


@pytest.mark.parametrize("line, why", [
    ("for builder-1: use ghp_abcdefghijklmnopqrstuvwxyz0123456789 (from lead)", "a token"),
    ("for builder-1: the key is s3cr3t-value-0123456789 (from lead)", "the value of $DEMO_API_KEY"),
])
def test_a_line_never_carries_a_secret(world, monkeypatch, line, why):
    monkeypatch.setenv("DEMO_API_KEY", "s3cr3t-value-0123456789")
    with pytest.raises(cli.ColonyError, match="never carries a secret") as raised:
        transport.send(RELAY, "builder-1", line, card=12)
    assert why in str(raised.value) and "s3cr3t" not in str(raised.value)
    assert world.calls(PROBE) == [] and world.calls("gh") == []


# colony post: every card line, from builders and the lead


@pytest.mark.parametrize("session, to, sentence, urgent, line, relayed", [
    ("builder-2", "lead", "blocked: the test database won't start", False,
     "for lead: blocked: the test database won't start (from builder-2)", True),
    ("builder-2", "Lead", "main is  red", True, "for lead: urgent: main is red (from builder-2)", True),
    ("lead", "builder-2", "start this card", False, "for builder-2: start this card (from lead)", True),
    ("builder-2", "lead", "done, builder-2/41 pushed, 12 passed", False,
     "for lead: done, builder-2/41 pushed, 12 passed (from builder-2)", False),  # waits for the lead's digest
])
def test_post_sends_a_card_line_through_the_transport(world, monkeypatch, capsys, session, to, sentence, urgent, line,
                                                      relayed):
    monkeypatch.setenv("COLONY_SESSION", session)
    assert wait.post(RELAY, Namespace(card=41, to=to, sentence=sentence, urgent=urgent)) == 0
    assert capsys.readouterr().out == f"#41 {line}\n"
    probe = [["relay", "send", "--socket", world.core, "--to", line.split(":")[0][4:], "--body", f"#41 {line}"]]
    assert world.calls(PROBE) == (probe if relayed else [])
    assert world.calls("gh") == [["issue", "comment", "41", "--repo", "acme/demo",
                                  "--body", f"{line}\n{transport.MARK}" if relayed else line]]


def test_post_is_a_command_on_the_command_line(world, tmp_path):
    host = tmp_path / "host"
    (host / ".colony").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(host)], check=True)
    (host / ".colony" / "colony.toml").write_text(Path(str(resources.files("colony") / "colony.toml.example")).read_text())
    env = {"HOME": str(tmp_path), "PATH": f"{world.bin}:/usr/bin:/bin", "COLONY_SESSION": "lead"}
    run = subprocess.run([sys.executable, "-m", "colony", "post", "#41", "builder-2", "start this card"],
                         capture_output=True, text=True, cwd=host, env=env)
    assert run.returncode == 0, run.stderr
    assert run.stdout == "#41 for builder-2: start this card (from lead)\n"
    assert world.calls("gh") == [["issue", "comment", "41", "--repo", "owner/myapp",
                                  "--body", "for builder-2: start this card (from lead)"]]
    bad = subprocess.run([sys.executable, "-m", "colony", "post", "the next one", "lead", "hi"],
                         capture_output=True, text=True, cwd=host, env=env)
    assert bad.returncode == 2 and "is not a card number" in bad.stderr
    args = cli.build_parser().parse_args(["post", "41", "lead", "main is red", "--urgent"])
    assert (args.card, args.to, args.sentence, args.urgent, args.run) == (41, "lead", "main is red", True, wait.post)


@pytest.mark.parametrize("session, to, sentence, why", [
    ("", "lead", "hello", "set COLONY_SESSION"),
    ("builder-2", "builder-2", "hello", "another session's name"),
    ("builder-2", "the lead", "hello", "another session's name"),
    ("builder-2", "lead", "  ", "one sentence under 300 characters"),
    ("builder-2", "lead", "word " * 60, "one sentence under 300 characters"),
])
def test_post_needs_a_session_another_name_and_one_short_sentence(world, monkeypatch, session, to, sentence, why):
    monkeypatch.setenv("COLONY_SESSION", session)
    with pytest.raises(cli.ColonyError, match=why):
        wait.post(RELAY, Namespace(card=41, to=to, sentence=sentence, urgent=False))
    assert world.calls(PROBE) == [] and world.calls("gh") == []
