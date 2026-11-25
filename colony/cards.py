"""Card housekeeping: what a card plans to touch, what it waits for, the lead's queue, the files a branch changed, and
the cards a merged pull request finished.

- A card's body names its folders on a `Folders:` line and, when the lead knows them, its files on a `Files:` line
  (planned_paths). `colony card new` warns about each open card that plans to touch the same paths (overlaps), and
  `colony card overlaps` lists every such pair among the open cards.
- A `Waits for: #12, #13` line holds a card until those cards land (waits_for). `colony card new --waits-for 12,13`
  writes it, `colony card waits <n> 12,13` changes it later, and `colony take` refuses a card whose wait isn't over
  (refuse_waiting). A card lands when its issue closes as completed, its Status is Done, or a merged pull request
  finishes it, on whatever branch it merged into (Landing).
- The lead's queue is its To do cards that wait for nothing still open, oldest first (queue_of). `colony card next`
  prints it, and `--start` hands the first one to a free helper. Every 10 minutes the lead's wait runs the same check
  (lead_lines, through cycle.stale_lines): it starts a card whose wait is over for the helper its title names, when
  that helper is free, and tells a lead whose cards sit queued what to hand out next.
- changed_files reads a branch's changed files from its diff against the base. A helper's done line carries that
  list (done_files), and `colony card files` prints it.
- finishing maps each open card to the merged pull request that finished it, on whatever branch it merged into, which
  `colony tidy` uses to close the cards GitHub left open.

Optional settings live in `[cards]`: `auto_start` ("waits", "all" or "off") and `remind_minutes`.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from colony import board, cli, wait

# The same line cli.card_folders reads, parsed here without a look at the disk, since a check reads many cards.
FOLDERS = re.compile(r"^\W*folders?\W*:\s*(.+)$", re.I)
FILES = re.compile(r"^\W*files?\W*:\s*(.+)$", re.I)
WAITS = re.compile(r"^\W*waits?\s+(?:for|on)\W*:(.*)$", re.I)
# GitHub's closing keywords in a pull request's body, such as `Closes #12`, which batch.pr_body writes for each card.
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)\b", re.I)
CARD_BRANCH = re.compile(r"([a-z0-9][a-z0-9.-]*)/(\d+)")  # a helper's card branch, <name>/<n>
IMAGE_PREFIX = "card"  # cli.card_branch's card/<n> holds a card's images, never its work
AUTO_START = ("waits", "all", "off")
REMIND_MINUTES = 60
MERGED_READ = 200  # merged pull requests a landing check reads, newest first
LANDED, DROPPED, OPEN = "landed", "dropped", "open"
TO_DO, IN_PROGRESS = "To do", "In progress"


def settings(config: dict) -> dict:
    """The [cards] table with its defaults: auto_start, one of AUTO_START, and remind_minutes, a whole number."""
    table = config.get("cards", {}) or {}
    auto = table.get("auto_start", "waits")
    if auto not in AUTO_START:
        raise cli.ColonyError(f"[cards] auto_start is one of {', '.join(AUTO_START)}, not {auto!r}")
    remind = table.get("remind_minutes", REMIND_MINUTES)
    if isinstance(remind, bool) or not isinstance(remind, int) or remind < 1:
        raise cli.ColonyError(f"[cards] remind_minutes must be a whole number of at least 1, not {remind!r}")
    return {"auto_start": auto, "remind_minutes": remind}


# What a card plans to touch


def norm(path: str, file: bool = False) -> str:
    """A planned path as a card names it, made comparable: relative, a folder with one trailing slash, and a file as
    it is. On a `Folders:` line a name whose last part has no dot counts as a folder, as presence.folder reads one not
    made yet; on a `Files:` line (`file`) only a name given with a trailing slash does."""
    given = path.strip().strip("`'\"")
    clean = given.removeprefix("./").strip("/")
    if not clean or clean.startswith("..") or given.startswith(("/", "~")):
        return ""
    if given.endswith("/"):
        return clean + "/"
    return clean if file or "." in clean.rsplit("/", 1)[-1] else clean + "/"


def line_paths(text: str, pattern: re.Pattern, file: bool = False) -> list[str]:
    """The paths on the first line of a card's text that the pattern matches, such as its `Files:` line."""
    for line in (text or "").splitlines():
        found = pattern.match(line.strip())
        if found:
            parts = re.split(r"[,\s]+", found[1].replace("`", " "))
            return [path for path in (norm(part, file) for part in parts) if path]
    return []


