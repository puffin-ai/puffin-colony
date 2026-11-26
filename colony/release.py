"""colony release: draft and open the release pull request, freeze landings while its checks run, release a chosen
part of the work, and afterwards bring the release back and keep the long-lived branches in step.

The branches come from the config (branches.names): a release goes from the integration branch, `[project]
integration` (the base by default), into the release branch, `[project] release` (origin's default branch by
default). Colony never merges a release, and never pushes into either branch here: a person merges each pull request.

`colony release` opens one pull request from the integration branch into the release branch. Its description is
drafted from the merged work (gather, body): every pull request merged into the integration branch whose merge commit
the release branch lacks, and the commits that came another way; each one's migrations and removed or changed tests,
read from its diff and from its own description's sections; and the check results on the release's head, from the
code host and from this computer's ledger of check runs. `--print` prints that description and opens nothing, and
`--refresh` rewrites the open release pull request's description from the work and the checks as they are now.
Before it opens the pull request, it freezes landings on the integration branch for every person's leads
(freeze.py), so no merge forces another long run of the release's checks, and it posts one `@all` line that says so
and names each other lead whose work the release carries.

`colony release --only <n>` (repeatable), or `--lead <name>`, releases a chosen part of the work: it cuts the branch
`<project>/release-<date>` from the release branch, copies each chosen pull request's change onto it, oldest first,
and opens the pull request from that branch. The rest stays on the integration branch for a later release, and
nothing is frozen, since the integration branch isn't what goes out.

`colony release --after`, once a person merged the release, lifts the release's freeze, opens a pull request that
brings the release branch back into the integration branch and into each `[release] long_lived` branch that lacks it
(branches.sync_pr), then watches the run of `[project] deploy_workflow` on the release branch's head until it ends,
and exits with the run's result.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time

from colony import batch, board, branches, cli, freeze, merge, wait

CLOSES = re.compile(r"\bCloses #(\d+)")  # how a batch pull request names its cards (batch.pr_body)
PICKED = re.compile(r"\(cherry picked from commit ([0-9a-f]{40})\)")  # git cherry-pick -x's line
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
LEFT = "Left for a later release"  # the description's heading for the work a partial release leaves out
LISTED_PR = re.compile(r"^\s*[-*]\s*#(\d+)\b")  # a description's `- #<n>` line, which names a pull request
NONE = re.compile(r"^\W*(none|n/?a|no|nothing)\W*$", re.I)
MIGRATION_HEADING = re.compile(r"\bmigrations?\b", re.I)
# A heading on tests that left or changed, such as a batch's "Removed tests", never one such as "Test plan".
TEST_HEADING = re.compile(r"\b(removed|changed|deleted|skipped|weakened|disabled)\b.*\btests?\b|"
                          r"\btests?\b.*\b(removed|changed|deleted|skipped|weakened|disabled)\b", re.I)
LISTED = 200  # merged pull requests into the integration branch read at most, newest first
COMMITS_READ = 100  # commits that came another way read at most
COMMITS_LISTED = 15  # of those, the ones the description names one by one
NOTES_KEPT = 8  # lines of a pull request's own notes the description keeps per kind
BODY_MAX = 60000  # a pull request's description holds at most 65,536 characters
RUN_TRIES, RUN_PAUSE = 30, 10  # looks for the deploy run, RUN_PAUSE seconds apart, before giving up


def settings(config: dict) -> dict:
    """`[release]`, each key with its default."""
    table = config.get("release") or {}
    migrations = table.get("migrations") or []
    if not isinstance(migrations, list) or not all(isinstance(m, str) for m in migrations):
        raise cli.ColonyError('[release] migrations is a list of paths or globs, such as ["db/changes/*"]')
    return {"freeze": bool(table.get("freeze", True)), "migrations": migrations}


def is_migration(config: dict, path: str) -> bool:
    """Whether a changed file is a migration: by the risk list's own sign (cycle.MIGRATION), or `[release]
    migrations`."""
    from colony import cycle

    return bool(cycle.MIGRATION.search(path)) or batch.matches(path, settings(config)["migrations"])


# What a release carries


def merged_prs(config: dict, into: str) -> list[dict]:
    """The pull requests merged into a branch, newest first, LISTED at most."""
    return json.loads(wait.gh("pr", "list", "--repo", config["project"]["repo"], "--base", into, "--state", "merged",
                              "--limit", str(LISTED), "--json",
                              "number,title,url,headRefName,author,mergeCommit,body") or "[]")


def unreleased(config: dict, root, source: str, target: str) -> list[dict]:
    """The pull requests merged into `source` whose merge commit origin/<target> lacks, oldest first, each with its
    number, title, url, author login, head branch, merge commit, cards, description, and whether a batch made it."""
    found = []
    for pr in merged_prs(config, source):
        oid = (pr.get("mergeCommit") or {}).get("oid", "")
        if not oid or (merge._exists(root, oid) and merge._behind(root, oid, f"origin/{target}")):
            continue
        head = pr.get("headRefName", "")
        found.append({"number": pr["number"], "title": pr.get("title", ""), "url": pr.get("url", ""),
                      "author": (pr.get("author") or {}).get("login", ""), "head": head, "oid": oid,
                      "body": pr.get("body") or "", "cards": [int(n) for n in CLOSES.findall(pr.get("body") or "")],
                      "batch": head.startswith(f"{config['project']['name']}/batch-")})
    return sorted(found, key=lambda pr: pr["number"])


def other_commits(root, target: str, head: str, taken: set[str]) -> list[tuple[str, str]]:
    """The commits on head's first-parent line that origin/<target> lacks and no pull request merged, oldest first,
    as (sha, subject): direct pushes and merges by hand. A merge that only brought the release branch back in is
    no work of its own, and is left out."""
    out = batch._git(root, "log", "--first-parent", f"-n{COMMITS_READ}", "--format=%H%x09%P%x09%s",
                     f"origin/{target}..{head}", check=False)
    found = []
    for line in out.splitlines():
        sha, parents, subject = (line.split("\t", 2) + ["", ""])[:3]
        if not sha or sha in taken:
            continue
        others = parents.split()[1:]
        if others and all(merge._behind(root, parent, f"origin/{target}") for parent in others):
            continue
        found.append((sha, subject))
    return list(reversed(found))


def files_of(root, sha: str) -> list[tuple[str, str]]:
    """What one merge, squash or commit changed against its first parent, as (status letter, path); empty when this
    clone lacks it."""
    if not merge._exists(root, f"{sha}^1"):
        return []
    out = batch._git(root, "diff", "--name-status", "-M", f"{sha}^1", sha, check=False)
    found = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            found.append((parts[0][0], parts[-1]))
    return found


def sections(text: str) -> dict[str, list[str]]:
    """A description's sections: each heading's lines, blank ones and the HTML comments of a template left out."""
    found: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            current = heading[1].strip()
            found.setdefault(current, [])
        elif current is not None and line.strip() and not line.strip().startswith("<!--"):
            found[current].append(line.rstrip())
    return found


def own_notes(text: str) -> tuple[list[str], list[str]]:
    """A pull request's own notes on migrations and on tests: the lines under a heading that names migrations, or
    tests, such as a batch's `## Removed tests`. A line that only says none, or looks like a secret, is left out."""
    from colony import transport

    migrations, tests = [], []
    for heading, lines in sections(text).items():
        kept = [line for line in lines if not NONE.match(line) and not transport.holds_secret(line)][:NOTES_KEPT]
        if MIGRATION_HEADING.search(heading):
            migrations += kept
        elif TEST_HEADING.search(heading):
            tests += kept
    return migrations, tests


