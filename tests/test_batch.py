"""Tests for colony batch and colony status, using temporary git repositories and stub `claude` and `gh` commands."""

import json
import os
import re
import subprocess
import time
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
    later = re.search(r"review-(\d+)\.md", report[1])[1] != "1" and os.environ.get("COLONY_STUB_MODE") != "stubborn"
    Path(report[1]).write_text("open: 0\n- tests: 0\nb.txt:1 — the line is wrong — tests — fixed\n" if later else
        "open: 3\n- tests: 3\n" + "".join(f"b.txt:{n} — line {n} is wrong — tests — change it\n" for n in (1, 2, 3)))
elif "fast builder" in prompt and os.environ.get("COLONY_STUB_MODE") != "lazy":
    checkout = re.search(r"Work only in (\S+), on its branch", prompt)[1]
    with open(Path(checkout, "b.txt"), "a") as fixed:
        fixed.write("fixed\n")
    subprocess.run(["git", "-C", checkout, "commit", "-qam", "fix b"], check=True)
print(json.dumps({"type": "result", "total_cost_usd": 0.25, "duration_ms": 90000, "is_error": False}))
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
worktrees = "{(tmp_path / 'wt').as_posix()}"
checks = "true"
backend_paths = ["api/"]
generated = ["gen/*"]
regen = "true"
[accounts.one]
config_dir = "{(tmp_path / 'account').as_posix()}"
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
    path.write_text(HACK_TOML.format(wt=(tmp_path / "wt").as_posix(), account=(tmp_path / "account").as_posix(), roles=roles))
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
    # One read of the board's comment count, so a long board moves first (tidy.keep_board), then one line, and no
    # pull request.
    assert gh == ["api", "repos/example/demo/issues/12", "issue", "comment", "12", "--repo", "example/demo", "--body",
                  line]
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


def test_paid_checks_run_once_in_the_passing_round_inside_the_ceiling_and_the_pr_shows_the_spend(repo, config, stubs,
                                                                                               capsys):
    config["budget"]["provider_dollars"] = 5
    config["gate"]["paid_checks"] = "echo \"ceiling $COLONY_SPEND_CEILING\" > ../paid.txt; echo 'spent: $1.25'"
    assert batch.run_batch(config, batch_args(repo, "11=card/a", "12=card/b")) == 0
    assert "done in round 2." in capsys.readouterr().out
    wt = Path(config["project"]["worktrees"])
    assert (wt / "paid.txt").read_text() == "ceiling 5.00\n"
    reports = wt / "demo-batch-b1" / ".colony" / "reports" / "b1"
    assert not (reports / "paid-checks-1.log").exists() and (reports / "paid-checks-2.log").exists()
    body = (reports / "pr.md").read_text()
    assert "## Paid checks\n- Round 2: `" in body and "pass, $1.25 spent of a $5.00 ceiling" in body
    assert "- Total: $1.25 of the $5.00 budget" in body


def test_paid_checks_never_run_at_a_zero_budget_and_a_spend_past_the_budget_stops_the_batch(repo, config, stubs,
                                                                                           capsys):
    config["gate"]["paid_checks"] = "echo ran > ../paid.txt; echo 'spent: $2'"
    assert batch.run_batch(config, batch_args(repo, "11=card/a", "12=card/b")) == 0
    wt = Path(config["project"]["worktrees"])
    assert not (wt / "paid.txt").exists()
    assert "None: [gate] paid_checks is unset or [budget] provider_dollars is 0, so $0.00 spent." in (
        wt / "demo-batch-b1" / ".colony" / "reports" / "b1" / "pr.md").read_text()
    config["budget"]["provider_dollars"] = 1
    args = batch_args(repo, "11=card/a", "12=card/b")
    args.name = "b2"
    capsys.readouterr()
    assert batch.run_batch(config, args) == 1
    assert "the paid checks spent $2.00, past the $1.00 budget" in capsys.readouterr().out
    assert git(repo.parent / "origin.git", "branch", "--list", "demo/batch-b2") == ""


def test_fast_runs_the_full_checks_once_with_no_agents_and_writes_gate_fast_in_the_pr(repo, config, stubs, capsys):
    args = batch_args(repo, "11=card/a", "12=card/b")
    args.fast = True
    assert batch.run_batch(config, args) == 0
    assert "done in round 1. https://example.test/pull/1" in capsys.readouterr().out
    assert not stubs["claude"].exists()
    body = (Path(config["project"]["worktrees"]) / "demo-batch-b1" / ".colony" / "reports" / "b1" / "pr.md").read_text()
    assert body.startswith("gate: fast\n")
    assert "| 1 | skipped | skipped | pass |" in body and "- Round 1: `true` pass" in body
    assert config["gate"]["walk"] is True and config["gate"]["max_rounds"] == 3  # the default gate is unchanged


