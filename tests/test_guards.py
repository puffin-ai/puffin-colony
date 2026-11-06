"""Tests for the guards: the wait guard, the hooks merge and the lines the hooks post, and the suppressions ledger."""
import argparse
import io
import json
import os
import platform
import re
import subprocess
import sys
from importlib import resources
from pathlib import Path

import pytest

from colony import cli, guards, wait

PACKAGE = Path(str(resources.files("colony")))
GUARD = PACKAGE / "hooks" / "wait_guard.py"
CONFIG = {"project": {"name": "demo", "repo": "acme/demo", "base": "main"},
          "accounts": {"first": {"config_dir": "~/.claude", "person": "ana"}}}
REFUSED = [
    "sleep 30",
    "sleep 2m",
    "while true; do gh pr checks 5; sleep 20; done",
    "while true; do date; done",
    "while :; do gh run list; done",
    "until false; do date; done",
    "while true\ndo\n  gh run list\ndone",
    "for i in 1 2 3; do sleep 1; done",
    "watch -n 5 gh pr checks 5",
    "watch git status",
    "gh pr checks 5 --watch",
    "gh --repo acme/demo run watch 123",
    "sleep 600 & wait",
    'bash -c "while true; do date; done"',
    "timeout 100 sleep 60",
    'python3 -c "import time; time.sleep(60)"',
]
ALLOWED = [
    "npm test",
    "git status && git log --oneline -3",
    "sleep 2",
    "for f in a b; do echo $f; done",
    "while read line; do echo $line; done < list.txt",
    "while true; do date; done &",
    "gh pr checks 5",
    "cat <<EOF > notes.txt\nwhile true; do sleep 600; done\nEOF",
    "gh api a > a.json & gh api b > b.json & wait",
    "echo watch this",
]


def guard(call) -> subprocess.CompletedProcess:
    """Run the wait guard the way Claude Code does, with the call as JSON on stdin."""
    return subprocess.run([sys.executable, str(GUARD)], input=call, capture_output=True, text=True)


@pytest.mark.parametrize("command", REFUSED)
def test_the_wait_guard_refuses_a_foreground_wait(command):
    run = guard(json.dumps({"tool_input": {"command": command}}))
    assert run.returncode == 2, command
    assert run.stderr.startswith("wait guard: refused, ") and "run_in_background" in run.stderr
    assert "colony wait" in run.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_the_wait_guard_lets_a_normal_command_run(command):
    run = guard(json.dumps({"tool_input": {"command": command}}))
    assert (run.returncode, run.stderr) == (0, ""), command


def test_the_wait_guard_names_the_endless_loop_and_lets_a_background_call_or_an_unreadable_one_run():
    assert "an endless `while true` loop" in guard(json.dumps({"tool_input": {"command": "while true; do date; done"}})).stderr
    assert guard(json.dumps({"tool_input": {"command": "sleep 600", "run_in_background": True}})).returncode == 0
    assert guard("not json").returncode == 0


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A fresh git repo to run in, with HOME in the temporary folder."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(root)
    return root.resolve()


def commands(data: dict, event: str) -> list[str]:
    return [hook["command"] for group in data["hooks"][event] for hook in group["hooks"]]


