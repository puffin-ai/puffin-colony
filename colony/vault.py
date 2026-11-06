"""`colony check-docs`: the knowledge vault's checks, each one off, note, warn or fail.

Generalized from Puffin Calendar's tools/check_vault.py. The vault is `knowledge/` at the repo root, or the folder
`[knowledge] vault` names in .colony/colony.toml. Its page types are the file names in its `.types/` folder, where
setup copies them. Without that folder, any `type:` a page declares counts. Each check takes its mode from
`[knowledge]`, such as `orphans = "warn"`. Every check fails by default except `size_caps`, which warns.
`--strict` fails on the warnings too, apart from a check set to `note`, which warns even then. `--staged` checks only the staged pages, with the checks that read one page at
a time, for a pre-commit hook. Every run ends with a count per check.

A repo adds its own checks as plug-ins: `[knowledge] plugins` lists Python files in the repo, each with a `CHECKS`
table of its checks and their default modes, an optional `ONE_PAGE` tuple of the ones `--staged` runs, and
`run(check, repo, vault, files)`, which returns the check's problems as (path, line, message). `files` is the set of
staged files under `--staged`, else None: a plug-in runs under `--staged` whenever any file is staged, so it can check files outside the vault. A plug-in check takes its mode from `[knowledge]` like a built-in one, and
counts in the same tally.

Every full run, and `--index` alone, also rewrites the decision log, `<vault>/decisions.md`, from the decision
records. The run fails when the log it found differed, so a stale or hand-edited log never lands.
Python 3.11+ standard library only.
"""
from __future__ import annotations

import functools
import importlib.util
import itertools
import os
import re
import subprocess
import urllib.parse
from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from colony import cli

OFF, NOTE, WARN, FAIL = "off", "note", "warn", "fail"
MODES = (OFF, NOTE, WARN, FAIL)  # a note warns even under --strict, which turns each warn into fail
# Every check with its default mode, in the order the closing count prints them.
CHECKS = {
    "page_types": FAIL,        # every page declares a known type
    "links": FAIL,             # every [[link]] and relative link resolves, and no two pages share a name
    "orphans": FAIL,           # another page links to every page
    "readme_maps": FAIL,       # every folder README links each page and subfolder beside it
    "code_paths": FAIL,        # every repo path a live page names in a code span exists
    "size_caps": WARN,         # each type's size cap, the living spec's among them
    "dated_caps": FAIL,        # a cap with a `from` date holds every page created on or after that day
    "copied_text": FAIL,       # no paragraph stands on two pages
    "rule_budget": FAIL,       # every rule stays within its size budget
    "replaced_records": FAIL,  # a replaced decision record says so, and one replaced in full sits in the archive
    "decision_log": FAIL,      # decisions.md is what the decision records generate
}
# The checks that read one page at a time, the ones --staged runs on the staged pages alone.
ONE_PAGE = ("page_types", "links", "code_paths", "size_caps", "dated_caps", "rule_budget")

DEFAULT_VAULT = "knowledge"
TYPES = ".types"
README = "README.md"
PAGES_HEADING = "## Pages"
ROOT_PAGES = ("README.md", "AGENTS.md", "CLAUDE.md")  # the repo's own pages, which link into the vault
# Each type's cap in characters. A README's cap counts only its text above `## Pages`, since its page list grows.
DEFAULT_CAPS = {"living-spec": 25_000, "design-spec": 25_000, "feature-spec": 12_000, "readme-page": 3_000}
DEFAULT_RULE_FOLDERS = (".colony/rules",)
DEFAULT_RULE_CHARS = 12_000
DEFAULT_COPY_WORDS = 20  # a shorter paragraph is too common to show it was copied
ARCHIVE = "archive"
PAST_FOLDERS = (ARCHIVE, "research", "raw")  # vault folders that record a past state, so a path there may have moved
FROZEN_FOLDERS = (ARCHIVE, "raw")  # vault folders frozen at capture, which may hold copied text
PAST_TYPES = ("decision-record", "reconciliation-report", "archive-record", "source", "research-report")
# The types that plan work, which name paths their tasks will create. The living spec records what was built.
PLAN_TYPES = ("feature-requirements", "feature-design", "feature-tasks", "feature-spec", "idea-spec",
              "implementation-plan", "tech-design", "prd", "one-pager", "launch-plan")
WALK_SKIPS = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
                        ".next", "build", "dist"})

