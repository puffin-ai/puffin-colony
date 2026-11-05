"""Tests for `colony check-docs`: each test writes a small vault into a temporary git repo, breaks one rule, and reads
what the run prints and returns."""
import argparse
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from colony import cli, vault

TYPES = ("readme-page", "living-spec", "decision-record", "rule", "research-report", "singleton")
LONG = ("The planner reads every calendar the person connects and keeps each event it finds in one list, so a "
        "later step can place new work around them without asking twice.")


def page(kind: str, body: str, created: str = "2026-11-02", description: str = "A page for the tests.") -> str:
    """One vault page with frontmatter."""
    return f"---\ntype: {kind}\ncreated: {created}\ndescription: {description}\n---\n\n{body}\n"


def readme(title: str, *items: str) -> str:
    """A README that lists the given links under ## Pages."""
    return page("readme-page", f"# {title}\n\nThe folder's map.\n\n## Pages\n\n" + "".join(f"- {i}\n" for i in items))


BASE = {
    "knowledge/README.md": readme("Knowledge", "[[alpha]]: the first page.", "[The wiki](wiki/README.md)"),
    "knowledge/alpha.md": page("living-spec", "# Alpha\n\n## Scope\n\nThe app starts in `src/app.py:3`.\n\n"
                                              "See [[beta#Usage]] and [the wiki](wiki/README.md#pages)."),
    "knowledge/wiki/README.md": readme("Wiki", "[[beta]]: the second page."),
    "knowledge/wiki/beta.md": page("living-spec", "# Beta\n\n## Usage\n\nBack to [[alpha]]."),
    "src/app.py": "print('hi')\n",
}
NO_LOG = {"decision_log": "off"}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """An empty git repo as the working folder."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write(root: Path, files: dict, types=TYPES) -> None:
    """The base vault with `files` laid over it (None removes a base file), and a .types/ file per type."""
    for name, text in {**BASE, **files}.items():
        if text is not None:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)
    for kind in types:
        (root / "knowledge/.types").mkdir(parents=True, exist_ok=True)
        (root / f"knowledge/.types/{kind}.md").write_text(f"# {kind}\n")


def run(capsys, knowledge=None, **flags) -> tuple[int, str]:
    """One `colony check-docs` run, with its exit code and what it printed."""
    args = Namespace(staged=flags.get("staged", False), strict=flags.get("strict", False),
                     index=flags.get("index", False))
    code = vault.check_docs({"knowledge": knowledge or {}}, args)
    return code, capsys.readouterr().out


def checked(repo, capsys, files=None, knowledge=None, **flags) -> tuple[int, str]:
    """Write the vault, then run the checks on it."""
    write(repo, files or {})
    return run(capsys, knowledge, **flags)


def test_a_clean_vault_passes_and_counts_every_check(repo, capsys):
    code, out = checked(repo, capsys)
    assert code == 0, out
    tally = next(line for line in out.splitlines() if line.startswith("check-docs: page_types"))
    for name, mode in vault.CHECKS.items():
        assert f"{name} 0" + (" (warn)" if mode == "warn" else "") in tally
    assert "4 page(s) clean" in out


def test_every_check_fails_by_default_but_the_size_caps():
    modes = vault.read_settings({}).modes
    assert modes == vault.CHECKS
    assert {name for name, mode in modes.items() if mode != "fail"} == {"size_caps"}
    assert modes["size_caps"] == "warn"
    assert vault.read_settings({}).vault == "knowledge"


# page_types

def test_a_page_with_no_type_fails(repo, capsys):
    code, out = checked(repo, capsys, {"knowledge/wiki/beta.md": "# Beta\n\n## Usage\n\nBack to [[alpha]].\n"})
    assert code == 1
    assert "knowledge/wiki/beta.md: page declares no type" in out


def test_a_type_the_types_folder_lacks_fails(repo, capsys):
    code, out = checked(repo, capsys, {"knowledge/wiki/beta.md": page("glossary", "# Beta\n\n## Usage\n\n[[alpha]]")})
    assert code == 1
    assert "declares the type glossary, which knowledge/.types/ does not define" in out


def test_without_a_types_folder_any_declared_type_counts(repo, capsys):
    write(repo, {"knowledge/wiki/beta.md": page("glossary", "# Beta\n\n## Usage\n\n[[alpha]]")}, types=())
    code, out = run(capsys)
    assert code == 0, out
    write(repo, {"knowledge/wiki/beta.md": "# Beta\n\n## Usage\n\n[[alpha]]\n"}, types=())
    code, out = run(capsys)
    assert code == 1 and "page declares no type" in out


# links

@pytest.mark.parametrize("link, message", [
    ("[[gone]]", "wikilink resolves to no page: [[gone]]"),
    ("[[beta#Nowhere]]", "wikilink names no heading on that page: [[beta#Nowhere]]"),
    ("[[README]]", "wikilink names a README"),
    ("[old](old.md)", "link resolves to no file: old.md"),
    ("[the wiki](wiki/README.md#nowhere)", "link names no heading on that page: wiki/README.md#nowhere"),
])
def test_a_link_that_resolves_to_nothing_fails(repo, capsys, link, message):
    code, out = checked(repo, capsys, {"knowledge/alpha.md": page("living-spec", f"# Alpha\n\n[[beta]] and {link}")})
    assert code == 1
    assert f"knowledge/alpha.md:9: {message}" in out


def test_links_to_types_headings_paths_and_inside_code_pass(repo, capsys):
    body = ("# Alpha\n\n## Here\n\n[[beta|the second page]], [[#Here]], [[wiki/beta]], [[living-spec]] and "
            "[top](../README.md).\n\nAn example: `[[gone]]`.\n\n```\n[[gone]]\n```")
    write(repo, {"README.md": "[vault](knowledge/README.md)\n"})
    code, out = checked(repo, capsys, {"knowledge/alpha.md": page("living-spec", body)})
    assert code == 0, out


def test_a_wikilink_to_a_rule_outside_the_vault_resolves(repo, capsys):
    files = {".colony/rules/authority.md": "# Authority\n\n## Where truth lives\n\nText.\n",
             "knowledge/alpha.md": page("living-spec", "# Alpha\n\n[[beta]] and [[authority#Where truth lives]]")}
    code, out = checked(repo, capsys, files)
    assert code == 0, out
    code, out = checked(repo, capsys, {"knowledge/alpha.md": page("living-spec", "# Alpha\n\n[[beta]] [[authority#No]]")})
    assert code == 1 and "wikilink names no heading on that page: [[authority#No]]" in out


def test_two_pages_with_one_name_fail(repo, capsys):
    code, out = checked(repo, capsys, {"knowledge/wiki/alpha.md": page("living-spec", "# Alpha again\n\n[[beta]]"),
                                       "knowledge/wiki/README.md": readme("Wiki", "[[beta]]", "[a](alpha.md)")})
    assert code == 1
    assert "another page has the name alpha, so [[alpha]] is ambiguous" in out


# orphans

def test_a_page_no_other_page_links_fails(repo, capsys):
    files = {"knowledge/notes/gamma.md": page("living-spec", "# Gamma\n\n[[alpha]]"),
             "knowledge/notes/delta.md": page("living-spec", "# Delta\n\n[[gamma]]"),
             "knowledge/README.md": readme("Knowledge", "[[alpha]]", "[The wiki](wiki/README.md)", "[[gamma]]")}
    code, out = checked(repo, capsys, files)
    assert code == 1
    assert "knowledge/notes/delta.md: no other page links to this page" in out
    assert "gamma.md: no other" not in out and "readme_maps 0" in out


# readme_maps

def test_a_readme_that_leaves_out_a_page_beside_it_fails(repo, capsys):
    files = {"knowledge/wiki/gamma.md": page("living-spec", "# Gamma\n\n[[alpha]]"),
             "knowledge/alpha.md": page("living-spec", "# Alpha\n\n[[beta]] and [[gamma]]")}
    code, out = checked(repo, capsys, files)
    assert code == 1
    assert "knowledge/wiki/README.md: the README does not list gamma.md" in out
    assert "orphans 0" in out


def test_a_readme_that_leaves_out_a_subfolder_fails(repo, capsys):
    files = {"knowledge/wiki/area/gamma.md": page("living-spec", "# Gamma\n\n[[alpha]]"),
             "knowledge/alpha.md": page("living-spec", "# Alpha\n\n[[beta]] and [[gamma]]")}
    code, out = checked(repo, capsys, files)
    assert code == 1
    assert "the README does not list area/" in out


# code_paths

def test_a_live_page_that_names_a_missing_path_fails(repo, capsys):
    code, out = checked(repo, capsys, {"knowledge/alpha.md": page("living-spec", "# Alpha\n\n[[beta]] `src/gone.py`")})
    assert code == 1
    assert "knowledge/alpha.md:9: code path does not exist: src/gone.py" in out


def test_a_research_report_and_a_span_that_is_no_path_pass(repo, capsys):
    report = page("research-report", "# Report\n\nIt read `src/gone.py` once, and `origin/main` and `a b/c`.")
    files = {"knowledge/research/report.md": report,
             "knowledge/README.md": readme("Knowledge", "[[alpha]]", "[The wiki](wiki/README.md)", "[[report]]"),
             "knowledge/alpha.md": page("living-spec", "# Alpha\n\n[[beta]], `origin/main`, `src/*.py`, `src/`")}
    code, out = checked(repo, capsys, files)
    assert code == 0, out


# size_caps and dated_caps

def padded(created: str) -> dict:
    """Alpha grown past a 200-character cap."""
    return {"knowledge/alpha.md": page("living-spec", "# Alpha\n\n[[beta]]\n\n" + "word " * 60, created)}


def test_a_page_over_its_types_cap_warns_and_fails_with_strict(repo, capsys):
    code, out = checked(repo, capsys, padded("2026-11-02"), {"caps": {"living-spec": 200}})
    assert code == 0, out
    assert "knowledge/alpha.md: warning: a living-spec holds" in out and "over its cap of 200" in out
    assert "size_caps 1 (warn)" in out
    code, out = run(capsys, {"caps": {"living-spec": 200}}, strict=True)
    assert code == 1 and "size_caps 1" in out


def test_a_readme_over_its_cap_above_its_pages_warns(repo, capsys):
    files = {"knowledge/wiki/README.md": page("readme-page", "# Wiki\n\n" + "intro " * 20 + "\n\n## Pages\n\n- [[beta]]")}
    code, out = checked(repo, capsys, files, {"caps": {"readme-page": 60}})
    assert code == 0
    assert "knowledge/wiki/README.md: warning: the README holds" in out and "above ## Pages" in out


def test_a_page_created_since_a_dated_cap_fails(repo, capsys):
    cap = {"caps": {"living-spec": {"chars": 200, "from": "2026-11-01"}}}
    code, out = checked(repo, capsys, padded("2026-11-02"), cap)
    assert code == 1
    assert "which holds every living-spec created on or after 2026-11-01" in out
    assert "dated_caps 1" in out and "size_caps 0" in out


def test_a_page_older_than_its_dated_cap_only_warns(repo, capsys):
    cap = {"caps": {"living-spec": {"chars": 200, "from": "2026-11-01"}}}
    code, out = checked(repo, capsys, padded("2026-10-01"), cap)
    assert code == 0, out
    assert "dated_caps 0" in out and "size_caps 1 (warn)" in out


# copied_text

def test_a_paragraph_on_two_pages_fails(repo, capsys):
    files = {"knowledge/alpha.md": page("living-spec", f"# Alpha\n\n[[beta]]\n\n{LONG}"),
             "knowledge/wiki/beta.md": page("living-spec", f"# Beta\n\n## Usage\n\n[[alpha]]\n\n- {LONG}")}
    code, out = checked(repo, capsys, files)
    assert code == 1
    assert "knowledge/wiki/beta.md:13: a paragraph also stands in knowledge/alpha.md" in out


def test_a_short_shared_line_and_a_quote_pass(repo, capsys):
    files = {"knowledge/alpha.md": page("living-spec", f"# Alpha\n\n[[beta]]\n\nThe planner reads calendars.\n\n> {LONG}"),
             "knowledge/wiki/beta.md": page("living-spec", f"# Beta\n\n## Usage\n\n[[alpha]]\n\nThe planner reads "
                                                           f"calendars.\n\n> {LONG}")}
    code, out = checked(repo, capsys, files)
    assert code == 0, out


# rule_budget

def test_a_rule_past_its_budget_fails(repo, capsys):
    files = {".colony/rules/conduct.md": "# Conduct\n\n" + "Report failure as failure. " * 5}
    code, out = checked(repo, capsys, files, {"rule_chars": 50})
    assert code == 1
    assert ".colony/rules/conduct.md: the rule holds" in out and "over its budget of 50" in out
    code, out = run(capsys, {"rule_chars": 50, "rule_budgets": {"conduct": 500}})
    assert code == 0, out


def test_a_vault_page_of_type_rule_has_a_budget_too(repo, capsys):
    files = {"knowledge/wiki/writing.md": page("rule", "# Writing\n\n[[alpha]] " + "Write short. " * 10),
             "knowledge/wiki/README.md": readme("Wiki", "[[beta]]", "[[writing]]")}
    code, out = checked(repo, capsys, files, {"rule_chars": 100})
    assert code == 1 and "knowledge/wiki/writing.md: the rule holds" in out


# replaced_records

def records(old_opening: str, old_folder: str = "wiki", new_opening: str = "This record replaces [[old-call]].") -> dict:
    """An old and a new decision record, each listed by its folder's README."""
    files = {f"knowledge/{old_folder}/old-call.md": page("decision-record", f"# Old call\n\n{old_opening}\n\n## Context"),
             "knowledge/wiki/new-call.md": page("decision-record", f"# New call\n\n{new_opening}\n\n## Context"),
             "knowledge/wiki/README.md": readme("Wiki", "[[beta]]", "[[new-call]]", "[[old-call]]")}
    if old_folder != "wiki":
        files["knowledge/README.md"] = readme("Knowledge", "[[alpha]]", "[The wiki](wiki/README.md)", "[[old-call]]")
    return files


