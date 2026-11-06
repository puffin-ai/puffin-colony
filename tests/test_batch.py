"""Tests for colony batch and colony status, using temporary git repositories and stub `claude` and `gh` commands."""

import os
import re
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from colony import batch, cli
from colony.batch import Finding

RUBRIC = ["bugs", "security and privacy", "data loading", "contract and write path",
          "design system and structure", "accessibility", "tests", "library use"]

CLAUDE_STUB = r'''#!/usr/bin/env python3
import json, os, re, subprocess, sys
from pathlib import Path
prompt = sys.argv[sys.argv.index("-p") + 1]
with open(os.environ["COLONY_STUB_LOG"], "a") as log:
    log.write(prompt.splitlines()[0][:50] + "\n")
report = re.search(r"Write your report to (\S+):", prompt)
if "fresh batch reviewer" in prompt:
    later = re.search(r"review-(\d+)\.md", report[1])[1] != "1"
    Path(report[1]).write_text("open: 0\n- tests: 0\nb.txt:1 — the line is wrong — tests — fixed\n" if later else
        "open: 3\n- tests: 3\n" + "".join(f"b.txt:{n} — line {n} is wrong — tests — change it\n" for n in (1, 2, 3)))
elif "fast builder" in prompt and os.environ.get("COLONY_STUB_MODE") != "lazy":
    checkout = re.search(r"Work only in (\S+), on its branch", prompt)[1]
    Path(checkout, "b.txt").write_text("fixed\n")
    subprocess.run(["git", "-C", checkout, "commit", "-qam", "fix b"], check=True)
print(json.dumps({"total_cost_usd": 0.25, "duration_ms": 90000, "is_error": False}))
'''

GH_STUB = r'''#!/bin/sh
printf '%s\n' "$@" >> "$COLONY_GH_LOG"
case "$1 $2" in
  "issue view") printf '%s' '{"title": "builder-1: the card", "body": "predicted: S, 20 min", "comments": []}' ;;
  *) echo https://example.test/pull/1 ;;
esac
'''