def test_fast_stops_when_the_checks_fail_and_runs_no_fixer_or_pr(repo, config, stubs, capsys):
    config["project"]["checks"] = "echo 'FAIL web lint (3s), exit 1'; exit 1"
    args = batch_args(repo, "11=card/a", "12=card/b")
    args.fast = True
    assert batch.run_batch(config, args) == 1
    assert "the full checks failed, and --fast runs no fixers: checks failed: FAIL web lint" in capsys.readouterr().out
    assert not stubs["claude"].exists() and not stubs["gh"].exists()
    assert git(repo.parent / "origin.git", "branch", "--list", "demo/*") == ""
    args.dry_run, args.name = True, "b2"
    assert batch.run_batch(config, args) == 0
    plan = capsys.readouterr().out
    assert "no reviewer, walk or fixers" in plan and "--- fixer" not in plan and "--- reviewer" not in plan



# Colony 0.5: checks for the areas a change touched, timeout reruns, a narrowed walk, three rounds, and rate limits


AREAS = {"web": ["web/"], "api": ["api/", "gen/"]}

# A check log in the shape a repo's check script prints: a step's FAIL line, its failure lines indented below it
PUFFIN_LOG = """PASS ruff check (3s)
FAIL pytest (1135s), exit 1. Full log: /tmp/checks/pytest.log
  ERROR tests/features/test_stream.py::test_a_paused_card_asks_its_question
  E           Failed: Timeout (>30.0s) from pytest-timeout.
  ============================ FAILED CPU time limits ============================
  FAILED tests/unit/test_migration_line.py::test_history_reaches_its_head
PASS web check (40s)
Logs: /tmp/checks
"""


def with_areas(config, **checks):
    """The config with [checks] areas set, `{areas}` in its check command, and any other [checks] keys given."""
    config["checks"] = {"areas": dict(AREAS), "all": "all", **checks}
    return config


def test_a_change_touches_the_areas_its_paths_are_in_and_an_unknown_path_touches_every_area(config):
    with_areas(config, skip=["docs/", "*.md"])
    assert batch.areas_of(config, ["web/page.tsx"]) == ["web"]
    assert batch.areas_of(config, ["gen/api.json", "web/page.tsx"]) == ["web", "api"]
    assert batch.areas_of(config, ["docs/guide.txt", "README.md"]) == []
    assert batch.areas_of(config, ["tools/build.sh"]) == ["web", "api"]
    assert batch.areas_of({**config, "checks": {}}, ["web/page.tsx"]) == []
    cmd = "python3 tools/agent_checks.py {areas} --keep-going"
    assert batch.check_command(config, cmd, ["api"]) == "python3 tools/agent_checks.py api --keep-going"
    assert batch.check_command(config, cmd, ["api", "web"]) == "python3 tools/agent_checks.py all --keep-going"
    assert batch.check_command(config, "true", ["api"]) == "true"
    assert batch.matches("apps/web/src/a.tsx", ["apps/*/src/*.tsx"]) and not batch.matches("web2/a", ["web/"])


def test_a_later_round_checks_the_areas_that_failed_and_the_areas_its_fixes_touched(repo, config):
    b = batch.Batch.from_args(with_areas(config), batch_args(repo, "11=card/a"))
    assert batch.round_areas(b, None, ["web/page.tsx"]) == ["web"]
    assert batch.round_areas(b, {"failed_areas": ["api"]}, ["web/page.tsx"]) == ["web", "api"]
    assert batch.round_areas(b, {"failed_areas": []}, []) == []
    b.wt = repo
    failures = [Finding("gen/api.json", 0, "failing test gen/api.json"), Finding("", 0, "checks failed: FAIL lint")]
    assert batch.failed_areas(b, ["api"], failures[:1]) == ["api"]
    assert batch.failed_areas(b, ["web", "api"], failures[1:]) == ["web", "api"]
    assert batch.failed_areas(b, None, failures) == []
    config.pop("checks")
    assert batch.round_areas(b, None, ["web/page.tsx"]) is None


