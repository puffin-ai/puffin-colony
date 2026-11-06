"""The anti-bloat limits, and `colony tidy`, which keeps the cards, the long issues, the board and the worktrees small.

- `colony idea "<one line>"` appends a dated line to the future-work register: `<vault>/future-work.md`, or
  `.colony/future-work.md` where there is no vault (hack and solo). An idea is never an issue.
- `colony card new "<title>" --body … --size S|M|L [--lead <name>]` makes a card, which is an issue only when its work
  starts this week. It refuses when the lead already has `[limits] open_cards_per_lead` open cards, counted by the
  board's Lead field, and when an open issue's title says the same thing. It puts the card on the board as To do.
- `check_kind` is the rule for a card line: a helper sends its lead only done, question, blocked and urgent lines, and
  a lead sends its helpers start, answer and urgent lines. Lead-to-lead lines are free text. `colony post` applies it.
- The coordination issue and each Needs issue rotate at `[limits] issue_comments` comments (`rotate`): the old one
  gets a closing comment with the open items from its last 50 comments and closes, and a fresh one with the same title
  links back to it. `keep_short` makes the same check from the comment count before a post.
- `colony tidy [--dry-run]` closes a card with no update in `[limits] stale_days`, or moves it to future-work when its
  work never started; rotates the long issues; archives Done items after `[limits] archive_days`; turns on the repo's
  `delete_branch_on_merge`; and removes each closed card's clean worktree, keeping a dirty one. It prints the counts
  before and after. `colony batch` runs it at its end.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from colony import board, cli, wait

LIMITS = {"open_cards_per_lead": 10, "stale_days": 7, "issue_comments": 200, "archive_days": 7}
SUMMARY_COMMENTS = 50  # a rotation's closing comment lists the open items among the old issue's last 50 comments
NEAR = 0.75  # two titles whose meaningful words overlap this much name the same card
STOP_WORDS = {"a", "an", "the", "to", "of", "and", "or", "for", "in", "on", "with", "is", "it", "at", "by"}
HELPER_KINDS = ("done", "question", "blocked", "urgent")
LEAD_KINDS = ("start", "answer", "urgent")
KIND = re.compile(r"([a-z]+)\s*[:,]", re.I)
OPEN_ITEM = re.compile(r"(question|blocked|urgent)\s*:", re.I)
DECIDES = re.compile(r"\bdecides:\s*(.+?)\s+Default:", re.I)
CARD_BRANCH = re.compile(r"[a-z0-9][a-z0-9.-]*/(\d+)")  # a card's branch, <name>/<n>
NEEDS = re.compile(r"Needs \S+")
IDEAS = "## Ideas"


def limits(config: dict) -> dict[str, int]:
    """The [limits] table over LIMITS, each a whole number."""
    table = config.get("limits", {}) or {}
    found = {}
    for key, default in LIMITS.items():
        value = table.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise cli.ColonyError(f"[limits] {key} must be a whole number of at least 1, not {value!r}")
        found[key] = value
    return found


def issue_number(url: str) -> int:
    """The number at the end of an issue's address, as `gh issue create` prints it."""
    return int(url.strip().rstrip("/").rsplit("/", 1)[-1])


def card_title(title: str) -> str:
    """A card's title without its `<helper>:` start, such as `login form` for `builder-2: login form`."""
    head, sep, rest = title.partition(":")
    return rest.strip() if sep and cli.SESSION_NAME.fullmatch(head.strip().lower()) else title.strip()


# Lines


