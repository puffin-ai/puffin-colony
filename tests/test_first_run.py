"""Tests for the first run on a computer: `colony` installs the colony-setup skill once, with no extra command."""
from importlib import resources
from pathlib import Path

from colony import cli

from conftest import REAL_FIRST_RUN

PACKAGE = Path(str(resources.files("colony")))


def test_the_first_run_installs_the_setup_skill_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "first_run", REAL_FIRST_RUN)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["tools"]) == 0  # no Claude settings folder yet: nothing written, no marker
    assert not (tmp_path / ".claude").exists()

    (tmp_path / ".claude").mkdir()
    assert cli.main(["tools"]) == 0
    skill = tmp_path / ".claude" / "skills" / "colony-setup" / "SKILL.md"
    assert skill.read_text() == (PACKAGE / "skills" / "colony-setup" / "SKILL.md").read_text()
    assert (tmp_path / ".claude" / cli.FIRST_RUN).exists()
    assert "installed the colony-setup skill" in capsys.readouterr().err

    skill.parent.joinpath("SKILL.md").unlink()  # the person removed it: the next run leaves it removed
    assert cli.main(["tools"]) == 0
    assert not skill.exists()
    assert "installed" not in capsys.readouterr().err


def test_the_first_run_uses_the_settings_folder_claude_config_dir_names(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "first_run", REAL_FIRST_RUN)
    folder = tmp_path / "work"
    folder.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(folder))
    monkeypatch.chdir(tmp_path)
    assert cli.main(["tools"]) == 0
    assert (folder / "skills" / "colony-setup" / "SKILL.md").exists()
    assert (folder / cli.FIRST_RUN).exists()
