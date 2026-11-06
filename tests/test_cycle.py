"""Tests for the cycle: the tier rules on fixture diffs, the risk list, `needs`, the handover, `stats` totals, stale
cards on a fake clock, and the retro prompt. gh is the stand-in from test_board."""
import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_board import CONFIG, LISTED, gh  # noqa: F401  (gh is the stand-in gh fixture)

from colony import cli, cycle


def parse(*argv):
    """Parse a command line the way cli.py will, through cycle.add_commands."""
    parser = argparse.ArgumentParser()
    cycle.add_commands(parser.add_subparsers(dest="command"))
    return parser.parse_args(list(argv))


def change(path, added=0, removed=0, status="M", old=None, lines=None, gone=None):
    """One file's part of a unified diff: `added` and `removed` filler lines, or the added `lines` and removed `gone`
    lines given."""
    old = old or path
    head = f"diff --git a/{old} b/{path}\n"
    if status == "A":
        head += f"new file mode 100644\n--- /dev/null\n+++ b/{path}\n"
    elif status == "D":
        head += f"deleted file mode 100644\n--- a/{path}\n+++ /dev/null\n"
    elif status == "R":
        head += f"similarity index 90%\nrename from {old}\nrename to {path}\n--- a/{old}\n+++ b/{path}\n"
    else:
        head += f"--- a/{path}\n+++ b/{path}\n"
    body = [f"+{line}" for line in (lines or [f"line {i}" for i in range(added)])]
    body += [f"-{line}" for line in (gone or [f"old {i}" for i in range(removed)])]
    return head + ("@@ -1 +1 @@\n" + "\n".join(body) + "\n" if body else "")


def verdict(*parts, config=None, existed=lambda entry: True, feature=False):
    """The verdict on a diff made of these parts."""
    return cycle.classify(cycle.parse_diff("".join(parts)), existed, config or CONFIG, feature)


# Tiers


def test_a_small_change_in_one_area_is_tiny():
    result = verdict(change("web/src/button.tsx", added=6, removed=4))
    assert (result.tier, result.reasons, result.risks) == ("TINY", [], [])


def test_docs_up_to_the_cap_are_tiny_and_past_it_small():
    assert verdict(change("knowledge/wiki/home.md", added=150, removed=150)).tier == "TINY"
    result = verdict(change("knowledge/wiki/home.md", added=200, removed=101))
    assert result.tier == "SMALL" and "301 changed docs lines, over 300" in result.reasons
    assert verdict(change("README.md", added=20)).tier == "TINY"


@pytest.mark.parametrize("parts, reason", [
    ([change("web/src/a.tsx", added=101)], "101 non-test code lines, over 100"),
    ([change("web/src/a.tsx", added=5), change("api/main.py", added=5)], "code in more than one area, api, web"),
    ([change("apps/web/a.tsx", added=5), change("apps/site/b.tsx", added=5)],
     "code in more than one area, apps/site, apps/web"),
    ([change("knowledge/wiki/old.md", status="D", removed=3)], "a docs page moved or deleted, knowledge/wiki/old.md"),
])
def test_a_change_past_a_tiny_limit_is_small(parts, reason):
    result = verdict(*parts)
    assert result.tier == "SMALL" and reason in result.reasons


def test_backend_code_is_never_tiny():
    config = {**CONFIG, "project": {**CONFIG["project"], "backend_paths": ["server/"]}}
    result = verdict(change("server/app.py", added=3), config=config)
    assert result.tier == "SMALL" and result.reasons == ["code in a backend path, server/app.py"]
    assert verdict(change("server/tests/test_app.py", added=3), config=config).tier == "TINY"


def test_tests_lockfiles_and_generated_files_do_not_count_toward_the_line_limits():
    config = {**CONFIG, "project": {**CONFIG["project"], "generated": ["web/src/gen/*"]}}
    result = verdict(change("web/src/a.tsx", added=10), change("web/src/a.test.tsx", added=900),
                     change("web/src/gen/api.ts", added=900), config=config)
    assert result.tier == "TINY"
    result = verdict(change("web/src/a.tsx", added=10), change("web/package-lock.json", added=900))
    assert result.tier == "SMALL" and result.reasons == ["1 place on the risk list"]