def planned_paths(body: str) -> list[str]:
    """The folders and files a card's body says it touches: its `Folders:` line, then its `Files:` line."""
    return list(dict.fromkeys(line_paths(body, FOLDERS) + line_paths(body, FILES, file=True)))


def inside(path: str, planned: list[str]) -> bool:
    """Whether a changed file sits in one of a card's planned paths: in a folder, or the very file."""
    return any(path == entry or (entry.endswith("/") and path.startswith(entry)) for entry in planned)


def overlap(a: str, b: str) -> bool:
    """Whether two planned paths overlap: the same path, or a folder that holds the other."""
    return a == b or (a.endswith("/") and b.startswith(a)) or (b.endswith("/") and a.startswith(b))


def shared(mine: list[str], theirs: list[str]) -> list[tuple[str, str]]:
    """Each pair of overlapping paths, one from each list."""
    return [(a, b) for a in mine for b in theirs if overlap(a, b)]


@dataclass
class Overlap:
    """An open card whose planned paths overlap another's: its number and title, and the pairs of paths."""

    number: int
    title: str
    pairs: list[tuple[str, str]] = field(default_factory=list)

    def text(self) -> str:
        """The overlap in words, each of the other card's paths once, such as `src/auth/ (this card:
        src/auth/login.ts)`, or the path alone when both cards name it."""
        parts = []
        for theirs in dict.fromkeys(theirs for _, theirs in self.pairs):
            mine = [m for m, t in self.pairs if t == theirs]
            parts.append(theirs if theirs in mine else f"{theirs} (this card: {', '.join(mine)})")
        return "; ".join(parts)


def is_card(issue: dict) -> bool:
    """Whether an open issue is a card, and not the coordination issue or a Needs issue."""
    from colony import tidy

    return not tidy.is_tracking(issue.get("title", ""))


def overlaps(body: str, issues: list[dict], skip: int | None = None) -> list[Overlap]:
    """The open cards among `issues` (each with a body) that plan to touch what `body` plans to touch, other than card
    `skip`, and other than a card this one waits for, or one that waits for it."""
    mine, found = planned_paths(body), []
    waits = set(waits_for(body))
    for issue in issues:
        number = issue.get("number")
        if not mine or number in (None, skip) or number in waits or not is_card(issue):
            continue
        theirs = issue.get("body") or ""
        if skip is not None and skip in waits_for(theirs):
            continue
        pairs = [(a, b) for a, b in shared(mine, planned_paths(theirs))]
        if pairs:
            found.append(Overlap(number, issue.get("title", ""), pairs))
    return found


def overlap_lines(number: int | None, found: list[Overlap]) -> list[str]:
    """What `colony card new` prints for a new card's overlaps: one line per open card, and what to do about it."""
    if not found:
        return []
    lines = [f"overlap: #{o.number} {o.title} plans to touch {o.text()} too" for o in found]
    first = found[0].number
    wait_cmd = f"`{cli.NAME} card waits {number} {first}`" if number is not None else f"--waits-for {first}"
    return lines + [f"  Give overlapping cards to one helper, or make this card wait for the other: {wait_cmd}"]


# What a card waits for


def waits_for(body: str) -> list[int]:
    """The cards a card's `Waits for:` line names, such as [12, 13] for `Waits for: #12, #13`."""
    for line in (body or "").splitlines():
        found = WAITS.match(line.strip())
        if found:
            return list(dict.fromkeys(int(n) for n in re.findall(r"#?(\d+)", found[1])))
    return []


