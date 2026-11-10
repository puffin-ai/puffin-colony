"""Tests for colony/private.py: a lead's private line goes to the private board in [messages] private_repo, with only a
pointer on a public repo's board, and `colony private` reads the lines for this session."""
import json
from argparse import Namespace

import pytest

from colony import cli, private, transport, wait

CONFIG = {"project": {"name": "demo", "repo": "acme/demo", "base": "main", "mode": "hack"},
          "accounts": {"ana": {"config_dir": "~/.claude", "person": "ana"}}, "messages": {"board": 7},
          "people": {"logins": ["ana", "ben"]}}
PRIVATE = {**CONFIG, "messages": {"board": 7, "private_repo": "acme/team-private"}}


class GitHub:
    """A public acme/demo, a private acme/team-private holding its private board, #3, and their calls."""

    def __init__(self, monkeypatch, visibility="PUBLIC"):
        self.visibility, self.calls, self.comments, self.pointers = visibility, [], [], []
        self.private_visibility = "PRIVATE"
        monkeypatch.setattr(wait, "gh", self.gh)
        monkeypatch.setattr(transport, "send", lambda config, to, line, card=None: self.pointers.append(line) or 7)

    def gh(self, *args: str) -> str:
        self.calls.append(args)
        if args[:2] == ("repo", "view"):
            return (self.private_visibility if args[2] == "acme/team-private" else self.visibility) + "\n"
        if args[:2] == ("issue", "list"):
            return json.dumps([{"number": 3, "title": "Private board: demo"}])
        if args[:2] == ("issue", "comment"):
            self.comments.append({"id": 50 + len(self.comments), "body": args[-1], "author_association": "OWNER"})
            return "https://github.com/acme/team-private/issues/3#issuecomment-1\n"
        if args[0] == "api" and "--paginate" in args:
            return "".join(json.dumps(comment) + "\n" for comment in self.comments)
        raise AssertionError(args)


@pytest.fixture
def lead(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("COLONY_SESSION", "lead")
    monkeypatch.setenv("COLONY_LEAD", "ana-main-lead")
    monkeypatch.setenv("COLONY_PERSON", "ana")


def test_a_private_line_on_a_public_repo_needs_a_private_repo(lead, monkeypatch):
    GitHub(monkeypatch)
    with pytest.raises(cli.ColonyError, match=r"set \[messages\] private_repo"):
        wait.say(CONFIG, Namespace(person=None, to="ben-main-lead", sentence="the auth route skips the claim check",
                                   private=True))


def test_a_private_line_goes_to_the_private_board_and_the_public_one_gets_a_pointer_alone(lead, monkeypatch, capsys):
    github = GitHub(monkeypatch)
    secret = "GET /api/records/:id skips the creator check"
    assert wait.say(PRIVATE, Namespace(person=None, to="ben-main-lead", sentence=secret, private=True)) == 0
    assert github.comments[0]["body"] == f"for ben-main-lead: {secret} (from ana-main-lead)"
    assert ("issue", "comment", "3", "--repo", "acme/team-private") == github.calls[-1][:5]
    assert github.pointers == ["@ben a private line waits for you: run `colony private` (from ana-main-lead)"]
    assert secret not in "".join(github.pointers)


def test_on_a_private_repo_a_private_line_goes_on_the_board_itself(lead, monkeypatch):
    github = GitHub(monkeypatch, visibility="PRIVATE")
    assert wait.say(CONFIG, Namespace(person=None, to="ben-main-lead", sentence="the key rotates at 5", private=True)) == 0
    assert github.pointers == ["for ben-main-lead: the key rotates at 5 (from ana-main-lead)"]


def test_colony_private_prints_the_lines_for_this_session_once(lead, monkeypatch, capsys):
    github = GitHub(monkeypatch)
    github.comments += [{"id": 1, "body": "for ana-main-lead: the staff token is in 1Password (from ben-main-lead)",
                         "user": {"login": "ben"}},
                        {"id": 2, "body": "for ben-main-lead: noted (from ana-main-lead)", "user": {"login": "ana"}},
                        {"id": 3, "body": "for ana-main-lead: hi (from eve-main-lead)", "user": {"login": "eve"}}]
    assert private.read(PRIVATE, Namespace(person=None)) == 0
    assert capsys.readouterr().out == "for ana-main-lead: the staff token is in 1Password (from ben-main-lead)\n"
    assert private.read(PRIVATE, Namespace(person=None)) == 0
    assert capsys.readouterr().out == "No new private line for ana-main-lead.\n"


def test_a_private_repo_that_is_public_gets_no_private_line(lead, monkeypatch):
    github = GitHub(monkeypatch)
    github.private_visibility = "PUBLIC"
    with pytest.raises(cli.ColonyError, match="acme/team-private is not private"):
        wait.say(PRIVATE, Namespace(person=None, to="ben-main-lead", sentence="the flaw", private=True))
    assert github.comments == [] and github.pointers == []


def test_visibility_is_read_live_for_each_private_line(lead, monkeypatch):
    github = GitHub(monkeypatch, visibility="PRIVATE")
    assert wait.say(CONFIG, Namespace(person=None, to="ben-main-lead", sentence="one", private=True)) == 0
    github.visibility = "PUBLIC"  # made public meanwhile
    with pytest.raises(cli.ColonyError, match="set \\[messages\\] private_repo"):
        wait.say(CONFIG, Namespace(person=None, to="ben-main-lead", sentence="two", private=True))
    assert github.pointers == ["for ben-main-lead: one (from ana-main-lead)"]
