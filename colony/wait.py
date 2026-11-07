"""colony wait and colony say: the lines a session waits for, and a lead's line for another lead.

A line is one line of an issue comment, `for <name>: <one sentence> (from <name>)`. A line is addressed to a session
when it starts with `for <name>:`, or contains `@<login>` for the session's person, or `@all` (see `taken`): a
person's line reaches their lead, and a builder takes only lines its lead signed. A builder's wait ends on the
first line for it. The lead's wait gathers its lines and ends every `lead_digest_minutes`, or at once on a line that
can't wait. The lead also takes, marked `redirected:`, each line for one of its own helpers that it didn't sign,
so a person or another agent writing to a helper directly is never lost (see `taken`). Leads talk to each other as
`<person>-lead` on one issue per repo, `Colony: coordination`. Every 15
seconds the wait asks `gh api` for the repo's issue comments changed since its last read, sending the last ETag, so
a quiet poll costs nothing against the rate limit. Its state lives in ~/.colony/<project>/<session>.json, and a
session's first wait reads the last hour. Lines are posted through transport.send. Every line goes out by `colony post` on a
card, or `colony say` lead to lead. When colony.cycle imports and the card board is on, the lead's wait also
gathers its cycle.stale_lines.

Hack mode puts every line on one board issue, `[messages] board`, after a `[<Name>'s Claude]` prefix (transport.send).
There a person is their GitHub login, the leads are peers named `<login>-lead`, and each signs its lines with that
name, so a builder takes lines from its own person's lead alone.

The unread cache, for the prompt hook: the state file's `unread` lists, as `{card, author, body, url}`, each line
addressed to this session that the wait gathered and hasn't printed. The hook prints them and empties the list; the
wait then drops those lines (`listed` names the ones it put there), so the session never reads a line twice.
`polled_at` is the time of the wait's last poll, which tells the hook a wait is running.

The lead's heartbeat: the lead's wait writes ~/.colony/<project>/lead.heartbeat at each poll, every 15 seconds, holding
its session name, account, token and time. A heartbeat under HEARTBEAT_FRESH old means a lead is alive, so a session
the person opens beside it claims another lead name (`colony`). The heartbeat is also the lock: `beat` writes it only when it is
missing, stale, or holds the writer's own token, under a file lock, so two sessions never both hold the lead. A lead's
token is $COLONY_LEAD_TOKEN, which `colony` and `colony claim` print when they claim a lead.
"""
from __future__ import annotations

import argparse
import functools
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from colony import cli, portable

INTERVAL = 15
LOOKBACK = timedelta(hours=1)
PAGE = 100
GIVE_UP = 40  # failed polls in a row, about 10 minutes, before the wait ends with the error
KEEP_SEEN = 500
DIGEST_MINUTES = 10
MAX_LINE = 300
COORDINATION = f"{cli.NAME.capitalize()}: coordination"
MARKUP = re.compile(r"^[\s>*_`-]+|[\s*_`]+$")
LINE = re.compile(r"for\s+([\w.-]+)\s*:\s*(\S.*)", re.I)
SIGNED = re.compile(r"\(from\s+([\w.-]+)\)\W*$", re.I)
CANT_WAIT = re.compile(r"(urgent|blocked|question)\s*:", re.I)
DONE = re.compile(r"done\b", re.I)
JOINED = re.compile(r"joined\s*:", re.I)  # a helper's first line, from `colony join`, which the lead's wait wakes on
PREFIX = re.compile(r"^\[[^\[\]\n]{1,80}'s [^\[\]\n]{1,40}\]\s*")  # a board post's `[<Name>'s <agent>]`
MENTION = re.compile(r"(?<![\w@./+-])@([A-Za-z0-9][A-Za-z0-9-]*)")  # @<login>, never the middle of an email
LEADING_MENTIONS = re.compile(r"^(?:@[A-Za-z0-9][A-Za-z0-9-]*[\s,:]*)+")
ALL = "all"  # @all reaches every lead, and every builder whose lead signed it
REDIRECTED = "redirected: "  # before a line for one of the lead's helpers that the lead didn't sign
AGENT = "Claude"  # the agent in the post prefix, [<Name>'s Claude]
CLOCK = SimpleNamespace(now=time.monotonic, sleep=time.sleep)  # the time a wait reads and sleeps on; tests pass a fake


LEAD_ENV = f"{cli.NAME.upper()}_LEAD"  # the lead's name a lead and its helpers carry, such as ana-engine-lead
HEARTBEAT_FRESH = 120  # a lead's heartbeat under 2 minutes old is alive; older, any session may take the lead
TOKEN_ENV = f"{cli.NAME.upper()}_LEAD_TOKEN"  # which claim a lead's session holds, so its wait refreshes its own beat
SILENT_AFTER = 5 * 60  # a helper opened with open or join posts its status comment within this long
STAMP = "%Y-%m-%dT%H:%M:%SZ"  # GitHub's updated_at, which a helper's opening time is compared with


class GhError(cli.ColonyError):
    """GitHub answered with an error, or gh failed."""


