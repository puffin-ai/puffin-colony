"""Tests for the modes, hack, solo and startup: each mode's defaults under colony.toml, the commands a mode turns off,
the gate per mode, the addresses (`for <name>:`, @login and @all), hack's board, and the unread cache the prompt hook
reads. A stand-in gh plays back canned answers and logs its calls, and a fake clock runs a wait in a moment."""
import json
import os
import subprocess
import sys
import tomllib
from argparse import Namespace
from importlib import resources
from pathlib import Path

import pytest

from conftest import stub_path
from colony import batch, cli, transport, wait

PACKAGE = Path(str(resources.files("colony")))
EXAMPLE = PACKAGE / "colony.toml.example"
HACK = """
[project]
mode = "hack"
name = "demo"
repo = "acme/demo"
checks = "make check"
fast_check = "make fast"
[accounts.ana]
config_dir = "~/ana"
person = "ana"
[accounts.bo]
config_dir = "~/bo"
person = "bo"
[messages]
board = 12
[people]
logins = ["ana", "bo"]
names = { ana = "Ana", bo = "Bo" }
"""
SOLO = """
[project]
mode = "solo"
name = "demo"
repo = "acme/demo"
checks = "make check"
fast_check = "make fast"
[accounts.ana]
config_dir = "~/ana"
person = "ana"
"""
GH_STUB = """#!{python}
import json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
args = sys.argv[1:]
with open(here / "calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\\n")
kind = "poll" if args[:2] == ["api", "-i"] else "-".join(args[:2])
answers = sorted(here.glob(kind + "-*.txt"))
if answers:
    sys.stdout.write(answers[0].read_text())
    answers[0].unlink()
elif kind == "poll":
    sys.stdout.write('HTTP/2.0 304 Not Modified\\r\\nEtag: W/"e1"\\r\\n\\r\\n')
    sys.exit(1)
elif kind == "issue-list":
    sys.stdout.write('[{"number": 5, "title": "Colony: coordination"}]')
else:
    sys.stdout.write("https://github.com/acme/demo/issues/12#issuecomment-9\\n")
"""
NOT_MODIFIED = 'HTTP/2.0 304 Not Modified\r\nEtag: W/"e1"\r\n\r\n'


def load(tmp_path: Path, text: str) -> dict:
    """A colony.toml with this text, loaded as the command line loads it."""
    path = tmp_path / "colony.toml"
    path.write_text(text)
    return cli.load_config(path)


def comment(id, body, issue=7, login="ana", updated="2026-11-05T10:00:00Z"):
    """One issue comment as GitHub's REST API answers it."""
    return {"id": id, "issue_url": f"https://api.github.com/repos/acme/demo/issues/{issue}", "body": body,
            "updated_at": updated, "user": {"login": login}}


def ok(*comments):
    """A 200 answer as `gh api -i` prints it."""
    return f'HTTP/2.0 200 OK\r\nEtag: W/"e1"\r\n\r\n{json.dumps(list(comments))}'


class Gh:
    """The stand-in gh: queue answers per kind of call, then read the calls it got."""

    def __init__(self, bin_dir: Path):
        self.bin, self.count = bin_dir, 0

    def answer(self, *texts: str, kind: str = "poll") -> None:
        for text in texts:
            self.count += 1
            (self.bin / f"{kind}-{self.count:03}.txt").write_text(text, newline="")  # as written, \r\n too

    def calls(self) -> list[list[str]]:
        log = self.bin / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def comments(self) -> list[tuple[str, str]]:
        """Each `gh issue comment` as (issue, body)."""
        return [(call[2], call[call.index("--body") + 1]) for call in self.calls() if call[:2] == ["issue", "comment"]]