def with_waits(body: str, numbers: list[int]) -> str:
    """A card's body with its `Waits for:` line set to these cards, added at the end when it has none, and taken out
    for no cards."""
    lines = [line for line in (body or "").splitlines() if not WAITS.match(line.strip())]
    while lines and not lines[-1].strip():
        lines.pop()
    if numbers:
        lines.append("Waits for: " + ", ".join(f"#{n}" for n in numbers))
    return "\n".join(lines)


def merged_pulls(repo: str, limit: int = MERGED_READ) -> list[dict]:
    """The repo's newest merged pull requests, each with its number, body, base and head branch, and merge time."""
    listed = json.loads(wait.gh("pr", "list", "--repo", repo, "--state", "merged", "--limit", str(limit), "--json",
                                "number,body,baseRefName,headRefName,mergedAt,url") or "[]")
    return [pull for pull in listed if isinstance(pull, dict)] if isinstance(listed, list) else []


def finishing(pulls: list[dict], helpers: dict[int, str] | None = None) -> dict[int, dict]:
    """Each card a merged pull request finishes, mapped to that pull request: one whose body says `Closes #<n>` (or
    fixes or resolves), on whatever branch it merged into, or one whose head is the card's own branch, `<helper>/<n>`,
    when `helpers` names that card's helper. A pull request still open or closed unmerged finishes nothing."""
    found: dict[int, dict] = {}
    for pull in pulls:
        if str(pull.get("state", "MERGED")).upper() != "MERGED" and not pull.get("mergedAt"):
            continue
        numbers = [int(n) for n in CLOSING.findall(pull.get("body") or "")]
        branch = CARD_BRANCH.fullmatch(str(pull.get("headRefName", "")))
        if branch and branch[1] != IMAGE_PREFIX and helpers and helpers.get(int(branch[2])) == branch[1]:
            numbers.append(int(branch[2]))
        for number in numbers:
            found.setdefault(number, pull)
    return found


def title_helper(title: str) -> str:
    """The helper a card's title names, `builder-2` for `builder-2: the login form`, or ""."""
    head, sep, _ = (title or "").partition(":")
    name = head.strip().lower()
    return name if sep and cli.SESSION_NAME.fullmatch(name) and name != cli.LEAD else ""


class Landing:
    """Whether cards have landed, read once per check: from the board's items, else each issue's state, and from the
    merged pull requests, read only when a card is still open."""

    def __init__(self, config: dict, items: list[dict]):
        self.repo = config["project"]["repo"]
        self.items = {item["number"]: item for item in items if item.get("number") is not None}
        self.issues: dict[int, dict] = {}
        self.pulls: dict[int, dict] | None = None

    def issue(self, number: int) -> dict:
        """A card's state and why it closed, from the board, else from one `gh issue view`."""
        if number in self.items:
            return self.items[number]
        if number not in self.issues:
            try:
                self.issues[number] = json.loads(wait.gh("issue", "view", str(number), "--repo", self.repo, "--json",
                                                         "state,stateReason,title") or "{}")
            except (cli.ColonyError, ValueError):
                self.issues[number] = {}
        return self.issues[number]

    def merged(self) -> dict[int, dict]:
        """Each card a merged pull request finished, read once. A card's helper, which its own branch is named after,
        comes from the board, else from the title of the issue `issue` read."""
        if self.pulls is None:
            try:
                helpers = {n: title_helper(issue.get("title", "")) for n, issue in self.issues.items()}
                helpers.update({n: title_helper(item.get("title", "")) or board.field_value(item, "Helper").lower()
                                for n, item in self.items.items() if item.get("fields") is not None})
                self.pulls = finishing(merged_pulls(self.repo), helpers)
            except (cli.ColonyError, ValueError):
                self.pulls = {}
        return self.pulls

    def state(self, number: int) -> str:
        """LANDED, DROPPED (closed as not planned) or OPEN."""
        issue = self.issue(number)
        if str(issue.get("state", "")).upper() == "CLOSED":
            return DROPPED if str(issue.get("stateReason") or "").upper() == "NOT_PLANNED" else LANDED
        if issue.get("fields") is not None and board.squash(board.field_value(issue, "Status")) == board.squash(
                board.DONE):
            return LANDED
        return LANDED if number in self.merged() else OPEN

    def why(self, number: int) -> str:
        """How a landed card landed, for a line: the pull request and branch, when one finished it."""
        pull = (self.pulls or {}).get(number)
        return f"#{number} (#{pull['number']} into {pull.get('baseRefName', '?')})" if pull else f"#{number}"


