"""colony merge <branch>: land a branch on the base after a passing fast check, or open its pull request.

Only in hack mode, and only when `[gate] merge_after_fast_check = true`, it fetches, merges the branch into the
base in Colony's own merge worktree, `<worktrees>/<project>-merge`, runs the fast check there on the merged result,
and pushes the base only when the check passes. Otherwise it pushes the branch and opens a pull request into the
base: in another mode, when merging is off, or when the merge conflicts, the check fails twice, or the base moved on
under the check twice in a row. A failed check runs once more, so a flaky test never blocks a good branch; each run's
whole output stays in ~/.colony/<project>/merge-logs/, and the message names the summary line and the failing tests.
When the check fails twice, the base runs alone, unless Colony landed it green itself: a base that fails on its own
gets no pull request, since the branch is not to blame, and one `@all urgent:` line on the board for that commit. It
never force-pushes, and one merge runs at a time on a computer. When it lands the branch,
it posts the last good build on the board, `[merged] <branch> → <base> <short sha>, fast check passed`, so every agent
knows which commit to go back to.

It exits 0 when the branch is on the base, or when the mode or the config sends it to a pull request, and 1 when it
opened a pull request because the merge or the check failed.

colony sync <branch>: merge origin/<base> into the branch, in the worktree that has it checked out, else in the
merge worktree. A conflict only in `[project] generated` paths takes the base's side and runs `[project] regen`;
any other conflict stops the merge and leaves the branch as it was. It pushes nothing.
"""
from __future__ import annotations

import contextlib
import json
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from colony import batch, cli, portable, transport, wait

TRIES = 2  # merges in a row before a base that keeps moving under the check sends the branch to a pull request
REJECTED = re.compile(r"\[rejected\]|non-fast-forward|fetch first", re.I)
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# A test runner's summary, such as `Tests 1464 passed (1464)`, `=== 1 failed, 821 passed in 3s ===` or
# `Tests: 1 failed, 4 passed`, and the lines that name a failing test, such as `FAIL src/a.test.ts > reads a`,
# pytest's `FAILED tests/test_a.py::test_b`, jest's `● reads a` or TAP's `not ok 3 reads a`.
SUMMARY = re.compile(r"\b\d+\s+(?:passed|failed|failing|passing|errors?)\b", re.I)
FAILING = re.compile(r"^(?:FAIL(?:ED)?|✗|×|✕|●|not ok)\s+\S")
NAMED = 5  # the failing tests a message names
LOGS_KEPT = 50
MERGES_READ = 500  # the merge commits on the base read to tell which worktrees' branches landed


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


def readable(output: str) -> list[str]:
    """The output's lines without colour codes, blank lines, or rule lines such as ⎯⎯⎯⎯ or ====, each squeezed."""
    lines = (" ".join(ANSI.sub("", raw).split()) for raw in output.splitlines())
    return [line for line in lines if any(ch.isalnum() for ch in line)]


def safe(line: str, what: str = "line") -> str:
    """The line, or a note in its place when it looks like a secret."""
    return f"its {what} looked like a secret, so it stays out" if transport.holds_secret(line) else line


def _shell(cmd: str, cwd: Path, env: dict) -> tuple[bool, str]:
    """Run one of the config's command strings, and say whether it passed, with its last readable line of output. A
    last line that looks like a secret stays out."""
    command, shell, env = portable.shell(cmd, env)
    run = subprocess.run(command, shell=shell, cwd=cwd, env=env, capture_output=True, text=True)
    lines = readable(f"{run.stdout}\n{run.stderr}")
    return run.returncode == 0, safe((lines[-1] if lines else "no output")[:200], "last line")


@dataclass
class Check:
    """One run of the fast check: whether it passed, the test runner's summary line, the failing tests it named,
    and the file that holds its whole output."""
    passed: bool
    summary: str
    failing: list[str]
    log: Path

    def failed(self, where: str) -> str:
        named = f"; failing: {', '.join(self.failing)}" if self.failing else ""
        return f"the fast check failed {where}: {self.summary}{named}"


def log_path(config: dict, name: str, run: str) -> Path:
    """Where one run's whole output goes: ~/.colony/<project>/merge-logs/<name>-<time>-<run>.log, the newest
    LOGS_KEPT of them kept."""
    folder = wait.state_path(config["project"]["name"], "merge-logs").with_suffix("")
    folder.mkdir(parents=True, exist_ok=True)
    for old in sorted(folder.glob("*.log"), key=lambda path: path.stat().st_mtime)[:-LOGS_KEPT]:
        old.unlink(missing_ok=True)
    return folder / f"{re.sub(r'[^\w.-]', '-', name)}-{time.strftime('%Y%m%d-%H%M%S')}-{run}.log"


