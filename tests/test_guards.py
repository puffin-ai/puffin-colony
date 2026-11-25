"""Tests for the guards: the wait guard, the hooks merge and the lines the hooks post, and the suppressions ledger."""
import argparse
import importlib.util
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
    "git push -f origin @",  # @ is HEAD, the branch checked out
    "git push origin +:",  # : pushes every branch both sides have, as push.default=matching does
    "git push -f origin HEAD:heads/main",  # git reads heads/main as refs/heads/main
    "git push origin :heads/main",
    "git --attr-source HEAD push --force origin main",
    "git --shallow-file x push --force origin main",
]
LEAVES_BASE = [
    "git push -u origin ana/login",
    "git push --force origin ana/login",
    "git push --force-with-lease origin HEAD:refs/heads/ana/login",
    "git push origin +ana/login",
    "echo git push --force origin main",
    "git log --oneline -3",
    "git push --tags -f",  # only tags, though the branch checked out is main
    "git push origin --tags --force",
    "git push -fodeploy origin ana/login",
    "git push --dry origin main",  # --dry-run, which pushes nothing
    "git push -n origin main",
    "git push --prune origin 'refs/heads/ana/*:refs/heads/ana/*'",
    "git push origin '+refs/heads/ana/*:refs/heads/ana/*'",
    "git push origin v1.0",
]
# A plain push that updates the base lands work on it, which no agent does without the person's yes: the merge guard
# refuses it unless [safety] merge_into names the branch.
UPDATES_BASE = [
    "git push origin main",
    "git push -odeploy origin main",  # -o's value, not -d
    "git push --prune origin main",  # --prune deletes only through a pattern, but the push still updates main
    "git push origin :",  # matching: every branch both sides have, main among them
    "git push",  # the branch checked out, main
    "git push origin HEAD",
    "git push origin @",
    "git push origin HEAD:refs/heads/main",
    "git push origin ana/login:main",
    "git push origin 'refs/heads/*:refs/heads/*'",
    "git push --follow-tags origin main",
    "npm test && git push origin main",
    "git push origin main &",
]


