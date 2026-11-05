"""colony batch and colony status: take a batch of finished cards through checks, review, walk and fixes to one pull request.

The command line in cli.py calls `run_batch(config, args)` and `batch_status(config, args)` with the dict
`load_config` returns. The args read are `name`, `card` (a list of `N=BRANCH`), `from_branch` and `dry_run`, and the
optional `account`, `person` and `repo`. The account rules and the repository root come from cli.py. Each batch's
reports go to `.colony/reports/<batch>/` in its worktree, and land on the batch branch.
"""

from __future__ import annotations

import concurrent.futures as futures
import fnmatch
import json
import os
import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from colony import cli

REPORTS = f"{cli.DIR}/reports"  # each batch's reports folder, inside its worktree
PROVIDER_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")
OPEN = re.compile(r"open:\s*(\d+)\b", re.I)
WALK = re.compile(r"walk:\s*(pass|fail)\b", re.I)
FINDING = re.compile(r"^\s*(?:[-*]|\d+[.)])?\s*`?(?P<path>[^\s`:]+):(?P<line>\d+)(?:[-–:]\d+)*`?\s*(?:—|–|--?)\s*(?P<text>\S.*)$")
FIXED = re.compile(r"^\W*fixed\b|\bfixed\W*$", re.I)
IMAGE = re.compile(r"\.(png|jpe?g|webp|gif)\b", re.I)
PYTEST_FAILED = re.compile(r"\bFAILED\s+(\S+?\.py)::(\S+)")
JS_FAILED = re.compile(r"(?:\bFAIL\b|×|✗)\s+(\S+\.(?:test|spec)\.[cm]?[jt]sx?)(?:\s*>\s*(.+))?")
MINUTE = re.compile(r"^(\d{1,2}:\d{2})\s+(\S+)\s+(\d+(?:\.\d+)?)(?:\s+\$(\d+(?:\.\d+)?))?")
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*\.py$|_test\.py$|\.(test|spec)\.[cm]?[jt]sx?$")


class Finding(NamedTuple):
    """One problem for a fixer: the file it is in (empty when unknown), its line (0 when unknown), and what is wrong."""

    path: str
    line: int
    text: str


class Stop(Exception):
    """A stop rule fired; the message says why."""


# Pure helpers


def fill(template: str, **values) -> str:
    """Replace each `{name}` in a prompt template with its value, raising KeyError for a placeholder with no value."""

    def value(match: re.Match) -> str:
        if match[1] not in values:
            raise KeyError(f"the template needs a value for {{{match[1]}}}")
        return str(values[match[1]])

    return re.sub(r"\{(\w+)\}", value, template)


def classify_conflict(paths, generated_globs) -> str:
    """Class a merge conflict as "generated" when every conflicted path matches a generated glob, else "other"."""
    paths = list(paths)
    if paths and all(any(fnmatch.fnmatchcase(p, g) for g in generated_globs) for p in paths):
        return "generated"
    return "other"


def _first_line(text: str) -> str:
    """Return a report's first non-blank line, without Markdown emphasis or heading marks around it."""
    return next((line.strip().strip("`*# ") for line in text.splitlines() if line.strip()), "")


def parse_open(text: str) -> int | None:
    """Read `open: N`, the confirmed problems still open, from a review report's first line, or None when it is not there."""
    match = OPEN.match(_first_line(text))
    return int(match[1]) if match else None


def parse_walk(text: str) -> str | None:
    """Read `walk: pass` or `walk: fail` from a walk report's first line, or None when it is not there."""
    match = WALK.match(_first_line(text))
    return match[1].lower() if match else None


def parse_findings(text: str) -> list[Finding]:
    """Read each `path:line — what is wrong — …` line of a review report, leaving out earlier findings marked fixed."""
    found, seen = [], set()
    for raw in text.splitlines():
        match = FINDING.match(raw)
        if not match:
            continue
        path, body = match["path"].strip("*"), match["text"].strip()
        if ("/" not in path and "." not in path) or FIXED.search(body) or (path, match["line"]) in seen:
            continue
        seen.add((path, match["line"]))
        found.append(Finding(path, int(match["line"]), body))
    return found


def parse_walk_failures(text: str) -> list[Finding]:
    """Read each `flow — what happened — screenshot — likely file` line of a walk report, using the likely file as the path."""
    found = []
    for raw in text.splitlines()[1:]:
        parts = [part.strip(" `*-") for part in re.split(r"\s+[—–]\s+", raw.strip())]
        if len(parts) < 3 or not any(IMAGE.search(part) for part in parts):
            continue
        place = re.fullmatch(r"([^\s:]+?)(?::(\d+))?", parts[-1])
        if place and not IMAGE.search(parts[-1]) and ("/" in place[1] or "." in place[1]):
            found.append(Finding(place[1], int(place[2] or 0), raw.strip()))
        else:
            found.append(Finding("", 0, raw.strip()))
    return found