def run_check(command: str, cwd: Path, env: dict, log: Path) -> Check:
    """Run the fast check, keep its whole output in `log`, and read its summary line and its failing tests."""
    shell_command, shell, env = portable.shell(command, env)
    run = subprocess.run(shell_command, shell=shell, cwd=cwd, env=env, capture_output=True, text=True)
    output = f"{run.stdout}\n{run.stderr}"
    log.write_text(output)
    lines = readable(output)
    summaries = [line for line in lines if SUMMARY.search(line)]
    summary = (summaries[-1] if summaries else lines[-1] if lines else "no output")[:200]
    failing = list(dict.fromkeys(line[:120] for line in lines if FAILING.match(line) and not transport.holds_secret(line)))
    return Check(run.returncode == 0, safe(summary, "summary line"), failing[:NAMED], log)


def checked_bases(config: dict) -> tuple[Path, dict]:
    """The file that remembers the base commit Colony last landed green, and the red ones it warned the team of."""
    path = wait.state_path(config["project"]["name"], "merge-checks")
    found = wait.read_json(path, {})
    return path, found if isinstance(found, dict) else {}


def remember_green(config: dict, head: str) -> None:
    """Remember the commit Colony just pushed to the base: it passed the fast check, so a later merge whose check
    fails needs no run on the base to know the base is green."""
    path, found = checked_bases(config)
    found["green"] = head
    wait.write_json(path, found)


def base_fails(config: dict, root: Path, wt: Path, base: str, sha: str, env: dict, command: str) -> Check | None:
    """The fast check's run on origin/<base> alone, at `sha`, when it fails there too, else None. A base Colony
    landed green itself, or one whose install fails here, isn't run."""
    path, found = checked_bases(config)
    if found.get("green") == sha:
        return None
    ready(root, wt, base)
    if config["project"].get("install") and not _shell(config["project"]["install"], wt, env)[0]:
        return None
    result = run_check(command, wt, env, log_path(config, base, "base"))
    if result.passed:
        remember_green(config, sha)
        return None
    return result


def warn_red_base(config: dict, base: str, sha: str, red: Check) -> None:
    """Post once per red base commit, for every agent: `@all urgent: <base> <sha> fails the fast check on its own`."""
    path, found = checked_bases(config)
    warned = [s for s in found.get("red", []) if isinstance(s, str)]
    if sha in warned:
        return
    named = f": {', '.join(red.failing[:2])}" if red.failing else ""
    line = (f"@all urgent: {base} {sha[:7]} fails the fast check on its own ({red.summary}){named}; every merge "
            "waits until a fix lands")
    try:
        transport.send(config, f"@{wait.ALL}", line)
    except cli.ColonyError as e:
        print(f"{cli.NAME} merge: the board didn't get the warning that {base} is red: {e}", file=sys.stderr)
        return
    found["red"] = [*warned, sha][-20:]
    wait.write_json(path, found)


@dataclass
class Landed:
    """What a merge did: whether the branch is on the base, what happened, the commit it pushed or "", the log to
    read, and whether a pull request should follow a failure."""
    landed: bool
    what: str
    head: str = ""
    log: Path | None = None
    pr: bool = True