def notes(config: dict, changed: list[tuple[str, str]], text: str = "") -> dict:
    """One piece of work's notes: the migrations it adds or changes, the test files it removes or changes, how many
    test files it adds, and its own description's notes on migrations and tests."""
    from colony import checks

    def is_test(path: str) -> bool:
        return checks.is_test_file(path) or checks.in_test_folder(path)

    own_migrations, own_tests = own_notes(text)
    return {"migrations": [(status, path) for status, path in changed if is_migration(config, path)],
            "removed": [path for status, path in changed if status == "D" and is_test(path)],
            "changed": [path for status, path in changed if status in "MR" and is_test(path)],
            "added": sum(1 for status, path in changed if status == "A" and is_test(path)),
            "own_migrations": own_migrations, "own_tests": own_tests}


def leads(config: dict, work: list[dict]) -> None:
    """Name each pull request's lead in its "leads": the board's Lead field of the cards it closes, else
    `@<author>`. A board that can't be read leaves every pull request on its author, with a note."""
    found = {}
    if any(pr["cards"] for pr in work) and config.get("features", {}).get("board", True) and not wait.hack(config):
        try:
            on_board = board.find_board(config)
            found = {item["number"]: board.field_value(item, "Lead").lower()
                     for item in (board.items(on_board) if on_board else [])}
        except cli.ColonyError as e:
            print(f"{cli.NAME}: the board was not read, so each pull request goes by its author: {e}", file=sys.stderr)
    for pr in work:
        pr["leads"] = sorted({found[n] for n in pr["cards"] if found.get(n)}) or [f"@{pr['author'].lower()}"]