def check_kind(from_lead: bool, to: str, sentence: str) -> None:
    """Refuse a card line of a kind its sender may not send. A helper's line to its lead starts done, question:,
    blocked: or urgent:, and a lead's line to a helper starts start:, answer: or urgent:. A lead's line for another
    lead, `<person>-lead`, `@<login>` or `@all`, is free text. Progress goes in the board's fields, never in a line."""
    if from_lead and (to.startswith("@") or to.endswith(f"-{cli.LEAD}")):
        return
    found = KIND.match(sentence)
    kind = found[1].lower() if found else ""
    allowed = LEAD_KINDS if from_lead else HELPER_KINDS
    if kind in allowed:
        return
    who = "a lead's line to its helper" if from_lead else "a helper's line to its lead"
    kinds = ", ".join(f"`{k}:`" for k in allowed)
    progress = "" if from_lead else f"; progress goes on the board, with `{cli.NAME} board set <n> ...`"
    raise cli.ColonyError(f"{who} starts with {kinds}, and this one starts {sentence.split(' ', 1)[0]!r}{progress}")


# Ideas


def future_work_path(config: dict, root: Path) -> Path:
    """The future-work register: `<vault>/future-work.md` with the knowledge vault on, else `.colony/future-work.md`."""
    if config.get("features", {}).get("knowledge"):
        vault = str(config.get("knowledge", {}).get("vault", "knowledge")).strip().rstrip("/")
        return root / vault / "future-work.md"
    return root / cli.DIR / "future-work.md"


