"""Standing orders: the profiles a person and a team keep, merged for each session (docs/profiles.md).

Three levels hold standing orders, each a TOML file of settings and free-text rules:

- **personal**: `<user config folder>/colony/profile.toml`, which follows the person into every repo and is never
  committed. The folder is $COLONY_CONFIG_HOME when set, else %APPDATA%\\colony on Windows, else
  $XDG_CONFIG_HOME/colony, else ~/.config/colony (config_home). On a computer that several people share under one
  login, each person's own file is `people/<person>.toml` there, and a profile.toml whose `[person] name` is someone
  else's never binds this person's sessions.
- **team**: `.colony/team.toml` in the repo. Colony reads the copy on `origin/<base>`, so the team's orders change only
  through a reviewed pull request, and an edit takes effect when that pull request merges. With no `origin/<base>`,
  the working copy counts, and `show` says so.
- **session**: settings for one session, kept beside the session's identity, `~/.colony/sessions/<id>.profile.toml`
  ($CLAUDE_CODE_SESSION_ID), or `~/.colony/<project>/<session>.profile.toml` outside Claude Code.

How they combine (merge): on the person's side, a session setting beats a mode's, which beats the personal one. The
team's profile applies to everyone, and where it and the person's side disagree, each key's `combine` decides: the
stricter value wins, the smaller number wins, both lists apply, only what both name applies, or the person is asked
once and their answer recorded in their personal profile's `[answers]`. Until they answer, the team's value applies.
Work between people follows the team profile alone (load with team_only=True).

No profile holds a secret: a value or rule that looks like a key or a token is refused when written and dropped,
with a warning that never shows it, when read (looks_secret).

The Python API, for the startup routine and anything else that starts a session:

    load(root=None, person=None, *, config=None, session=True, layers=(), team_only=False) -> Profile
        The merged orders for one session. `root` is the repo (found with git when None), `person` the session's
        person ($COLONY_PERSON when None), `config` a loaded colony.toml (its [project] base and name are read when
        given, else the repo's file is), `session` True for this process's session file, False for none, or a Path,
        and `layers` extra Layer objects that sit between the personal and the session layer in place of the active
        mode's bundle, which load adds itself (boot.mode_layer; layer_from builds a layer from a dict). Profile.settings maps each key to a Setting with its
        value, source and conflict note; Profile.rules lists the rules with their refs (p1, t2, s1); Profile.warnings
        holds every problem found, with no secret in it; Profile.value(key, default) reads one value.
    render(profile, role="lead") -> str
        The standing-order text for a lead's or a helper's start prompt: the role's settings as plain sentences,
        each conflict's outcome, the rules, and the role's guidance lines.
    order_lines(profile, role) -> list[str]
        The same orders as a list of sentences, with no header or guidance: what change_lines compares.
    show_lines(profile) -> list[str]
        `colony profile show`: every active order and where it came from.
    needs_setup(person=None) -> bool, QUESTIONS, ask_setup(...)
        Whether the person's one-time setup has run, and its short set of questions.
    change_lines(config, me, full=False) -> list[str], watcher(config, me), hook_lines(config, me, prompt)
        Live changes: the orders a running session hasn't seen yet, for the prompt hook and `colony wait`.
    looks_secret(text) -> str | None
        What in a text looks like a secret, named and never shown.

Python 3.11+ standard library only.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from colony import cli, portable

HOME_ENV = f"{cli.NAME.upper()}_CONFIG_HOME"  # the folder that holds the personal profile, when set
PERSONAL_FILE = "profile.toml"
PEOPLE_DIR = "people"  # <config home>/people/<person>.toml: each person's own profile on a shared computer
TEAM_FILE = "team.toml"  # in .colony/
TEAM_PATH = f"{cli.DIR}/{TEAM_FILE}"
LEAD_ROLES, ALL_ROLES = ("lead",), ("lead", "helper")
SPECIAL = ("rules", "answers", "imported")  # the top-level tables that hold no setting
META = ("person.name", "person.setup")  # a personal profile's own facts, not orders
TEXT_MAX, ITEM_MAX, RULE_MAX = 500, 200, 600
COMMANDS = ("profile", "prefer")
PROFILE_EVERY = 60  # seconds: a running wait reads the profiles again at most this often (watcher)


@dataclass(frozen=True)
class Key:
    """One setting a profile may hold.

    `kind` is choice, whole (a whole number), number (any number), money (dollars), text or names (a list of short
    texts). `combine` says
    what applies when the team's value and the person's differ: stricter (the earlier of `choices` wins), smaller
    (the smaller number wins), both (both lists or texts apply), common (only what both lists name applies, and the
    person is asked when they share nothing) or ask (the person is asked once, and the team's applies until then).
    `say` is the order's sentence, with {value}, or for a choice a sentence per value. `team` is False for a key only
    a person may set."""

    name: str
    kind: str
    combine: str
    text: str
    say: object
    example: object
    choices: tuple[str, ...] = ()
    low: float = 0
    high: float | None = None
    roles: tuple[str, ...] = ALL_ROLES
    team: bool = True


KEYS = (
    Key("person.role", "text", "ask", "The person's role on the team, in a few words, such as owner or designer.",
        "The person's role on the team: {value}.", "owner", roles=LEAD_ROLES, team=False),
    Key("mode", "text", "ask", "The named mode the person's sessions start in, such as speed or unattended. A mode is "
        "a bundle of these settings, switched on with one word.", "Active mode: {value}.", "speed", roles=LEAD_ROLES,
        team=False),
    Key("team.shape", "choice", "ask", "How the person's top session works: `lead` runs its own helpers; "
        "`orchestrator` runs one lead per task group, and each lead reports to it.",
        {"lead": "Work as one lead that runs its own helpers.",
         "orchestrator": "Work as an orchestrator: run one lead per task group, and have each lead report to you."},
        "lead", choices=("lead", "orchestrator"), roles=LEAD_ROLES),
    Key("team.max_leads", "whole", "smaller", "The most leads, one per task group, that run at once.",
        "Run at most {value} leads at once.", 3, low=1, roles=LEAD_ROLES),
    Key("team.helpers_per_lead", "whole", "smaller", "The most helpers each lead runs.",
        "Give each lead at most {value} helpers.", 4, roles=LEAD_ROLES),
    Key("decisions.autonomy", "choice", "stricter", "How much a lead decides alone: `ask` asks the person before "
        "every decision, `routine` decides routine choices and asks real decisions, `unattended` decides everything "
        "with its recommended default and logs each one.",
        {"ask": "Ask the person before every decision, with your recommended default.",
         "routine": "Decide routine choices alone with your recommended default, and ask the person only real "
                    "decisions.",
         "unattended": "Decide alone: take your recommended default for every decision, and log each one."},
        "routine", choices=("ask", "routine", "unattended"), roles=LEAD_ROLES),
    Key("decisions.answer_wait_minutes", "whole", "ask", "How long a lead waits for the person's answer.",
        "Wait up to {value} minutes for the person's answer.", 30, roles=LEAD_ROLES),
    Key("decisions.without_answer", "choice", "stricter", "What a lead does when no answer comes in time: `hold` "
        "parks that work and goes on with other work, `default` takes the recommended default and logs it.",
        {"hold": "With no answer in that time, hold that work and go on with other work.",
         "default": "With no answer in that time, take your recommended default and log it."},
        "hold", choices=("hold", "default"), roles=LEAD_ROLES),
    Key("decisions.never_raise", "names", "both", "Topics never to raise with the person.",
        "Never raise these topics: {value}.", ["the office move"], roles=LEAD_ROLES),
    Key("monitoring.check_minutes", "whole", "smaller", "How often a lead checks on its helpers and the team.",
        "Check on your helpers and the team every {value} minutes.", 10, low=1, roles=LEAD_ROLES),
    Key("monitoring.report", "choice", "ask", "How a lead keeps the person posted: `quiet` writes only to talk or "
        "when they must act, `progress` as work starts, finishes and merges, `detailed` at each step.",
        {"quiet": "Write to the person only to talk or when they must act, and put your status on the board.",
         "progress": "Tell the person when work starts, finishes and merges.",
         "detailed": "Keep the person posted at each step."},
        "progress", choices=("quiet", "progress", "detailed"), roles=LEAD_ROLES),
    # The pool and machine keys carry the names and units of colony.toml's [pool] and [machine] (capacity.py), so one
    # name means one thing in both places. pool.accounts is the person's order, [people.<person>] accounts there.
    Key("pool.accounts", "names", "common", "The AI accounts to use, by their names in colony.toml, in the person's "
        "order. Names only, never a credential.", "Use these accounts: {value}.", ["main"], roles=LEAD_ROLES),
    Key("pool.order", "choice", "ask", "Which account goes first: `pace`, the one with the most weekly room an hour "
        "until its reset, `reset`, the one whose weekly window resets soonest, or `listed`, the person's order.",
        {"pace": "Use the account with the most weekly room an hour until its reset first.",
         "reset": "Use the account whose weekly window resets soonest first.",
         "listed": "Use the accounts in the listed order."},
        "pace", choices=("pace", "reset", "listed"), roles=LEAD_ROLES),
    Key("pool.out_at", "whole", "smaller", "The percent of a usage window at which an account counts as out of room, "
        "and a session switches to the next one.",
        "Switch to the next account when one reaches {value}% of a usage window.", 95, low=1, high=100,
        roles=LEAD_ROLES),
    Key("pool.max_busy", "whole", "smaller", "The most helpers busy on one account at once.",
        "Keep at most {value} helpers busy on one account at once.", 3, low=1, roles=LEAD_ROLES),
    Key("machine.max_helpers", "whole", "smaller", "The most helpers that run on one computer.",
        "Run at most {value} helpers on one computer.", 4, roles=LEAD_ROLES),
    Key("machine.max_tests", "whole", "smaller", "The most test runs at once on one computer.",
        "Run at most {value} test runs at once on one computer.", 2, low=1),
    Key("machine.busy_load", "number", "smaller", "The load per core at which a computer counts as busy, and less "
        "work starts.", "Start less work when this computer's load per core reaches {value}.", 1.0, low=0.1),
    Key("tests.full_suite", "choice", "stricter", "When the full test suite runs: after every `change`, once per "
        "`batch`, or only at `release`, with the tests for the changed code and the guard tests in between.",
        {"change": "Run the full test suite after every change.",
         "batch": "Run the tests for the changed code and the guard tests after each change, and the full suite once "
                  "per batch.",
         "release": "Run the tests for the changed code and the guard tests; run the full suite only at release or "
                    "when the person asks."},
        "release", choices=("change", "batch", "release")),
    Key("tests.time_cap_minutes", "whole", "ask", "The longest a check may block anyone; a longer one runs in the "
        "background.", "Let a check block for at most {value} minutes; run a longer one in the background.", 10,
        low=1),
    Key("merge.policy", "choice", "stricter", "Whether agents merge: `pr` opens pull requests and the person merges, "
        "`branches` may merge into the branches `merge.branches` names.",
        {"pr": "Never merge: open a pull request, and the person merges.",
         "branches": "Merge only into the branches the next order names; open a pull request for any other."},
        "pr", choices=("pr", "branches")),
    Key("merge.branches", "names", "common", "The branches agents may merge into, when `merge.policy` is `branches`.",
        "Branches you may merge into: {value}.", ["integration"]),
    Key("writing.style", "text", "both", "How agents write: messages, docs, commits and pull requests.",
        "Write in this style: {value}.", "plain words and short sentences"),
    Key("writing.language", "text", "ask", "The language a lead writes to the person in.",
        "Write to the person in {value}.", "English", roles=LEAD_ROLES),
    Key("budgets.dollars_per_day", "money", "smaller", "The most a session spends a day on paid services and model "
        "calls without the person's yes, in dollars.",
        "Spend at most ${value} a day on paid services and model calls without the person's yes.", 0),
    # The keys the startup routine, request intake and the decisions flow read (boot.py, decisions.py).
    Key("intake.plan", "choice", "stricter", "Whether a lead shows its plan for a request before it starts: `show` "
        "shows the task groups, their owners and done-when results and waits for the person's yes; `start` starts at "
        "once and posts the plan for the record.",
        {"show": "Show the plan for each request, its task groups, owners and done-when results, and start only "
                 "after the person's yes.",
         "start": "Start each request at once, without showing the plan first, unless the person asks to see it; "
                  "post the plan for the record."},
        "start", choices=("show", "start"), roles=LEAD_ROLES),
    Key("decisions.gates", "names", "both", "Kinds of work drafted first and built only after the person's yes on "
        "the draft, such as new screens or schema changes.",
        "Draft these first, and build them only after the person's yes on the draft: {value}.", ["new screens"],
        roles=LEAD_ROLES),
)
BY_NAME = {key.name: key for key in KEYS}
COMBINE_TEXT = {"stricter": "the stricter wins", "smaller": "the smaller wins", "both": "both apply",
                "common": "only what both name applies", "ask": "the person is asked once"}


# Secrets


# Shapes transport.holds_secret doesn't look for, which a profile's free text could hold: a `token = …` assignment,
# a JSON web token, and a long run of mixed letters and digits, such as a key pasted alone.
ASSIGNED = re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)\b\s*[:=]\s*"
                      r"['\"]?[^\s'\"]{6,}")
JWT = re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}")
LONG_RUN = re.compile(r"[A-Za-z0-9+/=_-]{32,}")


def looks_secret(text: str) -> str | None:
    """What in the text looks like a secret, such as `a token`, or None. It names the kind alone, never the text."""
    from colony import transport

    text = str(text)
    found = transport.holds_secret(text)
    if found:
        return found
    if ASSIGNED.search(text) or JWT.search(text):
        return "a key or a token"
    for run in LONG_RUN.findall(text):
        if re.search(r"[a-z]", run) and re.search(r"[A-Z]", run) and re.search(r"[0-9]", run):
            return "a key or a token"
    return None


# Where the files live


def config_home(environ: dict | None = None, windows: bool | None = None) -> Path:
    """The folder that holds the personal profile: $COLONY_CONFIG_HOME, else %APPDATA%\\colony on Windows, else
    $XDG_CONFIG_HOME/colony, else ~/.config/colony."""
    env = os.environ if environ is None else environ
    windows = portable.WINDOWS if windows is None else windows
    if env.get(HOME_ENV):
        return Path(env[HOME_ENV]).expanduser()
    if windows and env.get("APPDATA"):
        return Path(env["APPDATA"]) / cli.NAME
    if env.get("XDG_CONFIG_HOME"):
        return Path(env["XDG_CONFIG_HOME"]).expanduser() / cli.NAME
    return Path.home() / ".config" / cli.NAME


def slug(person: str) -> str:
    """A person's name as a file name: lowercase letters, digits, dots, dashes and underscores."""
    return re.sub(r"[^a-z0-9._-]", "-", person.strip().lower()) or "person"


def owner(data: dict) -> str:
    """Whose personal profile this is, `[person] name`, or an empty string."""
    person = data.get("person")
    name = person.get("name") if isinstance(person, dict) else None
    return name.strip() if isinstance(name, str) else ""


def personal_path(person: str | None = None) -> Path:
    """The personal profile that binds the person's sessions, and that writes for them go to: their own
    people/<person>.toml when it exists, or when profile.toml belongs to someone else; else profile.toml."""
    home = config_home()
    main = home / PERSONAL_FILE
    if not person:
        return main
    own = home / PEOPLE_DIR / f"{slug(person)}.toml"
    if own.exists():
        return own
    held = owner(read_toml(main)[0])
    return own if held and held.lower() != person.strip().lower() else main


def session_path(project: str | None = None, name: str | None = None) -> Path | None:
    """This session's own profile: beside its Claude Code identity, ~/.colony/sessions/<id>.profile.toml, or outside
    Claude Code, ~/.colony/<project>/<session>.profile.toml; None when there is no session to keep it for."""
    sid = os.environ.get(cli.CLAUDE_SESSION_ENV, "")
    if cli.CLAUDE_SESSION_ID.fullmatch(sid):
        return cli.identity_path(sid).with_name(f"{sid}.profile.toml")
    me = (name or os.environ.get(cli.SESSION_ENV, "")).lower()
    if project and me:
        from colony import wait

        return Path.home() / f".{cli.NAME}" / project / f"{wait.state_name(me)}.profile.toml"
    return None


def repo() -> Path | None:
    """The top of the git checkout this command runs in, or None outside one: the personal profile works anywhere."""
    top = cli._out(["git", "rev-parse", "--show-toplevel"])
    return Path(top) if top and Path(top).is_dir() else None


def project_table(root: Path | None) -> dict:
    """The repo's colony.toml [project] table, read as it is, or {} when there is none."""
    if root is None:
        return {}
    data, _ = read_toml(root / cli.DIR / cli.CONFIG_NAME)
    table = data.get("project")
    return table if isinstance(table, dict) else {}


def account_folders(root: Path | None) -> list[str]:
    """The settings folders the repo's colony.toml names, for import to read."""
    if root is None:
        return []
    data, _ = read_toml(root / cli.DIR / cli.CONFIG_NAME)
    accounts = data.get("accounts")
    return [str(a["config_dir"]) for a in (accounts.values() if isinstance(accounts, dict) else [])
            if isinstance(a, dict) and isinstance(a.get("config_dir"), str)]


# Reading and writing TOML


def read_toml(path: Path) -> tuple[dict, str]:
    """A TOML file as a dict, and a problem when it can't be read; a missing file is {} with no problem."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, ""
    except OSError as e:
        return {}, f"{path} could not be read ({e.strerror or e})"
    try:
        return tomllib.loads(text), ""
    except tomllib.TOMLDecodeError as e:
        return {}, f"{path} is not valid TOML ({e})"


BARE = re.compile(r"[A-Za-z0-9_-]+")


def toml_key(name: str) -> str:
    return name if BARE.fullmatch(name) else json.dumps(name, ensure_ascii=False)


def toml_value(value) -> str:
    """One value in TOML: a string, number, true or false, list, or inline table."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("a profile holds finite numbers only")
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{toml_key(str(k))} = {toml_value(v)}" for k, v in value.items()) + " }"
    raise ValueError(f"a profile can't hold a {type(value).__name__}")