def test_the_check_output_names_its_failing_and_erroring_tests_and_the_failures_they_dont_explain():
    found = batch.parse_check_failures(PUFFIN_LOG)
    assert [batch.test_id(f) for f in found] == [
        "tests/features/test_stream.py::test_a_paused_card_asks_its_question",
        "tests/unit/test_migration_line.py::test_history_reaches_its_head"]
    tests = {batch.test_id(f) for f in found}
    assert batch.other_failures(PUFFIN_LOG, tests) == []
    assert batch.other_failures(PUFFIN_LOG + "FAIL web bundle (0s), exit 1\n", tests) == ["FAIL web bundle (0s), exit 1"]
    assert sorted(batch.other_failures("FAIL pytest (9s), exit 1\n  ERROR tests/x.py - ImportError\n", tests)) == [
        "ERROR tests/x.py - ImportError", "FAIL pytest (9s), exit 1"]
    assert batch.timing_tests(PUFFIN_LOG, sorted(tests)) == sorted(tests)
    assert batch.timing_tests(PUFFIN_LOG + "FAILED tests/y.py::test_b - AssertionError\n", ["tests/y.py::test_b"]) == []
    assert batch.timing_tests("FAILED tests/y.py::test_b\n", ["tests/y.py::test_b"]) == []


def check_run(b, r, cmd):
    """Run `cmd` as round r's background checks, the way gate starts them, and wait for them (run_checks)."""
    log = b.reports / f"checks-{r}.log"
    with log.open("wb") as out:
        proc = subprocess.Popen(cmd, shell=True, cwd=b.wt, stdout=out, stderr=subprocess.STDOUT)
    return batch.run_checks(b, r, cmd, proc, log, 0.0, "10:00")


def test_a_test_that_failed_on_a_timeout_runs_once_more_alone_and_counts_only_when_it_fails_again(repo, config,
                                                                                               tmp_path):
    (tmp_path / "log.txt").write_text(PUFFIN_LOG)
    rerun = "echo {test} >> ../reruns.txt; case {test} in *stream*) true ;; *) exit 1 ;; esac"
    b = batch.Batch.from_args(with_areas(config, rerun=rerun), batch_args(repo, "11=card/a"))
    b.wt, b.reports = repo, tmp_path / "reports"
    b.reports.mkdir()
    passed, _, failures, _ = check_run(b, 1, f"cat {tmp_path / 'log.txt'}; exit 1")
    assert not passed
    assert [batch.test_id(f) for f in failures] == ["tests/unit/test_migration_line.py::test_history_reaches_its_head"]
    assert (tmp_path / "reruns.txt").read_text().count("\n") == 2
    report = (b.reports / "checks-1.md").read_text()
    assert "passed alone on a rerun, so not counted: tests/features/test_stream.py::test_a_paused" in report
    assert "passed alone" in (b.reports / "checks-1.log").read_text()

    b.config["checks"]["rerun"] = "true"
    passed, _, failures, _ = check_run(b, 2, f"cat {tmp_path / 'log.txt'}; exit 1")
    assert passed and failures == [] and (b.reports / "checks-2.md").read_text().startswith("checks: pass")
    (tmp_path / "log.txt").write_text(PUFFIN_LOG + "FAIL web bundle (0s), exit 1. Full log: /tmp/web.log\n")
    passed, _, failures, _ = check_run(b, 3, f"cat {tmp_path / 'log.txt'}; exit 1")
    assert not passed and failures == [Finding("", 0, "checks failed: FAIL web bundle (0s), exit 1. Full log: /tmp/web.log")]
    assert "| rerun | 3 |" in batch.minutes_table((b.reports / "minutes.md").read_text())


VITEST_LOG = """ × src/cal/week.test.tsx > renders the week
 × src/cal/day.test.tsx > loads the day
   → Test timed out in 5000ms.
"""
MAKE_LOG = """eslint src
/repo/src/cal/day.ts
  3:7  error  'unused' is assigned a value but never used  no-unused-vars

✖ 1 problem (1 error, 0 warnings)

make: *** [lint] Error 1
vitest run
 × src/cal/day.test.tsx > loads the day
   → Test timed out in 5000ms.

 Test Files  1 failed (1)
make: *** [test] Error 1
make: Target `check' not remade because of errors.
"""


