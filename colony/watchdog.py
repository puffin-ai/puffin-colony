"""The watchdog: one process per project on each computer that keeps watching when every session has stopped, such as
an orchestrator or a lead stopped by its usage limit.

It runs apart from every Claude Code session, in its own process group, so a session that stops, hits its limit or
closes leaves it running. Three things start it: the lead's wait, when `[watch] watchdog` is on and none runs on its
computer (ensure); `colony watchdog start`; and, after `colony watchdog install`, the computer itself, at login and
again whenever it ends (launchd on macOS, a systemd user unit on Linux).

Each pass, every `[watch] every_minutes`, it:

1. starts again the waits that stopped: a session on this computer whose pulse (watch.write_pulse) went stale while
   the session sits idle is woken with a prompt to start its wait again (capacity.wake), unless it said it is done or
   waits for its usage limit;
2. names each background task something stopped from outside (recover.stopped_tasks, the task files recover.tracked
   keeps) to its idle session, with the line its own Stop hook would give it (recover.restart_line);
3. when no lead's wait runs on this computer, does that wait's part: wakes the sessions whose usage limit reset
   (capacity.wake_due), and after a sleep starts again what stopped (capacity.restart);
4. mentions a lead's person on GitHub, whose phone hears it, when the lead has sat idle, with no helper busy and no
   reason given or its reason past due, for `[watch] escalate_minutes` past `idle_minutes`. Its transcript says when
   it last moved, and its own wait's last look says which of its helpers, on any computer, are busy;
5. keeps the status page current (statuspage.keep).

Its heartbeat, ~/.colony/<project>/watchdog.json, holds its process id and its last pass; a file lock makes one run per
project on each computer. `colony watchdog stop` ends it by that exact process id. Started without --stay, it ends
after `[watch] quit_hours` with no session alive on this computer.
"""
from __future__ import annotations

import os
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from colony import cli, portable, wait

SLEEP = time.sleep  # tests pass a fake
RUN = subprocess.run  # what install and uninstall run launchctl and systemctl with; tests pass a fake
ENSURE_EVERY = 5 * 60  # the lead's wait tries to start a watchdog at most this often


def path(project: str, name: str = "watchdog") -> Path:
    return wait.state_path(project, name)


def lock_path(project: str) -> Path:
    return path(project).with_suffix(".lock")


def log_path(project: str) -> Path:
    return path(project).with_suffix(".log")


def running(config: dict) -> dict | None:
    """The watchdog that runs for this project on this computer, as its heartbeat says, or None: one runs when its
    lock is held."""
    project = config["project"]["name"]
    lock = lock_path(project)
    if not lock.exists():
        return None
    with open(lock, "a") as handle, portable.lock(handle, block=False) as got:
        if got:
            return None
    held = wait.read_json(path(project), {})
    return held if isinstance(held, dict) else {}


def command() -> list[str]:
    """How the computer runs Colony: the repo's pinned launcher, else `colony` on PATH, else this Python's module."""
    try:
        launcher = cli.repo_root() / cli.DIR / "bin" / cli.NAME
    except cli.ColonyError:
        launcher = None
    if launcher is not None and os.access(launcher, os.X_OK):
        return [str(launcher)]
    found = shutil.which(cli.NAME)
    return [found] if found else [sys.executable, "-m", cli.NAME]


def start(config: dict, stay: bool = False) -> bool:
    """Start the watchdog in the background, in its own process group and with no session's identity, unless one
    runs. Returns whether it started."""
    if running(config) is not None:
        return False
    log = log_path(config["project"]["name"])
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as out:
        subprocess.Popen([sys.executable, "-m", cli.NAME, "watchdog", "run", *(["--stay"] if stay else [])],
                         cwd=str(cli.repo_root()), stdin=subprocess.DEVNULL, stdout=out, stderr=out, env=own_env(),
                         **portable.own_group())
    return True


