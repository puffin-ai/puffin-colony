"""Tests for `colony step`: steps only a person can take, tested before they're handed over, kept as comments on the
code host's `Colony: person steps` issue, and saying who does each one. GitHub is an in-process stand-in that keeps
issues and comments and logs each call, so nothing reaches the network."""
import json
import re
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from colony import cli, steps, wait

CONFIG = """
[project]
name = "demo"
repo = "acme/demo"
base = "main"
worktrees = "{worktrees}"
checks = "false"
[people]
logins = ["ana-gh", "bob"]
names = {{ "ana-gh" = "Ana" }}
[accounts.ana]
config_dir = "~/.claude"
person = "ana"
[roles]
lead = {{ model = "m", effort = "high" }}
builder = {{ model = "m", effort = "medium" }}
reviewer = {{ model = "m", effort = "high" }}
walker = {{ model = "m", effort = "medium" }}
fixer = {{ model = "m", effort = "medium" }}
[gate]
rubric = ["bugs"]
max_rounds = 5
walk = false
[budget]
provider_dollars = 0
{extra}
"""


class GitHub:
    """A stand-in for gh: the repo's issues, each issue's comments, the signed-in login, and every call."""

    def __init__(self):
        self.issues: list[dict] = []
        self.comments: dict[int, list[dict]] = {}
        self.calls: list[tuple] = []
        self.login = "ana-gh"
        self.next_id = 100

    def issue(self, number: int, title: str) -> None:
        self.issues.append({"number": number, "title": title})
        self.comments.setdefault(number, [])

    def comment(self, number: int, body: str) -> str:
        self.next_id += 1
        url = f"https://github.com/acme/demo/issues/{number}#issuecomment-{self.next_id}"
        self.comments.setdefault(number, []).append({"id": self.next_id, "body": body, "html_url": url})
        return url

    def __call__(self, *args: str) -> str:
        self.calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps(self.issues)
        if args[:2] == ("issue", "create"):
            number = 7 + len(self.issues)
            self.issue(number, args[args.index("--title") + 1])
            return f"https://github.com/acme/demo/issues/{number}\n"
        if args[:2] == ("issue", "comment"):
            return self.comment(int(args[2]), args[args.index("--body") + 1]) + "\n"
        if args[:2] == ("api", "user"):
            return f"{self.login}\n"
        if args[:3] == ("api", "-X", "PATCH"):
            found = int(args[3].rsplit("/", 1)[1])
            for comment in (c for listed in self.comments.values() for c in listed if c["id"] == found):
                comment["body"] = args[args.index("-f") + 1].removeprefix("body=")
            return "{}"
        if args[0] == "api":
            number = int(re.search(r"issues/(\d+)/comments", args[1])[1])
            return "".join(json.dumps(c) + "\n" for c in self.comments.get(number, []))
        raise AssertionError(f"unexpected gh call: {args}")

    def posted(self) -> list[tuple]:
        return [call for call in self.calls if call[:2] == ("issue", "comment")]


@pytest.fixture
def github(monkeypatch):
    found = GitHub()
    monkeypatch.setattr(wait, "gh", found)
    return found


@pytest.fixture
def make_config(tmp_path, monkeypatch):
    """A loaded config with extra TOML; the command runs in tmp_path, as ana's session."""
    monkeypatch.chdir(tmp_path)
    for key in (cli.PERSON_ENV, cli.SESSION_ENV):
        monkeypatch.delenv(key, raising=False)

    def made(extra: str = "") -> dict:
        path = tmp_path / "colony.toml"
        path.write_text(CONFIG.format(worktrees=(tmp_path / "wt").as_posix(), extra=extra))
        return cli.load_config(path)
    return made


@pytest.fixture
def config(make_config):
    return make_config()


def add(config, what="Apply the network change", **values) -> int:
    fields = {"what": what, "run": None, "who": None, "why": None, "check": None, "no_check": False,
              "anyway": False, "dry_run": False, **values}
    return steps.run(config, Namespace(action="add", **fields))


def listed(config, who=None, every=False) -> int:
    return steps.run(config, Namespace(action="list", who=who, all=every))


def done(config, n, note=None) -> int:
    return steps.run(config, Namespace(action="done", n=n, note=note))


def note_of(body: str) -> dict:
    return json.loads(steps.NOTE_TEXT.search(body)[1])


# The dry-run form of a step's command


