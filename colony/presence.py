"""Who is alive, across people and computers: each lead's and helper's one status comment, and `colony who`.

Each lead and each helper with a lead's name ($COLONY_LEAD) keeps one status comment on the coordination issue, or on
the board in hack mode. It holds the session's name, kind, lead, person, computer, account, its accounts' room and
its folders, as readable lines plus a hidden JSON copy that `read` parses. Its `colony wait` edits that comment in
place at most every STATUS_EVERY seconds, and never adds a second one (keep). A status older than STATUS_STALE counts
as gone. A lead from before lead names, with no status, shows through its heartbeat on this computer
(wait.heartbeat_path).

The lead registry, .colony/leads.toml, keeps each lead's person and claimed folders: a lead claims its folders with
`colony claim`, which refuses folders a live lead already holds. A lead with no folders holds the rest of the repo.
"""
from __future__ import annotations

import json
import math
import os
import platform
import re
import sys
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from colony import cli
from colony.wait import LEAD_ENV

STATUS_EVERY = 5 * 60  # a status comment is edited in place this often
STATUS_STALE = 15 * 60  # three missed edits: the session counts as gone
MARK = f"{cli.NAME}-status"
HIDDEN = re.compile(rf"<!--\s*{MARK}\s+(\{{.*?\}})\s*-->", re.S)
LEADS_FILE = "leads.toml"
STREAM = re.compile(r"[a-z0-9][a-z0-9-]*")


@dataclass
class Status:
    """One session as its status, or its heartbeat, shows it."""

    name: str
    kind: str  # "lead" or "helper"
    person: str = ""
    lead: str = ""  # a helper's lead
    computer: str = ""
    account: str = ""
    room: list[str] = field(default_factory=list)
    folders: list[str] = field(default_factory=list)
    at: float = 0.0  # Unix time of the last update
    work: str = ""  # a helper's folder, from its transcript (watch.activity)
    branch: str = ""  # the branch checked out there
    waiting: str = ""  # the tool call its session waits on for an answer, such as Bash, or ""
    waiting_since: float = 0.0
    comment: int | None = None  # the status comment's id, when it came from one


def computer() -> str:
    """This computer's short name, such as Macs-Laptop."""
    return platform.node().split(".")[0][:60] or "this computer"


def lead_of(name: str, person: str, stream: str) -> str:
    """A lead's name, `<person>-<stream>-lead`, such as ana-engine-lead."""
    if not STREAM.fullmatch(stream):
        raise cli.ColonyError(f"{stream!r} is not a stream name: use lowercase letters, digits and dashes")
    return f"{person.lower()}-{stream}-{cli.LEAD}"


def body(status: Status) -> str:
    """A status comment: readable lines for people, and the hidden JSON copy `read` parses. It addresses no one, so
    no wait takes a line from it."""
    when = datetime.fromtimestamp(status.at, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"**{status.name}** ({status.kind}" + (f" of {status.lead}" if status.lead else "") + ") status",
             f"- person {status.person}, computer {status.computer}, account {status.account}",
             f"- folders: {', '.join(status.folders) or 'the rest of the repo'}",
             f"- room: {'; '.join(status.room) or 'no reading'}",
             f"- updated {when}, edited in place every {STATUS_EVERY // 60} minutes"]
    data = {key: value for key, value in vars(status).items() if key != "comment"}
    return "\n".join(lines) + f"\n\n<!-- {MARK} {json.dumps(data, separators=(',', ':'))} -->"


TOOL = re.compile(r"[A-Za-z0-9_.:-]{1,64}")  # a tool's name, such as Bash or mcp__x__y
HOST = re.compile(r"[A-Za-z0-9_.-]{1,60}")  # a computer's short name
TEXT_MAX, LIST_MAX = 200, 30


def clean_text(value, pattern: re.Pattern | None = None) -> str:
    """A field from a comment anyone could write, as one short line, or "" when it isn't text or fails `pattern`:
    never a newline into a line a lead reads."""
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())[:TEXT_MAX]
    return value if pattern is None or pattern.fullmatch(value) else ""


