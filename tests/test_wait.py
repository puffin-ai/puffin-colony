"""Tests for `colony wait` and `colony say`, with a stand-in `gh` that plays back canned GitHub answers and a fake
clock, so a 10-minute digest runs in a moment."""
import json
import subprocess
import sys
import time
import types
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from conftest import stub_path
from colony import board, cli, cycle, transport, wait

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
          "people": {"logins": ["Ana-GH"]}}
DIGEST_LINE = "for lead: done, builder-1/7 pushed, 12 passed (from builder-1)"
BATCH = [99]  # a batch running on another card, so DIGEST_LINE's done waits for the digest


def comment(id, body, updated="2026-11-05T10:00:00Z", issue=7, login="ana-gh"):
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
            (self.bin / f"{kind}-{self.count:03}.txt").write_text(text, newline="")  # as written, \r\n too

    def calls(self) -> list[list[str]]:
        """Each call's arguments."""
        log = self.bin / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def polls(self) -> list[list[str]]:
        """The calls that read the comments."""
        return [call for call in self.calls() if call[:2] == ["api", "-i"]]


@pytest.fixture
def gh(tmp_path, monkeypatch):
    """A temporary HOME, the stand-in gh first on PATH, and Ana as the person. colony.cycle doesn't import, so the
    lead's wait runs no stale-card check unless a test gives it one."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH_STUB.replace("{python}", sys.executable))
    (bin_dir / "gh").chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", stub_path(bin_dir))
    monkeypatch.setenv("COLONY_PERSON", "ana")
    monkeypatch.setitem(sys.modules, "colony.cycle", None)
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
                 comment(4, "for ana-lead: note to self (from ana-lead)\nfor the record: nothing here")))
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
    env = {"HOME": str(tmp_path), "PATH": stub_path(gh.bin)}
    run = subprocess.run([sys.executable, "-m", "colony", "wait"], capture_output=True, text=True, cwd=host, env=env)
    assert run.returncode == 2
    assert "set COLONY_SESSION to this session's name" in run.stderr
    assert gh.calls() == []


# The quiet lead


def test_the_lead_gathers_lines_and_returns_them_at_the_digest(gh, capsys, monkeypatch):
    gh.answer(ok(comment(1, DIGEST_LINE),
                 comment(2, "for lead: which blue for the button? I'm going with the brand one (from builder-2)")))
    code, out, clock = run_as("lead", capsys, monkeypatch, waiting_on=BATCH)
    assert code == 0 and clock.t == 60 and clock.naps == [15] * 4
    assert out.splitlines() == [f"#7 {DIGEST_LINE}",
                                "#7 for lead: which blue for the button? I'm going with the brand one (from builder-2)"]


def test_a_digest_with_no_lines_waits_for_the_next_one(gh, capsys, monkeypatch):
    gh.answer(*[NOT_MODIFIED] * 5, ok(comment(1, DIGEST_LINE)))
    code, out, clock = run_as("lead", capsys, monkeypatch, waiting_on=BATCH)
    assert code == 0 and out == f"#7 {DIGEST_LINE}\n"
    assert clock.t == 120  # the line came at 75 seconds, after the first digest passed empty


def test_the_digest_is_ten_minutes_by_default(gh, capsys, monkeypatch):
    monkeypatch.setattr(wait, "INTERVAL", 60)
    gh.answer(ok(comment(1, DIGEST_LINE)))
    code, out, clock = run_as("lead", capsys, monkeypatch, config={"project": CONFIG["project"]}, waiting_on=BATCH)
    assert code == 0 and out == f"#7 {DIGEST_LINE}\n" and clock.t == 600


@pytest.mark.parametrize("kind", ["urgent", "blocked", "question", "URGENT "])
def test_an_urgent_blocked_or_question_line_returns_at_once(gh, capsys, monkeypatch, kind):
    line = f"for lead: {kind}: the base branch no longer builds (from builder-2)"
    gh.answer(ok(comment(1, DIGEST_LINE), comment(2, line, issue=8)))
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and clock.naps == []
    assert out.splitlines() == [f"#7 {DIGEST_LINE}", f"#8 {line}"]


@pytest.mark.parametrize("line, login, at_once", [
    ("for lead: ship the batch as it is", "sam-gh", True),
    ("for lead: ship the batch as it is (from ana-gh)", "ana-gh", True),
    ("for lead: ship the batch as it is (from builder-1)", "ana-gh", False),
    ("for lead: the form is in, and no question: left (from builder-1)", "ana-gh", False),
])
def test_a_persons_line_returns_at_once(gh, capsys, monkeypatch, line, login, at_once):
    gh.answer(ok(comment(1, line, login=login)))
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and out == f"#7 {line}\n"
    assert clock.naps == ([] if at_once else [15] * 4)


def test_a_done_line_returns_at_once_while_no_batch_runs(gh, capsys, monkeypatch):
    gh.answer(ok(comment(1, "for lead: done, builder-1/1300 pushed (from builder-1)", issue=1300)))
    code, out, clock = run_as("lead", capsys, monkeypatch, waiting_on=[])
    assert code == 0 and clock.naps == [] and out == "#1300 for lead: done, builder-1/1300 pushed (from builder-1)\n"


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
        run_as("lead", capsys, monkeypatch, waiting_on=BATCH, clock=Clock(most=2))
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
    ask = "for ana-lead: can your builders take the export card? (from sam-lead)"
    warn = "for ana-lead: urgent: I merge dev into main in 10 minutes (from sam-lead)"
    gh.answer(ok(comment(1, ask, issue=5, login="sam-gh"),
                 comment(2, "for sam-lead: yes, after lunch (from ana-lead)", issue=5)),
              ok(comment(3, warn, issue=5, login="sam-gh", updated="2026-11-05T10:01:00Z")))
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and clock.naps == [15]  # the question waited for the digest, the warning didn't
    assert out.splitlines() == [f"#5 {ask}", f"#5 {warn}"]


def waited(name):
    """A session that ran a wait on this computer, by the state file its wait leaves."""
    wait.write_json(wait.state_path("demo", name), {"since": "2026-11-05T09:00:00Z", "pending": []})


def test_the_lead_takes_a_line_for_its_helper_it_didnt_sign_as_redirected(gh, capsys, monkeypatch):
    waited("builder-1")
    waited("researcher")
    gh.answer(ok(comment(1, "for builder-1: start this card (from lead)\n"
                            "for builder-1: use my fixture (from builder-2)"),
                 comment(2, "for researcher: also check the EU rules", issue=9),
                 comment(3, "for builder-9: hi (from sam-lead)\nfor the record: nothing here", issue=9)))
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and clock.naps == []  # Ana's own line to a helper can't wait
    assert out.splitlines() == ["#7 redirected: for builder-1: use my fixture (from builder-2)",
                                "#9 redirected: for researcher: also check the EU rules"]


def test_a_redirected_line_from_another_session_waits_for_the_digest(gh, capsys, monkeypatch):
    waited("builder-1")
    gh.answer(ok(comment(1, "for builder-1: rebase on mine first (from builder-2)")))
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and clock.naps == [15] * 4
    assert out == "#7 redirected: for builder-1: rebase on mine first (from builder-2)\n"


def test_a_named_lead_redirects_only_its_own_helpers_lines_by_their_status(gh, capsys, monkeypatch):
    from colony import presence

    monkeypatch.setenv(wait.LEAD_ENV, "ana-engine-lead")
    waited("builder-2")  # a helper on this computer, of another lead by its status
    statuses = [comment(i, presence.body(presence.Status(name, "helper", "ana", lead, at=1.0)), issue=5)
                for i, (name, lead) in enumerate((("builder-1", "ana-engine-lead"), ("builder-2", "sam-web-lead")), 1)]
    gh.answer(ok(*statuses, comment(3, "for builder-1: start this card (from ana-engine-lead)\n"
                                       "for builder-1: start that card (from lead)\n"
                                       "for builder-2: use the new client (from builder-1)"),
                 comment(4, "for builder-1: urgent: stop, the API moved (from sam-web-lead)", issue=5)))
    me = wait.lead_session(CONFIG, "ana-engine-lead")
    assert me.helpers == frozenset()
    assert wait.wait("acme/demo", "demo", me, clock=Clock()) == 0
    assert capsys.readouterr().out == "#5 redirected: for builder-1: urgent: stop, the API moved (from sam-web-lead)\n"


def test_a_builders_wait_posts_the_outbox_at_each_poll(gh, capsys, monkeypatch):
    from colony import guards

    guards.write_outbox(CONFIG, [{"to": "lead", "line": "for lead: builder-1 stopped (from builder-1)", "at": 1.0}])
    gh.answer(ok(comment(1, "for builder-1: start this card (from lead)")))
    code, out, _ = run_as("builder-1", capsys, monkeypatch)
    assert code == 0
    assert ["issue", "comment", "5", "--repo", "acme/demo", "--body",
            "for lead: builder-1 stopped (from builder-1)"] in gh.calls()
    assert guards.read_outbox(CONFIG) == [] and not guards.outbox_path(CONFIG).exists()


def test_say_posts_a_line_for_another_lead_on_the_coordination_issue(gh, tmp_path):
    host = tmp_path / "host"
    (host / ".colony").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(host)], check=True)
    (host / ".colony" / "colony.toml").write_text(Path(str(resources.files("colony") / "colony.toml.example")).read_text())
    env = {"HOME": str(tmp_path), "PATH": stub_path(gh.bin), "COLONY_SESSION": "lead", "COLONY_PERSON": "Ana"}
    run = subprocess.run([sys.executable, "-m", "colony", "say", "sam-lead", "can you  review #12\nbefore noon?"],
                         capture_output=True, text=True, cwd=host, env=env)
    line = "for sam-lead: can you review #12 before noon? (from ana-lead)"
    assert run.returncode == 0, run.stderr
    assert run.stdout == f"#5 {line}\n"
    assert gh.calls()[-1] == ["issue", "comment", "5", "--repo", "owner/myapp", "--body", line]


@pytest.mark.parametrize("session, to, why", [
    ("builder-1", "sam-lead", "say is for leads"),
    ("lead", "sam", "another lead's name"),
    ("lead", "ana-lead", "another lead's name"),
])
def test_say_is_for_a_lead_and_names_another_lead(gh, monkeypatch, session, to, why):
    monkeypatch.setenv("COLONY_SESSION", session)
    with pytest.raises(cli.ColonyError, match=why):
        wait.say(CONFIG, Namespace(person=None, to=to, sentence="hello"))
    with pytest.raises(cli.ColonyError, match="under 300 characters"):
        monkeypatch.setenv("COLONY_SESSION", "lead")
        wait.say(CONFIG, Namespace(person=None, to="sam-lead", sentence="word " * 60))
    assert gh.calls() == []


def test_an_unknown_transport_stops_the_wait_and_say(gh, capsys, monkeypatch):
    pigeon = {**CONFIG, "messages": {"transport": "pigeon"}}
    with pytest.raises(cli.ColonyError, match="transport = 'pigeon' is gone"):
        run_as("lead", capsys, monkeypatch, config=pigeon)
    with pytest.raises(cli.ColonyError, match="'pigeon' is gone"):
        wait.say(pigeon, Namespace(person=None, to="sam-lead", sentence="hello"))
    assert gh.calls() == []


# Stale cards, from the cycle module


def stale_module(monkeypatch, stale_lines, minutes=10):
    """Stand in for colony.cycle with the given stale_lines and check interval."""
    cycle = types.SimpleNamespace(stale_lines=stale_lines, STALE_CHECK_MINUTES=minutes)
    monkeypatch.setitem(sys.modules, "colony.cycle", cycle)


def test_the_leads_wait_adds_each_stale_line_once(gh, capsys, monkeypatch):
    calls = []
    stale = "#41 for lead: stale: builder-2 has had no update on #41 for 3 hours"
    stale_module(monkeypatch, lambda config, now: calls.append((config, now)) or [stale], minutes=0)
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and out == f"{stale}\n" and clock.t == 60  # gathered at the start, printed at the digest
    assert len(calls) == 1 and calls[0][0] is CONFIG
    assert abs(datetime.now(timezone.utc) - calls[0][1]) < timedelta(minutes=1)
    gh.answer(*[NOT_MODIFIED] * 5, ok(comment(1, DIGEST_LINE)))
    code, out, clock = run_as("lead", capsys, monkeypatch, waiting_on=BATCH)
    assert code == 0 and out == f"#7 {DIGEST_LINE}\n"  # the same stale line never prints twice
    assert len(calls) == 3  # at the start of each wait, and at the digest that passed empty


def test_the_stale_check_runs_at_most_once_per_its_interval_across_waits(gh, capsys, monkeypatch):
    calls = []
    stale_module(monkeypatch, lambda config, now: calls.append(now) or [])
    for id in (1, 2):
        gh.answer(*[NOT_MODIFIED] * 5, ok(comment(id, "for lead: urgent: main is red (from builder-2)")))
        assert run_as("lead", capsys, monkeypatch)[0] == 0
    assert len(calls) == 1  # the second wait, and both digests that passed empty, came within 10 minutes


def test_a_builders_wait_runs_no_stale_check(gh, capsys, monkeypatch):
    stale_module(monkeypatch, lambda config, now: pytest.fail("a builder's wait checked for stale cards"))
    gh.answer(ok(comment(1, "for builder-1: start this card (from lead)")))
    code, out, _ = run_as("builder-1", capsys, monkeypatch)
    assert code == 0 and out == "#7 for builder-1: start this card (from lead)\n"


@pytest.mark.parametrize("cycle, err", [
    (None, ""),  # colony.cycle doesn't import: skipped quietly
    (types.SimpleNamespace(), ""),  # it imports, with no stale_lines yet
    (types.SimpleNamespace(stale_lines=lambda config, now: 1 / 0), "stale-card check failed, the wait tries again"),
])
def test_a_missing_or_failing_stale_check_never_stops_the_leads_wait(gh, capsys, monkeypatch, cycle, err):
    monkeypatch.setitem(sys.modules, "colony.cycle", cycle)
    monkeypatch.setenv("COLONY_SESSION", "lead")
    gh.answer(ok(comment(1, "for lead: urgent: main is red (from builder-2)")))
    assert wait.run(CONFIG, Namespace(person=None, waiting_on=None), clock=Clock()) == 0
    captured = capsys.readouterr()
    assert captured.out == "#7 for lead: urgent: main is red (from builder-2)\n"
    assert (err in captured.err) if err else captured.err == ""


@pytest.mark.parametrize("found, err", [
    (None, ""),  # no board yet: no stale lines, and nothing to say
    (cli.ColonyError("gh project list failed (the gh login needs the project scope)"),
     "stale-card check failed, the wait tries again in 10 minutes: gh project list failed"),
])
def test_the_real_cycles_stale_check_never_stops_the_leads_wait_on_a_missing_board(gh, capsys, monkeypatch, found,
                                                                                  err):
    def find_board(config):
        if isinstance(found, Exception):
            raise found
        return found

    monkeypatch.setitem(sys.modules, "colony.cycle", cycle)  # the real module, which the fixture hid
    monkeypatch.setattr(board, "find_board", find_board)
    monkeypatch.setenv("COLONY_SESSION", "lead")
    gh.answer(ok(comment(1, "for lead: urgent: main is red (from builder-2)")))
    assert wait.run(CONFIG, Namespace(person=None, waiting_on=None), clock=Clock()) == 0
    captured = capsys.readouterr()
    assert captured.out == "#7 for lead: urgent: main is red (from builder-2)\n"
    assert (err in captured.err) if err else captured.err == ""


# A helper opened with open or join that posts no status comment


def status_comment(id, name, updated):
    """A helper's status comment on the coordination issue, naming its lead."""
    from colony import presence

    body = presence.body(presence.Status(name, "helper", lead="ana-main-lead"))
    return comment(id, body, updated=updated, issue=5)