@pytest.fixture
def gh(tmp_path, monkeypatch):
    """A temporary HOME, the stand-in gh first on PATH, and no session env. colony.cycle doesn't import, so a lead's
    wait runs no stale-card check."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH_STUB.replace("{python}", sys.executable))
    (bin_dir / "gh").chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", stub_path(bin_dir))
    for key in (cli.SESSION_ENV, cli.PERSON_ENV):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setitem(sys.modules, "colony.cycle", None)
    return Gh(bin_dir)


class Clock:
    """A fake clock whose naps move it on at once, calling `on_nap` first, as the prompt hook would run meanwhile."""

    def __init__(self, on_nap=None, most: int = 50):
        self.t, self.naps, self.on_nap, self.most = 0.0, [], on_nap, most

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.naps.append(seconds)
        if self.on_nap:
            self.on_nap(len(self.naps))
        self.t += seconds
        if len(self.naps) > self.most:
            raise AssertionError("the wait never ended")


def run_wait(config, session, person, monkeypatch, capsys, clock=None):
    """Run `colony wait` as `session` for `person`, and return its exit code and output."""
    monkeypatch.setenv(cli.SESSION_ENV, session)
    monkeypatch.setenv(cli.PERSON_ENV, person)
    code = wait.run(config, Namespace(person=None, waiting_on=None), clock=clock or Clock())
    return code, capsys.readouterr().out


# Each mode's defaults, under colony.toml


def test_a_config_with_no_mode_runs_startup_with_its_own_keys_unchanged(tmp_path):
    own = tomllib.loads(EXAMPLE.read_text())
    config = cli.load_config(EXAMPLE)
    assert "mode" not in own["project"] and config["project"]["mode"] == "startup"
    assert config["gate"] == {**own["gate"], "check": "full", "review": True}
    assert config["messages"] == own["messages"]  # its lead_digest_minutes is startup's 10
    assert config["features"] == dict.fromkeys(("knowledge", "specs", "research", "board", "retro"), True)
    for table in ("budget", "people", "knowledge", "board"):
        assert config[table] == own[table], table


@pytest.mark.parametrize("cut, missing", [("walk = ", "[gate] needs 'walk'"), ("max_rounds", "[gate] needs 'max_rounds'"),
                                          ("lead ", "[roles] lead needs 'model'")])
def test_startup_requires_every_key_it_did_before_modes(tmp_path, cut, missing):
    text = EXAMPLE.read_text()
    assert cut in text
    lines = [line for line in text.splitlines() if not line.startswith(cut)]
    with pytest.raises(cli.ColonyError, match=missing.replace("[", r"\[").replace("]", r"\]")):
        load(tmp_path, "\n".join(lines))


def test_a_hack_config_needs_only_what_setup_asks(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    config = load(tmp_path, HACK)
    project, gate = config["project"], config["gate"]
    assert (project["mode"], project["base"], project["worktrees"]) == ("hack", "main", str(tmp_path / "worktrees"))
    assert (gate["check"], gate["review"], gate["walk"], gate["merge_after_fast_check"]) == ("fast", False, False, True)
    assert config["messages"] == {"lead_digest_minutes": 0, "board": 12}
    assert not any(config["features"].values())
    assert config["roles"]["spec"] == config["roles"]["builder"]  # the mode's roles, and the builder's for spec
    assert config["accounts"]["ana"]["config_dir"] == str(tmp_path / "ana")


def test_the_repos_colony_toml_overrides_any_mode_key(tmp_path):
    config = load(tmp_path, HACK + '[gate]\nmax_rounds = 7\n[roles]\nbuilder = { effort = "low" }\n'
                                   "[features]\nresearch = true\n")
    assert config["gate"]["max_rounds"] == 7 and config["gate"]["check"] == "fast"
    assert config["roles"]["builder"] == {"model": "claude-opus-5-5", "effort": "low"}  # a table merges key by key
    assert config["features"]["research"] and not config["features"]["specs"]
    assert config["people"]["names"] == {"ana": "Ana", "bo": "Bo"}


def test_solo_runs_the_checks_and_a_reviewer_and_walks_only_when_asked(tmp_path):
    config = load(tmp_path, SOLO)
    assert (config["gate"]["check"], config["gate"]["review"], config["gate"]["walk"]) == ("full", True, False)
    assert config["project"]["preset"] == "lean" and not any(config["features"].values())
    assert load(tmp_path, SOLO + "[gate]\nwalk = true\n")["gate"]["walk"] is True


def test_an_unknown_mode_is_refused(tmp_path):
    with pytest.raises(cli.ColonyError, match='mode is "hack", "solo" or "startup", not \'party\''):
        load(tmp_path, HACK.replace('"hack"', '"party"'))


@pytest.mark.parametrize("mode", cli.MODES)
def test_every_mode_file_sets_the_keys_each_mode_sets_its_own_way(mode):
    defaults = tomllib.loads(cli.package_file("modes", f"{mode}.toml"))
    assert defaults["gate"]["check"] in ("fast", "full") and isinstance(defaults["gate"]["review"], bool)
    assert set(defaults["features"]) == set(cli.FEATURES.values())
    assert "mode" not in defaults.get("project", {})  # load_config names the mode
    if mode == "startup":  # startup relaxes no key a colony.toml had to hold before modes
        assert not any(key in defaults.get(table, {}) for table, keys in cli.REQUIRED.items() for key in keys)
        assert "roles" not in defaults


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A git repo to run the command line in, with a temporary HOME."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", stub_path(tmp_path / 'bin'))
    repo = tmp_path / "host"
    (repo / ".colony").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.chdir(repo)
    return repo


@pytest.mark.parametrize("argv, feature", [(["research", "which queue?"], "research"), (["spec", "dark mode"], "specs"),
                                           (["retro", "--name", "b1"], "retro"), (["check-docs"], "knowledge"),
                                           (["board", "init"], "board")])
def test_a_mode_turns_its_commands_off_and_the_repo_turns_them_on(host, capsys, argv, feature):
    (host / ".colony" / "colony.toml").write_text(SOLO)
    assert cli.main([*argv, "--dry-run"] if argv[0] in ("research", "spec", "retro") else argv) == 2
    assert (f"`colony {argv[0]}` is off in solo mode: set {feature} = true under [features] in .colony/colony.toml"
            in capsys.readouterr().err)
    if argv[0] == "research":
        (host / ".colony" / "colony.toml").write_text(SOLO + "[features]\nresearch = true\n")
        assert cli.main([*argv, "--dry-run", "--person", "ana"]) == 0
        assert "You are the researcher for demo." in capsys.readouterr().out


# The gate per mode


def plan(config, tmp_path, review=False) -> str:
    """The dry run of `colony batch` for one card, on Ana's account."""
    args = Namespace(name="b1", card=["11=card/a"], from_branch=None, dry_run=True, repo=str(tmp_path), review=review,
                     person="ana")
    b = batch.Batch.from_args(config, args)
    return batch.plan(b)


