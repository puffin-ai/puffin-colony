"""Symbolic links git wrote as plain text files, as it does on Windows with core.symlinks false: `colony` and `colony
join` say so in one line, and `colony fix-links` turns them back into links in the repo and every worktree, keeping an
edited one. The repos here hold their links only in the index, so the suite builds them on any system."""
import subprocess
from pathlib import Path

import pytest

from colony import cli, portable

LINKS = {"rules/a.md": "../shared/a.md", "skills/tool": "../shared/tool"}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    """A repo with core.symlinks false, a file link and a folder link, both checked out as one-line text files."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "core.symlinks", "false")
    (root / "shared" / "tool").mkdir(parents=True)
    (root / "shared" / "a.md").write_text("rule a\n")
    (root / "shared" / "tool" / "SKILL.md").write_text("skill\n")
    git(root, "add", "shared")
    for path, target in LINKS.items():
        blob = subprocess.run(["git", "-C", str(root), "hash-object", "-w", "--stdin"], input=target,
                              capture_output=True, text=True, check=True).stdout.strip()
        git(root, "update-index", "--add", "--cacheinfo", f"{portable.LINK_MODE},{blob},{path}")
    git(root, "commit", "-q", "-m", "links")
    git(root, "checkout", "-q", "--", ".")
    return root


def plain(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def test_the_fixture_checks_links_out_as_text_files(repo):
    assert plain(repo / "rules" / "a.md")
    assert (repo / "rules" / "a.md").read_text() == "../shared/a.md"
    assert portable.index_links(repo).keys() == LINKS.keys()
    assert sorted(portable.stubs(repo, portable.index_links(repo))) == sorted(LINKS)


def test_repair_restores_untouched_stubs_in_every_worktree_and_keeps_an_edited_one(repo, tmp_path):
    if not portable.can_symlink():
        pytest.skip("this computer can't make symbolic links: Windows without Developer Mode")
    second = tmp_path / "second"
    git(repo, "worktree", "add", "-q", "--detach", str(second))
    assert plain(second / "skills" / "tool")
    (repo / "rules" / "a.md").write_text("my own notes")

    report = portable.repair_links(repo)

    assert git(repo, "config", "--bool", "core.symlinks").strip() == "true"
    assert report["checkouts"] == 2
    assert report["restored"] == 3
    assert report["edited"] == [str(repo / "rules" / "a.md")]
    assert (repo / "rules" / "a.md").read_text() == "my own notes"
    assert (repo / "skills" / "tool").is_symlink()
    assert (repo / "skills" / "tool" / "SKILL.md").read_text() == "skill\n"
    assert (second / "rules" / "a.md").is_symlink()
    assert (second / "rules" / "a.md").read_text() == "rule a\n"
    assert (second / "skills" / "tool" / "SKILL.md").read_text() == "skill\n"
    assert git(second, "status", "--porcelain") == ""
    assert git(repo, "status", "--porcelain").strip() == "T rules/a.md"

    again = portable.repair_links(repo)
    assert (again["restored"], again["already"]) == (0, 3)


def test_the_note_names_the_stubs_and_the_fix_on_windows(repo, monkeypatch):
    monkeypatch.setattr(portable, "WINDOWS", True)
    monkeypatch.setattr(portable, "can_symlink", lambda: True)
    note = portable.links_note(repo)
    assert "2 of this repo's 2 symbolic links are plain text files" in note
    assert "run `colony fix-links`" in note and "Developer Mode" not in note
    assert "\n" not in note

    monkeypatch.setattr(portable, "can_symlink", lambda: False)
    assert "turn on Developer Mode" in portable.links_note(repo)


def test_the_note_is_quiet_off_windows_and_where_links_are_fine(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(portable, "WINDOWS", False)
    assert portable.links_note(repo) == ""
    monkeypatch.setattr(portable, "WINDOWS", True)
    plain_repo = tmp_path / "plain"
    plain_repo.mkdir()
    git(plain_repo, "init", "-q")
    assert portable.links_note(plain_repo) == ""


def test_fix_links_does_nothing_on_macos_and_linux(repo, monkeypatch, capsys):
    monkeypatch.setattr(portable, "WINDOWS", False)
    monkeypatch.chdir(repo)
    assert cli.main(["fix-links"]) == 0
    assert "nothing to do" in capsys.readouterr().out
    assert git(repo, "config", "--bool", "core.symlinks").strip() == "false"
    assert plain(repo / "rules" / "a.md")


def test_fix_links_changes_nothing_when_links_cant_be_made(repo, monkeypatch, capsys):
    monkeypatch.setattr(portable, "WINDOWS", True)
    monkeypatch.setattr(portable, "can_symlink", lambda: False)
    monkeypatch.chdir(repo)
    assert cli.main(["fix-links"]) == 2
    assert "Developer Mode" in capsys.readouterr().err
    assert git(repo, "config", "--bool", "core.symlinks").strip() == "false"
    assert plain(repo / "rules" / "a.md")


def test_fix_links_prints_the_counts_and_the_kept_file(repo, monkeypatch, capsys):
    if not portable.can_symlink():
        pytest.skip("this computer can't make symbolic links: Windows without Developer Mode")
    monkeypatch.setattr(portable, "WINDOWS", True)
    monkeypatch.chdir(repo)
    (repo / "rules" / "a.md").write_text("my own notes")
    assert cli.main(["fix-links"]) == 0
    out = capsys.readouterr().out
    assert "Restored 1 links in 1 checkouts" in out
    assert "Kept 1 edited" in out and str(repo / "rules" / "a.md") in out


@pytest.mark.parametrize("argv", [[], ["join"]])
def test_colony_and_join_warn_first(argv, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "warn_links", lambda: seen.append("warned"))
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(cli, "here", lambda args: seen.append("here") or 0)
    monkeypatch.setattr(cli, "join", lambda config, args: seen.append("join") or 0)
    monkeypatch.setattr(cli, "load_config", lambda path=None: {"features": {}})
    assert cli.main(argv) == 0
    assert seen == ["warned", "join" if argv else "here"]


def test_warn_links_prints_the_note_on_stderr(repo, monkeypatch, capsys):
    monkeypatch.setattr(portable, "WINDOWS", True)
    monkeypatch.setattr(portable, "can_symlink", lambda: True)
    monkeypatch.chdir(repo)
    cli.warn_links()
    assert "colony fix-links" in capsys.readouterr().err
