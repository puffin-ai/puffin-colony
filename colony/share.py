"""Sharing a file and asking another lead for something. Without them, a lead hands a file over on a throwaway branch,
which then looks like unmerged work, and tracks what it waits on from another lead in notes no one else sees.

`colony share <file> [--to @<login>]` commits the file under shared/ on the colony-shared branch, which no one merges,
pushes it, and posts its link on the board, so a teammate's agent on any computer reads it. It never shares a file
that holds a secret's shape, in UTF-8 or UTF-16, nor a kind of file that holds secrets, such as .env or a .pem; on a
public repo it shares only with --public, checked before anything is pushed.

`colony need <lead|@login> "<what>"` posts `@<login> need: <what> [N<n>]`, which reaches that lead at once, and
remembers it; `colony need` lists the open ones with their age, and `colony need --done N<n>` closes one and thanks the
other lead.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from colony import cli, transport, wait

BRANCH = "colony-shared"
# Files that hold secrets by their kind, whatever their words: never shared.
SECRET_FILES = re.compile(r"^(\.env.*|.*\.(pem|key|p12|pfx|jks|keystore|kdbx)|id_(rsa|dsa|ecdsa|ed25519).*|"
                          r"credentials.*|secrets?\..*|\.netrc|\.npmrc|\.pypirc|.*service[-_]account.*\.json)$", re.I)
SHARE_LIMIT = 10_000_000  # bytes
NEED = re.compile(r"N(\d+)$", re.I)


def is_public(config: dict) -> bool:
    """Whether the project's repo is public, as GitHub says now (private.is_public)."""
    from colony import private

    return private.is_public(config)


def sender(config: dict) -> str:
    """Who signs: the lead's name, or this session's."""
    me = os.environ.get(cli.SESSION_ENV, "").lower()
    return wait.lead_name(config, None) if me in ("", cli.LEAD) else me


def share(config: dict, args) -> int:
    """`colony share <file> [--to @<login>]`: see the module's docstring."""
    source = Path(args.file).expanduser()
    if not source.is_file():
        raise cli.ColonyError(f"{args.file} is not a file")
    if source.stat().st_size > SHARE_LIMIT:
        raise cli.ColonyError(f"{args.file} is over {SHARE_LIMIT // 1_000_000} MB: share a smaller copy")
    if SECRET_FILES.match(source.name):
        raise cli.ColonyError(f"{source.name} is a kind of file that holds secrets, and colony never shares a secret")
    data = source.read_bytes()
    texts = [data.decode("utf-8", "replace")]
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in data[:4096]:
        texts.append(data.decode("utf-16", "replace"))  # a secret in UTF-16 has a NUL between its letters
    if any(transport.holds_secret(text) for text in texts):
        raise cli.ColonyError(f"{args.file} holds a secret's shape, and colony never shares a secret")
    if is_public(config) and not getattr(args, "public", False):
        raise cli.ColonyError(f"{config['project']['repo']} is public, so anyone could read {source.name}: add "
                              f"--public to share it anyway, or use `{cli.NAME} say --private` for what isn't for "
                              "strangers")
    root, name = cli.repo_root(), re.sub(r"[^\w.-]", "-", source.name)

    def git(*parts: str, cwd: Path = root) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *parts], cwd=cwd, capture_output=True, text=True)

    git("fetch", "origin")
    start = f"origin/{BRANCH}" if git("rev-parse", "--verify", "--quiet", f"origin/{BRANCH}").returncode == 0 \
        else f"origin/{config['project']['base']}"
    folder = Path(config["project"].get("worktrees") or root.parent) / f"{config['project']['name']}-share-{os.getpid()}"
    made = git("worktree", "add", "--detach", str(folder), start)
    if made.returncode:
        raise cli.ColonyError(f"git worktree add failed: {made.stderr.strip()[:300]}")
    try:
        target = Path("shared") / name
        (folder / target).parent.mkdir(parents=True, exist_ok=True)
        (folder / target).write_bytes(data)
        for step in (("add", str(target)), ("commit", "-m", f"share {name}"), ("push", "origin",
                                                                              f"HEAD:refs/heads/{BRANCH}")):
            done = git(*step, cwd=folder)
            if done.returncode:
                raise cli.ColonyError(f"git {step[0]} failed: {(done.stderr or done.stdout).strip()[:300]}")
    finally:
        git("worktree", "remove", "--force", str(folder))
    link = f"https://github.com/{config['project']['repo']}/blob/{BRANCH}/shared/{name}"
    to = (args.to or f"@{wait.ALL}").strip()
    to = to if to.startswith("@") else f"@{to}"
    line = f"{to} shared: {name}, {link} (from {sender(config)})"
    transport.send(config, to, line)
    print(line)
    return 0


def needs_path(config: dict) -> Path:
    return wait.state_path(config["project"]["name"], f"{wait.state_name(cli.LEAD)}-needs")


def need(config: dict, args) -> int:
    """`colony need [<lead|@login> "<what>"] [--done N<n>]`: see the module's docstring."""
    path, me = needs_path(config), sender(config)
    held = wait.read_json(path, {})
    held = held if isinstance(held, dict) and isinstance(held.get("open"), list) else {"next": 1, "open": []}
    if args.done:
        found = NEED.fullmatch(args.done.strip())
        number = int(found[1]) if found else -1
        item = next((item for item in held["open"] if item.get("n") == number), None)
        if item is None:
            raise cli.ColonyError(f"no open need {args.done}: `{cli.NAME} need` lists them")
        held["open"] = [other for other in held["open"] if other is not item]
        wait.write_json(path, held)
        transport.send(config, item["to"], f"{item['to']} N{number} is done, thanks: {item['what']} (from {me})")
        print(f"N{number} is done: {item['what']}")
        return 0
    if not args.to:
        if not held["open"]:
            print("No open need.")
        for item in held["open"]:
            print(f"N{item['n']} from {item['to']}, open {int((time.time() - item['at']) // 60)} min: {item['what']}")
        return 0
    what = " ".join(" ".join(args.what).split())
    wait.check_sentence(what)
    to = args.to.strip().lower()
    to = to if to.startswith("@") else f"@{to.split('-', 1)[0]}"  # ben-main-lead is ben's
    number = int(held.get("next", 1))
    transport.send(config, to, f"{to} need: {what} [N{number}] (from {me})")
    held["open"].append({"n": number, "to": to, "what": what, "at": time.time()})
    held["next"] = number + 1
    wait.write_json(path, held)
    print(f"{to} need: {what} [N{number}]: `{cli.NAME} need --done N{number}` once it is done")
    return 0


def open_needs(config: dict) -> str:
    """One line on this lead's open needs, for `colony who`, or ""."""
    held = wait.read_json(needs_path(config), {})
    items = held.get("open", []) if isinstance(held, dict) else []
    if not items:
        return ""
    oldest = max(time.time() - float(item.get("at", 0)) for item in items)
    return f"Open needs: {len(items)}, the oldest {int(oldest // 60)} min: `{cli.NAME} need` lists them."
