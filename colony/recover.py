"""After a crash or a stop: which sessions were alive, why each stopped, and bringing them back.

The session ledger. Each Colony session on this computer keeps one file, ~/.colony/<project>/sessions/<name>.json,
which its own hooks write (note_session): its Claude Code session id, the folder it started in, its transcript, its
account, person and lead, and when it last showed life. The SessionStart, UserPromptSubmit and Stop hooks stamp it,
the StopFailure hook adds the error's code word (note_error), the SessionEnd hook the reason Claude Code gives
(note_end), and `colony stop` that it stopped the session on purpose (note_stopped). A ledger file holds Colony's own
fields alone, never a prompt, a command or a token.

Background tasks. A long colony command a session runs in the background, such as `colony wait` or `colony batch`,
keeps a file, ~/.colony/<project>/tasks/<pid>.json, while it runs (tracked), and removes it when it ends, on an error
too. A file whose process is gone means something stopped the task from outside: the agent tool, a kill or a crash.
At the end of the owning session's next turn, the Stop hook tells it once to start the task again (task_note).

`colony crash-report` says, for each session seen in the last `[recover] within_hours`, whether it runs, stopped on
purpose, or stopped unexpectedly, when it last showed life and from what, and the likely cause: the computer started
again, a kill by pattern on some session's line just before, many sessions stopping at once, a usage limit or another
API error, a signal, or a tool call in flight. It also lists the stopped background tasks and each service in
`[services.<name>]` whose check fails.

`colony resume` reopens every session that stopped unexpectedly, each with `claude --resume <id>` on its own account
and its role's settings, in the folder it started in, in cmux or the background, with a first line that says it was
restarted, when and why. Then it runs the restart command of each service whose check fails.
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from colony import cli, portable, wait

LEDGER, TASKS = "sessions", "tasks"  # folders in ~/.colony/<project>/
TRACKED = ("wait", "batch", "fast-check", "merge", "retro")  # the commands that keep a task file while they run
WITHIN_HOURS = 24  # how far back the report and resume look, [recover] within_hours
TOGETHER = 90  # seconds: sessions whose last signs of life lie this close stopped in one event
KILL_BEFORE, KILL_AFTER = 120, 30  # seconds around a session's last sign of life in which a kill counts as its cause
LIVE = 180  # seconds: when `claude agents` can't say, a sign of life this recent counts as running
TAIL_BYTES = 256 * 1024  # the end of a transcript read for its last entries
CHECK_TIMEOUT, RESTART_TIMEOUT = 30, 300  # seconds a service's check and restart command may take
WORD = re.compile(r"[a-z_]{1,40}")  # an error's code word, such as rate_limit
ENDED = ("ended", "reason", "stopped", "stopped_by", "error", "error_at", "resumed")  # facts of one stop
ON_PURPOSE = {"clear": "its conversation was cleared", "logout": "its person logged out",
              "prompt_input_exit": "its person exited it"}  # SessionEnd reasons a person chose
RUNNING, PURPOSE, UNEXPECTED = "running", "stopped on purpose", "stopped unexpectedly"


def project_of(config: dict) -> str:
    return config["project"]["name"]


def folder(project: str, name: str) -> Path:
    """One of Colony's folders for a project on this computer, such as ~/.colony/<project>/sessions."""
    return wait.state_path(project, name).with_suffix("")


def when(at: float) -> str:
    """A time as people read it in a report, such as 2026-11-24 14:02 UTC."""
    return datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def stamp(text: str) -> float:
    """An ISO time from a transcript, such as 2026-11-08T10:03:00.123Z, as Unix time; 0 when it can't be read."""
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def number(value) -> float:
    """A time from a ledger or task file, or 0.0 when it isn't a finite number."""
    from colony import presence

    return presence.clean_number(value)


def short(value, limit: int = 1000) -> str:
    """A field from a hook's event as text, or "" when it isn't a short string."""
    return value if isinstance(value, str) and len(value) <= limit and "\n" not in value else ""


# The session ledger


