"""Tests for the guards: the wait guard, the hooks merge and the lines the hooks post, and the suppressions ledger."""
import argparse
import io
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import time
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
    "for p in $(pgrep -f merge); do sleep 1; done",
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
    # Two lines the guard used to refuse: a $(...) holding quotes inside a double-quoted word, and a loop
    # over a $(...) whose `);` shlex reads as one token.
    """colony post board "the 'updates every 15 seconds' line"; echo "live: $(curl -s https://x/ | grep -o 'assets/index-[^"]*\\.js' | head -1)\"""",
    'for p in $(pgrep -f merge); do echo "merging: $(ps -o etime= -p $p)"; done; colony wait > out & sleep 0; kill %1',
    "echo $(date)| cat; sleep 1",
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


def test_a_line_whose_quoting_cant_be_read_is_refused_whenever_it_holds_a_push():
    unreadable = """echo "$(echo 'a"b')" """
    for push in ("git push --force origin main", "git push origin +main", "git push '--force' origin main",
                 '"git" push -"f"', "git push -u origin ana/login", "git <<X\npush --force origin main\nX"):
        run = guard(json.dumps({"tool_input": {"command": f"{unreadable}; {push}", "run_in_background": True}}))
        assert run.returncode == 2 and "run the push as a command of its own" in run.stderr, push
    assert guard(json.dumps({"tool_input": {"command": f"{unreadable}; git status"}})).returncode == 0


def test_a_line_whose_quoting_cant_be_read_is_refused_only_for_a_long_sleep():
    unreadable = """echo "$(echo 'a"b')" """
    assert guard(json.dumps({"tool_input": {"command": unreadable}})).returncode == 0
    run = guard(json.dumps({"tool_input": {"command": unreadable + "; sleep 600"}}))
    assert run.returncode == 2 and "`sleep 600` waits 600 seconds in the foreground" in run.stderr


REWRITES_BASE = [
    "git push --force origin main",
    "git push -f origin main",
    "git push -fu origin main",
    "git push origin +main",
    "git push origin +HEAD:refs/heads/main",
    "git push --force-with-lease origin HEAD:main",
    "git push --force-with-lease=main:abc123 origin main",
    "git push origin :main",
    "git push --delete origin main",
    "git push --mirror",
    "git push --force --all",
    "git -C . push --force origin main",
    "git push --force",  # no refspec: the branch checked out, which is main
    "git push -f origin main &",  # in the background it still rewrites main
    "npm test && git push --force origin main",
    "git push --tags -f origin main",
    "git push -fo ci.skip origin +main",
    # Git reads any unambiguous prefix of a long option as the option.
    "git push --del origin main",
    "git push --mir origin",
    "git push --force-w origin main",
    "git push -uf origin main",
    # --prune deletes what a pattern reaches and no local branch matches, and a pattern reaches the base.
    "git push --prune origin 'refs/heads/*:refs/heads/*'",
    "git push --pru origin 'refs/heads/*'",
    "git push --all --prune origin",
    "git push origin '+refs/heads/*:refs/heads/*'",
    # An option that takes the next word as its value, here or before `push`, hides no remote or push.
    "git push --recurse-submodules check -f origin",
    "git --config-env core.editor=EDITOR push --force origin main",
    "git push -f -- origin main",
]
LEAVES_BASE = [
    "git push origin main",
    "git push -u origin ana/login",
    "git push --force origin ana/login",
    "git push --force-with-lease origin HEAD:refs/heads/ana/login",
    "git push origin +ana/login",
    "echo git push --force origin main",
    "git log --oneline -3",
    "git push --tags -f",  # only tags, though the branch checked out is main
    "git push origin --tags --force",
    "git push -odeploy origin main",  # -o's value, not -d
    "git push -fodeploy origin ana/login",
    "git push --dry origin main",  # --dry-run, which forces nothing
    "git push --prune origin main",  # --prune deletes only through a pattern
    "git push --prune origin 'refs/heads/ana/*:refs/heads/ana/*'",
    "git push origin '+refs/heads/ana/*:refs/heads/ana/*'",
]


def push_guard(command: str, root: Path, **call) -> subprocess.CompletedProcess:
    """Run the guard on one command from a repo whose colony.toml names the base, as Claude Code runs it."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps({"cwd": str(root), "tool_input": {
        "command": command, **call}}), capture_output=True, text=True, env=env)


@pytest.fixture
def on_main(tmp_path):
    """A clone on its base, main, with a hack colony.toml."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    (tmp_path / ".colony").mkdir()
    (tmp_path / ".colony" / "colony.toml").write_text('[project]\nmode = "hack"\nbase = "main"\n')
    return tmp_path