def parse_check_failures(output: str) -> list[Finding]:
    """Read each failing test name from a check run's output, or one finding naming the failed checks when none parses."""
    found, seen = [], set()
    for raw in output.splitlines():
        if match := PYTEST_FAILED.search(raw):
            finding = Finding(match[1], 0, f"failing test {match[1]}::{match[2]}")
        elif match := JS_FAILED.search(raw):
            finding = Finding(match[1], 0, f"failing test {match[1]}" + (f" > {match[2].strip()}" if match[2] else ""))
        else:
            continue
        if finding.text not in seen:
            seen.add(finding.text)
            found.append(finding)
    if not found:
        fails = [line.strip() for line in output.splitlines() if line.startswith("FAIL")]
        last = [line.strip() for line in output.splitlines() if line.strip()][-1:]
        found.append(Finding("", 0, "checks failed: " + "; ".join(fails[:5] or last or ["no output"])))
    return found


def owner_of(path: str, card_branches, repo, base: str | None = None) -> str:
    """Name the card whose branch made the newest commit to path since base, falling back to the first card.

    base defaults to the point all the card branches share.
    """
    branches = dict(card_branches)
    cards = list(branches)
    if not path or len(cards) < 2:
        return cards[0]
    base = base or _git(repo, "merge-base", "--octopus", *branches.values(), check=False)
    best, newest = cards[0], -1
    for card, branch in branches.items():
        stamp = _git(repo, "log", "-1", "--format=%ct", f"{base}..{branch}", "--", path, check=False)
        if stamp.isdigit() and int(stamp) > newest:
            best, newest = card, int(stamp)
    return best


def minutes_table(lines) -> str:
    """Sum `HH:MM step minutes [$cost]` lines per kind of step (the name before its first dash) into a Markdown table."""
    if isinstance(lines, str):
        lines = lines.splitlines()
    rows: dict[str, list[float]] = {}
    for line in lines:
        if match := MINUTE.match(line.strip()):
            row = rows.setdefault(match[2].split("-")[0], [0, 0.0, 0.0])
            row[0] += 1
            row[1] += float(match[3])
            row[2] += float(match[4] or 0)
    table = ["| Step | Runs | Minutes | Cost |", "| --- | ---: | ---: | ---: |"]
    table += [f"| {kind} | {runs:.0f} | {mins:.1f} | ${cost:.2f} |" for kind, (runs, mins, cost) in rows.items()]
    totals = [sum(row[i] for row in rows.values()) for i in range(3)]
    table.append(f"| **total** | {totals[0]:.0f} | {totals[1]:.1f} | ${totals[2]:.2f} |")
    return "\n".join(table)


# Shelling out


def _run(cmd: list[str], cwd, check: bool = True, env=None) -> subprocess.CompletedProcess:
    """Run one command given as a list and capture its text output; raise Stop when check is set and it fails."""
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if check and proc.returncode:
        raise Stop(f"`{shlex.join(cmd[:3])}` failed: {(proc.stderr or proc.stdout).strip()[-600:]}")
    return proc


def _git(cwd, *args: str, check: bool = True) -> str:
    """Run one git command in cwd and return its stripped output."""
    return _run(["git", *args], cwd, check).stdout.strip()


def _touches(paths: list[str], prefixes: list[str]) -> bool:
    """Say whether any path starts with any of the prefixes."""
    return any(path.startswith(prefix) for path in paths for prefix in prefixes)


def claude_cmd(config: dict, role: str, prompt: str, add_dirs=()) -> list[str]:
    """Build the headless `claude -p` command for one role, with its model, effort and optional agent."""
    settings = config["roles"][role]
    cmd = ["claude", "-p", prompt, "--model", settings["model"], "--effort", settings["effort"],
           "--permission-mode", "auto", "--output-format", "json"]
    if settings.get("agent"):
        cmd += ["--agent", settings["agent"]]
    for folder in add_dirs:
        cmd += ["--add-dir", str(folder)]
    return cmd


