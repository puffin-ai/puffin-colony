"""The cycle around the build: tiers and the risk list, the Needs issue, the handover, card stats, the retro, and the
stale-card lines for the lead's wait.

- `colony tier` prints TINY, SMALL or FEATURE, the lowest tier a branch's diff allows, then its risk list, which is
  the batch reviewer's attention list.
- `colony needs` posts a decision for a person on their `Needs <Person>` issue, with a default, from the lead or
  from a session the lead opened, such as the spec agent or a researcher.
- `colony handover` posts the lead's handover on `Colony: coordination` and prints the command for a fresh lead.
- `colony stats` sums each card's predicted and actual minutes and tokens, from its lines and its builder's
  Claude Code transcripts. `--calibrate` prints the median actual minutes per size over the last 30 cards,
  and `colony card new` prints that median beside a new card's prediction.
- `colony retro` runs one agent on a batch's reports that writes each lesson as a rule line and a check, or a
  decision, into a pull request.
- `stale_lines(config, now)` is the lead's wait's board check, by each card's Status, Helper and Last update.

`needs` and `handover` check their issue's comment count before they post, and rotate a full one (tidy.keep_short).

Optional settings live in `[cycle]` in colony.toml: `stale_hours`, `tiny_code_lines`, `tiny_docs_lines`,
`feature_code_lines`, `docs` (the documentation folders), `feature_folders`, `risk`, a table of extra path
fragments per risk kind, such as `risk = { payments = ["src/ledger/"] }`, `structure_files` (globs of files whose
addition is a FEATURE and whose move or deletion is never TINY), `tiny_folders` (the only folders a TINY change's
code may be in), and `feature_triggers`, the repo's own FEATURE lines, such as
`{ path = "src/catalog.py", added = '"(\\w+)": Entry\\(', why = "a new catalog key" }`.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shlex
import statistics
import subprocess
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from colony import board, cli, tidy, wait

TINY, SMALL, FEATURE = "TINY", "SMALL", "FEATURE"
TINY_CODE_LINES, TINY_DOCS_LINES, FEATURE_CODE_LINES = 100, 300, 400
STALE_HOURS = 2.5
STALE_CHECK_MINUTES = 10  # how often the lead's wait should call stale_lines
KEEP_REPORTED = timedelta(days=7)
DOCS = ("knowledge/", "docs/", f"{cli.DIR}/reports/")
CONTAINERS = {"apps", "packages", "services", "libs", "modules", "crates", "cmd", "projects"}
FEATURE_SEGMENTS = {"features", "modules", "routes", "pages", "screens"}
SCREEN = re.compile(r"(^|/)app/(.+/)?((page|layout)\.[cm]?[jt]sx?|route\.[cm]?[jt]s)$")
MIGRATION = re.compile(r"(^|/)(migrations?|alembic|migrate)/|schema\.(sql|prisma)$|\.sql$")
CREATES_TABLE = re.compile(r"\bcreate\s+table\b|create_table|createTable", re.I)
LOCKFILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "uv.lock", "poetry.lock",
             "Pipfile.lock", "Cargo.lock", "go.sum", "Gemfile.lock", "composer.lock")
MANIFESTS = ("package.json", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "go.mod", "Cargo.toml", "Gemfile",
             "pom.xml", "build.gradle", "build.gradle.kts", "composer.json", *LOCKFILES)
# The risk list: a path that matches one of these, outside the docs, is on it, and so is never TINY.
RISK_PATHS = {
    "auth": re.compile(r"auth|log_?in|sign[-_]?(in|up|out)|session|oauth|passw|permission|jwt|csrf|cookie|guard"
                       r"|security"),
    "payments": re.compile(r"payment|billing|stripe|checkout|invoice|subscription|pricing|refund|payout"),
    "migrations": MIGRATION,
    "secrets": re.compile(r"(^|/)\.env|secret|credential|\.(pem|key|p12|pfx)$|id_rsa|keystore"),
    "public API": re.compile(r"(^|/)(api|apis|routes|endpoints|contracts|controllers)/|openapi|swagger|\.proto$"
                             r"|\.graphqls?$"),
    "config": re.compile(r"(^|/)(\.github|\.claude|infrastructure|infra|terraform|helm|k8s)/"
                         rf"|^{re.escape(cli.DIR)}/(?!reports/)|(^|/)(agents|claude)\.md$|dockerfile|docker-compose"
                         r"|\.tf$|(^|/)conftest\.py$"),
}
# An added line that matches one of these puts its file on the risk list too.
RISK_LINES = {
    "secrets": re.compile(r"(api[_-]?key|secret|passw(or)?d|private[_-]?key|access[_-]?token)['\"]?\s*[:=]\s*['\"]"
                          r"[^'\"\s]{8,}|-----BEGIN [A-Z ]*PRIVATE KEY|\bAKIA[0-9A-Z]{16}\b|\bsk-[A-Za-z0-9_-]{20,}"
                          r"|\bghp_[A-Za-z0-9]{30,}", re.I),
    "deletion": re.compile(r"\bdelete\s+from\b|\bdrop\s+(table|column|database|index)\b|\btruncate\s+table\b"
                           r"|\brm\s+-[a-z]*r|shutil\.rmtree|\.unlink\(|os\.remove\(|\.delete\(|\.destroy\(|deleteMany"
                           r"|drop_table|drop_column|\bfs\.(rm|unlink)", re.I),
    "migrations": re.compile(r"\bcreate\s+table\b|create_table|createTable|\balter\s+table\b|add_column|addColumn",
                             re.I),
}
# An added line holding one of these skips or narrows a test run, or silences a check.
SKIP_MARKS = ("pytest.mark.skip", "xfail", ".skip(", ".skipIf(", ".only(", ".fixme(", ".todo(", "xit(", "t.Skip(",
              "#[ignore]", "@Disabled", "@ts-ignore", "@ts-expect-error", "eslint-disable", "biome-ignore", "noqa",
              "type: ignore", "nolint")
RISK_ORDER = ("auth", "payments", "migrations", "secrets", "deletion", "public API", "dependencies", "config", "checks")
AGENT_FILES = ("agents.md", "claude.md")


def _settings(config: dict) -> dict:
    """The [cycle] table, or an empty one."""
    return config.get("cycle", {}) or {}


def _git(cwd, *args: str) -> str:
    """One git command's output in cwd; raise ColonyError when it fails."""
    run = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=cwd, capture_output=True, text=True)
    if run.returncode:
        raise cli.ColonyError(run.stderr.strip() or f"git {' '.join(args[:2])} failed")
    return run.stdout


