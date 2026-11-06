"""How a line travels: as a GitHub issue comment, the record every wait reads within its 15-second poll. `send` is
the one place that posts a line.

In hack mode every line goes to the pinned board issue, `[messages] board`, after the poster's prefix,
`[<Name>'s Claude]`.
"""
from __future__ import annotations

import os
import re

from colony import cli, wait

SECRET = re.compile(r"\b(gh[pousr]_\w{20,}|github_pat_\w{20,}|sk-[\w-]{20,}|xox[abprs]-[\w-]{10,}|AKIA[0-9A-Z]{16}"
                    r"|AIza[\w-]{35})|-----BEGIN [A-Z ]*PRIVATE KEY")
SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|KEY", re.I)


def check_transport(config: dict) -> None:
    """Refuse a [messages] transport other than "github": the Agent Relay transport is gone, and every line goes by
    GitHub. A "github" line from an older config is fine."""
    name = config.get("messages", {}).get("transport", "github")
    if name != "github":
        raise cli.ColonyError(f"[messages] transport = {name!r} is gone: every line goes by GitHub now, so delete the "
                              f"line from {cli.DIR}/{cli.CONFIG_NAME}")


def holds_secret(text: str) -> str | None:
    """What in the text looks like a secret, a token's shape or a secret env var's value (named, never shown)."""
    if SECRET.search(text):
        return "a token"
    for key, value in os.environ.items():
        if SECRET_NAME.search(key) and len(value) >= 16 and value in text:
            return f"the value of ${key}"
    return None


def board_issue(config: dict) -> int:
    """The hack board's issue number, [messages] board, which setup writes when it opens and pins the issue."""
    number = config.get("messages", {}).get("board")
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise cli.ColonyError("hack mode posts every line on the board issue: set [messages] board to its number in "
                              f"{cli.DIR}/{cli.CONFIG_NAME} (setup opens and pins it)")
    return number


def prefix(config: dict) -> str:
    """A board post's prefix, `[<Name>'s Claude]`, for this session's person ($COLONY_PERSON, else the one person)."""
    person = os.environ.get(cli.PERSON_ENV) or cli.default_person(config)
    return f"[{wait.display_name(config, person)}'s {wait.AGENT}]"


def send(config: dict, to: str, line: str, card: int | None = None) -> int:
    """Post `line` for `to` (a session, `@<login>` or `@all`) on issue `card`, or on the coordination issue when None,
    and return the issue. In hack mode the line goes to the board issue instead, after the poster's prefix."""
    check_transport(config)
    why = holds_secret(line)
    if why:
        raise cli.ColonyError(f"a line never carries a secret, and this one holds {why}")
    repo = config["project"]["repo"]
    if wait.hack(config):
        number, body = board_issue(config), f"{prefix(config)} {line}"
    else:
        number = int(card) if card is not None else wait.coordination_issue(repo, config["project"]["name"])
        body = line
    wait.gh("issue", "comment", str(number), "--repo", repo, "--body", body)
    return number
