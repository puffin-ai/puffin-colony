"""Puffin Colony's command line: one command for a repo's whole software life cycle.

`colony` alone runs setup the first time (the repo has no .colony/colony.toml) and opens the lead every time after.
`colony hi` tells a session opened without a task which case it is in: no setup yet, a lead running (offer to build
or help), or none (claim the lead through its heartbeat, wait.beat).
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
import time
import tomllib
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from colony import __version__

NAME = "colony"
DISPLAY = "Puffin Colony"
DIR = f".{NAME}"  # the folder a host repo keeps Colony's files in: the config, rules, playbook and reports
CONFIG_NAME = f"{NAME}.toml"
SESSION_ENV, PERSON_ENV = f"{NAME.upper()}_SESSION", f"{NAME.upper()}_PERSON"
LEAD = "lead"
LEAD_PROMPT = "Read {dir}/playbook.md, {section} section, and start."
BUILDER_PROMPT = "Read {dir}/playbook.md, {section} section. You are {builder}. Start the wait."
SESSION_NAME = re.compile(r"[a-z0-9][a-z0-9.-]*")
RESEARCHER, SPEC = "researcher", "spec"  # the sessions `colony research` and `colony spec` open, named as their roles
ROLES = ("lead", "builder", "reviewer", "walker", "fixer")
# Roles a colony.toml may leave out: each one missing takes the builder's settings.
BUILDER_LIKE = (RESEARCHER, SPEC)
FULL = 90.0  # an account whose saved 5-hour usage is at or past this percent has no room for prefer_account
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
        account["config_dir"] = os.path.expanduser(account["config_dir"])
    project = config["project"]
    if project.get("prefer_account") and project["prefer_account"] not in config["accounts"]:
        raise ColonyError(f"{path}: [project] prefer_account names {project['prefer_account']!r}, which no "
                          "[accounts.<name>] table holds")
    for key in ("worktrees", "check_env_file"):
        if project.get(key):
            project[key] = os.path.expanduser(project[key])
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


def five_hour_usage(config_dir: str) -> float | None:
    """The account's saved 5-hour usage in percent, 0 once that window has reset, or None when none is saved.

    Claude Code saves it as `cachedUsageUtilization.utilization.five_hour`, holding
    `utilization` (percent used) and `resets_at` (an ISO time).
    """
    try:
        window = _state(config_dir)["cachedUsageUtilization"]["utilization"]["five_hour"]
        used = float(window["utilization"])
        if window.get("resets_at") and datetime.fromisoformat(window["resets_at"]) <= datetime.now(timezone.utc):
            return 0.0
        return used
    except (ValueError, KeyError, TypeError):
        return None


def has_room(config_dir: str) -> bool:
    """Whether an account's folder is on this computer and its saved 5-hour usage, if any, is under FULL percent."""
    used = five_hour_usage(config_dir)
    return Path(config_dir).is_dir() and (used is None or used < FULL)


def pick_account(config: dict, person: str) -> tuple[str, str]:
    """The person's account for a new session, as (name, config_dir): `[project] prefer_account` when it is the
    person's and has room, else the person's account with the most room on this computer.

    Accounts whose person is `any` count for everyone, and folders this computer has come first. The lowest
    saved 5-hour usage wins, the earlier account on a tie. When no account has a saved figure, the first one wins.
    """
    mine = [(name, a["config_dir"]) for name, a in config["accounts"].items() if a["person"] in (person, "any")]
    if not mine:
        raise ColonyError(f"{CONFIG_NAME} has no account for {person!r}")
    preferred = config.get("project", {}).get("prefer_account")
    for name, folder in mine:
        if name == preferred and has_room(folder):
            return name, folder
    mine = [(name, folder) for name, folder in mine if Path(folder).is_dir()] or mine
    saved = [(used, i) for i, (_, folder) in enumerate(mine) if (used := five_hour_usage(folder)) is not None]
    return mine[min(saved)[1]] if saved else mine[0]


