"""Tests for the command line: config, account choice, setup or lead, join and open."""
import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path

import pytest

from conftest import stub_path
from colony import cli, portable

PACKAGE = Path(str(resources.files("colony")))
CONFIG = """
[project]
name = "demo"
repo = "acme/demo"
base = "dev"
worktrees = "~/trees"
checks = "make check"
[accounts.first]
config_dir = "~/first"
person = "ana"
[roles]
lead = { model = "m", effort = "high" }
builder = { model = "m", effort = "medium" }
reviewer = { model = "m", effort = "high" }
walker = { model = "m", effort = "medium", agent = "ui-check" }
fixer = { model = "m", effort = "medium" }
[gate]
rubric = ["bugs"]
max_rounds = 5
walk = true
[budget]
provider_dollars = 0
"""
ENV_NAMES = ("COLONY_SESSION COLONY_PERSON CLAUDE_CONFIG_DIR CLAUDE_CODE_RETRY_WATCHDOG "
             "CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS CLAUDE_CODE_AUTO_COMPACT_WINDOW")
LEAD_PROMPT = "'Run `colony` and do what it prints, then read .colony/playbook.md, Lead section, and start.'"


SETTINGS_FLAG = re.compile(r" --settings '[^']*'")


def no_settings(out: str) -> str:
    """A dry run's output without the --settings JSON, whose parts the settings tests check."""
    return SETTINGS_FLAG.sub("", out)


def builder_prompt(name):
    """A builder's first prompt as the dry run quotes it, with the line that renames the session to its name."""
    return shlex.quote(f"Read .colony/playbook.md, Builder section. You are {name}. Start the wait. "
                       f"Rename this session in the app's sidebar to {name}, with the app's own rename tool when you "
                       "have one; when you have none, skip this quietly.")


def write_usage(folder: Path, used: float, resets_in: timedelta) -> None:
    """Save a fake Claude Code usage reading in an account folder."""
    folder.mkdir(parents=True, exist_ok=True)
    resets_at = (datetime.now(timezone.utc) + resets_in).isoformat()
    window = {"utilization": used, "resets_at": resets_at}
    (folder / ".claude.json").write_text(json.dumps({"cachedUsageUtilization": {"utilization": {"five_hour": window}}}))