def _result(stdout: str) -> dict:
    """Read the JSON result a headless claude run prints, or an empty dict when it printed none."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


# One batch


@dataclass
class Batch:
    """One batch run: its config, cards, names, paths and running state."""

    config: dict
    name: str
    cards: dict[str, str]
    start: str
    root: Path
    account: tuple[str, str]
    dry: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)
    state: dict = field(default_factory=lambda: {"round": 0, "running": {}, "rounds": [], "backend_passed": False})

    @classmethod
    def from_args(cls, config: dict, args) -> Batch:
        """Work out the batch from the parsed command line, refusing a bad name or card."""
        name = getattr(args, "name", None) or ""
        if not re.fullmatch(r"[\w.-]+", name):
            raise SystemExit(f"colony batch needs --name made of letters, digits, dots and dashes, got {name!r}")
        cards = {}
        for item in getattr(args, "card", None) or []:
            number, sep, branch = item.partition("=")
            if not sep or not number.strip("# ") or not branch.strip():
                raise SystemExit(f"--card wants N=BRANCH, got {item!r}")
            cards[number.strip("# ")] = branch.strip()
        if not cards:
            raise SystemExit("colony batch needs at least one --card N=BRANCH")
        start = getattr(args, "from_branch", None) or f"origin/{config['project']['base']}"
        return cls(config, name, cards, start, _root(config, args), _account(config, args), bool(getattr(args, "dry_run", False)))

    def __post_init__(self) -> None:
        """Work out the names and paths every step uses.

        project and tag are the config's [project] table and short name; branch is the batch branch; wt is its
        worktree, where the checks run and the reports live; walk_wt is the walker's second worktree; reports is
        the round files' folder; trailer is the line every commit the run makes or asks for ends with.
        """
        self.project = self.config["project"]
        self.tag = self.project["name"]
        self.branch = f"{self.tag}/batch-{self.name}"
        self.worktrees = Path(self.project["worktrees"]).expanduser()
        self.wt = self.worktrees / f"{self.tag}-batch-{self.name}"
        self.walk_wt = self.worktrees / f"{self.tag}-batch-{self.name}-walk"
        self.reports = self.wt / REPORTS / self.name
        self.trailer = self.project.get("trailer") or f"Assisted-by: claude-code:{self.config['roles']['fixer']['model']}"

    def fix_names(self, card: str, r: int) -> tuple[str, Path]:
        """The fix branch and worktree for one card in one round."""
        return f"{self.tag}/fix-{self.name}-{card}-r{r}", self.worktrees / f"{self.tag}-fix-{self.name}-{card}-r{r}"

    def git(self, *args: str, check: bool = True) -> str:
        """Run git in the batch worktree."""
        return _git(self.wt, *args, check=check)

    def agent_env(self) -> dict:
        """The environment for headless agents: the picked account, and no API key, so runs use the account.

        The default settings folder leaves CLAUDE_CONFIG_DIR unset, since Claude Code ties a login to its value.
        """
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDE_CONFIG_DIR")}
        if not cli.is_default_dir(self.account[1]):
            env["CLAUDE_CONFIG_DIR"] = self.account[1]
        return env

    def check_env(self) -> dict:
        """The environment for the checks: check_env_file's values added, and provider keys dropped at a zero budget."""
        env = dict(os.environ)
        if self.project.get("check_env_file"):
            for line in (self.root / Path(self.project["check_env_file"]).expanduser()).read_text().splitlines():
                key, sep, value = line.strip().removeprefix("export ").partition("=")
                if sep and key and not key.startswith("#"):
                    env[key.strip()] = value.strip().strip("'\"")
        if not self.config.get("budget", {}).get("provider_dollars"):
            for key in PROVIDER_KEYS:
                env.pop(key, None)
        return env

    def save(self) -> None:
        """Write state.json for `colony status`."""
        with self.lock:
            if self.reports.is_dir():
                (self.reports / "state.json").write_text(json.dumps(self.state, indent=2))

    def running(self, step: str, on: bool) -> None:
        """Mark a step as running or ended in state.json."""
        with self.lock:
            if on:
                self.state["running"][step] = time.strftime("%H:%M")
            else:
                self.state["running"].pop(step, None)
            self.save()

    def minute(self, step: str, minutes: float, cost=None, clock: str | None = None) -> None:
        """Append `HH:MM step minutes [$cost]` to minutes.md."""
        line = f"{clock or time.strftime('%H:%M')} {step} {minutes:.1f}" + (f" ${cost:.2f}" if cost is not None else "")
        with self.lock, (self.reports / "minutes.md").open("a") as out:
            out.write(line + "\n")

    def shell(self, step: str, cmd: str, cwd: Path) -> None:
        """Run one of the config's shell commands (regen, install) as a timed step; stop the run when it fails."""
        started, clock = time.time(), time.strftime("%H:%M")
        self.running(step, True)
        proc = subprocess.run(cmd, shell=True, cwd=cwd, env=self.check_env(), capture_output=True, text=True)
        self.running(step, False)
        self.minute(step, (time.time() - started) / 60, clock=clock)
        if proc.returncode:
            raise Stop(f"{step} exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[-600:]}")

    def install(self, cwd: Path) -> None:
        """Install packages in a new worktree when the config names an install command."""
        if self.project.get("install"):
            self.shell("install", self.project["install"], cwd)


