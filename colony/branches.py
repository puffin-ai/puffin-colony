"""The project's long-lived branches, and keeping them in step after each release.

Colony names no branch itself. It reads three from the config, each with a default (names):

- the base, `[project] base`: where pull requests go;
- the integration branch, `[project] integration`, else the base: where the team's work gathers, the branch a
  release is cut from and comes back into;
- the release branch, `[project] release`, else origin's default branch when that differs from the integration
  branch.

`[release] long_lived` names any other long-lived branch each release goes into too, such as a staging branch.

`colony branches` shows how far each long-lived branch is from the release branch, and the commits that sit on one
branch alone, which conflict at release time. `colony branches --sync` opens a pull request that brings the release
branch into each branch that lacks it (sync_pr). Colony never merges into a long-lived branch here, and never
pushes to one: it pushes a branch of its own, `<project>/sync-<from>-into-<to>-<time>`, and a person merges the
pull request.
"""
from __future__ import annotations

import json
import re
import shlex
import time
from pathlib import Path
from typing import NamedTuple

from colony import batch, cli, merge, wait


class Names(NamedTuple):
    """The project's long-lived branches: the base, the integration branch, the release branch ("" when the project
    has none) and the other long-lived branches each release goes into."""
    base: str
    integration: str
    release: str
    long_lived: tuple[str, ...]


def default_branch(root: Path) -> str:
    """Origin's default branch, as this clone knows it (origin/HEAD), else as origin says; "" when neither says."""
    known = batch._git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False)
    if known.startswith("origin/"):
        return known.removeprefix("origin/")
    said = batch._git(root, "ls-remote", "--symref", "origin", "HEAD", check=False)
    found = re.search(r"^ref:\s+refs/heads/(\S+)\s+HEAD$", said, re.M)
    return found[1] if found else ""


def long_lived(config: dict) -> tuple[str, ...]:
    """`[release] long_lived`: the other long-lived branches each release goes into, such as a staging branch."""
    found = (config.get("release") or {}).get("long_lived") or []
    if not isinstance(found, list) or not all(isinstance(name, str) and name.strip() for name in found):
        raise cli.ColonyError('[release] long_lived is a list of branch names, such as ["staging"]')
    return tuple(dict.fromkeys(name.strip() for name in found))


def protected(config: dict, root: Path | None = None) -> list[str]:
    """The branch names and patterns no agent may push to, as the push guard reads them (wait_guard's
    protected_branches): the base, [safety] protect, and the project's other long-lived branches, [project]
    integration and release and [release] long_lived; with `root`, origin's default branch too."""
    project = config["project"]
    protect = [b for b in (config.get("safety") or {}).get("protect", []) if isinstance(b, str)]
    named = [project["base"], *protect, project.get("integration"), project.get("release"), *long_lived(config),
             default_branch(root) if root is not None else ""]
    return list(dict.fromkeys(b.strip() for b in named if isinstance(b, str) and b.strip()))


def names(config: dict, root: Path | None = None) -> Names:
    """The project's long-lived branches. The release branch is `[project] release`, else origin's default branch
    when `root` is given and that differs from the integration branch, else ""."""
    project = config["project"]
    base = project["base"]
    integration = (project.get("integration") or "").strip() or base
    release = (project.get("release") or "").strip()
    if not release and root is not None:
        found = default_branch(root)
        release = found if found and found != integration else ""
    return Names(base, integration, release, tuple(b for b in long_lived(config) if b not in (integration, release)))


def release_names(config: dict, root: Path | None = None) -> Names:
    """names(), refusing a project with no release branch, or one whose release branch is its integration branch."""
    found = names(config, root)
    if not found.release:
        raise cli.ColonyError(f"set [project] release in {cli.DIR}/{cli.CONFIG_NAME} to the branch a release goes "
                              f"into: origin's default branch is {found.integration}, the integration branch itself, "
                              "so there is no other branch to release into")
    if found.release == found.integration:
        raise cli.ColonyError(f"[project] release is {found.release}, the integration branch itself: name the branch "
                              "the integration branch releases into")
    return found