# Tiers and the risk list


@dataclass
class FileChange:
    """One file's part of a diff: its path (its old path when deleted), A, D, R or M, the path before a rename, and
    the text of each added and removed line."""

    path: str
    status: str = "M"
    old_path: str = ""
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def lines(self) -> int:
        """The count of added and removed lines."""
        return len(self.added) + len(self.removed)


@dataclass
class Verdict:
    """The tier a diff allows, each reason that raised it, and the risk list, one `kind: path, what` line each."""

    tier: str
    reasons: list[str]
    risks: list[str]


def _header_path(rest: str) -> str:
    """The new path in a `diff --git a/<old> b/<new>` header."""
    half = (len(rest) - 3) // 2
    if rest.startswith("a/") and rest[half:half + 3] == " b/":
        return rest[half + 3:]
    return rest.rpartition(" b/")[2]


def parse_diff(text: str) -> list[FileChange]:
    """Read the changed files and lines of a unified `git diff` with `a/` and `b/` prefixes, in the diff's order."""
    changes: list[FileChange] = []
    current: FileChange | None = None
    in_hunk = False
    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = FileChange(path=_header_path(line[len("diff --git "):]))
            current.old_path = current.path
            changes.append(current)
            in_hunk = False
        elif current is None:
            continue
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            current.added.append(line[1:])
        elif in_hunk and line.startswith("-"):
            current.removed.append(line[1:])
        elif in_hunk:
            continue
        elif line.startswith("new file mode"):
            current.status = "A"
        elif line.startswith("deleted file mode"):
            current.status = "D"
        elif line.startswith("rename from "):
            current.status, current.old_path = "R", line[len("rename from "):]
        elif line.startswith("rename to "):
            current.path = line[len("rename to "):]
        elif line.startswith("+++ b/"):
            current.path = line[len("+++ b/"):]
        elif line.startswith("--- a/"):
            current.old_path = line[len("--- a/"):]
            if current.status == "D":
                current.path = current.old_path
    return changes


def is_test(path: str) -> bool:
    """Whether a path holds tests, by the same pattern the batch uses for removed tests."""
    from colony.batch import TEST_PATH

    return bool(TEST_PATH.search(path))


def _risk_fragments(config: dict) -> dict[str, tuple[str, ...]]:
    """The [cycle] risk table, each kind's fragments lowercased."""
    return {kind: tuple(str(f).lower() for f in fragments)
            for kind, fragments in _settings(config).get("risk", {}).items()}


def is_docs(path: str, config: dict) -> bool:
    """Whether a path is documentation: under a [cycle] docs folder, or a Markdown file at the repo's top other than
    the agents' AGENTS.md and CLAUDE.md, which are on the risk list. A path that a [cycle] risk entry of any kind
    starts, such as `REVIEW.md` or `guide/`, is never docs, so it stays on the risk list. A fragment inside a docs
    path, such as `session` in a wiki page's name, leaves the page docs."""
    if path.rsplit("/", 1)[-1].lower() in AGENT_FILES:
        return False
    if path.lower().startswith(tuple(f for fragments in _risk_fragments(config).values() for f in fragments)):
        return False
    return path.startswith(tuple(_settings(config).get("docs", DOCS))) or ("/" not in path and path.endswith(".md"))


def in_folders(path: str, folders: Iterable[str]) -> bool:
    """Whether a path sits in one of these folders, each given with or without its trailing slash."""
    return any(path.startswith(folder.rstrip("/") + "/") for folder in folders)


def is_structure(path: str, config: dict) -> bool:
    """Whether a path is a page, layout or route file by the built-in pattern, or matches a [cycle]
    structure_files glob, in which `*` crosses folders."""
    return bool(SCREEN.search(path)) or any(fnmatch.fnmatchcase(path, glob)
                                            for glob in _settings(config).get("structure_files", ()))


def area(path: str) -> str:
    """A code path's area: its first folder, or its first two under a folder of apps such as `apps/`."""
    parts = path.split("/")
    if len(parts) == 1:
        return "."
    return "/".join(parts[:2]) if parts[0] in CONTAINERS and len(parts) > 2 else parts[0]


def counts(path: str, config: dict) -> bool:
    """Whether a path's lines count toward the code-line limits: not a test, a lockfile, or a generated file."""
    parts = path.split("/")
    generated = config.get("project", {}).get("generated", [])
    return not (is_test(path) or parts[-1] in LOCKFILES or any(fnmatch.fnmatchcase(path, g) for g in generated)
                or {"generated", "vendor", "node_modules", "dist"} & set(parts[:-1]))


def risks_of(change: FileChange, config: dict) -> list[tuple[str, str]]:
    """One file's places on the risk list, as (kind, what) pairs."""
    path, found = change.path, []
    docs, test = is_docs(path, config), is_test(path)
    name = path.rsplit("/", 1)[-1]
    extra = _risk_fragments(config)
    # A rename is read at both ends, so moving a file off the risk list puts it on the list too.
    ends = [path, change.old_path] if change.status == "R" and change.old_path else [path]
    paths = [end.lower() for end in dict.fromkeys(ends) if not is_docs(end, config)]
    for kind in [*RISK_PATHS, *(kind for kind in extra if kind not in RISK_PATHS)]:
        pattern = RISK_PATHS.get(kind)
        hit = any(bool(pattern and pattern.search(lower)) or any(f in lower for f in extra.get(kind, ()))
                  for lower in paths)
        if hit and (not test or kind == "config"):  # a test of sign-in code is not itself a risk
            found.append((kind, "the path"))
    if not docs:
        if name in MANIFESTS or (name.startswith("requirements") and name.endswith(".txt")):
            found.append(("dependencies", "a dependency manifest"))
        for kind, pattern in RISK_LINES.items():
            if test and kind != "secrets":
                continue
            hit = next((line.strip() for line in change.added if pattern.search(line)), None)
            if hit is not None:
                found.append((kind, f"adds `{hit[:60]}`"))
        mark = next((m for line in change.added for m in SKIP_MARKS if m in line), None)
        if mark:
            found.append(("checks", f"adds the skip mark `{mark}`"))
    if change.status in ("D", "R") and is_test(change.old_path):
        found.append(("checks", "moves or deletes a test file"))
    elif test and change.removed:
        found.append(("checks", "deletes test lines"))
    return found