def _root(config: dict, args=None) -> Path:
    """The host repository: --repo when given, else the checkout the command runs in."""
    return Path(getattr(args, "repo", None) or cli.repo_root()).expanduser()


def _account(config: dict, args) -> tuple[str, str]:
    """Pick the agents' account as (name, config_dir): --account, else the person's account with the most room.

    The person is --person, else the session's COLONY_PERSON, else cli.default_person.
    """
    name = getattr(args, "account", None)
    if name:
        return name, str(Path(config["accounts"][name]["config_dir"]).expanduser())
    return cli.pick_account(config, cli.person_of(config, args))


# Prompts


def _cards_text(b: Batch) -> str:
    """List the cards with their branches for a prompt."""
    return ", ".join(f"#{n} (`{ref}`)" for n, ref in b.cards.items())


def reviewer_prompt(b: Batch, r: int, head: str, prev: dict | None) -> str:
    """Fill the reviewer template for round r, reviewing from the base, or from the previous round's head."""
    gate = b.config["gate"]
    earlier = b.reports / f"review-{r - 1}.md"
    previous = "" if prev is None else f"This is round {r}. The previous report is {earlier}: mark each of its findings fixed or open."
    return fill(cli.package_file("prompts", "reviewer.md"), project=b.tag, checkout=b.wt, branch=b.branch, head=head,
                diff_range=f"origin/{b.project['base']}...HEAD" if prev is None else f"{prev['head']}..HEAD",
                generated=", ".join(f"`{g}`" for g in b.project.get("generated", [])), cards=_cards_text(b),
                previous=previous, rubric="\n".join(f"{i}. {item}" for i, item in enumerate(gate["rubric"], 1)),
                rules=", ".join(f"`{rule}`" for rule in gate.get("rules", [])), report=b.reports / f"review-{r}.md")


def walker_prompt(b: Batch, r: int, head: str) -> str:
    """Fill the walker template for round r, pointing at the previous walk report when there is one."""
    earlier = b.reports / f"walk-{r - 1}.md"
    previous = f"The previous walk report is {earlier}: walk its failed flows first." if r > 1 and earlier.exists() else ""
    return fill(cli.package_file("prompts", "walker.md"), walk_checkout=b.walk_wt, head=head, busy=b.wt,
                cards=_cards_text(b), previous=previous, report=b.reports / f"walk-{r}.md")


def fixer_prompt(b: Batch, r: int, items: list[Finding], checkout: Path, branch: str) -> str:
    """Fill the fixer template with one card's findings, and the full checks when any finding is in a backend path."""
    lines = []
    for f in items:
        place = f"{f.path}:{f.line} — " if f.path and f.line else f"{f.path} — " if f.path else ""
        lines.append(f"- {place}{f.text}")
    backend = _touches([f.path for f in items], b.project.get("backend_paths", []))
    checks = b.project["checks"] if backend or not b.project.get("web_checks") else b.project["web_checks"]
    return fill(cli.package_file("prompts", "fixer.md"), project=b.tag, checkout=checkout, branch=branch, round=r,
                batch=b.name, reports=b.reports, findings="\n".join(lines), checks=checks, trailer=b.trailer)


# The run


def run_agent(b: Batch, role: str, prompt: str, cwd: Path, step: str, report: Path | None = None,
              parse=None, add_dirs=()) -> dict:
    """Run one headless claude session and record its minutes and cost; retry once when it fails or leaves no valid report."""
    cmd = claude_cmd(b.config, role, prompt, add_dirs)
    for attempt in (1, 2):
        label = step if attempt == 1 else f"{step}-retry"
        started, clock = time.time(), time.strftime("%H:%M")
        b.running(label, True)
        proc = subprocess.run(cmd, cwd=cwd, env=b.agent_env(), capture_output=True, text=True)
        b.running(label, False)
        (b.reports / f"{label}.json").write_text(proc.stdout or proc.stderr)
        data = _result(proc.stdout)
        b.minute(label, data.get("duration_ms", (time.time() - started) * 1000) / 60000, data.get("total_cost_usd"), clock)
        ok = proc.returncode == 0 and not data.get("is_error")
        if ok and report is not None:
            ok = report.exists() and (parse is None or parse(report.read_text()) is not None)
        if ok:
            return data
    raise Stop(f"{step} failed twice (exit {proc.returncode}); its log is {b.reports / f'{step}-retry.json'}")


