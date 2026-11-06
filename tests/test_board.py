"""Tests for `colony board`: init and set build the right gh calls, against a stand-in gh on PATH."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import stub_path
from colony import board, cli

GH_STUB = """#!{python}
import json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
args = sys.argv[1:]
with open(here / "calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\\n")
answers_path = here / "answers.json"
answers = json.loads(answers_path.read_text()) if answers_path.exists() else []
words = " ".join(args)
for i, answer in enumerate(answers):
    if answer["match"] in words:
        if answer["once"]:
            del answers[i]
            answers_path.write_text(json.dumps(answers))
        sys.stdout.write(answer["out"])
        sys.exit(answer["code"])
"""
CONFIG = {"project": {"name": "demo", "repo": "acme/demo", "base": "dev", "checks": "make check",
                      "worktrees": "~/trees"},
          "accounts": {"main": {"config_dir": "~/.claude", "person": "ana"}},
          "roles": {role: {"model": "m", "effort": "high"} for role in cli.ROLES}}
NOW = datetime(2026, 11, 5, 14, 5, tzinfo=timezone.utc)


class Gh:
    """The stand-in gh: answer calls whose words hold a match, first match first, and read back every call made."""

    def __init__(self, bin_dir: Path):
        self.bin = bin_dir

    def answer(self, match: str, out="", code: int = 0, once: bool = False) -> None:
        """Answer each later call whose words hold `match` with `out` (a dict or list is JSON) and exit `code`."""
        path = self.bin / "answers.json"
        answers = json.loads(path.read_text()) if path.exists() else []
        text = out if isinstance(out, str) else json.dumps(out)
        answers.append({"match": match, "out": text, "code": code, "once": once})
        path.write_text(json.dumps(answers))

    def calls(self) -> list[list[str]]:
        """Each call's arguments, in order."""
        log = self.bin / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def called(self, *words: str) -> list[list[str]]:
        """The calls that start with these words."""
        return [call for call in self.calls() if call[:len(words)] == list(words)]


@pytest.fixture
def gh(tmp_path, monkeypatch):
    """A temporary HOME, the stand-in gh first on PATH, and a fixed clock."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gh"
    stub.write_text(GH_STUB.replace("{python}", sys.executable))
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", stub_path(bin_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(board, "utcnow", lambda: NOW)
    return Gh(bin_dir)


def field(id, name, data_type="TEXT", options=None):
    """One board field as the fields query answers it."""
    node = {"id": id, "name": name, "dataType": data_type}
    if options is not None:
        node["options"] = [{"id": f"{id}-{i}", "name": opt, "color": "GRAY", "description": ""}
                           for i, opt in enumerate(options)]
    return node


def fields_answer(*nodes):
    """The fields query's answer."""
    return {"data": {"node": {"fields": {"nodes": list(nodes)}}}}


FULL = [field("F1", "Title"), field("F2", "Status", "SINGLE_SELECT", board.STATUS), field("F3", "Lead"),
        field("F4", "Helper"), field("F5", "Size", "SINGLE_SELECT", board.SIZES), field("F6", "Last update")]
LISTED = {"projects": [{"number": 3, "id": "PVT_3", "title": "Colony: demo", "closed": False,
                        "url": "https://github.com/orgs/acme/projects/3"}]}


def parse(*argv):
    """Parse a `colony board ...` command line the way cli.py will, through board.add_commands."""
    parser = argparse.ArgumentParser()
    board.add_commands(parser.add_subparsers(dest="command"))
    return parser.parse_args(list(argv))


def test_init_makes_the_board_links_it_and_adds_its_five_fields_with_their_options(gh, capsys):
    gh.answer("project list", {"projects": []})
    gh.answer("project create", {"number": 7, "id": "PVT_7", "url": "https://github.com/orgs/acme/projects/7"})
    gh.answer("fields(first", fields_answer(field("F1", "Title"),
                                            field("F2", "Status", "SINGLE_SELECT", ("Todo", "In Progress", "Done"))))
    gh.answer("updateProjectV2Field", {"data": {"updateProjectV2Field": {"projectV2Field": {"id": "F2"}}}})
    args = parse("board", "init")
    assert args.run(CONFIG, args) == 0

    assert gh.called("project", "create") == [["project", "create", "--owner", "acme", "--title", "Colony: demo",
                                               "--format", "json"]]
    assert gh.called("project", "link") == [["project", "link", "7", "--owner", "acme", "--repo", "demo"]]
    created = gh.called("project", "field-create")
    assert [call[call.index("--name") + 1] for call in created] == ["Lead", "Helper", "Size", "Last update"]
    size = next(call for call in created if "Size" in call)
    assert size[-4:] == ["--data-type", "SINGLE_SELECT", "--single-select-options", "S,M,L"]
    assert next(call for call in created if "Helper" in call)[-2:] == ["--data-type", "TEXT"]
    assert list(board.FIELDS) == ["Status", "Lead", "Helper", "Size", "Last update"]
    # Status keeps its options' ids, so no card loses its value, takes the playbook's spelling, and gains In review.
    mutation = next(call for call in gh.called("api", "graphql") if "updateProjectV2Field" in " ".join(call))
    query = mutation[mutation.index("-f") + 1]
    assert 'id: "F2-0", name: "To do"' in query and 'id: "F2-1", name: "In progress"' in query
    assert 'name: "In review", color: YELLOW' in query and 'id: "F2-2", name: "Done"' in query
    assert "field=F2" in mutation
    out = capsys.readouterr().out
    assert "made the board Colony: demo: https://github.com/orgs/acme/projects/7" in out