def test_a_replaced_record_that_does_not_say_so_fails(repo, capsys):
    code, out = checked(repo, capsys, records("We used files."), NO_LOG)
    assert code == 1
    assert ("knowledge/wiki/old-call.md: knowledge/wiki/new-call.md replaces this record, so it must open with a "
            "line that names it: Replaced by [[new-call]]") in out


def test_a_record_replaced_in_full_outside_the_archive_fails(repo, capsys):
    code, out = checked(repo, capsys, records("Replaced by [[new-call]]."), NO_LOG)
    assert code == 1
    assert "knowledge/wiki/old-call.md: a decision record replaced in full belongs in knowledge/archive/" in out


def test_a_record_that_says_it_is_replaced_but_links_nothing_fails(repo, capsys):
    code, out = checked(repo, capsys, records("This was replaced last week.", new_opening="We use a database."), NO_LOG)
    assert code == 1 and "opens by saying it is replaced but links no replacement" in out


def test_a_replacement_outside_the_vault_and_a_record_cited_after_the_first_sentence_pass(repo, capsys):
    files = records("Replaced on one point by [the owner's answer](https://example.com/answer), and the rest stands.",
                    new_opening="This record replaces [[beta]]. The old rule still holds under [[old-call]].")
    files["knowledge/wiki/beta.md"] = page("decision-record", "# Beta\n\nReplaced in part by [[new-call]], on its "
                                                              "order.\n\n## Usage\n\n[[alpha]]")
    code, out = checked(repo, capsys, files, NO_LOG)
    assert code == 0, out


