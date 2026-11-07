"""Tests for the Claude Code plugin: .claude-plugin/ at the top of the repo names one plugin, puffin-colony, whose
skills are colony/skills/ and whose hooks file is colony/hooks/hooks.json, the hooks `colony hooks install` writes."""
import json
from pathlib import Path

from colony import __version__, cli, guards

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
MARKETPLACE = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())


def test_the_marketplace_names_the_one_plugin_at_the_top_of_the_repo():
    assert [(p["name"], p["source"]) for p in MARKETPLACE["plugins"]] == [("puffin-colony", "./")]
    assert PLUGIN["name"] == "puffin-colony"


def test_the_plugin_ships_colonys_own_skills_and_hooks():
    skills = ROOT / PLUGIN["skills"]
    assert skills == ROOT / "colony" / "skills/"
    assert {name for name in cli.ROLE_SKILLS + (cli.SETUP_SKILL,)} <= {p.parent.name for p in skills.glob("*/SKILL.md")}
    assert ROOT / PLUGIN["hooks"] == ROOT / "colony" / guards.PLUGIN_HOOKS


def test_the_plugins_hooks_file_holds_the_hooks_colony_hooks_install_writes():
    shipped = json.loads((ROOT / "colony" / guards.PLUGIN_HOOKS).read_text())
    assert shipped == guards.plugin_hooks(), "regenerate colony/hooks/hooks.json from guards.plugin_hooks()"
    installed = {event for event, *_ in guards.hook_entries()}
    assert set(shipped["hooks"]) == installed
    guard = shipped["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert '"${CLAUDE_PLUGIN_ROOT}/colony/hooks/wait_guard.py"' in guard and (ROOT / "colony/hooks/wait_guard.py").exists()


def test_the_plugin_carries_colonys_version():
    assert PLUGIN["version"] == MARKETPLACE["plugins"][0]["version"] == __version__


def run_first_run(tmp_path, with_colony: bool):
    """Run the plugin's first-run hook through sh, with a PATH that has `colony` on it or not."""
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if with_colony:
        (bin_dir / "colony").write_text("#!/bin/sh\nexit 0\n")
        (bin_dir / "colony").chmod(0o755)
    hooks = json.loads((ROOT / "colony" / guards.PLUGIN_HOOKS).read_text())["hooks"]["SessionStart"]
    command = next(h["command"] for group in hooks for h in group["hooks"] if "systemMessage" in h["command"])
    return subprocess.run(["sh", "-c", command], capture_output=True, text=True,
                          env={"PATH": f"{bin_dir}:/usr/bin:/bin"})


def test_the_first_run_names_the_install_command_when_colony_is_missing(tmp_path):
    run = run_first_run(tmp_path, with_colony=False)
    assert run.returncode == 0
    event = json.loads(run.stdout)
    line = f"uv tool install git+https://github.com/puffin-ai/puffin-colony@v{__version__}"
    assert event["systemMessage"].endswith(f"Run: {line}")
    assert f"Tell the person to run `{line}` themselves, and install nothing" in \
        event["hookSpecificOutput"]["additionalContext"]


def test_the_first_run_says_nothing_once_colony_is_installed(tmp_path):
    run = run_first_run(tmp_path, with_colony=True)
    assert (run.returncode, run.stdout, run.stderr) == (0, "", "")
