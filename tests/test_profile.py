"""Tests for colony/profile.py: standing orders at three levels, personal, team and session, merged for each session
with clear precedence and conflict rules; setup asked once; rules learned from corrections; import after the person's
yes; no secret in any profile; `colony profile show`; live changes; and many people on one team."""
import argparse
import io
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from colony import cli, guards, profile, wait

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "ghp_" + "a1B2" * 9


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          capture_output=True, text=True, check=True).stdout


def run(capsys, *argv: str) -> tuple[int, str, str]:
    """Run one colony command, and return its exit code, output and errors."""
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def config_home() -> Path:
    return Path(os.environ["COLONY_CONFIG_HOME"])


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """A fresh home folder, and a working folder outside any git checkout."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    (tmp_path / "home").mkdir()
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    return tmp_path / "home"


@pytest.fixture
def repo(home, tmp_path, monkeypatch) -> Path:
    """A set-up repo, `demo` on base main, with no remote: its working copy of the team profile counts."""
    root = tmp_path / "repo"
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    write(root / ".colony" / "colony.toml", '[project]\nname = "demo"\nbase = "main"\n')
    monkeypatch.chdir(root)
    return root


def team(root: Path, text: str) -> None:
    write(root / profile.TEAM_PATH, text)


def personal(text: str, name: str = profile.PERSONAL_FILE) -> Path:
    return write(config_home() / name, text)


# Where the files live


def test_the_personal_profile_folder_is_colony_config_home_then_appdata_then_xdg_then_dot_config():
    assert profile.config_home({"COLONY_CONFIG_HOME": "/somewhere"}, windows=False) == Path("/somewhere")
    windows = {"APPDATA": "/roaming", "XDG_CONFIG_HOME": "/xdg"}
    assert profile.config_home(windows, windows=True) == Path("/roaming") / "colony"
    assert profile.config_home(windows, windows=False) == Path("/xdg/colony")
    assert profile.config_home({}, windows=True) == Path.home() / ".config" / "colony"
    assert profile.config_home({}, windows=False) == Path.home() / ".config" / "colony"


def test_a_profile_round_trips_through_its_toml_writer():
    data = {"mode": "speed", "writing": {"style": 'say "it" plainly\\ \n then stop é \x7f', "language": "English"},
            "machine": {"max_helpers": 3, "busy_load_percent": 80}, "budgets": {"dollars_per_day": 2.5},
            "decisions": {"never_raise": ["a b", "c"]}, "flag": True,
            "answers": {"decisions.answer_wait_minutes": {"team": 30, "mine": 60, "chose": "mine"}},
            "rules": [{"id": 1, "text": "One.", "added": "2026-11-24"}, {"id": 3, "text": "Three.", "from": "x"}]}
    text = profile.dumps(data, "a header\nof two lines")
    assert text.startswith("# a header\n# of two lines\n")
    assert tomllib.loads(text) == data


# Rules: add, list, remove, and no secret


def test_prefer_adds_lists_and_removes_rules_by_their_ref(home, capsys):
    assert run(capsys, "prefer", "add", "Keep", "messages", "short.")[1].startswith("Rule p1 added: wrote ")
    assert run(capsys, "prefer", "add", "Answer first.", "--correction")[0] == 0
    out = run(capsys, "prefer", "list")[1]
    assert "p1: Keep messages short. (personal, " in out and "p2: Answer first. (personal, correction, " in out
    assert run(capsys, "prefer", "remove", "p1")[1].startswith("Rule p1 removed (Keep messages short.)")
    assert run(capsys, "prefer", "add", "Third.")[1].startswith("Rule p3 added")  # a ref is never reused
    out = run(capsys, "prefer", "list")[1]
    assert "p1:" not in out and "p2: Answer first." in out and "p3: Third." in out
    code, _, err = run(capsys, "prefer", "remove", "p9")
    assert code == 2 and "there is no rule p9 in the personal profile" in err
    if not sys.platform.startswith("win"):
        assert (config_home() / "profile.toml").stat().st_mode & 0o777 == 0o600


def test_no_profile_takes_a_secret_and_one_found_in_a_file_is_dropped_unseen(home, capsys):
    code, _, err = run(capsys, "prefer", "add", f"use {TOKEN} for the API")
    assert code == 2 and "looks like a token" in err and TOKEN not in err
    code, _, err = run(capsys, "profile", "set", "writing.style", "api_key = s3cretvalue")
    assert code == 2 and "secret" in err and "s3cretvalue" not in err
    assert not (config_home() / "profile.toml").exists()
    personal(f'[writing]\nstyle = "plain"\n\n[[rules]]\ntext = "token {TOKEN}"\n\n[[rules]]\ntext = "Be brief."\n'
             '[decisions]\nnever_raise = ["eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4f"]\n')
    loaded = profile.load()
    seen = json.dumps(profile.as_json(loaded)) + profile.render(loaded) + "\n".join(profile.show_lines(loaded))
    assert TOKEN not in seen and "SflKxwRJ" not in seen
    assert [rule.text for rule in loaded.rules] == ["Be brief."]
    assert any("rule 1 looks like it holds a secret" in w for w in loaded.warnings)
    assert any("decisions.never_raise looks like it holds a secret" in w for w in loaded.warnings)


def test_a_wrong_or_unknown_key_is_a_warning_and_never_stops_a_session(repo):
    team(repo, '[person]\nrole = "owner"\n\n[answers]\nx = 1\n\n[decisions]\nautonomy = "sometimes"\n'
               '[machine]\nmax_helpers = -1\n\n[made]\nup = 1\n')
    personal("this is [ not toml")
    loaded = profile.load()
    assert loaded.settings == {}
    text = " ".join(loaded.warnings)
    for part in ("person.role is a person's own setting", "[answers] belongs in a personal profile",
                 "decisions.autonomy is 'sometimes', not one of ask, routine, unattended",
                 "machine.max_helpers is -1, outside 0 or more", "made.up is not a profile key", "is not valid TOML"):
        assert part in text, part


# Precedence and conflict rules


def test_a_session_setting_beats_a_mode_which_beats_the_personal_one(home, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-1")
    personal('mode = "plan-first"\n[decisions]\nautonomy = "ask"\n[tests]\nfull_suite = "batch"\n')
    bundle = {"mode": "speed", "decisions": {"autonomy": "routine"}, "tests": {"full_suite": "release"}}
    mode = profile.layer_from(bundle, "mode speed", "mode speed")
    assert profile.load(layers=[mode]).value("tests.full_suite") == "release"
    path = profile.session_path("demo")
    assert path == home / ".colony" / "sessions" / "s-1.profile.toml"
    write(path, '[decisions]\nautonomy = "unattended"\n')
    loaded = profile.load(layers=[mode])
    assert loaded.mode == "speed" and loaded.value("decisions.autonomy") == "unattended"
    assert loaded.settings["decisions.autonomy"].source == "session"
    assert profile.load(session=False).value("decisions.autonomy") == "ask"


def test_where_the_team_and_a_person_disagree_the_stricter_or_smaller_wins_and_lists_combine():
    team_layer = profile.layer_from({"decisions": {"autonomy": "ask", "never_raise": ["pricing"]},
                                     "machine": {"max_helpers": 2}, "tests": {"full_suite": "release"},
                                     "merge": {"policy": "branches", "branches": ["integration", "next"]},
                                     "writing": {"style": "plain words"}, "budgets": {"dollars_per_day": 5}},
                                    "team", "team")
    mine = profile.layer_from({"decisions": {"autonomy": "unattended", "never_raise": ["the office move"]},
                               "machine": {"max_helpers": 6}, "tests": {"full_suite": "change"},
                               "merge": {"policy": "branches", "branches": ["next"]},
                               "writing": {"style": "short sentences"}, "budgets": {"dollars_per_day": 5}},
                              "personal", "personal")
    settings = profile.merge(team_layer, [mine], {}, "ana")
    autonomy = settings["decisions.autonomy"]
    assert autonomy.value == "ask" and autonomy.source == "team"
    assert autonomy.note == "the team's says ask, ana's says unattended: the stricter, the team's, applies"
    assert settings["tests.full_suite"].value == "change" and settings["tests.full_suite"].source == "personal"
    assert settings["machine.max_helpers"].value == 2
    assert settings["decisions.never_raise"].value == ["pricing", "the office move"]
    assert settings["merge.branches"].value == ["next"]
    assert settings["writing.style"].value == "plain words; short sentences"
    budget = settings["budgets.dollars_per_day"]
    assert budget.source == "team and personal" and not budget.note
    assert not any(setting.unresolved for setting in settings.values())


def test_a_disagreement_neither_side_wins_is_asked_once_and_the_answer_is_recorded(repo, capsys):
    team(repo, "[decisions]\nanswer_wait_minutes = 30\nautonomy = \"ask\"\n")
    personal("[decisions]\nanswer_wait_minutes = 60\nautonomy = \"routine\"\n")
    loaded = profile.load()
    wait_minutes = loaded.settings["decisions.answer_wait_minutes"]
    assert wait_minutes.value == 30 and wait_minutes.unresolved
    assert "`colony profile resolve decisions.answer_wait_minutes team|mine`" in wait_minutes.note
    assert "ask the person once which applies" in profile.render(loaded)
    code, _, err = run(capsys, "profile", "resolve", "decisions.autonomy", "mine")
    assert code == 2 and "needs no answer: the stricter wins" in err
    assert run(capsys, "profile", "resolve", "decisions.answer_wait_minutes", "mine")[0] == 0
    resolved = profile.load().settings["decisions.answer_wait_minutes"]
    assert resolved.value == 60 and not resolved.unresolved and "the person chose the personal one on " in resolved.note
    team(repo, "[decisions]\nanswer_wait_minutes = 20\n")  # the team's side changed: ask again
    assert profile.load().settings["decisions.answer_wait_minutes"].unresolved
    code, _, err = run(capsys, "profile", "resolve", "decisions.without_answer", "team")
    assert code == 2 and "nothing to resolve" in err


def test_the_team_profile_in_force_is_the_copy_on_origin_base(repo, tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    team(repo, '[decisions]\nautonomy = "ask"\n')
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "team profile")
    git(repo, "push", "-q", "origin", "main")
    team(repo, '[decisions]\nautonomy = "unattended"\n')  # an edit not merged yet
    loaded = profile.load()
    assert loaded.value("decisions.autonomy") == "ask"
    assert loaded.files["team"] == "team (.colony/team.toml on origin/main)"
    assert ".colony/team.toml here differs from origin/main: its changes take effect when their pull request merges" \
           in loaded.warnings
    git(repo, "commit", "-q", "-am", "loosen")
    git(repo, "push", "-q", "origin", "main")  # merged: now in force
    assert profile.load().value("decisions.autonomy") == "unattended"


def test_work_between_people_follows_the_team_profile_alone(repo):
    team(repo, '[tests]\nfull_suite = "batch"\n')
    personal('[tests]\nfull_suite = "change"\n\n[[rules]]\ntext = "Mine alone."\n')
    loaded = profile.load(team_only=True)
    assert loaded.value("tests.full_suite") == "batch" and loaded.rules == [] and "personal" not in loaded.files
    assert "the team's alone" in profile.show_lines(loaded)[0]


# Seeing the orders


def test_show_names_each_order_and_where_it_came_from(repo, capsys):
    team(repo, '[decisions]\nautonomy = "ask"\n\n[[rules]]\ntext = "Write plainly."\n')
    personal('[decisions]\nautonomy = "routine"\n[tests]\nfull_suite = "batch"\n')
    assert run(capsys, "prefer", "add", "Answer first.")[0] == 0
    out = run(capsys, "profile", "show")[1]
    assert "- decisions.autonomy = ask (from team; the team's says ask, the person's says routine: the stricter, " \
           "the team's, applies)" in out
    assert "- tests.full_suite = batch (from personal)" in out
    assert "- t1: Write plainly. (team)" in out and "- p1: Answer first. (personal, " in out
    assert "Files: team (.colony/team.toml, the working copy: no origin/main to read); personal (" in out
    data = json.loads(run(capsys, "profile", "show", "--json")[1])
    assert data["settings"]["decisions.autonomy"] == {"value": "ask", "source": "team", "unresolved": False,
                                                       "note": data["settings"]["decisions.autonomy"]["note"]}
    assert [rule["ref"] for rule in data["rules"]] == ["t1", "p1"]
    assert run(capsys, "profile", "show", "--orders", "--role", "helper")[1].startswith(
        "Standing orders for this helper")


def test_a_helper_gets_only_the_orders_for_its_work_and_a_lead_hears_how_to_learn(home):
    personal('mode = "speed"\n[decisions]\nautonomy = "unattended"\n[tests]\nfull_suite = "batch"\n'
             '[merge]\npolicy = "pr"\nbranches = ["integration"]\n\n[[rules]]\ntext = "Write plainly."\n')
    loaded = profile.load(person="ana")
    lead = profile.render(loaded, "lead")
    assert lead.startswith("Standing orders for ana's session, mode speed (")
    assert "- Decide alone: take your recommended default for every decision, and log each one." in lead
    assert "colony prefer add" in lead and "Branches you may merge into" not in lead
    helper = profile.render(loaded, "helper")
    assert "Decide alone" not in helper and "Active mode" not in helper
    assert "- Run the tests for the changed code and the guard tests after each change, and the full suite once " \
           "per batch." in helper
    assert "- Rule p1: Write plainly." in helper and helper.endswith("- Ask your lead, never the person, when an "
                                                                     "order is unclear.")


def test_the_keys_command_lists_every_key(capsys):
    out = run(capsys, "profile", "keys")[1]
    for key in profile.KEYS:
        assert f"{key.name}: " in out
    assert "decisions.autonomy: one of ask, routine, unattended, strictest first; the stricter wins." in out


# Setup, asked once


def test_setup_asks_once_in_an_agent_session_and_writes_the_answers(home, capsys):
    out = run(capsys, "profile", "setup")[1]
    assert "Ask the person these 8 questions once" in out and "1. How much may your leads decide alone" in out
    assert not (config_home() / "profile.toml").exists() and profile.needs_setup()
    code, out, _ = run(capsys, "profile", "setup", "--set", "decisions.autonomy=ask",
                       "--set", "decisions.never_raise=pricing, the office move")
    assert code == 0 and "It isn't asked again." in out
    loaded = profile.load()
    assert loaded.value("decisions.autonomy") == "ask"
    assert loaded.value("decisions.never_raise") == ["pricing", "the office move"]
    assert loaded.value("decisions.answer_wait_minutes") == 30  # a question left out takes its default
    assert not profile.needs_setup()
    assert "isn't asked again" in run(capsys, "profile", "setup")[1]
    assert run(capsys, "profile", "setup", "--again", "--defaults")[0] == 0
    assert profile.load().value("decisions.autonomy") == "ask"  # a default never replaces a value held


def test_setup_in_a_terminal_asks_each_question_and_enter_keeps_the_default(home, monkeypatch, capsys):
    answers = iter(["ask", "soon", "45", "", "", "", "branches", "integration, next", "", "3"])
    monkeypatch.setattr(profile.portable, "is_terminal", lambda stream: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    code, out, _ = run(capsys, "profile", "setup")
    assert code == 0 and "decisions.answer_wait_minutes takes a number, not 'soon'" in out
    loaded = profile.load()
    assert [loaded.value(k) for k in ("decisions.autonomy", "decisions.answer_wait_minutes", "monitoring.report",
                                      "merge.policy", "merge.branches", "budgets.dollars_per_day")] == \
        ["ask", 45, "progress", "branches", ["integration", "next"], 3]


def test_a_session_setting_is_written_for_that_session_alone(home, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-9")
    out = run(capsys, "profile", "set", "--session", "tests.full_suite", "change")[1]
    assert out.endswith("s-9.profile.toml, for this session alone\n")
    assert profile.load().settings["tests.full_suite"].source == "session"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-10")
    assert profile.load().settings == {}
    out = run(capsys, "profile", "unset", "--session", "tests.full_suite")[1]
    assert out.startswith("tests.full_suite was not set")


def test_a_helper_never_changes_a_profile(home, monkeypatch, capsys):
    monkeypatch.setenv("COLONY_SESSION", "builder-2")
    for argv in (("prefer", "add", "Be brief."), ("profile", "set", "decisions.autonomy", "ask"),
                 ("profile", "setup", "--defaults")):
        code, _, err = run(capsys, *argv)
        assert code == 2 and "a helper never changes a profile: ask your lead" in err
    assert not (config_home() / "profile.toml").exists()


def test_setup_leaves_a_key_the_team_sets_to_the_team(repo, capsys):
    team(repo, '[tests]\nfull_suite = "batch"\n')
    assert "When should the full test suite run" in run(capsys, "profile", "setup")[1]
    assert "Default: batch." in run(capsys, "profile", "setup")[1]
    assert run(capsys, "profile", "setup", "--defaults")[0] == 0
    data = tomllib.loads((config_home() / "profile.toml").read_text())
    assert "tests" not in data and data["decisions"]["autonomy"] == "routine"


# Import, after the person's yes


def test_import_offers_each_preference_and_adds_only_what_the_person_accepts(repo, home, capsys):
    write(home / ".claude" / "CLAUDE.md", "# Response style\n@extra.md\nAlways use simple, clear language.\n"
                                          "Explain every term.\n\n- Never push to the base branch.\n"
                                          f"- Use the key {TOKEN} for the API.\n```\n- not this, it is code\n```\n")
    memory = home / ".claude" / "projects" / profile.claude_slug(profile.repo()) / "memory"
    write(memory / "feedback_one.md", "---\nname: one\nmetadata:\n  type: feedback\n---\n\nRun one pytest per test "
                                      "database.\n**Why:** they clash.\n")
    write(memory / "project_state.md", "---\nname: state\ntype: project\n---\n\nFeature 3 merged last week.\n")
    write(memory / "MEMORY.md", "- [One](feedback_one.md) — an index line\n")
    write(home / ".codex" / "AGENTS.md", "- Keep each change small and reviewable.\n")
    out = run(capsys, "profile", "import")[1]
    offered = {line.split(": ", 1)[1].rsplit(" (", 1)[0]: line[2:9] for line in out.splitlines()
               if line.startswith("- ")}
    assert set(offered) == {"Always use simple, clear language. Explain every term.", "Never push to the base branch.",
                            "Run one pytest per test database.", "Keep each change small and reviewable."}
    assert "1 more looked like a secret and were left out." in out and TOKEN not in out
    assert not (config_home() / "profile.toml").exists()  # nothing is added before the person's yes
    code, out, _ = run(capsys, "profile", "import", "--accept", offered["Never push to the base branch."],
                       "--decline", offered["Keep each change small and reviewable."])
    assert code == 0 and out.startswith("Added 1 rule, and 1 declined won't be offered again")
    rules = profile.load().rules
    assert [(rule.text, rule.origin) for rule in rules] == [("Never push to the base branch.",
                                                            "import: ~/.claude/CLAUDE.md")]
    out = run(capsys, "profile", "import")[1]
    assert "Never push" not in out and "Keep each change" not in out and "Run one pytest" in out
    code, _, err = run(capsys, "profile", "import", "--accept", "nothere")
    assert code == 2 and "nothere is no candidate on offer" in err


def test_import_in_a_terminal_asks_about_each_and_q_keeps_the_rest_for_later(home, monkeypatch, capsys):
    write(home / "notes.md", "- First preference, kept.\n- Second preference, declined.\n- Third preference, later.\n")
    answers = iter(["y", "n", "q"])
    monkeypatch.setattr(profile.portable, "is_terminal", lambda stream: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert run(capsys, "profile", "import", "--from", str(home / "notes.md"))[0] == 0
    assert [rule.text for rule in profile.load().rules] == ["First preference, kept."]
    monkeypatch.setattr(profile.portable, "is_terminal", lambda stream: False)
    out = run(capsys, "profile", "import", "--from", str(home / "notes.md"))[1]
    assert "Third preference, later." in out and "Second" not in out and "First" not in out


# Privacy


def test_the_personal_profile_warns_when_a_git_checkout_could_commit_it(home, tmp_path, monkeypatch, capsys):
    dotfiles = tmp_path / "dotfiles"
    git(tmp_path, "init", "-q", str(dotfiles))
    monkeypatch.setenv("COLONY_CONFIG_HOME", str(dotfiles / "colony"))
    assert run(capsys, "prefer", "add", "Be brief.")[0] == 0
    assert "doesn't ignore it: add it to that repo's ignore file" in run(capsys, "profile", "show")[1]
    write(dotfiles / ".gitignore", "colony/\n")
    assert "ignore file" not in run(capsys, "profile", "show")[1]


def test_a_team_change_says_it_takes_effect_through_a_reviewed_pull_request(repo, capsys):
    out = run(capsys, "prefer", "add", "--team", "Write plainly.")[1]
    assert "wrote .colony/team.toml: commit it on a branch and open a pull request" in out
    code, _, err = run(capsys, "profile", "set", "--team", "person.role", "owner")
    assert code == 2 and "a team profile can't set" in err
    assert "Write plainly." in (repo / profile.TEAM_PATH).read_text()


def test_init_writes_a_team_profile_with_every_team_key_commented_out(repo, capsys):
    assert run(capsys, "profile", "init")[0] == 0
    text = (repo / profile.TEAM_PATH).read_text()
    assert tomllib.loads(text) == {}
    for key in profile.KEYS:
        assert (f"# {key.name.rpartition('.')[2]} = " in text) == key.team, key.name
    assert "stays as it is" in run(capsys, "profile", "init")[1]


def test_profile_commands_work_outside_a_repo_but_the_team_profile_needs_one(home, capsys):
    assert run(capsys, "profile")[0] == 0
    code, _, err = run(capsys, "prefer", "add", "--team", "Write plainly.")
    assert code == 2 and "run it inside the repo" in err


# Many people, one team


def test_each_persons_sessions_follow_their_own_profile_on_a_shared_computer(home, monkeypatch, capsys):
    monkeypatch.setenv("COLONY_PERSON", "ana")
    assert run(capsys, "prefer", "add", "Ana's rule.")[0] == 0
    assert tomllib.loads((config_home() / "profile.toml").read_text())["person"]["name"] == "ana"
    monkeypatch.setenv("COLONY_PERSON", "ben")
    loaded = profile.load()
    assert loaded.rules == [] and "is ana's personal profile, so it doesn't bind ben's sessions" in loaded.warnings[0]
    assert run(capsys, "prefer", "add", "Ben's rule.")[0] == 0
    assert (config_home() / "people" / "ben.toml").exists()
    assert [rule.text for rule in profile.load().rules] == ["Ben's rule."]
    assert [rule.text for rule in profile.load(person="ana").rules] == ["Ana's rule."]


# Live changes


CONFIG = {"project": {"name": "demo", "repo": "acme/demo", "base": "main"}}


def test_a_session_sees_its_orders_once_when_it_starts_and_each_change_after(home, monkeypatch):
    monkeypatch.setenv("COLONY_SESSION", "lead")
    assert profile.change_lines(CONFIG, "lead", full=True) == []  # no orders, no session id: nothing written
    assert not profile.record_path("demo", "lead").exists()
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-1")
    personal("[[rules]]\ntext = \"Be brief.\"\n")
    started = profile.change_lines(CONFIG, "lead", full=True)
    assert started[0].startswith("Standing orders for this session") and "- Rule p1: Be brief." in started
    assert profile.change_lines(CONFIG, "lead", full=True) == []
    personal("[[rules]]\ntext = \"Answer first.\"\n")
    assert profile.change_lines(CONFIG, "lead") == [profile.CHANGED, "- now: Rule p1: Answer first.",
                                                    "- no longer: Rule p1: Be brief."]
    assert profile.change_lines(CONFIG, "lead", full=True) == []  # the wait showed it: the hook doesn't again


def test_a_record_the_setup_reminder_wrote_alone_shows_no_empty_change(home, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-1")
    monkeypatch.setenv("COLONY_SESSION", "lead")
    assert profile.setup_nudge(CONFIG, "lead")  # writes a record that holds no orders yet
    assert profile.change_lines(CONFIG, "lead") == []


def test_a_running_wait_hears_a_change_within_a_minute(home):
    personal("[[rules]]\ntext = \"Be brief.\"\n")
    now = [0.0]
    check = profile.watcher(CONFIG, "builder-2", clock=lambda: now[0])
    assert check({}) == []  # the first look records what the session has
    personal("[[rules]]\ntext = \"Be brief.\"\n\n[[rules]]\ntext = \"Answer first.\"\n")
    now[0] = 30.0
    assert check({}) == []
    now[0] = 61.0
    assert check({}) == [profile.CHANGED, "- now: Rule p2: Answer first."]


def test_the_wait_of_every_session_carries_the_orders_check(home, monkeypatch):
    calls = []
    monkeypatch.setattr(wait.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(wait, "coordination_issue", lambda repo, project: 1)
    monkeypatch.setattr(wait, "wait", lambda *args, **kwargs: calls.append(kwargs) or 0)
    personal("[[rules]]\ntext = \"Be brief.\"\n")
    for me in ("builder-2", "lead"):
        monkeypatch.setenv("COLONY_SESSION", me)
        args = argparse.Namespace(person="ana", waiting_on=None)
        assert wait.run({**CONFIG, "features": {"board": False}}, args) == 0
    for kwargs in calls:
        assert kwargs["silent"]({}) == []  # its first look records the orders
    personal("[[rules]]\ntext = \"Answer first.\"\n")
    monkeypatch.setattr(profile, "PROFILE_EVERY", 0)
    assert calls[0]["silent"]({})[0] == profile.CHANGED


def test_the_prompt_hook_shows_the_orders_and_reminds_a_lead_of_setup_and_corrections(home, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-1")
    monkeypatch.setenv("COLONY_PERSON", "ana")
    wait.write_json(wait.state_path("demo", "lead"), {"polled_at": 9e12})  # a running wait: no GitHub read

    def hook(prompt: str) -> str:
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": prompt})))
        monkeypatch.setenv("COLONY_SESSION", "lead")
        assert guards.unread(CONFIG, argparse.Namespace()) == 0
        return capsys.readouterr().out

    out = hook("No, don't push to main without asking me.")
    assert "ana has no personal profile yet: ask its short setup questions once" in out
    assert "If this message corrects how you work, offer the person once to keep it as a standing order" in out
    assert hook("Add a dark mode switch.") == ""  # the setup reminder shows once a session
    personal('[person]\nname = "ana"\nsetup = "2026-11-24"\n\n[[rules]]\ntext = "Be brief."\n')
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-2")
    out = hook("Add a dark mode switch.")
    assert out.startswith("Standing orders for ana's session") and "- Rule p1: Be brief." in out
    assert "setup" not in out


def test_a_correction_reads_like_one():
    for prompt in ("No, don't push to main.", "From now on, answer first.", "I told you to ask first", "never again"):
        assert profile.correction_hint(prompt), prompt
    for prompt in ("Add a dark mode switch.", "Know what? Ship it.", ""):
        assert profile.correction_hint(prompt) == "", prompt


# Docs


def test_the_docs_name_every_key_and_every_command():
    page = (ROOT / "docs" / "profiles.md").read_text()
    for key in profile.KEYS:
        assert f"`{key.name}`" in page, key.name
    commands = (ROOT / "docs" / "commands.md").read_text()
    for command in ("profile show", "profile keys", "profile setup", "profile set", "profile unset",
                    "profile resolve", "profile import", "profile init", "prefer add", "prefer list",
                    "prefer remove"):
        assert f"`colony {command}" in commands, command
