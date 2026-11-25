"""colony freeze: pause new landings on a shared branch, for every person's leads, while a release is checked or while
the branch fails its checks.

A hold pauses landings on one branch. There are three kinds:

- `freeze`: a lead or the person froze the branch by hand, with `colony freeze on`;
- `release`: `colony release` froze the integration branch while the release's checks run, so no lead's merge forces
  another long test run; `colony release --after` lifts it;
- `red`: `colony health` found the branch failing its checks, and pauses new landings until it passes again.

The holds live on the code host, as one commit on origin's `refs/colony/holds` whose message holds them as JSON, so
every computer reads the same holds, whoever's leads run there. A change reads the holds, changes them, and pushes
only while the ref is still where it was read (compare and swap), so two computers never lose each other's change.
A `freeze` or `release` hold ends by itself at its `until` time, `[release] freeze_hours` after it started by
default, so a forgotten freeze never blocks the team for long. A `red` hold stays until the branch passes again.

While a branch holds a hold, `colony merge` refuses to land on it and `colony batch` refuses to start for it, except
for the fixes the hold names: a branch name, or a card as `#<n>`, which `colony freeze allow` adds. Each change to a
hold posts one `@all` line, so every lead hears it. `colony freeze check` answers for other tools, such as a merge
guard, with its exit code.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from colony import cli, wait

HOLDS_REF = "refs/colony/holds"
SEEN_REF = "refs/colony/holds-seen"  # this clone's copy of origin's holds, fetched to read them
KINDS = ("freeze", "release", "red")
FREEZE_HOURS = 12  # [release] freeze_hours: a freeze ends by itself after this long
TRIES = 5  # changes in a row another computer may beat, before a change gives up
LEASE_LOST = ("[rejected]", "stale info", "fetch first", "already exists")


class Unreadable(Exception):
    """Origin's holds could not be read, as when origin can't be reached."""


def freeze_hours(config: dict) -> float:
    """`[release] freeze_hours`: how long a freeze lasts unless it is lifted first."""
    hours = (config.get("release") or {}).get("freeze_hours", FREEZE_HOURS)
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0:
        raise cli.ColonyError("[release] freeze_hours is a number of hours above 0, such as 12")
    return float(hours)


AS_COLONY = {"GIT_AUTHOR_NAME": "Colony", "GIT_AUTHOR_EMAIL": "colony@localhost", "GIT_COMMITTER_NAME": "Colony",
             "GIT_COMMITTER_EMAIL": "colony@localhost"}


def _git(root, *args: str, text: str | None = None) -> subprocess.CompletedProcess:
    """One git command run as Colony, so a commit it makes names Colony and not a person. The names go in the
    environment, since a person's own GIT_AUTHOR_NAME there would win over git's settings."""
    return subprocess.run(["git", *args], cwd=root, input=text, capture_output=True, text=True,
                          env={**os.environ, **AS_COLONY})


def read(root) -> tuple[str, list[dict]]:
    """Origin's holds: the commit the ref points at ("" when origin has none) and the holds it holds."""
    listed = _git(root, "ls-remote", "origin", HOLDS_REF)
    if listed.returncode:
        raise Unreadable(listed.stderr.strip().splitlines()[-1][:200] if listed.stderr.strip() else "git ls-remote "
                         "failed")
    found = listed.stdout.split()
    if not found:
        return "", []
    fetched = _git(root, "fetch", "-q", "--no-tags", "origin", f"+{HOLDS_REF}:{SEEN_REF}")
    if fetched.returncode:
        raise Unreadable(fetched.stderr.strip()[:200] or "git fetch failed")
    message = _git(root, "log", "-1", "--format=%B", SEEN_REF).stdout
    _, _, body = message.partition("\n\n")
    try:
        holds = json.loads(body or "[]")
    except ValueError:
        holds = []
    return found[0], [hold for hold in holds if isinstance(hold, dict)] if isinstance(holds, list) else []


def ended(hold: dict, now: float | None = None) -> bool:
    """Whether a hold's time is up: it has an `until`, and that has passed."""
    until = hold.get("until") or 0
    return bool(until) and float(until) <= (time.time() if now is None else now)


