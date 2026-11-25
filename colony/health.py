"""colony health: keep the shared branch green.

`colony health run` looks at the newest commit of each shared branch, `[health] branches` (the integration branch by
default), and finds out whether it passes its checks, as `[health] source` says: "ci" reads the code host's checks on
that commit, which any CI reports; "local" runs the full suite on this computer, in the background (checks.py); and
"auto", the default, reads CI when the commit has any checks there, and runs the suite here otherwise. A result on a
commit is read again, never run again: the ledger keeps it, a pass or a failure.

When a branch fails, it finds the likely cause (suspects): the pull requests merged since the branch last passed,
narrowed by blame to the ones that changed a failing test or a file such a test covers. It sends each one's lead one
line, on the coordination issue or the board, naming the failure and the pull request, and every lead one `@all`
line. With `[health] pause` on, the default, it puts a `red` hold on the branch (freeze.py), so every lead's `colony
merge` and `colony batch` pause until it passes again, except the fixes `colony freeze allow` names. When the branch
passes again, it lifts the hold and tells every lead. Each red commit is told once, across every computer: the hold
on origin names it.

`colony health watch` runs that every `[health] every_minutes` (60), and every PENDING_SECONDS while a run is going,
as one lead's background command. With nothing new on a branch, a pass costs one fetch. `colony health status` prints
what each branch last showed on this computer, and what is held.
"""
from __future__ import annotations

import os
import re
import sys
import time
from argparse import Namespace
from pathlib import Path, PurePosixPath

from colony import batch, branches, cli, freeze, merge, wait

SOURCES = ("auto", "ci", "local")
EVERY_MINUTES = 60
PENDING_SECONDS = 120  # how often the watch looks again while a run or CI on a branch's head is still going
SUSPECTS_NAMED = 5  # the pull requests a red line names at most
SLEEP = time.sleep
PATHISH = re.compile(r"[\w./-]+\.\w+")


def settings(config: dict, root: Path | None = None) -> dict:
    """`[health]`, each key with its default."""
    table = config.get("health") or {}
    source = table.get("source") or "auto"
    if source not in SOURCES:
        raise cli.ColonyError(f"[health] source is {', '.join(map(repr, SOURCES))}, not {source!r}")
    every = table.get("every_minutes", EVERY_MINUTES)
    if isinstance(every, bool) or not isinstance(every, (int, float)) or every <= 0:
        raise cli.ColonyError("[health] every_minutes is a number of minutes above 0, such as 60")
    shared = table.get("branches") or [branches.names(config, root).integration]
    if not isinstance(shared, list) or not all(isinstance(b, str) and b.strip() for b in shared):
        raise cli.ColonyError('[health] branches is a list of branch names, such as ["develop"]')
    return {"source": source, "every_minutes": float(every), "branches": [b.strip() for b in shared],
            "pause": bool(table.get("pause", True))}


def state_path(config: dict) -> Path:
    """This computer's record of what each branch last showed: ~/.colony/<project>/health.json."""
    return wait.state_path(config["project"]["name"], "health")


def remembered(config: dict) -> dict:
    """What each branch last showed on this computer: its head, verdict, when, and the last commit that passed."""
    found = wait.read_json(state_path(config), {})
    return found if isinstance(found, dict) else {}


def remember(config: dict, branch: str, **values) -> None:
    """Keep what a branch showed."""
    found = remembered(config)
    found[branch] = {**(found.get(branch) or {}), **values, "at": time.time()}
    wait.write_json(state_path(config), found)


# The verdict on one commit


def ci_verdict(config: dict, sha: str) -> tuple[str, list[str]]:
    """The code host's verdict on a commit: green, red with the failing checks' names, pending, or none when no CI
    reported on it."""
    from colony import checks

    found = checks.ci_state(config["project"]["repo"], sha)
    if not found:
        return "none", []
    failed = [c["name"] for c in found if c["state"] == "fail"]
    if failed:
        return "red", failed
    if any(c["state"] == "pending" for c in found):
        return "pending", []
    return "green", []


def full_command(config: dict) -> str:
    """The full suite's command: `[project] checks` for every area."""
    return batch.every_area(config, config["project"]["checks"])