def make_stub(bin_dir: Path, name: str, code: int = 0) -> Path:
    """Put a fake command on PATH that writes its arguments, one per line, to <name>.log and exits with `code`."""
    bin_dir.mkdir(exist_ok=True)
    log = bin_dir / f"{name}.log"
    stub = bin_dir / name
    stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}"\nexit {code}\n')
    stub.chmod(0o755)
    return log


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A temporary HOME, a PATH with a stub folder and no real claude, cmux or gh, and no session env."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", stub_path(tmp_path / 'bin'))
    for key in (cli.SESSION_ENV, cli.PERSON_ENV, "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(key, raising=False)
    # A person at a terminal, unless a test says otherwise: with no cmux, the session opens right here.
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    return tmp_path


@pytest.fixture
def host(home, monkeypatch):
    """A fresh git repo to run in, with no .colony folder yet."""
    repo = home / "host"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.chdir(repo)
    return repo.resolve()


@pytest.fixture
def config(host):
    """The one-account demo config, written to the host's .colony/colony.toml and loaded from there."""
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(CONFIG)
    return cli.load_config()


def run_lead(config, capsys, **flags):
    """Open the lead for ana, as a dry run unless told otherwise, and return its exit code and output."""
    args = argparse.Namespace(person="ana", here=False, dry_run=True)
    vars(args).update(flags)
    code = cli.lead(config, args)
    return code, capsys.readouterr().out


def builder_args(name="builder-2", **flags):
    """The args the parser makes for `colony join` or `colony open`."""
    args = argparse.Namespace(name=name, person="ana", here=False, dry_run=True)
    vars(args).update(flags)
    return args


def run_colony(home, *args, cwd):
    """Run the installed command line as a new process, with only HOME and PATH set, and no terminal on stdin."""
    return subprocess.run([sys.executable, "-m", "colony", *args], capture_output=True, text=True, cwd=cwd,
                          env={"HOME": str(home), "PATH": stub_path(home / 'bin')}, stdin=subprocess.DEVNULL)


def test_the_example_config_loads(home):
    config = cli.load_config(PACKAGE / "colony.toml.example")
    assert config["project"]["preset"] == "lean"
    assert config["accounts"]["main"]["config_dir"] == str(home / ".claude")


def test_config_is_read_from_the_repo_and_expands_home(home, config):
    assert config["accounts"]["first"]["config_dir"] == str(home / "first")
    assert config["project"]["worktrees"] == str(home / "trees")


def test_config_names_a_missing_key(host):
    (host / "colony.toml").write_text(CONFIG.replace('base = "dev"\n', ""))
    with pytest.raises(cli.ColonyError, match="'base'"):
        cli.load_config(host / "colony.toml")


def test_config_needs_the_lead_role(host):
    (host / "colony.toml").write_text(CONFIG.replace("lead = ", "orchestrator = "))
    with pytest.raises(cli.ColonyError, match="lead needs 'model'"):
        cli.load_config(host / "colony.toml")


def accounts(home, *people):
    """A config whose accounts a, b, c... live in temporary folders, for the given people."""
    names = "abcd"[: len(people)]
    return {"accounts": {n: {"config_dir": str(home / n), "person": p} for n, p in zip(names, people)}}


def test_pick_account_takes_lowest_saved_usage_and_counts_any(home):
    config = accounts(home, "ana", "ana", "bo", "any")
    write_usage(home / "a", 70, timedelta(hours=2))
    write_usage(home / "b", 20, timedelta(hours=2))
    write_usage(home / "c", 0, timedelta(hours=2))  # another person's account never counts
    write_usage(home / "d", 10, timedelta(hours=2))
    assert cli.pick_account(config, "ana") == ("d", str(home / "d"))


def test_pick_account_counts_a_reset_window_as_empty(home):
    config = accounts(home, "ana", "ana")
    write_usage(home / "a", 90, timedelta(hours=-1))
    write_usage(home / "b", 20, timedelta(hours=2))
    assert cli.pick_account(config, "ana")[0] == "a"


def test_pick_account_falls_back_to_first_without_saved_usage(home):
    config = accounts(home, "bo", "ana", "ana")
    assert cli.pick_account(config, "ana") == ("b", str(home / "b"))


def test_pick_account_prefers_the_folders_this_computer_has(home):
    config = accounts(home, "ana", "ana")
    (home / "b").mkdir()
    assert cli.pick_account(config, "ana")[0] == "b"


def usage_stub(home: Path) -> Path:
    """Put a fake claude on PATH that logs `<its CLAUDE_CONFIG_DIR or default>|<its arguments>`, one run a line."""
    bin_dir = home / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = bin_dir / "claude.log"
    stub = bin_dir / "claude"
    stub.write_text(f'#!/bin/sh\necho "${{CLAUDE_CONFIG_DIR:-default}}|$*" >> "{log}"\n')
    stub.chmod(0o755)
    return log


def sign_in(folder: Path, fetched_ago: float | None = None) -> None:
    """Save a Claude Code login in an account folder, with a usage reading fetched that many seconds ago."""
    folder.mkdir(parents=True, exist_ok=True)
    state: dict = {"oauthAccount": {"emailAddress": "a@example.com"}}
    if fetched_ago is not None:
        state["cachedUsageUtilization"] = {"fetchedAtMs": (time.time() - fetched_ago) * 1000, "utilization": {}}
    (folder / ".claude.json").write_text(json.dumps(state))


def test_refresh_usage_fetches_only_signed_in_folders_with_a_stale_or_missing_reading(home, monkeypatch):
    monkeypatch.delenv(cli.NO_REFRESH_ENV)
    monkeypatch.setattr(cli, "_fetched", {})
    log = usage_stub(home)
    sign_in(home / "stale", fetched_ago=cli.USAGE_STALE + 60)
    sign_in(home / "missing")
    sign_in(home / "fresh", fetched_ago=30)
    (home / "out").mkdir()  # no login
    cli.refresh_usage([str(home / name) for name in ("stale", "missing", "fresh", "out", "gone")])
    assert sorted(log.read_text().splitlines()) == [f"{home / 'missing'}|-p /usage", f"{home / 'stale'}|-p /usage"]


def test_refresh_usage_runs_the_default_folder_without_a_settings_folder(home, monkeypatch):
    monkeypatch.delenv(cli.NO_REFRESH_ENV)
    monkeypatch.setattr(cli, "_fetched", {})
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / "other"))
    log = usage_stub(home)
    (home / ".claude").mkdir()
    (home / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "a@example.com"}}))
    cli.refresh_usage([str(home / ".claude")])
    assert log.read_text().splitlines() == ["default|-p /usage"]


