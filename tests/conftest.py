"""Shared test setup: each test runs as if from a terminal, with the first-run skill install off, so no test writes
to the real Claude settings folder.

On Windows, one more fixture installs tests/winshim.py, which lets the suite's POSIX habits work unchanged; macOS
and Linux never define it."""
import os
import shutil
import sys
from pathlib import Path

import pytest

from colony import cli, portable

REAL_FIRST_RUN = cli.first_run


def system_path() -> list[str]:
    """The folders of the system's own tools, with no real gh, claude or cmux: /usr/bin and /bin on POSIX. On Windows,
    git's folder, the folder of Git's coreutils that a stub script calls, and Windows' own."""
    if not portable.WINDOWS:
        return ["/usr/bin", "/bin"]
    folders = [str(Path(git).parent) for git in [shutil.which("git")] if git]
    bash = portable.git_bash()
    if bash:
        folders.append(str(Path(bash).parent.parent / "usr" / "bin"))
    root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return [*folders, str(Path(root) / "System32"), root]


SYSTEM_PATH = system_path()


def stub_path(*folders) -> str:
    """A PATH with the stub folders first, then the system's own tools: `<folders>:/usr/bin:/bin` on POSIX."""
    return os.pathsep.join([*map(str, folders), *SYSTEM_PATH])


@pytest.fixture(autouse=True)
def no_first_run(monkeypatch):
    monkeypatch.setattr(cli, "first_run", lambda: None)


@pytest.fixture(autouse=True)
def no_cmux_app(monkeypatch, tmp_path):
    """The machine running the suite may have the cmux app, so cmux is found only where a test puts it."""
    monkeypatch.setattr(cli, "CMUX_APP", tmp_path / "no-cmux-app" / "cmux")


@pytest.fixture(autouse=True)
def outside_claude_code(monkeypatch):
    """The suite may run inside a Claude Code session, whose $CLAUDECODE would make plain `colony` take the
    in-session path, and whose $CLAUDE_CODE_SESSION_ID would save and load a session's identity. A test that wants that
    path sets them."""
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)


@pytest.fixture(autouse=True)
def outside_a_colony_session(monkeypatch):
    """The suite may run from a lead's or a builder's terminal, whose $COLONY_SESSION, $COLONY_LEAD and the rest would
    make a command act as that agent. A test that wants one sets it."""
    for name in [name for name in os.environ if name.startswith("COLONY_")]:
        monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def one_session_one_read(monkeypatch):
    """Each wait reads GitHub itself, as one session alone does, so a test's queued answers go to its own polls; a test
    of the computer's shared read turns it on."""
    from colony import wait
    monkeypatch.setattr(wait, "SHARED_POLL", False, raising=False)


@pytest.fixture(autouse=True)
def with_the_retry_watchdog(monkeypatch):
    """Every Colony session runs with CLAUDE_CODE_RETRY_WATCHDOG=1, so the prompt hook's once-a-day note stays out of
    a test that doesn't ask for it, wherever the suite runs."""
    monkeypatch.setenv("CLAUDE_CODE_RETRY_WATCHDOG", "1")


@pytest.fixture(autouse=True)
def no_usage_refresh(monkeypatch, outside_a_colony_session):  # after the clearing, which would drop it
    """No test runs the real `claude -p /usage`. A test of refresh_usage clears this and puts a stub on PATH."""
    monkeypatch.setenv(cli.NO_REFRESH_ENV, "1")


if portable.WINDOWS:
    if not sys.flags.utf8_mode:
        pytest.exit("On Windows, run the suite in Python's UTF-8 mode, the mode Colony relaunches itself in there: "
                    "uv run --with pytest python -X utf8 -m pytest tests", returncode=4)
    import winshim

    winshim.prepare_session()

    @pytest.fixture(autouse=True)
    def windows_runs_posix_stubs(monkeypatch):
        winshim.install(monkeypatch.setattr)
