"""Watching the team: what each session is doing and why, and the lines that flag only a session idle without a reason.

A helper at a permission prompt still looks alive, since its background `colony wait` keeps its status fresh, and a
laptop that sleeps stops every wait on it without a word. A session's own Claude Code transcript says what it is doing
(activity): a last entry that is a tool call with no answer yet means its session waits on that call, which past a few
minutes is most often a permission prompt. Its status comment carries that, and the lead's wait raises one `urgent:`
line for a helper whose call has waited STUCK_AFTER (stuck_check). The lead's wait also names a gap in which the
computer slept (slept), and on macOS keeps the computer awake for the life of the lead's Claude Code session
(keep_awake).

Intent. A session says what it is doing and why with `colony intent`: working, waiting on something, holding
something, or done, with an optional end time. `colony take` sets working on the card, and a helper's `done` line sets
waiting for its next card. A session that works sends a short report at least every `[watch] report_minutes` with
`colony report`. Both live in ~/.colony/<project>/<session>-intent.json and go out in the session's status comment,
so a lead on another computer sees them.

The pulse. Each session's wait writes ~/.colony/<project>/<session>-pulse.json every PULSE_EVERY seconds: when its
transcript last moved, the call it waits on, and the helper agents it runs (agents_of). A pulse older than PULSE_FRESH
means the session's wait stopped. The watchdog on the same computer reads the pulses (colony/watchdog.py).

The team watch. The lead's wait looks at its helpers every `[watch] every_minutes` (lead_watch), and flags only:
a helper idle past `idle_minutes` with no reason given, a working helper that missed two reports, a wait or hold past
its end time, a wait on a session that is gone, limited or done, and a helper agent that ran past twice its limit. A
session waiting, holding or done on purpose raises nothing, and neither does one waiting for its usage limit to
reset. Each finding shows once per stretch. A helper's own wait reminds it of a report that is due, and of a helper
agent past `agent_minutes` (helper_watch). `colony watch` shows the whole team now.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from colony import cli, wait

STUCK_AFTER = 10 * 60  # a tool call waiting this long for an answer is most often a permission prompt
SLEPT_AFTER = 5 * 60  # a gap between polls longer than this, beyond the wait's own pauses, is a computer that slept
TAIL_BYTES = 256 * 1024  # the end of a transcript read for its last entry
SESSION_ID = re.compile(r"[A-Za-z0-9-]{1,100}")
PULSE_EVERY = 60  # seconds between a wait's pulses
PULSE_FRESH = 3 * 60  # a pulse older than this: the session's wait stopped
AGENT_FRESH = 10 * 60  # an unfinished helper agent whose transcript moved within this long still runs
AGENTS_KEPT = 10  # the most helper agents a status names
BUSY_FRESH = 15 * 60  # a lead's own word on its busy helpers counts this long
TEXT_MAX = 120  # the most characters of a reason or a report
RAISED_KEPT = 2 * 24 * 3600  # a finding raised longer ago than this is forgotten
INTENTS = ("working", "waiting", "holding", "done")
NEEDS_WHY = ("waiting", "holding")
WAITS = ("waiting", "holding")
BUSY = ("working", "waiting", "holding", "prompt", "limited")  # a helper in one of these keeps its lead waiting


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
    """What this session's transcript says it does (activity_of), or {} with no transcript."""
    path = transcript()
    return {} if path is None else activity_of(path)


def activity_of(path: Path) -> dict:
    """What a transcript says its session does: when it last acted (`active`), the folder it works in (`work`), and
    the tool call that waits for an answer (`waiting`, since `waiting_since`), or {} when it can't be read."""
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


# Settings: [watch]


@dataclass(frozen=True)
class Settings:
    """[watch]: how the team watch, the reporting rhythm, the watchdog and the status page behave."""

    idle_minutes: float = 20.0  # a session quiet this long, with no reason given, is idle
    report_minutes: float = 30.0  # a working helper sends a report at least this often
    agent_minutes: float = 45.0  # a helper's own helper agent may run this long
    intent_hours: float = 4.0  # a wait or a hold with no end time is checked after this long
    late_after: float = 1.0  # a card past this many times its predicted minutes is late
    every_minutes: float = 2.0  # how often the lead's wait and the watchdog look at the team
    page: bool = True  # whether the watchdog keeps the status page
    page_minutes: float = 5.0  # how often the status page may change
    watchdog: bool = True  # whether the lead's wait starts the watchdog when none runs on its computer
    escalate_minutes: float = 60.0  # a lead still idle this long after the watchdog's line: its person is mentioned
    quit_hours: float = 24.0  # a watchdog the lead's wait started ends after this long with no session alive


NUMBERS = {"idle_minutes": (1, None), "report_minutes": (5, None), "agent_minutes": (1, None),
           "intent_hours": (0.25, None), "late_after": (0.5, 10), "every_minutes": (0.5, 60), "page_minutes": (1, None),
           "escalate_minutes": (5, None), "quit_hours": (1, None)}