def session_name() -> str:
    """This session's name in the ledger: a named lead's name, else $COLONY_SESSION, or "" outside a Colony session
    or for a name that isn't a session's, which never becomes a file name."""
    me = os.environ.get(cli.SESSION_ENV, "").lower()
    name = wait.state_name(me) if me else ""
    return name if cli.SESSION_NAME.fullmatch(name) else ""


def ledger_path(project: str, name: str) -> Path:
    return folder(project, LEDGER) / f"{name}.json"


def read_ledger(config: dict) -> list[dict]:
    """Every session the ledger holds on this computer."""
    found = []
    path = folder(project_of(config), LEDGER)
    for file in sorted(path.glob("*.json")) if path.is_dir() else []:
        entry = wait.read_json(file, None)
        if isinstance(entry, dict) and cli.SESSION_NAME.fullmatch(str(entry.get("name", ""))):
            found.append(entry)
    return found


def update(project: str, name: str, change) -> None:
    """Change one session's ledger file under its lock, so two hooks never lose each other's write."""
    path = ledger_path(project, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "a") as handle, portable.lock(handle):
        entry = wait.read_json(path, {})
        entry = entry if isinstance(entry, dict) else {}
        change(entry)
        wait.write_json(path, entry)


def note_session(config: dict, event: dict, kind: str, now: float | None = None) -> None:
    """Stamp this session's ledger file from a hook's event. `kind` is "start" for SessionStart, which also records
    the folder the session started in and clears the facts of its last stop, "prompt" for UserPromptSubmit, or
    "turn" for Stop. A new Claude Code session id under the same name starts the file afresh."""
    name = session_name()
    if not name:
        return
    now = time.time() if now is None else now
    claude = short(event.get("session_id"), 100) or os.environ.get(cli.CLAUDE_SESSION_ENV, "")
    claude = claude if cli.CLAUDE_SESSION_ID.fullmatch(claude) else ""
    transcript, cwd = short(event.get("transcript_path")), short(event.get("cwd"))
    from colony import presence

    def change(entry: dict) -> None:
        if claude and entry.get("id") != claude:
            entry.clear()
            entry.update(id=claude, started=now)
        if kind == "start":
            for key in ENDED:
                entry.pop(key, None)
        if cwd and (kind == "start" or not entry.get("folder")) and Path(cwd).is_dir():
            entry["folder"] = cwd
        if transcript.endswith(".jsonl"):
            entry["transcript"] = transcript
        entry.update(name=name, session=os.environ.get(cli.SESSION_ENV, "").lower(),
                     lead=os.environ.get(wait.LEAD_ENV, "").lower(), person=os.environ.get(cli.PERSON_ENV, ""),
                     account=cli.current_account(config), config_dir=os.environ.get("CLAUDE_CONFIG_DIR", ""),
                     computer=presence.computer(), seen=now)
    update(project_of(config), name, change)


def note_end(config: dict, event: dict, now: float | None = None) -> None:
    """The SessionEnd hook's fact: when this session ended, and Claude Code's reason as one code word."""
    name = session_name()
    if not name:
        return
    reason = short(event.get("reason"), 40)
    reason = reason if WORD.fullmatch(reason) else "other"
    at = time.time() if now is None else now
    update(project_of(config), name, lambda entry: entry.update(ended=at, reason=reason, seen=at))


def note_error(config: dict, code: str, now: float | None = None) -> None:
    """The StopFailure hook's fact: this session's turn ended on an error, named by its code word alone."""
    name = session_name()
    if name:
        at = time.time() if now is None else now
        update(project_of(config), name, lambda entry: entry.update(error=code, error_at=at))


def note_stopped(config: dict, agent: dict, by: str, now: float | None = None) -> None:
    """`colony stop` stopped this session on purpose, so `colony resume` leaves it be. The ledger file is the one
    holding the agent's Claude Code session id, else the one named like the agent, without the project's prefix."""
    project = project_of(config)
    claude = str(agent.get("sessionId") or "")
    named = str(agent.get("name") or "").lower().removeprefix(f"{project}-")
    entries = read_ledger(config)
    name = next((entry["name"] for entry in entries if claude and entry.get("id") == claude), "") or \
        next((entry["name"] for entry in entries if entry["name"] == named), "")
    if name:
        at = time.time() if now is None else now
        update(project, name, lambda entry: entry.update(stopped=at, stopped_by=by or "a person"))