def test_a_record_replaced_in_full_in_the_archive_passes(repo, capsys):
    code, out = checked(repo, capsys, records("Replaced by [[new-call]].", old_folder="archive"), NO_LOG)
    assert code == 0, out


def test_a_record_replaced_in_part_stays(repo, capsys):
    opening = "Its retry rule is replaced by [[new-call]], and every other call here stands."
    code, out = checked(repo, capsys, records(opening), NO_LOG)
    assert code == 0, out


# decision_log

LOG_FILES = {
    "knowledge/wiki/calendar/use-db.md": page("decision-record", "# Use a database\n\nThis record replaces "
                                              "[[use-files]].", description="We store events in a database. Since 1."),
    "knowledge/wiki/calendar/pick-a-week.md": page("decision-record", "# Weeks start on Monday",
                                                   description=">\n  Weeks start on Monday.\n  Always."),
    "knowledge/archive/use-files.md": page("decision-record", "# Use files\n\nReplaced by [[use-db]].",
                                           description="We stored events in files."),
    "knowledge/archive/old-thing.md": page("decision-record", "# Old thing", description="An old thing."),
    "knowledge/wiki/ship-on-fridays.md": page("decision-record", "# Ship on Fridays", description="We ship on Fridays."),
}
LOG_BODY = """
## Calendar

- [[pick-a-week]]: Weeks start on Monday.
- [[use-db]]: We store events in a database.
- [[use-files]]: We stored events in files. (replaced by [[use-db]])

## General

- [[ship-on-fridays]]: We ship on Fridays.
- [[old-thing]]: An old thing. (replaced)
"""
QUIET = {"orphans": "off", "readme_maps": "off"}