def refs(numbers: list[int]) -> str:
    """Card numbers in words, such as `#12 and #13`."""
    texts = [f"#{n}" for n in numbers]
    return texts[0] if len(texts) == 1 else ", ".join(texts[:-1]) + f" and {texts[-1]}"


def refuse_waiting(config: dict, number: int, body: str) -> None:
    """Refuse to take card `number` while a card its `Waits for:` line names hasn't landed, for `colony take`."""
    deps = waits_for(body)
    if not deps:
        return
    view = Landing(config, [])
    still = [dep for dep in deps if view.state(dep) != LANDED]
    if still:
        raise cli.ColonyError(f"card #{number} waits for {refs(still)}, which {'has' if len(still) == 1 else 'have'} "
                              f"not landed: your lead starts it once {'it lands' if len(still) == 1 else 'they land'}, "
                              f"or clears the wait with `{cli.NAME} card waits {number} \"\"`")


# The lead's queue


def this_lead(config: dict) -> str:
    """This session's lead name, as the board's Lead field holds it, or "" when it can't be told."""
    try:
        return wait.lead_name(config, None).lower()
    except cli.ColonyError:
        return ""


def number_of(item: dict) -> int:
    """A board item's card number, 0 for an item with none."""
    return int(item.get("number") or 0)


def status_is(item: dict, status: str) -> bool:
    """Whether a board item's Status is this one."""
    return board.squash(board.field_value(item, "Status")) == board.squash(status)


def busy_helpers(items: list[dict]) -> set[str]:
    """The helpers named on an open card In progress, lowercased."""
    return {board.field_value(item, "Helper").lower() for item in items
            if board.is_open_card(item) and status_is(item, IN_PROGRESS) and board.field_value(item, "Helper")}


def live_helpers(config: dict, lead: str) -> list[str]:
    """The live helpers of this lead, by their status comments (presence.everyone); [] when none posts a status, as
    a lead from before lead names has none."""
    from colony import presence

    alive, _, _ = presence.everyone(config)
    return sorted({status.name.lower() for status in alive if status.kind == "helper" and status.lead.lower() == lead})


@dataclass
class Queue:
    """A lead's To do cards: the ready ones, oldest first, each with the cards it waited for, and the ones that still
    wait, each with the cards it waits on and the ones that closed without landing."""

    ready: list[tuple[dict, list[int]]] = field(default_factory=list)
    waiting: list[tuple[dict, list[int], list[int]]] = field(default_factory=list)
    view: Landing | None = None


def queue_of(config: dict, items: list[dict], lead: str) -> Queue:
    """The lead's queue: its open To do cards on the board, split into the ready and the waiting."""
    queue = Queue(view=Landing(config, items))
    todo = sorted((item for item in items if board.is_open_card(item) and item.get("number")
                   and board.field_value(item, "Lead").lower() == lead and status_is(item, TO_DO)), key=number_of)
    for item in todo:
        deps = waits_for(item.get("body") or "")
        states = {dep: queue.view.state(dep) for dep in deps}
        still = [dep for dep, state in states.items() if state == OPEN]
        dropped = [dep for dep, state in states.items() if state == DROPPED]
        if still or dropped:
            queue.waiting.append((item, still, dropped))
        else:
            queue.ready.append((item, deps))
    return queue