def add_idea(path: Path, text: str, today: str) -> str:
    """Add `- <today>: <text>` at the end of the register's Ideas section, making the file or the section when it is
    missing, and return the line."""
    text = " ".join(text.split())
    line = f"- {today}: {text}"
    if not text or len(line) >= wait.MAX_LINE:
        raise cli.ColonyError(f"an idea is one line under {wait.MAX_LINE} characters, and this one has {len(line)}")
    page = path.read_text() if path.exists() else ("# Future work\n\nIdeas and deferred work, one dated line each. None "
                                                    "of them is a card: a card is an issue only when its work starts "
                                                    "this week.\n")
    start = page.find(f"\n{IDEAS}\n")
    if start == -1:
        page = page.rstrip("\n") + f"\n\n{IDEAS}\n\n{line}\n"
    else:
        end = page.find("\n## ", start + 1)
        end = len(page) if end == -1 else end
        section = page[:end].rstrip("\n")
        page = f"{section}\n{line}\n" + (f"\n{page[end:].lstrip(chr(10))}" if end < len(page) else "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page)
    return line


def idea(config: dict, args) -> int:
    """`colony idea "<one line>"`: write an idea to the future-work register, never as an issue."""
    path = future_work_path(config, cli.repo_root())
    line = add_idea(path, args.text, board.utcnow().strftime("%Y-%m-%d"))
    print(f"{path}: {line}")
    print("Commit it with your next change.")
    return 0


# Cards


def title_words(title: str) -> list[str]:
    """A title's words, lowercase and without punctuation, after its `<helper>:` start."""
    return re.findall(r"[a-z0-9]+", card_title(title).lower())


def duplicate(title: str, issues: list[dict]) -> dict | None:
    """The open issue whose title names the same card: the same words, ignoring case and punctuation, or meaningful
    words that overlap by NEAR or more."""
    mine = title_words(title)
    words = set(mine) - STOP_WORDS
    for issue in issues:
        theirs = title_words(issue.get("title", ""))
        if theirs == mine:
            return issue
        other = set(theirs) - STOP_WORDS
        if words and other and len(words & other) / len(words | other) >= NEAR:
            return issue
    return None


def open_issues(repo: str) -> list[dict]:
    """The repo's open issues, each as {number, title}."""
    return json.loads(wait.gh("issue", "list", "--repo", repo, "--state", "open", "--json", "number,title", "--limit",
                              "1000") or "[]")


def is_tracking(title: str) -> bool:
    """Whether an issue is one of Colony's own threads, the coordination issue or a Needs issue, and not a card."""
    return title == wait.COORDINATION or NEEDS.fullmatch(title) is not None


def lead_cards(items: list[dict], lead: str) -> list[dict]:
    """The board's open cards whose Lead field names `lead`."""
    return [item for item in items if board.is_open_card(item)
            and board.field_value(item, "Lead").lower() == lead.lower()]


def card_new(config: dict, args) -> int:
    """`colony card new "<title>" --body … --size S|M|L [--lead <name>]`: make a card and put it on the board as To
    do, with its Lead and Size. It refuses at the lead's open-card limit, and on a duplicate of an open issue."""
    if wait.hack(config):
        raise cli.ColonyError("hack mode has no cards: hand a task out with a `start:` line on the board")
    title, repo = " ".join(args.title.split()), config["project"]["repo"]
    lead = (args.lead or wait.lead_name(config, args)).lower()
    if not title or not args.body.strip():
        raise cli.ColonyError("a card needs a title and a --body")
    limit = limits(config)["open_cards_per_lead"]
    on_board = bool(config.get("features", {}).get("board", True))
    issues = open_issues(repo)
    found = board.need_board(config) if on_board else None
    count = len(lead_cards(board.items(found), lead)) if found else \
        len([issue for issue in issues if not is_tracking(issue.get("title", ""))])
    if count >= limit:
        raise cli.ColonyError(f"{lead} has {count} open cards, and [limits] open_cards_per_lead is {limit}: close or "
                              "finish one first")
    same = duplicate(title, issues)
    if same is not None:
        raise cli.ColonyError(f"#{same['number']} is already open as {same.get('title')!r}: add to it instead of "
                              "opening a duplicate")
    number = issue_number(wait.gh("issue", "create", "--repo", repo, "--title", title, "--body", args.body))
    if found:
        try:
            board.set_fields(config, number, [("Status", "To do"), ("Lead", lead), ("Size", args.size)])
        except cli.ColonyError as e:
            raise cli.ColonyError(f"made #{number}, but the board didn't take it: {e}") from None
    print(f"#{number} {title} (Status=To do, Lead={lead}, Size={args.size})")
    return 0


# Long issues


def issue_info(repo: str, number: int) -> dict:
    """One issue as the REST API answers it: its state, title, body and comment count, in one cheap call."""
    info = json.loads(wait.gh("api", f"repos/{repo}/issues/{number}") or "{}")
    if not isinstance(info, dict) or "comments" not in info:
        raise cli.ColonyError(f"GitHub gave no comment count for #{number}")
    return info


def open_items(comments: list[dict], needs: bool) -> list[str]:
    """The open items in a run of comments: each `question:`, `blocked:` or `urgent:` line, and on a Needs issue
    each decision posted after the person's last answer, which is a line with no `(from …)`."""
    found, decisions = [], []
    for comment in comments:
        for raw in (comment.get("body") or "").splitlines():
            line = wait.MARKUP.sub("", wait.PREFIX.sub("", wait.MARKUP.sub("", raw)))
            addressed = wait.LINE.match(line)
            sentence = addressed[2] if addressed else line
            if OPEN_ITEM.match(sentence):
                found.append(line)
            elif needs and DECIDES.search(sentence):
                decisions.append(line)
            elif needs and addressed and not wait.SIGNED.search(line):
                decisions = []  # the person answered: what came before is settled, as far as a line can tell
    return found + [f"unanswered: {line}" for line in decisions]


def continued_body(old: str, number: int, count: int) -> str:
    """A rotated issue's body: the old one's text, without its own `Continues` line, and a link to the old issue."""
    text = "\n".join(line for line in (old or "").splitlines() if not line.startswith("Continues #")).strip()
    return f"{text}\n\nContinues #{number}, closed at {count} comments." if text else f"Continues #{number}."


def rotate(config: dict, number: int, info: dict) -> int:
    """Close a full issue and open its successor with the same title; return the new number. The old issue first
    gets a closing comment with the open items from its last SUMMARY_COMMENTS comments. A new coordination issue is
    remembered at once, so this computer's posts and wait follow it."""
    repo, title, count = config["project"]["repo"], info.get("title", ""), int(info.get("comments", 0))
    comments = json.loads(wait.gh("issue", "view", str(number), "--repo", repo, "--json", "comments") or "{}")
    items = open_items((comments.get("comments") or [])[-SUMMARY_COMMENTS:], NEEDS.fullmatch(title) is not None)
    new = issue_number(wait.gh("issue", "create", "--repo", repo, "--title", title, "--body",
                               continued_body(info.get("body", ""), number, count)))
    listed = "\n".join(f"- {item[:wait.MAX_LINE]}" for item in items) or "- none found"
    wait.gh("issue", "comment", str(number), "--repo", repo, "--body",
            f"Closed at {count} comments; this thread goes on in #{new}.\n\nOpen items from its last "
            f"{SUMMARY_COMMENTS} comments:\n{listed}")
    wait.gh("issue", "close", str(number), "--repo", repo)
    if title == wait.COORDINATION:
        wait.coordination_issue(repo, config["project"]["name"], moved=new)
    return new


def keep_short(config: dict, number: int) -> int:
    """Before a post on the coordination or a Needs issue: rotate it when it holds [limits] issue_comments comments,
    and return the issue to post on. It reads one comment count, and a failure never stops the post."""
    try:
        info = issue_info(config["project"]["repo"], number)
        if info.get("state") == "open" and int(info["comments"]) >= limits(config)["issue_comments"]:
            return rotate(config, number, info)
    except (cli.ColonyError, ValueError, KeyError, TypeError) as e:
        print(f"{cli.NAME}: the comment count of #{number} was not checked: {e}", file=sys.stderr)
    return number


# Worktrees


def worktrees(root: Path) -> list[dict]:
    """The repo's worktrees from `git worktree list --porcelain`, each as {path, branch, main}. The first is the main
    checkout."""
    run = subprocess.run(["git", "-C", str(root), "worktree", "list", "--porcelain"], capture_output=True, text=True)
    if run.returncode:
        raise cli.ColonyError(f"git worktree list failed: {run.stderr.strip()[:200]}")
    found = []
    for block in run.stdout.strip().split("\n\n"):
        entry = dict(line.partition(" ")[::2] for line in block.splitlines() if line.strip())
        if "worktree" in entry:
            found.append({"path": entry["worktree"], "branch": entry.get("branch", "").removeprefix("refs/heads/"),
                          "main": not found, "locked": "locked" in entry, "bare": "bare" in entry})
    return found


def dirt(path: str) -> str:
    """What keeps a worktree: uncommitted or untracked changes, or "" when it is clean."""
    run = subprocess.run(["git", "-C", path, "status", "--porcelain"], capture_output=True, text=True)
    if run.returncode:
        return "git can't read it"
    return "uncommitted or untracked changes" if run.stdout.strip() else ""


def card_closed(repo: str, number: int, open_numbers: set[int], closing: set[int]) -> bool:
    """Whether card `number` is closed, or closes in this tidy. An issue not on the open list is asked about once."""
    if number in closing:
        return True
    if number in open_numbers:
        return False
    try:
        state = json.loads(wait.gh("issue", "view", str(number), "--repo", repo, "--json", "state") or "{}")
    except (cli.ColonyError, ValueError):
        return False
    return state.get("state") == "CLOSED"


# colony tidy


@dataclass
class Tally:
    """What tidy counts: open cards per lead, comments per long issue, and what it changed."""

    cards: dict[str, int] = field(default_factory=dict)
    comments: dict[str, int] = field(default_factory=dict)
    closed: int = 0
    moved: int = 0
    rotated: int = 0
    archived: int = 0
    removed: int = 0
    kept: list[str] = field(default_factory=list)
    setting: str = "not read"


@dataclass
class Step:
    """One change tidy makes: the line that says it, the change, and its effect on the tally."""

    says: str
    do: Callable[[], str | None]
    effect: Callable[[Tally], None]


def card_steps(config: dict, root: Path, items: list[dict], now: datetime, after: Tally) -> tuple[list[Step], set]:
    """Close each open card with no update in [limits] stale_days, or move it to future-work when it is still To do,
    with one line on the card that says why; return the steps and the cards they close."""
    repo, days = config["project"]["repo"], limits(config)["stale_days"]
    steps, closing = [], set()
    for item in items:
        touched = board.last_touched(item)
        if not board.is_open_card(item) or item.get("number") is None or touched is None:
            continue
        if now - touched < timedelta(days=days):
            continue
        number, lead = item["number"], board.field_value(item, "Lead") or "(no lead)"
        since = touched.strftime("%Y-%m-%d")
        closing.add(number)
        if board.squash(board.field_value(item, "Status")) == board.squash("To do"):
            why = f"moved to future-work: its work never started, and it shows no update since {since}"
            entry = f"{card_title(item.get('title') or f'card #{number}')} (was #{number})"

            def move(number=number, why=why, entry=entry):
                add_idea(future_work_path(config, root), entry, now.strftime("%Y-%m-%d"))
                close_card(repo, number, why)

            steps.append(Step(f"#{number}: {why}", move, lambda t, lead=lead: count_off(t, lead, "moved")))
        else:
            why = f"closed: it shows no update since {since}; reopen it when its work starts again"
            steps.append(Step(f"#{number}: {why}", lambda number=number, why=why: close_card(repo, number, why),
                              lambda t, lead=lead: count_off(t, lead, "closed")))
    return steps, closing


def close_card(repo: str, number: int, why: str) -> None:
    """Close a card as not planned, with one line that says why."""
    wait.gh("issue", "close", str(number), "--repo", repo, "--reason", "not planned", "--comment", f"tidy: {why}")


def count_off(tally: Tally, lead: str, how: str) -> None:
    """Take one card off a lead's open count, as closed or moved."""
    tally.cards[lead] = tally.cards.get(lead, 1) - 1
    setattr(tally, how, getattr(tally, how) + 1)


def archive_steps(config: dict, found: dict, items: list[dict], now: datetime) -> list[Step]:
    """Archive each item Done, or closed, for over [limits] archive_days."""
    days, steps = limits(config)["archive_days"], []
    for item in items:
        if board.is_open_card(item):
            continue
        done_at = board.last_touched(item)
        if item.get("closedAt"):
            closed = datetime.fromisoformat(item["closedAt"].replace("Z", "+00:00"))
            done_at = max(done_at, closed) if done_at else closed
        if done_at is None or now - done_at < timedelta(days=days):
            continue
        name = f"#{item['number']}" if item.get("number") else item["id"]
        steps.append(Step(f"archive {name} from the board: done since {done_at:%Y-%m-%d}",
                          lambda item=item: board.archive(config, found, item["id"]),
                          lambda t: setattr(t, "archived", t.archived + 1)))
    return steps


def rotation_steps(config: dict, issues: list[dict], before: Tally) -> list[Step]:
    """Count the comments on the coordination issue and each Needs issue, and rotate each one at its limit."""
    repo, limit, steps = config["project"]["repo"], limits(config)["issue_comments"], []
    for issue in issues:
        title = issue.get("title", "")
        if not is_tracking(title) or (title == wait.COORDINATION and wait.hack(config)):
            continue
        label = f"#{issue['number']} {title}"
        try:
            info = issue_info(repo, issue["number"])
        except (cli.ColonyError, ValueError) as e:
            print(f"  {label}: its comment count was not read, so it is left as it is: {e}")
            continue
        before.comments[label] = int(info["comments"])
        if before.comments[label] >= limit:

            def turn(number=issue["number"], info=info):
                return f"now #{rotate(config, number, info)}"

            steps.append(Step(f"rotate {label}: {before.comments[label]} comments, at the limit of {limit}", turn,
                              lambda t, label=label: (t.comments.__setitem__(label, 0),
                                                      setattr(t, "rotated", t.rotated + 1))))
    return steps


def setting_steps(config: dict, before: Tally) -> list[Step]:
    """Turn on the repo's delete_branch_on_merge when it is off, so a merged branch goes away."""
    repo = config["project"]["repo"]
    try:
        info = json.loads(wait.gh("api", f"repos/{repo}") or "{}")
    except (cli.ColonyError, ValueError) as e:
        before.setting = f"not read: {e}"
        return []
    if not isinstance(info, dict) or "delete_branch_on_merge" not in info:
        before.setting = "not read (the gh login may lack admin rights)"
        return []
    if info["delete_branch_on_merge"]:
        before.setting = "on"
        return []
    before.setting = "off"
    return [Step("turn on delete_branch_on_merge, so GitHub deletes a branch when its pull request merges",
                 lambda: wait.gh("api", "-X", "PATCH", f"repos/{repo}", "-F", "delete_branch_on_merge=true") and None,
                 lambda t: setattr(t, "setting", "turned on"))]


def worktree_steps(config: dict, root: Path, issues: list[dict], closing: set, before: Tally) -> list[Step]:
    """Remove the worktree of each closed card, `<name>/<n>`, when it is clean; keep and name a dirty one. The main
    checkout is never removed."""
    repo, steps = config["project"]["repo"], []
    open_numbers = {issue["number"] for issue in issues}
    for tree in worktrees(root):
        found = CARD_BRANCH.fullmatch(tree["branch"])
        if tree["main"] or tree["bare"] or not found or Path(tree["path"]).resolve() == root.resolve():
            continue
        number = int(found[1])
        if not card_closed(repo, number, open_numbers, closing):
            continue
        why = "locked" if tree["locked"] else dirt(tree["path"])
        if why:
            before.kept.append(f"{tree['path']} ({why})")
            continue
        steps.append(Step(f"remove the worktree {tree['path']}: card #{number} is closed, and the worktree is clean",
                          lambda path=tree["path"]: git_remove(root, path),
                          lambda t: setattr(t, "removed", t.removed + 1)))
    return steps


def git_remove(root: Path, path: str) -> None:
    """Remove one clean worktree; git itself refuses a dirty one."""
    run = subprocess.run(["git", "-C", str(root), "worktree", "remove", path], capture_output=True, text=True)
    if run.returncode:
        raise cli.ColonyError(f"git worktree remove {path}: {run.stderr.strip()[:200]}")


def plan(config: dict, root: Path, now: datetime) -> tuple[Tally, list[Step]]:
    """Read everything tidy needs, changing nothing, and return the counts before and the steps."""
    before, steps, closing = Tally(), [], set()
    steps += setting_steps(config, before)
    issues = open_issues(config["project"]["repo"])
    found = board.find_board(config) if config.get("features", {}).get("board", True) else None
    items = board.items(found) if found else []
    for item in items:
        if board.is_open_card(item):
            lead = board.field_value(item, "Lead") or "(no lead)"
            before.cards[lead] = before.cards.get(lead, 0) + 1
    if found:
        cards, closing = card_steps(config, root, items, now, before)
        steps += cards + archive_steps(config, found, items, now)
    steps += rotation_steps(config, issues, before)
    steps += worktree_steps(config, root, issues, closing, before)
    return before, steps


def report(before: Tally, after: Tally, dry: bool) -> list[str]:
    """The counts before and after, one line each."""
    leads = sorted(set(before.cards) | set(after.cards))
    lines = ["open cards per lead: " + (", ".join(f"{lead} {before.cards.get(lead, 0)} → {after.cards.get(lead, 0)}"
                                                  for lead in leads) or "none"),
             f"stale cards: {after.closed} closed, {after.moved} moved to future-work",
             "comments: " + (", ".join(f"{label} {count} → {after.comments.get(label, count)}"
                                       for label, count in before.comments.items()) or "no coordination or Needs issue"),
             f"rotations: {after.rotated}", f"board items archived: {after.archived}",
             f"worktrees: {after.removed} removed, {len(after.kept)} kept" +
             (f": {'; '.join(after.kept)}" if after.kept else ""),
             f"delete_branch_on_merge: {before.setting}" +
             (f" → {after.setting}" if after.setting != before.setting else "")]
    return [f"  {line}" for line in lines] if not dry else [f"  {line} (planned)" for line in lines]


def run_tidy(config: dict, root: Path | None = None, dry: bool = False, now: datetime | None = None) -> int:
    """Plan tidy, then make each step, or with `dry` print the plan alone; print the counts before and after. A step
    that fails says so and the others go on; the result is 1 when one failed."""
    root, now = Path(root or cli.repo_root()), now or board.utcnow()
    before, steps = plan(config, root, now)
    after = Tally(dict(before.cards), dict(before.comments), kept=list(before.kept), setting=before.setting)
    print(f"{cli.NAME} tidy: " + ("dry run, nothing changes. The plan:" if dry else
                                  f"{len(steps)} {'change' if len(steps) == 1 else 'changes'}"))
    failed = 0
    for step in steps:
        if dry:
            print(f"  - {step.says}")
            step.effect(after)
            continue
        try:
            note = step.do()
        except (cli.ColonyError, OSError, ValueError, KeyError) as e:
            failed += 1
            print(f"  - failed: {step.says}: {e}")
            continue
        step.effect(after)
        print(f"  - {step.says}" + (f", {note}" if note else ""))
    if dry and not steps:
        print("  - nothing to change")
    print("Before → after:")
    print("\n".join(report(before, after, dry)))
    return 1 if failed else 0


def tidy(config: dict, args) -> int:
    """`colony tidy [--dry-run]`: tidy the cards, the long issues, the board and the worktrees."""
    return run_tidy(config, dry=args.dry_run)


def relax_batch(sub) -> None:
    """Let `colony batch` run without --card, for hack mode's `colony batch --review --name <n>`, which reviews the
    demo build; batch.Batch.from_args still asks for a card in every other case."""
    parser = sub.choices.get("batch")
    for action in parser._actions if parser else []:
        if action.dest == "card":
            action.required = False


def add_commands(sub) -> None:
    """cli.py's route to this module: `colony tidy`, `colony idea` and `colony card new`."""
    p = sub.add_parser("tidy", help="close stale cards, rotate long issues, archive done items and remove closed "
                                    "cards' clean worktrees; prints the counts before and after")
    p.add_argument("--dry-run", action="store_true", help="print the plan and change nothing")
    p.set_defaults(run=tidy)

    p = sub.add_parser("idea", help="write one idea to the future-work register, never as an issue")
    p.add_argument("text", help="the idea, one line")
    p.set_defaults(run=idea)

    p = sub.add_parser("card", help="make a card: an issue on the board, only for work that starts this week")
    card_sub = p.add_subparsers(dest="card_command", metavar="card-command", required=True)
    q = card_sub.add_parser("new", help="make a card, refusing at the lead's open-card limit and on a duplicate")
    q.add_argument("title", help="the card's title, such as \"builder-2: the login form\"")
    q.add_argument("--body", required=True, help="the task, up to 3 done-when results, the folders, and the "
                                                 "prediction line, such as predicted: S, 20 min")
    q.add_argument("--size", required=True, choices=board.SIZES, help="the card's size")
    q.add_argument("--lead", help="the lead whose card it is, <person>-lead, you by default")
    q.add_argument("--person", help="whose lead you are, when colony.toml names several people")
    q.set_defaults(run=card_new)
    relax_batch(sub)