@dataclass(frozen=True)
class Session:
    """Who waits: its name, the names it takes lines for and signs with, and for the lead, the people's logins, the
    cards the batch waits on, and its own person's logins, which an @<login> line names. The lead answers to `lead`
    on cards, and to `<person>-lead` on the coordination issue; in hack mode to `<person>-lead` alone. A builder takes
    lines signed by one of `leads`. The lead's `helpers` are the helpers it takes redirected lines for, and `others`
    the helpers whose status names another lead, whose `for lead:` lines it leaves to that lead."""

    name: str
    names: frozenset[str]
    people: frozenset[str] = frozenset()
    waiting: frozenset[str] = frozenset()
    logins: frozenset[str] = frozenset()
    leads: frozenset[str] = frozenset({cli.LEAD})
    helpers: frozenset[str] = frozenset()
    others: frozenset[str] = frozenset()


def state_path(project: str, name: str) -> Path:
    """Where a wait keeps a file, such as a session's read time, its ETag and the lines it gathered or printed."""
    return Path.home() / f".{cli.NAME}" / project / f"{name}.json"


def read_json(path: Path, default):
    """A JSON file's value, or `default` when it is missing or unreadable."""
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def write_json(path: Path, value) -> None:
    """Write a value as JSON, making its folder first. The file is replaced whole, so a reader such as the prompt
    hook never sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{os.getpid()}")
    part.write_text(json.dumps(value))
    os.replace(part, path)


class LeadTaken(cli.ColonyError):
    """Another session holds the lead: its heartbeat is fresh and carries another token."""


def heartbeat_path(project: str, name: str = "") -> Path:
    """A lead's heartbeat on this computer: ~/.colony/<project>/<lead name>.heartbeat for a named lead
    ($COLONY_LEAD), and lead.heartbeat for a lead from before lead names."""
    return state_path(project, name or cli.LEAD).with_suffix(".heartbeat")


def read_heartbeat(project: str, name: str = "") -> dict | None:
    """A lead's heartbeat, as {session, account, token, at}, or None when it is missing or unreadable."""
    beat = read_json(heartbeat_path(project, name), None)
    if not isinstance(beat, dict) or not isinstance(beat.get("at"), (int, float)):
        return None
    return beat


def fresh(beat: dict | None, now: float | None = None) -> bool:
    """Whether a heartbeat shows a live lead: it is under HEARTBEAT_FRESH seconds old."""
    return beat is not None and (time.time() if now is None else now) - beat["at"] < HEARTBEAT_FRESH


def new_token() -> str:
    """A fresh lead token, for one claim."""
    return uuid.uuid4().hex[:12]


@contextmanager
def heartbeat_lock(project: str, name: str = ""):
    """Hold the heartbeat's file lock, so a read, check and write of the heartbeat is one step."""
    path = heartbeat_path(project, name).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle, portable.lock(handle):
        yield


def beat(project: str, session: str, account: str, token: str, now: float | None = None, named: bool = False) -> dict:
    """Write a lead's heartbeat and return it: claim it when it is missing or stale, refresh it when it holds
    `token`. Raise LeadTaken when another token's heartbeat is fresh. A `named` lead ($COLONY_LEAD) keeps its own
    heartbeat, <session>.heartbeat, so several leads live side by side; a lead from before names keeps lead.heartbeat."""
    now = time.time() if now is None else now
    name = session if named else ""
    with heartbeat_lock(project, name):
        held = read_heartbeat(project, name)
        if fresh(held, now) and held.get("token", "") != token:
            raise LeadTaken(f"{held.get('session', 'a lead')} on account {held.get('account', 'unknown')} holds the "
                            f"lead: its heartbeat is {int(now - held['at'])} s old")
        mine = {"session": session, "account": account, "token": token, "at": now}
        write_json(heartbeat_path(project, name), mine)
    return mine


def keep_beat(heartbeat) -> None:
    """Run the lead's heartbeat: a LeadTaken goes up and ends the wait, and a failed write goes to stderr."""
    try:
        heartbeat()
    except (OSError, ValueError) as e:
        print(f"{cli.NAME} wait: the heartbeat was not written: {e}", file=sys.stderr)


def mentions(text: str) -> set[str]:
    """The lowercased logins a text mentions as `@<login>`, `all` among them for @all."""
    return {login.lower().rstrip("-") for login in MENTION.findall(text)}