def start_card(config: dict, number: int, helper: str, title: str = "") -> str:
    """Hand card `number` to `helper`: when the title names another helper, retitle it for this one first, so its
    stats find the start line, then post `start: this card` through `colony post`, and set Status In progress and
    Helper on the board. Return what the post printed."""
    from colony import tidy

    named = title_helper(title)
    if title and named and named != helper:
        wait.gh("issue", "edit", str(number), "--repo", config["project"]["repo"], "--title",
                f"{helper}: {tidy.card_title(title)}")
    args = argparse.Namespace(card=number, to=helper, sentence="start: this card", urgent=False, person=None,
                              attach=None, nudge=False, allow_unknown=False, public=False, private=False)
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        wait.post(config, args)
    board.set_fields(config, number, [("Status", IN_PROGRESS), ("Helper", helper)])
    return printed.getvalue().strip()


def queue_path(config: dict, lead: str) -> Path:
    """Where the lead's wait remembers the cards it started and the queue lines it gave, on this computer."""
    return wait.state_path(config["project"]["name"], f"{lead}-queue")


def lead_lines(config: dict, items: list[dict], now: datetime) -> list[str]:
    """The lead's wait's queue check, every STALE_CHECK_MINUTES with the stale-card check: for this lead's To do
    cards, start each card whose wait just ended for the helper its title names, when that helper is live and free
    (with [cards] auto_start "all", any ready card so); say once when a card waits for one that closed without
    landing; and when ready cards sit queued while a helper of this lead is free, or none of its cards is in
    progress, give one `queued:` line naming the next, again only when that changes or after remind_minutes."""
    if wait.hack(config):
        return []
    lead = this_lead(config)
    if not lead:
        return []
    queue = queue_of(config, items, lead)
    if not queue.ready and not queue.waiting:
        return []
    options = settings(config)
    path = queue_path(config, lead)
    state = wait.read_json(path, {})
    state = state if isinstance(state, dict) else {}
    started, told = state.setdefault("started", {}), state.setdefault("told", {})
    lines = []
    for item, still, dropped in queue.waiting:
        key = f"dropped:{item['number']}:{','.join(map(str, dropped))}"
        if dropped and key not in told:
            told[key] = now.isoformat()
            lines.append(f"#{item['number']} waits for {refs(dropped)}, which closed without landing: change its "
                         f"wait with `{cli.NAME} card waits {item['number']} <cards>`, or close it")
    mine_running = any(board.is_open_card(item) and status_is(item, IN_PROGRESS)
                       and board.field_value(item, "Lead").lower() == lead for item in items)
    busy = busy_helpers(items)
    helpers = live_helpers(config, lead) if queue.ready else []
    free = [name for name in helpers if name not in busy]
    queued = []
    for item, deps in queue.ready:
        number, named = item["number"], title_helper(item.get("title", ""))
        wanted = options["auto_start"] == "all" or (options["auto_start"] == "waits" and deps)
        if wanted and named in free and str(number) not in started:
            try:
                start_card(config, number, named, item.get("title", ""))
            except (cli.ColonyError, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
                lines.append(f"#{number} is ready, but starting it for {named} failed: {e}")
                queued.append(item)
                continue
            started[str(number)] = now.isoformat()
            free.remove(named)
            since = f"{', '.join(queue.view.why(dep) for dep in deps)} landed" if deps else "it was next in your queue"
            lines.append(f"#{number} started: {named} has it now, since {since}")
            continue
        queued.append(item)
    if queued and (free or not mine_running):
        key = ",".join(str(item["number"]) for item in queued) + "|" + ",".join(free)
        last = told.get("queue") if isinstance(told.get("queue"), dict) else {}
        due = last.get("key") != key or now - datetime.fromisoformat(last.get("at", now.isoformat())) >= timedelta(
            minutes=options["remind_minutes"])
        if due:
            told["queue"] = {"key": key, "at": now.isoformat()}
            first = queued[0]
            more = f", and {len(queued) - 1} more of your cards," if len(queued) > 1 else ""
            who = (f"{', '.join(free)} {'is' if len(free) == 1 else 'are'} free" if free
                   else "none of your cards is in progress")
            lines.append(f"queued: #{first['number']} {first.get('title', '')}{more} is ready while {who}: hand it "
                         f"out now with `{cli.NAME} card next --start`")
    keep = now - timedelta(days=7)
    state["started"] = {n: at for n, at in started.items() if datetime.fromisoformat(at) >= keep}
    state["told"] = {k: v for k, v in told.items() if k == "queue" or datetime.fromisoformat(v) >= keep}
    wait.write_json(path, state)
    return lines


# The files a branch changed


def _git(cwd, *args: str) -> str:
    """One git command's output in cwd; raise ColonyError when it fails."""
    run = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=cwd, capture_output=True, text=True)
    if run.returncode:
        raise cli.ColonyError(run.stderr.strip() or f"git {' '.join(args[:2])} failed")
    return run.stdout