def test_a_failing_test_with_no_reason_is_never_rerun_as_a_timeout_beside_one_that_timed_out(repo, config, tmp_path):
    tests = ["src/cal/week.test.tsx", "src/cal/day.test.tsx"]
    assert batch.timing_tests(VITEST_LOG, tests) == ["src/cal/day.test.tsx"]
    assert batch.timing_tests(" FAIL  src/cal/day.test.tsx > loads the day\nError: Test timed out in 5000ms.\n",
                              tests[1:]) == tests[1:]
    (tmp_path / "log.txt").write_text(VITEST_LOG)
    b = batch.Batch.from_args(with_areas(config, rerun="echo {test} >> ../reruns.txt"), batch_args(repo, "11=card/a"))
    b.wt, b.reports = repo, tmp_path / "reports"
    b.reports.mkdir()
    passed, _, failures, _ = check_run(b, 1, f"cat {tmp_path / 'log.txt'}; exit 1")
    assert (tmp_path / "reruns.txt").read_text() == "src/cal/day.test.tsx\n"
    assert not passed and [batch.test_id(f) for f in failures] == ["src/cal/week.test.tsx"]


def test_a_timeout_that_passes_alone_never_clears_a_round_whose_other_steps_failed(repo, config, tmp_path):
    (tmp_path / "log.txt").write_text(MAKE_LOG)
    b = batch.Batch.from_args(with_areas(config, rerun="true"), batch_args(repo, "11=card/a"))
    b.wt, b.reports = repo, tmp_path / "reports"
    b.reports.mkdir()
    passed, _, failures, _ = check_run(b, 1, f"cat {tmp_path / 'log.txt'}; exit 2")
    assert "passed alone on a rerun, so not counted: src/cal/day.test.tsx" in (b.reports / "checks-1.md").read_text()
    assert not passed
    assert failures == [Finding("", 0, "checks failed: make: *** [lint] Error 1; make: *** [test] Error 1")]
    assert batch.other_failures("error: the linker failed\n", {"src/a.test.ts"}) == [
        "error: the linker failed", "the output names no failing test or step"]
    assert batch.other_failures(" FAIL  src/a.test.ts > b\nError: Test timed out in 5000ms.\n", {"src/a.test.ts"}) == []


def test_a_batch_checks_only_the_areas_its_change_touched_and_minutes_md_shows_what_that_saved(repo, config, stubs):
    with_areas(config, skip=["*.txt"], minutes=41)
    config["project"]["checks"] = "echo {areas} >> ../areas.txt"
    config["walk"] = {"minutes": 27, "cost": 6}
    assert batch.run_batch(config, batch_args(repo, "11=card/a", "12=card/b")) == 0
    wt = Path(config["project"]["worktrees"])
    assert (wt / "areas.txt").read_text() == "api\n"  # round 1: gen/api.json; round 2's fix touched only b.txt
    reports = wt / "demo-batch-b1" / ".colony" / "reports" / "b1"
    body = (reports / "pr.md").read_text()
    assert "- Round 1: `echo api >> ../areas.txt` pass" in body
    assert "- Round 2: skipped, the change touches no check area" in body and "| 2 | 0 | skipped | skipped |" in body
    assert re.search(r"\| saved: checks \| 2 \| (8[01]\.\d|8[12]\.0) \| \$0\.00 \|", body)
    assert "| saved: walk | 2 | 54.0 | $12.00 |" in body
    state = (reports / "state.json").read_text()
    assert '"areas": [\n        "api"\n      ]' in state


def test_minutes_table_lists_what_each_kind_of_skipped_step_saved_below_the_total():
    table = batch.minutes_table(["10:00 checks-r1 4.0", "10:05 saved checks-r1 37.0", "10:30 saved walk-r1 27.0 $6.00",
                                 "10:40 saved walk-r2 20.5 $4.50"])
    assert "| **total** | 1 | 4.0 | $0.00 |" in table
    assert table.endswith("| saved: checks | 1 | 37.0 | $0.00 |\n| saved: walk | 2 | 47.5 | $10.50 |\n"
                          "| **saved** | 3 | 84.5 | $10.50 |")


def test_the_settings_refuse_web_checks_areas_without_areas_and_an_unknown_browser(repo, config):
    config["project"]["web_checks"] = "npm test"
    with pytest.raises(SystemExit, match=r"web_checks is gone: name each check area's paths in \[checks\] areas"):
        batch.Batch.from_args(config, batch_args(repo, "11=card/a"))
    del config["project"]["web_checks"]
    config["project"]["checks"] = "run {areas}"
    with pytest.raises(SystemExit, match=r"\[checks\] areas names none"):
        batch.Batch.from_args(config, batch_args(repo, "11=card/a"))
    with_areas(config)
    config["walk"] = {"browser": "lynx"}
    with pytest.raises(SystemExit, match="'playwright' or 'agent-browser', not 'lynx'"):
        batch.Batch.from_args(config, batch_args(repo, "11=card/a"))