@pytest.mark.parametrize("command, dry", [
    ("terraform apply -auto-approve", "terraform plan"),
    ("terraform apply -var-file=prod.tfvars", "terraform plan -var-file=prod.tfvars"),
    ("kubectl apply -f app.yaml", "kubectl apply -f app.yaml --dry-run=server"),
    ("kubectl apply -f app.yaml --dry-run=server", "kubectl apply -f app.yaml --dry-run=server"),
    ("make deploy", "make -n deploy"),
    ("npm publish --yes", "npm publish --dry-run"),
])
def test_a_known_command_gets_its_dry_run(config, command, dry):
    assert steps.dry_run_of(config, command) == dry


@pytest.mark.parametrize("command", ["terraform apply && echo done", "make deploy | tee log", "deploy > out.txt",
                                     "aws s3 sync . s3://bucket", "", "echo 'unclosed"])
def test_a_compound_or_unknown_command_gets_none(config, command):
    assert steps.dry_run_of(config, command) == ""


def test_the_repos_own_dry_run_wins_over_the_table(make_config):
    config = make_config('[steps]\ndry_runs = { "make deploy" = "./check-deploy.sh", "./ship" = "./ship --check" }')
    assert steps.dry_run_of(config, "make deploy prod") == "./check-deploy.sh prod"
    assert steps.dry_run_of(config, "./ship -y") == "./ship --check"


def test_a_dry_run_entry_with_unclosed_quotes_matches_nothing(make_config):
    config = make_config('[steps]\ndry_runs = { "./ship \'x" = "./ship --check" }')
    assert steps.dry_run_of(config, "make deploy") == "make -n deploy"


@pytest.mark.parametrize("table, match", [("issue = -1", "issue"), ("issue = true", "issue"),
                                          ('dry_runs = ["make"]', "dry_runs")])
def test_steps_settings_are_checked(make_config, table, match):
    with pytest.raises(cli.ColonyError, match=rf"\[steps\] {match}"):
        steps.settings(make_config(f"[steps]\n{table}"))


# Who does a step


def test_anyone_and_agent_are_kept_as_they_are(config):
    assert steps.who_of(config, "Anyone") == ("anyone", "anyone")
    assert steps.who_of(config, "agent") == ("agent", "agent")


def test_a_known_person_is_mentioned_by_login_with_their_name(config):
    assert steps.who_of(config, "Ana") == ("ana-gh", "@ana-gh (Ana)")
    assert steps.who_of(config, "@ana-gh") == ("ana-gh", "@ana-gh (Ana)")


def test_a_login_with_no_name_is_mentioned_alone(config):
    assert steps.who_of(config, "@bob") == ("bob", "@bob")
    assert steps.who_of(config, "@Carol") == ("carol", "@carol")


def test_a_person_with_no_login_is_named(config):
    assert steps.who_of(config, "Dana") == ("dana", "Dana")


# Handing a step over


def test_add_creates_the_steps_issue_and_posts_the_step_for_the_session_person(config, github, capsys):
    assert add(config, run="./apply.sh", why="it needs the owner's sign-in") == 0
    assert github.issues == [{"number": 7, "title": "Colony: person steps"}]
    [comment] = github.comments[7]
    body = comment["body"]
    assert body.startswith("**Step 1, for @ana-gh (Ana):** Apply the network change\n")
    assert "```sh\n./apply.sh\n```" in body and "Why a person: it needs the owner's sign-in" in body
    assert "Not tested: Colony knows no dry run for this command, so read it before you run it." in body
    assert "Status: open" in body
    assert note_of(body) == {"n": 1, "who": "ana-gh", "status": "open", "tested": False}
    out = capsys.readouterr().out
    assert f"step 1 for @ana-gh (Ana) is on #7: {comment['html_url']}" in out
    assert ("Tell them: One step needs you, Ana: apply the network change. It was not tested, so read it before you "
            f"run it. The details are here: {comment['html_url']}. Tell me when it is done.") in out


def test_add_uses_the_open_steps_issue(config, github):
    github.issue(3, "Colony: person steps (old copy)")
    github.issue(5, "Colony: person steps")
    assert add(config, no_check=True) == 0
    assert [call for call in github.calls if call[:2] == ("issue", "create")] == []
    assert len(github.comments[5]) == 1


