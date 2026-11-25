"""The status page: one pinned issue, `Colony: status`, whose body the watchdog keeps current, so a person has one link
that opens on a phone.

The page shows what is worth a look, the cards' progress against their predictions with when the work left ends, and
each lead and helper with what it does and why, its last report and its helper agents. It holds what the status
comments already hold, plus card numbers and titles: never a path on a computer, a command's output, or a secret.

The watchdog writes it every `[watch] page_minutes` while `[watch] page` is true (keep), and only when it changed,
or every REFRESH so a reader sees it is alive. `colony watch --page` writes it at once and prints its link. The issue
is made the first time, pinned when the repo has room for one more pinned issue, and found again by its title.
~/.colony/<project>/status-page.json remembers its number and what was written last.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

from colony import cli, wait

TITLE = f"{cli.NAME.capitalize()}: status"
BODY_MAX = 60_000  # GitHub takes 65,536 characters in an issue's body
REFRESH = 30 * 60  # an unchanged page is still stamped this often
CARDS_SHOWN = 40
STAMP_LINE = "Updated "


def cell(text) -> str:
    """Text for a Markdown table cell: one line, with its bars escaped."""
    return " ".join(str(text or "").split()).replace("|", "\\|") or "-"


def render(config: dict, team: dict, s, now: float, cards: list | None = None, note: str | None = None) -> str:
    """The page's Markdown, from the team the watch sees (watch.team_now) and the cards (progress.cards_or_note)."""
    from colony import presence, progress, watch

    cards = cards or []
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# {config['project']['name']}: team status", "",
             f"{STAMP_LINE}{stamp} from {presence.computer()}. While a watchdog runs, this page changes at most every "
             f"{s.page_minutes:g} minutes, and is stamped at least every {REFRESH // 60} minutes.", "",
             "## Worth a look", ""]
    found = [item for member in team.values() for item in watch.findings(member, s, now, team)]
    lines += [f"- {line}" for line in watch.lines_of(found, s)] or \
        ["Nothing: every session works, waits on purpose, or is done."]
    lines += ["", "## Progress", "", note or progress.summary(cards, progress.helpers_on(cards), now)]
    if cards:
        lines += ["", "| Card | Helper | Status | Predicted | Time | Title |", "| --- | --- | --- | --- | --- | --- |"]
        for card in cards[:CARDS_SHOWN]:
            taken = card.taken(now)
            time_ = "-" if taken is None else f"{taken:.0f} min" + (
                ", past its prediction" if card.predicted and taken > card.predicted and not card.ended else "")
            predicted = "-" if card.predicted is None else f"{card.predicted:g} min"
            lines.append(f"| #{card.number} | {cell(card.helper)} | {cell(card.status)} | {predicted} | {time_} | "
                         f"{cell(card.title[:80])} |")
        if len(cards) > CARDS_SHOWN:
            lines.append(f"\n{len(cards) - CARDS_SHOWN} more cards are on the board.")
    for kind, title in (("lead", "Leads"), ("helper", "Helpers")):
        group = sorted((m for m in team.values() if m.kind == kind), key=lambda m: (m.lead, m.name))
        lines += ["", f"## {title}", ""]
        if not group:
            lines.append("None seen.")
            continue
        lines += ["| Name | Lead | Doing | Why | Last report | Helper agents | Computer |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for member in group:
            word, detail = watch.standing(member, s, now, team)
            report = f"{watch.minutes(now - member.reported_at)} ago: {member.report}" if member.reported_at else "-"
            agents = "; ".join(f"\"{a['what']}\" for {watch.minutes(now - a.get('started', now))}"
                               for a in member.agents) or "-"
            lines.append(f"| {cell(member.name)} | {cell(member.lead)} | {cell(word)} | {cell(detail)} | {cell(report)} "
                         f"| {cell(agents)} | {cell(member.computer)} |")
    text = "\n".join(lines) + "\n"
    return text if len(text) <= BODY_MAX else text[:BODY_MAX - 60] + "\n\nThe page was cut at GitHub's size limit.\n"


def digest(text: str) -> str:
    """What the page says, without its stamp line, as a short hash: the same hash means nothing changed."""
    body = "\n".join(line for line in text.splitlines() if not line.startswith(STAMP_LINE))
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def state_path(config: dict):
    return wait.state_path(config["project"]["name"], "status-page")


def issue(config: dict, held: dict) -> int:
    """The status issue's number: remembered, else found by its title, else made and pinned."""
    repo = config["project"]["repo"]
    known = held.get("number")
    if isinstance(known, int):
        return known
    listed = json.loads(wait.gh("issue", "list", "--repo", repo, "--state", "open", "--search", f'"{TITLE}" in:title',
                                "--json", "number,title", "--limit", "20") or "[]")
    numbers = sorted(item["number"] for item in listed if item.get("title") == TITLE)
    if numbers:
        return numbers[-1]
    url = wait.gh("issue", "create", "--repo", repo, "--title", TITLE, "--body",
                  f"The watchdog writes the team's status here. `{cli.NAME} watch --page` writes it now.")
    number = int(url.strip().rstrip("/").rsplit("/", 1)[-1])
    try:
        wait.gh("issue", "pin", str(number), "--repo", repo)
    except wait.GhError:
        pass  # a repo pins at most three issues: the page works unpinned, by its link
    return number


def publish(config: dict, text: str, force: bool = False, now: float | None = None) -> str:
    """Write the page into the status issue's body when it changed, or every REFRESH, or with `force`; return its
    link."""
    now = time.time() if now is None else now
    repo, path = config["project"]["repo"], state_path(config)
    held = wait.read_json(path, {})
    held = held if isinstance(held, dict) else {}
    number = issue(config, held)
    url = f"https://github.com/{repo}/issues/{number}"
    fresh = digest(text)
    if not force and held.get("number") == number and held.get("digest") == fresh and \
            now - float(held.get("at") or 0) < REFRESH:
        return url
    try:
        wait.gh("api", "-X", "PATCH", f"repos/{repo}/issues/{number}", "-f", f"body={text}")
    except wait.GhError:
        if held.get("number") != number:
            raise
        held.pop("number")  # closed or gone: make or find it again next time
        wait.write_json(path, held)
        raise
    wait.write_json(path, {"number": number, "digest": fresh, "at": now})
    return url


def keep(config: dict, s, now: float | None = None) -> str:
    """The watchdog's part: write the page when `[watch] page` is on and `page_minutes` passed since the last try.
    Returns a line for its log when it wrote or failed, else ""."""
    from colony import progress, watch

    now = time.time() if now is None else now
    if not s.page:
        return ""
    path = state_path(config).with_name("status-page-tried.json")
    tried = wait.read_json(path, 0)
    if isinstance(tried, (int, float)) and now - tried < s.page_minutes * 60:
        return ""
    wait.write_json(path, now)
    try:
        team, _ = watch.team_now(config, now)
        cards, note = progress.cards_or_note(config)
        before = wait.read_json(state_path(config), {})
        url = publish(config, render(config, team, s, now, cards, note), now=now)
        after = wait.read_json(state_path(config), {})
        return f"the status page changed: {url}" if after != before else ""
    except (cli.ColonyError, OSError, ValueError, KeyError) as e:
        return f"the status page was not written: {e}"