def dumps(data: dict, header: str = "") -> str:
    """A profile as TOML text: its plain values, then its tables, then its [[rules]], under `header` as comments."""
    lines = [f"# {line}".rstrip() for line in header.splitlines()]

    def tables_of(value) -> bool:
        return isinstance(value, list) and bool(value) and all(isinstance(item, dict) for item in value)

    def table(path: list[str], values: dict) -> None:
        plain = [(k, v) for k, v in values.items() if not isinstance(v, dict) and not tables_of(v)]
        nested = [(k, v) for k, v in values.items() if isinstance(v, dict)]
        if plain or not nested:
            lines.extend(["", "[" + ".".join(map(toml_key, path)) + "]"])
            lines.extend(f"{toml_key(k)} = {toml_value(v)}" for k, v in plain)
        for k, v in nested:
            table([*path, k], v)

    plain = [(k, v) for k, v in data.items() if not isinstance(v, dict) and not tables_of(v)]
    if plain and lines:
        lines.append("")
    lines.extend(f"{toml_key(k)} = {toml_value(v)}" for k, v in plain)
    for k, v in data.items():
        if isinstance(v, dict):
            table([k], v)
    for k, v in data.items():
        if tables_of(v):
            for item in v:
                lines.extend(["", f"[[{toml_key(k)}]]"])
                lines.extend(f"{toml_key(a)} = {toml_value(b)}" for a, b in item.items())
    return "\n".join(lines).lstrip("\n") + "\n"