def changed_files(cwd, base: str, head: str = "HEAD") -> list[tuple[str, str]]:
    """Each file `head` changed since it left `base`, as (status, path): A, M, D, R with `old -> new`, from the diff
    of their merge base with `head`, the same diff the batch merges."""
    merge_base = _git(cwd, "merge-base", base, head).strip()
    found = []
    for line in _git(cwd, "diff", "--name-status", "-M", "--no-color", merge_base, head).splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            status = parts[0][:1]
            found.append((status, f"{parts[1]} -> {parts[2]}" if status in "RC" and len(parts) > 2 else parts[1]))
    return found


def uncommitted(cwd) -> list[str]:
    """The files changed in the worktree and not committed, untracked ones too."""
    return [line[3:].strip() for line in _git(cwd, "status", "--porcelain").splitlines() if line.strip()]


def unpushed(cwd, branch: str) -> str:
    """Why HEAD isn't on origin as pushed, or "" when origin/<branch> holds it."""
    remote = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"origin/{branch}"], cwd=cwd,
                            capture_output=True, text=True)
    if remote.returncode:
        return f"origin/{branch} doesn't exist: push the branch"
    ahead = _git(cwd, "rev-list", "--count", f"origin/{branch}..HEAD").strip()
    return f"HEAD is {ahead} commit{'s' if ahead != '1' else ''} ahead of origin/{branch}: push it" \
        if ahead not in ("", "0") else ""


def same_repo(config: dict, cwd) -> bool:
    """Whether cwd is a clone of the repo colony.toml names, by its origin's address."""
    run = subprocess.run(["git", "remote", "get-url", "origin"], cwd=cwd, capture_output=True, text=True)
    url = run.stdout.strip().lower().removesuffix(".git") if not run.returncode else ""
    repo = config["project"]["repo"].lower()
    return bool(url) and (url.endswith(f"/{repo}") or url.endswith(f":{repo}"))


def files_report(config: dict, cwd, base: str | None = None, head: str = "HEAD",
                 body: str | None = None) -> tuple[int, str, str]:
    """A branch's changed files from its diff, as (count, label, text): the files, then what is uncommitted, what is
    not pushed, and the changed files outside the card's planned paths when its body is given."""
    base = base or f"origin/{config['project']['base']}"
    _git(cwd, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    branch = _git(cwd, "rev-parse", "--abbrev-ref", head).strip() if head == "HEAD" else head.removeprefix("origin/")
    files = changed_files(cwd, base, head)
    lines = [f"{status} {path}" for status, path in files] or ["(none)"]
    if head == "HEAD":
        if left := uncommitted(cwd):
            lines += ["", "Not committed, so not on the branch: " + ", ".join(left)]
        if branch and branch != "HEAD" and (note := unpushed(cwd, branch)):
            lines += ["", f"Not pushed: {note}"]
    planned = planned_paths(body or "")
    if planned:
        outside = [path for _, entry in files for path in [entry.split(" -> ")[-1]] if not inside(path, planned)]
        if outside:
            lines += ["", f"Outside the card's planned paths ({', '.join(planned)}): " + ", ".join(outside)]
    label = f"changed files: {len(files)}, from git diff {base}...{branch or head}"
    return len(files), label, "\n".join(lines)


def card_head(cwd, helper: str, card: int) -> str:
    """The branch a helper's done line reads its changed files from: HEAD when it is the card's branch,
    `<helper>/<card>`; else origin/<helper>/<card> when that exists, as when the helper posts from another folder; else
    HEAD."""
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD").strip()
    own = f"{helper}/{card}"
    if not helper or branch == own:
        return "HEAD"
    remote = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"origin/{own}^{{commit}}"], cwd=cwd,
                            capture_output=True, text=True)
    return "HEAD" if remote.returncode else f"origin/{own}"


