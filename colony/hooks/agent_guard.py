#!/usr/bin/env python3
"""Puffin Colony's subagent guard: cap how many subagents one Colony session runs at once, so builders run as helpers
Colony opens, which it can see and place on an account with room, and never inside a lead.

Claude Code runs it before each Agent call (Task in older versions), with the call as JSON on stdin. Exit code 2
refuses the call, and stderr says why and what to do instead. `colony hooks install` copies this file into a repo's
.colony/hooks/ and adds it to .claude/settings.json; the plugin runs its own copy. Standard library only, and it
imports nothing of Colony's, so it runs with any python3, 3.9 and later.

Which sessions. A Colony session is one with $COLONY_SESSION, or one whose Claude Code session id has a Colony
identity, ~/.colony/sessions/<id>.json, which `colony` or `colony claim` keeps. Every other session passes: the guard
is Colony's rule, and a person's own Claude Code session in the repo keeps its own ways.

How many run. Claude Code keeps each subagent's transcript beside the session's own, in <the session's transcript
without .jsonl>/subagents/, with an <agent>.meta.json that says "finished": true once it ends. One with no finish
whose transcript moved within STALE_MINUTES still runs; an older one died with an earlier run of the session. A call
the guard let through counts too, until its subagent's files show up or GRACE seconds pass, since calls made side by
side start before their files exist. The guard keeps those calls in ~/.colony/subagents/<session id>.json, under a
file lock.

The cap. `[subagents] max_running` in the repo's .colony/colony.local.toml (the main checkout's, then this one's),
else in .colony/colony.toml, else DEFAULT_CAP. 0 lets no subagent run at all.

Past the cap. A lead or an orchestrator, a session named `lead` or `<...>-lead`, hears that builders run as helpers,
opened with `colony helpers <n> --open` or `colony open <name>`, never as subagents. A helper hears to wait for one of
its subagents to finish, or to do that piece itself.

A hook stops an agent's honest mistakes, never a determined one: an agent that can edit .claude/settings.json or this
script can get past it.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

DEFAULT_CAP = 2  # subagents one session runs at once, when the config says nothing
STALE_MINUTES = 15  # an unfinished subagent whose transcript moved longer ago than this no longer runs
GRACE = 180  # seconds a call the guard let through counts as running before its subagent's files show up
TOOLS = ("Agent", "Task")  # the tool that starts a subagent: Agent, and Task in older Claude Code versions
SESSION_ID = re.compile(r"[A-Za-z0-9-]{1,100}")
NAME = "colony"
TABLE = re.compile(r"^\s*\[\s*subagents\s*\]\s*(?:#.*)?$", re.M)
NEXT_TABLE = re.compile(r"^\s*\[", re.M)
MAX_RUNNING = re.compile(r"^\s*max_running\s*=\s*(\d+)\s*(?:#.*)?$", re.M)
LEAD_REFUSAL = ("subagent guard: refused, this session already runs {running} subagent{s}, the most one session runs "
                "at once ([subagents] max_running = {cap}). A lead or an orchestrator never builds through subagents: "
                "a subagent runs on your own account, where Colony can't see it, place it or count it, and enough of "
                "them drain your account and cut off you and your whole team at once. Open builders as helpers: `"
                f"{NAME} helpers <n> --open`, or `{NAME} open <name>`, which places each on an account with room, in "
                "waves, under each account's cap. Keep a subagent for a quick search or a browser check, and start it "
                "once one of yours finishes.")
HELPER_REFUSAL = ("subagent guard: refused, this session already runs {running} subagent{s}, the most one session runs "
                  "at once ([subagents] max_running = {cap}). A helper's subagent is only for a quick search or a "
                  "browser check: wait for one of yours to finish, or do this piece yourself. When the card is too "
                  "big for you alone, ask your lead to split it.")


def home() -> Path:
    return Path(os.path.expanduser("~"))


def session_name(session_id: str) -> str:
    """This session's Colony name: $COLONY_SESSION, else the one its saved identity holds, else ""."""
    name = os.environ.get("COLONY_SESSION", "")
    if name or not SESSION_ID.fullmatch(session_id or ""):
        return name
    try:
        held = json.loads((home() / f".{NAME}" / "sessions" / f"{session_id}.json").read_text())
    except (OSError, ValueError):
        return ""
    return str(held.get("COLONY_SESSION") or "") if isinstance(held, dict) else ""


def is_lead(name: str) -> bool:
    """Whether a Colony name is a lead's or an orchestrator's: `lead`, or a named lead such as ana-engine-lead."""
    return name == "lead" or name.endswith("-lead")


def main_checkout(root: Path) -> Path | None:
    """The main checkout of the clone a worktree belongs to, read from its .git file, or None when `root` is the main
    checkout or no clone at all."""
    marker = root / ".git"
    try:
        text = marker.read_text().strip() if marker.is_file() else ""
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    gitdir = (root / text.split(":", 1)[1].strip()).resolve()
    try:
        common = (gitdir / (gitdir / "commondir").read_text().strip()).resolve()
    except OSError:
        common = gitdir.parent.parent
    return common.parent


def repo_root(cwd: str) -> Path | None:
    """The folder above `cwd`, or $CLAUDE_PROJECT_DIR, that holds .colony/colony.toml."""
    for start in (os.environ.get("CLAUDE_PROJECT_DIR", ""), cwd):
        if not start:
            continue
        here = Path(start).resolve()
        for folder in (here, *here.parents):
            if (folder / f".{NAME}" / f"{NAME}.toml").is_file():
                return folder
    return None