def own_env() -> dict[str, str]:
    """This process's environment without the session's identity, so the watchdog belongs to no session: no Claude
    Code session id and no Colony session, lead or token."""
    session = ("CLAUDECODE", cli.CLAUDE_SESSION_ENV, "CLAUDE_PID")
    return {key: value for key, value in os.environ.items()
            if key not in session and not key.startswith(f"{cli.NAME.upper()}_")}


def ensure(config: dict, s) -> None:
    """The lead's wait's part: inside a Claude Code session, with `[watch] watchdog` on, start a watchdog when none
    runs on this computer, trying at most every ENSURE_EVERY. It never raises."""
    if not s.watchdog or not cli.in_claude_code():
        return
    project = config["project"]["name"]
    tried = path(project, "watchdog-ensured")
    at = wait.read_json(tried, 0)
    if isinstance(at, (int, float)) and time.time() - at < ENSURE_EVERY:
        return
    try:
        wait.write_json(tried, time.time())
        start(config)
    except (OSError, cli.ColonyError) as e:
        print(f"{cli.NAME} wait: the watchdog was not started: {e}", file=sys.stderr)


# One pass


def stopped_tasks(config: dict) -> list[dict]:
    """The background tasks something stopped from outside (recover.stopped_tasks): each task file on this computer,
    ~/.colony/<project>/tasks/<pid>.json, whose process is gone. A failure to read them never stops the watchdog: it
    goes to stderr, and the pass finds none."""
    from colony import recover

    try:
        return recover.stopped_tasks(config)
    except Exception as e:  # recover's failure never stops the watchdog
        print(f"{cli.NAME} watchdog: the stopped tasks were not read: {e}", file=sys.stderr)
        return []


def task_prompt(task: dict) -> str:
    """What a session is told about a background task of its that stopped: the line its own Stop hook would give it
    (recover.restart_line)."""
    from colony import recover

    return recover.restart_line(task)


def forget_tasks(tasks: list[dict]) -> None:
    """Drop the task files of tasks the watchdog told their sessions about (recover.forget), so the Stop hook doesn't
    tell them again."""
    from colony import recover

    recover.forget(tasks)


def acted(how: str) -> bool:
    """Whether capacity.wake reached the session, by what it says it did."""
    return how.startswith(("sent", "typed", "started"))


def lead_here(config: dict, now: float) -> bool:
    """Whether a lead's wait runs on this computer: a fresh lead heartbeat."""
    from colony import presence

    return bool(presence.local(config, now))


def person_logins(config: dict, lead: str) -> list[str]:
    """The GitHub logins of a named lead's person, `<person>-<stream>-lead`, sorted; [] when unknown."""
    if not lead.endswith(f"-{cli.LEAD}") or "-" not in lead.removesuffix(f"-{cli.LEAD}"):
        logins = sorted(str(login).lower() for login in config.get("people", {}).get("logins", []))
        return logins if len(logins) == 1 else []
    return sorted(wait.person_logins(config, lead.split("-", 1)[0]))