@pytest.mark.parametrize("parts, existed, reason", [
    ([change("web/src/a.tsx", added=401)], True, "401 non-test code lines, over 400, in web"),
    ([change("src/features/billing/index.ts", status="A", added=5)], False,
     "a new entry under features/, src/features/billing"),
    ([change("web/app/settings/page.tsx", status="A", added=5)], True,
     "a new page, layout or route file, web/app/settings/page.tsx"),
    ([change("knowledge/specs/billing/requirements.md", status="A", added=5)], True,
     "a new spec page, knowledge/specs/billing/requirements.md"),
    ([change("db/migrations/0003_users.sql", status="A", lines=["CREATE TABLE users (id int);"])], True,
     "a migration that creates a table, db/migrations/0003_users.sql"),
])
def test_a_feature_trigger_makes_it_a_feature(parts, existed, reason):
    result = verdict(*parts, existed=lambda entry: existed)
    assert result.tier == "FEATURE" and reason in result.reasons


def test_a_new_file_in_a_feature_folder_that_exists_is_no_feature():
    assert verdict(change("src/features/calendar/more.ts", status="A", added=5)).tier == "TINY"
    assert verdict(change("tests/routes/test_users.py", status="A", added=5), existed=lambda e: False).tier == "TINY"


def test_feature_asked_for_wins_over_a_tiny_diff():
    result = verdict(change("web/src/a.tsx", added=1), feature=True)
    assert result.tier == "FEATURE" and result.reasons == ["FEATURE was asked for with --feature"]


def test_weakened_checks_are_never_tiny():
    result = verdict(change("tests/test_a.py", removed=2, added=1))
    assert result.tier == "SMALL" and result.risks == ["checks: tests/test_a.py, deletes test lines"]
    result = verdict(change("web/src/a.ts", lines=["// eslint-disable-next-line no-console"]))
    assert result.risks == ["checks: web/src/a.ts, adds the skip mark `eslint-disable`"]
    result = verdict(change("tests/test_a.py", status="D", removed=3))
    assert "checks: tests/test_a.py, moves or deletes a test file" in result.risks


# A repo's own tier lines, in the shape of a web app, a site and a service with its own FEATURE lines

SHAPED = {**CONFIG, "project": {**CONFIG["project"], "backend_paths": ["apps/service/"]}, "cycle": {
    "docs": ["knowledge/"],
    "feature_folders": ["apps/service/src/api/"],
    "risk": {"config": ["apps/service/", "guide/", "REVIEW.md", "session"]},
    "tiny_folders": ["apps/web/", "apps/site/"],
    "structure_files": ["apps/*/src/screens/*.screen.tsx"],
    "feature_triggers": [
        {"why": "a ShareLevel change", "path": "apps/service/*", "added": ".*ShareLevel.*",
         "removed": ".*ShareLevel.*"},
        {"why": "a new registry key", "path": "apps/service/src/commands/registry.py",
         "added": r'^\s*"([a-z_]+)"\s*:\s*Entry\(|REGISTRY\["([^"]+)"\]\s*='},
        {"why": "a new tool", "path": "apps/service/src/tools/list.py", "added": r'name="([a-z_]+__[a-z_]+)"'},
        {"why": "a name leaving HELD", "path": "apps/service/src/tools/list.py", "line": r"^\s*HELD\b",
         "removed": r'"([^"]+)"|\*([A-Z][A-Z_]+)'},
    ]}}


@pytest.mark.parametrize("part, reason", [
    (change("apps/service/src/sharing/rules.py", lines=["    level = ShareLevel.FRIENDS"],
            gone=["    level = ShareLevel.ANYONE"]),
     "a ShareLevel change, apps/service/src/sharing/rules.py: level = ShareLevel.ANYONE, level = ShareLevel.FRIENDS"),
    (change("apps/service/tests/test_rules.py", lines=["assert ShareLevel.NOBODY"]),
     "a ShareLevel change, apps/service/tests/test_rules.py: assert ShareLevel.NOBODY"),
    (change("apps/service/src/commands/registry.py", lines=['    "move_exam": Entry(kind="write"),']),
     "a new registry key, apps/service/src/commands/registry.py: move_exam"),
    (change("apps/service/src/commands/registry.py", lines=['REGISTRY["sam_only"] = Entry()']),
     "a new registry key, apps/service/src/commands/registry.py: sam_only"),
    (change("apps/service/src/tools/list.py", lines=['    Tool(name="calendar__move", run=move),']),
     "a new tool, apps/service/src/tools/list.py: calendar__move"),
    (change("apps/service/src/tools/list.py", lines=['HELD = frozenset({"mail__send"})'],
            gone=['HELD = frozenset({"mail__send", "mail__read", *WRITES})']),
     "a name leaving HELD, apps/service/src/tools/list.py: WRITES, mail__read"),
])
def test_a_feature_trigger_from_the_config_makes_it_a_feature_with_its_why(part, reason):
    result = verdict(part, config=SHAPED)
    assert result.tier == "FEATURE" and reason in result.reasons


