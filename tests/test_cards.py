"""Tests for card housekeeping: overlapping cards, cards that wait for others, the lead's queue, a branch's changed
files, and closing the cards GitHub left open. gh is the stand-in from test_board, git is real in temporary
repositories, and nothing reaches GitHub."""
import argparse
import json
import re
import subprocess
from argparse import Namespace
from datetime import datetime, timedelta, timezone

import pytest
from test_board import CONFIG, FULL, LISTED, fields_answer, gh  # noqa: F401  (gh is the stand-in gh fixture)
from test_tidy import card, changes, git, items_answer, quiet, repo  # noqa: F401  (repo is a fixture)

from colony import board, cards, cli, cycle, tidy, transport, wait

NOW = datetime(2026, 11, 5, 14, 5, tzinfo=timezone.utc)


def parse(*argv):
    """Parse a `colony card ...` command line the way cli.py will, through tidy.add_commands."""
    parser = argparse.ArgumentParser()
    tidy.add_commands(parser.add_subparsers(dest="command"))
    return parser.parse_args(list(argv))


def item(number, status, title=None, lead="ana-lead", helper="", body="", state="OPEN", reason=""):
    """One board item as board.items returns it."""
    fields = {"status": status, "lead": lead, "helper": helper, "lastupdate": ""}
    return {"id": f"I{number}", "number": number, "state": state, "stateReason": reason, "url": f"u/{number}",
            "title": title or f"builder-1: card {number}", "body": body, "updatedAt": "", "closedAt": "",
            "fields": {key: value for key, value in fields.items() if value}}


# What a card plans to touch


def test_a_cards_planned_paths_are_its_folders_line_then_its_files_line():
    body = "the task\nFolders: src/auth, `tests/`\nFiles: src/auth/login.ts, ./Makefile\npredicted: S, 20 min"
    assert cards.planned_paths(body) == ["src/auth/", "tests/", "src/auth/login.ts", "Makefile"]
    assert cards.planned_paths("no lines here") == []
    assert cards.overlap("src/", "src/auth/login.ts") and cards.overlap("src/a.ts", "src/a.ts")
    assert not cards.overlap("src/a.ts", "src/b.ts") and not cards.overlap("src/auth/", "src/authz/")


def test_card_new_names_each_open_card_that_plans_to_touch_the_same_paths(gh, capsys):  # noqa: F811
    quiet(gh, issues=[{"number": 12, "title": "builder-3: the sign-up form", "body": "Folders: src/auth/"},
                      {"number": 13, "title": "builder-4: the docs", "body": "Folders: docs/"},
                      {"number": 2, "title": "Colony: coordination", "body": "Folders: src/"},
                      {"number": 9, "title": "builder-1: the login api", "body": "Files: src/auth/login.ts"}])
    gh.answer("issue create", "https://github.com/acme/demo/issues/41\n")
    gh.answer("fields(first", fields_answer(*FULL))
    gh.answer("project item-add", {"id": "PVTI_41"})
    args = parse("card", "new", "builder-2: the login form", "--body", "Files: src/auth/login.ts\nFolders: src/auth/",
                 "--size", "S", "--waits-for", "9")
    assert args.run(CONFIG, args) == 0
    created = gh.called("issue", "create")[0]
    assert created[created.index("--body") + 1] == "Files: src/auth/login.ts\nFolders: src/auth/\nWaits for: #9"
    assert gh.called("issue", "list")[0][gh.called("issue", "list")[0].index("--json") + 1] == "number,title,body"
    out = capsys.readouterr().out
    assert "#41 waits for #9, and starts once it lands" in out
    # #9 is the card it waits for, #13 plans other paths, and #2 is the coordination issue: none is an overlap.
    assert re.findall(r"overlap: #(\d+)", out) == ["12"]
    assert "overlap: #12 builder-3: the sign-up form plans to touch src/auth/ too" in out
    assert "colony card waits 41 12" in out


def test_card_overlaps_lists_every_pair_of_open_cards_that_plan_to_touch_the_same_paths(gh, capsys):  # noqa: F811
    gh.answer("issue list", [{"number": 12, "title": "builder-3: sign-up", "body": "Folders: src/auth/"},
                             {"number": 14, "title": "builder-2: login", "body": "Files: src/auth/login.ts"},
                             {"number": 15, "title": "builder-4: docs", "body": "Folders: docs/"},
                             {"number": 16, "title": "builder-5: login copy", "body": "Folders: src/auth/\nWaits for: #14"}])
    args = parse("card", "overlaps")
    assert args.run(CONFIG, args) == 0
    out = capsys.readouterr().out
    assert "#12 builder-3: sign-up and #14 builder-2: login: src/auth/login.ts (this card: src/auth/)" in out
    assert "#12 builder-3: sign-up and #16 builder-5: login copy: src/auth/" in out
    assert "#14 builder-2: login and #16" not in out  # #16 waits for #14, so the overlap is planned for
    assert "2 overlapping pairs" in out


