"""Tests for real-use testing: the registry of the test accounts and fixtures a person prepared, and the findings list
that testers on several computers share on the code host. The code host is an in-memory stand-in, so two testers can
race for one card, and nothing reaches GitHub."""
import json
import re
import tomllib
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from colony import board, cli, cycle, presence, testers, wait

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc)
CONFIG = {"project": {"name": "demo", "repo": "acme/demo", "base": "dev"}, "people": {"logins": ["ana", "sam"]}}


# The registry of test accounts and fixtures


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A repo top whose .colony/ folder holds the registry."""
    monkeypatch.setattr(cli, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(board, "utcnow", lambda: NOW)
    return tmp_path


def add(kind, name, what, **given):
    """`colony fixtures add <kind> <name> --what <what> …` as parsed arguments."""
    values = {key: None for key in ("where", "login", "secret_at", "how", "note")}
    return Namespace(kind=kind, name=name, what=what, person="ana", **{**values, **given})


def test_fixtures_add_records_references_and_list_prints_them(root, capsys):
    assert testers.fixtures_add(CONFIG, add("account", "staging-admin", "an admin on staging", where="staging",
                                            login="qa-admin@example.test", secret_at="the team vault, QA admin")) == 0
    assert testers.fixtures_add(CONFIG, add("fixture", "seeded-shop", "a shop with 40 orders",
                                            how="make seed-shop")) == 0
    out = capsys.readouterr().out
    assert "recorded account staging-admin: an admin on staging; where: staging; login: qa-admin@example.test; " \
           "secret kept in: the team vault, QA admin" in out
    assert "Commit .colony/fixtures.toml with your next change, so every computer reads it." in out
    data = tomllib.loads((root / ".colony" / "fixtures.toml").read_text())
    assert data["accounts"]["staging-admin"] == {"what": "an admin on staging", "where": "staging",
                                                 "login": "qa-admin@example.test",
                                                 "secret_at": "the team vault, QA admin", "by": "ana",
                                                 "added": "2026-11-05"}
    assert data["fixtures"]["seeded-shop"]["how"] == "make seed-shop"
    assert testers.fixtures_list(CONFIG, Namespace(json=False)) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Test accounts (1):",
        "- staging-admin: an admin on staging; where: staging; login: qa-admin@example.test; secret kept in: the "
        "team vault, QA admin",
        "Fixtures (1):",
        "- seeded-shop: a shop with 40 orders; how: make seed-shop"]
    # Adding the same name again replaces it, and it is never both an account and a fixture.
    testers.fixtures_add(CONFIG, add("account", "staging-admin", "an admin on staging, reset nightly"))
    assert "updated account staging-admin" in capsys.readouterr().out
    with pytest.raises(cli.ColonyError, match="one of the accounts already"):
        testers.fixtures_add(CONFIG, add("fixture", "staging-admin", "x"))


def test_the_registry_never_holds_a_secret(root):
    with pytest.raises(cli.ColonyError, match=r"--note holds what looks like a key or a token, and the registry "
                                              r"never holds a secret: name where the secret is kept with --secret-at"):
        testers.fixtures_add(CONFIG, add("account", "qa", "a tester", note="password: hunter2hunter2"))
    with pytest.raises(cli.ColonyError, match="--login holds what looks like"):
        testers.fixtures_add(CONFIG, add("account", "qa", "a tester", login="eyJhbGciOiJI.eyJzdWIiOiIx.SflKxwRJSMeK"))
    with pytest.raises(cli.ColonyError, match="is not a name"):
        testers.fixtures_add(CONFIG, add("account", "qa admin", "a tester"))
    assert not (root / ".colony" / "fixtures.toml").exists()


def test_fixtures_remove_drops_one_and_names_what_the_registry_holds(root, capsys):
    testers.fixtures_add(CONFIG, add("account", "qa", "a tester"))
    with pytest.raises(cli.ColonyError, match="the registry has no other: it holds qa"):
        testers.fixtures_remove(CONFIG, Namespace(name="other"))
    assert testers.fixtures_remove(CONFIG, Namespace(name="qa")) == 0
    assert testers.read_registry() == {"accounts": {}, "fixtures": {}}
    testers.fixtures_list(CONFIG, Namespace(json=False))
    assert "No test account or fixture is recorded yet" in capsys.readouterr().out.splitlines()[-1]


def test_a_question_for_test_accounts_is_refused_while_the_registry_holds_some(root):
    testers.check_question("Which test account should the tester use?")  # an empty registry: ask away
    testers.fixtures_add(CONFIG, add("account", "staging-admin", "an admin on staging"))
    for question in ("Which test account should the tester use?", "Can you seed data for the shop?",
                     "May I make a new fixture?", "Do we have test users on staging?"):
        with pytest.raises(cli.ColonyError, match=r"the person prepared test accounts and fixtures already: "
                                                  r"staging-admin\. Read them with `colony fixtures`"):
            testers.check_question(question)
    testers.check_question("Ship the dark mode switch today?")  # any other question goes through


def test_needs_checks_the_registry_unless_new_fixture(monkeypatch):
    seen = []
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    monkeypatch.setattr(testers, "check_question", lambda question: seen.append(question) or (_ for _ in ()).throw(
        cli.ColonyError("prepared already")))
    args = Namespace(question="Which test account?", default="qa", needs_person=None, person="ana", new_fixture=False)
    with pytest.raises(cli.ColonyError, match="prepared already"):
        cycle.needs(CONFIG, args)
    assert seen == ["Which test account?"]
    # With --new-fixture the check is skipped, and needs goes on to post, which this test stops at the lead's name.
    monkeypatch.setattr(wait, "lead_name", lambda config, args: (_ for _ in ()).throw(cli.ColonyError("posting")))
    with pytest.raises(cli.ColonyError, match="posting"):
        cycle.needs(CONFIG, Namespace(**{**vars(args), "new_fixture": True}))
    assert seen == ["Which test account?"]
    parsed = cli.build_parser().parse_args(["needs", "Which test account?", "--default", "qa", "--new-fixture"])
    assert parsed.new_fixture is True


# The findings list: where each card stands


def event(kind, card, by, minutes, note=""):
    return testers.Event(kind, card, by, NOW + timedelta(minutes=minutes), note)


def test_the_earlier_claim_wins_and_a_claim_lapses_with_no_result():
    cards = [{"number": 11, "title": "a"}, {"number": 12, "title": "b"}, {"number": 13, "title": "c"}]
    events = [event("claim", 11, "tester on laptop", 0), event("claim", 11, "tester-2 on desktop", 1),
              event("claim", 12, "tester-2 on desktop", 2), event("fail", 12, "tester-2 on desktop", 5, "it resets"),
              event("claim", 13, "tester on laptop", 0)]
    states = testers.standing(cards, events, NOW + timedelta(minutes=30), timedelta(minutes=60))
    assert (states[11].holder, states[11].result) == ("tester on laptop", "")
    assert (states[12].holder, states[12].result, states[12].note, states[12].by) == (
        "", "fail", "it resets", "tester-2 on desktop")
    # After the lapse, a claim with no result frees its card, and another tester's claim takes it.
    states = testers.standing(cards, events, NOW + timedelta(minutes=61), timedelta(minutes=60))
    assert (states[11].holder, states[11].lapsed) == ("", "tester on laptop")
    later = events + [event("claim", 13, "tester-2 on desktop", 61)]
    assert testers.standing(cards, later, NOW + timedelta(minutes=62), timedelta(minutes=60))[13].holder == \
        "tester-2 on desktop"


def test_a_holders_own_claim_renews_it_and_a_free_hands_the_card_back():
    cards = [{"number": 11, "title": "a"}]
    renewed = [event("claim", 11, "tester on laptop", 0), event("claim", 11, "tester on laptop", 50)]
    states = testers.standing(cards, renewed, NOW + timedelta(minutes=90), timedelta(minutes=60))
    assert (states[11].holder, states[11].since) == ("tester on laptop", NOW + timedelta(minutes=50))
    freed = renewed + [event("free", 11, "tester-2 on desktop", 51), event("free", 11, "tester on laptop", 52)]
    states = testers.standing(cards, freed[:3], NOW + timedelta(minutes=55), timedelta(minutes=60))
    assert states[11].holder == "tester on laptop"  # only the holder frees a card
    assert testers.standing(cards, freed, NOW + timedelta(minutes=55), timedelta(minutes=60))[11].holder == ""


def test_only_the_teams_comments_count_and_a_note_may_hold_brackets():
    comments = [
        {"id": 2, "created_at": "2026-11-05T14:02:00Z", "user": {"login": "Sam"},
         "body": "findings: fail #12: the switch (in settings) resets (by tester-2 on desktop)"},
        {"id": 1, "created_at": "2026-11-05T14:01:00Z", "user": {"login": "ana"},
         "body": "findings: claim #12 (by tester on laptop)"},
        {"id": 3, "created_at": "2026-11-05T14:03:00Z", "user": {"login": "stranger"},
         "body": "findings: pass #12 (by tester on laptop)"}]
    found = testers.events_of(comments, frozenset({"ana", "sam"}))
    assert [(e.kind, e.card, e.by, e.note) for e in found] == [
        ("claim", 12, "tester on laptop", ""), ("fail", 12, "tester-2 on desktop", "the switch (in settings) resets")]


def test_the_list_renders_every_card_and_reads_its_cards_back():
    cards = [{"number": 11, "title": "builder-1: the login form"}, {"number": 12, "title": "a | b"}]
    states = testers.standing(cards, [event("claim", 11, "tester on laptop", 0),
                                      event("fail", 12, "tester-2 on desktop", 1, "it resets")],
                              NOW + timedelta(minutes=2), timedelta(minutes=60))
    body = testers.render(testers.Findings(100, 50, cards), states)
    assert "| #11 builder-1: the login form | testing | tester on laptop, since 14:00 UTC |  |" in body
    assert "| #12 a \\| b | fail | tester-2 on desktop | it resets |" in body
    assert "1 of 2 cards tested: 0 pass, 1 fail, 0 blocked." in body
    assert "## Failures\n- #12 a | b: it resets (tester-2 on desktop)" in body
    assert testers.data_of(body) == {"release": 50, "cards": cards}
    assert testers.data_of("no data here") == {}


# The findings list: testers on several computers


class Host:
    """An in-memory code host for the findings commands: open and closed issues with their comments, pull request
    bodies, and issue titles. `between` posts another tester's comment just before the next one, as a race does."""

    def __init__(self, pulls: dict[int, str], titles: dict[int, str]):
        self.issues: dict[int, dict] = {}
        self.pulls, self.titles = pulls, titles
        self.number, self.clock, self.login = 100, NOW, "ana"
        self.between: list[tuple[int, str, str]] = []

    def comment(self, number: int, body: str, login: str) -> None:
        self.clock += timedelta(seconds=1)
        found = self.issues[number]["comments"]
        found.append({"id": sum(len(i["comments"]) for i in self.issues.values()) + 1, "body": body,
                      "created_at": self.clock.strftime("%Y-%m-%dT%H:%M:%SZ"), "user": {"login": login}})

    def create(self, title: str, body: str, login: str = "") -> int:
        number, self.number = self.number, self.number + 1
        self.issues[number] = {"title": title, "body": body, "state": "OPEN", "comments": [],
                               "user": {"login": login or self.login}}
        return number

    def gh(self, *args: str) -> str:
        a = list(args)

        def opt(name: str) -> str:
            return a[a.index(name) + 1]

        if a[0] == "api" and "/comments" not in " ".join(a):  # the REST list of open issues, newest first, a page of it
            assert "state=open" in a[1] and "page=1" in a[1]  # a plain list: a search lags behind a new issue
            return json.dumps([{"number": n, "title": i["title"], "body": i["body"], "user": i["user"]}
                               for n, i in sorted(self.issues.items(), reverse=True) if i["state"] == "OPEN"]
                              + [{"number": 7, "title": "a pull request", "pull_request": {}}])
        if a[:2] == ["issue", "create"]:
            return f"https://github.com/acme/demo/issues/{self.create(opt('--title'), opt('--body'))}\n"
        if a[:2] == ["issue", "edit"]:
            self.issues[int(a[2])]["body"] = opt("--body")
            return ""
        if a[:2] == ["issue", "close"]:
            self.issues[int(a[2])]["state"] = "CLOSED"
            return ""
        if a[:2] == ["issue", "comment"]:
            for number, body, login in self.between:
                self.comment(number, body, login)
            self.between = []
            self.comment(int(a[2]), opt("--body"), self.login)
            return ""
        if a[:2] == ["issue", "view"]:
            return json.dumps({"title": self.titles.get(int(a[2]), "")})
        if a[:2] == ["pr", "view"]:
            return json.dumps({"body": self.pulls[int(a[2])]})
        if a[0] == "api":
            number = int(re.search(r"issues/(\d+)/comments", a[2])[1])
            return "\n".join(json.dumps(c) for c in self.issues[number]["comments"])
        raise AssertionError(f"an unexpected gh call: {a}")

    def body(self) -> str:
        return next(i["body"] for i in self.issues.values() if i["state"] == "OPEN")


