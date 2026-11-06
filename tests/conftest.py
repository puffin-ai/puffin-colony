"""Shared test setup: the first-run skill install stays off, so no test writes to the real Claude settings folder."""
import pytest

from colony import cli

REAL_FIRST_RUN = cli.first_run


@pytest.fixture(autouse=True)
def no_first_run(monkeypatch):
    monkeypatch.setattr(cli, "first_run", lambda: None)
