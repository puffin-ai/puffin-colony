"""colony release: release the base into the release branch, then bring it back and watch the deploy.

`colony release` opens one pull request from `[project] base` into `[project] release`, whose body lists each batch
pull request merged into the base since the last release: each one whose merge commit the release branch lacks. It
never merges that pull request, because a person does.

`colony release --after`, once a person has merged it, merges the release branch back into the base in Colony's
merge worktree (merge.merge_back), then watches the run of `[project] deploy_workflow` on the release branch's head
until it ends, and exits with the run's result.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time

from colony import batch, cli, merge, wait

CLOSES = re.compile(r"\bCloses #(\d+)")  # how a batch pull request names its cards (batch.pr_body)
LISTED = 200  # merged pull requests into the base read at most, newest first
RUN_TRIES, RUN_PAUSE = 30, 10  # looks for the deploy run, RUN_PAUSE seconds apart, before giving up


def branches(config: dict) -> tuple[str, str]:
    """The base and the release branch, `[project] release`, which must be set and differ from the base."""
    project = config["project"]
    base, release = project["base"], (project.get("release") or "").strip()
    if not release:
        raise cli.ColonyError(f"set [project] release in {cli.DIR}/{cli.CONFIG_NAME} to the branch a release goes "
                              f"into, such as main, to use `{cli.NAME} release`")
    if release == base:
        raise cli.ColonyError(f"[project] release is {release}, the base itself: name the branch the base releases "
                              "into")
    return base, release


def unreleased(config: dict, root, release: str) -> list[dict]:
    """The batch pull requests merged into the base whose merge commit origin/<release> lacks, oldest first, each
    with its number, title, url, author login and cards."""
    project = config["project"]
    found = json.loads(wait.gh("pr", "list", "--repo", project["repo"], "--base", project["base"], "--state",
                               "merged", "--limit", str(LISTED), "--json",
                               "number,title,url,headRefName,author,mergeCommit,body") or "[]")
    batches = []
    for pr in found:
        oid = (pr.get("mergeCommit") or {}).get("oid", "")
        if not pr.get("headRefName", "").startswith(f"{project['name']}/batch-") or not oid:
            continue
        if merge._exists(root, oid) and merge._behind(root, oid, f"origin/{release}"):
            continue
        batches.append({"number": pr["number"], "title": pr.get("title", ""), "url": pr.get("url", ""),
                        "author": (pr.get("author") or {}).get("login", ""),
                        "cards": [int(n) for n in CLOSES.findall(pr.get("body") or "")]})
    return sorted(batches, key=lambda pr: pr["number"])


def body(config: dict, base: str, release: str, batches: list[dict]) -> str:
    """The release pull request's body: the batches it carries, and what happens after a person merges it."""
    none = f"- No batch pull request: the commits came to {base} another way."
    listed = [f"- #{pr['number']} {pr['title']}" for pr in batches] or [none]
    return "\n".join(["## Batches in this release", *listed, "",
                      f"A person merges this pull request. Then `{cli.NAME} release --after` merges {release} back "
                      f"into {base} and watches the deploy.", "", batch.trailer(config), ""])


def open_release(config: dict, root, base: str, release: str) -> str:
    """Open the release pull request from the base into the release branch, or return the one already open; None
    when the release branch already holds the base."""
    repo = config["project"]["repo"]
    found = json.loads(wait.gh("pr", "list", "--repo", repo, "--head", base, "--base", release, "--state", "open",
                               "--json", "url") or "[]")
    if found:
        return found[0]["url"]
    if merge._behind(root, f"origin/{base}", f"origin/{release}"):
        return None
    batches = unreleased(config, root, release)
    title = f"{config['project']['name']}: release {base} into {release}"
    if batches:
        title += " (" + ", ".join(f"#{pr['number']}" for pr in batches) + ")"
    return wait.gh("pr", "create", "--repo", repo, "--base", release, "--head", base, "--title", title, "--body",
                   body(config, base, release, batches)).strip()


def released(config: dict, base: str, release: str) -> None:
    """Refuse --after while the release pull request is still open, or when none was ever merged."""
    repo = config["project"]["repo"]

    def listed(state: str) -> list:
        return json.loads(wait.gh("pr", "list", "--repo", repo, "--head", base, "--base", release, "--state", state,
                                  "--limit", "1", "--json", "url") or "[]")

    still_open = listed("open")
    if still_open:
        raise cli.ColonyError(f"the release pull request {still_open[0]['url']} is still open: a person merges it "
                              "first")
    if not listed("merged"):
        raise cli.ColonyError(f"no pull request from {base} into {release} was merged: run `{cli.NAME} release` "
                              "first")