SWITCHES = ("page", "watchdog")


def settings(config: dict) -> Settings:
    """[watch] as Settings, each key checked; a config without it gets the defaults."""
    from colony import capacity

    table = config.get("watch") or {}
    if not isinstance(table, dict):
        raise cli.ColonyError(f"{cli.CONFIG_NAME}: [watch] is a table")
    unknown = sorted(set(table) - set(NUMBERS) - set(SWITCHES))
    if unknown:
        raise cli.ColonyError(f"{cli.CONFIG_NAME}: [watch] has no key {unknown[0]!r}: its keys are "
                              f"{', '.join([*NUMBERS, *SWITCHES])}")
    defaults, values = Settings(), {}
    for key, (low, high) in NUMBERS.items():
        values[key] = capacity.number(table, key, getattr(defaults, key), low, high, where="[watch]")
    for key in SWITCHES:
        value = table.get(key, getattr(defaults, key))
        if not isinstance(value, bool):
            raise cli.ColonyError(f"{cli.CONFIG_NAME}: [watch] {key} is true or false, not {value!r}")
        values[key] = value
    return Settings(**values)


# Intent: what a session says it is doing, and its reports


def intent_path(project: str, name: str) -> Path:
    return wait.state_path(project, f"{name}-intent")


def short_text(value, limit: int = TEXT_MAX) -> str:
    """A reason, a report or a name from a file or a comment anyone could write, as one short line with no path on
    this computer in it, or "" when it isn't text."""
    from colony import messages, presence

    text = messages.LOCAL_PATH.sub("…", presence.clean_text(value))
    return text[:limit]


def number(value) -> float:
    from colony import presence

    return presence.clean_number(value)


def clean(value) -> dict:
    """A session's watch fields from its status comment or its files, checked as the status's other fields are: a
    known intent or none, short single lines, finite numbers, and at most AGENTS_KEPT helper agents."""
    if not isinstance(value, dict):
        return {}
    found = {"intent": value.get("intent") if value.get("intent") in INTENTS else ""}
    for key in ("why", "report", "on"):
        found[key] = short_text(value.get(key))
    if found["on"] and not cli.SESSION_NAME.fullmatch(found["on"]):
        found["on"] = ""
    for key in ("since", "until", "reported_at", "active", "started"):
        found[key] = number(value.get(key))
    agents = value.get("agents")
    found["agents"] = [{"what": short_text(agent.get("what"), 60) or "a helper agent",
                        "started": number(agent.get("started")), "last": number(agent.get("last")),
                        "id": short_text(agent.get("id"), 40)}
                       for agent in (agents if isinstance(agents, list) else [])[:AGENTS_KEPT] if isinstance(agent, dict)]
    return {key: item for key, item in found.items() if item not in ("", 0.0, [])}


def read_intent(project: str, name: str) -> dict:
    """A session's intent and last report, as `colony intent` and `colony report` wrote them, or {}."""
    return clean(wait.read_json(intent_path(project, name), {}))


def set_intent(project: str, name: str, intent: str, why: str = "", until: float = 0.0, on: str = "",
               now: float | None = None) -> dict:
    """Write a session's intent, keeping its last report, and have its wait edit its status comment at its next poll
    (poke_status). `intent` "" clears it."""
    now = time.time() if now is None else now
    held = read_intent(project, name)
    mine = {key: held[key] for key in ("report", "reported_at") if key in held}
    if intent:
        mine.update(intent=intent, why=short_text(why), since=now, until=until, on=on)
    wait.write_json(intent_path(project, name), clean(mine))
    poke_status(project, name)
    return read_intent(project, name)


def poke_status(project: str, name: str) -> None:
    """Have the session's wait edit its status comment at its next poll, not up to five minutes later, by clearing the
    time of its last edit (presence.keep)."""
    path = wait.state_path(project, f"{name}-status")
    held = wait.read_json(path, None)
    if isinstance(held, dict) and held.get("status_at"):
        held["status_at"] = 0
        wait.write_json(path, held)


def session_name() -> str:
    """This session's name for its files: a named lead's own name, else $COLONY_SESSION."""
    me = os.environ.get(cli.SESSION_ENV, "").lower()
    if not me:
        raise cli.ColonyError(f"{cli.SESSION_ENV} is not set: this is not a {cli.DISPLAY} session")
    return wait.state_name(me)


def note_take(config: dict, card: int) -> None:
    """`colony take`'s part: the helper now works on the card. It never raises."""
    try:
        set_intent(config["project"]["name"], session_name(), "working", f"#{card}")
    except (cli.ColonyError, OSError) as e:
        print(f"{cli.NAME}: the intent was not noted: {e}", file=sys.stderr)


