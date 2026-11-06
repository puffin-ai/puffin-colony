"""Tests for the npm wrapper, npm/bin/colony.js: it passes the arguments on, tries uvx first and python3 second, and
says how to install uv when neither works. Each stub records its arguments, and PATH holds the stubs alone."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parent.parent / "npm" / "bin" / "colony.js"
NODE = shutil.which("node")
STUB = """#!/bin/sh
printf '%s|' {name} "$@" >> "{log}"
printf '\\n' >> "{log}"
{body}
"""

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")
SH_STUBS = pytest.mark.skipif(os.name == "nt", reason="the stand-in uvx and python3 are sh scripts, which node "
                              "starts only on macOS and Linux")


def stub(bin_dir: Path, name: str, body: str = "exit 0") -> None:
    path = bin_dir / name
    path.write_text(STUB.format(name=name, log=bin_dir.parent / "calls.log", body=body))
    path.chmod(0o755)


def calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "calls.log"
    return [line.split("|")[:-1] for line in log.read_text().splitlines()] if log.exists() else []


def wrapper(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([NODE, str(WRAPPER), *args], capture_output=True, text=True,
                          env={"PATH": str(tmp_path / "bin"), "HOME": str(tmp_path)})


@pytest.fixture
def bin_dir(tmp_path):
    (tmp_path / "bin").mkdir()
    return tmp_path / "bin"


@SH_STUBS
def test_uvx_runs_first_with_every_argument_as_given(tmp_path, bin_dir):
    stub(bin_dir, "uvx", "exit 3")
    stub(bin_dir, "python3")
    run = wrapper(tmp_path, "open", "builder-2", "a task with  spaces", "--dry-run")
    assert run.returncode == 3  # uvx's exit code is the wrapper's
    assert calls(tmp_path) == [["uvx", "puffin-colony", "open", "builder-2", "a task with  spaces", "--dry-run"]]


@SH_STUBS
def test_python3_runs_when_uvx_is_missing_and_colony_is_installed(tmp_path, bin_dir):
    stub(bin_dir, "python3")
    run = wrapper(tmp_path, "hi", "--person", "ana")
    assert run.returncode == 0, run.stderr
    assert calls(tmp_path) == [["python3", "-c", "import colony.cli"],
                               ["python3", "-m", "colony", "hi", "--person", "ana"]]


@SH_STUBS
def test_neither_way_prints_one_line_on_installing_uv(tmp_path, bin_dir):
    stub(bin_dir, "python3", 'case "$1" in -c) exit 1;; esac')  # python3 without the colony package
    run = wrapper(tmp_path, "hi")
    assert run.returncode == 127
    assert run.stdout == ""
    assert run.stderr.count("\n") == 1 and "install it with `curl -LsSf https://astral.sh/uv/install.sh | sh`" in run.stderr
    assert calls(tmp_path) == [["python3", "-c", "import colony.cli"]]


def test_the_package_has_both_commands_and_no_dependencies():
    package = json.loads((WRAPPER.parent.parent / "package.json").read_text())
    assert package["name"] == "puffin-colony" and package["license"] == "MIT"
    assert package["bin"] == {"colony": "bin/colony.js", "puffin-colony": "bin/colony.js"}
    assert "dependencies" not in package


def test_the_npm_version_is_the_python_version():
    from colony import __version__
    assert json.loads((WRAPPER.parent.parent / "package.json").read_text())["version"] == __version__