def test_the_walker_walks_only_the_screens_the_changed_files_feed(config):
    config["gate"]["walk_paths"] = ["web/"]
    config["walk"] = {"screens": {"/calendar": ["web/calendar/"], "/settings": ["web/settings/", "web/*.css"]}}
    changed = ["web/calendar/day.tsx", "web/app.css", "web/lib/words.ts", "api/app.py"]
    assert batch.walk_screens(config, changed) == (["/calendar", "/settings"], ["web/lib/words.ts"])
    text = batch.screens_text(config, changed)
    assert text.startswith("Walk only these screens, which this round's changed files feed: /calendar, /settings.")
    assert "Also walk the screens that use these changed files: `web/lib/words.ts`." in text and "api/app.py" not in text
    assert batch.screens_text(config, ["api/app.py"]).startswith("This round changed no screen file")


def test_a_walker_on_agent_browser_drives_its_cli_with_no_mcp_server(repo, config, tmp_path):
    default = batch.claude_cmd(config, "walker", "walk")
    assert default[default.index("--output-format") + 1] == "stream-json" and "--verbose" in default
    assert "--strict-mcp-config" not in default
    config["walk"] = {"browser": "agent-browser"}
    cmd = batch.claude_cmd(config, "walker", "walk")
    assert cmd[cmd.index("--allowedTools") + 1] == "Bash(agent-browser:*)" and "--strict-mcp-config" in cmd
    assert "--strict-mcp-config" not in batch.claude_cmd(config, "reviewer", "review")
    b = batch.Batch.from_args(config, batch_args(repo, "11=card/a"))
    prompt = batch.walker_prompt(b, 1, "abc123", ["web/page.tsx"])
    assert "`agent-browser skills get core`" in prompt and "--session colony-walk-b1" in prompt
    assert "Walk only the screens that use these changed files: `web/page.tsx`." in prompt
    assert re.search(r"\{\w+\}", prompt) is None


def test_after_the_last_round_each_open_finding_becomes_a_card_and_the_pr_lists_them(repo, config, stubs, capsys,
                                                                                    monkeypatch):
    from colony import tidy

    made = []

    def make_card(config, title, body, size, lead, capped=True):
        made.append((title, size, lead, capped))
        if len(made) == 2:
            raise tidy.Duplicate(77, title)
        return 100 + len(made)

    monkeypatch.setattr(tidy, "make_card", make_card)
    monkeypatch.setenv("COLONY_STUB_MODE", "stubborn")
    config["gate"]["max_rounds"] = 5  # Colony runs 3 at most
    assert batch.run_batch(config, batch_args(repo, "11=card/a", "12=card/b")) == 0
    assert "round 3 of 3 left 3 findings open, now cards the pull request lists." in capsys.readouterr().out
    assert stubs["claude"].read_text().count("You are a fast builder") == 2
    assert made[0] == ("Batch b1 left open: line 1 is wrong — tests — change it", "S", "pat-lead", False)
    body = (Path(config["project"]["worktrees"]) / "demo-batch-b1" / ".colony" / "reports" / "b1" / "pr.md").read_text()
    carried = body.split("## Left open, now cards\n", 1)[1].split("\n\n", 1)[0]
    assert "- #101 review: `b.txt:1` — line 1 is wrong" in carried and "- #77, already open: review: `b.txt:2`" in carried
    assert "Closes #101" not in body and "## Open problems by round\n3 → 3 → 3\n" in body


def test_a_check_that_still_fails_in_the_last_round_stops_the_batch(repo, config, stubs, capsys):
    config["project"]["checks"] = 'echo "FAILED tests/test_x.py::test_$(git rev-parse --short HEAD)"; exit 1'
    assert batch.run_batch(config, batch_args(repo, "11=card/a", "12=card/b")) == 1
    assert "round 3 of 3 still fails its checks (failing test tests/test_x.py::test_" in capsys.readouterr().out
    assert not stubs["gh"].exists()
    assert git(repo.parent / "origin.git", "branch", "--list", "demo/*") == ""



def test_a_check_that_fails_on_the_start_point_alone_stops_the_batch_with_no_fixer(repo, config, stubs, capsys):
    # A broken base, or a check's database that is down, fails every branch: no fixer chases what the cards didn't do.
    config["project"]["checks"] = "echo 'FAILED tests/test_db.py::test_connects'; exit 1"
    config["gate"].update(review=False, walk=False)
    assert batch.run_batch(config, batch_args(repo, "12=card/b")) == 1
    out = capsys.readouterr().out
    start = git(repo, "rev-parse", "origin/main")[:9]
    assert (f"every failing check also fails on origin/main alone at {start}, without the cards "
            "(tests/test_db.py::test_connects): the cards are not to blame, so no fixer runs") in out
    assert not stubs["claude"].exists()
    reports = Path(config["project"]["worktrees"]) / "demo-batch-b1" / ".colony" / "reports" / "b1"
    assert f"fails on origin/main alone at {start} too, so no fixer gets it" in (reports / "checks-1.md").read_text()
    assert not (Path(config["project"]["worktrees"]) / "demo-batch-b1-start").exists()