@pytest.mark.parametrize("command", REWRITES_BASE)
def test_the_guard_refuses_a_push_that_force_pushes_or_deletes_the_base(command, on_main):
    run = push_guard(command, on_main)
    assert run.returncode == 2, command
    assert run.stderr.startswith("push guard: refused, ") and "colony merge <branch>" in run.stderr
    assert push_guard(command, on_main, run_in_background=True).returncode == 2


@pytest.mark.parametrize("command", LEAVES_BASE)
def test_the_guard_lets_a_push_that_leaves_the_base_alone_run(command, on_main):
    run = push_guard(command, on_main)
    assert (run.returncode, run.stderr) == (0, ""), command


def test_the_guard_protects_the_base_colony_toml_names(on_main):
    (on_main / ".colony" / "colony.toml").write_text('[project]\nbase = "dev"\n\n[gate]\nbase = "other"\n')
    assert push_guard("git push --force origin dev", on_main).returncode == 2
    assert push_guard("git push --force origin other", on_main).returncode == 0
    subprocess.run(["git", "-C", str(on_main), "checkout", "-q", "-b", "ana/login"], check=True)
    assert push_guard("git push --force", on_main).returncode == 0  # the branch checked out is not the base


def test_the_guard_protects_the_default_branch_too_when_the_base_is_another(on_main):
    (on_main / ".colony" / "colony.toml").write_text('[project]\nbase = "dev"\n')
    # With no origin/HEAD, main stands in for the default branch.
    run = push_guard("git push --force origin main", on_main)
    assert run.returncode == 2 and "this push force-pushes main" in run.stderr and "dev and main" in run.stderr
    assert push_guard("git push origin main", on_main).returncode == 0
    subprocess.run(["git", "-C", str(on_main), "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk"],
                   check=True)
    assert push_guard("git push --force origin trunk", on_main).returncode == 2
    assert push_guard("git push origin :trunk", on_main).returncode == 2
    assert push_guard("git push --force origin dev", on_main).returncode == 2
    assert push_guard("git push --force origin main", on_main).returncode == 0  # main is neither base nor default
    assert push_guard("git push origin trunk", on_main).returncode == 0


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
    assert '.colony/bin/colony" hooks asking' in asking["hooks"][0]["command"]
    assert "matcher" not in data["hooks"]["StopFailure"][0]
    assert '.colony/bin/colony" hooks stopped' in commands(data, "StopFailure")[0]
    assert "CLAUDE_ENV_FILE" in commands(data, "SessionStart")[1]


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


def test_a_line_gh_cant_post_waits_in_the_outbox_and_the_next_hook_posts_it_first(posted, monkeypatch, capsys):
    working = wait.gh

    def refuse(*args):
        raise wait.GhError("gh issue failed: connection reset")
    monkeypatch.setattr(wait, "gh", refuse)
    assert hook(monkeypatch, guards.stopped, {"error": "rate_limit"}, "builder-2") == 1
    assert hook(monkeypatch, guards.asking, {}, "builder-3") == 1
    assert "waits in" in capsys.readouterr().err and posted == []
    kept = [item["line"] for item in guards.read_outbox(CONFIG)]
    assert len(kept) == 2 and kept[0].startswith("for ana-lead: builder-2 stopped") and "builder-3 waits" in kept[1]
    assert guards.outbox_path(CONFIG) == wait.state_path("demo", "outbox")
    monkeypatch.setattr(wait, "gh", working)
    assert hook(monkeypatch, guards.stopped, {"error": "server_error"}, "builder-3") == 0
    assert [call[-1] for call in posted][:2] == kept and "builder-3 stopped" in posted[2][-1]
    assert guards.read_outbox(CONFIG) == []


def test_an_outbox_line_that_can_never_post_is_dropped_and_the_rest_post(posted, monkeypatch, capsys):
    guards.write_outbox(CONFIG, [{"to": "lead", "line": "for lead: token ghp_" + "a" * 36 + " (from builder-1)"},
                                 {"to": "lead", "line": "for lead: hello (from builder-1)"}, "broken"])
    assert guards.flush_outbox(CONFIG) == 2
    assert [call[-1] for call in posted] == ["for lead: hello (from builder-1)"]
    assert "can never post, and is dropped" in capsys.readouterr().err and guards.read_outbox(CONFIG) == []


