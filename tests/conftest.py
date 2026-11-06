"""Shared test setup."""
import pytest


@pytest.fixture(autouse=True)
def outside_claude_code(monkeypatch):
    """Run each test as if from a terminal: the suite itself may run inside a Claude Code session, whose $CLAUDECODE
    would make plain `colony` take the in-session path. A test that wants that path sets it."""
    monkeypatch.delenv("CLAUDECODE", raising=False)