def others(work: list[dict], me: str, mine: frozenset[str]) -> list[dict]:
    """The pull requests another lead made: none of their leads is this lead, or this lead's person's login."""
    return [pr for pr in work if not any(lead in (me, *(f"@{login}" for login in mine)) for lead in pr["leads"])]


def check_results(config: dict, root, sha: str) -> list[str]:
    """The check results on the release's head: the code host's checks on the commit, from any CI, and the results
    this computer's ledger keeps for the same commit or the same code."""
    from colony import checks, transport

    lines = []
    try:
        found = checks.ci_state(config["project"]["repo"], sha)
    except (cli.ColonyError, ValueError) as e:
        found, lines = [], [f"- The code host's checks could not be read: {e}"]
    if found:
        failed = [c for c in found if c["state"] == "fail"]
        pending = [c for c in found if c["state"] == "pending"]
        passed = [c for c in found if c["state"] in ("pass", "skipped")]
        head = (f"failed: {len(failed)} of {len(found)} checks" if failed else
                f"still running: {len(pending)} of {len(found)} checks" if pending else f"passed: all {len(found)} checks")
        lines.append(f"- On the code host, {head}" + (f", {len(passed)} passed" if failed or pending else "") + ".")
        lines += [f"  - {c['name']} failed" + (f": {c['url']}" if c.get("url") else "") for c in failed]
    tree = batch._git(root, "rev-parse", f"{sha}^{{tree}}", check=False)
    kept = checks.read_json(checks.ledger_path(checks.colony_home(config)), {})
    entries = [e for e in (kept.values() if isinstance(kept, dict) else []) if isinstance(e, dict)
               and e.get("kind") != "ci" and (e.get("commit") == sha and not e.get("dirty")
                                              or (tree and e.get("tree") == tree))]
    for e in sorted(entries, key=lambda e: e.get("at", 0)):
        said = str(e.get("line") or "")
        said = "" if transport.holds_secret(said) else f": {said[:160]}"
        command = str(e.get("command") or "?")
        command = ("a check whose command looked like it held a secret, so it stays out,"
                   if transport.holds_secret(command) else f"`{command}`")
        lines.append(f"- On this computer, {command} "
                     f"{'passed' if e.get('result') == 'pass' else 'failed'} at {checks.clock(e.get('at', 0))}{said}")
    if not lines:
        lines = [f"- No check has run on `{sha[:9]}` yet. `{cli.NAME} ci {sha[:9]}` starts CI on it, and "
                 f"`{cli.NAME} check run --full --ref {sha[:9]}` runs the full suite on this computer. "
                 f"`{cli.NAME} release --refresh` writes the results here once they are in."]
    return lines


def gather(config: dict, root, found: branches.Names, head: str, picked: set[str] | None = None) -> dict:
    """What a release from `head` carries, for its description: the pull requests in it, the ones left for later,
    the other commits, each one's notes, and the check results on head. `picked` is a partial release's merge
    commits; without it, every unreleased pull request and commit goes."""
    work = unreleased(config, root, found.integration, found.release)
    leads(config, work)
    for pr in work:
        pr["notes"] = notes(config, files_of(root, pr["oid"]), pr["body"])
    chosen = work if picked is None else [pr for pr in work if pr["oid"] in picked]
    left = [] if picked is None else [pr for pr in work if pr["oid"] not in picked]
    commits = [] if picked is not None else other_commits(root, found.release, head, {pr["oid"] for pr in work})
    changed = [item for sha, _ in commits for item in files_of(root, sha)]
    sha = batch._git(root, "rev-parse", head)
    return {"work": chosen, "left": left, "commits": commits, "commit_notes": notes(config, changed), "head": sha,
            "checks": check_results(config, root, sha), "partial": picked is not None}