def test_hack_gates_on_the_fast_check_alone(tmp_path, gh):
    out = plan(load(tmp_path, HACK), tmp_path)
    commands = out.split("Prompts for round 1:", 1)[0]
    assert "  the fast check, in the background: $ make fast" in commands
    assert "make check" not in commands and "reviewer" not in commands and "walker" not in commands
    assert "--- reviewer" not in out and "--- walker" not in out
    assert "done at the fast check passes, walk pass or skipped" in out
    assert "- Run `make fast` and fix what it reports." in out.split("--- fixer", 1)[1]  # the fixer runs it too


def test_review_adds_one_reviewer_to_the_hack_gate(tmp_path):
    out = plan(load(tmp_path, HACK), tmp_path, review=True)
    assert "  reviewer: $ claude -p '<reviewer prompt>'" in out and "--- reviewer" in out
    assert "done at the fast check passes, open: 0, walk pass or skipped" in out
    assert batch.Batch.from_args(load(tmp_path, HACK), Namespace(
        name="b1", card=["11=card/a"], repo=str(tmp_path), review=False, person="ana")).review is False
    assert cli.build_parser().parse_args(["batch", "--name", "b", "--card", "1=x", "--review"]).review


def test_solo_gates_on_the_checks_and_a_reviewer_and_walks_when_asked(tmp_path):
    out = plan(load(tmp_path, SOLO), tmp_path)
    assert "  checks, in the background: $ make check" in out and "  reviewer: $ " in out
    assert "walker" not in out and "done at checks pass, open: 0, walk pass or skipped" in out
    assert "--- walker" in plan(load(tmp_path, SOLO + "[gate]\nwalk = true\n"), tmp_path)