def taken(body: str, me: Session, card: str) -> list[tuple[str, bool]]:
    """The lines of one comment on issue `card` that `me` takes, without their markdown, each with whether it can't
    wait for the lead's digest. A board post's `[<Name>'s <agent>]` prefix stays on the line, and is skipped to read it.

    A line is addressed to `me` when it starts with `for <name>:` for one of its names, or, for the lead, contains
    `@<login>` for its person or `@all`, and for a builder `@all`. A builder takes a line addressed to it that one
    of its leads signed. The lead takes every line addressed to it that it didn't sign, and can't wait on one whose
    sentence starts `urgent:`, `blocked:`, `question:` or `joined:`, on a person's line, or on a `done` for a card
    the batch waits on, or for any card while no batch runs (`me.waiting` is empty). A person's line is unsigned, or
    signed with a login [people] logins lists: agents post through their person's own gh login, so the signature,
    not the comment's author, tells them apart.

    The lead also takes a line for one of its `helpers` that it didn't sign, as `redirected: <line>`, by the same
    rules for when it can't wait: a person or another session writing to a helper directly reaches the lead too. A
    line signed `lead`, as a lead's card lines are, counts as the lead's own.

    A helper's `for lead:` line belongs to that helper's own lead: a lead takes it when the helper is one of its
    `helpers`, even when the lead answers to its name alone, and never when the helper is one of its `others`.
    """
    lines = []
    for raw in body.splitlines():
        line = MARKUP.sub("", raw)
        text = MARKUP.sub("", PREFIX.sub("", line))
        found = LINE.match(text)
        signed = SIGNED.search(text)
        sender = signed[1].lower() if signed else ""
        to = found[1].lower() if found else ""
        redirected = False
        if to == cli.LEAD and me.name == cli.LEAD and sender in me.others:
            continue  # another lead's helper: the line is for that lead
        if found and (to in me.names or (to == cli.LEAD and me.name == cli.LEAD and sender in me.helpers)):
            sentence = found[2]
        elif mentions(text) & (me.logins | {ALL} if me.name == cli.LEAD else {ALL}):
            sentence = LEADING_MENTIONS.sub("", text)
        elif me.name == cli.LEAD and found and found[1].lower() in me.helpers:
            sentence, redirected = found[2], True
        else:
            continue
        if me.name != cli.LEAD:
            if sender in me.leads:
                lines.append((line, True))
        elif sender not in me.names and not (redirected and sender == cli.LEAD):
            done = DONE.match(sentence) is not None and (card in me.waiting or not me.waiting) and not redirected
            cant_wait = bool(CANT_WAIT.match(sentence) or JOINED.match(sentence)) or not sender or \
                sender in me.people or done
            lines.append((REDIRECTED + line if redirected else line, cant_wait))
    return lines


def learn_helpers(state: dict, comments: list) -> None:
    """Remember, in state["helpers"], each helper's lead from the status comments among these comments: a helper
    belongs to the lead its $COLONY_LEAD names, which its status carries (presence.py). state["heard"] keeps when each
    helper's status last changed, which silent_check reads."""
    from colony import presence

    known, heard = state.setdefault("helpers", {}), state.setdefault("heard", {})
    for comment in comments:
        status = presence.parse(comment.get("body") or "")
        if status and status.kind == "helper" and status.lead:
            known[status.name.lower()] = status.lead.lower()
            heard[status.name.lower()] = max(heard.get(status.name.lower(), ""), comment.get("updated_at") or "")


def with_helpers(me: Session, state: dict) -> Session:
    """The lead with its helpers: those on this computer it started with, and each helper whose status names it,
    less each helper whose status names another lead."""
    known = state.get("helpers") or {}
    mine = {name for name, lead in known.items() if lead in me.names}
    theirs = {name for name, lead in known.items() if lead not in me.names}
    return replace(me, helpers=frozenset((me.helpers - theirs) | mine), others=frozenset(theirs))


def local_helpers(project: str) -> frozenset[str]:
    """The sessions other than a lead that ran a wait on this computer, by their state files: the helpers of a lead
    from before lead names, whose helpers post no status."""
    folder = state_path(project, cli.LEAD).parent
    found = set()
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        name = path.stem
        if name == cli.LEAD or name.endswith(f"-{cli.LEAD}") or not cli.SESSION_NAME.fullmatch(name):
            continue
        state = read_json(path, None)
        if isinstance(state, dict) and "pending" in state and "since" in state:
            found.add(name)
    return frozenset(found)


def gh_get(path: str, etag: str | None) -> tuple[int, str | None, list]:
    """GET a REST path through `gh api -i` with the last ETag: the status, the newest ETag, and a 200's JSON."""
    headers = ["-H", f"If-None-Match: {etag}"] if etag else []
    run = subprocess.run(["gh", "api", "-i", *headers, path], capture_output=True, text=True, timeout=60)
    head, _, body = run.stdout.replace("\r\n", "\n").partition("\n\n")
    first = head.split(maxsplit=2)
    status = int(first[1]) if len(first) > 1 and first[1].isdigit() else 0
    for header in head.splitlines()[1:]:
        key, _, value = header.partition(":")
        if key.strip().lower() == "etag":
            etag = value.strip()
    if status not in (200, 304):
        hint = " (run: gh auth login)" if status == 401 else ""
        raise GhError(f"GitHub answered {status or 'nothing'}{hint}: {run.stderr.strip()[:200]}")
    return status, etag, json.loads(body) if status == 200 else []


def gh(*args: str) -> str:
    """Run one gh command and return what it printed; raise GhError when it fails."""
    try:
        run = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise GhError(f"gh {' '.join(args[:2])}: {e}") from None
    if run.returncode:
        raise GhError(f"gh {' '.join(args[:2])} failed: {run.stderr.strip()[:200]}")
    return run.stdout