def tick(config: dict, s, held: dict, now: float | None = None) -> list[str]:
    """One pass of the watchdog, keeping its memory in `held`; returns a line for each thing it did."""
    from colony import capacity, guards, watch

    now = time.time() if now is None else now
    raised = held.setdefault("raised", {})
    for key in [key for key, at in raised.items() if not isinstance(at, (int, float)) or now - at > watch.RAISED_KEPT]:
        raised.pop(key)
    lines: list[str] = []
    team = watch.local_members(config)
    found: dict = {}

    def sessions() -> tuple[dict, dict]:
        if not found:
            agents = cli.running_sessions(config)
            found["id"] = {a.get("sessionId"): a for a in agents if a.get("sessionId")}
            found["name"] = {capacity.short(config, a): a for a in agents}
        return found["id"], found["name"]

    woken: set[str] = set()
    for name, member in team.items():  # 1. waits that stopped
        if not member.pulse or now - member.pulse < watch.PULSE_FRESH or member.intent == "done" or member.limited:
            continue
        key = f"wait:{name}:{member.pulse}"
        if key in raised:
            continue
        by_id, by_name = sessions()
        agent = by_id.get(member.session) or by_name.get(name)
        if agent is None:
            continue  # its session runs no more here: `colony resume` and `colony crash-report` are for that
        how = capacity.wake(config, name, agent, capacity.STOPPED_PROMPT)
        if acted(how):
            raised[key] = now
            woken.add(name)
            lines.append(f"{name}: its wait had stopped; {how}")
    tasks = [task for task in stopped_tasks(config) if task.get("command") != "wait"]
    told = []
    for task in tasks:  # 2. background tasks stopped from outside
        name = str(task.get("session") or "")
        if not name or name in woken:
            continue
        by_id, by_name = sessions()
        agent = by_id.get(task.get("claude")) or by_name.get(name)
        if agent is None:
            continue
        how = capacity.wake(config, name, agent, task_prompt(task))
        if acted(how):
            told.append(task)
            lines.append(f"{name}: its background {task.get('label') or task.get('command')} had stopped; {how}")
    if told:
        forget_tasks(told)
    if not lead_here(config, now):  # 3. the lead's wait's part, while none runs here
        if capacity.limited(config):
            lines += capacity.wake_due(config, now)
        gap = capacity.slept(held.setdefault("clock", {}))
        if gap:
            what = "restarted" if gap < 0 else f"slept for {round(gap / 60)} minutes"
            lines += [f"this computer {what}; {line}" for line in capacity.restart(config, capacity.SLEPT_PROMPT, True)]
    for name, member in team.items():  # 4. a lead idle too long
        if member.kind != "lead" or member.intent == "done" or member.limited:
            continue
        if member.intent in watch.WAITS and now < watch.due(member, s):
            continue
        if watch.busy_helpers(name, team, s, now) or (member.busy and now - member.seen < watch.BUSY_FRESH):
            continue
        moved = watch.activity_of(Path(member.transcript)).get("active", 0.0) if member.transcript else 0.0
        active = max(moved, member.active)
        quiet = now - active if active else 0.0
        if quiet < (s.idle_minutes + s.escalate_minutes) * 60 or quiet > s.quit_hours * 3600:
            continue  # not idle long enough, or quiet for so long that its session has ended
        key = f"escalate:{name}:{active}"
        if key in raised:
            continue
        raised[key] = now
        what = f"has done nothing for {watch.minutes(quiet)}, " + (
            "with no helper busy and no reason given" if not member.intent else
            f"and its {member.intent} on \"{member.why}\" is past due")
        mention = " ".join(f"@{login}" for login in person_logins(config, name))
        sentence = f"urgent: {name} {what}; " + (f"{mention}, please " if mention else "please ") + \
            f"look at its window on {member.computer or 'its computer'}"
        guards.post(config, name, sentence, cli.NAME)
        lines.append(f"{name}: {what}; its person was told on GitHub")
    from colony import statuspage

    if line := statuspage.keep(config, s, now):  # 5. the status page
        lines.append(line)
    return lines


def alive_here(config: dict, now: float) -> bool:
    """Whether any session of the project shows life on this computer: a fresh pulse or a fresh lead heartbeat."""
    from colony import watch

    pulses = [m.pulse for m in watch.local_members(config).values() if m.pulse]
    return any(now - at < watch.PULSE_FRESH for at in pulses) or lead_here(config, now)


