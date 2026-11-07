"""Tests for the Claude Code plugin: .claude-plugin/ at the top of the repo names one plugin, puffin-colony, whose
skills are colony/skills/ and whose hooks file is colony/hooks/hooks.json, the hooks `colony hooks install` writes."""
import json
import os
import shutil
import subprocess
import sys
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


def test_the_plugins_hooks_run_the_plugins_own_colony():
    hooks = json.loads((ROOT / "colony" / guards.PLUGIN_HOOKS).read_text())["hooks"]
    for event in ("Notification", "StopFailure", "UserPromptSubmit"):
        command = hooks[event][0]["hooks"][0]["command"]
        assert '"${CLAUDE_PLUGIN_ROOT}/bin/colony" hooks' in command and " colony hooks" not in command


def run_bin(*args, cwd, env=None):
    return subprocess.run([str(ROOT / "bin" / "colony"), *args], capture_output=True, text=True, cwd=cwd,
                          env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], **(env or {})}, timeout=120)


def test_the_plugins_bin_runs_colony_from_the_plugins_own_copy(tmp_path):
    shadow = tmp_path / "colony"  # a repo with its own colony folder must not shadow the package
    shadow.mkdir()
    (shadow / "__main__.py").write_text('raise SystemExit("shadowed")\n')
    run = run_bin("--version", cwd=tmp_path)
    assert (run.returncode, run.stdout.strip()) == (0, f"{cli.DISPLAY} {__version__}")


def test_the_plugins_bin_is_no_uvx_run_that_installs_colony_for_good(tmp_path):
    """bin/colony runs the plugin's copy in place, outside any active virtualenv, so cli.install_permanently never
    fires a `uv tool install`: not even from inside a uvx run, such as this test's own."""
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "uv").write_text('#!/bin/sh\nprintf "%s|" "VIRTUAL_ENV=$VIRTUAL_ENV" "$@"\n')
    (fake / "uv").chmod(0o755)
    run = run_bin("--version", cwd=tmp_path, env={"PATH": f"{fake}:/usr/bin:/bin", "VIRTUAL_ENV": sys.prefix})
    assert run.stdout == "VIRTUAL_ENV=|run|-q|--no-project|--python|>=3.11|python|-P|-m|colony|--version|"
    probe = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); from colony import cli; "
             f"print(bool(cli.EPHEMERAL.search(sys.prefix)))")
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    run = subprocess.run([shutil.which("uv"), "run", "-q", "--no-project", "--python", ">=3.11", "python", "-P", "-c",
                          probe], capture_output=True, text=True, cwd=tmp_path, env=env, timeout=120)
    assert run.stdout.strip() == "False"