def coordination_issue(repo: str, project: str, moved: int | None = None) -> int:
    """The number of the repo's open `Colony: coordination` issue: remembered, else found by title (the newest), else
    created. The issue rotates at its comment limit (tidy.rotate), so a number remembered over 10 minutes ago is
    checked again, and dropped once its issue is closed. `moved` remembers the issue a rotation just opened."""
    path = state_path(project, f"{cli.LEAD}-coordination")
    checked = path.with_name(f"{cli.LEAD}-coordination-checked.json")
    if moved is not None:
        write_json(path, moved)
        write_json(checked, time.time())
        return moved
    known = read_json(path, None)
    if isinstance(known, int):
        at = read_json(checked, None)
        if not isinstance(at, (int, float)):  # remembered before rotations: start its 10 minutes now
            write_json(checked, time.time())
            return known
        if time.time() - at < 600:
            return known
        try:
            state = gh("api", f"repos/{repo}/issues/{known}", "--jq", ".state").strip()
        except GhError:
            return known  # GitHub can't say now: keep the number, and ask again next time
        if state == "open":
            write_json(checked, time.time())
            return known
    listed = json.loads(gh("issue", "list", "--repo", repo, "--state", "open", "--search", f'"{COORDINATION}" in:title',
                           "--json", "number,title", "--limit", "50") or "[]")
    numbers = sorted(issue["number"] for issue in listed if issue.get("title") == COORDINATION)
    if not numbers:
        body = f'Leads post lines for each other here: `{cli.NAME} say <lead-name> "<sentence>"`.'
        url = gh("issue", "create", "--repo", repo, "--title", COORDINATION, "--body", body)
        numbers = [int(url.strip().rstrip("/").rsplit("/", 1)[-1])]
    write_json(path, numbers[-1])
    write_json(checked, time.time())
    return numbers[-1]


def unread_entry(repo: str, comment: dict, card: str, line: str) -> dict:
    """One line of the unread cache: its issue, the comment's author, the line, and the comment's address."""
    url = comment.get("html_url") or f"https://github.com/{repo}/issues/{card}#issuecomment-{comment['id']}"
    return {"card": int(card) if card.isdigit() else card, "author": (comment.get("user") or {}).get("login", ""),
            "body": line, "url": url}


def unread_text(entry: dict) -> str:
    """An unread entry as the wait prints it, `#<card> <line>`, which is also its gathered line's text."""
    return f"#{entry.get('card')} {entry.get('body')}"


def poll(repo: str, state: dict, me: Session) -> bool:
    """Read the comments changed since state["since"] once, add the new lines `me` takes to state["pending"] and to
    the unread cache (state["unread"], with their texts in state["listed"]), and say whether a full page came. The
    read time moves to the newest comment, so the next poll asks only after it."""
    path = f"repos/{repo}/issues/comments?since={state['since']}&sort=updated&direction=asc&per_page={PAGE}"
    _, state["etag"], comments = gh_get(path, state.get("etag"))
    if me.name == cli.LEAD:
        learn_helpers(state, comments)
        me = with_helpers(me, state)
    seen = state.setdefault("seen", [])
    for comment in comments:
        card, body = str(comment.get("issue_url", "")).rsplit("/", 1)[-1], comment.get("body") or ""
        for line, cant_wait in taken(body, me, card):
            key = f"{comment['id']}:{line}"
            if key not in seen:
                seen.append(key)
                entry = unread_entry(repo, comment, card, line)
                state["pending"].append([unread_text(entry), cant_wait])
                state.setdefault("unread", []).append(entry)
                state.setdefault("listed", []).append(unread_text(entry))
    if comments:
        state["since"] = comments[-1]["updated_at"]
    del seen[:-KEEP_SEEN]
    return len(comments) >= PAGE


def drop_shown(path: Path, state: dict, listed: set[str]) -> None:
    """Drop each gathered line the prompt hook already showed: one of `listed`, the lines this wait put in the
    state file's unread cache, that the file's cache no longer holds. A file with no cache to read drops nothing."""
    on_file = read_json(path, {})
    cache = on_file.get("unread") if isinstance(on_file, dict) else None
    if not isinstance(cache, list):
        return
    shown = listed - {unread_text(entry) for entry in cache if isinstance(entry, dict)}
    if shown:
        state["pending"] = [item for item in state["pending"] if item[0] not in shown]
        state["unread"] = [entry for entry in state.get("unread", []) if unread_text(entry) not in shown]
        state["listed"] = [text for text in state.get("listed", []) if text not in shown]


def stale_check(config: dict):
    """The lead's stale-card check, cycle.stale_lines(config, now), with the seconds between checks (the cycle's
    STALE_CHECK_MINUTES), or None when colony.cycle doesn't import cleanly or has no stale_lines: the cycle is
    another module's, and its absence never stops a wait."""
    try:
        cycle = importlib.import_module(f"{__package__}.cycle")
        stale_lines = cycle.stale_lines
        every = float(getattr(cycle, "STALE_CHECK_MINUTES", DIGEST_MINUTES)) * 60
    except Exception:
        return None
    return lambda: stale_lines(config, datetime.now(timezone.utc)), every