def done_files(config: dict, card: int, text: str, cwd=None) -> str:
    """A helper's done comment with its branch's changed files attached, read from its diff against the base, so the
    lead never relies on a list the helper typed. The branch is the folder's HEAD, or the pushed card branch when the
    helper posts from another folder (card_head). Outside a clone of the repo, or when git can't tell, the comment
    goes as it is, and stderr says why."""
    from colony import transport

    cwd = cwd or Path.cwd()
    try:
        if not same_repo(config, cwd):
            return text
        try:
            card_body = json.loads(wait.gh("issue", "view", str(card), "--repo", config["project"]["repo"], "--json",
                                           "body") or "{}").get("body") or ""
        except (cli.ColonyError, ValueError, AttributeError):
            card_body = ""
        head = card_head(cwd, os.environ.get(cli.SESSION_ENV, "").lower(), card)
        _, label, listing = files_report(config, cwd, head=head, body=card_body)
    except (cli.ColonyError, OSError, subprocess.SubprocessError) as e:
        print(f"{cli.NAME} post: the done line goes without its changed files: {e}", file=sys.stderr)
        return text
    return f"{text}\n\n{transport.attachment(label, listing)}"


# Commands


def need_cards(config: dict) -> None:
    """Refuse a card command in hack mode, which has no cards."""
    if wait.hack(config):
        raise cli.ColonyError("hack mode has no cards: hand a task out with a `start:` line on the board")


def open_cards(config: dict) -> list[dict]:
    """The repo's open cards, each with its number, title and body."""
    listed = json.loads(wait.gh("issue", "list", "--repo", config["project"]["repo"], "--state", "open", "--json",
                                "number,title,body", "--limit", "1000") or "[]")
    return [issue for issue in listed if isinstance(issue, dict) and is_card(issue)]


def overlaps_command(config: dict, args) -> int:
    """`colony card overlaps`: every pair of open cards that plan to touch the same paths."""
    need_cards(config)
    cards = open_cards(config)
    pairs = 0
    for i, card in enumerate(cards):
        for found in overlaps(card.get("body") or "", cards[i + 1:], skip=card["number"]):
            pairs += 1
            print(f"#{card['number']} {card.get('title', '')} and #{found.number} {found.title}: {found.text()}")
    if not pairs:
        print("no two open cards plan to touch the same paths")
        return 0
    print(f"{pairs} overlapping pair{'s' if pairs != 1 else ''}: give each pair to one helper, or make one card wait "
          f"for the other with `{cli.NAME} card waits <n> <other>`")
    return 0


def waits_command(config: dict, args) -> int:
    """`colony card waits <n> <cards>`: set the cards card n waits for, or clear its wait with ""."""
    need_cards(config)
    repo = config["project"]["repo"]
    numbers = wait.card_numbers(args.cards)
    if args.card in numbers:
        raise cli.ColonyError(f"card #{args.card} can't wait for itself")
    found = json.loads(wait.gh("issue", "view", str(args.card), "--repo", repo, "--json", "body") or "{}")
    body = with_waits(found.get("body") or "", numbers)
    wait.gh("issue", "edit", str(args.card), "--repo", repo, "--body", body)
    print(f"#{args.card} waits for {refs(numbers)}" if numbers else f"#{args.card} waits for nothing now")
    return 0


