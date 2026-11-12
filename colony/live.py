"""Which commit is live, and which merges on the base aren't yet. A merge is not a deploy, so without this a lead
asked "is it live?" can only guess. The question comes in every mode once work merges, so `colony who` and `colony
status` answer it in each.

The live commit comes from GitHub's deployments, which hosts such as Vercel and Netlify record for each deploy: the
newest successful one to `[project] deploy_environment` (Production by default; hack configs from before it name it
under `[hack]`). A deploy GitHub doesn't know, such as one run by hand, is announced with `colony live <sha> [--url
<url>]`, which posts `@all live: <sha> is live on <url>` on the board, or on the coordination issue outside hack mode,
and every lead reads it. `colony who` and `colony status` print the newer of the two, and what landed on the base
since then, which isn't live yet: `colony merge`'s merges, GitHub's pull request merges and squashes, and a count of
the other commits. Outside hack mode a project may deploy nothing, such as a library, so the line shows only a known
deploy.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from colony import cli, presence, wait

LIVE_LINE = re.compile(r"\blive: ([0-9a-f]{7,40}) is live(?: on (\S+))?")
SHA = re.compile(r"[0-9a-f]{7,40}")
COLONY_MERGE = re.compile(r"^Merge (\S+) into ")  # colony merge's
PULL_MERGE = re.compile(r"^Merge pull request (#\d+) from [^/\s]+/(\S+)")  # GitHub's merge button: from <owner>/<branch>
LOCAL_MERGE = re.compile(r"^Merge (?:remote-tracking )?branch '([^']+)'")  # git merge on a computer
SQUASHED = re.compile(r"^(.*\S) \((#\d+)\)$")  # GitHub's squash and merge: "<title> (#13)"
DEPLOYMENTS = 20  # the newest deployments read, newest first


@dataclass
class Live:
    """A deploy: its commit, when it went live, where, and how Colony knows."""
    sha: str
    at: str
    url: str
    source: str


def environment(config: dict) -> str:
    """The deployment environment that is the live app: [project] deploy_environment, else the [hack] key that hack
    configs from before it hold, else Production."""
    return str(config.get("project", {}).get("deploy_environment")
               or config.get("hack", {}).get("deploy_environment") or "Production")


def from_deployments(config: dict) -> Live | None:
    """The newest successful deployment GitHub records to the live environment, or None."""
    repo, wanted = config["project"]["repo"], environment(config).lower()
    try:
        deployments = json.loads(wait.gh("api", f"repos/{repo}/deployments?per_page={DEPLOYMENTS}") or "[]")
    except (wait.GhError, ValueError):
        return None
    for deployment in deployments if isinstance(deployments, list) else []:
        if str(deployment.get("environment", "")).lower() != wanted:
            continue
        try:
            statuses = json.loads(wait.gh("api", f"repos/{repo}/deployments/{deployment['id']}/statuses?per_page=1")
                                  or "[]")
        except (wait.GhError, ValueError, KeyError):
            continue
        if statuses and statuses[0].get("state") == "success":
            return Live(str(deployment.get("sha", "")), str(statuses[0].get("created_at") or deployment.get(
                "created_at", "")), str(statuses[0].get("environment_url") or ""),
                f"GitHub's {deployment.get('environment')} deployment")
    return None


def from_board(comments: list[dict]) -> Live | None:
    """The newest `live: <sha> is live` line on the board, from `colony live`, or None."""
    for comment in reversed(comments):
        found = LIVE_LINE.search(comment.get("body") or "")
        if found:
            url = found[2] or ""
            url = url if url.startswith("https://") else ""  # a link the person may open: https alone
            return Live(found[1], str(comment.get("created_at") or ""), url, "a live: line on the board")
    return None


def newest(*found: Live | None) -> Live | None:
    """The newer of the deploys, by when each went live."""
    known = [one for one in found if one is not None]
    return max(known, key=lambda one: one.at) if known else None


def landed_as(subject: str) -> str:
    """What a commit on the base's first-parent line landed, read from its subject, or "" when it names nothing."""
    if found := COLONY_MERGE.match(subject):
        return found[1]
    if found := PULL_MERGE.match(subject):
        return f"{found[1]} ({found[2]})"
    if found := LOCAL_MERGE.match(subject):
        return found[1]
    if found := SQUASHED.match(subject):
        return f"{found[2]} ({found[1]})"
    return ""


def not_live(root: Path, ref: str, sha: str) -> list[str] | None:
    """What landed on `ref` after `sha`, oldest first: each merge or squashed pull request by name, then a count of
    the other commits, such as a direct push. None when git can't tell, such as when the clone lacks `sha`."""
    run = subprocess.run(["git", "log", "--first-parent", "--format=%s", "--reverse", f"{sha}..{ref}"],
                         cwd=root, capture_output=True, text=True)
    if run.returncode:
        return None
    landed = [landed_as(line) for line in run.stdout.splitlines()]
    named = [one for one in landed if one]
    if others := len(landed) - len(named):
        named.append(f"{others} other commit{'' if others == 1 else 's'}")
    return named


def summary(config: dict, root: Path) -> str:
    """One line on what is live and what isn't yet, for `colony who` and `colony status`, or "" outside hack mode
    when no deploy is known."""
    logins = frozenset(str(login).lower() for login in config.get("people", {}).get("logins", []))
    try:
        # On a public repo anyone can comment: a live: line counts from the team's own logins alone.
        comments = [comment for comment in presence.read_comments(config) if presence.by_team(comment, logins)]
    except (cli.ColonyError, OSError, ValueError):
        comments = []
    found = newest(from_deployments(config), from_board(comments))
    if found is None:
        if not wait.hack(config):
            return ""  # a project outside hack mode may deploy nothing, such as a library
        return (f"Live: unknown: GitHub records no {environment(config)} deployment, and no one posted `{cli.NAME} live "
                "<sha>`. Whoever deploys runs it.")
    where = f" on {found.url}" if found.url else ""
    waiting = not_live(root, f"origin/{config['project']['base']}", found.sha)
    if waiting is None:
        rest = f"; which merges aren't live is unknown: this clone lacks {found.sha[:7]}, so run `git fetch`"
    elif waiting:
        rest = f"; merged but not live yet: {', '.join(waiting)}"
    else:
        rest = f"; everything merged into {config['project']['base']} is live"
    return f"Live: {found.sha[:7]}{where}, since {found.at}, from {found.source}{rest}."


def post(config: dict, args) -> int:
    """`colony live <sha> [--url <url>]`: whoever deploys by hand tells every lead which commit is live."""
    from colony import transport

    sha = args.sha.strip().lower()
    if not SHA.fullmatch(sha):
        raise cli.ColonyError(f"{args.sha!r} is not a commit, such as 1a2b3c4: name the commit you deployed")
    where = f" on {args.url.strip()}" if getattr(args, "url", "") else ""
    line = f"@{wait.ALL} live: {sha} is live{where}"
    number = transport.send(config, f"@{wait.ALL}", line)
    print(f"#{number} {line}")
    return 0
