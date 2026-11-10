"""Private lines between leads. On a public repo the board is a public issue, so a lead has nowhere to post what
must stay private, such as a security flaw it found, and the person ends up carrying it to the other lead by hand.

`colony say --private <to> "<sentence>"` posts the line on the private board, an issue titled `Private board:
<project>` in `[messages] private_repo`, a private repo the team owns, and on the public board only a pointer, `@<login>
a private line waits for you: run colony private`, with none of the line's words. `colony private` prints the private
lines for this session that it hasn't shown yet. When the project's own repo is private, its board is private already,
and a private line goes there.
"""
from __future__ import annotations

import json
import os
import time

from colony import cli, presence, wait

TITLE = "Private board: {project}"
VISIBILITY_EVERY = 24 * 3600  # how long the repo's visibility is remembered


def is_public(config: dict) -> bool:
    """Whether the project's repo is public, as GitHub says, remembered for a day; unknown counts as public."""
    project, repo = config["project"]["name"], config["project"]["repo"]
    path = wait.state_path(project, "visibility")
    held = wait.read_json(path, {})
    if isinstance(held, dict) and time.time() - float(held.get("at", 0)) < VISIBILITY_EVERY:
        return bool(held.get("public", True))
    try:
        seen = wait.gh("repo", "view", repo, "--json", "visibility", "-q", ".visibility").strip().upper()
    except wait.GhError:
        return True
    public = seen not in ("PRIVATE", "INTERNAL")
    wait.write_json(path, {"public": public, "at": time.time()})
    return public


def board(config: dict) -> tuple[str, int]:
    """The private board: the open issue titled `Private board: <project>` in [messages] private_repo, made the first
    time."""
    repo = str(config.get("messages", {}).get("private_repo") or "")
    if not repo:
        raise cli.ColonyError(f"{config['project']['repo']} is public, so its board is too: set [messages] "
                              f"private_repo = \"<owner>/<a private repo the team owns>\" in {cli.DIR}/{cli.CONFIG_NAME} "
                              "for private lines")
    title = TITLE.format(project=config["project"]["name"])
    listed = json.loads(wait.gh("issue", "list", "--repo", repo, "--state", "open", "--search", f'"{title}" in:title',
                                "--json", "number,title") or "[]")
    found = next((issue["number"] for issue in listed if issue.get("title") == title), None)
    if found is None:
        made = wait.gh("issue", "create", "--repo", repo, "--title", title, "--body",
                       f"Private lines between the leads of {config['project']['name']}: `colony say --private` posts "
                       "here, and `colony private` reads it.")
        found = int(made.strip().rsplit("/", 1)[-1])
    return repo, int(found)


def send(config: dict, to: str, lines: list[str], me: str) -> int:
    """Post private lines for `to`: on the private board with a pointer on the public one, or on a private repo's
    own board."""
    from colony import transport

    if not is_public(config):
        number = transport.send(config, to, "\n".join(lines))
        for line in lines:
            print(f"#{number} {line}")
        return 0
    repo, number = board(config)
    wait.gh("issue", "comment", str(number), "--repo", repo, "--body", "\n".join(lines))
    login = to if to.startswith("@") else f"@{to.split('-', 1)[0]}"  # ben-main-lead is ben's
    pointer = f"{login} a private line waits for you: run `{cli.NAME} private` (from {me})"
    transport.send(config, login, pointer)
    for line in lines:
        print(f"private #{number} in {repo}: {line}")
    print(f"and on the board: {pointer}")
    return 0


def read(config: dict, args) -> int:
    """`colony private`: print the private board's lines for this session that it hasn't shown yet."""
    me = os.environ.get(cli.SESSION_ENV, "").lower()
    if not me:
        raise cli.ColonyError(f"set {cli.SESSION_ENV} to this session's name, such as lead")
    session = wait.session(config, args, me)
    name = wait.lead_name(config, args) if me == cli.LEAD else me
    if not is_public(config) and not config.get("messages", {}).get("private_repo"):
        print(f"{config['project']['repo']} is private, so private lines come on its board: `{cli.NAME} wait` shows them")
        return 0
    repo, number = board(config)
    out = wait.gh("api", "--paginate", f"repos/{repo}/issues/{number}/comments?per_page=100", "--jq", ".[]")
    comments = [json.loads(line) for line in out.splitlines() if line.strip()]
    logins = frozenset(str(login).lower() for login in config.get("people", {}).get("logins", []))
    path = wait.state_path(config["project"]["name"], f"{wait.state_name(me)}-private")
    seen = wait.read_json(path, 0)
    seen = seen if isinstance(seen, int) else 0
    lines = [line for comment in comments if int(comment.get("id") or 0) > seen and presence.by_team(comment, logins)
             for line, _ in wait.taken(comment.get("body") or "", session, "")]
    print("\n".join(lines) if lines else f"No new private line for {name}.")
    wait.write_json(path, max([seen, *(int(comment.get("id") or 0) for comment in comments)]))
    return 0
