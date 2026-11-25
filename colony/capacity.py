"""Capacity: the team's accounts, this computer, and the things one run at a time may use.

Seven parts, each with its own section below:

- The account pool ([pool], [accounts.<name>]): the order accounts are used in, when a session switches away from
  one, which accounts stay free, and how many helpers one account runs at once. Any provider: an account whose
  `usage_command` prints its usage is judged the same way as a Claude Code settings folder (policy, judge, busy).
- Waves: `colony helpers <n> --open` opens a wave of helpers now and the rest in later waves, each helper on an
  account under its cap, within the room this computer has (open_helpers, open_later).
- Usage limits: a session whose turn ended on its account's usage limit is noted (note_limited), and woken once that
  limit resets, by its own wait, its lead's wait, or `colony wake --follow` (wake_due).
- Services: each service the team relies on, such as an AI provider, a cloud CLI, the code host or a registry, has a
  check, a command with a pass condition, and the lead hears when one fails (services, run_service).
- The right account: the account a session really runs on, from the folder that holds its own transcript, and a line
  when that differs from the account it was opened for (session_account, account_line).
- This computer: its cores, memory, free disk and load, read with the standard library on macOS, Linux and Windows,
  and how many helpers, test runs and builds may run at once, fewer while it is busy (machine, limits).
- Locks: named locks with slots for what can't be shared, such as one test database or one port (hold, `colony lock`).
- Sleep: a gap the computer slept through, after which the waits and helpers that stopped start again (slept,
  restart).
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
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from colony import cli, portable, wait

SLEEP = time.sleep  # what the waves and the follower sleep on; tests pass a fake
ACCOUNT_ENV = f"{cli.NAME.upper()}_ACCOUNT"  # the account Colony opened a session on, which its checks compare with
CHECK_EVERY = 60  # seconds between a wait's capacity checks
FOLLOW_EVERY = 60  # seconds between `colony wake --follow` passes
SEEN_EVERY = 5 * 60  # seconds between the lead's notes of which helpers run here, which a restart compares with
LIMIT_GRACE = 60  # seconds after a reset before a limited session is woken, so the provider has reset too
UNKNOWN_RESET_RETRY = 30 * 60  # with no known reset time, a limited session is tried again this long after its limit
LIMITED_KEPT = 8 * 24 * 3600  # a limit noted longer ago than a week and a day is dropped: every window has reset
WAVE_PATIENCE = 60 * 60  # the later waves give up after this long with no room to open a helper
SERVICE_TIMEOUT = 20  # seconds a service check runs by default
SERVICE_EVERY = 30  # minutes between a service's checks by default
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")  # a lock's or a service's name
LIMIT_ERROR = re.compile(r"limit", re.I)  # a StopFailure error code that means a usage limit, such as rate_limit
IDLE = ("idle", "done", "stopped", "exited", "completed")  # a session state that takes a prompt
LIMIT_PROMPT = ("Your account {account}'s usage limit has reset. Start `colony wait` in the background again, and "
                "carry on from where you stopped.")
SLEPT_PROMPT = ("This computer slept or restarted, and your wait stopped. Start `colony wait` in the background again, "
                "and carry on from where you stopped.")
STOPPED_PROMPT = "Your `colony wait` had stopped. Start it in the background again, and carry on from where you stopped."


def state(project: str, name: str) -> Path:
    """One of this module's files for the project on this computer, ~/.colony/<project>/<name>.json."""
    return wait.state_path(project, name)


def read(project: str, name: str) -> dict:
    """One of this module's files as a dict, or {} when it is missing or unreadable."""
    held = wait.read_json(state(project, name), {})
    return held if isinstance(held, dict) else {}


# The account pool: [pool] and each account's own keys


ORDERS = ("reset", "listed")
POOL_KEYS = ("order", "out_at", "near_at", "near_hours", "reserve", "max_busy", "wave", "wave_seconds", "stale_minutes",
             "share_lead_accounts", "helper_rate", "scan_folders")
SCAN_FOLDERS = ("~/.claude", "~/.claude-*", "~/.claude_*")  # where `colony accounts scan` looks for settings folders


@dataclass(frozen=True)
class Policy:
    """The team's rules for its pool of accounts, from [pool]."""

    order: str = "reset"  # "reset": the soonest weekly reset first, "use it or lose it"; "listed": the person's order
    out_at: float = 95.0  # a window at or past this percent has no room: the session switches account
    near_at: float = 80.0  # the 5-hour window at or past this, with its reset more than near_hours off, is skipped
    near_hours: float = 1.0
    reserve: frozenset = frozenset()  # accounts kept free: used only when named with --account
    max_busy: int = 3  # helpers one account runs at once; [accounts.<name>] max_busy sets one account's own
    wave: int = 3  # helpers `colony helpers --open` opens at once
    wave_seconds: float = 60.0  # the pause between waves
    stale_minutes: float = 15.0  # a reading older than this never places a session: its account's room is unknown
    share_lead_accounts: bool = False  # True: a live lead's own account takes helpers as any other, with no room kept
    helper_rate: float = 10.0  # the 5-hour window's percent one busy helper uses an hour, until readings show it
    scan_folders: tuple = SCAN_FOLDERS


def number(table: dict, key: str, default, low: float, high: float | None = None, whole: bool = False,
           where: str = "[pool]"):
    """A number from a config table, checked: a whole number when `whole`, from `low`, up to `high`."""
    value = table.get(key, default)
    if value is None:
        return None
    good = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= low and \
        (high is None or value <= high) and (not whole or float(value).is_integer())
    if not good:
        span = f"from {low:g} to {high:g}" if high is not None else f"of at least {low:g}"
        raise cli.ColonyError(f"{cli.CONFIG_NAME}: {where} {key} is a {'whole ' if whole else ''}number {span}, not "
                              f"{value!r}")
    return int(value) if whole else float(value)


def policy(config: dict) -> Policy:
    """[pool] as a Policy, with each key checked; a config without it gets the defaults."""
    table = config.get("pool") or {}
    if not isinstance(table, dict):
        raise cli.ColonyError(f"{cli.CONFIG_NAME}: [pool] is a table")
    unknown = sorted(set(table) - set(POOL_KEYS))
    if unknown:
        raise cli.ColonyError(f"{cli.CONFIG_NAME}: [pool] has no key {unknown[0]!r}: its keys are {', '.join(POOL_KEYS)}")
    order = table.get("order", "reset")
    if order not in ORDERS:
        raise cli.ColonyError(f'{cli.CONFIG_NAME}: [pool] order is "reset" or "listed", not {order!r}')
    reserve = table.get("reserve", [])
    if not isinstance(reserve, list) or not all(isinstance(name, str) for name in reserve):
        raise cli.ColonyError(f"{cli.CONFIG_NAME}: [pool] reserve is a list of account names")
    missing = [name for name in reserve if name not in config.get("accounts", {})]
    if missing:
        raise cli.ColonyError(f"{cli.CONFIG_NAME}: [pool] reserve names {missing[0]!r}, which no [accounts.<name>] "
                              "table holds")
    share = table.get("share_lead_accounts", False)
    if not isinstance(share, bool):
        raise cli.ColonyError(f"{cli.CONFIG_NAME}: [pool] share_lead_accounts is true or false, not {share!r}")
    scan = table.get("scan_folders", list(SCAN_FOLDERS))
    if not isinstance(scan, list) or not all(isinstance(item, str) and item.strip() for item in scan):
        raise cli.ColonyError(f"{cli.CONFIG_NAME}: [pool] scan_folders is a list of folders, such as "
                              '["~/.claude", "~/.claude-*"]')
    from colony import profile  # a profile's pool.max_busy binds placement too, the stricter of the two

    busy = profile.stricter(config, "pool.max_busy", number(table, "max_busy", 3, 1, whole=True))
    return Policy(order, number(table, "out_at", 95, 1, 100), number(table, "near_at", 80, 1, 100),
                  number(table, "near_hours", 1, 0), frozenset(reserve), busy,
                  number(table, "wave", 3, 1, whole=True), number(table, "wave_seconds", 60, 0),
                  # a reading is fetched again once it is cli.USAGE_STALE old, so a shorter limit would never be met
                  stale_minutes=number(table, "stale_minutes", 15, cli.USAGE_STALE / 60),
                  share_lead_accounts=share, helper_rate=number(table, "helper_rate", 10, 0, 100),
                  scan_folders=tuple(scan))


def cap(config: dict, name: str, pool: Policy) -> int:
    """The most helpers one account runs at once: its own max_busy, else [pool] max_busy, and never more than a
    profile's pool.max_busy."""
    from colony import profile

    own = number(config["accounts"][name], "max_busy", pool.max_busy, 1, whole=True, where=f"[accounts.{name}]")
    return profile.stricter(config, "pool.max_busy", own)


_readings: dict[str, tuple[float, dict]] = {}  # each usage_command's last output in this process, and when


def command_reading(command: str, folder: str, now: float | None = None) -> dict:
    """What an account's usage_command printed: Claude Code's shape, `{"five_hour": {"utilization": 40, "resets_at":
    "<ISO time>"}, "seven_day": {...}}`, run at most once per cli.USAGE_STALE seconds. It runs with the account's folder
    as $COLONY_ACCOUNT_DIR, so one command serves several accounts. A failure, or output in another shape, is no
    reading."""
    now = time.time() if now is None else now
    held = _readings.get(f"{command}\n{folder}")
    if held and now - held[0] < cli.USAGE_STALE:
        return held[1]
    args, use_shell, env = portable.shell(command, {**os.environ, f"{ACCOUNT_ENV}_DIR": folder})
    try:
        run = subprocess.run(args, shell=use_shell, env=env, capture_output=True, text=True, timeout=SERVICE_TIMEOUT)
        data = json.loads(run.stdout) if run.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    _readings[f"{command}\n{folder}"] = (now, data)
    return data


def windows(config: dict, name: str, now: datetime | None = None) -> dict[str, tuple[float, datetime | None]]:
    """An account's usage per window, as cli.usage gives it: from its usage_command when it has one, which any
    provider can have, else from its Claude Code settings folder."""
    account = config["accounts"][name]
    if account.get("usage_command"):
        return cli.read_windows(command_reading(account["usage_command"], account["config_dir"]),
                                now or datetime.now(timezone.utc))
    return cli.usage(account["config_dir"], now)


def reading_age(config: dict, name: str, now: float | None = None) -> float | None:
    """Seconds since an account's usage was read, or None when it has no reading: for a usage_command, since Colony
    last ran it; for a Claude Code folder, since Claude Code fetched it (cli.reading_age), else, for a reading saved
    with no time, since its state file last changed."""
    now = time.time() if now is None else now
    account = config["accounts"][name]
    if account.get("usage_command"):
        held = _readings.get(f"{account['usage_command']}\n{account['config_dir']}")
        return now - held[0] if held and held[1] else None
    age = cli.reading_age(account["config_dir"], now)
    if age is not None or not cli.usage(account["config_dir"]):
        return age
    try:
        return now - cli.usage_file(account["config_dir"]).stat().st_mtime
    except OSError:
        return None