def run(config: dict, args) -> int:
    """`colony watchdog run [--stay] [--once]`: the watchdog itself, in the foreground. One runs per project on this
    computer; a second says so and ends."""
    from colony import watch

    project = config["project"]["name"]
    lock_path(project).parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path(project), "a") as handle, portable.lock(handle, block=False) as got:
        if not got:
            print(f"A {cli.NAME} watchdog already runs for {project} on this computer.")
            return 0
        held: dict = {}
        started = last_alive = time.time()
        try:
            with wait.stop_on_terminate():
                while True:
                    now = time.time()
                    s = watch.settings(config)
                    try:
                        for line in tick(config, s, held, now):
                            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}", flush=True)
                    except Exception as e:  # one pass that fails never ends the watchdog
                        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} the pass failed: {e}", flush=True)
                    if alive_here(config, now):
                        last_alive = now
                    wait.write_json(path(project), {"pid": os.getpid(), "started": started, "at": now,
                                                    "stay": bool(args.stay), "every_minutes": s.every_minutes})
                    if args.once:
                        return 0
                    if not args.stay and now - last_alive >= s.quit_hours * 3600:
                        print(f"No session has run here for {s.quit_hours:g} hours, so the watchdog ends.", flush=True)
                        return 0
                    SLEEP(s.every_minutes * 60)
        except wait.Stopped:
            print("The watchdog stopped on a terminate signal.", flush=True)
            return 0
        finally:
            path(project).unlink(missing_ok=True)


# The commands, and installing it with the computer's own service manager


def label(config: dict) -> str:
    """The service's name, such as com.colony.watchdog.myapp."""
    return f"com.{cli.NAME}.watchdog.{re.sub(r'[^A-Za-z0-9.-]', '-', config['project']['name'])}"