def test_a_fixer_gets_only_the_cards_own_failures_and_the_start_points_stop_the_next_round(repo, config, stubs,
                                                                                           capsys):
    # test_db fails on main already; test_b fails only with card/b's change, until its fixer appends "fixed".
    config["project"]["checks"] = ("echo 'FAILED tests/test_db.py::test_connects'; grep -q fixed b.txt || "
                                   "{ grep -qx b1 b.txt && echo 'FAILED tests/test_b.py::test_b'; }; exit 1")
    config["gate"].update(review=False, walk=False)
    assert batch.run_batch(config, batch_args(repo, "12=card/b")) == 1
    out = capsys.readouterr().out
    assert stubs["claude"].read_text().count("You are a fast builder") == 1
    assert "every failing check also fails on origin/main alone" in out and "round 2" not in out.split("stopped")[0]
    reports = Path(config["project"]["worktrees"]) / "demo-batch-b1" / ".colony" / "reports" / "b1"
    state = json.loads((reports / "state.json").read_text())
    assert [x["on_start"] for x in state["rounds"]] == [["failing test tests/test_db.py::test_connects"]] * 2
    assert list(state["start_checks"].values()) == [["tests/test_db.py::test_connects"]]  # run once, then kept


RATE_STUB = r'''#!/usr/bin/env python3
import json, os, sys, time
prompt = sys.argv[sys.argv.index("-p") + 1]
folder = os.environ.get("CLAUDE_CONFIG_DIR", "")
with open(os.environ["COLONY_STUB_LOG"], "a") as log:
    log.write(os.path.basename(folder) + "\n")
mode = os.environ.get("COLONY_STUB_MODE", "")
print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
if mode == "stall":
    time.sleep(30)
elif folder.endswith("account") and mode == "retry":
    for attempt in range(1, 300):
        print(json.dumps({"type": "system", "subtype": "api_retry", "attempt": attempt, "max_retries": 10,
                          "retry_delay_ms": 100, "error_status": 429, "error": "rate_limit"}), flush=True)
        time.sleep(0.1)
elif folder.endswith("account") and mode == "subscription":
    print(json.dumps({"type": "assistant", "message": {"model": "<synthetic>", "content": [
        {"type": "text", "text": "You've hit your limit · resets 3pm (Europe/Berlin)"}]}}))
    print(json.dumps({"type": "result", "is_error": True, "total_cost_usd": 0, "duration_ms": 10,
                      "result": "You've hit your limit · resets 3pm (Europe/Berlin)"}))
    sys.exit(1)
elif folder.endswith("account") and mode == "rejected":
    print(json.dumps({"type": "result", "is_error": True, "total_cost_usd": 0, "duration_ms": 10, "result":
                      "API Error: 429 {\"type\":\"error\",\"error\":{\"type\":\"rate_limit_error\",\"message\":"
                      "\"This request would exceed your account's rate limit. Please try again later.\"}}"}))
    sys.exit(1)
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "the rate limit doc says hi"}]}}))
print(json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.5, "duration_ms": 60000, "result": "done"}))
'''