def stale(config: dict, name: str, pool: Policy | None = None, now: float | None = None) -> float | None:
    """How old an account's reading is when it is past [pool] stale_minutes, too old to place a session by, else
    None."""
    age = reading_age(config, name, now)
    return age if age is not None and age > (pool or policy(config)).stale_minutes * 60 else None


def judge(config: dict, name: str, now: datetime, pool: Policy | None = None) -> tuple[int, tuple, str]:
    """One account's standing for the pick, as (tier, rank, why): tier 0 has room, 1 has no reading, or one older than
    [pool] stale_minutes, which never places a session, 2 is out of room or near it with a reset far off, 3 has no
    folder on this computer. Within tier 0, [pool] order "reset" ranks the soonest weekly reset first, "use it or
    lose it", counting resets in the same hour as a tie, then the most 5-hour room; "listed" leaves the person's
    order alone. A reading's age counts from now on the clock, whatever `now` the windows are judged at."""
    pool = pool or policy(config)
    far = datetime.max.replace(tzinfo=timezone.utc)
    if not Path(config["accounts"][name]["config_dir"]).expanduser().is_dir():
        return 3, (), f"{name}: its folder is not on this computer"
    found = windows(config, name, now)
    if not found:
        return 1, (), f"{name}: no saved reading, so its room is unknown"
    if (old := stale(config, name, pool)) is not None:
        return 1, (), (f"{name}: its last reading is {cli.ago(old)} old, past [pool] stale_minutes "
                       f"({pool.stale_minutes:g}), so its room is unknown and its old numbers are not used")
    five_used, five_reset = found.get("five_hour", (0.0, None))
    week_used, week_reset = found.get("seven_day", (0.0, None))
    five = f"5h {five_used:g}% used, resets in {cli.in_hours(five_reset, now)}"
    if five_used >= pool.out_at:
        return 2, (), f"{name}: out of 5-hour room ({five})"
    if five_used >= pool.near_at and five_reset and (five_reset - now).total_seconds() > pool.near_hours * 3600:
        return 2, (), f"{name}: near its 5-hour limit with the reset far off ({five})"
    if week_used >= pool.out_at:
        return 2, (), (f"{name}: no weekly room left (weekly {week_used:g}% used, resets in "
                       f"{cli.in_hours(week_reset, now)})")
    why = f"{name}: weekly resets in {cli.in_hours(week_reset, now)}, {100 - week_used:g}% left; {five}"
    hour = int((week_reset or far).timestamp() // 3600)  # resets within the same hour tie
    return 0, ((hour, five_used) if pool.order == "reset" else ()), why


def reset_time(config: dict, name: str, now: datetime | None = None) -> float | None:
    """When an account out of room gets it back: the latest reset of its windows at or past [pool] out_at, as Unix
    time, or None when no window is out or none says when it resets."""
    pool = policy(config)
    resets = [reset.timestamp() for used, reset in windows(config, name, now).values()
              if used >= pool.out_at and reset is not None]
    return max(resets) if resets else None


# The right account


def folder_key(path: str) -> str:
    """A settings folder as one comparable string: `~` expanded, links followed, no trailing slash, and on macOS and
    Windows, whose disks ignore case, in one case."""
    found = Path(os.path.expanduser(path))
    try:
        found = found.resolve()
    except OSError:
        pass
    text = str(found).rstrip("/\\") or str(found)
    return text.casefold() if portable.WINDOWS or sys.platform == "darwin" else text


def accounts_in(config: dict, folder: str) -> list[str]:
    """The accounts whose settings folder is `folder`, in the file's order."""
    key = folder_key(folder)
    return [name for name, account in config.get("accounts", {}).items() if folder_key(account["config_dir"]) == key]


def session_folder(config: dict) -> str:
    """The settings folder this Claude Code session really runs in. Its transcript, <folder>/projects/*/<session
    id>.jsonl, lives in that folder whatever the environment says, so the account folder that holds it wins; else
    $CLAUDE_CONFIG_DIR, else the default folder, ~/.claude."""
    session = os.environ.get(cli.CLAUDE_SESSION_ENV, "")
    if cli.CLAUDE_SESSION_ID.fullmatch(session):
        for folder in dict.fromkeys(a["config_dir"] for a in config.get("accounts", {}).values()):
            projects = Path(folder).expanduser() / "projects"
            if projects.is_dir() and next(projects.glob(f"*/{session}.jsonl"), None) is not None:
                return folder
    return os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")


def session_account(config: dict) -> str:
    """The account this session runs on (session_folder). When several accounts share that folder, the one Colony
    opened it on ($COLONY_ACCOUNT) wins, then the one of this session's person, then the first. A folder no account
    names gives its own name, and the default folder "default"."""
    folder = session_folder(config)
    found = accounts_in(config, folder)
    intended = os.environ.get(ACCOUNT_ENV, "")
    if intended in found:
        return intended
    person = os.environ.get(cli.PERSON_ENV, "").lower()
    mine = [name for name in found if str(config["accounts"][name].get("person", "")).lower() == person]
    if mine or found:
        return (mine or found)[0]
    return Path(folder).name if os.environ.get("CLAUDE_CONFIG_DIR") else "default"


def account_line(config: dict, me: str) -> str:
    """A line for the lead when this session runs on another account than the one Colony opened it on, or on an
    account [pool] reserve keeps free that nobody named for it; else ""."""
    actual, intended = session_account(config), os.environ.get(ACCOUNT_ENV, "")
    if intended and intended in config.get("accounts", {}) and actual != intended:
        return (f"urgent: {me} runs on account {actual}, but was opened on {intended}: stop it and open it again on "
                f"{intended}")
    try:
        reserve = policy(config).reserve
    except cli.ColonyError:
        reserve = frozenset()
    if actual in reserve and actual != intended:
        return (f"urgent: {me} runs on account {actual}, which [pool] reserve keeps free: stop it and open it again "
                "on another account")
    return ""


def remember_opened(config: dict, session: str, role: str, account: str, person: str, lead: str) -> None:
    """Note a session Colony opened, by its name: its role, account, person and lead, so a restart after a limit or a
    sleep opens it the same way (restart)."""
    project = config["project"]["name"]
    opened = read(project, "opened")
    opened[session] = {"role": role, "account": account, "person": person, "lead": lead, "at": time.time()}
    wait.write_json(state(project, "opened"), opened)


# Waves: helpers on accounts under their caps, within this computer's room


def short(config: dict, agent: dict) -> str:
    """A running session's Colony name, its title without `<project>-`, in lower case, such as builder-2."""
    return str(agent.get("name", "")).removeprefix(f"{config['project']['name']}-").lower()


def is_lead(name: str) -> bool:
    """Whether a session's name is a lead's: `lead`, or a named lead such as ana-engine-lead."""
    return name == cli.LEAD or name.endswith(f"-{cli.LEAD}")


def busy(config: dict, alive: list | None = None, here: list[dict] | None = None) -> dict[str, set[str]]:
    """Each account's live helpers, by name: the helpers whose status comment names the account, on any computer, and
    this computer's other running Colony sessions that aren't leads, by the folder each runs in."""
    counts: dict[str, set[str]] = {name: set() for name in config["accounts"]}
    statuses = [status for status in alive or [] if status.kind == "helper"]
    for status in statuses:
        if status.account in counts:
            counts[status.account].add(status.name)
    seen = {status.name for status in statuses}
    for agent in cli.running_sessions(config) if here is None else here:
        name = short(config, agent)
        names = accounts_in(config, agent.get("config_dir", ""))
        if name and not is_lead(name) and name not in seen and names:
            counts[names[0]].add(name)
    return counts


def full_accounts(config: dict, counts: dict[str, set[str]], pool: Policy) -> set[str]:
    """The accounts at their cap of busy helpers."""
    return {name for name in config["accounts"] if len(counts.get(name, ())) >= cap(config, name, pool)}


AT_CAP = "every account is at its cap of busy helpers"
NO_FIT = "no account has room for one more helper before its window resets"
SHARED = "it shares the own account of"  # a why's start when a helper or agent shares a live lead's account


def lead_accounts(config: dict, alive: list | None = None) -> dict[str, list[str]]:
    """The accounts a live lead or orchestrator runs on, each with the leads on it: this session's own account when it
    leads, and each live lead's, from its status comment on any computer or its heartbeat on this one. With no
    `alive` given, this computer's heartbeats alone (presence.local)."""
    from colony import presence

    accounts = config.get("accounts", {})
    found: dict[str, list[str]] = {}

    def add(account: str, lead: str) -> None:
        if account in accounts and lead not in found.setdefault(account, []):
            found[account].append(lead)

    me = os.environ.get(cli.SESSION_ENV, "")
    if is_lead(me):
        add(session_account(config), wait.state_name(me))
    if alive is None:
        try:
            alive = presence.local(config)
        except (cli.ColonyError, OSError, ValueError, KeyError):
            alive = []
    for status in alive:
        if status.kind == "lead" and status.account:
            add(status.account, status.name)
    return found


def kept_for_leads(config: dict, person: str, alive: list | None = None) -> dict[str, list[str]]:
    """The live leads' own accounts where a new session keeps the lead room, by the rule place() follows: none with
    [pool] share_lead_accounts, none when the person has one account, else each live lead's (lead_accounts)."""
    order, last = cli.person_accounts(config, person)
    if policy(config).share_lead_accounts or len(dict.fromkeys(order + last)) <= 1:
        return {}
    return lead_accounts(config, alive)


def agent_account(config: dict, args) -> tuple[str, str, str]:
    """The account a headless agent Colony runs for its own work, such as a batch's reviewer, fixer or walker, runs
    on, as (name, config_dir, why): --account when given, else the person's best account with room, a live lead's
    own in its place in the ranking where the lead keeps its room (pick_keeping_lead_room, from this computer's
    heartbeats and this session's own). An agent counts toward no helper's cap. When no account has room, the first
    account no lead runs on, else the plain pick (cli.pick)."""
    if getattr(args, "account", None):
        return cli.choose_account_why(config, args)
    person = cli.person_of(config, args)
    kept = kept_for_leads(config, person)
    found = pick_keeping_lead_room(config, person, kept=kept)
    if found:
        return found
    order, last = cli.person_accounts(config, person)
    rest = [name for name in dict.fromkeys(order + last) if name not in policy(config).reserve and name not in kept]
    if rest:
        return (rest[0], config["accounts"][rest[0]]["config_dir"],
                f"every account is out of room, so {rest[0]}, the first no live lead runs on")
    return cli.pick(config, person)


def pick_keeping_lead_room(config: dict, person: str, skip=(), kept: dict[str, list[str]] | None = None
                           ) -> tuple[str, str, str] | None:
    """The person's best account with room for a headless agent, as (name, config_dir, why), or None: the ranking
    cli.pick_with_room keeps for every account, the soonest weekly reset first, with a live lead's own account
    (`kept`, kept_for_leads by default) in its place there, taken only while the lead and the agent last until each
    window resets with the lead's share of it kept (forecast.fits with lead)."""
    from colony import forecast

    kept = kept_for_leads(config, person) if kept is None else kept
    skip, pool = set(skip), policy(config)
    while (found := cli.pick_with_room(config, person, skip=skip)) is not None:
        name, folder, why = found
        if name not in kept:
            return found
        if forecast.fits(config, name, 1, pool, lead=True)[0]:
            return name, folder, f"{SHARED} {' and '.join(kept[name])}; {why}"
        skip.add(name)
    return None


def lead_cap(config: dict, name: str, pool: Policy) -> int:
    """The most helpers a lead's own account takes when they share it: one fewer than its cap, at least one, so the
    lead keeps room."""
    return max(1, cap(config, name, pool) - 1)


def shared_warning(config: dict, name: str, leads: list[str], pool: Policy) -> str:
    """The one plain line a person and a lead read when helpers open on a lead's own account."""
    from colony import forecast

    return (f"Warning: account {name} is {' and '.join(leads)}'s own, so helpers share it with the lead: at most "
            f"{lead_cap(config, name, pool)} at once, one fewer than its cap, and only while the lead keeps "
            f"{forecast.LEAD_ROOM:g}% of each window until it resets. Put this one in [pool] reserve to keep helpers "
            "off it.")


def refusal(config: dict, names: list[str], full: set[str], leads: dict[str, list[str]], pool: Policy,
            counts: dict[str, set[str]]) -> str:
    """Why no account takes a new helper, when each is at its cap, a lead's own account at its lower cap included,
    or the accounts are all in [pool] reserve."""
    held = [name for name in names if name in leads]
    if not held:
        return AT_CAP
    owners = "; ".join(f"{name} is {' and '.join(leads[name])}'s own and runs {len(counts.get(name, ()))} helpers, the "
                       f"most it takes while its lead shares it ({lead_cap(config, name, pool)})" for name in held)
    others = "every other account is at its cap of busy helpers, and " if len(held) < len(names) else ""
    return f"{others}{owners}: wait for a helper to finish, or add an account with `{cli.NAME} accounts scan`"


def place(config: dict, args, counts: dict[str, set[str]],
          kept: dict[str, list[str]] | None = None) -> tuple[tuple[str, str, str] | None, str]:
    """The account a new helper opens on, as ((name, folder, why), "") or (None, why not). --account wins when given.
    Otherwise the person's pick (cli.pick_with_room) among their accounts under their cap of busy helpers, leaving out
    the ones [pool] reserve keeps free, and taking the first where one more helper lasts until its windows reset
    (forecast.fits). A live lead's or orchestrator's own account (`kept`, lead_accounts by default) takes its place
    in that same ranking, the soonest weekly reset first, under a lower cap (lead_cap) and a fit check that keeps the
    lead room (forecast.fits with lead), and the why starts with SHARED. [pool] share_lead_accounts = true treats it
    as any other. When every account with room would run out before its reset, or every one is out of room, none (NO_FIT):
    the helper waits for the soonest reset, or opens on an account named with --account."""
    if getattr(args, "account", None):
        return cli.choose_account_why(config, args), ""
    from colony import forecast

    pool = policy(config)
    full = full_accounts(config, counts, pool)
    leads = {} if pool.share_lead_accounts else (lead_accounts(config) if kept is None else kept)
    person = cli.person_of(config, args)
    order, last = cli.person_accounts(config, person)
    alone = len(dict.fromkeys(order + last)) == 1  # the person's only account
    names = [name for name in dict.fromkeys(order + last) if name not in pool.reserve]
    usable = [name for name in names if name not in full and name not in leads]
    shared = [name for name in names if name in leads and len(counts.get(name, ())) < lead_cap(config, name, pool)]
    tight: list[str] = []
    skip = set(config["accounts"]) - set(usable) - set(shared)  # one ranking: a lead's own account in its place
    while (found := cli.pick_with_room(config, person, skip=skip)) is not None:
        name, folder, why = found
        here, lead = len(counts.get(name, ())), name in leads
        fit, outlook = forecast.fits(config, name, here + 1, pool, lead=lead)
        if fit:
            most = lead_cap(config, name, pool) if lead else cap(config, name, pool)
            head = f"{SHARED} {' and '.join(leads[name])}; " if lead else ""
            return (name, folder, f"{head}{why}; helpers {here} of {most}" + (f"; {outlook}" if outlook else "")), ""
        tight.append(outlook)
        skip.add(name)
    if tight:
        return None, f"{NO_FIT}: {'; '.join(tight)}"
    now = datetime.now(timezone.utc)
    out = [name for name in usable if judge(config, name, now, pool)[0] == 2]  # known to be out, not just unread
    if usable and not alone and len(out) == len(usable):  # several accounts, each out: wait for the soonest reset
        listed = f"{', '.join(usable[:-1])} and {usable[-1]} are" if len(usable) > 1 else f"{usable[0]} is"
        until = "their windows reset" if len(usable) > 1 else "its window resets"
        return None, f"{NO_FIT}: {listed} out of room until {until}"
    # No account was picked, but not every one is known to be out of room, such as one with no reading, or it is the
    # only account: the first is still named, as cli.pick names it, but never a lead's own account that is out of
    # room, where a helper would only take the lead's window once it resets.
    fallback = usable or [name for name in shared if judge(config, name, now, pool)[0] != 2]
    if not fallback:
        if shared:
            others = "every other account is at its cap of busy helpers, and " if len(shared) < len(names) else ""
            return None, (f"{others}{shared[0]} is {' and '.join(leads[shared[0]])}'s own account and out of room: "
                          f"wait for its reset, or add an account with `{cli.NAME} accounts scan`")
        return None, refusal(config, names, full, leads, pool, counts)
    name = fallback[0]
    here, lead = len(counts.get(name, ())), name in leads
    head = f"{SHARED} {' and '.join(leads[name])}; " if lead else ""
    return (name, config["accounts"][name]["config_dir"], f"{head}every account under its cap is out of room, so "
            f"{name}; helpers {here} of {lead_cap(config, name, pool) if lead else cap(config, name, pool)}"), ""


def helper_account(config: dict, args, counts: dict[str, set[str]],
                   kept: dict[str, list[str]] | None = None) -> tuple[str, str, str] | None:
    """The account a new helper opens on, as (name, folder, why) (place), or None when none takes it."""
    return place(config, args, counts, kept)[0]


def choose_helper_account(config: dict, args) -> None:
    """For `colony open` and `colony join`: put the account a new helper opens on in args.account, with why (place):
    under each account's cap of busy helpers, a live lead's own in its place in the ranking under a cap one lower,
    and where it lasts until the account's reset.
    Refuses, saying why, when no account takes it. A named --account stays as it is."""
    from colony import presence

    if getattr(args, "account", None):
        return
    try:
        alive = presence.everyone(config)[0]
    except (cli.ColonyError, OSError, ValueError, KeyError):
        alive = []
    kept = lead_accounts(config, alive)
    found, why = place(config, args, busy(config, alive), kept)
    if found is None:
        if why == AT_CAP:
            raise cli.ColonyError(f"{AT_CAP} ([pool] max_busy, {policy(config).max_busy} by default): wait for a "
                                  "helper to finish, or name an account with --account")
        raise cli.ColonyError(f"{why}: wait, or name an account with --account")
    args.account, _, args.account_why = found
    if args.account_why.startswith(SHARED):
        print(shared_warning(config, args.account, kept[args.account], policy(config)), flush=True)


def local_helpers(config: dict, here: list[dict]) -> list[str]:
    """This computer's running Colony sessions that aren't leads."""
    return [name for agent in here if (name := short(config, agent)) and not is_lead(name)]


def open_wave(config: dict, args, count: int, taken: set[str]) -> tuple[int, str]:
    """Open up to `count` helpers now, each on an account under its cap, within this computer's room, under names no
    live session and nothing in `taken` holds. Returns how many opened, and why it stopped short, or ""."""
    from colony import presence

    try:
        alive = presence.everyone(config)[0]
    except (cli.ColonyError, OSError, ValueError, KeyError):
        alive = []
    here = cli.running_sessions(config)
    counts = busy(config, alive, here)
    room = limits(config, running=len(local_helpers(config, here)))
    if room["open_now"] <= 0:
        return 0, room_reason(room)
    from colony import forecast

    forecast.record_all(config, counts)  # each fresh reading, with the helpers its account runs now
    kept = lead_accounts(config, alive)
    opened, warned = 0, set()
    lead = getattr(args, "lead_name", "") or os.environ.get(wait.LEAD_ENV, "").lower()
    from colony import boot  # each helper starts with its lead's standing orders, read through profile.py

    orders = boot.helper_brief(config, lead)
    for _ in range(min(count, room["open_now"])):
        found, refused = place(config, args, counts, kept)
        if found is None:
            return opened, refused
        account, _, why = found
        if why.startswith(SHARED) and account not in warned:
            warned.add(account)
            print(shared_warning(config, account, kept[account], policy(config)), flush=True)
        name = cli.free_helper(config, [*alive, *(presence.Status(t, "helper") for t in taken)])
        taken.add(name)
        counts.setdefault(account, set()).add(name)
        if lead and not args.dry_run:
            wait.expect_status(config["project"]["name"], lead, name)
        opening = argparse.Namespace(**{**vars(args), "name": name, "here": False, "account": account,
                                        "account_why": why})
        code = cli.launch(config, opening, name, "builder", cli.builder_prompt(name, config, orders))
        if code:
            raise cli.ColonyError(f"{name} did not open: claude ended with {code}")
        opened += 1
    return opened, "" if opened >= count else room_reason(room)


def room_reason(room: dict) -> str:
    """Why this computer opens no more helpers now."""
    if room["why"]:
        return f"this computer is busy ({'; '.join(room['why'])})"
    return f"this computer runs its most helpers, {room['helpers']}"


def open_helpers(config: dict, args, lead: str) -> int:
    """`colony helpers <n> --open`: open the first wave now, [pool] wave helpers at most, and leave the rest to a
    background run that opens one wave every [pool] wave_seconds (open_later). Every helper opens on an account under
    its cap of busy helpers, where it lasts until the account's reset (place), a live lead's own in its place in the
    ranking under a cap one lower. It
    opens only while this computer has room (limits). Helpers that fit on no account before its reset, or find every
    account out of room, open right after the soonest reset. A dry run prints the plan."""
    pool = policy(config)
    taken: set[str] = set()
    first = min(args.count, pool.wave)
    opened, why = open_wave(config, args, first, taken)
    rest = args.count - opened
    if rest > 0:
        waves = -(-rest // pool.wave)
        plan = (f"{rest} more helper{'s' if rest != 1 else ''} open in {waves} later wave{'s' if waves != 1 else ''}, "
                f"{pool.wave} every {pool.wave_seconds:g} s, each when an account is under its cap and this computer "
                "has room")
        if why:
            print(f"Opened {opened} now: {why}.")
        if args.dry_run:
            print(f"dry run: {plan}.")
        else:
            log = state(config["project"]["name"], "helpers-waves").with_suffix(".log")
            spawn([sys.executable, "-m", cli.NAME, "open-later", str(rest), "--taken", ",".join(sorted(taken)),
                   *(["--person", args.person] if getattr(args, "person", None) else []),
                   *(["--account", args.account] if getattr(args, "account", None) else [])], log)
            print(f"{plan.capitalize()}. The waves log to {log}.")
    if opened and not cli.cmux_usable():
        print(f"They run in the background. To see them in cmux, paste this into any cmux terminal: {cli.NAME} view")
    return 0


def spawn(argv: list[str], log: Path) -> None:
    """Start a Colony command in the background, in its own process group so it outlives this one, writing to `log`."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as out:
        subprocess.Popen(argv, cwd=str(cli.repo_root()), stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                         **portable.own_group())


def open_later(config: dict, args) -> int:
    """`colony open-later <n>`, which `colony helpers --open` starts in the background: open the rest of the helpers,
    one wave every [pool] wave_seconds, each when an account is under its cap and this computer has room. When the
    helpers left fit on no account before its reset, the next wave starts right after the soonest reset
    (forecast.next_reset). After WAVE_PATIENCE with no room, counted from that reset when it waits for one, it gives
    up, and the lead hears how many did not open."""
    from colony import forecast

    pool, left = policy(config), args.count
    taken = {name for name in (args.taken or "").split(",") if name}
    args.dry_run, last, pause = False, time.time(), pool.wave_seconds
    lead = os.environ.get(wait.LEAD_ENV, "").lower() or cli.LEAD
    while left > 0:
        SLEEP(pause)
        pause = pool.wave_seconds
        opened, why = open_wave(config, args, min(left, pool.wave), taken)
        left -= opened
        print(f"{time.strftime('%H:%M:%S')} opened {opened}, {left} left" + (f": {why}" if why and left else ""),
              flush=True)
        if opened:
            last = time.time()
        elif why.startswith(NO_FIT) and (resets := forecast.next_reset(config, cli.person_of(config, args))):
            pause = max(pool.wave_seconds, resets + LIMIT_GRACE - time.time())  # start them right after the reset
            last = max(last, resets + LIMIT_GRACE)
            print(f"{time.strftime('%H:%M:%S')} the next wave waits for the reset at {forecast.clock(resets)}",
                  flush=True)
        elif time.time() - last > WAVE_PATIENCE:
            from colony import guards

            guards.post(config, lead, f"urgent: {left} helper{'s' if left != 1 else ''} did not open in "
                                      f"{WAVE_PATIENCE // 60} minutes: {why}", "open-later")  # a lead skips its own
            return 1
    return 0


# Usage limits: note a session that stopped on one, and wake it once it resets


def limited(config: dict) -> dict[str, dict]:
    """The sessions on this computer that stopped on their account's usage limit, by name, each as {session,
    account, at, resets_at}."""
    held = read(config["project"]["name"], "limited")
    return {name: record for name, record in held.items() if isinstance(record, dict)}


def write_limited(config: dict, records: dict[str, dict]) -> None:
    wait.write_json(state(config["project"]["name"], "limited"), records)


def note_limited(config: dict, me: str, error: str) -> bool:
    """The StopFailure hook's part: when this session's turn ended on a usage limit, note it with its account and
    when that account resets, so it is woken then, and inside a Claude Code session start `colony wake --follow`,
    which wakes it even when no wait on this computer runs. Returns whether it noted one; it never raises."""
    if not me or not LIMIT_ERROR.search(error or ""):
        return False
    me = wait.state_name(me)  # a named lead by its own name, which its wait and its lines go by
    try:
        account = session_account(config)
        resets = reset_time(config, account) if account in config.get("accounts", {}) else None
        records = limited(config)
        records[me] = {"session": os.environ.get(cli.CLAUDE_SESSION_ENV, ""), "account": account, "at": time.time(),
                       "resets_at": resets}
        write_limited(config, records)
        if cli.in_claude_code():
            start_follower(config)
    except (cli.ColonyError, OSError, ValueError, KeyError) as e:
        print(f"{cli.NAME}: the usage limit was not noted for a wake at its reset: {e}", file=sys.stderr)
        return False
    return True


def is_due(config: dict, record: dict, now: float) -> bool:
    """Whether a limited session's account has its room back: its reset time, plus LIMIT_GRACE, has passed and the
    account has room or no reading; with no known reset time, UNKNOWN_RESET_RETRY after the limit once it has room."""
    account = record.get("account")
    if account not in config.get("accounts", {}):
        return now - float(record.get("at") or 0) >= UNKNOWN_RESET_RETRY
    resets = record.get("resets_at")
    if isinstance(resets, (int, float)) and now < resets + LIMIT_GRACE:
        return False
    if not isinstance(resets, (int, float)) and now - float(record.get("at") or 0) < UNKNOWN_RESET_RETRY:
        return False
    return judge(config, account, datetime.fromtimestamp(now, timezone.utc))[0] in (0, 1)


def wait_running(project: str, name: str, now: float | None = None) -> bool:
    """Whether a session's `colony wait` polled within the last two minutes."""
    held = wait.read_json(wait.state_path(project, name), {})
    polled = held.get("polled_at") if isinstance(held, dict) else None
    return isinstance(polled, (int, float)) and (time.time() if now is None else now) - polled < wait.HEARTBEAT_FRESH


def lead_of(config: dict, name: str) -> str:
    """Who signs a wake line for a session: for a helper, the lead it takes lines from, the one Colony noted when it
    opened the helper, else $COLONY_LEAD, else `lead`; for a lead, which skips the lines it signed itself, Colony."""
    if is_lead(name):
        return cli.NAME
    held = read(config["project"]["name"], "opened").get(name, {})
    return (held.get("lead") if isinstance(held, dict) else "") or os.environ.get(wait.LEAD_ENV, "").lower() or cli.LEAD


def account_env(config: dict, folder: str) -> dict[str, str]:
    """This process's environment for a command on an account's folder: CLAUDE_CONFIG_DIR set to it, or left unset for
    the default folder, and no ANTHROPIC_API_KEY unless [budget] use_api_key."""
    keep = config.get("budget", {}).get("use_api_key", False)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR" and (keep or k != "ANTHROPIC_API_KEY")}
    if folder and not cli.is_default_dir(folder):
        env["CLAUDE_CONFIG_DIR"] = folder
    return env


def ledger_entry(config: dict, name: str, agent: dict) -> dict:
    """What recover.reopen opens a stopped session from: the session ledger's entry that holds the Claude Code session
    id `claude agents` listed, else, for a session no hook of this Colony stamped, one made from that listing and what
    Colony noted when it opened the session (remember_opened)."""
    from colony import recover

    claude = str(agent.get("sessionId") or "")
    found = next((entry for entry in recover.read_ledger(config) if claude and entry.get("id") == claude), None)
    if found is not None:
        return found
    opened = read(config["project"]["name"], "opened").get(name, {})
    opened = opened if isinstance(opened, dict) else {}
    return {"name": name, "session": name, "id": claude, "config_dir": agent.get("config_dir") or "",
            "folder": agent.get("cwd") or "", "account": opened.get("account") or "",
            "person": opened.get("person") or "", "lead": opened.get("lead") or ""}


def reopen_session(config: dict, name: str, agent: dict, prompt: str, dry_run: bool = False) -> str:
    """Start a stopped session again under its own id, with `prompt` as its first line, through recover.reopen, the
    one way Colony reopens a session: `claude --resume` on the account that holds its conversation, with its role's
    settings, in the folder it started in, in cmux or the background. Says how, or why not."""
    from colony import recover

    if not cli.SESSION_NAME.fullmatch(name):
        return f"it was not started again: {name!r} is no session's name"
    try:
        failed = recover.reopen(config, ledger_entry(config, name, agent), prompt, dry_run)
    except cli.ColonyError as e:
        return f"it was not started again: {e}"
    if failed:
        return "it was not started again, for the reason above"
    return "would start it again under its own id" if dry_run else "started again under its own id"


def cmux_paste(title: str, prompt: str) -> bool:
    """Type a prompt into the cmux workspace named `title` and submit it. cmux refuses when a draft or a question is
    open there, and so does this. False when there is no such workspace or cmux isn't usable."""
    command = cli.cmux_command()
    if command is None:
        return False
    try:
        listed = subprocess.run([command, "workspace", "list"], capture_output=True, text=True, timeout=10)
        ref = next((m[1] for line in listed.stdout.splitlines()
                    if (m := re.match(r"^\W*(workspace:\S+)\s+(.+?)(\s+\[selected\])?$", line)) and m[2] == title),
                   None)
        return ref is not None and subprocess.run([command, "paste", "--workspace", ref, "--submit", prompt],
                                                  capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def wake(config: dict, name: str, agent: dict | None, prompt: str, dry_run: bool = False) -> str:
    """Wake one session with a prompt, the least forceful way that works, and say how: a line its running wait
    delivers; else, for an idle background helper, `claude stop` and the same conversation opened again with the
    prompt (reopen_session); else,
    for an idle session in cmux, the prompt typed into its window. A busy session and one waiting on a person are left
    alone, a lead is never stopped, and the line says so."""
    project = config["project"]["name"]
    if wait_running(project, name):
        if dry_run:
            return "would send it a line, which its wait delivers"
        from colony import guards

        guards.post(config, name, f"urgent: {prompt}", lead_of(config, name))
        return "sent it a line, which its wait delivers"
    if agent is None:
        return "it runs on no other computer Colony can reach from here"
    state_ = str(agent.get("state") or agent.get("status") or "").lower()
    if state_ not in IDLE:
        return f"it is {state_ or 'running'}, so it is left alone"
    if agent.get("kind") == "background" and agent.get("sessionId") and not is_lead(name):
        if dry_run:
            return reopen_session(config, name, agent, prompt, dry_run=True)
        if agent.get("id") and state_ == "idle":
            from colony import stop

            stop.stop_background(agent)
        return reopen_session(config, name, agent, prompt)
    title = str(agent.get("name") or f"{project}-{name}")
    if dry_run:
        return f"would type the prompt into its cmux window {title}, or ask you to"
    if cmux_paste(title, prompt):
        return "typed the prompt into its cmux window"
    return "it is idle in its own window: type 'carry on' there"


def wake_due(config: dict, now: float | None = None, dry_run: bool = False) -> list[str]:
    """Wake each session on this computer whose usage limit has reset (is_due), and drop its record. Records older
    than LIMITED_KEPT are dropped unwoken. Returns one line per session."""
    now = time.time() if now is None else now
    if not limited(config):
        return []
    path = state(config["project"]["name"], "limited").with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle, portable.lock(handle, block=False) as mine:
        if not mine:
            return []  # another wait or the follower wakes them now
        records = limited(config)
        before = json.dumps(records, sort_keys=True)
        accounts = config.get("accounts", {})
        cli.refresh_usage([accounts[r["account"]]["config_dir"] for r in records.values() if r.get("account") in accounts])
        running = cli.running_sessions(config)
        here = {short(config, agent): agent for agent in running}
        by_id = {agent.get("sessionId"): agent for agent in running if agent.get("sessionId")}
        lines, left = [], {}
        for name, record in records.items():
            if now - float(record.get("at") or 0) > LIMITED_KEPT:
                continue
            if record.get("resets_at") is None and record.get("account") in accounts:
                record["resets_at"] = reset_time(config, record["account"])  # a fresh reading may know it now
            if not is_due(config, record, now):
                left[name] = record
                continue
            agent = by_id.get(record.get("session")) or here.get(name)  # a lead's title differs from its name
            how = wake(config, name, agent, LIMIT_PROMPT.replace("{account}", str(record.get("account"))), dry_run)
            lines.append(f"{name}: account {record.get('account')}'s usage limit reset; {how}")
        if not dry_run and json.dumps(left, sort_keys=True) != before:
            write_limited(config, left)
    return lines


def follower_running(config: dict) -> bool:
    """Whether a `colony wake --follow` holds this project's follower lock on this computer."""
    path = state(config["project"]["name"], "follower").with_suffix(".lock")
    if not path.exists():
        return False
    with open(path, "a") as handle, portable.lock(handle, block=False) as got:
        return not got


def start_follower(config: dict) -> bool:
    """Start `colony wake --follow` in the background when a limit is noted and none runs yet, so a session is woken
    at its reset even after every wait on this computer has ended. Returns whether it started one."""
    if not limited(config) or follower_running(config) or shutil.which("claude") is None:
        return False
    spawn([sys.executable, "-m", cli.NAME, "wake", "--follow"],
          state(config["project"]["name"], "follower").with_suffix(".log"))
    return True


# Sleep: notice it, and start again what stopped


def awake_clock() -> float:
    """Seconds this computer has been awake, a clock that stands still while it sleeps: time.monotonic on macOS and
    Linux, and on Windows, where that clock runs on through sleep, QueryUnbiasedInterruptTime."""
    if portable.WINDOWS:
        try:
            import ctypes

            value = ctypes.c_ulonglong()
            if ctypes.windll.kernel32.QueryUnbiasedInterruptTime(ctypes.byref(value)):
                return value.value / 10_000_000
        except (AttributeError, OSError):
            pass
    return time.monotonic()


def slept(clock: dict, wall: float | None = None, awake: float | None = None, after: float = 300) -> float:
    """Seconds this computer slept since the last call that kept `clock`, at least `after` of them, else 0; -1 when
    the awake clock went back, which a restart of the computer does. It keeps the readings in `clock`."""
    wall = time.time() if wall is None else wall
    awake = awake_clock() if awake is None else awake
    last_wall, last_awake = clock.get("wall"), clock.get("awake")
    clock["wall"], clock["awake"] = wall, awake
    if not isinstance(last_wall, (int, float)) or not isinstance(last_awake, (int, float)):
        return 0.0
    if awake < last_awake:
        return -1.0
    gap = (wall - last_wall) - (awake - last_awake)
    return gap if gap >= after else 0.0


def restart(config: dict, prompt: str = STOPPED_PROMPT, reopen: bool = False, dry_run: bool = False) -> list[str]:
    """Start again the helpers on this computer that stopped: each idle helper whose wait stopped is woken (wake),
    and with `reopen`, after a sleep or a restart of the computer, each background helper Colony saw running before
    (remember_seen) that no longer runs opens again under its own id. Leads and the session that runs this are left
    alone. Returns one line per helper it touched, and keeps what runs now for the next time."""
    project = config["project"]["name"]
    me = os.environ.get(cli.CLAUDE_SESSION_ENV, "")
    here = {short(config, agent): agent for agent in cli.running_sessions(config)
            if not me or agent.get("sessionId") != me}
    seen = read(project, "seen")
    lines = []
    for name, agent in seen.items() if reopen else ():
        if name in here or is_lead(name) or not isinstance(agent, dict):
            continue
        if agent.get("kind") == "background" and agent.get("sessionId"):
            lines.append(f"{name}: no longer ran; {reopen_session(config, name, agent, prompt, dry_run)}")
        else:
            lines.append(f"{name}: its window closed; open it again with `{cli.NAME} open {name}`")
    for name, agent in here.items():
        if is_lead(name) or wait_running(project, name):
            continue
        how = wake(config, name, agent, prompt, dry_run)
        if "left alone" not in how:
            lines.append(f"{name}: its wait had stopped; {how}")
    if not dry_run:
        remember_seen(config, list(here.values()))
    return lines


def forget_seen(config: dict, names: list[str]) -> None:
    """Drop sessions from the note of what runs here, as `colony stop` does for the ones it stops, so a restart
    after a sleep never opens them again."""
    project = config["project"]["name"]
    seen = read(project, "seen")
    if any(name in seen for name in names):
        wait.write_json(state(project, "seen"), {k: v for k, v in seen.items() if k not in names})


def remember_seen(config: dict, here: list[dict] | None = None) -> None:
    """Note which helpers run on this computer now, background ones with their session id, so a restart after a
    sleep knows what stopped."""
    keep = ("id", "sessionId", "kind", "config_dir", "cwd", "name")
    found = cli.running_sessions(config) if here is None else here
    wait.write_json(state(config["project"]["name"], "seen"),
                    {name: {key: agent.get(key) for key in keep} for agent in found
                     if (name := short(config, agent)) and not is_lead(name)})


# Services: a check per service the team relies on


@dataclass
class Service:
    """One service's check: a command and its pass condition, or a built-in account check."""

    name: str
    command: str = ""
    expect: str = ""  # a regular expression the output must match
    at_least: float | None = None  # the output's first number must be at least this, such as requests left
    at_most: float | None = None  # or at most this, such as percent used
    exit: int = 0  # the exit code that passes
    every: float = SERVICE_EVERY  # minutes between checks in the lead's wait
    timeout: float = SERVICE_TIMEOUT
    fix: str = ""  # what the person does when it fails, such as `gh auth login`
    restart: str = ""  # a command that brings a local service back, which Colony's recovery runs; never run here
    account: str = ""  # a built-in check of one account
    part: str = ""  # which: "sign-in", or "room", its usage limits
    in_repo: bool = False  # a team's own check: it runs in the repo's top folder, where its restart runs too


SERVICE_KEYS = ("check", "expect", "at_least", "at_most", "exit", "every_minutes", "timeout", "fix", "restart")


def services_table(config: dict) -> dict:
    table = config.get("services") or {}
    if not isinstance(table, dict):
        raise cli.ColonyError(f"{cli.CONFIG_NAME}: [services] is a table")
    return table


def services(config: dict) -> list[Service]:
    """Every service check: the built-in ones unless [services] builtin = false, a check per account whose folder is
    on this computer and one for GitHub's gh, then the team's own (team_services)."""
    table = services_table(config)
    found = []
    builtin = table.get("builtin", True)
    if not isinstance(builtin, bool):
        raise cli.ColonyError(f"{cli.CONFIG_NAME}: [services] builtin is true or false")
    if builtin:
        for name, account in config.get("accounts", {}).items():
            if Path(account["config_dir"]).expanduser().is_dir():
                found += [Service(f"account {name} sign-in", account=name, part="sign-in", fix=account_fix(name, account)),
                          Service(f"account {name} room", account=name, part="room",
                                  fix="nothing: it resets by itself, and new sessions open on another account meanwhile")]
        found.append(Service("github", "gh auth status", fix="gh auth login"))
    return found + team_services(config)


def team_services(config: dict) -> list[Service]:
    """The team's own checks, one per [services.<name>] table, checked. It is the one services table: `colony
    services` and the lead's wait run these checks, and `colony crash-report` and `colony resume` judge a local
    service by the same check and pass condition and run its `restart` (recover.py)."""
    found = []
    for name, item in services_table(config).items():
        if name == "builtin":
            continue
        where = f"[services.{name}]"
        if not isinstance(item, dict) or not NAME.fullmatch(name):
            raise cli.ColonyError(f"{cli.CONFIG_NAME}: {where} is a table, named in lowercase letters, digits and "
                                  "dashes")
        unknown = sorted(set(item) - set(SERVICE_KEYS))
        if unknown:
            raise cli.ColonyError(f"{cli.CONFIG_NAME}: {where} has no key {unknown[0]!r}: its keys are "
                                  f"{', '.join(SERVICE_KEYS)}")
        if not isinstance(item.get("check"), str) or not item["check"].strip():
            raise cli.ColonyError(f"{cli.CONFIG_NAME}: {where} needs 'check', the command to run")
        if not isinstance(item.get("restart", ""), str):
            raise cli.ColonyError(f"{cli.CONFIG_NAME}: {where} restart is a command")
        expect = item.get("expect", "")
        try:
            re.compile(expect)
        except (re.error, TypeError):
            raise cli.ColonyError(f"{cli.CONFIG_NAME}: {where} expect is a regular expression") from None
        found.append(Service(name, item["check"], expect, number(item, "at_least", None, -1e18, where=where),
                             number(item, "at_most", None, -1e18, where=where),
                             number(item, "exit", 0, 0, 255, whole=True, where=where),
                             number(item, "every_minutes", SERVICE_EVERY, 1, where=where),
                             number(item, "timeout", SERVICE_TIMEOUT, 1, 600, where=where), str(item.get("fix", "")),
                             restart=item.get("restart", ""), in_repo=True))
    return found


def check_folder(service: Service) -> str:
    """Where a check runs: a team's own in the repo's top folder, where its restart runs too, so both read the same
    files, such as a compose file; a built-in one, and any check outside a repo, in the temp folder."""
    if service.in_repo:
        try:
            return str(cli.repo_root())
        except cli.ColonyError:
            pass
    return tempfile.gettempdir()


def account_fix(name: str, account: dict) -> str:
    """How a person signs an account in again: Claude Code's /login on its folder, or the provider's own login."""
    if account.get("provider", "claude") != "claude":
        return f"sign in to account {name} again with its provider's own login"
    folder = account["config_dir"]
    return f"run `{'claude' if cli.is_default_dir(folder) else f'CLAUDE_CONFIG_DIR={folder} claude'}`, then /login"


def check_account(config: dict, service: Service) -> tuple[bool, str]:
    """A built-in account check. Its sign-in: by its auth_command when it has one, else for a Claude Code account by
    `claude auth status --json` on its folder. Its room: by the pick's own judge, under [pool] out_at."""
    account = config["accounts"][service.account]
    if service.part == "room":
        tier, _, why = judge(config, service.account, datetime.now(timezone.utc))
        return (False, why.split(": ", 1)[-1]) if tier == 2 else (True, "")
    command = account.get("auth_command")
    if command:
        ok, why = run_command(Service(service.name, command), account_env(config, account["config_dir"]))
        return (True, "") if ok else (False, f"not signed in: {why}")
    if account.get("provider", "claude") == "claude" and claude_signed_in(config, account["config_dir"]) is False:
        return False, "not signed in"
    return True, ""


def claude_signed_in(config: dict, folder: str) -> bool | None:
    """Whether Claude Code is signed in on a folder, by `claude auth status --json`; by its state file when claude
    can't say; None when neither knows."""
    if shutil.which("claude"):
        try:
            run = subprocess.run([portable.program("claude"), "auth", "status", "--json"], capture_output=True,
                                 text=True, timeout=SERVICE_TIMEOUT, env=account_env(config, folder),
                                 cwd=tempfile.gettempdir())
            data = json.loads(run.stdout)
            if isinstance(data, dict) and isinstance(data.get("loggedIn"), bool):
                return data["loggedIn"]
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return cli.signed_in(folder) if cli.usage_file(folder).exists() else None


FIRST_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def run_command(service: Service, env: dict[str, str] | None = None) -> tuple[bool, str]:
    """Run a service's command and judge it by its pass condition, as (passed, why not). The output is read, never
    printed or kept: a sign-in check can print a token."""
    args, use_shell, env = portable.shell(service.command, env)
    try:
        run = subprocess.run(args, shell=use_shell, env=env, capture_output=True, text=True, timeout=service.timeout,
                             stdin=subprocess.DEVNULL, cwd=check_folder(service))
    except subprocess.TimeoutExpired:
        return False, f"it ran past {service.timeout:g} s"
    except OSError as e:
        return False, f"it could not run ({type(e).__name__})"
    output = f"{run.stdout}\n{run.stderr}"
    if run.returncode != service.exit:
        if run.returncode == 127:  # the shell's code for a command it can't find
            return False, "its command was not found"
        return False, f"it ended with {run.returncode}"
    if service.expect and not re.search(service.expect, output, re.M):
        return False, "its output lacks what `expect` names"
    if service.at_least is not None or service.at_most is not None:
        found = FIRST_NUMBER.search(run.stdout)
        if found is None:
            return False, "its output holds no number"
        value = float(found[0])
        if service.at_least is not None and value < service.at_least:
            return False, f"{value:g} is under {service.at_least:g}"
        if service.at_most is not None and value > service.at_most:
            return False, f"{value:g} is over {service.at_most:g}"
    return True, ""


def run_service(config: dict, service: Service) -> tuple[bool, str]:
    """One service's check, as (passed, why not)."""
    if service.account:
        return check_account(config, service)
    return run_command(service)


def run_services(config: dict, chosen: list[Service]) -> list[tuple[Service, bool, str]]:
    """Run several checks side by side, each within its own timeout."""
    if not chosen:
        return []
    cli.refresh_usage([config["accounts"][s.account]["config_dir"] for s in chosen if s.account])
    with ThreadPoolExecutor(max_workers=min(8, len(chosen))) as pool:
        results = list(pool.map(lambda service: run_service(config, service), chosen))
    return [(service, ok, why) for service, (ok, why) in zip(chosen, results)]


def service_lines(config: dict, held: dict, now: float) -> list[str]:
    """The lead's wait's part: run each service whose check is due, and say when one starts to fail, once a
    stretch, and when it passes again."""
    seen = held.setdefault("services", {})
    due = [s for s in services(config) if now - float((seen.get(s.name) or {}).get("at", 0)) >= s.every * 60]
    lines = []
    for service, ok, why in run_services(config, due):
        was = (seen.get(service.name) or {}).get("ok", True)
        seen[service.name] = {"at": now, "ok": ok}
        if not ok and was:
            fix = f" To fix it: {service.fix}." if service.fix else ""
            lines.append(f"urgent: the check of {service.name} failed: {why}.{fix}")
        elif ok and not was:
            lines.append(f"the check of {service.name} passes again")
    return lines


# This computer: what it has, and what it may run at once


@dataclass
class Machine:
    """This computer as it stands: each reading None when it can't be read."""

    cores: int
    memory_gb: float | None = None
    free_memory_gb: float | None = None
    free_disk_gb: float | None = None
    load: float | None = None  # the 1-minute load average; on Windows, the busy share of the cores times the cores


def cores() -> int:
    """The cores this process may use."""
    if hasattr(os, "process_cpu_count"):
        return os.process_cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0)) or 1
    return os.cpu_count() or 1