def test_refresh_usage_fetches_a_folder_once_per_stale_window(home, monkeypatch):
    """A plan whose /usage saves no windows keeps a stale reading, so the same process waits before asking again."""
    monkeypatch.delenv(cli.NO_REFRESH_ENV)
    monkeypatch.setattr(cli, "_fetched", {})
    log = usage_stub(home)
    sign_in(home / "a")
    cli.refresh_usage([str(home / "a")])
    cli.refresh_usage([str(home / "a")])
    assert len(log.read_text().splitlines()) == 1


def test_refresh_usage_is_off_when_its_env_is_set(home):
    log = usage_stub(home)
    sign_in(home / "a")
    cli.refresh_usage([str(home / "a")])
    assert not log.exists()


def test_pick_account_refuses_an_unknown_person(home):
    with pytest.raises(cli.ColonyError, match="'zed'"):
        cli.pick_account(accounts(home, "ana"), "zed")


def test_person_comes_from_the_flag_then_the_session_env_then_the_git_user(home, monkeypatch):
    config = accounts(home, "ana", "bo")
    monkeypatch.setattr(cli, "git_user", lambda: {"bo"})
    assert cli.person_of(config, argparse.Namespace(person="ana")) == "ana"
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    assert cli.person_of(config, argparse.Namespace(person=None)) == "ana"
    monkeypatch.delenv(cli.PERSON_ENV)
    assert cli.person_of(config, argparse.Namespace(person=None)) == "bo"
    monkeypatch.setattr(cli, "git_user", lambda: {"zed"})
    with pytest.raises(cli.ColonyError, match="--person ana or bo"):
        cli.person_of(config, argparse.Namespace(person=None))


def test_no_command_shows_the_setup_plan_when_the_repo_has_no_config(host, capsys):
    claude_log = make_stub(host.parent / "bin", "claude")
    assert cli.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"setup plan: .colony/colony.toml is missing, so colony sets up {host} in this terminal." in out
    assert ".colony/colony.toml, .colony/rules/, .colony/playbook.md" in out
    assert not claude_log.exists()


def test_no_command_opens_the_lead_when_the_repo_has_a_config(config, capsys):
    assert cli.main(["--dry-run", "--person", "ana"]) == 0
    out = capsys.readouterr().out
    assert f"command: claude --remote-control demo-lead --model m --effort high --permission-mode auto {LEAD_PROMPT}" in no_settings(out)
    assert "setup" not in out


def test_outside_a_git_repo_every_command_says_to_run_inside_a_clone(home, capsys, monkeypatch):
    monkeypatch.chdir(home)
    assert cli.main(["--dry-run"]) == 2
    assert "run colony inside a clone of your repo" in capsys.readouterr().err


def test_a_command_other_than_setup_names_the_missing_config(host, capsys):
    assert cli.main(["status"]) == 2
    assert f"{host / '.colony' / 'colony.toml'} is missing: pull the branch that has it" in capsys.readouterr().err


def test_setup_opens_claude_with_the_setup_prompt_filled_in(home, host):
    claude_log = make_stub(home / "bin", "claude")
    run = run_colony(home, cwd=host)
    assert run.returncode == 0, run.stderr
    assert "No .colony/colony.toml yet, so Puffin Colony starts setup." in run.stdout
    prompt = claude_log.read_text()
    assert prompt.startswith("You are setting up Puffin Colony in this repository.")
    assert f"Copy `{PACKAGE}/colony.toml.example` to `.colony/colony.toml`" in prompt
    assert f"`{PACKAGE}/presets/lean/rules/`" in prompt and f"`{PACKAGE}/presets/<preset>/core.md`" in prompt
    assert "This repo runs Puffin Colony: read .colony/playbook.md." in prompt
    for placeholder in ("{name}", "{dir}", "{package}", "{display}"):
        assert placeholder not in prompt
    assert "{fast_check}" in prompt  # the playbook's own placeholders stay for the session to fill