# The description


def note_lines(label: str, n: dict, kind: str) -> list[str]:
    """One piece of work's lines in the Migrations or the Tests section, or none when it has nothing there."""
    if kind == "migrations":
        named = [f"`{path}` ({'removed' if status == 'D' else 'new' if status == 'A' else 'changed'})"
                 for status, path in n["migrations"]]
        own = n["own_migrations"]
    else:
        named = [f"removed `{path}`" for path in n["removed"]] + [f"changed `{path}`" for path in n["changed"]]
        if n["added"] and named:
            named.append(f"{n['added']} new test file{'' if n['added'] == 1 else 's'}")
        own = n["own_tests"]
    if not named and not own:
        return []
    return [f"- {label}: " + ("; ".join(named) if named else "its description says:"),
            *[f"  - From its description: {line.lstrip('-* ').strip()}" for line in own]]


def body(config: dict, found: branches.Names, carried: dict, theirs: list[dict], notes_kept: bool = True) -> str:
    """The release pull request's description (see the module's docstring)."""
    work, commits = carried["work"], carried["commits"]
    what = "a chosen part of " if carried["partial"] else ""
    count = f"{len(work)} pull request{'' if len(work) == 1 else 's'}"
    if commits:
        count += f" and {len(commits)} other commit{'' if len(commits) == 1 else 's'}"
    lines = [f"Releases {what}`{found.integration}` into `{found.release}`: {count}.", "", "## What changed"]
    lines += [f"- #{pr['number']} {pr['title']}, from {', '.join(pr['leads'])}" for pr in work]
    lines += [f"- `{sha[:7]}` {subject} (no pull request)" for sha, subject in commits[:COMMITS_LISTED]]
    if len(commits) > COMMITS_LISTED:
        lines.append(f"- {len(commits) - COMMITS_LISTED} more commits with no pull request")
    if not work and not commits:
        lines.append("- Nothing new: the release branch lacks only merges.")
    for kind, title in (("migrations", "Migrations"), ("tests", "Tests removed or changed")):
        found_lines = [line for pr in work for line in note_lines(f"#{pr['number']}", pr["notes"], kind)]
        found_lines += note_lines("The commits with no pull request", carried["commit_notes"], kind)
        if not notes_kept:
            found_lines = [line for line in found_lines if not line.startswith("  - From its description")]
        lines += ["", f"## {title}", *(found_lines or ["None."])]
    lines += ["", f"## Checks on `{carried['head'][:9]}`", *carried["checks"]]
    if carried["left"]:
        lines += ["", f"## {LEFT}",
                  *[f"- #{pr['number']} {pr['title']}, from {', '.join(pr['leads'])}" for pr in carried["left"]]]
    if theirs:
        lines += ["", "## Other leads' work", *[f"- #{pr['number']}, from {', '.join(pr['leads'])}" for pr in theirs]]
    back = ", ".join(f"`{b}`" for b in (found.integration, *found.long_lived))
    lines += ["", "## After the merge",
              f"A person merges this pull request. Then `{cli.NAME} release --after` lifts the merge freeze on "
              f"`{found.integration}`, opens a pull request that brings `{found.release}` back into {back}, and "
              "watches the deploy.", "", batch.trailer(config), ""]
    text = "\n".join(lines)
    if len(text) > BODY_MAX and notes_kept:
        return body(config, found, carried, theirs, notes_kept=False)
    return text if len(text) <= BODY_MAX else text[:BODY_MAX] + "\n\n(cut here: the description was too long)\n"


