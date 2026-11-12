"""The demo's clock in hack mode. `[hack] demo`, the demo's date and time with its time zone, sets a countdown that
`colony who` and `colony status` print first, and the freeze, `[hack] freeze_minutes` before it (60 by default).
When the freeze starts, the team lead's wait, `[hack] team_lead` (else the first of `[people] logins`), posts
`@all freeze: ...` on the board once, so no one has to remember it an hour before the demo.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone

from colony import cli, wait

FREEZE_MINUTES = 60
ZONE_GAP = re.compile(r"\s+([+-]\d{2}:?\d{2}|Z)$")  # "17:00 -08:00": the space before the zone


def demo_at(config: dict) -> datetime | None:
    """[hack] demo as a time with its zone, or None when it is unset."""
    text = str(config.get("hack", {}).get("demo") or "").strip()
    if not text:
        return None
    try:
        at = datetime.fromisoformat(ZONE_GAP.sub(r"\1", text).replace("Z", "+00:00"))
    except ValueError:
        raise cli.ColonyError(f"[hack] demo = {text!r} is not a time, such as 2026-11-08 17:00 -08:00") from None
    if at.tzinfo is None:
        raise cli.ColonyError(f"[hack] demo = {text!r} needs its time zone, such as 2026-11-08 17:00 -08:00")
    return at


def freeze_at(config: dict, at: datetime) -> datetime:
    """When the freeze starts: [hack] freeze_minutes before the demo."""
    return at - timedelta(minutes=int(config.get("hack", {}).get("freeze_minutes", FREEZE_MINUTES)))


def clock(at: datetime) -> str:
    """A time as the demo's zone gives it, such as 17:00 UTC-08:00."""
    zone = at.strftime("%z") or "+0000"
    return f"{at:%H:%M} UTC{zone[:3]}:{zone[3:]}"


def span(seconds: float) -> str:
    """A time left, such as 3 h 20 min or 45 min."""
    minutes = max(0, int(seconds // 60))
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


def countdown(config: dict, now: datetime | None = None) -> str:
    """One line on the time left before the demo and the freeze, or "" when [hack] demo is unset."""
    at = demo_at(config)
    if at is None:
        return ""
    now = now or datetime.now(timezone.utc)
    freeze = freeze_at(config, at)
    if now < freeze:
        return (f"Demo at {clock(at)}, in {span((at - now).total_seconds())}; the freeze starts at "
                f"{freeze.astimezone(at.tzinfo):%H:%M}, in {span((freeze - now).total_seconds())}.")
    if now < at:
        return f"Freeze: the demo at {clock(at)} is in {span((at - now).total_seconds())}, so only fixes from now."
    return f"The demo time, {clock(at)}, has passed."


def team_lead(config: dict) -> str:
    """The person whose lead posts the freeze: [hack] team_lead, else the first of [people] logins."""
    named = str(config.get("hack", {}).get("team_lead") or "")
    logins = config.get("people", {}).get("logins") or []
    return (named or (str(logins[0]) if logins else "")).lower()


def freeze_check(config: dict, person: str):
    """The callable the team lead's wait runs at each poll: once the freeze starts, and before the demo, it posts
    `@all freeze: ...` on the board, once per demo time, and never raises."""
    from colony import transport

    def run(now: datetime | None = None) -> None:
        try:
            at = demo_at(config)
        except cli.ColonyError:
            return
        if at is None or not person or person.lower() != team_lead(config):
            return
        now = now or datetime.now(timezone.utc)
        if not freeze_at(config, at) <= now < at:
            return
        path = wait.state_path(config["project"]["name"], "freeze")
        if wait.read_json(path, {}).get("posted") == at.isoformat():
            return
        line = (f"@{wait.ALL} freeze: the demo is at {clock(at)}, in {span((at - now).total_seconds())}: only fixes "
                "from now. Merge what is ready, then rehearse on the last [merged] build")
        try:
            transport.send(config, f"@{wait.ALL}", line)
        except cli.ColonyError as e:
            print(f"{cli.NAME} wait: the freeze didn't go on the board, the next poll tries again: {e}", file=sys.stderr)
            return
        wait.write_json(path, {"posted": at.isoformat()})
    return run