def test_lead_dry_run_without_cmux_uses_this_terminal_and_hides_values(home, config, capsys):
    claude_log = make_stub(home / "bin", "claude")
    code, out = run_lead(config, capsys)
    assert code == 0
    assert f"command: claude --remote-control demo-lead --model m --effort high --permission-mode auto {LEAD_PROMPT}" in no_settings(out)
    assert f"env: {ENV_NAMES}\n" in out
    assert "dry run: demo-lead on account first, in this terminal" in out
    assert str(home / "first") not in out and "21600000" not in out
    assert not claude_log.exists()


def test_lead_dry_run_with_cmux_opens_a_workspace_and_runs_nothing(home, config, capsys):
    cmux_log = make_stub(home / "bin", "cmux")
    code, out = run_lead(config, capsys)
    assert code == 0 and "in a new cmux workspace" in out
    assert not cmux_log.exists() or cmux_log.read_text().split() == ["workspace", "list"]  # only the probe ran


def test_lead_opens_cmux_from_the_app_when_it_is_not_on_path(home, config, capsys, monkeypatch):
    app = home / "cmux.app" / "bin"
    app.mkdir(parents=True)
    cmux_log = make_stub(app, "cmux")
    monkeypatch.setattr(cli, "CMUX_APP", app / "cmux")
    make_stub(home / "bin", "claude")
    code, out = run_lead(config, capsys, dry_run=False)
    assert code == 0 and "in a new cmux workspace" in out
    assert cmux_log.read_text().splitlines()[:3] == ["new-workspace", "--name", "demo-lead"]


def test_here_forces_this_terminal_when_cmux_is_on_path(home, config, capsys):
    cmux_log = make_stub(home / "bin", "cmux")
    _, out = run_lead(config, capsys, here=True)
    assert "in this terminal" in out
    assert not cmux_log.exists() or cmux_log.read_text().split() == ["workspace", "list"]  # only the probe ran


def test_lead_opens_cmux_with_the_env_and_prints_no_values(home, host, config, capsys):
    cmux_log = make_stub(home / "bin", "cmux")
    claude_log = make_stub(home / "bin", "claude")
    code, out = run_lead(config, capsys, dry_run=False)
    args = cmux_log.read_text().splitlines()
    assert code == 0
    assert args[:5] == ["new-workspace", "--name", "demo-lead", "--cwd", str(host)]
    assert args[args.index("--command") + 1].startswith("env -u ANTHROPIC_API_KEY claude --remote-control demo-lead ")
    for pair in ("COLONY_SESSION=lead", "COLONY_PERSON=ana", f"CLAUDE_CONFIG_DIR={home / 'first'}",
                 "CLAUDE_CODE_RETRY_WATCHDOG=1", "CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS=21600000",
                 "CLAUDE_CODE_AUTO_COMPACT_WINDOW=250000"):
        assert args[args.index(pair) - 1] == "--env"
    assert str(home / "first") not in out
    assert not claude_log.exists()


def live_lead(name="ana-main-lead"):
    """A lead alive on this computer by its heartbeat, as `colony claim` leaves it."""
    from colony import wait

    wait.beat("demo", name, "first", "token0000000", named=True)


def test_join_dry_run_says_what_is_missing_and_shows_the_builder(home, config, capsys):
    gh_log = make_stub(home / "bin", "gh", code=1)
    live_lead()
    assert cli.join(config, builder_args(lead=None)) == 0
    out = capsys.readouterr().out
    assert "missing: a clone of acme/demo: run `gh repo clone acme/demo`, then `colony join` inside it" in out
    assert "missing: claude: install Claude Code" in out
    assert "missing: gh auth: run `gh auth login`" in out
    assert gh_log.read_text().split() == ["auth", "status"]
    assert "Joining ana-main-lead as builder-1." in out
    assert f"command: claude --remote-control demo-builder-1 --model m --effort medium --permission-mode auto {builder_prompt('builder-1')}" in no_settings(out)
    assert f"env: {ENV_NAMES.replace('COLONY_PERSON', 'COLONY_PERSON COLONY_LEAD')}\n" in out