# What a card waits for


def test_card_waits_sets_the_waits_for_line_and_an_empty_value_clears_it(gh, capsys):  # noqa: F811
    gh.answer("issue view", {"body": "the task\nWaits for: #3\nFolders: src/\n"})
    args = parse("card", "waits", "14", "12,#13")
    assert args.run(CONFIG, args) == 0
    edit = gh.called("issue", "edit")[-1]
    assert edit[edit.index("--body") + 1] == "the task\nFolders: src/\nWaits for: #12, #13"
    args = parse("card", "waits", "14", "")
    assert args.run(CONFIG, args) == 0
    edit = gh.called("issue", "edit")[-1]
    assert edit[edit.index("--body") + 1] == "the task\nFolders: src/"
    assert capsys.readouterr().out.splitlines() == ["#14 waits for #12 and #13", "#14 waits for nothing now"]
    with pytest.raises(cli.ColonyError, match="can't wait for itself"):
        args = parse("card", "waits", "14", "14")
        args.run(CONFIG, args)


def test_take_refuses_a_card_until_what_it_waits_for_lands_on_any_branch(gh):  # noqa: F811
    body = "Folders: src/\nWaits for: #12"
    gh.answer("issue view 12", {"state": "OPEN", "stateReason": None}, once=True)
    gh.answer("pr list", [], once=True)
    with pytest.raises(cli.ColonyError, match=r"card #14 waits for #12, which has not landed: your lead starts it "
                                              r"once it lands, or clears the wait with `colony card waits 14 \"\"`"):
        cards.refuse_waiting(CONFIG, 14, body)
    # Closed as not planned is no landing either.
    gh.answer("issue view 12", {"state": "CLOSED", "stateReason": "NOT_PLANNED"}, once=True)
    with pytest.raises(cli.ColonyError, match="waits for #12"):
        cards.refuse_waiting(CONFIG, 14, body)
    # Still open, but its batch merged into an integration branch, where GitHub closes nothing: it landed.
    gh.answer("issue view 12", {"state": "OPEN", "stateReason": None}, once=True)
    gh.answer("pr list", [{"number": 90, "body": "## Cards\n- Closes #12, from `builder-1/12`",
                           "baseRefName": "integration", "headRefName": "demo/batch-b1"}], once=True)
    cards.refuse_waiting(CONFIG, 14, body)
    gh.answer("issue view 12", {"state": "CLOSED", "stateReason": "COMPLETED"}, once=True)
    cards.refuse_waiting(CONFIG, 14, body)
    cards.refuse_waiting(CONFIG, 15, "Folders: src/")  # a card that waits for nothing never asks


def test_a_wait_is_over_when_the_cards_own_branch_merged_by_its_title(gh):  # noqa: F811
    # #12 is open and named builder-1 in its title; its own branch builder-1/12 merged into an integration branch.
    gh.answer("issue view 12", {"state": "OPEN", "stateReason": None, "title": "builder-1: the base"}, once=True)
    gh.answer("pr list", [{"number": 95, "body": "", "baseRefName": "integration", "headRefName": "builder-1/12"}],
              once=True)
    cards.refuse_waiting(CONFIG, 14, "Folders: src/\nWaits for: #12")
    # Another helper's branch of the same number finishes nothing.
    gh.answer("issue view 12", {"state": "OPEN", "stateReason": None, "title": "builder-1: the base"}, once=True)
    gh.answer("pr list", [{"number": 96, "body": "", "baseRefName": "integration", "headRefName": "builder-7/12"}],
              once=True)
    with pytest.raises(cli.ColonyError, match="waits for #12"):
        cards.refuse_waiting(CONFIG, 14, "Folders: src/\nWaits for: #12")


