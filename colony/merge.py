"""colony merge <branch>: land a branch on the base after a passing fast check, or open its pull request.

Only in hack mode, and only when `[gate] merge_after_fast_check = true`, it fetches, merges the branch into the
base in Colony's own merge worktree, `<worktrees>/<project>-merge`, runs the fast check there on the merged result,
and pushes the base only when the check passes. Otherwise it pushes the branch and opens a pull request into the
base: in another mode, when merging is off, or when the merge conflicts, the check fails, or the base moved on under
the check twice in a row. It never force-pushes, and one merge runs at a time on a computer.

It exits 0 when the branch is on the base, or when the mode or the config sends it to a pull request, and 1 when it
opened a pull request because the merge or the check failed.
"""
from __future__ import annotations

import fcntl
import json
import re
import shlex
import subprocess
from pathlib import Path

from colony import batch, cli, transport, wait

TRIES = 2  # merges in a row before a base that keeps moving under the check sends the branch to a pull request
REJECTED = re.compile(r"\[rejected\]|non-fast-forward|fetch first", re.I)


def _git(cwd, *args: str, check: bool = True) -> str:
    """One git command's stripped output (batch._git), with a failure as a one-line ColonyError."""
    try:
        return batch._git(cwd, *args, check=check)
    except batch.Stop as e:
        raise cli.ColonyError(str(e)) from None


def _exists(root: Path, ref: str) -> bool:
    """Whether the ref names a commit."""
    return batch._run(["git", "rev-parse", "--verify", "--quiet", ref], root, check=False).returncode == 0


def _behind(root: Path, ref: str, other: str) -> bool:
    """Whether `ref` is `other` or an ancestor of it."""
    return batch._run(["git", "merge-base", "--is-ancestor", ref, other], root, check=False).returncode == 0


def branch_ref(root: Path, branch: str) -> str:
    """The commit to land: the local branch, unless origin's copy is ahead of it or the only one."""
    local, remote = f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"
    has_local, has_remote = _exists(root, local), _exists(root, remote)
    if not has_local and not has_remote:
        raise cli.ColonyError(f"{branch} is neither a local branch nor on origin")
    return remote if has_remote and (not has_local or _behind(root, local, remote)) else local


def worktree(config: dict) -> Path:
    """Colony's merge worktree, `<worktrees>/<project>-merge`, kept between merges so installs stay warm."""
    project = config["project"]
    return Path(project["worktrees"]).expanduser() / f"{project['name']}-merge"


def ready(root: Path, wt: Path, base: str) -> None:
    """Put the merge worktree at origin/<base>, clean, making it the first time. A folder there that is not one of
    this repo's worktrees is never touched."""
    if wt.exists():
        listing = _git(root, "worktree", "list", "--porcelain").splitlines()
        if wt.resolve() not in {Path(line[len("worktree "):]).resolve() for line in listing
                                if line.startswith("worktree ")}:
            raise cli.ColonyError(f"{wt} is in the way: it is not this repo's merge worktree, so move it")
        _git(wt, "merge", "--abort", check=False)
        _git(wt, "checkout", "--quiet", "--detach", "--force", f"origin/{base}")
        _git(wt, "clean", "-fdq")
    else:
        _git(root, "worktree", "prune")
        _git(root, "worktree", "add", "--detach", str(wt), f"origin/{base}")


def _shell(cmd: str, cwd: Path, env: dict) -> tuple[bool, str]:
    """Run one of the config's command strings, and say whether it passed, with its last line of output. A last
    line that looks like a secret stays out."""
    run = subprocess.run(cmd, shell=True, cwd=cwd, env=env, capture_output=True, text=True)
    output = f"{run.stdout}\n{run.stderr}"
    last = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), "no output")[:200]
    if transport.holds_secret(last):
        last = "its last line looked like a secret, so it stays out"
    return run.returncode == 0, last


