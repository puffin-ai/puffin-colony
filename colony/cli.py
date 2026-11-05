"""Puffin Colony's command line: one command for a repo's whole software life cycle.

`colony` alone runs setup the first time (the repo has no .colony/colony.toml) and opens the lead every time after.
`colony join <name>` opens a builder on another computer. The lead and the builders use `open`, `wait`, `batch`
and `status`. Every command finds the repo with `git rev-parse --show-toplevel`. Python 3.11+ standard library only.
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
LEAD_PROMPT = "Read {dir}/playbook.md, Lead section, and start."
BUILDER_PROMPT = "Read {dir}/playbook.md, Builder section. You are {builder}. Start the wait."
SESSION_NAME = re.compile(r"[a-z0-9][a-z0-9.-]*")
ROLES = ("lead", "builder", "reviewer", "walker", "fixer")
REQUIRED = {
    "project": ("name", "repo", "base", "worktrees", "checks"),
    "gate": ("rubric", "max_rounds", "walk"),
    "budget": ("provider_dollars",),
}


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


def load_config(path=None) -> dict:
    """Read the repo's .colony/colony.toml (or `path`), expand `~` in its paths, and check its keys."""
    path = Path(path) if path else config_path()
    try:
        with open(path, "rb") as f:
            config = tomllib.load(f)
    except FileNotFoundError:
        raise ColonyError(f"{path} is missing: pull the branch that has it, or run `{NAME}` to set this repo up") from None
    except tomllib.TOMLDecodeError as e:
        raise ColonyError(f"{path}: {e}") from None
    for table, keys in REQUIRED.items():
        for key in keys:
            if key not in config.get(table, {}):
                raise ColonyError(f"{path}: [{table}] needs {key!r}")
    for role in ROLES:
        for key in ("model", "effort"):
            if key not in config.get("roles", {}).get(role, {}):
                raise ColonyError(f"{path}: [roles] {role} needs {key!r}")
    if not config.get("accounts"):
        raise ColonyError(f"{path}: needs at least one [accounts.<name>] table")
    for name, account in config["accounts"].items():
        for key in ("config_dir", "person"):
            if key not in account:
                raise ColonyError(f"{path}: [accounts.{name}] needs {key!r}")
        account["config_dir"] = os.path.expanduser(account["config_dir"])
    project = config["project"]
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


def pick_account(config: dict, person: str) -> tuple[str, str]:
    """The person's account with the most room on this computer, as (name, config_dir).

    Accounts whose person is `any` count for everyone, and folders this computer has come first. The lowest
    saved 5-hour usage wins, the earlier account on a tie. When no account has a saved figure, the first one wins.
    """
    mine = [(name, a["config_dir"]) for name, a in config["accounts"].items() if a["person"] in (person, "any")]
    if not mine:
        raise ColonyError(f"{CONFIG_NAME} has no account for {person!r}")
    mine = [(name, folder) for name, folder in mine if Path(folder).is_dir()] or mine
    saved = [(used, i) for i, (_, folder) in enumerate(mine) if (used := five_hour_usage(folder)) is not None]
    return mine[min(saved)[1]] if saved else mine[0]


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


def claude_argv(config: dict, role: str, title: str, config_dir: str, prompt: str) -> list[str]:
    """A session's command line: Remote Control under its title, the role's model and effort, and the first prompt."""
    settings = config["roles"][role]
    argv = ["claude", "--remote-control", title, "--model", settings["model"], "--effort", settings["effort"], prompt]
    # The default folder also drops a CLAUDE_CONFIG_DIR inherited from the caller's shell.
    return ["env", "-u", "CLAUDE_CONFIG_DIR", *argv] if is_default_dir(config_dir) else argv


def launch(config: dict, args, session: str, role: str, prompt: str, cmux_only: bool = False) -> int:
    """Open one session on the person's account with the most room, in a new cmux workspace or in this terminal.

    A dry run prints the command, the env names (never their values) and where it would open, and runs nothing.
    """
    person = person_of(config, args)
    account, config_dir = pick_account(config, person)
    title = f"{config['project']['name']}-{session}"
    env = session_env(person, session, config_dir)
    argv = claude_argv(config, role, title, config_dir, prompt)
    root = str(repo_root())
    in_cmux = not getattr(args, "here", False) and shutil.which("cmux") is not None
    if cmux_only and not in_cmux:
        raise ColonyError(f"open needs cmux on PATH; in a new terminal run: {NAME} join {session}")
    where = f"a new cmux workspace at {root}" if in_cmux else f"this terminal at {root}"
    if args.dry_run:
        print("command:", shlex.join(argv))
        print("env:", " ".join(env))
        print(f"dry run: {title} on account {account}, in {where}")
        return 0
    if shutil.which("claude") is None:
        raise ColonyError("claude is not on PATH")
    print(f"Opening {title} on account {account}, in {where}.", flush=True)
    if in_cmux:
        cmd = ["cmux", "new-workspace", "--name", title, "--cwd", root, "--command", shlex.join(argv)]
        cmd += [part for key, value in env.items() for part in ("--env", f"{key}={value}")]
        return subprocess.run(cmd).returncode
    os.chdir(root)
    os.execvpe(argv[0], argv, {**os.environ, **env})