def test_take_runs_the_waits_for_check_before_it_marks_the_card(monkeypatch):
    seen = []
    monkeypatch.setenv(cli.SESSION_ENV, "builder-2")
    monkeypatch.setenv(wait.LEAD_ENV, "ana-lead")
    monkeypatch.setattr(wait, "gh", lambda *args: json.dumps({"body": "Folders: src/\nWaits for: #12"}))
    from colony import folders, presence

    # The folder check passes: the lead's folders hold src/ (folders.why_not_take, from every lead's status).
    monkeypatch.setattr(presence, "everyone", lambda config: ([], [], ""))
    monkeypatch.setattr(folders, "why_not_take", lambda config, alive, lead, card, paths: "")
    monkeypatch.setattr(cards, "refuse_waiting", lambda config, number, body: seen.append((number, body)) or (
        _ for _ in ()).throw(cli.ColonyError("waits")))
    monkeypatch.setattr(board, "set_fields", lambda *args: pytest.fail("the card was marked"))
    with pytest.raises(cli.ColonyError, match="waits"):
        cli.take(CONFIG, Namespace(card=14))
    assert seen == [(14, "Folders: src/\nWaits for: #12")]


# The lead's queue


@pytest.fixture
def lead_env(gh, monkeypatch):  # noqa: F811
    """The lead's wait as ana-lead, with builder-2 and builder-3 live, and starts recorded instead of posted."""
    monkeypatch.setenv(wait.LEAD_ENV, "ana-lead")
    monkeypatch.setattr(cards, "live_helpers", lambda config, lead: ["builder-2", "builder-3"])
    started = []
    monkeypatch.setattr(cards, "start_card", lambda config, number, helper, title="": started.append((number, helper)))
    return started


def queue_items(changes=None):
    """#12 landed, #14 waits for it and names builder-2, #15 waits for nothing and names builder-3, and #16 is in
    progress with builder-4."""
    found = {12: item(12, "Done", state="CLOSED", reason="COMPLETED"),
             14: item(14, "To do", "builder-2: the login form", body="Folders: src/\nWaits for: #12"),
             15: item(15, "To do", "builder-3: the export button", body="Folders: web/"),
             16: item(16, "In progress", "builder-4: the api", helper="builder-4")}
    found.update(changes or {})
    return list(found.values())


def test_the_leads_wait_starts_a_card_whose_wait_is_over_and_names_the_next_queued_one(lead_env):
    lines = cards.lead_lines(CONFIG, queue_items(), NOW)
    assert lead_env == [(14, "builder-2")]
    assert lines == ["#14 started: builder-2 has it now, since #12 landed",
                     "queued: #15 builder-3: the export button is ready while builder-3 is free: hand it out now with "
                     "`colony card next --start`"]
    # The board caught up: the same queue says nothing again, until the reminder is due.
    later = queue_items({14: item(14, "In progress", "builder-2: the login form", helper="builder-2")})
    assert cards.lead_lines(CONFIG, later, NOW + timedelta(minutes=10)) == []
    assert cards.lead_lines(CONFIG, later, NOW + timedelta(minutes=61))[0].startswith("queued: #15")
    assert lead_env == [(14, "builder-2")]


def test_a_card_starts_only_for_a_free_helper_and_auto_start_all_starts_queued_cards_too(lead_env):
    busy = queue_items({16: item(16, "In progress", "builder-2: the api", helper="builder-2")})
    lines = cards.lead_lines(CONFIG, busy, NOW)
    assert lead_env == []  # builder-2 is busy with #16, so #14 waits in the queue
    assert lines == ["queued: #14 builder-2: the login form, and 1 more of your cards, is ready while builder-3 is "
                     "free: hand it out now with `colony card next --start`"]
    cards.lead_lines({**CONFIG, "cards": {"auto_start": "all"}}, queue_items(), NOW + timedelta(hours=2))
    assert lead_env == [(14, "builder-2"), (15, "builder-3")]


def test_auto_start_off_leaves_every_card_to_the_lead(lead_env):
    lines = cards.lead_lines({**CONFIG, "cards": {"auto_start": "off"}}, queue_items(), NOW)
    assert lead_env == []
    assert lines[0].startswith("queued: #14 builder-2: the login form, and 1 more of your cards, is ready while "
                               "builder-2, builder-3 are free")


def test_no_queued_line_while_the_lead_has_work_running_and_no_helper_is_free(lead_env, monkeypatch):
    monkeypatch.setattr(cards, "live_helpers", lambda config, lead: [])
    assert cards.lead_lines(CONFIG, queue_items(), NOW) == []
    idle = queue_items({16: item(16, "Done", "builder-4: the api", state="CLOSED", reason="COMPLETED")})
    assert cards.lead_lines(CONFIG, idle, NOW)[0].endswith(
        "is ready while none of your cards is in progress: hand it out now with `colony card next --start`")