def land(config: dict, root: Path, wt: Path, branch: str) -> tuple[bool, str]:
    """Merge the branch into origin/<base> in the merge worktree, run the install and the fast check there, and push
    the base when the check passes. Return whether the branch is on the base, and what happened."""
    project = config["project"]
    base, env = project["base"], batch.checks_env(config, root)
    for attempt in range(TRIES):
        if attempt:
            _git(root, "fetch", "origin")
        ref = branch_ref(root, branch)
        ready(root, wt, base)
        before = _git(wt, "rev-parse", "HEAD")
        if batch._run(["git", "merge", "--no-ff", "--no-edit", ref], wt, check=False).returncode:
            paths = _git(wt, "diff", "--name-only", "--diff-filter=U", check=False).split()
            _git(wt, "merge", "--abort", check=False)
            return False, f"merging it into {base} conflicts in {', '.join(paths) or 'the merge'}"
        head = _git(wt, "rev-parse", "HEAD")
        if head == before:
            return True, f"{branch} is already in {base}: nothing to push"
        if project.get("install"):
            installed, last = _shell(project["install"], wt, env)
            if not installed:
                return False, f"the install failed in the merge worktree: {last}"
        passed, last = _shell(batch.fast_check(project), wt, env)
        if not passed:
            return False, f"the fast check failed on the merged result: {last}"
        push = batch._run(["git", "push", "origin", f"HEAD:refs/heads/{base}"], wt, check=False)
        if push.returncode == 0:
            return True, f"merged {branch} into {base} at {head[:9]}: the fast check passed ({last})"
        if not REJECTED.search(push.stderr):
            raise cli.ColonyError(f"git push to {base} failed: {push.stderr.strip()[-300:]}")
    return False, f"{base} moved on {TRIES} times while the fast check ran"


def open_pr(config: dict, root: Path, branch: str, reason: str) -> str:
    """Push the branch when origin lacks its commits (never forced), and open its pull request into the base, or
    return the one already open."""
    project = config["project"]
    repo, base = project["repo"], project["base"]
    local, remote = f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"
    if _exists(root, local) and not (_exists(root, remote) and _behind(root, local, remote)):
        _git(root, "push", "origin", f"{local}:refs/heads/{branch}")
    found = json.loads(wait.gh("pr", "list", "--repo", repo, "--head", branch, "--base", base, "--state", "open",
                               "--json", "url") or "[]")
    if found:
        return found[0]["url"]
    body = f"`{cli.NAME} merge` didn't land `{branch}` on `{base}`: {reason}.\n\n{batch.trailer(config)}\n"
    return wait.gh("pr", "create", "--repo", repo, "--base", base, "--head", branch, "--title",
                   f"{project['name']}: {branch} into {base}", "--body", body).strip()


def plan(config: dict, branch: str, wt: Path, why: str | None) -> str:
    """What the merge would run, for --dry-run."""
    project = config["project"]
    base = project["base"]
    pr = ["gh", "pr", "create", "--repo", project["repo"], "--base", base, "--head", branch]
    lines = [f"{cli.NAME} merge {branch}: dry run, nothing runs.", "  $ git fetch origin"]
    if why:
        return "\n".join(lines + [f"  it opens a pull request, since {why}:", f"  $ git push origin {branch}",
                                  "  $ " + shlex.join(pr)])
    lines += [f"  in {wt}, at origin/{base}:", "  $ " + shlex.join(["git", "merge", "--no-ff", "--no-edit", branch])]
    if project.get("install"):
        lines.append(f"  $ {project['install']}")
    return "\n".join(lines + [f"  the fast check: $ {batch.fast_check(project)}",
                              f"  when it passes: $ git push origin HEAD:refs/heads/{base}",
                              f"  on a conflict or a failing check: $ git push origin {branch}, then",
                              "  $ " + shlex.join(pr)])


def run(config: dict, args) -> int:
    """`colony merge <branch>`: land the branch on the base after a passing fast check in hack mode, else open its
    pull request (see the module's docstring)."""
    project = config["project"]
    base, branch = project["base"], args.branch.strip()
    if not branch or branch.startswith("-") or branch in (base, f"origin/{base}"):
        raise cli.ColonyError(f"merge needs a branch to land on {base}, other than {base} itself")
    if not wait.hack(config):
        why = f"{cli.mode(config)} mode lands work through pull requests and `{cli.NAME} batch`"
    elif not config["gate"].get("merge_after_fast_check"):
        why = "[gate] merge_after_fast_check is false, so a person merges it"
    else:
        why = None
    root, wt = cli.repo_root(), worktree(config)
    if args.dry_run:
        print(plan(config, branch, wt, why))
        return 0
    _git(root, "fetch", "origin")
    branch_ref(root, branch)
    if why:
        print(f"pull request: {open_pr(config, root, branch, why)} ({why})")
        return 0
    lock = wait.state_path(project["name"], "merge").with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)  # one merge at a time on this computer; closing the file releases it
        landed, what = land(config, root, wt, branch)
    if landed:
        print(what)
        return 0
    print(f"not merged: {what}. Pull request: {open_pr(config, root, branch, what)}")
    return 1