def push_guard(command: str, root: Path, path: str = "", **call) -> subprocess.CompletedProcess:
    """Run the guard on one command from a repo whose colony.toml names the base, as Claude Code runs it, with `path`
    first on PATH when given, such as a folder holding a stub gh."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    if path:
        env["PATH"] = os.pathsep.join([path, env["PATH"]])
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


def merge_refused(run: subprocess.CompletedProcess, reason: str = "") -> bool:
    """Whether the merge guard refused the call, for `reason` when given."""
    return run.returncode == 2 and run.stderr.startswith(f"merge guard: refused, {reason}") and \
        "merge_into" in run.stderr


@pytest.mark.parametrize("command", UPDATES_BASE)
def test_the_merge_guard_refuses_a_plain_push_into_the_base_by_default(command, on_main):
    run = push_guard(command, on_main)
    assert merge_refused(run, "this push updates main"), (command, run.stderr)
    assert "open a pull request" in run.stderr and "colony merge <branch>" in run.stderr
    assert merge_refused(push_guard(command, on_main, run_in_background=True))


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
    assert merge_refused(push_guard("git push origin main", on_main), "this push updates main")
    subprocess.run(["git", "-C", str(on_main), "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk"],
                   check=True)
    assert push_guard("git push --force origin trunk", on_main).returncode == 2
    assert push_guard("git push origin :trunk", on_main).returncode == 2
    assert push_guard("git push --force origin dev", on_main).returncode == 2
    assert push_guard("git push --force origin main", on_main).returncode == 0  # main is neither base nor default
    assert push_guard("git push origin main", on_main).returncode == 0
    assert merge_refused(push_guard("git push origin trunk", on_main), "this push updates trunk")


def test_a_push_with_repo_is_refused_when_either_reading_of_its_words_reaches_the_base(on_main):
    # Git takes the first word as the repository even with --repo, so this forces main, checked out, to origin.
    assert push_guard("git push --repo=elsewhere --force origin", on_main).returncode == 2
    subprocess.run(["git", "-C", str(on_main), "checkout", "-q", "-b", "ana/login"], check=True)
    for command in ("git push --repo=origin --force main", "git push --repo origin --force main",
                    "git push --rep=origin --force main"):
        run = push_guard(command, on_main)
        assert run.returncode == 2 and "this push force-pushes main" in run.stderr, command
    for command in ("git push --repo=origin --force ana/login", "git push --repo=origin --force origin ana/login"):
        assert push_guard(command, on_main).returncode == 0, command
    assert merge_refused(push_guard("git push --repo=origin main", on_main), "this push updates main")


def git_in(root: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@example.test", *arguments],
                   check=True, capture_output=True)


def test_a_forced_push_with_no_refspec_updates_what_git_config_says(on_main):
    git_in(on_main, "checkout", "-q", "-b", "ana/login")
    assert push_guard("git push -f", on_main).returncode == 0  # push.default=simple: ana/login alone
    run = push_guard("git -c push.default=matching push -f", on_main)
    assert run.returncode == 2 and "this push force-pushes main, through push.default=matching" in run.stderr
    git_in(on_main, "config", "push.default", "matching")
    assert push_guard("git push --force", on_main).returncode == 2
    for command in ("git push --force origin ana/login", "git push --tags -f", "git push -f origin @",
                    "git -c push.default=simple push -f"):
        assert push_guard(command, on_main).returncode == 0, command
    # A plain push with push.default=matching updates main too, which the merge guard refuses.
    assert merge_refused(push_guard("git push", on_main), "this push updates main, through push.default=matching")


def test_a_forced_push_with_no_refspec_reads_the_upstream_and_the_remotes_push_refspecs(on_main):
    git_in(on_main, "checkout", "-q", "-b", "ana/login")
    git_in(on_main, "config", "branch.ana/login.remote", "origin")
    git_in(on_main, "config", "branch.ana/login.merge", "refs/heads/main")
    run = push_guard("git -c push.default=upstream push -f", on_main)
    assert run.returncode == 2 and "this push force-pushes main, through push.default=upstream" in run.stderr
    # A plain push to the upstream, main, updates the base, which the merge guard refuses.
    assert merge_refused(push_guard("git -c push.default=upstream push", on_main),
                         "this push updates main, through push.default=upstream")
    run = push_guard("git -c 'remote.origin.push=refs/heads/*:refs/heads/*' push -f", on_main)
    assert run.returncode == 2 and "through remote.origin.push" in run.stderr
    git_in(on_main, "config", "remote.fork.push", "refs/heads/*:refs/heads/*")
    assert push_guard("git push -f fork", on_main).returncode == 2
    assert push_guard("git push -f origin", on_main).returncode == 0  # fork's refspecs are not origin's


def test_a_forced_push_with_no_refspec_is_refused_when_git_config_cant_say_what_it_updates(on_main):
    git_in(on_main, "commit", "-q", "--allow-empty", "-m", "base")
    git_in(on_main, "checkout", "-q", "-b", "ana/login")
    for command in ("git --config-env push.default=PUSH_DEFAULT push -f", "git -c push.default=sideways push -f"):
        run = push_guard(command, on_main)
        assert run.returncode == 2 and "git config can't say which branches" in run.stderr, command
    git_in(on_main, "checkout", "-q", "--detach")  # no branch checked out for simple to push
    assert push_guard("git push -f", on_main).returncode == 2
    assert push_guard("git push --tags -f", on_main).returncode == 0


def test_a_plain_push_with_no_refspec_is_refused_when_git_config_forces_deletes_or_mirrors_the_base(on_main):
    git_in(on_main, "checkout", "-q", "-b", "ana/login")
    for command in ("git -c 'remote.origin.push=+refs/heads/*:refs/heads/*' push",
                    "git -c remote.origin.push=:refs/heads/main push", "git -c remote.origin.mirror=true push"):
        assert push_guard(command, on_main).returncode == 2, command
    git_in(on_main, "config", "remote.origin.mirror", "true")
    run = push_guard("git push", on_main)
    assert run.returncode == 2 and "remote.origin.mirror" in run.stderr
    for command in ("git push origin ana/login", "git push fork", "git -c remote.origin.mirror=false push"):
        assert push_guard(command, on_main).returncode == 0, command


def test_a_forced_push_names_its_branch_after_a_command_on_the_line_that_can_change_what_it_pushes(on_main):
    git_in(on_main, "checkout", "-q", "-b", "ana/login")
    for command in ("git checkout main && git push -f", "git switch main; git push --force-with-lease",
                    "git config push.default matching && git push -f", "cd ../other && git push -f",
                    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=push.default GIT_CONFIG_VALUE_0=matching git push -f",
                    "export GIT_DIR=../other/.git; git push -f", "git --git-dir=../other/.git push -f",
                    "git checkout main && git push -f origin HEAD",
                    "git symbolic-ref HEAD refs/heads/main && git push -f", "env -C ../other git push -f",
                    "HOME=/tmp/elsewhere git push -f", "export XDG_CONFIG_HOME=/tmp/elsewhere; git push -f"):
        run = push_guard(command, on_main)
        assert run.returncode == 2 and "on this line can change" in run.stderr, command
    for command in ("git rebase main && git push -f", "npm test && git push --force-with-lease",
                    "git checkout main && git push -f origin ana/login", "git push -f && git checkout main"):
        assert push_guard(command, on_main).returncode == 0, command
    # A plain push the line can point at main, after the checkout, is the merge guard's to refuse.
    assert merge_refused(push_guard("git checkout main && git push", on_main),
                         "this push names no refspec, and `git checkout` on this line can change which branch")
    assert merge_refused(push_guard("git checkout main && git push origin HEAD", on_main), "this push updates HEAD")


def test_a_branch_the_line_makes_and_a_folder_it_moves_to_name_what_a_push_updates(on_main, tmp_path_factory):
    git_in(on_main, "commit", "-q", "--allow-empty", "-m", "base")
    for command in ("git checkout -b ana/new && git push -u origin HEAD", "git switch -c ana/new && git push -f origin @",
                    "git switch --create=ana/new && npm test && git push origin HEAD"):
        assert push_guard(command, on_main).returncode == 0, command
    for command in ("git checkout -B main && git push origin HEAD", "git checkout -b x && git checkout main && "
                    "git push origin HEAD"):
        assert push_guard(command, on_main).returncode == 2, command
    # A `cd` into a folder the guard can name moves where the line's push runs: here a clone on a branch of its own.
    other = tmp_path_factory.mktemp("other")
    git_in(on_main, "worktree", "add", "-q", "-b", "ana/login", str(other))
    assert push_guard(f"cd {other} && git push origin HEAD", on_main).returncode == 0
    assert push_guard(f"cd {other} && git push", on_main).returncode == 0
    assert merge_refused(push_guard(f"cd {other} && git push origin main", on_main))
    # Inside a subshell a `cd` ends with it, and a folder that isn't there is one the guard can't name.
    for command in (f"(cd {other}) && git push origin HEAD", "cd ../nowhere && git push origin HEAD"):
        assert merge_refused(push_guard(command, on_main)), command


CHAINS_THE_GUARD_CANT_COUNT_ON = [
    "cd {other} || git push origin HEAD",  # the push runs only when the cd fails
    "cd {other}; git push origin HEAD",  # the push runs whether the cd worked or not
    "cd {other} && true; git push origin HEAD",
    "true || cd {other} && git push origin HEAD",  # the cd runs only when true fails, and the push runs anyway
    "echo | cd {other} && git push origin HEAD",  # a cd in a pipeline runs in a shell of its own
    "cd {other} && git push origin HEAD; git push origin HEAD",  # the second push may run in either folder
    "git checkout -b ana/x || git push origin HEAD",
    "git checkout -b ana/x; git push origin HEAD",  # when the branch exists, HEAD stays on main
    "git switch -c ana/x & git push origin HEAD",
]


@pytest.mark.parametrize("command", CHAINS_THE_GUARD_CANT_COUNT_ON)
def test_a_cd_or_new_branch_counts_only_when_and_joins_it_to_the_push(command, on_main, tmp_path_factory):
    git_in(on_main, "commit", "-q", "--allow-empty", "-m", "base")
    other = tmp_path_factory.mktemp("other")
    git_in(on_main, "worktree", "add", "-q", "-b", "ana/login", str(other))
    run = push_guard(command.format(other=other), on_main)
    assert merge_refused(run, "this push updates HEAD, and"), (command, run.stderr)


@pytest.mark.parametrize("command", ["git checkout -b ana/x && git -C {root} push origin HEAD",
                                     "git checkout -b ana/x && git --git-dir={root}/.git push origin HEAD",
                                     "git checkout -b ana/x && GIT_DIR={root}/.git git push origin HEAD",
                                     "git checkout -b ana/x && env -C {root} git push origin HEAD"])
def test_a_new_branch_names_head_only_in_the_folder_and_repo_it_was_made_in(command, on_main):
    git_in(on_main, "commit", "-q", "--allow-empty", "-m", "base")
    run = push_guard(command.format(root=on_main), on_main)
    assert merge_refused(run), (command, run.stderr)


def test_a_push_of_every_branch_is_refused_while_the_clone_has_the_base(on_main, tmp_path_factory):
    assert push_guard("git push --all origin", on_main).returncode == 0  # no commit yet, so no local main
    git_in(on_main, "commit", "-q", "--allow-empty", "-m", "base")
    run = push_guard("git push --all origin", on_main)
    assert merge_refused(run, "`git push --all` pushes every local branch, main among them")
    assert push_guard("git push --all --dry-run origin", on_main).returncode == 0


def github(folder: Path, default: str | None = None, branches: dict[str, str] | None = None, pr: str = "",
           aliases: str = "") -> str:
    """A folder with a stub gh that stands in for GitHub, and logs each call: `gh api .../contents/.colony/colony.toml`
    prints `default`, or the copy on `branches[ref]` with ?ref=, and fails when there is none; `gh pr view` prints `pr`,
    "<base> <url>", and fails when it is empty; `gh alias list` prints `aliases`."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in {"default": default, **(branches or {})}.items():
        if text is not None:
            (folder / f"host-{name}.toml").write_text(text)
    (folder / "pr").write_text(pr)
    (folder / "aliases").write_text(aliases)
    gh = folder / "gh"
    gh.write_text(f'''#!/bin/sh
D="{folder}"
echo "$@" >> "$D/gh.log"
for last; do :; done
if [ "$1" = api ]; then
  case "$last" in
    *contents/.colony/colony.toml\\?ref=*) ref="${{last#*\\?ref=}}" ;;
    *contents/.colony/colony.toml) ref=default ;;
    *) exit 0 ;;
  esac
  [ -f "$D/host-$ref.toml" ] && exec cat "$D/host-$ref.toml"
  exit 1
fi
if [ "$1 $2" = "pr view" ]; then [ -s "$D/pr" ] && exec cat "$D/pr"; exit 1; fi
if [ "$1 $2" = "alias list" ]; then exec cat "$D/aliases"; fi
exit 0
''')
    gh.chmod(0o755)
    return str(folder)