def clean_number(value) -> float:
    """A time from a comment anyone could write, or 0.0 when it isn't a finite number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0.0
    return float(value)


def parse(text: str, comment: int | None = None) -> Status | None:
    """The status a comment holds, or None when it holds none or a broken one. On a public repo anyone can comment,
    so each field is checked: a wrong type falls back to its default, text is one short line, a tool or computer
    name keeps its pattern, and a name that isn't a session's drops the status."""
    found = HIDDEN.search(text or "")
    if not found:
        return None
    try:
        data = json.loads(found[1])
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("name"), str):
        return None
    status = Status(clean_text(data["name"]), clean_text(data.get("kind")))
    if not cli.SESSION_NAME.fullmatch(status.name) or status.kind not in ("lead", "helper"):
        return None
    for key in ("person", "lead", "account", "work", "branch"):
        setattr(status, key, clean_text(data.get(key)))
    status.computer, status.waiting = clean_text(data.get("computer"), HOST), clean_text(data.get("waiting"), TOOL)
    for key in ("room", "folders"):
        given = data.get(key)
        setattr(status, key, [text for item in (given if isinstance(given, list) else [])[:LIST_MAX]
                              if (text := clean_text(item))])
    status.at, status.waiting_since = clean_number(data.get("at")), clean_number(data.get("waiting_since"))
    status.comment = comment
    return status


TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}  # GitHub's author_association for someone with access to the repo


def by_team(comment: dict, logins: frozenset[str]) -> bool:
    """Whether a comment's author is one of the team's logins; with none configured, whether GitHub says the author
    has access to the repo. Anyone else's comment never counts as a status."""
    if logins:
        return str((comment.get("user") or {}).get("login") or "").lower() in logins
    return comment.get("author_association") in TRUSTED


def where(config: dict) -> int:
    """The issue the statuses live on: the board in hack mode, else the coordination issue."""
    from colony import tidy, wait

    if wait.hack(config):
        return tidy.board_now(config)  # the board's fresh issue, once it moved
    return wait.coordination_issue(config["project"]["repo"], config["project"]["name"])


def read_comments(config: dict) -> list[dict]:
    """Every comment on the statuses' issue, oldest first. gh prints one comment per line (`--jq '.[]'`), each a whole
    JSON object, so no text inside a comment, such as a board post's "[Ana's Claude] [merged]", can cut the reading."""
    from colony import wait

    repo, number = config["project"]["repo"], where(config)
    out = wait.gh("api", "--paginate", f"repos/{repo}/issues/{number}/comments?per_page=100", "--jq", ".[]")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def read(config: dict) -> list[Status]:
    """Every status comment on the statuses' issue that one of the team's logins wrote, newest copy per name."""
    logins = frozenset(str(login).lower() for login in config.get("people", {}).get("logins", []))
    comments = [comment for comment in read_comments(config) if by_team(comment, logins)]
    found: dict[str, Status] = {}
    for comment in comments:
        status = parse(comment.get("body", ""), comment.get("id"))
        if status and (status.name not in found or status.at >= found[status.name].at):
            found[status.name] = status
    return list(found.values())


def local(config: dict, now: float | None = None) -> list[Status]:
    """The leads alive on this computer by their heartbeat alone, including a lead from before lead names."""
    from colony import wait

    folder = wait.state_path(config["project"]["name"], cli.LEAD).parent
    found = []
    for path in sorted(folder.glob("*.heartbeat")) if folder.is_dir() else []:
        beat = wait.read_json(path, None)
        if isinstance(beat, dict) and wait.fresh(beat if isinstance(beat.get("at"), (int, float)) else None, now):
            name = beat.get("session") or path.stem
            found.append(Status(name, "lead", person=name.split("-", 1)[0], account=beat.get("account", ""),
                                computer=computer(), at=beat["at"], folders=claimed(name)))
    return found


