"""Tests for setup's extras: the puffin preset's shipped files, the role skills, and the tools setup writes."""
import json
import re
import subprocess
from importlib import resources
from pathlib import Path

import pytest

from colony import cli

PACKAGE = Path(str(resources.files("colony")))
PUFFIN = PACKAGE / "presets" / "puffin"
RULES = ("performance", "full-stack", "accessibility", "coding", "design-principles", "testing",
         "performance-service", "security-and-privacy", "database", "commits", "pull-requests", "writing")
PLACEHOLDER = re.compile(r"\{([A-Za-z_][\w-]*)\}")


def preset_files():
    """Every file the puffin preset ships."""
    return sorted(path for path in PUFFIN.rglob("*") if path.is_file())


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A fresh git repo to run in, with no .colony folder, and a PATH whose stub folder comes first."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")
    monkeypatch.chdir(root)
    return root.resolve()


def test_the_preset_files_hold_no_vault_links_no_glass_and_no_product_name():
    for path in preset_files():
        text = path.read_text()
        assert "[[" not in text, path
        assert "glass" not in text.lower(), path
        assert "puffin calendar" not in text.lower(), path
        assert not re.search(r"apps/(web|backend)|puffin\.", text), path  # Puffin's own paths and modules


def test_every_placeholder_in_the_preset_is_in_the_known_set():
    used = {name for path in preset_files() for name in PLACEHOLDER.findall(path.read_text())}
    assert used <= set(cli.PRESET_PLACEHOLDERS), used - set(cli.PRESET_PLACEHOLDERS)
    assert used == set(cli.PRESET_PLACEHOLDERS)  # a known placeholder no file uses would be dead


def test_the_setup_prompt_names_every_preset_placeholder_and_ends_with_the_three_lines():
    prompt = cli.fill_names(cli.package_file("prompts", "setup.md"))
    for name in cli.PRESET_PLACEHOLDERS:
        assert f"`{{{name}}}`" in prompt
    assert "run `colony tools` and keep what it prints" in prompt
    assert "You're set: wrote" in prompt and "Pull request: <the PR link>" in prompt
    assert "Run `colony` to start." in prompt
    for rule in RULES:
        assert f"`{rule}.md`" in prompt


def test_merging_into_mcp_json_keeps_the_entries_already_there(tmp_path):
    path = tmp_path / ".mcp.json"
    mine = {"command": "my-playwright"}
    path.write_text(json.dumps({"mcpServers": {"github": {"type": "http", "url": "https://x"}, "playwright": mine},
                                "other": 1}))
    assert cli.merge_mcp(path, ["playwright", "context7"]) == ["context7"]
    data = json.loads(path.read_text())
    assert data["other"] == 1
    assert data["mcpServers"]["github"] == {"type": "http", "url": "https://x"}
    assert data["mcpServers"]["playwright"] == mine
    assert data["mcpServers"]["context7"] == cli.MCP_SERVERS["context7"]


def test_merging_into_a_missing_mcp_json_creates_it(tmp_path):
    path = tmp_path / ".mcp.json"
    assert cli.merge_mcp(path, ["playwright"]) == ["playwright"]
    assert json.loads(path.read_text()) == {"mcpServers": {"playwright": cli.MCP_SERVERS["playwright"]}}


def test_a_broken_mcp_json_is_left_as_it_is(tmp_path):
    path = tmp_path / ".mcp.json"
    path.write_text("{not json")
    with pytest.raises(cli.ColonyError, match="is not valid JSON"):
        cli.merge_mcp(path, ["context7"])
    assert path.read_text() == "{not json"


def test_tools_without_names_prints_the_list_before_any_config_exists(repo, capsys):
    assert cli.main(["tools"]) == 0
    out = capsys.readouterr().out
    for name, (default, _) in cli.TOOLS.items():
        assert re.search(rf"^  {name} +\[{default}\] ", out, re.M), name
    assert "npx downloads @playwright/mcp" in out


def test_tools_writes_the_mcp_servers_and_the_role_skills(repo, capsys):
    assert cli.main(["tools", "playwright", "context7", "role-skills"]) == 0
    servers = json.loads((repo / ".mcp.json").read_text())["mcpServers"]
    assert set(servers) == {"playwright", "context7"}
    for name in cli.ROLE_SKILLS:
        copied = repo / ".claude" / "skills" / name / "SKILL.md"
        assert copied.read_text() == (PACKAGE / "skills" / name / "SKILL.md").read_text()
    out = capsys.readouterr().out
    assert '[tools]\nmcp = ["playwright", "context7"]\nskills = ["colony-lead", ' in out


def test_tools_dry_run_writes_nothing(repo, capsys):
    assert cli.main(["tools", "context7", "role-skills", "--dry-run"]) == 0
    assert "Nothing ran." in capsys.readouterr().out
    assert not (repo / ".mcp.json").exists() and not (repo / ".claude").exists()


def test_an_unknown_tool_is_refused(repo, capsys):
    assert cli.main(["tools", "playwright", "sparkles"]) == 2
    assert "'sparkles' is not a tool" in capsys.readouterr().err
    assert not (repo / ".mcp.json").exists()


def test_an_outside_skill_downloads_at_its_pinned_commit(repo, capsys):
    bin_dir = repo.parent / "bin"
    bin_dir.mkdir()
    log = bin_dir / "gh.log"
    listing = json.dumps([{"name": "SKILL.md", "path": "skills/frontend-design/SKILL.md", "type": "file"}])
    stub = bin_dir / "gh"
    stub.write_text(f"#!/bin/sh\necho \"$*\" >> \"{log}\"\n"
                    f"case \"$*\" in *raw*) printf 'skill text' ;; *) printf '%s' '{listing}' ;; esac\n")
    stub.chmod(0o755)
    assert cli.main(["tools", "ui-design"]) == 0
    assert (repo / ".claude" / "skills" / "frontend-design" / "SKILL.md").read_text() == "skill text"
    commit = cli.OUTSIDE_SKILLS["ui-design"][1]
    calls = log.read_text().splitlines()
    assert len(calls) == 2 and all(f"?ref={commit}" in call for call in calls)


def test_each_role_skill_names_itself_triggers_on_its_role_and_points_to_the_playbook():
    for name in cli.ROLE_SKILLS:
        text = (PACKAGE / "skills" / name / "SKILL.md").read_text()
        front = re.match(r"---\n(.*?)\n---\n", text, re.S)
        assert front, name
        fields = dict(line.split(": ", 1) for line in front[1].splitlines())
        assert fields["name"] == name
        assert "Use when" in fields["description"], name
        assert ".colony/playbook.md" in text[front.end():]