def test_a_flush_while_another_runs_skips(posted, monkeypatch):
    guards.write_outbox(CONFIG, [{"to": "lead", "line": "for lead: hello (from builder-1)"}])
    with guards.outbox_lock(CONFIG):
        assert guards.flush_outbox(CONFIG) == 0
    assert guards.flush_outbox(CONFIG) == 1 and len(posted) == 1


def test_the_prompt_hook_says_once_a_day_when_the_session_runs_without_the_retry_watchdog(posted, monkeypatch, capsys):
    monkeypatch.delenv(guards.WATCHDOG_ENV)
    wait.write_json(wait.state_path("demo", "builder-2"), {"polled_at": 9e12})  # a running wait: no GitHub read
    assert hook(monkeypatch, guards.unread, {}, "builder-2") == 0
    assert capsys.readouterr().out == (f"builder-2 runs without {guards.WATCHDOG_ENV}=1, so a usage limit or a dropped "
                                       "connection can end a turn for good: reopen it through `colony`, which sets it "
                                       "(this note shows once a day).\n")
    assert hook(monkeypatch, guards.unread, {}, "builder-2") == 0
    assert capsys.readouterr().out == ""
    assert guards.watchdog_note(CONFIG, "builder-2", now=time.time() + guards.WATCHDOG_EVERY + 1)
    monkeypatch.setenv(guards.WATCHDOG_ENV, "1")
    assert guards.watchdog_note(CONFIG, "builder-2", now=time.time() + 3 * guards.WATCHDOG_EVERY) == ""


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


# The repo's launcher, .colony/bin/colony, and the upgrade that moves its pin