def _rules(config: dict) -> list[dict]:
    """The [cycle] feature_triggers, each checked and with its patterns compiled."""
    rules = []
    for i, rule in enumerate(_settings(config).get("feature_triggers", ())):
        if not isinstance(rule, dict) or not rule.get("path") or not rule.get("why") or not (
                rule.get("added") or rule.get("removed")):
            raise cli.ColonyError(f"[cycle] feature_triggers entry {i + 1} needs path, why, and added or removed")
        try:
            rules.append({**rule, **{key: re.compile(rule[key]) for key in ("added", "removed", "line")
                                     if rule.get(key)}})
        except re.error as e:
            raise cli.ColonyError(f"[cycle] feature_triggers entry {i + 1} ({rule['why']}): bad pattern, {e}") from None
    return rules


def _found(pattern: re.Pattern[str], lines: Iterable[str], only: re.Pattern[str] | None) -> Counter[str]:
    """What a pattern finds in these lines, counted: each match's first group that took part, else the whole match,
    stripped. With `only`, it reads just the lines that pattern matches."""
    found: Counter[str] = Counter()
    for line in lines:
        if only and not only.search(line):
            continue
        for match in pattern.finditer(line):
            found[next((g for g in match.groups() if g is not None), match.group(0)).strip()] += 1
    return found


def configured_triggers(change: FileChange, config: dict) -> list[str]:
    """The [cycle] feature_triggers one changed file meets. A rule's `added` pattern fires on what it finds more
    often in the added lines than in the removed ones, so a line moved within the file is no trigger, and its
    `removed` pattern the other way round."""
    found = []
    for rule in _rules(config):
        if not fnmatch.fnmatchcase(change.path, rule["path"]):
            continue
        only = rule.get("line")
        names: Counter[str] = Counter()
        if rule.get("added"):
            names += _found(rule["added"], change.added, only) - _found(rule["added"], change.removed, only)
        if rule.get("removed"):
            names += _found(rule["removed"], change.removed, only) - _found(rule["removed"], change.added, only)
        if names:
            what = ", ".join(sorted(names))
            found.append(f"{rule['why']}, {change.path}: {what if len(what) <= 80 else what[:77] + '...'}")
    return found


def feature_triggers(change: FileChange, existed: Callable[[str], bool], config: dict) -> list[str]:
    """The FEATURE triggers one changed file meets, one sentence each. The repo's own [cycle] feature_triggers read
    test files too, and a new feature folder counts whatever file it starts with, unless the folder is itself under
    a tests folder."""
    path, found = change.path, configured_triggers(change, config)
    if change.status == "A":
        parts = path.split("/")
        folders = {folder.rstrip("/") for folder in _settings(config).get("feature_folders", ())}
        for i, part in enumerate(parts[:-1]):
            entry = "/".join(parts[:i + 2])
            if is_test(entry + "/"):
                break
            if (part in FEATURE_SEGMENTS or "/".join(parts[:i + 1]) in folders) and not existed(entry):
                found.append(f"a new entry under {part}/, {entry}")
                break
    if is_test(path):
        return found
    if change.status == "A":
        if is_structure(path, config):
            found.append(f"a new page, layout or route file, {path}")
        specs = [f"{d.rstrip('/')}/specs/" for d in _settings(config).get("docs", DOCS)]
        if path.endswith(".md") and path.startswith(tuple(specs)):
            found.append(f"a new spec page, {path}")
    if MIGRATION.search(path.lower()) and any(CREATES_TABLE.search(line) for line in change.added):
        found.append(f"a migration that creates a table, {path}")
    return found


def classify(changes: list[FileChange], existed: Callable[[str], bool], config: dict,
             feature: bool = False) -> Verdict:
    """Pick the lowest tier a diff allows, with the reasons and the risk list.

    TINY is code of at most tiny_code_lines non-test lines in one area outside backend_paths (and inside
    tiny_folders, when set), or docs of at most tiny_docs_lines lines, with nothing on the risk list and no page,
    layout, route or feature-folder file moved or deleted. FEATURE is a new feature folder, module, route or page, a
    migration that creates a table, a new spec page, a [cycle] feature_triggers line, over feature_code_lines
    non-test lines, or `--feature`. SMALL is everything else.
    """
    settings = _settings(config)
    tiny_code = int(settings.get("tiny_code_lines", TINY_CODE_LINES))
    tiny_docs = int(settings.get("tiny_docs_lines", TINY_DOCS_LINES))
    feature_lines = int(settings.get("feature_code_lines", FEATURE_CODE_LINES))
    backend = tuple(config.get("project", {}).get("backend_paths", []))
    tiny_folders = tuple(settings.get("tiny_folders", ()))
    feature_folders = tuple(settings.get("feature_folders", ()))
    features = ["FEATURE was asked for with --feature"] if feature else []
    features += dict.fromkeys(reason for change in changes for reason in feature_triggers(change, existed, config))
    code_lines: Counter[str] = Counter()
    docs_lines, blocks, risks, seen, areas, outside = 0, [], [], set(), set(), []
    for change in changes:
        if is_docs(change.path, config):
            docs_lines += change.lines
            if change.status in ("D", "R"):
                blocks.append(f"a docs page moved or deleted, {change.old_path}")
        else:
            areas.add(area(change.path))  # tests, lockfiles and generated files have an area too
            if counts(change.path, config):
                code_lines[area(change.path)] += change.lines
            if tiny_folders and not in_folders(change.path, tiny_folders):
                outside.append(change.path)
        if change.status in ("D", "R") and not is_test(change.old_path) and (
                is_structure(change.old_path, config) or in_folders(change.old_path, feature_folders)):
            blocks.append(f"a page, layout, route or feature-folder file moved or deleted, {change.old_path}")
        if backend and change.path.startswith(backend) and not is_test(change.path):
            blocks.append(f"code in a backend path, {change.path}")
        for kind, what in risks_of(change, config):
            if (kind, change.path) not in seen:
                seen.add((kind, change.path))
                risks.append((kind, change.path, what))
    risks.sort(key=lambda r: RISK_ORDER.index(r[0]) if r[0] in RISK_ORDER else len(RISK_ORDER))
    risk_lines = [f"{kind}: {path}" + ("" if what == "the path" else f", {what}") for kind, path, what in risks]
    total = sum(code_lines.values())
    if total > feature_lines:
        features.append(f"{total} non-test code lines, over {feature_lines}, in {', '.join(sorted(code_lines))}")
    if features:
        return Verdict(FEATURE, features, risk_lines)
    if risks:
        blocks.insert(0, f"{len(risks)} {'place' if len(risks) == 1 else 'places'} on the risk list")
    if outside:
        more = ", ..." if len(outside) > 3 else ""
        blocks.append(f"code outside the tiny_folders, {', '.join(outside[:3])}{more}")
    if len(areas) > 1:
        blocks.append(f"code in more than one area, {', '.join(sorted(areas))}")
    if total > tiny_code:
        blocks.append(f"{total} non-test code lines, over {tiny_code}")
    if docs_lines > tiny_docs:
        blocks.append(f"{docs_lines} changed docs lines, over {tiny_docs}")
    return Verdict(SMALL if blocks else TINY, blocks, risk_lines)