ALLOW_MAIN = '[project]\nbase = "main"\n\n[safety]\nmerge_into = ["main"]\n'


@pytest.fixture
def hosted(on_main):
    """A clone whose origin is acme/demo on GitHub."""
    git_in(on_main, "remote", "add", "origin", "https://github.com/acme/demo.git")
    return on_main


@pytest.mark.parametrize("command", UPDATES_BASE)
def test_a_plain_push_into_a_branch_merge_into_names_on_github_runs(command, hosted, tmp_path):
    (hosted / ".colony" / "colony.toml").write_text(ALLOW_MAIN)
    run = push_guard(command, hosted, path=github(tmp_path / "gh", default=ALLOW_MAIN))
    assert (run.returncode, run.stderr) == (0, ""), command


def test_merge_into_counts_only_what_the_copy_on_the_code_hosts_default_branch_names(hosted, tmp_path):
    """An agent can't allow itself a merge by editing its own colony.toml, nor by rewriting a ref on its computer: the
    copy on GitHub's default branch, which the person merged, must name the branch too."""
    (hosted / ".colony" / "colony.toml").write_text(ALLOW_MAIN)
    unnamed = '[project]\nbase = "main"\n'
    assert merge_refused(push_guard("git push origin main", hosted, path=github(tmp_path / "a", default=unnamed)))
    assert merge_refused(push_guard("git push origin main", hosted, path=github(tmp_path / "b")))  # can't be read
    assert merge_refused(push_guard("git push origin main", on_main_no_gh(hosted)))  # no gh at all
    # A copy of origin's main forged on this computer counts for nothing.
    git_in(hosted, "add", "-A")
    git_in(hosted, "commit", "-q", "-m", "allow main")
    git_in(hosted, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert merge_refused(push_guard("git push origin main", hosted, path=github(tmp_path / "c", default=unnamed)))
    assert push_guard("git push origin main", hosted, path=github(tmp_path / "d", default=ALLOW_MAIN)).returncode == 0
    # A pattern only the working copy names counts for nothing either, and a working copy can only narrow the list.
    (hosted / ".colony" / "colony.toml").write_text('[project]\nbase = "main"\n\n[safety]\nmerge_into = ["m*"]\n')
    assert merge_refused(push_guard("git push origin main", hosted, path=github(tmp_path / "e", default=ALLOW_MAIN)))
    (hosted / ".colony" / "colony.toml").write_text(unnamed)
    assert merge_refused(push_guard("git push origin main", hosted, path=github(tmp_path / "f", default=ALLOW_MAIN)))


def on_main_no_gh(root: Path) -> str:
    """A folder whose gh always fails, as when gh isn't signed in."""
    folder = root.parent / f"{root.name}-no-gh"
    folder.mkdir(exist_ok=True)
    (folder / "gh").write_text("#!/bin/sh\nexit 4\n")
    (folder / "gh").chmod(0o755)
    return str(folder)


def test_the_base_the_default_copy_names_counts_unless_agents_may_push_to_it(hosted, tmp_path):
    (hosted / ".colony" / "colony.toml").write_text('[project]\nbase = "dev"\n\n[safety]\nmerge_into = ["dev", "main"]\n')
    default = '[project]\nbase = "dev"\n'
    on_dev = '[project]\nbase = "dev"\n\n[safety]\nmerge_into = ["dev"]\n'
    stub = github(tmp_path / "a", default=default, branches={"dev": on_dev})
    assert push_guard("git push origin dev", hosted, path=stub).returncode == 0
    assert "contents/.colony/colony.toml?ref=dev" in (tmp_path / "a" / "gh.log").read_text()
    # Once the default copy lets agents push to dev, dev's own copy could be an agent's: only the default copy counts.
    default = '[project]\nbase = "dev"\n\n[safety]\nmerge_into = ["dev"]\n'
    stub = github(tmp_path / "b", default=default, branches={"dev": '[safety]\nmerge_into = ["dev", "main"]\n'})
    assert push_guard("git push origin dev", hosted, path=stub).returncode == 0
    assert merge_refused(push_guard("git push origin main", hosted, path=stub), "this push updates main")


def test_protect_adds_branches_and_patterns_to_the_ones_no_push_rewrites_or_updates(hosted, tmp_path):
    toml = ('[project]\nbase = "main"\n\n[safety]  # what agents may land\nprotect = [\n  "staging",  # the demo\n'
            '  "release/[0-9]*",\n]\nmerge_into = ["release/*"]\n')
    (hosted / ".colony" / "colony.toml").write_text(toml)
    stub = github(tmp_path / "gh", default=toml)
    assert merge_refused(push_guard("git push origin staging", hosted, path=stub), "this push updates staging")
    run = push_guard("git push --force origin release/1.2", hosted, path=stub)
    assert run.returncode == 2 and "this push force-pushes release/1.2" in run.stderr
    assert push_guard("git push origin release/1.2", hosted, path=stub).returncode == 0  # merge_into names it
    assert push_guard("git push origin release-notes", hosted, path=stub).returncode == 0


FORGES = [
    "git update-ref refs/remotes/origin/main 1234567",
    "git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/ana/login",
    "git fetch . ana/login:refs/remotes/origin/main",
    "git fetch origin +refs/heads/ana/login:refs/remotes/origin/main",
    "git remote set-head origin ana/login",
    "git remote set-url origin https://github.com/someone/else.git",
    "git remote rename origin old",
    "git config remote.origin.url https://github.com/someone/else.git",
    "git config --file .git/config remote.origin.fetch +refs/heads/x:refs/remotes/origin/main",
    "git config set remote.origin.fetch +refs/heads/x:refs/remotes/origin/main",
    "git config --unset remote.origin.fetch",
    "git -c remote.origin.fetch=+refs/heads/x:refs/remotes/origin/main fetch",
    "git config url.https://github.com/someone/.insteadOf https://github.com/acme/",
]
NO_FORGE = [
    "git fetch origin", "git fetch origin main", "git pull --rebase origin main", "git remote set-head origin -a",
    "git remote -v", "git config --get remote.origin.url", "git config remote.origin.url", "git config user.name T",
    "git update-ref refs/heads/ana/x HEAD", "git remote add upstream https://github.com/acme/demo.git",
]


@pytest.mark.parametrize("command", FORGES)
def test_the_merge_guard_refuses_a_rewrite_of_what_it_reads_as_origin(command, hosted):
    run = push_guard(command, hosted)
    assert merge_refused(run), (command, run.stderr)


@pytest.mark.parametrize("command", NO_FORGE)
def test_the_merge_guard_lets_an_ordinary_fetch_or_config_read_run(command, hosted):
    run = push_guard(command, hosted)
    assert (run.returncode, run.stderr) == (0, ""), command


ALIASES_THAT_PUSH = [
    "bash -c 'git push origin main'",
    "eval 'git push origin main'",
    "sudo -u ana git push origin main",
    "git -c alias.p='push origin main' p",
    "git -c alias.p='!git push origin main' p",
    "git config alias.p 'push origin main' && git p",
    "echo main | xargs git push origin",
    "alias gp='git push origin main'",
]


@pytest.mark.parametrize("command", ALIASES_THAT_PUSH)
def test_the_merge_guard_follows_shells_sudo_and_aliases_to_the_push(command, hosted):
    run = push_guard(command, hosted)
    assert merge_refused(run), (command, run.stderr)


def test_a_git_alias_in_config_is_read_as_what_it_runs(hosted):
    git_in(hosted, "config", "alias.ship", "push origin main")
    git_in(hosted, "config", "alias.sh-ship", "!git push origin main")
    git_in(hosted, "config", "alias.st", "status")
    assert merge_refused(push_guard("git ship", hosted), "this push updates main")
    assert merge_refused(push_guard("git sh-ship", hosted), "this push updates main")
    assert push_guard("git st", hosted).returncode == 0
    assert push_guard("git lfs pull", hosted).returncode == 0  # an outside git-lfs program, no alias


GH_API_MERGES = [
    "gh api -X PUT repos/acme/demo/pulls/5/merge",
    "gh api --method PUT /repos/{owner}/{repo}/pulls/5/merge -f merge_method=squash",
    "gh api repos/acme/demo/merges -f base=main -f head=ana/login",
    "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"X\"}) { clientMutationId } }'",
    "gh api graphql -F query='mutation { enablePullRequestAutoMerge(input: {pullRequestId: \"X\"}) { clientMutationId } }'",
]


@pytest.mark.parametrize("command", ["gh pr merge 5 --squash", "gh pr merge", "gh -R acme/demo pr merge 5 --auto",
                                     "npm test && gh pr merge https://github.com/acme/demo/pull/5 -d"])
def test_the_merge_guard_refuses_every_pr_merge_while_merge_into_is_empty(command, hosted, tmp_path):
    run = push_guard(command, hosted, path=github(tmp_path / "gh"))
    assert merge_refused(run, "`gh pr merge` merges a pull request, and [safety] merge_into allows no branch"), command
    assert not (tmp_path / "gh" / "gh.log").exists()  # no network call when nothing is allowed


ALLOW_DEV = '[project]\nbase = "dev"\n\n[safety]\nmerge_into = ["dev"]\n'


def test_a_pr_merge_runs_only_into_a_branch_merge_into_names_in_this_repo(hosted, tmp_path):
    (hosted / ".colony" / "colony.toml").write_text(ALLOW_DEV)
    stub = github(tmp_path / "dev", default=ALLOW_DEV, pr="dev https://github.com/acme/demo/pull/5")
    assert push_guard("gh pr merge 5 --squash -R acme/demo", hosted, path=stub).returncode == 0
    assert "pr view 5 --repo acme/demo --json baseRefName,url" in (tmp_path / "dev" / "gh.log").read_text()
    for pr, reason in (("main https://github.com/acme/demo/pull/5", "this pull request merges into main, which"),
                       ("dev https://github.com/someone/else/pull/5", "this pull request is in someone/else, not in "
                                                                       "this repo's origin, acme/demo"),
                       ("", "`gh pr view` could not say which branch")):
        stub = github(tmp_path / f"case-{len(pr)}", default=ALLOW_DEV, pr=pr)
        assert merge_refused(push_guard("gh pr merge 5", hosted, path=stub), reason), pr
    stub = github(tmp_path / "off", default=ALLOW_DEV, pr="main https://github.com/acme/demo/pull/5")
    assert push_guard("gh pr merge 5 --disable-auto", hosted, path=stub).returncode == 0


@pytest.mark.parametrize("command", ["cd /tmp && gh pr merge 5", "GH_REPO=someone/else gh pr merge 5",
                                     "export GH_REPO=someone/else; gh pr merge 5", "env -C /tmp gh pr merge 5",
                                     "GH_HOST=example.com gh pr merge 5", "HOME=/tmp gh pr merge 5"])
def test_a_pr_merge_that_shares_its_line_with_another_repo_or_folder_is_refused(command, hosted, tmp_path):
    (hosted / ".colony" / "colony.toml").write_text(ALLOW_DEV)
    stub = github(tmp_path / "gh", default=ALLOW_DEV, pr="dev https://github.com/acme/demo/pull/5")
    assert merge_refused(push_guard(command, hosted, path=stub), "`gh pr merge` shares its line with"), command


@pytest.mark.parametrize("command", ["gh m 5", "gh ship 5", "bash -c 'gh pr merge 5'", "eval 'gh pr merge 5'",
                                     "gh alias set m 'pr merge'", "gh alias set m '!gh api -X PUT x'",
                                     "gh alias import aliases.yml", "echo 5 | xargs gh pr merge",
                                     "alias m='gh pr merge'"])
def test_the_merge_guard_follows_gh_aliases_and_shells_to_the_merge(command, hosted, tmp_path):
    stub = github(tmp_path / "gh", aliases="co: pr checkout\nm: pr merge\nship: '!gh pr merge \"$1\"'\n")
    assert merge_refused(push_guard(command, hosted, path=stub)), command
    assert push_guard("gh co 5", hosted, path=stub).returncode == 0


@pytest.mark.parametrize("command", GH_API_MERGES)
def test_a_merge_through_the_api_is_refused_even_into_an_allowed_branch(command, hosted, tmp_path):
    (hosted / ".colony" / "colony.toml").write_text(ALLOW_MAIN)
    assert merge_refused(push_guard(command, hosted, path=github(tmp_path / "gh", default=ALLOW_MAIN)), "`gh api"), \
        command


@pytest.mark.parametrize("command", ["gh api repos/acme/demo/pulls/5/merge", "gh pr view 5", "gh pr create --base main",
                                     "gh api repos/acme/demo/merges", "git merge origin/main", "colony merge ana/login",
                                     "echo gh pr merge 5", "gh dash"])
def test_the_merge_guard_lets_a_command_that_merges_nothing_on_github_run(command, hosted, tmp_path):
    assert push_guard(command, hosted, path=github(tmp_path / "gh")).returncode == 0, command


def tool_guard(tool: str, tool_input: dict, root: Path, path: str = "") -> subprocess.CompletedProcess:
    """Run the guard on a GitHub tool's call, as Claude Code runs it for the PreToolUse matcher's MCP tools."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    if path:
        env["PATH"] = os.pathsep.join([path, env["PATH"]])
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps({"cwd": str(root), "tool_name": tool,
                          "tool_input": tool_input}), capture_output=True, text=True, env=env)


def test_a_github_tools_merge_and_commit_onto_a_protected_branch_are_refused(hosted, tmp_path):
    # The working copy's [project] repo is an agent's to edit, so the guard knows this repo by origin's URL alone.
    (hosted / ".colony" / "colony.toml").write_text('[project]\nrepo = "someone/else"\nbase = "main"\n')
    merge = {"owner": "acme", "repo": "demo", "pullNumber": 5}
    assert merge_refused(tool_guard("mcp__github__merge_pull_request", merge, hosted), "`merge_pull_request` merges")
    commit = {"owner": "acme", "repo": "demo", "branch": "main", "files": [], "message": "x"}
    assert merge_refused(tool_guard("mcp__github__push_files", commit, hosted), "`push_files` commits straight onto main")
    assert merge_refused(tool_guard("mcp__github__push_files", {**commit, "branch": ""}, hosted), "`push_files` names "
                                                                                                    "no branch")
    for tool, call in (("mcp__github__push_files", {**commit, "branch": "ana/login"}),
                       ("mcp__github__create_or_update_file", {**commit, "owner": "someone", "repo": "else"}),
                       ("mcp__github__get_file_contents", commit), ("mcp__other__search", {})):
        assert tool_guard(tool, call, hosted).returncode == 0, tool
    (hosted / ".colony" / "colony.toml").write_text(ALLOW_MAIN)
    stub = github(tmp_path / "b", default=ALLOW_MAIN, pr="main https://github.com/acme/demo/pull/5")
    assert tool_guard("mcp__github__merge_pull_request", merge, hosted, stub).returncode == 0
    assert "pr view 5 --repo acme/demo " in (tmp_path / "b" / "gh.log").read_text()
    assert tool_guard("mcp__github__push_files", commit, hosted, stub).returncode == 0
    for call, reason in (({**merge, "owner": ""}, "`merge_pull_request` names no pull request number, owner and repo"),
                         ({**merge, "owner": "someone", "repo": "else"}, "pull request 5 is in")):
        stub = github(tmp_path / f"c{len(reason)}", default=ALLOW_MAIN, pr="main https://github.com/someone/else/pull/5")
        assert merge_refused(tool_guard("mcp__github__merge_pull_request", call, hosted, stub), f"{reason}"), call


def test_a_github_tools_commit_is_refused_when_origin_cant_say_which_repo_this_is(on_main):
    commit = {"owner": "acme", "repo": "demo", "branch": "ana/login", "files": [], "message": "x"}
    assert merge_refused(tool_guard("mcp__github__push_files", commit, on_main), "`push_files` commits onto ana/login, "
                                                                                  "and the guard can't tell this repo")


KILLS = [
    'pkill -f "colony wait" -U $(id -u) -n',  # the line that ended every session on a computer
    "pkill -9 claude",
    "killall node",
    "/usr/bin/pkill -f merge",
    "sudo -u ana pkill node",
    "timeout 5 killall -9 node",
    "kill $(pgrep -f colony)",
    "kill -9 `pgrep node`",
    'kill "$(pgrep -f x)"',
    "pgrep -f merge | xargs kill",
    "ps aux | grep claude | awk '{print $2}' | xargs -r kill -9",
    "for p in $(pgrep -f x); do kill $p; done",
    "pid=$(pgrep -f x); kill $pid",
    "kill -9 $(lsof -ti :3000)",
    "kill -9 -1",
    "kill 0",
    "kill -TERM -- -4242",
    'bash -c "pkill -f x"',
    "eval 'killall node'",
    "fuser -k 3000/tcp",
    "taskkill /F /IM node.exe",
    "taskkill //IM node.exe //F",
    'powershell -Command "Stop-Process -Name node"',
    "pwsh -c 'Get-Process node | Stop-Process'",
    "xargs pkill < names.txt",
    "{ pkill x; }",
    "pkill x 2>/dev/null &",
]
KILL_ALLOWED = [
    "kill 12345",
    "kill -9 12345",
    "kill -s TERM 12345",
    "kill %1",
    "npm run dev & sleep 1; kill $!",
    "ps -p 12345 -o pid=,command= && kill 12345",
    "kill -l",
    "kill $(cat server.pid)",
    "kill 12345 2>/dev/null",
    "kill -9 12345 1>/dev/null",
    'echo "pkill is refused"',
    "grep -rn killall docs/",
    "git log --grep=pkill",
    "colony stop builder-2",
    "taskkill /PID 4242 /F",
    "lsof -ti :3000",
    "pgrep -fl colony",
]


@pytest.mark.parametrize("command", KILLS)
def test_the_kill_guard_refuses_a_kill_by_name_or_pattern(command):
    run = guard(json.dumps({"tool_input": {"command": command}}))
    assert run.returncode == 2 and run.stderr.startswith("kill guard: refused, "), (command, run.stderr)
    assert "colony stop <name>" in run.stderr and "ps -p <pid>" in run.stderr
    assert guard(json.dumps({"tool_input": {"command": command, "run_in_background": True}})).returncode == 2


@pytest.mark.parametrize("command", KILL_ALLOWED)
def test_the_kill_guard_lets_a_kill_of_one_checked_process_run(command):
    run = guard(json.dumps({"tool_input": {"command": command}}))
    assert (run.returncode, run.stderr) == (0, ""), command


def test_the_kill_guard_names_what_each_kill_reaches():
    reasons = {"pkill -f x": "`pkill` signals every process its name or pattern matches",
               "kill $(pgrep x)": "this `kill` takes its process ids from a search of the running processes",
               "kill -9 -1": "`kill -1` signals every process you own",
               "kill -- -4242": "`kill -4242` signals the whole process group 4242",
               "fuser -km /mnt": "`fuser -k` signals every process that uses a file or a port"}
    for command, reason in reasons.items():
        assert reason in guard(json.dumps({"tool_input": {"command": command}})).stderr, command
    unreadable = """echo "$(echo 'a"b')"; pkill -f x"""
    run = guard(json.dumps({"tool_input": {"command": unreadable}}))
    assert run.returncode == 2 and "run the kill as a command of its own" in run.stderr


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
                                         "SessionStart", "SessionEnd", "Stop"], [])
    data = json.loads(path.read_text())
    assert data["permissions"] == {"deny": ["Read(**/.env)"]}
    for event, groups in theirs.items():
        assert data["hooks"][event][:len(groups)] == groups, event
    assert ".colony/hooks/wait_guard.py" in data["hooks"]["PreToolUse"][1]["hooks"][0]["command"]
    assert data["hooks"]["PreToolUse"][1]["matcher"] == guards.GUARD_MATCHER  # Bash, and GitHub tools that merge
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