@pytest.mark.parametrize("part", [
    change("apps/service/src/sharing/rules.py", lines=["    level = ShareLevel.ANYONE"],
           gone=["    level = ShareLevel.ANYONE"]),
    change("apps/service/src/commands/registry.py", lines=['    "move_exam": Entry(kind="read"),'],
           gone=['    "move_exam": Entry(kind="write"),']),
    change("apps/service/src/tools/list.py", lines=['HELD = frozenset({"mail__send", "mail__read"})'],
           gone=['HELD = frozenset({"mail__send"})']),
    change("apps/service/src/other.py", lines=['    Tool(name="calendar__move", run=move),']),
])
def test_a_config_trigger_ignores_a_moved_line_an_edited_key_a_name_held_back_and_other_files(part):
    assert verdict(part, config=SHAPED).tier == "SMALL"


def test_a_bad_feature_trigger_is_a_one_line_error():
    config = {**CONFIG, "cycle": {"feature_triggers": [{"path": "a/*", "why": "x", "added": "("}]}}
    with pytest.raises(cli.ColonyError, match="feature_triggers entry 1 \\(x\\): bad pattern"):
        verdict(change("a/b.py", added=1), config=config)
    with pytest.raises(cli.ColonyError, match="needs path, why, and added or removed"):
        verdict(change("a/b.py", added=1), config={**CONFIG, "cycle": {"feature_triggers": [{"path": "a/*"}]}})


def test_a_top_level_page_on_the_risk_list_is_not_docs_but_a_wiki_page_named_for_a_fragment_is():
    result = verdict(change("REVIEW.md", added=2), config=SHAPED)
    assert result.tier == "SMALL" and result.risks == ["config: REVIEW.md"]
    assert verdict(change("README.md", added=2), config=SHAPED).tier == "TINY"
    assert verdict(change("knowledge/wiki/session-length.md", added=2), config=SHAPED).tier == "TINY"
    assert verdict(change("guide/rules/coding.md", added=2), config=SHAPED).risks == ["config: guide/rules/coding.md"]


@pytest.mark.parametrize("part, old", [
    (change("apps/web/src/app/settings/page.tsx", status="D", removed=4), "apps/web/src/app/settings/page.tsx"),
    (change("apps/site/src/app/(public)/layout.tsx", status="R", old="apps/site/src/app/layout.tsx"),
     "apps/site/src/app/layout.tsx"),
    (change("apps/web/src/screens/home.screen.tsx", status="D", removed=1), "apps/web/src/screens/home.screen.tsx"),
    (change("apps/web/src/features/plan/old.ts", status="D", removed=2), "apps/web/src/features/plan/old.ts"),
])
def test_a_moved_or_deleted_page_layout_route_or_feature_folder_file_is_never_tiny(part, old):
    config = {**SHAPED, "cycle": {**SHAPED["cycle"], "feature_folders": ["apps/web/src/features/"]}}
    result = verdict(part, config=config)
    assert result.tier == "SMALL"
    assert f"a page, layout, route or feature-folder file moved or deleted, {old}" in result.reasons


def test_a_new_structure_file_from_the_config_is_a_feature():
    result = verdict(change("apps/web/src/screens/week.screen.tsx", status="A", added=3), config=SHAPED)
    assert result.reasons == ["a new page, layout or route file, apps/web/src/screens/week.screen.tsx"]


def test_code_outside_the_tiny_folders_is_never_tiny_even_a_test_or_a_root_file():
    assert verdict(change("apps/web/src/a.tsx", added=3), config=SHAPED).tier == "TINY"
    for path in ("tools/check.py", "skills-lock.json", "tests/e2e/helpers.py"):
        result = verdict(change(path, added=3), config=SHAPED)
        assert result.tier == "SMALL" and f"code outside the tiny_folders, {path}" in result.reasons
    assert verdict(change("tools/check.py", added=3)).tier == "TINY"  # no tiny_folders, no such rule


def test_a_test_in_a_second_area_makes_two_areas():
    result = verdict(change("apps/web/src/a.tsx", added=3), change("apps/site/tests/a.test.ts", added=3))
    assert result.tier == "SMALL" and "code in more than one area, apps/site, apps/web" in result.reasons


