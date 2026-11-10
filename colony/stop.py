"""Ending a person's part. Without it, a lead closes its helpers by finding and killing their processes, can miss
one, and after a handoff the other person's builders keep asking the side that closed.

`colony stop [<name> ...]` stops this project's Colony sessions on this computer: a background one with `claude stop`,
which keeps its conversation, and an interactive one with a terminate signal. It never stops the session that runs
it, and keeps one whose folder holds uncommitted work unless --force. The board hears who stopped.

`colony handoff @<login>` hands this person's open work to another person's lead: the branches not yet in the base,
with their commits, a warning for each one never pushed, and this lead's claimed paths, which it releases. The board
gets it as one line for that login.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from colony import cli, presence, wait


def stop_background(agent: dict) -> None:
    """Stop a background session with `claude stop <id>`, on its own account."""
    env = {key: value for key, value in os.environ.items() if key != "CLAUDE_CONFIG_DIR"}
    if agent.get("config_dir") and not cli.is_default_dir(agent["config_dir"]):
        env["CLAUDE_CONFIG_DIR"] = agent["config_dir"]
    subprocess.run(["claude", "stop", str(agent["id"])], env=env, capture_output=True, text=True, timeout=30)


def stop_interactive(agent: dict) -> None:
    """Ask an interactive session to end: a terminate signal, which Claude Code ends on, keeping the conversation."""
    os.kill(int(agent["pid"]), signal.SIGTERM)


def uncommitted(agent: dict) -> bool:
    """Whether the session's folder holds uncommitted or untracked work."""
    folder = agent.get("cwd") or ""
    if not folder or not Path(folder).is_dir():
        return False
    run = subprocess.run(["git", "-C", folder, "status", "--porcelain"], capture_output=True, text=True)
    return run.returncode == 0 and bool(run.stdout.strip())


def stop(config: dict, args) -> int:
    """`colony stop [<name> ...] [--force]`: see the module's docstring. Returns 1 when it kept a session."""
    from colony import transport

    me = os.environ.get(cli.CLAUDE_SESSION_ENV, "")
    project = config["project"]["name"]
    here = [agent for agent in cli.running_sessions(config) if agent.get("sessionId") != me or not me]
    names = [name.strip().lower() for name in getattr(args, "names", []) or []]
    if names:
        wanted = {name.removeprefix(f"{project}-") for name in names}
        chosen = [agent for agent in here if str(agent.get("name", "")).removeprefix(f"{project}-").lower() in wanted]
        missing = wanted - {str(agent.get("name", "")).removeprefix(f"{project}-").lower() for agent in chosen}
        if missing:
            raise cli.ColonyError(f"no session named {', '.join(sorted(missing))} runs on this computer")
    else:
        chosen = here
    stopped, kept = [], []
    for agent in chosen:
        name = str(agent.get("name") or agent.get("id") or agent.get("pid"))
        if not args.force and uncommitted(agent):
            kept.append(name)
            print(f"kept {name}: its folder {agent.get('cwd')} holds uncommitted work; commit or drop it, or run "
                  f"`{cli.NAME} stop {name} --force`")
            continue
        try:
            (stop_background if agent.get("kind") == "background" else stop_interactive)(agent)
        except (OSError, subprocess.SubprocessError, KeyError, ValueError) as e:
            kept.append(name)
            print(f"kept {name}: it didn't stop: {e}", file=sys.stderr)
            continue
        stopped.append(name)
        print(f"stopped {name}")
    if not stopped and not kept:
        print(f"No other {cli.DISPLAY} session of {project} runs on this computer.")
        return 0
    if wait.hack(config) and stopped:
        line = f"@{wait.ALL} {' and '.join(stopped)} stopped on {presence.computer()}"
        if kept:
            line += f"; {' and '.join(kept)} kept, with uncommitted work"
        try:
            transport.send(config, f"@{wait.ALL}", line)
        except cli.ColonyError as e:
            print(f"{cli.NAME} stop: the board didn't hear it: {e}", file=sys.stderr)
    return 1 if kept else 0


def open_work(root: Path, config: dict, login: str) -> list[str]:
    """This person's branches, `<login>/...`, local or on origin, with commits not yet in origin/<base>: each as
    `<branch> (<n> commits, at <sha>)`, with `never pushed: push it first` when origin lacks it."""
    base = config["project"]["base"]

    def git(*args: str) -> str:
        run = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
        return run.stdout.strip() if run.returncode == 0 else ""

    local = set(git("for-each-ref", "--format=%(refname:short)", f"refs/heads/{login}/").split())
    remote = {name.removeprefix("origin/") for name in
              git("for-each-ref", "--format=%(refname:short)", f"refs/remotes/origin/{login}/").split()}
    found = []
    for branch in sorted(local | remote):
        ref = branch if branch in local else f"origin/{branch}"
        count = int(git("rev-list", "--count", f"origin/{base}..{ref}") or 0)
        if not count:
            continue
        sha = git("rev-parse", "--short=7", ref)
        unpushed = branch not in remote or int(git("rev-list", "--count", f"origin/{branch}..{branch}") or 0) > 0
        found.append(f"{branch} ({count} commit{'s' if count != 1 else ''}, at {sha}"
                     + (", never pushed: push it first)" if unpushed else ")"))
    return found


def handoff(config: dict, args) -> int:
    """`colony handoff @<login>`: see the module's docstring."""
    from colony import transport

    to = args.to.strip().lower()
    login = to.removeprefix("@")
    person = (os.environ.get(cli.PERSON_ENV) or cli.default_person(config)).lower()
    known = {str(name).lower() for name in config.get("people", {}).get("logins", [])}
    if not to.startswith("@") or login == person or (known and login not in known):
        raise cli.ColonyError(f"hand work to another person's lead, by their login, such as @ben (you are {person})")
    lead = os.environ.get(wait.LEAD_ENV, "").lower() or f"{person}-{cli.LEAD}"
    work = open_work(cli.repo_root(), config, person)
    leads = presence.registry()
    paths = [str(path) for path in leads.pop(lead, {}).get("folders", [])]
    presence.write_registry(leads)
    for line in work:
        print(f"open: {line}")
    line = (f"@{login} handoff: {lead} stops, and its work is yours: {'; '.join(work) or 'no open branch'}. "
            f"Its paths are free: {', '.join(paths) or 'none were claimed'}. Ask @{login}, not {lead}, from now on")
    transport.send(config, f"@{login}", line)
    print(line)
    return 0