def merge_into_batch(b: Batch, ref: str) -> None:
    """Merge a branch into the batch with --no-ff, taking its side of a generated-only conflict and running regen."""
    proc = _run(["git", "merge", "--no-ff", "--no-edit", ref], b.wt, check=False)
    if proc.returncode == 0:
        return
    paths = b.git("diff", "--name-only", "--diff-filter=U").splitlines()
    if classify_conflict(paths, b.project.get("generated", [])) != "generated":
        b.git("merge", "--abort", check=False)
        raise Stop(f"merging {ref} conflicts outside the generated paths: {', '.join(paths) or proc.stderr.strip()}")
    try:
        b.git("checkout", "--theirs", "--", *paths)
        if b.project.get("regen"):
            b.shell("regen", b.project["regen"], b.wt)
        b.git("add", "-A", "--", ".", f":(exclude){REPORTS}/{b.name}")
        b.git("commit", "--no-edit")
    except Stop:
        b.git("merge", "--abort", check=False)
        raise


def assemble(b: Batch) -> None:
    """Make the batch branch in its own worktree from the start point and merge each card branch into it."""
    started, clock = time.time(), time.strftime("%H:%M")
    _git(b.root, "fetch", "origin")
    for card, branch in b.cards.items():
        local = _run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], b.root, check=False)
        remote = _run(["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], b.root, check=False)
        if local.returncode and remote.returncode:
            raise Stop(f"card #{card}'s branch {branch} is neither a local branch nor on origin")
        b.cards[card] = branch if local.returncode == 0 else f"origin/{branch}"
    _git(b.root, "worktree", "add", "--no-track", "-b", b.branch, str(b.wt), b.start)
    b.reports.mkdir(parents=True, exist_ok=True)
    b.state.update(batch=b.name, branch=b.branch, cards=b.cards)
    for ref in b.cards.values():
        merge_into_batch(b, ref)
    b.minute("assemble", (time.time() - started) / 60, clock=clock)
    b.install(b.wt)


def walk_round(b: Batch, r: int, head: str) -> None:
    """Move the walk worktree to the round's head, making it the first time, and run the walker there."""
    if b.walk_wt.exists():
        _git(b.walk_wt, "checkout", "--detach", head)
    else:
        _git(b.root, "worktree", "add", "--detach", str(b.walk_wt), head)
        b.install(b.walk_wt)
    run_agent(b, "walker", walker_prompt(b, r, head), b.walk_wt, f"walk-r{r}", b.reports / f"walk-{r}.md",
              parse_walk, add_dirs=[b.reports])


def run_checks(b: Batch, r: int, cmd: str, proc: subprocess.Popen, log: Path, started: float, clock: str):
    """Wait for the round's background checks and write checks-<r>.md; return (passed, result line, failures)."""
    code = proc.wait()
    b.running(f"checks-r{r}", False)
    b.minute(f"checks-r{r}", (time.time() - started) / 60, clock=clock)
    output = log.read_text(errors="replace")
    last = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), "no output")
    failures = [] if code == 0 else parse_check_failures(output)
    summary = [f"checks: {'pass' if code == 0 else 'fail'}", "", f"`{cmd}` exited {code}: {last}", ""]
    (b.reports / f"checks-{r}.md").write_text("\n".join(summary + [f"- {f.text}" for f in failures]) + "\n")
    return code == 0, last, failures