def script(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return path


def run_launcher(tmp_path, *args, path: str = "/usr/bin:/bin"):
    """Write the launcher into a repo of its own and run it, with HOME and the cache folder in tmp_path."""
    launcher = tmp_path / "repo" / guards.LAUNCHER
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(guards.launcher("9.9.9"))
    launcher.chmod(0o755)
    env = {"PATH": path, "HOME": str(tmp_path / "home"), "XDG_CACHE_HOME": str(tmp_path / "cache"),
           "VIRTUAL_ENV": "/somewhere/archive-v0/env"}
    return subprocess.run([str(launcher), *args], capture_output=True, text=True, env=env, timeout=60)


CACHED = "puffin-colony/v9.9.9"
FAKE_PYTHON = 'echo "PATH=${PATH%%:*} VIRTUAL_ENV=$VIRTUAL_ENV args=$*"'


def test_hooks_install_writes_the_launcher_pinned_to_this_version(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    guards.install({}, argparse.Namespace(dry_run=False))
    launcher = tmp_path / guards.LAUNCHER
    assert launcher.read_text() == guards.launcher() and os.access(launcher, os.X_OK)
    assert f"\npin={cli.__version__}\n" in launcher.read_text()
    assert "git+https://github.com/puffin-ai/puffin-colony@v$pin" in launcher.read_text()


def test_the_launcher_runs_the_cached_pin_with_its_folder_first_on_path(tmp_path):
    script(tmp_path / "cache" / CACHED / "bin" / "python", FAKE_PYTHON)
    run = run_launcher(tmp_path, "wait", "--x")
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == f"PATH={tmp_path / 'repo' / cli.DIR / 'bin'} VIRTUAL_ENV= args=-P -m colony wait --x"
    assert run.stderr == ""


def fake_uv(path: Path, log: Path) -> Path:
    """A uv that logs each call, and whose `venv` makes a folder with the fake Python in it."""
    return script(path, f'echo "VIRTUAL_ENV=$VIRTUAL_ENV $*" >> {log}\nfor last; do :; done\n'
                        f'if [ "$1" = venv ]; then mkdir -p "$last/bin"; printf \'#!/bin/sh\\n%s\\n\' '
                        f'{shlex.quote(FAKE_PYTHON)} > "$last/bin/python"; chmod +x "$last/bin/python"; fi')


def test_the_launcher_installs_the_pin_from_its_github_tag_once(tmp_path):
    bin_dir, log = tmp_path / "bin", tmp_path / "uv.log"
    fake_uv(bin_dir / "uv", log)
    run = run_launcher(tmp_path, "--version", path=f"{bin_dir}:/usr/bin:/bin")
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip().endswith("VIRTUAL_ENV= args=-P -m colony --version")
    assert "fetching Puffin Colony v9.9.9 for this repo, once per computer" in run.stderr
    venv, install = log.read_text().splitlines()
    assert venv.startswith("VIRTUAL_ENV= venv -q --relocatable --python >=3.11 ")
    staged = venv.rsplit(" ", 1)[1]
    assert install == (f"VIRTUAL_ENV={staged} pip install -q "
                       "puffin-colony @ git+https://github.com/puffin-ai/puffin-colony@v9.9.9")
    assert (tmp_path / "cache" / CACHED / "bin" / "python").exists() and not Path(staged).exists()
    again = run_launcher(tmp_path, "--version", path=f"{bin_dir}:/usr/bin:/bin")
    assert again.stderr == "" and len(log.read_text().splitlines()) == 2


def test_the_launcher_installs_uv_with_astrals_installer_when_there_is_none(tmp_path):
    template = fake_uv(tmp_path / "template" / "uv", tmp_path / "uv.log")
    uv = tmp_path / "home" / ".local" / "bin" / "uv"
    script(tmp_path / "bin" / "curl",
           f'[ "$2" = "{guards.UV_INSTALLER}" ] || exit 7\necho "mkdir -p {uv.parent}; cp {template} {uv}"')
    run = run_launcher(tmp_path, path=f"{tmp_path / 'bin'}:/usr/bin:/bin")
    assert "installing uv, which runs Puffin Colony, with Astral's installer" in run.stderr
    assert run.returncode == 0 and run.stdout.strip().endswith("args=-P -m colony"), run.stderr
    assert uv.exists()


def test_the_launcher_stops_with_a_reason_when_uv_cannot_install(tmp_path):
    script(tmp_path / "bin" / "curl", "exit 6")
    run = run_launcher(tmp_path, path=f"{tmp_path / 'bin'}:/usr/bin:/bin")
    assert run.returncode == 127 and "uv did not install" in run.stderr


def test_the_repos_session_start_hook_puts_the_launcher_first_on_the_bash_path(tmp_path):
    [(event, _, hook, _)] = [entry for entry in guards.hook_entries() if entry[3] == "CLAUDE_ENV_FILE"]
    assert event == "SessionStart"
    env_file = tmp_path / "env"
    env_file.write_text("export A=1\n")
    env = {"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(tmp_path), "CLAUDE_ENV_FILE": str(env_file)}
    assert subprocess.run(["sh", "-c", hook["command"]], env=env).returncode == 0
    assert env_file.read_text() == "export A=1\n"  # no launcher yet: nothing to put on PATH
    script(tmp_path / guards.LAUNCHER, "echo repo-colony")
    assert subprocess.run(["sh", "-c", hook["command"]], env=env).returncode == 0
    assert env_file.read_text() == f'export A=1\nexport PATH="{tmp_path}/.colony/bin:$PATH"\n'
    run = subprocess.run(["bash", "-c", f". {env_file}; colony"], capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin"})
    assert run.stdout == "repo-colony\n"


def test_the_repos_hooks_run_the_launcher():
    for event, _, hook, marker in guards.hook_entries():
        if marker.startswith("hooks "):
            assert f'exec "$CLAUDE_PROJECT_DIR/{guards.LAUNCHER}" {marker}' in hook["command"] or \
                f'&& "$CLAUDE_PROJECT_DIR/{guards.LAUNCHER}" {marker}' in hook["command"], event


def test_an_install_brings_a_hook_from_before_the_launcher_up_to_date(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hooks": {"StopFailure": [{"hooks": [{"type": "command", "command":
        '[ -n "$COLONY_SESSION" ] && command -v colony >/dev/null 2>&1 || exit 0; exec colony hooks stopped'}]}]}}))
    assert "StopFailure" in guards.merge_hooks(path)[1]
    assert len(commands(json.loads(path.read_text()), "StopFailure")) == 1


def test_release_tags_compare_as_versions(monkeypatch):
    out = "".join(f"abc\trefs/tags/{tag}\n" for tag in ("v0.9.0", "v0.10.0", "v0.10.0-rc1", "latest", "v0.4.0"))
    monkeypatch.setattr(guards.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, out, ""))
    assert guards.latest_release() == "v0.10.0"
    monkeypatch.setattr(guards.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 128, "", "offline"))
    assert guards.latest_release() is None