def test_a_card_whose_wait_closed_without_landing_is_named_once(lead_env):
    found = queue_items({18: item(18, "To do", state="CLOSED", reason="NOT_PLANNED"),
                           19: item(19, "To do", "builder-3: the import", body="Waits for: #18, #12")})
    lines = cards.lead_lines(CONFIG, found, NOW)
    assert ("#19 waits for #18, which closed without landing: change its wait with `colony card waits 19 <cards>`, "
            "or close it") in lines
    assert not any(line.startswith("#19") for line in cards.lead_lines(CONFIG, found, NOW + timedelta(minutes=10)))


def test_another_leads_cards_and_hack_mode_give_no_queue_lines(lead_env):
    theirs = [item(15, "To do", "builder-3: x", lead="sam-lead")]
    assert cards.lead_lines(CONFIG, theirs, NOW) == []
    assert cards.lead_lines({**CONFIG, "project": {**CONFIG["project"], "mode": "hack"}}, queue_items(), NOW) == []


def node(number, status, title, body="", helper="", state="OPEN"):
    """One board item as the items query answers it, with its body."""
    values = [{"name": status, "field": {"name": "Status"}}, {"text": "ana-lead", "field": {"name": "Lead"}},
              {"text": helper, "field": {"name": "Helper"}}]
    return {"id": f"I{number}", "content": {"number": number, "url": f"u/{number}", "state": state, "title": title,
                                            "body": body}, "fieldValues": {"nodes": values}}