@pytest.fixture
def host(root, monkeypatch):
    """The release #50 lists batches #40 and #41, which close cards #11, #12 and #13."""
    found = Host({50: "## Batches\n- #40 the login batch\n- #41 the export batch",
                  40: "## Cards\n- Closes #11, from `builder-1/11`\n- Closes #12, from `builder-2/12`",
                  41: "## Cards\n- Closes #13, from `builder-3/13`"},
                 {11: "builder-1: the login form", 12: "builder-2: the sign-up form", 13: "builder-3: the export"})
    monkeypatch.setattr(wait, "gh", found.gh)
    monkeypatch.setattr(board, "utcnow", lambda: found.clock)
    return found


def as_tester(name):
    return {"release": "50", "as_name": name}


def test_two_testers_share_one_list_and_the_earlier_claim_wins_a_race(host, capsys):
    testers.fixtures_add(CONFIG, add("account", "staging-admin", "an admin on staging"))
    assert testers.findings_open(CONFIG, Namespace(release="https://github.com/acme/demo/pull/50", card=None)) == 0
    out = capsys.readouterr().out
    assert "made the findings issue #100 for the release #50" in out
    assert "  #11 builder-1: the login form: not tested" in out
    assert "  - staging-admin: an admin on staging" in out  # the prepared accounts come before any question
    assert host.issues[100]["title"] == "test: findings for the release #50"
    # The second tester, on another computer, finds the same issue.
    assert testers.findings_open(CONFIG, Namespace(release="50", card=None)) == 0
    assert "the release #50's findings issue is #100" in capsys.readouterr().out
    assert len(host.issues) == 1

    testers.findings_next(CONFIG, Namespace(**as_tester("tester on laptop")))
    assert capsys.readouterr().out.startswith("yours: #11 builder-1: the login form")
    # tester-2 claims #12 at the same moment as tester on laptop: its comment lands first, so it wins.
    host.between = [(100, "findings: claim #12 (by tester-2 on desktop)", "sam")]
    host.login = "ana"
    testers.findings_next(CONFIG, Namespace(**as_tester("tester on laptop")))
    out = capsys.readouterr().out
    assert out.startswith("yours already: #11")  # one card at a time: its own card comes back
    testers.findings_report(CONFIG, Namespace(card=11, result="pass", note="", **as_tester("tester on laptop")))
    host.between = [(100, "findings: claim #13 (by tester-2 on desktop)", "sam")]
    testers.findings_next(CONFIG, Namespace(**as_tester("tester on laptop")))
    out = capsys.readouterr().out
    assert "#13 went to tester-2 on desktop, who claimed it first; trying the next card" in out
    assert "nothing left to claim: 1 of 3 cards tested: 1 pass, 0 fail, 0 blocked; 2 still being tested by " \
           "tester-2 on desktop" in out
    assert "| #12 builder-2: the sign-up form | testing | tester-2 on desktop, since 14:00 UTC |  |" in host.body()

    host.login = "sam"
    with pytest.raises(cli.ColonyError, match="a fail needs what you saw"):
        testers.findings_report(CONFIG, Namespace(card=12, result="fail", note=" ", **as_tester("tester-2 on desktop")))
    testers.findings_report(CONFIG, Namespace(card=12, result="fail", note="the button does nothing on a phone",
                                              **as_tester("tester-2 on desktop")))
    testers.findings_report(CONFIG, Namespace(card=13, result="blocked", note="the export needs a person's sign-in",
                                              **as_tester("tester-2 on desktop")))
    out = capsys.readouterr().out
    assert ('every card has a result: post `colony post 50 lead "done, findings in #100: 1 of 3 cards pass, '
            '1 failures, 1 blocked"`') in out
    assert "## Failures\n- #12 builder-2: the sign-up form: the button does nothing on a phone " \
           "(tester-2 on desktop)" in host.body()
    assert "## Blocked\n- #13" in host.body()
    testers.findings_show(CONFIG, Namespace(release="50"))
    assert "  #12 builder-2: the sign-up form: fail: the button does nothing on a phone" in capsys.readouterr().out