def count(root: Path, *revs: str) -> int:
    """How many commits `git rev-list` counts for the revisions, such as origin/a..origin/b; 0 when git can't."""
    out = batch._git(root, "rev-list", "--count", *revs, check=False)
    return int(out) if out.isdigit() else 0


def slug(branch: str) -> str:
    """A branch name made safe for the middle of another branch's name: dev for dev, lead-x for lead/x."""
    return re.sub(r"[^\w.-]+", "-", branch).strip("-.") or "branch"


def sync_prefix(config: dict, source: str, target: str) -> str:
    """The start of every branch that brings `source` into `target`."""
    return f"{config['project']['name']}/sync-{slug(source)}-into-{slug(target)}"


def open_sync(config: dict, source: str, target: str) -> dict | None:
    """The open pull request that brings `source` into `target`, or None."""
    found = json.loads(wait.gh("pr", "list", "--repo", config["project"]["repo"], "--base", target, "--state", "open",
                               "--json", "url,headRefName,isCrossRepository", "--limit", "100") or "[]")
    prefix = sync_prefix(config, source, target)
    # A fork's pull request may take a sync branch's name: only a branch on the repo itself counts.
    return next((pr for pr in found if not pr.get("isCrossRepository")
                 and str(pr.get("headRefName", "")).startswith(prefix)), None)


def _merge_in(config: dict, root: Path, wt: Path, source: str, target: str) -> list[str]:
    """Merge origin/<source> into the worktree's commit. A conflict only in `[project] generated` paths takes the
    source's side and runs `[project] regen`. Any other conflict aborts the merge and returns its paths."""
    project = config["project"]
    message = f"Merge {source} into {target}"
    if batch._run(["git", "merge", "--no-ff", "--no-edit", "-m", message, f"origin/{source}"], wt,
                  check=False).returncode == 0:
        return []
    paths = merge._git(wt, "diff", "--name-only", "--diff-filter=U", check=False).split()
    if paths and batch.classify_conflict(paths, project.get("generated", [])) == "generated":
        merge._git(wt, "checkout", "--theirs", "--", *paths)
        if not project.get("regen") or merge._shell(project["regen"], wt, batch.checks_env(config, root))[0]:
            merge._git(wt, "add", "-u")
            merge._git(wt, "add", "-A", "--", *[f":(glob){glob}" for glob in project.get("generated", [])])
            merge._git(wt, "commit", "--no-edit")
            return []
    merge._git(wt, "merge", "--abort", check=False)
    return paths or ["the merge"]


def sync_body(config: dict, source: str, target: str, why: str, conflicts: list[str]) -> str:
    """The sync pull request's description."""
    lines = [f"This brings `{source}` into `{target}`, so the two long-lived branches stay in step. {why}".strip(), ""]
    if conflicts:
        lines += ["## Conflicts", f"Merging `{source}` into `{target}` conflicts in these files, so this branch holds "
                  f"`{source}` alone. Merge `origin/{target}` into it, settle each file, and push it:",
                  *[f"- `{path}`" for path in conflicts], ""]
    lines += ["A person merges this pull request.", "", batch.trailer(config), ""]
    return "\n".join(lines)


