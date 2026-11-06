"""Windows only: lets the suite's POSIX habits work unchanged. macOS and Linux never import it.

- A test that points HOME at a temporary folder gets that folder from Path.home(), as on POSIX, where Windows' Python
  reads USERPROFILE instead.
- A stub a test writes as a `#!` script, such as a fake gh, runs through this Python or Git's bash, since Windows runs
  only .exe, .cmd and the like.
- Arguments reach Git's bash (a `#!/bin/sh` stub, or `sh`, `dash` or `bash` by name) through the environment, not
  the command line, because Git's bash rewrites a Windows command line: it globs `[`, `*` and `?`, and drops
  backslashes, as in a JSON argument.

conftest installs it for the suite's own process, and winsite/sitecustomize.py for every Python the suite starts, such
as `python -m colony` or a race test's workers, so they run the stubs the same way."""
from __future__ import annotations

import ntpath
import os
import shutil
import subprocess
import sys
from pathlib import Path

from colony import portable

SESSION_HOME_ENV = "COLONY_TEST_SESSION_HOME"  # the HOME the suite started with, before any test changed it
SITE = str(Path(__file__).resolve().parent / "winsite")  # holds the sitecustomize.py that installs this in a child
SESSION_HOME = os.environ.get(SESSION_HOME_ENV, os.environ.get("HOME", ""))
REAL_EXPANDUSER = ntpath.expanduser
REAL_WHICH = shutil.which
REAL_POPEN = subprocess.Popen
BASH = portable.git_bash()
MSYS_SHELLS = {"sh", "bash", "dash"}
# What a child needs to start on Windows, and what carries this shim into it.
KEEP = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "PYTHONPATH", "PYTHONUTF8",
        SESSION_HOME_ENV)
# A Python stub runs with its output's newlines as written, as on POSIX: Windows' text mode would turn each \n into
# \r\n, so a stub's \r\n became \r\r\n.
PYTHON_STUB = ("import runpy, sys; sys.stdout.reconfigure(newline=''); sys.stderr.reconfigure(newline=''); "
               "sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')")
# Rebuilds "$@" from STUB_ARG_1 .. STUB_ARG_<STUB_ARGC> and runs STUB_PROGRAM with it. It holds no backslash, `[`,
# `*` or `?`, so the command line can't change it.
REBUILD = ('set --; for ((i=1; i<=STUB_ARGC; i++)); do n=STUB_ARG_$i; set -- "$@" "${!n}"; unset "$n"; done; '
           'p=$STUB_PROGRAM; unset STUB_ARGC STUB_PROGRAM; exec "$p" "$@"')


def prepare_session() -> None:
    """Mark the suite's own process: the HOME it started with, and the site folder every child loads this from."""
    os.environ.setdefault(SESSION_HOME_ENV, SESSION_HOME)
    paths = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    if SITE not in paths:
        os.environ["PYTHONPATH"] = os.pathsep.join([SITE, *paths])
    os.environ["PYTHONUTF8"] = "1"  # every Python the suite starts runs in UTF-8 mode, as Colony does on Windows


def expanduser(path):
    """`~` is $HOME once a test has changed it, as on POSIX; otherwise Windows' own answer."""
    home = os.environ.get("HOME")
    text = os.fspath(path)
    if home and home != SESSION_HOME and text[:1] == "~" and text[1:2] in ("", "/", "\\"):
        return home + text[1:]
    return REAL_EXPANDUSER(path)


def shebang(path: Path) -> str | None:
    """A file's `#!` line when it is a script with no extension, as the suite writes its stubs; else None."""
    if path.suffix or not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            first = handle.readline(200)
    except OSError:
        return None
    return first.decode("utf-8", "replace").strip() if first.startswith(b"#!") else None


def find(name: str, search: str | None) -> Path | None:
    """The first `#!` stub named `name` on `search`, unless a real program of that name comes first."""
    if os.sep in name or "/" in name:
        return Path(name) if shebang(Path(name)) else None
    exts = os.environ.get("PATHEXT", ".EXE;.CMD;.BAT").split(os.pathsep)
    for folder in (search if search is not None else os.environ.get("PATH", "")).split(os.pathsep):
        if not folder:
            continue
        candidate = Path(folder) / name
        if shebang(candidate):
            return candidate
        if any((Path(folder) / (name + ext)).is_file() for ext in exts):
            return None
    return None


def child_env(env: dict | None) -> dict | None:
    """A child's env with what Windows needs to start a process, and USERPROFILE following a test's HOME, so a
    colony the test starts keeps out of the real home as it does on POSIX."""
    if env is not None:
        env = {**{k: os.environ[k] for k in KEEP if k in os.environ and k not in env}, **env}
    home = (env if env is not None else os.environ).get("HOME")
    if home and home != SESSION_HOME:
        env = {**(env if env is not None else os.environ), "USERPROFILE": home}
    return env


def through_bash(program: str, args: list, env: dict | None) -> tuple[list[str], dict]:
    """Git's bash running `program` with `args`, which ride in the environment (REBUILD)."""
    env = dict(env if env is not None else os.environ)
    env.update({"STUB_PROGRAM": program, "STUB_ARGC": str(len(args)),
                **{f"STUB_ARG_{i}": os.fspath(arg) for i, arg in enumerate(args, 1)}})
    return [BASH, "-c", REBUILD], env


class StubPopen(REAL_POPEN):
    """Popen that runs a `#!` stub through its interpreter, hands Git's bash its arguments through the environment,
    and gives a test's child the env it needs."""

    def __init__(self, args, *rest, **kwargs):
        env = child_env(kwargs.get("env"))
        if not kwargs.get("shell") and isinstance(args, (list, tuple)) and args:
            name = os.fspath(args[0])
            stub = find(name, (env or os.environ).get("PATH"))
            if stub and "python" in (shebang(stub) or ""):
                args = [sys.executable, "-c", PYTHON_STUB, str(stub), *args[1:]]
            elif stub and BASH:
                args, env = through_bash("sh", [str(stub), *args[1:]], env)
            elif name in MSYS_SHELLS and BASH:
                args, env = through_bash(name, list(args[1:]), env)
        kwargs["env"] = env
        super().__init__(args, *rest, **kwargs)


def which(cmd, mode=os.F_OK | os.X_OK, path=None):
    stub = find(os.fspath(cmd), path)
    return str(stub) if stub else REAL_WHICH(cmd, mode, path)


def install(patch) -> None:
    """Install the shim with `patch(target, name, value)`: monkeypatch.setattr in a test, setattr in a child."""
    patch(ntpath, "expanduser", expanduser)
    patch(subprocess, "Popen", StubPopen)
    patch(shutil, "which", which)