HEADERS = {
    "personal": f"{cli.DISPLAY}: your personal profile, the standing orders that follow you into every repo.\n"
                "It lives outside every repo and is never committed. Never put a secret here.\n"
                f"`{cli.NAME} profile keys` lists every key, and `{cli.NAME} profile show` what is in force.",
    "team": f"{cli.DISPLAY}: the team profile, the standing orders every person's leads and helpers follow here.\n"
            f"It changes only through a reviewed pull request: {cli.NAME} reads the copy on origin/<base>, so an\n"
            "edit takes effect when its pull request merges. Never put a secret here. Where it and a person's own\n"
            "profile disagree, the stricter wins, or the person is asked once.\n"
            f"`{cli.NAME} profile keys` lists every key.",
    "session": f"{cli.DISPLAY}: this session's own standing orders, for this session alone.",
}


def write_profile(path: Path, data: dict, level: str) -> None:
    """Write a profile whole, through a temporary file. A personal or session file is readable by its owner alone."""
    private = level != "team"
    path.parent.mkdir(parents=True, exist_ok=True, **({"mode": 0o700} if private else {}))
    part = path.with_name(f".{path.name}.{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    with os.fdopen(os.open(part, flags, 0o600 if private else 0o644), "w", encoding="utf-8") as handle:
        handle.write(dumps(data, HEADERS.get(level, "")))
    os.replace(part, path)


@contextmanager
def locked(path: Path):
    """Hold a profile's file lock, so a read, change and write is one step for every session on this computer."""
    lock = Path(path).with_name(f".{Path(path).name}.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a") as handle, portable.lock(handle):
        yield


# Layers


@dataclass(frozen=True)
class Rule:
    """One free-text standing order: its number within its level, its text, its level, when it was added, and where
    it came from (a correction, an import, or empty for by hand)."""

    id: int
    text: str
    level: str
    added: str = ""
    origin: str = ""

    @property
    def ref(self) -> str:
        """Its name in `colony prefer list`, such as p3 for the personal profile's third rule, t1 or s2."""
        return f"{self.level[:1]}{self.id}"


@dataclass
class Layer:
    """One level's orders: `level` is team, personal, session or a mode's name, `label` says where they came from."""

    level: str
    label: str
    settings: dict = field(default_factory=dict)
    rules: list = field(default_factory=list)
    data: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)
    path: Path | None = None


def check_value(key: Key, value) -> tuple[object, str]:
    """A value checked against its key, as (the clean value, ""), or (None, the problem). A problem never quotes a
    value that looks like a secret."""
    texts = value if isinstance(value, list) else [value]
    if any(isinstance(text, str) and looks_secret(text) for text in texts):
        return None, "looks like it holds a secret"
    if key.kind == "choice":
        if isinstance(value, str) and value in key.choices:
            return value, ""
        return None, f"is {value!r}, not one of {', '.join(key.choices)}"
    if key.kind in ("whole", "number", "money"):
        number = isinstance(value, int) or (key.kind != "whole" and isinstance(value, float))
        if isinstance(value, bool) or not number or not math.isfinite(value):
            return None, f"is {value!r}, not a {'whole ' if key.kind == 'whole' else ''}number"
        if value < key.low or (key.high is not None and value > key.high):
            top = f" to {key.high:g}" if key.high is not None else " or more"
            return None, f"is {value!r}, outside {key.low:g}{top}"
        return (int(value) if float(value).is_integer() else value), ""
    if key.kind == "text":
        if not isinstance(value, str) or not value.strip():
            return None, "is not a text"
        clean = " ".join(value.split())
        return (clean, "") if len(clean) <= TEXT_MAX else (None, f"is over {TEXT_MAX} characters")
    if key.kind == "names":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return None, "is not a list of texts"
        clean = list(dict.fromkeys(" ".join(item.split()) for item in value if item.strip()))
        if any(len(item) > ITEM_MAX for item in clean):
            return None, f"has an item over {ITEM_MAX} characters"
        return clean, ""
    return None, "has an unknown kind"


def parse_value(key: Key, text: str):
    """A value typed on the command line, such as `30`, `routine` or `a, b`, as its key's kind, checked."""
    text = text.strip()
    if key.kind == "names":
        value = [part.strip() for part in text.split(",") if part.strip()]
    elif key.kind in ("whole", "number", "money"):
        try:
            value = int(text) if re.fullmatch(r"-?\d+", text) else float(text.lstrip("$"))
        except ValueError:
            raise cli.ColonyError(f"{key.name} takes a number, not {text!r}") from None
    else:
        value = text
    clean, problem = check_value(key, value)
    if problem:
        raise cli.ColonyError(f"{key.name} {problem}" + (": a profile never holds a secret" if "secret" in problem
                                                         else ""))
    return clean


def flatten(data: dict, prefix: str = ""):
    """Each (dotted key, value) in a profile's tables, leaving out the special tables."""
    for name, value in data.items():
        dotted = f"{prefix}{name}"
        if not prefix and name in SPECIAL:
            continue
        if isinstance(value, dict):
            yield from flatten(value, f"{dotted}.")
        else:
            yield dotted, value


def layer_from(data: dict, level: str, label: str, path: Path | None = None) -> Layer:
    """A Layer from a profile's TOML data: each known key checked, each rule read. Unknown keys, values of the
    wrong kind, a team file's personal-only keys and anything that looks like a secret become problems and are
    not used."""
    layer = Layer(level, label, data=data, path=path)
    for name, value in flatten(data):
        if name in META:
            continue
        key = BY_NAME.get(name)
        if key is None:
            layer.problems.append(f"{label}: {name} is not a profile key, so it is not used "
                                  f"(`{cli.NAME} profile keys` lists them)")
            continue
        if level == "team" and not key.team:
            layer.problems.append(f"{label}: {name} is a person's own setting, which a team profile can't set")
            continue
        clean, problem = check_value(key, value)
        if problem:
            layer.problems.append(f"{label}: {name} {problem}, so it is not used")
            continue
        layer.settings[name] = clean
    if level == "team":
        for name in ("answers", "imported"):
            if name in data:
                layer.problems.append(f"{label}: [{name}] belongs in a personal profile, so it is not used")
    rules = data.get("rules", [])
    used: set[int] = set()
    for i, item in enumerate(rules if isinstance(rules, list) else [], 1):
        text = item.get("text") if isinstance(item, dict) else None
        if not isinstance(text, str) or not text.strip():
            layer.problems.append(f"{label}: rule {i} has no text, so it is not used")
            continue
        if looks_secret(text):
            layer.problems.append(f"{label}: rule {i} looks like it holds a secret, so it is not used")
            continue
        number = item.get("id")
        number = number if isinstance(number, int) and not isinstance(number, bool) and number > 0 else i
        while number in used:
            number += 1
        used.add(number)
        layer.rules.append(Rule(number, " ".join(text.split()), level, str(item.get("added", "")),
                                str(item.get("from", ""))))
    return layer


def read_layer(path: Path, level: str, label: str = "") -> Layer | None:
    """A level's file as a Layer, or None when the file doesn't exist."""
    path = Path(path)
    if not path.exists():
        return None
    data, problem = read_toml(path)
    layer = layer_from(data, level, label or f"{level} ({path})", path)
    if problem:
        layer.problems.append(f"{problem}, so its orders are not used")
    return layer


def personal_layer(person: str | None = None) -> tuple[Layer | None, list[str]]:
    """The person's personal profile as a Layer, and why one was set aside: a profile.toml that names another
    person never binds this person's sessions."""
    path, main = personal_path(person), config_home() / PERSONAL_FILE
    notes = []
    if person and path != main and not path.exists():  # personal_path passed over a profile.toml of someone else's
        notes.append(f"{display(main)} is {owner(read_toml(main)[0])}'s personal profile, so it doesn't bind "
                     f"{person}'s sessions: {person}'s own goes in {display(path)}")
    return read_layer(path, "personal", f"personal ({display(path)})"), notes


