"""Tests for `colony plain`: the check that finds internal shorthand in a message to the person, the plain status
templates, and the command's actions and exit codes."""
import io
import sys
from argparse import Namespace

import pytest

from colony import cli, plain


def kinds(text: str, config: dict | None = None) -> list[tuple[str, str]]:
    """Each finding in the text, as (words, kind)."""
    return [(f.words, f.kind) for f in plain.findings(text, config)]


def check(text=(), file=None) -> int:
    return plain.run({}, Namespace(action="check", text=list(text), file=file))


# Each kind of finding


def test_an_arrow_is_found():
    assert kinds("The fix -> done.") == [("->", "an arrow")]
    assert kinds("Build → test.") == [("→", "an arrow")]


def test_a_chat_abbreviation_is_found():
    assert kinds("Done w/ the change, fyi.") == [("w/", "a chat abbreviation"), ("fyi", "a chat abbreviation")]


def test_an_internal_word_is_found():
    assert kinds("The worktree is clean.") == [("worktree", "an internal word")]


def test_an_internal_word_in_capitals_is_found_only_in_capitals():
    assert kinds("Moved HEAD to the fix.") == [("HEAD", "an internal word")]
    assert kinds("The head of the team agreed.") == []


def test_a_helpers_name_is_found():
    assert kinds("builder-2 finished the change.") == [("builder-2", "a helper's name")]


def test_a_commit_id_is_found():
    assert kinds("The change abc1234 landed.") == [("abc1234", "a commit id")]


def test_an_internal_code_is_found():
    assert kinds("I fixed TD236 and moved on.") == [("TD236", "an internal code")]
    assert kinds("Task T52 is done.") == [("T52", "an internal code")]
    assert kinds("WS-12 is done.") == [("WS-12", "an internal code")]


def test_a_short_form_never_spelled_out_is_found():
    [found] = plain.findings("The SLA holds.")
    assert (found.words, found.kind) == ("SLA", "a short form")
    assert "Spell SLA out" in found.advice


def test_a_long_sentence_is_found():
    text = " ".join(["word"] * (plain.MAX_WORDS + 1)) + "."
    [found] = plain.findings(text)
    assert found.kind == "a long sentence" and f"{plain.MAX_WORDS + 1} words" in found.advice


def test_each_finding_is_named_once():
    assert kinds("The worktree and the worktree again.") == [("worktree", "an internal word")]


# No false alarms


@pytest.mark.parametrize("text", [
    "The release is ready. I merged it at 12:30 on 2026-11-24.",
    "Today I spoke to Ana. Then I wrote the code in Python 3.11.",
    "The step is on issue #12, and it costs $5.",
    "I added 10 tests in 3 files, and the year is 2026.",
    "The deploy finished at 10:45 UTC, and we ship in Q4.",
    "The CPUs are busy, and PRs #12 and #14 are open.",
    "Version 1.2.3 is out, and v2 follows.",
    "Rooms a1 and B2 are free, and so is the X1 laptop.",
    "I read the README and the FAQ.",
])
def test_ordinary_prose_finds_nothing(text):
    assert kinds(text) == []


def test_links_and_text_in_backticks_are_left_alone():
    assert kinds("See https://github.com/acme/demo/pull/20 -> done, then run `colony step list w/ TD236`.") == \
        [("->", "an arrow")]


def test_common_short_forms_pass():
    assert kinds("The API and CI checks passed on the PR, at 9 UTC.") == []


def test_a_short_form_spelled_out_in_brackets_passes():
    assert kinds("The service level agreement (SLA) holds, and the SLA is met.") == []
    assert kinds("The SLA (service level agreement) holds.") == []


@pytest.mark.parametrize("name", list(plain.TEMPLATES))
def test_each_template_reads_plainly_when_filled(name):
    assert kinds(plain.fill(name)) == []


# The team's own words


def test_allow_lets_the_projects_own_names_through():
    config = {"plain": {"allow": ["SLA", "worktree"]}}
    assert kinds("The SLA and the worktree are fine.", config) == []


def test_jargon_adds_the_teams_own_shorthand():
    config = {"plain": {"jargon": ["the hive"]}}
    assert kinds("I sent it to the hive.", config) == [("the hive", "an internal word")]


@pytest.mark.parametrize("table", [{"allow": "SLA"}, {"jargon": [1]}])
def test_allow_and_jargon_must_be_lists_of_words(table):
    with pytest.raises(cli.ColonyError, match=r"\[plain\]"):
        plain.findings("Hello.", {"plain": table})


# Templates


def test_fill_keeps_a_blank_with_no_value_as_its_name():
    assert plain.fill("done", change="The sign-in page") == \
        "The sign-in page is finished, and its checks passed. Next, <next>."


def test_fill_refuses_an_unknown_template():
    with pytest.raises(cli.ColonyError, match="no status template 'nope'"):
        plain.fill("nope")


def test_templates_prints_every_template_or_one(capsys):
    assert plain.run({}, Namespace(action="templates", name=None)) == 0
    assert capsys.readouterr().out.count("\n") == len(plain.TEMPLATES)
    assert plain.run({}, Namespace(action="templates", name="red")) == 0
    assert capsys.readouterr().out == f"red: {plain.TEMPLATES['red']}\n"
    with pytest.raises(cli.ColonyError, match="no status template"):
        plain.run({}, Namespace(action="templates", name="nope"))


def test_fill_prints_the_message_and_passes_when_it_reads_plainly(capsys):
    assert plain.run({}, Namespace(action="fill", name="done", values=["change=The page", "next=the tests"])) == 0
    assert capsys.readouterr().out == "The page is finished, and its checks passed. Next, the tests.\n"


def test_fill_fails_when_the_values_hold_shorthand(capsys):
    assert plain.run({}, Namespace(action="fill", name="done", values=["change=TD236", "next=the tests"])) == 1
    out, err = capsys.readouterr()
    assert out.startswith("TD236 is finished") and '"TD236": an internal code' in err


def test_fill_refuses_a_value_with_no_name():
    with pytest.raises(cli.ColonyError, match="name=value"):
        plain.run({}, Namespace(action="fill", name="done", values=["the page"]))


# The check command


def test_check_exits_0_on_a_plain_message(capsys):
    assert check(["The", "release", "is", "ready."]) == 0
    assert capsys.readouterr().out.strip() == "plain: it reads plainly."


def test_check_exits_1_and_names_each_finding(capsys):
    assert check(["Done", "->", "TD236", "fyi."]) == 1
    out = capsys.readouterr().out
    assert out.startswith("plain: 3 things to fix before this reaches the person:")
    assert '- "->": an arrow.' in out and '- "TD236": an internal code.' in out


def test_check_reads_a_file(tmp_path, capsys):
    path = tmp_path / "message.txt"
    path.write_text("The worktree is ready.\n")
    assert check(file=str(path)) == 1
    assert '"worktree": an internal word' in capsys.readouterr().out


def test_check_reads_standard_input(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("The release is ready.\n"))
    assert check(file="-") == 0


def test_check_refuses_a_file_it_cannot_read(tmp_path):
    with pytest.raises(cli.ColonyError, match="could not be read"):
        check(file=str(tmp_path / "missing.txt"))


def test_check_refuses_an_empty_message():
    with pytest.raises(cli.ColonyError, match="give the message"):
        check([])