def note_done(config: dict, card: int | None, lead: str) -> None:
    """A helper's `done` line's part: it now waits for its next card, from its lead. It never raises."""
    try:
        what = f"its next card, after #{card}" if card is not None else "its next card"
        set_intent(config["project"]["name"], session_name(), "waiting", what, on=lead if lead != cli.LEAD else "")
    except (cli.ColonyError, OSError) as e:
        print(f"{cli.NAME}: the intent was not noted: {e}", file=sys.stderr)


def describe_intent(held: dict, now: float) -> str:
    """A session's intent and last report, as a person reads them."""
    if not held.get("intent"):
        said = "no intent set"
    else:
        said = held["intent"] + (f": {held['why']}" if held.get("why") else "")
        said += f", on {held['on']}" if held.get("on") else ""
        said += f", since {clock(held['since'])}" if held.get("since") else ""
        said += f", until {clock(held['until'])}" if held.get("until") else ""
    if held.get("reported_at"):
        said += f"; last report {minutes(now - held['reported_at'])} ago: {held.get('report', '')}"
    return said


def clock(at: float) -> str:
    """A time of day in UTC, such as 14:05 UTC, or with its date when it isn't today."""
    when, today = datetime.fromtimestamp(at, timezone.utc), datetime.now(timezone.utc)
    return when.strftime("%H:%M UTC" if when.date() == today.date() else "%Y-%m-%d %H:%M UTC")


