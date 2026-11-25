"""One wait per session, and `colony waits`: the computer's list of waits, and stopping one by its exact process id.

Each `colony wait` writes ~/.colony/<project>/waits/<pid>.json while it runs: its session, its listener token, when
it started and whether it follows. A new wait for a session stops the older one at once (replace): only after it
checks, by the process's own command line, that the process id still belongs to a `colony wait`, so a reused id is
never touched. `colony waits` lists every wait on the computer, the leftovers among them, and the colony waits no list
names, such as one from an older Colony; `--stop <pid>` stops one, and `--stop-leftovers` stops this project's
leftovers, each by its exact process id. Nothing here ever stops a process by a name pattern.

On Windows a process's command line isn't read, so a new wait leaves the older one to stop at its next poll, as it
always did, and `colony waits` lists without stopping.
"""
from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from pathlib import Path, PurePath

from colony import cli, portable

STOP_SECONDS = 3.0  # how long a stop waits for the process to end
GLOBAL_VALUES = ("--person", "--account")  # colony's options before the command that take a value


def folder(project: str) -> Path:
    """~/.colony/<project>/waits: one file per running wait."""
    from colony import wait

    return wait.state_path(project, "waits").with_suffix("")


def register(project: str, name: str, token: str, follow: bool) -> None:
    """Put this wait on the computer's list."""
    from colony import wait

    entry = {"pid": os.getpid(), "session": name, "token": token, "started": time.time(), "follow": follow}
    try:
        wait.write_json(folder(project) / f"{os.getpid()}.json", entry)
    except OSError:
        pass  # the list is for people to read: a wait runs without it


def forget(project: str) -> None:
    """Take this wait off the list, as it ends."""
    try:
        (folder(project) / f"{os.getpid()}.json").unlink(missing_ok=True)
    except OSError:
        pass


def alive(pid: int) -> bool:
    """Whether a process runs: it exists and hasn't ended as a zombie its parent hasn't collected yet. Never asked
    on Windows, where os.kill would end it."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    try:
        run = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return True
    return not run.stdout.strip().startswith("Z")


def command_of(pid: int) -> str | None:
    """A process's command line, or None when it isn't running or can't be read, as on Windows."""
    if portable.WINDOWS:
        return None
    try:
        run = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return (run.stdout.strip() or None) if run.returncode == 0 else None


def is_wait(command: str) -> bool:
    """Whether a command line is a `colony wait`: a `colony` program, or `-m colony`, whose command is `wait`."""
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    for at, word in enumerate(words):
        name = PurePath(word).name.lower().removesuffix(".exe")
        if name not in (cli.NAME, f"puffin-{cli.NAME}") and not (word == cli.NAME and at and words[at - 1] == "-m"):
            continue
        rest = words[at + 1:]
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in GLOBAL_VALUES else rest[1:]
        return bool(rest) and rest[0] == "wait"
    return False


def ours(pid) -> bool:
    """Whether a process id may be stopped: a real one, not this process or its parent, running a colony wait."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 or pid in (os.getpid(), os.getppid()):
        return False
    command = command_of(pid)
    return command is not None and is_wait(command)


def stop(pid: int, seconds: float = STOP_SECONDS) -> bool:
    """Send one colony wait a terminate signal, which it ends on cleanly, and say whether it ended in `seconds`."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return not alive(pid)


def replace(project: str, pid, name: str) -> bool:
    """Stop the older wait for session `name`, by its exact process id, once it is checked to be a colony wait.
    Returns whether it stopped one; when it can't check, the older wait stops at its next poll."""
    if portable.WINDOWS or not ours(pid):
        return False
    return stop(pid)


