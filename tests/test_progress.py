"""Tests for progress: each card's minutes against its prediction, the work left and when it ends, and the lead's
warning when a card runs past its prediction."""
import time
from argparse import Namespace

import pytest

from colony import board, progress

CONFIG = {"project": {"name": "demo", "repo": "acme/demo"}, "accounts": {}}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def item(number, status, lead="ana-main-lead", helper="", updated="2026-11-24T10:00:00Z", size="S"):
    return {"id": f"I{number}", "number": number, "title": f"card {number}", "state": "OPEN", "updatedAt": updated,
            "fields": {"status": status, "lead": lead, "helper": helper, "size": size}}


@pytest.fixture
def cards(home, monkeypatch):
    """A board with a lead's five cards and another lead's one, and the issues' predictions and start times."""
    now = time.time()
    windows = {41: {"predicted": 20.0, "size": "S", "started": now - 30 * 60, "ended": None},
               42: {"predicted": 60.0, "size": "M", "started": now - 15 * 60, "ended": None},
               43: {"predicted": 30.0, "size": "S", "started": None, "ended": None},
               44: {"predicted": None, "size": "", "started": None, "ended": None},
               45: {"predicted": 20.0, "size": "S", "started": now - 60 * 60, "ended": now - 40 * 60}}
    reads = []

    def read(config, number):
        reads.append(number)
        return windows[number]
    items = [item(41, "In progress", helper="builder-2"), item(42, "In progress", helper="builder-3"),
             item(43, "To do"), item(44, "To do"), item(45, "In review", helper="builder-2"), item(46, "Done"),
             item(47, "In progress", lead="ben-main-lead")]
    monkeypatch.setattr(board, "find_board", lambda config: {"id": "P1"})
    monkeypatch.setattr(board, "items", lambda found: items)
    monkeypatch.setattr(progress, "window_of", read)
    return items, windows, reads


def test_a_leads_cards_show_their_minutes_against_their_predictions(cards):
    found = progress.survey(CONFIG, "ana-main-lead")
    assert [(c.number, c.status) for c in found] == [(43, "To do"), (44, "To do"), (41, "In progress"),
                                                    (42, "In progress"), (45, "In review"), (46, "Done")]
    now = time.time()
    line = progress.card_line(next(c for c in found if c.number == 41), now)
    assert line == "#41 (builder-2), In progress: 30 of 20 predicted min so far, past its prediction. card 41"
    assert progress.card_line(next(c for c in found if c.number == 45), now).startswith(
        "#45 (builder-2), In review: 20 of 20 predicted min took.")


def test_the_estimate_counts_the_work_left_and_names_what_makes_it_low(cards):
    found, now = progress.survey(CONFIG, "ana-main-lead"), time.time()
    estimate = progress.estimate(found, helpers=2, now=now)
    assert estimate["counts"] == {"To do": 2, "In progress": 2, "In review": 1, "Done": 1}
    assert round(estimate["left"]) == 75 and estimate["late"] == [41] and estimate["unknown"] == [44]
    assert abs((estimate["ends"] - now) / 60 - 37.5) < 0.1  # 75 minutes over 2 helpers
    text = progress.summary(found, 2, now)
    assert text.startswith("Progress: 1 done, 1 in review, 2 in progress, 2 to do. About 75 minutes of predicted work "
                           "is left; with 2 helpers at once, it ends near ")
    assert text.endswith("#41 is past the prediction; #44 has no prediction, so the estimate is low.")


def test_an_issue_is_read_again_only_when_it_changed(cards):
    items, _, reads = cards
    progress.survey(CONFIG, "ana-main-lead")
    progress.survey(CONFIG, "ana-main-lead")
    assert sorted(reads) == [41, 42, 43, 44, 45]  # Done cards are never read, the rest once
    items[0]["updatedAt"] = "2026-11-24T11:00:00Z"
    progress.survey(CONFIG, "ana-main-lead")
    assert sorted(reads) == [41, 41, 42, 43, 44, 45]


def test_the_lead_hears_once_past_the_prediction_and_once_past_twice_it(cards):
    check, state = progress.late_check(CONFIG, "ana-main-lead"), {}
    now = time.time()
    assert check(state, now) == []  # the first look only starts the clock
    state["late"]["at"] = 0
    assert check(state, now) == ["#41 late: builder-2 has taken 30 minutes on a card predicted at 20"]
    state["late"]["at"] = 0
    assert check(state, now) == []
    state["late"]["at"] = 0
    assert check(state, now + 15 * 60) == ["#41 late: builder-2 has taken 45 minutes, past twice its prediction of 20: "
                                           "ask what holds it up, and split it if it is bigger than it looked"]
    state["late"]["at"] = 0
    assert check(state, now + 30 * 60) == []


def test_progress_says_why_when_there_are_no_cards(home, monkeypatch, capsys):
    assert progress.cards_or_note({**CONFIG, "features": {"board": False}}) == \
        ([], "Progress: the card board is off in this mode.")
    monkeypatch.setattr(board, "find_board", lambda config: None)
    assert progress.command(CONFIG, Namespace(all=True, json=False, person=None)) == 0
    assert capsys.readouterr().out == "Progress: no cards on the board.\n"