def choose_account(config: dict, args) -> tuple[str, str]:
    """The account a session or batch runs on, as (name, config_dir): --account when given, else pick_account for
    the session's person."""
    name = getattr(args, "account", None)
    if name:
        if name not in config["accounts"]:
            raise ColonyError(f"--account {name!r} is not in {CONFIG_NAME}: choose from {', '.join(config['accounts'])}")
        return name, config["accounts"][name]["config_dir"]
    return pick_account(config, person_of(config, args))


def git_user() -> set[str]:
    """The git user's first name and email name in this checkout, lowercased, to tell whose computer this is."""
    found = set()
    for key in ("user.name", "user.email"):
        value = _out(["git", "config", key]).lower().split("@")[0].split()
        if value:
            found.add(value[0])
    return found


def default_person(config: dict) -> str:
    """The one person colony.toml names, else the one the git user matches, else an error asking for --person."""
    people = sorted({a["person"] for a in config["accounts"].values()} - {"any"})
    if len(people) == 1:
        return people[0]
    matches = [p for p in people if p.lower() in git_user()]
    if len(matches) == 1:
        return matches[0]
    raise ColonyError(f"say whose session this is: --person {' or '.join(people)}")


def person_of(config: dict, args) -> str:
    """Whose session this is: --person, else $COLONY_PERSON, else default_person."""
    return getattr(args, "person", None) or os.environ.get(PERSON_ENV) or default_person(config)


def session_env(person: str, session: str, config_dir: str) -> dict[str, str]:
    """The environment variables a lead or builder starts with.

    Claude Code ties a login to the CLAUDE_CONFIG_DIR value, so the default folder leaves it
    unset; naming `~/.claude` there would open a session that is not signed in.
    """
    env = {SESSION_ENV: session, PERSON_ENV: person}
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
    folders.append(str(repo_root().parent))  # the playbook's ../<name>-<n> worktrees sit beside the clone
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
    return ["env", "-u", "CLAUDE_CONFIG_DIR", *argv] if is_default_dir(config_dir) else argv