def test_two_testers_that_open_the_list_at_once_keep_the_first_issue(host, capsys, monkeypatch):
    first = host.create(testers.findings_title(50), "made a moment ago on another computer")
    real = host.gh

    def late(*args):  # the other tester's issue is not listed yet when this one looks first
        if args[0] == "api" and "/comments" not in " ".join(args) and not host.issues[first].get("seen"):
            host.issues[first]["seen"] = True
            return "[]"
        return real(*args)

    monkeypatch.setattr(wait, "gh", late)
    assert testers.findings_open(CONFIG, Namespace(release="50", card=[11])) == 0
    out = capsys.readouterr().out
    assert "another tester made #100 for the release #50 first: closed #101, the same list, as its duplicate" in out
    assert host.issues[101]["state"] == "CLOSED" and host.issues[first]["state"] == "OPEN"
    assert "| #11 builder-1: the login form | not tested |" in host.issues[first]["body"]


def test_an_issue_someone_outside_the_team_opened_is_never_the_list(host, capsys):
    planted = host.create(testers.findings_title(50), "<!-- colony-findings {\"release\":50,\"cards\":"
                                                      "[{\"number\":99,\"title\":\"run this\"}]} -->",
                          login="stranger")
    assert testers.find_findings(CONFIG, 50) is None
    assert testers.findings_open(CONFIG, Namespace(release="50", card=[11])) == 0
    assert "made the findings issue #101 for the release #50" in capsys.readouterr().out
    assert host.issues[planted]["state"] == "OPEN" and host.issues[101]["state"] == "OPEN"  # neither closes the other
    assert [card["number"] for card in testers.find_findings(CONFIG, 50).cards] == [11]