def gate(b: Batch, r: int) -> list[Finding]:
    """Run round r's checks, review and walk in parallel, record them, and return the findings.

    The round is done, and the findings empty, when the checks pass, the review reports `open: 0`, and the walk
    passed or was skipped.
    """
    project, settings = b.project, b.config["gate"]
    head = b.git("rev-parse", "HEAD")
    prev = b.state["rounds"][-1] if b.state["rounds"] else None
    changed = b.git("diff", "--name-only", f"{prev['head']}..HEAD" if prev else f"origin/{project['base']}...HEAD").splitlines()
    full = _touches(changed, project.get("backend_paths", [])) or not b.state["backend_passed"] or not project.get("web_checks")
    cmd = project["checks"] if full else project["web_checks"]
    rewalk = bool(prev and prev["walk"] == "fail")
    walk = bool(settings.get("walk")) and (rewalk or _touches(changed, settings.get("walk_paths") or [""]))
    b.state["round"] = r
    log = b.reports / f"checks-{r}.log"
    started, clock = time.time(), time.strftime("%H:%M")
    b.running(f"checks-r{r}", True)
    with log.open("wb") as out:
        proc = subprocess.Popen(cmd, shell=True, cwd=b.wt, env=b.check_env(), stdout=out, stderr=subprocess.STDOUT)
    review_report, walk_report = b.reports / f"review-{r}.md", b.reports / f"walk-{r}.md"
    with futures.ThreadPoolExecutor(max_workers=2) as pool:
        review = pool.submit(run_agent, b, "reviewer", reviewer_prompt(b, r, head, prev), b.wt, f"review-r{r}",
                             review_report, parse_open)
        walked = pool.submit(walk_round, b, r, head) if walk else None
        passed, last, check_findings = run_checks(b, r, cmd, proc, log, started, clock)
        review.result()
        if walked:
            walked.result()
    review_text = review_report.read_text()
    open_count = parse_open(review_text)
    walk_text = walk_report.read_text() if walk else ""
    walk_result = parse_walk(walk_text) if walk else "skipped"
    signature = sorted(re.sub(r"\d+(\.\d+)?m?s\b", "", f.text) for f in check_findings)
    b.state["rounds"].append({"round": r, "head": head, "open": open_count, "walk": walk_result,
                              "checks": "pass" if passed else "fail", "checks_cmd": cmd, "checks_line": last,
                              "checks_signature": signature})
    b.state["backend_passed"] = b.state["backend_passed"] or (passed and full)
    b.save()
    if not passed and prev and prev["checks"] == "fail" and prev["checks_signature"] == signature:
        raise Stop(f"the checks failed the same way in rounds {r - 1} and {r}")
    if passed and open_count == 0 and walk_result in ("pass", "skipped"):
        return []
    findings = []
    if open_count:
        missing = Finding("", 0, f"the review counts {open_count} open problems; read {review_report}")
        findings += parse_findings(review_text) or [missing]
    if walk_result not in ("pass", "skipped"):
        findings += parse_walk_failures(walk_text) or [Finding("", 0, f"the walk failed; read {walk_report}")]
    return findings + check_findings


def _resolve(b: Batch, path: str) -> str:
    """Turn a finding's path into a repository path: drop the checkout prefix, and find a test path given from a subfolder."""
    path = path.removeprefix(str(b.wt) + "/")
    if not path or (b.wt / path).exists():
        return path
    hits = b.git("ls-files", "--", f":(glob)**/{path}", check=False).splitlines()
    return hits[0] if hits else path


def fix_card(b: Batch, r: int, card: str, items: list[Finding], head: str) -> tuple[str, Path]:
    """Cut one card's fix branch from the batch head, run its fixer there, and return the branch once it holds a commit."""
    branch, path = b.fix_names(card, r)
    _git(b.root, "worktree", "add", "-b", branch, str(path), head)
    b.install(path)
    run_agent(b, "fixer", fixer_prompt(b, r, items, path, branch), path, f"fix-r{r}-{card}", add_dirs=[b.reports])
    if _git(path, "rev-list", "--count", f"{head}..HEAD") == "0":
        raise Stop(f"the fixer for #{card} in round {r} committed nothing")
    return branch, path


def fix_round(b: Batch, r: int, findings: list[Finding]) -> None:
    """Route the findings to their cards, run one fixer per card in parallel, and merge every fix branch into the batch."""
    head = b.git("rev-parse", "HEAD")
    groups: dict[str, list[Finding]] = {}
    for f in findings:
        groups.setdefault(owner_of(_resolve(b, f.path), b.cards, b.wt, b.start), []).append(f)
    with futures.ThreadPoolExecutor(max_workers=len(groups)) as pool:
        jobs = [pool.submit(fix_card, b, r, card, items, head) for card, items in groups.items()]
    for branch, path in [job.result() for job in jobs]:
        merge_into_batch(b, branch)
        _git(b.root, "worktree", "remove", "--force", str(path))


def commit_reports(b: Batch, result: str) -> None:
    """Write result.md and commit the batch's Markdown reports to the batch branch."""
    if not b.reports.is_dir():
        return
    b.state["result"] = result
    b.save()
    rounds = [f"- Round {x['round']}: open {x['open']}, walk {x['walk']}, checks {x['checks']}" for x in b.state["rounds"]]
    (b.reports / "result.md").write_text("\n".join([f"result: {result}", "", *rounds]) + "\n")
    b.git("add", "--", *sorted(str(p.relative_to(b.wt)) for p in b.reports.glob("*.md")))
    if _run(["git", "diff", "--cached", "--quiet"], b.wt, check=False).returncode:
        b.git("commit", "-m", f"docs(colony): batch {b.name} reports\n\n{b.trailer}")