def on(holds: list[dict], branch: str, now: float | None = None) -> list[dict]:
    """The holds on a branch whose time isn't up."""
    return [hold for hold in holds if hold.get("branch") == branch and not ended(hold, now)]


def write(root, change) -> list[dict]:
    """Change origin's holds: `change` takes the holds whose time isn't up and returns the new list. The push goes
    through only while origin's ref is still the one read, else it reads again and tries once more, up to TRIES
    times. An empty list removes the ref."""
    for _ in range(TRIES):
        old, holds = read(root)
        new = change([hold for hold in holds if not ended(hold)])
        if new == holds:
            return new
        if new:
            tree = _git(root, "hash-object", "-w", "-t", "tree", "--stdin", text="").stdout.strip()
            made = _git(root, "commit-tree", tree, "-m", f"colony holds\n\n{json.dumps(new, indent=1)}")
            if made.returncode:
                raise cli.ColonyError(f"git commit-tree failed: {made.stderr.strip()[:200]}")
            target = f"{made.stdout.strip()}:{HOLDS_REF}"
        else:
            target = f":{HOLDS_REF}"
        push = _git(root, "push", "--porcelain", f"--force-with-lease={HOLDS_REF}:{old}", "origin", target)
        if push.returncode == 0:
            return new
        said = f"{push.stdout}\n{push.stderr}"
        if not any(sign in said for sign in LEASE_LOST):
            raise cli.ColonyError(f"origin refused the holds: {said.strip().splitlines()[-1][:200]}")
    raise cli.ColonyError(f"origin's holds changed {TRIES} times while this change was made: run it again")


def when(at) -> str:
    """A time as HH:MM UTC, with the date when it isn't today."""
    at = float(at or 0)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    day = time.strftime("%Y-%m-%d", time.gmtime(at))
    return time.strftime("%H:%M UTC" if day == today else "%Y-%m-%d %H:%M UTC", time.gmtime(at))


def describe(hold: dict) -> str:
    """One hold in words, such as `dev is frozen for the release, by ana-lead since 14:02 UTC, until 02:02 UTC`."""
    branch, kind = hold.get("branch", "?"), hold.get("kind")
    why = f" ({hold['why']})" if hold.get("why") else ""
    if kind == "red":
        text = f"{branch} is red: it fails its checks at {str(hold.get('sha', ''))[:7]}{why}, since {when(hold.get('since'))}"
    else:
        reason = "for the release" if kind == "release" else "by hand"
        text = f"{branch} is frozen {reason}{why}, by {hold.get('by') or 'someone'} since {when(hold.get('since'))}"
    if hold.get("until"):
        text += f", until {when(hold['until'])}"
    if hold.get("allow"):
        text += f"; named fixes: {', '.join(hold['allow'])}"
    return text


def allowed(hold: dict, groups) -> bool:
    """Whether every piece of work may land under the hold: each group, a piece's names such as its branch and its
    card as `#<n>`, has a name the hold allows."""
    names = set(hold.get("allow") or [])
    return all(names & {str(name) for name in group} for group in groups)


def blocking(config: dict, root, branch: str, groups, also=()) -> list[dict]:
    """The holds on the branch, and on the branches in `also`, that refuse the work (see allowed). Holds that can't
    be read refuse nothing, with a note on stderr: the merge or batch that asked fetches origin itself next, and stops
    there when origin is down."""
    try:
        found = read(root)[1]
    except Unreadable as e:
        print(f"{cli.NAME}: origin's merge freeze could not be read, so nothing is held: {e}", file=sys.stderr)
        return []
    holds = [hold for name in dict.fromkeys([branch, *also]) for hold in on(found, name)]
    return [hold for hold in holds if not allowed(hold, groups)]


def reaches(config: dict, branch: str) -> list[str]:
    """The branches whose holds pause work that lands on `branch`: the branch itself, and for `[project] base`, the
    integration branch too when it differs, since the team's work reaches the integration branch from the base. So a
    freeze on either one, such as the release's freeze on the integration branch, pauses every lead's landing."""
    from colony import branches

    if branch != config["project"]["base"]:
        return [branch]
    return list(dict.fromkeys([branch, branches.names(config).integration]))