# Background tasks


def task_label(args) -> str:
    """A tracked command as a person reads it, such as `colony batch --name 2026-11-24`."""
    name = getattr(args, "name", "") if args.command in ("batch", "retro") else ""
    detail = f"--name {name}" if name else " ".join(getattr(args, "branch", None) or []) if args.command == "merge" \
        else ""
    return " ".join(filter(None, [cli.NAME, args.command, detail]))


@contextlib.contextmanager
def tracked(config: dict, args):
    """Keep a task file while a long colony command runs, removed when it ends, on an error too. A process that is
    killed, or a computer that stops, leaves its file behind, which shows the task stopped from outside."""
    if getattr(args, "command", None) not in TRACKED or getattr(args, "dry_run", False):
        yield
        return
    path: Path | None = folder(project_of(config), TASKS) / f"{os.getpid()}.json"
    try:
        wait.write_json(path, {"pid": os.getpid(), "command": args.command, "label": task_label(args),
                               "session": session_name(), "claude": os.environ.get(cli.CLAUDE_SESSION_ENV, ""),
                               "started": time.time()})
    except OSError:
        path = None  # a task that can't be recorded still runs
    try:
        yield
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def alive(pid) -> bool:
    """Whether a process with this id runs on this computer."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if portable.WINDOWS:
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True  # another user's process holds the id
    except OSError:
        return False
    return True


def tasks(config: dict) -> list[dict]:
    """Every task file on this computer for the project, each with its `path`."""
    found = []
    path = folder(project_of(config), TASKS)
    for file in sorted(path.glob("*.json")) if path.is_dir() else []:
        task = wait.read_json(file, None)
        if isinstance(task, dict) and isinstance(task.get("pid"), int):
            found.append({**task, "path": str(file)})
    return found


def stopped_tasks(config: dict) -> list[dict]:
    """The tasks whose process is gone without removing its file: stopped from outside."""
    return [task for task in tasks(config) if not alive(task["pid"])]


def owned(task: dict, name: str, claude: str) -> bool:
    """Whether a task belongs to a session, by its Claude Code session id, else by its ledger name."""
    return bool(claude and task.get("claude") == claude) or (not task.get("claude") and task.get("session") == name)


def forget(stopped: list[dict]) -> None:
    for task in stopped:
        Path(task["path"]).unlink(missing_ok=True)


def restart_line(task: dict) -> str:
    """What a session does about one of its tasks that stopped."""
    label, started = task.get("label") or f"{cli.NAME} {task.get('command')}", when(number(task.get("started")))
    head = f"Your background `{label}`, started {started}, stopped without finishing: something ended its process, " \
           "such as the agent tool, a kill or a crash."
    if task.get("command") == "wait":
        return f"{head} Start it again now with run_in_background, so lines reach you."
    if task.get("command") in ("batch", "retro"):
        name = label.rsplit(" ", 1)[-1]
        return f"{head} Run `{cli.NAME} status --name {name}` to see where it stopped, then start it again."
    return f"{head} Start it again if it should still run."


def task_note(config: dict, event: dict) -> str:
    """The Stop hook's note for this session: one line per background task of its that stopped from outside, which
    it then forgets, so each shows once. A stopped task whose command the session already runs again, such as a wait
    it replaced, needs no line. Empty when none did, or when this turn already follows a Stop hook's note."""
    if event.get("stop_hook_active"):
        return ""
    name, claude = session_name(), os.environ.get(cli.CLAUDE_SESSION_ENV, "")
    if not name:
        return ""
    mine = [task for task in tasks(config) if owned(task, name, claude)]
    running = {task.get("command") for task in mine if alive(task["pid"])}
    stopped = [task for task in mine if not alive(task["pid"])]
    forget(stopped)
    return " ".join(restart_line(task) for task in stopped if task.get("command") not in running)


# The crash report