def carried_prs(text: str) -> list[int]:
    """The pull requests a release's description says it carries: each `- #<n>` line, in What changed and every
    other section, except under Left for a later release, where a partial release names the ones it leaves out.
    testers.release_cards reads a release's cards through it, so the format has one owner."""
    found, current = [], ""
    for line in text.splitlines():
        if heading := HEADING.match(line):
            current = heading[1].strip()
        elif current != LEFT and (listed := LISTED_PR.match(line)):
            found.append(int(listed[1]))
    return list(dict.fromkeys(found))


def few(items: list[str]) -> str:
    """Up to three items in words, such as `#12, #15 and #20`, with how many more after them."""
    shown = items[:3] + ([f"{len(items) - 3} more"] if len(items) > 3 else [])
    return shown[0] if len(shown) == 1 else f"{', '.join(shown[:-1])} and {shown[-1]}"


def auto_merge_note(stopped: list[int], failed: list[str]) -> str:
    """What the freeze did to auto-merge, for its line: the pull requests it turned it off on, and those it couldn't."""
    note = f"; auto-merge is off on {few([f'#{n}' for n in stopped])} until you turn it back on" if stopped else ""
    return note + (f"; turn auto-merge off by hand on {few(failed)}" if failed else "")


def warning(source: str, target: str, theirs: list[dict], me: str, frozen: str = "", auto: str = "") -> str:
    """The @all line: the release, the freeze when there is one, with what it did to auto-merge (`auto`,
    auto_merge_note), and the other leads' work it carries, with their leads while that fits in one line."""
    held = f"; {source} is frozen until {frozen}, so only named fixes land{auto}" if frozen else ""
    for named in (True, False):
        listed = ", ".join(f"#{pr['number']}" + (f" ({', '.join(pr['leads'])})" if named else "") for pr in theirs)
        carries = f", which carries your work {listed}: tell me at once if one must wait" if theirs else ""
        sentence = f"releasing {source} into {target} now{carries}{held}"
        line = wait.compose(f"@{wait.ALL}", sentence, me)
        if len(line) < wait.MAX_LINE:
            break
    return wait.checked(line, sentence)


def warn(config: dict, line: str) -> None:
    """Post the line on the coordination issue, or the board in hack mode, as `colony say` does."""
    from colony import tidy, transport

    transport.check_transport(config)
    if not wait.hack(config):
        tidy.keep_short(config, wait.coordination_issue(config["project"]["repo"], config["project"]["name"]))
    transport.send(config, f"@{wait.ALL}", line)


# The release pull request


def release_prs(config: dict, found: branches.Names, state: str) -> list[dict]:
    """The release pull requests into the release branch in a state: from the integration branch, or from a partial
    release's `<project>/release-<date>` branch."""
    listed = json.loads(wait.gh("pr", "list", "--repo", config["project"]["repo"], "--base", found.release, "--state",
                                state, "--limit", "20", "--json", "number,url,headRefName,isCrossRepository") or "[]")
    partial = f"{config['project']['name']}/release-"
    # A fork's pull request may name its branch after the integration branch: only a branch on the repo itself counts.
    return [pr for pr in listed if not pr.get("isCrossRepository") and (
        pr.get("headRefName") == found.integration or str(pr.get("headRefName", "")).startswith(partial))]


def picked_on(root, found: branches.Names, head: str) -> set[str] | None:
    """A partial release branch's chosen merge commits, from git cherry-pick -x's lines; None for the integration
    branch itself."""
    if head == f"origin/{found.integration}":
        return None
    text = batch._git(root, "log", "--format=%B", f"origin/{found.release}..{head}", check=False)
    return set(PICKED.findall(text))


def refresh(config: dict, root, found: branches.Names, pr: dict) -> str:
    """Rewrite an open release pull request's description from the work and the checks as they are now."""
    head = f"origin/{pr['headRefName']}"
    carried = gather(config, root, found, head, picked_on(root, found, head))
    wait.gh("pr", "edit", str(pr["number"]), "--repo", config["project"]["repo"], "--body",
            body(config, found, carried, []))
    return pr["url"]


def pick(work: list[dict], only: list[int], lead: str) -> list[dict]:
    """The pull requests a partial release takes: the numbers in `only`, and every one whose lead is `lead`."""
    numbers = {pr["number"] for pr in work}
    missing = [n for n in only if n not in numbers]
    if missing:
        raise cli.ColonyError(f"{', '.join(f'#{n}' for n in missing)} is not unreleased work merged into the "
                              f"integration branch: `{cli.NAME} release --print` lists what is")
    chosen = [pr for pr in work if pr["number"] in only or (lead and lead.lower() in pr["leads"])]
    if not chosen:
        raise cli.ColonyError(f"no unreleased pull request is {lead}'s: `{cli.NAME} release --print` lists each one's "
                              "lead")
    return chosen