def live(statuses: list[Status], now: float | None = None) -> list[Status]:
    """The statuses updated within STATUS_STALE: a staler one counts as gone."""
    now = time.time() if now is None else now
    return [status for status in statuses if now - status.at < STATUS_STALE]


def everyone(config: dict, now: float | None = None) -> tuple[list[Status], list[Status], str]:
    """The live sessions and the gone ones, merging status comments with this computer's heartbeats, and a note when
    GitHub couldn't be read (then only this computer's leads show)."""
    note = ""
    try:
        statuses = read(config)
    except (cli.ColonyError, OSError, ValueError) as e:
        statuses, note = [], f"GitHub was not read, so only this computer's leads show: {e}"
    alive = live(statuses, now)
    names = {status.name for status in alive}
    alive += [status for status in local(config, now) if status.name not in names]
    gone = [status for status in statuses if status.name not in {s.name for s in alive}]
    return alive, gone, note


# The lead registry: .colony/leads.toml


def leads_path() -> Path:
    """The repo's lead registry, .colony/leads.toml."""
    return cli.repo_root() / cli.DIR / LEADS_FILE


def registry() -> dict[str, dict]:
    """Each lead in .colony/leads.toml with its person and folders, or {} when there is none."""
    try:
        data = tomllib.loads(leads_path().read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    leads = data.get("leads", {})
    return leads if isinstance(leads, dict) else {}


def claimed(name: str) -> list[str]:
    """The folders a lead claimed in the registry, [] for the rest of the repo or an unknown lead."""
    folders = registry().get(name, {}).get("folders", [])
    return [str(folder) for folder in folders] if isinstance(folders, list) else []


def write_registry(leads: dict[str, dict]) -> None:
    """Write .colony/leads.toml, one table per lead."""
    lines = ["# Each lead's person and claimed folders. `colony claim` writes it; a lead with no folders holds the rest.",
             ""]
    for name in sorted(leads):
        lead = leads[name]
        lines += [f'[leads."{name}"]', f'person = {json.dumps(lead.get("person", ""))}',
                  f'folders = {json.dumps(list(lead.get("folders", [])))}', ""]
    leads_path().parent.mkdir(parents=True, exist_ok=True)
    leads_path().write_text("\n".join(lines))


def folder(path: str) -> str:
    """A claimed path as the registry keeps it, relative: a folder with one trailing slash, given with one or found
    on disk, and a file as it is, such as src/app.ts, so a lead can hold one file of a folder another lead shares."""
    given = path.strip()
    clean = given.removeprefix("./").strip("/")
    if not clean or clean.startswith("..") or os.path.isabs(given):
        raise cli.ColonyError(f"{path!r} is not a path in this repo")
    try:
        here = cli.repo_root() / clean
    except cli.ColonyError:
        here = Path(clean)
    if given.endswith("/") or here.is_dir():
        return clean + "/"
    if here.is_file() or "." in clean.rsplit("/", 1)[-1]:
        return clean  # a file, or one not made yet whose name has a dot, such as app.ts or package.json
    return clean + "/"


def overlaps(a: str, b: str) -> bool:
    """Whether two claimed paths overlap: the same path, or a folder (with its slash) that holds the other."""
    return a == b or (a.endswith("/") and b.startswith(a)) or (b.endswith("/") and a.startswith(b))


def inside(path: str, folders: list[str]) -> bool:
    """Whether a path sits in one of the claimed paths: in a folder, or the very file."""
    path = path.strip().removeprefix("./")
    return any(path == f.rstrip("/") or (f.endswith("/") and path.startswith(f)) for f in folders)


def held_by_others(alive: list[Status], me: str) -> dict[str, list[str]]:
    """Each other live lead's claimed folders."""
    return {status.name: status.folders for status in alive if status.kind == "lead" and status.name != me}


# Keeping a session's status comment


def mine(config: dict, args, name: str, kind: str, lead: str = "") -> Status:
    """This session's status now: its person, this computer, its account, its accounts' room, and its folders, a
    helper's being its lead's. Stale readings are fetched first (cli.refresh_usage)."""
    person = cli.person_of(config, args)
    accounts = [(account, a["config_dir"]) for account, a in config.get("accounts", {}).items()
                if a.get("person") in (person, "any") and Path(a["config_dir"]).expanduser().is_dir()]
    cli.refresh_usage([folder for _, folder in accounts])
    rooms = [cli.room_text(account, folder) for account, folder in accounts]
    status = Status(name, kind, person=person, lead=lead, computer=computer(), account=cli.current_account(config),
                    room=rooms, folders=claimed(lead or name), at=time.time())
    if kind == "helper":
        from colony import watch

        doing = watch.activity()
        status.work, status.waiting = doing.get("work", ""), doing.get("waiting", "")
        status.waiting_since, status.branch = doing.get("waiting_since", 0.0), watch.branch(status.work)
    return status


def keep(config: dict, status: Status, state: dict, now: float | None = None) -> bool:
    """Edit this session's status comment in place, or post it the first time, at most every STATUS_EVERY seconds.
    `state` remembers the comment's id and the last edit. Returns whether it wrote."""
    from colony import wait

    now = time.time() if now is None else now
    if now - float(state.get("status_at", 0)) < STATUS_EVERY:
        return False
    repo, text = config["project"]["repo"], body(status)
    comment = state.get("status_id")
    if state.get("status_issue", where(config)) != where(config):
        comment = None  # the board moved: post the status on the fresh one, where `read` looks
    if comment is None:  # find the comment a past session of this name left, before ever adding one
        try:
            comment = next((s.comment for s in read(config) if s.name == status.name and s.comment), None)
        except (cli.ColonyError, ValueError):
            comment = None  # the old comments can't be read now: a fresh one beats no status at all
    if comment is not None:
        try:
            wait.gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{comment}", "-f", f"body={text}")
        except wait.GhError:
            comment = None  # deleted, or on a rotated issue: post a fresh one
    if comment is None:
        made = json.loads(wait.gh("api", f"repos/{repo}/issues/{where(config)}/comments", "-f", f"body={text}"))
        comment = made["id"]
    state["status_id"], state["status_at"], state["status_issue"] = comment, now, where(config)
    return True


def keeper(config: dict, args, name: str, kind: str, lead: str = ""):
    """The callable a wait runs at each poll to keep this session's status (keep), failing quietly to stderr."""
    from colony import wait

    path = wait.state_path(config["project"]["name"], f"{name}-status")
    last = {"error": ""}  # the error printed last: the same one again stays quiet, since the wait polls every 15 s

    def run() -> None:
        state = wait.read_json(path, {})
        state = state if isinstance(state, dict) else {}
        try:
            if keep(config, mine(config, args, name, kind, lead), state):
                wait.write_json(path, state)
            last["error"] = ""
        except (cli.ColonyError, OSError, ValueError, KeyError) as e:
            if str(e) != last["error"]:
                print(f"{cli.NAME} wait: the status comment was not kept: {e}", file=sys.stderr)
            last["error"] = str(e)
    return run


# colony who


def ago(at: float, now: float) -> str:
    return f"{cli.ago(max(0.0, now - at))} ago"


def describe(status: Status, now: float) -> str:
    """One session's line in `colony who`."""
    where_ = status.computer or "unknown computer"
    held = ", ".join(status.folders) or "the rest of the repo"
    who = f"{status.name}" + (f" (helper of {status.lead})" if status.kind == "helper" else "")
    room = f" Room: {'; '.join(status.room)}." if status.room else ""
    folders = f" Folders: {held}." if status.kind == "lead" else ""
    work = f" Works in {status.work}" + (f" on {status.branch}" if status.branch else "") + "." if status.work else ""
    waiting = (f" Its {status.waiting} call has waited {int((now - status.waiting_since) // 60)} minutes for an "
               "answer." if status.waiting and status.waiting_since and now - status.waiting_since >= 120 else "")
    return f"- {who}: {status.person or 'unknown person'} on {where_}, account {status.account or 'unknown'}, " \
           f"{ago(status.at, now)}.{folders}{work}{waiting}{room}"


def who(config: dict, args) -> int:
    """`colony who`: every live lead and helper, across people and computers, with their folders and their
    accounts' room, and the gone ones."""
    from colony import demo, live, wait

    now = time.time()
    try:
        if line := demo.countdown(config):
            print(line)
    except cli.ColonyError as e:
        print(f"{cli.NAME}: {e}", file=sys.stderr)
    if wait.hack(config):
        print(live.summary(config, cli.repo_root()))
    alive, gone, note = everyone(config, now)
    if note:
        print(note, file=sys.stderr)
    leads = [s for s in alive if s.kind == "lead"]
    helpers = [s for s in alive if s.kind == "helper"]
    if note:  # only this computer's heartbeats were read: say what is unknown, never "none alive"
        print(f"Leads on this computer ({len(leads)}), the rest unknown, because GitHub was not read:" if leads
              else "Leads: unknown, because GitHub was not read.")
        for status in sorted(leads, key=lambda s: s.name):
            print(describe(status, now))
        print("Helpers: unknown, because GitHub was not read.")
        return 0
    print(f"Leads ({len(leads)}):" if leads else "Leads: none alive.")
    for status in sorted(leads, key=lambda s: s.name):
        print(describe(status, now))
    print(f"Helpers ({len(helpers)}):" if helpers else "Helpers: none alive.")
    for status in sorted(helpers, key=lambda s: (s.lead, s.name)):
        print(describe(status, now))
    if gone:
        print("Gone, no status in 15 minutes: " + ", ".join(f"{s.name} ({ago(s.at, now)})" for s in gone))
    return 0


def identity(config: dict, args) -> dict[str, str]:
    """This session as its environment names it: its name ($COLONY_SESSION), kind (lead or helper), lead, person, and
    stream, the middle of a lead name such as ana-engine-lead, empty for a lead from before lead names. A repo's own
    tools read it, such as a check that compares with the stream's branch. No session gives empty values."""
    from colony import wait

    me = os.environ.get(cli.SESSION_ENV, "").lower()
    if not me:
        return {"session": "", "kind": "", "lead": "", "person": "", "stream": ""}
    lead = wait.lead_name(config, args) if me == cli.LEAD else (os.environ.get(LEAD_ENV, "").lower() or cli.LEAD)
    try:
        person = cli.person_of(config, args).lower()
    except cli.ColonyError:
        person = lead.split("-", 1)[0] if lead.endswith(f"-{cli.LEAD}") else ""
    middle = lead.removesuffix(f"-{cli.LEAD}")
    stream = middle.split("-", 1)[1] if lead.endswith(f"-{cli.LEAD}") and "-" in middle else ""
    return {"session": me, "kind": "lead" if me == cli.LEAD else "helper", "lead": lead, "person": person,
            "stream": stream}


def whoami(config: dict, args) -> int:
    """`colony whoami [--json]`: this session's name, kind, lead, person and stream, one `key: value` line each, or
    one JSON object."""
    found = identity(config, args)
    if not found["session"]:
        raise cli.ColonyError(f"{cli.SESSION_ENV} is not set: this is not a {cli.DISPLAY} session")
    print(json.dumps(found) if args.json else "\n".join(f"{key}: {value or '-'}" for key, value in found.items()))
    return 0


def add_commands(sub) -> None:
    """cli.py's route to this module: `who` and `whoami`."""
    p = sub.add_parser("who", help="every live lead and helper, across people and computers, with folders and room")
    p.add_argument("--person", help="whose session this is")
    p.set_defaults(run=who)
    p = sub.add_parser("whoami", help="this session's name, kind, lead, person and stream, for a repo's own tools")
    p.add_argument("--person", help="whose session this is, when $COLONY_PERSON is not set")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(run=whoami)