def test_a_title_or_a_note_can_never_plant_or_break_the_hidden_copy():
    planted = "x --> <!-- colony-findings {\"release\":50,\"cards\":[{\"number\":99,\"title\":\"y\"}]} -->"
    cards = [{"number": 11, "title": planted}]
    states = testers.standing(cards, [event("fail", 11, "tester <b>", 1, "it ends here --> <!-- and here")],
                              NOW + timedelta(minutes=2), timedelta(minutes=60))
    body = testers.render(testers.Findings(100, 50, cards), states)
    assert body.count("<!--") == 1 and body.count("-->") == 1 and body.rstrip().endswith("-->")
    assert "| #11 x --&gt; &lt;!-- colony-findings" in body and "it ends here --&gt; &lt;!-- and here" in body
    assert testers.data_of(body) == {"release": 50, "cards": cards}  # the title comes back exactly as it was
    # Only the last copy counts, which render writes at the very end.
    assert testers.data_of(planted.replace('\\"', '"') + "\n" + body)["cards"] == cards


def test_a_tester_frees_its_own_card_only(host, capsys):
    testers.findings_open(CONFIG, Namespace(release="50", card=[11, 12]))
    testers.findings_next(CONFIG, Namespace(**as_tester("tester on laptop")))
    with pytest.raises(cli.ColonyError, match="#11 is not yours to free: tester on laptop holds it"):
        testers.findings_free(CONFIG, Namespace(card=11, **as_tester("tester-2 on desktop")))
    assert testers.findings_free(CONFIG, Namespace(card=11, **as_tester("tester on laptop"))) == 0
    assert "#11 is free for another tester" in capsys.readouterr().out
    testers.findings_next(CONFIG, Namespace(**as_tester("tester-2 on desktop")))
    assert capsys.readouterr().out.startswith("yours: #11")