@pytest.fixture
def rate_stub(tmp_path, monkeypatch, config, repo):
    """A stub claude that hits the rate limit on the account `one` (the folder `account`) in the way
    COLONY_STUB_MODE names, and a batch whose person, pat, has the accounts one and two."""
    bin_dir = tmp_path / "rate-bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(RATE_STUB)
    (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("COLONY_STUB_LOG", str(tmp_path / "rate.log"))
    monkeypatch.setattr(cli, "refresh_usage", lambda folders: None)
    monkeypatch.setattr(batch, "RATE_LIMIT_GRACE", 1)
    for folder in ("account", "two"):
        (tmp_path / folder).mkdir()
    config["accounts"]["two"] = {"config_dir": str(tmp_path / "two"), "person": "pat"}
    config["people"] = {"pat": {"accounts": ["one", "two"]}}
    b = batch.Batch.from_args(config, batch_args(repo, "11=card/a"))
    b.reports = tmp_path / "reports"
    b.reports.mkdir()
    assert b.account[0] == "one" and b.person == "pat"
    return b


@pytest.mark.parametrize("mode", ["retry", "rejected", "subscription"])
def test_a_step_on_a_rate_limited_account_runs_again_on_the_next_account_with_room(rate_stub, tmp_path, monkeypatch,
                                                                                    capsys, mode):
    monkeypatch.setenv("COLONY_STUB_MODE", mode)
    b, started = rate_stub, time.monotonic()
    data = batch.run_agent(b, "reviewer", "review it", tmp_path, "review-r1")
    assert data["total_cost_usd"] == 0.5 and time.monotonic() - started < 15
    assert (tmp_path / "rate.log").read_text() == "account\ntwo\n"
    assert b.account[0] == "two" and b.limited == {"one"}
    assert b.state["switches"][0]["from"] == "one" and b.state["switches"][0]["to"] == "two"
    assert (b.reports / "review-r1-two.jsonl").exists()
    assert "review-r1 hit the rate limit on one; it runs again on two" in capsys.readouterr().out
    b.state["rounds"] = []
    monkeypatch.setattr(batch, "removed_tests", lambda b: [])
    monkeypatch.setattr(batch, "card_stats", lambda b: "")
    assert "## Account switches\n- " + b.state["switches"][0]["at"] + " review-r1 hit the rate limit on one, and ran again on two" in \
        batch.pr_body(b)


def test_a_rate_limit_with_no_account_left_with_room_stops_naming_the_account(rate_stub, tmp_path, monkeypatch):
    monkeypatch.setenv("COLONY_STUB_MODE", "rejected")
    rate_stub.config["people"]["pat"]["accounts"] = ["one"]
    with pytest.raises(batch.Stop, match="review-r1 hit the rate limit on the account one, and no other account of "
                                          "pat's has room"):
        batch.run_agent(rate_stub, "reviewer", "review it", tmp_path, "review-r1")


def test_an_agent_that_goes_silent_is_stopped_and_its_step_fails(rate_stub, tmp_path, monkeypatch):
    monkeypatch.setenv("COLONY_STUB_MODE", "stall")
    monkeypatch.setattr(batch, "STALL_SECONDS", 1)
    started = time.monotonic()
    with pytest.raises(batch.Stop, match=r"review-r1 failed twice \(stalled"):
        batch.run_agent(rate_stub, "reviewer", "review it", tmp_path, "review-r1")
    assert time.monotonic() - started < 20


def test_the_rate_limit_signs_come_only_from_claude_codes_own_events():
    sign = batch.rate_limit_sign
    assert sign('{"type":"system","subtype":"api_retry","error_status":429,"error":"rate_limit"}') == "waiting"
    assert sign('{"type":"system","subtype":"api_retry","error_status":529,"error":"overloaded"}') is None
    assert sign('{"type":"rate_limit_event","rate_limit_info":{"status":"rejected"}}') == "waiting"
    assert sign('{"type":"rate_limit_event","rate_limit_info":{"status":"allowed_warning"}}') == "moving"
    assert sign('{"type":"result","is_error":true,"result":"rate_limit_error: slow down"}') == "limited"
    assert sign('{"type":"result","is_error":false,"result":"read the rate limit code"}') is None
    assert sign('{"type":"user","message":{"content":"rate_limit_error in a file"}}') == "moving"
    assert sign("API Error: This request would exceed your account's rate limit.") == "limited"
    assert sign("plain progress") is None
    # A Claude subscription's limit, and any message Claude Code marks with "error": "rate_limit", end the run.
    assert sign('{"type":"assistant","message":{"model":"<synthetic>","content":[{"type":"text","text":'
                '"You\'ve hit your limit · resets 3pm (Europe/Berlin)"}]}}') == "limited"
    assert sign('{"type":"result","is_error":true,"result":"Claude AI usage limit reached|1794250800"}') == "limited"
    assert sign('{"type":"result","is_error":true,"result":"5-hour limit reached ∙ resets 3pm"}') == "limited"
    assert sign('{"type":"assistant","message":{"content":[{"type":"text","text":"API Error: 429"}]},'
                '"error":"rate_limit"}') == "limited"
    assert sign('{"type":"assistant","message":{"content":[{"type":"text","text":"The doc: usage limit reached '
                'means wait"}]}}') == "moving"
    assert sign('{"type":"result","is_error":false,"result":"You\'ve hit your limit"}') is None
    assert batch.RATE_LIMIT_GRACE == 300  # a short burst of 429s on a shared account rides it out


def test_the_next_account_with_room_skips_the_limited_ones(config, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "refresh_usage", lambda folders: None)
    for folder in ("account", "admin"):
        (tmp_path / folder).mkdir()
    config["accounts"]["admin"] = {"config_dir": str(tmp_path / "admin"), "person": "pat"}
    config["people"] = {"pat": {"accounts": ["admin", "one"]}}
    assert cli.pick_with_room(config, "pat")[0] == "admin"
    assert cli.pick_with_room(config, "pat", skip={"admin"})[0] == "one"
    assert cli.pick_with_room(config, "pat", skip={"admin", "one"}) is None


def test_a_dry_run_names_the_areas_the_rerun_the_browser_and_the_three_rounds(repo, config, stubs, capsys):
    with_areas(config, rerun="uv run pytest {test}")
    config["project"]["checks"] = "python3 tools/agent_checks.py {areas} --keep-going"
    config["walk"] = {"browser": "agent-browser"}
    config["gate"]["max_rounds"], config["gate"]["walk_paths"] = 5, ["gen/"]
    assert batch.run_batch(config, batch_args(repo, "11=card/a", dry_run=True)) == 0
    out = capsys.readouterr().out
    for expected in ("checks, in the background, for the areas a round touches: $ python3 tools/agent_checks.py "
                     "<areas> --keep-going", "areas: web = web/; api = api/, gen/; every area: all",
                     "runs once more by itself: $ uv run pytest {test}", "on agent-browser:",
                     "rounds: at most 3; done at checks pass, open: 0", "each finding still open becomes a card",
                     "Walk only the screens that use these changed files: `gen/api.json`.",
                     "python3 tools/agent_checks.py all --keep-going"):
        assert expected in out, expected
    assert re.search(r"\{\w+\}", out.replace("{test}", "")) is None


STOP_SCRIPT = r'''
import concurrent.futures as futures, json, sys
from pathlib import Path
from colony import batch
config, folder, agent = json.loads(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
batch.claude_cmd = lambda *args, **kwargs: [sys.executable, agent]
b = batch.Batch(config, "b1", {}, "HEAD", folder, ("one", str(folder)))
b.reports = folder
batch.stop_on_signal(b)
with futures.ThreadPoolExecutor(max_workers=2) as pool:
    for step in ("review-r1", "walk-r1"):
        pool.submit(batch.run_agent, b, "reviewer", "review it", folder, step)
print("the pool ended", flush=True)
'''
LONG_AGENT = r'''
import json, os, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
with open(os.path.join(os.path.dirname(__file__), "pids.txt"), "a") as out:
    out.write(f"{os.getpid()} {child.pid}\n")
print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
time.sleep(600)
'''


def gone(pid: int) -> bool:
    """Whether a process has ended and nothing waits to reap it."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    run = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return run.stdout.strip().startswith("Z") or not run.stdout.strip()


@pytest.mark.skipif(os.name == "nt", reason="Ctrl-C reaches a process group through POSIX signals")
@pytest.mark.parametrize("signum", ["SIGINT", "SIGTERM"])
def test_ctrl_c_stops_every_running_agent_and_ends_the_batch_without_waiting_on_them(config, tmp_path, signum):
    import json
    import signal
    import sys

    (tmp_path / "stop.py").write_text(STOP_SCRIPT)
    (tmp_path / "agent.py").write_text(LONG_AGENT)
    env = {**os.environ, "PYTHONPATH": str(Path(batch.__file__).resolve().parents[1])}
    run = subprocess.Popen([sys.executable, str(tmp_path / "stop.py"), json.dumps(config), str(tmp_path),
                            str(tmp_path / "agent.py")], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True)
    pids = tmp_path / "pids.txt"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and (not pids.exists() or pids.read_text().count("\n") < 2):
        time.sleep(0.1)
    if not pids.exists() or pids.read_text().count("\n") != 2:
        run.kill()
        pytest.fail(f"the agents never started: {run.communicate()[0]}")
    started = time.monotonic()
    run.send_signal(getattr(signal, signum))
    out, _ = run.communicate(timeout=30)
    assert time.monotonic() - started < 15
    assert run.returncode == 128 + getattr(signal, signum), out
    assert f"colony batch b1: stopped by {signum}, with the 2 processes it had running" in out
    assert "the pool ended" not in out
    every = [int(pid) for line in pids.read_text().split("\n") if line for pid in line.split()]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not all(gone(pid) for pid in every):
        time.sleep(0.1)
    assert all(gone(pid) for pid in every), every