def local_verdict(config: dict, root: Path, sha: str, start: bool = True) -> tuple[str, list[str]]:
    """The full suite's verdict on a commit, from the ledger when it ran on the same code before, pending while a
    run of it is going here, else pending once it starts one in the background (checks.check_run)."""
    from colony import checks

    tree = batch._git(root, "rev-parse", f"{sha}^{{tree}}")
    command = full_command(config)
    kept = checks.read_json(checks.ledger_path(checks.colony_home(config)), {})
    entries = sorted((e for e in (kept.values() if isinstance(kept, dict) else []) if isinstance(e, dict)
                      and e.get("tree") == tree and e.get("command") == command), key=lambda e: e.get("at", 0))
    if entries:
        newest = entries[-1]
        return ("green", []) if newest.get("result") == "pass" else ("red", list(newest.get("failures") or
                                                                                [newest.get("line") or "the suite"]))
    if any(run.get("tree") == tree and run.get("command") == command for run in checks.running(config)):
        return "pending", []
    if not start:
        return "none", []
    checks.check_run(config, Namespace(full=True, scope=None, ref=sha, again=False, wait=0, until_failure=False,
                                       dry_run=False))
    return "pending", []


def verdict(config: dict, root: Path, sha: str, source: str) -> tuple[str, list[str], str]:
    """A commit's verdict, its failures, and where it came from: CI or this computer."""
    if source in ("auto", "ci"):
        found, failures = ci_verdict(config, sha)
        if found != "none" or source == "ci":
            return found, failures, "CI"
    found, failures = local_verdict(config, root, sha)
    return found, failures, "the full suite here"


# Who to tell


def failing_paths(failures: list[str]) -> list[str]:
    """The files the failures name, such as tests/test_a.py from tests/test_a.py::test_b."""
    found = []
    for failure in failures:
        for token in PATHISH.findall(failure.split("::")[0].split(" > ")[0]):
            if "/" in token or PurePosixPath(token).suffix:
                found.append(token)
    return list(dict.fromkeys(found))


def landed_since(config: dict, root: Path, branch: str, head: str, green: str) -> list[dict]:
    """The pull requests merged into the branch after `green`, the last commit that passed, up to head, oldest first;
    without a known green, the one head itself merged."""
    from colony import release

    found = []
    if green and not merge._exists(root, f"{green}^{{commit}}"):  # ^{commit}: a bare full id passes unread
        green = ""  # a green this clone lacks, as after a force push, bounds nothing: go by head alone
    for pr in release.merged_prs(config, branch):
        oid = (pr.get("mergeCommit") or {}).get("oid", "")
        if not oid or not merge._exists(root, oid) or not merge._behind(root, oid, head):
            continue
        if green and merge._behind(root, oid, green):
            continue
        if not green and oid != head:
            continue
        found.append({"number": pr["number"], "title": pr.get("title", ""), "oid": oid,
                      "author": (pr.get("author") or {}).get("login", ""),
                      "cards": [int(n) for n in release.CLOSES.findall(pr.get("body") or "")]})
    return sorted(found, key=lambda pr: pr["number"])


def blamed(config: dict, root: Path, landed: list[dict], paths: list[str]) -> list[dict]:
    """The pull requests that changed a failing test, or a file a failing test covers (checks.related_tests)."""
    from colony import checks, release

    if not paths:
        return []
    failing = set(paths)
    found = []
    for pr in landed:
        changed = [path for _, path in release.files_of(root, pr["oid"])]
        covered = set(checks.related_tests(config, root, changed)[0]) if changed else set()
        if failing & (set(changed) | covered):
            found.append(pr)
    return found


def suspects(config: dict, root: Path, branch: str, head: str, green: str, failures: list[str]) -> tuple[list[dict], str]:
    """The likely cause of a red branch, and how it was found: by blame, or by the pull requests merged since it
    last passed."""
    from colony import release

    landed = landed_since(config, root, branch, head, green)
    found = blamed(config, root, landed, failing_paths(failures))
    how = "blame on the failing tests" if found else "the pull requests merged since it last passed"
    found = found or landed
    release.leads(config, found)
    return found, how