def test_a_new_feature_folder_counts_even_when_its_first_file_is_a_test():
    result = verdict(change("apps/web/src/features/exams/exams.test.ts", status="A", added=3),
                     existed=lambda entry: False)
    assert result.reasons == ["a new entry under features/, apps/web/src/features/exams"]


def test_a_rename_off_the_risk_list_is_on_it_and_e2e_helpers_are_tests():
    result = verdict(change("apps/web/src/user/form.tsx", status="R", old="apps/web/src/auth/form.tsx"))
    assert result.risks == ["auth: apps/web/src/user/form.tsx"]
    result = verdict(change("apps/web/e2e/support/walk.ts", removed=2))
    assert result.risks == ["checks: apps/web/e2e/support/walk.ts, deletes test lines"]


# The risk list


@pytest.mark.parametrize("path, lines, risk", [
    ("src/auth/session.ts", None, "auth: src/auth/session.ts"),
    ("web/src/login/form.tsx", None, "auth: web/src/login/form.tsx"),
    ("src/billing/invoice.py", None, "payments: src/billing/invoice.py"),
    ("db/migrations/0004.py", ["op.add_column('users', sa.Column('age'))"], "migrations: db/migrations/0004.py"),
    ("src/settings.py", ['API_KEY = "abcd1234efgh5678"'],
     'secrets: src/settings.py, adds `API_KEY = "abcd1234efgh5678"`'),
    (".env.example", None, "secrets: .env.example"),
    ("src/jobs/cleanup.py", ['db.execute("DELETE FROM users WHERE old")'],
     'deletion: src/jobs/cleanup.py, adds `db.execute("DELETE FROM users WHERE old")`'),
    ("src/api/users.py", None, "public API: src/api/users.py"),
    ("proto/calendar.proto", None, "public API: proto/calendar.proto"),
    ("web/package.json", None, "dependencies: web/package.json, a dependency manifest"),
    ("requirements-dev.txt", None, "dependencies: requirements-dev.txt, a dependency manifest"),
    (".github/workflows/ci.yml", None, "config: .github/workflows/ci.yml"),
    ("AGENTS.md", None, "config: AGENTS.md"),
    (".colony/rules/coding.md", None, "config: .colony/rules/coding.md"),
])
def test_the_risk_list_names_each_kind(path, lines, risk):
    result = verdict(change(path, added=1, lines=lines))
    assert risk in result.risks and result.tier != "TINY"


def test_docs_tests_and_reports_stay_off_the_risk_list():
    result = verdict(change("knowledge/wiki/auth.md", lines=["Run DELETE FROM users to reset."]),
                     change("tests/test_auth.py", lines=["shutil.rmtree(tmp)"]),
                     change(".colony/reports/b1/review-1.md", added=3))
    assert result.risks == [] and result.tier == "TINY"


def test_a_test_with_a_real_looking_secret_is_still_flagged():
    result = verdict(change("tests/test_client.py", lines=['token = "ghp_' + "a" * 36 + '"']))
    assert [risk.split(",")[0] for risk in result.risks] == ["secrets: tests/test_client.py"]


def test_the_config_adds_risk_fragments_and_new_kinds():
    config = {**CONFIG, "cycle": {"risk": {"payments": ["src/ledger/"], "personal data": ["src/profile/"]}}}
    result = verdict(change("src/ledger/post.py", added=1), change("src/profile/view.py", added=1), config=config)
    assert result.risks == ["payments: src/ledger/post.py", "personal data: src/profile/view.py"]


