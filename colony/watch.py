"""Watching helpers and the lead's computer. A helper at a permission prompt still looks alive, since its background
`colony wait` keeps its status fresh, and a laptop that sleeps stops every wait on it without a word.

A helper's own Claude Code transcript says what it is doing (activity): a last entry that is a tool call with no
answer yet means its session waits on that call, which past a few minutes is most often a permission prompt. Its
status comment carries that, and the lead's wait raises one `urgent:` line for a helper whose call has waited
STUCK_AFTER (stuck_check). The lead's wait also names a gap in which the computer slept (slept), and on macOS keeps the
computer awake for the life of the lead's Claude Code session (keep_awake).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from colony import wait

STUCK_AFTER = 10 * 60  # a tool call waiting this long for an answer is most often a permission prompt
SLEPT_AFTER = 5 * 60  # a gap between polls longer than this, beyond the wait's own pauses, is a computer that slept
TAIL_BYTES = 256 * 1024  # the end of a transcript read for its last entry
SESSION_ID = re.compile(r"[A-Za-z0-9-]{1,100}")


def transcript() -> Path | None:
    """This session's Claude Code transcript: <config dir>/projects/*/<$CLAUDE_CODE_SESSION_ID>.jsonl."""
    session = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not SESSION_ID.fullmatch(session):
        return None
    folder = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser() / "projects"
    found = list(folder.glob(f"*/{session}.jsonl")) if folder.is_dir() else []
    return max(found, key=lambda path: path.stat().st_mtime) if found else None


def seconds(stamp: str) -> float:
    """An ISO time, such as 2026-11-08T10:03:00.123Z, as Unix time; 0 when it can't be read."""
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return 0.0


def activity() -> dict:
    """What this session's transcript says it does: when it last acted (`active`), the folder it works in (`work`),
    and the tool call that waits for an answer (`waiting`, since `waiting_since`), or {} with no transcript."""
    path = transcript()
    if path is None:
        return {}
    try:
        with open(path, "rb") as held:
            held.seek(max(0, path.stat().st_size - TAIL_BYTES))
            lines = held.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") not in ("user", "assistant") or entry.get("isSidechain"):
            continue
        at = seconds(entry.get("timestamp", ""))
        content = (entry.get("message") or {}).get("content")
        last = content[-1] if isinstance(content, list) and content else {}
        calling = entry["type"] == "assistant" and isinstance(last, dict) and last.get("type") == "tool_use"
        return {"active": at, "work": str(entry.get("cwd") or ""), "waiting": str(last.get("name") or "")
                if calling else "", "waiting_since": at if calling else 0.0}
    return {}


def branch(folder: str) -> str:
    """The branch checked out in a folder, or ""."""
    if not folder or not Path(folder).is_dir():
        return ""
    run = subprocess.run(["git", "-C", folder, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else ""


def stuck_check(lead: str):
    """The lead's check for its helpers whose tool call has waited STUCK_AFTER for an answer, from their status
    comments (wait.learn_helpers keeps state["waiting"]): one `urgent:` line per helper per stretch."""
    def check(state: dict, now: float) -> list[str]:
        raised, lines = state.setdefault("stuck", {}), []
        for name, held in (state.get("waiting") or {}).items():
            if not isinstance(held, list) or len(held) != 4:
                continue
            owner, tool, since, where = held
            if not isinstance(since, (int, float)) or isinstance(since, bool):
                continue
            if owner != lead or not tool or not since or now - since < STUCK_AFTER or raised.get(name) == since:
                continue
            raised[name] = since
            lines.append(f"urgent: {name}'s {tool} call has waited {int((now - since) // 60)} minutes for an answer, "
                         f"likely a permission prompt in its window on {where or 'its computer'}: answer it there, "
                         "or open the helper again")
        return lines
    return check


def slept(last_wall: float, last_mono: float, wall: float, mono: float) -> str:
    """A line when the wall clock moved SLEPT_AFTER further than the monotonic one, which stands still while the
    computer sleeps, else ""."""
    gap = (wall - last_wall) - (mono - last_mono)
    if gap < SLEPT_AFTER:
        return ""
    return (f"urgent: this computer slept for {int(gap // 60)} minutes, so its helpers, merges and waits stopped: "
            "check them")


def keep_awake(project: str, claude_pid: str, popen=subprocess.Popen, alive=None, system: str = sys.platform) -> None:
    """On macOS, keep the computer from sleeping while the lead's Claude Code session ($CLAUDE_PID) lives: one
    `caffeinate -i -s -w <pid>`, started once and ended with that session. Elsewhere, nothing."""
    if system != "darwin" or not claude_pid.isdigit():
        return
    alive = alive or running
    path = wait.state_path(project, "caffeinate")
    held = wait.read_json(path, {})
    if isinstance(held, dict) and held.get("for") == claude_pid and alive(int(held.get("pid") or 0)):
        return
    try:
        started = popen(["caffeinate", "-i", "-s", "-w", claude_pid], stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return
    wait.write_json(path, {"pid": started.pid, "for": claude_pid})


def running(pid: int) -> bool:
    """Whether a process with this id runs."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
