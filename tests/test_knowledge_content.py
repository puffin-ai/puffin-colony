"""The knowledge vault's shipped content: the page types, the knowledge rules, the folder templates and their prompts."""

import argparse
import datetime
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from colony import vault

PACKAGE = Path(__file__).resolve().parent.parent / "colony"
KNOWLEDGE = PACKAGE / "knowledge"
TYPES_DIR = KNOWLEDGE / "types"
RULES_DIR = KNOWLEDGE / "rules"
TEMPLATES = KNOWLEDGE / "templates"
# setup.md holds the vault's setup steps, spliced in from the K1 track's setup-knowledge section.
PROMPTS = {name: PACKAGE / "prompts" / f"{name}.md" for name in ("researcher", "spec", "setup")}

PAGE_TYPES = """
architecture archive-record build-checklist building-block decision-record design-spec diagram-type
feature-design feature-requirements feature-spec feature-tasks
glossary-entry idea-spec implementation-plan launch-plan living-spec one-pager owner-checklist
prd readme-page reconciliation-report research-report rule runbook
singleton source tech-design threat-model type-definition
""".split()
RULES = ["authority", "code-documentation", "diagrams", "docs-life-cycle", "naming-and-links", "page-types", "writing"]
TYPE_SECTIONS = ["Send it elsewhere when", "Frontmatter", "Skeleton", "Rules", "Before you publish", "Background"]
RULE_SECTIONS = ["What the rule is", "Why it exists", "What it applies to", "What is exempt", "How it is enforced"]
FOLDERS = ["wiki", "specs", "specs/plans", "specs/checklists", "specs/system", "research", "raw", "archive"]
PLACEHOLDERS = {"product", "knowledge", "apps"}
PROMPT_PLACEHOLDERS = {
    "researcher": {"project", "question", "knowledge"},
    "spec": {"project", "feature", "knowledge"},
    # Setup fills its own names; the vault's, the presets', the playbook's, the briefs' and the hack templates'
    # placeholders appear as text for the setup session to fill.
    "setup": {"package", "dir", "name", "display"} | PLACEHOLDERS
             | {"web_app", "service", "fast_check", "checks", "base", "install", "project", "worktrees"}
             | {"repo", "board", "lead", "demo", "team", "owners"},
}

CONTENT = sorted(KNOWLEDGE.rglob("*.md"))
SHIPPED = CONTENT + sorted(PROMPTS.values()) + [Path(__file__)]


def frontmatter(text: str) -> dict[str, str]:
    """The top-level keys of a page's own frontmatter block."""
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, "the page opens with no frontmatter block"
    return dict(re.findall(r"^([a-z-]+): ?(.*)$", match[1], re.M))


def headings(text: str) -> list[str]:
    return re.findall(r"^#{1,6} (.+?)\s*$", strip_code(text), re.M)