@functools.lru_cache(maxsize=1)
def guard():
    """The wait guard script as a module, for its kill guard (kills), which reads a Bash command line."""
    path = str(resources.files("colony").joinpath("hooks", "wait_guard.py"))
    spec = importlib.util.spec_from_file_location("colony_wait_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def transcript_facts(path: str) -> dict:
    """What the end of a transcript says: when its last entry was written (`at`, and the file's `mtime`), the code
    words of an API error that ended it (`error`), the tool call it waited on (`calling`), and its Bash calls as
    (time, command) (`calls`). {} when there is no transcript."""
    file = Path(path) if path else None
    if file is None or not file.is_file():
        return {}
    try:
        size = file.stat().st_size
        with open(file, "rb") as held:
            held.seek(max(0, size - TAIL_BYTES))
            lines = held.read().decode("utf-8", "replace").splitlines()
        facts: dict = {"mtime": file.stat().st_mtime, "calls": []}
    except OSError:
        return {}
    last = None
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") not in ("user", "assistant") or entry.get("isSidechain"):
            continue
        last = entry
        content = (entry.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash":
                command = (block.get("input") or {}).get("command")
                if isinstance(command, str):
                    facts["calls"].append((stamp(entry.get("timestamp", "")), command))
    if last is None:
        return facts
    facts["at"] = stamp(last.get("timestamp", ""))
    if last.get("isApiErrorMessage"):
        facts["error"] = [code for code in (last.get("error"), last.get("apiError")) if WORD.fullmatch(str(code or ""))]
    content = (last.get("message") or {}).get("content")
    block = content[-1] if isinstance(content, list) and content else {}
    if last["type"] == "assistant" and isinstance(block, dict) and block.get("type") == "tool_use":
        facts["calling"] = str(block.get("name") or "a tool")
    return facts


def listed_ids(config: dict) -> set[str] | None:
    """The Claude Code session ids `claude agents --json` lists on this computer for each account folder, whatever
    their names, or None when claude can't list them."""
    if shutil.which("claude") is None:
        return None
    found: set[str] = set()
    answered = False
    for config_dir in dict.fromkeys(account["config_dir"] for account in config["accounts"].values()):
        if not Path(config_dir).expanduser().is_dir():
            continue
        env = {key: value for key, value in os.environ.items() if key != "CLAUDE_CONFIG_DIR"}
        if not cli.is_default_dir(config_dir):
            env["CLAUDE_CONFIG_DIR"] = config_dir
        try:
            run = subprocess.run([portable.program("claude"), "agents", "--json"], capture_output=True, text=True,
                                 env=env, timeout=30)
            listed = json.loads(run.stdout) if run.returncode == 0 else None
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
        if isinstance(listed, list):
            answered = True
            found |= {str(agent.get("sessionId")) for agent in listed if isinstance(agent, dict)}
    return found if answered else None


def boot_time() -> float | None:
    """When this computer last started, as Unix time, or None when it can't say."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5).stdout
            found = re.search(r"sec\s*=\s*(\d+)", out)
            return float(found[1]) if found else None
        if sys.platform.startswith("linux"):
            for line in Path("/proc/stat").read_text().splitlines():
                if line.startswith("btime "):
                    return float(line.split()[1])
            return None
        if portable.WINDOWS:
            import ctypes

            ticks = ctypes.windll.kernel32.GetTickCount64
            ticks.restype = ctypes.c_ulonglong
            return time.time() - ticks() / 1000
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return None
    return None


@dataclass
class Seen:
    """One session as the report sees it."""

    entry: dict
    last: float  # its last sign of life
    source: str  # what showed it
    state: str = UNEXPECTED
    cause: str = ""
    clues: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.entry["name"]


def last_life(config: dict, entry: dict, facts: dict) -> tuple[float, str]:
    """A session's last sign of life and what showed it: a hook, its transcript, its colony wait, or its heartbeat."""
    project, name = project_of(config), entry["name"]
    signs = [(number(entry.get("seen")), "a hook"), (number(facts.get("at")), "its transcript"),
             (number(facts.get("mtime")), "its transcript")]
    with contextlib.suppress(OSError):
        signs.append((wait.state_path(project, name).stat().st_mtime, "its colony wait"))
    if entry.get("session") == cli.LEAD:
        beat = wait.read_heartbeat(project, name if entry.get("lead") else "")
        signs.append((float(beat["at"]) if beat else 0.0, "its heartbeat"))
    return max(signs, key=lambda sign: sign[0])


def error_words(codes: list[str]) -> str:
    """An API error's code words as a cause."""
    words = ", ".join(codes) or "an unnamed error"
    if any("limit" in code for code in codes):
        return f"its account hit a usage limit ({words})"
    if any(part in code for code in codes for part in ("auth", "oauth", "login")):
        return f"its sign-in failed ({words})"
    return f"its last turn ended on an API error ({words})"


def kill_events(seens: list[Seen]) -> list[tuple[float, str, str]]:
    """Every kill by name or pattern in the sessions' transcripts, as (time, session, the command or a note in its
    place when it looks like a secret)."""
    from colony import transport

    found = []
    for seen in seens:
        for at, command in seen.facts.get("calls", []):
            if at and guard().kills(command):
                line = " ".join(command.split())
                shown = f"`{line[:100]}`" if not transport.holds_secret(line) else "a command"
                found.append((at, seen.name, shown))
    return found


def infer(seens: list[Seen], boot: float | None) -> None:
    """Fill in each unexpected stop's likely cause and its other clues."""
    kills = kill_events(seens)
    groups: list[list[Seen]] = []
    for seen in sorted((s for s in seens if s.state == UNEXPECTED), key=lambda s: s.last):
        if groups and seen.last - groups[-1][-1].last <= TOGETHER:
            groups[-1].append(seen)
        else:
            groups.append([seen])
    for group in groups:
        for seen in group:
            clues = []
            if boot and boot > seen.last:
                clues.append(f"the computer started again at {when(boot)}, after its last sign of life")
            clues += [f"{name} ran {shown} at {when(at)}, a kill by name or pattern, just before"
                      for at, name, shown in kills if seen.last - KILL_BEFORE <= at <= seen.last + KILL_AFTER]
            others = [s.name for s in group if s is not seen]
            if others:
                clues.append(f"it stopped within {TOGETHER} seconds of {', '.join(others)}, so one event stopped them "
                             "all, such as a kill of many processes, the terminal app closing, or a crash")
            if "error" in seen.facts:
                clues.append(error_words(seen.facts["error"]))
            if seen.entry.get("error"):
                clues.append(f"its last turn ended on an error ({seen.entry['error']}) at "
                             f"{when(number(seen.entry.get('error_at')))}")
            if seen.entry.get("ended"):
                clues.append(f"Claude Code ended it at {when(number(seen.entry['ended']))} with no exit by its person "
                             f"({seen.entry.get('reason')}), as a signal or a closed window does")
            if seen.facts.get("calling"):
                clues.append(f"it stopped during a {seen.facts['calling']} call, which may have ended it")
            seen.cause = clues[0] if clues else "unknown: nothing on this computer recorded why"
            seen.clues = clues[1:]


def within(config: dict, args) -> float:
    """How far back to look, in hours: --within, else [recover] within_hours, else WITHIN_HOURS."""
    hours = getattr(args, "within", None) or config.get("recover", {}).get("within_hours", WITHIN_HOURS)
    try:
        return float(hours)
    except (TypeError, ValueError):
        raise cli.ColonyError(f"[recover] within_hours is a number of hours, not {hours!r}") from None


def survey(config: dict, hours: float, now: float | None = None) -> list[Seen]:
    """Every session the ledger saw in the last `hours`, with its state, last sign of life and likely cause."""
    now = time.time() if now is None else now
    ids = listed_ids(config)
    seens = []
    for entry in read_ledger(config):
        facts = transcript_facts(entry.get("transcript", ""))
        last, source = last_life(config, entry, facts)
        running = entry.get("id") in ids if ids is not None else now - last < LIVE
        if not running and now - last > hours * 3600:
            continue
        seen = Seen(entry, last, source, facts=facts)
        if running:
            seen.state, seen.cause = RUNNING, "it runs"
        elif entry.get("stopped"):
            seen.state = PURPOSE
            seen.cause = f"`{cli.NAME} stop` by {entry.get('stopped_by')} at {when(number(entry['stopped']))}"
        elif entry.get("reason") in ON_PURPOSE:
            seen.state, seen.cause = PURPOSE, ON_PURPOSE[entry["reason"]]
        seens.append(seen)
    infer(seens, boot_time())
    return seens


@dataclass
class Service:
    """One of the [services.<name>] tables: a local service, its check and the command that starts it again."""

    name: str
    check: str
    restart: str = ""


def services(config: dict) -> list[Service]:
    """The [services.<name>] tables, each with a `check` and an optional `restart`. A key of [services] that is no
    table, such as a switch another command reads, is left out, and so are a table's other keys."""
    found = []
    for name, item in (config.get("services") or {}).items():
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("check"), str):
            raise cli.ColonyError(f'[services.{name}] needs a check, a command that exits 0 while the service is up, '
                                  'such as check = "pg_isready -h localhost"')
        found.append(Service(str(name), item["check"], str(item.get("restart") or "")))
    return found


def run_command(command: str, timeout: float) -> bool:
    """Whether a service's command, run through the repo's shell in the repo's folder, passed within its time."""
    argv, shell, env = portable.shell(command, None)
    try:
        return subprocess.run(argv, shell=shell, env=env, cwd=cli.repo_root(), capture_output=True,
                              timeout=timeout).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def report_lines(config: dict, hours: float, seens: list[Seen], stopped: list[dict], down: list[Service]) -> list[str]:
    """The crash report as lines."""
    lines = [f"{cli.NAME} crash-report: this computer, the last {hours:g} hours (now {when(time.time())})"]
    groups = {state: [s for s in seens if s.state == state] for state in (UNEXPECTED, PURPOSE, RUNNING)}
    if not seens:
        lines.append(f"No {cli.DISPLAY} session showed life here in that time.")
    if groups[UNEXPECTED]:
        lines.append(f"Stopped unexpectedly ({len(groups[UNEXPECTED])}), which `{cli.NAME} resume` reopens:")
        for seen in sorted(groups[UNEXPECTED], key=lambda s: s.last):
            entry = seen.entry
            who = f" (helper of {entry['lead']})" if entry.get("lead") and entry.get("session") != cli.LEAD else ""
            lines.append(f"- {seen.name}{who}, account {entry.get('account') or 'unknown'}: last sign of life "
                         f"{when(seen.last)}, from {seen.source}. Likely cause: {seen.cause}."
                         + (f" Also: {'; '.join(seen.clues)}." if seen.clues else ""))
    if groups[PURPOSE]:
        lines.append(f"Stopped on purpose ({len(groups[PURPOSE])}):")
        lines += [f"- {seen.name}: {seen.cause}." for seen in groups[PURPOSE]]
    if groups[RUNNING]:
        lines.append(f"Running ({len(groups[RUNNING])}): {', '.join(sorted(s.name for s in groups[RUNNING]))}.")
    if stopped:
        lines.append(f"Background tasks that stopped without finishing ({len(stopped)}):")
        lines += [f"- {task.get('session') or 'a session'}'s `{task.get('label') or task.get('command')}`, started "
                  f"{when(number(task.get('started')))}" for task in stopped]
    if down:
        lines.append(f"Services whose check fails ({len(down)}):")
        lines += [f"- {service.name}: `{service.check}` failed; " + (f"`{cli.NAME} resume` runs `{service.restart}`"
                  if service.restart else "it has no restart command, so start it by hand") for service in down]
    return lines


def crash_report(config: dict, args) -> int:
    """`colony crash-report [--within H] [--json]`: see the module's docstring."""
    hours = within(config, args)
    seens = survey(config, hours)
    stopped = stopped_tasks(config)
    down = [service for service in services(config) if not run_command(service.check, CHECK_TIMEOUT)]
    if args.json:
        print(json.dumps({"sessions": [{"name": s.name, "state": s.state, "last": s.last, "source": s.source,
                                        "cause": s.cause, "clues": s.clues, "account": s.entry.get("account", ""),
                                        "id": s.entry.get("id", "")} for s in seens],
                          "tasks": [{key: task.get(key) for key in ("session", "label", "started", "pid")}
                                    for task in stopped],
                          "services": [service.name for service in down]}, indent=2))
        return 0
    print("\n".join(report_lines(config, hours, seens, stopped, down)))
    return 0


# colony resume


def role_of(session: str) -> str:
    """The [roles] entry a session opens with: lead, researcher, spec or tester by its name, else builder."""
    return session if session in (cli.LEAD, cli.RESEARCHER, cli.SPEC, cli.TESTER) else "builder"


def account_of(config: dict, entry: dict) -> str:
    """The account a session ran on, which its conversation lives under: the ledger's name, else the account whose
    folder it ran with, else ""."""
    accounts = config["accounts"]
    if entry.get("account") in accounts:
        return entry["account"]
    folder_ = entry.get("config_dir") or ""
    for name, account in accounts.items():
        if (not folder_ and cli.is_default_dir(account["config_dir"])) or (
                folder_ and Path(account["config_dir"]).expanduser() == Path(folder_).expanduser()):
            return name
    return ""


def slug(path: str) -> str:
    """The name Claude Code gives a folder's transcripts folder, such as -Users-ana-myapp for /Users/ana/myapp."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def start_folder(entry: dict) -> str:
    """The folder to reopen a session in, the one it started in, so `claude --resume` finds its conversation: the
    ledger's folder, else the repo's top, whichever its transcript's folder is named after."""
    candidates = [candidate for candidate in (entry.get("folder"), str(cli.repo_root())) if candidate]
    transcript = Path(entry.get("transcript") or "")
    for candidate in candidates:
        if Path(candidate).is_dir() and transcript.parent.name == slug(str(Path(candidate).resolve())):
            return candidate
    return next((candidate for candidate in candidates if Path(candidate).is_dir()), "")


def restart_note(seen: Seen, stopped: list[dict]) -> str:
    """The first line a reopened session reads: it stopped, when and why, and what to start again."""
    why = f"stopped unexpectedly after {when(seen.last)}, likely because" if seen.state == UNEXPECTED else \
        f"stopped after {when(seen.last)}:"
    note = (f"{cli.DISPLAY} reopened this session with `{cli.NAME} resume`: it {why} {seen.cause}. Your conversation "
            "is as it was.")
    if seen.entry.get("session") == cli.LEAD:
        note += (f" Start your `{cli.NAME} wait` again with run_in_background, which takes your lead's heartbeat back, "
                 f"run `{cli.NAME} crash-report` to see what else stopped, and carry on where you left off.")
    else:
        note += (f" Start your `{cli.NAME} wait` again with run_in_background, check your worktree with `git status`, "
                 "and carry on with your card.")
    return " ".join([note, *(restart_line(task) for task in stopped if task.get("command") != "wait")])


def reopen(config: dict, entry: dict, note: str, dry_run: bool = False) -> int:
    """Open one session from its ledger entry again: `claude --resume <its id>` on the account that holds its
    conversation, with its role's settings, in the folder it started in, in cmux or the background (never this
    terminal), with `note` as its first line. The ledger notes that it was reopened. Returns 1 when it wasn't, saying
    why on stderr. `colony resume` and any other recovery, such as a wake after a usage limit, open sessions through it."""
    name = entry.get("name") or ""
    account = account_of(config, entry)
    if not entry.get("id"):
        print(f"kept {name}: the ledger holds no Claude Code session id to resume it by", file=sys.stderr)
        return 1
    if not account:
        print(f"kept {name}: its settings folder, {entry.get('config_dir') or '~/.claude'}, is no account in "
              f"{cli.CONFIG_NAME}, and only that account holds its conversation", file=sys.stderr)
        return 1
    session = entry.get("session") or name
    opened = argparse.Namespace(account=account, person=entry.get("person") or None, lead_name=entry.get("lead", ""),
                                resume=entry["id"], background=True, here=False, name=session, dry_run=dry_run)
    start, before = start_folder(entry), os.getcwd()
    try:
        if start:
            os.chdir(start)  # launch opens the session at the repo's top here, as it first opened
        code = cli.launch(config, opened, session, role_of(session), note)
    except cli.ColonyError as e:
        print(f"kept {name}: {e}", file=sys.stderr)
        code = 1
    finally:
        os.chdir(before)
    if code:
        return 1
    if not dry_run and name:
        update(project_of(config), name, lambda held: held.update(resumed=time.time()))
    return 0


def resume(config: dict, args) -> int:
    """`colony resume [<name> ...] [--within H] [--dry-run]`: see the module's docstring. Returns 1 when a session or
    a service didn't come back."""
    from colony import transport

    project, hours = project_of(config), within(config, args)
    seens = survey(config, hours)
    me = os.environ.get(cli.CLAUDE_SESSION_ENV, "")
    names = {name.strip().lower().removeprefix(f"{project}-") for name in args.names or []}
    if names:
        missing = names - {seen.name for seen in seens}
        if missing:
            raise cli.ColonyError(f"no session named {', '.join(sorted(missing))} showed life here in the last "
                                  f"{hours:g} hours: `{cli.NAME} crash-report` lists them")
        chosen = [seen for seen in seens if seen.name in names]
        for seen in chosen:
            if seen.state == RUNNING:
                print(f"kept {seen.name}: it runs")
        chosen = [seen for seen in chosen if seen.state != RUNNING]
    else:
        chosen = [seen for seen in seens if seen.state == UNEXPECTED
                  and number(seen.entry.get("resumed")) <= seen.last]
    failed = 0
    for seen in chosen:
        if not seen.entry.get("id"):
            print(f"kept {seen.name}: the ledger holds no Claude Code session id to resume it by", file=sys.stderr)
            failed += 1
    chosen = sorted((seen for seen in chosen if seen.entry.get("id") and seen.entry.get("id") != me),
                    key=lambda seen: (seen.entry.get("session") != cli.LEAD, seen.name))
    stopped = stopped_tasks(config)
    if not chosen and not failed:
        print(f"No session to reopen: none stopped unexpectedly here in the last {hours:g} hours.")
    for seen in chosen:
        mine = [task for task in stopped if owned(task, seen.name, seen.entry.get("id", ""))]
        note = restart_note(seen, mine)
        if transport.holds_secret(note):
            note = restart_note(Seen(seen.entry, seen.last, seen.source, seen.state,
                                     "of something this note leaves out"), mine)
        if reopen(config, seen.entry, note, args.dry_run):
            failed += 1
        elif not args.dry_run:
            forget(mine)
    for service in services(config):
        if run_command(service.check, CHECK_TIMEOUT):
            continue
        if not service.restart:
            print(f"{service.name}: its check `{service.check}` fails, and it has no restart command: start it by hand")
            failed += 1
        elif args.dry_run:
            print(f"dry run: {service.name} fails its check, so `{service.restart}` would start it again")
        elif run_command(service.restart, RESTART_TIMEOUT) and run_command(service.check, CHECK_TIMEOUT):
            print(f"{service.name}: started again with `{service.restart}`, and its check passes")
        else:
            print(f"{service.name}: `{service.restart}` ran, and its check `{service.check}` still fails", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


def register(sub) -> None:
    """cli.py's route to this module: `crash-report` and `resume`."""
    p = sub.add_parser("crash-report", help="which sessions on this computer stopped, when each last showed life, the "
                                            "likely cause, and the background tasks and services that stopped")
    p.add_argument("--within", type=float, metavar="HOURS", help=f"how far back to look; [recover] within_hours, "
                                                                 f"{WITHIN_HOURS} by default")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(run=crash_report)
    p = sub.add_parser("resume", help="reopen every session on this computer that stopped unexpectedly, with its "
                                      "conversation, account and settings, and restart failed services")
    p.add_argument("names", nargs="*", metavar="name", help="only these sessions, such as builder-2")
    p.add_argument("--within", type=float, metavar="HOURS", help=f"how far back to look; [recover] within_hours, "
                                                                 f"{WITHIN_HOURS} by default")
    p.add_argument("--dry-run", action="store_true", help="print each command and the env names, and run nothing")
    p.set_defaults(run=resume)