def test_an_install_widens_the_old_guards_matcher_and_leaves_a_group_of_the_persons_own_hooks(tmp_path):
    path = tmp_path / "settings.json"
    guards.merge_hooks(path)
    data = json.loads(path.read_text())
    data["hooks"]["PreToolUse"][0]["matcher"] = "Bash"  # the guard's group from before the merge guard
    path.write_text(json.dumps(data))
    assert guards.merge_hooks(path) == ([], ["PreToolUse"])
    assert json.loads(path.read_text())["hooks"]["PreToolUse"][0]["matcher"] == guards.GUARD_MATCHER
    data["hooks"]["PreToolUse"][0]["hooks"].append({"type": "command", "command": "my-own-guard"})
    path.write_text(json.dumps(data))
    guards.merge_hooks(path)
    assert json.loads(path.read_text())["hooks"]["PreToolUse"][0]["matcher"] == "Bash"


def test_the_guards_matcher_sends_it_every_github_tool_the_merge_guard_reads():
    spec = importlib.util.spec_from_file_location("wait_guard", GUARD)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    matcher = re.compile(guards.GUARD_MATCHER)
    for action in script.MCP_PR_MERGES | script.MCP_COMMITS:
        assert matcher.fullmatch(f"mcp__github__{action}"), action
    for tool in ("Bash", "mcp__github__merge_pull_request"):
        assert matcher.fullmatch(tool)
    assert not matcher.fullmatch("mcp__github__get_pull_request") and not matcher.fullmatch("Edit")


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
    assert set(data["hooks"]) == {"PreToolUse", "Notification", "StopFailure", "UserPromptSubmit", "SessionStart",
                                  "SessionEnd", "Stop"}
    env = {"PATH": os.environ["PATH"], "CLAUDE_PROJECT_DIR": str(repo)}
    command = commands(data, "PreToolUse")[0]
    for call, code in (("sleep 30", 2), ("npm test", 0)):
        run = subprocess.run(["sh", "-c", command], input=json.dumps({"tool_input": {"command": call}}),
                             capture_output=True, text=True, env=env)
        assert run.returncode == code, (call, run.stderr)
    for event in ("Notification", "StopFailure", "UserPromptSubmit", "SessionStart", "SessionEnd", "Stop"):
        # a session not Colony's runs nothing
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