def land(config: dict, root: Path, wt: Path, branch: str) -> Landed:
    """Merge the branch into origin/<base> in the merge worktree, run the install and the fast check there, and push
    the base when the check passes. A failed check runs once more, so a flaky test never blocks a good branch; when
    it fails again, the base runs alone, and a base that fails on its own gets no pull request, since the branch is
    not to blame."""
    project = config["project"]
    base, env = project["base"], batch.checks_env(config, root)
    command = batch.every_area(config, batch.fast_check(project))
    for attempt in range(TRIES):
        if attempt:
            _git(root, "fetch", "origin")
        ref = branch_ref(root, branch)
        ready(root, wt, base)
        before = _git(wt, "rev-parse", "HEAD")
        message = f"Merge {branch} into {base}"
        if batch._run(["git", "merge", "--no-ff", "--no-edit", "-m", message, ref], wt, check=False).returncode:
            paths = _git(wt, "diff", "--name-only", "--diff-filter=U", check=False).split()
            _git(wt, "merge", "--abort", check=False)
            return Landed(False, f"merging it into {base} conflicts in {', '.join(paths) or 'the merge'}")
        head = _git(wt, "rev-parse", "HEAD")
        if head == before:
            return Landed(True, f"{branch} is already in {base}: nothing to push")
        if project.get("install"):
            installed, last = _shell(project["install"], wt, env)
            if not installed:
                return Landed(False, f"the install failed in the merge worktree: {last}")
        first = run_check(command, wt, env, log_path(config, branch, "check"))
        passed, note = f"({first.summary})", ""
        if not first.passed:
            second = run_check(command, wt, env, log_path(config, branch, "again"))
            if not second.passed:
                red = base_fails(config, root, wt, base, before, env, command)
                if red is not None:
                    warn_red_base(config, base, before, red)
                    return Landed(False, f"{base} itself fails the fast check at {before[:9]}, so {branch} is not "
                                         f"to blame: {red.failed('on its own')}. Run `{cli.NAME} merge {branch}` "
                                         f"again once a fix lands", log=red.log, pr=False)
                return Landed(False, second.failed("twice on the merged result"), log=second.log)
            failing = ", ".join(first.failing) or first.summary
            passed = f"on its second run ({second.summary})"
            note = f"; its first run failed ({failing}), so a test there is flaky: its log is {first.log}"
        push = batch._run(["git", "push", "origin", f"HEAD:refs/heads/{base}"], wt, check=False)
        if push.returncode == 0:
            remember_green(config, head)
            return Landed(True, f"merged {branch} into {base} at {head[:9]}: the fast check passed {passed}{note}",
                          head)
        if not REJECTED.search(push.stderr):
            raise cli.ColonyError(f"git push to {base} failed: {push.stderr.strip()[-300:]}")
    return Landed(False, f"{base} moved on {TRIES} times while the fast check ran")


def post_landed(config: dict, branch: str, head: str) -> None:
    """Post the last good build on the board: `[merged] <branch> → <base> <short sha>, fast check passed`. It wakes
    no agent, and a post that fails says so on stderr alone, since the branch has landed."""
    line = f"[merged] {branch} → {config['project']['base']} {head[:7]}, fast check passed"
    try:
        print(f"posted on the board #{transport.send(config, '', line)}: {line}")
    except cli.ColonyError as e:
        print(f"{cli.NAME} merge: the branch landed, and the board didn't get the line: {e}", file=sys.stderr)


def drop_merged_worktrees(config: dict, root: Path) -> None:
    """After a landing, remove each clean worktree whose branch is already in origin/<base>: helpers make one per
    task, so they pile up otherwise. Never the main checkout, the merge worktree, a locked
    or dirty one, or the one this command runs in, whose session still works there; the next landing takes it."""
    from colony import tidy

    base, here = config["project"]["base"], Path.cwd().resolve()
    keep = {root.resolve(), worktree(config).resolve()}
    # A branch is merged when a merge commit on the base took its tip as a second parent. A tip merely on the base,
    # such as a task's branch just cut from it with no commit yet, is work that has only begun.
    merges = _git(root, "log", "--merges", "--format=%P", f"-n{MERGES_READ}", f"origin/{base}", check=False)
    taken = {parent for line in merges.splitlines() for parent in line.split()[1:]}
    for tree in tidy.worktrees(root):
        path = Path(tree["path"]).resolve()
        if tree["main"] or tree["bare"] or tree["locked"] or not tree["branch"] or path in keep:
            continue
        if here == path or path in here.parents:
            continue
        tip = _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{tree['branch']}", check=False)
        if tip not in taken or tidy.dirt(tree["path"]):
            continue
        try:
            tidy.git_remove(root, tree["path"])
        except cli.ColonyError as e:
            print(f"{cli.NAME} merge: kept {tree['path']}: {e}", file=sys.stderr)
            continue
        print(f"removed the worktree {tree['path']}: {tree['branch']} is in {base}, and it was clean")


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


@contextlib.contextmanager
def one_at_a_time(config: dict):
    """Hold this computer's merge lock, so one merge or release runs at a time; closing the file releases it."""
    lock = wait.state_path(config["project"]["name"], "merge").with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as held, portable.lock(held):
        yield


