"""Progress: each card's predicted minutes against the time it has taken, the work left, and a warning when a card runs
past its prediction.

A card's prediction is the `predicted: S, 20 min` line the lead writes in it, and its time runs from the lead's
`start: this card` line to the helper's `done` line, or to now (cycle.card_window). The cards are the board's, by
their Lead, Status and Helper. Each card's issue is read once per change: ~/.colony/<project>/progress.json keeps
what was read, by the issue's last change.

`colony progress` lists the lead's open cards, or every lead's with --all, and estimates the minutes left and when the
work ends, from the predictions and the helpers working (estimate). The lead's wait warns once when a card In progress
passes `[watch] late_after` times its prediction, and once more at twice that (late_check). `colony watch` and the
status page show the same.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from colony import cli, wait

CACHE = "progress"  # ~/.colony/<project>/progress.json
LATE_EVERY = 10 * 60  # the lead's wait reads the board for late cards this often
WATCHED = ("To do", "In progress", "In review", "Done")


@dataclass
class Card:
    """One card as progress sees it."""

    number: int
    title: str
    status: str
    helper: str = ""
    lead: str = ""
    size: str = ""
    predicted: float | None = None  # minutes
    started: float | None = None  # Unix time of the start line
    ended: float | None = None  # Unix time of the done line

    def taken(self, now: float) -> float | None:
        """Minutes from its start line to its done line, or to now; None before it started."""
        if self.started is None:
            return None
        return max(0.0, ((self.ended or now) - self.started) / 60)


def window_of(config: dict, number: int) -> dict:
    """What a card's issue says of its progress: its prediction and size, and when its start and done lines came."""
    from colony import cycle

    issue = json.loads(wait.gh("issue", "view", str(number), "--repo", config["project"]["repo"], "--json",
                               "title,body,comments"))
    window = cycle.card_window(issue)
    guess = window.prediction
    return {"predicted": guess.minutes if guess else None, "size": guess.size if guess else "",
            "started": window.start.timestamp() if window.start else None,
            "ended": window.end.timestamp() if window.end and window.ends_by == "done line" else None}


def survey(config: dict, lead: str | None = None, read=None) -> list[Card]:
    """The board's cards for a lead, or for every lead with None: To do, In progress, In review and Done. An open
    card's issue is read when it changed since the last reading (`read` is window_of; tests pass their own)."""
    from colony import board

    read = read or window_of
    found = board.find_board(config)
    if found is None:
        return []
    path = wait.state_path(config["project"]["name"], CACHE)
    cache = wait.read_json(path, {})
    cache = cache if isinstance(cache, dict) else {}
    cards, kept = [], {}
    for item in board.items(found):
        number, status = item.get("number"), board.field_value(item, "Status")
        if not isinstance(number, int) or status not in WATCHED:
            continue
        owner = board.field_value(item, "Lead").lower()
        if lead and owner != lead.lower():
            continue
        card = Card(number, str(item.get("title") or ""), status, board.field_value(item, "Helper").lower(), owner,
                    board.field_value(item, "Size"))
        if status != "Done":
            held = cache.get(str(number))
            if not isinstance(held, dict) or held.get("updated") != item.get("updatedAt"):
                held = {"updated": item.get("updatedAt"), **read(config, number)}
            kept[str(number)] = held
            card.predicted, card.started, card.ended = held.get("predicted"), held.get("started"), held.get("ended")
            card.size = card.size or str(held.get("size") or "")
        cards.append(card)
    wait.write_json(path, kept)
    return sorted(cards, key=lambda card: (WATCHED.index(card.status), card.number))


def estimate(cards: list[Card], helpers: int, now: float) -> dict:
    """The counts by status, the predicted minutes left, the cards past their prediction or with none, and when the
    work ends with `helpers` working at once (at least one)."""
    counts = {status: sum(card.status == status for card in cards) for status in WATCHED}
    left, late, unknown = 0.0, [], []
    for card in cards:
        if card.status in ("In review", "Done"):
            continue
        if card.predicted is None:
            unknown.append(card.number)
            continue
        taken = card.taken(now) or 0.0
        if card.status == "In progress" and taken > card.predicted:
            late.append(card.number)
            continue
        left += card.predicted - (taken if card.status == "In progress" else 0.0)
    open_cards = counts["To do"] + counts["In progress"]
    working = max(1, min(helpers, open_cards)) if open_cards else 1
    ends = now + left / working * 60 if left else None
    return {"counts": counts, "left": left, "working": working, "ends": ends, "late": late, "unknown": unknown}


