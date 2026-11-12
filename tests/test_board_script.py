"""Tests for colony/scripts/board, the any-agent board script, run in sh (and dash, where it is installed) against a
stub gh. The stub serves the board issue's comments from a JSON file, logs every call, and runs each --jq program
through jq, standing in for the jq gh carries inside."""
import json
import os
import re
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

import pytest

SCRIPT = Path(str(resources.files("colony"))) / "scripts" / "board"
SHELLS = [shell for shell in ("sh", "dash") if shutil.which(shell)]
REPO, ISSUE = "acme/app", 12
STUB = r'''#!{python}
import json, os, subprocess, sys
from urllib.parse import parse_qs, urlsplit

path = os.environ["STUB_DB"]
with open(path) as f:
    db = json.load(f)
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
if db.get("fail"):
    sys.exit("HTTP 502: Bad Gateway")


def answer(data, program):
    run = subprocess.run(["jq", "-r", program or "."], input=json.dumps(data), capture_output=True, text=True)
    if run.returncode:
        sys.exit("stub gh: jq failed: " + run.stderr)
    sys.stdout.write(run.stdout)


def save():
    with open(path, "w") as f:
        json.dump(db, f)


if args[:2] == ["repo", "view"]:
    answer({"nameWithOwner": db["repo"]}, ".nameWithOwner")
    sys.exit(0)
closed = db.get("closed", [])


def comments_of(number):
    """An issue's comments: the board's in db["comments"], any other issue's in db["boards"]."""
    if number == db["issue"]:
        return db["comments"]
    return db.setdefault("boards", {}).setdefault(str(number), [])


if args[:2] == ["issue", "list"]:
    program = args[args.index("--jq") + 1] if "--jq" in args else None
    numbers = [db["issue"]] + [int(n) for n in db.get("boards", {})]
    answer([{"number": n, "title": "Board: app"} for n in numbers if n not in closed], program)
    sys.exit(0)
program, fields, target, rest = None, {}, None, args[1:]
while rest:
    word = rest.pop(0)
    if word == "--jq":
        program = rest.pop(0)
    elif word == "-f":
        key, _, value = rest.pop(0).partition("=")
        fields[key] = value
    elif word == "--paginate":
        pass
    elif word.startswith("-"):
        sys.exit("stub gh: unknown flag " + word)
    else:
        target = word
url = urlsplit(target)
query = {key: values[0] for key, values in parse_qs(url.query).items()}
parts = url.path.split("/")
on_issue = url.path.startswith("repos/{}/issues/".format(db["repo"])) and len(parts) >= 5 and parts[4].isdigit()
number = int(parts[4]) if on_issue else None
if url.path == "user":
    answer({"login": db["login"]}, program)
elif on_issue and len(parts) == 5:
    answer({"number": number, "comments": len(comments_of(number)), "title": "Board: app",
            "state": "closed" if number in closed else "open"}, program)
elif on_issue and parts[5:] == ["comments"] and fields:
    everything = db["comments"] + [c for board in db.get("boards", {}).values() for c in board]
    made_id = max([c["id"] for c in everything] + [100]) + 1
    at = "2026-11-05T11:{:02d}:00Z".format(len(everything) % 60)
    made = {"id": made_id, "user": {"login": db["login"]}, "body": fields["body"], "created_at": at,
            "updated_at": at,
            "html_url": "https://github.com/{}/issues/{}#issuecomment-{}".format(db["repo"], number, made_id)}
    comments_of(number).append(made)
    save()
    answer(made, program)
elif on_issue and parts[5:] == ["comments"]:
    comments = sorted(comments_of(number), key=lambda c: c["id"])
    if "since" in query:
        page = [c for c in comments if c["updated_at"] >= query["since"]]
    else:
        size, page_number = int(query.get("per_page", 30)), int(query.get("page", 1))
        page = comments[(page_number - 1) * size:page_number * size]
    answer(page, program)
    if db.get("arrivals"):
        db["comments"].append(db["arrivals"].pop(0))
        save()
else:
    sys.exit("HTTP 404: Not Found (" + str(target) + ")")
'''


def comment(number: int, login: str, body: str) -> dict:
    """One issue comment, created at a time that grows with its number."""
    at = f"2026-11-05T10:{number // 60 % 60:02d}:{number % 60:02d}Z"
    return {"id": number, "user": {"login": login}, "body": body, "created_at": at, "updated_at": at,
            "html_url": f"https://github.com/{REPO}/issues/{ISSUE}#issuecomment-{number}"}