def short(text: str, most: int) -> str:
    """The text cut to `most` characters, with … when cut."""
    text = " ".join(str(text).split())
    return text if len(text) <= most else text[:most - 1].rstrip() + "…"


def tell(config: dict, args, branch: str, sha: str, failures: list[str], found: list[dict], how: str, by: str) -> None:
    """Send each suspect's lead one line, and every lead one @all line. A line that can't be posted says so on
    stderr, and the others still go."""
    from colony import transport

    me = wait.lead_name(config, args)
    first = short(failures[0] if failures else "the checks", 60)
    sent = []
    for lead in dict.fromkeys(lead for pr in found for lead in pr["leads"]):
        mine = [pr for pr in found if lead in pr["leads"]][:2]
        named = " and ".join(f"#{pr['number']} ({short(pr['title'], 40)})" for pr in mine)
        sentence = (f"red: {branch} fails its checks at {sha[:7]} ({first}), by {by}; your {named} is the likely "
                    f"cause, found by {how}: fix it first, and name the fix with `{cli.NAME} freeze allow <branch>`")
        sent.append((lead, wait.compose(lead, short(sentence, wait.MAX_LINE - 40), me)))
    cause = ", ".join(f"#{pr['number']} ({', '.join(pr['leads'])})" for pr in found[:SUSPECTS_NAMED]) or "unknown"
    pause = "; new landings pause until it passes, except named fixes" if settings(config)["pause"] else ""
    sentence = short(f"red: {branch} fails its checks at {sha[:7]} ({first}){pause}; the likely cause is {cause}",
                     wait.MAX_LINE - 40)
    sent.append((f"@{wait.ALL}", wait.compose(f"@{wait.ALL}", sentence, me)))
    for to, line in sent:
        try:
            transport.send(config, to, line)
            print(line)
        except (cli.ColonyError, wait.GhError) as e:
            print(f"{cli.NAME} health: not posted for {to}: {e}", file=sys.stderr)


def check_branch(config: dict, root: Path, branch: str, args) -> int:
    """One look at a branch's head: 0 green, 1 red, checks.RUNNING_EXIT while its verdict is still pending."""
    from colony import checks

    if not merge._exists(root, f"origin/{branch}"):
        print(f"{branch}: not on origin")
        return 0
    head = merge._git(root, "rev-parse", f"origin/{branch}")
    s = settings(config, root)
    found, failures, by = verdict(config, root, head, getattr(args, "source", None) or s["source"])
    known = remembered(config).get(branch) or {}
    try:
        holds = freeze.on(freeze.read(root)[1], branch)
    except freeze.Unreadable as e:
        print(f"{cli.NAME} health: origin's holds could not be read: {e}", file=sys.stderr)
        holds = []
    red = next((h for h in holds if h.get("kind") == "red"), None)
    if found == "pending":
        remember(config, branch, head=head, verdict="pending")
        print(f"{branch} at {head[:9]}: its checks are still running ({by})")
        return checks.RUNNING_EXIT
    if found == "none":
        print(f"{branch} at {head[:9]}: no check ran on it, and none could start")
        return checks.RUNNING_EXIT
    if found == "green":
        remember(config, branch, head=head, verdict="green", green=head)
        print(f"{branch} at {head[:9]}: green ({by})")
        lifted = freeze.lift(root, branch, ("red",)) if red else []
        if lifted or (not s["pause"] and known.get("verdict") == "red"):
            freeze.post(config, args, f"green: {branch} passes its checks again at {head[:7]}, so work lands as usual")
        return 0
    green = known.get("green") or (red or {}).get("green") or ""
    remember(config, branch, head=head, verdict="red", failures=failures[:10])
    print(f"{branch} at {head[:9]}: red ({by}): {', '.join(failures[:3]) or 'failing'}")
    if (red and red.get("sha") == head) or known.get("told") == head:
        print(f"every lead already heard that {branch} is red at {head[:7]}")
        return 1
    found_prs, how = suspects(config, root, branch, head, green, failures)
    if s["pause"]:
        freeze.put(root, {**freeze.hold("red", branch, wait.lead_name(config, args),
                                        short(failures[0] if failures else "", 80), sha=head), "green": green})
    tell(config, args, branch, head, failures, found_prs, how, by)
    remember(config, branch, told=head)
    return 1


