"""Shared test setup: each test runs as if from a terminal, with the first-run skill install off, so no test writes
to the real Claude settings folder."""
import pytest

from colony import cli

REAL_FIRST_RUN = cli.first_run


@pytest.fixture(autouse=True)
def no_first_run(monkeypatch):
    monkeypatch.setattr(cli, "first_run", lambda: None)


@pytest.fixture(autouse=True)
def outside_claude_code(monkeypatch):
    """The suite may run inside a Claude Code session, whose $CLAUDECODE would make plain `colony` take the
    in-session path. A test that wants that path sets it."""
    monkeypatch.delenv("CLAUDECODE", raising=False)


@pytest.fixture(autouse=True)
def with_the_retry_watchdog(monkeypatch):
    """Every Colony session runs with CLAUDE_CODE_RETRY_WATCHDOG=1, so the prompt hook's once-a-day note stays out of
    a test that doesn't ask for it, wherever the suite runs."""
    monkeypatch.setenv("CLAUDE_CODE_RETRY_WATCHDOG", "1")


@pytest.fixture(autouse=True)
def no_usage_refresh(monkeypatch):
    """No test runs the real `claude -p /usage`. A test of refresh_usage clears this and puts a stub on PATH."""
    monkeypatch.setenv(cli.NO_REFRESH_ENV, "1")
