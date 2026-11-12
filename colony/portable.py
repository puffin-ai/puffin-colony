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
