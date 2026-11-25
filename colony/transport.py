"""How a line travels: as a GitHub issue comment, the record every wait reads within its 15-second poll. `send` is
the one place that posts a line. It returns the issue's number, which also carries the comment's address (Sent).

In hack mode every line goes to the pinned board issue, `[messages] board`, after the poster's prefix,
`[<Name>'s Claude]`. A long board moves to a fresh pinned issue first (tidy.keep_board).

A comment can carry two hidden parts after its lines, which no wait reads as a line (wait.strip_extras): a file's
text, attached under the lines in a folded block (attachment), so a long note travels on GitHub instead of as a path
on one computer; and the sender's note (sender_note), which says which session posted the lines and whether a start
line asks for an acknowledgement.
"""
from __future__ import annotations

import json
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


COMMENT_MAX = 65000  # GitHub keeps a comment of at most 65,536 characters
COMMENT_URL = re.compile(r"#issuecomment-(\d+)")


class Sent(int):
    """Where a comment went: the issue's number, which is what every caller reads, with the comment's address as gh
    printed it ("" when it printed none) and the comment's id. Read the two with getattr, since a test's stand-in for
    `send` returns a plain number."""

    def __new__(cls, number: int, url: str = "", comment: int | None = None):
        sent = super().__new__(cls, number)
        sent.url, sent.comment = url, comment
        return sent


def send(config: dict, to: str, line: str, card: int | None = None) -> Sent:
    """Post `line` for `to` (a session, `@<login>` or `@all`) on issue `card`, or on the coordination issue when None,
    and return where it went. In hack mode the line goes to the board issue instead, after the poster's prefix.
    `line` may hold several lines, an attachment and the sender's note: it goes out as one comment, whole or not at
    all."""
    check_transport(config)
    why = holds_secret(line)
    if why:
        raise cli.ColonyError(f"a line never carries a secret, and this one holds {why}")
    repo = config["project"]["repo"]
    if wait.hack(config):
        from colony import tidy

        number, body = tidy.keep_board(config), f"{prefix(config)} {line}"
    else:
        number = int(card) if card is not None else wait.coordination_issue(repo, config["project"]["name"])
        body = line
    if len(body) > COMMENT_MAX:
        raise cli.ColonyError(f"a comment holds at most {COMMENT_MAX} characters, and this one has {len(body)}: attach "
                              "a shorter file, or share it with a link")
    out = wait.gh("issue", "comment", str(number), "--repo", repo, "--body", body).strip()
    url = out.splitlines()[-1].strip() if out else ""
    url = url if url.startswith("http") else ""
    found = COMMENT_URL.search(url)
    return Sent(number, url, int(found[1]) if found else None)


ATTACH_MAX = 60000  # an attachment's characters, so the comment stays under GitHub's limit


def attachment(name: str, text: str) -> str:
    """A file's text as a comment's folded attachment: after the marker wait.strip_extras cuts at, so no line in the
    file ever reaches a wait as a line, and in a fence longer than any run of tildes in the text. The text's `<!--`
    and `-->` become `&lt;!--` and `--&gt;`, so it can never open or close a hidden part of the comment, such as a
    marker or a sender's note."""
    if len(text) > ATTACH_MAX:
        raise cli.ColonyError(f"an attachment holds at most {ATTACH_MAX} characters, and {name} has {len(text)}: "
                              "attach a part of it, or share it with a link")
    text = text.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    runs = re.findall(r"~{4,}", text)
    fence = "~" * max([4, *(len(run) + 1 for run in runs)])
    label = re.sub(r"[<>&]", "_", " ".join(name.split())[:80]) or "a file"
    return (f"<!-- {wait.ATTACHED} -->\n<details><summary>attached: {label}</summary>\n\n{fence}text\n{text}\n"
            f"{fence}\n\n</details>\n<!-- /{wait.ATTACHED} -->")


def sender_note(data: dict) -> str:
    """The sender's hidden note, after a comment's lines: a JSON object wait.note_of reads back."""
    return f"<!-- {wait.NOTE} {json.dumps(data, separators=(',', ':'))} -->"