def test_add_uses_the_issue_steps_names(make_config, github):
    config = make_config("[steps]\nissue = 42")
    assert add(config, no_check=True) == 0
    assert [call[:2] for call in github.calls] == [("api", "repos/acme/demo/issues/42/comments?per_page=100"),
                                                    ("issue", "comment")]
    assert github.posted()[0][2] == "42"


def test_add_numbers_the_step_after_the_highest_on_the_issue(config, github):
    github.issue(5, "Colony: person steps")
    github.comment(5, 'Step 4\n<!-- colony-step {"n":4,"who":"bob","status":"done","tested":true} -->')
    github.comment(5, "a person's own comment, which is no step")
    assert add(config, no_check=True) == 0
    assert note_of(github.comments[5][-1]["body"])["n"] == 5


def test_add_tests_the_step_first_and_never_runs_its_own_command(make_config, github, tmp_path, capsys):
    config = make_config('[steps]\ndry_runs = { "touch ran.txt" = "touch checked.txt" }')
    assert add(config, run="touch ran.txt") == 0
    assert (tmp_path / "checked.txt").exists() and not (tmp_path / "ran.txt").exists()
    body = github.comments[7][0]["body"]
    assert "Tested: `touch checked.txt` passed at " in body and note_of(body)["tested"] is True
    assert "It was tested first, and the test passed." in capsys.readouterr().out


def test_a_failing_test_stops_the_hand_over(config, github, capsys):
    assert add(config, run="./apply.sh", check="echo the plan has 3 errors; false") == 1
    assert github.posted() == [] and github.issues == []
    out = capsys.readouterr().out
    assert out.startswith("not handed over: its test failed, so the step would fail too: $ echo the plan has 3 "
                          "errors; false\n  the plan has 3 errors\n")
    assert "--anyway" in out


def test_anyway_hands_over_a_step_whose_test_failed_with_the_failure_noted(config, github, capsys):
    assert add(config, check="echo no access; false", anyway=True) == 0
    body = github.comments[7][0]["body"]
    assert "Its test failed, and it was handed over anyway: `echo no access; false` said: no access" in body
    assert note_of(body)["tested"] is False
    assert "the test failed, so read the note on it before you run it" in capsys.readouterr().out


def test_no_check_skips_the_test_and_says_so(make_config, github, tmp_path):
    config = make_config('[steps]\ndry_runs = { "touch ran.txt" = "touch checked.txt" }')
    assert add(config, run="touch ran.txt", no_check=True) == 0
    assert not (tmp_path / "checked.txt").exists()
    assert "Not tested: its test was skipped on purpose." in github.comments[7][0]["body"]


@pytest.mark.parametrize("field", ["what", "run", "why", "check"])
def test_a_step_never_holds_a_secret(config, github, field):
    with pytest.raises(cli.ColonyError, match="never holds a secret"):
        add(config, **{field: "export TOKEN=ghp_" + "a" * 36})
    assert github.calls == []


def test_add_refuses_an_empty_step(config, github):
    with pytest.raises(cli.ColonyError, match="say what the step is"):
        add(config, what="  ")


def test_a_step_for_someone_else_names_them(config, github, capsys):
    assert add(config, "AWS sign-in for the billing account", who="@bob", no_check=True) == 0
    assert github.comments[7][0]["body"].startswith("**Step 1, for @bob:** AWS sign-in")
    assert "One step needs you, bob: AWS sign-in for the billing account." in capsys.readouterr().out


def test_dry_run_runs_nothing(make_config, github, tmp_path, capsys):
    config = make_config('[steps]\ndry_runs = { "touch ran.txt" = "touch checked.txt" }')
    assert add(config, run="touch ran.txt", dry_run=True) == 0
    assert github.calls == [] and list(tmp_path.glob("*.txt")) == []
    out = capsys.readouterr().out
    assert "dry run, nothing runs." in out and "test first: $ touch checked.txt" in out


# Listing steps and marking them done


@pytest.fixture
def three(config, github):
    """Three steps on issue 7: ana's, bob's, and a done one of ana's."""
    add(config, "Sign in to the cloud console", no_check=True)
    add(config, "Approve the payment", who="@bob", no_check=True)
    add(config, "Rotate the old key", no_check=True)
    done(config, 3)
    return github


def test_list_prints_the_open_steps(config, three, capsys):
    capsys.readouterr()
    assert listed(config) == 0
    out = capsys.readouterr().out
    assert "Step 1, for @ana-gh (Ana): Sign in to the cloud console [open, not tested]" in out
    assert "Step 2, for @bob: Approve the payment" in out and "Step 3" not in out


