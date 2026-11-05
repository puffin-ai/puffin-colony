"""colony wait and colony say: the lines a session waits for, and a lead's line for another lead.

A line is one line of an issue comment, `for <name>: <one sentence> (from <name>)`. A builder's wait ends on the
first line for it that the lead signed. The lead's wait gathers its lines and ends every `lead_digest_minutes`, or
at once on a line that can't wait (see `taken`). Leads talk to each other as `<person>-lead` on one issue per repo,
`Colony: coordination`. Every 15 seconds the wait asks `gh api` for the repo's issue comments changed since its
last read, sending the last ETag, so a quiet poll costs nothing against the rate limit. Its state lives in
~/.colony/<project>/<session>.json, and a session's first wait reads the last hour. Lines are posted through
transport.send. With transport = "relay", a line that also came through Agent Relay is skipped, so it is acted on
once. When colony.cycle imports, the lead's wait also gathers its cycle.stale_lines.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from colony import cli

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
CLOCK = SimpleNamespace(now=time.monotonic, sleep=time.sleep)  # the time a wait reads and sleeps on; tests pass a fake


class GhError(cli.ColonyError):
    """GitHub answered with an error, or gh failed."""


@dataclass(frozen=True)
class Session:
    """Who waits: its name, the names it takes lines for and signs with, and for the lead, the people's logins and the
    cards the batch waits on. The lead answers to `lead` on cards, and to `<person>-lead` on the coordination issue."""

    name: str
    names: frozenset[str]
    people: frozenset[str] = frozenset()
    waiting: frozenset[str] = frozenset()


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
    """Write a value as JSON, making its folder first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def taken(body: str, me: Session, card: str) -> list[tuple[str, bool]]:
    """The lines of one comment on issue `card` that `me` takes, without their markdown, each with whether it can't
    wait for the lead's digest.

    A builder takes a line for it that the lead signed. The lead takes every line for it that it didn't sign, and
    can't wait on one whose sentence starts `urgent:`, `blocked:` or `question:`, on a person's line, or on a `done`
    for a card the batch waits on. A person's line is unsigned, or signed with a login [people] logins lists: agents
    post through their person's own gh login, so the signature, not the comment's author, tells them apart.
    """
    lines = []
    for raw in body.splitlines():
        line = MARKUP.sub("", raw)
        found = LINE.match(line)
        if not found or found[1].lower() not in me.names:
            continue
        signed = SIGNED.search(line)
        sender = signed[1].lower() if signed else ""
        if me.name != cli.LEAD:
            if sender == cli.LEAD:
                lines.append((line, True))
        elif sender not in me.names:
            sentence = found[2]
            done = DONE.match(sentence) is not None and card in me.waiting
            lines.append((line, bool(CANT_WAIT.match(sentence)) or not sender or sender in me.people or done))
    return lines


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


def coordination_issue(repo: str, project: str) -> int:
    """The number of the repo's `Colony: coordination` issue: remembered, else found by title, else created."""
    path = state_path(project, f"{cli.LEAD}-coordination")
    known = read_json(path, None)
    if isinstance(known, int):
        return known
    listed = json.loads(gh("issue", "list", "--repo", repo, "--state", "open", "--search", f'"{COORDINATION}" in:title',
                           "--json", "number,title", "--limit", "50") or "[]")
    numbers = sorted(issue["number"] for issue in listed if issue.get("title") == COORDINATION)
    if not numbers:
        body = f'Leads post lines for each other here: `{cli.NAME} say <lead-name> "<sentence>"`.'
        url = gh("issue", "create", "--repo", repo, "--title", COORDINATION, "--body", body)
        numbers = [int(url.strip().rstrip("/").rsplit("/", 1)[-1])]
    write_json(path, numbers[0])
    return numbers[0]


def poll(repo: str, state: dict, me: Session, mark: str | None = None) -> bool:
    """Read the comments changed since state["since"] once, add the new lines `me` takes to state["pending"], and
    say whether a full page came. The read time moves to the newest comment, so the next poll asks only after it.
    A comment that carries `mark` (transport.MARK, with relay on) reached `me` through the relay too: its lines go
    into seen and never print."""
    path = f"repos/{repo}/issues/comments?since={state['since']}&sort=updated&direction=asc&per_page={PAGE}"
    _, state["etag"], comments = gh_get(path, state.get("etag"))
    seen = state.setdefault("seen", [])
    for comment in comments:
        card, body = str(comment.get("issue_url", "")).rsplit("/", 1)[-1], comment.get("body") or ""
        relayed = mark is not None and mark in body.splitlines()
        for line, cant_wait in taken(body, me, card):
            key = f"{comment['id']}:{line}"
            if key not in seen:
                seen.append(key)
                if not relayed:
                    state["pending"].append([f"#{card} {line}", cant_wait])
    if comments:
        state["since"] = comments[-1]["updated_at"]
    del seen[:-KEEP_SEEN]
    return len(comments) >= PAGE


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


