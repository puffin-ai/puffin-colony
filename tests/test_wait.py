"""Tests for `colony wait` and `colony say`, with a stand-in `gh` that plays back canned GitHub answers and a fake
clock, so a 10-minute digest runs in a moment."""
import json
import subprocess
import sys
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from colony import cli, wait

GH_STUB = """#!{python}
import json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
args = sys.argv[1:]
with open(here / "calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\\n")
kind = "poll" if args[:2] == ["api", "-i"] else "-".join(args[:2])
answers = sorted(here.glob(kind + "-*.txt"))
if answers:
    sys.stdout.write(answers[0].read_text())
    answers[0].unlink()
elif kind == "poll":
    sys.stdout.write('HTTP/2.0 304 Not Modified\\r\\nEtag: W/"e1"\\r\\n\\r\\n')
    sys.exit(1)
elif kind == "issue-list":
    sys.stdout.write('[{"number": 5, "title": "Colony: coordination"}]')
else:
    sys.stdout.write("https://github.com/acme/demo/issues/41\\n")
"""
NOT_MODIFIED = 'HTTP/2.0 304 Not Modified\r\nEtag: W/"e1"\r\n\r\n'
CONFIG = {"project": {"repo": "acme/demo", "name": "demo"}, "messages": {"lead_digest_minutes": 1},
          "people": {"logins": ["Serdar-GH"]}}
DIGEST_LINE = "for lead: done, builder-1/7 pushed, 12 passed (from builder-1)"


def comment(id, body, updated="2026-11-05T10:00:00Z", issue=7, login="serdar-gh"):
    """One issue comment as GitHub's REST API answers it. Agents post through their person's login."""
    return {"id": id, "issue_url": f"https://api.github.com/repos/acme/demo/issues/{issue}", "body": body,
            "updated_at": updated, "user": {"login": login}}


def ok(*comments, etag='W/"e1"'):
    """A 200 answer as `gh api -i` prints it."""
    return f"HTTP/2.0 200 OK\r\nContent-Type: application/json\r\nEtag: {etag}\r\n\r\n{json.dumps(list(comments))}"


class Gh:
    """The stand-in gh: queue answers per kind of call, then read the calls the wait made."""

    def __init__(self, bin_dir: Path):
        self.bin = bin_dir
        self.count = 0

    def answer(self, *texts: str, kind: str = "poll") -> None:
        """Queue the next answers to `gh api -i` (kind poll) or to another call, such as issue-list, in order."""
        for text in texts:
            self.count += 1
            (self.bin / f"{kind}-{self.count:03}.txt").write_text(text)

    def calls(self) -> list[list[str]]:
        """Each call's arguments."""
        log = self.bin / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def polls(self) -> list[list[str]]:
        """The calls that read the comments."""
        return [call for call in self.calls() if call[:2] == ["api", "-i"]]


