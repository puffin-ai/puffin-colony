"""Tests for `colony wait`, with a stand-in `gh` that plays back canned GitHub answers."""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from colony import wait

GH_STUB = """#!{python}
import json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
with open(here / "calls.jsonl", "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
answers = sorted(here.glob("answer-*.txt"))
if answers:
    sys.stdout.write(answers[0].read_text())
    answers[0].unlink()
else:
    sys.stdout.write('HTTP/2.0 304 Not Modified\\r\\nEtag: W/"e1"\\r\\n\\r\\n')
    sys.exit(1)
"""
NOT_MODIFIED = 'HTTP/2.0 304 Not Modified\r\nEtag: W/"e1"\r\n\r\n'


def comment(id, body, updated="2026-11-05T10:00:00Z", issue=7):
    """One issue comment as GitHub's REST API answers it."""
    return {"id": id, "issue_url": f"https://api.github.com/repos/acme/demo/issues/{issue}", "body": body,
            "updated_at": updated}


def ok(*comments, etag='W/"e1"'):
    """A 200 answer as `gh api -i` prints it."""
    return f"HTTP/2.0 200 OK\r\nContent-Type: application/json\r\nEtag: {etag}\r\n\r\n{json.dumps(list(comments))}"


class Gh:
    """The stand-in gh: queue answers, then read the calls the wait made."""

    def __init__(self, bin_dir: Path):
        self.bin = bin_dir
        self.count = 0

    def answer(self, *texts: str) -> None:
        """Queue the next answers, in order."""
        for text in texts:
            self.count += 1
            (self.bin / f"answer-{self.count:03}.txt").write_text(text)

    def calls(self) -> list[list[str]]:
        """Each call's arguments."""
        log = self.bin / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


@pytest.fixture
def gh(tmp_path, monkeypatch):
    """A temporary HOME, and the stand-in gh first on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH_STUB.replace("{python}", sys.executable))
    (bin_dir / "gh").chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return Gh(bin_dir)


class Naps(list):
    """A stand-in sleep that records each nap and stops a wait that would never end."""

    def __call__(self, seconds):
        self.append(seconds)
        if len(self) > 5:
            raise AssertionError("the wait never ended")


def run_wait(me, capsys):
    """Run one wait as session `me` on acme/demo, and return its exit code, output and naps."""
    naps = Naps()
    code = wait.wait("acme/demo", "demo", me, interval=0, sleep=naps)
    out = capsys.readouterr()
    return code, out.out, naps


def test_a_builder_takes_only_lines_for_it_that_the_lead_signed(gh, capsys):
    gh.answer(ok(comment(1, "for builder-1: can you look? (from builder-2)\nfor builder-2: start this card (from lead)"),
                 comment(2, "for builder-1: start this card (from lead)", issue=12)))
    code, out, _ = run_wait("builder-1", capsys)
    assert code == 0
    assert out == "#12 for builder-1: start this card (from lead)\n"


def test_the_lead_takes_every_line_for_it_but_its_own(gh, capsys):
    gh.answer(ok(comment(1, "- **for lead: done, builder-1/7 pushed, 12 passed (from builder-1)**"),
                 comment(2, "For Lead: yes, merge it"),
                 comment(3, "for lead: note to self (from lead)\nfor builder-1: start this card (from lead)"),
                 comment(4, "for the record: nothing here")))
    code, out, _ = run_wait("lead", capsys)
    assert code == 0
    assert out.splitlines() == ["#7 for lead: done, builder-1/7 pushed, 12 passed (from builder-1)",
                                "#7 For Lead: yes, merge it"]


def test_a_quiet_poll_sends_the_last_etag_and_sleeps(gh, capsys):
    gh.answer(ok(comment(1, "for builder-2: start this card (from lead)"), etag='W/"e1"'), NOT_MODIFIED,
              ok(comment(1, "for builder-2: start this card (from lead)"),
                 comment(2, "for builder-1: start this card (from lead)", updated="2026-11-05T10:05:00Z"), etag='W/"e2"'))
    code, out, naps = run_wait("builder-1", capsys)
    calls = gh.calls()
    assert code == 0 and out == "#7 for builder-1: start this card (from lead)\n"
    assert naps == [0, 0]
    assert "If-None-Match" not in " ".join(calls[0])
    assert calls[1][:4] == ["api", "-i", "-H", 'If-None-Match: W/"e1"']
    assert calls[2][:4] == ["api", "-i", "-H", 'If-None-Match: W/"e1"']


def test_the_first_wait_reads_the_last_hour(gh, capsys):
    gh.answer(ok(comment(1, "for builder-1: start this card (from lead)")))
    run_wait("builder-1", capsys)
    query = parse_qs(urlsplit(gh.calls()[0][-1]).query)
    since = datetime.strptime(query["since"][0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert abs(datetime.now(timezone.utc) - timedelta(hours=1) - since) < timedelta(minutes=1)
    assert gh.calls()[0][-1].startswith("repos/acme/demo/issues/comments?since=")


def test_a_printed_line_never_prints_again_and_the_state_lives_in_home(gh, capsys, tmp_path):
    gh.answer(ok(comment(1, "for builder-1: start this card (from lead)", updated="2026-11-05T10:00:00Z")))
    run_wait("builder-1", capsys)
    state_file = tmp_path / ".colony" / "demo" / "builder-1.json"
    assert json.loads(state_file.read_text())["since"] == "2026-11-05T10:00:00Z"
    gh.answer(ok(comment(1, "for builder-1: start this card (from lead)", updated="2026-11-05T10:00:00Z"),
                 comment(2, "for builder-1: take #9 next (from lead)", updated="2026-11-05T10:09:00Z", issue=9)))
    code, out, _ = run_wait("builder-1", capsys)
    assert code == 0 and out == "#9 for builder-1: take #9 next (from lead)\n"
    assert "since=2026-11-05T10:00:00Z&" in gh.calls()[1][-1]


def test_a_full_page_reads_on_without_sleeping(gh, capsys, monkeypatch):
    monkeypatch.setattr(wait, "PAGE", 2)
    gh.answer(ok(comment(1, "unrelated"), comment(2, "also unrelated", updated="2026-11-05T10:01:00Z")),
              ok(comment(3, "for lead: done (from builder-1)", updated="2026-11-05T10:02:00Z")))
    code, out, naps = run_wait("lead", capsys)
    assert code == 0 and naps == []
    assert "since=2026-11-05T10:01:00Z&" in gh.calls()[1][-1]


def test_lasting_failures_end_the_wait_with_the_reason(gh, capsys, monkeypatch):
    monkeypatch.setattr(wait, "GIVE_UP", 2)
    gh.answer("HTTP/2.0 401 Unauthorized\r\n\r\n{}", "HTTP/2.0 401 Unauthorized\r\n\r\n{}")
    naps = Naps()
    assert wait.wait("acme/demo", "demo", "lead", interval=0, sleep=naps) == 1
    assert "GitHub answered 401 (run: gh auth login)" in capsys.readouterr().err
    assert naps == [0]


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
