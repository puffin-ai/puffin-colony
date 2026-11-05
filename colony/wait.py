"""colony wait: wait for the lines addressed to this session, print them, and exit.

A line is one line of an issue comment, `for <name>: <one sentence> (from <name>)`. A builder's wait ends on the
first line for it that the lead signed. The lead's wait ends on any line for it, signed or not (a person's answer
carries no signature), except one it signed itself. Every 15 seconds it asks `gh api` for the repo's issue comments
changed since its last read, sending the last ETag, so a quiet poll costs nothing against the rate limit. Its state
lives in ~/.colony/<project>/<session>.json. A session's first wait reads the last hour, so a card line the lead
posted while the session was opening still counts.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from colony import cli

INTERVAL = 15
LOOKBACK = timedelta(hours=1)
PAGE = 100
GIVE_UP = 40  # failed polls in a row, about 10 minutes, before the wait ends with the error
KEEP_SEEN = 500
MARKUP = re.compile(r"^[\s>*_`-]+|[\s*_`]+$")
LINE = re.compile(r"for\s+([\w.-]+)\s*:\s*\S", re.I)
SIGNED = re.compile(r"\(from\s+([\w.-]+)\)\W*$", re.I)


class GhError(Exception):
    """GitHub answered with neither 200 nor 304."""


def state_path(project: str, session: str) -> Path:
    """Where a session's wait keeps its read time, its ETag and the lines it already printed."""
    return Path.home() / f".{cli.NAME}" / project / f"{session}.json"


def taken(body: str, me: str) -> list[str]:
    """The lines of one comment that the session `me` takes, without their markdown.

    A builder takes a line for it that the lead signed. The lead takes every line for it that it didn't sign.
    """
    lines = []
    for raw in body.splitlines():
        line = MARKUP.sub("", raw)
        found = LINE.match(line)
        if not found or found[1].lower() != me:
            continue
        signed = SIGNED.search(line)
        sender = signed[1].lower() if signed else ""
        if (me == cli.LEAD and sender != cli.LEAD) or (me != cli.LEAD and sender == cli.LEAD):
            lines.append(line)
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


def poll(repo: str, state: dict, me: str) -> tuple[list[str], bool]:
    """Read the comments changed since state["since"] once: the new lines `me` takes, and whether a full page came.

    The read time moves to the newest comment, so the next poll asks only for what came after it.
    """
    path = f"repos/{repo}/issues/comments?since={state['since']}&sort=updated&direction=asc&per_page={PAGE}"
    _, state["etag"], comments = gh_get(path, state.get("etag"))
    seen, found = state.setdefault("seen", []), []
    for comment in comments:
        issue = str(comment.get("issue_url", "")).rsplit("/", 1)[-1]
        for line in taken(comment.get("body") or "", me):
            key = f"{comment['id']}:{line}"
            if key not in seen:
                seen.append(key)
                found.append(f"#{issue} {line}")
    if comments:
        state["since"] = comments[-1]["updated_at"]
    del seen[:-KEEP_SEEN]
    return found, len(comments) >= PAGE


def wait(repo: str, project: str, me: str, interval: float = INTERVAL, sleep=time.sleep) -> int:
    """Poll until there are lines for `me`, print them and return 0; return 1 after GIVE_UP failed polls in a row."""
    path = state_path(project, me)
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {}
    state.setdefault("since", (datetime.now(timezone.utc) - LOOKBACK).strftime("%Y-%m-%dT%H:%M:%SZ"))
    failures = 0
    while True:
        try:
            found, more = poll(repo, state, me)
            failures = 0
        except (GhError, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
            failures, found, more = failures + 1, [], False
            if failures >= GIVE_UP:
                print(f"{cli.NAME} wait: {e}", file=sys.stderr)
                return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state))
        if found:
            print("\n".join(found))
            return 0
        if not more:
            sleep(interval)


def run(config: dict, args) -> int:
    """`colony wait`: wait as the session $COLONY_SESSION names, on the repo colony.toml names."""
    me = os.environ.get(cli.SESSION_ENV, "").lower()
    if not me:
        print(f"{cli.NAME} wait: set {cli.SESSION_ENV} to this session's name, such as lead", file=sys.stderr)
        return 2
    if shutil.which("gh") is None:
        print(f"{cli.NAME} wait: gh is not on PATH", file=sys.stderr)
        return 2
    return wait(config["project"]["repo"], config["project"]["name"], me)