def refuse(config: dict, root, branch: str, groups, what: str) -> None:
    """Refuse work that lands on the branch while a hold on it, or on the integration branch (reaches), doesn't name
    it, saying who holds it, why, until when, and how a fix gets through."""
    held = blocking(config, root, branch, groups, also=reaches(config, branch))
    if not held:
        return
    first = [str(group[0]) for group in groups][:3]
    raise cli.ColonyError(f"{what} is paused: {describe(held[0])}. A fix gets through once it is named: "
                          f"`{cli.NAME} freeze allow {' '.join(first) or '<branch>'}`")


def post(config: dict, args, sentence: str) -> None:
    """Tell every lead, on the board in hack mode or on the coordination issue; a post that fails says so on stderr,
    since the hold itself is on origin."""
    from colony import transport

    line = wait.compose(f"@{wait.ALL}", sentence, wait.lead_name(config, args))
    try:
        transport.send(config, f"@{wait.ALL}", line)
    except (cli.ColonyError, wait.GhError) as e:
        print(f"{cli.NAME} freeze: the other leads didn't hear it: {e}", file=sys.stderr)


def hold(kind: str, branch: str, by: str, why: str, until: float = 0.0, sha: str = "", allow=()) -> dict:
    """A new hold."""
    return {"branch": branch, "kind": kind, "by": by, "why": why, "since": time.time(), "until": until, "sha": sha,
            "allow": list(dict.fromkeys(allow))}


def put(root, new: dict) -> list[dict]:
    """Add a hold, in place of one of the same kind on the same branch, keeping the fixes that one named."""
    def change(holds: list[dict]) -> list[dict]:
        kept = [h for h in holds if (h.get("branch"), h.get("kind")) != (new["branch"], new["kind"])]
        named = [name for h in holds if (h.get("branch"), h.get("kind")) == (new["branch"], new["kind"])
                 for name in h.get("allow") or []]
        return [*kept, {**new, "allow": list(dict.fromkeys([*named, *new["allow"]]))}]
    return write(root, change)


def lift(root, branch: str, kinds) -> list[dict]:
    """Remove the branch's holds of these kinds; returns the ones removed."""
    gone: list[dict] = []

    def change(holds: list[dict]) -> list[dict]:
        gone[:] = [h for h in holds if h.get("branch") == branch and h.get("kind") in kinds]
        return [h for h in holds if h not in gone]
    write(root, change)
    return gone


def card_or_branch(name: str) -> str:
    """A fix as a hold names it: a card as `#<n>`, else the branch as given."""
    name = name.strip()
    return f"#{name.lstrip('#')}" if name.lstrip("#").isdigit() else name


def default_branch(config: dict) -> str:
    """The branch a freeze holds when none is named: the integration branch (branches.names)."""
    from colony import branches

    return branches.names(config).integration


def lead_only() -> None:
    """Refuse a helper: holds pause every person's leads, so a lead or the person sets them."""
    if os.environ.get(cli.SESSION_ENV, "").lower() not in ("", cli.LEAD):
        raise cli.ColonyError("a merge freeze is for a lead or the person, never a helper: ask your lead")


def run(config: dict, args) -> int:
    """`colony freeze on|off|allow|status|check`: see the module's docstring."""
    try:
        return act(config, args, cli.repo_root())
    except Unreadable as e:
        raise cli.ColonyError(f"origin's merge freeze could not be read: {e}") from None