def partial_branch(config: dict, root) -> str:
    """A new branch name for a partial release: `<project>/release-<date>`, with -2, -3 … when taken on origin."""
    name = f"{config['project']['name']}/release-{time.strftime('%Y-%m-%d')}"
    found, n = name, 1
    while merge._exists(root, f"origin/{found}"):
        n += 1
        found = f"{name}-{n}"
    return found


def cut(config: dict, root, found: branches.Names, chosen: list[dict]) -> str:
    """Cut a partial release branch from the release branch, copy each chosen pull request's change onto it, oldest
    first, and push it. A change that doesn't apply alone stops it, naming the files, with the release branch and
    the integration branch untouched."""
    branch = partial_branch(config, root)
    with merge.one_at_a_time(config):
        wt = merge.worktree(config)
        merge.ready(root, wt, found.release)
        for pr in chosen:
            if not merge._exists(root, pr["oid"]):
                raise cli.ColonyError(f"this clone lacks #{pr['number']}'s merge commit {pr['oid'][:9]}: run "
                                      "`git fetch origin` and try again")
            parents = batch._git(root, "rev-list", "--parents", "-n", "1", pr["oid"]).split()
            mainline = ["-m", "1"] if len(parents) > 2 else []
            picked = batch._run(["git", "cherry-pick", "-x", *mainline, pr["oid"]], wt, check=False)
            if picked.returncode == 0:
                continue
            conflicted = merge._git(wt, "diff", "--name-only", "--diff-filter=U", check=False).split()
            if "empty" in f"{picked.stdout}{picked.stderr}" and not conflicted:
                merge._git(wt, "cherry-pick", "--skip", check=False)  # the release branch holds it already
                continue
            merge._git(wt, "cherry-pick", "--abort", check=False)
            raise cli.ColonyError(f"#{pr['number']} doesn't apply on {found.release} without the work before it: it "
                                  f"conflicts in {', '.join(conflicted) or 'its change'}. Add the pull request it "
                                  f"builds on with --only, or release all of {found.integration}")
        head = merge._git(wt, "rev-parse", "HEAD")
        if head == merge._git(root, "rev-parse", f"origin/{found.release}"):
            raise cli.ColonyError(f"{found.release} already holds every chosen change: nothing to release")
        merge._git(wt, "push", "origin", f"{head}:refs/heads/{branch}")
    merge._git(root, "fetch", "origin", check=False)
    return branch


def open_release(config: dict, root, found: branches.Names, me: str, mine: frozenset[str], args) -> str | None:
    """Open the release pull request (see the module's docstring), or return the one already open; None when the
    release branch already holds the integration branch."""
    repo, name = config["project"]["repo"], config["project"]["name"]
    already = release_prs(config, found, "open")
    if already:
        return refresh(config, root, found, already[0]) if args.refresh else already[0]["url"]
    if args.refresh:
        raise cli.ColonyError(f"no release pull request into {found.release} is open: `{cli.NAME} release` opens one")
    if merge._behind(root, f"origin/{found.integration}", f"origin/{found.release}"):
        return None
    only, lead = list(args.only or []), (args.lead or "").strip()
    if lead == "me":
        lead = me
    if only or lead:
        everything = unreleased(config, root, found.integration, found.release)
        leads(config, everything)
        chosen = pick(everything, only, lead)
        branch = cut(config, root, found, chosen)
        carried = gather(config, root, found, f"origin/{branch}", {pr["oid"] for pr in chosen})
        theirs = others(carried["work"], me, mine)
        if theirs:
            warn(config, warning(found.integration, found.release, theirs, me))
        title = f"{name}: release " + ", ".join(f"#{pr['number']}" for pr in chosen) + f" into {found.release}"
        return wait.gh("pr", "create", "--repo", repo, "--base", found.release, "--head", branch, "--title", title,
                       "--body", body(config, found, carried, theirs)).strip()
    carried = gather(config, root, found, f"origin/{found.integration}")
    theirs = others(carried["work"], me, mine)
    title = f"{name}: release {found.integration} into {found.release}"
    if carried["work"]:
        title += " (" + ", ".join(f"#{pr['number']}" for pr in carried["work"]) + ")"
    text = body(config, found, carried, theirs)
    until, auto = "", ""
    if settings(config)["freeze"]:
        ends = time.time() + 3600 * freeze.freeze_hours(config)
        freeze.put(root, freeze.hold("release", found.integration, me, f"releasing into {found.release}", ends))
        until = freeze.when(ends)
        # A pull request queued to merge by itself would merge during the freeze, past the merge guard.
        auto = auto_merge_note(*freeze.stop_auto_merges(config, freeze.paused(config, found.integration)))
    if theirs or until:
        warn(config, warning(found.integration, found.release, theirs, me, until, auto))
    try:
        return wait.gh("pr", "create", "--repo", repo, "--base", found.release, "--head", found.integration, "--title",
                       title, "--body", text).strip()
    except cli.ColonyError:
        if until:  # no release pull request, so nothing to hold the integration branch for
            freeze.lift(root, found.integration, ("release",))
            freeze.post(config, args, f"freeze: {found.integration} is open again: the release pull request was not "
                                      "opened")
        raise


