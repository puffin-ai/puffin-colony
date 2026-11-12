"""Puffin Colony's command line: one command for a repo's whole software life cycle.

`colony` alone runs setup the first time (the repo has no .colony/colony.toml) and opens the lead every time after.
Inside a Claude Code session ($CLAUDECODE), plain `colony` makes that session the lead instead of opening one (here):
a session a person types into is a lead, and never asks what it is.
`colony join <name>` opens a builder on another computer. The lead and the builders use `open`, `wait`, `batch`
and `status`, and the lead opens a researcher or the spec agent with `research` and `spec`. In hack mode,
`colony merge <branch>` lands a branch after the fast check (merge.py). The cycle's commands (cycle.py, board.py),
the knowledge checks (vault.py) and the guards (guards.py) add their own. The repo's `[project] mode`, hack, solo or
startup, picks the defaults in modes/<mode>.toml that colony.toml overrides. Every command finds the repo with
`git rev-parse --show-toplevel`. Python 3.11+ standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from colony import __version__, portable

NAME = "colony"
DISPLAY = "Puffin Colony"
DIR = f".{NAME}"  # the folder a host repo keeps Colony's files in: the config, rules, playbook and reports
CONFIG_NAME = f"{NAME}.toml"
SESSION_ENV, PERSON_ENV = f"{NAME.upper()}_SESSION", f"{NAME.upper()}_PERSON"
LEAD = "lead"
LEAD_PROMPT = "Run `colony` and do what it prints, then read {dir}/playbook.md, {section} section, and start."
BUILDER_PROMPT = "Read {dir}/playbook.md, {section} section. You are {builder}. Start the wait."
RENAME = ("Rename this session in the app's sidebar to {name}, with the app's own rename tool when you have one; "
          "when you have none, skip this quietly.")
SESSION_NAME = re.compile(r"[a-z0-9][a-z0-9.-]*")
RESEARCHER, SPEC, TESTER = "researcher", "spec", "tester"  # the sessions `colony research`, `spec` and `tester` open
ROLES = ("lead", "builder", "reviewer", "walker", "fixer")
# Roles a colony.toml may leave out: each one missing takes the builder's settings.
BUILDER_LIKE = (RESEARCHER, SPEC, TESTER)
FULL = 90.0  # an account at or past this percent of a window has no room, for has_room
FIVE_HOUR_OUT = 95.0  # at or past this 5-hour use, an account is out of room
FIVE_HOUR_NEAR = 80.0  # at or past this 5-hour use with its reset over FAR_RESET away, it is skipped too
FAR_RESET_HOURS = 1.0
WEEK_OUT = 95.0  # at or past this weekly use, no weekly room is left
REQUIRED = {
    "project": ("name", "repo", "base", "worktrees", "checks"),
    "gate": ("rubric", "max_rounds", "walk"),
    "budget": ("provider_dollars",),
}
MODES = ("hack", "solo", "startup")
DEFAULT_MODE = "startup"  # the mode of a colony.toml that names none: Colony as it ran before modes
# The commands a mode can turn off, each with its [features] key: a false key refuses the command.
FEATURES = {"check-docs": "knowledge", "spec": "specs", "research": "research", "board": "board", "retro": "retro"}


class ColonyError(Exception):
    """A problem the command reports in one line, such as a missing colony.toml key."""


def package_file(*parts: str) -> str:
    """The text of one file the package ships, such as prompts/setup.md."""
    return resources.files(__package__).joinpath(*parts).read_text()


def fill_names(text: str) -> str:
    """Put Colony's names into a prompt: `{name}`, `{display}`, `{dir}` and `{package}` (the installed package's folder)."""
    names = {"name": NAME, "display": DISPLAY, "dir": DIR, "package": str(resources.files(__package__))}
    return re.sub(r"\{(name|display|dir|package)\}", lambda m: names[m[1]], text)


def _out(cmd: list[str]) -> str:
    """A read-only command's output, stripped, or an empty string when it fails or is missing."""
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return run.stdout.strip() if run.returncode == 0 else ""


def repo_root() -> Path:
    """The top of the git checkout this command runs in."""
    top = _out(["git", "rev-parse", "--show-toplevel"])
    if not top:
        raise ColonyError(f"run {NAME} inside a clone of your repo: this folder is not in a git checkout")
    return Path(top)


def config_path() -> Path:
    """Where this repo keeps its colony.toml."""
    return repo_root() / DIR / CONFIG_NAME


def mode(config: dict) -> str:
    """The config's `[project] mode`: hack, solo or startup, which a config that names none runs."""
    return config.get("project", {}).get("mode") or DEFAULT_MODE


def merge_tables(defaults: dict, own: dict) -> dict:
    """`own` laid over `defaults`: a table in both merges key by key, and any other value in `own` wins whole."""
    merged = dict(defaults)
    for key, value in own.items():
        both = isinstance(value, dict) and isinstance(merged.get(key), dict)
        merged[key] = merge_tables(merged[key], value) if both else value
    return merged


def load_config(path=None) -> dict:
    """Read the repo's .colony/colony.toml (or `path`) over its mode's defaults (modes/<mode>.toml), expand `~` in
    its paths, and check its keys."""
    path = Path(path) if path else config_path()
    try:
        with open(path, "rb") as f:
            own = tomllib.load(f)
    except FileNotFoundError:
        raise ColonyError(f"{path} is missing: pull the branch that has it, or run `{NAME}` to set this repo up") from None
    except tomllib.TOMLDecodeError as e:
        raise ColonyError(f"{path}: {e}") from None
    name = mode(own)
    if name not in MODES:
        raise ColonyError(f'{path}: [project] mode is "hack", "solo" or "startup", not {name!r}')
    config = merge_tables(tomllib.loads(package_file("modes", f"{name}.toml")), own)
    config.setdefault("project", {})["mode"] = name
    for table, keys in REQUIRED.items():
        for key in keys:
            if key not in config.get(table, {}):
                raise ColonyError(f"{path}: [{table}] needs {key!r}")
    roles = config.setdefault("roles", {})
    for role in ROLES + tuple(role for role in BUILDER_LIKE if role in roles):
        for key in ("model", "effort"):
            if key not in roles.get(role, {}):
                raise ColonyError(f"{path}: [roles] {role} needs {key!r}")
    for role in BUILDER_LIKE:
        roles.setdefault(role, dict(roles["builder"]))
    if not config.get("accounts"):
        raise ColonyError(f"{path}: needs at least one [accounts.<name>] table")
    for name, account in config["accounts"].items():
        for key in ("config_dir", "person"):
            if key not in account:
                raise ColonyError(f"{path}: [accounts.{name}] needs {key!r}")
        account["config_dir"] = portable.native(os.path.expanduser(account["config_dir"]))
    project = config["project"]
    for person, table in config.get("people", {}).items():
        if isinstance(table, dict):
            for name in [*table.get("accounts", []), *table.get("last_resort", [])]:
                if name not in config["accounts"]:
                    raise ColonyError(f"{path}: [people.{person}] names the account {name!r}, which no "
                                      "[accounts.<name>] table holds")
            if not isinstance(table.get("quiet_lead", False), bool):
                raise ColonyError(f"{path}: [people.{person}] quiet_lead is true or false")
    for key in ("worktrees", "check_env_file"):
        if project.get(key):
            project[key] = portable.native(os.path.expanduser(project[key]))
    if project.get("worktrees") and not os.path.isabs(project["worktrees"]):  # such as "../worktrees", from the clone
        project["worktrees"] = portable.native(os.path.normpath(path.resolve().parent.parent / project["worktrees"]))
    return config


def is_default_dir(config_dir: str) -> bool:
    """Whether a settings folder is Claude Code's default one, `~/.claude`."""
    return Path(config_dir).expanduser().resolve() == (Path.home() / ".claude").resolve()


def usage_file(config_dir: str) -> Path:
    """The state file Claude Code keeps for an account: `.claude.json` in the folder, or `~/.claude.json` for the default."""
    return Path.home() / ".claude.json" if is_default_dir(config_dir) else Path(config_dir) / ".claude.json"


def _state(config_dir: str) -> dict:
    """The account's Claude Code state file as a dict, or an empty one when it is missing or unreadable."""
    try:
        data = json.loads(usage_file(config_dir).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def signed_in(config_dir: str) -> bool:
    """Whether the account's state file records a claude login."""
    return bool(_state(config_dir).get("oauthAccount"))


WINDOWS = {"five_hour": "5h", "seven_day": "week"}  # the usage windows Claude Code saves, and their short names
USAGE_STALE = 600  # seconds: a saved reading older than this is fetched again (refresh_usage)
USAGE_TIMEOUT = 60  # seconds every fetch of one refresh_usage gets, together
NO_REFRESH_ENV = "COLONY_NO_USAGE_REFRESH"  # set, refresh_usage fetches nothing
_fetched: dict[str, float] = {}  # each folder's last fetch in this process, so a plan that saves no windows is not
# fetched on every call


def reading_age(config_dir: str, now: float | None = None) -> float | None:
    """Seconds since Claude Code saved the account's usage reading, or None when it saved none."""
    try:
        fetched = float(_state(config_dir)["cachedUsageUtilization"]["fetchedAtMs"]) / 1000
    except (KeyError, TypeError, ValueError):
        return None
    return (time.time() if now is None else now) - fetched


def refresh_usage(folders: list[str]) -> None:
    """Fetch a live usage reading for each signed-in account folder whose saved one is missing or older than
    USAGE_STALE, so usage reads today's numbers and not the copy from the account's last session.

    Runs `claude -p /usage` with each folder as its settings folder, side by side, in the temp folder so no project
    hooks run. /usage makes no model call: Claude Code fetches the windows and saves them in the folder's state
    file. A fetch that fails or passes USAGE_TIMEOUT leaves the saved reading as it was. NO_REFRESH_ENV turns it off.
    """
    if os.environ.get(NO_REFRESH_ENV) or not shutil.which("claude"):
        return
    now = time.time()
    running = []
    for folder in dict.fromkeys(str(Path(f).expanduser()) for f in folders):
        if not Path(folder).is_dir() or not signed_in(folder) or now - _fetched.get(folder, 0.0) < USAGE_STALE:
            continue
        age = reading_age(folder, now)
        if age is not None and age < USAGE_STALE:
            continue
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)
        if is_default_dir(folder):
            env.pop("CLAUDE_CONFIG_DIR", None)
        else:
            env["CLAUDE_CONFIG_DIR"] = folder
        _fetched[folder] = now
        try:
            running.append(subprocess.Popen(["claude", "-p", "/usage"], env=env, cwd=tempfile.gettempdir(),
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL))
        except OSError:
            continue
    deadline = time.monotonic() + USAGE_TIMEOUT
    for process in running:
        try:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()