def service_files(config: dict, system: str = sys.platform) -> tuple[Path, str, list[list[str]], list[list[str]]]:
    """The service file for this system, its text, and the commands that load and unload it. macOS uses a launchd
    agent, Linux a systemd user unit; elsewhere it raises."""
    argv = [*command(), "watchdog", "run", "--stay"]
    root, log = str(cli.repo_root()), str(log_path(config["project"]["name"]))
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home())}
    if system == "darwin":
        file = Path.home() / "Library" / "LaunchAgents" / f"{label(config)}.plist"
        text = plistlib.dumps({"Label": label(config), "ProgramArguments": argv, "WorkingDirectory": root,
                               "RunAtLoad": True, "KeepAlive": True, "StandardOutPath": log, "StandardErrorPath": log,
                               "EnvironmentVariables": env}).decode()
        return file, text, [["launchctl", "load", "-w", str(file)]], [["launchctl", "unload", "-w", str(file)]]
    if system.startswith("linux"):
        unit = f"{label(config)}.service"
        file = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user" / unit
        text = "\n".join([
            "[Unit]", f"Description={cli.DISPLAY} watchdog for {config['project']['name']}", "",
            "[Service]", f"ExecStart={shlex.join(argv)}", f"WorkingDirectory={root}", "Restart=always", "RestartSec=30",
            *(f"Environment={key}={value}" for key, value in env.items()), f"StandardOutput=append:{log}",
            f"StandardError=append:{log}", "", "[Install]", "WantedBy=default.target", ""])
        return file, text, [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", unit]], \
            [["systemctl", "--user", "disable", "--now", unit]]
    raise cli.ColonyError(f"`{cli.NAME} watchdog install` knows macOS and Linux; here, have the computer run "
                          f"`{shlex.join(argv)}` at login, such as with Task Scheduler")


def install(config: dict, args, system: str = sys.platform) -> int:
    """`colony watchdog install [--dry-run]`: have the computer run the watchdog at login and again whenever it
    ends. It writes one service file for this project, and runs the service manager's load command."""
    file, text, load, _ = service_files(config, system)
    if args.dry_run:
        print(f"would write {file}:\n{text}")
        for argv in load:
            print(f"would run: {shlex.join(argv)}")
        return 0
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    for argv in load:
        done = RUN(argv, capture_output=True, text=True)
        if done.returncode:
            raise cli.ColonyError(f"{shlex.join(argv)} failed: {(done.stderr or done.stdout).strip()[:200]}")
    print(f"The computer now runs the watchdog for {config['project']['name']} at login and again whenever it ends: "
          f"{file}. `{cli.NAME} watchdog uninstall` undoes it.")
    return 0


def uninstall(config: dict, args, system: str = sys.platform) -> int:
    """`colony watchdog uninstall [--dry-run]`: unload and remove the service file install wrote."""
    file, _, _, unload = service_files(config, system)
    if not file.exists():
        print(f"No watchdog service is installed for {config['project']['name']}: {file} is missing.")
        return 0
    if args.dry_run:
        print("\n".join(f"would run: {shlex.join(argv)}" for argv in unload) + f"\nwould remove {file}")
        return 0
    for argv in unload:
        RUN(argv, capture_output=True, text=True)
    file.unlink()
    print(f"Removed {file}; the computer no longer starts the watchdog.")
    return 0


def stop(config: dict) -> int:
    """`colony watchdog stop`: end the running watchdog by its exact process id, from its heartbeat."""
    held = running(config)
    pid = held.get("pid") if held else None
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        print(f"No {cli.NAME} watchdog runs for {config['project']['name']} on this computer.")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        raise cli.ColonyError(f"the watchdog, process {pid}, was not stopped: {e}") from None
    installed = service_files_quiet(config)
    note = f" The installed service starts it again; `{cli.NAME} watchdog uninstall` ends that." if installed else ""
    print(f"Stopped the watchdog, process {pid}.{note}")
    return 0


def service_files_quiet(config: dict) -> Path | None:
    """The installed service file, or None when there is none or this system has no service manager Colony knows."""
    try:
        file = service_files(config)[0]
    except cli.ColonyError:
        return None
    return file if file.exists() else None


def status(config: dict) -> int:
    """`colony watchdog status`: whether it runs, since when, its last pass, whether the computer starts it, its log,
    and the status page's link."""
    from colony import statuspage, watch

    project = config["project"]["name"]
    held, now = running(config), time.time()
    if held is None:
        print(f"The watchdog does not run for {project} on this computer.")
    else:
        since = watch.minutes(now - float(held.get("started") or now))
        last = watch.minutes(now - float(held.get("at") or now))
        print(f"The watchdog runs for {project}: process {held.get('pid')}, for {since}, last pass {last} ago.")
    installed = service_files_quiet(config)
    print(f"The computer starts it at login: {installed}." if installed else
          f"The computer does not start it by itself; `{cli.NAME} watchdog install` makes it.")
    print(f"Its log: {log_path(project)}")
    page = wait.read_json(statuspage.state_path(config), {})
    if isinstance(page, dict) and isinstance(page.get("number"), int):
        print(f"The status page: https://github.com/{config['project']['repo']}/issues/{page['number']}")
    return 0


def watchdog_command(config: dict, args) -> int:
    """`colony watchdog [start|stop|status|run|install|uninstall]`."""
    action = args.action or "status"
    if action == "start":
        started = start(config, stay=args.stay)
        print(f"Started the watchdog; its log is {log_path(config['project']['name'])}." if started else
              f"A {cli.NAME} watchdog already runs for {config['project']['name']} on this computer.")
        return 0
    if action == "stop":
        return stop(config)
    if action == "run":
        return run(config, args)
    if action == "install":
        return install(config, args)
    if action == "uninstall":
        return uninstall(config, args)
    return status(config)


def register(sub) -> None:
    """`colony watchdog`, which watch.register adds."""
    p = sub.add_parser("watchdog", help="the process that watches the team when every session has stopped: start, "
                                        "stop, status, run, install or uninstall")
    p.add_argument("action", nargs="?", choices=("start", "stop", "status", "run", "install", "uninstall"),
                   help="status by default")
    p.add_argument("--stay", action="store_true", help="run on with no session alive here, as an installed one does")
    p.add_argument("--once", action="store_true", help="with run: one pass, then end")
    p.add_argument("--dry-run", action="store_true", help="with install or uninstall: say what it would do")
    p.set_defaults(run=watchdog_command)