def test_the_stale_check_carries_the_queue_lines_after_the_stale_ones(gh, lead_env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(cli, "running_sessions", lambda config: [])
    gh.answer("project list", LISTED)
    gh.answer("items(first", items_answer(node(15, "To do", "builder-3: the export button", "Folders: web/")))
    assert cycle.stale_lines(CONFIG, NOW) == [
        "queued: #15 builder-3: the export button is ready while builder-2, builder-3 are free: hand it out now with "
        "`colony card next --start`"]
    monkeypatch.setattr(cards, "lead_lines", lambda *args: (_ for _ in ()).throw(cli.ColonyError("no presence")))
    assert cycle.stale_lines(CONFIG, NOW) == []  # a broken queue check never stops the stale lines


def test_card_next_lists_the_queue_and_start_hands_the_first_ready_card_to_a_free_helper(gh, lead_env,  # noqa: F811
                                                                                        capsys):
    gh.answer("project list", LISTED)
    gh.answer("items(first", items_answer(
        node(12, "Done", "builder-9: the base", state="CLOSED"),
        node(14, "To do", "builder-2: the login form", "Waits for: #12"),
        node(15, "To do", "builder-3: the export button", "Waits for: #17"),
        node(17, "In progress", "builder-2: the api", helper="builder-2")))
    args = parse("card", "next")
    assert args.run(CONFIG, args) == 0
    assert capsys.readouterr().out.splitlines() == [
        "ready: #14 builder-2: the login form, since #12 landed",
        "waiting: #15 builder-3: the export button: waits for #17"]
    # builder-2 is busy on #17, so the first free helper takes #14.
    args = parse("card", "next", "--start")
    assert args.run(CONFIG, args) == 0
    assert lead_env == [(14, "builder-3")]
    assert capsys.readouterr().out.strip() == "#14 started for builder-3, in place of builder-2"
    args = parse("card", "next", "--start", "--helper", "builder-7")
    assert args.run(CONFIG, args) == 0
    assert lead_env[-1] == (14, "builder-7")


def test_start_card_retitles_a_card_for_another_helper_then_posts_the_start_line_and_marks_it(gh, monkeypatch):  # noqa: F811
    posted, marked = [], []
    monkeypatch.setattr(wait, "post", lambda config, args: posted.append((args.card, args.to, args.sentence)) or
                        print(f"#{args.card} for {args.to}: start: this card (from ana-lead)"))
    monkeypatch.setattr(board, "set_fields", lambda config, number, pairs: marked.append((number, pairs)))
    printed = cards.start_card(CONFIG, 14, "builder-3", "builder-2: the login form")
    assert gh.called("issue", "edit") == [["issue", "edit", "14", "--repo", "acme/demo", "--title",
                                           "builder-3: the login form"]]
    assert posted == [(14, "builder-3", "start: this card")]
    assert marked == [(14, [("Status", "In progress"), ("Helper", "builder-3")])]
    assert printed == "#14 for builder-3: start: this card (from ana-lead)"


# The files a branch changed


@pytest.fixture
def clone(tmp_path, monkeypatch):
    """A clone of a bare origin at .../acme/demo, with main pushed and a helper's branch builder-2/41 that changed
    a.txt and added src/new.py, pushed, then one more commit not pushed and one file not committed."""
    (tmp_path / "gitconfig").write_text("")
    for key, value in {"GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.test",
                       "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.test"}.items():
        monkeypatch.setenv(key, value)
    origin = tmp_path / "acme" / "demo"
    origin.mkdir(parents=True)
    git(origin, "init", "-q", "--bare", "-b", "main")
    root = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(origin), str(root))
    (root / "a.txt").write_text("a\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    git(root, "push", "-q", "origin", "main")
    git(root, "checkout", "-qb", "builder-2/41")
    (root / "a.txt").write_text("b\n")
    (root / "src").mkdir()
    (root / "src" / "new.py").write_text("x = 1\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "the change")
    git(root, "push", "-q", "-u", "origin", "builder-2/41")
    (root / "src" / "more.py").write_text("y = 2\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "not pushed")
    (root / "notes.txt").write_text("draft\n")
    return root


MAIN = {**CONFIG, "project": {**CONFIG["project"], "base": "main"}}


def test_a_branchs_changed_files_come_from_its_diff_with_what_is_left_out_named(clone):
    count, label, text = cards.files_report(MAIN, clone, body="Folders: src/")
    assert count == 3
    assert label == "changed files: 3, from git diff origin/main...builder-2/41"
    assert text.splitlines()[:3] == ["M a.txt", "A src/more.py", "A src/new.py"]
    assert "Not committed, so not on the branch: notes.txt" in text
    assert "Not pushed: HEAD is 1 commit ahead of origin/builder-2/41: push it" in text
    assert "Outside the card's planned paths (src/): a.txt" in text
    # The pushed branch alone, as the lead reads it from origin.
    count, label, text = cards.files_report(MAIN, clone, head="origin/builder-2/41")
    assert (count, text) == (2, "M a.txt\nA src/new.py")


def test_a_helpers_done_line_carries_its_changed_files_and_other_lines_carry_none(gh, clone, monkeypatch):  # noqa: F811
    sent = []
    monkeypatch.setattr(transport, "send", lambda config, to, body, card=None: sent.append(body) or 41)
    monkeypatch.setattr(wait, "in_review", lambda config, card: None)
    monkeypatch.chdir(clone)
    monkeypatch.setenv(cli.SESSION_ENV, "builder-2")
    gh.answer("issue view 41", {"body": "Folders: src/"})
    wait.post(MAIN, Namespace(card=41, to="lead", sentence="done, builder-2/41 pushed, fast check: passed",
                              urgent=False))
    body = sent[0]
    assert body.startswith("for lead: done, builder-2/41 pushed, fast check: passed (from builder-2)")
    assert "attached: changed files: 3, from git diff origin/main...builder-2/41" in body
    assert "A src/new.py" in body and "Outside the card's planned paths (src/): a.txt" in body
    assert wait.strip_extras(body).strip() == "for lead: done, builder-2/41 pushed, fast check: passed (from builder-2)"
    wait.post(MAIN, Namespace(card=41, to="lead", sentence="question: keep it? I'm going with yes", urgent=False))
    assert "changed files" not in sent[1]


def test_a_done_line_posted_from_another_folder_reads_the_pushed_card_branch(gh, clone, monkeypatch):  # noqa: F811
    # The helper posts from the main checkout, whose HEAD is main: the list comes from origin/builder-2/41.
    git(clone, "checkout", "-q", "main")
    monkeypatch.setenv(cli.SESSION_ENV, "builder-2")
    gh.answer("issue view 41", {"body": "Folders: src/"})
    body = cards.done_files(MAIN, 41, "for lead: done (from builder-2)", cwd=clone)
    assert "attached: changed files: 2, from git diff origin/main...builder-2/41" in body
    assert "A src/new.py" in body and "src/more.py" not in body  # the commit not pushed is not on origin
    # With no such branch on origin, the folder's own HEAD is read, as before.
    assert cards.card_head(clone, "builder-2", 99) == "HEAD"
    assert cards.card_head(clone, "", 41) == "HEAD"


def test_a_done_line_outside_a_clone_of_the_repo_goes_as_it_is(clone, capsys):
    other = {**MAIN, "project": {**MAIN["project"], "repo": "acme/other"}}
    assert cards.done_files(other, 41, "for lead: done (from builder-2)", cwd=clone) == "for lead: done (from builder-2)"
    no_base = {**MAIN, "project": {**MAIN["project"], "base": "nowhere"}}
    assert cards.done_files(no_base, 41, "for lead: done", cwd=clone) == "for lead: done"
    assert "the done line goes without its changed files" in capsys.readouterr().err


# Closing the cards GitHub left open


def test_tidy_closes_cards_whose_pull_request_merged_into_any_branch_and_cards_marked_done(gh, repo, capsys):  # noqa: F811
    quiet(gh, items=[card(30, "In review", "2026-11-04 10:00 UTC"),
                     card(31, "Done", "2026-11-04 10:00 UTC"),
                     card(32, "In progress", "2026-11-04 10:00 UTC"),
                     card(33, "In review", "2026-11-04 10:00 UTC", helper="builder-1"),
                     card(34, "Done", "2026-11-04 10:00 UTC", state="CLOSED", closed="2026-11-04T00:00:00Z")])
    gh.answer("pr list", [
        {"number": 90, "headRefName": "demo/batch-b1", "baseRefName": "integration", "state": "MERGED",
         "body": "## Cards\n- Closes #30, from `builder-1/30`"},
        {"number": 91, "headRefName": "demo/batch-b2", "baseRefName": "integration", "state": "OPEN",
         "body": "- Closes #32"},
        {"number": 92, "headRefName": "builder-1/33", "baseRefName": "integration", "state": "MERGED", "body": ""}])
    assert tidy.run_tidy(CONFIG, repo) == 0
    closed = gh.called("issue", "close")
    assert closed == [
        ["issue", "close", "30", "--repo", "acme/demo", "--reason", "completed", "--comment",
         "tidy: closed: #90 merged into integration, which finishes it; GitHub closes a card by itself only when a "
         "pull request merges into the default branch"],
        ["issue", "close", "31", "--repo", "acme/demo", "--reason", "completed", "--comment",
         "tidy: closed: its Status on the board is Done"],
        ["issue", "close", "33", "--repo", "acme/demo", "--reason", "completed", "--comment",
         "tidy: closed: #92 merged into integration, which finishes it; GitHub closes a card by itself only when a "
         "pull request merges into the default branch"]]
    listed = gh.called("pr", "list")
    assert len(listed) == 1 and listed[0][listed[0].index("--json") + 1] == \
        "headRefName,state,number,baseRefName,body,mergedAt"
    out = capsys.readouterr().out
    assert "finished cards closed: 3" in out
    assert "open cards per lead: ana-lead 3 → 1" in out


def test_tidy_without_a_board_closes_the_open_cards_merged_pull_requests_finished(gh, repo, capsys):  # noqa: F811
    config = {**CONFIG, "features": {"board": False}}
    gh.answer("api repos/acme/demo", {"delete_branch_on_merge": True})
    gh.answer("issue list", [{"number": 40, "title": "builder-1: the form"}, {"number": 41, "title": "Needs Ana"},
                             {"number": 42, "title": "a bug a user reported"}])
    gh.answer("pr list", [{"number": 93, "headRefName": "builder-1/40", "baseRefName": "integration",
                           "state": "MERGED", "body": ""},
                          {"number": 94, "headRefName": "demo/batch-x", "baseRefName": "integration",
                           "state": "MERGED", "body": "Closes #41 and closes #42"}])
    assert tidy.run_tidy(config, repo, dry=True) == 0
    assert changes(gh) == []
    assert "#40: closed: #93 merged into integration" in capsys.readouterr().out
    assert tidy.run_tidy(config, repo) == 0
    assert [call[2] for call in gh.called("issue", "close")] == ["40"]  # a Needs issue and a user's bug stay open


# Docs


def test_the_docs_name_every_card_command_and_every_cards_key():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    commands = (root / "docs" / "commands.md").read_text()
    for command in ("card overlaps", "card waits", "card next", "card files"):
        assert f"`colony {command}" in commands, command
    assert "--waits-for N,N" in commands
    settings = (root / "docs" / "configuration.md").read_text()
    assert "## `[cards]`" in settings
    for key in cards.settings({}):
        assert f"`{key}`" in settings, key
    example = (root / "colony" / "colony.toml.example").read_text()
    assert "# [cards]" in example