def add_stale(state: dict, stale) -> None:
    """Gather each line the stale-card check returns, such as a `stale:` line for a card with no update, once. The
    check runs at most once per its interval, across waits; a failing check says so on stderr and gathers nothing."""
    if stale is None:
        return
    check, every = stale
    now = time.time()
    if now - float(state.get("stale_at", 0)) < every:
        return
    state["stale_at"] = now
    try:
        lines = [str(line) for line in check()]
    except Exception as e:
        print(f"{cli.NAME} wait: the stale-card check failed, the wait tries again in {every / 60:g} minutes: {e}",
              file=sys.stderr)
        return
    seen = state.setdefault("seen", [])
    for line in lines:
        if f"stale:{line}" not in seen:
            seen.append(f"stale:{line}")
            state["pending"].append([line, False])


def opened_path(project: str, lead: str) -> Path:
    """Where a lead's helpers opened with `colony open` or `colony join` wait for their first status comment."""
    return state_path(project, f"{lead}-opened")


def expect_status(project: str, lead: str, helper: str, now: float | None = None) -> None:
    """Note that `helper` of `lead` was just opened, so the lead's wait raises it when no status comment follows
    within SILENT_AFTER (silent_check)."""
    path = opened_path(project, lead)
    opened = read_json(path, {})
    opened = opened if isinstance(opened, dict) else {}
    write_json(path, {**opened, helper.lower(): time.time() if now is None else now})