@pytest.fixture
def gh(tmp_path, monkeypatch):
    """A temporary HOME, the stand-in gh first on PATH, and Serdar as the person."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH_STUB.replace("{python}", sys.executable))
    (bin_dir / "gh").chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("COLONY_PERSON", "serdar")
    return Gh(bin_dir)


class Clock:
    """A fake clock: a nap moves it on at once, and a wait that would never end stops the test."""

    def __init__(self, most: int = 50):
        self.t, self.naps, self.most = 0.0, [], most

    def now(self) -> float:
        """The fake time, in seconds from the start."""
        return self.t

    def sleep(self, seconds: float) -> None:
        """Record the nap and move the clock on."""
        self.naps.append(seconds)
        self.t += seconds
        if len(self.naps) > self.most:
            raise AssertionError("the wait never ended")


def run_as(session, capsys, monkeypatch, config=CONFIG, waiting_on=None, clock=None):
    """Run `colony wait` as `session` on acme/demo, and return its exit code, output and clock."""
    monkeypatch.setenv("COLONY_SESSION", session)
    clock = clock or Clock()
    code = wait.run(config, Namespace(person=None, waiting_on=waiting_on), clock=clock)
    return code, capsys.readouterr().out, clock


def test_a_builder_takes_only_lines_for_it_that_the_lead_signed(gh, capsys, monkeypatch):
    gh.answer(ok(comment(1, "for builder-1: can you look? (from builder-2)\nfor builder-2: start this card (from lead)"),
                 comment(2, "for builder-1: start this card (from lead)", issue=12)))
    code, out, clock = run_as("builder-1", capsys, monkeypatch)
    assert code == 0 and clock.naps == []
    assert out == "#12 for builder-1: start this card (from lead)\n"
    assert gh.calls() == gh.polls()  # a builder never looks for the coordination issue


def test_the_lead_takes_every_line_for_it_but_its_own(gh, capsys, monkeypatch):
    gh.answer(ok(comment(1, "- **for lead: done, builder-1/7 pushed, 12 passed (from builder-1)**"),
                 comment(2, "For Lead: yes, merge it"),
                 comment(3, "for lead: note to self (from lead)\nfor builder-1: start this card (from lead)"),
                 comment(4, "for serdar-lead: note to self (from serdar-lead)\nfor the record: nothing here")))
    code, out, _ = run_as("lead", capsys, monkeypatch)
    assert code == 0
    assert out.splitlines() == ["#7 for lead: done, builder-1/7 pushed, 12 passed (from builder-1)",
                                "#7 For Lead: yes, merge it"]


def test_a_quiet_poll_sends_the_last_etag_and_sleeps(gh, capsys, monkeypatch):
    gh.answer(ok(comment(1, "for builder-2: start this card (from lead)"), etag='W/"e1"'), NOT_MODIFIED,
              ok(comment(1, "for builder-2: start this card (from lead)"),
                 comment(2, "for builder-1: start this card (from lead)", updated="2026-11-05T10:05:00Z"), etag='W/"e2"'))
    code, out, clock = run_as("builder-1", capsys, monkeypatch)
    calls = gh.calls()
    assert code == 0 and out == "#7 for builder-1: start this card (from lead)\n"
    assert clock.naps == [15, 15]
    assert "If-None-Match" not in " ".join(calls[0])
    assert calls[1][:4] == ["api", "-i", "-H", 'If-None-Match: W/"e1"']
    assert calls[2][:4] == ["api", "-i", "-H", 'If-None-Match: W/"e1"']


def test_the_first_wait_reads_the_last_hour(gh, capsys, monkeypatch):
    gh.answer(ok(comment(1, "for builder-1: start this card (from lead)")))
    run_as("builder-1", capsys, monkeypatch)
    query = parse_qs(urlsplit(gh.calls()[0][-1]).query)
    since = datetime.strptime(query["since"][0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert abs(datetime.now(timezone.utc) - timedelta(hours=1) - since) < timedelta(minutes=1)
    assert gh.calls()[0][-1].startswith("repos/acme/demo/issues/comments?since=")


def test_a_printed_line_never_prints_again_and_the_state_lives_in_home(gh, capsys, monkeypatch, tmp_path):
    gh.answer(ok(comment(1, "for builder-1: start this card (from lead)", updated="2026-11-05T10:00:00Z")))
    run_as("builder-1", capsys, monkeypatch)
    state_file = tmp_path / ".colony" / "demo" / "builder-1.json"
    assert json.loads(state_file.read_text())["since"] == "2026-11-05T10:00:00Z"
    gh.answer(ok(comment(1, "for builder-1: start this card (from lead)", updated="2026-11-05T10:00:00Z"),
                 comment(2, "for builder-1: take #9 next (from lead)", updated="2026-11-05T10:09:00Z", issue=9)))
    code, out, _ = run_as("builder-1", capsys, monkeypatch)
    assert code == 0 and out == "#9 for builder-1: take #9 next (from lead)\n"
    assert "since=2026-11-05T10:00:00Z&" in gh.calls()[1][-1]


def test_a_full_page_reads_on_without_sleeping(gh, capsys, monkeypatch):
    monkeypatch.setattr(wait, "PAGE", 2)
    gh.answer(ok(comment(1, "unrelated"), comment(2, "also unrelated", updated="2026-11-05T10:01:00Z")),
              ok(comment(3, "for builder-1: start this card (from lead)", updated="2026-11-05T10:02:00Z")))
    code, out, clock = run_as("builder-1", capsys, monkeypatch)
    assert code == 0 and clock.naps == []
    assert "since=2026-11-05T10:01:00Z&" in gh.calls()[1][-1]


def test_lasting_failures_end_the_wait_with_the_reason(gh, capsys, monkeypatch):
    monkeypatch.setattr(wait, "GIVE_UP", 2)
    gh.answer("HTTP/2.0 401 Unauthorized\r\n\r\n{}", "HTTP/2.0 401 Unauthorized\r\n\r\n{}")
    clock = Clock()
    assert wait.wait("acme/demo", "demo", wait.Session("lead", frozenset({"lead"})), clock=clock) == 1
    assert "GitHub answered 401 (run: gh auth login)" in capsys.readouterr().err
    assert clock.naps == [15]


def test_the_command_needs_a_session_name(gh, tmp_path):
    host = tmp_path / "host"
    (host / ".colony").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(host)], check=True)
    (host / ".colony" / "colony.toml").write_text(Path(str(resources.files("colony") / "colony.toml.example")).read_text())
    env = {"HOME": str(tmp_path), "PATH": f"{gh.bin}:/usr/bin:/bin"}
    run = subprocess.run([sys.executable, "-m", "colony", "wait"], capture_output=True, text=True, cwd=host, env=env)
    assert run.returncode == 2
    assert "set COLONY_SESSION to this session's name" in run.stderr
    assert gh.calls() == []


# The quiet lead


def test_the_lead_gathers_lines_and_returns_them_at_the_digest(gh, capsys, monkeypatch):
    gh.answer(ok(comment(1, DIGEST_LINE),
                 comment(2, "for lead: which blue for the button? I'm going with the brand one (from builder-2)")))
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and clock.t == 60 and clock.naps == [15] * 4
    assert out.splitlines() == [f"#7 {DIGEST_LINE}",
                                "#7 for lead: which blue for the button? I'm going with the brand one (from builder-2)"]


def test_a_digest_with_no_lines_waits_for_the_next_one(gh, capsys, monkeypatch):
    gh.answer(*[NOT_MODIFIED] * 5, ok(comment(1, DIGEST_LINE)))
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and out == f"#7 {DIGEST_LINE}\n"
    assert clock.t == 120  # the line came at 75 seconds, after the first digest passed empty


def test_the_digest_is_ten_minutes_by_default(gh, capsys, monkeypatch):
    monkeypatch.setattr(wait, "INTERVAL", 60)
    gh.answer(ok(comment(1, DIGEST_LINE)))
    code, out, clock = run_as("lead", capsys, monkeypatch, config={"project": CONFIG["project"]})
    assert code == 0 and out == f"#7 {DIGEST_LINE}\n" and clock.t == 600


@pytest.mark.parametrize("kind", ["urgent", "blocked", "question", "URGENT "])
def test_an_urgent_blocked_or_question_line_returns_at_once(gh, capsys, monkeypatch, kind):
    line = f"for lead: {kind}: the base branch no longer builds (from builder-2)"
    gh.answer(ok(comment(1, DIGEST_LINE), comment(2, line, issue=8)))
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and clock.naps == []
    assert out.splitlines() == [f"#7 {DIGEST_LINE}", f"#8 {line}"]


@pytest.mark.parametrize("line, login, at_once", [
    ("for lead: ship the batch as it is", "burak-gh", True),
    ("for lead: ship the batch as it is (from serdar-gh)", "serdar-gh", True),
    ("for lead: ship the batch as it is (from builder-1)", "serdar-gh", False),
    ("for lead: done, and no question: left (from builder-1)", "serdar-gh", False),
])
def test_a_persons_line_returns_at_once(gh, capsys, monkeypatch, line, login, at_once):
    gh.answer(ok(comment(1, line, login=login)))
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and out == f"#7 {line}\n"
    assert clock.naps == ([] if at_once else [15] * 4)


def test_a_done_line_returns_at_once_for_a_card_the_batch_waits_on(gh, capsys, monkeypatch, tmp_path):
    gh.answer(ok(comment(1, "for lead: done, builder-1/1251 pushed (from builder-1)", issue=1251)))
    code, out, clock = run_as("lead", capsys, monkeypatch, waiting_on=[1251, 1252])
    assert code == 0 and clock.naps == [] and out == "#1251 for lead: done, builder-1/1251 pushed (from builder-1)\n"
    assert json.loads((tmp_path / ".colony" / "demo" / "lead-waiting.json").read_text()) == [1251, 1252]
    # The list stays for the next wait, and a done line on another card waits for the digest.
    gh.answer(ok(comment(2, "for lead: done, builder-2/1300 pushed (from builder-2)", issue=1300,
                         updated="2026-11-05T10:01:00Z")))
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and clock.naps == [15] * 4
    gh.answer(ok(comment(3, "for lead: done again, builder-2/1252 pushed (from builder-2)", issue=1252,
                         updated="2026-11-05T10:02:00Z")))
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and clock.naps == []


def test_waiting_on_takes_card_numbers_and_is_for_the_lead(gh, capsys, monkeypatch):
    assert cli.build_parser().parse_args(["wait", "--waiting-on", "1251, #1252"]).waiting_on == [1251, 1252]
    assert cli.build_parser().parse_args(["wait", "--waiting-on", ""]).waiting_on == []
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["wait", "--waiting-on", "the next one"])
    with pytest.raises(cli.ColonyError, match="for the lead"):
        run_as("builder-1", capsys, monkeypatch, waiting_on=[1251])


def test_gathered_lines_outlive_a_wait_that_ended(gh, capsys, monkeypatch):
    gh.answer(ok(comment(1, DIGEST_LINE)))
    with pytest.raises(AssertionError, match="never ended"):
        run_as("lead", capsys, monkeypatch, clock=Clock(most=2))
    gh.answer(ok(comment(2, "for lead: urgent: main is red (from builder-2)", updated="2026-11-05T10:01:00Z")))
    code, out, _ = run_as("lead", capsys, monkeypatch)
    assert code == 0 and out.splitlines() == [f"#7 {DIGEST_LINE}", "#7 for lead: urgent: main is red (from builder-2)"]


# Lead to lead


def test_the_lead_finds_the_coordination_issue_by_title_once(gh, capsys, monkeypatch, tmp_path):
    gh.answer(json.dumps([{"number": 9, "title": "Colony: coordination notes"},
                          {"number": 3, "title": "Colony: coordination"}]), kind="issue-list")
    gh.answer(ok(comment(1, "for lead: yes")), ok(comment(2, "for lead: and this", updated="2026-11-05T10:01:00Z")))
    run_as("lead", capsys, monkeypatch)
    run_as("lead", capsys, monkeypatch)
    calls = [call[:2] for call in gh.calls() if call not in gh.polls()]
    assert calls == [["issue", "list"]]
    assert '"Colony: coordination" in:title' in gh.calls()[0]
    assert json.loads((tmp_path / ".colony" / "demo" / "lead-coordination.json").read_text()) == 3


def test_the_lead_creates_the_coordination_issue_on_first_use(gh, capsys, monkeypatch, tmp_path):
    gh.answer("[]", kind="issue-list")
    gh.answer(ok(comment(1, "for lead: yes")))
    run_as("lead", capsys, monkeypatch)
    create = [call for call in gh.calls() if call[:2] == ["issue", "create"]]
    assert len(create) == 1 and create[0][create[0].index("--title") + 1] == "Colony: coordination"
    assert json.loads((tmp_path / ".colony" / "demo" / "lead-coordination.json").read_text()) == 41


def test_the_lead_takes_lead_to_lead_lines_by_the_same_rules(gh, capsys, monkeypatch):
    ask = "for serdar-lead: can your builders take the export card? (from burak-lead)"
    warn = "for serdar-lead: urgent: I merge dev into main in 10 minutes (from burak-lead)"
    gh.answer(ok(comment(1, ask, issue=5, login="burak-gh"),
                 comment(2, "for burak-lead: yes, after lunch (from serdar-lead)", issue=5)),
              ok(comment(3, warn, issue=5, login="burak-gh", updated="2026-11-05T10:01:00Z")))
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and clock.naps == [15]  # the question waited for the digest, the warning didn't
    assert out.splitlines() == [f"#5 {ask}", f"#5 {warn}"]


def test_say_posts_a_line_for_another_lead_on_the_coordination_issue(gh, tmp_path):
    host = tmp_path / "host"
    (host / ".colony").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(host)], check=True)
    (host / ".colony" / "colony.toml").write_text(Path(str(resources.files("colony") / "colony.toml.example")).read_text())
    env = {"HOME": str(tmp_path), "PATH": f"{gh.bin}:/usr/bin:/bin", "COLONY_SESSION": "lead", "COLONY_PERSON": "Serdar"}
    run = subprocess.run([sys.executable, "-m", "colony", "say", "burak-lead", "can you  review #12\nbefore noon?"],
                         capture_output=True, text=True, cwd=host, env=env)
    line = "for burak-lead: can you review #12 before noon? (from serdar-lead)"
    assert run.returncode == 0, run.stderr
    assert run.stdout == f"#5 {line}\n"
    assert gh.calls()[-1] == ["issue", "comment", "5", "--repo", "owner/myapp", "--body", line]


@pytest.mark.parametrize("session, to, why", [
    ("builder-1", "burak-lead", "say is for leads"),
    ("lead", "burak", "another lead's name"),
    ("lead", "serdar-lead", "another lead's name"),
])
def test_say_is_for_a_lead_and_names_another_lead(gh, monkeypatch, session, to, why):
    monkeypatch.setenv("COLONY_SESSION", session)
    with pytest.raises(cli.ColonyError, match=why):
        wait.say(CONFIG, Namespace(person=None, to=to, sentence="hello"))
    with pytest.raises(cli.ColonyError, match="under 300 characters"):
        monkeypatch.setenv("COLONY_SESSION", "lead")
        wait.say(CONFIG, Namespace(person=None, to="burak-lead", sentence="word " * 60))
    assert gh.calls() == []


def test_the_relay_transport_is_not_built_yet(gh, capsys, monkeypatch):
    relay = {**CONFIG, "messages": {"transport": "relay"}}
    with pytest.raises(cli.ColonyError, match='"relay" \\(Agent Relay\\) is not built yet'):
        run_as("lead", capsys, monkeypatch, config=relay)
    with pytest.raises(cli.ColonyError, match="not built yet"):
        wait.say(relay, Namespace(person=None, to="burak-lead", sentence="hello"))
    assert gh.calls() == []
