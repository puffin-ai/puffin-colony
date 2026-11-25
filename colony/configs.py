"""Config layers, settings an upgrade renamed or removed, and the check settings every command follows.

Layers. Colony reads three layers, each over the one before: the mode's defaults in the package
(modes/<mode>.toml), the team's `.colony/colony.toml`, which git tracks, and this computer's own
`.colony/colony.local.toml`, which git never tracks. A key in a later layer wins, and a table merges key by key. The
local file of the main checkout counts for every worktree of the clone, and a worktree's own local file, when it has
one, counts over it. So a person's own setting, such as a time cap on the checks, never touches a tracked file, and an
upgrade or a pull never meets it. `colony config local` makes the file and keeps it out of git, and `colony config
local --from-edits` moves uncommitted edits of the tracked file into it.

Migrations. A setting a newer Colony renamed is read at its new place, and a removed one is skipped, each with a note
that names its replacement (MIGRATIONS), so an old setting never stops a command. The notes show once a day where a
lead starts and where a batch starts, and every time in `colony config`. `colony config migrate`, which `colony
upgrade` runs, rewrites the tracked file: it moves a renamed key and comments out a removed one with the reason.

Check settings. Every command that runs a check takes its scope, its areas and its time cap from `[checks]`, the way
`colony fast-check` does: `colony batch` stops a round past its kind's cap, a fast gate's round counting as `fast`,
and `colony merge` runs the fast check for the merged change in the configured scope, stopped past the `fast` cap
(merge_plan, cap).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from colony import cli

LOCAL = "colony.local.toml"
NOTES_EVERY = 24 * 3600  # a migration or worktree note shows at most once a day per project
LAST: list[str] = []  # the notes of the last load_config, which the commands that brief a person print
BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class Migration:
    """One setting a newer Colony renamed or removed: its table, "*" for any name such as a person's, and its key;
    for a rename, the table and key it moved to; for a removal, what replaces it."""

    table: tuple[str, ...]
    key: str
    to: tuple[str, ...] | None = None
    new_key: str = ""
    why: str = ""


MIGRATIONS = (
    Migration(("project",), "web_checks", why="name each check area's paths in [checks] areas, and put {areas} in "
                                              "[project] checks where the area names go"),
    Migration(("hack",), "deploy_environment", ("project",), "deploy_environment"),
    Migration(("people", "*"), "prefer_account", why="[pool] order and [people.<person>] accounts set which account "
                                                     "goes first"),
    Migration(("people", "*"), "drain", why="[pool] reserve keeps an account free, and [pool] out_at says when a "
                                            "session switches"),
)


# Layers


def label(table: tuple[str, ...]) -> str:
    return "[" + ".".join(table) + "]"


def tables(data: dict, pattern: tuple[str, ...], at: tuple[str, ...] = ()):
    """Each table of `data` whose path matches `pattern`, "*" matching any name, with its path."""
    if not pattern:
        yield at, data
        return
    names = [name for name, value in data.items() if isinstance(value, dict)] if pattern[0] == "*" else \
        [pattern[0]] if isinstance(data.get(pattern[0]), dict) else []
    for name in names:
        yield from tables(data[name], pattern[1:], (*at, name))


def migrate(layer: dict, where: str) -> list[str]:
    """Apply MIGRATIONS to one layer in place: move each renamed key to its new place, unless that is set already,
    and drop each removed key. Returns a note for each."""
    notes = []
    for m in MIGRATIONS:
        for path, table in list(tables(layer, m.table)):
            if m.key not in table:
                continue
            value = table.pop(m.key)
            if m.to is None:
                notes.append(f"{label(path)} {m.key} in {where} is gone, so {cli.NAME} skips it: {m.why}. "
                             f"`{cli.NAME} config migrate` takes it out")
                continue
            target = layer
            for name in m.to:
                target = target.setdefault(name, {})
            target.setdefault(m.new_key, value)
            notes.append(f"{label(path)} {m.key} in {where} is now {label(m.to)} {m.new_key}, and {cli.NAME} reads it "
                         f"there. `{cli.NAME} config migrate` moves it")
    return notes


def local_layers(path: Path) -> list[Path]:
    """The local files that count over the tracked config at `path`: the main checkout's, then this checkout's own,
    when the config sits in a repo's .colony/ folder."""
    from colony import folders

    path = Path(path)
    if path.parent.name != cli.DIR:
        return []
    main = folders.main_checkout(path.parent)
    places = ([main / cli.DIR / LOCAL] if main else []) + [path.parent / LOCAL]
    return [place for place in dict.fromkeys(p.resolve() for p in places) if place.is_file()]