def setup(args) -> int:
    """First run: an interactive claude session in this terminal whose first message is the setup prompt."""
    root = repo_root()
    prompt = fill_names(package_file("prompts", "setup.md"))
    if args.dry_run:
        print(f"setup plan: {DIR}/{CONFIG_NAME} is missing, so {NAME} sets up {root} in this terminal.")
        print(f"  command: claude <the setup prompt from {NAME} {__version__}, {len(prompt)} characters>")
        print("  it reads the repo, asks at most 5 questions, and writes:")
        print(f"    {DIR}/{CONFIG_NAME}, {DIR}/rules/, {DIR}/playbook.md, and one line in CLAUDE.md after asking")
        print("  then opens one pull request with them. Nothing ran.")
        return 0
    if shutil.which("claude") is None:
        raise ColonyError(f"claude is not on PATH: install Claude Code, then run {NAME} again")
    print(f"No {DIR}/{CONFIG_NAME} yet, so {DISPLAY} starts setup.", flush=True)
    os.chdir(root)
    os.execvp("claude", ["claude", prompt])


def lead(config: dict, args) -> int:
    """Open the person's lead."""
    return launch(config, args, LEAD, "lead", LEAD_PROMPT.replace("{dir}", DIR))


def builder_prompt(name: str) -> str:
    """A builder's first prompt."""
    return BUILDER_PROMPT.replace("{dir}", DIR).replace("{builder}", name)


def open_builder(config: dict, args) -> int:
    """Open a builder on this computer in a new cmux workspace (the lead runs this)."""
    return launch(config, args, args.name, "builder", builder_prompt(args.name), cmux_only=True)


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
        account, folder = pick_account(config, person_of(config, args))
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
    return launch(config, args, args.name, "builder", builder_prompt(args.name))


def batch(config: dict, args) -> int:
    """Take a batch of cards through the loop to a pull request (batch.run_batch)."""
    from colony import batch as runner

    return runner.run_batch(config, args)


def status(config: dict, args) -> int:
    """Print where a batch stands (batch.batch_status)."""
    from colony import batch as runner

    return runner.batch_status(config, args)


def wait(config: dict, args) -> int:
    """Wait for the lines addressed to this session (wait.run)."""
    from colony import wait as watcher

    return watcher.run(config, args)


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


def build_parser() -> argparse.ArgumentParser:
    """The command line: no command for setup or the lead, then join, open, wait, batch and status."""
    parser = argparse.ArgumentParser(prog=NAME, description=f"{DISPLAY}: run with no command to open your lead "
                                     f"(or to set up the repo, the first time).")
    parser.add_argument("--version", action="version", version=f"{DISPLAY} {__version__}")
    parser.add_argument("--person", help=f"whose accounts to use (needed when {CONFIG_NAME} names several people)")
    parser.add_argument("--here", action="store_true", help="open in this terminal even when cmux is on PATH")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and the env names, and run nothing")
    parser.set_defaults(run=lead)
    sub = parser.add_subparsers(dest="command", metavar="command")

    for command, run, text in (("join", join, "open a builder on this computer (paste the line the lead prints)"),
                               ("open", open_builder, "open a builder here in a new cmux workspace (the lead runs it)")):
        p = sub.add_parser(command, help=text)
        p.add_argument("name", type=builder_name, help="the builder's name, such as builder-2")
        p.add_argument("--person", help="whose accounts to use")
        p.add_argument("--dry-run", action="store_true", help="print the command and the env names, and run nothing")
        if command == "join":
            p.add_argument("--here", action="store_true", help="open in this terminal even when cmux is on PATH")
        p.set_defaults(run=run)

    p = sub.add_parser("wait", help=f"wait for the lines addressed to ${SESSION_ENV}, then print them")
    p.set_defaults(run=wait)

    p = sub.add_parser("batch", help="take finished cards through review, checks and a walk to a pull request")
    p.add_argument("--name", required=True, help="the batch name")
    p.add_argument("--card", action="append", required=True, type=card, metavar="N=BRANCH",
                   help="a card's issue number and branch; repeat for each card")
    p.add_argument("--from", dest="from_branch", metavar="BRANCH", help="build on this branch instead of origin/<base>")
    p.add_argument("--person", help="whose accounts the agents use")
    p.add_argument("--dry-run", action="store_true", help="print the plan and run nothing")
    p.set_defaults(run=batch)

    p = sub.add_parser("status", help="show a batch's round, open problems, walk, running steps and minutes")
    p.add_argument("--name", help="the batch name")
    p.set_defaults(run=status)
    return parser


def main(argv=None) -> int:
    """Parse the command line and run one command: setup when the repo has no .colony/colony.toml, else the one asked."""
    args = build_parser().parse_args(argv)
    try:
        if args.command is None and not config_path().exists():
            return setup(args)
        return args.run(load_config(), args) or 0
    except ColonyError as e:
        print(f"{NAME}: {e}", file=sys.stderr)
        return 2
