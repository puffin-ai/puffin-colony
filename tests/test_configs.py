"""Tests for configs.py: this computer's own settings in an untracked layer, settings an upgrade renamed or removed,
and the check settings every command follows: `colony merge`'s scope and cap, and a batch round's cap."""
import argparse
import subprocess
import time
import tomllib

import pytest

from colony import batch, checks, cli, configs, guards, merge
from test_hi import CONFIG, config, home, host  # noqa: F401  (fixtures)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def commit_all(repo, message="setup"):
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)


@pytest.fixture
def tracked(host):
    """The repo with its colony.toml committed."""
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(CONFIG)
    commit_all(host)
    return host


# This computer's own layer


def test_the_local_file_counts_over_the_tracked_one_in_every_worktree_and_git_never_sees_it(home, tracked,
                                                                                           monkeypatch, capsys):
    assert cli.main(["config", "local"]) == 0
    local = tracked / ".colony" / configs.LOCAL
    local.write_text(local.read_text() + '[checks]\ncaps = { fast = 600 }\n[project]\nbase = "main"\n')
    config = cli.load_config()
    assert config["checks"]["caps"] == {"fast": 600} and config["project"]["base"] == "main"
    assert config["project"]["repo"] == "acme/demo"  # the tracked keys stay
    assert git(tracked, "status", "--porcelain") == ""
    tree = tracked.parent / "tree"
    git(tracked, "worktree", "add", "-q", "-b", "w", str(tree))
    monkeypatch.chdir(tree)
    assert cli.load_config()["checks"]["caps"] == {"fast": 600}  # the main checkout's local file counts here too


def test_uncommitted_edits_of_the_tracked_file_move_into_the_local_file(home, tracked, capsys):
    path = tracked / ".colony" / "colony.toml"
    before = cli.load_config()
    path.write_text(CONFIG.replace('checks = "make check"', 'checks = "make check-fast"')
                    .replace("walk = true", 'walk = true\ncheck = "fast"'))
    edited = cli.load_config()
    assert cli.main(["config", "local", "--from-edits"]) == 0
    assert "Moved project.checks, gate.check into .colony/colony.local.toml" in capsys.readouterr().out
    assert path.read_text() == CONFIG and git(tracked, "status", "--porcelain") == ""
    after = cli.load_config()
    assert after == edited and after != before  # the same settings, and the upgrade meets a clean tree


def test_a_local_file_cant_remove_a_key_so_moving_such_an_edit_is_refused(home, tracked):
    (tracked / ".colony" / "colony.toml").write_text(CONFIG.replace("max_rounds = 5\n", ""))
    with pytest.raises(cli.ColonyError, match="remove gate.max_rounds"):
        configs.from_edits(tracked, dry=False)


def test_a_local_file_git_tracks_gets_a_note(home, tracked):
    local = configs.make_local(tracked)
    git(tracked, "add", "-f", str(local))
    notes = configs.briefing(cli.load_config(), tracked)
    assert any(".colony/colony.local.toml is tracked by git" in note for note in notes)


def test_an_upgrade_refused_on_local_edits_names_the_local_file(home, tracked):
    (tracked / ".colony" / "colony.toml").write_text(CONFIG + "\n# mine\n")
    with pytest.raises(cli.ColonyError, match="config local --from-edits` moves them there"):
        guards.upgrade({}, argparse.Namespace(refresh=False, to="v99.0.0", dry_run=False))


# Settings an upgrade renamed or removed


OLD = CONFIG.replace('checks = "make check"', 'checks = "make check"\nweb_checks = "npm test"') + """
[hack]
deploy_environment = "Live"

[people.ana]
prefer_account = "admin"
accounts = ["main"]
"""


def test_old_settings_load_with_a_note_each_and_never_stop_a_command(home, host):
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(OLD)
    config = cli.load_config()
    assert "web_checks" not in config["project"] and config["project"]["deploy_environment"] == "Live"
    assert "prefer_account" not in config["people"]["ana"]
    notes = " | ".join(configs.LAST)
    assert "[project] web_checks in .colony/colony.toml is gone, so colony skips it: name each check area's paths" \
           in notes
    assert "[hack] deploy_environment in .colony/colony.toml is now [project] deploy_environment" in notes
    assert "[people.ana] prefer_account" in notes and "`colony config migrate`" in notes