def listed(project: str) -> list[dict]:
    """The waits on this computer's list for `project`, each with `state`: listening, a leftover, or gone. A gone
    one's file is removed."""
    from colony import wait

    found = []
    for path in sorted(folder(project).glob("*.json")) if folder(project).is_dir() else []:
        entry = wait.read_json(path, None)
        if not isinstance(entry, dict) or not isinstance(entry.get("pid"), int):
            continue
        if not portable.WINDOWS and not alive(entry["pid"]):
            path.unlink(missing_ok=True)
            continue
        held = wait.read_json(wait.state_path(project, f"{entry.get('session')}-listener"), None)
        listening = isinstance(held, dict) and held.get("token") == entry.get("token")
        found.append({**entry, "state": "listening" if listening else "leftover",
                      "listener": held.get("pid") if isinstance(held, dict) else None})
    return found


def unlisted(known: set[int]) -> list[tuple[int, str]]:
    """The colony waits running on this computer that no list names, such as one from an older Colony or another
    project, by `ps`. None on Windows."""
    if portable.WINDOWS:
        return []
    try:
        run = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for row in run.stdout.splitlines():
        pid, _, command = row.strip().partition(" ")
        if pid.isdigit() and int(pid) not in known | {os.getpid(), os.getppid()} and is_wait(command.strip()):
            found.append((int(pid), command.strip()))
    return found


def describe(entry: dict, now: float) -> str:
    since = cli.ago(max(0.0, now - float(entry.get("started", now))))
    how = ", following" if entry.get("follow") else ""
    if entry["state"] == "listening":
        return f"- {entry['pid']}: {entry.get('session')}, listening{how}, for {since}"
    return (f"- {entry['pid']}: {entry.get('session')}, a leftover{how}, for {since}: "
            f"{entry.get('listener') or 'another wait'} listens for {entry.get('session')}")


def run(config: dict, args) -> int:
    """`colony waits [--stop PID ...] [--stop-leftovers]`: list this computer's waits, or stop some by exact id."""
    project = config["project"]["name"]
    entries = listed(project)
    if args.stop or args.stop_leftovers:
        if portable.WINDOWS:
            raise cli.ColonyError("colony waits lists the waits on Windows, and stops none: a wait there stops at its "
                                  "next poll once a newer one starts")
        targets = list(dict.fromkeys(args.stop or []))
        if args.stop_leftovers:
            targets += [entry["pid"] for entry in entries if entry["state"] == "leftover" and entry["pid"] not in targets]
        code = 0
        for pid in targets:
            if not ours(pid):
                print(f"{pid}: not a colony wait on this computer, so left alone")
                code = 1
            elif stop(pid):
                print(f"{pid}: stopped")
            else:
                print(f"{pid}: still runs after {STOP_SECONDS:g} seconds")
                code = 1
        if not targets:
            print("No leftover waits to stop.")
        return code
    now = time.time()
    print(f"Waits for {project} on this computer:" if entries else f"No waits for {project} on this computer.")
    for entry in entries:
        print(describe(entry, now))
    others = unlisted({entry["pid"] for entry in entries})
    if others:
        print("Colony waits no list names, from an older Colony or another project:")
        for pid, command in others:
            print(f"- {pid}: {command[:120]}")
    if any(entry["state"] == "leftover" for entry in entries) or others:
        print(f"Stop one by its id with `{cli.NAME} waits --stop <pid>`, or this project's leftovers with "
              f"`{cli.NAME} waits --stop-leftovers`.")
    return 0


def pid_value(value: str) -> int:
    import argparse

    if not value.isdigit() or int(value) <= 0:
        raise argparse.ArgumentTypeError(f"{value!r} is not a process id, such as 4321")
    return int(value)


def add_commands(sub) -> None:
    """`colony waits`."""
    p = sub.add_parser("waits", help="list this computer's colony waits and the leftovers, or stop one by its exact "
                                     "process id")
    p.add_argument("--stop", nargs="+", type=pid_value, metavar="PID",
                   help="stop these colony waits, each by its exact process id, after checking it is one")
    p.add_argument("--stop-leftovers", action="store_true",
                   help="stop this project's leftover waits: each one a newer wait for its session replaced")
    p.set_defaults(run=run)