def next_command(config: dict, args) -> int:
    """`colony card next [--start] [--helper <name>]`: the lead's queue, its ready To do cards oldest first and the
    ones that still wait; --start hands the first ready one to a free helper."""
    need_cards(config)
    lead = (args.lead or wait.lead_name(config, args)).lower()
    items = board.items(board.need_board(config))
    queue = queue_of(config, items, lead)
    if not args.start:
        for item, deps in queue.ready:
            since = f", since {', '.join(queue.view.why(dep) for dep in deps)} landed" if deps else ""
            print(f"ready: #{item['number']} {item.get('title', '')}{since}")
        for item, still, dropped in queue.waiting:
            gone = f"; {refs(dropped)} closed without landing" if dropped else ""
            waits = f"waits for {refs(still)}" if still else "waits"
            print(f"waiting: #{item['number']} {item.get('title', '')}: {waits}{gone}")
        if not queue.ready and not queue.waiting:
            print(f"{lead} has no To do card")
        return 0
    if not queue.ready:
        print(f"nothing of {lead}'s is ready to start" + (f": {len(queue.waiting)} card"
                                                          f"{'s' if len(queue.waiting) != 1 else ''} still wait"
                                                          if queue.waiting else ""))
        return 0
    item, _ = queue.ready[0]
    busy, helpers = busy_helpers(items), live_helpers(config, lead)
    named = title_helper(item.get("title", ""))
    helper = (args.helper or "").lower()
    if not helper:
        if named and named not in busy and (not helpers or named in helpers):
            helper = named
        else:
            helper = next((name for name in helpers if name not in busy), "")
    if not helper:
        raise cli.ColonyError(f"#{item['number']} is next, and no helper of yours is free: open one with "
                              f"`{cli.NAME} helpers 1 --open`, or name one with --helper")
    printed = start_card(config, item["number"], helper, item.get("title", ""))
    if printed:
        print(printed)
    print(f"#{item['number']} started for {helper}" + (f", in place of {named}" if named and named != helper else ""))
    return 0


def files_command(config: dict, args) -> int:
    """`colony card files [<n>] [--branch B] [--base B]`: a branch's changed files from its diff against the base,
    HEAD's by default, and with a card, the ones outside its planned paths."""
    body = None
    if args.card is not None:
        found = json.loads(wait.gh("issue", "view", str(args.card), "--repo", config["project"]["repo"], "--json",
                                   "body") or "{}")
        body = found.get("body") or ""
    _, label, listing = files_report(config, Path.cwd(), base=args.base, head=args.branch or "HEAD", body=body)
    print(label)
    print(listing)
    return 0


def add_card_commands(card_sub) -> None:
    """tidy.add_commands' route to this module: `colony card overlaps`, `waits`, `next` and `files`."""
    q = card_sub.add_parser("overlaps", help="list every pair of open cards that plan to touch the same folders or "
                                             "files")
    q.set_defaults(run=overlaps_command)
    q = card_sub.add_parser("waits", help="set the cards a card waits for; it starts when they land")
    q.add_argument("card", type=board.card_number, help="the card's issue number")
    q.add_argument("cards", help="the cards it waits for, such as 12,13; \"\" clears its wait")
    q.set_defaults(run=waits_command)
    q = card_sub.add_parser("next", help="the lead: your queue of ready To do cards; --start hands the next to a "
                                         "free helper")
    q.add_argument("--start", action="store_true", help="hand the first ready card to a free helper: the one its "
                                                        "title names, else the first free one")
    q.add_argument("--helper", help="the helper to hand it to, instead")
    q.add_argument("--lead", help="whose queue, by the lead's name; yours by default")
    q.add_argument("--person", help="whose lead you are, when colony.toml names several people")
    q.set_defaults(run=next_command)
    q = card_sub.add_parser("files", help="a branch's changed files from its diff against the base, and with a card, "
                                          "the ones outside its planned paths")
    q.add_argument("card", nargs="?", type=board.card_number, help="the card, whose planned paths it checks")
    q.add_argument("--branch", help="the branch to read, such as origin/builder-2/41; HEAD by default")
    q.add_argument("--base", help="the base to compare with, origin/<base> by default")
    q.set_defaults(run=files_command)
