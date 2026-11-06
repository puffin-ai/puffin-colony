"""Tests for hack mode's content: the prompt hook and its install, the AGENTS.md and board issue templates, the hack
core, and setup's mode step with its hack and solo branches."""
import argparse
import io
import json
import re
import subprocess
import sys
import time
from importlib import resources
from pathlib import Path

import pytest

from colony import cli, guards, wait

PACKAGE = Path(str(resources.files("colony")))
HACK = PACKAGE / "templates" / "hack"
CORE = PACKAGE / "presets" / "hack" / "core.md"
SETUP = cli.fill_names(cli.package_file("prompts", "setup.md"))
PLACEHOLDER = re.compile(r"\{([A-Za-z_][\w-]*)\}")
CONFIG = {"project": {"name": "demo", "repo": "acme/demo", "base": "main", "mode": "hack"},
          "accounts": {"ana": {"config_dir": "~/.claude", "person": "ana"}}, "messages": {"board": 7},
          "people": {"logins": ["ana", "ben"], "names": {"ana": "Ana", "ben": "Ben"}}}


def comment(number: int, body: str, issue: int = 7, author: str = "ben") -> dict:
    at = f"2026-11-05T10:00:{number % 60:02d}Z"
    return {"id": number, "body": body, "user": {"login": author}, "updated_at": at,
            "issue_url": f"https://api.github.com/repos/acme/demo/issues/{issue}",
            "html_url": f"https://github.com/acme/demo/issues/{issue}#issuecomment-{number}"}


class Clock:
    """The time the hook reads, which a test moves by hand."""

    def __init__(self, now: float):
        self.now = now

    def __call__(self) -> float:
        return self.now


class Lead:
    """A Colony lead's prompt hook: its state file, the clock it reads, and the GitHub reads it made."""

    def __init__(self, path: Path, clock: Clock, monkeypatch):
        self.path, self.clock, self.reads, self.monkeypatch = path, clock, [], monkeypatch

    def github(self, *answers) -> None:
        """GitHub answers each read with the next (status, etag, comments), and the reads are logged."""
        queue = list(answers)

        def gh_get(path, etag):
            self.reads.append((path, etag))
            return queue.pop(0)
        self.monkeypatch.setattr(wait, "gh_get", gh_get)

    def state(self) -> dict:
        return json.loads(self.path.read_text())

    def hook(self, config: dict = CONFIG) -> int:
        """Run the hook as Claude Code does, with the prompt's event on stdin."""
        self.monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": "what next?"})))
        return guards.unread(config, argparse.Namespace())