def test_the_risk_list_runs_in_kind_order():
    result = verdict(change("web/package.json", added=1), change("src/auth/a.py", added=1),
                     change("tests/test_a.py", removed=1))
    assert [risk.split(":")[0] for risk in result.risks] == ["auth", "dependencies", "checks"]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git repo with one commit on `base`, checked out on a new branch `work`."""
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, check=True,
                       capture_output=True)

    git("init", "-q", "-b", "base")
    (root / "src" / "features" / "calendar").mkdir(parents=True)
    (root / "src" / "features" / "calendar" / "view.ts").write_text("export const a = 1\n")
    git("add", "-A")
    git("commit", "-qm", "first")
    git("switch", "-qc", "work")
    monkeypatch.chdir(root)
    return root, git


def test_tier_reads_the_branch_from_git_and_prints_the_tier_and_risks(repo, capsys):
    root, git = repo
    (root / "src" / "features" / "calendar" / "view.ts").write_text("export const a = 2\n")
    (root / "src" / "features" / "billing").mkdir()
    (root / "src" / "features" / "billing" / "pay.ts").write_text("export const pay = 1\n")
    git("add", "-A")
    git("commit", "-qm", "billing")
    args = parse("tier", "--base", "base", "--why")
    assert args.run(CONFIG, args) == 0
    assert capsys.readouterr().out.splitlines() == [
        "FEATURE", "why:", "- a new entry under features/, src/features/billing", "risks:",
        "- payments: src/features/billing/pay.ts"]
    assert cycle.risk_text(CONFIG, "base") == "- payments: src/features/billing/pay.ts"


def test_tier_against_a_base_that_names_no_commit_says_to_fetch(repo):
    args = parse("tier", "--base", "origin/gone")
    with pytest.raises(cli.ColonyError, match="git fetch origin"):
        args.run(CONFIG, args)


# Needs you


@pytest.fixture
def lead(monkeypatch):
    """This session is Ana's lead."""
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    monkeypatch.setenv(cli.PERSON_ENV, "ana")


def test_needs_makes_the_issue_and_posts_the_line(gh, lead, capsys):  # noqa: F811
    gh.answer("issue list", [])
    gh.answer("issue create", "https://github.com/acme/demo/issues/9\n")
    args = parse("needs", "keep health checks at 30 s", "--default", "yes")
    assert args.run(CONFIG, args) == 0
    create = gh.called("issue", "create")[0]
    assert create[create.index("--title") + 1] == "Needs Ana"
    line = "for ana-lead: Ana decides: keep health checks at 30 s? Default: yes (from ana-lead)"
    assert gh.called("issue", "comment") == [["issue", "comment", "9", "--repo", "acme/demo", "--body", line]]
    assert capsys.readouterr().out.strip() == f"#9 {line}"


def test_needs_for_another_person_posts_on_their_issue(gh, lead):  # noqa: F811
    gh.answer("issue list", [{"number": 4, "title": "Needs Ana"}, {"number": 6, "title": "Needs Sam"}])
    args = parse("needs", "Ship the bundle today?", "--default", "tomorrow.", "--person", "sam")
    args.run(CONFIG, args)
    assert not gh.called("issue", "create")
    search = gh.called("issue", "list")[0]
    assert search[search.index("--search") + 1] == '"Needs Sam" in:title'
    assert gh.called("issue", "comment")[0][2] == "6"
    assert gh.called("issue", "comment")[0][-1] == ("for ana-lead: Sam decides: Ship the bundle today? "
                                                    "Default: tomorrow (from ana-lead)")


def test_needs_needs_a_session_and_one_short_line(gh, lead, monkeypatch):  # noqa: F811
    with pytest.raises(cli.ColonyError, match="under 300 characters"):
        cycle.needs_line("ana-lead", "ana", "why " * 80, "yes")
    monkeypatch.delenv(cli.SESSION_ENV)
    args = parse("needs", "a question", "--default", "x")
    with pytest.raises(cli.ColonyError, match="set COLONY_SESSION to this session's name"):
        args.run(CONFIG, args)
    assert gh.calls() == []


@pytest.mark.parametrize("session", ["spec", "researcher"])
def test_a_session_the_lead_opened_posts_needs_signed_with_its_name(gh, lead, monkeypatch, capsys, session):  # noqa: F811
    monkeypatch.setenv(cli.SESSION_ENV, session)
    gh.answer("issue list", [{"number": 4, "title": "Needs Ana"}])
    args = parse("needs", "Approve the requirements of export?", "--default", "no cards until you approve")
    assert args.run(CONFIG, args) == 0
    line = ("for ana-lead: Ana decides: Approve the requirements of export? Default: no cards until you approve "
            f"(from {session})")
    assert gh.called("issue", "comment") == [["issue", "comment", "4", "--repo", "acme/demo", "--body", line]]
    assert capsys.readouterr().out.strip() == f"#4 {line}"
    lead_wait = cycle.wait.lead_session(CONFIG, "ana-lead")
    assert [taken for taken, _ in cycle.wait.taken(line, lead_wait, "4")] == [line]  # the lead's wait takes it


# The handover


