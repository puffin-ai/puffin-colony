"""Tests for colony/transport.py: a stand-in `gh` on PATH logs its calls, so nothing reaches GitHub. Every line goes
as an issue comment, and `transport.send` is the one place that posts it."""
import json
import subprocess
import sys
from argparse import Namespace
from importlib import resources
from pathlib import Path

import pytest

from conftest import stub_path
from colony import cli, transport, wait

STUB = """#!{python}
import json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
with open(here / "calls.jsonl", "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
sys.stdout.write("https://github.com/acme/demo/issues/12#issuecomment-1\\n")
"""
GITHUB = {"project": {"repo": "acme/demo", "name": "demo"}}


@pytest.fixture
def gh(tmp_path, monkeypatch):
    """A temporary HOME and the stand-in gh first on PATH; returns a reader of the calls it got."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(STUB.replace("{python}", sys.executable))
    (bin_dir / "gh").chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", stub_path(bin_dir))
    monkeypatch.setenv("COLONY_PERSON", "ana")
    log = bin_dir / "calls.jsonl"
    return lambda: [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_a_line_goes_as_one_comment_on_its_card(gh):
    assert transport.send(GITHUB, "lead", "for lead: done, b/1 pushed (from builder-1)", card=12) == 12
    assert gh() == [["issue", "comment", "12", "--repo", "acme/demo", "--body",
                     "for lead: done, b/1 pushed (from builder-1)"]]


@pytest.mark.parametrize("value", ["relay", "carrier-pigeon"])
def test_a_transport_other_than_github_is_refused_with_how_to_fix_it(gh, value):
    with pytest.raises(cli.ColonyError, match=f"transport = '{value}' is gone: every line goes by GitHub now"):
        transport.send({**GITHUB, "messages": {"transport": value}}, "lead", "for lead: done (from b)", card=12)
    assert gh() == []


def test_an_older_configs_github_transport_line_still_works(gh):
    transport.send({**GITHUB, "messages": {"transport": "github"}}, "lead", "for lead: done (from b)", card=12)
    assert len(gh()) == 1


@pytest.mark.parametrize("line, why", [
    ("for builder-1: use ghp_abcdefghijklmnopqrstuvwxyz0123456789 (from lead)", "a token"),
    ("for builder-1: the key is s3cr3t-value-0123456789 (from lead)", "the value of $DEMO_API_KEY"),
])
def test_a_line_never_carries_a_secret(gh, monkeypatch, line, why):
    monkeypatch.setenv("DEMO_API_KEY", "s3cr3t-value-0123456789")
    with pytest.raises(cli.ColonyError, match="never carries a secret") as raised:
        transport.send(GITHUB, "builder-1", line, card=12)
    assert why in str(raised.value) and "s3cr3t" not in str(raised.value)
    assert gh() == []


# colony post: every card line, from builders and the lead


@pytest.mark.parametrize("session, to, sentence, urgent, line", [
    ("builder-2", "lead", "blocked: the test database won't start", False,
     "for lead: blocked: the test database won't start (from builder-2)"),
    ("builder-2", "Lead", "main is  red", True, "for lead: urgent: main is red (from builder-2)"),
    ("lead", "builder-2", "start: this card", False, "for builder-2: start: this card (from lead)"),
    ("builder-2", "lead", "done, builder-2/41 pushed, 12 passed", False,
     "for lead: done, builder-2/41 pushed, 12 passed (from builder-2)"),
])
def test_post_sends_a_card_line_as_a_comment(gh, monkeypatch, capsys, session, to, sentence, urgent, line):
    from colony import board

    monkeypatch.setattr(board, "set_fields", lambda config, card, pairs: pairs)  # a done's board move, tested below
    monkeypatch.setenv("COLONY_SESSION", session)
    assert wait.post(GITHUB, Namespace(card=41, to=to, sentence=sentence, urgent=urgent)) == 0
    assert capsys.readouterr().out == f"#41 {line}\n"
    assert gh() == [["issue", "comment", "41", "--repo", "acme/demo", "--body", line]]


def test_post_is_a_command_on_the_command_line(gh, tmp_path):
    host = tmp_path / "host"
    (host / ".colony").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(host)], check=True)
    (host / ".colony" / "colony.toml").write_text(Path(str(resources.files("colony") / "colony.toml.example")).read_text())
    env = {"HOME": str(tmp_path), "PATH": stub_path(tmp_path / 'bin'), "COLONY_SESSION": "builder-2"}
    run = subprocess.run([sys.executable, "-m", "colony", "post", "#41", "lead", "done, builder-2/41 pushed"],
                         capture_output=True, text=True, cwd=host, env=env)
    assert run.returncode == 0, run.stderr
    assert run.stdout == "#41 for lead: done, builder-2/41 pushed (from builder-2)\n"
    # The comment goes first; then the done line looks for the board to move the card to In review.
    assert gh()[0] == ["issue", "comment", "41", "--repo", "owner/myapp",
                       "--body", "for lead: done, builder-2/41 pushed (from builder-2)"]
    assert gh()[1][:2] == ["project", "list"]
    bad = subprocess.run([sys.executable, "-m", "colony", "post", "the next one", "lead", "hi"],
                         capture_output=True, text=True, cwd=host, env=env)
    assert bad.returncode == 2 and "another session's name" in bad.stderr
    args = cli.build_parser().parse_args(["post", "41", "lead", "main is red", "--urgent"])
    assert (args.card, args.to, args.sentence, args.urgent, args.run) == (41, "lead", "main is red", True, wait.post)


def test_the_limit_counts_the_sentence_alone_not_the_lines_wrapper(gh, monkeypatch):
    monkeypatch.setenv("COLONY_SESSION", "lead")
    sentence = "start: " + "x" * 293  # 300 characters, and the line around it is longer
    assert wait.post(GITHUB, Namespace(card=41, to="builder-2", sentence=sentence, urgent=False)) == 0
    with pytest.raises(cli.ColonyError, match="this one has 301, so cut 1"):
        wait.post(GITHUB, Namespace(card=41, to="builder-2", sentence=sentence + "y", urgent=False))
    assert len(gh()) == 1


def test_a_lead_may_tell_its_helper_to_stop(gh, monkeypatch):
    monkeypatch.setenv("COLONY_SESSION", "lead")
    assert wait.post(GITHUB, Namespace(card=41, to="builder-2", sentence="stop: drop T84, verify takes it",
                                       urgent=False)) == 0


def test_several_sentences_go_out_as_one_comment_or_not_at_all(gh, monkeypatch, capsys):
    monkeypatch.setenv("COLONY_SESSION", "lead")
    args = cli.build_parser().parse_args(["post", "41", "builder-2", "start: the ops page", "answer: use one table"])
    assert wait.post(GITHUB, args) == 0
    body = gh()[0][-1]
    assert body == "for builder-2: start: the ops page (from lead)\nfor builder-2: answer: use one table (from lead)"
    helper = wait.Session("builder-2", frozenset({"builder-2"}), leads=frozenset({"lead"}))
    assert len(wait.taken(body, helper, "41")) == 2
    too_long = cli.build_parser().parse_args(["post", "41", "builder-2", "start: a", "answer: " + "x" * 300])
    with pytest.raises(cli.ColonyError, match="so cut"):
        wait.post(GITHUB, too_long)
    assert len(gh()) == 1  # nothing of the second post went out


def test_post_reads_a_card_number_only_when_the_first_word_is_one():
    parse = cli.build_parser().parse_args
    assert (parse(["post", "staff", "start: a", "answer: b"]).card, parse(["post", "staff", "start: a"]).to) == (None, "staff")
    assert parse(["post", "staff", "start: a", "answer: b"]).sentence == ["start: a", "answer: b"]
    assert parse(["post", "#41", "lead", "done"]).card == 41
    assert parse(["say", "sam-lead", "one", "two"]).sentence == ["one", "two"]


@pytest.mark.parametrize("session, to, sentence, why", [
    ("", "lead", "hello", "set COLONY_SESSION"),
    ("builder-2", "builder-2", "hello", "another session's name"),
    ("builder-2", "the lead", "hello", "another session's name"),
    ("builder-2", "lead", "  ", "a line holds one sentence, and this one is empty"),
    ("builder-2", "lead", "word " * 61, "at most 300 characters"),
])
def test_post_needs_a_session_another_name_and_one_short_sentence(gh, monkeypatch, session, to, sentence, why):
    monkeypatch.setenv("COLONY_SESSION", session)
    with pytest.raises(cli.ColonyError, match=why):
        wait.post(GITHUB, Namespace(card=41, to=to, sentence=sentence, urgent=False))
    assert gh() == []


@pytest.mark.parametrize("session, sentence, features, moved", [
    ("builder-2", "done, builder-2/41 pushed", {}, [(41, [("Status", "In review")])]),
    ("builder-2", "question: keep 30 s? I'm going with yes", {}, []),
    ("lead", "urgent: stop this card", {}, []),
    ("builder-2", "done, builder-2/41 pushed", {"features": {"board": False}}, []),
])
def test_a_helpers_done_moves_its_card_to_in_review(gh, monkeypatch, session, sentence, features, moved):
    from colony import board

    calls = []
    monkeypatch.setattr(board, "set_fields", lambda config, card, pairs: calls.append((card, pairs)) or pairs)
    monkeypatch.setenv("COLONY_SESSION", session)
    to = "builder-2" if session == "lead" else "lead"
    assert wait.post({**GITHUB, **features}, Namespace(card=41, to=to, sentence=sentence, urgent=False)) == 0
    assert calls == moved and len(gh()) == 1


def test_a_board_that_fails_leaves_the_done_line_sent(gh, monkeypatch, capsys):
    from colony import board

    def refuse(config, card, pairs):
        raise cli.ColonyError("this repo has no board yet")

    monkeypatch.setattr(board, "set_fields", refuse)
    monkeypatch.setenv("COLONY_SESSION", "builder-2")
    assert wait.post(GITHUB, Namespace(card=41, to="lead", sentence="done, pushed", urgent=False)) == 0
    assert gh()[0][:3] == ["issue", "comment", "41"]
    assert "#41 stays as it was on the board: this repo has no board yet" in capsys.readouterr().err