def test_the_upgrade_note_names_a_newer_release_at_most_once_a_day(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    config = {"project": {"name": "demo"}}
    asked = []
    start = 1_800_000_000

    def latest():
        asked.append(1)
        return "v99.0.0"
    note = guards.upgrade_note(config, now=start, latest=latest)
    assert note.startswith(f"Puffin Colony v99.0.0 is out, and this repo pins v{cli.__version__}")
    assert "https://github.com/puffin-ai/puffin-colony/blob/v99.0.0/CHANGELOG.md" in note
    assert "`colony upgrade`" in note and "\n" not in note
    assert guards.upgrade_note(config, now=start + guards.UPGRADE_EVERY - 1, latest=latest) == ""
    assert len(asked) == 1  # within the day, not even GitHub is asked
    assert guards.upgrade_note(config, now=start + guards.UPGRADE_EVERY, latest=latest) != ""
    current = guards.upgrade_note(config, now=start + 3 * guards.UPGRADE_EVERY, latest=lambda: f"v{cli.__version__}")
    assert current == ""
    assert guards.upgrade_note(config, now=start + 5 * guards.UPGRADE_EVERY, latest=lambda: None) == ""


@pytest.mark.parametrize("me, shown", [("lead", True), ("builder-1", False)])
def test_only_the_leads_prompt_hook_shows_the_upgrade_note(me, shown, monkeypatch, capsys):
    monkeypatch.setenv(cli.SESSION_ENV, me)
    monkeypatch.setattr(guards, "hook_event", dict)
    monkeypatch.setattr(guards, "watchdog_note", lambda *a: "")
    monkeypatch.setattr(guards, "read_unread", lambda *a: [])
    monkeypatch.setattr(guards, "upgrade_note", lambda config: "Puffin Colony v99.0.0 is out")
    assert guards.unread({"project": {"name": "demo"}}, argparse.Namespace()) == 0
    assert ("v99.0.0 is out" in capsys.readouterr().out) is shown


def git_repo(root: Path) -> Path:
    root.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"],
                 ["commit", "-q", "--allow-empty", "-m", "start"]):
        subprocess.run(["git", *args], cwd=root, check=True)
    return root


def test_upgrade_moves_the_pin_on_a_branch_and_commits_the_refreshed_files(tmp_path, monkeypatch):
    root = git_repo(tmp_path / "repo")
    monkeypatch.chdir(root)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    # The new release's cached Python stands in for its `colony upgrade --refresh`, which rewrites the copied files.
    script(tmp_path / "cache" / "puffin-colony/v99.0.0/bin/python",
           f'echo "$*" > {tmp_path / "refresh"}; mkdir -p .colony/hooks; echo new > .colony/hooks/wait_guard.py')
    assert guards.upgrade({}, argparse.Namespace(refresh=False, to="v99.0.0", dry_run=False)) == 0
    assert (tmp_path / "refresh").read_text() == "-P -m colony upgrade --refresh\n"
    git = lambda *args: subprocess.run(["git", *args], cwd=root, capture_output=True, text=True).stdout.strip()
    assert git("branch", "--show-current") == "colony/upgrade-v99.0.0"
    assert git("log", "-1", "--format=%s") == "chore(colony): upgrade Puffin Colony to v99.0.0"
    assert set(git("show", "--name-only", "--format=").split()) == {guards.LAUNCHER, ".colony/hooks/wait_guard.py"}
    assert "\npin=99.0.0\n" in (root / guards.LAUNCHER).read_text() and git("status", "--porcelain") == ""


def test_upgrade_keeps_the_pin_when_it_is_the_newest(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(git_repo(tmp_path / "repo"))
    assert guards.upgrade({}, argparse.Namespace(refresh=False, to=f"v{cli.__version__}", dry_run=False)) == 0
    assert "the pin stays" in capsys.readouterr().out and not (tmp_path / "repo" / guards.LAUNCHER).exists()


def test_upgrade_refuses_a_working_tree_with_changes(tmp_path, monkeypatch):
    root = git_repo(tmp_path / "repo")
    (root / "notes.txt").write_text("mine\n")
    monkeypatch.chdir(root)
    with pytest.raises(cli.ColonyError, match="the working tree has changes"):
        guards.upgrade({}, argparse.Namespace(refresh=False, to="v99.0.0", dry_run=False))


def test_upgrade_refresh_rewrites_the_copied_files_and_the_role_skills_the_repo_has(tmp_path, monkeypatch):
    root = git_repo(tmp_path / "repo")
    monkeypatch.chdir(root)
    skill = root / ".claude" / "skills" / "colony-lead" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("old\n")
    assert guards.upgrade({}, argparse.Namespace(refresh=True, to=None, dry_run=False)) == 0
    assert (root / guards.LAUNCHER).read_text() == guards.launcher()
    assert (root / cli.DIR / "hooks" / guards.GUARD).exists() and (root / ".claude" / "settings.json").exists()
    assert skill.read_text() != "old\n" and not (root / ".claude" / "skills" / "colony-builder").exists()