def team_layer(root: Path | None, base: str = "") -> tuple[Layer | None, list[str]]:
    """The team profile in force, and notes: the copy of .colony/team.toml on origin/<base>, which changes only
    through a merged pull request, or the working copy when there is no origin/<base> to read."""
    if root is None:
        return None, []
    working = root / TEAM_PATH
    ref = f"origin/{base}" if base else ""
    if ref and cli._out(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]):
        text = cli._out(["git", "-C", str(root), "show", f"{ref}:{TEAM_PATH}"])
        notes = []
        try:
            mine = working.read_text(encoding="utf-8") if working.exists() else None
        except OSError:
            mine = None
        if mine is not None and mine.strip() != text.strip():
            notes.append(f"{TEAM_PATH} here differs from {ref}: its changes take effect when their pull request "
                         "merges")
        if not text:
            return None, notes
        label = f"team ({TEAM_PATH} on {ref})"
        try:
            layer = layer_from(tomllib.loads(text), "team", label)
        except tomllib.TOMLDecodeError as e:
            layer = Layer("team", label, problems=[f"{label} is not valid TOML ({e}), so its orders are not used"])
        return layer, notes
    layer = read_layer(working, "team", f"team ({TEAM_PATH}, the working copy: no {ref or 'origin/<base>'} to read)")
    return layer, []