def usage(config_dir: str, now: datetime | None = None) -> dict[str, tuple[float, datetime | None]]:
    """The account's saved usage per window, `five_hour` and `seven_day`, as (percent used, reset time), with a
    window whose reset time has passed counted as 0. A window with no saved reading is left out.

    Claude Code saves them as `cachedUsageUtilization.utilization.<window>`, each holding `utilization` (percent
    used) and `resets_at` (an ISO time).
    """
    now = now or datetime.now(timezone.utc)
    try:
        saved = _state(config_dir)["cachedUsageUtilization"]["utilization"]
    except (KeyError, TypeError):
        return {}
    found = {}
    for window in WINDOWS:
        try:
            used = float(saved[window]["utilization"])
            resets = datetime.fromisoformat(saved[window]["resets_at"]) if saved[window].get("resets_at") else None
        except (KeyError, TypeError, ValueError):
            continue
        found[window] = (0.0, None) if resets is not None and resets <= now else (used, resets)
    return found


def five_hour_usage(config_dir: str) -> float | None:
    """The account's saved 5-hour usage in percent, 0 once that window has reset, or None when none is saved."""
    window = usage(config_dir).get("five_hour")
    return None if window is None else window[0]


def fullest(config_dir: str) -> float | None:
    """The account's binding usage: its fuller window's percent, or None when it has no reading."""
    windows = usage(config_dir)
    return max(used for used, _ in windows.values()) if windows else None


def has_room(config_dir: str) -> bool:
    """Whether an account's folder is on this computer and every saved window, if any, is under FULL percent."""
    used = fullest(config_dir)
    return Path(config_dir).is_dir() and (used is None or used < FULL)


def room_text(name: str, config_dir: str) -> str:
    """One account's room for a status, such as `admin: 5h 40% (resets 23:50 UTC), week 63% (resets Sat 10:00 UTC)`,
    or `admin: no reading`."""
    windows = usage(config_dir)
    if not windows:
        return f"{name}: no reading"
    parts = []
    for window, short in WINDOWS.items():
        if window in windows:
            used, resets = windows[window]
            when = f" (resets {resets.astimezone(timezone.utc):%a %H:%M} UTC)" if resets else ""
            parts.append(f"{short} {used:g}%{when}")
    return f"{name}: {', '.join(parts)}"


def person_accounts(config: dict, person: str) -> tuple[list[str], list[str]]:
    """The person's accounts in their order, and their last-resort accounts: `[people.<person>] accounts` and
    `last_resort`, else every account whose person is theirs or `any`, in the file's order."""
    table = config.get("people", {}).get(person)
    if isinstance(table, dict) and table.get("accounts"):
        return list(table["accounts"]), list(table.get("last_resort", []))
    return [name for name, a in config["accounts"].items() if a["person"] in (person, "any")], []


def quiet_lead(config: dict, person: str) -> bool:
    """Whether the person wants a quiet lead, `[people.<person>] quiet_lead = true`; false by default."""
    table = config.get("people", {}).get(person)
    return isinstance(table, dict) and table.get("quiet_lead", False)


def in_hours(when: datetime | None, now: datetime) -> str:
    """How far off a reset is, such as `20 h` or `35 min`."""
    if when is None:
        return "an unknown time"
    seconds = max(0.0, (when - now).total_seconds())
    return f"{int(seconds // 3600)} h" if seconds >= 3600 else f"{int(seconds // 60)} min"