def test_a_tester_is_named_by_its_session_and_computer(monkeypatch):
    monkeypatch.setenv(cli.SESSION_ENV, "tester")
    monkeypatch.setattr(presence, "computer", lambda: "laptop")
    assert testers.me(Namespace()) == "tester on laptop"
    assert testers.me(Namespace(as_name="  qa   one ")) == "qa one"
    with pytest.raises(cli.ColonyError, match="without brackets"):
        testers.me(Namespace(as_name="qa (one)"))


def test_claim_minutes_comes_from_the_testers_table():
    assert testers.claim_minutes({}) == 60
    assert testers.claim_minutes({"testers": {"claim_minutes": 30}}) == 30
    with pytest.raises(cli.ColonyError, match=r"\[testers\] claim_minutes must be a whole number"):
        testers.claim_minutes({"testers": {"claim_minutes": 0}})


# Docs and the tester's brief


def test_the_docs_and_the_testers_brief_name_the_registry_and_the_findings_commands():
    commands = (ROOT / "docs" / "commands.md").read_text()
    for command in ("fixtures", "fixtures add", "fixtures remove", "findings open", "findings next", "findings claim",
                    "findings free", "findings report", "findings show"):
        assert f"`colony {command}" in commands, command
    assert "--new-fixture" in commands
    assert "`claim_minutes`" in (ROOT / "docs" / "configuration.md").read_text()
    brief = (ROOT / "colony" / "prompts" / "tester.md").read_text()
    for step in ("colony fixtures", "colony findings open", "colony findings next", "colony findings report",
                 "colony findings claim", "colony findings free"):
        assert step in brief, step
    assert "gh issue create" not in brief  # testers share one list instead of each filing its own
