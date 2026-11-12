"""What differs between macOS and Linux, where Colony began, and Windows: a file lock, handing the terminal to a
session, and the shell that runs a repo's commands. On macOS and Linux each helper makes the calls Colony always made."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator

WINDOWS = os.name == "nt"
RETRY_SECONDS = 0.05  # how often a blocking lock on Windows tries again

if WINDOWS:
    import msvcrt
else:
    import fcntl


@contextmanager
def lock(handle: IO, block: bool = True) -> Iterator[bool]:
    """Hold an exclusive lock on `handle`, one process at a time on this computer, and yield True, then release it.
    With `block` false, yield False at once when another process holds it.

    macOS and Linux use flock. Windows has no fcntl, so it locks the file's first byte with msvcrt, which works on an
    empty file too, since the byte may lie past the end."""
    if not WINDOWS:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX if block else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
        return
    while True:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            break
        except OSError:
            if not block:
                yield False
                return
            time.sleep(RETRY_SECONDS)
    try:
        yield True
    finally:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def needs_utf8() -> bool:
    """Whether this Python reads and writes text in a code page other than UTF-8: Windows' Python outside its UTF-8
    mode, which decodes files and program output as the ANSI code page, such as cp1252, while gh, git and Colony's own
    files are UTF-8. macOS and Linux run in a UTF-8 locale already."""
    return WINDOWS and not sys.flags.utf8_mode


def relaunch_in_utf8(argv: list[str]) -> int:
    """Run this colony command again in Python's UTF-8 mode, and return its exit code."""
    return subprocess.run([sys.executable, "-X", "utf8", "-m", "colony", *argv]).returncode


def is_terminal(stream) -> bool:
    """Whether a person types into `stream`: its isatty() on macOS and Linux. On Windows isatty() is true for the NUL
    device too, as in `colony < NUL` or under Claude Code's Bash tool, so the stream must also have a console mode."""
    if not WINDOWS:
        return stream.isatty()
    if not stream.isatty():
        return False
    import ctypes

    try:
        handle = msvcrt.get_osfhandle(stream.fileno())
    except (OSError, ValueError):  # no handle of its own, such as a test's stand-in stream: its isatty() answers
        return True
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(ctypes.c_ulong())))


def program(name: str) -> str:
    """The path to run a program by: its name on macOS and Linux. On Windows, the full path from PATH, because a
    program installed as a .cmd shim, as npm installs one, starts only by its full path without a shell."""
    return (shutil.which(name) or name) if WINDOWS else name


def process_env(inherited: dict[str, str], env: dict[str, str], default_dir: bool) -> dict[str, str]:
    """The environment a session's process starts with: the caller's, then the session's own. On Windows, a session on
    the default settings folder also drops an inherited CLAUDE_CONFIG_DIR here, the work `env -u` does on macOS and
    Linux (cli.claude_argv), since Windows has no `env`."""
    merged = {**inherited, **env}
    if WINDOWS and default_dir and "CLAUDE_CONFIG_DIR" not in env:
        merged.pop("CLAUDE_CONFIG_DIR", None)
    return merged


def hand_over(argv: list[str], env: dict[str, str] | None = None) -> int:
    """Hand this terminal to `argv`. macOS and Linux replace this process with it, so this never returns. Windows has no
    such exec: its os.exec* starts a new process and ends this one, and the shell and the session then both read the
    keyboard. There `argv` runs as a child, and its exit code comes back."""
    if not WINDOWS:
        if env is None:
            os.execvp(argv[0], argv)
        os.execvpe(argv[0], argv, env)
    return subprocess.run([program(argv[0]), *argv[1:]], env=env).returncode


def git_bash() -> str | None:
    """Git for Windows' bash, the one Claude Code's Bash tool runs: $CLAUDE_CODE_GIT_BASH_PATH, else the bash.exe
    beside git, else None. A bare `bash` on PATH is not trusted, because C:\\Windows\\System32\\bash.exe opens WSL."""
    named = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH", "")
    if named and Path(named).is_file():
        return named
    git = shutil.which("git")
    if not git:
        return None
    git_path = Path(git).resolve()
    for root in (git_path.parent.parent, git_path.parent.parent.parent):  # Git\cmd\git.exe, Git\mingw64\bin\git.exe
        bash = root / "bin" / "bash.exe"
        if bash.is_file():
            return str(bash)
    return None