def tier_of(config: dict, base: str, head: str = "HEAD", cwd=None, feature: bool = False) -> Verdict:
    """The tier of `head` against `base` from their merge base, read from git in cwd (the repo by default).

    A base that names no commit is an error, since a tier read against nothing means nothing. A diff git can't read
    otherwise is FEATURE, which errs toward more review.
    """
    cwd = cwd or cli.repo_root()
    try:
        _git(cwd, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    except cli.ColonyError:
        raise cli.ColonyError(f"the base {base} names no commit here: run `git fetch origin`, or name the branch "
                              "this one merges into with --base") from None
    try:
        merge_base = _git(cwd, "merge-base", base, head).strip()
        diff = _git(cwd, "diff", "--no-color", "--no-ext-diff", "-U0", "-M", merge_base, head)
        files = set(_git(cwd, "ls-tree", "-r", "--name-only", merge_base).splitlines())
    except cli.ColonyError as e:
        return Verdict(FEATURE, [f"git could not compare {base} with {head}: {e}"], [])
    folders = {"/".join(path.split("/")[:i]) for path in files for i in range(1, path.count("/") + 1)}
    return classify(parse_diff(diff), lambda entry: entry in files or entry in folders, config, feature)


def risk_text(config: dict, base: str, head: str = "HEAD", cwd=None) -> str:
    """The risk list as Markdown bullets for the batch reviewer's prompt, or a line that says none was found."""
    risks = tier_of(config, base, head, cwd).risks
    return "\n".join(f"- {risk}" for risk in risks) or "- none found"


def tier(config: dict, args) -> int:
    """`colony tier`: print the tier, the reasons with --why, and the risk list."""
    base = args.base or f"origin/{config['project']['base']}"
    verdict = tier_of(config, base, args.head, feature=args.feature)
    print(verdict.tier)
    if args.why:
        print("why:" if verdict.reasons else "why: nothing raised it")
        for reason in verdict.reasons:
            print(f"- {reason}")
    print("risks:" if verdict.risks else "risks: none")
    for risk in verdict.risks:
        print(f"- {risk}")
    return 0


# Needs you


def _lead_only(command: str) -> None:
    """Refuse a lead's command in any other session."""
    if os.environ.get(cli.SESSION_ENV, "").lower() != cli.LEAD:
        raise cli.ColonyError(f"{command} is for the lead: a builder sends its question to the lead on its card")


def person_title(person: str) -> str:
    """A person's name as a title shows it, such as Ana."""
    return person[:1].upper() + person[1:]


def needs_title(person: str) -> str:
    """The person's Needs issue title, such as `Needs Ana`."""
    return f"Needs {person_title(person)}"


def find_issue(repo: str, title: str, body: str) -> int:
    """The number of the repo's open issue with this exact title, the newest when a rotation left two open for a
    moment, made with `body` when there is none. Nothing remembers the number, so a rotated issue is never used."""
    listed = json.loads(wait.gh("issue", "list", "--repo", repo, "--state", "open", "--search", f'"{title}" in:title',
                                "--json", "number,title", "--limit", "50") or "[]")
    numbers = sorted(issue["number"] for issue in listed if issue.get("title", "").lower() == title.lower())
    if numbers:
        return numbers[-1]
    url = wait.gh("issue", "create", "--repo", repo, "--title", title, "--body", body)
    return int(url.strip().rstrip("/").rsplit("/", 1)[-1])


def needs_line(lead: str, person: str, question: str, default: str, sender: str | None = None) -> str:
    """The line posted on a Needs issue for the person's lead, signed by `sender` (the lead by default), such as
    `for ana-lead: Ana decides: keep 30 s? Default: yes (from ana-lead)`."""
    question, default = " ".join(question.split()), " ".join(default.split()).rstrip(".")
    if not question or not default:
        raise cli.ColonyError("needs takes a question and its --default")
    if question[-1] not in "?.!":
        question += "?"
    line = f"for {lead}: {person_title(person)} decides: {question} Default: {default} (from {sender or lead})"
    if len(line) >= wait.MAX_LINE:
        raise cli.ColonyError(f"a line stays under {wait.MAX_LINE} characters, and this one has {len(line)}: put the "
                              "detail in a committed file and link it")
    return line


def needs(config: dict, args) -> int:
    """`colony needs "<question>" --default "<x>" [--person p]`: post a decision on the person's Needs issue, for
    their lead. Any session may post one, such as the spec agent's approval question, and signs it with
    $COLONY_SESSION; the lead signs as `<person>-lead`, so its own wait skips the line."""
    me = os.environ.get(cli.SESSION_ENV, "").lower()
    if not me:
        raise cli.ColonyError(f"set {cli.SESSION_ENV} to this session's name: needs signs its line with it")
    person = (args.needs_person or cli.person_of(config, args)).lower()
    lead, repo = wait.lead_name(config, args), config["project"]["repo"]
    line = needs_line(lead, person, args.question, args.default, lead if me == cli.LEAD else me)
    body = (f"The decisions only {person_title(person)} makes, one line each with the lead's default. The lead keeps "
            "working on the default. Answer with a comment `for <the lead's name>: <your answer>`, and your answer "
            "wins.")
    number = tidy.keep_short(config, find_issue(repo, needs_title(person), body))
    wait.gh("issue", "comment", str(number), "--repo", repo, "--body", line)
    print(f"#{number} {line}")
    return 0


# The handover


def handover_text(lead: str, decisions: str, open_questions: str, next_step: str, at: datetime) -> str:
    """The handover comment: who, when, the decisions, the open questions and the next step."""
    return "\n".join([f"handover from {lead}, {board.stamp(at)}", f"decisions: {decisions}",
                      f"open questions: {open_questions}", f"next: {next_step}"])


def fresh_lead_command(config: dict, args) -> list[str]:
    """The command that opens a fresh lead for the same person, with the same name."""
    return [cli.NAME, "--person", cli.person_of(config, args)]


def handover(config: dict, args) -> int:
    """`colony handover`: post the handover on the coordination issue and print the fresh lead's command, or with
    --read, print this lead's last handover."""
    _lead_only("handover")
    lead, repo = wait.lead_name(config, args), config["project"]["repo"]
    number = wait.coordination_issue(repo, config["project"]["name"])
    if args.read:
        comments = json.loads(wait.gh("issue", "view", str(number), "--repo", repo, "--json", "comments") or "{}")
        mine = [c.get("body", "") for c in comments.get("comments", [])
                if c.get("body", "").startswith(f"handover from {lead},")]
        print(mine[-1] if mine else f"no handover from {lead} on #{number} yet")
        return 0
    parts = {"--decisions": args.decisions, "--open": args.open, "--next": args.next}
    missing = [flag for flag, value in parts.items() if not (value or "").strip()]
    if missing:
        raise cli.ColonyError(f"handover needs {', '.join(missing)}: write `none` for an empty one")
    number = tidy.keep_short(config, number)
    body = handover_text(lead, args.decisions.strip(), args.open.strip(), args.next.strip(), board.utcnow())
    url = wait.gh("issue", "comment", str(number), "--repo", repo, "--body", body).strip()
    print(body)
    print(f"posted on #{number}{f': {url}' if url else ''}")
    print(f"Open the fresh lead: {shlex.join(fresh_lead_command(config, args))}")
    return 0


# Card stats

PREDICTED = re.compile(r"\bpredicted:\s*(?P<size>[SML])\s*,\s*(?P<minutes>\d+(?:\.\d+)?)\s*min\w*"
                       r"(?:\s*,\s*(?P<tokens>\d+(?:\.\d+)?)\s*(?P<unit>[KM])\b)?", re.I)
TOKEN_UNITS = {"K": 1_000, "M": 1_000_000}
START_LINE = re.compile(r"start:?\s+this card\b", re.I)  # the lead's `start: this card`, or the older `start this card`
ACTIVE_GAP = timedelta(minutes=2)
FIRST_PROMPTS = 3
NONE = "-"


@dataclass(frozen=True)
class Prediction:
    """The lead's `predicted: S, 20 min[, 15M tokens]` line: size, minutes, and tokens or None."""

    size: str
    minutes: float
    tokens: float | None


@dataclass(frozen=True)
class Window:
    """When a card's builder worked on it: from the start line to the builder's done line, or the stop line."""

    builder: str
    start: datetime | None
    end: datetime | None
    ends_by: str
    prediction: Prediction | None


@dataclass
class Usage:
    """The calls, tokens and active minutes of a builder's transcript lines inside a window."""

    calls: int = 0
    tokens: int = 0
    active: float = 0.0


def moment(text: str) -> datetime:
    """A UTC time from GitHub or a transcript, such as 2026-11-05T10:00:00Z or 2026-11-05T10:00:00.123Z."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def prediction_of(text: str) -> Prediction | None:
    """The first prediction line in a card's text, or None."""
    found = PREDICTED.search(text)
    if found is None:
        return None
    tokens = float(found["tokens"]) * TOKEN_UNITS[found["unit"].upper()] if found["tokens"] else None
    return Prediction(found["size"].upper(), float(found["minutes"]), tokens)


def card_window(card: dict) -> Window:
    """Read a card's builder, window and prediction from `gh issue view --json title,body,comments`.

    The builder is the title's first word before its colon, else the session the first start line names. The window
    opens at the start line for the builder, and closes at the builder's done line, else at a stop line for it.
    """
    comments = sorted(card.get("comments") or [], key=lambda c: moment(c["createdAt"]))
    prediction = prediction_of(card.get("body") or "")
    lines = []
    for comment in comments:
        body = comment.get("body") or ""
        prediction = prediction or prediction_of(body)
        for raw in body.splitlines():
            line = wait.MARKUP.sub("", raw)
            found = wait.LINE.match(line)
            if found:
                signed = wait.SIGNED.search(line)
                lines.append((moment(comment["createdAt"]), found[1].lower(), signed[1].lower() if signed else "",
                              found[2].lower()))
    head = (card.get("title") or "").partition(":")
    titled = head[0].strip().lower() if head[1] and cli.SESSION_NAME.fullmatch(head[0].strip().lower()) else ""
    starts = [(at, to) for at, to, _, sentence in lines if START_LINE.search(sentence)]
    builder = titled or (starts[0][1] if starts else "")
    start = next((at for at, to in starts if to == builder), None)
    if start is None:
        return Window(builder, None, None, "no start line", prediction)
    later = [line for line in lines if line[0] >= start]
    done = next((at for at, _, sender, sentence in later if sender == builder and wait.DONE.match(sentence)), None)
    stop = next((at for at, to, _, sentence in later if to == builder and "stop this card" in sentence), None)
    if done is not None:
        return Window(builder, start, done, "done line", prediction)
    if stop is not None:
        return Window(builder, start, stop, "stop line", prediction)
    return Window(builder, start, None, "open", prediction)


def project_folder(root: Path) -> str:
    """The folder name Claude Code gives a working folder's transcripts: each character but a letter or digit is -."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(root))


def first_prompts(path: Path):
    """The text of a transcript's first user prompts, skipping tool results."""
    count = 0
    with path.open(encoding="utf-8", errors="replace") as lines:
        for raw in lines:
            if count >= FIRST_PROMPTS:
                return
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("type") != "user":
                continue
            content = (entry.get("message") or {}).get("content")
            if isinstance(content, list):
                content = " ".join(block.get("text", "") for block in content
                                   if isinstance(block, dict) and block.get("type") == "text")
            if isinstance(content, str) and content.strip():
                count += 1
                yield content


def transcripts(builder: str, homes: Iterable[Path], root: Path, since: datetime) -> list[Path]:
    """A builder's transcripts in each account folder: the main files that started in the repo and whose first
    prompts say `You are <builder>`, written since the window opened, with their subagents' files."""
    named = re.compile(rf"\bYou are {re.escape(builder)}(?![\w-])")
    found = []
    for home in homes:
        for main in sorted((Path(home) / "projects" / project_folder(root)).glob("*.jsonl")):
            if datetime.fromtimestamp(main.stat().st_mtime, timezone.utc) < since:
                continue
            if any(named.search(prompt) for prompt in first_prompts(main)):
                found += [main, *sorted((main.parent / main.stem / "subagents").glob("*.jsonl"))]
    return found


def measure(files: Iterable[Path], start: datetime, end: datetime) -> Usage:
    """Sum the calls, tokens (input, cache and output) and active minutes inside a window. Each assistant message
    counts once by its message and request ids, and active minutes add only gaps of 2 minutes or less."""
    usage, seen, stamps = Usage(), set(), []
    for path in files:
        with path.open(encoding="utf-8", errors="replace") as lines:
            for raw in lines:
                try:
                    entry = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(entry, dict) or not entry.get("timestamp"):
                    continue
                at = moment(entry["timestamp"])
                if not start <= at <= end:
                    continue
                stamps.append(at)
                message = entry.get("message") or {}
                used = message.get("usage") if entry.get("type") == "assistant" else None
                key = (str(message.get("id")), str(entry.get("requestId")))
                if not used or key in seen:
                    continue
                seen.add(key)
                usage.calls += 1
                usage.tokens += sum(used.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                                "cache_read_input_tokens", "output_tokens"))
    stamps.sort()
    gaps = (later - earlier for earlier, later in zip(stamps, stamps[1:]))
    usage.active = sum((gap for gap in gaps if gap <= ACTIVE_GAP), timedelta()).total_seconds() / 60
    return usage