def test_a_helper_with_no_status_comment_after_5_minutes_is_raised_once(gh):
    opened_at = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc).timestamp()
    wait.expect_status("demo", "ana-main-lead", "builder-1", now=opened_at)
    wait.expect_status("demo", "ana-main-lead", "builder-2", now=opened_at)
    check, state = wait.silent_check("demo", "ana-main-lead"), {}
    assert check(state, now=opened_at + 299) == []
    # builder-2's status from before it was opened doesn't count; builder-1's after it does.
    wait.learn_helpers(state, [status_comment(1, "builder-1", "2026-11-05T10:01:00Z"),
                               status_comment(2, "builder-2", "2026-11-05T09:30:00Z")])
    assert check(state, now=opened_at + 360) == [
        "urgent: builder-2 was opened 6 minutes ago and has posted no status comment; look at its window, or open it "
        "again"]
    assert check(state, now=opened_at + 900) == []


def test_the_named_leads_wait_returns_at_once_on_a_silent_helper(gh, capsys, monkeypatch):
    from colony import presence

    monkeypatch.setenv("COLONY_LEAD", "ana-main-lead")
    monkeypatch.setattr(presence, "keeper", lambda *args, **kwargs: lambda: None)
    wait.expect_status("demo", "ana-main-lead", "builder-3", now=time.time() - 400)
    code, out, clock = run_as("lead", capsys, monkeypatch)
    assert code == 0 and clock.naps == []
    assert out == ("urgent: builder-3 was opened 6 minutes ago and has posted no status comment; look at its "
                   "window, or open it again\n")
