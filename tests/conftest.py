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