def judge(name: str, folder: str, now: datetime) -> tuple[int, tuple, str]:
    """One account's standing for the pick, as (tier, rank, why): tier 0 has room, 1 has no saved reading, 2 is out
    of room or near it with a reset far off, 3 has no folder on this computer. Within tier 0 the rank puts the
    soonest weekly reset first, "use it or lose it", counting resets in the same hour as a tie, then the most 5-hour
    room."""
    far = datetime.max.replace(tzinfo=timezone.utc)
    if not Path(folder).expanduser().is_dir():
        return 3, (), f"{name}: its folder is not on this computer"
    windows = usage(folder, now)
    if not windows:
        return 1, (), f"{name}: no saved reading, so its room is unknown"
    five_used, five_reset = windows.get("five_hour", (0.0, None))
    week_used, week_reset = windows.get("seven_day", (0.0, None))
    five = f"5h {five_used:g}% used, resets in {in_hours(five_reset, now)}"
    if five_used >= FIVE_HOUR_OUT:
        return 2, (), f"{name}: out of 5-hour room ({five})"
    if five_used >= FIVE_HOUR_NEAR and five_reset and (five_reset - now).total_seconds() > FAR_RESET_HOURS * 3600:
        return 2, (), f"{name}: near its 5-hour limit with the reset far off ({five})"
    if week_used >= WEEK_OUT:
        return 2, (), f"{name}: no weekly room left (weekly {week_used:g}% used, resets in {in_hours(week_reset, now)})"
    why = f"{name}: weekly resets in {in_hours(week_reset, now)}, {100 - week_used:g}% left; {five}"
    hour = int((week_reset or far).timestamp() // 3600)  # resets within the same hour tie
    return 0, (hour, five_used), why


def pick(config: dict, person: str, now: datetime | None = None) -> tuple[str, str, str]:
    """The person's account for a new session, as (name, config_dir, why).

    The person's accounts, in their order (person_accounts), are judged on this computer (judge). An account with
    room wins, the soonest weekly reset first, then the most 5-hour room, then the person's order. Next comes an
    account with no reading, in order. A last-resort account counts only when none of those has room. When every
    account is out of room, the first in order is named, and why says so. Stale readings are fetched first
    (refresh_usage).
    """
    now = now or datetime.now(timezone.utc)
    order, last = person_accounts(config, person)
    if not order and not last:
        raise ColonyError(f"{CONFIG_NAME} has no account for {person!r}")
    found = pick_with_room(config, person, now)
    if found:
        return found
    name = (order or last)[0]
    whys = "; ".join(judge(n, config["accounts"][n]["config_dir"], now)[2] for n in order + last)
    return name, config["accounts"][name]["config_dir"], f"every account is out of room, so {name}, the first: {whys}"


def pick_with_room(config: dict, person: str, now: datetime | None = None, skip=()) -> tuple[str, str, str] | None:
    """The person's best account with room or no reading, leaving out the names in `skip`, as (name, config_dir, why),
    or None when none of the rest has room. pick ranks them; a batch whose account hits its rate limit asks here for
    the next one."""
    now = now or datetime.now(timezone.utc)
    order, last = (([name for name in names if name not in skip]) for names in person_accounts(config, person))
    refresh_usage([config["accounts"][name]["config_dir"] for name in order + last])
    for names in (order, last):
        judged = [(judge(name, config["accounts"][name]["config_dir"], now), i, name) for i, name in enumerate(names)]
        for tier in (0, 1):
            ranked = sorted((rank, i, name, why) for (t, rank, why), i, name in judged if t == tier)
            if ranked:
                _, _, name, why = ranked[0]
                return name, config["accounts"][name]["config_dir"], why + (" (last resort)" if names is last else "")
    return None


def pick_account(config: dict, person: str) -> tuple[str, str]:
    """The person's account for a new session, as (name, config_dir) (pick)."""
    name, folder, _ = pick(config, person)
    return name, folder


def choose_account(config: dict, args) -> tuple[str, str]:
    """The account a session or batch runs on, as (name, config_dir): --account when given, else the pick for the
    session's person (pick)."""
    return choose_account_why(config, args)[:2]


def choose_account_why(config: dict, args) -> tuple[str, str, str]:
    """choose_account with why it was chosen, which a session prints as it opens."""
    name = getattr(args, "account", None)
    if name:
        if name not in config["accounts"]:
            raise ColonyError(f"--account {name!r} is not in {CONFIG_NAME}: choose from {', '.join(config['accounts'])}")
        return name, config["accounts"][name]["config_dir"], f"{name}: named with --account"
    return pick(config, person_of(config, args))


def git_user() -> set[str]:
    """The git user's first name and email name in this checkout, lowercased, to tell whose computer this is."""
    found = set()
    for key in ("user.name", "user.email"):
        value = _out(["git", "config", key]).lower().split("@")[0].split()
        if value:
            found.add(value[0])
    return found


def gh_login() -> str:
    """The signed-in gh user's login, lowercased, or an empty string when gh can't say."""
    return _out(["gh", "api", "user", "--jq", ".login"]).lower()


def default_person(config: dict) -> str:
    """The one person colony.toml names, else the one the git user matches, else the one the gh login maps to through
    `[people.<person>] login`, else an error asking for --person."""
    people = sorted({a["person"] for a in config["accounts"].values()} - {"any"})
    if len(people) == 1:
        return people[0]
    matches = [p for p in people if p.lower() in git_user()]
    if len(matches) == 1:
        return matches[0]
    login = gh_login()
    tables = {person: table for person, table in config.get("people", {}).items() if isinstance(table, dict)}
    mapped = [p for p in people if login and login in (str(tables.get(p, {}).get("login", "")).lower(), p.lower())]
    if len(mapped) == 1:
        return mapped[0]
    raise ColonyError(f"say whose session this is: --person {' or '.join(people)}")


def person_of(config: dict, args) -> str:
    """Whose session this is: --person, else $COLONY_PERSON, else default_person."""
    return getattr(args, "person", None) or os.environ.get(PERSON_ENV) or default_person(config)


def session_env(person: str, session: str, config_dir: str, lead: str = "") -> dict[str, str]:
    """The environment variables a lead or builder starts with, with $COLONY_LEAD for a helper of a named lead.

    Claude Code ties a login to the CLAUDE_CONFIG_DIR value, so the default folder leaves it
    unset; naming `~/.claude` there would open a session that is not signed in.
    """
    from colony.wait import LEAD_ENV

    env = {SESSION_ENV: session, PERSON_ENV: person, **({LEAD_ENV: lead} if lead else {})}
    if not is_default_dir(config_dir):
        env["CLAUDE_CONFIG_DIR"] = config_dir
    env["CLAUDE_CODE_RETRY_WATCHDOG"] = "1"
    env["CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS"] = "21600000"
    env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "250000"
    return env


# Routine commands a session runs all day, allowed so the permission mode never stops a session to ask about them,
# and the pushes no session makes, denied. A deny rule wins over an allow rule.
ROUTINE = ("Bash(git:*)", "Bash(gh:*)", "Bash(colony:*)", "Bash(tools/board:*)")
NEVER = ("Bash(git push --force:*)", "Bash(git push -f:*)", "Bash(git push --force-with-lease:*)")


def session_settings(config: dict, env: dict[str, str], masked: bool = False) -> str:
    """The --settings JSON every session opens with: its env, and the permissions for routine commands.

    The env goes in the settings too, because `claude --bg` hands a new session to a spare process of a daemon an
    earlier session started, which carries that session's environment: without this, a researcher, spec or builder
    opened in the background ran as the lead (COLONY_SESSION=lead), and its hooks and lines spoke for the lead.
    CLAUDE_CONFIG_DIR stays out: it picks the account, so it must be in the process's own environment. `masked`
    shows the env's names alone, for a dry run."""
    base = config["project"]["base"]
    worktrees = Path(config["project"].get("worktrees", "")).expanduser() if config["project"].get("worktrees") else None
    folders = [str(worktrees)] if worktrees else []
    folders.append(str(repo_root().parent))  # the lead's ../next-<batch> worktree sits beside the clone
    settings = {
        "env": {key: "…" if masked else value for key, value in env.items() if key != "CLAUDE_CONFIG_DIR"},
        "permissions": {"allow": list(ROUTINE),
                        "deny": [*NEVER, f"Bash(git push origin {base}:*)", f"Bash(git push origin HEAD:{base}:*)"],
                        "additionalDirectories": folders},
    }
    return json.dumps(settings, ensure_ascii=False)


def claude_argv(config: dict, role: str, title: str, config_dir: str, prompt: str, settings: str = "") -> list[str]:
    """A session's command line: Remote Control under its title, the role's model and effort, its settings
    (session_settings), and the first prompt."""
    role_settings = config["roles"][role]
    argv = ["claude", "--remote-control", title, "--model", role_settings["model"], "--effort", role_settings["effort"],
            *(["--settings", settings] if settings else []),
            "--permission-mode", role_settings.get("permission_mode", "auto"), prompt]
    # The default folder also drops a CLAUDE_CONFIG_DIR inherited from the caller's shell.
    if portable.WINDOWS:  # no `env` there: launch's portable.process_env drops it
        return argv
    return ["env", "-u", "CLAUDE_CONFIG_DIR", *argv] if is_default_dir(config_dir) else argv


# Where the cmux app keeps its command when the app's installer left it off PATH, as on some Macs.
CMUX_APP = Path("/Applications/cmux.app/Contents/Resources/bin/cmux")


def cmux_command() -> str | None:
    """The cmux command: the one on PATH, else the one inside the cmux app, else None."""
    if shutil.which("cmux") is not None:
        return "cmux"
    return str(CMUX_APP) if os.access(CMUX_APP, os.X_OK) else None


def cmux_usable() -> bool:
    """Whether cmux is found and takes commands from this process, which it does only inside cmux."""
    cmux = cmux_command()
    if cmux is None:
        return False
    try:
        return subprocess.run([cmux, "workspace", "list"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def where_to_open(args) -> str:
    """cmux when it takes us, this terminal for --here or a person at a terminal, else a background session."""
    if getattr(args, "here", False):
        return "terminal"
    if cmux_usable():
        return "cmux"
    return "terminal" if portable.is_terminal(sys.stdin) else "background"


def launch(config: dict, args, session: str, role: str, prompt: str) -> int:
    """Open one session on --account, else the person's account (pick_account): in cmux, in this terminal, or in the
    background.

    A background session runs under Remote Control, so the person follows it in the Claude app, or with
    `claude attach`. A dry run prints the command, the env names (never their values) and where it would
    open, and runs nothing. A lead's session claims its own name by running `colony` inside itself, or `colony claim`. Every other
    session is a helper of one lead: the lead `colony join` picked, else the lead that runs the command ($COLONY_LEAD).
    """
    from colony.wait import LEAD_ENV

    if session != LEAD:  # a lead learns its name when it claims it, and renames itself then
        prompt = f"{prompt} {rename_line(session)}"
    person = person_of(config, args)
    account, config_dir, why = choose_account_why(config, args)
    title = f"{config['project']['name']}-{session}"
    lead = "" if session == LEAD else (getattr(args, "lead_name", "") or os.environ.get(LEAD_ENV, ""))
    env = session_env(person, session, config_dir, lead)
    argv = claude_argv(config, role, title, config_dir, prompt, session_settings(config, env, masked=args.dry_run))
    root = str(repo_root())
    mode = where_to_open(args)
    where = {"cmux": f"a new cmux workspace at {root}", "terminal": f"this terminal at {root}",
             "background": f"a background session at {root}; follow it in the Claude app or with `claude attach`"}[mode]
    if args.dry_run:
        print("command:", shlex.join(argv))
        print("env:", " ".join(env))
        print(f"dry run: {title} on account {account}, in {where}")
        print(f"why: {why}")
        return 0
    if shutil.which("claude") is None:
        raise ColonyError("claude is not on PATH")
    print(f"Opening {title} on account {account}, in {where}. Why: {why}.", flush=True)
    # A set ANTHROPIC_API_KEY makes Claude Code bill that key instead of the account's
    # subscription, so a session drops it unless colony.toml says to use it.
    keep_key = config.get("budget", {}).get("use_api_key", False)
    inherited = {k: v for k, v in os.environ.items() if keep_key or k != "ANTHROPIC_API_KEY"}
    if mode == "cmux":
        command = argv if keep_key else ["env", "-u", "ANTHROPIC_API_KEY", *argv]
        cmd = [cmux_command() or "cmux", "new-workspace", "--name", title, "--cwd", root, "--command", shlex.join(command)]
        cmd += [part for key, value in env.items() for part in ("--env", f"{key}={value}")]
        return subprocess.run(cmd).returncode
    if mode == "background":
        at = argv.index("claude") + 1
        background = [*argv[:at], "--bg", "--name", title, *argv[at:]]
        background[0] = portable.program(background[0])
        return subprocess.run(background, cwd=root,
                              env=portable.process_env(inherited, env, is_default_dir(config_dir))).returncode
    os.chdir(root)
    return portable.hand_over(argv, portable.process_env(inherited, env, is_default_dir(config_dir)))


# The placeholders the puffin preset's files hold, which the setup session fills with this repo's values:
# the web app's folder, the Python service's folder, and the fast and full checks.
PRESET_PLACEHOLDERS = ("web_app", "service", "fast_check", "checks")

# The MCP servers setup can add to the repo's .mcp.json, under these names.
MCP_SERVERS = {
    "playwright": {"command": "npx", "args": ["-y", "@playwright/mcp@latest"]},
    "context7": {"type": "http", "url": "https://mcp.context7.com/mcp"},
}
ROLE_SKILLS = ("colony-lead", "colony-builder", "colony-reviewer", "colony-walker")  # shipped in skills/
SETUP_SKILL = "colony-setup"  # the skill `colony skill-install` copies into a settings folder, for repos not set up yet
# Outside skills, each pinned to a commit: (repo, commit, folder in that repo, the skill's folder name here).
OUTSIDE_SKILLS = {
    "ui-design": ("anthropics/skills", "ca45fc496a3436251f191354091d557da31c15b5", "skills/frontend-design",
                  "frontend-design"),
    "test-first": ("obra/superpowers", "22f0b463e7a5e579904dd6211a520321035526f7", "skills/test-driven-development",
                   "test-driven-development"),
}
# The tools `colony tools` writes, in the order setup's one yes-or-no list shows them (see offered).
TOOLS = ("playwright", "context7", "role-skills", "starter-skills", "ui-design", "test-first")


def offered() -> dict[str, tuple[str, str]]:
    """Each tool with its default (yes, no, or ask for no default) and what it is."""
    from colony import guards

    return {
        "playwright": ("yes", "Playwright MCP, the walker's browser. It installs a package: npx downloads "
                              "@playwright/mcp on first use."),
        "context7": ("yes", "Context7 MCP, current docs for every library. A hosted server: nothing is installed."),
        "role-skills": ("yes", f"{DISPLAY}'s role skills, {', '.join(ROLE_SKILLS)}: the playbook split per role, "
                               "copied from the package."),
        "starter-skills": ("yes", f"{DISPLAY}'s starter skills, {', '.join(guards.STARTER_SKILLS)}, copied from the "
                                  "package. A skill the repo already has is kept."),
        "ui-design": ("ask", "A UI design skill, Anthropic's frontend-design. Its files download from "
                             "github.com/anthropics/skills."),
        "test-first": ("no", "A test-first skill, superpowers' test-driven-development. Its files download from "
                             "github.com/obra/superpowers."),
    }


def setup(args) -> int:
    """First run: an interactive claude session in this terminal whose first message is the setup prompt. With
    --print, the prompt alone, for a session already open to follow (the colony-setup skill)."""
    root = repo_root()
    prompt = fill_names(package_file("prompts", "setup.md"))
    if getattr(args, "print", False):
        print(prompt)
        return 0
    if args.dry_run:
        print(f"setup plan: {DIR}/{CONFIG_NAME} is missing, so {NAME} sets up {root} in this terminal.")
        print(f"  command: claude <the setup prompt from {NAME} {__version__}, {len(prompt)} characters>")
        print("  it reads the repo, asks at most 5 questions and one yes-or-no list of tools, and writes:")
        print(f"    {DIR}/{CONFIG_NAME}, {DIR}/rules/, {DIR}/playbook.md, {DIR}/core.md and {DIR}/prompts/, "
              "and an AGENTS.md per app")
        print("    the knowledge vault, and for the items accepted: .mcp.json, .claude/skills/, the hooks in "
              ".claude/settings.json,")
        print("    the board, and two lines in CLAUDE.md that load the core and point to the playbook")
        print("  then opens one pull request with them. Nothing ran.")
        return 0
    if shutil.which("claude") is None:
        raise ColonyError(f"claude is not on PATH: install Claude Code, then run {NAME} again")
    print(f"No {DIR}/{CONFIG_NAME} yet, so {DISPLAY} starts setup.", flush=True)
    os.chdir(root)
    return portable.hand_over(["claude", prompt])


def ago(seconds: float) -> str:
    """A time span in the largest whole unit, such as `40 s`, `12 min` or `3 h`."""
    if seconds < 60:
        return f"{int(seconds)} s"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    return f"{int(seconds // 3600)} h"


def current_account(config: dict) -> str:
    """The account this process runs on: the one whose folder is $CLAUDE_CONFIG_DIR, or the default folder's when it
    is unset, else the folder's own name."""
    folder = os.environ.get("CLAUDE_CONFIG_DIR", "")
    for name, account in config.get("accounts", {}).items():
        if (is_default_dir(account["config_dir"]) and not folder) or (
                folder and Path(account["config_dir"]).expanduser() == Path(folder).expanduser()):
            return name
    return Path(folder).name if folder else "default"


def lead_line(config: dict) -> str:
    """This computer's leads, one line each with name, account and heartbeat age, or that none is running."""
    from colony import wait

    folder = wait.state_path(config["project"]["name"], LEAD).parent
    lines = []
    for path in sorted(folder.glob("*.heartbeat")) if folder.is_dir() else []:
        held = wait.read_json(path, None)
        if not isinstance(held, dict) or not isinstance(held.get("at"), (int, float)):
            continue
        age, name = ago(time.time() - held["at"]), held.get("session", path.stem)
        lines.append(f"lead: {name} on account {held.get('account', 'unknown')}, heartbeat {age} ago" if wait.fresh(held)
                     else f"lead: none running as {name} on this computer (its heartbeat is {age} old)")
    return "\n".join(lines) or "lead: none running on this computer (no heartbeat)"


def env_line(*pairs: tuple[str, str]) -> str:
    """The env a session puts before every colony command, such as `COLONY_SESSION=lead COLONY_LEAD=…`."""
    return " ".join(f"{key}={value}" for key, value in pairs if value)


def claim_lead(config: dict, args, stream: str, folders: list[str]) -> tuple[str, str]:
    """Claim the lead `<person>-<stream>-lead` for this session: refuse a folder another live lead holds, and a name a
    live session already leads; write its heartbeat, its folders in .colony/leads.toml and its status comment.
    Returns (the lead's name, its token). A dry run checks the same refusals, writes nothing, and returns no token."""
    from colony import presence, wait

    person = person_of(config, args)
    name = presence.lead_of("", person, stream)
    folders = [presence.folder(f) for f in folders]
    alive, _, note = presence.everyone(config)
    if note:
        print(note, file=sys.stderr)
    clash = [f"{mine} overlaps {held} of {lead}" for lead, theirs in presence.held_by_others(alive, name).items()
             for mine in folders for held in theirs if presence.overlaps(mine, held)]
    if clash:
        raise ColonyError(f"another live lead holds those folders: {'; '.join(clash)}. Pick other folders")
    if any(status.name == name for status in alive if status.kind == "lead" and status.computer != presence.computer()):
        raise ColonyError(f"{name} is alive on another computer: pick another stream name")
    if getattr(args, "dry_run", False):
        return name, ""
    token, account = wait.new_token(), current_account(config)
    try:
        wait.beat(config["project"]["name"], name, account, token, named=True)
    except wait.LeadTaken as e:
        raise ColonyError(f"{e}: pick another stream name") from None
    leads = presence.registry()
    leads[name] = {"person": person, "folders": folders}
    presence.write_registry(leads)
    state_path = wait.state_path(config["project"]["name"], f"{name}-status")
    state: dict = {}
    try:
        presence.keep(config, presence.mine(config, args, name, "lead"), state)
        wait.write_json(state_path, state)
    except (ColonyError, OSError, ValueError, KeyError) as e:
        print(f"{NAME}: the status comment waits for the first `{NAME} wait`: {e}", file=sys.stderr)
    return name, token


def rename_line(name: str) -> str:
    """The line that tells a session to take its role name in the app's sidebar, such as builder-7."""
    return RENAME.replace("{name}", name)


def lead_env(config: dict, args, name: str, token: str) -> str:
    """The env line a claimed lead starts every colony command with."""
    from colony import wait

    return env_line((SESSION_ENV, LEAD), (wait.LEAD_ENV, name), (PERSON_ENV, person_of(config, args)),
                    (wait.TOKEN_ENV, token))


def claim(config: dict, args) -> int:
    """`colony claim <stream> [folder ...]`: this session becomes the lead `<person>-<stream>-lead` over the folders,
    which no other live lead holds. No folders: the rest of the repo."""
    from colony import presence

    name, token = claim_lead(config, args, args.stream, args.folders)
    if not token:
        over = ", ".join(map(presence.folder, args.folders)) or "the rest of the repo"
        print(f"This session would lead {name}, over {over}. Nothing ran.")
        return 0
    print(f"This session leads {name}, over {', '.join(presence.claimed(name)) or 'the rest of the repo'}.")
    print(rename_line(name))
    print(f"Start every {NAME} command with `{lead_env(config, args, name, token)}`, and start `{NAME} wait` in the "
          "background within 2 minutes: it keeps the heartbeat and the status comment that hold the lead. Commit "
          f"{DIR}/{presence.LEADS_FILE} with your next change.")
    return 0


def in_claude_code() -> bool:
    """Whether this process runs inside a Claude Code session, which sets $CLAUDECODE for its commands."""
    return bool(os.environ.get("CLAUDECODE"))


def here(args) -> int:
    """Plain `colony` inside a Claude Code session: that session becomes the lead, with no new session. It never asks
    what it is.

    No .colony/colony.toml: it prints the setup prompt for this session to follow. A helper Colony opened
    ($COLONY_SESSION set to a builder's name) stays a helper. Otherwise `colony who` shows the live leads: with none,
    this session claims `<person>-main-lead` over the whole repo; with some, it names them and their folders, and asks
    the person only what's theirs, then claims those folders with `colony claim`. A first message of "join" or
    "join <lead>" makes it a helper instead, through `colony join`."""
    from colony import presence, wait

    if not config_path().exists():
        print(f"{DISPLAY}: not set up in this repo, since {DIR}/{CONFIG_NAME} is missing. Set it up in this session: "
              "follow the setup prompt below, asking the person its questions here.\n")
        print(fill_names(package_file("prompts", "setup.md")))
        return 0
    config = load_config()
    print(f"{DISPLAY}: set up here, project {config['project']['name']}, {mode(config)} mode.")
    me = os.environ.get(SESSION_ENV, "").lower()
    if me and not (me == LEAD and not wait.named()):
        role = section(config, "Lead" if me == LEAD else "Builder")
        kind = "a lead" if me == LEAD else "a helper, for good: it never asks the person anything"
        print(f"This session is {me}, which {NAME} opened, and is {kind}. Follow the {role} section of "
              f"{DIR}/playbook.md.")
        return 0
    try:
        person = person_of(config, args)
    except ColonyError:
        people = sorted({a["person"] for a in config["accounts"].values()} - {"any"})
        print(f"Next: ask the person which of {', '.join(people)} they are, then run `{NAME} --person <them>`.")
        return 0
    print('A session a person types into is a lead. (When their first message was "join" or "join <lead>", run '
          f"`{NAME} join [<lead>]` instead, and be that lead's helper.)")
    if quiet_lead(config, person):
        print(f"{person} wants a quiet lead ([people.{person}] quiet_lead = true): act on notifications silently, "
              "write to them only to converse or when they must act, and put your own status lines on the board, "
              "never in chat.")
    alive, _, note = presence.everyone(config)
    if note:
        print(note)
    leads = [status for status in alive if status.kind == "lead"]
    if not leads:
        name, token = claim_lead(config, args, "main", [])
        if not token:
            print(f"No other lead is alive, so this session would lead {name}, over the whole repo. Nothing ran.")
            return 0
        print(f"No other lead is alive, so this session leads {name}, over the whole repo.")
        print(rename_line(name))
        print(f"Next: start every {NAME} command with `{lead_env(config, args, name, token)}`, start `{NAME} wait` in "
              "the background within 2 minutes, load the colony-lead skill, and ask the person what they want.")
        return 0
    held = sorted({folder for status in leads for folder in status.folders})
    print(f"Live leads ({len(leads)}), whose folders this lead avoids:")
    for status in sorted(leads, key=lambda s: s.name):
        print(f"- {status.name} ({status.person or 'unknown person'}, {status.computer or 'unknown computer'}): "
              f"{', '.join(status.folders) or 'the rest of the repo'}")
    print(f"Next: say who is leading what, in one line, and ask the person only \"What's mine?\". Then run "
          f"`{NAME} claim <a short stream name> <folder> ...` for their answer"
          + (f", avoiding {', '.join(held)}" if held else "")
          + f". It names this lead {person.lower()}-<stream>-lead and prints the env line every command starts with.")
    return 0


def skill_install(args) -> int:
    """`colony skill-install`: copy the colony-setup skill into a Claude settings folder's skills/, so a session in
    any repo, before setup, knows how to set Colony up."""
    folder = Path(args.config_dir or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
    target = folder / "skills" / SETUP_SKILL
    if args.dry_run:
        print(f"would write {target}/. Nothing ran.")
        return 0
    if not folder.is_dir():
        raise ColonyError(f"{folder} is not a Claude settings folder: pass --config-dir")
    _copy_tree(resources.files(__package__).joinpath("skills", SETUP_SKILL), target)
    print(f"wrote {target}/")
    return 0


FIRST_RUN = ".colony-first-run"  # the marker, in the settings folder, that says the first run installed the skill


EPHEMERAL = re.compile(r"[\\/](?:archive|builds)-v\d+[\\/]")  # uv's cache folders, where a uvx run lives


def install_permanently() -> None:
    """In a uvx or npx run, which lives in uv's cache and is gone afterwards, install Colony for good with
    `uv tool install puffin-colony`, once, so the sessions it opens find `colony` on PATH later."""
    if not EPHEMERAL.search(sys.prefix) or shutil.which("uv") is None:
        return
    listed = _out(["uv", "tool", "list"])
    if re.search(r"^puffin-colony\b", listed, re.M):
        return
    print(f"{NAME}: installing {DISPLAY} for good with `uv tool install puffin-colony`, so later sessions find "
          f"`{NAME}` on PATH", file=sys.stderr)
    try:
        run = subprocess.run(["uv", "tool", "install", "puffin-colony"], capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"{NAME}: the install did not run, and this run goes on: {e}", file=sys.stderr)
        return
    if run.returncode:
        print(f"{NAME}: the install failed, and this run goes on: {(run.stderr or run.stdout).strip()[:300]}",
              file=sys.stderr)
        return
    subprocess.run(["uv", "tool", "update-shell"], capture_output=True)


def first_run() -> None:
    """Install Colony for good when this is a uvx or npx run (install_permanently). The first time `colony` runs on
    a computer, install the colony-setup skill as `colony skill-install` does, so a
    plain hi works in a repo that has never used Colony. The marker makes it happen once: a skill the person removes
    stays removed. A computer without Claude's settings folder yet is skipped, and tried again on the next run."""
    install_permanently()
    folder = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
    marker = folder / FIRST_RUN
    if not folder.is_dir() or marker.exists():
        return
    target = folder / "skills" / SETUP_SKILL
    try:
        if not target.exists():
            _copy_tree(resources.files(__package__).joinpath("skills", SETUP_SKILL), target)
            print(f"{NAME}: installed the {SETUP_SKILL} skill in {target}/, so a hi in any repo can set {DISPLAY} up",
                  file=sys.stderr)
        marker.write_text(f"{__version__}\n")
    except OSError:
        pass  # a settings folder we cannot write to never stops the command the person ran


def tools_list() -> str:
    """The one yes-or-no list of tools setup shows the person, with each tool's default and what it installs."""
    lines = ["Tools for this repo, one yes or no each, with the default in brackets:"]
    width = max(map(len, TOOLS))
    lines += [f"  {name:<{width}} [{default}] {text}" for name, (default, text) in offered().items()]
    return "\n".join(lines)


def merge_mcp(path: Path, names: list[str]) -> list[str]:
    """Add the named servers to a .mcp.json, keeping every entry already there, and return the names it added.

    A server the file already names keeps its own entry. A file that is not a JSON object with an
    `mcpServers` object is left as it is, with an error that says so.
    """
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except ValueError as e:
            raise ColonyError(f"{path} is not valid JSON ({e}): fix it, then run this again") from None
    if not isinstance(data, dict) or not isinstance(data.setdefault("mcpServers", {}), dict):
        raise ColonyError(f"{path} must hold a JSON object with an mcpServers object: fix it, then run this again")
    added = [name for name in names if name not in data["mcpServers"]]
    for name in added:
        data["mcpServers"][name] = json.loads(json.dumps(MCP_SERVERS[name]))
    if added:
        path.write_text(json.dumps(data, indent=2) + "\n")
    return added


def _copy_tree(source, target: Path) -> None:
    """Copy a package folder, with its subfolders, into `target`."""
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_dir():
            _copy_tree(item, target / item.name)
        else:
            (target / item.name).write_bytes(item.read_bytes())


def copy_skills(root: Path, names, keep: bool = False) -> tuple[list[str], list[str]]:
    """Copy the package's named skills into the repo's .claude/skills/, and return the folders written and kept.
    With `keep`, a skill folder the repo already has stays as it is."""
    written, kept = [], []
    for name in names:
        target = root / ".claude" / "skills" / name
        if keep and target.exists():
            kept.append(f".claude/skills/{name}/")
            continue
        _copy_tree(resources.files(__package__).joinpath("skills", name), target)
        written.append(f".claude/skills/{name}/")
    return written, kept


def _gh_api(path: str, raw: bool = False) -> bytes:
    """One read-only `gh api` call's output, or an error naming the call and gh's message."""
    cmd = ["gh", "api", path] + (["-H", "Accept: application/vnd.github.raw+json"] if raw else [])
    try:
        run = subprocess.run(cmd, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise ColonyError(f"gh api {path}: {e}") from None
    if run.returncode:
        raise ColonyError(f"gh api {path} failed: {run.stderr.decode(errors='replace').strip()[:300]}")
    return run.stdout


def _download(repo: str, commit: str, folder: str, target: Path) -> None:
    """Write every file of a repo's folder at a commit into `target`, keeping its subfolders."""
    for entry in json.loads(_gh_api(f"repos/{repo}/contents/{folder}?ref={commit}")):
        name = entry["name"]
        if name in ("", ".", "..") or "/" in name or "\\" in name:
            raise ColonyError(f"{repo} lists a file named {name!r}: nothing more was downloaded")
        if entry["type"] == "dir":
            _download(repo, commit, entry["path"], target / name)
        elif entry["type"] == "file":
            target.mkdir(parents=True, exist_ok=True)
            (target / name).write_bytes(_gh_api(f"repos/{repo}/contents/{entry['path']}?ref={commit}", raw=True))


def fetch_skill(root: Path, tool: str) -> str:
    """Download an outside skill at its pinned commit into the repo's .claude/skills/, and return its folder."""
    repo, commit, folder, name = OUTSIDE_SKILLS[tool]
    _download(repo, commit, folder, root / ".claude" / "skills" / name)
    return f".claude/skills/{name}/"


def tools(args) -> int:
    """`colony tools`: print the list setup offers, or write the named tools into this repo after the person's yes.

    The MCP servers merge into .mcp.json, the role and starter skills copy from the package, and an outside skill
    downloads at its pinned commit through gh. It ends by printing the [tools] table for colony.toml.
    """
    from colony import guards

    if not args.names:
        print(tools_list())
        return 0
    unknown = [name for name in args.names if name not in TOOLS]
    if unknown:
        raise ColonyError(f"{unknown[0]!r} is not a tool: choose from {', '.join(TOOLS)}")
    chosen = [name for name in TOOLS if name in args.names]
    mcps = [name for name in chosen if name in MCP_SERVERS]
    skills = [*(ROLE_SKILLS if "role-skills" in chosen else ()),
              *(guards.STARTER_SKILLS if "starter-skills" in chosen else ())]
    skills += [OUTSIDE_SKILLS[name][3] for name in chosen if name in OUTSIDE_SKILLS]
    root = repo_root()
    if args.dry_run:
        print(f"tools plan for {root}: {', '.join(chosen)}")
        if mcps:
            print(f"  .mcp.json: add {', '.join(mcps)}, keeping every entry already there")
        for skill in skills:
            print(f"  .claude/skills/{skill}/")
        print("Nothing ran.")
        return 0
    if mcps:
        added = merge_mcp(root / ".mcp.json", mcps)
        kept = [name for name in mcps if name not in added]
        print(f"wrote .mcp.json: added {', '.join(added) or 'nothing'}"
              + (f", kept the entries already there for {', '.join(kept)}" if kept else ""))
    if "role-skills" in chosen:
        print("wrote", ", ".join(copy_skills(root, ROLE_SKILLS)[0]))
    if "starter-skills" in chosen:
        written, kept = copy_skills(root, guards.STARTER_SKILLS, keep=True)
        also = f", and kept {', '.join(kept)}, which the repo already has" if kept else ""
        print(f"wrote {', '.join(written) or 'no starter skill'}{also}")
    for name in chosen:
        if name in OUTSIDE_SKILLS:
            print("wrote", fetch_skill(root, name))
    print(f"\nAdd this table to {DIR}/{CONFIG_NAME}:\n[tools]\nmcp = {json.dumps(mcps)}\nskills = {json.dumps(skills)}")
    return 0


def section(config: dict, role: str) -> str:
    """The playbook section a lead or builder follows: its role's, `Lead` or `Builder`, or `Hack` in hack mode."""
    return "Hack" if mode(config) == "hack" else role


def lead(config: dict, args) -> int:
    """Open the person's lead."""
    return launch(config, args, LEAD, "lead", LEAD_PROMPT.replace("{dir}", DIR).replace("{section}",
                                                                                         section(config, "Lead")))


def builder_prompt(name: str, config: dict) -> str:
    """A builder's first prompt."""
    return BUILDER_PROMPT.replace("{dir}", DIR).replace("{section}", section(config, "Builder")).replace("{builder}", name)


def open_builder(config: dict, args) -> int:
    """Open a builder on this computer in a new cmux workspace (the lead runs this). A named lead's wait then expects
    its status comment (wait.expect_status)."""
    from colony import wait

    lead = os.environ.get(wait.LEAD_ENV, "").lower()
    if lead and not args.dry_run:
        wait.expect_status(config["project"]["name"], lead, args.name)
    return launch(config, args, args.name, "builder", builder_prompt(args.name, config))


LOCAL = "local.toml"  # this computer's own answers, such as the last helpers answer; git-ignored
OPEN, PASTE = "open", "paste"


def local_path() -> Path:
    return repo_root() / DIR / LOCAL


def read_local() -> dict:
    """.colony/local.toml, or {} when there is none."""
    try:
        return tomllib.loads(local_path().read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def write_local(values: dict) -> None:
    """Write .colony/local.toml, and make sure git ignores it."""
    path = local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{key} = {json.dumps(value)}\n" for key, value in sorted(values.items())))
    ignore = path.parent / ".gitignore"
    lines = ignore.read_text().splitlines() if ignore.exists() else []
    if LOCAL not in lines:
        ignore.write_text("\n".join([*lines, LOCAL]) + "\n")


def helpers(config: dict, args) -> int:
    """`colony helpers <n>`: the lead needs n helpers. With no answer, it prints the one question the lead asks the
    person every time, with the last answer as the default: open them myself, or you paste? `--open` opens them on
    this computer: cmux windows when the lead runs in a terminal or cmux, else background sessions, with `colony view`
    to see them in cmux. `--paste` prints one `colony join <lead>` per helper, for any computer. Either answer becomes
    the next default, in .colony/local.toml."""
    from colony import presence, wait

    lead = wait.lead_name(config, args)
    last = read_local().get("helpers_answer", OPEN)
    answer = OPEN if args.open else PASTE if args.paste else None
    if answer is None:
        account, _, why = choose_account_why(config, args)
        first, second = ("Open them", "I'll paste") if last == OPEN else ("I'll paste", "Open them")
        print(f"Ask the person, with [{first}] as the default: \"I need {args.count} helper"
              f"{'s' if args.count != 1 else ''}. Open them myself on {account}, or you paste?\" "
              f"[{first}] [{second}]. Then run `{NAME} helpers {args.count} --{'open' if first == 'Open them' else 'paste'}`"
              f", or the other answer. ({why})")
        return 0
    write_local({**read_local(), "helpers_answer": answer})
    alive, _, _ = presence.everyone(config)
    if answer == PASTE:
        print(f"Paste this on any computer, in a cmux terminal or typed into an app session there; each connects to "
              f"{lead} by itself:")
        for _ in range(args.count):
            print(f"  {NAME} join {lead}")
        return 0
    taken: set[str] = set()
    for _ in range(args.count):
        name = free_helper(config, [*alive, *(presence.Status(n, "helper") for n in taken)])
        taken.add(name)
        code = launch(config, argparse.Namespace(**{**vars(args), "name": name, "here": False}), name, "builder",
                      builder_prompt(name, config))
        if code:
            return code
    if not cmux_usable():
        print(f"They run in the background. To see them in cmux, paste this into any cmux terminal: {NAME} view")
    return 0


def running_sessions(config: dict) -> list[dict]:
    """Every running Colony session on this computer, as `claude agents --json` lists it per account folder: the ones
    whose name starts `<project>-`, each with its account's folder."""
    found = []
    for folder in dict.fromkeys(a["config_dir"] for a in config["accounts"].values()):
        if not Path(folder).expanduser().is_dir():
            continue
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        if not is_default_dir(folder):
            env["CLAUDE_CONFIG_DIR"] = folder
        try:
            run = subprocess.run(["claude", "agents", "--json"], capture_output=True, text=True, env=env, timeout=30)
            listed = json.loads(run.stdout) if run.returncode == 0 else []
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
        for agent in listed if isinstance(listed, list) else []:
            if isinstance(agent, dict) and agent.get("id") and str(agent.get("name", "")).startswith(
                    f"{config['project']['name']}-"):
                found.append({**agent, "config_dir": folder})
    return found


def view_commands(config: dict) -> list[list[str]]:
    """One cmux command per running Colony session: a workspace that attaches to it on its own account."""
    commands = []
    for agent in running_sessions(config):
        attach = ["claude", "attach", agent["id"]]
        if not is_default_dir(agent["config_dir"]):
            attach = ["env", f"CLAUDE_CONFIG_DIR={agent['config_dir']}", *attach]
        commands.append([cmux_command() or "cmux", "new-workspace", "--name", agent["name"], "--cwd", agent.get("cwd") or str(repo_root()),
                         "--command", shlex.join(attach)])
    return commands


def view(config: dict, args) -> int:
    """`colony view`: open a cmux workspace for every running Colony session on this computer, attached to it, so
    background sessions show in cmux. Outside cmux it prints the commands instead."""
    commands = view_commands(config)
    if not commands:
        print(f"No {DISPLAY} session runs on this computer.")
        return 0
    if args.dry_run or not cmux_usable():
        if not args.dry_run:
            print("cmux doesn't take commands from here: run `colony view` in a cmux terminal, or these:")
        for command in commands:
            print(shlex.join(command))
        return 0
    for command in commands:
        subprocess.run(command)
    print(f"Opened {len(commands)} workspace{'s' if len(commands) != 1 else ''} in cmux.")
    return 0


def brief(name: str) -> tuple[str, str]:
    """A role's brief and where it came from: the repo's own {dir}/prompts/<name>.md, which setup copies with the
    project's values in, else the package's prompts/<name>.md."""
    own = repo_root() / DIR / "prompts" / f"{name}.md"
    if own.is_file():
        return own.read_text(), f"{DIR}/prompts/{name}.md"
    return package_file("prompts", f"{name}.md"), f"the package's prompts/{name}.md"


def open_brief(config: dict, args, role: str, **values: str) -> int:
    """Open a researcher, the spec agent or a tester on this computer, whose first prompt is its brief filled in:
    `{project}`, `{knowledge}` (the vault folder, `[knowledge] vault`) and the request (`{question}`, `{feature}` or
    `{release}`)."""
    from colony import batch, vault

    for key, value in values.items():
        values[key] = " ".join(value.split())
        if not values[key]:
            raise ColonyError(f"{NAME} {args.command} needs the {key}, in quotes")
    text, source = brief(role)
    try:
        prompt = batch.fill(text, project=config["project"]["name"], knowledge=vault.read_settings(config).vault,
                            **values)
    except KeyError as e:
        raise ColonyError(f"{source}: {e.args[0]}") from None
    return launch(config, args, role, role, prompt)


def research(config: dict, args) -> int:
    """`colony research "<question>"`: open a researcher, which answers one question with cited sources."""
    return open_brief(config, args, RESEARCHER, question=args.question)


def spec(config: dict, args) -> int:
    """`colony spec "<feature>"`: open the spec agent, which writes a FEATURE's requirements, design and tasks."""
    return open_brief(config, args, SPEC, feature=args.feature)


def tester(config: dict, args) -> int:
    """`colony tester "<release pull request>"`: open a tester, which checks a release's cards on the deployed app."""
    return open_brief(config, args, TESTER, release=args.release)


def origin_url() -> str:
    """The URL of this checkout's origin remote, or an empty string when it has none."""
    return _out(["git", "remote", "get-url", "origin"])


def join_missing(config: dict, args) -> list[str]:
    """What this computer lacks to run a builder: a clone of the repo, claude and its login, or gh auth."""
    repo, missing = config["project"]["repo"], []
    if repo.lower() not in origin_url().lower():
        missing.append(f"a clone of {repo}: run `gh repo clone {repo}`, then `{NAME} join` inside it")
    if shutil.which("claude") is None:
        missing.append("claude: install Claude Code, then sign in with /login")
    else:
        account, folder = choose_account(config, args)
        if not signed_in(folder):
            missing.append(f"the claude login for account {account}: open claude on that account and run /login")
    if shutil.which("gh") is None or subprocess.run(["gh", "auth", "status"], capture_output=True).returncode:
        missing.append("gh auth: run `gh auth login`")
    return missing


def pick_lead(config: dict, args, alive: list) -> str:
    """The lead a joining helper belongs to: `<lead>` when given, by its name or its stream, else the person's one live
    lead, else, with several, the person's answer to one question naming each lead and its folders."""
    person = person_of(config, args).lower()
    mine = [s for s in alive if s.kind == "lead" and (s.person.lower() == person or s.name.startswith(f"{person}-"))]
    wanted = (getattr(args, "lead", None) or "").lower()
    if wanted:
        for status in mine:
            if status.name in (wanted, f"{person}-{wanted}-{LEAD}"):
                return status.name
        raise ColonyError(f"no live lead of yours is {wanted!r}: yours are {', '.join(s.name for s in mine) or 'none'}")
    if not mine:
        raise ColonyError(f"no live lead of {person}'s: open a session in the repo and say hi first, which makes a lead")
    if len(mine) == 1:
        return mine[0].name
    choices = "\n".join(f"  {i}. {s.name}: {', '.join(s.folders) or 'the rest of the repo'}"
                        for i, s in enumerate(mine, 1))
    if not portable.is_terminal(sys.stdin):
        raise ColonyError(f"you have {len(mine)} live leads, so name one: `{NAME} join <lead>`\n{choices}")
    answer = input(f"Which lead does this computer help?\n{choices}\nNumber or name: ").strip().lower()
    for i, status in enumerate(mine, 1):
        if answer in (str(i), status.name, status.name.removeprefix(f"{person}-").removesuffix(f"-{LEAD}")):
            return status.name
    raise ColonyError(f"{answer!r} is none of those leads")


def free_helper(config: dict, alive: list) -> str:
    """The next builder name no live helper anywhere, and no wait on this computer, uses: builder-1 up."""
    from colony import wait

    used = {s.name for s in alive if s.kind == "helper"}
    n = 1
    while True:
        name = f"builder-{n}"
        state = wait.read_json(wait.state_path(config["project"]["name"], name), {})
        polled = state.get("polled_at") if isinstance(state, dict) else None
        busy = isinstance(polled, (int, float)) and time.time() - polled < wait.HEARTBEAT_FRESH
        if name not in used and not busy:
            return name
        n += 1


def tell_lead_joined(config: dict, lead: str, name: str) -> None:
    """Post `for <lead>: joined: <name> (from <name>)` on the coordination issue, so the lead's wait wakes on it. The
    helper has joined either way, so a post that fails says so on stderr alone."""
    from colony import transport, wait

    try:
        transport.send(config, lead, wait.compose(lead, f"joined: {name}", name))
    except (ColonyError, OSError, ValueError, KeyError) as e:
        print(f"{NAME} join: {lead} hears of {name} from its status comment instead: {e}", file=sys.stderr)


def join(config: dict, args) -> int:
    """`colony join [<lead>]`: lend this computer to one of the person's leads, as a helper under the next free
    builder name, after saying what this computer still lacks. Inside a Claude Code session ($CLAUDECODE), or with
    --in-session, the session that ran it becomes the helper on its own account, instead of a new session opening:
    it claims the name with its status comment at once, so the lead sees it and gives it a card."""
    from colony import presence, wait

    alive, _, note = presence.everyone(config)
    if note:
        print(note, file=sys.stderr)
    args.lead_name = pick_lead(config, args, alive)
    name = free_helper(config, alive)
    if getattr(args, "in_session", False) or in_claude_code():
        state: dict = {}
        try:
            status = presence.mine(config, args, name, "helper", args.lead_name)
            presence.keep(config, status, state)
            wait.write_json(wait.state_path(config["project"]["name"], f"{name}-status"), state)
        except (ColonyError, OSError, ValueError, KeyError) as e:
            print(f"{NAME}: the status comment waits for the first `{NAME} wait`: {e}", file=sys.stderr)
        env = env_line((SESSION_ENV, name), (wait.LEAD_ENV, args.lead_name), (PERSON_ENV, person_of(config, args)))
        tell_lead_joined(config, args.lead_name, name)
        print(f"This session is {name}, a helper of {args.lead_name}, on account {current_account(config)}.")
        print(rename_line(name))
        print(f"Next: start every {NAME} command with `{env}`, start `{NAME} wait` in the background now, which tells "
              f"{args.lead_name} you are here, load the colony-builder skill, and read {DIR}/playbook.md, "
              f"{section(config, 'Builder')} section. Never ask the person anything: your lead gives you cards.")
        return 0
    missing = join_missing(config, args)
    for item in missing:
        print("missing:", item)
    if missing and not args.dry_run:
        return 1
    print(f"Joining {args.lead_name} as {name}.")
    if not args.dry_run:
        wait.expect_status(config["project"]["name"], args.lead_name, name)
        tell_lead_joined(config, args.lead_name, name)
    return launch(config, args, name, "builder", builder_prompt(name, config))


def card_folders(text: str) -> list[str]:
    """The folders a card's body names on its `Folders:` line, such as `Folders: apps/web/, tools/`."""
    from colony import presence

    for line in text.splitlines():
        found = re.match(r"^\W*folders?\W*:\s*(.+)$", line.strip(), re.I)
        if found:
            parts = re.split(r"[,\s]+", found[1].replace("`", " "))
            return [presence.folder(part) for part in parts if part.strip(" ./")]
    return []


IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".svg")
IMAGE_LIMIT = 10_000_000  # bytes


def card_branch(card: int) -> str:
    """The card's own branch, which holds what the lead adds for it, such as a pasted image: card/<n>."""
    return f"card/{card}"


def image(config: dict, args) -> int:
    """`colony image <n> <file>`: the lead saves an image the person pasted for card n under .colony/images/<n>/ on
    the card's branch, card/<n>, and pushes it, so a helper on any computer sees it. It works in a throwaway worktree,
    so the lead's own checkout is untouched, and comments on the card where the image is."""
    from colony import wait

    source = Path(args.file).expanduser()
    if not source.is_file() or source.suffix.lower() not in IMAGE_TYPES:
        raise ColonyError(f"{args.file} is not an image file ({', '.join(IMAGE_TYPES)})")
    if source.stat().st_size > IMAGE_LIMIT:
        raise ColonyError(f"{args.file} is over {IMAGE_LIMIT // 1_000_000} MB: save a smaller copy")
    root, branch = repo_root(), card_branch(args.card)

    def git(*parts: str, cwd: Path = root) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *parts], cwd=cwd, capture_output=True, text=True)

    git("fetch", "origin")
    start = f"origin/{branch}" if git("rev-parse", "--verify", "--quiet", f"origin/{branch}").returncode == 0 \
        else f"origin/{config['project']['base']}"
    folder = Path(config["project"].get("worktrees") or root.parent) / f"{config['project']['name']}-image-{args.card}"
    made = git("worktree", "add", "--detach", str(folder), start)
    if made.returncode:
        raise ColonyError(f"git worktree add failed: {made.stderr.strip()[:300]}")
    try:
        name = re.sub(r"[^\w.-]", "-", source.name)
        target = Path(DIR) / "images" / str(args.card) / name
        (folder / target).parent.mkdir(parents=True, exist_ok=True)
        (folder / target).write_bytes(source.read_bytes())
        for step in (("add", str(target)), ("commit", "-m", f"card #{args.card}: add {name}"),
                     ("push", "origin", f"HEAD:refs/heads/{branch}")):
            done = git(*step, cwd=folder)
            if done.returncode:
                raise ColonyError(f"git {step[0]} failed: {(done.stderr or done.stdout).strip()[:300]}")
    finally:
        git("worktree", "remove", "--force", str(folder))
    wait.gh("issue", "comment", str(args.card), "--repo", config["project"]["repo"], "--body",
            f"Image for this card: `{target}` on the branch `{branch}`. Start the card's branch from origin/{branch}.")
    print(f"Saved {target} on {branch}, and said so on #{args.card}.")
    return 0


def take(config: dict, args) -> int:
    """`colony take <n>`: a helper takes card n, which must sit in its lead's folders, and marks it In progress with
    itself as Helper. A lead with no folders holds the rest of the repo, so its card must avoid other live leads'."""
    from colony import board, presence, wait

    me = os.environ.get(SESSION_ENV, "").lower()
    lead = os.environ.get(wait.LEAD_ENV, "").lower()
    if not me or me == LEAD or not lead:
        raise ColonyError(f"take is for a helper, with {SESSION_ENV} and {wait.LEAD_ENV} set")
    card = json.loads(wait.gh("issue", "view", str(args.card), "--repo", config["project"]["repo"], "--json", "body"))
    folders = card_folders(card.get("body") or "")
    if not folders:
        raise ColonyError(f"card #{args.card} names no folders: ask {lead} to add a `Folders:` line")
    own = presence.claimed(lead)
    if own:
        outside = [f for f in folders if not any(f.startswith(mine) for mine in own)]
        if outside:
            raise ColonyError(f"card #{args.card} touches {', '.join(outside)}, outside {lead}'s folders "
                              f"({', '.join(own)}): post `question:` to {lead}, and take no card outside them")
    else:
        alive, _, _ = presence.everyone(config)
        held = [(f, g, other) for other, theirs in presence.held_by_others(alive, lead).items()
                for f in folders for g in theirs if presence.overlaps(f, g)]
        if held:
            raise ColonyError(f"card #{args.card} touches {held[0][0]}, which {held[0][2]} holds: post `question:` to "
                              f"{lead}, and take no card in another lead's folders")
    board.set_fields(config, args.card, [("Status", "In progress"), ("Helper", me)])
    print(f"#{args.card} is yours, {me}: In progress.")
    start = f"origin/{config['project']['base']}"
    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"origin/{card_branch(args.card)}"],
                      capture_output=True).returncode == 0:
        start = f"origin/{card_branch(args.card)}"
        print(f"Its images are on {start}, so your branch starts there, not from the base.")
    print("Make its worktree with:\n  " + worktree_command(config, me, args.card, start))
    return 0


def worktree_command(config: dict, me: str, card: int, start: str) -> str:
    """The command that makes a builder's worktree for a card, `<worktrees>/<project>-<me>-<n>` on the branch
    `<me>/<n>`, with forward slashes, which git takes on every system and Bash keeps as they are."""
    folder = Path(config["project"]["worktrees"]).expanduser() / f"{config['project']['name']}-{me}-{card}"
    return f"git fetch origin && git worktree add {shlex.quote(folder.as_posix())} -b {me}/{card} {start}"


def batch(config: dict, args) -> int:
    """Take a batch of cards through the loop to a pull request (batch.run_batch)."""
    from colony import batch as runner

    return runner.run_batch(config, args)


def status(config: dict, args) -> int:
    """Print this computer's lead (lead_line), then where a batch stands (batch.batch_status)."""
    from colony import batch as runner

    print(lead_line(config))
    return runner.batch_status(config, args)


def wait(config: dict, args) -> int:
    """Wait for the lines addressed to this session (wait.run)."""
    from colony import wait as watcher

    return watcher.run(config, args)


def merge(config: dict, args) -> int:
    """Land a branch on the base after a passing fast check, or open its pull request (merge.run)."""
    from colony import merge as lander

    return lander.run(config, args)


def sync(config: dict, args) -> int:
    """Merge origin/<base> into a branch, rebuilding a conflict only in generated files (merge.sync)."""
    from colony import merge as lander

    return lander.sync(config, args)


def card(value: str) -> str:
    """Check that a --card value has the shape N=BRANCH, and return it unchanged."""
    number, _, branch = value.partition("=")
    if not number.isdigit() or not branch:
        raise argparse.ArgumentTypeError(f"{value!r} is not N=BRANCH")
    return value


def builder_name(value: str) -> str:
    """Check a builder's name: lowercase letters, digits, dots and dashes, and not the lead's."""
    if not SESSION_NAME.fullmatch(value) or value == LEAD:
        raise argparse.ArgumentTypeError(f"{value!r} is not a builder name, such as builder-2")
    return value


ACCOUNT_HELP = ("the account to open on, instead of the pick: [people.<person>] accounts with room, the soonest weekly "
                "reset first, then last_resort")


def build_parser() -> argparse.ArgumentParser:
    """The command line: no command for setup or the lead, then the sessions (join, open, research, spec), the lines
    (wait, say, post), the gate (batch, status, merge), the cycle's, the board, check-docs, the guards', and tools."""
    from colony import board, cycle, guards, presence, release, tidy, vault
    parser = argparse.ArgumentParser(prog=NAME, description=f"{DISPLAY}: run with no command to open your lead "
                                     f"(or to set up the repo, the first time).")
    parser.add_argument("--version", action="version", version=f"{DISPLAY} {__version__}")
    parser.add_argument("--person", help=f"whose accounts to use (needed when {CONFIG_NAME} names several people)")
    parser.add_argument("--account", metavar="NAME", help=ACCOUNT_HELP)
    parser.add_argument("--here", action="store_true", help="open in this terminal even when cmux is on PATH")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and the env names, and run nothing")
    parser.set_defaults(run=lead)
    sub = parser.add_subparsers(dest="command", metavar="command")

    p = sub.add_parser("join", help="lend this computer to one of your leads, as a helper under the next free name")
    p.add_argument("lead", nargs="?", help="the lead, by name or stream, such as engine; asked once when you have several")
    p.add_argument("--in-session", action="store_true",
                   help="make the session that runs this the helper, on its own account, instead of opening one")
    p.add_argument("--person", help="whose accounts to use")
    p.add_argument("--account", metavar="NAME", help=ACCOUNT_HELP)
    p.add_argument("--here", action="store_true", help="open in this terminal even when cmux is on PATH")
    p.add_argument("--dry-run", action="store_true", help="print the command and the env names, and run nothing")
    p.set_defaults(run=join)
    p = sub.add_parser("open", help="open a helper for the lead that runs it: in cmux, else in the background")
    p.add_argument("name", type=builder_name, help="the builder's name, such as builder-2")
    p.add_argument("--person", help="whose accounts to use")
    p.add_argument("--account", metavar="NAME", help=ACCOUNT_HELP)
    p.add_argument("--dry-run", action="store_true", help="print the command and the env names, and run nothing")
    p.set_defaults(run=open_builder)
    p = sub.add_parser("helpers", help="the lead needs n helpers: ask open-or-paste with the last answer as the "
                                       "default, then --open them here or --paste join lines")
    p.add_argument("count", type=int, help="how many helpers")
    answer = p.add_mutually_exclusive_group()
    answer.add_argument("--open", action="store_true", help="open them on this computer")
    answer.add_argument("--paste", action="store_true", help="print one `colony join <lead>` per helper to paste")
    p.add_argument("--person", help="whose accounts to use")
    p.add_argument("--account", metavar="NAME", help=ACCOUNT_HELP)
    p.add_argument("--dry-run", action="store_true", help="print the commands and the env names, and run nothing")
    p.set_defaults(run=helpers)
    p = sub.add_parser("view", help="open a cmux workspace for every running Colony session on this computer")
    p.add_argument("--dry-run", action="store_true", help="print the cmux commands, and run nothing")
    p.set_defaults(run=view)
    p = sub.add_parser("claim", help="this session becomes the lead <person>-<stream>-lead over folders no live lead "
                                     "holds")
    p.add_argument("stream", help="a short name for this lead's stream of work, such as engine")
    p.add_argument("folders", nargs="*", metavar="folder", help="the folders it holds; none for the rest of the repo")
    p.add_argument("--person", help="whose session this is")
    p.set_defaults(run=claim)
    p = sub.add_parser("image", help="the lead: save a pasted image for a card on its branch card/<n>, for every "
                                     "helper to see")
    p.add_argument("card", type=int, help="the card's issue number")
    p.add_argument("file", help="the image file")
    p.set_defaults(run=image)
    p = sub.add_parser("take", help="a helper: take a card inside its lead's folders, and mark it In progress")
    p.add_argument("card", type=int, help="the card's issue number")
    p.set_defaults(run=take)

    for command, run, field, text in (
            ("research", research, "question", "open a researcher on one question, answered with cited sources"),
            ("spec", spec, "feature", "open the spec agent on a FEATURE: requirements, design and tasks"),
            ("tester", tester, "release", "open a tester after a release: it checks the release's cards on the deployed "
                                          "app and files one findings issue")):
        p = sub.add_parser(command, help=text)
        p.add_argument(field, help=f"the {field}, in quotes")
        p.add_argument("--person", help="whose accounts to use")
        p.add_argument("--account", metavar="NAME", help=ACCOUNT_HELP)
        p.add_argument("--here", action="store_true", help="open in this terminal even when cmux is on PATH")
        p.add_argument("--dry-run", action="store_true", help="print the command and the env names, and run nothing")
        p.set_defaults(run=run)

    p = sub.add_parser("wait", help=f"wait for the lines addressed to ${SESSION_ENV}, then print them")
    p.set_defaults(run=wait)
    from colony import wait as watcher  # wait's --waiting-on, and `say`, live in wait.py
    watcher.add_commands(sub, p)

    p = sub.add_parser("batch", help="take finished cards through review, checks and a walk to a pull request")
    p.add_argument("--name", required=True, help="the batch name")
    p.add_argument("--card", action="append", required=True, type=card, metavar="N=BRANCH",
                   help="a card's issue number and branch; repeat for each card")
    p.add_argument("--from", dest="from_branch", metavar="BRANCH", help="build on this branch instead of origin/<base>")
    p.add_argument("--person", help="whose accounts the agents use")
    p.add_argument("--account", metavar="NAME", help="the account the agents run on, instead of the pick "
                                                     "([people.<person>] accounts by room, soonest weekly reset first)")
    p.add_argument("--review", action="store_true",
                   help="add a fresh reviewer to a gate whose [gate] review is false, as in hack mode")
    p.add_argument("--fast", action="store_true",
                   help="run the full checks once, with no reviewer, walk or fixers, and open the PR when they pass")
    p.add_argument("--dry-run", action="store_true", help="print the plan and run nothing")
    p.set_defaults(run=batch)

    p = sub.add_parser("status", help="show the lead's name, account and heartbeat, then a batch's round, open "
                                      "problems, walk, running steps and minutes")
    p.add_argument("--name", help="the batch name")
    p.set_defaults(run=status)

    p = sub.add_parser("merge", help="hack mode: merge a branch into the base after a passing fast check, "
                                     "else open its pull request")
    p.add_argument("branch", help="the branch to land, such as ana/login-form")
    p.add_argument("--dry-run", action="store_true", help="print the plan and run nothing")
    p.set_defaults(run=merge)

    p = sub.add_parser("sync", help="merge origin/<base> into a branch; a conflict only in generated files is rebuilt "
                                    "with regen, any other stops it")
    p.add_argument("branch", help="the branch to bring up to the base, such as lead/integration")
    p.set_defaults(run=sync)

    for module in (cycle, board, vault, guards, presence, tidy, release):
        module.add_commands(sub)

    p = sub.add_parser("setup", help="set this repo up in a new claude session in this terminal, or --print the "
                                     "setup prompt for a session already open")
    p.add_argument("--print", action="store_true", help="print the setup prompt, and run nothing")
    p.add_argument("--dry-run", action="store_true", help="print the plan and run nothing")
    p.set_defaults(run=setup)

    p = sub.add_parser("skill-install", help=f"copy the {SETUP_SKILL} skill into a Claude settings folder, so a "
                                             "session in any repo can set Colony up")
    p.add_argument("--config-dir", metavar="DIR", help="the settings folder, $CLAUDE_CONFIG_DIR or ~/.claude by default")
    p.add_argument("--dry-run", action="store_true", help="print what it would write, and run nothing")
    p.set_defaults(run=skill_install)

    p = sub.add_parser("tools", help="list the MCPs and skills setup offers, or write the named ones "
                                     "(setup runs it)")
    p.add_argument("names", nargs="*", metavar="tool", help=f"the tools to write: {', '.join(TOOLS)}")
    p.add_argument("--dry-run", action="store_true", help="print what it would write, and run nothing")
    p.set_defaults(run=tools)
    return parser


def main(argv=None) -> int:
    """Parse the command line and run one command: setup when the repo has no .colony/colony.toml, else the one asked."""
    if portable.needs_utf8():
        return portable.relaunch_in_utf8(sys.argv[1:] if argv is None else list(argv))
    args = build_parser().parse_args(argv)
    if not getattr(args, "dry_run", False):
        first_run()
    try:
        if args.command is None and in_claude_code():
            return here(args)
        if args.command is None and not config_path().exists():
            return setup(args)
        if args.command in ("tools", "setup", "skill-install"):  # each runs before colony.toml exists
            return args.run(args)
        config = load_config()
        feature = FEATURES.get(args.command)
        if feature and not config["features"][feature]:
            raise ColonyError(f"`{NAME} {args.command}` is off in {mode(config)} mode: set {feature} = true under "
                              f"[features] in {DIR}/{CONFIG_NAME} to turn it on")
        return args.run(config, args) or 0
    except ColonyError as e:
        print(f"{NAME}: {e}", file=sys.stderr)
        return 2
