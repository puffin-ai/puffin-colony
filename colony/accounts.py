"""Accounts on each computer (docs/capacity.md#finding-accounts).

- `colony accounts` lists every account in the pool: on this computer with its sign-in, its live usage and resets,
  how old that reading is, its helpers and its forecast; on the other computers as their sessions' status comments
  last showed them; and the signed-in settings folders here that no account names yet.
- `colony accounts scan` finds those new folders, where [pool] scan_folders looks, and offers to add each one: in a
  terminal it asks, elsewhere it prints the command, and --add adds them all.
- `colony accounts add <name> --dir <folder>` writes an account into this computer's own layer,
  .colony/colony.local.toml, never the shared .colony/colony.toml: a new account, or this computer's folder for an
  account the team's file already names.
- The startup briefing flags an account of the person's that is missing here or signed out, and a new signed-in
  folder not yet in the pool (briefing_lines). The lead's wait flags each of these once when it starts (wait_lines);
  a sign-in that expires is the service check's to flag, unless `[services] builtin = false`.

Python 3.11+ standard library only.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from colony import capacity, cli, portable

WAIT_EVERY = 10 * 60  # seconds between the lead's wait's looks at the accounts


def short_path(folder) -> str:
    """A folder as a person writes it: under the home folder, with `~`."""
    path, home = Path(os.path.expanduser(str(folder))), Path.home()
    try:
        return "~/" + path.relative_to(home).as_posix() if path != home else "~"
    except ValueError:
        return str(path)


def candidates(config: dict) -> list[Path]:
    """The settings folders on this computer that [pool] scan_folders names, each once."""
    found: dict[str, Path] = {}
    for pattern in capacity.policy(config).scan_folders:
        expanded = os.path.expanduser(pattern)
        paths = sorted(glob.glob(expanded)) if any(mark in expanded for mark in "*?[") else [expanded]
        for path in map(Path, paths):
            if path.is_dir():
                found.setdefault(capacity.folder_key(str(path)), path)
    return list(found.values())


def new_folders(config: dict) -> list[Path]:
    """The signed-in settings folders on this computer that no [accounts.<name>] table names."""
    known = {capacity.folder_key(account["config_dir"]) for account in config.get("accounts", {}).values()}
    return [path for path in candidates(config) if capacity.folder_key(str(path)) not in known
            and cli.signed_in(str(path))]


def suggest(folder: Path, taken: set[str]) -> str:
    """A name for a new account from its folder, such as `work` for ~/.claude-work, that no account holds."""
    stem = re.sub(r"^claude(?=$|[-_.])[-_.]?", "", folder.name.lstrip(".").lower()) or "default"
    stem = re.sub(r"[^a-z0-9._-]+", "-", stem).strip("-._") or "account"
    name, number = stem, 2
    while name in taken:
        name, number = f"{stem}-{number}", number + 1
    return name


def here(config: dict, name: str) -> bool:
    return Path(config["accounts"][name]["config_dir"]).expanduser().is_dir()


def quick_sign_in(config: dict, name: str) -> bool | None:
    """Whether an account on this computer is signed in, from its Claude Code state file alone, which takes no time;
    None for another provider or no state file."""
    account = config["accounts"][name]
    if account.get("provider", "claude") != "claude" or not cli.usage_file(account["config_dir"]).exists():
        return None
    return cli.signed_in(account["config_dir"])


def sign_in(config: dict, name: str) -> bool | None:
    """Whether an account on this computer is signed in: by its auth_command when it has one, else for a Claude Code
    account by `claude auth status` (capacity.claude_signed_in); None when nothing can say."""
    account = config["accounts"][name]
    if account.get("auth_command"):
        return capacity.run_command(capacity.Service(name, account["auth_command"]),
                                    capacity.account_env(config, account["config_dir"]))[0]
    if account.get("provider", "claude") != "claude":
        return None
    return capacity.claude_signed_in(config, account["config_dir"])


# Flags: the briefing's and the lead's wait's


def problems(config: dict, names=None) -> dict[str, list[str]]:
    """What to flag on this computer: accounts, all or `names`, whose folder is missing here; signed out ones; and
    new signed-in folders not in the pool."""
    accounts = config.get("accounts", {})
    names = [name for name in (accounts if names is None else names) if name in accounts]
    missing = [name for name in names if not here(config, name)]
    signed_out = [name for name in names if name not in missing and quick_sign_in(config, name) is False]
    return {"missing": missing, "signed_out": signed_out, "new": [short_path(path) for path in new_folders(config)]}


def briefing_lines(config: dict, names=None) -> list[str]:
    """The briefing's line on the accounts to look at, or none when every one is here and signed in and no new
    folder waits."""
    found, parts = problems(config, names), []
    if found["signed_out"]:
        parts.append(f"signed out here: {', '.join(found['signed_out'])}, so no helper opens on "
                     f"{'it' if len(found['signed_out']) == 1 else 'them'} (`{cli.NAME} services` says how to sign in)")
    if found["missing"]:
        parts.append(f"missing on this computer: {', '.join(found['missing'])} (when one is in another folder here, "
                     f"`{cli.NAME} accounts add <name> --dir <folder>`)")
    if found["new"]:
        parts.append(f"new and signed in, not in the pool: {', '.join(found['new'])} (`{cli.NAME} accounts scan` offers "
                     "to add each)")
    return [f"Accounts to look at: {'; '.join(parts)}."] if parts else []


def wait_lines(config: dict, held: dict, now: float | None = None) -> list[str]:
    """The lead's wait's part, every WAIT_EVERY: a line for each account whose folder left this computer, each new
    signed-in folder not in the pool, and, when `[services] builtin = false` turns the sign-in checks off, each
    account that signed out, once each. The first look only notes what it finds: the briefing named it."""
    now = time.time() if now is None else now
    if now - float(held.get("at") or 0) < WAIT_EVERY:
        return []
    first = "at" not in held
    held["at"] = now
    found = problems(config)
    present = [name for name in config.get("accounts", {}) if name not in found["missing"]]
    before = {key: set(held.get(key) or []) for key in ("present", "signed_out", "new")}
    held.update(present=present, signed_out=found["signed_out"], new=found["new"])
    if first:
        return []
    lines = [f"account {name}'s folder is no longer on this computer, so no helper opens on it here: "
             f"`{cli.NAME} accounts` shows the pool" for name in found["missing"] if name in before["present"]]
    services = config.get("services") if isinstance(config.get("services"), dict) else {}
    if services.get("builtin", True) is False:
        lines += [f"account {name} is signed out on this computer: "
                  f"{capacity.account_fix(name, config['accounts'][name])}"
                  for name in found["signed_out"] if name not in before["signed_out"]]
    lines += [f"a new signed-in settings folder is on this computer, {path}, in no [accounts.<name>] table: "
              f"`{cli.NAME} accounts scan` offers to add it to the pool" for path in found["new"]
              if path not in before["new"]]
    return lines


# colony accounts


def standing(config: dict, name: str, counts: dict, pool: capacity.Policy, signed: bool | None) -> dict:
    """One account on this computer, for `colony accounts`."""
    from colony import forecast

    account = config["accounts"][name]
    return {"name": name, "person": account.get("person", ""), "here": True, "signed_in": signed,
            "room": cli.room_text(name, account["config_dir"]).split(": ", 1)[1],
            "read_seconds_ago": capacity.reading_age(config, name), "helpers": sorted(counts.get(name, ())),
            "max_busy": capacity.cap(config, name, pool), "reserved": name in pool.reserve,
            "forecast": forecast.summary(config, name)}


def list_accounts(config: dict, args) -> int:
    """`colony accounts [--json]`: every account in the pool on each computer, and the new folders here."""
    from colony import forecast, presence

    pool = capacity.policy(config)
    try:
        alive, _, note = presence.everyone(config)
    except (cli.ColonyError, OSError, ValueError, KeyError) as e:
        alive, note = [], f"GitHub was not read, so only this computer's accounts show: {e}"
    names = list(config["accounts"])
    present = [name for name in names if here(config, name)]
    cli.refresh_usage([config["accounts"][name]["config_dir"] for name in present])
    counts = capacity.busy(config, alive)
    forecast.record_all(config, counts, present)
    with ThreadPoolExecutor(max_workers=max(1, min(8, len(present)))) as threads:
        signed = dict(zip(present, threads.map(lambda name: sign_in(config, name), present)))
    rows = [standing(config, name, counts, pool, signed[name]) if name in present else
            {"name": name, "person": config["accounts"][name].get("person", ""), "here": False,
             "folder": short_path(config["accounts"][name]["config_dir"])} for name in names]
    computer = presence.computer()
    elsewhere: dict[str, dict] = {}
    for status in sorted(alive, key=lambda s: -s.at):
        if status.computer and status.computer != computer and status.room and status.computer not in elsewhere:
            elsewhere[status.computer] = {"at": status.at, "room": status.room}
    new = [short_path(path) for path in new_folders(config)]
    if args.json:
        print(json.dumps({"computer": computer, "accounts": rows, "elsewhere": elsewhere, "new": new}, default=str))
        return 0
    if note:
        print(note, file=sys.stderr)
    print(f"Accounts on this computer, {computer}, read live:")
    for row in rows:
        account = config["accounts"][row["name"]]
        if not row["here"]:
            print(f"- {row['name']} ({row['person']}): not on this computer, its folder {row['folder']} is missing "
                  f"here. When it is in another folder here: `{cli.NAME} accounts add {row['name']} --dir <folder>`.")
            continue
        state = {True: "signed in", False: f"signed out: {capacity.account_fix(row['name'], account)}",
                 None: "sign-in unknown"}[row["signed_in"]]
        kept = " Reserved: used only with --account." if row["reserved"] else ""
        print(f"- {row['name']} ({row['person']}): {state}. {row['room']}. Helpers {len(row['helpers'])} of "
              f"{row['max_busy']}.{kept} Forecast: {row['forecast']}.")
    if elsewhere:
        print("On other computers, as their sessions' status comments last showed them:")
        for where, seen in elsewhere.items():
            print(f"- {where}, {cli.ago(max(0.0, time.time() - seen['at']))} ago: {'; '.join(seen['room'])}.")
    if new:
        print(f"New here, signed in, in no [accounts.<name>] table: {', '.join(new)}. `{cli.NAME} accounts scan` offers "
              "to add each.")
    return 0


def scan(config: dict, args) -> int:
    """`colony accounts scan [--add] [--person P] [--json]`: the signed-in settings folders on this computer that no
    account names, each offered as a new account of the person's, in this computer's own layer."""
    found = new_folders(config)
    person = getattr(args, "person", None) or cli.person_of(config, args)
    taken, offers = set(config["accounts"]), []
    for folder in found:
        name = suggest(folder, taken)
        taken.add(name)
        offers.append({"name": name, "folder": short_path(folder), "person": person})
    if getattr(args, "json", False):
        print(json.dumps(offers))
        return 0
    if not offers:
        print(f"No new signed-in settings folder on this computer: every one [pool] scan_folders finds is in the pool "
              f"({', '.join(capacity.policy(config).scan_folders)}).")
        return 0
    ask = not args.add and portable.is_terminal(sys.stdin)
    for offer in offers:
        command = f"{cli.NAME} accounts add {offer['name']} --dir {offer['folder']} --person {person}"
        yes = args.add
        if ask:
            answer = input(f"Add {offer['folder']}, signed in, as account {offer['name']} for {person}, in this "
                           f"computer's {cli.DIR}/colony.local.toml? [y/N] ")
            yes = answer.strip().lower() in ("y", "yes")
        if yes:
            print(write_account(config, offer["name"], offer["folder"], person))
        else:
            print(f"- {offer['folder']}, signed in, in no [accounts.<name>] table: to add it, `{command}`")
    return 0


def local_file() -> Path:
    """This computer's own layer: the main checkout's .colony/colony.local.toml, which counts in every worktree."""
    from colony import configs, folders

    root = folders.main_checkout(cli.config_path().parent) or cli.repo_root()
    return configs.make_local(root)


def write_account(config: dict, name: str, folder: str, person: str = "", max_busy: int | None = None) -> str:
    """Write [accounts.<name>] into this computer's own layer: its folder, and its person for a new account. The
    file keeps its comments when the table is new there. The config must still load, or nothing changes."""
    from colony import configs

    if not capacity.NAME.fullmatch(name):
        raise cli.ColonyError(f"an account's name is lowercase letters, digits, dots and dashes, such as work, not "
                              f"{name!r}")
    path = Path(os.path.expanduser(folder))
    if not path.is_dir():
        raise cli.ColonyError(f"{folder} is not a folder on this computer")
    table: dict = {"config_dir": short_path(path)}
    if person or name not in config["accounts"]:
        table["person"] = person or cli.person_of(config, argparse.Namespace(person=None))
    if max_busy is not None:
        table["max_busy"] = max_busy
    target = local_file()
    before = target.read_text()
    current = configs.read(target)
    if name in (current.get("accounts") or {}):
        text = configs.dump(cli.merge_tables(current, {"accounts": {name: table}}), configs.LOCAL_HEADER)
    else:
        body = "\n".join(f"{configs.key_text(key)} = {configs.value_text(value)}" for key, value in table.items())
        text = f"{before.rstrip()}\n\n[accounts.{configs.key_text(name)}]\n{body}\n"
    target.write_text(text)
    try:
        loaded = cli.load_config()
    except cli.ColonyError as e:
        target.write_text(before)
        raise cli.ColonyError(f"account {name} was not added, since the config would not load with it: {e}") from None
    what = "this computer's folder for" if name in config["accounts"] else "the new account"
    lines = [f"Wrote {what} {name}, {short_path(path)}, into {cli.DIR}/colony.local.toml, which git never tracks."]
    who = loaded["accounts"][name]["person"]
    listed = (loaded.get("people", {}).get(who) or {}).get("accounts") if isinstance(loaded.get("people"), dict) else None
    if isinstance(listed, list) and listed and name not in listed:
        lines.append(f"[people.{who}] accounts lists that person's accounts by name, without {name}: add it there for "
                     "sessions to use it.")
    if not cli.signed_in(str(path)):
        lines.append(f"It is not signed in yet: {capacity.account_fix(name, loaded['accounts'][name])}.")
    return " ".join(lines)


def add(config: dict, args) -> int:
    """`colony accounts add <name> --dir <folder> [--person P] [--max-busy N]`."""
    print(write_account(config, args.name, args.dir, getattr(args, "person", None) or "", args.max_busy))
    return 0


def accounts_command(config: dict, args) -> int:
    if args.action == "scan":
        return scan(config, args)
    if args.action == "add":
        return add(config, args)
    return list_accounts(config, args)


def register(sub) -> None:
    """cli.py's route to this module: `accounts`, `accounts scan` and `accounts add`."""
    p = sub.add_parser("accounts", help="every account in the pool on each computer: sign-in, live usage, resets and "
                                        "forecast; scan finds signed-in folders here that the pool lacks")
    p.add_argument("--person", help="whose accounts a scan adds, when $COLONY_PERSON is not set")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(run=accounts_command, action=None, add=False, max_busy=None)
    actions = p.add_subparsers(dest="action", metavar="action")
    a = actions.add_parser("scan", help="find signed-in settings folders on this computer that no account names, and "
                                        "offer to add each in this computer's own config layer")
    a.add_argument("--add", action="store_true", help="add every one found, without asking")
    a.add_argument("--person", default=argparse.SUPPRESS, help="whose accounts they become")
    a.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the offers as JSON")
    a = actions.add_parser("add", help="write an account, or this computer's folder for one, into "
                                       ".colony/colony.local.toml")
    a.add_argument("name", help="the account's name, such as work")
    a.add_argument("--dir", required=True, metavar="FOLDER", help="its settings folder on this computer")
    a.add_argument("--person", default=argparse.SUPPRESS, help="whose account it is; needed for a new one, else yours")
    a.add_argument("--max-busy", type=int, help="the most helpers it runs at once, instead of [pool] max_busy")