def parse_meminfo(text: str) -> tuple[float | None, float | None]:
    """Linux's /proc/meminfo as (total, available) in GB."""
    found = {m[1]: int(m[2]) for m in re.finditer(r"^(\w+):\s+(\d+)\s*kB", text, re.M)}
    total, available = found.get("MemTotal"), found.get("MemAvailable", found.get("MemFree"))
    return (total / 1024 ** 2 if total else None), (available / 1024 ** 2 if available is not None else None)


def parse_vm_stat(text: str) -> float | None:
    """macOS's `vm_stat` as the memory a new program can have in GB: free, inactive and speculative pages."""
    size = re.search(r"page size of (\d+) bytes", text)
    pages = {m[1].lower(): int(m[2]) for m in re.finditer(r"^Pages ([\w ]+?):\s+(\d+)\.", text, re.M)}
    if not size or "free" not in pages:
        return None
    return sum(pages.get(kind, 0) for kind in ("free", "inactive", "speculative")) * int(size[1]) / 1024 ** 3


def read_memory() -> tuple[float | None, float | None]:
    """This computer's memory as (total, available) in GB, or None for what can't be read."""
    if sys.platform.startswith("linux"):
        try:
            return parse_meminfo(Path("/proc/meminfo").read_text())
        except OSError:
            return None, None
    if sys.platform == "darwin":
        total = cli._out([shutil.which("sysctl") or "/usr/sbin/sysctl", "-n", "hw.memsize"])  # often off PATH
        pages = cli._out([shutil.which("vm_stat") or "/usr/bin/vm_stat"])
        return (int(total) / 1024 ** 3 if total.isdigit() else None), parse_vm_stat(pages)
    if portable.WINDOWS:
        try:
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = Status()
            status.dwLength = ctypes.sizeof(Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullTotalPhys / 1024 ** 3, status.ullAvailPhys / 1024 ** 3
        except (AttributeError, OSError):
            pass
    return None, None


def read_load(count: int) -> float | None:
    """The 1-minute load average on macOS and Linux. On Windows, which has none, the share of the cores busy over a
    quarter second, times the cores."""
    if hasattr(os, "getloadavg"):
        try:
            return os.getloadavg()[0]
        except OSError:
            return None
    if portable.WINDOWS:
        try:
            import ctypes

            def times() -> tuple[int, int]:
                idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
                ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
                return idle.value, kernel.value + user.value  # kernel time includes idle time
            idle1, total1 = times()
            time.sleep(0.25)
            idle2, total2 = times()
            spent = total2 - total1
            return (1 - (idle2 - idle1) / spent) * count if spent > 0 else None
        except (AttributeError, OSError):
            return None
    return None


def read_disk(folder: Path) -> float | None:
    """The free disk in GB where `folder` lives, or under the nearest folder above it that exists."""
    for path in (folder, *folder.parents):
        if path.exists():
            try:
                return shutil.disk_usage(path).free / 1024 ** 3
            except OSError:
                return None
    return None


def machine(config: dict) -> Machine:
    """This computer now: its cores, memory, the free disk where worktrees go, and its load."""
    count = cores()
    total, available = read_memory()
    folder = Path(config.get("project", {}).get("worktrees") or Path.home()).expanduser()
    return Machine(count, total, available, read_disk(folder), read_load(count))


MACHINE_KEYS = ("helper_gb", "test_gb", "build_gb", "test_cores", "build_cores", "keep_free_gb", "keep_free_disk_gb",
                "busy_load", "max_helpers", "max_tests", "max_builds")


@dataclass(frozen=True)
class MachinePolicy:
    """[machine]: what one helper, test run and build needs, what is kept free for the person, and the caps."""

    helper_gb: float = 1.0
    test_gb: float = 2.0
    build_gb: float = 2.0
    test_cores: float = 2.0
    build_cores: float = 2.0
    keep_free_gb: float = 2.0
    keep_free_disk_gb: float = 10.0
    busy_load: float = 1.0  # a load per core at or past this is a busy computer
    max_helpers: int = 4  # [project] max_builders when [machine] doesn't say
    max_tests: int | None = None
    max_builds: int | None = None


def machine_policy(config: dict) -> MachinePolicy:
    """[machine] as a MachinePolicy, each key checked."""
    table = config.get("machine") or {}
    if not isinstance(table, dict):
        raise cli.ColonyError(f"{cli.CONFIG_NAME}: [machine] is a table")
    unknown = sorted(set(table) - set(MACHINE_KEYS))
    if unknown:
        raise cli.ColonyError(f"{cli.CONFIG_NAME}: [machine] has no key {unknown[0]!r}: its keys are "
                              f"{', '.join(MACHINE_KEYS)}")
    w = "[machine]"
    default = MachinePolicy()
    helpers = config.get("project", {}).get("max_builders", default.max_helpers)
    from colony import profile  # a profile's machine limits bind too, the stricter of the two

    def limit(key: str, value):
        return profile.stricter(config, f"machine.{key}", value)
    return MachinePolicy(*(number(table, key, getattr(default, key), 0.1, where=w) for key in MACHINE_KEYS[:5]),
                         number(table, "keep_free_gb", default.keep_free_gb, 0, where=w),
                         number(table, "keep_free_disk_gb", default.keep_free_disk_gb, 0, where=w),
                         limit("busy_load", number(table, "busy_load", default.busy_load, 0.1, where=w)),
                         limit("max_helpers", number(table, "max_helpers", helpers, 0, whole=True, where=w)),
                         limit("max_tests", number(table, "max_tests", None, 1, whole=True, where=w)),
                         number(table, "max_builds", None, 1, whole=True, where=w))


def limits(config: dict, found: Machine | None = None, running: int = 0) -> dict:
    """How much this computer runs at once, from what it has and how busy it is now:

    - helpers: the most helper sessions at once, by total memory past keep_free_gb and the cores, at most max_helpers;
    - open_now: how many more may open now, past the `running` ones: none while the computer is busy;
    - tests, builds: runs at once, by the cores not busy now and the memory free now, at least 1, at most their caps.

    It is busy while its load per core is at or past busy_load, its free memory past keep_free_gb is under one
    helper's, or its free disk is under keep_free_disk_gb; `why` says which. A reading that can't be read limits
    nothing."""
    m = found or machine(config)
    p = machine_policy(config)
    load = m.load if m.load is not None else 0.0
    free_cores = max(0.0, m.cores - load)
    room = None if m.free_memory_gb is None else m.free_memory_gb - p.keep_free_gb
    helpers = p.max_helpers
    if m.memory_gb is not None:
        helpers = min(helpers, max(1, int((m.memory_gb - p.keep_free_gb) // p.helper_gb)))
    helpers = min(helpers, max(1, m.cores))

    def runs(per_core: float, per_gb: float, most: int | None) -> int:
        count = int(free_cores // per_core)
        if room is not None:
            count = min(count, int(room // per_gb))
        return max(1, min(count, most) if most else count)

    why = []
    if m.load is not None and load / m.cores >= p.busy_load:
        why.append(f"load {load:.1f} on {m.cores} cores")
    if room is not None and room < p.helper_gb:
        why.append(f"{m.free_memory_gb:.1f} GB memory free")
    if m.free_disk_gb is not None and m.free_disk_gb < p.keep_free_disk_gb:
        why.append(f"{m.free_disk_gb:.1f} GB disk free")
    open_now = 0 if why else max(0, helpers - running)
    if room is not None and not why:
        open_now = min(open_now, int(room // p.helper_gb))
    return {**asdict(m), "helpers": helpers, "open_now": open_now, "running": running,
            "tests": runs(p.test_cores, p.test_gb, p.max_tests), "builds": runs(p.build_cores, p.build_gb, p.max_builds),
            "busy": bool(why), "why": why}


def machine_line(config: dict, held: dict) -> list[str]:
    """The lead's wait's part: one line when this computer turns busy, so the lead opens no more helpers and runs
    fewer tests, and one when it is free again."""
    room = limits(config)
    was = held.get("busy", False)
    held["busy"] = room["busy"]
    if room["busy"] and not was:
        return [f"urgent: this computer is busy ({'; '.join(room['why'])}): open no more helpers here, and run one "
                "test or build at a time until it calms down"]
    if was and not room["busy"]:
        return [f"this computer has room again: {room['open_now']} more helpers, {room['tests']} test runs at once"]
    return []


# Locks: what one run at a time may use


LOCK_POLL = 1.0  # seconds between tries for a held lock
LOCK_WAIT_MINUTES = 30  # how long `colony lock` waits for a slot by default
SLOT_ENV = f"{cli.NAME.upper()}_LOCK_SLOT"  # the slot a locked command holds, 0 up, such as for one database each


def locks_dir() -> Path:
    """Where this computer's named locks live, for every project: ~/.colony/locks. A database or a port is the
    computer's, whichever repo uses it."""
    return Path.home() / f".{cli.NAME}" / "locks"


def slots(config: dict, name: str, given: int | None = None) -> int:
    """How many runs may hold a lock at once: --slots, else [locks.<name>] slots, else this computer's test or build
    runs for a lock named `tests` or `builds` (limits), else 1."""
    if given:
        return given
    table = (config.get("locks") or {}).get(name)
    if isinstance(table, dict) and "slots" in table:
        return number(table, "slots", 1, 1, whole=True, where=f"[locks.{name}]")
    if name in ("tests", "builds"):
        return limits(config)[name]
    return 1


def holders(name: str, folder: Path | None = None) -> list[dict]:
    """Who holds a lock now, one entry per held slot, from each holder's note: a note whose lock nobody holds is
    stale, and goes. `folder` is the locks' folder, locks_dir() by default."""
    found = []
    for note in sorted((folder or locks_dir()).glob(f"{name}.*.json")):
        path = note.with_suffix(".lock")
        if path.exists():
            with open(path, "a") as handle, portable.lock(handle, block=False) as free:
                if free:
                    note.unlink(missing_ok=True)
                    continue
        held = wait.read_json(note, {})
        if isinstance(held, dict):
            found.append(held)
    return found


@contextmanager
def hold(name: str, count: int, minutes: float, note: dict, folder: Path | None = None, stop=None):
    """Hold one of a named lock's `count` slots, waiting up to `minutes` for one, and yield its number. A lock is a
    file per slot under locks_dir(), or `folder`, locked with portable.lock, so a holder that dies frees its slot at
    once. `stop`, when given, is asked between tries, and a true answer ends the wait with a ColonyError."""
    folder = folder or locks_dir()
    folder.mkdir(parents=True, exist_ok=True)
    deadline, said = time.monotonic() + minutes * 60, False
    while True:
        for slot in range(count):
            stack = ExitStack()
            handle = stack.enter_context(open(folder / f"{name}.{slot}.lock", "a"))
            if stack.enter_context(portable.lock(handle, block=False)):
                with stack:
                    wait.write_json(folder / f"{name}.{slot}.json", {**note, "slot": slot, "since": time.time()})
                    try:
                        yield slot
                    finally:
                        (folder / f"{name}.{slot}.json").unlink(missing_ok=True)
                return
            stack.close()
        held = holders(name, folder)
        if stop is not None and stop():
            raise cli.ColonyError(f"asked to stop while it waited for the lock {name}")
        if time.monotonic() >= deadline:
            raise cli.ColonyError(f"the lock {name} stayed held for {minutes:g} minutes, by "
                                  f"{describe_holders(held) or 'a run that left no note'}")
        if not said:
            print(f"{cli.NAME} lock: waiting for {name}, held by {describe_holders(held) or 'another run'}",
                  file=sys.stderr, flush=True)
            said = True
        SLEEP(LOCK_POLL)


@contextmanager
def hold_all(locks, minutes: float, note: dict, folder: Path | None = None, stop=None):
    """Hold one slot of each lock in `locks`, pairs of a name and its slots, and yield {name: slot}. They are taken
    in the order of their names, the same order for every run, so two runs that need the same locks never hold one
    each while they wait for the other. Each waits up to `minutes`, as hold does."""
    with ExitStack() as stack:
        held = {}
        for name, count in sorted((str(name), int(count)) for name, count in locks):
            held[name] = stack.enter_context(hold(name, count, minutes, note, folder, stop))
        yield held


def slot_env(held: dict) -> dict:
    """The environment that names the slot of each lock a run holds: $COLONY_LOCK_SLOT_<NAME>, its name in capitals
    with every other character an underscore, such as COLONY_LOCK_SLOT_TEST_DB=1 for test-db."""
    return {f"{SLOT_ENV}_{re.sub(r'[^A-Z0-9]', '_', name.upper())}": str(slot) for name, slot in held.items()}


def describe_holders(held: list[dict], now: float | None = None) -> str:
    """Each holder of a lock as `<session> (<command>) for <age>`."""
    now = time.time() if now is None else now
    return "; ".join(f"{h.get('session') or 'pid ' + str(h.get('pid'))} ({h.get('command', '')[:60]}) for "
                     f"{cli.ago(max(0.0, now - float(h.get('since') or now)))}" for h in held)


def lock_command(config: dict, args) -> int:
    """`colony lock <name> [--slots N] [--wait MINUTES] -- <command>`: run the command while holding the named lock,
    with its slot in $COLONY_LOCK_SLOT; `colony lock --list` names every held lock and who holds it."""
    if args.list:
        names = sorted({path.name.split(".")[0] for path in locks_dir().glob("*.json")}) if locks_dir().is_dir() else []
        lines = [f"{name}: {describe_holders(found)}" for name in names if (found := holders(name))]
        print("\n".join(lines) or "No lock is held on this computer.")
        return 0
    if not args.name or not NAME.fullmatch(args.name):
        raise cli.ColonyError("name the lock in lowercase letters, digits, dots and dashes, such as test-db: "
                              f"`{cli.NAME} lock test-db -- <command>`")
    command = list(args.argv or [])
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise cli.ColonyError(f"give the command to run under the lock, after --: `{cli.NAME} lock {args.name} -- "
                              "<command>`")
    count = slots(config, args.name, args.slots)
    minutes = LOCK_WAIT_MINUTES if args.wait is None else args.wait
    text = command[0] if len(command) == 1 else shlex.join(command)
    note = {"pid": os.getpid(), "session": os.environ.get(cli.SESSION_ENV, ""), "command": text}
    with hold(args.name, count, minutes, note) as slot:
        env = {**os.environ, SLOT_ENV: str(slot)}
        if len(command) == 1:  # one string: a shell line, such as "pytest -q && npm test"
            run_args, use_shell, env = portable.shell(command[0], env)
            return subprocess.run(run_args, shell=use_shell, env=env).returncode
        return subprocess.run(command, env=env).returncode


# The waits' parts: one callable each, which a wait runs at every poll


def helper_check(config: dict, me: str, lead: str):
    """What a helper's wait runs at each poll: once, a line for its lead when it runs on the wrong account
    (account_line); then every CHECK_EVERY, its own wake line once its usage limit has reset, which ends the wait so
    the session carries on. It starts `colony wake --follow` when a limit is noted, and never raises."""
    def check(waited: dict) -> list[str]:
        try:
            now, held = time.time(), waited.setdefault("capacity", {})
            if held.get("account_for") != os.environ.get(cli.CLAUDE_SESSION_ENV, "once"):
                held["account_for"] = os.environ.get(cli.CLAUDE_SESSION_ENV, "once")
                if line := account_line(config, me):
                    from colony import guards

                    guards.post(config, lead or cli.LEAD, line, me)
            if now - float(held.get("at") or 0) < CHECK_EVERY:
                return []
            held["at"] = now
            records = limited(config)
            record = records.get(me)
            if record is None:
                return []
            start_follower(config)
            if not is_due(config, record, now):
                return []
            records.pop(me, None)
            write_limited(config, records)
            return [LIMIT_PROMPT.replace("{account}", str(record.get("account")))]
        except Exception as e:  # a capacity check never stops a wait
            print(f"{cli.NAME} wait: the capacity check failed: {e}", file=sys.stderr)
            return []
    return check


def lead_check(config: dict, name: str):
    """What the lead's wait runs at each poll. After the computer slept or restarted, it starts again the helpers and
    waits that stopped (restart). Every CHECK_EVERY, after the first: a line when the lead itself runs on the wrong
    account, wakes for the sessions whose usage limit reset (wake_due), the service checks that are due
    (service_lines), a line when this computer turns busy (machine_line), every few minutes a live reading of each
    account with a warning ahead of a reset its helpers would reach first (forecast.lead_part), and, for the digest,
    an account gone from this computer or a new one found (accounts.wait_lines). It never raises."""
    def check(waited: dict) -> list[str]:
        lines: list[str] = []
        try:
            now, held = time.time(), waited.setdefault("capacity", {})
            gap = slept(held.setdefault("clock", {}))
            if gap:
                # the wall clock and the awake clock tick apart by a hair, so the minutes are rounded, not cut
                what = "restarted" if gap < 0 else f"slept for {round(gap / 60)} minutes"
                done = restart(config, SLEPT_PROMPT, reopen=True)
                lines.append(f"urgent: this computer {what}; " + ("; ".join(done) if done else
                                                                  "every helper here still runs its wait"))
            if "at" not in held:  # the first poll: the checks start one interval later, never in a short wait
                held["at"], held["seen_at"] = now, now - SEEN_EVERY + CHECK_EVERY
                return lines
            if now - float(held["at"]) < CHECK_EVERY:
                return lines
            held["at"] = now
            if held.get("account_for") != os.environ.get(cli.CLAUDE_SESSION_ENV, "once"):
                held["account_for"] = os.environ.get(cli.CLAUDE_SESSION_ENV, "once")
                if line := account_line(config, name):
                    lines.append(line)
            if limited(config):
                start_follower(config)
                lines += [f"urgent: {line}" for line in wake_due(config, now)]
            lines += service_lines(config, held, now)
            lines += machine_line(config, held)
            from colony import accounts, forecast  # warnings ahead of a reset; accounts gone, signed out or new

            lines += forecast.lead_part(config, held.setdefault("forecast", {}), now)
            for line in accounts.wait_lines(config, held.setdefault("accounts", {}), now):
                waited.setdefault("pending", []).append([line, False])  # it can wait for the digest
            if now - float(held.get("seen_at") or 0) >= SEEN_EVERY:
                held["seen_at"] = now
                remember_seen(config)
        except Exception as e:  # a capacity check never stops a wait
            print(f"{cli.NAME} wait: the capacity check failed: {e}", file=sys.stderr)
        return lines
    return check


# The commands


def gb(value: float | None) -> str:
    """A size in GB for a line, or "unknown"."""
    return "unknown" if value is None else f"{value:.1f} GB"


def show(config: dict, args) -> int:
    """`colony capacity [--json]`: this computer's readings and what it runs at once, each account's room, with how
    old its reading is, its helpers and its forecast (forecast.summary), the accounts kept for a live lead, the
    sessions waiting for a limit to reset, and the locks held. It takes a live reading first, and keeps it."""
    from colony import presence

    try:
        alive, _, note = presence.everyone(config)
    except (cli.ColonyError, OSError, ValueError, KeyError) as e:
        alive, note = [], f"GitHub was not read, so only this computer's helpers count: {e}"
    here = cli.running_sessions(config)
    room = limits(config, running=len(local_helpers(config, here)))
    pool = policy(config)
    counts = busy(config, alive, here)
    try:
        order, last = cli.person_accounts(config, cli.person_of(config, args))
        names = list(dict.fromkeys([*order, *last]))
    except cli.ColonyError:
        names = list(config["accounts"])
    now = datetime.now(timezone.utc)
    cli.refresh_usage([config["accounts"][name]["config_dir"] for name in names])
    from colony import forecast

    forecast.record_all(config, counts, names)
    kept = {} if pool.share_lead_accounts else lead_accounts(config, alive)
    accounts = [{"name": name, "room": cli.room_text(name, config["accounts"][name]["config_dir"]).split(": ", 1)[1],
                 "standing": judge(config, name, now, pool)[2].split(": ", 1)[1], "helpers": sorted(counts[name]),
                 "max_busy": cap(config, name, pool), "reserved": name in pool.reserve,
                 "kept_for": kept.get(name, []), "read_seconds_ago": reading_age(config, name),
                 "forecast": forecast.summary(config, name)} for name in names]
    waiting = limited(config)
    locked = {path.name.split(".")[0] for path in locks_dir().glob("*.json")} if locks_dir().is_dir() else set()
    held = {name: found for name in sorted(locked) if (found := holders(name))}
    if args.json:
        print(json.dumps({"machine": room, "accounts": accounts, "limited": waiting, "locks": held,
                          "policy": {**asdict(pool), "reserve": sorted(pool.reserve)}}, default=str))
        return 0
    if note:
        print(note, file=sys.stderr)
    load = "unknown" if room["load"] is None else f"{room['load']:.1f}"
    print(f"This computer: {room['cores']} cores, load {load}; memory {gb(room['memory_gb'])}, "
          f"{gb(room['free_memory_gb'])} free; disk {gb(room['free_disk_gb'])} free.")
    print(f"At once: {room['helpers']} helpers ({room['running']} running, {room['open_now']} more now), "
          f"{room['tests']} test runs, {room['builds']} builds.")
    print(f"Busy: {'; '.join(room['why'])}." if room["busy"] else "Busy: no.")
    print(f"Accounts, in the order {'of the soonest weekly reset' if pool.order == 'reset' else 'listed'}:")
    for account in accounts:
        if account["reserved"]:
            print(f"- {account['name']}: reserved, used only with --account. {account['room']}.")
            continue
        kept_for = (f" Shared with {' and '.join(account['kept_for'])}, its own account: helpers open here in its turn, "
                    f"at most {lead_cap(config, account['name'], pool)} at once, and only while the lead keeps its room."
                    if account["kept_for"] else "")
        print(f"- {account['name']}: {account['room']}; helpers {len(account['helpers'])} of {account['max_busy']}"
              + (f" ({', '.join(account['helpers'])})" if account["helpers"] else "") + f". {account['standing']}."
              + kept_for + f" Forecast: {account['forecast']}.")
    for name, record in waiting.items():
        when = record.get("resets_at")
        at = datetime.fromtimestamp(when, timezone.utc).strftime("%a %H:%M UTC") if isinstance(when, (int, float)) \
            else "an unknown time"
        print(f"Waits for a reset: {name} on {record.get('account')}, at {at}.")
    for name, found in held.items():
        print(f"Lock {name}: {describe_holders(found)}.")
    return 0


def check_services(config: dict, args) -> int:
    """`colony services [--json]`: run every service check now, and print each pass or fail with how to fix it.
    Returns 1 when one fails. It prints no command's output, which could hold a token."""
    results = run_services(config, services(config))
    if args.json:
        print(json.dumps([{"name": s.name, "ok": ok, "why": why, "fix": s.fix} for s, ok, why in results]))
    else:
        for service, ok, why in results:
            print(f"pass: {service.name}" if ok else
                  f"fail: {service.name}: {why}." + (f" To fix it: {service.fix}." if service.fix else ""))
    return 1 if any(not ok for _, ok, _ in results) else 0


def wake_command(config: dict, args) -> int:
    """`colony wake [--after-sleep] [--follow] [--dry-run]`: wake the sessions on this computer whose usage limit reset,
    and the idle helpers whose wait stopped; --after-sleep also opens again the background helpers that stopped
    running. --follow keeps doing it every FOLLOW_EVERY seconds, and after a sleep, until no session waits for a reset;
    one runs per project on this computer."""
    if not args.follow:
        prompt = SLEPT_PROMPT if args.after_sleep else STOPPED_PROMPT
        lines = wake_due(config, dry_run=args.dry_run) + restart(config, prompt, args.after_sleep, args.dry_run)
        print("\n".join(lines) or "Nothing to wake: every helper here runs its wait, and no limit waits to reset.")
        return 0
    path = state(config["project"]["name"], "follower").with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle, portable.lock(handle, block=False) as got:
        if not got:
            print(f"Another `{cli.NAME} wake --follow` runs for {config['project']['name']} on this computer.")
            return 0
        clock: dict = {}
        slept(clock)
        while limited(config):
            lines = wake_due(config)
            if slept(clock):
                lines += restart(config, SLEPT_PROMPT, reopen=True)
            for line in lines:
                print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}", flush=True)
            if limited(config):
                SLEEP(FOLLOW_EVERY)
    return 0


def register(sub) -> None:
    """cli.py's route to this module: `capacity`, `services`, `lock`, `wake`, and the helpers' later waves."""
    p = sub.add_parser("capacity", help="this computer's room for helpers, test runs and builds, each account's room "
                                        "and helpers, limits waiting to reset, and locks held")
    p.add_argument("--person", help="whose accounts to list")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(run=show)
    p = sub.add_parser("services", help="check the sign-in and limits of every service the team relies on")
    p.add_argument("--json", action="store_true", help="print one JSON list")
    p.set_defaults(run=check_services)
    p = sub.add_parser("lock", help="run a command while holding a named lock on this computer, such as one test "
                                    "database or one port")
    p.add_argument("name", nargs="?", help="the lock's name, such as test-db; tests and builds take this computer's "
                                           "runs at once as their slots")
    p.add_argument("--slots", type=int, help="how many runs may hold it at once; default [locks.<name>] slots, or 1")
    p.add_argument("--wait", type=float, metavar="MINUTES", help=f"how long to wait for a slot (default "
                                                                 f"{LOCK_WAIT_MINUTES})")
    p.add_argument("--list", action="store_true", help="name every held lock and who holds it")
    p.add_argument("argv", nargs=argparse.REMAINDER, metavar="command", help="the command, after --")
    p.set_defaults(run=lock_command)
    p = sub.add_parser("wake", help="wake the sessions whose usage limit reset, and start again the helpers whose wait "
                                    "or session stopped")
    p.add_argument("--follow", action="store_true", help="keep doing it, and after a sleep, until no limit waits")
    p.add_argument("--after-sleep", action="store_true", help="also open again the background helpers that ran here "
                                                              "before the computer slept and no longer run")
    p.add_argument("--dry-run", action="store_true", help="say what it would do, and do nothing")
    p.set_defaults(run=wake_command)
    p = sub.add_parser("open-later", help="the later waves of `colony helpers <n> --open`, which it starts in the "
                                          "background")
    p.add_argument("count", type=int)
    p.add_argument("--taken", default="")
    p.add_argument("--person")
    p.add_argument("--account")
    p.set_defaults(run=open_later, dry_run=False, here=False)