def removed_tests(b: Batch) -> list[str]:
    """List the test files the batch deletes, from `git diff --name-status` against the base."""
    out = b.git("diff", "--name-status", f"origin/{b.project['base']}...HEAD")
    return [line.split("\t")[1] for line in out.splitlines() if line.startswith("D") and TEST_PATH.search(line.split("\t")[1])]


def pr_body(b: Batch) -> str:
    """The pull request body: the cards, the open problems by round, the check results, the removed tests, and the minutes."""
    rounds = b.state["rounds"]
    minutes = (b.reports / "minutes.md").read_text().splitlines() if (b.reports / "minutes.md").exists() else []
    return "\n".join([
        "## Cards", *[f"- #{n} from `{ref}`" for n, ref in b.cards.items()], "",
        "## Open problems by round", " → ".join(str(x["open"]) for x in rounds), "",
        "| Round | Open | Walk | Checks |", "| --- | --- | --- | --- |",
        *[f"| {x['round']} | {x['open']} | {x['walk']} | {x['checks']} |" for x in rounds], "",
        "## Checks", *[f"- Round {x['round']}: `{x['checks_cmd']}` {x['checks']}: {x['checks_line']}" for x in rounds], "",
        "## Removed tests", *([f"- `{p}`" for p in removed_tests(b)] or ["None."]), "",
        "## Minutes", minutes_table(minutes), "",
        f"The round reports are in `{REPORTS}/{b.name}/`.", "", b.trailer, ""])


def push_cmd(b: Batch) -> list[str]:
    """The one push the runner makes: the batch branch, never the base."""
    return ["git", "push", "-u", "origin", f"refs/heads/{b.branch}:refs/heads/{b.branch}"]


def pr_cmd(b: Batch, body: Path) -> list[str]:
    """The `gh pr create` command for the batch."""
    return ["gh", "pr", "create", "--repo", b.project["repo"], "--base", b.project["base"], "--head", b.branch,
            "--title", f"{b.tag}: batch {b.name} (" + ", ".join(f"#{n}" for n in b.cards) + ")", "--body-file", str(body)]


def open_pr(b: Batch) -> str:
    """Commit the reports, push the batch branch, and open its pull request into the base; return the PR's address."""
    if b.branch == b.project["base"] or not b.branch.startswith(f"{b.tag}/batch-"):
        raise Stop(f"refusing to push {b.branch}")
    body = b.reports / "pr.md"
    body.write_text(pr_body(b))
    commit_reports(b, "done")
    _run(push_cmd(b), b.wt)
    return _run(pr_cmd(b, body), b.wt).stdout.strip()


def plan(b: Batch) -> str:
    """Describe the run without running it: the branches, the commands, and round 1's prompts filled in."""
    project, settings = b.project, b.config["gate"]
    head = "<batch head>"
    generated, backend = ", ".join(project.get("generated", [])), ", ".join(project.get("backend_paths", []))
    fix_branch, fix_path = b.fix_names(next(iter(b.cards)), 1)
    lines = [f"colony batch {b.name}: dry run, nothing runs. Agents run as {b.account[0]}.", "", "Branches:",
             f"  batch  {b.branch} from {b.start}, in {b.wt}",
             *[f"  card   #{n} {ref}" for n, ref in b.cards.items()],
             f"  walk   detached worktree {b.walk_wt} at each round's head",
             f"  fix    {b.tag}/fix-{b.name}-<card>-r<round>, cut from the batch head, one per card with findings",
             f"  pr     {b.branch} into {project['base']}", "", "Commands:",
             "  $ git fetch origin",
             "  $ " + shlex.join(["git", "worktree", "add", "--no-track", "-b", b.branch, str(b.wt), b.start]),
             *["  $ " + shlex.join(["git", "merge", "--no-ff", "--no-edit", ref]) for ref in b.cards.values()],
             f"  a conflict only in {generated}: take the card's side, then $ {project.get('regen', '')}"]
    if project.get("install"):
        lines.append(f"  in each new worktree: $ {project['install']}")
    lines += [f"  checks, in the background: $ {project['checks']}",
              f"    or $ {project.get('web_checks')} when a round changes no {backend} file after a passing full run",
              "  reviewer: $ " + shlex.join(claude_cmd(b.config, "reviewer", "<reviewer prompt>"))]
    if settings.get("walk"):
        lines.append("  walker, when a round touches " + ", ".join(settings.get("walk_paths") or ["any file"]) + ": $ "
                     + shlex.join(claude_cmd(b.config, "walker", "<walker prompt>", [b.reports])))
    lines += ["  fixers, in parallel: $ " + shlex.join(claude_cmd(b.config, "fixer", "<fixer prompt>", [b.reports])),
              f"  rounds: at most {settings.get('max_rounds', 5)}; done at checks pass, open: 0, walk pass or skipped",
              "  done: $ " + shlex.join(push_cmd(b)),
              "        $ " + shlex.join(pr_cmd(b, b.reports / "pr.md")), "", "Prompts for round 1:", "",
              "--- reviewer", reviewer_prompt(b, 1, head, None).rstrip(), ""]
    if settings.get("walk"):
        lines += ["--- walker", walker_prompt(b, 1, head).rstrip(), ""]
    example = [Finding("<path>", 1, "<each finding routed to this card>")]
    lines += [f"--- fixer, for card #{next(iter(b.cards))}", fixer_prompt(b, 1, example, fix_path, fix_branch).rstrip()]
    return "\n".join(lines)


