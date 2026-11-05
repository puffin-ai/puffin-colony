"""Tests for the command line: config, account choice, setup or lead, join and open."""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path

import pytest

from colony import cli

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
LEAD_PROMPT = "'Read .colony/playbook.md, Lead section, and start.'"


def builder_prompt(name):
    """A builder's first prompt as the dry run quotes it."""
    return f"'Read .colony/playbook.md, Builder section. You are {name}. Start the wait.'"


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
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")
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
    """Run the installed command line as a new process, with only HOME and PATH set."""
    return subprocess.run([sys.executable, "-m", "colony", *args], capture_output=True, text=True, cwd=cwd,
                          env={"HOME": str(home), "PATH": f"{home / 'bin'}:/usr/bin:/bin"})


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
    assert f"command: claude --remote-control demo-lead --model m --effort high --permission-mode auto {LEAD_PROMPT}" in out
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
    assert f"copy `{PACKAGE}/colony.toml.example`" in prompt
    assert f"`{PACKAGE}/presets/lean/` into `.colony/rules/`" in prompt
    assert "This repo runs Puffin Colony: read .colony/playbook.md." in prompt
    for placeholder in ("{name}", "{dir}", "{package}", "{display}"):
        assert placeholder not in prompt
    assert "{fast_check}" in prompt  # the playbook's own placeholders stay for the session to fill


def test_lead_dry_run_without_cmux_uses_this_terminal_and_hides_values(home, config, capsys):
    claude_log = make_stub(home / "bin", "claude")
    code, out = run_lead(config, capsys)
    assert code == 0
    assert f"command: claude --remote-control demo-lead --model m --effort high --permission-mode auto {LEAD_PROMPT}" in out
    assert f"env: {ENV_NAMES}\n" in out
    assert "dry run: demo-lead on account first, in this terminal" in out
    assert str(home / "first") not in out and "21600000" not in out
    assert not claude_log.exists()


def test_lead_dry_run_with_cmux_opens_a_workspace_and_runs_nothing(home, config, capsys):
    cmux_log = make_stub(home / "bin", "cmux")
    code, out = run_lead(config, capsys)
    assert code == 0 and "in a new cmux workspace" in out
    assert not cmux_log.exists() or cmux_log.read_text().split() == ["workspace", "list"]  # only the probe ran


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


def test_join_dry_run_says_what_is_missing_and_shows_the_builder(home, config, capsys):
    gh_log = make_stub(home / "bin", "gh", code=1)
    assert cli.join(config, builder_args()) == 0
    out = capsys.readouterr().out
    assert "missing: a clone of acme/demo: run `gh repo clone acme/demo`, then `colony join builder-2` inside it" in out
    assert "missing: claude: install Claude Code" in out
    assert "missing: gh auth: run `gh auth login`" in out
    assert gh_log.read_text().split() == ["auth", "status"]
    assert f"command: claude --remote-control demo-builder-2 --model m --effort medium --permission-mode auto {builder_prompt('builder-2')}" in out
    assert f"env: {ENV_NAMES}\n" in out


def test_join_refuses_to_open_while_the_account_is_not_signed_in(home, host, config, capsys):
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:acme/demo.git"], cwd=host, check=True)
    make_stub(home / "bin", "gh")
    claude_log = make_stub(home / "bin", "claude")
    cmux_log = make_stub(home / "bin", "cmux")
    assert cli.join(config, builder_args(dry_run=False)) == 1
    out = capsys.readouterr().out
    assert out.strip() == "missing: the claude login for account first: open claude on that account and run /login"
    assert not claude_log.exists() and not cmux_log.exists()


def test_join_opens_the_builder_once_nothing_is_missing(home, host, config, capsys):
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/acme/demo.git"], cwd=host, check=True)
    make_stub(home / "bin", "gh")
    make_stub(home / "bin", "claude")
    cmux_log = make_stub(home / "bin", "cmux")
    (home / "first").mkdir()
    (home / "first" / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "ana@example.test"}}))
    assert cli.join(config, builder_args(dry_run=False)) == 0
    out = capsys.readouterr().out
    assert "missing" not in out and "Opening demo-builder-2 on account first" in out
    args = cmux_log.read_text().splitlines()
    assert args[:3] == ["new-workspace", "--name", "demo-builder-2"]
    assert "COLONY_SESSION=builder-2" in args and "COLONY_PERSON=ana" in args


def test_open_dry_run_opens_the_builder_in_cmux(home, config, capsys):
    cmux_log = make_stub(home / "bin", "cmux")
    assert cli.open_builder(config, builder_args("builder-1")) == 0
    out = capsys.readouterr().out
    assert f"--model m --effort medium --permission-mode auto {builder_prompt('builder-1')}" in out
    assert "dry run: demo-builder-1 on account first, in a new cmux workspace" in out
    assert not cmux_log.exists() or cmux_log.read_text().split() == ["workspace", "list"]  # only the probe ran


def test_open_without_cmux_or_a_terminal_opens_a_background_session(home, config, capsys, monkeypatch):
    """The lead runs `colony open` inside its own session, with no cmux to talk to and no terminal."""
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    cli.open_builder(config, builder_args("builder-1"))
    assert "in a background session" in capsys.readouterr().out


def test_a_background_session_runs_claude_with_bg_and_its_name(home, host, config, monkeypatch):
    claude_log = make_stub(home / "bin", "claude")
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    cli.open_builder(config, builder_args("builder-1", dry_run=False))
    args = claude_log.read_text().splitlines()
    assert args[:4] == ["--bg", "--name", "demo-builder-1", "--remote-control"]
    assert "--permission-mode" in args and args[args.index("--permission-mode") + 1] == "auto"


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
    run = run_colony(home, "--person", "ana", "--dry-run", cwd=host)
    assert run.returncode == 0, run.stderr
    assert "command: env -u CLAUDE_CONFIG_DIR claude --remote-control demo-lead" in run.stdout
    assert "env: COLONY_SESSION COLONY_PERSON CLAUDE_CODE_RETRY_WATCHDOG " in run.stdout
    assert "on account first, in a background session" in run.stdout  # a subprocess has no terminal
    assert not claude_log.exists()


def test_the_version_comes_from_the_package(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip() == "Puffin Colony 0.1.0"


LEAN = ("coding", "testing", "security", "performance", "accessibility", "git")


@pytest.mark.parametrize("name", LEAN)
def test_each_lean_rule_is_short_and_has_must_and_must_not_lines(name):
    text = (PACKAGE / "presets" / "lean" / f"{name}.md").read_text()
    assert len(text.split()) < 400
    assert "## Must\n" in text and "## Must not\n" in text


def test_the_lean_preset_holds_only_its_six_files():
    assert sorted(p.stem for p in (PACKAGE / "presets" / "lean").iterdir()) == sorted(LEAN)


def test_lead_keeps_the_api_key_only_when_the_config_says_so(home, host, config, capsys):
    """A set ANTHROPIC_API_KEY bills that key instead of the subscription, so it is dropped by default."""
    cmux_log = make_stub(home / "bin", "cmux")
    make_stub(home / "bin", "claude")
    config["budget"]["use_api_key"] = True
    run_lead(config, capsys, dry_run=False)
    args = cmux_log.read_text().splitlines()
    assert args[args.index("--command") + 1].startswith("claude --remote-control demo-lead ")
