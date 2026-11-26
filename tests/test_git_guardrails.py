"""Tests for the script the git-guardrails skill writes, run exactly as the skill ships it."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent / "colony" / "skills" / "git-guardrails" / "SKILL.md"


@pytest.fixture
def guard(tmp_path):
    """The skill's script, written out as its steps say, run with a call on stdin: its exit code."""
    [script] = re.findall(r"```python\n(.*?)```", SKILL.read_text(), re.S)
    path = tmp_path / "git_guard.py"
    path.write_text(script)

    def run(command: str) -> int:
        return subprocess.run([sys.executable, str(path)], input=json.dumps({"tool_input": {"command": command}}),
                              capture_output=True, text=True, env={"CLAUDE_PROJECT_DIR": str(tmp_path)}).returncode
    return run


def test_the_skills_guard_lets_a_builder_push_its_branch_in_the_allowed_form_and_refuses_the_base(guard):
    """Regression: the base rule read only `:main` or ` main`, so `HEAD:refs/heads/main`, the full form Colony's push
    guard asks for, reached the base past it."""
    assert guard("git push -u origin HEAD:refs/heads/builder-1/12") == 0
    assert guard("git push --force origin x") == 2
    for push in ("git push origin HEAD:refs/heads/main", "git push origin main", "git push origin HEAD:main"):
        assert guard(push) == 2, push
    assert guard("git push -u origin HEAD:refs/heads/feature/main-menu") == 0