def summary(cards: list[Card], helpers: int, now: float) -> str:
    """The progress in two or three plain sentences."""
    if not cards:
        return "Progress: no cards on the board."
    found = estimate(cards, helpers, now)
    counts = found["counts"]
    text = (f"Progress: {counts['Done']} done, {counts['In review']} in review, {counts['In progress']} in progress, "
            f"{counts['To do']} to do.")
    if found["left"]:
        when = datetime.fromtimestamp(found["ends"], timezone.utc).strftime("%H:%M UTC")
        text += (f" About {found['left']:.0f} minutes of predicted work is left; with {found['working']} "
                 f"{'helper' if found['working'] == 1 else 'helpers'} at once, it ends near {when}.")
    elif counts["To do"] + counts["In progress"]:
        text += " No predicted work is left to count."
    notes = []
    if found["late"]:
        notes.append(f"{', '.join(f'#{n}' for n in found['late'])} {'is' if len(found['late']) == 1 else 'are'} past "
                     "the prediction")
    if found["unknown"]:
        notes.append(f"{', '.join(f'#{n}' for n in found['unknown'])} {'has' if len(found['unknown']) == 1 else 'have'}"
                     " no prediction")
    if notes:
        text += f" {'; '.join(notes).capitalize()}, so the estimate is low."
    return text


def card_line(card: Card, now: float) -> str:
    """One card's line: who works on it, and its minutes against its prediction."""
    taken = card.taken(now)
    who = f" ({card.helper})" if card.helper else ""
    if card.predicted is None:
        time_ = "no prediction" + (f", {taken:.0f} min so far" if taken is not None else "")
    elif taken is None:
        time_ = f"predicted {card.predicted:g} min, not started"
    else:
        verb = "took" if card.ended else "so far"
        time_ = f"{taken:.0f} of {card.predicted:g} predicted min {verb}"
        if taken > card.predicted and not card.ended:
            time_ += ", past its prediction"
    return f"#{card.number}{who}, {card.status}: {time_}. {card.title}"


def cards_or_note(config: dict, lead: str | None = None) -> tuple[list[Card], str | None]:
    """The cards, or none with why they can't be read: the board is off, missing, or unreadable."""
    if not config.get("features", {}).get("board", True):
        return [], "Progress: the card board is off in this mode."
    try:
        return survey(config, lead), None
    except (cli.ColonyError, OSError, ValueError, KeyError) as e:
        return [], f"Progress: unknown, because the board was not read: {e}"


def helpers_on(cards: list[Card]) -> int:
    """How many helpers work on the cards now: the distinct helpers of the cards In progress, at least one."""
    return max(1, len({card.helper for card in cards if card.status == "In progress" and card.helper}))


def late_check(config: dict, lead: str):
    """The lead's check for its cards past their prediction, every LATE_EVERY after the first: one line per card when
    it passes `[watch] late_after` times its prediction, and one more at twice that. The lines can wait for the digest. It
    returns [] when the board is off or missing, and says once on stderr when the board can't be read."""
    def check(state: dict, now: float) -> list[str]:
        from colony import watch

        held = state.setdefault("late", {})
        if "at" not in held:  # the first look: the board is read one interval later, never in a short wait
            held["at"] = now
            return []
        if not config.get("features", {}).get("board", True) or now - float(held["at"]) < LATE_EVERY:
            return []
        held["at"] = now
        try:
            cards = survey(config, lead)
        except (cli.ColonyError, OSError, ValueError, KeyError) as e:
            if str(e) != held.get("error"):
                print(f"{cli.NAME} wait: the cards' progress was not read: {e}", file=sys.stderr)
            held["error"] = str(e)
            return []
        held.pop("error", None)
        factor, lines = watch.settings(config).late_after, []
        raised = held.setdefault("raised", {})
        for card in cards:
            taken = card.taken(now)
            if card.status != "In progress" or not card.predicted or taken is None or card.ended:
                continue
            level = 2 if taken >= 2 * factor * card.predicted else 1 if taken >= factor * card.predicted else 0
            key = f"{card.number}:{card.started}"
            if not level or raised.get(key, 0) >= level:
                continue
            raised[key] = level
            who = card.helper or "its helper"
            if level == 1:
                lines.append(f"#{card.number} late: {who} has taken {taken:.0f} minutes on a card predicted at "
                             f"{card.predicted:g}")
            else:
                lines.append(f"#{card.number} late: {who} has taken {taken:.0f} minutes, past twice its prediction "
                             f"of {card.predicted:g}: ask what holds it up, and split it if it is bigger than it looked")
        held["raised"] = {key: level for key, level in raised.items()
                          if any(key == f"{card.number}:{card.started}" for card in cards)}
        return lines
    return check


def command(config: dict, args) -> int:
    """`colony progress [--all] [--json]`: the lead's cards, or every lead's, with their minutes against their
    predictions, and when the work left ends."""
    lead = None if args.all else wait.lead_name(config, args)
    cards, why = cards_or_note(config, lead)
    now = time.time()
    if args.json:
        print(json.dumps({"cards": [asdict(card) for card in cards], "note": why,
                          **({"estimate": estimate(cards, helpers_on(cards), now)} if cards else {})}))
        return 0
    if why:
        print(why)
        return 0
    for card in cards:
        print(f"- {card_line(card, now)}")
    print(summary(cards, helpers_on(cards), now))
    return 0


def register(sub) -> None:
    """`colony progress`, which watch.register adds."""
    p = sub.add_parser("progress", help="the cards' minutes against their predictions, and when the work left ends")
    p.add_argument("--all", action="store_true", help="every lead's cards, not only yours")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.add_argument("--person", help="whose lead this is, when $COLONY_PERSON is not set")
    p.set_defaults(run=command)