def wait(repo: str, project: str, me: Session, digest: float = DIGEST_MINUTES * 60, clock=None,
         mark: str | None = None, stale=None) -> int:
    """Poll until `me` has lines due, print them and return 0; return 1 after GIVE_UP failed polls in a row. A builder's
    lines are due at once. The lead's are due at the end of the first `digest` seconds that gathered one, or at once
    when one can't wait. Gathered lines stay in the state file until they print. `mark` skips relayed lines (poll),
    and `stale`, the lead's stale-card check (stale_check), runs at the start and at each digest, within its interval."""
    clock = clock or CLOCK
    path = state_path(project, me.name)
    state = read_json(path, {})
    state.setdefault("since", (datetime.now(timezone.utc) - LOOKBACK).strftime("%Y-%m-%dT%H:%M:%SZ"))
    state.setdefault("pending", [])
    failures, digest_at = 0, clock.now() + digest
    add_stale(state, stale)
    while True:
        try:
            more = poll(repo, state, me, mark)
            failures = 0
        except (GhError, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
            failures, more = failures + 1, False
            if failures >= GIVE_UP:
                print(f"{cli.NAME} wait: {e}", file=sys.stderr)
                return 1
        pending = state["pending"]
        if pending and (me.name != cli.LEAD or any(cant_wait for _, cant_wait in pending) or clock.now() >= digest_at):
            print("\n".join(line for line, _ in pending))
            state["pending"] = []
            write_json(path, state)
            return 0
        if clock.now() >= digest_at:
            digest_at = clock.now() + digest
            add_stale(state, stale)
        write_json(path, state)
        if not more:
            clock.sleep(INTERVAL)


def lead_name(config: dict, args) -> str:
    """The lead's name on the coordination issue, `<person>-lead`, such as serdar-lead."""
    return f"{cli.person_of(config, args).lower()}-{cli.LEAD}"


def lead_session(config: dict, name: str) -> Session:
    """The lead as its wait sees it: answering to `lead` and to `name`, its `<person>-lead`, with the people's logins
    and the cards the batch waits on."""
    people = frozenset(str(login).lower() for login in config.get("people", {}).get("logins", []))
    cards = read_json(state_path(config["project"]["name"], f"{cli.LEAD}-waiting"), [])
    return Session(cli.LEAD, frozenset({cli.LEAD, name}), people, frozenset(str(card) for card in cards))


def run(config: dict, args, clock=None) -> int:
    """`colony wait`: wait as $COLONY_SESSION on the repo colony.toml names. The lead's --waiting-on lists the cards
    the batch waits on, and the lead's wait makes sure the coordination issue exists for other leads to post on."""
    from colony import transport

    me = os.environ.get(cli.SESSION_ENV, "").lower()
    if not me:
        raise cli.ColonyError(f"set {cli.SESSION_ENV} to this session's name, such as lead")
    mark = transport.MARK if transport.kind(config) == "relay" else None
    if shutil.which("gh") is None:
        raise cli.ColonyError("gh is not on PATH")
    repo, project, cards = config["project"]["repo"], config["project"]["name"], getattr(args, "waiting_on", None)
    if me != cli.LEAD:
        if cards is not None:
            raise cli.ColonyError("--waiting-on is for the lead's wait")
        return wait(repo, project, Session(me, frozenset({me})), clock=clock, mark=mark)
    waiting_path = state_path(project, f"{cli.LEAD}-waiting")
    if cards is not None:
        write_json(waiting_path, cards)
    try:
        coordination_issue(repo, project)
    except (GhError, ValueError, KeyError) as e:
        print(f"{cli.NAME} wait: no coordination issue yet, the next wait tries again: {e}", file=sys.stderr)
    minutes = float(config.get("messages", {}).get("lead_digest_minutes", DIGEST_MINUTES))
    lead = lead_session(config, lead_name(config, args))
    return wait(repo, project, lead, minutes * 60, clock, mark, stale_check(config))


def say(config: dict, args) -> int:
    """`colony say <lead-name> "<sentence>"`: post a line for another lead on the coordination issue (transport.send)."""
    from colony import transport

    if os.environ.get(cli.SESSION_ENV, "").lower() != cli.LEAD:
        raise cli.ColonyError("say is for leads: a builder posts its line on its card, for its lead")
    transport.kind(config)
    me, to, sentence = lead_name(config, args), args.to.lower(), " ".join(args.sentence.split())
    if not to.endswith(f"-{cli.LEAD}") or to == me or not cli.SESSION_NAME.fullmatch(to):
        raise cli.ColonyError(f"say needs another lead's name, such as burak-lead (you are {me})")
    line = f"for {to}: {sentence} (from {me})"
    if not sentence or len(line) >= MAX_LINE:
        raise cli.ColonyError(f"a line is one sentence under {MAX_LINE} characters, and this one has {len(line)}")
    number = transport.send(config, to, line)
    print(f"#{number} {line}")
    return 0


def card_numbers(value: str) -> list[int]:
    """Check a --waiting-on value, card numbers such as 1251,1252, and return them; "" clears the list."""
    parts = [part.strip().lstrip("#") for part in value.split(",") if part.strip()]
    if not all(part.isdigit() for part in parts):
        raise argparse.ArgumentTypeError(f"{value!r} is not card numbers, such as 1251,1252")
    return [int(part) for part in parts]


def add_commands(sub, wait_parser) -> None:
    """cli.py's route to this module: wait's --waiting-on, and the `say` command."""
    wait_parser.add_argument("--waiting-on", type=card_numbers, metavar="N,N",
                             help="the lead: the cards the batch waits on, whose done lines come at once")
    p = sub.add_parser("say", help="a lead: post a line for another lead on the coordination issue")
    p.add_argument("to", metavar="lead-name", help="the other lead, such as burak-lead")
    p.add_argument("sentence", help="one sentence")
    p.set_defaults(run=say)