def merge_back(config: dict, root: Path, ref: str) -> str:
    """`colony release --after`'s merge: merge `ref`, the released branch, into origin/<base> in the merge worktree
    and push the base, never forced. A conflict, or a base that moved on, stops it with the base untouched."""
    base = config["project"]["base"]
    with one_at_a_time(config):
        wt = worktree(config)
        ready(root, wt, base)
        if _behind(root, ref, f"origin/{base}"):
            return f"{base} already holds {ref}: nothing to merge back"
        if batch._run(["git", "merge", "--no-ff", "--no-edit", ref], wt, check=False).returncode:
            paths = _git(wt, "diff", "--name-only", "--diff-filter=U", check=False).split()
            _git(wt, "merge", "--abort", check=False)
            raise cli.ColonyError(f"merging {ref} back into {base} conflicts in {', '.join(paths) or 'the merge'}: "
                                  "merge it by hand")
        head = _git(wt, "rev-parse", "HEAD")
        push = batch._run(["git", "push", "origin", f"HEAD:refs/heads/{base}"], wt, check=False)
        if push.returncode:
            raise cli.ColonyError(f"git push to {base} failed: {push.stderr.strip()[-300:]}: run "
                                  f"`{cli.NAME} release --after` again")
    return f"merged {ref} back into {base} at {head[:9]}"


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
    return "\n".join(lines + [f"  the fast check: $ {batch.every_area(config, batch.fast_check(project))}",
                              f"  when it passes: $ git push origin HEAD:refs/heads/{base}, and it posts "
                              f"`[merged] {branch} → {base} <short sha>, fast check passed` on the board",
                              f"  on a conflict or a failing check: $ git push origin {branch}, then",
                              "  $ " + shlex.join(pr)])


def checked_out_in(root: Path, branch: str) -> Path | None:
    """The worktree that has the branch checked out, or None."""
    current = None
    for line in _git(root, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            current = Path(line[len("worktree "):])
        elif line == f"branch refs/heads/{branch}":
            return current
    return None


def sync(config: dict, args) -> int:
    """`colony sync <branch>`: merge origin/<base> into the branch (see the module's docstring). Return 0 when the
    branch holds the base, and 1 when a conflict outside the generated paths stopped the merge."""
    project = config["project"]
    base, branch = project["base"], args.branch.strip()
    if not branch or branch.startswith("-") or branch in (base, f"origin/{base}"):
        raise cli.ColonyError(f"sync needs a branch to bring up to {base}, other than {base} itself")
    root = cli.repo_root()
    _git(root, "fetch", "origin")
    wt = checked_out_in(root, branch)
    if wt is None:
        if not _exists(root, f"refs/heads/{branch}"):
            branch_ref(root, branch)  # names a branch on neither side
            _git(root, "branch", branch, f"origin/{branch}")
        wt = worktree(config)
        ready(root, wt, base)
        _git(wt, "checkout", "--quiet", branch)
    elif _git(wt, "status", "--porcelain", "--untracked-files=no"):  # untracked files, such as reports, never block it
        raise cli.ColonyError(f"{branch} has uncommitted changes in {wt}: commit them first")
    before = _git(wt, "rev-parse", "HEAD")
    took = ""
    if batch._run(["git", "merge", "--no-edit", f"origin/{base}"], wt, check=False).returncode:
        paths = _git(wt, "diff", "--name-only", "--diff-filter=U", check=False).split()
        if batch.classify_conflict(paths, project.get("generated", [])) != "generated":
            _git(wt, "merge", "--abort", check=False)
            print(f"not synced: merging origin/{base} into {branch} conflicts outside the generated paths, in "
                  f"{', '.join(paths) or 'the merge'}; {branch} is as it was")
            return 1
        _git(wt, "checkout", "--theirs", "--", *paths)
        if project.get("regen"):
            built, last = _shell(project["regen"], wt, batch.checks_env(config, root))
            if not built:
                _git(wt, "merge", "--abort", check=False)
                print(f"not synced: regen failed after a conflict in {', '.join(paths)}: {last}; {branch} is as it was")
                return 1
        # The tracked files, and what regen writes under the generated paths, never an untracked report.
        _git(wt, "add", "-u")
        _git(wt, "add", "-A", "--", *[f":(glob){glob}" for glob in project.get("generated", [])])
        _git(wt, "commit", "--no-edit")
        took = f", taking origin/{base}'s side of {', '.join(paths)}" + (" and running regen" if project.get("regen")
                                                                        else "")
    head = _git(wt, "rev-parse", "HEAD")
    if head == before:
        print(f"{branch} already holds origin/{base}: nothing to merge")
    else:
        print(f"merged origin/{base} into {branch} at {head[:9]} in {wt}{took}; push it with `git push origin {branch}`")
    return 0


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
    with one_at_a_time(config):
        result = land(config, root, wt, branch)
    if result.landed:
        print(result.what)
        if result.head:
            post_landed(config, branch, result.head)
            _git(root, "fetch", "origin", check=False)
            drop_merged_worktrees(config, root)
        return 0
    log = f"; full log: {result.log}" if result.log else ""
    if not result.pr:
        print(f"not merged: {result.what}{log}.")
        return 1
    # The pull request gets the reason alone: a path on this computer means nothing on GitHub.
    print(f"not merged: {result.what}{log}. Pull request: {open_pr(config, root, branch, result.what)}")
    return 1