def test_handover_posts_on_the_coordination_issue_and_prints_the_fresh_lead(gh, lead, capsys):  # noqa: F811
    gh.answer("issue list", [{"number": 5, "title": "Colony: coordination"}])
    gh.answer("issue comment", "https://github.com/acme/demo/issues/5#issuecomment-1\n")
    args = parse("handover", "--decisions", "#12 uses the default", "--open", "none", "--next", "merge #13")
    assert args.run(CONFIG, args) == 0
    body = gh.called("issue", "comment")[0][-1]
    assert body.splitlines() == ["handover from ana-lead, 2026-11-05 14:05 UTC", "decisions: #12 uses the default",
                                 "open questions: none", "next: merge #13"]
    assert "Open the fresh lead: colony --person ana" in capsys.readouterr().out


def test_handover_read_prints_this_leads_last_handover(gh, lead, capsys):  # noqa: F811
    gh.answer("issue list", [{"number": 5, "title": "Colony: coordination"}])
    gh.answer("issue view", {"comments": [{"body": "handover from ana-lead, 1\nnext: a"},
                                          {"body": "handover from sam-lead, 2\nnext: b"},
                                          {"body": "handover from ana-lead, 3\nnext: c"}]})
    args = parse("handover", "--read")
    args.run(CONFIG, args)
    assert capsys.readouterr().out.strip() == "handover from ana-lead, 3\nnext: c"


def test_handover_needs_all_three_parts(gh, lead):  # noqa: F811
    gh.answer("issue list", [{"number": 5, "title": "Colony: coordination"}])
    args = parse("handover", "--decisions", "x")
    with pytest.raises(cli.ColonyError, match="--open, --next"):
        args.run(CONFIG, args)


# Card stats

T0 = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)


def at(minutes: float) -> str:
    """A GitHub time `minutes` after T0."""
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def card(title, body, *comments):
    """A card as `gh issue view --json title,body,comments` answers it."""
    return {"title": title, "body": body, "comments": [{"createdAt": at(m), "body": b} for m, b in comments]}


def transcript(home: Path, root: Path, name: str, builder: str, calls):
    """A builder's Claude Code transcript in an account folder: its first prompt, then one assistant call per
    (minutes, message id, tokens)."""
    folder = home / "projects" / cycle.project_folder(root)
    folder.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "user", "timestamp": at(-1),
              "message": {"content": f"Read .colony/playbook.md, Builder section. You are {builder}. Start the wait."}}]
    lines += [{"type": "assistant", "timestamp": at(m), "requestId": f"r{mid}",
               "message": {"id": mid, "usage": {"input_tokens": tokens, "output_tokens": 0}}}
              for m, mid, tokens in calls]
    path = folder / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    os.utime(path, (T0.timestamp() + 7200, T0.timestamp() + 7200))
    return path


def test_stats_sums_each_cards_predicted_and_actual_minutes_and_tokens(gh, tmp_path):  # noqa: F811
    root = tmp_path / "repo"
    gh.answer("issue view 12", card("builder-1: the banner", "## Task\nx\n\npredicted: S, 20 min, 1M tokens",
                                    (0, "for builder-1: start this card (from lead)"),
                                    (30, "for lead: done, builder-1/12 pushed, 12 passed (from builder-1)")))
    gh.answer("issue view 13", card("builder-2: the route", "predicted: M, 40 min",
                                    (10, "**for builder-2: start this card (from lead)**")))
    one, two = tmp_path / "acct-one", tmp_path / "acct-two"
    main = transcript(one, root, "s1", "builder-1", [(1, "a", 1000), (2, "b", 500), (2, "b", 500), (45, "c", 9000)])
    sub = main.parent / "s1" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.jsonl").write_text(json.dumps({"type": "assistant", "timestamp": at(3), "requestId": "rs",
                                                   "message": {"id": "s", "usage": {"input_tokens": 2000}}}) + "\n")
    transcript(two, root, "s2", "builder-2", [(11, "d", 3000), (12, "e", 4000)])
    transcript(two, root, "s3", "builder-22", [(11, "f", 99999)])  # another builder whose name starts the same

    table = cycle.stats_table(CONFIG, {"12": None, "13": None}, now=T0 + timedelta(minutes=70), homes=[one, two],
                              root=root)
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in table.splitlines()[2:]]
    assert rows[0] == ["#12", "builder-1", "S", "done line", "20", "30.0", "2.0", "1.0M", "4K", "-"]
    assert rows[1] == ["#13", "builder-2", "M", "open", "40", "60.0", "1.0", "-", "7K", "-"]
    assert rows[2] == ["**total**", "", "", "", "60", "90.0", "3.0", "1.0M", "10K", ""]