def cmux_usable() -> bool:
    """Whether cmux is on PATH and takes commands from this process, which it does only inside cmux."""
    if shutil.which("cmux") is None:
        return False
    try:
        return subprocess.run(["cmux", "workspace", "list"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def where_to_open(args) -> str:
    """cmux when it takes us, this terminal for --here or a person at a terminal, else a background session."""
    if getattr(args, "here", False):
        return "terminal"
    if cmux_usable():
        return "cmux"
    return "terminal" if sys.stdin.isatty() else "background"


def launch(config: dict, args, session: str, role: str, prompt: str) -> int:
    """Open one session on --account, else the person's account (pick_account): in cmux, in this terminal, or in the
    background.

    A background session runs under Remote Control, so the person follows it in the Claude app, or with
    `claude attach`. A dry run prints the command, the env names (never their values) and where it would
    open, and runs nothing. A lead claims the heartbeat first (wait.beat), so a second lead never opens while one runs.
    """
    person = person_of(config, args)
    account, config_dir = choose_account(config, args)
    title = f"{config['project']['name']}-{session}"
    env = session_env(person, session, config_dir)
    argv = claude_argv(config, role, title, config_dir, prompt, session_settings(config, env, masked=args.dry_run))
    root = str(repo_root())
    mode = where_to_open(args)
    where = {"cmux": f"a new cmux workspace at {root}", "terminal": f"this terminal at {root}",
             "background": f"a background session at {root}; follow it in the Claude app or with `claude attach`"}[mode]
    if args.dry_run:
        print("command:", shlex.join(argv))
        print("env:", " ".join(env))
        print(f"dry run: {title} on account {account}, in {where}")
        return 0
    if shutil.which("claude") is None:
        raise ColonyError("claude is not on PATH")
    if session == LEAD:
        from colony import wait

        env[wait.TOKEN_ENV] = wait.new_token()
        try:
            wait.beat(config["project"]["name"], wait.lead_name(config, args), account, env[wait.TOKEN_ENV])
        except wait.LeadTaken as e:
            raise ColonyError(f"a lead is running here, so {NAME} opens no second one: {e}") from None
        argv = claude_argv(config, role, title, config_dir, prompt, session_settings(config, env))
    print(f"Opening {title} on account {account}, in {where}.", flush=True)
    # A set ANTHROPIC_API_KEY makes Claude Code bill that key instead of the account's
    # subscription, so a session drops it unless colony.toml says to use it.
    keep_key = config.get("budget", {}).get("use_api_key", False)
    inherited = {k: v for k, v in os.environ.items() if keep_key or k != "ANTHROPIC_API_KEY"}
    if mode == "cmux":
        command = argv if keep_key else ["env", "-u", "ANTHROPIC_API_KEY", *argv]
        cmd = ["cmux", "new-workspace", "--name", title, "--cwd", root, "--command", shlex.join(command)]
        cmd += [part for key, value in env.items() for part in ("--env", f"{key}={value}")]
        return subprocess.run(cmd).returncode
    if mode == "background":
        at = argv.index("claude") + 1
        background = [*argv[:at], "--bg", "--name", title, *argv[at:]]
        return subprocess.run(background, cwd=root, env={**inherited, **env}).returncode
    os.chdir(root)
    os.execvpe(argv[0], argv, {**inherited, **env})


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
TOOLS = ("playwright", "context7", "role-skills", "starter-skills", "relay", "ui-design", "test-first")
RELAY_LINE = 'transport = "relay"'  # the [messages] line a yes to relay puts in colony.toml


def offered() -> dict[str, tuple[str, str]]:
    """Each tool with its default (yes, no, or ask for no default) and what it is. The relay's default is yes when
    this computer runs an Agent Relay core."""
    from colony import guards, transport

    relay = transport.relay_available()
    return {
        "playwright": ("yes", "Playwright MCP, the walker's browser. It installs a package: npx downloads "
                              "@playwright/mcp on first use."),
        "context7": ("yes", "Context7 MCP, current docs for every library. A hosted server: nothing is installed."),
        "role-skills": ("yes", f"{DISPLAY}'s role skills, {', '.join(ROLE_SKILLS)}: the playbook split per role, "
                               "copied from the package."),
        "starter-skills": ("yes", f"{DISPLAY}'s starter skills, {', '.join(guards.STARTER_SKILLS)}, copied from the "
                                  "package. A skill the repo already has is kept."),
        "relay": ("yes" if relay else "no",
                  "Instant lines: each line also goes at once through this computer's Agent Relay core, and the issue "
                  "comment stays the record. " + ("A core runs on this computer." if relay else
                                                  "No core runs on this computer now.")),
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
    os.execvp("claude", ["claude", prompt])


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
    """One line on this computer's lead: its name, account and heartbeat age, or that none is running."""
    from colony import wait

    held = wait.read_heartbeat(config["project"]["name"])
    if held is None:
        return "lead: none running on this computer (no heartbeat)"
    age = ago(time.time() - held["at"])
    if not wait.fresh(held):
        return f"lead: none running on this computer ({held.get('session', 'the last lead')}'s heartbeat is {age} old)"
    return f"lead: {held.get('session', 'unknown')} on account {held.get('account', 'unknown')}, heartbeat {age} ago"


def free_builder(project: str) -> str:
    """The first builder name, builder-1 up, with no wait that polled on this computer in the last 2 minutes."""
    from colony import wait

    n = 1
    while True:
        state = wait.read_json(wait.state_path(project, f"builder-{n}"), {})
        polled = state.get("polled_at") if isinstance(state, dict) else None
        if not isinstance(polled, (int, float)) or time.time() - polled >= wait.HEARTBEAT_FRESH:
            return f"builder-{n}"
        n += 1


def hi(args) -> int:
    """`colony hi`: for a session opened without a task, say which case this repo is in and what to do.

    No .colony/colony.toml: set Colony up in this session. A session Colony opened ($COLONY_SESSION set) is a helper
    for good, and is told its role. Otherwise the lead's heartbeat decides: fresh, and the session offers to be a
    builder or to help; stale or missing, and the session claims the lead by writing the heartbeat (wait.beat), which
    lapses in 2 minutes unless its `colony wait` keeps it."""
    from colony import wait

    if not config_path().exists():
        print(f"{DISPLAY}: not set up in this repo, since {DIR}/{CONFIG_NAME} is missing.")
        print(f"Next: set it up in this session. Load the {SETUP_SKILL} skill, or run `{NAME} setup --print` and follow "
              "the prompt it prints, asking the person its questions here.")
        return 0
    config = load_config()
    project = config["project"]["name"]
    print(f"{DISPLAY}: set up here, project {project}, {mode(config)} mode.")
    me = os.environ.get(SESSION_ENV, "").lower()
    if me:
        role = section(config, "Lead" if me == LEAD else "Builder")
        print(f"This session is {me}, which {NAME} opened: follow the {role} section of {DIR}/playbook.md.")
        return 0
    try:
        person = person_of(config, args)
    except ColonyError:
        people = sorted({a["person"] for a in config["accounts"].values()} - {"any"})
        print(f"Next: ask the person which of {', '.join(people)} they are, then run `{NAME} hi --person <them>`.")
        return 0
    account, token = current_account(config), wait.new_token()
    try:
        wait.beat(project, wait.lead_name(config, args), account, token)
    except wait.LeadTaken:
        builder = free_builder(project)
        print(lead_line(config))
        print(f"Next: offer to be a builder, or to help. As a builder: take the name {builder}, ask the person to tell "
              f"their lead that {builder} waits for a card, load the colony-builder skill and follow it, and start "
              f"every {NAME} command with `{SESSION_ENV}={builder} {PERSON_ENV}={person}`. To help: do what the person "
              "asks, and leave the cards to the lead and its builders.")
        return 0
    print(f"No lead was running on this computer, so this session claimed the lead, on account {account}.")
    print(f"Next: tell the person you are their lead, then load the colony-lead skill and follow it. Start every {NAME} "
          f"command with `{SESSION_ENV}={LEAD} {PERSON_ENV}={person} {wait.TOKEN_ENV}={token}`, and start "
          f"`{NAME} wait` in the background within 2 minutes: it keeps the heartbeat that holds the lead. When the "
          "person would rather you didn't lead, start no wait, and the claim lapses in 2 minutes.")
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


def first_run() -> None:
    """The first time `colony` runs on a computer, install the colony-setup skill as `colony skill-install` does, so a
    plain hi works in a repo that has never used Colony. The marker makes it happen once: a skill the person removes
    stays removed. A computer without Claude's settings folder yet is skipped, and tried again on the next run."""
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
    downloads at its pinned commit through gh. It ends by printing the [tools] table for colony.toml, and with relay,
    the [messages] transport line.
    """
    from colony import guards, transport

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
        if "relay" in chosen:
            print(f"  {DIR}/{CONFIG_NAME}: [messages] {RELAY_LINE}")
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
    if "relay" in chosen:
        print(f"\nand set this line in its [messages] table:\n{RELAY_LINE}")
        if not transport.relay_available():
            print("No Agent Relay core runs on this computer now: until one does, each line goes by GitHub alone.")
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
    """Open a builder on this computer in a new cmux workspace (the lead runs this)."""
    return launch(config, args, args.name, "builder", builder_prompt(args.name, config))


def brief(name: str) -> tuple[str, str]:
    """A role's brief and where it came from: the repo's own {dir}/prompts/<name>.md, which setup copies with the
    project's values in, else the package's prompts/<name>.md."""
    own = repo_root() / DIR / "prompts" / f"{name}.md"
    if own.is_file():
        return own.read_text(), f"{DIR}/prompts/{name}.md"
    return package_file("prompts", f"{name}.md"), f"the package's prompts/{name}.md"


def open_brief(config: dict, args, role: str, **values: str) -> int:
    """Open a researcher or the spec agent on this computer, whose first prompt is its brief filled in: `{project}`,
    `{knowledge}` (the vault folder, `[knowledge] vault`) and the request (`{question}` or `{feature}`)."""
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


def origin_url() -> str:
    """The URL of this checkout's origin remote, or an empty string when it has none."""
    return _out(["git", "remote", "get-url", "origin"])


def join_missing(config: dict, args) -> list[str]:
    """What this computer lacks to run a builder: a clone of the repo, claude and its login, or gh auth."""
    repo, missing = config["project"]["repo"], []
    if repo.lower() not in origin_url().lower():
        missing.append(f"a clone of {repo}: run `gh repo clone {repo}`, then `{NAME} join {args.name}` inside it")
    if shutil.which("claude") is None:
        missing.append("claude: install Claude Code, then sign in with /login")
    else:
        account, folder = choose_account(config, args)
        if not signed_in(folder):
            missing.append(f"the claude login for account {account}: open claude on that account and run /login")
    if shutil.which("gh") is None or subprocess.run(["gh", "auth", "status"], capture_output=True).returncode:
        missing.append("gh auth: run `gh auth login`")
    return missing


def join(config: dict, args) -> int:
    """Open a builder on another computer, after saying what that computer still lacks."""
    missing = join_missing(config, args)
    for item in missing:
        print("missing:", item)
    if missing and not args.dry_run:
        return 1
    return launch(config, args, args.name, "builder", builder_prompt(args.name, config))


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


ACCOUNT_HELP = ("the account to open on, instead of the pick ([project] prefer_account while it has room, else the "
                "one with the most room)")


def build_parser() -> argparse.ArgumentParser:
    """The command line: no command for setup or the lead, then the sessions (join, open, research, spec), the lines
    (wait, say, post), the gate (batch, status, merge), the cycle's, the board, check-docs, the guards', and tools."""
    from colony import board, cycle, guards, vault
    parser = argparse.ArgumentParser(prog=NAME, description=f"{DISPLAY}: run with no command to open your lead "
                                     f"(or to set up the repo, the first time).")
    parser.add_argument("--version", action="version", version=f"{DISPLAY} {__version__}")
    parser.add_argument("--person", help=f"whose accounts to use (needed when {CONFIG_NAME} names several people)")
    parser.add_argument("--account", metavar="NAME", help=ACCOUNT_HELP)
    parser.add_argument("--here", action="store_true", help="open in this terminal even when cmux is on PATH")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and the env names, and run nothing")
    parser.set_defaults(run=lead)
    sub = parser.add_subparsers(dest="command", metavar="command")

    for command, run, text in (("join", join, "open a builder on this computer (paste the line the lead prints)"),
                               ("open", open_builder, "open a builder here in a new cmux workspace (the lead runs it)")):
        p = sub.add_parser(command, help=text)
        p.add_argument("name", type=builder_name, help="the builder's name, such as builder-2")
        p.add_argument("--person", help="whose accounts to use")
        p.add_argument("--account", metavar="NAME", help=ACCOUNT_HELP)
        p.add_argument("--dry-run", action="store_true", help="print the command and the env names, and run nothing")
        if command == "join":
            p.add_argument("--here", action="store_true", help="open in this terminal even when cmux is on PATH")
        p.set_defaults(run=run)

    for command, run, field, text in (
            ("research", research, "question", "open a researcher on one question, answered with cited sources"),
            ("spec", spec, "feature", "open the spec agent on a FEATURE: requirements, design and tasks")):
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
                                                     "([project] prefer_account, else the one with the most room)")
    p.add_argument("--review", action="store_true",
                   help="add a fresh reviewer to a gate whose [gate] review is false, as in hack mode")
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

    for module in (cycle, board, vault, guards):
        module.add_commands(sub)

    p = sub.add_parser("hi", help="for a session opened without a task: set up, claim the lead when none runs, or "
                                  "offer to build or help")
    p.add_argument("--person", help="whose session this is")
    p.set_defaults(run=hi)

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

    p = sub.add_parser("tools", help="list the MCPs, skills and relay setup offers, or write the named ones "
                                     "(setup runs it)")
    p.add_argument("names", nargs="*", metavar="tool", help=f"the tools to write: {', '.join(TOOLS)}")
    p.add_argument("--dry-run", action="store_true", help="print what it would write, and run nothing")
    p.set_defaults(run=tools)
    return parser


def main(argv=None) -> int:
    """Parse the command line and run one command: setup when the repo has no .colony/colony.toml, else the one asked."""
    args = build_parser().parse_args(argv)
    if not getattr(args, "dry_run", False):
        first_run()
    try:
        if args.command is None and not config_path().exists():
            return setup(args)
        if args.command in ("tools", "hi", "setup", "skill-install"):  # each runs before colony.toml exists
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
