"""Tests for the anti-bloat limits and `colony tidy`: cards, ideas, line kinds, long issues, the board and worktrees.
gh is the stand-in from test_board, git is real, in a temporary repository, and nothing reaches GitHub."""
import argparse
import json
import re
import subprocess
import time
from argparse import Namespace
from pathlib import Path

import pytest
from test_board import CONFIG, FULL, LISTED, fields_answer, gh  # noqa: F401  (gh is the stand-in gh fixture)

from colony import cli, tidy, transport, wait

REPO_INFO = {"delete_branch_on_merge": True}


def parse(*argv):
    """Parse a command line the way cli.py will, through tidy.add_commands."""
    parser = argparse.ArgumentParser()
    tidy.add_commands(parser.add_subparsers(dest="command"))
    return parser.parse_args(list(argv))


def card(number, status, last="", lead="ana-lead", helper="", state="OPEN", title=None, closed=None):
    """One board item as the items query answers it, on the five-field board."""
    values = [{"name": status, "field": {"name": "Status"}}, {"text": last, "field": {"name": "Last update"}},
              {"text": lead, "field": {"name": "Lead"}}, {"text": helper, "field": {"name": "Helper"}}]
    content = {"number": number, "url": f"u/{number}", "state": state, "title": title or f"builder-1: card {number}",
               "updatedAt": "2026-11-05T09:00:00Z", "closedAt": closed}
    return {"id": f"I{number}", "content": content, "fieldValues": {"nodes": values}}