def run(config: dict, args) -> int:
    """`colony health run|watch|status`: see the module's docstring."""
    root = cli.repo_root()
    if args.action == "status":
        return status(config, root, args)
    if os.environ.get(cli.SESSION_ENV, "").lower() not in ("", cli.LEAD):
        raise cli.ColonyError("health is for a lead or the person, never a helper")
    from colony import checks

    s = settings(config, root)  # a setting it can't use stops it here, never round after round in the watch
    shared = [args.branch] if args.branch else s["branches"]
    if args.dry_run:
        where = {"ci": "CI", "auto": "CI, else the full suite here", "local": "the full suite here"}[
            getattr(args, "source", None) or s["source"]]
        print(f"{cli.NAME} health: dry run, nothing runs.\n  $ git fetch origin\n  for {', '.join(shared)}: read the "
              f"verdict on the head commit from {where}, the suite being `{full_command(config)}`\n  on red: tell the "
              "likely cause's lead" + (", and pause landings until it passes" if s["pause"] else ""))
        return 0
    rounds = getattr(args, "rounds", None)  # how many looks the watch takes before it ends; None is no end
    done = 0
    while True:
        try:
            merge._git(root, "fetch", "origin")
            codes = [check_branch(config, root, branch, args) for branch in shared]
        except (cli.ColonyError, freeze.Unreadable) as e:
            if args.action == "run":
                if isinstance(e, cli.ColonyError):
                    raise
                raise cli.ColonyError(f"origin's merge freeze could not be read: {e}") from None
            # The watch runs for hours: a look that fails, as when origin can't be reached, is tried again soon.
            print(f"{cli.NAME} health: this look failed, so the watch looks again in {PENDING_SECONDS // 60} "
                  f"minutes: {e}", file=sys.stderr)
            codes = [checks.RUNNING_EXIT]
        done += 1
        if args.action == "run" or (rounds is not None and done >= rounds):
            return 1 if 1 in codes else checks.RUNNING_EXIT if any(codes) else 0
        pending = any(code not in (0, 1) for code in codes)
        every = getattr(args, "every", None) or s["every_minutes"]
        SLEEP(PENDING_SECONDS if pending else 60 * every)


def status(config: dict, root: Path, args) -> int:
    """What each branch last showed on this computer, and what origin holds."""
    known = remembered(config)
    shared = [args.branch] if args.branch else settings(config, root)["branches"]
    for branch in shared:
        found = known.get(branch)
        if not found:
            print(f"{branch}: not looked at on this computer yet: `{cli.NAME} health run`")
            continue
        green = f", last green {str(found.get('green', ''))[:9]}" if found.get("green") else ""
        print(f"{branch}: {found.get('verdict')} at {str(found.get('head', ''))[:9]}, looked at "
              f"{freeze.when(found.get('at', 0))}{green}")
    try:
        holds = [h for h in freeze.read(root)[1] if h.get("branch") in shared and not freeze.ended(h)]
    except freeze.Unreadable:
        holds = []
    for held in holds:
        print(f"held: {freeze.describe(held)}")
    return 0


def register(sub) -> None:
    """The `health` command and its actions."""
    p = sub.add_parser("health", help="keep the shared branch green: check its head, tell the lead whose change broke "
                                      "it, and pause landings while it is red")
    actions = p.add_subparsers(dest="action", metavar="action", required=True)
    for name, text in (("run", "look at each shared branch's head once"),
                       ("watch", "look every [health] every_minutes, as a background command"),
                       ("status", "what each shared branch last showed, and what is held")):
        a = actions.add_parser(name, help=text)
        a.add_argument("--branch", help="this branch alone, instead of [health] branches")
        if name != "status":
            a.add_argument("--source", choices=SOURCES, help="where the verdict comes from, instead of [health] source")
            a.add_argument("--dry-run", action="store_true", help="print the plan and run nothing")
        if name == "watch":
            a.add_argument("--every", type=float, metavar="MINUTES", help="minutes between looks")
        a.set_defaults(run=run, action=name)
