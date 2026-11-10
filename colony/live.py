"""Which commit is live, and which merges on the base aren't yet. A merge is not a deploy, so without this a lead
asked "is it live?" can only guess.

The live commit comes from GitHub's deployments, which hosts such as Vercel and Netlify record for each deploy: the
newest successful one to `[hack] deploy_environment` (Production by default). A deploy GitHub doesn't know, such as one
run by hand, is announced with `colony live <sha> [--url <url>]`, which posts `@all live: <sha> is live on <url>` on
the board, and every lead reads it. `colony who` and `colony status` print the newer of the two, and the branches
merged into the base since then, which aren't live yet.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from colony import cli, wait

LIVE_LINE = re.compile(r"\blive: ([0-9a-f]{7,40}) is live(?: on (\S+))?")
SHA = re.compile(r"[0-9a-f]{7,40}")
MERGED = re.compile(r"^Merge (\S+) into ")
DEPLOYMENTS = 20  # the newest deployments read, newest first


@dataclass
class Live:
    """A deploy: its commit, when it went live, where, and how Colony knows."""
    sha: str
    at: str
    url: str
    source: str


def environment(config: dict) -> str:
    """The deployment environment that is the live app: [hack] deploy_environment, Production by default."""
    return str(config.get("hack", {}).get("deploy_environment") or "Production")


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
            return Live(found[1], str(comment.get("created_at") or ""), found[2] or "", "a live: line on the board")
    return None


def newest(*found: Live | None) -> Live | None:
    """The newer of the deploys, by when each went live."""
    known = [one for one in found if one is not None]
    return max(known, key=lambda one: one.at) if known else None


def not_live(root: Path, ref: str, sha: str) -> list[str]:
    """The branches merged into `ref` after `sha`, oldest first, from their merge commits' "Merge <branch> into"."""
    run = subprocess.run(["git", "log", "--merges", "--first-parent", "--format=%s", "--reverse", f"{sha}..{ref}"],
                         cwd=root, capture_output=True, text=True)
    if run.returncode:
        return []
    return [found[1] for line in run.stdout.splitlines() if (found := MERGED.match(line))]


def summary(config: dict, root: Path) -> str:
    """One line on what is live and what isn't yet, for `colony who` and `colony status`."""
    from colony import presence

    try:
        comments = presence.read_comments(config)
    except (cli.ColonyError, OSError, ValueError):
        comments = []
    found = newest(from_deployments(config), from_board(comments))
    if found is None:
        return (f"Live: unknown: GitHub records no {environment(config)} deployment, and no one posted `{cli.NAME} live "
                "<sha>`. Whoever deploys runs it.")
    where = f" on {found.url}" if found.url else ""
    waiting = not_live(root, f"origin/{config['project']['base']}", found.sha)
    rest = (f"; merged but not live yet: {', '.join(waiting)}" if waiting
            else f"; everything merged into {config['project']['base']} is live")
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