GIT_ENV = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "Test",
           "GIT_COMMITTER_EMAIL": "t@example.test", "GIT_CONFIG_NOSYSTEM": "1"}
CLAUDE_STUB = """#!/bin/sh
echo "$@" >> "{log}"
echo '{{"total_cost_usd": 0, "duration_ms": 1000, "is_error": false}}'
"""
GH_BATCH_STUB = """#!/bin/sh
printf '%s\\n' "$@" >> "{log}"
case "$1 $2" in
  "issue view") printf '%s' '{{"title": "card", "body": "", "comments": []}}' ;;
  *) echo https://example.test/pull/1 ;;
esac
"""


def test_a_hack_batch_runs_the_fast_check_and_no_agent(tmp_path, monkeypatch, capsys):
    (tmp_path / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in (("claude", CLAUDE_STUB), ("gh", GH_BATCH_STUB)):
        (bin_dir / name).write_text(text.format(log=tmp_path / f"{name}.log"))
        (bin_dir / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    origin, repo = tmp_path / "origin.git", tmp_path / "repo"
    run = lambda cwd, *args: subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: E731
    run(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    run(tmp_path, "init", "-q", "-b", "main", str(repo))
    (repo / "a.txt").write_text("a\n")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "base")
    run(repo, "remote", "add", "origin", str(origin))
    run(repo, "push", "-q", "origin", "main")
    run(repo, "checkout", "-q", "-b", "card/a")
    (repo / "a.txt").write_text("a1\n")
    run(repo, "commit", "-qam", "card")
    config = load(tmp_path, HACK.replace('"make check"', '"false"').replace('"make fast"', '"true"'))
    config["project"]["worktrees"] = str(tmp_path / "wt")
    args = Namespace(name="b1", card=["11=card/a"], from_branch=None, dry_run=False, repo=str(repo), review=False)
    assert batch.run_batch(config, args) == 0
    assert "done in round 1. https://example.test/pull/1" in capsys.readouterr().out
    assert not (tmp_path / "claude.log").exists()  # no reviewer, walker or fixer ran
    state = json.loads((tmp_path / "wt" / "demo-batch-b1" / ".colony" / "reports" / "b1" / "state.json").read_text())
    assert [(r["checks_cmd"], r["checks"], r["open"], r["walk"]) for r in state["rounds"]] == [
        ("true", "pass", "skipped", "skipped")]


# Addresses


def startup_people() -> dict:
    """A startup config whose people have GitHub logins apart from their names."""
    return {"project": {"name": "demo", "repo": "acme/demo"},
            "people": {"logins": ["ana-gh", "bo-gh"], "names": {"ana-gh": "Ana", "bo-gh": "Bo"}}}


@pytest.mark.parametrize("line, at_once", [
    ("@ana-gh can you look at the export? (from bo-lead)", False),
    ("@ana-gh urgent: main is red (from bo-lead)", True),
    ("@ana-gh can you look?", True),  # a person's line
    ("thanks, @ANA-gh, merged (from bo-lead)", False),
    ("@all I merge dev at 15:00 (from bo-lead)", False),
    ("**@all** freeze: only fixes from now (from bo-lead)", False),
])
def test_the_lead_takes_its_persons_login_and_all(gh, line, at_once):
    lead = wait.lead_session(startup_people(), "ana-lead")
    assert lead.logins == {"ana-gh"}
    assert wait.taken(line, lead, "5") == [(wait.MARKUP.sub("", line), at_once)]


@pytest.mark.parametrize("line", [
    "@bo-gh can you look? (from ana-lead)",  # another person's
    "@ana is not a login here (from bo-lead)",  # a person's name is not their login outside hack mode
    "write to ana-gh@example.com (from bo-lead)",  # an email, not a mention
    "@all from me (from ana-lead)",  # its own line
])
def test_the_lead_leaves_a_line_for_someone_else(gh, line):
    assert wait.taken(line, wait.lead_session(startup_people(), "ana-lead"), "5") == []


@pytest.mark.parametrize("line, taken", [
    ("@all stop and push what you have (from lead)", True),
    ("@all stop and push what you have (from bo-lead)", False),  # a builder takes work from its lead alone
    ("@all stop and push what you have", False),
    ("@ana-gh can you look? (from lead)", False),  # a person's line goes to their lead
])
def test_a_builder_takes_all_from_its_lead_alone(gh, line, taken):
    builder = wait.builder_session(startup_people(), "builder-1")
    assert bool(wait.taken(line, builder, "41")) is taken


def test_in_hack_mode_the_leads_are_peers_and_a_builder_takes_its_own_leads_lines(tmp_path, gh):
    config = load(tmp_path, HACK)
    lead = wait.lead_session(config, "ana-lead")
    assert lead.names == {"ana-lead"} and lead.logins == {"ana"}
    assert wait.taken("[Bo's Claude] for lead: who takes the export? (from bo-lead)", lead, "12") == []
    post = "[Bo's Claude] @ana can the login form return the name too? (from bo-lead)"
    assert wait.taken(post, lead, "12") == [(post, False)]
    builder = wait.builder_session(config, "builder-1", "ana")
    start = "[Ana's Claude] for builder-1: start the login form (from ana-lead)"
    assert wait.taken(start, builder, "12") == [(start, True)]
    for other in ("[Bo's Claude] for builder-1: start the export (from bo-lead)",
                  "for builder-1: start the export (from lead)"):
        assert wait.taken(other, builder, "12") == []


# Posting with @login, and hack's board


def test_say_and_post_take_at_login_and_at_all(gh, monkeypatch, capsys):
    config = startup_people()
    (Path(os.environ["HOME"]) / ".colony" / "demo").mkdir(parents=True)
    (Path(os.environ["HOME"]) / ".colony" / "demo" / "lead-coordination.json").write_text("5")
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    monkeypatch.setenv(cli.PERSON_ENV, "bo")
    assert wait.say(config, Namespace(person=None, to="@Ana-GH", sentence="can you  review #12?")) == 0
    monkeypatch.setenv(cli.SESSION_ENV, "builder-2")
    assert wait.post(config, Namespace(card=41, to="@all", sentence="main is red", urgent=True)) == 0
    assert capsys.readouterr().out.splitlines() == ["#5 @ana-gh can you review #12? (from bo-lead)",
                                                    "#41 @all urgent: main is red (from builder-2)"]
    assert gh.comments() == [("5", "@ana-gh can you review #12? (from bo-lead)"),
                             ("41", "@all urgent: main is red (from builder-2)")]
    # Ana's lead takes both: an agent's line waits for the digest, and an urgent one doesn't.
    lead = wait.lead_session(config, "ana-lead")
    assert wait.taken(gh.comments()[0][1], lead, "5") == [(gh.comments()[0][1], False)]
    assert wait.taken(gh.comments()[1][1], lead, "41") == [(gh.comments()[1][1], True)]


@pytest.mark.parametrize("command, to, error", [
    ("say", "@nobody", "@nobody names no login colony.toml knows"),
    ("say", "@bo-gh", "@bo-gh is your own person"),
    ("say", "@", "@ is not @<login> or @all"),
    ("post", "@nobody", "@nobody names no login colony.toml knows"),
])
def test_an_unknown_login_or_your_own_is_refused(gh, monkeypatch, command, to, error):
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    monkeypatch.setenv(cli.PERSON_ENV, "bo")
    args = Namespace(person=None, card=41, to=to, sentence="hello", urgent=False)
    with pytest.raises(cli.ColonyError, match=error):
        getattr(wait, command)(startup_people(), args)
    assert gh.calls() == []


def test_outside_hack_mode_a_post_still_needs_its_card(gh, monkeypatch):
    monkeypatch.setenv(cli.SESSION_ENV, "builder-2")
    with pytest.raises(cli.ColonyError, match="post needs the card first"):
        wait.post(startup_people(), Namespace(card=None, to="lead", sentence="done", urgent=False))
    assert cli.build_parser().parse_args(["post", "lead", "done"]).card is None
    assert cli.build_parser().parse_args(["post", "41", "lead", "done"]).card == 41


def test_in_hack_mode_every_line_goes_to_the_board_with_its_prefix(tmp_path, gh, monkeypatch, capsys):
    config = load(tmp_path, HACK)
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    assert wait.post(config, Namespace(card=None, to="builder-1", sentence="start: the login form", urgent=False)) == 0
    assert wait.say(config, Namespace(person=None, to="@bo", sentence="can /api/login return the name?")) == 0
    assert wait.say(config, Namespace(person=None, to="bo-lead", sentence="I merge in 5 minutes")) == 0
    monkeypatch.setenv(cli.SESSION_ENV, "builder-1")
    assert wait.post(config, Namespace(card=41, to="lead", sentence="done, pushed", urgent=False)) == 0
    lines = ["for builder-1: start: the login form (from ana-lead)", "@bo can /api/login return the name? (from ana-lead)",
             "for bo-lead: I merge in 5 minutes (from ana-lead)", "for ana-lead: done, pushed (#41) (from builder-1)"]
    assert capsys.readouterr().out.splitlines() == [f"#12 {line}" for line in lines]
    assert gh.comments() == [("12", f"[Ana's Claude] {line}") for line in lines]
    assert not any(call[:2] in (["issue", "list"], ["issue", "create"]) for call in gh.calls())  # no coordination


def test_hack_mode_needs_the_board_number(tmp_path, gh, monkeypatch):
    config = load(tmp_path, HACK.replace("board = 12", ""))
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    with pytest.raises(cli.ColonyError, match=r"set \[messages\] board to its number"):
        wait.post(config, Namespace(card=None, to="builder-1", sentence="start: the login form", urgent=False))
    assert gh.calls() == []


# hack's wait


def test_a_hack_lead_reads_the_board_at_once_and_opens_no_coordination_issue(tmp_path, gh, monkeypatch, capsys):
    config = load(tmp_path, HACK)
    post = "[Bo's Claude] @ana can the login form return the name? (from bo-lead)"
    gh.answer(ok(comment(1, post, issue=12, login="bo"), comment(2, "[Bo's Claude] @bo note to self (from bo-lead)")))
    code, out = run_wait(config, "lead", "ana", monkeypatch, capsys)
    assert code == 0 and out == f"#12 {post}\n"
    assert [call[:2] for call in gh.calls()] == [["api", "-i"]]


def test_a_hack_builder_takes_its_own_leads_lines_alone(tmp_path, gh, monkeypatch, capsys):
    config = load(tmp_path, HACK)
    mine = "[Ana's Claude] for builder-1: start the login form (from ana-lead)"
    gh.answer(ok(comment(1, "[Bo's Claude] for builder-1: start the export (from bo-lead)", issue=12, login="bo"),
                 comment(2, mine, issue=12)))
    assert run_wait(config, "builder-1", "ana", monkeypatch, capsys) == (0, f"#12 {mine}\n")


# The unread cache


LINE_1 = "for lead: done, builder-1/7 pushed (from builder-1)"
LINE_2 = "for lead: which blue? I'm going with the brand one (from builder-2)"
STARTUP_WAIT = {"project": {"repo": "acme/demo", "name": "demo"}, "messages": {"lead_digest_minutes": 1}}


def state_file(home: Path, session: str = "lead") -> Path:
    return home / ".colony" / "demo" / f"{session}.json"


def test_the_wait_lists_each_gathered_line_in_unread_for_the_hook(gh, tmp_path, monkeypatch, capsys):
    seen = []
    clock = Clock(on_nap=lambda n: seen.append(json.loads(state_file(tmp_path).read_text())))
    wait.write_json(tmp_path / ".colony" / "demo" / "lead-waiting.json", [99])  # a batch runs, so LINE_1 waits
    gh.answer(ok(comment(1, LINE_1, login="ana-gh"), {**comment(2, LINE_2, login="ana-gh"),
                                                       "html_url": "https://github.com/acme/demo/issues/7#c2"}))
    code, out = run_wait(STARTUP_WAIT, "lead", "ana", monkeypatch, capsys, clock)
    assert code == 0 and out.splitlines() == [f"#7 {LINE_1}", f"#7 {LINE_2}"]
    assert seen[0]["unread"] == [
        {"card": 7, "author": "ana-gh", "body": LINE_1, "url": "https://github.com/acme/demo/issues/7#issuecomment-1"},
        {"card": 7, "author": "ana-gh", "body": LINE_2, "url": "https://github.com/acme/demo/issues/7#c2"}]
    assert isinstance(seen[0]["polled_at"], float)
    after = json.loads(state_file(tmp_path).read_text())
    assert after["unread"] == [] and after["pending"] == []  # printed lines are read


def test_a_line_the_hook_showed_never_prints_again(gh, tmp_path, monkeypatch, capsys):
    def hook(nap):
        if nap == 1:  # the person sends a prompt: the hook prints the cache and empties it
            state = json.loads(state_file(tmp_path).read_text())
            state["unread"] = []
            state_file(tmp_path).write_text(json.dumps(state))

    wait.write_json(tmp_path / ".colony" / "demo" / "lead-waiting.json", [99])  # a batch runs, so LINE_1 waits
    gh.answer(ok(comment(1, LINE_1)), ok(comment(2, LINE_2, updated="2026-11-05T10:01:00Z")))
    code, out = run_wait(STARTUP_WAIT, "lead", "ana", monkeypatch, capsys, Clock(on_nap=hook))
    assert code == 0 and out == f"#7 {LINE_2}\n"


def test_lines_the_hook_showed_between_waits_never_print(gh, tmp_path, monkeypatch, capsys):
    wait.write_json(tmp_path / ".colony" / "demo" / "lead-waiting.json", [99])  # a batch runs, so LINE_1 waits
    gh.answer(ok(comment(1, LINE_1)))
    with pytest.raises(AssertionError, match="never ended"):
        run_wait(STARTUP_WAIT, "lead", "ana", monkeypatch, capsys, Clock(most=1))
    state = json.loads(state_file(tmp_path).read_text())
    assert state["pending"] == [[f"#7 {LINE_1}", False]] and state["listed"] == [f"#7 {LINE_1}"]
    state["unread"] = []  # the hook showed it while no wait ran
    state_file(tmp_path).write_text(json.dumps(state))
    gh.answer(ok(comment(2, "for lead: urgent: main is red (from builder-2)", updated="2026-11-05T10:01:00Z")))
    code, out = run_wait(STARTUP_WAIT, "lead", "ana", monkeypatch, capsys)
    assert code == 0 and out == "#7 for lead: urgent: main is red (from builder-2)\n"


def test_the_wait_and_the_prompt_hook_read_one_session(tmp_path, gh, monkeypatch):
    hack = load(tmp_path, HACK)
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    args = Namespace(person=None)
    assert wait.session(hack, args, "builder-1").leads == {"ana-lead"}
    assert wait.session(hack, args, "lead").names == {"ana-lead"}
    assert wait.session(startup_people(), args, "builder-1").leads == {"lead"}
    assert wait.session(startup_people(), args, "lead").names == {"lead", "ana-lead"}