def test_join_refuses_to_open_while_the_account_is_not_signed_in(home, host, config, capsys):
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:acme/demo.git"], cwd=host, check=True)
    make_stub(home / "bin", "gh")
    claude_log = make_stub(home / "bin", "claude")
    cmux_log = make_stub(home / "bin", "cmux")
    live_lead()
    assert cli.join(config, builder_args(lead=None, dry_run=False)) == 1
    out = capsys.readouterr().out
    assert out.strip().splitlines()[-1] == \
        "missing: the claude login for account first: open claude on that account and run /login"
    assert not claude_log.exists() and not cmux_log.exists()


def test_join_opens_the_builder_once_nothing_is_missing(home, host, config, capsys):
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/acme/demo.git"], cwd=host, check=True)
    make_stub(home / "bin", "gh")
    make_stub(home / "bin", "claude")
    cmux_log = make_stub(home / "bin", "cmux")
    (home / "first").mkdir()
    (home / "first" / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "ana@example.test"}}))
    live_lead()
    assert cli.join(config, builder_args(lead=None, dry_run=False)) == 0
    out = capsys.readouterr().out
    assert "missing" not in out and "Opening demo-builder-1 on account first" in out
    args = cmux_log.read_text().splitlines()
    assert args[:3] == ["new-workspace", "--name", "demo-builder-1"]
    assert "COLONY_SESSION=builder-1" in args and "COLONY_PERSON=ana" in args
    assert "COLONY_LEAD=ana-main-lead" in args  # a helper belongs to one lead
    assert set(json.loads((home / ".colony" / "demo" / "ana-main-lead-opened.json").read_text())) == {"builder-1"}


def test_open_dry_run_opens_the_builder_in_cmux(home, config, capsys):
    cmux_log = make_stub(home / "bin", "cmux")
    assert cli.open_builder(config, builder_args("builder-1")) == 0
    out = capsys.readouterr().out
    assert f"--model m --effort medium --permission-mode auto {builder_prompt('builder-1')}" in no_settings(out)
    assert "dry run: demo-builder-1 on account first, in a new cmux workspace" in out
    assert not cmux_log.exists() or cmux_log.read_text().split() == ["workspace", "list"]  # only the probe ran


def test_open_without_cmux_or_a_terminal_opens_a_background_session(home, config, capsys, monkeypatch):
    """The lead runs `colony open` inside its own session, with no cmux to talk to and no terminal."""
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    cli.open_builder(config, builder_args("builder-1"))
    assert "in a background session" in capsys.readouterr().out


def test_open_from_a_named_lead_expects_the_helpers_status_and_a_dry_run_does_not(home, host, config, monkeypatch):
    make_stub(home / "bin", "claude")
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setenv("COLONY_LEAD", "ana-main-lead")
    opened = home / ".colony" / "demo" / "ana-main-lead-opened.json"
    cli.open_builder(config, builder_args("builder-1"))
    assert not opened.exists()
    cli.open_builder(config, builder_args("builder-1", dry_run=False))
    assert set(json.loads(opened.read_text())) == {"builder-1"}


def test_a_background_session_runs_claude_with_bg_and_its_name(home, host, config, monkeypatch):
    claude_log = make_stub(home / "bin", "claude")
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    cli.open_builder(config, builder_args("builder-1", dry_run=False))
    args = claude_log.read_text().splitlines()
    assert args[:4] == ["--bg", "--name", "demo-builder-1", "--remote-control"]
    assert "--permission-mode" in args and args[args.index("--permission-mode") + 1] == "auto"


def test_a_background_session_carries_its_own_session_in_its_settings_not_the_daemons(home, host, config,
                                                                                         monkeypatch):
    """The live bug: `claude --bg` hands the session to a spare process of a daemon the lead started, whose
    environment says COLONY_SESSION=lead, so a spec session's permission pop-up posted nothing. The session's own
    env rides in --settings, which overrides what the spare inherited."""
    claude_log = make_stub(home / "bin", "claude")
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setenv(cli.SESSION_ENV, "lead")  # the daemon's, and so the spare's, environment
    cli.open_builder(config, builder_args("builder-1", dry_run=False))
    args = claude_log.read_text().splitlines()
    settings = json.loads(args[args.index("--settings") + 1])
    assert settings["env"][cli.SESSION_ENV] == "builder-1" and settings["env"][cli.PERSON_ENV] == "ana"
    assert "CLAUDE_CONFIG_DIR" not in settings["env"]  # it picks the account, so it stays in the process env


