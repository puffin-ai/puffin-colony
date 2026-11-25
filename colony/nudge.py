"""`colony nudge` and the nudge after a post: wake an idle session on this computer through cmux.

A session whose wait isn't running reads no line until its person types something. A nudge types one short pointer
into the recipient's cmux workspace and presses Enter: the prompt hook then shows the session its unread lines. The
nudge reads the screen afterwards to confirm the pointer left the prompt box, and presses Enter again, up to
CONFIRM_TRIES times, when it still sits there unsent. cmux refuses to type over a draft someone is writing, or into a
question that waits, and the nudge says so.

The recipient's workspace is the one titled with its name, or `<project>-<name>`, as `colony open` names it, or the
one --workspace names. Without cmux, or with no such workspace on this computer, there is no nudge, and the line
still went out. [messages] nudge sets when a post nudges by itself: "off" (the default), "auto" for a recipient
whose wait isn't running on this computer, or "always". --nudge on a post nudges once.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
import uuid

from colony import cli

MODES = ("off", "auto", "always")
CONFIRM_TRIES = 3
PAUSE = 1.0  # seconds between pressing Enter and reading the screen
RUNNING = 60  # a wait whose last poll is under this many seconds old is running, as the prompt hook reads it
RULE = re.compile(r"^\s*[╭╰]?[─━]{10,}")  # a border line of an agent's prompt box


def mode(config: dict) -> str:
    """[messages] nudge: off, auto or always. An unknown value counts as off, and says so."""
    value = str((config.get("messages") or {}).get("nudge", "off")).lower()
    if value not in MODES:
        print(f"{cli.NAME}: [messages] nudge is off, auto or always, not {value!r}, so no nudge", file=sys.stderr)
        return "off"
    return value


def cmux(command: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([command, *args], capture_output=True, text=True, timeout=15)


def workspaces(command: str) -> list[tuple[str, str]]:
    """cmux's workspaces on this computer, as (ref, title), from `cmux workspace list`."""
    run = cmux(command, "workspace", "list")
    if run.returncode:
        raise cli.ColonyError(f"cmux doesn't take commands from here: {run.stderr.strip()[:200]}")
    found = []
    for row in run.stdout.splitlines():
        words = row.strip().lstrip("*").split(None, 1)
        if len(words) == 2 and words[0].startswith("workspace:"):
            found.append((words[0], re.sub(r"\s*\[selected\]\s*$", "", words[1]).strip()))
    return found


def find(project: str, name: str, found: list[tuple[str, str]]) -> str | None:
    """The workspace titled with the session's name, or `<project>-<name>`, ignoring case."""
    wanted = {name.lower(), f"{project}-{name}".lower()}
    return next((ref for ref, title in found if title.lower() in wanted), None)


def pointer(name: str, card: int | None, mark: str) -> str:
    """The words a nudge types: one line, with a mark that tells it apart on the screen."""
    on = f" on #{card}" if card else ""
    return f"[{cli.NAME} nudge {mark}] A line for {name} waits{on}: read your unread lines and act on them."


def unsent(screen: str, mark: str) -> bool:
    """Whether the nudge still sits in the prompt box: between the box's last two border lines, or with no border
    found, in the last three lines with text."""
    lines = screen.splitlines()
    rules = [at for at, line in enumerate(lines) if RULE.match(line)]
    box = lines[rules[-2] + 1:rules[-1]] if len(rules) >= 2 else [line for line in lines if line.strip()][-3:]
    return any(mark in line for line in box)


def nudge(config: dict, name: str, card: int | None = None, workspace: str = "", pause: float = PAUSE,
          sleep=time.sleep) -> tuple[bool, str]:
    """Type the pointer into `name`'s cmux workspace, press Enter, and confirm it was submitted. Returns whether it
    was, and what happened, in words."""
    command = cli.cmux_command()
    if command is None:
        return False, "cmux isn't on this computer"
    try:
        found = workspaces(command)
    except (cli.ColonyError, OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    ref = workspace or find(config["project"]["name"], name, found)
    if not ref:
        return False, f"no cmux workspace on this computer is named {name} or {config['project']['name']}-{name}"
    mark = uuid.uuid4().hex[:6]
    try:
        typed = cmux(command, "send", "--workspace", ref, "--", pointer(name, card, mark))
        if typed.returncode:
            return False, (f"cmux didn't type into {ref}, as when its prompt holds a draft or a question waits there: "
                           f"{typed.stderr.strip()[:200]}")
        for _ in range(CONFIRM_TRIES):
            cmux(command, "send-key", "--workspace", ref, "enter")
            sleep(pause)
            screen = cmux(command, "read-screen", "--workspace", ref, "--lines", "40")
            if screen.returncode:
                return True, f"typed and sent in {ref}, unconfirmed, since its screen couldn't be read"
            if not unsent(screen.stdout, mark):
                return True, f"submitted in {ref}"
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"cmux failed: {e}"
    return False, f"typed in {ref}, and it still sits unsent in the prompt after {CONFIRM_TRIES} tries"


def here(config: dict, name: str) -> bool:
    """Whether `name` has a cmux workspace on this computer, as far as cmux says."""
    command = cli.cmux_command()
    if command is None:
        return False
    try:
        return find(config["project"]["name"], name, workspaces(command)) is not None
    except (cli.ColonyError, OSError, subprocess.SubprocessError):
        return False


def idle(config: dict, name: str, now: float | None = None) -> bool:
    """Whether `name` runs no wait on this computer: its last poll is over RUNNING seconds old, or there is none."""
    from colony import wait

    state = wait.read_json(wait.state_path(config["project"]["name"], name), {})
    polled = state.get("polled_at") if isinstance(state, dict) else None
    now = time.time() if now is None else now
    return not isinstance(polled, (int, float)) or now - polled >= RUNNING


def after_post(config: dict, args, to: str, card: int | None) -> None:
    """Nudge the recipient of a line just posted, when --nudge asks or [messages] nudge says so. The line is out
    either way, so what happened goes to stdout on success and stderr otherwise."""
    forced = bool(getattr(args, "nudge", False))
    if to.startswith("@"):
        if forced:
            print(f"{cli.NAME}: no nudge, since {to} names no one session", file=sys.stderr)
        return
    how = mode(config)
    if not forced and (how == "off" or (how == "auto" and not idle(config, to)) or not here(config, to)):
        return  # by the setting alone, a session with no workspace on this computer, or no cmux, gets none, quietly
    done, what = nudge(config, to, card)
    if done:
        print(f"nudged {to}: {what}")
    else:
        print(f"{cli.NAME}: no nudge for {to}: {what}", file=sys.stderr)


def run(config: dict, args) -> int:
    """`colony nudge <name> [--card N] [--workspace REF]`."""
    done, what = nudge(config, args.name.lower(), args.card, args.workspace or "")
    print(f"nudged {args.name}: {what}" if done else f"{cli.NAME}: no nudge for {args.name}: {what}",
          file=sys.stdout if done else sys.stderr)
    return 0 if done else 1


def add_commands(sub) -> None:
    """`colony nudge`."""
    from colony import wait

    p = sub.add_parser("nudge", help="type a short pointer into a session's cmux workspace on this computer, so an "
                                     "idle session reads its lines, and confirm it was submitted")
    p.add_argument("name", help="the session, such as builder-2 or ana-web-lead")
    p.add_argument("--card", type=wait.card_number, help="the card the line waits on, which the pointer names")
    p.add_argument("--workspace", metavar="REF", help="the cmux workspace, such as workspace:3, when its title isn't "
                                                      "the session's name")
    p.set_defaults(run=run)