def test_a_here_documents_body_on_a_line_whose_quoting_cant_be_read_holds_no_kill_or_merge():
    unreadable = """echo "$(echo 'a"b')"; cat <<EOF > notes.md\npkill -f x, then gh pr merge 5\nEOF"""
    assert guard(json.dumps({"tool_input": {"command": unreadable}})).returncode == 0


# A `<<` counts as a here-document only where the shell reads commands, and its body only up to an exact terminator:
# text that merely looks like one never hides the lines after it from any guard.
UNREADABLE = """echo "$(echo 'a"b')" """
FAKE_HEREDOCS = [
    'echo "<<EOF"\n{hidden}',  # the << is in double quotes
    "echo '<<EOF'\n{hidden}",  # in single quotes
    "# <<EOF\n{hidden}",  # in a comment
    UNREADABLE + '"<<EOF"\n{hidden}',  # on a line whose quoting can't be read
    "cat <<EOF\n{hidden}",  # a here-document with no terminator
    "cat <<EOF\n{hidden}\nEOF ",  # a terminator line that isn't the delimiter exactly
    "cat <<-EOF\n{hidden}\n  EOF",  # <<- strips leading tabs alone
    UNREADABLE + "; cat <<EOF\n{hidden}",
]


@pytest.mark.parametrize("fake", FAKE_HEREDOCS)
def test_a_fake_here_document_hides_no_kill(fake):
    run = guard(json.dumps({"tool_input": {"command": fake.format(hidden="pkill -f x")}}))
    assert run.returncode == 2 and run.stderr.startswith("kill guard: refused, "), (fake, run.stderr)


@pytest.mark.parametrize("fake", FAKE_HEREDOCS)
def test_a_fake_here_document_hides_no_merge(fake, hosted):
    run = push_guard(fake.format(hidden="gh pr merge 5"), hosted)
    assert merge_refused(run), (fake, run.stderr)


@pytest.mark.parametrize("fake", FAKE_HEREDOCS[:3])
def test_a_fake_here_document_hides_no_push_or_wait(fake, hosted):
    assert merge_refused(push_guard(fake.format(hidden="git push origin main"), hosted))
    assert guard(json.dumps({"tool_input": {"command": fake.format(hidden="sleep 600")}})).returncode == 2


@pytest.mark.parametrize("command", [
    "cat <<-EOF\n\tpkill -f x\n\tEOF",
    "git commit -m \"$(cat <<'EOF'\nfeat: refuse pkill and gh pr merge 5\n\nkill $(pgrep x) too\nEOF\n)\"",
    "echo $((1 << 2)); cat <<<'pkill x'",
    "(( n = 1 << 3 )); echo $n",
])
def test_a_real_here_document_or_shift_still_reads_as_text(command):
    run = guard(json.dumps({"tool_input": {"command": command}}))
    assert (run.returncode, run.stderr) == (0, ""), command