def test_routine_git_gh_and_colony_commands_never_stop_a_session_to_ask(home, host, config, monkeypatch):
    claude_log = make_stub(home / "bin", "claude")
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    cli.open_builder(config, builder_args("builder-1", dry_run=False))
    args = claude_log.read_text().splitlines()
    permissions = json.loads(args[args.index("--settings") + 1])["permissions"]
    assert {"Bash(git:*)", "Bash(gh:*)", "Bash(colony:*)"} <= set(permissions["allow"])
    assert {"Bash(git push --force:*)", "Bash(git push -f:*)", "Bash(git push origin dev:*)"} <= set(
        permissions["deny"])
    assert str(home / "trees") in permissions["additionalDirectories"]  # worktrees = "~/trees"
    assert str(host.parent) in permissions["additionalDirectories"]  # the playbook's ../<name>-<n>
    assert args.index("--settings") < args.index("--permission-mode") < len(args) - 1  # the prompt stays last


def test_a_dry_run_shows_the_settings_env_names_but_never_their_values(home, config, capsys):
    _, out = run_lead(config, capsys)
    shown = json.loads(re.search(r"--settings '([^']*)'", out)[1])
    assert set(shown["env"]) >= {cli.SESSION_ENV, cli.PERSON_ENV} and set(shown["env"].values()) == {"…"}


def test_cmux_that_refuses_this_process_counts_as_no_cmux(home, config, capsys):
    make_stub(home / "bin", "cmux", code=1)
    _, out = run_lead(config, capsys)
    assert "in this terminal" in out


@pytest.mark.parametrize("name", ["lead", "Builder 2", "x_y"])
def test_a_builder_name_refuses_the_lead_and_odd_names(name, capsys):
    with pytest.raises(SystemExit):
        cli.main(["open", name, "--dry-run"])
    assert "not a builder name" in capsys.readouterr().err


def test_cli_dry_run_on_the_default_folder_leaves_config_dir_unset(home, host, config):
    (host / ".colony" / "colony.toml").write_text(CONFIG.replace('"~/first"', '"~/.claude"'))
    claude_log = make_stub(home / "bin", "claude")
    # A cmux that refuses the probe, so a cmux app on the machine running the suite is not used.
    make_stub(home / "bin", "cmux", code=1)
    run = run_colony(home, "--person", "ana", "--dry-run", cwd=host)
    assert run.returncode == 0, run.stderr
    # Windows has no `env`, so there the session drops CLAUDE_CONFIG_DIR from its own environment instead.
    unset = "" if portable.WINDOWS else "env -u CLAUDE_CONFIG_DIR "
    assert f"command: {unset}claude --remote-control demo-lead" in run.stdout
    assert "env: COLONY_SESSION COLONY_PERSON CLAUDE_CODE_RETRY_WATCHDOG " in run.stdout
    assert "on account first, in a background session" in run.stdout  # a subprocess has no terminal
    assert not claude_log.exists()


