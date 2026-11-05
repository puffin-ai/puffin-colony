"""Tests for the presets' three rule levels (core, essentials, rules) and the skills the package ships."""
import re
from importlib import resources
from pathlib import Path

import pytest

from colony import cli, guards

PACKAGE = Path(str(resources.files("colony")))
PRESETS = PACKAGE / "presets"
SKILLS = PACKAGE / "skills"
LEAN_RULES = ("coding", "testing", "security", "performance", "accessibility", "git", "conversation", "skills")
PUFFIN_RULES = ("performance", "full-stack", "accessibility", "coding", "design-principles", "testing",
                "performance-service", "security-and-privacy", "database", "commits", "pull-requests", "writing",
                "docs", "conversation", "skills")
HONESTY = ("Report a failure as a failure", "Quote the output behind every success claim", "Never weaken a check",
           "Keep secrets out of output", "Add, remove or upgrade no dependency", "spend no money")
POINTERS = (".colony/rules/", "AGENTS.md", ".colony/playbook.md", "conversation.md", "skills.md")
PLACEHOLDER = re.compile(r"\{([A-Za-z_][\w-]*)\}")


def files(preset: str) -> list[Path]:
    return sorted(path for path in (PRESETS / preset).rglob("*") if path.is_file())


def shipped_skills() -> list[str]:
    return sorted(path.name for path in SKILLS.iterdir() if path.is_dir() and not path.name.startswith((".", "_")))


@pytest.mark.parametrize("preset", ["lean", "puffin"])
def test_each_preset_holds_the_three_levels(preset):
    root = PRESETS / preset
    assert sorted(path.name for path in root.iterdir() if not path.name.startswith(".")) == [
        "core.md", "essentials", "rules"]
    assert list((root / "essentials").glob("*.md")) and list((root / "rules").glob("*.md"))


@pytest.mark.parametrize("preset", ["lean", "puffin"])
def test_each_core_is_under_1500_words_holds_the_honesty_duties_and_points_to_the_other_levels(preset):
    text = (PRESETS / preset / "core.md").read_text()
    assert len(text.split()) < 1500
    for line in HONESTY + POINTERS:
        assert line in text, line


@pytest.mark.parametrize("preset", ["lean", "puffin"])
def test_every_rule_a_core_or_an_essentials_file_names_ships_in_its_preset(preset):
    shipped = {path.name for path in (PRESETS / preset / "rules").glob("*.md")}
    for path in [PRESETS / preset / "core.md", *sorted((PRESETS / preset / "essentials").glob("*.md"))]:
        for named in re.findall(r"`([\w-]+\.md)`", path.read_text()):
            assert named in shipped | {"CLAUDE.md", "AGENTS.md", "SKILL.md"}, (path.name, named)


@pytest.mark.parametrize("path", [path for preset in ("lean", "puffin")
                                  for path in sorted((PRESETS / preset / "essentials").glob("*.md"))],
                         ids=lambda path: f"{path.parent.parent.name}-{path.stem}")
def test_each_essentials_file_numbers_its_must_lines_and_each_line_names_its_rule(path):
    lines = re.findall(r"^(\d+)\. (.+)$", path.read_text(), re.M)
    assert len(lines) >= 5
    assert [int(number) for number, _ in lines] == list(range(1, len(lines) + 1))
    for _, line in lines:
        assert line.startswith(("You must", "A GET must")), line
        assert re.search(r"\(`[^`]+\.md`", line), line
    assert "`.colony/rules/`" in path.read_text()


def test_the_lean_preset_holds_its_rules_and_one_essentials_template():
    assert sorted(path.stem for path in (PRESETS / "lean" / "rules").iterdir()) == sorted(LEAN_RULES)
    assert [path.name for path in (PRESETS / "lean" / "essentials").iterdir()] == ["generic.md"]


@pytest.mark.parametrize("name", LEAN_RULES)
def test_each_lean_rule_is_short_and_has_must_and_must_not_lines(name):
    text = (PRESETS / "lean" / "rules" / f"{name}.md").read_text()
    assert len(text.split()) < 400
    assert "## Must\n" in text and "## Must not\n" in text


def test_the_puffin_preset_ships_every_rule_its_essentials_and_its_core():
    names = {path.relative_to(PRESETS / "puffin").as_posix() for path in files("puffin")}
    assert names == {f"rules/{rule}.md" for rule in PUFFIN_RULES} | {
        "essentials/nextjs.md", "essentials/fastapi.md", "essentials/generic.md", "core.md"}


def test_the_lean_files_hold_no_vault_links_no_product_and_only_the_check_placeholders():
    for path in files("lean"):
        text = path.read_text()
        assert "[[" not in text and "glass" not in text.lower() and "puffin calendar" not in text.lower(), path
        assert set(PLACEHOLDER.findall(text)) <= {"fast_check", "checks"}, path


@pytest.mark.parametrize("preset", ["lean", "puffin"])
def test_each_skills_rule_names_every_shipped_skill(preset):
    text = (PRESETS / preset / "rules" / "skills.md").read_text()
    for name in shipped_skills():
        assert f"`{name}`" in text, name


@pytest.mark.parametrize("name", shipped_skills())
def test_every_shipped_skill_has_a_skill_md_with_its_name_and_a_description(name):
    folder = SKILLS / name
    assert [path.name for path in folder.iterdir() if not path.name.startswith(".")] == ["SKILL.md"]
    text = (folder / "SKILL.md").read_text()
    front = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert front, name
    fields = dict(line.split(": ", 1) for line in front[1].splitlines())
    assert fields["name"] == name
    description = fields["description"]
    assert len(description) > 40 and "Use when" in description, name
    assert description[0].isalpha() and ": " not in description and " #" not in description, name  # plain YAML
    assert "[[" not in text and "glass" not in text.lower() and "puffin calendar" not in text.lower(), name
    assert not re.search(r"\]\((?!https?://)", text), name  # a link to a sibling file the package doesn't ship


def test_the_starter_set_is_every_shipped_skill_beside_the_role_skills():
    assert set(guards.STARTER_SKILLS) == set(shipped_skills()) - set(cli.ROLE_SKILLS) - {cli.SETUP_SKILL}
    assert len(guards.STARTER_SKILLS) == 10