def git(cwd, *args, date=None):
    """Run git in cwd, with a fixed commit date when one is given, and return its output."""
    env = {**os.environ, **({"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {})}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, files, message, date=None):
    """Write the files and commit them."""
    for name, text in files.items():
        path = Path(repo, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message, date=date)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A clone of a bare origin with main and the card branches card/a, card/b and card/c."""
    (tmp_path / "gitconfig").write_text("")
    for key, value in {"GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.test",
                       "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.test"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("COLONY_PERSON", raising=False)
    origin, clone = tmp_path / "origin.git", tmp_path / "repo"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(clone))
    commit(clone, {"a.txt": "a\n", "b.txt": "b\n", "shared.txt": "s\n", "gen/api.json": "{}\n"}, "base",
           date="2026-01-01T00:00:00")
    git(clone, "remote", "add", "origin", str(origin))
    git(clone, "push", "-q", "origin", "main")
    for branch, files, date in [("card/a", {"a.txt": "a1\n", "gen/api.json": '{"a": 1}\n'}, "2026-01-02T00:00:00"),
                                ("card/b", {"b.txt": "b1\n", "gen/api.json": '{"b": 1}\n'}, "2026-01-03T00:00:00"),
                                ("card/c", {"a.txt": "c1\n"}, "2026-01-04T00:00:00")]:
        git(clone, "checkout", "-q", "-b", branch, "main")
        commit(clone, files, branch, date=date)
    git(clone, "checkout", "-q", "main")
    return clone


@pytest.fixture
def config(tmp_path):
    """A colony.toml for a demo project, loaded the way the command line loads it."""
    roles = "\n".join(f'{role} = {{ model = "m-{role}", effort = "low" }}'
                      for role in cli.ROLES)
    (tmp_path / "colony.toml").write_text(f'''
[project]
name = "demo"
repo = "example/demo"
base = "main"
worktrees = "{tmp_path / 'wt'}"
checks = "true"
web_checks = "true"
backend_paths = ["api/"]
generated = ["gen/*"]
regen = "true"
[accounts.one]
config_dir = "{tmp_path / 'account'}"
person = "pat"
[roles]
{roles}
[gate]
rubric = {RUBRIC!r}
rules = ["rules/*.md"]
max_rounds = 3
walk = true
walk_paths = ["web/"]
[budget]
provider_dollars = 0
''')
    return cli.load_config(tmp_path / "colony.toml")


@pytest.fixture
def stubs(tmp_path, monkeypatch):
    """Put stub claude and gh commands first on PATH; return the files they log their calls to. The tidy every batch
    ends with (batch.tidy_at_end) only logs the batch's name here, so the gh log holds the batch's own calls; tidy has
    its own tests in test_tidy.py."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in (("claude", CLAUDE_STUB), ("gh", GH_STUB)):
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    logs = {"claude": tmp_path / "claude.log", "gh": tmp_path / "gh.log", "tidy": tmp_path / "tidy.log"}
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("COLONY_STUB_LOG", str(logs["claude"]))
    monkeypatch.setenv("COLONY_GH_LOG", str(logs["gh"]))
    monkeypatch.setattr(batch, "tidy_at_end", lambda b: logs["tidy"].open("a").write(f"{b.name}\n"))
    return logs


def batch_args(repo, *cards, dry_run=False):
    """The args the parser makes for `colony batch`."""
    return Namespace(name="b1", card=list(cards), from_branch=None, dry_run=dry_run, repo=str(repo))


def test_fill_replaces_every_placeholder_and_refuses_a_missing_one():
    assert batch.fill("{a} and {b}", a=1, b="two") == "1 and two"
    with pytest.raises(KeyError, match="b"):
        batch.fill("{a} and {b}", a=1)


def test_conflict_is_generated_only_when_every_path_is_generated():
    globs = ["*/generated/*", "contracts/generated/manifest.json"]
    assert batch.classify_conflict(["apps/web/generated/api.ts", "contracts/generated/manifest.json"], globs) == "generated"
    assert batch.classify_conflict(["apps/web/generated/api.ts", "apps/web/src/page.tsx"], globs) == "other"
    assert batch.classify_conflict([], globs) == "other"


def test_open_count_and_walk_parse_from_the_first_line():
    assert batch.parse_open("open: 3\n- bugs: 1\n") == 3
    assert batch.parse_open("\n**open: 0**\n") == 0
    assert batch.parse_open("Two problems stay open\nopen: 2") is None
    assert batch.parse_open("score: 8/8") is None
    assert batch.parse_walk("walk: fail\nlogin: fail") == "fail"
    assert batch.parse_walk("walk: pass") == "pass"
    assert batch.parse_walk("walked fine") is None


def test_findings_parse_from_file_line_lines_and_skip_fixed_ones():
    report = """open: 2
- bugs: 0
- tests: 1
apps/web/src/a.tsx:12 — the old finding — bugs — fixed
- apps/web/src/b.tsx:30-34 — reads the list twice — data loading — read it once
`apps/backend/x.py:7` — no test for the empty case — tests — add one
apps/web/src/b.tsx:30 — the same finding again — data loading — read it once
"""
    assert batch.parse_findings(report) == [
        Finding("apps/web/src/b.tsx", 30, "reads the list twice — data loading — read it once"),
        Finding("apps/backend/x.py", 7, "no test for the empty case — tests — add one"),
    ]


def test_walk_failures_and_check_failures_become_findings():
    walk = "walk: fail\nlogin: fail, 900ms\nlogin — the button does nothing — shots/login.png — apps/web/src/login.tsx:40\n"
    assert batch.parse_walk_failures(walk) == [Finding("apps/web/src/login.tsx", 40, walk.splitlines()[2])]
    output = "FAIL backend (12s), exit 1\nFAILED tests/test_x.py::test_empty - AssertionError\n"
    assert batch.parse_check_failures(output) == [Finding("tests/test_x.py", 0, "failing test tests/test_x.py::test_empty")]
    assert batch.parse_check_failures("FAIL web lint (3s), exit 1\n")[0].path == ""


def test_a_finding_reaches_the_card_that_last_touched_its_file(repo):
    git(repo, "checkout", "-q", "card/a")
    commit(repo, {"shared.txt": "from a\n"}, "a shares", date="2026-01-05T00:00:00")
    git(repo, "checkout", "-q", "card/b")
    commit(repo, {"shared.txt": "from b\n"}, "b shares", date="2026-01-06T00:00:00")
    cards = {"11": "card/a", "12": "card/b"}
    for base in (None, "main"):
        assert batch.owner_of("a.txt", cards, repo, base) == "11"
        assert batch.owner_of("b.txt", cards, repo, base) == "12"
        assert batch.owner_of("shared.txt", cards, repo, base) == "12"
        assert batch.owner_of("nobody.txt", cards, repo, base) == "11"
        assert batch.owner_of("", cards, repo, base) == "11"


def test_minutes_table_sums_each_kind_of_step():
    table = batch.minutes_table(["10:00 assemble 0.5", "10:01 review-r1 3.0 $0.50", "10:01 checks-r1 4.0",
                                 "10:09 review-r2 2.0 $0.25", "not a minutes line"])
    assert "| assemble | 1 | 0.5 | $0.00 |" in table
    assert "| review | 2 | 5.0 | $0.75 |" in table
    assert "| **total** | 4 | 9.5 | $0.75 |" in table


def test_agents_run_on_the_picked_account_without_an_api_key(repo, config, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used")
    env = batch.Batch.from_args(config, batch_args(repo, "11=card/a")).agent_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert env["CLAUDE_CONFIG_DIR"] == config["accounts"]["one"]["config_dir"]


def test_the_session_person_comes_from_colony_person(repo, config, monkeypatch):
    monkeypatch.setenv("COLONY_PERSON", "nobody")
    with pytest.raises(Exception, match="nobody"):
        batch.Batch.from_args(config, batch_args(repo, "11=card/a"))


def test_dry_run_prints_the_plan_and_runs_no_claude(repo, config, stubs, capsys):
    assert batch.run_batch(config, batch_args(repo, "11=card/a", "12=card/b", dry_run=True)) == 0
    out = capsys.readouterr().out
    assert not stubs["claude"].exists()
    assert not Path(config["project"]["worktrees"]).exists()
    for expected in ("demo/batch-b1 from origin/main", "git merge --no-ff --no-edit card/b", "--model m-reviewer",
                     "open: N", "8. library use", "done at checks pass, open: 0", "origin/main...HEAD", "--- walker", "--- fixer, for card #11",
                     "refs/heads/demo/batch-b1:refs/heads/demo/batch-b1", "gh pr create --repo example/demo --base main"):
        assert expected in out
    assert re.search(r"\{\w+\}", out) is None


def test_a_batch_loops_a_fix_to_its_card_and_opens_the_pr(repo, config, stubs, capsys):
    main_before = git(repo, "rev-parse", "origin/main")
    assert batch.run_batch(config, batch_args(repo, "11=card/a", "12=card/b")) == 0
    assert "done in round 2. https://example.test/pull/1" in capsys.readouterr().out
    origin = repo.parent / "origin.git"
    assert git(origin, "rev-parse", "main") == main_before
    assert git(origin, "branch", "--list", "demo/fix-*") == ""
    log = git(origin, "log", "--format=%s", "demo/batch-b1")
    assert "fix b" in log and "docs(colony): batch b1 reports" in log
    assert git(origin, "show", "demo/batch-b1:gen/api.json") == '{"b": 1}'
    assert "demo/fix-b1-12-r1" in git(repo, "branch", "--list", "demo/fix-*")
    reports = Path(config["project"]["worktrees"]) / "demo-batch-b1" / ".colony" / "reports" / "b1"
    body = (reports / "pr.md").read_text()
    assert "## Open problems by round\n3 → 0\n" in body
    assert "| 1 | 3 | skipped | pass |" in body and "| 2 | 0 | skipped | pass |" in body
    assert "| review | 2 | 3.0 | $0.50 |" in body and "None." in body
    gh = stubs["gh"].read_text().splitlines()
    create = gh.index("create") - 1  # after the card stats read each card with `gh issue view`
    assert gh[create:create + 3] == ["pr", "create", "--repo"] and "demo/batch-b1" in gh and "main" in gh
    assert gh[:3] == ["issue", "view", "11"]
    assert "## Card stats\n" in body and "| #11 | builder-1 | S | no start line | 20 |" in body
    assert stubs["claude"].read_text().count("You are a fast builder") == 1
    assert batch.batch_status(config, Namespace(name="b1", repo=str(repo))) == 0
    status = capsys.readouterr().out
    assert "round 2, open 0 (round 2), walk none yet" in status and "running: nothing" in status


def test_a_fixer_that_commits_nothing_stops_the_batch(repo, config, stubs, capsys, monkeypatch):
    monkeypatch.setenv("COLONY_STUB_MODE", "lazy")
    assert batch.run_batch(config, batch_args(repo, "11=card/a", "12=card/b")) == 1
    assert "the fixer for #12 in round 1 committed nothing" in capsys.readouterr().out
    assert git(repo.parent / "origin.git", "branch", "--list", "demo/*") == ""
    assert not stubs["gh"].exists()


def test_a_conflict_outside_generated_paths_stops_the_batch(repo, config, stubs, capsys):
    assert batch.run_batch(config, batch_args(repo, "11=card/a", "13=card/c")) == 1
    assert "merging card/c conflicts outside the generated paths: a.txt" in capsys.readouterr().out
    assert not stubs["claude"].exists()
    stopped = git(repo, "rev-parse", "demo/batch-b1")
    assert batch.run_batch(config, batch_args(repo, "11=card/a")) == 1
    assert "already exists; pick another --name" in capsys.readouterr().out
    assert git(repo, "rev-parse", "demo/batch-b1") == stopped


# Colony 0.2: the reviewer's risk list, the card stats in the PR body, and the agents' account


def test_the_reviewer_reads_the_batch_risk_list_first(repo, config):
    git(repo, "checkout", "-q", "-b", "card/d", "main")
    commit(repo, {"auth/session.py": "TOKEN_TTL = 30\n", "a.txt": "d\n"}, "sessions")
    git(repo, "push", "-q", "origin", "main")
    b = batch.Batch.from_args(config, batch_args(repo, "14=card/d"))
    b.wt = repo
    prompt = batch.reviewer_prompt(b, 1, "card/d", None, batch.risk_list(b, "card/d"))
    rest = prompt.split("Read these places first.", 1)[1]
    assert "- auth: auth/session.py" in rest.split("Check the batch", 1)[0]
    assert re.search(r"\{\w+\}", prompt) is None
    assert batch.risk_list(b, "main") == "- none found"


def test_a_risk_list_git_cant_read_never_stops_the_review(repo, config):
    config["project"]["base"] = "gone"
    b = batch.Batch.from_args(config, batch_args(repo, "11=card/a"))
    b.wt = repo
    assert batch.risk_list(b, "card/a").startswith("- the risk list could not be read (the base origin/gone names no")


def test_card_stats_that_cant_be_read_leave_a_line_in_the_pr_body(repo, config, monkeypatch):
    from colony import cycle

    def unreadable(*args, **kwargs):
        raise cli.ColonyError("gh issue view failed: HTTP 502\nmore detail")

    monkeypatch.setattr(cycle, "stats_table", unreadable)
    b = batch.Batch.from_args(config, batch_args(repo, "11=card/a"))
    assert batch.card_stats(b) == "The card stats could not be read: gh issue view failed: HTTP 502."


def test_the_agents_run_on_account_else_on_the_persons_first_account_with_room(repo, config, tmp_path):
    config["accounts"]["admin"] = {"config_dir": str(tmp_path / "admin"), "person": "pat"}
    for folder in ("admin", "account"):
        (tmp_path / folder).mkdir()
    assert batch.Batch.from_args(config, batch_args(repo, "11=card/a")).account[0] == "one"
    config["people"] = {**config.get("people", {}), "pat": {"accounts": ["admin", "one"]}}
    assert batch.Batch.from_args(config, batch_args(repo, "11=card/a")).account == ("admin", str(tmp_path / "admin"))
    args = batch_args(repo, "11=card/a")
    args.account = "one"
    assert batch.Batch.from_args(config, args).account[0] == "one"


# Tidy at the end of every batch, the PR body's closing keywords, and hack mode's demo review


def test_every_batch_that_runs_ends_with_tidy_whether_it_opens_its_pr_or_stops(repo, config, stubs, capsys,
                                                                              monkeypatch):
    assert batch.run_batch(config, batch_args(repo, "11=card/a", "12=card/b")) == 0
    monkeypatch.setenv("COLONY_STUB_MODE", "lazy")
    args = batch_args(repo, "11=card/a", "12=card/b")
    args.name = "b2"
    assert batch.run_batch(config, args) == 1
    assert batch.run_batch(config, batch_args(repo, "11=card/a", dry_run=True)) == 0
    assert stubs["tidy"].read_text() == "b1\nb2\n"  # a dry run runs nothing, tidy included
    body = (Path(config["project"]["worktrees"]) / "demo-batch-b1" / ".colony" / "reports" / "b1" / "pr.md").read_text()
    assert body.startswith("## Cards\n- Closes #11, from `card/a`\n- Closes #12, from `card/b`\n")


def test_tidy_at_the_end_runs_colony_tidy_on_the_repo_and_a_failure_never_changes_the_batch(repo, config, capsys,
                                                                                         monkeypatch):
    from colony import tidy

    seen = []
    monkeypatch.setattr(tidy, "run_tidy", lambda config, root: seen.append(root))
    b = batch.Batch.from_args(config, batch_args(repo, "11=card/a"))
    batch.tidy_at_end(b)
    assert seen == [repo]

    def broken(config, root):
        raise cli.ColonyError("gh project list failed")

    monkeypatch.setattr(tidy, "run_tidy", broken)
    batch.tidy_at_end(b)
    assert "colony batch b1: tidy did not run: gh project list failed" in capsys.readouterr().out


HACK_TOML = '''
[project]
mode = "hack"
name = "demo"
repo = "example/demo"
base = "main"
worktrees = "{wt}"
checks = "false"
fast_check = "true"
[accounts.one]
config_dir = "{account}"
person = "pat"
[roles]
{roles}
[messages]
board = 12
'''


@pytest.fixture
def hack_config(tmp_path):
    """A hack mode colony.toml, with its board issue, #12."""
    roles = "\n".join(f'{role} = {{ model = "m-{role}", effort = "low" }}' for role in cli.ROLES)
    path = tmp_path / "hack.toml"
    path.write_text(HACK_TOML.format(wt=tmp_path / "wt", account=tmp_path / "account", roles=roles))
    return cli.load_config(path)


def demo_args(repo, dry_run=False):
    """The args the parser makes for `colony batch --review --name demo`, with no --card."""
    return Namespace(name="demo", card=None, from_branch=None, dry_run=dry_run, repo=str(repo), review=True)


def test_hack_review_with_no_cards_reviews_the_demo_build_and_posts_one_line_on_the_board(repo, hack_config, stubs,
                                                                                        capsys):
    head = git(repo, "rev-parse", "origin/main")
    assert batch.run_batch(hack_config, demo_args(repo)) == 0
    claude = stubs["claude"].read_text()
    assert claude.count("You are the fresh batch reviewer") == 1 and "fast builder" not in claude  # no fixers
    origin = repo.parent / "origin.git"
    report = git(origin, "show", "demo/batch-demo:.colony/reports/demo/review-1.md")
    assert report.startswith("open: 3")
    assert git(origin, "rev-parse", "main") == head  # the base never moves
    link = "https://github.com/example/demo/blob/demo/batch-demo/.colony/reports/demo/review-1.md"
    line = f"[pat's Claude] @all demo build {head[:7]} reviewed: open: 3, fast check pass, report: {link} (from pat-lead)"
    gh = stubs["gh"].read_text().splitlines()
    assert gh == ["issue", "comment", "12", "--repo", "example/demo", "--body", line]  # one line, and no pull request
    checks = (Path(hack_config["project"]["worktrees"]) / "demo-batch-demo" / ".colony" / "reports" / "demo" /
              "checks-1.md").read_text()
    assert "`true` exited 0" in checks  # the fast check, not the full checks
    assert stubs["tidy"].read_text() == "demo\n"
    assert f"open 3. {link}" in capsys.readouterr().out


def test_the_demo_reviewer_reads_the_whole_build_and_its_dry_run_runs_nothing(repo, hack_config, stubs, capsys):
    assert batch.run_batch(hack_config, demo_args(repo, dry_run=True)) == 0
    out = capsys.readouterr().out
    assert not stubs["claude"].exists() and not stubs["gh"].exists()
    for expected in ("one fresh reviewer", "no fixers", f"diff {batch.EMPTY_TREE} HEAD", "the demo build, origin/main",
                     "@all <the open count>", "--- reviewer"):
        assert expected in out, expected
    assert re.search(r"\{\w+\}", out) is None


def test_no_cards_is_the_demo_review_only_in_hack_mode_with_review(repo, config, hack_config):
    with pytest.raises(SystemExit, match="at least one --card"):
        batch.Batch.from_args(config, demo_args(repo))
    args = demo_args(repo)
    args.review = False
    with pytest.raises(SystemExit, match="--review alone reviews the demo build"):
        batch.Batch.from_args(hack_config, args)


def test_a_round_after_a_passing_walk_walks_only_when_a_screen_file_changes():
    settings = {"walk": True, "walk_paths": ["web/"]}
    passed = [{"walk": "pass"}]
    assert batch.should_walk(settings, [], ["web/lib/words.ts"])
    assert not batch.should_walk(settings, passed, ["web/lib/words.ts", "api/app.py"])
    assert batch.should_walk(settings, passed, ["web/lib/words.ts", "web/panel.tsx"])
    assert batch.should_walk(settings, [{"walk": "fail"}], ["api/app.py"])
    assert not batch.should_walk({"walk": False}, [], ["web/panel.tsx"])