def test_a_full_run_writes_the_decision_log_by_area_active_first(repo, capsys):
    code, out = checked(repo, capsys, LOG_FILES, QUIET)
    assert code == 1
    assert "knowledge/decisions.md: decisions.md was missing, so this run rewrote it" in out
    log = (repo / "knowledge/decisions.md").read_text()
    head = f"---\ntype: singleton\ndescription: {vault.LOG_DESCRIPTION}\n---\n\n# Decisions\n\n{vault.LOG_NOTICE}\n"
    assert log == head + LOG_BODY
    code, out = run(capsys, QUIET)
    assert code == 0, out
    assert "decision_log 0" in out


def test_a_hand_edited_decision_log_fails_and_is_rewritten(repo, capsys):
    checked(repo, capsys, LOG_FILES, QUIET)
    log = repo / "knowledge/decisions.md"
    generated = log.read_text()
    log.write_text(generated + "- [[ship-on-fridays]]: An extra line.\n")
    code, out = run(capsys, QUIET)
    assert code == 1
    assert "decisions.md was not what the decision records generate" in out
    assert log.read_text() == generated


def test_index_only_writes_the_log(repo, capsys):
    files = {**LOG_FILES, "knowledge/alpha.md": page("living-spec", "# Alpha\n\n[[gone]]")}
    code, out = checked(repo, capsys, files, index=True)
    assert code == 0, out
    assert out.strip() == "check-docs: wrote knowledge/decisions.md, 5 decision record(s)"
    assert (repo / "knowledge/decisions.md").is_file()