@pytest.fixture
def session(tmp_path, monkeypatch) -> Lead:
    """Ana's lead, with HOME in the temporary folder, the clock at 1000, and a GitHub that fails the test when read
    before the test says what it answers."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    monkeypatch.setenv(cli.PERSON_ENV, "ana")
    clock = Clock(1000.0)
    monkeypatch.setattr(time, "time", clock)

    def no_network(path, etag):
        raise AssertionError(f"the hook read GitHub: {path}")
    monkeypatch.setattr(wait, "gh_get", no_network)
    return Lead(wait.state_path("demo", "lead"), clock, monkeypatch)


LINE = "[Ben's Claude] @all the API returns the user's name now"
ENTRY = {"card": 7, "author": "ben", "body": LINE, "url": "https://github.com/acme/demo/issues/7#issuecomment-41"}


def test_the_hook_prints_the_unread_cache_and_empties_it_with_no_network_call(session, capsys):
    gathered = {"since": "2026-11-05T09:00:00Z", "etag": '"e9"', "polled_at": 990.0, "unread": [ENTRY],
                "pending": [[f"#7 {LINE}", True]], "listed": [f"#7 {LINE}"]}
    session.path.parent.mkdir(parents=True)
    session.path.write_text(json.dumps(gathered))
    assert session.hook() == 0
    assert capsys.readouterr().out == f"Unread lines for lead, which colony wait won't print again:\n#7 {LINE}\n"
    # the running wait owns the rest of the file, and drops its own copy of the line when it next reads it
    assert session.state() == {**gathered, "unread": []}
    assert session.hook() == 0
    assert capsys.readouterr().out == ""


def test_the_wait_drops_a_line_the_hook_showed(session, capsys):
    session.path.parent.mkdir(parents=True)
    state = {"since": "2026-11-05T09:00:00Z", "polled_at": 990.0, "unread": [ENTRY],
             "pending": [[f"#7 {LINE}", True]], "listed": [f"#7 {LINE}"]}
    session.path.write_text(json.dumps(state))
    session.hook()
    wait.drop_shown(session.path, state, set(state["listed"]))
    assert state["pending"] == [] and state["unread"] == []


def test_with_no_wait_running_the_hook_reads_github_itself_at_most_once_per_30_seconds(session, capsys):
    first = [comment(41, LINE), comment(42, "for ana-lead: can you review #12? (from ben-lead)", issue=12),
             comment(43, "[Ben's Claude] @carl the schema moved"), comment(44, "for builder-2: start (from lead)"),
             comment(45, "[Ben's Codex] @ana the form needs a name field")]
    session.github((200, '"e1"', first), (304, '"e1"', []))
    assert session.hook() == 0
    assert capsys.readouterr().out == ("Unread lines for lead, which colony wait won't print again:\n"
                                       f"#7 {LINE}\n#12 for ana-lead: can you review #12? (from ben-lead)\n"
                                       "#7 [Ben's Codex] @ana the form needs a name field\n")
    path, etag = session.reads[0]
    assert path.startswith("repos/acme/demo/issues/comments?since=") and etag is None
    state = session.state()
    assert (state["unread"], state["pending"], state["listed"]) == ([], [], [])
    assert state["etag"] == '"e1"' and "polled_at" not in state  # the hook's read never passes for a running wait
    session.clock.now = 1029
    assert session.hook() == 0 and len(session.reads) == 1
    session.clock.now = 1030
    assert session.hook() == 0 and session.reads[1] == (
        "repos/acme/demo/issues/comments?since=2026-11-05T10:00:45Z&sort=updated&direction=asc&per_page=100", '"e1"')
    assert capsys.readouterr().out == ""
    # a line the hook showed never prints again in a later wait
    session.github((200, '"e2"', first))
    seen_again = {**session.state(), "pending": []}
    wait.poll("acme/demo", seen_again, wait.session(CONFIG, argparse.Namespace(), "lead"))
    assert seen_again["pending"] == []


def test_a_running_wait_keeps_the_hook_off_github(session):
    session.path.parent.mkdir(parents=True)
    session.path.write_text(json.dumps({"since": "2026-11-05T09:00:00Z", "polled_at": 1000.0 - 59}))
    assert session.hook() == 0  # no_network would raise
    session.path.write_text(json.dumps({"since": "2026-11-05T09:00:00Z", "polled_at": 1000.0 - 61}))
    session.github((304, None, []))
    assert session.hook() == 0 and len(session.reads) == 1


def test_a_builders_hook_takes_only_the_lines_its_lead_sent_it(session, capsys, monkeypatch):
    monkeypatch.setenv(cli.SESSION_ENV, "builder-2")
    session.github((200, None, [comment(1, "for builder-2: start card 41 (from lead)", issue=41),
                                comment(2, "for builder-3: start card 42 (from lead)", issue=42),
                                comment(3, "for builder-2: I'm not your lead (from builder-3)", issue=41)]))
    assert session.hook({**CONFIG, "project": {**CONFIG["project"], "mode": "startup"}}) == 0
    assert capsys.readouterr().out == ("Unread lines for builder-2, which colony wait won't print again:\n"
                                       "#41 for builder-2: start card 41 (from lead)\n")
    assert wait.state_path("demo", "builder-2").exists() and not session.path.exists()


def test_a_failed_read_never_stops_the_prompt_and_waits_30_seconds_to_try_again(session, capsys):
    def refuse(path, etag):
        session.reads.append(path)
        raise wait.GhError("GitHub answered 401 (run: gh auth login)")
    session.monkeypatch.setattr(wait, "gh_get", refuse)
    assert session.hook() == 0
    out, err = capsys.readouterr()
    assert out == "" and "GitHub was not read" in err and "401" in err
    assert session.hook() == 0 and len(session.reads) == 1
    session.path.write_text("{broken")
    session.clock.now = 2000
    assert session.hook() == 0 and len(session.reads) == 2  # a broken state file starts afresh


def test_outside_a_colony_session_the_hook_does_nothing(session, capsys, monkeypatch):
    monkeypatch.delenv(cli.SESSION_ENV)
    assert session.hook() == 0
    assert capsys.readouterr() == ("", "") and not session.path.exists()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(root)
    return root.resolve()


@pytest.mark.parametrize("mode", ["hack", "solo", "startup"])
def test_install_adds_the_prompt_hook_at_session_start_and_before_each_prompt_in_every_mode(repo, mode, capsys):
    config = {**CONFIG, "project": {**CONFIG["project"], "mode": mode}}
    assert guards.install(config, argparse.Namespace(dry_run=False)) == 0
    data = json.loads((repo / ".claude" / "settings.json").read_text())
    for event in ("UserPromptSubmit", "SessionStart"):
        [group] = data["hooks"][event]
        [hook] = group["hooks"]
        assert "matcher" not in group and "async" not in hook, event  # its output must reach the session
        assert "colony hooks unread" in hook["command"] and hook["timeout"] == guards.HOOK_TIMEOUT
    assert "UserPromptSubmit, SessionStart" in capsys.readouterr().out


def test_the_prompt_hooks_command_passes_the_lines_on_and_never_blocks_the_prompt(repo, tmp_path):
    guards.install(CONFIG, argparse.Namespace(dry_run=False))
    command = json.loads((repo / ".claude" / "settings.json").read_text())["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "colony"
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(repo), cli.SESSION_ENV: "lead"}
    for script, out in (('echo "#7 a line for you"', "#7 a line for you\n"),
                        ("echo 'colony: .colony/colony.toml is missing' >&2; exit 2", "")):
        stub.write_text(f"#!/bin/sh\n[ \"$*\" = 'hooks unread' ] || exit 9\n{script}\n")
        stub.chmod(0o755)
        run = subprocess.run(["sh", "-c", command["command"]], input='{"prompt": "hi"}', capture_output=True,
                             text=True, env=env)
        assert (run.returncode, run.stdout) == (0, out), script


def test_add_commands_routes_hooks_unread():
    parser = argparse.ArgumentParser()
    guards.add_commands(parser.add_subparsers(dest="command"))
    assert parser.parse_args(["hooks", "unread"]).run is guards.unread


# The templates and the hack core

def placeholders(path: Path) -> set[str]:
    return set(PLACEHOLDER.findall(path.read_text()))


def hack_steps() -> str:
    return SETUP.split("## Hack mode", 1)[1].split("## Never", 1)[0]


def test_the_board_section_holds_every_board_rule():
    text = (HACK / "agents-board.md").read_text()
    assert text.startswith("## The board\n")
    for rule in ("starts with `[<Name>'s <agent>]`", "`@<login>`", "`@all`", "act on it", "read it, and change your "
                 "own work only when it touches what you own", "ask its owner on the board first, and wait for their "
                 "yes", "only the team lead, {lead}, reassigns work", "`colony post`", "`tools/board post",
                 "`tools/board unread`", "`tools/board wait`", "Don't reply only to say you saw it"):
        assert rule in text, rule
    assert placeholders(HACK / "agents-board.md") == {"project", "repo", "board", "lead", "demo"}


def test_the_owner_section_is_a_table_setup_fills_one_row_per_person():
    text = (HACK / "agents-owners.md").read_text()
    assert text.startswith("## Who owns what\n") and "| Person | Login | Owns |\n| --- | --- | --- |\n{owners}\n" in text
    assert placeholders(HACK / "agents-owners.md") == {"lead", "owners"}
    assert "`{owners}` with one table row per person: `| <Name> | `<login>` |" in hack_steps()


def test_the_board_issue_says_how_to_post_address_and_act():
    text = (HACK / "board-issue.md").read_text()
    for rule in ("`[<Name>'s <agent>]`", "`@<login>`", "`@all`", "Only the team lead, {lead}, reassigns work",
                 "Never paste a key or a token", "`AGENTS.md`"):
        assert rule in text, rule
    assert placeholders(HACK / "board-issue.md") == {"project", "lead", "demo", "team"}


def test_setup_fills_every_placeholder_the_hack_files_hold():
    steps = hack_steps()
    for path in [*HACK.glob("*.md"), CORE]:
        for name in placeholders(path):
            assert f"`{{{name}}}`" in steps, (path.name, name)


def test_the_hack_core_is_about_300_words_of_honesty_ownership_board_duties_and_the_fast_check():
    text = CORE.read_text()
    words = [word for word in text.split() if re.search(r"[A-Za-z]", word)]
    assert 250 <= len(words) <= 350, len(words)
    for line in ("Report a failure as a failure", "Quote the output behind every success claim", "Never weaken a check",
                 "Keep secrets out of output", "Add, remove or upgrade no dependency", "spend no money",
                 "the owner table", "ask its owner on the board", "Only the team lead reassigns work",
                 "`@all`", "`tools/board unread`", "Start with `[<Name>'s <agent>]`", "Run the fast check, `{fast_check}`",
                 "Merge only on a pass", "`colony merge <branch>`", "Never force-push"):
        assert line in text, line
    assert placeholders(CORE) == {"project", "base", "fast_check"}


# Setup's mode step and its branches

def test_setup_asks_the_mode_first_with_a_line_for_each_and_startup_by_default():
    first = SETUP.split("## The mode, first", 1)[1].split("## 1. ", 1)[0]
    assert SETUP.index("## The mode, first") < SETUP.index("## 1. Read the repo")
    for mode in ("hack", "solo", "startup"):
        assert len(re.findall(rf"^    - {mode}: .+$", first, re.M)) == 1, mode
    assert "Default: startup." in first and 'write `mode = "<mode>"`' in first
    for branch in ("- `startup`: steps 1 to 9 below, exactly as written.", '- `solo`: "Solo mode"', '- `hack`: "Hack mode"'):
        assert branch in first, branch
    assert SETUP.index("## 9. ") < SETUP.index("## Solo mode") < SETUP.index("## Hack mode") < SETUP.index("## Never")


def test_the_hack_branch_asks_only_the_hack_questions():
    asked = hack_steps().split("2. **Ask everything in one message.**", 1)[1].split("3. **", 1)[0]
    questions = re.findall(r"^   (\d)\. (.+)$", asked, re.M)
    assert [number for number, _ in questions] == ["1", "2", "3", "4", "5"]
    for (_, question), words in zip(questions, (("GitHub login and name", "team lead"), ("owns which folders",),
                                                ("Default: `main`",), ("merge", "fast check", "Default: yes"),
                                                ("demo",))):
        assert all(word in question for word in words), question
    assert "yes-or-no list" not in hack_steps()


def test_the_hack_branch_opens_and_pins_the_board_then_writes_the_config_agents_md_the_script_and_the_hooks():
    steps = hack_steps()
    order = ['--title "Board: <project>"', "gh issue pin <number>", 'mode = "hack"', "merge_after_fast_check = true",
             "board = <the board issue", "names = { <login>", "presets/hack/core.md", "templates/hack/agents-board.md",
             "templates/hack/agents-owners.md", "scripts/board` to `tools/board`", "chmod +x tools/board",
             "colony hooks install", "chore: set up Puffin Colony in hack mode"]
    at = [steps.find(text) for text in order]
    assert -1 not in at, [text for text, i in zip(order, at) if i == -1]
    assert at == sorted(at)
    assert "gh issue create --repo <owner/name>" in steps and "--body-file" in steps
    assert "templates/hack/board-issue.md" in steps
    for skipped in ("knowledge vault", "specs", "card board", "retro"):
        assert skipped in steps.split("\n\n", 2)[1], skipped


def test_the_solo_branch_writes_lean_rules_and_skips_knowledge_the_board_and_specs():
    solo = SETUP.split("## Solo mode", 1)[1].split("## Hack mode", 1)[0]
    for line in ("`lean` (the default)", 'mode = "solo"', "Write no `[knowledge]` or `[board]` table",
                 "skip the spec and researcher briefs", "**Step 6:** skip it.", "skip the tools and the board",
                 "install the hooks"):
        assert line in solo, line


def test_setups_never_list_allows_what_hack_writes():
    never = SETUP.split("## Never", 1)[1]
    assert "the board and owner sections at the end of the top `AGENTS.md`" in never and "`tools/board`" in never
    assert "Post or comment on the board issue" in never


def test_the_hack_files_ship_in_an_installed_package():
    import tomllib

    data = tomllib.loads((PACKAGE.parent / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["colony"]
    shipped = {path for pattern in data for path in PACKAGE.glob(pattern) if path.is_file()}
    hack = [*HACK.glob("*.md"), CORE, PACKAGE / "scripts" / "board"]
    assert len(hack) == 5 and [path.name for path in hack if path not in shipped] == []


def test_the_config_setups_hack_branch_writes_loads_over_the_hack_defaults(tmp_path):
    block = hack_steps().split("4. **Write the config.**", 1)[1].split("   Write one", 1)[0]
    text = "\n".join(line[7:] for line in block.splitlines() if line.startswith("       "))
    for old, new in (("<short name>", "app"), ("<owner/name>", "acme/app"), ("<question 3>", "main"),
                     ("<the fast check again: hack's gate runs it alone>", "npm test"), ("<the fast check>", "npm test"),
                     ("<the install command>", "npm ci"), ("<a sibling folder of the clone>", "~/worktrees"),
                     ("<the board issue's number>", "12"), ('["<login>", "<login>"]', '["ana", "ben"]'),
                     ('{ <login> = "<Name>", <login> = "<Name>" }', '{ ana = "Ana", ben = "Ben" }'),
                     ("[accounts.<login>]", "[accounts.ana]"), ('"<login>"', '"ana"')):
        assert old in text, old
        text = text.replace(old, new)
    assert "<" not in text, text
    path = tmp_path / "colony.toml"
    path.write_text(text)
    config = cli.load_config(path)
    assert cli.mode(config) == "hack" and config["messages"]["board"] == 12
    assert config["gate"]["merge_after_fast_check"] is True and config["people"]["names"] == {"ana": "Ana", "ben": "Ben"}
    assert (PACKAGE / "presets" / config["project"]["preset"] / "core.md") == CORE
    assert wait.display_name(config, "ana") == "Ana"


# The playbook's Hack section, which a hack lead and its builders follow instead of Lead and Builder

PLAYBOOK = (PACKAGE / "playbook.md").read_text()
REPO = PACKAGE.parent


def playbook_section(name: str) -> str:
    """One `## <name>` section of the playbook, with its subsections, up to the next `## `."""
    start = PLAYBOOK.index(f"\n## {name}\n")
    end = PLAYBOOK.find("\n## ", start + 1)
    return PLAYBOOK[start:end if end != -1 else None]


def test_the_lead_and_builder_sections_send_a_hack_session_to_the_hack_section():
    for name in ("Lead", "Builder"):
        assert "In hack mode, follow the Hack section instead." in playbook_section(name)


def test_the_hack_section_covers_the_board_the_lead_and_the_builder_without_cards():
    hack = playbook_section("Hack")
    for part in ("### The board", "### Hack lead", "### Hack builder"):
        assert part in hack
    for rule in ("`colony post <to> \"<sentence>\"`, with no card number", "`<login>-lead`", "`@all`",
                 "ask its owner on the board", "Only the team lead reassigns work", "`colony open <name>`",
                 "`colony merge <login>/<task>`", "never with `git add -A`", "never force-push", "`{fast_check}`",
                 "origin/{base}", "keep `colony wait` running", "`@all freeze: only fixes from now`"):
        assert rule in hack, rule
    for startup_only in ("gh issue create", "colony board set", "colony tier", "colony spec", "colony retro"):
        assert startup_only not in hack, startup_only


def test_the_hack_section_holds_only_the_placeholders_setup_fills_in_the_playbook():
    assert set(PLACEHOLDER.findall(playbook_section("Hack"))) <= {"base", "fast_check"}


def test_a_hack_lead_and_builder_open_on_the_hack_section(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    hack = {"project": {"mode": "hack"}}
    assert cli.section(hack, "Lead") == "Hack" and cli.section({"project": {}}, "Lead") == "Lead"
    assert cli.builder_prompt("builder-1", hack) == \
        "Read .colony/playbook.md, Hack section. You are builder-1. Start the wait."
    assert cli.builder_prompt("builder-1", {"project": {"mode": "solo"}}).startswith(
        "Read .colony/playbook.md, Builder section.")


def test_the_docs_say_board_unread_prints_every_new_post_and_marks_yours():
    script = (PACKAGE / "scripts" / "board").read_text()
    assert "every post by others since your last look, marking the ones for you" in script
    assert '[ "$flag" = you ] && mark=", for you"' in script
    for doc in ("docs/commands.md", "docs/hackathon.md"):
        text = (REPO / doc).read_text()
        assert ("| `tools/board unread` | Prints every post by others since your last look, and marks the ones for "
                "you `, for you`. |") in text, doc
        assert "Prints the posts addressed to you that you haven't seen" not in text, doc
        assert "Prints the posts for you that you haven't seen" not in text, doc


def test_the_playbook_says_subagents_are_for_speed_searches_and_browser_checks():
    section = playbook_section("Subagents")
    for use in ("**Speed.**", "in parallel", "**Searches.**", "**Browser checks.**"):
        assert use in section, use
    builder = (PACKAGE / "skills" / "colony-builder" / "SKILL.md").read_text()
    assert "start no subagents" not in builder and "Subagents section" in builder


def test_the_builder_section_keeps_builders_fast_without_dropping_a_required_test():
    builder = playbook_section("Builder")
    for rule in ("one test per done-when result", "Run `{fast_check}` once", "post the done line at once",
                 "`predicted:`", "A bug fix still carries its regression test",
                 "a test the repo's own rules demand still goes in"):
        assert rule in builder, rule