def run_batch(config: dict, args) -> int:
    """Run `colony batch`: assemble the cards, then gate and fix round by round until the PR opens or a stop rule fires."""
    b = Batch.from_args(config, args)
    if b.dry:
        print(plan(b))
        return 0
    if b.wt.exists() or _git(b.root, "branch", "--list", b.branch):
        print(f"colony batch {b.name}: {b.branch} or {b.wt} already exists; pick another --name")
        return 1
    rounds = int(b.config["gate"].get("max_rounds", 5))
    try:
        assemble(b)
        for r in range(1, rounds + 1):
            findings = gate(b, r)
            if not findings:
                print(f"colony batch {b.name}: done in round {r}. {open_pr(b)}")
                return 0
            if r == rounds:
                raise Stop(f"round {r} of {rounds} still has {len(findings)} findings")
            fix_round(b, r, findings)
    except (Stop, OSError) as stop:
        try:
            commit_reports(b, f"stopped: {stop}")
        except Stop as also:
            print(f"colony batch {b.name}: the reports could not be committed: {also}")
        print(f"colony batch {b.name} stopped: {stop}\nReports: {b.reports}")
        return 1
    return 1


def _find_reports(config: dict, name: str | None, args=None) -> Path | None:
    """Find a batch's reports folder, in its worktree or the repository; without a name, the newest one."""
    tag, worktrees = config["project"]["name"], Path(config["project"]["worktrees"]).expanduser()
    root = _root(config, args)
    if name:
        candidates = [worktrees / f"{tag}-batch-{name}" / REPORTS / name, root / REPORTS / name]
    else:
        candidates = sorted([*worktrees.glob(f"{tag}-batch-*/{REPORTS}/*"), *(root / REPORTS).glob("*")],
                            key=lambda p: p.stat().st_mtime, reverse=True)
    return next((p for p in candidates if p.is_dir()), None)


def _latest(folder: Path, prefix: str) -> tuple[int, str]:
    """Return the highest round number and text among a folder's `<prefix>-<r>.md` files, or (0, "")."""
    found = [(int(m[1]), p) for p in folder.glob(f"{prefix}-*.md") if (m := re.fullmatch(rf"{prefix}-(\d+)\.md", p.name))]
    if not found:
        return 0, ""
    r, path = max(found)
    return r, path.read_text()


def batch_status(config: dict, args) -> int:
    """Run `colony status`: print the batch's round, last open count and walk, the steps running now, and the minutes so far."""
    folder = _find_reports(config, getattr(args, "name", None), args)
    if folder is None:
        print("colony status: no batch reports found")
        return 1
    state = json.loads((folder / "state.json").read_text()) if (folder / "state.json").exists() else {}
    review_round, review = _latest(folder, "review")
    walk_round_, walk = _latest(folder, "walk")
    open_count = parse_open(review)
    print(f"batch {folder.name}: round {max(state.get('round', 0), review_round)}, "
          f"open {'none yet' if open_count is None else f'{open_count} (round {review_round})'}, "
          f"walk {f'{parse_walk(walk)} (round {walk_round_})' if walk else 'none yet'}")
    running = state.get("running", {})
    print("running: " + (", ".join(f"{step} since {clock}" for step, clock in running.items()) or "nothing"))
    if state.get("result"):
        print(f"result: {state['result']}")
    minutes = folder / "minutes.md"
    print(minutes_table(minutes.read_text()) if minutes.exists() else "no minutes yet")
    return 0