def diff_lines(base: str, branch: str, cwd) -> str:
    """A branch's `+added -removed` lines against the base, or - when git can't tell."""
    try:
        out = _git(cwd, "diff", "--shortstat", f"{base}...{branch}")
    except cli.ColonyError:
        return NONE
    added, removed = re.search(r"(\d+) insertion", out), re.search(r"(\d+) deletion", out)
    return f"+{added[1] if added else 0} -{removed[1] if removed else 0}" if out.strip() else NONE


def tokens_text(count: float | None) -> str:
    """A token count in K or M, such as 19.1M or 52K."""
    if count is None:
        return NONE
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    return f"{count / 1_000:.0f}K" if count >= 1_000 else f"{count:.0f}"


def main_root() -> Path:
    """The main checkout every session starts in, also when this runs in a worktree."""
    common = cli._out(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"])
    return Path(common).parent if common else cli.repo_root()


def stats_table(config: dict, cards: dict[str, str | None], base: str | None = None, now: datetime | None = None,
                homes: Iterable[Path] | None = None, root: Path | None = None) -> str:
    """The cards' Markdown table of predicted and actual minutes and tokens, with a total row.

    `cards` maps each card number to its branch, or None. The batch's pull request body carries this table.
    """
    now = now or board.utcnow()
    base = base or f"origin/{config['project']['base']}"
    root = root or main_root()
    homes = list(homes) if homes is not None else [Path(a["config_dir"]).expanduser()
                                                   for a in config["accounts"].values()]
    header = ["Card", "Builder", "Size", "Ends by", "Predicted min", "Wall min", "Active min", "Predicted tokens",
              "Tokens", "Lines"]
    rows, total = [], {"predicted": 0.0, "wall": 0.0, "active": 0.0, "predicted_tokens": 0.0, "tokens": 0}
    for number, branch in cards.items():
        card = json.loads(wait.gh("issue", "view", str(number), "--repo", config["project"]["repo"], "--json",
                                  "title,body,comments"))
        window, used = card_window(card), None
        if window.start is not None:
            used = measure(transcripts(window.builder, homes, root, window.start), window.start, window.end or now)
        wall = ((window.end or now) - window.start).total_seconds() / 60 if window.start else None
        guess = window.prediction
        total["predicted"] += guess.minutes if guess else 0
        total["predicted_tokens"] += (guess.tokens or 0) if guess else 0
        total["wall"] += wall or 0
        total["active"] += used.active if used else 0
        total["tokens"] += used.tokens if used else 0
        rows.append([f"#{number}", window.builder or NONE, guess.size if guess else NONE, window.ends_by,
                     f"{guess.minutes:g}" if guess else NONE, f"{wall:.1f}" if wall is not None else NONE,
                     f"{used.active:.1f}" if used else NONE, tokens_text(guess.tokens if guess else None),
                     tokens_text(used.tokens) if used else NONE, diff_lines(base, branch, root) if branch else NONE])
    rows.append(["**total**", "", "", "", f"{total['predicted']:g}", f"{total['wall']:.1f}", f"{total['active']:.1f}",
                 tokens_text(total["predicted_tokens"]), tokens_text(total["tokens"]), ""])
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    return "\n".join(lines + ["| " + " | ".join(row) + " |" for row in rows])


def stats_card(value: str) -> tuple[str, str | None]:
    """A --card value, N or N=BRANCH, as (number, branch or None)."""
    number, _, branch = value.partition("=")
    if not number.lstrip("#").isdigit():
        raise argparse.ArgumentTypeError(f"{value!r} is not N or N=BRANCH")
    return number.lstrip("#"), branch or None


CALIBRATE_CARDS = 30
CALIBRATE_LISTED = 100  # closed issues read to find the last CALIBRATE_CARDS measured cards among them


def calibration(config: dict) -> dict[str, tuple[float, int]]:
    """The median actual minutes per size, {size: (median, cards)}, over the last CALIBRATE_CARDS closed cards with a
    prediction and a done line. A card's actual minutes are its wall minutes, from the start line to the done line."""
    listed = json.loads(wait.gh("issue", "list", "--repo", config["project"]["repo"], "--state", "closed", "--json",
                                "number,title,body,comments", "--limit", str(CALIBRATE_LISTED)) or "[]")
    sizes: dict[str, list[float]] = {}
    measured = 0
    for card in listed:
        window = card_window(card)
        if window.prediction is None or window.ends_by != "done line":
            continue
        sizes.setdefault(window.prediction.size, []).append((window.end - window.start).total_seconds() / 60)
        measured += 1
        if measured == CALIBRATE_CARDS:
            break
    return {size: (statistics.median(minutes), len(minutes)) for size, minutes in sizes.items()}


def calibration_line(config: dict, size: str, prediction: Prediction | None) -> str | None:
    """The median beside a new card's prediction, or None when no measured card of its size is found or gh fails."""
    try:
        found = calibration(config).get(size.upper())
    except cli.ColonyError:
        return None
    if found is None:
        return None
    median, count = found
    guess = f"predicted {prediction.minutes:g} min; " if prediction else ""
    return f"{guess}the last {count} {size.upper()} cards took a median of {median:.0f} min"


def stats(config: dict, args) -> int:
    """`colony stats --card N[=BRANCH] ...`: print the cards' table, or with --calibrate the median actual minutes
    per size over the last CALIBRATE_CARDS cards."""
    if args.calibrate:
        found = calibration(config)
        print(f"Median actual (wall) minutes per size, over the last {CALIBRATE_CARDS} closed cards with a prediction "
              "and a done line:")
        print("| Size | Cards | Median min |\n| --- | --- | --- |")
        for size in sorted(found, key="SML".index):
            print(f"| {size} | {found[size][1]} | {found[size][0]:.0f} |")
        return 0
    if not args.card:
        raise cli.ColonyError("stats needs --card N[=BRANCH], or --calibrate")
    print(stats_table(config, dict(args.card), args.base))
    return 0


# The retro

RETRO_PROMPT = """You are the retro agent for {project}. Batch {batch} has ended, and its round reports are in \
{reports}: each round's review, walk and checks, and minutes.md.

Read them all, and find the lessons: each problem the gate caught that a builder's fast check could have caught, \
each problem that came back in a later round, and each card that ran far over its prediction.

Write each lesson in the checkout {checkout}, on branch {branch}, as one of these two, and never as a note alone:
- A rule line plus a check. The rule line is one sentence with must or must not, in the file of {rules} it belongs \
to. The check fails on the problem: a test, a lint setting, or a script the full check (`{checks}`) runs.
- A decision for the person, with your default, when the lesson turns on a choice only they can make.

Run `{fast_check}` before each commit, and end each commit message with `{trailer}`. Push nothing, and start no \
agent of your own.

Write {report}. Its first line is exactly `lessons: N`. Then one line per lesson: \
`rule: <file> — <the rule line> — check: <the check>`, or `decision: <the question> — default: <your default>`.

Final reply: the lessons line, in under 100 words."""
LESSONS = re.compile(r"lessons:\s*(\d+)", re.I)
DECISION = re.compile(r"^\s*[-*]?\s*decision:\s*(.+?)\s+[—–-]+\s*default:\s*(.+)$", re.I)


def retro_names(config: dict, name: str) -> tuple[str, Path]:
    """The retro's branch and worktree for a batch."""
    tag = config["project"]["name"]
    return f"{tag}/retro-{name}", Path(config["project"]["worktrees"]).expanduser() / f"{tag}-retro-{name}"


def retro_prompt(config: dict, name: str, reports: Path, checkout: Path, branch: str, report: Path,
                 trailer: str) -> str:
    """The retro agent's prompt, filled in for one batch, its check commands for every check area."""
    from colony import batch as runner

    project = config["project"]
    rules = ", ".join(f"`{rule}`" for rule in config.get("gate", {}).get("rules", [f"{cli.DIR}/rules/*.md"]))
    return runner.fill(RETRO_PROMPT, project=project["name"], batch=name, reports=reports, checkout=checkout, branch=branch,
                rules=rules, checks=runner.every_area(config, project["checks"]),
                fast_check=runner.every_area(config, runner.fast_check(project)),
                trailer=trailer, report=report)


def retro(config: dict, args) -> int:
    """`colony retro --name <batch>`: run the retro agent in its own worktree, and open its pull request when it
    finds a lesson. It prints each decision for the lead to post with `colony needs`."""
    from colony import batch as runner

    reports = runner._find_reports(config, args.name, args)
    if reports is None:
        raise cli.ColonyError(f"no reports for batch {args.name!r}: run it with `{cli.NAME} batch` first")
    project, root = config["project"], cli.repo_root()
    branch, checkout = retro_names(config, args.name)
    gate = runner.Batch(config, args.name, {}, f"origin/{project['base']}", root, runner._account(config, args))
    report = checkout / runner.REPORTS / args.name / "retro.md"
    prompt = retro_prompt(config, args.name, reports, checkout, branch, report, gate.trailer)
    role = "retro" if "retro" in config["roles"] else "reviewer"
    agent = runner.claude_cmd(config, role, prompt, [reports])
    worktree = ["git", "worktree", "add", "--no-track", "-b", branch, str(checkout), f"origin/{project['base']}"]
    if args.dry_run:
        print(f"{cli.NAME} retro {args.name}: dry run, nothing runs. The agent runs as {gate.account[0]}.")
        print(f"  $ git fetch origin\n  $ {shlex.join(worktree)}")
        print(f"  $ {shlex.join(agent[:2] + ['<the prompt>'] + agent[3:])}")
        print(f"  then, with a lesson: $ git push -u origin {branch}, and a pull request into {project['base']}")
        print(f"\n--- retro prompt\n{prompt}")
        return 0
    _git(root, "fetch", "origin")
    _git(root, *worktree[1:])
    run = subprocess.run(agent, cwd=checkout, env=gate.agent_env(), capture_output=True, text=True)
    if run.returncode or not report.exists():
        raise cli.ColonyError(f"the retro agent ended without {report} (exit {run.returncode}); its worktree stays "
                              f"at {checkout}")
    text = report.read_text()
    lessons = int(found[1]) if (found := LESSONS.search(text.split("\n", 1)[0])) else 0
    if lessons == 0:
        _git(root, "worktree", "remove", "--force", str(checkout))
        _git(root, "branch", "-D", branch)
        print(f"retro {args.name}: no lessons")
        return 0
    _git(checkout, "add", "--", str(report.relative_to(checkout)))
    if _git(checkout, "status", "--porcelain", "--", str(report.relative_to(checkout))).strip():
        _git(checkout, "commit", "-m", f"docs(colony): lessons from batch {args.name}\n\n{gate.trailer}")
    if branch == project["base"] or not branch.startswith(f"{project['name']}/retro-"):
        raise cli.ColonyError(f"refusing to push {branch}")
    _git(checkout, "push", "-u", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
    url = wait.gh("pr", "create", "--repo", project["repo"], "--base", project["base"], "--head", branch, "--title",
                  f"{project['name']}: lessons from batch {args.name}", "--body-file", str(report)).strip()
    print(f"retro {args.name}: {lessons} lessons. {url}")
    for question, default in (m.groups() for line in text.splitlines() if (m := DECISION.match(line))):
        print(f'  post: {cli.NAME} needs "{question}" --default "{default}"')
    return 0


# Stale cards


def stale_lines(config: dict, now) -> list[str]:
    """The `stale:` lines for the lead's wait: one per card In progress whose Last update is older than
    [cycle] stale_hours (2.5 by default). The board has no State, so a helper waiting on a usage limit is stale too:
    the lead looks at its session and finds out.

    `now` is an aware datetime, or a Unix time. Each card is reported once until its Last update changes, through
    a state file in ~/.colony/<project>/. Call it at most every STALE_CHECK_MINUTES. It returns [] when the repo has
    no board, and raises cli.ColonyError when the board can't be read, which the caller prints and goes on.
    """
    now = now if isinstance(now, datetime) else datetime.fromtimestamp(now, timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    found = board.find_board(config)
    if found is None:
        return []
    after = timedelta(hours=float(_settings(config).get("stale_hours", STALE_HOURS)))
    path = wait.state_path(config["project"]["name"], f"{cli.LEAD}-stale")
    reported = wait.read_json(path, {})
    reported = reported if isinstance(reported, dict) else {}
    lines = []
    for item in board.items(found):
        last = board.field_value(item, board.LAST_UPDATE)
        if board.squash(board.field_value(item, "Status")) != board.squash("In progress"):
            continue
        if item["state"] and item["state"] != "OPEN":
            continue
        updated = board.read_stamp(last)
        key = f"{item['id']}:{last}"
        if updated is None or now - updated <= after or key in reported:
            continue
        reported[key] = now.isoformat()
        who = board.field_value(item, "Helper") or "its helper"
        lines.append(f"#{item['number']} stale: {who} shows no update since {last}; check its session")
    reported = {key: at for key, at in reported.items() if now - moment(at) <= KEEP_REPORTED}
    wait.write_json(path, reported)
    return lines


def add_commands(sub) -> None:
    """cli.py's route to this module: tier, needs, handover, stats and retro."""
    p = sub.add_parser("tier", help="print TINY, SMALL or FEATURE from a branch's diff, and its risk list")
    p.add_argument("--base", help="the branch it merges into, origin/<base> by default")
    p.add_argument("--head", default="HEAD", help="the branch to read, HEAD by default, such as origin/builder-1/12")
    p.add_argument("--feature", action="store_true", help="FEATURE whatever the diff holds: a spec was asked for")
    p.add_argument("--why", action="store_true", help="print each reason after the tier")
    p.set_defaults(run=tier)

    p = sub.add_parser("needs", help="post a decision on the person's Needs issue, with your default")
    p.add_argument("question", help="the question, one sentence")
    p.add_argument("--default", required=True, help="what you do until the person answers")
    p.add_argument("--person", dest="needs_person", metavar="PERSON", help="whose decision it is, you by default")
    p.set_defaults(run=needs)

    p = sub.add_parser("handover", help="the lead: post the handover before compaction, or --read the last one")
    p.add_argument("--decisions", help="each decision made, with its card")
    p.add_argument("--open", help="each open question, and where it waits")
    p.add_argument("--next", help="what you were about to do")
    p.add_argument("--read", action="store_true", help="print your last handover instead")
    p.set_defaults(run=handover)

    p = sub.add_parser("stats", help="each card's predicted and actual minutes and tokens, as a table")
    p.add_argument("--card", action="append", type=stats_card, metavar="N[=BRANCH]",
                   help="a card's issue number, and its branch for the lines column; repeat for each card")
    p.add_argument("--base", help="the branch the cards' branches are measured against, origin/<base> by default")
    p.add_argument("--calibrate", action="store_true",
                   help=f"print the median actual minutes per size over the last {CALIBRATE_CARDS} cards instead")
    p.set_defaults(run=stats)

    p = sub.add_parser("retro", help="after a batch: an agent turns its lessons into rules and checks, in a PR")
    p.add_argument("--name", required=True, help="the batch name")
    p.add_argument("--person", help="whose accounts the agent uses")
    p.add_argument("--dry-run", action="store_true", help="print the plan and the prompt, and run nothing")
    p.set_defaults(run=retro)