def test_stats_reads_the_cards_given_on_the_command_line(gh, capsys, monkeypatch):  # noqa: F811
    monkeypatch.setattr(cycle, "main_root", lambda: Path("/nowhere"))
    gh.answer("issue view 7", card("builder-1: x", "no prediction"))
    args = parse("stats", "--card", "#7")
    assert args.card == [("7", None)]
    args.run(CONFIG, args)
    assert "| #7 | builder-1 | - | no start line |" in capsys.readouterr().out


# Stale cards


def items_answer(*cards):
    """The board's items query answer: (number, status, last update, helper) per card, on the five-field board."""
    nodes = []
    for number, status, last, helper in cards:
        values = [{"name": status, "field": {"name": "Status"}}, {"text": last, "field": {"name": "Last update"}},
                  {"text": helper, "field": {"name": "Helper"}}, {"text": "ana-lead", "field": {"name": "Lead"}}]
        nodes.append({"id": f"I{number}", "content": {"number": number, "url": f"u/{number}", "state": "OPEN"},
                      "fieldValues": {"nodes": values}})
    return {"data": {"node": {"items": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}}


NOW = datetime(2026, 11, 5, 13, 0, tzinfo=timezone.utc)


def test_a_card_in_progress_with_no_update_for_2_5_hours_is_stale_once(gh):  # noqa: F811
    gh.answer("project list", LISTED)
    gh.answer("items(first", items_answer((12, "In progress", "2026-11-05 10:29 UTC", "builder-2"),
                                          (13, "In progress", "2026-11-05 10:31 UTC", "builder-3"),
                                          (15, "Done", "2026-11-05 06:00 UTC", "builder-5"),
                                          (16, "In progress", "", "builder-6")))
    assert cycle.stale_lines(CONFIG, NOW) == [
        "#12 stale: builder-2 shows no update since 2026-11-05 10:29 UTC; check its session"]
    assert cycle.stale_lines(CONFIG, NOW.timestamp() + 60) == []  # reported once, and a Unix time works too
    later = cycle.stale_lines(CONFIG, NOW + timedelta(minutes=5))
    assert [line.split(" ")[0] for line in later] == ["#13"]


def test_the_board_has_no_state_so_a_helper_on_a_usage_limit_is_stale_too(gh):  # noqa: F811
    # The five-field board dropped State, and with it the usage-limit exemption: the lead looks at the session.
    gh.answer("project list", LISTED)
    gh.answer("items(first", items_answer((14, "In progress", "2026-11-05 06:00 UTC", "builder-4")))
    assert cycle.stale_lines(CONFIG, NOW) == [
        "#14 stale: builder-4 shows no update since 2026-11-05 06:00 UTC; check its session"]


def test_a_stale_card_is_reported_again_after_its_last_update_changes(gh):  # noqa: F811
    gh.answer("project list", LISTED)
    gh.answer("items(first", items_answer((12, "In progress", "2026-11-05 08:00 UTC", "")), once=True)
    gh.answer("items(first", items_answer((12, "In progress", "2026-11-05 09:00 UTC", "")))
    assert len(cycle.stale_lines(CONFIG, NOW)) == 1
    assert cycle.stale_lines(CONFIG, NOW) == ["#12 stale: its helper shows no update since 2026-11-05 09:00 UTC; "
                                              "check its session"]


def test_no_board_means_no_stale_lines_and_a_broken_board_is_an_error(gh):  # noqa: F811
    gh.answer("project list", {"projects": []}, once=True)
    assert cycle.stale_lines(CONFIG, NOW) == []
    gh.answer("project list", "", code=1)
    with pytest.raises(cli.ColonyError):
        cycle.stale_lines(CONFIG, NOW)


def test_the_stale_hours_come_from_the_config(gh):  # noqa: F811
    gh.answer("project list", LISTED)
    gh.answer("items(first", items_answer((12, "In progress", "2026-11-05 12:00 UTC", "builder-2")))
    assert cycle.stale_lines({**CONFIG, "cycle": {"stale_hours": 0.5}}, NOW) != []


# The retro


def test_the_retro_prompt_is_filled_in_for_the_batch():
    config = {**CONFIG, "project": {**CONFIG["project"], "fast_check": "make fast"},
              "gate": {"rules": [".colony/rules/*.md", "CLAUDE.md"]}}
    prompt = cycle.retro_prompt(config, "2026-11-05", Path("/r/reports"), Path("/w/demo-retro"),
                                "demo/retro-2026-11-05", Path("/w/demo-retro/retro.md"), "Assisted-by: x")
    assert "{" not in prompt and "}" not in prompt
    for text in ("Batch 2026-11-05", "/r/reports", "/w/demo-retro, on branch demo/retro-2026-11-05",
                 "`.colony/rules/*.md`, `CLAUDE.md`", "(`make check`)", "Run `make fast`", "`Assisted-by: x`",
                 "Write /w/demo-retro/retro.md", "`lessons: N`", "rule line plus a check", "decision",
                 "never as a note alone"):
        assert text in prompt, text


def test_retro_dry_run_finds_the_reports_and_prints_the_plan_and_prompt(repo, tmp_path, capsys, monkeypatch):
    root, _ = repo
    reports = root / ".colony" / "reports" / "b1"
    reports.mkdir(parents=True)
    (reports / "review-1.md").write_text("open: 0\n")
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    config = {**CONFIG, "project": {**CONFIG["project"], "worktrees": str(tmp_path / "trees")}}
    args = parse("retro", "--name", "b1", "--dry-run")
    assert args.run(config, args) == 0
    out = capsys.readouterr().out
    assert f"--no-track -b demo/retro-b1 {tmp_path / 'trees' / 'demo-retro-b1'} origin/dev" in out
    assert f"its round reports are in {reports}" in out.replace(str(reports.resolve()), str(reports))
    assert "--add-dir" in out and "--- retro prompt" in out


def test_retro_without_reports_says_to_run_the_batch(repo):
    args = parse("retro", "--name", "nope", "--dry-run")
    with pytest.raises(cli.ColonyError, match="no reports for batch 'nope'"):
        args.run(CONFIG, args)


def test_the_retro_reads_the_decisions_it_prints():
    found = cycle.DECISION.match("decision: keep the walk on phones? — default: yes")
    assert found.groups() == ("keep the walk on phones?", "yes")


def calibrated_cards():
    """Closed cards as `gh issue list --json number,title,body,comments` answers them: two S cards done in 30 and 50
    minutes, an M card done in 90, one with no prediction and one with no done line, which don't count."""
    def done(number, title, prediction, minutes):
        builder = title.split(":")[0]
        return {"number": number, **card(title, prediction, (0, f"for {builder}: start this card (from lead)"),
                                         (minutes, f"for lead: done, x pushed, 3 passed (from {builder})"))}
    return [done(5, "builder-1: a", "predicted: S, 20 min", 30), done(4, "builder-2: b", "predicted: S, 20 min", 50),
            done(3, "builder-1: c", "predicted: M, 40 min", 90), done(2, "builder-1: d", "no prediction", 10),
            {"number": 1, **card("builder-2: e", "predicted: L, 60 min", (0, "for builder-2: start this card"))}]


def test_stats_calibrate_prints_the_median_actual_minutes_per_size(gh, capsys):  # noqa: F811
    gh.answer("issue list", calibrated_cards())
    args = parse("stats", "--calibrate")
    assert args.run(CONFIG, args) == 0
    out = capsys.readouterr().out
    assert "| S | 2 | 40 |\n| M | 1 | 90 |\n" in out
    assert "| L |" not in out
    assert gh.called("issue", "list")[0][-1] == str(cycle.CALIBRATE_LISTED)


def test_stats_calibrate_reads_only_the_last_thirty_measured_cards(gh, monkeypatch):  # noqa: F811
    gh.answer("issue list", calibrated_cards())
    monkeypatch.setattr(cycle, "CALIBRATE_CARDS", 2)
    assert cycle.calibration(CONFIG) == {"S": (40, 2)}


def test_stats_needs_a_card_or_calibrate(gh):  # noqa: F811
    args = parse("stats")
    with pytest.raises(cli.ColonyError, match="--calibrate"):
        args.run(CONFIG, args)


def test_calibration_line_puts_the_median_beside_the_prediction(gh):  # noqa: F811
    gh.answer("issue list", calibrated_cards())
    assert cycle.calibration_line(CONFIG, "s", cycle.prediction_of("predicted: S, 25 min")) == \
        "predicted 25 min; the last 2 S cards took a median of 40 min"
    assert cycle.calibration_line(CONFIG, "M", None) == "the last 1 M cards took a median of 90 min"
    assert cycle.calibration_line(CONFIG, "L", None) is None