def test_the_plugins_bin_finds_uv_where_astrals_installer_puts_it(tmp_path):
    home_bin = tmp_path / ".local" / "bin"
    home_bin.mkdir(parents=True)
    (home_bin / "uv").symlink_to(shutil.which("uv"))
    run = run_bin("--version", cwd=tmp_path, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert run.stdout.strip() == f"{cli.DISPLAY} {__version__}"


def test_the_plugins_bin_says_how_to_get_uv_when_there_is_none(tmp_path):
    run = run_bin("--version", cwd=tmp_path, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert run.returncode == 127 and "uv is not installed" in run.stderr


def run_first_run(tmp_path, curl: str | None = None, uv: bool = False):
    """Run the plugin's first-run hook through sh, in a HOME and PATH of its own: with uv on PATH or not, and with a
    stand-in curl that serves the `curl` script as Astral's installer."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    for name, body in (("uv", "exit 0" if uv else None), ("curl", curl)):
        if body is not None:
            (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
            (bin_dir / name).chmod(0o755)
    hooks = json.loads((ROOT / "colony" / guards.PLUGIN_HOOKS).read_text())["hooks"]["SessionStart"]
    command = next(h["command"] for group in hooks for h in group["hooks"] if guards.UV_INSTALLER in h["command"])
    run = subprocess.run(["sh", "-c", command], capture_output=True, text=True,
                         env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(home)}, timeout=60)
    return run, home


INSTALLER = ('echo "mkdir -p \\$HOME/.local/bin; printf \'#!/bin/sh\\n\' > \\$HOME/.local/bin/uv; '
             'chmod +x \\$HOME/.local/bin/uv"')  # a stand-in installer script that puts uv where Astral's does


def test_the_first_run_installs_uv_with_astrals_installer_and_says_so(tmp_path):
    run, home = run_first_run(tmp_path, curl=f'[ "$2" = "{guards.UV_INSTALLER}" ] && {INSTALLER}')
    assert run.returncode == 0 and (home / ".local" / "bin" / "uv").exists()
    event = json.loads(run.stdout)
    assert event["systemMessage"].startswith(f"{cli.DISPLAY} installed uv") and "\n" not in event["systemMessage"]
    assert event["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_the_first_run_says_so_when_uv_could_not_be_installed(tmp_path):
    run, home = run_first_run(tmp_path, curl="exit 6")
    assert run.returncode == 0
    assert json.loads(run.stdout)["systemMessage"].startswith(f"{cli.DISPLAY} could not install uv")


def test_the_first_run_says_nothing_when_uv_is_there(tmp_path):
    run, _ = run_first_run(tmp_path, curl="touch called; exit 1", uv=True)
    assert (run.returncode, run.stdout, run.stderr) == (0, "", "")
    assert not (tmp_path / "called").exists()


def run_plugin_hook(tmp_path, event: str, repo_hooks: bool, colony_on_path: bool):
    """Run the plugin's `event` hook through sh in a project of its own, whose settings carry the hooks `colony hooks
    install` writes or not, with a `colony` on PATH or not. Each colony, the plugin's and the PATH one, writes its
    name to `ran` when it runs."""
    project, plugin, path_bin = tmp_path / "project", tmp_path / "plugin", tmp_path / "path"
    for folder in (project / ".claude", project / cli.DIR / "hooks", plugin / "bin", plugin / "colony" / "hooks",
                   path_bin):
        folder.mkdir(parents=True)
    ran = tmp_path / "ran"
    for program, name in ((plugin / "bin" / "colony", "plugin"), (path_bin / "colony", "path")):
        program.write_text(f"#!/bin/sh\necho {name} >> {ran}\n")
        program.chmod(0o755)
    for guard in (plugin / "colony" / "hooks" / guards.GUARD, project / cli.DIR / "hooks" / guards.GUARD):
        guard.write_text(f"open({str(ran)!r}, 'a').write({guard.parts[-4]!r} + '\\n')\n")
    if repo_hooks:
        settings = {"hooks": {}}
        for repo_event, matcher, hook, _ in guards.hook_entries():
            settings["hooks"].setdefault(repo_event, []).append({"hooks": [hook]})
        (project / ".claude" / "settings.json").write_text(json.dumps(settings))
    hooks = json.loads((ROOT / "colony" / guards.PLUGIN_HOOKS).read_text())["hooks"][event]
    command = hooks[0]["hooks"][0]["command"]
    path = f"{path_bin}:/usr/bin:/bin" if colony_on_path else "/usr/bin:/bin"
    subprocess.run(["sh", "-c", command], input="{}", capture_output=True, text=True, timeout=60,
                   env={"PATH": path, "CLAUDE_PROJECT_DIR": str(project), "CLAUDE_PLUGIN_ROOT": str(plugin),
                        cli.SESSION_ENV: "builder-1"})
    return ran.read_text().split() if ran.exists() else []


def test_the_plugins_hooks_step_aside_where_the_repos_own_hooks_run(tmp_path):
    for event in ("Notification", "StopFailure", "UserPromptSubmit", "SessionStart"):
        assert run_plugin_hook(tmp_path / event, event, repo_hooks=True, colony_on_path=True) == []
    assert run_plugin_hook(tmp_path / "guard", "PreToolUse", repo_hooks=True, colony_on_path=False) == []


def test_the_plugins_hooks_run_where_the_repos_own_hooks_cannot(tmp_path):
    for event in ("Notification", "StopFailure", "UserPromptSubmit", "SessionStart"):
        assert run_plugin_hook(tmp_path / f"{event}-no-path", event, repo_hooks=True, colony_on_path=False) == ["plugin"]
        assert run_plugin_hook(tmp_path / f"{event}-no-repo", event, repo_hooks=False, colony_on_path=True) == ["plugin"]
    assert run_plugin_hook(tmp_path / "guard", "PreToolUse", repo_hooks=False, colony_on_path=True) == ["plugin"]