def read(path: Path) -> dict:
    """One TOML layer, or a ColonyError that names the file."""
    try:
        return tomllib.loads(Path(path).read_text())
    except tomllib.TOMLDecodeError as e:
        raise cli.ColonyError(f"{path}: {e}") from None


def layered(own: dict, path: Path) -> dict:
    """The tracked config with its migrations applied and the local layers over it; the notes go to LAST."""
    notes = migrate(own, f"{cli.DIR}/{cli.CONFIG_NAME}")
    for local in local_layers(path):
        layer = read(local)
        notes += migrate(layer, f"{cli.DIR}/{LOCAL}")
        own = cli.merge_tables(own, layer)
    LAST[:] = notes
    return own


# Notes, once a day


def say(config: dict, extra=(), always: bool = False, out=None) -> list[str]:
    """Print the last load's migration notes and `extra` to `out`, stderr by default, each at most once a day per
    project unless `always`. Returns what it printed."""
    from colony import wait

    out = out or sys.stderr
    shown = []
    path = wait.state_path(config["project"]["name"], "config-notes")
    seen = wait.read_json(path, {})
    seen = seen if isinstance(seen, dict) else {}
    now = time.time()
    for note in [*LAST, *extra]:
        if always or now - float(seen.get(note) or 0) >= NOTES_EVERY:
            print(f"{cli.NAME}: {note}.", file=out)
            seen[note] = now
            shown.append(note)
    if shown and not always:
        try:
            wait.write_json(path, {note: at for note, at in seen.items() if now - at < 7 * NOTES_EVERY})
        except OSError:
            pass
    return shown


def briefing(config: dict, start: Path | None = None) -> list[str]:
    """Everything a person should hear about the config: the migration notes, the worktrees notes, and a local file
    git tracks."""
    from colony import folders

    lines = list(LAST)
    try:
        lines += folders.notes(config, start)
        root = (start or cli.repo_root()).resolve()
        for place in local_layers(cli.config_path()):
            relative = place.relative_to(root) if place.is_relative_to(root) else None
            if relative and not subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch",
                                                relative.as_posix()], capture_output=True).returncode:
                lines.append(f"{relative.as_posix()} is tracked by git, so an upgrade or a pull can meet it: "
                             f"`git rm --cached {relative.as_posix()}`, then commit")
    except (cli.ColonyError, OSError):
        pass
    return lines


# Writing TOML: the local file's keys


def key_text(key: str) -> str:
    return key if BARE_KEY.fullmatch(key) else json.dumps(key)


def value_text(value) -> str:
    """A TOML value: strings as basic strings, whose escapes JSON's are, lists as arrays, tables as inline tables."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(value_text(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{key_text(k)} = {value_text(v)}" for k, v in value.items()) + " }" if value else "{}"
    return value.isoformat()


def leaves(data: dict, at: tuple[str, ...] = ()) -> dict[tuple[str, ...], object]:
    """Every key of a config that holds a value rather than a table, by its path."""
    found = {}
    for key, value in data.items():
        if isinstance(value, dict) and value:
            found.update(leaves(value, (*at, key)))
        else:
            found[(*at, key)] = value
    return found


def dump(data: dict, header: str = "") -> str:
    """A config as TOML text: its top-level keys, then one table per table path."""
    groups: dict[tuple[str, ...], list[str]] = {}
    for path, value in leaves(data).items():
        groups.setdefault(path[:-1], []).append(f"{key_text(path[-1])} = {value_text(value)}")
    lines = [header] if header else []
    for table in sorted(groups, key=lambda t: (len(t) > 0, t)):
        if table:
            lines += ["", "[" + ".".join(key_text(name) for name in table) + "]"]
        lines += groups[table]
    return "\n".join(lines).strip("\n") + "\n"


def differences(old: dict, new: dict) -> tuple[dict, list[str]]:
    """The keys `new` adds or changes over `old`, as a config, and the keys it removes, which a layer over `old`
    can't remove."""
    before, after = leaves(old), leaves(new)
    changed: dict = {}
    for path, value in after.items():
        if before.get(path, object()) != value:
            target = changed
            for name in path[:-1]:
                target = target.setdefault(name, {})
            target[path[-1]] = value
    removed = [".".join(path) for path in before if path not in after and not any(
        other[:len(path)] == path for other in after)]
    return changed, removed