class Board:
    """A clone with a hack colony.toml, a home folder, and a stub gh whose comments live in db.json."""

    def __init__(self, tmp_path: Path, shell: str):
        self.shell, self.root, self.home = shell, tmp_path / "repo", tmp_path / "home"
        self.root.mkdir()
        self.home.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".colony").mkdir()
        self.config = self.root / ".colony" / "colony.toml"
        self.config.write_text(f'[project]\nmode = "hack"\nname = "app"\nrepo = "{REPO}"   # the repo\n\n'
                               f'[messages]\nboard = {ISSUE}\n\n'
                               '[people]\nlogins = ["ana", "sam"]\n'
                               'names = { ana = "Ana", sam = "Sam" }\n')
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(STUB.replace("{python}", sys.executable))
        (bin_dir / "gh").chmod(0o755)
        self.db, self.log = tmp_path / "db.json", tmp_path / "gh.log"
        self.save({"repo": REPO, "issue": ISSUE, "login": "ana", "comments": []})
        self.env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HOME": str(self.home), "STUB_DB": str(self.db),
                    "STUB_LOG": str(self.log), "BOARD_AGENT": "Codex"}

    def save(self, db: dict) -> None:
        self.db.write_text(json.dumps(db))

    def load(self) -> dict:
        return json.loads(self.db.read_text())

    def add(self, *comments: dict, key: str = "comments") -> None:
        db = self.load()
        db.setdefault(key, []).extend(comments)
        self.save(db)

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def run(self, *args: str, stdin: str | None = None, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run([self.shell, str(SCRIPT), *args], cwd=self.root, input=stdin, capture_output=True,
                              text=True, env={**self.env, **env}, timeout=30)

    def cursor(self) -> Path:
        return self.home / ".colony" / "board" / f"acme_app-{ISSUE}" / "codex" / "cursor"


@pytest.fixture(params=SHELLS)
def board(tmp_path, request) -> Board:
    if shutil.which("jq") is None:
        pytest.skip("the stub gh runs each --jq program through jq, which is not installed")
    return Board(tmp_path, request.param)


def posts(out: str) -> list[str]:
    """Each post's header line, as `<author> <comment> <for you or ->`."""
    found = re.findall(r"^--- @(\S+) at \S+, comment (\d+)(, for you)?$", out, re.M)
    return [f"{who} {number} {'you' if mine else '-'}" for who, number, mine in found]


def test_the_script_is_posix_sh_that_needs_only_gh():
    text = SCRIPT.read_text()
    assert text.startswith("#!/bin/sh\n") and os.access(SCRIPT, os.X_OK)
    for bashism in ("[[ ", "local ", "$'", "function ", "<<<", "declare ", "${!", "pipefail", "source "):
        assert bashism not in text, bashism
    assert not re.search(r"(^|[|;&(]|then|do)\s*jq\b", text, re.M), "jq runs only inside gh, through --jq"
    for shell in SHELLS:
        assert subprocess.run([shell, "-n", str(SCRIPT)]).returncode == 0, shell


def test_whoami_names_the_login_the_name_from_colony_toml_and_the_agent(board):
    run = board.run("whoami")
    assert run.returncode == 0, run.stderr
    assert run.stdout == ("login: ana\nname: Ana\nagent: Codex\nposts as: [Ana's Codex]\n"
                          f"board: {REPO}#{ISSUE}\n")
    claude = board.run("whoami", BOARD_AGENT="", CLAUDECODE="1")
    assert "posts as: [Ana's Claude]" in claude.stdout
    override = board.run("whoami", BOARD_NAME="Ana K", BOARD_ISSUE="40", BOARD_REPO="acme/other")
    assert "posts as: [Ana K's Codex]" in override.stdout and "board: acme/other#40" in override.stdout


def test_post_adds_the_prefix_once_and_takes_the_text_from_stdin(board):
    run = board.run("post", "@sam", "the login API is up")
    assert run.returncode == 0, run.stderr
    assert run.stdout == f"posted https://github.com/{REPO}/issues/{ISSUE}#issuecomment-101\n"
    assert board.run("post", "[Ana's Claude] @all main is green").returncode == 0
    assert board.run("post", stdin="two lines\nof news\n").returncode == 0
    bodies = [c["body"] for c in board.load()["comments"]]
    assert bodies == ["[Ana's Codex] @sam the login API is up", "[Ana's Claude] @all main is green",
                      "[Ana's Codex] two lines\nof news"]


def test_a_colony_session_signs_each_line_it_posts_so_its_own_wait_never_takes_it(board):
    lead = {"COLONY_SESSION": "lead", "COLONY_LEAD": "ana-main-lead"}
    assert board.run("post", "@all merging ana/login now", **lead).returncode == 0
    assert board.run("post", stdin="@all one\n\n@sam two (from ana-main-lead)\n", **lead).returncode == 0
    assert board.run("post", "@all from a helper", COLONY_SESSION="staff", COLONY_LEAD="ana-main-lead").returncode == 0
    bodies = [c["body"] for c in board.load()["comments"]]
    assert bodies == ["[Ana's Codex] @all merging ana/login now (from ana-main-lead)",
                      "[Ana's Codex] @all one (from ana-main-lead)\n\n@sam two (from ana-main-lead)",
                      "[Ana's Codex] @all from a helper (from staff)"]


def test_post_refuses_an_empty_text_and_a_token_without_calling_github(board):
    empty = board.run("post", "  ")
    assert empty.returncode == 1 and "nothing to post" in empty.stderr
    token = board.run("post", "the key is ghp_" + "a" * 36)
    assert token.returncode == 1 and "never carries a secret" in token.stderr
    assert not [call for call in board.calls() if "-f" in call]
    assert board.load()["comments"] == []


def test_unread_first_shows_the_last_posts_then_only_the_new_ones_by_others(board):
    board.add(*[comment(n, "sam", f"post {n}") for n in range(1, 11)],
              comment(11, "lee", "@ana can you review?"), comment(12, "sam", "@ALL demo at 5"),
              comment(13, "lee", "mail @ana-k, not me"), comment(14, "lee", "line one\nline two"))
    first = board.run("unread")
    assert first.returncode == 0, first.stderr
    assert posts(first.stdout) == [f"sam {n} -" for n in (5, 6, 7, 8, 9, 10)] + [
        "lee 11 you", "sam 12 you", "lee 13 -", "lee 14 -"]
    assert "--- @lee at 2026-11-05T10:00:14Z, comment 14\nline one\nline two\n" in first.stdout
    again = board.run("unread")
    assert (again.returncode, again.stdout, again.stderr) == (0, "", "board: no new posts\n")
    assert board.run("post", "@all I take the login form").returncode == 0
    board.add(comment(200, "sam", "@ana the API returns the name now"))
    third = board.run("unread")
    assert posts(third.stdout) == ["sam 200 you"]  # the post this agent made is not unread
    assert board.cursor().read_text().split()[0] == "200"


def test_a_check_github_fails_marks_nothing_read(board):
    board.add(comment(1, "sam", "@ana hi"))
    assert board.run("unread").returncode == 0
    before = board.cursor().read_text()
    board.add(comment(2, "sam", "@ana again"))
    db = board.load()
    board.save({**db, "fail": True})
    run = board.run("unread")
    assert run.returncode == 1 and "could not reach GitHub, so nothing was marked read" in run.stderr
    assert board.cursor().read_text() == before
    board.save(db)
    assert posts(board.run("unread").stdout) == ["sam 2 you"]


def test_read_shows_the_last_n_posts_across_pages_and_leaves_unread_alone(board):
    board.add(*[comment(n, "sam", f"post {n}") for n in range(1, 151)])
    run = board.run("read", "-n", "60")
    assert run.returncode == 0, run.stderr
    assert posts(run.stdout) == [f"sam {n} -" for n in range(91, 151)]
    pages = [call[1] for call in board.calls() if call[0] == "api" and "/comments?" in call[1]]
    assert [re.search(r"&page=(\d+)", page)[1] for page in pages] == ["2", "1"]  # the last page, then the one before
    assert posts(board.run("read", "-n2").stdout) == ["sam 149 -", "sam 150 -"]
    assert not board.cursor().exists()
    assert len(posts(board.run("unread").stdout)) == 10


def test_wait_sleeps_through_posts_for_others_and_wakes_on_one_for_you(board):
    board.add(comment(1, "sam", "kickoff"))
    board.run("unread")
    board.add(comment(2, "sam", "pushed the schema"))
    board.add(comment(3, "lee", "@all freeze at 4"), key="arrivals")
    run = board.run("wait", "--interval", "1")
    assert run.returncode == 0, run.stderr
    assert posts(run.stdout) == ["sam 2 -", "lee 3 you"]
    reads = [call for call in board.calls() if any("since=" in word for word in call)]
    assert len(reads) == 2  # one check saw only sam's post, the next one lee's too
    assert "--paginate" in reads[0]
    assert board.cursor().read_text().split()[0] == "3"


def test_wait_and_read_refuse_bad_numbers_and_every_command_needs_a_board(board):
    for args in (("wait", "--interval", "0"), ("wait", "--interval", "soon"), ("read", "-n", "x"), ("unread", "x")):
        run = board.run(*args)
        assert run.returncode == 1 and run.stderr.startswith("board: "), args
    board.config.write_text(f'[project]\nrepo = "{REPO}"\n')
    run = board.run("unread")
    assert run.returncode == 1 and "set board = <issue number> under [messages]" in run.stderr
    assert board.run("nonsense").returncode == 2
    assert "tools/board post" in board.run("help").stdout
    assert board.calls() == []


def since_values(calls: list[list[str]]) -> list[str]:
    """The since= time of each read of new comments, in order."""
    return [re.search(r"since=(\S+)", word)[1] for call in calls for word in call if "since=" in word]


def test_wait_asks_only_for_what_came_since_its_last_check(board):
    board.add(comment(1, "sam", "kickoff"))
    board.run("unread")
    board.add(comment(2, "sam", "pushed the schema"), comment(3, "sam", "pushed the seed"),
              comment(4, "lee", "@all freeze at 4"), key="arrivals")
    run = board.run("wait", "--interval", "1")
    assert run.returncode == 0, run.stderr
    assert posts(run.stdout) == ["sam 2 -", "sam 3 -", "lee 4 you"]
    # Each check starts from the newest post the wait has read, so a quiet agent never reads the same posts again.
    assert since_values(board.calls()) == [comment(n, "", "")["updated_at"] for n in (1, 1, 2, 3)]
    assert board.cursor().read_text().split()[0] == "4"


def test_board_wait_off_returns_at_once_without_reading_github(board):
    run = board.run("wait", BOARD_WAIT="off")
    assert run.returncode == 1 and "waiting is off" in run.stderr
    assert board.calls() == []


def test_unread_follows_the_board_to_the_fresh_issue_it_moved_to_and_posts_there(board):
    board.add(comment(1, "sam", "kickoff"))
    board.run("unread")
    board.add(comment(2, "ana", "Closed at 300 comments; this thread goes on in #13.\n\nOpen items: none"))
    db = board.load()
    db["closed"], db["boards"] = [ISSUE], {"13": [comment(3, "sam", "@all first post on the fresh board")]}
    board.save(db)
    run = board.run("unread")
    assert posts(run.stdout) == ["ana 2 -", "sam 3 you"]
    assert board.run("whoami").stdout.splitlines()[-1] == f"board: {REPO}#13"
    assert board.run("post", "hello").returncode == 0
    assert board.load()["boards"]["13"][-1]["body"] == "[Ana's Codex] hello"


def test_a_first_look_at_a_closed_board_finds_the_fresh_one_by_its_title(board):
    db = board.load()
    db["comments"] = [comment(1, "sam", "old post")]
    db["closed"], db["boards"] = [ISSUE], {"13": [comment(5, "sam", "new post")]}
    board.save(db)
    run = board.run("read", "-n", "5")
    assert posts(run.stdout) == ["sam 5 -"]
    assert any(call[:2] == ["issue", "list"] for call in board.calls())
    assert board.run("whoami").stdout.splitlines()[-1] == f"board: {REPO}#13"


def test_a_board_moved_twice_at_once_is_followed_to_the_lowest_fresh_board_as_colony_keeps(board):
    db = board.load()
    db["comments"] = [comment(1, "sam", "old post"),
                      comment(2, "ana", "Closed at 300 comments; this thread goes on in #14.\n\nOpen items: none"),
                      comment(3, "sam", "Closed at 300 comments; this thread goes on in #13.\n\nOpen items: none")]
    db["closed"], db["boards"] = [ISSUE], {"13": [comment(5, "sam", "kept board")], "14": [comment(6, "sam", "twin")]}
    board.save(db)
    run = board.run("read", "-n", "5")
    assert posts(run.stdout) == ["sam 5 -"]
    assert not any(call[:2] == ["issue", "list"] for call in board.calls()), "the notes name the board, no search"
    assert board.run("whoami").stdout.splitlines()[-1] == f"board: {REPO}#13"


def test_unread_follows_the_lowest_of_two_moved_notes(board):
    board.add(comment(1, "sam", "kickoff"))
    board.run("unread")
    board.add(comment(2, "ana", "Closed at 300 comments; this thread goes on in #14."),
              comment(3, "sam", "Closed at 300 comments; this thread goes on in #13."))
    db = board.load()
    db["closed"], db["boards"] = [ISSUE], {"13": [comment(4, "sam", "@all kept board")], "14": [comment(5, "ana", "x")]}
    board.save(db)
    run = board.run("unread")
    assert posts(run.stdout) == ["ana 2 -", "sam 3 -", "sam 4 you"]
    assert board.run("whoami").stdout.splitlines()[-1] == f"board: {REPO}#13"