def silent_check(project: str, lead: str):
    """The lead's check for silent helpers: given the wait's state, it returns an `urgent:` line for each helper
    opened over SILENT_AFTER ago whose status comment hasn't changed since (state["heard"]), and forgets that helper,
    so each is raised once. A helper whose status came is forgotten too."""
    path = opened_path(project, lead)

    def check(state: dict, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        opened = read_json(path, {})
        opened = opened if isinstance(opened, dict) else {}
        heard, lines, left = state.get("heard") or {}, [], {}
        for name, at in opened.items():
            if not isinstance(at, (int, float)) or heard.get(name, "") >= time.strftime(STAMP, time.gmtime(at)):
                continue
            if now - at >= SILENT_AFTER:
                lines.append(f"urgent: {name} was opened {int((now - at) // 60)} minutes ago and has posted no status "
                             f"comment; look at its window, or open it again")
            else:
                left[name] = at
        if left != opened:
            write_json(path, left)
        return lines
    return check


def wait(repo: str, project: str, me: Session, digest: float = DIGEST_MINUTES * 60, clock=None,
         stale=None, heartbeat=None, status=None, outbox=None, silent=None) -> int:
    """Poll until `me` has lines due, print them and return 0; return 1 after GIVE_UP failed polls in a row. A builder's
    lines are due at once. The lead's are due at the end of the first `digest` seconds that gathered one, or at once
    when one can't wait. Gathered lines stay in the state file until they print. `stale`, the lead's stale-card check (stale_check), runs at the start and at each digest, within its interval.
    A gathered line the prompt hook showed from the unread cache meanwhile never prints (drop_shown). `heartbeat`, the
    lead's, runs at each poll (beat); a LeadTaken from it ends the wait, and any other failure goes to stderr.
    `outbox` posts the hooks' lines that failed to post (guards.flush_outbox) at each poll, and never raises. `silent`,
    the lead's silent_check, gathers its `urgent:` lines at each poll."""
    clock = clock or CLOCK
    path = state_path(project, state_name(me.name))
    state = read_json(path, {})
    state.setdefault("since", (datetime.now(timezone.utc) - LOOKBACK).strftime("%Y-%m-%dT%H:%M:%SZ"))
    state.setdefault("pending", [])
    state.setdefault("unread", [])
    state.setdefault("listed", [])
    failures, digest_at = 0, clock.now() + digest
    add_stale(state, stale)
    while True:
        listed = set(state["listed"])  # what the file's cache holds since the last write, unless the hook took it
        try:
            more = poll(repo, state, me)
            failures = 0
        except (GhError, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
            failures, more = failures + 1, False
            if failures >= GIVE_UP:
                print(f"{cli.NAME} wait: {e}", file=sys.stderr)
                return 1
        state["polled_at"] = time.time()
        if heartbeat is not None:
            keep_beat(heartbeat)
        if status is not None:
            status()  # edits the session's status comment, at most every 5 minutes, and never raises
        if outbox is not None:
            outbox()
        if silent is not None:
            state["pending"] += [[line, True] for line in silent(state)]
        drop_shown(path, state, listed)
        pending = state["pending"]
        if pending and (me.name != cli.LEAD or any(cant_wait for _, cant_wait in pending) or clock.now() >= digest_at):
            print("\n".join(line for line, _ in pending))
            state["pending"], state["unread"], state["listed"] = [], [], []
            write_json(path, state)
            return 0
        if clock.now() >= digest_at:
            digest_at = clock.now() + digest
            add_stale(state, stale)
        write_json(path, state)
        if not more:
            clock.sleep(INTERVAL)


def lead_name(config: dict, args) -> str:
    """The lead's name: $COLONY_LEAD, such as ana-engine-lead, which `colony claim` gives a lead and its helpers
    carry. A lead from before lead names is `<person>-lead`, such as ana-lead; in hack mode a person is their
    GitHub login, so it is `<login>-lead`."""
    return os.environ.get(LEAD_ENV, "").lower() or f"{cli.person_of(config, args).lower()}-{cli.LEAD}"


def state_name(me: str) -> str:
    """The name a session's state files go under: a named lead's own name, so leads on one computer keep apart, and
    otherwise the session's name ($COLONY_SESSION)."""
    return os.environ[LEAD_ENV].lower() if me == cli.LEAD and named() else me


def named() -> bool:
    """Whether this session carries a lead's name ($COLONY_LEAD): a lead from `colony claim`, or one of its helpers."""
    return bool(os.environ.get(LEAD_ENV))


def hack(config: dict) -> bool:
    """Whether the config runs hack mode, where every line goes to the board issue."""
    return cli.mode(config) == "hack"


def people_names(config: dict) -> dict[str, str]:
    """[people] names: each GitHub login's name for the post prefix, keyed by the lowercased login."""
    names = config.get("people", {}).get("names") or {}
    return {str(login).lower(): str(name) for login, name in names.items()} if isinstance(names, dict) else {}


def known_logins(config: dict) -> set[str]:
    """Every GitHub login colony.toml names, lowercased: [people] logins and names, and in hack mode, where a person
    is their login, each account's person."""
    found = {str(login).lower() for login in config.get("people", {}).get("logins", [])} | set(people_names(config))
    if hack(config):
        found |= {str(account.get("person", "")).lower() for account in config.get("accounts", {}).values()}
    return found - {"any", ""}


def person_logins(config: dict, person: str) -> frozenset[str]:
    """A person's GitHub logins, which an @<login> line names: each known login that is the person or whose
    [people] name is the person's. In hack mode the person is a login."""
    person, names = person.lower(), people_names(config)
    found = {login for login in known_logins(config) if person in (login, names.get(login, "").lower())}
    return frozenset(found | ({person} if hack(config) and person else set()))


def display_name(config: dict, person: str) -> str:
    """The person's name in a post's prefix: their [people] name, else the person as colony.toml writes it."""
    return people_names(config).get(person.lower()) or person


def digest_seconds(config: dict) -> float:
    """How long the lead's wait gathers lines before it prints them: [messages] lead_digest_minutes, in seconds."""
    return float(config.get("messages", {}).get("lead_digest_minutes", DIGEST_MINUTES)) * 60


def lead_session(config: dict, name: str) -> Session:
    """The lead as its wait sees it: answering to `lead` and to `name`, its `<person>-lead` (in hack mode to `name`
    alone, since every person's lead reads the one board), with the people's logins, the cards the batch waits on,
    and its person's logins for @<login> lines."""
    people = frozenset(str(login).lower() for login in config.get("people", {}).get("logins", []))
    cards = read_json(state_path(config["project"]["name"], f"{state_name(cli.LEAD)}-waiting"), [])
    person = name.removesuffix(f"-{cli.LEAD}") if name.endswith(f"-{cli.LEAD}") else ""
    if named():  # ana-engine-lead: the person is the first part, and its helpers address it by name alone
        person = name.split("-", 1)[0]
    names = {name} if hack(config) or named() else {cli.LEAD, name}
    logins = person_logins(config, person) if person else frozenset()
    # A lead from before lead names has the helpers on this computer; a named lead learns its own from their statuses.
    project = config["project"].get("name", "")
    helpers = local_helpers(project) if project and not (hack(config) or named()) else frozenset()
    return Session(cli.LEAD, frozenset(names), people, frozenset(str(card) for card in cards), logins,
                   helpers=helpers)


def builder_session(config: dict, name: str, person: str = "") -> Session:
    """A builder as its wait sees it: answering to its name, and taking the lines its lead signed, `lead`, or in hack
    mode, where every person's builders read the one board, its person's `<person>-lead`."""
    if named():
        leads = {os.environ[LEAD_ENV].lower()}  # a helper belongs to one lead, and takes that lead's lines alone
    else:
        leads = {f"{person.lower()}-{cli.LEAD}"} if hack(config) and person else {cli.LEAD}
    return Session(name, frozenset({name}), leads=frozenset(leads))


def session(config: dict, args, me: str) -> Session:
    """The session named `me` ($COLONY_SESSION) as its wait sees it: the lead (lead_session), else a builder
    (builder_session), whose person is needed only in hack mode. The wait and the prompt hook both read lines so."""
    if me == cli.LEAD:
        return lead_session(config, lead_name(config, args))
    return builder_session(config, me, cli.person_of(config, args) if hack(config) else "")


def run(config: dict, args, clock=None) -> int:
    """`colony wait`: wait as $COLONY_SESSION on the repo colony.toml names. The lead's --waiting-on lists the cards
    the batch waits on, and outside hack mode the lead's wait makes sure the coordination issue exists for other
    leads to post on."""
    from colony import transport

    me = os.environ.get(cli.SESSION_ENV, "").lower()
    if not me:
        raise cli.ColonyError(f"set {cli.SESSION_ENV} to this session's name, such as lead")
    transport.check_transport(config)
    if shutil.which("gh") is None:
        raise cli.ColonyError("gh is not on PATH")
    repo, project, cards = config["project"]["repo"], config["project"]["name"], getattr(args, "waiting_on", None)
    from colony import guards, presence

    outbox = functools.partial(guards.flush_outbox, config)
    if me != cli.LEAD:
        if cards is not None:
            raise cli.ColonyError("--waiting-on is for the lead's wait")
        status = presence.keeper(config, args, me, "helper", lead_name(config, args)) if named() else None
        return wait(repo, project, session(config, args, me), clock=clock, status=status, outbox=outbox)
    waiting_path = state_path(project, f"{state_name(me)}-waiting")
    if cards is not None:
        write_json(waiting_path, cards)
    if not hack(config):
        try:
            coordination_issue(repo, project)
        except (GhError, ValueError, KeyError) as e:
            print(f"{cli.NAME} wait: no coordination issue yet, the next wait tries again: {e}", file=sys.stderr)
    stale = stale_check(config) if config.get("features", {}).get("board", True) else None
    name, account, token = lead_name(config, args), cli.current_account(config), os.environ.get(TOKEN_ENV, "")
    heartbeat = functools.partial(beat, project, name, account, token, named=named())
    keep_beat(heartbeat)  # before any poll, so a second session never holds the same lead
    status = presence.keeper(config, args, name, "lead") if named() else None
    silent = silent_check(project, name) if named() else None  # only a named lead's helpers post a status
    return wait(repo, project, session(config, args, me), digest_seconds(config), clock, stale, heartbeat, status,
                outbox=outbox, silent=silent)


def check_mention(config: dict, to: str, own: frozenset[str], me: str) -> None:
    """Refuse a recipient `@<login>` that names no login colony.toml knows, or the sender's own person; `@all` is
    always a recipient."""
    login = to[1:]
    if not MENTION.fullmatch(to):
        raise cli.ColonyError(f"{to} is not @<login> or @all (you are {me})")
    if login != ALL and login not in known_logins(config):
        raise cli.ColonyError(f"{to} names no login {cli.CONFIG_NAME} knows: add it to [people] logins (you are {me})")
    if login in own:
        raise cli.ColonyError(f"{to} is your own person, whose lead you are (you are {me})")


def compose(to: str, sentence: str, sender: str) -> str:
    """A line: `for <to>: <sentence> (from <sender>)`, or for `@<login>` or `@all`, `<to> <sentence> (from
    <sender>)`, which is also a GitHub mention of the person."""
    return f"{to} {sentence} (from {sender})" if to.startswith("@") else f"for {to}: {sentence} (from {sender})"


def checked(line: str, sentence: str) -> str:
    """The line, once it holds a sentence and stays under MAX_LINE characters."""
    if not sentence or len(line) >= MAX_LINE:
        raise cli.ColonyError(f"a line is one sentence under {MAX_LINE} characters, and this one has {len(line)}")
    return line


def say(config: dict, args) -> int:
    """`colony say <lead-name|@login|@all> "<sentence>"`: post a line for another lead, or for a person's lead, on the
    coordination issue, or on the board in hack mode (transport.send). Lead-to-lead talk is free text under MAX_LINE
    characters, and waits for the other lead's digest unless --urgent starts it with `urgent:`. Before it posts on
    the coordination issue, the issue rotates when it is full (tidy.keep_short)."""
    from colony import tidy, transport

    if os.environ.get(cli.SESSION_ENV, "").lower() != cli.LEAD:
        raise cli.ColonyError("say is for leads: a builder posts its line on its card, for its lead")
    transport.check_transport(config)
    me, to, sentence = lead_name(config, args), args.to.lower(), " ".join(args.sentence.split())
    if sentence and getattr(args, "urgent", False) and not CANT_WAIT.match(sentence):
        sentence = f"urgent: {sentence}"
    if to.startswith("@"):
        check_mention(config, to, person_logins(config, cli.person_of(config, args)), me)
    elif not to.endswith(f"-{cli.LEAD}") or to == me or not cli.SESSION_NAME.fullmatch(to):
        raise cli.ColonyError(f"say needs another lead's name, such as sam-lead, or @login (you are {me})")
    line = checked(compose(to, sentence, me), sentence)
    if not hack(config):
        tidy.keep_short(config, coordination_issue(config["project"]["repo"], config["project"]["name"]))
    number = transport.send(config, to, line)
    print(f"#{number} {line}")
    return 0


def post(config: dict, args) -> int:
    """`colony post [<card>] <to> "<sentence>" [--urgent]`: post `for <to>: <sentence> (from $COLONY_SESSION)` on the
    card through transport.send, with `urgent:` first for --urgent. Builders and the lead post every card line so.
    `<to>` may be `@<login>`, for that person's lead, or `@all`.

    In hack mode the line goes to the board, so the card is optional and named after the sentence as `(#<card>)`, the
    lead signs as `<person>-lead`, and a builder's `lead` means its own person's lead.

    A line has a kind (tidy.check_kind): a helper sends done, question:, blocked: or urgent:, and the lead sends its
    helpers start:, answer: or urgent:. The lead's line for another lead or a person is free text. A helper's `done`
    also moves its card to In review on the board (in_review)."""
    from colony import tidy, transport

    me = os.environ.get(cli.SESSION_ENV, "").lower()
    if not me:
        raise cli.ColonyError(f"set {cli.SESSION_ENV} to this session's name, such as lead")
    transport.check_transport(config)
    on_board, card = hack(config), getattr(args, "card", None)
    # a named lead signs with its name, which its helpers take lines from; so does every lead on the hack board
    sender = lead_name(config, args) if me == cli.LEAD and (on_board or named()) else me
    to, sentence = args.to.lower(), " ".join(args.sentence.split())
    if to.startswith("@"):
        own = person_logins(config, cli.person_of(config, args)) if me == cli.LEAD else frozenset()
        check_mention(config, to, own, me)
    else:
        if to == cli.LEAD and (on_board or (me != cli.LEAD and named())):
            to = lead_name(config, args)  # a helper's `lead` is its own lead, by name, so no other lead takes it
        if not cli.SESSION_NAME.fullmatch(to) or to in (me, sender) or to.isdigit():
            raise cli.ColonyError(f"post needs another session's name, such as lead or builder-2, or @login "
                                  f"(you are {me})")
    if card is None and not on_board:
        raise cli.ColonyError(f'post needs the card first: {cli.NAME} post <card> <name> "<sentence>"')
    if sentence and args.urgent and not CANT_WAIT.match(sentence):
        sentence = f"urgent: {sentence}"
    about = f" (#{card})" if on_board and card is not None and sentence else ""
    line = checked(compose(to, sentence + about, sender), sentence)
    tidy.check_kind(me == cli.LEAD, to, sentence)
    number = transport.send(config, to, line, card=None if on_board else card)
    print(f"#{number} {line}")
    if me != cli.LEAD and card is not None and DONE.match(sentence):
        in_review(config, card)
    return 0


def in_review(config: dict, card: int) -> None:
    """Move a card a helper just posted `done` on to In review, which stamps its Last update, so the lead's stale
    check never raises a finished card. The line is already out, so a board that fails says so on stderr alone."""
    if not config.get("features", {}).get("board", True):
        return
    from colony import board

    try:
        board.set_fields(config, card, [("Status", "In review")])
    except (cli.ColonyError, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
        print(f"{cli.NAME} post: the line went out, and #{card} stays as it was on the board: {e}", file=sys.stderr)


def card_number(value: str) -> int:
    """Check a card value, such as 41 or #41, and return its number."""
    if not value.lstrip("#").isdigit():
        raise argparse.ArgumentTypeError(f"{value!r} is not a card number, such as 41")
    return int(value.lstrip("#"))


def card_numbers(value: str) -> list[int]:
    """Check a --waiting-on value, card numbers such as 1251,1252, and return them; "" clears the list."""
    parts = [part.strip().lstrip("#") for part in value.split(",") if part.strip()]
    if not all(part.isdigit() for part in parts):
        raise argparse.ArgumentTypeError(f"{value!r} is not card numbers, such as 1251,1252")
    return [int(part) for part in parts]


def add_commands(sub, wait_parser) -> None:
    """cli.py's route to this module: wait's --waiting-on, and the `say` and `post` commands."""
    wait_parser.add_argument("--waiting-on", type=card_numbers, metavar="N,N",
                             help="the lead: the cards the batch waits on, whose done lines come at once; with none, every done comes at once")
    p = sub.add_parser("say", help="a lead: post a line for another lead on the coordination issue (the board in "
                                   "hack mode)")
    p.add_argument("to", metavar="lead-name", help="the other lead, such as sam-lead, or @login for that person's "
                                                   "lead, or @all")
    p.add_argument("sentence", help="one sentence")
    p.add_argument("--urgent", action="store_true",
                   help="start the sentence with urgent:, so the other lead gets it at once instead of in its digest")
    p.set_defaults(run=say)
    p = sub.add_parser("post", help="post a line for another session on a card (the board in hack mode), through "
                                    "the transport")
    p.add_argument("card", type=card_number, nargs="?",
                   help="the card's issue number, such as 41; optional in hack mode, where the line goes to the board")
    p.add_argument("to", metavar="name", help="who the line is for, such as lead or builder-2, or @login for that "
                                              "person's lead, or @all")
    p.add_argument("sentence", help="one sentence")
    p.add_argument("--urgent", action="store_true", help="start the sentence with urgent:, so it can't wait")
    p.set_defaults(run=post)