LOCAL_HEADER = (f"# This computer's own {cli.DISPLAY} settings, over .colony/colony.toml. Git never tracks this file, "
                "so an upgrade or a pull never meets it.")


# colony config


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def make_local(root: Path) -> Path:
    """The checkout's .colony/colony.local.toml, made with its header when missing, and kept out of git by the clone's
    own exclude file."""
    from colony import folders

    path = root / cli.DIR / LOCAL
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(LOCAL_HEADER + "\n")
    folders.exclude(f"/{cli.DIR}/{LOCAL}", root)
    return path


def from_edits(root: Path, dry: bool) -> int:
    """Move the uncommitted edits of the tracked .colony/colony.toml into .colony/colony.local.toml, and give the
    tracked file back its committed text. It refuses when an edit removes a key, which a layer can't express."""
    tracked = f"{cli.DIR}/{cli.CONFIG_NAME}"
    committed = git(root, "show", f"HEAD:{tracked}")
    if committed.returncode:
        raise cli.ColonyError(f"{tracked} has no committed version to keep: commit it first")
    old, new = tomllib.loads(committed.stdout), read(root / tracked)
    changed, removed = differences(old, new)
    if removed:
        raise cli.ColonyError(f"your edits remove {', '.join(removed)}, which a local file can't remove: put "
                              "them back, or commit that removal")
    if not changed:
        print(f"{tracked} has no uncommitted edit to move.")
        return 0
    path = root / cli.DIR / LOCAL
    current = read(path) if path.exists() else {}
    merged = cli.merge_tables(current, changed)
    text = dump(merged, LOCAL_HEADER)
    if cli.merge_tables(old, merged) != cli.merge_tables(new, current):
        raise cli.ColonyError("the moved settings would not read the same: edit .colony/colony.local.toml by hand")
    if dry:
        print(f"Would write {cli.DIR}/{LOCAL}:\n{text}and give {tracked} back its committed text. Nothing ran.")
        return 0
    make_local(root)
    path.write_text(text)
    restored = git(root, "checkout", "HEAD", "--", tracked)
    if restored.returncode:
        raise cli.ColonyError(f"wrote {path}, but git didn't restore {tracked}: {restored.stderr.strip()[:200]}")
    keys = ", ".join(".".join(p) for p in leaves(changed))
    print(f"Moved {keys} into {cli.DIR}/{LOCAL}, which git never tracks, and gave {tracked} back its committed text.")
    return 0