def test_config_migrate_rewrites_the_tracked_file_and_the_notes_end(home, host, capsys):
    (host / ".colony").mkdir()
    path = host / ".colony" / "colony.toml"
    path.write_text(OLD)
    assert cli.main(["config", "migrate", "--dry-run"]) == 0 and path.read_text() == OLD
    assert cli.main(["config", "migrate"]) == 0
    text = path.read_text()
    assert "# colony: [project] web_checks is gone: name each check area's paths" in text
    assert '# web_checks = "npm test"' in text
    data = tomllib.loads(text)
    assert data["project"]["deploy_environment"] == "Live" and "deploy_environment" not in data["hack"]
    assert "prefer_account" not in data["people"]["ana"] and data["people"]["ana"]["accounts"] == ["main"]
    cli.load_config()
    assert configs.LAST == []
    assert cli.main(["config", "migrate"]) == 0
    assert "needs no migration" in capsys.readouterr().out


def test_a_renamed_key_already_set_at_its_new_place_is_only_commented_out():
    text = '[project]\nname = "x"\ndeploy_environment = "Prod"\n\n[hack]\ndeploy_environment = "Old"\n'
    new, done = configs.migrate_text(text)
    assert tomllib.loads(new)["project"]["deploy_environment"] == "Prod"
    assert done == ["commented out [hack] deploy_environment: [project] deploy_environment is set already"]


def test_a_multi_line_removed_value_is_commented_out_whole():
    text = '[project]\nweb_checks = [\n  "a",\n  "b",\n]\nname = "x"\n'
    new, _ = configs.migrate_text(text)
    assert tomllib.loads(new) == {"project": {"name": "x"}}


def test_upgrade_refresh_migrates_the_config_and_keeps_the_local_file_out_of_every_clone(home, host, monkeypatch):
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(OLD)
    lines = configs.refresh(host)
    assert any("commented out [project] web_checks" in line for line in lines)
    assert configs.LOCAL in (host / ".colony" / ".gitignore").read_text().splitlines()
    assert configs.refresh(host) == []  # nothing left to do


def test_the_notes_show_once_a_day(home, host, capsys):
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(OLD)
    config = cli.load_config()
    assert configs.say(config) and "web_checks" in capsys.readouterr().err
    assert configs.say(config) == []
    assert configs.say(config, always=True)


def test_config_shows_the_layers_the_check_settings_and_the_notes(home, host, capsys):
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(OLD + "\n[checks]\ncaps = { fast = 600 }\n")
    assert cli.main(["config"]) == 0
    out = capsys.readouterr().out
    assert "2. .colony/colony.toml, the team's, which git tracks" in out
    assert "3. .colony/colony.local.toml, not there" in out
    assert "Checks: scope areas, caps fast 10m 00s." in out
    assert "note: [project] web_checks" in out


# Every command follows the configured check settings


def test_a_fast_gates_batch_round_stops_at_the_fast_cap_and_a_full_one_at_the_full_cap(home, config):
    config["checks"] = {"caps": {"fast": 600, "checks": 900, "full": 3600}}
    b = argparse.Namespace(config=config, full=False)
    assert batch.round_cap(b) == 900
    config["gate"]["check"] = "fast"
    assert batch.round_cap(b) == 600  # a fast gate runs the fast check, so the fast cap holds it
    b.full = True
    assert batch.round_cap(b) == 3600


def test_colony_merge_checks_the_merged_change_in_the_configured_scope_with_the_fast_cap(home, host, config):
    config["project"]["fast_check"] = "check {areas}"
    config["checks"] = {"areas": {"web": ["web/"], "api": ["api/"]}, "caps": {"fast": 120}}
    plan, cap = configs.merge_plan(config, host, ["web/page.ts"])
    assert plan.cmd == "check web" and cap == 120  # before, every area ran, with no cap
    config["checks"]["related"] = "pytest {tests}"
    (host / "tests").mkdir()
    (host / "tests" / "test_page.py").write_text("")
    commit_all(host)
    plan, _ = configs.merge_plan(config, host, ["web/page.py"])
    assert plan.cmd.startswith("rc=0; ( check web ) || rc=$?; ( pytest tests/test_page.py ) ||")


def test_colony_merges_check_past_its_cap_is_stopped_and_fails(home, tmp_path):
    started = time.monotonic()
    result = merge.run_check("sleep 30", tmp_path, None, tmp_path / "log", cap=0.5)
    assert time.monotonic() - started < 10
    assert not result.passed and result.summary == "stopped past its cap of 0 s, [checks] caps"
    assert merge.run_check("echo 3 passed", tmp_path, None, tmp_path / "log2").passed


def test_the_cap_settings_are_read_with_their_defaults(config):
    assert configs.cap(config, "fast") == 0
    config["checks"] = {"caps": {"fast": 60}}
    assert configs.cap(config, "fast") == 60 and checks.settings(config)["caps"] == {"fast": 60}