def cap_in(text: str) -> int | None:
    """`[subagents] max_running` in one TOML file's text, or None when it holds none."""
    try:
        import tomllib  # Python 3.11 and later

        table = tomllib.loads(text).get("subagents")
        value = table.get("max_running") if isinstance(table, dict) else None
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    except ImportError:
        pass
    except ValueError:
        return None
    start = TABLE.search(text)
    if start is None:
        return None
    rest = text[start.end():]
    end = NEXT_TABLE.search(rest)
    found = MAX_RUNNING.search(rest[:end.start()] if end else rest)
    return int(found[1]) if found else None


def cap(cwd: str) -> int:
    """The most subagents one session runs at once: the local files first, then the tracked one, else DEFAULT_CAP."""
    root = repo_root(cwd)
    if root is None:
        return DEFAULT_CAP
    main = main_checkout(root)
    folder = f".{NAME}"
    for path in (root / folder / f"{NAME}.local.toml", *([main / folder / f"{NAME}.local.toml"] if main else []),
                 root / folder / f"{NAME}.toml"):
        try:
            found = cap_in(path.read_text())
        except OSError:
            continue
        if found is not None:
            return found
    return DEFAULT_CAP


def running_agents(transcript: str, now: float) -> set[str]:
    """The tool call ids of the subagents this session runs now, from the meta files beside its transcript: one with
    no finish whose own transcript moved within STALE_MINUTES. A subagent whose meta names no call goes by its file."""
    if not transcript:
        return set()
    folder = Path(transcript).with_suffix("") / "subagents"
    found = set()
    for meta in folder.glob("*.meta.json") if folder.is_dir() else []:
        try:
            held = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(held, dict) or held.get("finished") is True:
            continue
        log = meta.with_name(meta.name[:-len(".meta.json")] + ".jsonl")
        try:
            moved = log.stat().st_mtime
        except OSError:
            moved = meta.stat().st_mtime
        if now - moved <= STALE_MINUTES * 60:
            found.add(str(held.get("toolUseId") or meta.name))
    return found


def known_calls(transcript: str) -> set[str]:
    """Every tool call id the subagents folder names, finished or not: a call whose subagent has its files."""
    if not transcript:
        return set()
    folder = Path(transcript).with_suffix("") / "subagents"
    found = set()
    for meta in folder.glob("*.meta.json") if folder.is_dir() else []:
        try:
            held = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(held, dict) and held.get("toolUseId"):
            found.add(str(held["toolUseId"]))
    return found


class Lock:
    """An exclusive lock on a file for the life of a `with`, so calls made side by side count one at a time. Where
    the system offers no lock, it holds none."""

    def __init__(self, path: Path):
        self.path, self.handle = path, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "a+")
        try:
            import fcntl

            fcntl.flock(self.handle, fcntl.LOCK_EX)
        except ImportError:
            try:
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_LOCK, 1)
            except (ImportError, OSError):
                pass
        return self

    def __exit__(self, *exc):
        self.handle.close()  # closing the file frees its lock


def ledger_path(session_id: str) -> Path:
    return home() / f".{NAME}" / "subagents" / f"{session_id}.json"


def decide(call: dict, now: float | None = None) -> tuple[bool, str]:
    """Whether the Agent call may start, and the refusal to print when it may not."""
    now = time.time() if now is None else now
    session_id = str(call.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    name = session_name(session_id)
    if not name:
        return True, ""
    most = cap(str(call.get("cwd") or os.getcwd()))
    transcript = str(call.get("transcript_path") or "")
    this_call = str(call.get("tool_use_id") or f"call-{now:.6f}-{os.getpid()}")
    key = session_id if SESSION_ID.fullmatch(session_id) else f"name-{re.sub(r'[^a-z0-9.-]', '-', name.lower())}"
    path = ledger_path(key)
    with Lock(path.with_suffix(".lock")):
        try:
            held = json.loads(path.read_text())
        except (OSError, ValueError):
            held = {}
        started = held.get("started") if isinstance(held, dict) and isinstance(held.get("started"), dict) else {}
        known = known_calls(transcript)
        pending = {call_id: at for call_id, at in started.items()
                   if isinstance(at, (int, float)) and call_id not in known and now - at < GRACE}
        running = len(running_agents(transcript, now) | set(pending))
        if running >= most:
            refusal = LEAD_REFUSAL if is_lead(name) else HELPER_REFUSAL
            return False, refusal.format(running=running, s="" if running == 1 else "s", cap=most)
        pending[this_call] = now
        part = path.with_name(f".{path.name}.{os.getpid()}")
        part.write_text(json.dumps({"started": pending}))
        os.replace(part, path)
    return True, ""


def main() -> int:
    """Read the hook's call from stdin: exit 2 with the refusal when an Agent call would pass the session's cap,
    else 0. A call the guard can't read runs."""
    try:
        call = json.load(sys.stdin)
        if not isinstance(call, dict) or str(call.get("tool_name") or "") not in TOOLS:
            return 0
        allowed, refusal = decide(call)
    except (ValueError, OSError, TypeError):
        return 0
    if allowed:
        return 0
    sys.stderr.write(refusal + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