def test_no_log_without_records_or_with_the_check_off(repo, capsys):
    code, out = checked(repo, capsys)
    assert code == 0 and not (repo / "knowledge/decisions.md").exists()
    code, out = checked(repo, capsys, LOG_FILES, {**QUIET, "decision_log": "off"})
    assert "decision_log off" in out and not (repo / "knowledge/decisions.md").exists()


# modes and settings

def test_a_check_set_off_or_warn_does_not_fail_the_run(repo, capsys):
    files = {"knowledge/alpha.md": page("living-spec", "# Alpha\n\n[[beta]] [[gone]]")}
    code, out = checked(repo, capsys, files, {"links": "off"})
    assert code == 0 and "links off" in out and "gone" not in out
    code, out = run(capsys, {"links": "warn"})
    assert code == 0 and "warning: wikilink resolves to no page: [[gone]]" in out
    code, out = run(capsys, {"links": "warn"}, strict=True)
    assert code == 1


@pytest.mark.parametrize("knowledge, message", [
    ({"orphan": "off"}, "has no check 'orphan'"),
    ({"links": "loud"}, "links must be off, warn or fail"),
    ({"caps": {"living-spec": "big"}}, "caps.living-spec must be a whole number"),
    ({"rules": ".colony/rules"}, "rules must be a list of strings"),
])
def test_a_bad_setting_is_an_error(knowledge, message):
    with pytest.raises(cli.ColonyError, match=message):
        vault.read_settings({"knowledge": knowledge})


def test_the_vault_folder_comes_from_the_config(repo, capsys):
    for name, text in BASE.items():
        target = repo / name.replace("knowledge/", "docs/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    code, out = run(capsys, {"vault": "docs/"})
    assert code == 0, out
    with pytest.raises(cli.ColonyError, match="no vault at knowledge/"):
        run(capsys)


# --staged

def stage(repo: Path, *names: str) -> None:
    subprocess.run(["git", "add", *names], cwd=repo, check=True)


def test_staged_checks_only_the_staged_pages(repo, capsys):
    write(repo, {"knowledge/alpha.md": page("living-spec", "# Alpha\n\n[[beta]] [[gone]]")})
    stage(repo, "knowledge/wiki/beta.md")
    code, out = run(capsys, staged=True)
    assert code == 0, out
    assert "1 staged page(s) clean" in out
    stage(repo, "knowledge/alpha.md")
    code, out = run(capsys, staged=True)
    assert code == 1 and "wikilink resolves to no page: [[gone]]" in out


def test_staged_skips_the_whole_vault_checks_and_writes_no_log(repo, capsys):
    write(repo, {**LOG_FILES, "knowledge/wiki/lonely.md": page("living-spec", "# Lonely\n\n[[alpha]]")})
    stage(repo, "knowledge/wiki/lonely.md")
    code, out = run(capsys, staged=True)
    assert code == 0, out
    assert "orphans" not in out.splitlines()[0]
    assert "--staged skips orphans, readme_maps, copied_text, replaced_records, decision_log" in out
    assert not (repo / "knowledge/decisions.md").exists()


def test_staged_with_no_staged_page_passes(repo, capsys):
    write(repo, {})
    stage(repo, "src/app.py")
    code, out = run(capsys, staged=True)
    assert code == 0 and out.strip() == "check-docs: no staged pages"


def test_add_commands_routes_check_docs():
    parser = argparse.ArgumentParser()
    vault.add_commands(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["check-docs", "--staged", "--strict"])
    assert args.run is vault.check_docs and args.staged and args.strict and not args.index