def sync_pr(config: dict, root: Path, source: str, target: str, why: str = "") -> str | None:
    """Open a pull request that brings origin/<source> into origin/<target>, or bring the open one up to date; None
    when the target already holds the source. The change is built in Colony's merge worktree, one merge at a time on
    this computer, and pushed to a branch of Colony's own, never to the target and never forced. On a conflict outside
    the generated paths, the branch holds the source alone and the description names each file to settle."""
    if merge._behind(root, f"origin/{source}", f"origin/{target}"):
        return None
    repo = config["project"]["repo"]
    found = open_sync(config, source, target)
    if found and merge._behind(root, f"origin/{source}", f"origin/{found['headRefName']}"):
        return found["url"]
    branch = found["headRefName"] if found else f"{sync_prefix(config, source, target)}-{time.strftime('%Y%m%d-%H%M')}"
    with merge.one_at_a_time(config):
        wt = merge.worktree(config)
        merge.ready(root, wt, target)
        if found:  # bring the open pull request's branch up to the newest source, on top of what it holds
            merge._git(wt, "checkout", "--quiet", "--detach", "--force", f"origin/{branch}")
        conflicts = _merge_in(config, root, wt, source, target)
        if conflicts and not found:
            merge._git(wt, "checkout", "--quiet", "--detach", "--force", f"origin/{source}")
        if conflicts and found:
            raise cli.ColonyError(f"the open pull request {found['url']} lacks the newest {source}, and merging it in "
                                  f"conflicts in {', '.join(conflicts)}: settle them on {branch}")
        head = merge._git(wt, "rev-parse", "HEAD")
        merge._git(wt, "push", "origin", f"{head}:refs/heads/{branch}")
    if found:
        return found["url"]
    return wait.gh("pr", "create", "--repo", repo, "--base", target, "--head", branch, "--title",
                   f"{config['project']['name']}: bring {source} into {target}", "--body",
                   sync_body(config, source, target, why, conflicts)).strip()


def drift(root: Path, found: Names) -> list[str]:
    """One line per long-lived branch: how many of the release branch's commits it lacks, and how many commits sit
    on it alone, in no other long-lived branch, which conflict at release time."""
    lines = []
    every = [b for b in (found.release, found.integration, *found.long_lived) if b]
    for branch in [found.integration, *found.long_lived]:
        if not merge._exists(root, f"origin/{branch}"):
            lines.append(f"{branch}: not on origin")
            continue
        lacks = count(root, f"origin/{branch}..origin/{found.release}")
        others = [f"origin/{b}" for b in every if b != branch and merge._exists(root, f"origin/{b}")]
        alone = count(root, f"origin/{branch}", "--not", *others) if branch != found.integration else 0
        parts = [f"lacks {lacks} commit{'' if lacks == 1 else 's'} of {found.release}" if lacks
                 else f"holds all of {found.release}"]
        if alone:
            parts.append(f"has {alone} commit{'' if alone == 1 else 's'} no other long-lived branch has, which "
                         "conflict at release time")
        lines.append(f"{branch}: " + ", and ".join(parts))
    return lines


def run(config: dict, args) -> int:
    """`colony branches [--sync]`: how far each long-lived branch is from the release branch, and with --sync, a pull
    request that brings the release branch into each one that lacks it."""
    root = cli.repo_root()
    if args.dry_run:
        found = names(config, root)
        print(f"{cli.NAME} branches: dry run, nothing runs.\n  $ git fetch origin\n  release: {found.release or 'none'}"
              f", integration: {found.integration}, long-lived: {', '.join(found.long_lived) or 'none'}")
        if args.sync and found.release:
            for target in (found.integration, *found.long_lived):
                print(f"  open a pull request from {sync_prefix(config, found.release, target)}-<time> into {target} "
                      f"when it lacks {found.release}: $ " + shlex.join(["gh", "pr", "create", "--base", target]))
        return 0
    merge._git(root, "fetch", "origin")
    found = release_names(config, root)
    print(f"release: {found.release}, integration: {found.integration}"
          + (f", long-lived: {', '.join(found.long_lived)}" if found.long_lived else ""))
    for line in drift(root, found):
        print(f"  {line}")
    if not args.sync:
        return 0
    for target in (found.integration, *found.long_lived):
        if not merge._exists(root, f"origin/{target}"):
            continue
        url = sync_pr(config, root, found.release, target, f"`{cli.NAME} branches --sync` opened it.")
        print(f"{target} holds {found.release}: nothing to bring" if url is None else f"{target}: {url}")
    return 0


def register(sub) -> None:
    """The `branches` command."""
    p = sub.add_parser("branches", help="the lead: how far each long-lived branch is from the release branch, and "
                                        "--sync opens a pull request into each that lacks it")
    p.add_argument("--sync", action="store_true", help="open a pull request that brings the release branch into each "
                                                       "long-lived branch that lacks it")
    p.add_argument("--dry-run", action="store_true", help="print the plan and run nothing")
    p.set_defaults(run=run)