SHELL_COMMAND = "COLONY_SHELL_COMMAND"  # where a repo's command rides into Git's bash on Windows (shell)


def shell(command: str, env: dict[str, str] | None) -> tuple[str | list[str], bool, dict[str, str] | None]:
    """What subprocess runs for a repo's shell command: its args, its `shell` flag and its env. macOS and Linux run the
    command as it is through /bin/sh, with `env` unchanged.

    Windows runs it through Git's bash, so a colony.toml written on a Mac, with `&&`, `~`, `$VAR` and single quotes,
    runs the same. The command rides in $COLONY_SHELL_COMMAND and not on the command line, because Git's bash rewrites
    a Windows command line: it globs `[`, `*` and `?`, and drops backslashes. Without Git's bash, cmd.exe runs it."""
    if WINDOWS:
        bash = git_bash()
        if bash:
            base = env if env is not None else os.environ
            return [bash, "-c", f'eval "${SHELL_COMMAND}"'], False, {**base, SHELL_COMMAND: command}
    return command, True, env


def own_group() -> dict:
    """The subprocess arguments that start a program in its own process group, so stop_group can end it with every
    process it started, such as a dev server an agent ran: a new session on macOS and Linux, a new group on Windows."""
    return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}


def stop_group(proc: subprocess.Popen) -> None:
    """End a program started with own_group, and everything it started: SIGTERM to its group, then up to 5 seconds
    later SIGKILL to whatever of the group is left, on macOS and Linux; `taskkill /T /F` on its tree on Windows."""
    stop_groups([proc])