WIKILINK = re.compile(r"\[\[([^\]\n]+)\]\]")
MARKDOWN_LINK = re.compile(r"\[[^\]\n]*\]\(([^)\n]+)\)")
SCHEME = re.compile(r"^[a-zA-Z][\w+.-]*:")  # https:, mailto: and the like name no file
ATTACHMENT = re.compile(r"\.[A-Za-z0-9]{1,5}$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"`[^`]*`")
CODE_SPAN = re.compile(r"`([^`\n]+)`")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
TITLE = re.compile(r"^#\s+")
SHOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
NOT_SLUG = re.compile(r"[^\w\- ]")
FIELD = re.compile(r"^([\w-]+):\s*(.*?)\s*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(?:\[[ xX]\]\s+)?")
NOT_A_PATH = re.compile(r"[\s*<>{}$?…]|\.\.\.")
LINE_SUFFIX = re.compile(r"(?::\d+(?:-\d+)?|#L\d+(?:-L?\d+)?)$")
# A decision record's opening line: one that says this record is replaced, and one that names what it replaces.
REPLACED = re.compile(r"\b(?:replaced|superseded)\b|\b(?:replaces|supersedes) (?:it|this record)\b", re.I)
REPLACES = re.compile(r"^(?:this record\s+)?(?:replaces|supersedes)\b(?!\s+(?:it|this record)\b)", re.I)
# The opening lines of a record replaced in full. A record replaced in part names the part, and stays.
IN_FULL = (
    re.compile(r"^(?:replaced|superseded) (?:in full )?by\s+\[", re.I),
    re.compile(r"\b(?:replaced|superseded) in full by\b", re.I),
    re.compile(r"\b(?:replaces|supersedes) this record(?: in full)?\s*[.,]", re.I),
    re.compile(r"\b(?:replaces|supersedes) (?:it|this record) in full\b", re.I),
)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
BLOCK_SCALAR = (">", "|", ">-", "|-", ">+", "|+")
LOG = "decisions.md"
LOG_DESCRIPTION = "Every decision record in the vault by area, the replaced ones marked. Read it to find a decision."
LOG_NOTICE = ("This page is generated by `colony check-docs --index`. Do not edit it by hand: change the decision "
              "records, then run that command.")

Problem = tuple[Path, int, str]  # the file, its line (0 for the whole file) and what is wrong


@dataclass
class Plugin:
    """A repo's own checks, from one file `[knowledge] plugins` names."""

    path: str
    checks: dict[str, str]
    one_page: tuple[str, ...]
    run: Callable[..., list]


@dataclass
class Settings:
    """What `[knowledge]` in colony.toml sets, with every default filled in."""

    vault: str = DEFAULT_VAULT
    modes: dict[str, str] = field(default_factory=lambda: dict(CHECKS))
    caps: dict[str, tuple[int, str]] = field(default_factory=lambda: {k: (v, "") for k, v in DEFAULT_CAPS.items()})
    rule_folders: tuple[str, ...] = DEFAULT_RULE_FOLDERS
    rule_chars: int = DEFAULT_RULE_CHARS
    rule_budgets: dict[str, int] = field(default_factory=dict)
    code_roots: tuple[str, ...] | None = None  # None: every top-level folder of the repo
    copy_words: int = DEFAULT_COPY_WORDS
    plugins: list[Plugin] = field(default_factory=list)


def load_plugin(repo: Path, name: str, index: int) -> Plugin:
    """Load one plug-in file from the repo, and check that it has CHECKS, a valid ONE_PAGE and run."""
    path = (repo / name).resolve()
    if not inside(path, repo.resolve()) or path.suffix != ".py" or not path.is_file():
        raise cli.ColonyError(f"[knowledge] plugins: {name} is not a Python file in this repo")
    spec = importlib.util.spec_from_file_location(f"{cli.NAME}_docs_plugin_{index}", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        raise cli.ColonyError(f"[knowledge] plugins: {name} failed to load: {type(e).__name__}: {e}") from None
    checks, one_page, run = getattr(module, "CHECKS", None), getattr(module, "ONE_PAGE", ()), getattr(module, "run", None)
    if not isinstance(checks, dict) or not checks or any(mode not in MODES for mode in checks.values()):
        raise cli.ColonyError(f"{name}: CHECKS must map each check to off, note, warn or fail")
    if not callable(run):
        raise cli.ColonyError(f"{name}: needs run(check, repo, vault, files)")
    if not set(one_page) <= set(checks):
        raise cli.ColonyError(f"{name}: ONE_PAGE names a check not in its CHECKS")
    return Plugin(name, dict(checks), tuple(one_page), run)


def plugin_problems(plugin: Plugin, check: str, vault: Vault, files: set[Path] | None) -> list[Problem]:
    """Run one plug-in check, with each problem's path made absolute and its shape checked."""
    try:
        found = plugin.run(check, vault.repo, vault.root, files)
    except Exception as e:
        raise cli.ColonyError(f"{plugin.path}: {check} crashed, so the run counts as failed: "
                              f"{type(e).__name__}: {e}") from None
    problems = []
    for item in found or ():
        if not (isinstance(item, (tuple, list)) and len(item) == 3 and isinstance(item[1], int)):
            raise cli.ColonyError(f"{plugin.path}: {check} returned {item!r}, not (path, line, message)")
        path = Path(item[0])
        problems.append((path if path.is_absolute() else vault.repo / path, item[1], str(item[2])))
    return problems


def _number(value, where: str) -> int:
    """A setting that must be a whole number of zero or more."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise cli.ColonyError(f"[knowledge] {where} must be a whole number, not {value!r}")
    return value


def _names(value, where: str) -> tuple[str, ...]:
    """A setting that must be a list of strings."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise cli.ColonyError(f"[knowledge] {where} must be a list of strings, such as [\".colony/rules\"]")
    return tuple(value)


def _table(table: dict, key: str) -> dict:
    """A setting that must be a table, such as caps."""
    value = table.get(key, {})
    if not isinstance(value, dict):
        raise cli.ColonyError(f"[knowledge] {key} must be a table, such as [knowledge.{key}]")
    return value


def read_settings(config: dict, strict: bool = False) -> Settings:
    """Read `[knowledge]` from colony.toml. `strict` turns every warn into fail.

    A key whose value is a mode must name a check, so a misspelled check is an error instead of a check left on.
    """
    table = config.get("knowledge", {})
    if not isinstance(table, dict):
        raise cli.ColonyError("[knowledge] must be a table")
    settings = Settings()
    if "plugins" in table:
        repo = cli.repo_root()
        settings.plugins = [load_plugin(repo, name, i) for i, name in enumerate(_names(table["plugins"], "plugins"))]
    for plugin in settings.plugins:
        for name, mode in plugin.checks.items():
            if name in settings.modes:
                raise cli.ColonyError(f"{plugin.path}: its check {name!r} has the name of another check")
            settings.modes[name] = mode
    for key, value in table.items():
        if key in settings.modes or value in MODES:
            if key not in settings.modes:
                raise cli.ColonyError(f"[knowledge] has no check {key!r}: the checks are {', '.join(settings.modes)}")
            if value not in MODES:
                raise cli.ColonyError(f"[knowledge] {key} must be off, note, warn or fail, not {value!r}")
            settings.modes[key] = value
    if strict:
        settings.modes = {name: FAIL if mode == WARN else mode for name, mode in settings.modes.items()}
    vault = table.get("vault", DEFAULT_VAULT)
    if not isinstance(vault, str) or not vault.strip("/ "):
        raise cli.ColonyError("[knowledge] vault must name a folder, such as \"knowledge\"")
    settings.vault = vault.strip().rstrip("/")
    for kind, value in _table(table, "caps").items():
        if isinstance(value, dict) and set(value) <= {"chars", "from"} and "chars" in value:
            settings.caps[kind] = (_number(value["chars"], f"caps.{kind}.chars"), str(value.get("from", "")))
        elif isinstance(value, dict):
            raise cli.ColonyError(f"[knowledge] caps.{kind} must be {{ chars = N, from = \"YYYY-MM-DD\" }}")
        else:
            settings.caps[kind] = (_number(value, f"caps.{kind}"), "")
    if "rules" in table:
        settings.rule_folders = _names(table["rules"], "rules")
    if "code_roots" in table:
        settings.code_roots = _names(table["code_roots"], "code_roots")
    settings.rule_chars = _number(table.get("rule_chars", DEFAULT_RULE_CHARS), "rule_chars")
    settings.copy_words = _number(table.get("copy_words", DEFAULT_COPY_WORDS), "copy_words")
    settings.rule_budgets = {name: _number(chars, f"rule_budgets.{name}")
                             for name, chars in _table(table, "rule_budgets").items()}
    return settings


@functools.lru_cache(maxsize=None)
def real(path: Path) -> Path:
    """A path with every symbolic link followed, kept, since the link checks resolve the same targets often."""
    return path.resolve()


def inside(path: Path, folder: Path) -> bool:
    """Whether a path sits at or below a folder, compared by their parts."""
    return path.parts[: len(folder.parts)] == folder.parts


@functools.lru_cache(maxsize=None)
def mask_code(text: str, keep_inline: bool = False) -> tuple[str, ...]:
    """A page's lines with fenced blocks blanked, and inline code too unless `keep_inline`.

    Pages quote links and frontmatter as examples inside code, which are not links. Each line keeps its place, so a
    problem names the line a reader looks at.
    """
    lines: list[str] = []
    opening: tuple[str, int] | None = None  # the open fence's character and length
    for line in text.splitlines():
        fence = FENCE.match(line)
        if fence and opening is None:
            opening = (fence.group(1)[0], len(fence.group(1)))
            lines.append("")
        elif (fence and opening and fence.group(1)[0] == opening[0] and len(fence.group(1)) >= opening[1]
              and not line[fence.end():].strip()):
            opening = None
            lines.append("")
        elif opening:
            lines.append("")
        else:
            lines.append(line if keep_inline else INLINE_CODE.sub("", line))
    return tuple(lines)


def body_start(lines: Sequence[str]) -> int:
    """The index of a page's first line below its frontmatter."""
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return index + 1
    return 0


@functools.lru_cache(maxsize=None)
def frontmatter(text: str) -> dict[str, str]:
    """A page's frontmatter fields, as plain strings with their quotes taken off. A `>` or `|` value joins its lines."""
    lines = text.splitlines()
    block = lines[1:body_start(lines) - 1] if body_start(lines) else []
    fields: dict[str, str] = {}
    for index, line in enumerate(block):
        found = FIELD.match(line)
        if not found:
            continue
        value = found.group(2)
        if value in BLOCK_SCALAR:
            rest = itertools.takewhile(lambda next_line: next_line[:1].isspace() or not next_line.strip(),
                                       block[index + 1:])
            value = " ".join(part.strip() for part in rest if part.strip())
        fields.setdefault(found.group(1), value.strip("\"'"))
    return fields


def page_type(text: str) -> str:
    """The type a page declares, or an empty string."""
    return frontmatter(text).get("type", "")


class Headings:
    """One page's headings, as Obsidian matches `[[page#Heading]]` and as GitHub slugs `page.md#heading`."""

    def __init__(self, lines: Sequence[str]) -> None:
        self.texts: set[str] = set()
        self.slugs: set[str] = set()
        seen: dict[str, int] = {}
        for line in lines:
            found = HEADING.match(line)
            if not found:
                continue
            self.texts.add(found.group(1).lower())
            slug = NOT_SLUG.sub("", SHOWN_LINK.sub(r"\1", found.group(1)).lower()).replace(" ", "-")
            count = seen.get(slug, 0)
            seen[slug] = count + 1
            self.slugs.add(slug if count == 0 else f"{slug}-{count}")


class Vault:
    """The vault's pages, read once, with the maps the checks share."""

    def __init__(self, repo: Path, settings: Settings) -> None:
        self.repo = real(repo)
        self.settings = settings
        self.root = real(self.repo / settings.vault)
        self.pages: list[Path] = []
        self.attachments: dict[str, Path] = {}  # every other file in the vault, by name, for `[[image.png]]`
        for folder, names, files in os.walk(self.root):
            names[:] = sorted(name for name in names if not name.startswith(".") and name not in WALK_SKIPS)
            for name in files:
                if name.endswith(".md"):
                    self.pages.append(Path(folder) / name)
                elif not name.startswith("."):
                    self.attachments.setdefault(name, Path(folder) / name)
        self.pages.sort()
        self.texts = {page: page.read_text(encoding="utf-8", errors="replace") for page in self.pages}
        self.stems: dict[str, list[Path]] = defaultdict(list)
        for page in self.pages:
            if page.name != README:
                self.stems[page.stem].append(page)
        self.folders = {folder for page in self.pages for folder in page.parents}
        types = self.root / TYPES
        # The type definitions, which pages may link as [[living-spec]]. Without the folder, any type counts.
        self.type_pages = {path.stem: path for path in sorted(types.rglob("*.md")) if path.name != README}
        self.types = set(self.type_pages) if types.is_dir() else None
        # The rules in the `rules` folders, which pages may link as [[authority]] though they sit outside the vault.
        self.rule_pages: dict[str, Path] = {}
        for folder in settings.rule_folders:
            for path in sorted((self.repo / folder).rglob("*.md")) if (self.repo / folder).is_dir() else ():
                if path.name != README:
                    self.rule_pages.setdefault(path.stem, real(path))
        self._headings: dict[Path, Headings] = {}

    def rel(self, path: Path) -> str:
        """A path as the repo names it."""
        try:
            return path.relative_to(self.repo).as_posix()
        except ValueError:
            return str(path)

    def folder_of(self, page: Path) -> str:
        """The top vault folder a page sits in, or an empty string for a page at the vault's root."""
        parts = page.relative_to(self.root).parts
        return parts[0] if len(parts) > 1 else ""

    def text(self, path: Path) -> str:
        """A page's text, read from disk when the page is outside the vault."""
        if path not in self.texts:
            self.texts[path] = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        return self.texts[path]

    def headings(self, path: Path) -> Headings:
        """A markdown file's headings, read once."""
        if path not in self._headings:
            self._headings[path] = Headings(mask_code(self.text(path)) if path.suffix == ".md" else ())
        return self._headings[path]

    def wikilink(self, page: Path, body: str) -> tuple[Path | None, str]:
        """Where `[[body]]` on a page leads, and the problem with it, or an empty string."""
        name, _, anchor = body.split("|")[0].rstrip("\\").partition("#")
        name, anchor = name.strip(), anchor.split("#")[-1].strip()
        stem = name.removesuffix(".md")
        if not name:
            target = page
        elif stem == "README":
            return None, "wikilink names a README, which has no unique name: link its folder instead"
        elif "/" in name:
            places = [base / form for base in (self.root, page.parent) for form in (name, f"{stem}.md")]
            found = [place for place in places if place.is_file()]
            if not found:
                return None, f"wikilink resolves to no file: [[{name}]]"
            target = real(found[0])
        elif stem in self.stems:
            target = self.stems[stem][0]
        elif stem in self.type_pages or stem in self.rule_pages:
            target = self.type_pages.get(stem) or self.rule_pages[stem]
        elif ATTACHMENT.search(name) and name in self.attachments:
            return self.attachments[name], ""
        else:
            return None, f"wikilink resolves to no page: [[{name}]]"
        if anchor and not anchor.startswith("^") and anchor.lower() not in self.headings(target).texts:
            return target, f"wikilink names no heading on that page: [[{name}#{anchor}]]"
        return target, ""

    def relative_link(self, page: Path, target: str) -> tuple[Path | None, str]:
        """Where a Markdown link's target leads from a page, and the problem with it, or an empty string."""
        file_part, _, anchor = target.partition("#")
        file_part = urllib.parse.unquote(file_part)
        if not file_part:
            path = page
        elif file_part.startswith("/"):
            path = real(self.repo / file_part.lstrip("/"))
        else:
            path = real(page.parent / file_part)
        if not path.exists():
            return None, f"link resolves to no file: {target}"
        if anchor and path.suffix == ".md" and anchor.lower() not in self.headings(path).slugs:
            return path, f"link names no heading on that page: {target}"
        return path, ""

    def line_links(self, page: Path, line: str) -> Iterator[tuple[Path | None, str]]:
        """Each link on one line, as (the file it reaches or None, the problem with it or an empty string)."""
        for body in WIKILINK.findall(line):
            yield self.wikilink(page, body)
        for target in MARKDOWN_LINK.findall(line):
            words = target.split()
            if words and not SCHEME.match(words[0].strip("<>")):
                yield self.relative_link(page, words[0].strip("<>"))

    def links(self, page: Path) -> Iterator[tuple[int, Path | None, str]]:
        """Each link on a page, as (its line, the file it reaches or None, the problem with it)."""
        for number, line in enumerate(mask_code(self.text(page)), start=1):
            for target, problem in self.line_links(page, line):
                yield number, target, problem

    def targets(self, page: Path) -> set[Path]:
        """Every file and folder a page links to."""
        return {target for _, target, _ in self.links(page) if target}


def check_page_types(vault: Vault, pages: Sequence[Path]) -> list[Problem]:
    """Every page declares a type, and one of the vault's `.types/` when that folder exists."""
    problems: list[Problem] = []
    for page in pages:
        kind = page_type(vault.texts[page])
        if not kind:
            problems.append((page, 0, "page declares no type: add `type:` to its frontmatter"))
        elif vault.types is not None and kind not in vault.types:
            where = f"{vault.settings.vault}/{TYPES}/"
            problems.append((page, 0, f"page declares the type {kind}, which {where} does not define"))
    return problems


def check_links(vault: Vault, pages: Sequence[Path]) -> list[Problem]:
    """Every wikilink and relative link resolves, to a heading too when it names one, and page names are unique."""
    problems = [(page, number, problem) for page in pages for number, _, problem in vault.links(page) if problem]
    checked = set(pages)
    for stem, holders in sorted(vault.stems.items()):
        for page in holders[1:]:
            if page in checked or holders[0] in checked:
                problems.append((page, 0, f"another page has the name {stem}, so [[{stem}]] is ambiguous: "
                                          f"{vault.rel(holders[0])}"))
    return problems


def check_orphans(vault: Vault, pages: Sequence[Path]) -> list[Problem]:
    """Another page links to every page but the vault's own README. The repo's README and AGENTS.md count."""
    sources = list(vault.pages) + [real(vault.repo / name) for name in ROOT_PAGES if (vault.repo / name).is_file()]
    reached: set[Path] = set()
    for source in dict.fromkeys(sources):
        for target in vault.targets(source) - {source}:
            reached.add(target / README if target.is_dir() else target)
    entry = vault.root / README
    return [(page, 0, "no other page links to this page: list it in its folder's README")
            for page in pages if page != entry and page not in reached]


def check_readme_maps(vault: Vault, pages: Sequence[Path]) -> list[Problem]:
    """Every README links each page beside it and each subfolder that holds pages.

    A subfolder with its own README is listed by a link to the folder or that README, and one without by a link to
    any page in it.
    """
    problems: list[Problem] = []
    for readme in (page for page in pages if page.name == README):
        targets = vault.targets(readme)
        for child in sorted(readme.parent.iterdir()):
            if child.name == README or child.name.startswith(".") or child.name in WALK_SKIPS:
                continue
            if child.is_file() and child.suffix == ".md":
                listed = child in targets
            elif child.is_dir() and child in vault.folders:
                if (child / README).is_file():
                    listed = child in targets or child / README in targets
                else:
                    listed = any(inside(target, child) for target in targets)
            else:
                continue
            if not listed:
                problems.append((readme, 0, f"the README does not list {child.name}{'/' if child.is_dir() else ''}"))
    return problems


def check_code_paths(vault: Vault, pages: Sequence[Path]) -> list[Problem]:
    """Every repo path a live page names in a code span exists.

    A path counts when it starts at a top-level folder of the repo, or one `code_roots` names. Pages that record a
    past state (the archive, research and raw folders, and the past types) or plan work (the plan types) may name a
    path that has moved or is still to be built.
    """
    roots = set(vault.settings.code_roots or ())
    if vault.settings.code_roots is None:
        roots = {entry.name for entry in vault.repo.iterdir() if entry.is_dir() and entry.name not in WALK_SKIPS}
    problems: list[Problem] = []
    for page in pages:
        text = vault.texts[page]
        if vault.folder_of(page) in PAST_FOLDERS or page_type(text) in PAST_TYPES + PLAN_TYPES:
            continue
        for number, line in enumerate(mask_code(text, keep_inline=True), start=1):
            for span in CODE_SPAN.findall(line):
                path = LINE_SUFFIX.sub("", span.strip().rstrip(".,;:"))
                parts = path.split("/")
                if len(parts) < 2 or parts[0] not in roots or NOT_A_PATH.search(path) or "node_modules" in parts:
                    continue
                if not (vault.repo / path).exists():
                    problems.append((page, number, f"code path does not exist: {path}"))
    return problems


def over_cap(vault: Vault, page: Path) -> tuple[str, int, int, str] | None:
    """A page over its type's cap, as (its kind, its size, the cap, the cap's from date), or None."""
    text = vault.texts[page]
    kind = "readme-page" if page.name == README else page_type(text)
    chars, since = vault.settings.caps.get(kind, (0, ""))
    if page.name == README:
        lines = text.splitlines()
        text = "\n".join(lines[body_start(lines):]).split("\n" + PAGES_HEADING, 1)[0]
    return (kind, len(text), chars, since) if chars and len(text) > chars else None


def check_caps(vault: Vault, pages: Sequence[Path], dated: bool) -> list[Problem]:
    """The pages over their type's cap: with `dated`, those a dated cap holds, else the rest.

    A cap with a `from` date holds the pages created on or after that day, so an older page over it only warns,
    under size_caps.
    """
    problems: list[Problem] = []
    for page in pages:
        found = over_cap(vault, page)
        if not found:
            continue
        kind, size, chars, since = found
        created = frontmatter(vault.texts[page]).get("created", "")
        if bool(since and created and created >= since) != dated:
            continue
        if page.name == README:
            message = (f"the README holds {size:,} characters above {PAGES_HEADING}, over its cap of {chars:,}: "
                       "move the detail into a page it lists")
        else:
            held = f", which holds every {kind} created on or after {since}" if dated else ""
            message = f"a {kind} holds {size:,} characters, over its cap of {chars:,}{held}: split it into linked pages"
        problems.append((page, 0, message))
    return problems


def paragraphs(text: str) -> Iterator[tuple[int, str]]:
    """A page's prose paragraphs with their first line, spacing normalized. Each list item is its own paragraph."""
    lines = mask_code(text)
    current: list[str] = []
    start = 0
    for number, line in enumerate(lines[body_start(lines):], start=body_start(lines) + 1):
        stripped = line.strip()
        item = LIST_ITEM.match(line)
        if not stripped or item or HEADING.match(stripped) or stripped.startswith(("|", ">", "<")):
            if current:
                yield start, " ".join(" ".join(current).split())
            current = [line[item.end():]] if item else []
            start = number
        else:
            current.append(stripped)
    if current:
        yield start, " ".join(" ".join(current).split())


def check_copied_text(vault: Vault, pages: Sequence[Path]) -> list[Problem]:
    """No prose paragraph of `copy_words` words or more stands on two pages: keep it in one and link it.

    The archive and raw folders and source pages are frozen at capture, so the check skips them.
    """
    seen: dict[str, Path] = {}
    problems: list[Problem] = []
    for page in pages:
        text = vault.texts[page]
        if vault.folder_of(page) in FROZEN_FOLDERS or page_type(text) == "source":
            continue
        for number, paragraph in paragraphs(text):
            if len(paragraph.split()) < vault.settings.copy_words:
                continue
            first = seen.setdefault(paragraph, page)
            if first != page:
                problems.append((page, number, f"a paragraph also stands in {vault.rel(first)}: "
                                               "keep it in one page and link to it"))
    return problems


def rule_files(vault: Vault) -> list[Path]:
    """The rules: each markdown file in the `rules` folders, and every vault page of type rule."""
    found = list(vault.rule_pages.values()) + [page for page in vault.pages if page_type(vault.texts[page]) == "rule"]
    return list(dict.fromkeys(found))


def check_rule_budget(vault: Vault, rules: Sequence[Path]) -> list[Problem]:
    """Every rule stays within its budget: `rule_budgets.<name>`, else `rule_chars`, in characters.

    A rule line a check enforces stays one sentence, with its reason in the check's message, so a rule past its
    budget has taken back text a check carries.
    """
    problems: list[Problem] = []
    for path in rules:
        budget = vault.settings.rule_budgets.get(path.stem, vault.settings.rule_chars)
        size = len(vault.text(path))
        if budget and size > budget:
            problems.append((path, 0, f"the rule holds {size:,} characters, over its budget of {budget:,}: move "
                                      "what a check enforces into its message, and detail into a page it links"))
    return problems


def opening(vault: Vault, page: Path) -> str:
    """The first line of text below a page's title, with code blanked and leading emphasis taken off."""
    lines = mask_code(vault.texts[page])
    lines = lines[body_start(lines):]
    titled = next((index + 1 for index, line in enumerate(lines) if TITLE.match(line)), 0)
    line = next((line.strip() for line in lines[titled:] if line.strip()), "")
    return line.lstrip("*_> ").strip()


def check_replaced_records(vault: Vault, pages: Sequence[Path]) -> list[Problem]:
    """A replaced decision record says so, and one replaced in full moves to the archive.

    A record that replaces another names it on its opening line ("This record replaces [[old]]"). The old record
    then opens with a line that names its replacement and links it ("Replaced by [[new]]"). One replaced in full
    binds nothing, so it sits in the vault's archive folder. One replaced in part names the part and stays.
    """
    records = [page for page in pages if page_type(vault.texts[page]) == "decision-record"]
    lines = {page: opening(vault, page) for page in records}
    problems: list[Problem] = []
    for page in records:
        line = lines[page]
        if REPLACED.search(line):
            if not (WIKILINK.search(line) or MARKDOWN_LINK.search(line)):
                problems.append((page, 0, "the record opens by saying it is replaced but links no replacement: "
                                          "link the record that replaces it"))
            if any(pattern.search(line) for pattern in IN_FULL) and vault.folder_of(page) != ARCHIVE:
                problems.append((page, 0, f"a decision record replaced in full belongs in "
                                          f"{vault.settings.vault}/{ARCHIVE}/"))
        if not REPLACES.search(line):
            continue
        # Only the sentence that says "replaces" names the replaced records. A later one may cite records that stand.
        for old, _ in vault.line_links(page, SENTENCE_END.split(line, 1)[0]):
            if old not in lines or old == page:
                continue
            said = REPLACED.search(lines[old]) and page in {t for t, _ in vault.line_links(old, lines[old])}
            if not said:
                problems.append((old, 0, f"{vault.rel(page)} replaces this record, so it must open with a line "
                                         f"that names it: Replaced by [[{page.stem}]]"))
    return problems


def area_of(vault: Vault, page: Path) -> str:
    """A page's wiki area: its folder below `wiki/` or `decisions/`, the archive taken off, or an empty string."""
    parts = list(page.relative_to(vault.root).parts[:-1])
    if parts[:1] == [ARCHIVE]:
        parts = parts[1:]
    if parts[:1] in (["wiki"], ["decisions"]):
        parts = parts[1:]
    return parts[0] if parts else ""


def replacement(vault: Vault, page: Path) -> tuple[bool, Path | None]:
    """Whether a decision record is replaced, and the record its opening line names as the replacement.

    A record is replaced when its opening line names a replacement, or when it sits in the archive.
    """
    line = opening(vault, page)
    named = None
    if REPLACED.search(line):
        named = next((target for target, _ in vault.line_links(page, line)
                      if target and target != page and target.suffix == ".md" and inside(target, vault.root)), None)
    return named is not None or vault.folder_of(page) == ARCHIVE, named


def decision_log(vault: Vault) -> tuple[str, int]:
    """The decision log's text and its count of records.

    One section per wiki area, then General. In each, the active records come first and then the replaced ones,
    each by name, as `- [[name]]: <its description's first sentence>`. An archived record with no area of its own
    sits in its replacement's area.
    """
    groups: dict[str, list[tuple[bool, str, str]]] = defaultdict(list)
    records = [page for page in vault.pages if page_type(vault.texts[page]) == "decision-record"]
    for page in records:
        replaced, by = replacement(vault, page)
        area = area_of(vault, page) or (area_of(vault, by) if by else "")
        sentence = SENTENCE_END.split(frontmatter(vault.texts[page]).get("description", "").strip(), 1)[0]
        line = f"- [[{page.stem}]]" + (f": {sentence}" if sentence else "")
        if replaced:
            line += f" (replaced by [[{by.stem}]])" if by else " (replaced)"
        groups[area].append((replaced, page.stem, line))
    out = ["---", "type: singleton", f"description: {LOG_DESCRIPTION}", "---", "", "# Decisions", "", LOG_NOTICE]
    for area in sorted(groups, key=lambda name: (name == "", name)):
        out += ["", f"## {area.replace('-', ' ').capitalize() if area else 'General'}", ""]
        out += [line for _, _, line in sorted(groups[area])]
    if not records:
        out += ["", "The vault holds no decision record yet."]
    return "\n".join(out) + "\n", len(records)


def write_log(vault: Vault, always: bool = False) -> tuple[bool, bool, int]:
    """Rewrite the decision log when it differs, as (whether it wrote, whether a log was there, the record count).

    Without `always`, a vault with no decision record and no log gets no log.
    """
    path = vault.root / LOG
    old = path.read_text(encoding="utf-8") if path.is_file() else None
    new, count = decision_log(vault)
    wrote = old != new and (always or count > 0 or old is not None)
    if wrote:
        path.write_text(new, encoding="utf-8")
    return wrote, old is not None, count


def check_decision_log(vault: Vault) -> list[Problem]:
    """Rewrite the decision log, and fail when the log the run found was missing or differed."""
    wrote, existed, _ = write_log(vault)
    if not wrote:
        return []
    word = "not what the decision records generate" if existed else "missing"
    return [(vault.root / LOG, 0, f"{LOG} was {word}, so this run rewrote it: commit the new file, "
                                  "and never edit it by hand")]


def staged_files(repo: Path) -> set[Path]:
    """The files staged for the next commit, added, copied, changed or renamed."""
    run = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
                         cwd=repo, capture_output=True, text=True)
    if run.returncode:
        raise cli.ColonyError(f"git diff --cached failed: {run.stderr.strip()[:300]}")
    return {real(repo / name) for name in run.stdout.split("\0") if name}


def check_docs(config: dict, args) -> int:
    """`colony check-docs`: run each check in its mode, print each problem and a count per check.

    Returns 1 when a check set to fail found a problem, else 0, so a warning never fails the run.
    """
    settings = read_settings(config, strict=getattr(args, "strict", False))
    staged = getattr(args, "staged", False)
    vault = Vault(cli.repo_root(), settings)
    if not vault.root.is_dir():
        raise cli.ColonyError(f"no vault at {settings.vault}/: set [knowledge] vault in {cli.DIR}/{cli.CONFIG_NAME}")
    if getattr(args, "index", False):
        wrote, _, count = write_log(vault, always=True)
        print(f"check-docs: {'wrote' if wrote else 'kept'} {vault.rel(vault.root / LOG)}, {count} decision record(s)")
        return 0
    log_problems: list[Problem] = []
    if not staged and settings.modes["decision_log"] != OFF:
        log_problems = check_decision_log(vault)
        if log_problems:  # the other checks read the log as this run wrote it
            vault = Vault(vault.repo, settings)
    pages, rules, files = vault.pages, rule_files(vault), None
    if staged:
        files = staged_files(vault.repo)
        pages, rules = [page for page in pages if page in files], [path for path in rules if path in files]
        if not files or (not pages and not rules and not settings.plugins):
            print("check-docs: no staged pages")
            return 0
    runs = {
        "page_types": lambda: check_page_types(vault, pages),
        "links": lambda: check_links(vault, pages),
        "orphans": lambda: check_orphans(vault, pages),
        "readme_maps": lambda: check_readme_maps(vault, pages),
        "code_paths": lambda: check_code_paths(vault, pages),
        "size_caps": lambda: check_caps(vault, pages, dated=False),
        "dated_caps": lambda: check_caps(vault, pages, dated=True),
        "copied_text": lambda: check_copied_text(vault, pages),
        "rule_budget": lambda: check_rule_budget(vault, rules),
        "replaced_records": lambda: check_replaced_records(vault, pages),
        "decision_log": lambda: log_problems,
    }
    one_page = set(ONE_PAGE)
    for plugin in settings.plugins:
        one_page |= set(plugin.one_page)
        for name in plugin.checks:
            runs[name] = functools.partial(plugin_problems, plugin, name, vault, files)
    problems: list[Problem] = []
    warnings: list[Problem] = []
    tally: list[str] = []
    for name, mode in settings.modes.items():
        if staged and name not in one_page:
            continue
        if mode == OFF:
            tally.append(f"{name} off")
            continue
        found = runs[name]()
        (problems if mode == FAIL else warnings).extend(found)
        tally.append(f"{name} {len(found)}" + (f" ({mode})" if mode in (WARN, NOTE) else ""))
    for mark, found in (("warning: ", warnings), ("", problems)):
        for path, number, message in sorted(found, key=lambda problem: (problem[0], problem[1])):
            print(f"{vault.rel(path)}{f':{number}' if number else ''}: {mark}{message}")
    print(f"check-docs: {', '.join(tally)}")
    if staged:
        print(f"check-docs: --staged skips {', '.join(name for name in settings.modes if name not in one_page)}")
    scope = f"{len(pages)} {'staged ' if staged else ''}page(s)"
    if problems:
        print(f"check-docs: {len(problems)} problem(s) and {len(warnings)} warning(s) across {scope}")
        return 1
    print(f"check-docs: {scope} clean" + (f", with {len(warnings)} warning(s)" if warnings else ""))
    return 0


def add_commands(sub) -> None:
    """cli.py's route to this module: the `check-docs` command."""
    p = sub.add_parser("check-docs", help="check the knowledge vault: types, links, maps, code paths, caps, "
                                          "copied text, rule budgets, replaced records and the decision log")
    p.add_argument("--staged", action="store_true",
                   help="check only the staged pages, with the checks that read one page (the pre-commit hook)")
    p.add_argument("--strict", action="store_true", help="fail on the checks set to warn too")
    p.add_argument("--index", action="store_true", help=f"only rewrite the decision log, <vault>/{LOG}")
    p.set_defaults(run=check_docs)