def test_the_version_comes_from_the_package(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip() == "Puffin Colony 0.3.0"


def test_lead_keeps_the_api_key_only_when_the_config_says_so(home, host, config, capsys):
    """A set ANTHROPIC_API_KEY bills that key instead of the subscription, so it is dropped by default."""
    cmux_log = make_stub(home / "bin", "cmux")
    make_stub(home / "bin", "claude")
    config["budget"]["use_api_key"] = True
    run_lead(config, capsys, dry_run=False)
    args = cmux_log.read_text().splitlines()
    assert args[args.index("--command") + 1].startswith("claude --remote-control demo-lead ")


# Colony 0.2's wiring: every command, the researcher and spec sessions, their roles, and the account choice

COMMANDS = ("join", "open", "helpers", "view", "claim", "image", "take", "research", "spec", "tester", "wait", "say", "post", "batch", "status", "merge", "sync", "tier",
            "needs", "handover", "stats", "retro", "board", "check-docs", "suppressions", "hooks", "who", "whoami",
            "tidy", "idea", "card", "release", "setup", "skill-install", "tools")


def test_the_command_line_holds_every_tracks_commands(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    sub = next(a for a in cli.build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    assert tuple(sub.choices) == COMMANDS
    for command in COMMANDS:
        assert f"\n    {command} " in out, command


def test_research_opens_a_researcher_whose_brief_holds_the_question(config, capsys):
    assert cli.main(["research", "Which queue fits a 10k jobs a day load?", "--dry-run", "--person", "ana"]) == 0
    out = capsys.readouterr().out
    assert "command: claude --remote-control demo-researcher --model m --effort medium " in out
    assert "You are the researcher for demo." in out
    assert "The question: Which queue fits a 10k jobs a day load?" in out
    assert "`knowledge/.types/research-report.md`" in out
    assert "{question}" not in out and "{knowledge}" not in out and "{project}" not in out
    assert "dry run: demo-researcher on account first" in out


def test_tester_opens_a_tester_whose_brief_holds_the_release(config, capsys):
    url = "https://github.com/acme/demo/pull/20"
    assert cli.main(["tester", url, "--dry-run", "--person", "ana"]) == 0
    out = capsys.readouterr().out
    assert "command: claude --remote-control demo-tester --model m --effort medium " in out
    assert "You are the tester for demo." in out and f"The release: {url}" in out
    assert 'lead "blocked: <the step, and whose it is>"' in out and "one findings issue" in out
    assert "{release}" not in out and "{project}" not in out
    assert "dry run: demo-tester on account first" in out


def test_spec_names_the_vault_colony_toml_sets(host, capsys):
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(CONFIG + '[knowledge]\nvault = "docs/vault/"\n')
    assert cli.main(["spec", "  dark   mode ", "--dry-run", "--person", "ana"]) == 0
    out = capsys.readouterr().out
    assert "You are the spec agent for demo." in out and "The feature: dark mode" in out
    assert "`docs/vault/specs/plans/<feature>/`" in out
    assert "dry run: demo-spec on account first" in out


def test_a_brief_setup_copied_into_the_repo_wins_over_the_package(config, host, capsys):
    (host / ".colony" / "prompts").mkdir()
    (host / ".colony" / "prompts" / "spec.md").write_text("Our own spec brief for demo.\n\nThe feature: {feature}\n")
    assert cli.main(["spec", "export to CSV", "--dry-run", "--person", "ana"]) == 0
    out = capsys.readouterr().out
    assert "Our own spec brief for demo." in out and "The feature: export to CSV" in out
    assert "You are the spec agent" not in out


@pytest.mark.parametrize("brief, error", [
    ("The question: {question}\nUnknown: {nope}\n", ".colony/prompts/researcher.md: the template needs a value for {nope}"),
    (None, "colony research needs the question, in quotes"),
])
def test_a_brief_with_an_unknown_placeholder_or_an_empty_request_is_refused(config, host, capsys, brief, error):
    if brief:
        (host / ".colony" / "prompts").mkdir()
        (host / ".colony" / "prompts" / "researcher.md").write_text(brief)
    assert cli.main(["research", "?" if brief else "   ", "--dry-run", "--person", "ana"]) == 2
    assert error in capsys.readouterr().err


def test_a_config_without_the_researcher_spec_or_tester_role_takes_the_builders_settings(config):
    assert "researcher" not in CONFIG and "spec =" not in CONFIG and "tester" not in CONFIG  # an 0.1 colony.toml loads
    for role in (cli.RESEARCHER, cli.SPEC, cli.TESTER):
        assert config["roles"][role] == config["roles"]["builder"] == {"model": "m", "effort": "medium"}
    config["roles"]["builder"]["effort"] = "low"
    assert config["roles"][cli.SPEC]["effort"] == "medium"  # a copy, not the builder's own table


def test_a_researcher_role_colony_toml_names_needs_its_model_and_effort(host):
    (host / "colony.toml").write_text(CONFIG.replace("[gate]", 'researcher = { model = "m" }\n[gate]'))
    with pytest.raises(cli.ColonyError, match=r"\[roles\] researcher needs 'effort'"):
        cli.load_config(host / "colony.toml")
    (host / "colony.toml").write_text(CONFIG.replace("[gate]", 'spec = { model = "s", effort = "max" }\n[gate]'))
    assert cli.load_config(host / "colony.toml")["roles"]["spec"] == {"model": "s", "effort": "max"}


def test_the_example_config_holds_the_new_tables(home):
    from colony import vault

    config = cli.load_config(PACKAGE / "colony.toml.example")
    assert config["roles"]["researcher"]["model"] and config["roles"]["spec"]["effort"]
    assert config["roles"]["tester"]["model"] and config["roles"]["tester"]["effort"]
    assert "transport" not in config["messages"]  # every line goes by GitHub
    assert "board" in config and "prefer_account" not in config["project"]
    knowledge = config["knowledge"]
    assert knowledge["vault"] == "knowledge"
    assert {name: knowledge[name] for name in vault.CHECKS} == vault.CHECKS  # each check, with its default mode
    assert vault.read_settings(config).vault == "knowledge"


def test_every_shipped_rule_fits_the_example_configs_rule_budgets(home):
    from colony import vault

    settings = vault.read_settings(cli.load_config(PACKAGE / "colony.toml.example"))
    for path in [*(PACKAGE / "presets").glob("*/rules/*.md"), *(PACKAGE / "knowledge" / "rules").glob("*.md")]:
        budget = settings.rule_budgets.get(path.stem, settings.rule_chars)
        assert len(path.read_text()) <= budget, f"{path.relative_to(PACKAGE)} runs past its budget of {budget}"


def test_prefer_account_and_drain_are_gone_and_an_old_config_still_loads(host):
    (host / "colony.toml").write_text(CONFIG.replace('checks = "make check"', 'checks = "make check"\n'
                                                                             'prefer_account = "admin"\ndrain = true'))
    config = cli.load_config(host / "colony.toml")  # the live config still has the line, so it must keep loading
    assert cli.pick_account(config, "ana")[0] == "first"  # and the line no longer steers the pick


def test_a_people_table_must_name_real_accounts(host):
    (host / "colony.toml").write_text(CONFIG + '\n[people.ana]\naccounts = ["first", "ghost"]\n')
    with pytest.raises(cli.ColonyError, match=r"\[people.ana\] names the account 'ghost'"):
        cli.load_config(host / "colony.toml")


def test_quiet_lead_must_be_true_or_false(host):
    (host / "colony.toml").write_text(CONFIG + '\n[people.ana]\nquiet_lead = "yes"\n')
    with pytest.raises(cli.ColonyError, match=r"\[people.ana\] quiet_lead is true or false"):
        cli.load_config(host / "colony.toml")


@pytest.mark.parametrize("argv", [["--account", "admin"], ["join", "builder-2", "--account", "admin"],
                                  ["open", "builder-2", "--account", "admin"], ["research", "q", "--account", "admin"],
                                  ["spec", "f", "--account", "admin"],
                                  ["batch", "--name", "b", "--card", "1=x", "--account", "admin"]])
def test_every_command_that_opens_a_session_or_a_batch_takes_account(argv):
    assert cli.build_parser().parse_args(argv).account == "admin"


def test_account_overrides_the_pick_and_refuses_an_unknown_one(home, config, capsys):
    config["accounts"]["admin"] = {"config_dir": str(home / "admin"), "person": "bo"}
    code, out = run_lead(config, capsys, account="admin")
    assert code == 0 and "on account admin" in out
    assert "CLAUDE_CONFIG_DIR" in out.split("env:", 1)[1].splitlines()[0]
    with pytest.raises(cli.ColonyError, match="--account 'nobody' is not in colony.toml: choose from first, admin"):
        run_lead(config, capsys, account="nobody")


def test_account_reaches_the_lead_from_the_command_line(home, host, capsys):
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(CONFIG + '[accounts.admin]\nconfig_dir = "~/admin"\nperson = "ana"\n')
    assert cli.main(["--dry-run", "--person", "ana", "--account", "admin"]) == 0
    assert "dry run: demo-lead on account admin" in capsys.readouterr().out