def deploy_run(repo: str, workflow: str, release: str, sha: str, sleep=time.sleep) -> dict | None:
    """The run of the deploy workflow on the release branch's head commit, waiting for it to start."""
    for attempt in range(RUN_TRIES):
        if attempt:
            sleep(RUN_PAUSE)
        runs = json.loads(wait.gh("run", "list", "--repo", repo, "--workflow", workflow, "--branch", release,
                                  "--limit", "10", "--json", "databaseId,headSha,status,conclusion,url") or "[]")
        run = next((r for r in runs if r.get("headSha") == sha), None)
        if run:
            return run
    return None


def watch(config: dict, root, release: str, sleep=time.sleep) -> int:
    """Watch the deploy workflow's run on the release branch's head until it ends, and return 0 when it succeeded."""
    project = config["project"]
    workflow = (project.get("deploy_workflow") or "").strip()
    if not workflow:
        print("No [project] deploy_workflow is set, so there is no deploy to watch.")
        return 0
    sha = merge._git(root, "rev-parse", f"origin/{release}")
    run = deploy_run(project["repo"], workflow, release, sha, sleep)
    if run is None:
        print(f"No run of {workflow} started on {release} at {sha[:9]} within {RUN_TRIES * RUN_PAUSE // 60} "
              "minutes: start it, then run `gh run watch`.")
        return 1
    print(f"Watching {workflow} on {release} at {sha[:9]}: {run.get('url', '')}")
    if run.get("status") != "completed":
        subprocess.run(["gh", "run", "watch", str(run["databaseId"]), "--repo", project["repo"], "--exit-status"],
                       capture_output=True, check=False)
        run = json.loads(wait.gh("run", "view", str(run["databaseId"]), "--repo", project["repo"], "--json",
                                 "status,conclusion,url"))
    conclusion = run.get("conclusion") or "unknown"
    print(f"{workflow} ended: {conclusion}.")
    return 0 if conclusion == "success" else 1


def plan(config: dict, base: str, release: str, after: bool) -> str:
    """What the release would run, for --dry-run."""
    repo = config["project"]["repo"]
    if not after:
        pr = ["gh", "pr", "create", "--repo", repo, "--base", release, "--head", base]
        return "\n".join([f"{cli.NAME} release: dry run, nothing runs.", "  $ git fetch origin",
                          f"  list the batch pull requests merged into {base} whose merge commit {release} lacks",
                          "  $ " + shlex.join(pr)])
    workflow = config["project"].get("deploy_workflow") or ""
    return "\n".join([f"{cli.NAME} release --after: dry run, nothing runs.", "  $ git fetch origin",
                      f"  in {merge.worktree(config)}, at origin/{base}:",
                      "  $ " + shlex.join(["git", "merge", "--no-ff", "--no-edit", f"origin/{release}"]),
                      f"  $ git push origin HEAD:refs/heads/{base}",
                      f"  then watch {workflow} on {release}" if workflow else "  no deploy_workflow to watch"])


def run(config: dict, args) -> int:
    """`colony release [--after]`: open the release pull request, or after a person merged it, merge the release
    branch back into the base and watch the deploy (see the module's docstring)."""
    if os.environ.get(cli.SESSION_ENV, "").lower() not in ("", cli.LEAD):
        raise cli.ColonyError("release is for the lead, never a helper")
    base, release = branches(config)
    if args.dry_run:
        print(plan(config, base, release, args.after))
        return 0
    root = cli.repo_root()
    merge._git(root, "fetch", "origin")
    if not merge._exists(root, f"origin/{release}"):
        raise cli.ColonyError(f"origin has no branch {release}")
    if not args.after:
        url = open_release(config, root, base, release)
        print(f"release pull request: {url}" if url else f"{release} already holds {base}: nothing to release")
        return 0
    released(config, base, release)
    print(merge.merge_back(config, root, f"origin/{release}"))
    merge._git(root, "fetch", "origin")
    return watch(config, root, release)


def add_commands(sub) -> None:
    """cli.py's route to this module: the `release` command."""
    p = sub.add_parser("release", help="the lead: open the pull request from the base into [project] release, or "
                                       "--after a person merged it, merge it back and watch the deploy")
    p.add_argument("--after", action="store_true",
                   help="after a person merged the release: merge the release branch back into the base, then watch "
                        "[project] deploy_workflow until it ends")
    p.add_argument("--dry-run", action="store_true", help="print the plan and run nothing")
    p.set_defaults(run=run)