def released(config: dict, found: branches.Names) -> None:
    """Refuse --after while a release pull request is still open, or when none was ever merged."""
    still_open = release_prs(config, found, "open")
    if still_open:
        raise cli.ColonyError(f"the release pull request {still_open[0]['url']} is still open: a person merges it "
                              "first")
    if not release_prs(config, found, "merged"):
        raise cli.ColonyError(f"no release pull request into {found.release} was merged: run `{cli.NAME} release` "
                              "first")


def bring_back(config: dict, root, found: branches.Names, args) -> None:
    """After a release: lift its freeze, and open a pull request that brings the release branch into the integration
    branch and each long-lived branch that lacks it."""
    try:
        gone = freeze.lift(root, found.integration, ("release",))
    except (freeze.Unreadable, cli.ColonyError) as e:
        print(f"the release's freeze on {found.integration} was not lifted: {e}: run `{cli.NAME} freeze off`",
              file=sys.stderr)
        gone = []
    if gone:
        print(f"lifted the release's freeze on {found.integration}")
        freeze.post(config, args, f"freeze: {found.integration} is open again after the release, so work lands as "
                                  "usual")
    why = f"The release into `{found.release}` merged, and `{cli.NAME} release --after` opened this."
    for target in (found.integration, *found.long_lived):
        if not merge._exists(root, f"origin/{target}"):
            print(f"{target} is not on origin, so nothing was brought into it")
            continue
        url = branches.sync_pr(config, root, found.release, target, why)
        print(f"{target} already holds {found.release}: nothing to bring back" if url is None else
              f"bring {found.release} into {target}: {url} (a person merges it)")


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


def plan(config: dict, found: branches.Names, args) -> str:
    """What the release would run, for --dry-run."""
    repo, source, target = config["project"]["repo"], found.integration, found.release or "<the release branch>"
    name = config["project"]["name"]
    if args.after:
        workflow = config["project"].get("deploy_workflow") or ""
        lines = [f"{cli.NAME} release --after: dry run, nothing runs.", "  $ git fetch origin",
                 f"  lift the release's merge freeze on {source}"]
        lines += [f"  when {b} lacks {target}: open a pull request from {branches.sync_prefix(config, target, b)}"
                  f"-<time> into {b}, which a person merges" for b in (source, *found.long_lived)]
        return "\n".join(lines + [f"  then watch {workflow} on {target}" if workflow else "  no deploy_workflow to watch"])
    if args.only or args.lead:
        chosen = ", ".join([*(f"#{n}" for n in args.only or []), *([f"{args.lead}'s work"] if args.lead else [])])
        return "\n".join([f"{cli.NAME} release: dry run, nothing runs.", "  $ git fetch origin",
                          f"  cut {name}/release-<date> from origin/{target}, and copy {chosen} onto it, oldest "
                          "first: $ git cherry-pick -x -m 1 <merge commit>",
                          f"  $ git push origin <head>:refs/heads/{name}/release-<date>",
                          "  draft the description from the chosen work, its migrations, tests and checks",
                          "  $ " + shlex.join(["gh", "pr", "create", "--repo", repo, "--base", target, "--head",
                                               f"{name}/release-<date>"])])
    pr = ["gh", "pr", "create", "--repo", repo, "--base", target, "--head", source]
    lines = [f"{cli.NAME} release: dry run, nothing runs.", "  $ git fetch origin",
             f"  draft the description from the pull requests and commits merged into {source} that {target} lacks: "
             "what changed, migrations, removed or changed tests, and the checks on its head"]
    if settings(config)["freeze"]:
        lines.append(f"  freeze {source} for every person's leads for {freeze.freeze_hours(config):g} hours, or until "
                     f"`{cli.NAME} release --after`")
    return "\n".join(lines + ["  post one @all line that says so, naming the other leads whose work it carries",
                              "  $ " + shlex.join(pr)])