def display(path: Path) -> str:
    """A path with the home folder as ~, for show and messages."""
    try:
        return "~/" + Path(path).resolve().relative_to(Path.home().resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


# Merging


@dataclass
class Setting:
    """One setting in force: its value, the level it came from, and how a disagreement was settled."""

    key: Key
    value: object
    source: str
    note: str = ""
    unresolved: bool = False


@dataclass
class Profile:
    """The merged standing orders for one session (load)."""

    person: str = ""
    settings: dict = field(default_factory=dict)
    rules: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    files: dict = field(default_factory=dict)
    team_only: bool = False

    def value(self, name: str, default=None):
        """One setting's value in force, or `default`."""
        setting = self.settings.get(name)
        return default if setting is None else setting.value

    @property
    def mode(self) -> str:
        return self.value("mode", "") or ""

    @property
    def unresolved(self) -> list:
        return [setting for setting in self.settings.values() if setting.unresolved]

    @property
    def empty(self) -> bool:
        return not self.settings and not self.rules


def shown(value) -> str:
    """A value as an order says it: a list joined with commas."""
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "none"
    return f"{value:g}" if isinstance(value, float) else str(value)


def combine(key: Key, team, own, own_level: str, answers: dict, whose: str) -> tuple[object, str, str, bool]:
    """The value in force when the team's and the person's side differ, as (value, source, note, unresolved)."""
    said = f"the team's says {shown(team)}, {whose} says {shown(own)}"
    if key.combine == "stricter":
        winner = "team" if key.choices.index(team) <= key.choices.index(own) else own_level
        return (team if winner == "team" else own), winner, f"{said}: the stricter, the {winner}'s, applies", False
    if key.combine == "smaller":
        winner = "team" if team <= own else own_level
        return (team if winner == "team" else own), winner, f"{said}: the smaller, the {winner}'s, applies", False
    if key.combine == "both":
        if key.kind == "names":
            return [*team, *(item for item in own if item not in team)], f"team and {own_level}", \
                f"the team's and {whose} both apply", False
        return f"{team}; {own}", f"team and {own_level}", f"the team's and {whose} both apply", False
    if key.combine == "common":
        common = [item for item in own if item in team]
        if common:
            return common, f"team and {own_level}", f"{said}: only what both name applies", False
    if own_level != "personal":  # a session's or a mode's setting is the person's choice for now
        return own, own_level, f"{said}: the {own_level} setting applies, as the person's choice for now", False
    answer = answers.get(key.name) if isinstance(answers, dict) else None
    if isinstance(answer, dict) and answer.get("team") == team and answer.get("mine") == own \
            and answer.get("chose") in ("team", "mine"):
        chose = answer["chose"]
        when = f" on {answer['at']}" if answer.get("at") else ""
        return (team if chose == "team" else own), ("team" if chose == "team" else "personal"), \
            f"{said}: the person chose the {'team' if chose == 'team' else 'personal'} one{when}", False
    return team, "team", (f"{said}: unresolved, so the team's applies until the person answers once "
                          f"(`{cli.NAME} profile resolve {key.name} team|mine`)"), True


def merge(team: Layer | None, own_side: list[Layer], answers: dict, person: str = "") -> dict:
    """Each key's Setting: the person's side's value, the last of `own_side` that sets it, combined with the team's
    (combine)."""
    whose = f"{person}'s" if person else "the person's"
    settings = {}
    for key in KEYS:
        team_value = team.settings.get(key.name) if team else None
        own = next((layer for layer in reversed(own_side) if key.name in layer.settings), None)
        if team_value is None and own is None:
            continue
        if own is None:
            settings[key.name] = Setting(key, team_value, "team")
        elif team_value is None or not key.team:
            settings[key.name] = Setting(key, own.settings[key.name], own.level)
        elif team_value == own.settings[key.name]:
            settings[key.name] = Setting(key, team_value, f"team and {own.level}")
        else:
            value, source, note, unresolved = combine(key, team_value, own.settings[key.name], own.level, answers,
                                                      whose)
            settings[key.name] = Setting(key, value, source, note, unresolved)
    return settings


def load(root=None, person: str | None = None, *, config: dict | None = None, session=True, layers=(),
         team_only: bool = False) -> Profile:
    """The merged standing orders for one session: the team's profile, then the person's own, the active mode's
    bundle (boot.mode_layer, for the `mode` the session or the personal profile names) or the `layers` given
    instead, and this session's, combined key by key (merge). With `team_only`, the team's alone: the orders for
    work between people. It never raises for a broken file: each problem is a warning."""
    root = Path(root) if root else repo()
    given = (config or {}).get("project")
    project = given if isinstance(given, dict) else project_table(root)
    person = (person if person is not None else os.environ.get(cli.PERSON_ENV, "")).strip()
    profile = Profile(person=person, team_only=team_only)
    team, notes = team_layer(root, str(project.get("base", "") or ""))
    profile.warnings += notes
    own_side: list[Layer] = []
    if not team_only:
        personal, set_aside = personal_layer(person or None)
        profile.warnings += set_aside
        if personal:
            own_side.append(personal)
            if not person:
                profile.person = owner(personal.data)
        own_side += [layer for layer in layers if isinstance(layer, Layer)]
        path = session if isinstance(session, Path) else (session_path(project.get("name")) if session else None)
        mine = read_layer(path, "session", f"session ({display(path)})") if path else None
        if not layers:  # the active mode's bundle sits between the personal profile and the session (boot.py)
            named = next((layer.settings["mode"] for layer in (mine, personal) if layer and "mode" in layer.settings),
                         "")
            if named:
                from colony import boot

                own_side.append(boot.mode_layer(named, root, str(project.get("base", "") or "")))
        if mine:
            own_side.append(mine)
    for layer in ([team] if team else []) + own_side:
        profile.warnings += layer.problems
        profile.files[layer.level] = layer.label
        profile.rules += layer.rules
    answers = own_side[0].data.get("answers", {}) if own_side and own_side[0].level == "personal" else {}
    profile.settings = merge(team, own_side, answers, profile.person)
    return profile


# Rendering


# The limits Colony's own commands share with colony.toml: they take the stricter, the smaller, of the two.
LIMITS = ("pool.max_busy", "machine.max_helpers", "machine.max_tests", "machine.busy_load", "tests.time_cap_minutes")
LIMIT_FRESH = 60  # seconds one process keeps the merged profile it read for limit(), unless a profile file changes
_limits: dict[tuple, tuple[float, Profile | None]] = {}


def limit(config: dict, name: str) -> int | float | None:
    """A number a profile sets for one of LIMITS, which a command takes with colony.toml's own, the stricter of the
    two; None when no profile sets it, or the profiles can't be read, so colony.toml decides alone. A default no one
    wrote never counts. One process reads the merged profile again once a profile file on this computer changes, and
    at least once a minute, for the team's, so a long run such as a wait sees a change soon."""
    if name not in LIMITS:
        raise ValueError(f"{name} is no limit a command reads")
    project = str((config.get("project") or {}).get("name") or "")
    home = config_home()
    files = [*home.glob("*.toml"), *home.glob(f"{PEOPLE_DIR}/*.toml")]
    held_session = session_path(project or None)
    files += [held_session] if held_session else []
    stamps = tuple(sorted((str(path), path.stat().st_mtime_ns) for path in files if path.is_file()))
    key = (project, str(home), os.environ.get(cli.PERSON_ENV, ""), os.getcwd(), stamps)
    now = time.monotonic()
    held = _limits.get(key)
    if held is None or now - held[0] > LIMIT_FRESH:
        try:
            merged = load(config=config)
        except (cli.ColonyError, OSError, ValueError):
            merged = None
        held = _limits[key] = (now, merged)
    value = held[1].value(name) if held[1] is not None else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def stricter(config: dict, name: str, value):
    """colony.toml's `value` for one of LIMITS, or the profile's when that is smaller (limit)."""
    found = limit(config, name)
    return value if found is None or (value is not None and value <= found) else found


def say(setting: Setting, profile: Profile) -> str:
    """One setting as the order a session follows."""
    key = setting.key
    if key.kind == "choice":
        return key.say[setting.value]
    if key.name == "budgets.dollars_per_day" and not setting.value:
        return "Spend nothing on paid services or model calls without the person's yes."
    return key.say.format(value=shown(setting.value))


def order_lines(profile: Profile, role: str = "lead") -> list[str]:
    """The orders for a role as sentences: each setting with how a disagreement was settled, then each rule. A
    helper gets only the orders that concern its work."""
    lines = []
    for setting in profile.settings.values():
        key = setting.key
        if role not in key.roles:
            continue
        if key.name == "merge.branches" and profile.value("merge.policy", "pr") != "branches":
            continue
        line = say(setting, profile)
        if setting.note and role == "lead":
            line += f" ({setting.note}.)"
        lines.append(line)
    lines += [f"Rule {rule.ref}: {rule.text}" for rule in profile.rules]
    return lines


def guidance(profile: Profile, role: str) -> list[str]:
    """The lines every rendered set of orders ends with, for the role."""
    if role != "lead":
        return ["Ask your lead, never the person, when an order is unclear."]
    lines = [f"When the person corrects how you work, offer once to keep it as a standing order, and on a yes run "
             f'`{cli.NAME} prefer add "<the rule, in one sentence>" --correction`.']
    if profile.unresolved:
        lines.append(f"Where an order says unresolved, ask the person once which applies, and record the answer with "
                     f"`{cli.NAME} profile resolve <key> team|mine`.")
    if not profile.team_only:
        lines.append("In work with another person's lead, the team profile alone binds: your person's own orders are "
                     "theirs.")
    return lines


def render(profile: Profile, role: str = "lead") -> str:
    """The standing-order text for a lead's or a helper's start prompt."""
    who = f"{profile.person}'s" if profile.person else "this"
    head = f"Standing orders for {who} {'session' if role == 'lead' else 'helper'}"
    head += f", mode {profile.mode}" if profile.mode and role == "lead" else ""
    head += f" (`{cli.NAME} profile show` lists where each comes from):"
    lines = order_lines(profile, role) or ["None yet."]
    return "\n".join([head, *(f"- {line}" for line in lines + guidance(profile, role))])


def show_lines(profile: Profile) -> list[str]:
    """`colony profile show`: the files read, every setting and rule in force and where each came from, and any
    warnings."""
    who = profile.person or "this computer's person"
    lines = [f"Standing orders for {who}" + (f", mode {profile.mode}" if profile.mode else "")
             + (", the team's alone (work between people)" if profile.team_only else "") + "."]
    files = dict(profile.files)
    levels = ["team"] if profile.team_only else ["team", "personal", "session"]
    lines.append("Files: " + "; ".join(files.pop(level, f"{level}: none") for level in levels)
                 + "".join(f"; {label}" for label in files.values()) + ".")
    if profile.settings:
        lines.append("Settings:")
        for name, setting in profile.settings.items():
            note = f"; {setting.note}" if setting.note else ""
            lines.append(f"- {name} = {shown(setting.value)} (from {setting.source}{note})")
    if profile.rules:
        lines.append("Rules:")
        for rule in profile.rules:
            where = ", ".join(part for part in (rule.level, rule.origin, rule.added) if part)
            lines.append(f"- {rule.ref}: {rule.text} ({where})")
    if profile.empty:
        lines.append(f"No orders yet: `{cli.NAME} profile setup` asks a short set of questions once, and "
                     f'`{cli.NAME} prefer add "<rule>"` adds one.')
    for warning in profile.warnings:
        lines.append(f"Note: {warning}.")
    return lines


def as_json(profile: Profile) -> dict:
    """`colony profile show --json`: the same as show_lines, as data."""
    return {"person": profile.person, "mode": profile.mode, "team_only": profile.team_only, "files": profile.files,
            "settings": {name: {"value": s.value, "source": s.source, "note": s.note, "unresolved": s.unresolved}
                         for name, s in profile.settings.items()},
            "rules": [{"ref": r.ref, "text": r.text, "level": r.level, "from": r.origin, "added": r.added}
                      for r in profile.rules],
            "warnings": profile.warnings}


# Setup, asked once


@dataclass(frozen=True)
class Question:
    key: str
    ask: str


QUESTIONS = (
    Question("decisions.autonomy", "How much may your leads decide alone: ask (ask you before every decision), "
             "routine (decide routine choices, ask you real decisions) or unattended (decide everything with the "
             "recommended default, and log it)?"),
    Question("decisions.answer_wait_minutes", "How many minutes should a lead wait for your answer?"),
    Question("decisions.without_answer", "With no answer by then: hold (park that work and go on with other work) or "
             "default (take the recommended default, and log it)?"),
    Question("monitoring.report", "How should your lead keep you posted: quiet (only to talk, or when you must act), "
             "progress (as work starts, finishes and merges) or detailed (at each step)?"),
    Question("tests.full_suite", "When should the full test suite run: change (after every change), batch (once per "
             "batch) or release (only at release; the tests for the changed code otherwise)?"),
    Question("merge.policy", "May agents merge: pr (no, they open pull requests and you merge) or branches (yes, into "
             "branches you name)? This is advice to your leads: only [safety] merge_into in .colony/colony.toml, on "
             "the repo's default branch, lets an agent merge, so for branches setup prints that change for you to "
             "make through a reviewed pull request."),
    Question("decisions.never_raise", "Any topics agents should never raise with you? Comma-separated."),
    Question("budgets.dollars_per_day", "The most a session may spend a day on paid services and model calls "
             "without asking you, in dollars?"),
)
DEFAULTS = {"decisions.autonomy": "routine", "decisions.answer_wait_minutes": 30, "decisions.without_answer": "hold",
            "monitoring.report": "progress", "tests.full_suite": "release", "merge.policy": "pr",
            "decisions.never_raise": [], "budgets.dollars_per_day": 0}


def needs_setup(person: str | None = None) -> bool:
    """Whether the person's one-time setup hasn't run: no personal profile, or one with no `[person] setup` date."""
    layer, _ = personal_layer(person)
    table = layer.data.get("person") if layer else None
    return not (isinstance(table, dict) and table.get("setup"))


def team_settings(root: Path | None) -> dict:
    """The team profile's settings in force, {} with none. A setup question's default is the team's value where it
    sets one, so a yes agrees with the team, else Colony's own (DEFAULTS)."""
    team, _ = team_layer(root, str(project_table(root).get("base", "") or ""))
    return dict(team.settings) if team else {}


def set_value(data: dict, name: str, value) -> None:
    """Put one dotted key's value into a profile's data, making its tables."""
    *tables, last = name.split(".")
    held = data
    for table in tables:
        held = held.setdefault(table, {})
    held[last] = value


def drop_value(data: dict, name: str) -> bool:
    """Take one dotted key out of a profile's data, dropping tables it leaves empty; whether it was there."""
    *tables, last = name.split(".")
    trail, held = [], data
    for table in tables:
        if not isinstance(held.get(table), dict):
            return False
        trail.append((held, table))
        held = held[table]
    if last not in held:
        return False
    del held[last]
    for parent, table in reversed(trail):
        if not parent[table]:
            del parent[table]
    return True


# Live changes: what a running session hasn't seen


CHANGED = f"Your standing orders changed (`{cli.NAME} profile show` lists where each comes from):"


def record_path(project: str, me: str) -> Path:
    """Where a session's last-seen orders are kept: ~/.colony/<project>/<session>-orders.json."""
    from colony import wait

    return wait.state_path(project, f"{wait.state_name(me)}-orders")


def session_id() -> str:
    sid = os.environ.get(cli.CLAUDE_SESSION_ENV, "")
    return sid if cli.CLAUDE_SESSION_ID.fullmatch(sid) else ""


def change_lines(config: dict, me: str, full: bool = False) -> list[str]:
    """The orders session `me` hasn't seen: with `full`, the whole set once per Claude Code session (the prompt
    hook, when a session starts), and after that each change as `now:` and `no longer:` lines. The record of what
    the session saw is shared with its wait, so a change shows once."""
    from colony import wait

    project = (config.get("project") or {}).get("name")
    if not project or not me:
        return []
    role = "lead" if me == cli.LEAD else "helper"
    profile = load(config=config)
    lines = order_lines(profile, role)
    path = record_path(project, me)
    seen = wait.read_json(path, None)
    seen = seen if isinstance(seen, dict) else None
    sid = session_id() if full else ""
    out: list[str] = []
    starting = bool(sid) and (seen is None or seen.get("session") != sid)
    if starting:
        out = render(profile, role).splitlines() if lines else []
    elif seen is not None:
        old = [line for line in seen.get("orders") or [] if isinstance(line, str)]
        moved = [*(f"- now: {line}" for line in lines if line not in old),
                 *(f"- no longer: {line}" for line in old if line not in lines)]
        out = [CHANGED, *moved] if moved else []
    if seen is None and not lines and not starting:
        return out
    record = dict(seen or {})
    record["orders"] = lines
    if starting:
        record["session"] = sid
    if record != seen:
        wait.write_json(path, record)
    return out


def watcher(config: dict, me: str, clock=time.monotonic):
    """The check a running `colony wait` makes at each poll, at most every PROFILE_EVERY seconds: the lines of an
    orders change (change_lines), which end the wait at once so the session sees them. It never raises."""
    last = {"at": None, "error": ""}

    def check(state=None) -> list[str]:
        now = clock()
        if last["at"] is not None and now - last["at"] < PROFILE_EVERY:
            return []
        last["at"] = now
        try:
            lines = change_lines(config, me)
        except (cli.ColonyError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as e:
            if str(e) != last["error"]:
                print(f"{cli.NAME} wait: the standing orders were not read: {e}", file=sys.stderr)
            last["error"] = str(e)
            return []
        last["error"] = ""
        return lines
    return check


CORRECTION = re.compile(
    r"^\W*(no\b|nope\b|don'?t\b|do not\b|never\b|stop\b|wrong\b|not like that|that'?s not|i (told|said|asked) you|"
    r"please don'?t|instead\b)|\b(from now on|next time|every time|in (the )?future|always|never again|stop doing|"
    r"i'?d rather|i prefer)\b", re.I)


def correction_hint(prompt: str) -> str:
    """A reminder for the lead when the person's message reads like a correction, else an empty string."""
    text = " ".join(str(prompt or "").split())[:2000]
    if not text or not CORRECTION.search(text):
        return ""
    return ("If this message corrects how you work, offer the person once to keep it as a standing order, and on a "
            f'yes run `{cli.NAME} prefer add "<the rule, in one sentence>" --correction`.')


def setup_nudge(config: dict, me: str) -> list[str]:
    """Once per Claude Code session, a lead whose person has no personal profile yet hears to ask its setup
    questions once."""
    from colony import wait

    sid, project = session_id(), (config.get("project") or {}).get("name")
    person = os.environ.get(cli.PERSON_ENV, "")
    if me != cli.LEAD or not sid or not project or not needs_setup(person or None):
        return []
    path = record_path(project, me)
    record = wait.read_json(path, {})
    record = record if isinstance(record, dict) else {}
    if record.get("nudged") == sid:
        return []
    record["nudged"] = sid
    wait.write_json(path, record)
    who = person or "The person"
    return [f"{who} has no personal profile yet: ask its short setup questions once, in one message, as "
            f"`{cli.NAME} profile setup` prints them, and it is never asked again."]


def hook_lines(config: dict, me: str, prompt: str = "") -> list[str]:
    """What the prompt hook adds for session `me`: the orders when it starts and any change since, and for a lead,
    the one-time setup reminder and a correction reminder. It never raises."""
    try:
        lines = change_lines(config, me, full=True)
        if me == cli.LEAD:
            lines += setup_nudge(config, me)
            if hint := correction_hint(prompt):
                lines.append(hint)
            from colony import boot  # a prompt that is a mode's name switches that mode on (boot.py)

            lines += boot.prompt_lines(config, prompt)
        return lines
    except (cli.ColonyError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as e:
        print(f"{cli.NAME} hooks unread: the standing orders were not read: {e}", file=sys.stderr)
        return []


# Import from the agent tool's memory and instruction files


@dataclass(frozen=True)
class Candidate:
    """One preference found in an agent tool's file, which becomes a rule only after the person's yes."""

    id: str
    text: str
    origin: str


def claude_slug(root: Path) -> str:
    """The folder name Claude Code keeps a repo's memory under: its path with each other character a dash."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(root))


def import_sources(root: Path | None = None, folders=()) -> list[Path]:
    """The agent tools' instruction and memory files on this computer: each Claude settings folder's CLAUDE.md and
    its memory for this repo (feedback and user memories), Codex's AGENTS.md and Gemini's GEMINI.md."""
    claude = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    found: list[Path] = []
    for folder in dict.fromkeys(str(Path(f).expanduser()) for f in [claude, *folders]):
        found.append(Path(folder) / "CLAUDE.md")
        if root is not None:
            memory = Path(folder) / "projects" / claude_slug(root) / "memory"
            found += sorted(p for p in memory.glob("*.md") if p.name != "MEMORY.md") if memory.is_dir() else []
    found.append(Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "AGENTS.md")
    found.append(Path.home() / ".gemini" / "GEMINI.md")
    return [path for path in dict.fromkeys(found) if path.is_file()]


FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.+)$")


def clean_text(text: str) -> str:
    return " ".join(re.sub(r"\*\*|__", "", text).split())


def file_candidates(path: Path) -> list[str]:
    """The preferences one file holds: a feedback or user memory's first paragraph, or an instruction file's list
    items and paragraphs, leaving out headings, code, tables, imports and comments."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    front = FRONT.match(text)
    if path.parent.name == "memory":
        kind = re.search(r"^\s*type:\s*([\w-]+)", front[1], re.M) if front else None
        if not (kind and kind[1] in ("feedback", "user")):
            return []
        body = text[front.end():].strip()
        first = clean_text(re.split(r"\n\s*\n|\*\*Why:\*\*|\*\*How to apply:\*\*", body)[0])
        return [first] if first else []
    text = text[front.end():] if front else text
    found, paragraph, fenced = [], [], False

    def end_paragraph() -> None:
        if paragraph:
            found.append(clean_text(" ".join(paragraph)))
            paragraph.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("```") or line.startswith("~~~"):
            fenced = not fenced
            end_paragraph()
            continue
        if fenced or not line or line.startswith(("#", "|", "<!--", "@", ">")):
            end_paragraph()
            continue
        item = LIST_ITEM.match(line)
        if item and not raw[:1].isspace():
            end_paragraph()
            found.append(clean_text(item[1]))
        elif not raw[:1].isspace():
            paragraph.append(line)
    end_paragraph()
    return found


def candidates(root: Path | None = None, extra=()) -> tuple[list[Candidate], int]:
    """Every candidate rule in the agent tools' files and the `extra` files, and how many were left out because they
    looked like a secret. Each has a short id that stays the same between runs."""
    paths = [*import_sources(root, account_folders(root)), *(Path(p).expanduser() for p in extra)]
    found, secrets = {}, 0
    for path in dict.fromkeys(paths):
        for text in file_candidates(path):
            if not 12 <= len(text) <= RULE_MAX:
                continue
            if looks_secret(text):
                secrets += 1
                continue
            cid = hashlib.sha1(text.lower().encode()).hexdigest()[:7]
            found.setdefault(cid, Candidate(cid, text, f"import: {display(path)}"))
    return list(found.values()), secrets


# The commands


def person_of(args) -> str:
    return (getattr(args, "person", None) or os.environ.get(cli.PERSON_ENV, "")).strip()


def level_of(args) -> str:
    return "team" if getattr(args, "team", False) else "session" if getattr(args, "session", False) else "personal"


def target(args) -> tuple[Path, str, Path | None]:
    """The file a change writes, its level, and the repo: the personal profile, the team's working copy, or this
    session's file."""
    level, root = level_of(args), repo()
    if level == "team":
        if root is None:
            raise cli.ColonyError(f"--team writes {TEAM_PATH}, so run it inside the repo")
        return root / TEAM_PATH, level, root
    if level == "session":
        path = session_path(project_table(root).get("name"))
        if path is None:
            raise cli.ColonyError(f"--session needs a session: run it inside a Claude Code session, or one with "
                                  f"${cli.SESSION_ENV} set in a set-up repo")
        return path, level, root
    return personal_path(person_of(args) or None), level, root


def refuse_helper() -> None:
    """A helper follows the orders it is given and never changes a profile: its lead does, with the person."""
    me = os.environ.get(cli.SESSION_ENV, "").lower()
    if me and me != cli.LEAD:
        raise cli.ColonyError(f"{me} is a helper, and a helper never changes a profile: ask your lead")


def change(args, edit) -> tuple[Path, str, dict]:
    """Read the target profile under its lock, let `edit` change its data, and write it back."""
    refuse_helper()
    path, level, _ = target(args)
    with locked(path):
        data, problem = read_toml(path)
        if problem:
            raise cli.ColonyError(f"{problem}: fix it by hand first, so nothing in it is lost")
        result = edit(data, level)
        person = person_of(args)
        if level == "personal" and person and not owner(data) and path.name == PERSONAL_FILE:
            set_value(data, "person.name", person)
        write_profile(path, data, level)
    return path, level, result


def written(path: Path, level: str) -> str:
    """What a write says about where it went, and for the team file, how it takes effect."""
    if level == "team":
        return (f"wrote {TEAM_PATH}: commit it on a branch and open a pull request. The team's orders change only "
                "through a reviewed pull request, and take effect when it merges.")
    return f"wrote {display(path)}" + (", for this session alone" if level == "session" else "")


def privacy_note(path: Path) -> str:
    """A warning when the personal profile sits inside a git checkout that doesn't ignore it, where a commit could
    take it along."""
    top = cli._out(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"]) if path.parent.is_dir() else ""
    if not top:
        return ""
    try:
        ignored = subprocess.run(["git", "-C", top, "check-ignore", "-q", str(path)], capture_output=True,
                                 timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ignored = False
    return "" if ignored else (f"your personal profile {display(path)} sits inside the git checkout {top}, which "
                               "doesn't ignore it: add it to that repo's ignore file, so it is never committed")


def show_cmd(args) -> int:
    """`colony profile show`: the active orders and where each came from, or with --orders, the standing-order text
    a session starts with."""
    profile = load(person=person_of(args) or None, team_only=getattr(args, "team_only", False))
    note = privacy_note(personal_path(profile.person or None))
    if note:
        profile.warnings.append(note)
    if getattr(args, "json", False):
        print(json.dumps(as_json(profile), ensure_ascii=False))
    elif getattr(args, "orders", False):
        role = getattr(args, "role", None) or ("lead" if os.environ.get(cli.SESSION_ENV, cli.LEAD).lower() == cli.LEAD
                                               else "helper")
        print(render(profile, role))
    else:
        print("\n".join(show_lines(profile)))
    return 0


def keys_cmd(args) -> int:
    """`colony profile keys`: every key a profile may hold, with its kind and how the team's and a person's combine."""
    for key in KEYS:
        kind = {"choice": f"one of {', '.join(key.choices)}" + (", strictest first" if key.combine == "stricter"
                                                                else ""),
                "whole": "a whole number", "number": "a number", "money": "dollars", "text": "a text",
                "names": "a list of texts"}[key.kind]
        where = "personal and session only" if not key.team else COMBINE_TEXT[key.combine]
        print(f"{key.name}: {kind}; {where}. {key.text}")
    print('rules: free-text orders, added with `colony prefer add "<rule>"`; the team\'s and the person\'s all apply.')
    return 0


def set_cmd(args) -> int:
    """`colony profile set <key> <value> [--team|--session]`."""
    key = BY_NAME.get(args.key)
    if key is None:
        raise cli.ColonyError(f"{args.key!r} is not a profile key: `{cli.NAME} profile keys` lists them")
    if level_of(args) == "team" and not key.team:
        raise cli.ColonyError(f"{key.name} is a person's own setting, which a team profile can't set")
    value = parse_value(key, args.value)
    path, level, _ = change(args, lambda data, level: set_value(data, key.name, value))
    print(f"{key.name} = {shown(value)}: {written(path, level)}")
    return 0


def unset_cmd(args) -> int:
    """`colony profile unset <key> [--team|--session]`."""
    if args.key not in BY_NAME:
        raise cli.ColonyError(f"{args.key!r} is not a profile key: `{cli.NAME} profile keys` lists them")
    path, level, was = change(args, lambda data, level: drop_value(data, args.key))
    print(f"{args.key} {'removed' if was else 'was not set'}: {written(path, level)}")
    return 0


def resolve_cmd(args) -> int:
    """`colony profile resolve <key> team|mine`: record the person's answer where the team's and their own profile
    disagree and neither is stricter, so they are asked once."""
    person = person_of(args) or None
    profile = load(person=person, session=False)
    setting = profile.settings.get(args.key)
    root = repo()
    team, _ = team_layer(root, str(project_table(root).get("base", "") or ""))
    personal, _ = personal_layer(person)
    team_value = team.settings.get(args.key) if team else None
    mine = personal.settings.get(args.key) if personal else None
    if setting is None or team_value is None or mine is None or team_value == mine:
        raise cli.ColonyError(f"the team's and the personal profile don't disagree on {args.key}, so there is "
                              "nothing to resolve")
    if setting.key.combine not in ("ask", "common"):
        raise cli.ColonyError(f"{args.key} needs no answer: {COMBINE_TEXT[setting.key.combine]}")
    answer = {"team": team_value, "mine": mine, "chose": args.choice, "at": date.today().isoformat()}
    args.team = args.session = False
    path, level, _ = change(args, lambda data, level: set_value(data, "answers", {**data.get("answers", {}),
                                                                                  args.key: answer}))
    chosen, which = (team_value, "team") if args.choice == "team" else (mine, "personal")
    print(f"{args.key} = {shown(chosen)}, the {which} one: {written(path, level)}. It is asked again only if either "
          "side changes.")
    return 0


def setup_cmd(args) -> int:
    """`colony profile setup`: the one-time questions that write the personal profile. In a terminal it asks them;
    elsewhere, such as in an agent's session, it prints them for the lead to ask in one message, and `--set` or
    `--defaults` writes the answers. Once done, it never asks again unless `--again`."""
    person = person_of(args) or None
    path = personal_path(person)
    if not needs_setup(person) and not args.again:
        print(f"Setup ran already ({display(path)}), so it isn't asked again. Change one setting with "
              f"`{cli.NAME} profile set <key> <value>`, or run `{cli.NAME} profile setup --again`.")
        return 0
    team = team_settings(repo())
    defaults = {**DEFAULTS, **{name: value for name, value in team.items() if name in DEFAULTS}}
    answers: dict = {}
    for pair in args.set or []:
        name, sep, text = pair.partition("=")
        key = BY_NAME.get(name.strip())
        if not sep or key is None:
            raise cli.ColonyError(f"--set takes <key>=<value> with a profile key, not {pair!r}: "
                                  f"`{cli.NAME} profile keys` lists them")
        answers[key.name] = parse_value(key, text)
    if not answers and not args.defaults:
        if portable.is_terminal(sys.stdin) and not cli.in_claude_code():
            answers = ask_setup(defaults)
        else:
            print(f"Ask the person these {len(QUESTIONS)} questions once, numbered, in one message, each with its "
                  'default, so "defaults" is a full answer:')
            for i, question in enumerate(QUESTIONS, 1):
                print(f"{i}. {question.ask} Default: {shown(defaults[question.key]) or 'none'}.")
            print(f"Then run `{cli.NAME} profile setup --set <key>=<value> ...` with their answers, by these keys in "
                  f"order: {', '.join(q.key for q in QUESTIONS)}; with merge.policy=branches, add merge.branches=<a, "
                  f"b>. `{cli.NAME} profile setup --defaults` takes every default. Questions left out take their "
                  "default.")
            return 0
    # An answer is written as given. A question left out keeps a value the profile already holds, else takes Colony's
    # default, written so the orders say it, unless the team profile sets that key: then nothing is written, so the
    # team's value, and any later change to it, apply.
    fallback = {name: value for name, value in DEFAULTS.items() if name not in team and value != []}

    def edit(data: dict, level: str) -> None:
        held = dict(flatten(data))
        for name, value in {**{k: v for k, v in fallback.items() if k not in held}, **answers}.items():
            if value == []:
                drop_value(data, name)
            else:
                set_value(data, name, value)
        set_value(data, "person.setup", date.today().isoformat())

    args.team = args.session = False
    path, level, _ = change(args, edit)
    print(f"Set up the personal profile: {written(path, level)}. It isn't asked again.")
    note = privacy_note(path)
    if note:
        print(f"Note: {note}.")
    branches = answers.get("merge.branches") if answers.get("merge.policy") == "branches" else None
    if branches:
        print(merge_change(branches))
    print(f"Next: `{cli.NAME} profile import` finds preferences in your agent tool's memory and instruction files, "
          "and adds each one only after your yes.")
    return 0


def merge_change(branches: list[str]) -> str:
    """What lets agents merge into the branches a person named: the colony.toml change, since the merge guard reads
    [safety] merge_into on the repo's default branch alone, never a profile."""
    listed = ", ".join(json.dumps(branch) for branch in branches)
    return (f"Merges into {', '.join(branches)} are allowed only once [safety] merge_into names them in "
            f".{cli.NAME}/{cli.CONFIG_NAME}, through a reviewed pull request into the default branch. The profile "
            f"only tells your leads. Add this, and merge it:\n\n[safety]\nmerge_into = [{listed}]\n")


def ask_setup(defaults: dict) -> dict:
    """Ask the setup questions in a terminal, one at a time; Enter keeps the default."""
    answers = {}
    for i, question in enumerate(QUESTIONS, 1):
        key = BY_NAME[question.key]
        while True:
            given = input(f"{i}. {question.ask} [{shown(defaults[key.name]) or 'none'}] ").strip()
            if not given:
                break
            try:
                answers[key.name] = parse_value(key, given)
                break
            except cli.ColonyError as e:
                print(f"  {e}")
        if key.name == "merge.policy" and answers.get(key.name) == "branches":
            given = input("   Which branches may agents merge into? Comma-separated: ").strip()
            if given:
                answers["merge.branches"] = parse_value(BY_NAME["merge.branches"], given)
    return answers


def init_cmd(args) -> int:
    """`colony profile init`: write .colony/team.toml, every team key as a commented example, for the team to fill
    in through reviewed pull requests. It never overwrites one."""
    refuse_helper()
    root = repo()
    if root is None:
        raise cli.ColonyError(f"run it inside the repo: it writes {TEAM_PATH}")
    path = root / TEAM_PATH
    if path.exists():
        print(f"{TEAM_PATH} is there already, and stays as it is.")
        return 0
    lines = [f"# {line}".rstrip() for line in HEADERS["team"].splitlines()]
    table = ""
    for key in KEYS:
        if not key.team:
            continue
        head, _, name = key.name.rpartition(".")
        if head != table:
            lines += ["", f"# [{head}]"]
            table = head
        lines.append(f"# {name} = {toml_value(key.example)}")
    lines += ["", "# [[rules]]", "# id = 1", '# text = "A rule every session here follows, in one sentence."', ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {TEAM_PATH}, every key commented out. The team fills it in through reviewed pull requests.")
    return 0


def import_cmd(args) -> int:
    """`colony profile import`: find preferences in the agent tools' memory and instruction files, and add each to
    the personal profile only after the person's yes. In a terminal it asks about each; elsewhere it lists them for
    the lead to ask, and `--accept` and `--decline` record the answers. A declined one is never offered again."""
    person = person_of(args) or None
    found, secrets = candidates(repo(), args.from_file or [])
    layer, _ = personal_layer(person)
    data = layer.data if layer else {}
    imported = data.get("imported") if isinstance(data.get("imported"), dict) else {}
    declined = set(imported.get("declined", []) if isinstance(imported.get("declined", []), list) else [])
    have = {rule.text.lower() for rule in (layer.rules if layer else [])}
    fresh = [c for c in found if c.id not in declined and c.text.lower() not in have]
    accept = [part.strip() for value in args.accept or [] for part in value.split(",") if part.strip()]
    decline = [part.strip() for value in args.decline or [] for part in value.split(",") if part.strip()]
    if not accept and not decline:
        if not fresh:
            print("Nothing new to import." + (f" {secrets} looked like a secret and were left out." if secrets else ""))
            return 0
        if portable.is_terminal(sys.stdin) and not cli.in_claude_code():
            accept, decline = ask_import(fresh)
        else:
            print(f"Ask the person about each of these {len(fresh)}, one yes or no each: nothing is added without "
                  "their yes.")
            for c in fresh:
                print(f"- {c.id}: {c.text} ({c.origin})")
            if secrets:
                print(f"{secrets} more looked like a secret and were left out.")
            print(f"Then run `{cli.NAME} profile import --accept <id>,<id> --decline <id>,<id>`.")
            return 0
    by_id = {c.id: c for c in fresh}
    unknown = [cid for cid in accept + decline if cid not in by_id]
    if unknown:
        raise cli.ColonyError(f"{', '.join(unknown)} is no candidate on offer: run `{cli.NAME} profile import` to "
                              "list them")
    today = date.today().isoformat()

    def edit(data: dict, level: str) -> None:
        rules = data.setdefault("rules", [])
        for cid in accept:
            add_rule(rules, by_id[cid].text, today, by_id[cid].origin)
        if decline:
            table = data.setdefault("imported", {})
            table["declined"] = list(dict.fromkeys([*table.get("declined", []), *decline]))

    args.team = args.session = False
    path, level, _ = change(args, edit)
    print(f"Added {len(accept)} rule{'s' if len(accept) != 1 else ''}, and {len(decline)} declined won't be offered "
          f"again: {written(path, level)}.")
    return 0


def ask_import(fresh: list[Candidate]) -> tuple[list[str], list[str]]:
    """Ask about each candidate in a terminal: y adds it, n declines it for good, q stops and keeps the rest for
    later."""
    accept, decline = [], []
    for c in fresh:
        given = input(f"{c.text}\n  ({c.origin}) Keep as a standing order? [y/n/q] ").strip().lower()
        if given.startswith("q"):
            break
        (accept if given.startswith("y") else decline if given.startswith("n") else []).append(c.id)
    return accept, decline


def add_rule(rules: list, text: str, today: str, origin: str = "") -> int:
    """Append a rule to a profile's [[rules]], with the next free number, and return that number."""
    numbers = [item.get("id") for item in rules if isinstance(item, dict) and isinstance(item.get("id"), int)]
    number = max(numbers + [len(rules)], default=0) + 1
    rules.append({"id": number, "text": text, "added": today, **({"from": origin} if origin else {})})
    return number


def prefer_add(args) -> int:
    """`colony prefer add "<rule>" [--team|--session] [--correction]`: keep a rule as a standing order."""
    text = " ".join(" ".join(args.rule).split())
    if not text:
        raise cli.ColonyError("say the rule, in quotes")
    if len(text) > RULE_MAX:
        raise cli.ColonyError(f"a rule is at most {RULE_MAX} characters: say it in one sentence")
    if found := looks_secret(text):
        raise cli.ColonyError(f"the rule holds what looks like {found}, and a profile never holds a secret: keep "
                              "secrets in your secret store and name it instead")
    origin = "correction" if args.correction else ""
    path, level, number = change(args, lambda data, level: add_rule(data.setdefault("rules", []), text,
                                                                     date.today().isoformat(), origin))
    print(f"Rule {level[:1]}{number} added: {written(path, level)}")
    return 0


def prefer_list(args) -> int:
    """`colony prefer list`: every rule in force, with its ref and where it came from."""
    profile = load(person=person_of(args) or None)
    wanted = level_of(args) if any(getattr(args, name, False) for name in ("team", "session", "personal")) else None
    rules = [rule for rule in profile.rules if wanted is None or rule.level == wanted]
    if not rules:
        print(f'No rules yet. `{cli.NAME} prefer add "<rule>"` adds one.')
    for rule in rules:
        where = ", ".join(part for part in (rule.level, rule.origin, rule.added) if part)
        print(f"{rule.ref}: {rule.text} ({where})")
    return 0


def prefer_remove(args) -> int:
    """`colony prefer remove <ref>`: drop a rule by its ref, such as p3, t1 or s2."""
    found = re.fullmatch(r"([pts])(\d+)", args.ref.strip().lower())
    if not found:
        raise cli.ColonyError(f"{args.ref!r} is not a rule's ref, such as p3: `{cli.NAME} prefer list` shows them")
    level = {"p": "personal", "t": "team", "s": "session"}[found[1]]
    args.team, args.session = level == "team", level == "session"
    number = int(found[2])

    def edit(data: dict, level: str) -> str:
        rules = data.get("rules", [])
        held = layer_from(data, level, level).rules
        match = next((rule for rule in held if rule.id == number), None)
        if match is None:
            raise cli.ColonyError(f"there is no rule {args.ref} in the {level} profile")
        kept = [item for item in rules if not (isinstance(item, dict) and " ".join(str(item.get("text", "")).split())
                                               == match.text)]
        data["rules"] = kept
        if not kept:
            del data["rules"]
        return match.text

    path, level, text = change(args, edit)
    print(f"Rule {args.ref} removed ({text}): {written(path, level)}")
    return 0


def register(sub) -> None:
    """cli.py's route to this module: `colony profile …` and `colony prefer …`."""
    def person(p) -> None:
        p.add_argument("--person", help="whose profile, when $COLONY_PERSON is not set")

    def levels(p, personal: bool = False) -> None:
        group = p.add_mutually_exclusive_group()
        group.add_argument("--team", action="store_true", help=f"the team profile, {TEAM_PATH}, which changes "
                                                               "through a reviewed pull request")
        group.add_argument("--session", action="store_true", help="this session alone")
        if personal:
            group.add_argument("--personal", action="store_true", help="your personal profile")

    p = sub.add_parser("profile", help="standing orders: show what is in force and where each came from, set them up "
                                       "once, change, resolve or import them")
    person(p)
    p.set_defaults(run=show_cmd)
    actions = p.add_subparsers(dest="action", metavar="action")
    a = actions.add_parser("show", help="the active orders and where each came from")
    a.add_argument("--orders", action="store_true", help="print the standing-order text a session starts with")
    a.add_argument("--role", choices=("lead", "helper"), help="whose orders --orders prints; by $COLONY_SESSION")
    a.add_argument("--team-only", action="store_true", help="the team's orders alone, for work between people")
    a.add_argument("--json", action="store_true", help="print one JSON object")
    person(a)
    a.set_defaults(run=show_cmd)
    a = actions.add_parser("keys", help="every key a profile may hold")
    a.set_defaults(run=keys_cmd)
    a = actions.add_parser("setup", help="the one-time questions that write your personal profile")
    a.add_argument("--set", action="append", metavar="KEY=VALUE", help="an answer, such as "
                                                                        "decisions.autonomy=routine; repeat it")
    a.add_argument("--defaults", action="store_true", help="take every default")
    a.add_argument("--again", action="store_true", help="ask again, though setup ran already")
    person(a)
    a.set_defaults(run=setup_cmd)
    a = actions.add_parser("set", help="set one key")
    a.add_argument("key", help="the key, such as decisions.autonomy")
    a.add_argument("value", help="its value; a list is comma-separated")
    levels(a)
    person(a)
    a.set_defaults(run=set_cmd)
    a = actions.add_parser("unset", help="remove one key")
    a.add_argument("key", help="the key, such as decisions.autonomy")
    levels(a)
    person(a)
    a.set_defaults(run=unset_cmd)
    a = actions.add_parser("resolve", help="record which applies where the team's and your profile disagree")
    a.add_argument("key", help="the key, such as decisions.answer_wait_minutes")
    a.add_argument("choice", choices=("team", "mine"), help="the team's value or your own")
    person(a)
    a.set_defaults(run=resolve_cmd)
    a = actions.add_parser("import", help="offer preferences from your agent tool's memory and instruction files, "
                                          "each added only after your yes")
    a.add_argument("--from", dest="from_file", action="append", metavar="FILE", help="read this file too")
    a.add_argument("--accept", action="append", metavar="ID,ID", help="the candidates the person said yes to")
    a.add_argument("--decline", action="append", metavar="ID,ID", help="the ones they said no to")
    person(a)
    a.set_defaults(run=import_cmd)
    a = actions.add_parser("init", help=f"write {TEAM_PATH} with every team key commented out")
    a.set_defaults(run=init_cmd)

    p = sub.add_parser("prefer", help="add, list or remove standing-order rules")
    rules = p.add_subparsers(dest="action", metavar="action", required=True)
    a = rules.add_parser("add", help="keep a rule as a standing order")
    a.add_argument("rule", nargs="+", help="the rule, in one sentence")
    a.add_argument("--correction", action="store_true", help="it came from the person's correction")
    levels(a)
    person(a)
    a.set_defaults(run=prefer_add)
    a = rules.add_parser("list", help="every rule in force, with its ref")
    levels(a, personal=True)
    person(a)
    a.set_defaults(run=prefer_list)
    a = rules.add_parser("remove", help="drop a rule by its ref, such as p3")
    a.add_argument("ref", help="the rule's ref from `colony prefer list`, such as p3, t1 or s2")
    person(a)
    a.set_defaults(run=prefer_remove)