def strip_code(text: str) -> str:
    """The text with fenced blocks and code spans removed, where links and placeholders are examples."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def page(name: str) -> Path | None:
    """The shipped page a wikilink name resolves to: a type, a rule or a template page."""
    for folder in (TYPES_DIR, RULES_DIR, TEMPLATES):
        found = [p for p in folder.rglob(f"{name}.md") if p.name != "README.md"]
        if found:
            return found[0]
    return None


def test_every_page_type_exists_with_frontmatter_and_its_sections():
    assert sorted(p.stem for p in TYPES_DIR.glob("*.md") if p.name != "README.md") == sorted(PAGE_TYPES)
    for name in PAGE_TYPES:
        text = (TYPES_DIR / f"{name}.md").read_text()
        meta = frontmatter(text)
        assert meta.get("type") == "type-definition", name
        for key in ("created", "description", "enforced-by"):
            assert meta.get(key), f"{name} lacks {key}"
        found = [h for h in headings(text) if h in TYPE_SECTIONS]
        assert found == TYPE_SECTIONS, f"{name} has sections {found}"
        assert headings(text)[-1] == "Background", f"{name} must end on its Background"
        block = re.search(r"^## Frontmatter\n+```yaml\n(.*?)```", text, re.S | re.M)
        assert block, f"{name} has no yaml block under Frontmatter"
        assert re.search(rf"^type: {re.escape(name)}\s*$", block[1], re.M), f"{name}'s yaml block names another type"
        for field in ("created:", "description:"):
            assert field in block[1], f"{name}'s yaml block lacks {field}"


def test_the_type_table_and_the_types_readme_list_every_type():
    table = (RULES_DIR / "page-types.md").read_text()
    listed = re.findall(r"^\| \[\[([a-z-]+)\]\]", table, re.M)
    assert sorted(listed) == sorted(PAGE_TYPES)
    readme = (TYPES_DIR / "README.md").read_text()
    assert frontmatter(readme)["type"] == "readme-page"
    for name in PAGE_TYPES:
        assert f"[[{name}]]" in readme, f"the types readme misses {name}"


def test_every_rule_has_its_sections_and_must_lines():
    assert sorted(p.stem for p in RULES_DIR.glob("*.md")) == sorted(RULES)
    for name in RULES:
        text = (RULES_DIR / f"{name}.md").read_text()
        meta = frontmatter(text)
        assert meta.get("type") == "rule" and meta.get("enforced-by") and meta.get("description"), name
        assert [h for h in headings(text) if h in RULE_SECTIONS] == RULE_SECTIONS, name
        must_lines = [line for line in text.splitlines() if re.search(r"\bmust\b", line)]
        assert len(must_lines) >= 3, f"{name} has {len(must_lines)} must lines"


def test_every_folder_template_has_a_readme_that_maps_it():
    for folder in FOLDERS:
        text = (TEMPLATES / folder / "README.md").read_text()
        assert frontmatter(text)["type"] == "readme-page", folder
        assert {"What this folder holds", "Pages"} <= set(headings(text)), folder
    root = (TEMPLATES / "README.md").read_text()
    for folder in ("wiki", "specs", "research", "raw", "archive"):
        assert f"]({folder}/README.md)" in root, f"the root readme does not map {folder}"
    assert "](future-work.md)" in root and "decisions.md" in root
    assert frontmatter((TEMPLATES / "future-work.md").read_text())["type"] == "singleton"
    assert not (TEMPLATES / "decisions").exists(), "decision records live in the wiki's area folders"


def test_decisions_live_in_the_wiki_and_the_log_is_generated():
    authority = (RULES_DIR / "authority.md").read_text()
    wiki = (TEMPLATES / "wiki" / "README.md").read_text()
    for text in (authority, wiki):
        assert "no separate folder of decision records" in text
    assert "`{knowledge}/decisions.md`" in authority and "by hand" in authority
    assert "archive/decisions/" in authority


def test_research_ends_in_rules():
    authority = (RULES_DIR / "authority.md").read_text()
    assert "Research ends in rules" in headings(authority)
    researcher = PROMPTS["researcher"].read_text()
    for phrase in ("research/<topic>-<yyyy-mm>.md", "feeds-rules", "colony needs", "A rule line.", "A check.", "A decision."):
        assert phrase in researcher, phrase


def test_the_spec_agent_asks_for_approval_before_cards():
    spec = PROMPTS["spec"].read_text()
    for phrase in ("feature-requirements.md", "feature-design.md", "feature-tasks.md", "Approve the requirements", "no cards until you approve"):
        assert phrase in spec, phrase


def test_no_file_carries_another_products_names():
    issue = re.compile(r"(?<![\w:&/])#\d+\b|\b(?:issue|PR) \d+\b")
    for path in SHIPPED:
        text = path.read_text()
        if path == Path(__file__):
            text = text.split("def test_no_file_carries", 1)[0]
        assert not re.search(r"glass", text, re.I), f"{path.name} mentions glass"
        assert "Puffin Calendar" not in text, path.name
        assert not issue.search(text), f"{path.name} cites an issue number: {issue.search(text)[0]}"
        if path.is_relative_to(KNOWLEDGE):
            assert "puffin" not in text.lower(), f"{path.name} names Puffin"


def test_every_placeholder_is_a_known_one():
    pattern = re.compile(r"\{([A-Za-z_][\w-]*)\}")
    for path in CONTENT:
        unknown = set(pattern.findall(path.read_text())) - PLACEHOLDERS
        assert not unknown, f"{path.relative_to(KNOWLEDGE)} uses {unknown}"
    for name, path in PROMPTS.items():
        unknown = set(pattern.findall(path.read_text())) - PROMPT_PLACEHOLDERS[name]
        assert not unknown, f"{name}.md uses {unknown}"


@pytest.mark.parametrize("path", CONTENT, ids=lambda p: str(p.relative_to(KNOWLEDGE)))
def test_every_link_resolves(path: Path):
    text = strip_code(path.read_text())
    for target in re.findall(r"\[\[([^\]]+)\]\]", text):
        name, _, heading = target.partition("#")
        assert name != "README", f"{target}: a wikilink never points at a readme"
        found = page(name)
        assert found, f"[[{target}]] resolves to no shipped page"
        if heading:
            assert heading in headings(found.read_text()), f"[[{target}]] names a heading {found.name} lacks"
    if path.is_relative_to(TEMPLATES):
        for link in re.findall(r"\]\(([^)#\s]+\.md)\)", text):
            if path == TEMPLATES / "README.md" and link == vault.LOG:
                continue  # the decision log, which `colony check-docs --index` writes at setup
            assert (path.parent / link).resolve().exists(), f"{path.name} links {link}, which no template holds"


def build_vault(repo: Path, folder: str = "knowledge") -> None:
    """Lay the vault into a repo as setup does: copy, fill the three placeholders, date the pages, write the readme."""
    shutil.copytree(TEMPLATES, repo / folder)
    shutil.copytree(TYPES_DIR, repo / folder / ".types")
    shutil.copytree(RULES_DIR, repo / ".colony" / "rules")
    (repo / "apps" / "web").mkdir(parents=True)
    today = datetime.date.today().isoformat()
    for path in list((repo / folder).rglob("*.md")) + list((repo / ".colony").rglob("*.md")):
        text = path.read_text()
        text = text.replace("{product}", "Acme").replace("{knowledge}", folder).replace("{apps}", "apps/web")
        if ".types" not in path.parts:
            text = re.sub(r"^created: YYYY-MM-DD$", f"created: {today}", text, count=1, flags=re.M)
        path.write_text(text)
    readme = repo / folder / "README.md"
    readme.write_text(re.sub(r"^Acme is <.*>\.$", "Acme is a web app that keeps a team's notes.", readme.read_text(),
                             flags=re.M))


def check(capsys, folder: str = "knowledge", index: bool = False) -> tuple[int, str]:
    args = argparse.Namespace(staged=False, strict=True, index=index)
    code = vault.check_docs({"knowledge": {"vault": folder}}, args)
    return code, capsys.readouterr().out


@pytest.mark.parametrize("folder", ["knowledge", "docs/knowledge"])
def test_a_vault_built_from_the_templates_passes_check_docs_clean(tmp_path, monkeypatch, capsys, folder):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    build_vault(tmp_path, folder)
    assert "{" not in (tmp_path / folder / "README.md").read_text()
    code, out = check(capsys, folder, index=True)
    assert code == 0 and (tmp_path / folder / "decisions.md").is_file(), out
    code, out = check(capsys, folder)
    assert code == 0, out
    assert out.rstrip().endswith("clean"), out