def minutes(span: float) -> str:
    """A span as whole minutes, or hours and minutes past an hour, such as 25 min or 3 h 10 min."""
    whole = max(0, int(span // 60))
    return f"{whole} min" if whole < 60 else f"{whole // 60} h" + (f" {whole % 60} min" if whole % 60 else "")


# The pulse and the helper agents


def pulse_path(project: str, name: str) -> Path:
    return wait.state_path(project, f"{name}-pulse")


def agents_of(path: Path | None, now: float | None = None) -> list[dict]:
    """The helper agents a session runs now, from its transcript's subagents folder: each unfinished one whose own
    transcript moved within AGENT_FRESH, with what it does, when it started and when it last moved."""
    if path is None:
        return []
    now = time.time() if now is None else now
    folder = path.with_suffix("") / "subagents"
    found = []
    for log in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        try:
            last = log.stat().st_mtime
        except OSError:
            continue
        meta = wait.read_json(log.with_name(log.stem + ".meta.json"), {})
        meta = meta if isinstance(meta, dict) else {}
        if meta.get("finished") is True or now - last > AGENT_FRESH:
            continue
        found.append({"what": short_text(meta.get("description"), 60) or "a helper agent",
                      "started": first_time(log) or last, "last": last, "id": log.stem.removeprefix("agent-")[:40]})
    found.sort(key=lambda agent: agent["started"])
    return found[:AGENTS_KEPT]


def first_time(log: Path) -> float:
    """The time of a transcript's first entry, or 0."""
    try:
        with open(log, encoding="utf-8", errors="replace") as held:
            for _ in range(5):
                line = held.readline()
                if not line:
                    break
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and (at := seconds(str(entry.get("timestamp") or ""))):
                    return at
    except OSError:
        pass
    return 0.0


def write_pulse(project: str, name: str, kind: str, lead: str = "", now: float | None = None,
                busy: list | None = None) -> dict:
    """This session's pulse, from its own wait: its transcript's last move, the call it waits on, its helper agents,
    since when this Claude Code session has pulsed (`started`), which the reporting rhythm counts from, and for a lead
    its helpers that are busy, on any computer."""
    now = time.time() if now is None else now
    path = transcript()
    doing = activity_of(path) if path else {}
    session = os.environ.get(cli.CLAUDE_SESSION_ENV, "")
    held = wait.read_json(pulse_path(project, name), {})
    held = held if isinstance(held, dict) else {}
    started = held.get("started") if held.get("session") == session and isinstance(held.get("started"), (int, float)) \
        else now
    pulse = {"name": name, "kind": kind, "lead": lead, "at": now, "session": session, "pid": os.getpid(),
             "transcript": str(path or ""), "started": started, "active": doing.get("active", 0.0),
             "waiting": doing.get("waiting", ""), "waiting_since": doing.get("waiting_since", 0.0),
             "agents": agents_of(path, now), **({"busy": busy} if busy is not None else {})}
    wait.write_json(pulse_path(project, name), pulse)
    return pulse


def published(project: str, name: str) -> dict:
    """What a session's status comment carries for the watch: its intent and last report, when its transcript last
    moved, and the helper agents it runs."""
    found = dict(read_intent(project, name))
    path = transcript()
    if path is not None:
        found["active"] = activity_of(path).get("active", 0.0)
        found["agents"] = agents_of(path)
    pulse = wait.read_json(pulse_path(project, name), {})
    if isinstance(pulse, dict) and pulse.get("started"):
        found["started"] = pulse["started"]
    return clean(found)


def readable(held: dict, now: float) -> str:
    """The status comment's line for people: the intent, the last report and the helper agents, or ""."""
    if not held:
        return ""
    parts = [describe_intent(held, now)] if held.get("intent") or held.get("reported_at") else []
    for agent in held.get("agents") or []:
        parts.append(f"helper agent \"{agent['what']}\" for {minutes(now - agent.get('started', now))}")
    return "; ".join(parts)


# The team: each session as the watch sees it


@dataclass
class Member:
    """One session as the watch sees it, from its status comment, its pulse on this computer, or both."""

    name: str
    kind: str = "helper"
    lead: str = ""
    computer: str = ""
    seen: float = 0.0  # when its status or pulse was last written: its wait ran then
    intent: str = ""
    why: str = ""
    on: str = ""
    since: float = 0.0
    until: float = 0.0
    report: str = ""
    reported_at: float = 0.0
    started: float = 0.0
    active: float = 0.0  # when its transcript last moved
    waiting: str = ""  # the tool call it waits on for an answer
    waiting_since: float = 0.0
    agents: list = field(default_factory=list)
    limited: bool = False  # it stopped on its account's usage limit, and waits for the reset
    pulse: float = 0.0  # when its pulse on this computer was written, 0 for none
    transcript: str = ""
    session: str = ""  # its Claude Code session id, from its pulse
    busy: list = field(default_factory=list)  # a lead's busy helpers on any computer, from its wait's last look


def member_of(name: str, kind: str, lead: str, seen: float, held: dict, **extra) -> Member:
    """A Member from a session's watch fields (clean)."""
    found = Member(name, kind, lead, seen=seen, **extra)
    for key, value in clean(held).items():
        setattr(found, key, value)
    return found


def remember(state: dict, status) -> None:
    """The lead's wait's part of reading a helper's status comment (wait.learn_helpers): keep what the watch needs."""
    state.setdefault("team", {})[status.name.lower()] = {
        "kind": status.kind, "lead": status.lead.lower(), "computer": status.computer, "at": status.at,
        "waiting": status.waiting, "waiting_since": status.waiting_since, "watch": getattr(status, "watch", {}) or {}}


def from_state(state: dict) -> dict[str, Member]:
    """The helpers whose status comments the lead's wait read (remember)."""
    found = {}
    for name, held in (state.get("team") or {}).items():
        if not isinstance(held, dict):
            continue
        found[name] = member_of(name, str(held.get("kind") or "helper"), str(held.get("lead") or ""),
                                number(held.get("at")), held.get("watch") or {},
                                computer=short_text(held.get("computer"), 60),
                                waiting=short_text(held.get("waiting"), 64),
                                waiting_since=number(held.get("waiting_since")))
    return found


def from_statuses(statuses) -> dict[str, Member]:
    """Members from status comments (presence.everyone)."""
    return {status.name: member_of(status.name, status.kind, status.lead, status.at, getattr(status, "watch", {}) or {},
                                   computer=status.computer, waiting=status.waiting, waiting_since=status.waiting_since)
            for status in statuses}


def local_members(config: dict) -> dict[str, Member]:
    """The sessions on this computer by their pulses, with their intents and usage limits."""
    from colony import capacity

    project = config["project"]["name"]
    folder = wait.state_path(project, cli.LEAD).parent
    limited = set(capacity.limited(config)) if folder.is_dir() else set()
    found = {}
    for path in sorted(folder.glob("*-pulse.json")) if folder.is_dir() else []:
        pulse = wait.read_json(path, None)
        name = path.name.removesuffix("-pulse.json")
        if not isinstance(pulse, dict) or not cli.SESSION_NAME.fullmatch(name):
            continue
        held = {**{key: pulse.get(key) for key in ("active", "agents", "started")}, **read_intent(project, name)}
        found[name] = member_of(name, "lead" if pulse.get("kind") == "lead" else "helper",
                                short_text(pulse.get("lead"), 64), number(pulse.get("at")), held,
                                waiting=short_text(pulse.get("waiting"), 64),
                                waiting_since=number(pulse.get("waiting_since")), limited=name in limited,
                                pulse=number(pulse.get("at")), transcript=str(pulse.get("transcript") or ""),
                                session=short_text(pulse.get("session"), 100),
                                busy=[short_text(n, 64) for n in pulse.get("busy") or [] if isinstance(n, str)][:30])
    return found


def merged(*groups: dict[str, Member]) -> dict[str, Member]:
    """The members of several sources by name: the newest reading of each, keeping what only an older one knows,
    such as a pulse's transcript or a usage limit on this computer."""
    found: dict[str, Member] = {}
    for group in groups:
        for name, member in group.items():
            old = found.get(name)
            if old is None:
                found[name] = member
                continue
            new, older = (member, old) if member.seen >= old.seen else (old, member)
            new.limited = new.limited or older.limited
            new.pulse, new.transcript = max(new.pulse, older.pulse), new.transcript or older.transcript
            new.session, new.busy = new.session or older.session, new.busy or older.busy
            new.computer, new.lead = new.computer or older.computer, new.lead or older.lead
            for key in ("intent", "why", "on", "since", "until", "report", "reported_at", "started", "active"):
                if not getattr(new, key) and getattr(older, key):
                    setattr(new, key, getattr(older, key))
            found[name] = new
    return found


# Judging: what a session is doing, and what is worth a line


def last_report(member: Member) -> float:
    """When a member's reporting rhythm last began: its last report or its intent, whichever is newer, else when its
    Claude Code session first pulsed."""
    return max(member.reported_at, member.since) or member.started


def due(member: Member, s: Settings) -> float:
    """When a member's wait or hold is due: its end time, else intent_hours after it began."""
    return member.until or member.since + s.intent_hours * 3600


def standing(member: Member, s: Settings, now: float, team: dict[str, Member] | None = None) -> tuple[str, str]:
    """What a member is doing, in a word, with the detail people read: gone, done, limited, prompt, waiting, holding,
    working, or idle."""
    from colony import presence

    if member.seen and now - member.seen >= presence.STATUS_STALE:
        return "gone", f"no sign from its wait for {minutes(now - member.seen)}"
    if member.intent == "done":
        return "done", member.why or "said it is done"
    if member.limited:
        return "limited", "waits for its account's usage limit to reset"
    if member.waiting and member.waiting_since and now - member.waiting_since >= 120:
        return "prompt", f"its {member.waiting} call has waited {minutes(now - member.waiting_since)} for an answer"
    if member.intent in WAITS:
        detail = (member.why or "something") + (f", on {member.on}" if member.on else "")
        return member.intent, detail + (f", until {clock(member.until)}" if member.until else "")
    if member.intent == "working" or (member.active and now - member.active < s.idle_minutes * 60):
        return "working", member.why or "working"
    if member.kind == "lead" and (busy_helpers(member.name, team or {}, s, now) or
                                  (member.busy and now - member.seen < BUSY_FRESH)):
        return "waiting", "on its helpers"
    quiet = f"quiet for {minutes(now - member.active)}" if member.active else "no activity read"
    return "idle", quiet + ", with no reason given"


def busy_helpers(lead: str, team: dict[str, Member], s: Settings, now: float) -> list[str]:
    """The helpers of a lead that work, wait or hold on purpose, or wait on a prompt."""
    return [m.name for m in team.values() if m.kind == "helper" and m.lead == lead and m.name != lead
            and standing(m, s, now)[0] in BUSY]


@dataclass(frozen=True)
class Finding:
    """One thing worth a line: its kind, the member, the key that makes it show once per stretch, and its words."""

    kind: str  # idle, quiet, overdue, stalled or agent
    name: str
    key: str
    text: str


def findings(member: Member, s: Settings, now: float, team: dict[str, Member]) -> list[Finding]:
    """What is worth a line about one member: idle with no reason, a missed reporting rhythm, a wait or hold past its
    end, a wait on a session that is gone, limited or done, or a helper agent past twice its limit. A session gone,
    done, limited or on a prompt raises nothing here: other checks name those."""
    word, _ = standing(member, s, now, team)
    found = []
    for agent in member.agents:
        ran = now - agent.get("started", now)
        if ran >= 2 * s.agent_minutes * 60:
            found.append(Finding("agent", member.name, f"agent:{member.name}:{agent.get('id') or agent['what']}",
                                 f"{member.name}'s helper agent \"{agent['what']}\" has run {minutes(ran)}"))
    if word in WAITS and member.intent in WAITS:
        if now >= due(member, s):
            said = "until " + clock(member.until) if member.until else f"for {minutes(now - member.since)}"
            found.append(Finding("overdue", member.name, f"overdue:{member.name}:{member.since}",
                                 f"{member.name} has been {member.intent} on \"{member.why}\" {said}"))
        other = team.get(member.on) if member.on else None
        if other is not None and other.name != member.name:
            theirs, _ = standing(other, s, now, team)
            if theirs in ("gone", "limited", "done", "idle"):
                found.append(Finding("stalled", member.name, f"stalled:{member.name}:{member.on}:{theirs}:{member.since}",
                                     f"{member.name} waits on {member.on}, which is {theirs}"))
    elif word == "working" and member.intent == "working" and member.kind == "helper":
        last = last_report(member)
        if last and now - last >= 2 * s.report_minutes * 60:
            found.append(Finding("quiet", member.name, f"quiet:{member.name}:{last}",
                                 f"{member.name} ({minutes(now - last)})"))
    elif word == "idle" and member.active:
        found.append(Finding("idle", member.name, f"idle:{member.name}:{member.active}",
                             f"{member.name} ({minutes(now - member.active)})"))
    return found


def joined(names: list[str]) -> str:
    """Names as a sentence lists them: a, b and c."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"


def lines_of(found: list[Finding], s: Settings) -> list[str]:
    """One line per kind of finding, naming every member it holds."""
    by: dict[str, list[str]] = {}
    for item in found:
        by.setdefault(item.kind, []).append(item.text)
    lines = []
    if texts := by.get("idle"):
        one = len(texts) == 1
        lines.append(f"idle: {joined(texts)} {'has' if one else 'have'} done nothing and gave no reason: hand "
                     f"{'it' if one else 'each'} a card, or ask why; `{cli.NAME} intent` records a reason")
    if texts := by.get("quiet"):
        lines.append(f"quiet: {joined(texts)} sent no report, against a rhythm of one every "
                     f"{s.report_minutes:g} minutes: look at {'its' if len(texts) == 1 else 'their'} window")
    for kind, ending in (("overdue", "check on it"), ("stalled", "check on both"),
                         ("agent", f"past twice the {s.agent_minutes:g}-minute limit: ask why")):
        for text in by.get(kind, []):
            lines.append(f"{kind}: {text}: {ending}")
    return lines


def once(state: dict, found: list[Finding], now: float) -> list[Finding]:
    """The findings not raised before in this stretch, now marked raised; old marks are forgotten."""
    raised = state.setdefault("raised", {})
    for key in [key for key, at in raised.items() if not isinstance(at, (int, float)) or now - at > RAISED_KEPT]:
        raised.pop(key)
    fresh = [item for item in found if item.key not in raised]
    for item in fresh:
        raised[item.key] = now
    return fresh


# The waits' parts


def helper_watch(config: dict, me: str, lead: str):
    """What a helper's wait runs at each poll: every PULSE_EVERY, its pulse; a reminder to report when its rhythm is
    due; and a line when one of its own helper agents runs past `agent_minutes`, and again past twice that. It never
    raises."""
    def check(waited: dict) -> list[str]:
        try:
            now, held = time.time(), waited.setdefault("watch", {})
            if now - float(held.get("at") or 0) < PULSE_EVERY:
                return []
            held["at"] = now
            s, project = settings(config), config["project"]["name"]
            name = wait.state_name(me)
            pulse = write_pulse(project, name, "helper", lead, now)
            member = member_of(name, "helper", lead, now, {**read_intent(project, name), "active": pulse["active"],
                                                           "started": pulse["started"], "agents": pulse["agents"]})
            return self_lines(member, s, held, now)
        except Exception as e:  # the watch never stops a wait
            print(f"{cli.NAME} wait: the watch failed: {e}", file=sys.stderr)
            return []
    return check


def self_lines(member: Member, s: Settings, held: dict, now: float) -> list[str]:
    """A helper's lines for itself: a report that is due, and a helper agent past its limit, each once."""
    lines = []
    word, _ = standing(member, s, now)
    last = last_report(member)
    if word == "working" and last and now - last >= s.report_minutes * 60:
        period = int((now - last) // (s.report_minutes * 60))
        if once(held, [Finding("report", member.name, f"report:{last}:{period}", "")], now):
            lines.append(f"report: your last report was {minutes(now - last)} ago, and the rhythm is one every "
                         f"{s.report_minutes:g} minutes: run `{cli.NAME} report \"<one line of progress>\"`, or say what "
                         f"you wait on with `{cli.NAME} intent waiting \"<what>\"`")
    for agent in member.agents:
        ran = now - agent.get("started", now)
        times = int(ran // (s.agent_minutes * 60))
        if times >= 1 and once(held, [Finding("agent", member.name, f"agent:{agent.get('id')}:{min(times, 2)}", "")], now):
            lines.append(f"urgent: your helper agent \"{agent['what']}\" has run {minutes(ran)}, past the "
                         f"{s.agent_minutes:g}-minute limit ([watch] agent_minutes): read its output, and stop it with "
                         "your agent tool unless it is about to finish")
    return lines


def lead_watch(config: dict, lead: str):
    """What the lead's wait runs at each poll: every PULSE_EVERY its pulse, and every `every_minutes`, after the first,
    a look at its helpers. Findings about them can wait for the digest, so they go straight into the wait's gathered
    lines, as the stale-card check's do. The lines it returns can't wait: the lead itself idle with no helper busy and
    no reason given, or its own wait past due. It also has the progress check warn of cards past their prediction
    (progress.late_check), and starts the watchdog when none runs on this computer (watchdog.ensure). It never
    raises."""
    from colony import progress

    late = progress.late_check(config, lead)

    def check(waited: dict) -> list[str]:
        try:
            now, held = time.time(), waited.setdefault("watch", {})
            s, project = settings(config), config["project"]["name"]
            if now - float(held.get("pulse_at") or 0) >= PULSE_EVERY:
                held["pulse_at"] = now
                write_pulse(project, wait.state_name(cli.LEAD), "lead", "", now, busy=held.get("busy", []))
            if "at" not in held:  # the first poll: the look starts one interval later, never in a short wait
                held["at"] = now
                return []
            if now - float(held["at"]) < s.every_minutes * 60:
                return []
            held["at"] = now
            me = wait.state_name(cli.LEAD)
            team = merged(from_state(waited), local_members(config))
            mine = {name: m for name, m in team.items() if m.kind == "helper" and m.name != me and helper_of(m, lead)}
            held["busy"] = [m.name for m in mine.values() if standing(m, s, now)[0] in BUSY]
            found = [item for m in mine.values() for item in findings(m, s, now, team)]
            for line in lines_of(once(held, found, now), s):
                waited.setdefault("pending", []).append([line, False])
            for line in late(waited, now):
                waited.setdefault("pending", []).append([line, False])
            from colony import watchdog

            watchdog.ensure(config, s)
            own = team.get(me)
            if own is None or own.limited:
                return []
            if standing(own, s, now, {**mine, me: own})[0] == "idle" and own.active and \
                    once(held, [Finding("self", me, f"self:{own.active}", "")], now):
                return [lead_idle_line(now - own.active)]
            late_own = [item for item in findings(own, s, now, team) if item.kind in ("overdue", "stalled")]
            return [f"urgent: {item.text}, and that is you: carry on, or give a new reason with `{cli.NAME} intent`"
                    for item in once(held, late_own, now)]
        except Exception as e:  # the watch never stops a wait
            print(f"{cli.NAME} wait: the watch failed: {e}", file=sys.stderr)
            return []
    return check


def helper_of(member: Member, lead: str) -> bool:
    """Whether a helper belongs to this lead: by name for a named lead; a lead from before lead names has every
    helper on this computer whose lead is `lead` or unknown."""
    if member.lead == lead.lower():
        return True
    return not wait.named() and member.lead in ("", cli.LEAD)


def lead_idle_line(quiet: float) -> str:
    """The line that wakes a lead idle with no helper busy and no reason given."""
    return (f"urgent: you have done nothing for {minutes(quiet)}, no helper of yours is busy, and you gave no reason: "
            f"hand out or pick up the next card, or say why with `{cli.NAME} intent waiting \"<what>\"` or "
            f"`{cli.NAME} intent done`")


# The commands


def intent_command(config: dict, args) -> int:
    """`colony intent [working|waiting|holding|done|clear] ["<what>"] [--on <session>] [--for MINUTES]`: say what
    this session does and why, so the watch flags it only when it is idle without a reason. With no state, print it."""
    project, name, now = config["project"]["name"], session_name(), time.time()
    if not args.state:
        print(f"{name}: {describe_intent(read_intent(project, name), now)}")
        return 0
    what = " ".join(" ".join(args.what or []).split())
    if args.state == "clear":
        set_intent(project, name, "", now=now)
        print(f"{name}: no intent set; the watch flags you when you sit idle past "
              f"{settings(config).idle_minutes:g} minutes")
        return 0
    if args.state in NEEDS_WHY and not what:
        raise cli.ColonyError(f"say what you are {args.state} on, such as {cli.NAME} intent {args.state} \"#42 to land\"")
    check_text(what)
    on = (args.on or "").lower()
    if on and not cli.SESSION_NAME.fullmatch(on):
        raise cli.ColonyError(f"--on takes a session's name, such as ana-main-lead, not {args.on!r}")
    until = now + args.minutes * 60 if args.minutes else 0.0
    held = set_intent(project, name, args.state, what, until, on, now)
    print(f"{name}: {describe_intent(held, now)}")
    return 0


def check_text(text: str) -> None:
    """Refuse a reason or report too long for one line, or one that names a path on this computer, which goes out in
    the status comment on GitHub."""
    from colony import messages

    if len(text) > TEXT_MAX:
        raise cli.ColonyError(f"keep it to one line of at most {TEXT_MAX} characters; this one has {len(text)}")
    if found := messages.LOCAL_PATH.search(text):
        raise cli.ColonyError(f"{found[0]} is a path on this computer, which your status comment would carry to "
                              "GitHub: name the file in the repo instead")


def report_command(config: dict, args) -> int:
    """`colony report "<one line of progress>" [--card N]`: this session's report, which keeps its reporting rhythm.
    It goes out in the status comment, sets the intent to working when it was anything else, and stamps the card's
    Last update on the board, for --card or the card the intent names."""
    project, name, now = config["project"]["name"], session_name(), time.time()
    text = " ".join(" ".join(args.text).split())
    if not text:
        raise cli.ColonyError("a report is one line of progress, such as \"the login form passes its tests\"")
    check_text(text)
    held = read_intent(project, name)
    if held.get("intent") != "working":
        held = set_intent(project, name, "working", f"#{args.card}" if args.card else "", now=now)
    held.update(report=text, reported_at=now)
    wait.write_json(intent_path(project, name), clean(held))
    poke_status(project, name)
    card = args.card or next((int(m[1]) for m in [re.search(r"#(\d+)", held.get("why", ""))] if m), None)
    if card and config.get("features", {}).get("board", True):
        from colony import board

        try:
            board.set_fields(config, card, [("Last update", "now")])
        except (cli.ColonyError, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
            print(f"{cli.NAME} report: the report is kept, and #{card}'s Last update stays as it was: {e}",
                  file=sys.stderr)
    print(f"{name}: reported at {clock(now)}: {text}")
    return 0


def team_now(config: dict, now: float) -> tuple[dict[str, Member], str]:
    """Every session the watch can see: the status comments on GitHub and the pulses on this computer, with a note
    when GitHub couldn't be read."""
    from colony import presence

    try:
        alive, gone, note = presence.everyone(config, now)
        statuses = [*alive, *gone]
    except (cli.ColonyError, OSError, ValueError, KeyError) as e:
        statuses, note = [], f"GitHub was not read, so only this computer's sessions show: {e}"
    return merged(from_statuses(statuses), local_members(config)), note


def watch_command(config: dict, args) -> int:
    """`colony watch [--json] [--page] [--folded]`: every lead and helper with what it does and why, what is worth a
    look, and the cards' progress; --page writes the status page now and prints its link; --folded prints the
    helper lines the lead's digest folded (chatter.py)."""
    from colony import chatter, progress, statuspage

    if args.folded:
        for line in chatter.folded(config["project"]["name"], wait.state_name(cli.LEAD)):
            print(line)
        return 0
    now, s = time.time(), settings(config)
    team, note = team_now(config, now)
    if note:
        print(note, file=sys.stderr)
    if args.page:
        cards, why = progress.cards_or_note(config)
        print(statuspage.publish(config, statuspage.render(config, team, s, now, cards, why), force=True))
        return 0
    found = [item for m in team.values() for item in findings(m, s, now, team)]
    if args.json:
        print(json.dumps({"members": [{**asdict(m), "state": standing(m, s, now, team)[0],
                                       "detail": standing(m, s, now, team)[1]} for m in team.values()],
                          "findings": [asdict(item) for item in found]}, default=str))
        return 0
    for kind in ("lead", "helper"):
        group = sorted((m for m in team.values() if m.kind == kind), key=lambda m: (m.lead, m.name))
        print(f"{kind.capitalize()}s ({len(group)}):" if group else f"{kind.capitalize()}s: none seen.")
        for member in group:
            print(f"- {member_line(member, s, now, team)}")
    print("Worth a look:" if found else "Worth a look: nothing; every session works, waits on purpose, or is done.")
    for line in lines_of(found, s):
        print(f"- {line}")
    cards, why = progress.cards_or_note(config)
    print(progress.summary(cards, len([m for m in team.values() if m.kind == "helper"]), now) if why is None else why)
    return 0


def member_line(member: Member, s: Settings, now: float, team: dict[str, Member]) -> str:
    """One session's line in `colony watch` and on the status page."""
    word, detail = standing(member, s, now, team)
    who = member.name + (f" (helper of {member.lead})" if member.kind == "helper" and member.lead else "")
    where = f" on {member.computer}" if member.computer else ""
    report = f" Last report {minutes(now - member.reported_at)} ago: {member.report}." if member.reported_at else ""
    agents = "".join(f" Helper agent \"{a['what']}\" for {minutes(now - a.get('started', now))}." for a in member.agents)
    return f"{who}{where}: {word}, {detail}.{report}{agents}"


def register(sub) -> None:
    """cli.py's route to the watch: `intent`, `report`, `watch`, `progress` and `watchdog`."""
    from colony import progress, watchdog

    p = sub.add_parser("intent", help="say what this session does and why: working, waiting, holding or done, so the "
                                      "watch flags it only when idle without a reason")
    p.add_argument("state", nargs="?", choices=(*INTENTS, "clear"), help="what you do now; none prints it")
    p.add_argument("what", nargs="*", help="what on, such as \"#42 to land\"; waiting and holding need it")
    p.add_argument("--on", metavar="SESSION", help="the session you wait on, such as ana-main-lead, so the watch "
                                                   "says when it is gone, limited or done")
    p.add_argument("--for", dest="minutes", type=float, metavar="MINUTES",
                   help="how long it should take; past it the watch asks")
    p.set_defaults(run=intent_command)
    p = sub.add_parser("report", help="a one-line progress report, at least every [watch] report_minutes while you "
                                      "work; it also stamps the card's Last update")
    p.add_argument("text", nargs="+", help="one line of progress, in quotes")
    p.add_argument("--card", type=int, help="the card it is about, when the intent names none")
    p.set_defaults(run=report_command)
    p = sub.add_parser("watch", help="every lead and helper with what it does and why, what is worth a look, and the "
                                     "cards' progress")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.add_argument("--page", action="store_true", help="write the status page now and print its link")
    p.add_argument("--folded", action="store_true", help="print the helper lines the lead's digest folded")
    p.set_defaults(run=watch_command)
    progress.register(sub)
    watchdog.register(sub)