HEADER = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]\s*(#.*)?$")  # [table], not [[array]]
ARRAY_HEADER = re.compile(r"^\s*\[\[\s*([^\[\]]+?)\s*\]\]\s*(#.*)?$")
KEY = re.compile(r'^\s*("[^"]*"|[A-Za-z0-9_-]+)\s*=')


def table_path(text: str) -> tuple[str, ...]:
    """A table header's path, such as ("people", "ana") for [people.ana] or [people."ana"]."""
    return tuple(part.strip().strip('"') for part in re.findall(r'"[^"]*"|[^.]+', text))


STRINGS = re.compile(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'')


def value_end(lines: list[str], start: int) -> int:
    """The line after a key's value, which may span lines while its brackets stay open."""
    depth, i = 0, start
    while i < len(lines):
        text = STRINGS.sub('""', lines[i]).split("#", 1)[0]
        depth += text.count("[") + text.count("{") - text.count("]") - text.count("}")
        i += 1
        if depth <= 0:
            return i
    return i


def matches(pattern: tuple[str, ...], path: tuple[str, ...]) -> bool:
    return len(pattern) == len(path) and all(p in ("*", q) for p, q in zip(pattern, path))


def migrate_text(text: str) -> tuple[str, list[str]]:
    """The tracked config's text with MIGRATIONS applied: a removed key commented out with the reason, and a renamed
    key commented out where it was and written at its new place, unless that is set already. Returns the text and a
    line for each change."""
    lines = text.splitlines(keepends=True)
    out, done, moved = [], [], {}
    table: tuple[str, ...] = ()
    i = 0
    present = tomllib.loads(text)
    while i < len(lines):
        line = lines[i]
        header = HEADER.match(line)
        array = ARRAY_HEADER.match(line)
        if header or array:
            table = table_path((header or array)[1])
        key = KEY.match(line)
        hit = next((m for m in MIGRATIONS if key and matches(m.table, table) and key[1].strip('"') == m.key), None)
        if hit is None:
            out.append(line)
            i += 1
            continue
        end = value_end(lines, i)
        block = lines[i:end]
        if hit.to is None:
            out.append(f"# {cli.NAME}: {label(table)} {hit.key} is gone: {hit.why}\n")
            done.append(f"commented out {label(table)} {hit.key}: {hit.why}")
        else:
            target = present
            for name in hit.to:
                target = target.get(name, {}) if isinstance(target, dict) else {}
            out.append(f"# {cli.NAME}: {label(table)} {hit.key} is now {label(hit.to)} {hit.new_key}\n")
            if isinstance(target, dict) and hit.new_key in target:
                done.append(f"commented out {label(table)} {hit.key}: {label(hit.to)} {hit.new_key} is set already")
            else:
                first = KEY.sub(f"{hit.new_key} =", block[0], count=1)
                moved.setdefault(hit.to, []).extend([first, *block[1:]])
                done.append(f"moved {label(table)} {hit.key} to {label(hit.to)} {hit.new_key}")
        out += [f"# {part}" if part.strip() else part for part in block]
        i = end
    for target, block in moved.items():
        at = next((n for n, line in enumerate(out) if (m := HEADER.match(line)) and table_path(m[1]) == target), None)
        block = [part if part.endswith("\n") else part + "\n" for part in block]
        if at is None:
            out += ["\n" if out and not out[-1].endswith("\n\n") else "", f"{label(target)}\n", *block]
        else:
            out[at + 1:at + 1] = block
    return "".join(out), done


def migrate_file(root: Path, dry: bool = False) -> list[str]:
    """Rewrite the tracked .colony/colony.toml with MIGRATIONS (migrate_text), when it needs it. Returns the changes."""
    path = root / cli.DIR / cli.CONFIG_NAME
    if not path.is_file():
        return []
    text = path.read_text()
    new, done = migrate_text(text)
    if not done:
        return []
    try:
        left = migrate(tomllib.loads(new), "")
    except tomllib.TOMLDecodeError as e:
        raise cli.ColonyError(f"the migrated {path} would not read ({e}): edit it by hand") from None
    if left:
        done.append("some old keys sit inside inline tables, which only a hand edit moves: " + "; ".join(left))
    if not dry:
        path.write_text(new)
    return done


def upgrade_hint(changes: str) -> str:
    """What `colony upgrade` adds to its refusal when the uncommitted changes hold edits of the tracked config."""
    tracked = f"{cli.DIR}/{cli.CONFIG_NAME}"
    if not any(line.split(maxsplit=1)[-1].strip('"') == tracked for line in changes.splitlines() if line.strip()):
        return ""
    return (f". Your edits to {tracked} can live in {cli.DIR}/{LOCAL}, which git never tracks and an upgrade never "
            f"touches: `{cli.NAME} config local --from-edits` moves them there")


def refresh(root: Path) -> list[str]:
    """What `colony upgrade --refresh` does for the config under the new version: migrate the tracked file's old
    settings, and list the local file in .colony/.gitignore, so no clone of the repo ever tracks it."""
    if not (root / cli.DIR / cli.CONFIG_NAME).is_file():
        return []
    lines = [f"{cli.DIR}/{cli.CONFIG_NAME}: {line}" for line in migrate_file(root)]
    ignore = root / cli.DIR / ".gitignore"
    present = ignore.read_text().splitlines() if ignore.exists() else []
    if LOCAL not in present:
        ignore.parent.mkdir(parents=True, exist_ok=True)
        ignore.write_text("\n".join([*present, LOCAL]) + "\n")
        lines.append(f"wrote {cli.DIR}/.gitignore: git never tracks {cli.DIR}/{LOCAL}")
    return lines


def config_command(config: dict, args) -> int:
    """`colony config [migrate|local]`: show the layers and every note; rewrite old settings in the tracked file; or
    make the local file, moving uncommitted edits of the tracked file into it with --from-edits."""
    root = cli.repo_root()
    if args.action == "migrate":
        done = migrate_file(root, args.dry_run)
        for line in done:
            print(("would have " if args.dry_run else "") + line)
        print(f"{cli.DIR}/{cli.CONFIG_NAME} needs no migration." if not done else
              "Nothing ran." if args.dry_run else f"Rewrote {cli.DIR}/{cli.CONFIG_NAME}: commit it.")
        return 0
    if args.action == "local":
        if args.from_edits:
            return from_edits(root, args.dry_run)
        if args.dry_run:
            print(f"Would make {cli.DIR}/{LOCAL} and keep it out of git. Nothing ran.")
            return 0
        print(f"{make_local(root)} holds this computer's own settings, over {cli.DIR}/{cli.CONFIG_NAME}, and git never "
              "tracks it.")
        return 0
    print(f"{cli.DISPLAY} reads its settings in three layers, each over the one before:")
    print(f"1. the {cli.mode(config)} mode's defaults, in the package's modes/{cli.mode(config)}.toml")
    print(f"2. {cli.DIR}/{cli.CONFIG_NAME}, the team's, which git tracks")
    places = local_layers(cli.config_path())
    print(f"3. {', '.join(map(str, places)) if places else f'{cli.DIR}/{LOCAL}, not there'}: this computer's own, "
          "which git never tracks")
    from colony import checks, folders

    s = checks.settings(config)
    caps = ", ".join(f"{kind} {checks.span(seconds)}" for kind, seconds in s["caps"].items() if seconds) or "none"
    print(f"Checks: scope {s['scope']}, caps {caps}. Worktrees: {folders.worktrees_folder(config).as_posix()}.")
    lines = briefing(config, root)
    for line in lines:
        print(f"note: {line}.")
    if not lines:
        print("No note: every setting is current.")
    return 0


# The check settings every command follows


def cap(config: dict, kind: str) -> float:
    """`[checks] caps` for a kind of check, in seconds; 0 is no cap."""
    from colony import checks

    return float(checks.settings(config)["caps"].get(kind, 0) or 0)


def batch_kind(config: dict, full: bool) -> str:
    """The kind of check a batch round runs, whose cap stops it: `full` with --full or the full scope, `fast` for a
    fast gate, which runs the fast check, else `checks`."""
    from colony import batch, checks

    if full or checks.settings(config)["scope"] == "full":
        return "full"
    return "fast" if batch.fast_gate(config) else "checks"


def merge_plan(config: dict, root: Path, changed: list[str]):
    """`colony merge`'s check for the merged change: the fast check in `[checks] scope`, for the areas the change
    touches, as `colony fast-check` runs it for a branch (checks.fast_plan), and the `fast` cap. Its command is None
    when the change touches no check area."""
    from colony import batch, checks

    scope = checks.settings(config)["scope"]
    base = batch.fast_check(config["project"])
    named = bool(batch.check_areas(config))
    if scope == "areas" and ("{areas}" not in base or not named):
        plan = checks.Plan(base, None, [], [])
    else:
        plan = checks.scoped(config, root, changed, batch.areas_of(config, changed) if named else None, base, scope)
    return plan, cap(config, "full" if scope == "full" else "fast")


def register(sub) -> None:
    """cli.py's route to this module: `config`, `config migrate` and `config local`."""
    p = sub.add_parser("config", help="show the settings' layers and notes, migrate old settings, or keep this "
                                      "computer's own settings in .colony/colony.local.toml")
    p.add_argument("action", nargs="?", choices=("show", "migrate", "local"), default="show",
                   help="show (the default), migrate, or local")
    p.add_argument("--from-edits", action="store_true",
                   help="local: move the uncommitted edits of .colony/colony.toml into the local file")
    p.add_argument("--dry-run", action="store_true", help="print what it would write, and run nothing")
    p.set_defaults(run=config_command)