def items_answer(*cards):
    """The board's items query answer."""
    return {"data": {"node": {"items": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": list(cards)}}}}


def comment(body):
    """One comment as `gh issue view --json comments` answers it."""
    return {"body": body, "createdAt": "2026-11-05T10:00:00Z", "author": {"login": "ana-gh"}}


def git(cwd, *args):
    """Run git in cwd and return its output."""
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git repository with one commit on main, as the main checkout."""
    (tmp_path / "gitconfig").write_text("")
    for key, value in {"GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.test",
                       "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.test"}.items():
        monkeypatch.setenv(key, value)
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "a.txt").write_text("a\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    return root


def quiet(gh, issues=(), items=(), info=REPO_INFO):  # noqa: F811
    """The answers of a repo with nothing to tidy unless the test adds it: the repo's settings, its open issues,
    the board and its items."""
    gh.answer("project list", LISTED)
    gh.answer("items(first", items_answer(*items))
    gh.answer("issue list", list(issues))
    gh.answer("api repos/acme/demo", info)


def changes(gh):  # noqa: F811
    """The calls that change something on GitHub."""
    writes = (["issue", "close"], ["issue", "create"], ["issue", "comment"], ["project", "item-archive"],
              ["project", "item-add"], ["project", "item-edit"])
    return [call for call in gh.calls() if call[:2] in writes or "PATCH" in call]


# colony card new


def test_card_new_refuses_a_lead_at_its_open_card_limit(gh, capsys):  # noqa: F811
    full = [card(n, "In progress") for n in range(1, 11)] + [card(11, "Done"), card(12, "To do", lead="sam-lead")]
    quiet(gh, items=full)
    args = parse("card", "new", "builder-1: the export button", "--body", "predicted: S, 20 min", "--size", "S")
    with pytest.raises(cli.ColonyError, match="ana-lead has 10 open cards, and \\[limits\\] open_cards_per_lead is "
                                              "10: close or finish one first"):
        args.run(CONFIG, args)
    assert changes(gh) == []
    # Another lead's cards, and Done ones, never count: sam-lead has room, and so has a higher limit.
    gh.answer("issue create", "https://github.com/acme/demo/issues/40\n")
    gh.answer("fields(first", fields_answer(*FULL))
    gh.answer("project item-add", {"id": "PVTI_40"})
    args = parse("card", "new", "builder-1: the export button", "--body", "b", "--size", "S", "--lead", "sam-lead")
    assert args.run(CONFIG, args) == 0
    args = parse("card", "new", "builder-1: the import button", "--body", "b", "--size", "M")
    assert args.run({**CONFIG, "limits": {"open_cards_per_lead": 11}}, args) == 0
    assert len(gh.called("issue", "create")) == 2


def test_card_new_makes_the_issue_and_puts_it_on_the_board_as_to_do_with_its_lead_and_size(gh, capsys):  # noqa: F811
    quiet(gh, items=[card(1, "In progress")])
    gh.answer("issue create", "https://github.com/acme/demo/issues/41\n")
    gh.answer("fields(first", fields_answer(*FULL))
    gh.answer("project item-add", {"id": "PVTI_41"})
    args = parse("card", "new", "builder-2: the  login form", "--body", "done when: it signs in", "--size", "M")
    assert args.run(CONFIG, args) == 0
    assert gh.called("issue", "create") == [["issue", "create", "--repo", "acme/demo", "--title",
                                             "builder-2: the login form", "--body", "done when: it signs in"]]
    head = ["project", "item-edit", "--project-id", "PVT_3", "--id", "PVTI_41", "--field-id"]
    assert gh.called("project", "item-edit") == [head + ["F2", "--single-select-option-id", "F2-0"],
                                                 head + ["F3", "--text", "ana-lead"],
                                                 head + ["F5", "--single-select-option-id", "F5-1"],
                                                 head + ["F6", "--text", "2026-11-05 14:05 UTC"]]
    assert capsys.readouterr().out.strip() == "#41 builder-2: the login form (Status=To do, Lead=ana-lead, Size=M)"


def test_card_new_prints_the_median_of_the_last_cards_of_its_size_beside_the_prediction(gh, capsys):  # noqa: F811
    done = [{"number": n, "title": f"builder-1: c{n}", "body": "predicted: M, 30 min", "comments": [
        {"createdAt": "2026-01-05T10:00:00Z", "body": "for builder-1: start this card (from lead)"},
        {"createdAt": f"2026-01-05T1{h}:00:00Z", "body": "for lead: done, x pushed, 3 passed (from builder-1)"}]}
        for n, h in ((9, 1), (8, 2), (7, 3))]
    gh.answer("--state closed", done)
    quiet(gh, items=[card(1, "In progress")])
    gh.answer("issue create", "https://github.com/acme/demo/issues/41\n")
    gh.answer("fields(first", fields_answer(*FULL))
    gh.answer("project item-add", {"id": "PVTI_41"})
    args = parse("card", "new", "builder-2: the export", "--body", "predicted: M, 45 min", "--size", "M")
    assert args.run(CONFIG, args) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "predicted 45 min; the last 3 M cards took a median of 120 min"


@pytest.mark.parametrize("title", ["builder-1: Add dark-mode to settings!", "ADD DARK MODE TO SETTINGS",
                                   "builder-3: add dark mode to the settings page"])
def test_card_new_refuses_a_duplicate_of_an_open_card_by_its_number(gh, title):  # noqa: F811
    quiet(gh, issues=[{"number": 7, "title": "Colony: coordination"},
                      {"number": 12, "title": "builder-2: Add dark mode to settings"}])
    args = parse("card", "new", title, "--body", "b", "--size", "S")
    with pytest.raises(cli.ColonyError, match="#12 is already open as 'builder-2: Add dark mode to settings'"):
        args.run(CONFIG, args)
    assert changes(gh) == []


def test_titles_that_share_a_word_or_two_are_not_duplicates():
    issues = [{"number": 12, "title": "builder-2: fix the login button"}]
    assert tidy.duplicate("builder-1: fix the logout page", issues) is None
    assert tidy.duplicate("fix login", issues) is None
    assert tidy.duplicate("builder-1: fix the login button.", issues) == issues[0]


def test_hack_mode_has_no_cards(gh):  # noqa: F811
    args = parse("card", "new", "the form", "--body", "b", "--size", "S")
    with pytest.raises(cli.ColonyError, match="hack mode has no cards"):
        args.run({**CONFIG, "project": {**CONFIG["project"], "mode": "hack"}}, args)
    assert gh.calls() == []


# colony idea


def test_idea_appends_a_dated_line_to_colony_future_work_without_a_vault(gh, repo, monkeypatch, capsys):  # noqa: F811
    monkeypatch.chdir(repo)
    for text in ("a dark mode for the  calendar", "export to iCal"):
        args = parse("idea", text)
        assert args.run(CONFIG, args) == 0
    page = (repo / ".colony" / "future-work.md").read_text()
    assert page.endswith("## Ideas\n\n- 2026-11-05: a dark mode for the calendar\n- 2026-11-05: export to iCal\n")
    assert gh.calls() == []  # an idea is never an issue
    assert f"{Path('.colony', 'future-work.md')}: - 2026-11-05: export to iCal" in capsys.readouterr().out


def test_an_idea_goes_into_the_vaults_register_inside_its_ideas_section(tmp_path):
    config = {**CONFIG, "features": {"knowledge": True}, "knowledge": {"vault": "docs/kb/"}}
    path = tidy.future_work_path(config, tmp_path)
    assert path == tmp_path / "docs" / "kb" / "future-work.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Future work\n\n## Ideas\n\n- 2026-11-01: one\n\n## Items\n\n| Item |\n")
    tidy.add_idea(path, "two", "2026-11-05")
    assert path.read_text() == "# Future work\n\n## Ideas\n\n- 2026-11-01: one\n- 2026-11-05: two\n\n## Items\n\n| Item |\n"
    with pytest.raises(cli.ColonyError, match="one line under 300 characters"):
        tidy.add_idea(path, "word " * 70, "2026-11-05")



def test_an_idea_goes_to_the_register_future_work_names_as_a_row_of_its_ideas_table(tmp_path):
    config = {**CONFIG, "features": {"knowledge": True}, "knowledge": {"future_work": "kb/future/register.md"}}
    path = tidy.future_work_path(config, tmp_path)
    assert path == tmp_path / "kb" / "future" / "register.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Register\n\n## Ideas\n\n| Item | Stage | Why |\n| --- | --- | --- |\n| one | Idea | x |\n\n"
                    "Notes under the table.\n\n## Product work\n\n| Item |\n")
    line = tidy.add_idea(path, "two", "2026-11-07")
    assert line == "| 2026-11-07: two | | |"
    assert path.read_text() == ("# Register\n\n## Ideas\n\n| Item | Stage | Why |\n| --- | --- | --- |\n| one | Idea | x |\n"
                                "| 2026-11-07: two | | |\n\nNotes under the table.\n\n## Product work\n\n| Item |\n")

# Line kinds


@pytest.fixture
def sent(monkeypatch):
    """transport.send, recorded instead of posted."""
    lines = []
    monkeypatch.setattr(transport, "send", lambda config, to, line, card=None: lines.append(line) or 41)
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    return lines


def post_as(monkeypatch, session, to, sentence):
    """`colony post 41 <to> "<sentence>"` from `session`."""
    monkeypatch.setenv(cli.SESSION_ENV, session)
    return wait.post(CONFIG, Namespace(card=41, to=to, sentence=sentence, urgent=False))


@pytest.mark.parametrize("sentence", ["done, builder-2/41 pushed, 12 passed", "question: keep 30 s? I'm going with yes",
                                      "blocked: the test database won't start", "urgent: main is red"])
def test_post_lets_a_helper_send_its_lead_each_permitted_kind(sent, monkeypatch, sentence):
    assert post_as(monkeypatch, "builder-2", "lead", sentence) == 0
    assert sent == [f"for lead: {sentence} (from builder-2)"]


@pytest.mark.parametrize("sentence", ["working on the form, half done", "pushed a first commit", "progress: 50%",
                                      "start: this card"])
def test_post_refuses_a_helpers_progress_line_and_says_where_progress_goes(sent, monkeypatch, sentence):
    with pytest.raises(cli.ColonyError, match="a helper's line to its lead starts with `done:`, `question:`, "
                                              "`blocked:`, `urgent:`.*progress goes on the board"):
        post_as(monkeypatch, "builder-2", "lead", sentence)
    assert sent == []


@pytest.mark.parametrize("sentence", ["start: this card", "answer: yes, keep 30 s", "urgent: stop this card"])
def test_post_lets_a_lead_hand_out_and_answer_work(sent, monkeypatch, sentence):
    assert post_as(monkeypatch, "lead", "builder-2", sentence) == 0
    assert sent == [f"for builder-2: {sentence} (from lead)"]


def test_post_refuses_a_leads_chatter_to_a_helper_and_lets_lead_to_lead_talk_run_free(sent, monkeypatch):
    with pytest.raises(cli.ColonyError, match="a lead's line to its helper starts with `start:`, `answer:`, `urgent:`"):
        post_as(monkeypatch, "lead", "builder-2", "nice work on the form")
    assert post_as(monkeypatch, "lead", "sam-lead", "can your builders take the export card?") == 0
    assert post_as(monkeypatch, "lead", "@all", "I merge dev into main in 10 minutes") == 0
    assert len(sent) == 2


# Long issues


def coordination_answers(gh, count):  # noqa: F811
    """The answers of a repo whose coordination issue, #5, holds `count` comments, and whose Needs Ana, #6,
    holds 3."""
    gh.answer("api repos/acme/demo/issues/5", {"state": "open", "title": wait.COORDINATION, "comments": count,
                                               "body": "Leads post lines for each other here."})
    gh.answer("api repos/acme/demo/issues/6", {"state": "open", "title": "Needs Ana", "comments": 3, "body": "b"})
    quiet(gh, issues=[{"number": 5, "title": wait.COORDINATION}, {"number": 6, "title": "Needs Ana"}])


def test_tidy_rotates_the_coordination_issue_at_200_comments_and_the_watcher_follows_it(gh, repo, tmp_path,  # noqa: F811
                                                                                     capsys):
    coordination_answers(gh, 200)
    chatter = [comment(f"for sam-lead: note {n} (from ana-lead)") for n in range(60)]
    early = comment("for ana-lead: question: an old question, past the last 50? (from sam-lead)")
    gh.answer("issue view 5", {"comments": [early, *chatter[:-3],
                                            comment("for ana-lead: question: can you take #12? (from sam-lead)"),
                                            comment("[Bo's Claude] for sam-lead: blocked: main is red (from bo-lead)"),
                                            comment("for sam-lead: urgent: I merge in 5 minutes (from ana-lead)")]})
    gh.answer("issue create", "https://github.com/acme/demo/issues/31\n")
    assert tidy.run_tidy(CONFIG, repo) == 0

    create = gh.called("issue", "create")[0]
    assert create[create.index("--title") + 1] == "Colony: coordination"
    assert create[create.index("--body") + 1].endswith("Continues #5, closed at 200 comments.")
    closing = gh.called("issue", "comment", "5")[0][-1]
    assert closing.startswith("Closed at 200 comments; this thread goes on in #31.")
    assert ("- for ana-lead: question: can you take #12? (from sam-lead)\n"
            "- for sam-lead: blocked: main is red (from bo-lead)\n"
            "- for sam-lead: urgent: I merge in 5 minutes (from ana-lead)") in closing
    assert "note 1 " not in closing and "an old question" not in closing
    assert gh.called("issue", "close") == [["issue", "close", "5", "--repo", "acme/demo"]]
    assert not gh.called("issue", "create", "--repo", "acme/demo", "--title", "Needs Ana")
    out = capsys.readouterr().out
    assert "#5 Colony: coordination 200 → 0" in out and "#6 Needs Ana 3 → 3" in out and "rotations: 1" in out
    # This computer's watcher follows the new issue at once, with no call to GitHub.
    calls = len(gh.calls())
    assert wait.coordination_issue("acme/demo", "demo") == 31
    assert len(gh.calls()) == calls


def test_another_computers_watcher_drops_the_closed_coordination_issue_and_finds_the_new_one(gh, tmp_path):  # noqa: F811
    state = tmp_path / "home" / ".colony" / "demo"
    state.mkdir(parents=True)
    (state / "lead-coordination.json").write_text("5")
    (state / "lead-coordination-checked.json").write_text(str(time.time() - 3600))
    gh.answer("issues/5 --jq .state", "closed\n")
    gh.answer("issue list", [{"number": 31, "title": wait.COORDINATION}])
    assert wait.coordination_issue("acme/demo", "demo") == 31
    assert json.loads((state / "lead-coordination.json").read_text()) == 31
    assert wait.coordination_issue("acme/demo", "demo") == 31  # checked just now: no call for the next 10 minutes
    assert len(gh.called("issue", "list")) == 1 and len(gh.called("api")) == 1


def test_a_post_on_a_full_needs_issue_rotates_it_first_and_names_the_unanswered_decisions(gh):  # noqa: F811
    gh.answer("api repos/acme/demo/issues/6", {"state": "open", "title": "Needs Ana", "comments": 200,
                                               "body": "The decisions only Ana makes.\n\nContinues #2."})
    gh.answer("issue view 6", {"comments": [
        comment("for ana-lead: Ana decides: keep 30 s? Default: yes (from ana-lead)"),
        comment("for ana-lead: no, 60 s"),
        comment("for ana-lead: Ana decides: ship on Friday? Default: yes (from ana-lead)")]})
    gh.answer("issue create", "https://github.com/acme/demo/issues/44\n")
    assert tidy.keep_short(CONFIG, 6) == 44
    create = gh.called("issue", "create")[0]
    assert create[create.index("--body") + 1] == ("The decisions only Ana makes.\n\nContinues #6, closed at 200 "
                                                  "comments.")
    closing = gh.called("issue", "comment", "6")[0][-1]
    assert "unanswered: for ana-lead: Ana decides: ship on Friday? Default: yes" in closing
    assert "keep 30 s" not in closing


def test_a_post_on_an_issue_under_its_limit_costs_one_read(gh):  # noqa: F811
    gh.answer("api repos/acme/demo/issues/6", {"state": "open", "title": "Needs Ana", "comments": 199})
    assert tidy.keep_short(CONFIG, 6) == 6
    assert gh.calls() == [["api", "repos/acme/demo/issues/6"]]


# The hack board

HACK_BOARD = {**CONFIG, "project": {**CONFIG["project"], "mode": "hack"}, "messages": {"board": 7},
              "people": {"logins": ["ana"], "names": {"ana": "Ana"}}}


def test_a_post_on_a_board_with_300_comments_moves_it_to_a_fresh_pinned_issue_that_every_later_post_uses(gh):  # noqa: F811
    gh.answer("api repos/acme/demo/issues/7", {"state": "open", "title": "Board: demo", "comments": 300,
                                               "body": "The board for demo."})
    gh.answer("issue view 7", {"comments": [comment("[Ana's Claude] @all blocked: main is red")]})
    gh.answer("issue create", "https://github.com/acme/demo/issues/40\n")
    assert transport.send(HACK_BOARD, "@all", "@all hello (from ana-lead)") == 40
    create = gh.called("issue", "create")[0]
    assert create[create.index("--title") + 1] == "Board: demo"
    assert create[create.index("--body") + 1].endswith("Continues #7, closed at 300 comments.")
    closing = gh.called("issue", "comment", "7")[0][-1]
    assert closing.startswith("Closed at 300 comments; this thread goes on in #40.")
    assert gh.called("issue", "unpin") == [["issue", "unpin", "7", "--repo", "acme/demo"]]
    assert gh.called("issue", "pin") == [["issue", "pin", "40", "--repo", "acme/demo"]]
    assert gh.called("issue", "comment", "40")[0][-1] == "[Ana's Claude] @all hello (from ana-lead)"
    # Every later read and post on this computer, and the status comments, use the fresh board.
    assert tidy.board_now(HACK_BOARD) == 40
    from colony import presence
    assert presence.where(HACK_BOARD) == 40


def test_the_board_moves_at_the_limit_the_config_sets_and_not_before(gh):  # noqa: F811
    gh.answer("api repos/acme/demo/issues/7", {"state": "open", "title": "Board: demo", "comments": 299})
    assert tidy.keep_board(HACK_BOARD) == 7
    assert gh.calls() == [["api", "repos/acme/demo/issues/7"]]
    assert tidy.limits({"limits": {"board_comments": 120}})["board_comments"] == 120


def test_a_post_from_another_computer_follows_the_closed_board_to_the_fresh_one(gh):  # noqa: F811
    gh.answer("api repos/acme/demo/issues/7", {"state": "closed", "title": "Board: demo", "comments": 301})
    gh.answer("issue list", [{"number": 5, "title": "Board: demo"}, {"number": 40, "title": "Board: demo"},
                             {"number": 41, "title": "Board: demo, old notes"}])
    gh.answer("api repos/acme/demo/issues/40", {"state": "open", "title": "Board: demo", "comments": 3})
    assert tidy.keep_board(HACK_BOARD) == 40
    assert not gh.called("issue", "create")
    assert tidy.board_now(HACK_BOARD) == 40


BOARD_7 = {"state": "open", "title": "Board: demo", "comments": 300, "body": "The board for demo."}


def moved_note(new: int) -> dict:
    """The note a move leaves on the old board, as the comments API answers it."""
    return {"body": f"Closed at 300 comments; this thread goes on in #{new}.\n\nOpen items: none"}


def test_a_full_board_that_another_post_moved_already_is_followed_there_without_a_second_fresh_board(gh):  # noqa: F811
    gh.answer("api repos/acme/demo/issues/7", BOARD_7)
    gh.answer("issue list", [{"number": 40, "title": "Board: demo"}])
    assert tidy.keep_board(HACK_BOARD) == 40
    assert not gh.called("issue", "create")
    assert gh.called("issue", "comment", "7")[0][-1].startswith("Closed at 300 comments; this thread goes on in #40.")
    assert gh.called("issue", "close") == [["issue", "close", "7", "--repo", "acme/demo"]]
    assert gh.called("issue", "pin") == [["issue", "pin", "40", "--repo", "acme/demo"]]


def test_two_posts_that_move_the_board_at_once_keep_the_lowest_fresh_board_and_close_the_other(gh):  # noqa: F811
    gh.answer("api repos/acme/demo/issues/41", {"state": "open", "title": "Board: demo", "comments": 0})
    gh.answer("api repos/acme/demo/issues/7", BOARD_7)
    gh.answer("issue list", [], once=True)  # the other post's fresh board, #40, is not found before this one opens
    gh.answer("issue list", [{"number": 40, "title": "Board: demo"}, {"number": 41, "title": "Board: demo"}])
    gh.answer("issue create", "https://github.com/acme/demo/issues/41\n")
    assert tidy.keep_board(HACK_BOARD) == 40
    assert len(gh.called("issue", "create")) == 1
    assert gh.called("issue", "comment", "41")[0][-1].startswith("Closed at 0 comments; this thread goes on in #40.")
    assert ["issue", "close", "41", "--repo", "acme/demo"] in gh.called("issue", "close")
    assert gh.called("issue", "pin") == [["issue", "pin", "40", "--repo", "acme/demo"]]
    assert tidy.board_now(HACK_BOARD) == 40


def test_a_post_after_a_move_that_stopped_half_way_finishes_it_on_the_board_it_made(gh):  # noqa: F811
    gh.answer("api repos/acme/demo/issues/7", BOARD_7)
    gh.answer("issue create", "https://github.com/acme/demo/issues/40\n")
    gh.answer("issue comment 7", "", code=1, once=True)  # GitHub refuses the closing note once
    assert tidy.keep_board(HACK_BOARD) == 7
    # The search does not list #40 yet, and the old board is still open and full: the next post finishes the move.
    assert tidy.keep_board(HACK_BOARD) == 40
    assert len(gh.called("issue", "create")) == 1
    assert gh.called("issue", "close") == [["issue", "close", "7", "--repo", "acme/demo"]]
    assert tidy.board_now(HACK_BOARD) == 40


def test_right_after_a_move_the_closed_board_is_followed_by_its_note_before_the_search_finds_the_fresh_one(gh):  # noqa: F811
    gh.answer("api repos/acme/demo/issues/7/comments", [{"body": "kickoff"}, moved_note(41), moved_note(40)])
    gh.answer("api repos/acme/demo/issues/7", {**BOARD_7, "state": "closed", "comments": 302})
    gh.answer("api repos/acme/demo/issues/40", {"state": "open", "title": "Board: demo", "comments": 1})
    assert tidy.keep_board(HACK_BOARD) == 40
    assert not gh.called("issue", "list")
    assert tidy.board_now(HACK_BOARD) == 40


def test_the_shell_script_reads_the_note_rotate_leaves_on_the_old_board():
    pattern = re.search(r"^MOVED='([^']+)'", (Path(tidy.__file__).parent / "scripts" / "board").read_text(), re.M)[1]
    note = "Closed at 300 comments; this thread goes on in #40.\n\nOpen items from its last 50 comments:\n- none"
    assert re.match(pattern.replace("[0-9]+", r"\d+"), note)
    assert "this thread goes on in #{new}" in Path(tidy.__file__).read_text()


# The board


def test_tidy_closes_a_started_stale_card_and_moves_a_never_started_one_to_future_work(gh, repo, capsys):  # noqa: F811
    quiet(gh, items=[card(20, "In progress", "2026-10-20 10:00 UTC", helper="builder-1"),
                     card(21, "To do", "2026-10-25 10:00 UTC", title="builder-2: the login form"),
                     card(22, "In review", "2026-11-04 10:00 UTC"),
                     card(23, "To do", "2026-11-01 10:00 UTC", lead="sam-lead")])
    assert tidy.run_tidy(CONFIG, repo) == 0
    closed = gh.called("issue", "close")
    assert closed == [["issue", "close", "20", "--repo", "acme/demo", "--reason", "not planned", "--comment",
                       "tidy: closed: it shows no update since 2026-10-20; reopen it when its work starts again"],
                      ["issue", "close", "21", "--repo", "acme/demo", "--reason", "not planned", "--comment",
                       "tidy: moved to future-work: its work never started, and it shows no update since 2026-10-25"]]
    assert (repo / ".colony" / "future-work.md").read_text().endswith("- 2026-11-05: the login form (was #21)\n")
    out = capsys.readouterr().out
    assert "open cards per lead: ana-lead 3 → 1, sam-lead 1 → 1" in out
    assert "stale cards: 1 closed, 1 moved to future-work" in out


def test_tidy_archives_done_items_after_7_days(gh, repo, capsys):  # noqa: F811
    quiet(gh, items=[card(40, "Done", "2026-10-28 14:00 UTC"),
                     card(41, "In review", "2026-10-01 10:00 UTC", state="CLOSED", closed="2026-11-01T00:00:00Z"),
                     card(42, "Done", "2026-10-01 10:00 UTC", state="CLOSED", closed="2026-11-04T00:00:00Z"),
                     card(43, "Done", "2026-10-29 15:00 UTC")])
    assert tidy.run_tidy(CONFIG, repo) == 0
    assert gh.called("project", "item-archive") == [["project", "item-archive", "3", "--owner", "acme", "--id", "I40"]]
    assert "board items archived: 1" in capsys.readouterr().out


def test_tidy_turns_on_delete_branch_on_merge_and_says_so(gh, repo, capsys):  # noqa: F811
    quiet(gh, info={"delete_branch_on_merge": False})
    assert tidy.run_tidy(CONFIG, repo) == 0
    assert gh.called("api", "-X", "PATCH") == [["api", "-X", "PATCH", "repos/acme/demo", "-F",
                                                "delete_branch_on_merge=true"]]
    assert "delete_branch_on_merge: off → turned on" in capsys.readouterr().out


# Worktrees


def worktree(repo, branch, dirty=False):
    """A worktree beside the repo on a new branch, with an untracked file when dirty."""
    path = repo.parent / branch.replace("/", "-")
    git(repo, "worktree", "add", "-q", "-b", branch, str(path))
    if dirty:
        (path / "notes.txt").write_text("not committed\n")
    return path


def test_tidy_removes_a_closed_cards_clean_worktree_and_keeps_a_dirty_one_and_the_main_checkout(gh, repo,  # noqa: F811
                                                                                             capsys):
    clean, dirty = worktree(repo, "builder-1/12"), worktree(repo, "builder-2/13", dirty=True)
    still_open, batch = worktree(repo, "builder-3/14"), worktree(repo, "demo/batch-b1")
    git(repo, "checkout", "-q", "-b", "builder-9/15")  # the main checkout, on a closed card's branch
    quiet(gh, issues=[{"number": 14, "title": "builder-3: card 14"}])
    gh.answer("issue view", {"state": "CLOSED"})
    assert tidy.run_tidy(CONFIG, repo) == 0
    assert not clean.exists() and dirty.exists() and still_open.exists() and batch.exists() and repo.exists()
    assert not gh.called("issue", "view", "14")
    assert "builder-1/12" in git(repo, "branch", "--list", "builder-1/12")  # the branch stays: only the folder goes
    out = capsys.readouterr().out
    assert re.search(r"worktrees: 1 removed, \d+ bytes freed, 1 kept: " +
                     re.escape(f"{dirty} (uncommitted or untracked changes)"), out)


def detached(repo, name):
    """A detached worktree beside the repo, as Colony makes for a walk, a merge or an image."""
    path = repo.parent / name
    git(repo, "worktree", "add", "-q", "--detach", str(path))
    return path


def test_tidy_removes_the_worktrees_of_merged_cards_and_ended_batches_merges_and_retros_and_prints_the_space_freed(
        gh, repo, capsys):  # noqa: F811
    git(repo, "update-ref", "refs/remotes/origin/dev", "HEAD")
    merged = worktree(repo, "builder-1/12")
    batch, fix, retro = worktree(repo, "demo/batch-b1"), worktree(repo, "demo/fix-b1-12-r1"), worktree(repo, "demo/retro-b1")
    walk, merge, image = detached(repo, "demo-batch-b1-walk"), detached(repo, "demo-merge"), detached(repo, "demo-image-7")
    running, fresh = worktree(repo, "demo/batch-b2"), worktree(repo, "demo/batch-b3")
    reports = batch / ".colony" / "reports" / "b1"
    reports.mkdir(parents=True)
    (reports / "state.json").write_text("{}")  # a batch's own untracked state never keeps its worktree
    quiet(gh, issues=[{"number": 12, "title": "builder-1: card 12"}])
    gh.answer("pr list", [{"headRefName": "builder-1/12", "state": "MERGED"},
                          {"headRefName": "demo/batch-b1", "state": "MERGED"},
                          {"headRefName": "demo/fix-b1-12-r1", "state": "MERGED"},
                          {"headRefName": "demo/retro-b1", "state": "CLOSED"},
                          {"headRefName": "demo/batch-b2", "state": "CLOSED"},
                          {"headRefName": "demo/batch-b2", "state": "OPEN"}])
    assert tidy.run_tidy(CONFIG, repo) == 0
    assert not any(path.exists() for path in (merged, batch, fix, retro, walk, merge, image))
    assert running.exists() and fresh.exists() and repo.exists()  # an open pull request, and none yet
    assert len([call for call in gh.calls() if call[:2] == ["pr", "list"]]) == 1
    out = capsys.readouterr().out
    assert "card #12's pull request merged" in out and "demo/retro-b1's pull request closed" in out
    assert re.search(r"worktrees: 7 removed, [\d.]+ (bytes|KB|MB) freed, 0 kept", out)


def test_tidy_keeps_a_merge_worktree_whose_head_is_not_in_the_base(gh, repo, capsys):  # noqa: F811
    git(repo, "update-ref", "refs/remotes/origin/dev", "HEAD")
    merge = detached(repo, "demo-merge")
    (merge / "b.txt").write_text("b\n")
    git(merge, "add", "-A")
    git(merge, "commit", "-qm", "not merged yet")
    quiet(gh)
    assert tidy.run_tidy(CONFIG, repo) == 0
    assert merge.exists()


def test_tidy_dry_run_lists_the_worktrees_it_leaves_with_their_size_and_last_commit_date(gh, repo, capsys):  # noqa: F811
    working, dirty = worktree(repo, "builder-3/14"), worktree(repo, "builder-2/13", dirty=True)
    (working / "big.bin").write_bytes(b"x" * 5000)
    quiet(gh, issues=[{"number": 14, "title": "builder-3: card 14"}])
    gh.answer("issue view", {"state": "CLOSED"})
    assert tidy.run_tidy(CONFIG, repo, dry=True) == 0
    assert working.exists() and (working / "big.bin").exists() and dirty.exists()
    out = capsys.readouterr().out
    today = git(repo, "log", "-1", "--format=%cs")
    assert "The other worktrees, which tidy leaves:" in out
    assert re.search(rf"{re.escape(str(working))}: 5\.\d KB, last commit {today}", out)
    assert re.search(rf"{re.escape(str(dirty))}: \d+ bytes, last commit {today}", out)
    assert str(repo) + ":" not in out  # the main checkout is never listed


# colony tidy


def test_tidy_dry_run_prints_the_plan_and_changes_nothing(gh, repo, tmp_path, capsys, monkeypatch):  # noqa: F811
    clean = worktree(repo, "builder-1/12")
    gh.answer("api repos/acme/demo/issues/5", {"state": "open", "title": wait.COORDINATION, "comments": 250})
    quiet(gh, issues=[{"number": 5, "title": wait.COORDINATION}],
          items=[card(20, "In progress", "2026-10-20 10:00 UTC"), card(21, "To do", "2026-10-20 10:00 UTC"),
                 card(40, "Done", "2026-10-01 10:00 UTC")],
          info={"delete_branch_on_merge": False})
    gh.answer("issue view", {"state": "CLOSED"})
    args = parse("tidy", "--dry-run")
    monkeypatch.chdir(repo)
    assert args.run(CONFIG, args) == 0
    assert changes(gh) == []
    assert clean.exists() and not (repo / ".colony").exists()
    assert not (tmp_path / "home" / ".colony" / "demo" / "lead-coordination.json").exists()
    out = capsys.readouterr().out
    for planned in ("dry run, nothing changes", "#20: closed:", "#21: moved to future-work",
                    "rotate #5 Colony: coordination: 250 comments", "archive #40", "turn on delete_branch_on_merge",
                    f"remove the worktree {clean}", "ana-lead 2 → 0 (planned)"):
        assert planned in out, planned


def test_a_failing_step_says_so_and_the_others_go_on(gh, repo, capsys):  # noqa: F811
    quiet(gh, items=[card(20, "In progress", "2026-10-20 10:00 UTC"), card(40, "Done", "2026-10-01 10:00 UTC")])
    gh.answer("issue close", "", code=1)
    assert tidy.run_tidy(CONFIG, repo) == 1
    assert gh.called("project", "item-archive")
    out = capsys.readouterr().out
    assert "failed: #20: closed" in out and "stale cards: 0 closed" in out and "board items archived: 1" in out


def test_tidy_skips_the_card_board_in_hack_mode(gh, repo, capsys):  # noqa: F811
    hack = {**CONFIG, "project": {**CONFIG["project"], "mode": "hack"}, "features": {"board": False}}
    gh.answer("issue list", [{"number": 5, "title": wait.COORDINATION}])
    gh.answer("api repos/acme/demo", REPO_INFO)
    assert tidy.run_tidy(hack, repo) == 0
    assert not gh.called("project") and not gh.called("api", "repos/acme/demo/issues/5")
    assert "open cards per lead: none" in capsys.readouterr().out


def test_tidy_and_card_are_commands_on_the_command_line():
    args = cli.build_parser().parse_args(["tidy", "--dry-run"])
    assert args.run is tidy.tidy and args.dry_run
    args = cli.build_parser().parse_args(["card", "new", "t", "--body", "b", "--size", "L", "--lead", "ana-lead"])
    assert (args.run, args.size, args.lead) == (tidy.card_new, "L", "ana-lead")
    assert cli.build_parser().parse_args(["idea", "dark mode"]).run is tidy.idea
    assert cli.build_parser().parse_args(["batch", "--name", "demo", "--review"]).card is None


def test_limits_come_from_the_config_and_must_be_whole_numbers():
    assert tidy.limits({"limits": {"issue_comments": 50}})["issue_comments"] == 50
    assert tidy.limits({})["open_cards_per_lead"] == 10
    with pytest.raises(cli.ColonyError, match="\\[limits\\] stale_days must be a whole number"):
        tidy.limits({"limits": {"stale_days": "a week"}})


def test_an_old_coordination_number_starts_its_check_clock_without_a_call(gh, tmp_path):  # noqa: F811
    state = tmp_path / "home" / ".colony" / "demo"
    state.mkdir(parents=True)
    (state / "lead-coordination.json").write_text("5")
    assert wait.coordination_issue("acme/demo", "demo") == 5
    assert gh.calls() == [] and (state / "lead-coordination-checked.json").exists()


def test_the_future_work_path_has_no_vault_in_hack_and_solo(tmp_path):
    assert tidy.future_work_path({"features": {"knowledge": False}}, tmp_path) == tmp_path / ".colony/future-work.md"
    assert tidy.future_work_path({"features": {"knowledge": True}}, tmp_path) == tmp_path / "knowledge/future-work.md"


def test_open_items_read_past_a_board_posts_prefix_and_markup():
    found = tidy.open_items([comment("**[Ana's Claude] for bo-lead: question: is /api up? (from ana-lead)**")], False)
    assert found == ["for bo-lead: question: is /api up? (from ana-lead)"]


POSTED = re.compile(r'colony post (?:<n> |#?\d+ )?(\S+) "([^"]+)"( --urgent)?')


def test_every_line_the_playbook_skills_and_docs_tell_agents_to_post_is_a_permitted_kind():
    root = Path(__file__).resolve().parent.parent
    pages = [root / "colony" / "playbook.md", *sorted((root / "colony" / "skills").glob("*/SKILL.md")),
             *sorted((root / "docs").glob("*.md"))]
    found = 0
    for page in pages:
        for to, sentence, urgent in POSTED.findall(page.read_text()):
            if re.fullmatch(r"<[^>]+>", sentence):  # the command's syntax, not a line to post
                continue
            found += 1
            sentence = f"urgent: {sentence}" if urgent else sentence  # --urgent starts it so
            tidy.check_kind(to != "lead", to, sentence)  # a line for `lead` is a builder's; any other, the lead's
    assert found >= 15