def stop_groups(procs: list[subprocess.Popen]) -> None:
    """End several programs started with own_group at once, as stop_group ends one: every group gets SIGTERM first,
    and SIGKILL goes to whatever is left 5 seconds later."""
    if WINDOWS:
        for proc in procs:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
            proc.wait()
        return
    import signal

    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, None)):
        for proc in procs:
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        deadline = None if wait is None else time.monotonic() + wait
        for proc in procs:
            try:
                proc.wait(timeout=None if deadline is None else max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass


def native(path: str) -> str:
    """A path as this system writes it: unchanged on macOS and Linux. On Windows with backslashes throughout, since
    `~` there expands to C:\\Users\\<name>/... and git prints C:/..., and a mixed path prints and compares unlike."""
    return os.path.normpath(path) if WINDOWS else path


def same_path(a: str, b: str, windows: bool = WINDOWS) -> bool:
    """Whether two absolute paths name one folder, as Claude Code keys its projects. On Windows its state file holds
    both C:\\Users\\... and C:/Users/..., and case doesn't count there, so neither slashes nor case do; on macOS and
    Linux only a trailing slash is ignored."""
    def key(path: str) -> str:
        path = path.replace("\\", "/") if windows else path
        path = path.rstrip("/") or "/"
        return path.casefold() if windows else path
    return key(a) == key(b)


LINK_MODE = "120000"  # the index mode git gives a symbolic link
FIX_LINKS = "colony fix-links"
DEVELOPER_MODE = "turn on Developer Mode (Settings > System > For developers)"


def _git(cwd: Path, *args: str) -> str:
    """A read-only git command's output in `cwd`, or "" when it fails."""
    run = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8")
    return run.stdout if run.returncode == 0 else ""


def can_symlink() -> bool:
    """Whether this process may make a symbolic link: always on macOS and Linux. Windows allows it only with Developer
    Mode on, or as an administrator."""
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        try:
            os.symlink("target", Path(folder) / "link")
        except OSError:
            return False
    return True


def index_links(checkout: Path) -> dict[str, str]:
    """Each symbolic link in a checkout's index, by its path, with its blob's id, which holds the link's target."""
    links = {}
    for line in _git(checkout, "ls-files", "-s", "-z").split("\0"):
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[0] == LINK_MODE:
            links[path] = parts[1]
    return links


def stubs(checkout: Path, links: dict[str, str]) -> list[str]:
    """The links git wrote as plain files in a checkout, as it does with core.symlinks false: one-line text files
    holding the target."""
    return [path for path in links if (checkout / path).is_file() and not (checkout / path).is_symlink()]


def symlinks_on(root: Path) -> bool:
    """Whether git makes real links in this repo: its core.symlinks."""
    return _git(root, "config", "--bool", "core.symlinks").strip() == "true"


def links_note(root: Path) -> str:
    """One line telling a person on Windows that their repo's symbolic links are plain text files, or would become
    them, and how to fix it, or "" when they are fine. On Windows, git writes a link as a text file holding its target
    when core.symlinks is false or it may not make links, so a linked rule or skill silently never loads. macOS and
    Linux make links always, so there it is always ""."""
    if not WINDOWS:
        return ""
    links = index_links(root)
    if not links:
        return ""
    plain = stubs(root, links)
    if not plain and symlinks_on(root):
        return ""
    allowed = can_symlink()
    if not plain and allowed:  # core.symlinks is off, but every link is a link: a fresh checkout would break them
        return (f"colony: this repo has {len(links)} symbolic links but git's core.symlinks is off here, so new "
                f"checkouts write them as text files. Run `{FIX_LINKS}`.")
    what = (f"{len(plain)} of this repo's {len(links)} symbolic links are plain text files here"
            if plain else f"this repo has {len(links)} symbolic links but this computer can't make links")
    how = f"{DEVELOPER_MODE}, then run `{FIX_LINKS}`" if not allowed else f"run `{FIX_LINKS}`"
    return f"colony: {what}, so the rules and skills they point to don't load. To fix it, {how}."


def checkouts(root: Path) -> list[Path]:
    """The repo's checkout and every worktree of it that still exists on disk."""
    found = []
    for line in _git(root, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
            if path.is_dir():
                found.append(path)
    return found or [root]


def blobs(root: Path, ids: list[str]) -> dict[str, bytes]:
    """Each blob's content, by its id, read with one `git cat-file --batch`."""
    if not ids:
        return {}
    unique = sorted(set(ids))
    run = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"], input=("\n".join(unique) + "\n").encode(),
                         capture_output=True, check=True)
    out, found, at = run.stdout, {}, 0
    for _ in unique:
        end = out.index(b"\n", at)
        blob_id, _, size = out[at:end].decode().split()
        at = end + 1
        found[blob_id] = out[at:at + int(size)]
        at += int(size) + 1
    return found


def make_link(path: Path, target: str) -> None:
    """Make `path` a symbolic link to `target`, a relative path with forward slashes as git stores it. Windows needs
    backslashes in a relative target, and its own kind of link for a folder, as Git for Windows makes them."""
    if WINDOWS:
        target = target.replace("/", "\\")
    os.symlink(target, path, target_is_directory=(path.parent / target).is_dir())


def repair_links(root: Path) -> dict:
    """Turn on core.symlinks and turn each link git wrote as a plain file back into a link, in the repo and every
    worktree. Only an untouched stub, whose text is exactly its target, becomes a link: an edited one is kept, and
    named. Returns the counts: `checkouts`, `restored`, `already` (links already), `missing` and `edited` (paths)."""
    subprocess.run(["git", "-C", str(root), "config", "core.symlinks", "true"], check=True, capture_output=True)
    report: dict = {"checkouts": 0, "restored": 0, "already": 0, "missing": 0, "edited": []}
    for checkout in checkouts(root):
        links = index_links(checkout)
        if not links:
            continue
        report["checkouts"] += 1
        plain = stubs(checkout, links)
        report["already"] += sum(1 for path in links if (checkout / path).is_symlink())
        report["missing"] += sum(1 for path in links if not os.path.lexists(checkout / path))
        targets = blobs(checkout, [links[path] for path in plain])
        changed = False
        for path in plain:
            file = checkout / path
            target = targets[links[path]]
            if file.read_bytes() != target:
                report["edited"].append(str(file))
                continue
            file.unlink()
            make_link(file, target.decode())
            report["restored"] += 1
            changed = True
        if changed:
            _git(checkout, "update-index", "-q", "--refresh")
    return report