def act(config: dict, args, root) -> int:
    """One `colony freeze` action (run)."""
    branch = (args.branch or "").strip() or default_branch(config)
    if args.action == "status":
        found = read(root)[1]
        holds = on(found, branch) if args.branch else [h for h in found if not ended(h)]
        print("\n".join(describe(h) for h in holds) if holds else
              f"nothing is frozen{f' on {branch}' if args.branch else ''}: work lands as usual")
        return 0
    if args.action == "check":
        groups = [(card_or_branch(name),) for name in args.names] or [("",)]
        held = blocking(config, root, branch, groups)
        print(describe(held[0]) if held else f"{', '.join(args.names) or 'work'} may land on {branch}")
        return 1 if held else 0
    lead_only()
    me = wait.lead_name(config, args)
    if args.action == "on":
        until = time.time() + 3600 * (args.hours if args.hours else freeze_hours(config))
        why = " ".join((args.why or "").split())
        put(root, hold("freeze", branch, me, why, until, allow=[card_or_branch(n) for n in args.allow or []]))
        print(f"froze {branch} until {when(until)}: `{cli.NAME} merge` and `{cli.NAME} batch` refuse to land on it, "
              "except named fixes")
        post(config, args, f"freeze: {branch} is frozen until {when(until)}{f' ({why})' if why else ''}; only named "
                           f"fixes land, so name yours with `{cli.NAME} freeze allow <branch>`")
        return 0
    if args.action == "off":
        kinds = ("freeze", "release", "red") if args.red else ("freeze", "release")
        gone = lift(root, branch, kinds)
        if not gone:
            print(f"{branch} held no {'hold' if args.red else 'freeze'}: nothing to lift")
            return 0
        print(f"lifted on {branch}: " + "; ".join(describe(h) for h in gone))
        post(config, args, f"freeze: {branch} is open again, so work lands as usual")
        return 0
    names = [card_or_branch(name) for name in args.names]
    if not names:
        raise cli.ColonyError(f"name the fix: `{cli.NAME} freeze allow <branch or card number>`")

    def change(holds: list[dict]) -> list[dict]:
        return [{**h, "allow": list(dict.fromkeys([*(h.get("allow") or []), *names]))} if h.get("branch") == branch
                else h for h in holds]
    if not on(write(root, change), branch):
        print(f"nothing is frozen on {branch}, so {', '.join(names)} lands as usual")
        return 0
    print(f"{', '.join(names)} may land on {branch} while it is held")
    post(config, args, f"freeze: {', '.join(names)} may land on {branch} as a named fix")
    return 0


def register(sub) -> None:
    """The `freeze` command and its actions."""
    p = sub.add_parser("freeze", help="pause new landings on a shared branch for every person's leads, except named "
                                      "fixes, or see what is held")
    actions = p.add_subparsers(dest="action", metavar="action", required=True)
    for name, text in (("on", "freeze the integration branch, or --branch, for every person's leads"),
                       ("off", "lift the freeze on the branch, and with --red its red hold too"),
                       ("allow", "name fixes that may land while the branch is held: branches, or cards as numbers"),
                       ("status", "what is held, on every branch or on --branch"),
                       ("check", "exit 0 when the named work may land on the branch, 1 while a hold refuses it")):
        a = actions.add_parser(name, help=text)
        a.add_argument("--branch", help="the branch, instead of the integration branch")
        if name == "on":
            a.add_argument("--why", help="why, in a few words, such as the release's link")
            a.add_argument("--hours", type=float, help="how long it lasts, instead of [release] freeze_hours")
            a.add_argument("--allow", action="append", metavar="NAME", help="a fix that may land anyway; repeat it")
        if name == "off":
            a.add_argument("--red", action="store_true", help="lift the red hold too, as for a false alarm")
        if name in ("allow", "check"):
            a.add_argument("names", nargs="*" if name == "check" else "+", metavar="name",
                           help="a branch, or a card's number")
        a.set_defaults(run=run, action=name)


def guard_merge(config: dict, root, base: str, branches: list[str]) -> None:
    """`colony merge`'s check before it lands branches on the base: each branch must be a named fix."""
    refuse(config, root, base, [(b,) for b in branches], f"landing {' and '.join(branches)} on {base}")


def guard_batch(config: dict, root, base: str, cards: dict[str, str]) -> None:
    """`colony batch`'s check before it starts: every card's branch, or the card itself, must be a named fix."""
    refuse(config, root, base, [(branch, f"#{number}") for number, branch in cards.items()], f"a batch into {base}")