def test_init_on_a_board_that_has_every_field_changes_nothing(gh, capsys):
    gh.answer("project list", LISTED)
    gh.answer("fields(first", fields_answer(*FULL))
    args = parse("board", "init")
    assert args.run(CONFIG, args) == 0
    assert not gh.called("project", "create") and not gh.called("project", "field-create")
    assert not [call for call in gh.calls() if "updateProjectV2Field" in " ".join(call)]
    assert "found the board" in capsys.readouterr().out


def test_set_adds_the_card_and_sets_each_field_and_stamps_last_update(gh, capsys):
    gh.answer("project list", LISTED)
    gh.answer("fields(first", fields_answer(*FULL))
    gh.answer("project item-add", {"id": "PVTI_12"})
    args = parse("board", "set", "#12", "status=in progress", "Helper=builder-2", "size=m")
    assert args.run(CONFIG, args) == 0

    assert gh.called("project", "item-add") == [["project", "item-add", "3", "--owner", "acme", "--url",
                                                 "https://github.com/acme/demo/issues/12", "--format", "json"]]
    edits = gh.called("project", "item-edit")
    head = ["project", "item-edit", "--project-id", "PVT_3", "--id", "PVTI_12", "--field-id"]
    assert edits == [head + ["F2", "--single-select-option-id", "F2-1"],
                     head + ["F4", "--text", "builder-2"],
                     head + ["F5", "--single-select-option-id", "F5-1"],
                     head + ["F6", "--text", "2026-11-05 14:05 UTC"]]
    assert capsys.readouterr().out.strip() == ("#12 Status=in progress, Helper=builder-2, Size=m, "
                                               "Last update=2026-11-05 14:05 UTC")


def test_set_clears_a_field_given_no_value_and_stamps_last_update_on_now(gh):
    gh.answer("project list", LISTED)
    gh.answer("fields(first", fields_answer(*FULL))
    gh.answer("project item-add", {"id": "PVTI_4"})
    args = parse("board", "set", "4", "Helper=", "last_update=now")
    args.run(CONFIG, args)
    edits = gh.called("project", "item-edit")
    assert edits[0][-3:] == ["--field-id", "F4", "--clear"]
    assert edits[1][-2:] == ["--text", "2026-11-05 14:05 UTC"]
    assert len(edits) == 2


@pytest.mark.parametrize("pair, message", [("Colour=red", "no field 'Colour'"),
                                           ("Size=XL", "Size has no option 'XL': choose from S, M, L")])
def test_set_checks_every_name_and_value_before_it_writes_anything(gh, pair, message):
    gh.answer("project list", LISTED)
    gh.answer("fields(first", fields_answer(*FULL))
    args = parse("board", "set", "12", "Helper=builder-2", pair)
    with pytest.raises(cli.ColonyError, match=message):
        args.run(CONFIG, args)
    assert not gh.called("project", "item-add") and not gh.called("project", "item-edit")


@pytest.mark.parametrize("old", ["State=working", "Builder=builder-2", "Tier=SMALL", "Account=main", "Branch=b/12"])
def test_set_refuses_a_field_the_five_field_board_dropped_even_on_an_old_board_that_has_it(gh, old):
    gh.answer("project list", LISTED)
    gh.answer("fields(first", fields_answer(*FULL, field("F9", old.split("=")[0])))
    args = parse("board", "set", "12", old)
    with pytest.raises(cli.ColonyError, match="choose from Status, Lead, Helper, Size, Last update"):
        args.run(CONFIG, args)
    assert gh.calls() == []


def test_set_without_a_board_says_to_make_it(gh):
    gh.answer("project list", {"projects": [{"number": 1, "id": "P", "title": "Other", "closed": False}]})
    args = parse("board", "set", "12", "Status=Done")
    with pytest.raises(cli.ColonyError, match="run `colony board init`"):
        args.run(CONFIG, args)


def test_a_failing_board_call_names_the_project_scope(gh):
    gh.answer("project list", "", code=1)
    with pytest.raises(cli.ColonyError, match="gh auth refresh -s project"):
        board.find_board(CONFIG)


def test_board_number_in_the_config_names_the_project(gh):
    gh.answer("project view 9", {"number": 9, "id": "PVT_9", "url": "u"})
    assert board.find_board({**CONFIG, "board": {"number": 9}}) == {"number": 9, "id": "PVT_9", "url": "u"}
    assert not gh.called("project", "list")


def test_set_takes_field_value_pairs_and_refuses_a_bare_word():
    assert board.parse_pairs(["Status=In  progress", "Helper="]) == [("Status", "In progress"), ("Helper", "")]
    with pytest.raises(cli.ColonyError, match="not field=value"):
        board.parse_pairs(["working"])
    with pytest.raises(SystemExit):
        parse("board", "set", "twelve", "Status=Done")


def test_last_update_reads_back_what_set_writes():
    assert board.read_stamp(board.stamp(NOW)) == NOW
    assert board.read_stamp("") is None and board.read_stamp("soon") is None


def test_the_board_title_comes_from_the_config_else_the_project_name():
    from colony import board
    assert board.title({"project": {"name": "demo"}}) == "Colony: demo"
    assert board.title({"project": {"name": "demo"}, "board": {"title": "Demo Colony"}}) == "Demo Colony"