def test_list_all_shows_the_done_ones_too(config, three, capsys):
    capsys.readouterr()
    assert listed(config, every=True) == 0
    assert "Step 3, for @ana-gh (Ana): Rotate the old key [done, not tested]" in capsys.readouterr().out


def test_list_filters_by_person_by_name_or_login(config, three, capsys):
    capsys.readouterr()
    listed(config, who="Ana")
    by_name = capsys.readouterr().out
    listed(config, who="@ana-gh")
    assert capsys.readouterr().out == by_name
    assert "Step 1" in by_name and "Step 2" not in by_name
    listed(config, who="@bob")
    assert "Step 2" in capsys.readouterr().out


def test_list_shows_the_steps_command(config, github, capsys):
    add(config, run="./apply.sh", no_check=True)
    capsys.readouterr()
    listed(config)
    assert "\n    $ ./apply.sh\n" in capsys.readouterr().out


def test_list_says_when_nothing_is_open(config, github, capsys):
    assert listed(config) == 0
    assert capsys.readouterr().out.strip() == "no open person steps on #7"


def test_done_edits_the_status_line_and_the_note(config, github, capsys):
    add(config, no_check=True)
    assert done(config, 1, note="applied in the console") == 0
    body = github.comments[7][0]["body"]
    assert re.search(r"^Status: done by @ana-gh at \d{4}-\d\d-\d\d \d\d:\d\d UTC: applied in the console$", body, re.M)
    assert "Status: open" not in body
    assert note_of(body) == {"n": 1, "who": "ana-gh", "tested": False, "status": "done"}
    assert capsys.readouterr().out.strip().endswith(f"step 1 is done: {github.comments[7][0]['html_url']}")


def test_done_keeps_a_name_with_letters_beyond_english(config, github):
    add(config, who="José", no_check=True)
    assert done(config, 1) == 0
    assert note_of(github.comments[7][0]["body"]) == {"n": 1, "who": "josé", "tested": False, "status": "done"}


def test_a_done_step_says_so(config, github, capsys):
    add(config, no_check=True)
    done(config, 1)
    edits = [call for call in github.calls if call[:3] == ("api", "-X", "PATCH")]
    capsys.readouterr()
    assert done(config, 1) == 0
    assert capsys.readouterr().out.strip() == "step 1 is already done"
    assert [call for call in github.calls if call[:3] == ("api", "-X", "PATCH")] == edits


def test_done_refuses_a_step_that_does_not_exist(config, github):
    with pytest.raises(cli.ColonyError, match="holds no step 9"):
        done(config, 9)


# A person's words never take over the comment


def test_a_note_written_into_a_steps_text_can_not_pass_for_its_note(config, github):
    fake = '<!-- colony-step {"n":99,"who":"bob","status":"done","tested":true} -->'
    assert add(config, what=f"Sign in {fake}", why="it hides the rest --> here", no_check=True) == 0
    body = github.comments[7][0]["body"]
    assert "&lt;!-- colony-step" in body and "--&gt; here" in body
    [step] = steps.read_steps(config, 7)
    assert (step["n"], step["who"], step["status"]) == (1, "ana-gh", "open")


def test_done_edits_colonys_status_line_and_not_one_in_the_command(config, github, capsys):
    assert add(config, run="echo 'Status: open'\n./apply.sh", no_check=True) == 0
    assert done(config, 1) == 0
    body = github.comments[7][0]["body"]
    assert "echo 'Status: open'" in body
    assert re.search(r"^Status: done by @ana-gh at ", body, re.M)
    assert body.count("Status: open") == 1


def test_a_command_holding_a_fence_stays_whole_and_list_shows_it(config, github, capsys):
    command = "printf '```\\nnot the end\\n```'"
    assert add(config, run=command, no_check=True) == 0
    assert "````sh\n" in github.comments[7][0]["body"]
    capsys.readouterr()
    listed(config)
    assert f"\n    $ {command}\n" in capsys.readouterr().out


def test_a_steps_test_runs_from_the_top_of_the_repo(make_config, github, tmp_path, monkeypatch):
    config = make_config()
    repo = tmp_path / "repo"
    (repo / "web").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.chdir(repo / "web")
    assert add(config, check="test -d web && touch at-the-top.txt") == 0
    assert (repo / "at-the-top.txt").exists()