def test_merging_the_hooks_keeps_the_hooks_and_settings_already_there(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir()
    theirs = {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my-lint-guard"}]}],
              "Notification": [{"matcher": "", "hooks": [{"type": "command", "command": "notify-me"}]}],
              "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "fmt"}]}]}
    path.write_text(json.dumps({"permissions": {"deny": ["Read(**/.env)"]}, "hooks": json.loads(json.dumps(theirs))}))
    assert guards.merge_hooks(path) == (["PreToolUse", "Notification", "StopFailure", "UserPromptSubmit",
                                         "SessionStart"], [])
    data = json.loads(path.read_text())
    assert data["permissions"] == {"deny": ["Read(**/.env)"]}
    for event, groups in theirs.items():
        assert data["hooks"][event][:len(groups)] == groups, event
    assert ".colony/hooks/wait_guard.py" in data["hooks"]["PreToolUse"][1]["hooks"][0]["command"]
    assert data["hooks"]["PreToolUse"][1]["matcher"] == "Bash"
    asking = data["hooks"]["Notification"][1]
    assert asking["matcher"] == "permission_prompt" and asking["hooks"][0]["async"] is True
    assert "colony hooks asking" in asking["hooks"][0]["command"]
    assert "matcher" not in data["hooks"]["StopFailure"][0]
    assert "colony hooks stopped" in commands(data, "StopFailure")[0]


def test_merging_again_changes_nothing_and_brings_an_old_colony_hook_up_to_date(tmp_path):
    path = tmp_path / "settings.json"
    guards.merge_hooks(path)
    first = path.read_text()
    assert guards.merge_hooks(path) == ([], [])
    assert path.read_text() == first
    data = json.loads(first)
    data["hooks"]["StopFailure"][0]["hooks"][0]["command"] = "colony hooks stopped --from-an-older-colony"
    path.write_text(json.dumps(data))
    assert guards.merge_hooks(path) == ([], ["StopFailure"])
    assert json.loads(path.read_text()) == json.loads(first)


def test_a_broken_settings_file_is_left_as_it_is(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    with pytest.raises(cli.ColonyError, match="is not valid JSON"):
        guards.merge_hooks(path)
    assert path.read_text() == "{not json"
    path.write_text(json.dumps({"hooks": {"PreToolUse": {"matcher": "Bash"}}}))
    with pytest.raises(cli.ColonyError, match="hooks.PreToolUse must be a list"):
        guards.merge_hooks(path)


def test_install_copies_the_guard_and_the_settings_command_runs_it(repo, capsys):
    assert guards.install(CONFIG, argparse.Namespace(dry_run=False)) == 0
    copied = repo / ".colony" / "hooks" / "wait_guard.py"
    assert copied.read_text() == GUARD.read_text()
    data = json.loads((repo / ".claude" / "settings.json").read_text())
    assert set(data["hooks"]) == {"PreToolUse", "Notification", "StopFailure", "UserPromptSubmit", "SessionStart"}
    env = {"PATH": os.environ["PATH"], "CLAUDE_PROJECT_DIR": str(repo)}
    command = commands(data, "PreToolUse")[0]
    for call, code in (("sleep 30", 2), ("npm test", 0)):
        run = subprocess.run(["sh", "-c", command], input=json.dumps({"tool_input": {"command": call}}),
                             capture_output=True, text=True, env=env)
        assert run.returncode == code, (call, run.stderr)
    for event in ("Notification", "StopFailure", "UserPromptSubmit", "SessionStart"):  # a session not Colony's runs nothing
        run = subprocess.run(["sh", "-c", commands(data, event)[0]], capture_output=True, text=True, env=env)
        assert (run.returncode, run.stdout, run.stderr) == (0, "", ""), event
    assert "wrote .claude/settings.json: added PreToolUse, Notification, StopFailure" in capsys.readouterr().out


def test_install_dry_run_writes_nothing(repo, capsys):
    assert guards.install(CONFIG, argparse.Namespace(dry_run=True)) == 0
    assert "Nothing ran." in capsys.readouterr().out
    assert not (repo / ".claude").exists() and not (repo / ".colony").exists()


@pytest.fixture
def posted(tmp_path, monkeypatch):
    """The gh calls the hooks make, with the coordination issue at #7 and the session's person ana."""
    calls = []
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    monkeypatch.delenv(cli.SESSION_ENV, raising=False)
    monkeypatch.setattr(wait, "coordination_issue", lambda repo, project: 7)
    monkeypatch.setattr(wait, "gh", lambda *args: calls.append(args) or "")
    return calls


def hook(monkeypatch, run, event: dict, session: str | None) -> int:
    """Run one hook command as Claude Code would, with its event on stdin, in the named session."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    if session:
        monkeypatch.setenv(cli.SESSION_ENV, session)
    return run(CONFIG, argparse.Namespace())


def test_a_builders_pop_up_posts_one_urgent_line_for_its_lead_every_10_minutes(posted, monkeypatch):
    event = {"hook_event_name": "Notification", "message": "Claude needs your permission to use Bash: curl -H 'x: sk-12345'"}
    assert hook(monkeypatch, guards.asking, event, "builder-2") == 0
    assert hook(monkeypatch, guards.asking, event, "builder-2") == 0
    assert len(posted) == 1
    *head, body = posted[0]
    assert head == ["issue", "comment", "7", "--repo", "acme/demo", "--body"]
    assert body == f"for ana-lead: urgent: builder-2 waits for a person's approval on {platform.node()[:60]} (from builder-2)"
    assert "sk-12345" not in body
    lead = wait.Session("lead", frozenset({"lead", "ana-lead"}))
    assert wait.taken(body, lead, "7") == [(body, True)]  # the lead's wait prints it at once


def test_the_lead_and_a_session_outside_colony_post_no_pop_up_line(posted, monkeypatch):
    assert hook(monkeypatch, guards.asking, {}, "lead") == 0
    monkeypatch.delenv(cli.SESSION_ENV)
    assert hook(monkeypatch, guards.asking, {}, None) == 0
    assert hook(monkeypatch, guards.stopped, {"error": "rate_limit"}, None) == 0
    assert posted == []


def test_a_builders_error_posts_a_line_naming_only_the_error_code(posted, monkeypatch):
    assert hook(monkeypatch, guards.stopped, {"error": "rate_limit"}, "builder-2") == 0
    assert hook(monkeypatch, guards.stopped, {"error": "Bad key sk-12345 in /Users/ana/.env"}, "builder-2") == 0
    first, second = (call[-1] for call in posted)
    stamp = r"\d{4}-\d\d-\d\d \d\d:\d\d UTC"
    assert re.fullmatch(rf"for ana-lead: builder-2 stopped on an error \(rate_limit\) at {stamp} \(from builder-2\)", first)
    assert "(unknown error)" in second and "sk-12345" not in second and ".env" not in second


def test_the_leads_error_posts_a_line_for_its_person(posted, monkeypatch):
    assert hook(monkeypatch, guards.stopped, {"error": "server_error"}, "lead") == 0
    assert re.fullmatch(r"for ana: ana-lead stopped on an error \(server_error\) at .+ UTC \(from ana-lead\)", posted[0][-1])


def test_a_line_github_refuses_fails_the_hook_and_says_so(posted, monkeypatch, capsys):
    def refuse(*args):
        raise wait.GhError("GitHub answered 401")
    monkeypatch.setattr(wait, "gh", refuse)
    assert hook(monkeypatch, guards.stopped, {"error": "rate_limit"}, "builder-2") == 1
    assert "the line was not posted: GitHub answered 401" in capsys.readouterr().err


FILES = {
    "src/app.py": "import os  # noqa: F401\nx = y  # type: ignore[name-defined]\nz = 1  # noqa\n",
    "web/page.tsx": "// eslint-disable-next-line no-console\nconsole.log(1)\n// @ts-expect-error old type\nconst a = 1\n",
    "web/page.test.ts": "it.skip('works', () => {})\n",
    "svc/main.go": "x := f() //nolint:errcheck\n",
    "docs/notes.md": "A # noqa in prose is not code.\n",
}


def track(root: Path, files: dict[str, str]) -> None:
    """Write files and add them to git."""
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


def suppressions(update: bool = False, config: dict | None = None) -> int:
    return guards.suppressions(config or CONFIG, argparse.Namespace(update=update))


def test_the_first_update_records_each_tracked_files_counts(repo, capsys):
    track(repo, FILES)
    (repo / "untracked.py").write_text("a = 1  # noqa\n")
    assert suppressions(update=True) == 0
    assert json.loads((repo / ".colony" / "suppressions.json").read_text()) == {
        "src/app.py": {"noqa": 2, "type-ignore": 1},
        "svc/main.go": {"nolint": 1},
        "web/page.test.ts": {"test-skip": 1},
        "web/page.tsx": {"eslint-disable": 1, "ts-expect-error": 1},
    }
    assert "recorded 7 suppressions in 4 files" in capsys.readouterr().out
    assert suppressions() == 0
    assert "7 suppressions in 4 files, none above the record." in capsys.readouterr().out


def test_a_missing_ledger_fails_and_names_the_command_that_records_it(repo):
    with pytest.raises(cli.ColonyError, match="run `colony suppressions --update`"):
        suppressions()


def test_a_new_suppression_fails_and_update_never_raises_the_record(repo, capsys):
    track(repo, FILES)
    suppressions(update=True)
    ledger = repo / ".colony" / "suppressions.json"
    before = ledger.read_text()
    track(repo, {"src/app.py": FILES["src/app.py"] + "w = 2  # noqa\n", "src/new.py": "v = 1  # type: ignore\n"})
    capsys.readouterr()
    assert suppressions() == 1
    out = capsys.readouterr().out
    assert "RISE src/app.py: 3 noqa, the record allows 2" in out
    assert "RISE src/new.py: 1 type-ignore, the record allows 0" in out
    assert suppressions(update=True) == 1
    assert ledger.read_text() == before


def test_a_removed_suppression_fails_until_update_lowers_the_record(repo, capsys):
    track(repo, FILES)
    suppressions(update=True)
    track(repo, {"src/app.py": "import os\nx = y  # type: ignore[name-defined]\n"})
    capsys.readouterr()
    assert suppressions() == 1
    assert "FALL src/app.py: 0 noqa, the record holds 2" in capsys.readouterr().out
    assert suppressions(update=True) == 0
    assert json.loads((repo / ".colony" / "suppressions.json").read_text())["src/app.py"] == {"type-ignore": 1}
    assert suppressions() == 0


def test_the_config_can_limit_the_count_to_some_folders(repo):
    track(repo, FILES)
    suppressions(update=True, config={**CONFIG, "suppressions": {"paths": ["src"]}})
    assert list(json.loads((repo / ".colony" / "suppressions.json").read_text())) == ["src/app.py"]


def test_each_language_counts_its_own_suppressions(tmp_path):
    files = {"a.py": "# ruff: noqa\n# pylint: disable=x\n@pytest.mark.skip\n", "b.rs": "#[allow(dead_code)]\n#[ignore]\n",
             "c.rb": "# rubocop:disable Style\n", "D.java": "@SuppressWarnings(\"x\")\n@Disabled\n",
             "e.sh": "# shellcheck disable=SC2086\n", "f.css": "/* stylelint-disable */\n", "g.ts": "// @ts-ignore\n"}
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    assert guards.count(tmp_path, list(files)) == {
        "a.py": {"noqa": 1, "pylint-disable": 1, "test-skip": 1}, "b.rs": {"allow": 1, "test-skip": 1},
        "c.rb": {"rubocop-disable": 1}, "D.java": {"suppress-warnings": 1, "test-skip": 1},
        "e.sh": {"shellcheck-disable": 1}, "f.css": {"stylelint-disable": 1}, "g.ts": {"ts-ignore": 1}}


def test_noqa_counts_in_any_case_and_a_stylesheet_counts_type_and_test_suppressions(tmp_path):
    files = {"a.py": "x = 1  # NOQA\ny = 2  # NoQa: E501\nz = 3  # Type: ignore\n",
             "b.css": "/* @ts-expect-error */\n/* @ts-ignore */\n/* biome-ignore lint: x */\n/* it.skip( */\n"}
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    assert guards.count(tmp_path, list(files)) == {
        "a.py": {"noqa": 2}, "b.css": {"biome-ignore": 1, "test-skip": 1, "ts-expect-error": 1, "ts-ignore": 1}}


def test_add_commands_routes_suppressions_and_the_hooks_actions():
    parser = argparse.ArgumentParser()
    guards.add_commands(parser.add_subparsers(dest="command"))
    assert parser.parse_args(["suppressions", "--update"]).run is guards.suppressions
    args = parser.parse_args(["hooks", "install", "--dry-run"])
    assert args.run is guards.install and args.dry_run
    assert parser.parse_args(["hooks", "asking"]).run is guards.asking
    assert parser.parse_args(["hooks", "stopped"]).run is guards.stopped
    with pytest.raises(SystemExit):
        parser.parse_args(["hooks"])


def test_hooks_install_local_writes_the_machine_settings_only(tmp_path, monkeypatch):
    """--local keeps the hooks out of the committed settings.json, so a CI job never runs them."""
    import argparse, subprocess
    from colony import cli, guards
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    guards.install({}, argparse.Namespace(dry_run=False, local=True))
    assert (tmp_path / ".claude" / "settings.local.json").exists()
    assert not (tmp_path / ".claude" / "settings.json").exists()