def run(config: dict, args) -> int:
    """`colony release`: see the module's docstring."""
    try:
        return act(config, args)
    except freeze.Unreadable as e:
        raise cli.ColonyError(f"origin's merge freeze could not be read, so nothing was released: {e}") from None


def act(config: dict, args) -> int:
    """One `colony release` (run)."""
    if os.environ.get(cli.SESSION_ENV, "").lower() not in ("", cli.LEAD):
        raise cli.ColonyError("release is for the lead, never a helper")
    for flag in ("only", "lead", "print", "refresh"):
        if not hasattr(args, flag):
            setattr(args, flag, None)
    if args.dry_run:
        try:
            found = branches.names(config, cli.repo_root())
        except cli.ColonyError:
            found = branches.names(config)
        print(plan(config, found, args))
        return 0
    root = cli.repo_root()
    merge._git(root, "fetch", "origin")
    found = branches.release_names(config, root)
    if not merge._exists(root, f"origin/{found.release}"):
        raise cli.ColonyError(f"origin has no branch {found.release}")
    if args.after:
        released(config, found)
        bring_back(config, root, found, args)
        merge._git(root, "fetch", "origin")
        return watch(config, root, found.release)
    me = wait.lead_name(config, args)
    mine = wait.person_logins(config, cli.person_of(config, args))
    if args.print:
        everything = unreleased(config, root, found.integration, found.release)
        leads(config, everything)
        lead = me if args.lead == "me" else (args.lead or "")
        picked = {pr["oid"] for pr in pick(everything, list(args.only or []), lead)} if args.only or lead else None
        carried = gather(config, root, found, f"origin/{found.integration}", picked)
        print(body(config, found, carried, others(carried["work"], me, mine)))
        return 0
    url = open_release(config, root, found, me, mine, args)
    print(f"release pull request: {url}" if url else
          f"{found.release} already holds {found.integration}: nothing to release")
    return 0


def add_commands(sub) -> None:
    """cli.py's route to the release workstream's commands: `release`, and `freeze`, `branches`, `health`, `step` and
    `plain`, each registered by its own module."""
    from colony import health, plain, steps

    p = sub.add_parser("release", help="the lead: open the release pull request from the integration branch into the "
                                       "release branch, with a drafted description, or --after a person merged it, "
                                       "bring it back and watch the deploy")
    p.add_argument("--after", action="store_true",
                   help="after a person merged the release: lift its freeze, open the pull requests that bring the "
                        "release branch back into the integration and long-lived branches, then watch "
                        "[project] deploy_workflow until it ends")
    p.add_argument("--only", action="append", type=int, metavar="N",
                   help="release only this merged pull request, and the others named; repeat it")
    p.add_argument("--lead", metavar="NAME", help="release only this lead's merged pull requests; `me` for yours")
    p.add_argument("--print", action="store_true", help="print the drafted description, and open nothing")
    p.add_argument("--refresh", action="store_true",
                   help="rewrite the open release pull request's description from the work and checks as they are now")
    p.add_argument("--dry-run", action="store_true", help="print the plan and run nothing")
    p.set_defaults(run=run)
    for module in (freeze, branches, health, steps, plain):
        module.register(sub)
