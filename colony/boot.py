"""Starting a session with no onboarding: the startup routine, the project summary, the automatic handover, modes,
request intake, and the standing orders a lead passes its helpers (docs/boot.md).

- **The startup routine** (`colony boot`, and by itself when a lead opens: at the end of plain `colony` in a session,
  and from the SessionStart hook) loads the merged standing orders and the last handover, refreshes the project
  summary, reads the live leads on every computer, the open pull requests, the lead's cards, the plan and the pending
  decisions, and this computer's and the accounts' room. It prints a short briefing that names the active mode, and
  ends on one next step: resume the plan, or ask the person one question (briefing). The network parts run side by
  side under one deadline, and a part that isn't read in time says so.
- **The project summary** is built once from git, and refreshed from what changed since it was built: only the areas
  a change touched are read again. Each session also hears what changed since its own last start (summary, since).
- **The automatic handover** is a snapshot each session keeps after every turn (the Stop hook), saves in full before
  a compaction and when the session ends, and, for a lead, posts in the shape `colony handover` uses, so the next
  session, here or on another computer, reads it. What the person said stays on this computer.
- **Modes** are named bundles of profile settings and rules, switched on with one word, `colony mode <name>`: the
  package's own in modes/work/, the team's in .colony/modes/ (read from origin/<base>, like the team profile), and a
  person's own in <config home>/modes/. profile.load lays the active one between the personal profile and the session
  (mode_layer).
- **Request intake** (`colony plan`) turns one request into task groups, each with the folders it owns, its done-when
  results and its helpers, and starts them: an orchestrator opens one lead per group, which reports to it, and a lead
  gets one card per group. It shows the plan first only when the profile, the mode or the request asks.
- **Orders reach helpers**: a helper's first prompt carries its lead's standing orders for helpers and the approvals
  the person gave at their own terminal on that computer (helper_brief). The lead publishes its standing orders, as
  text alone, for helpers on other computers, which read them only from the lead's own person's comment
  (publish_orders, published_orders). No approval ever travels on the code host.

Python 3.11+ standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
import threading
import time
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from colony import cli, profile, wait

DEADLINE = 12.0  # seconds the briefing's network parts get, together, so the SessionStart hook ends within its 20
STALE_HANDOVER = 7 * 24 * 3600  # an automatic handover older than a week is left out of the briefing
TAIL = 256 * 1024  # the bytes of a transcript's end the handover reads
SAID_KEPT, SAID_MAX, LAST_MAX = 3, 600, 1000  # the person's last messages a handover keeps, and their length
EXPIRED = (cli.ColonyError, OSError, ValueError, KeyError, TypeError)  # what a hook or a briefing part survives


def _git(root, *args: str) -> str | None:
    """One read-only git command's output in `root`, stripped, or None when it fails."""
    import subprocess

    try:
        run = subprocess.run(["git", "-C", str(root), "-c", "core.quotePath=false", *args], capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout.strip() if run.returncode == 0 else None


def me() -> str:
    """This session's name, $COLONY_SESSION, lowercased: `lead`, or a helper's name."""
    return os.environ.get(cli.SESSION_ENV, "").lower()


def lead_of(config: dict, args=None) -> str:
    """The lead this session is or belongs to, by its claimed name, or `<person>-lead`; "" when nobody can say."""
    try:
        return wait.lead_name(config, args or argparse.Namespace(person=None))
    except cli.ColonyError:
        return ""


def state(config: dict, name: str) -> Path:
    """One of this module's files for the project on this computer, ~/.colony/<project>/<name>.json."""
    return wait.state_path(config["project"]["name"], name)


def ago(at: float, now: float | None = None) -> str:
    """How long ago a Unix time was, such as `3 h ago`."""
    return f"{cli.ago(max(0.0, (time.time() if now is None else now) - at))} ago"


def clean(text: str, limit: int) -> str:
    """A text on one line, cut to `limit` characters, with what looks like a secret left out."""
    text = " ".join(str(text or "").split())
    if profile.looks_secret(text):
        return "(left out: it looked like a secret)"
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


# Modes: named bundles of profile settings


MODES_DIR = "modes"  # <config home>/modes/<name>.toml for a person's own, .colony/modes/<name>.toml for the team's
BUILT_IN = ("modes", "work")  # the package's own: orchestrator, unattended, plan-first, speed
MODE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
OFF = ("off", "none", "normal")
NOT_IN_A_MODE = ("description", "mode", "person")  # a mode file's own text, and keys a mode never sets


@dataclass
class Mode:
    """One mode: its name, whose it is, what it is for, its profile data, and any problem reading it."""

    name: str
    where: str
    about: str = ""
    data: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)


def personal_mode_path(name: str) -> Path:
    return profile.config_home() / MODES_DIR / f"{name}.toml"


def team_mode_path(name: str) -> str:
    return f"{cli.DIR}/{MODES_DIR}/{name}.toml"


def has_ref(root: Path, ref: str) -> bool:
    return bool(ref) and _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") is not None


def team_mode_text(name: str, root: Path | None, base: str) -> tuple[str, str]:
    """The team's mode file and where it came from: the copy on origin/<base>, so it changes only through a merged
    pull request, else the working copy when there is no origin/<base>; ("", "") when there is none."""
    if root is None:
        return "", ""
    rel, ref = team_mode_path(name), f"origin/{base}" if base else ""
    if has_ref(root, ref):
        text = _git(root, "show", f"{ref}:{rel}")
        return (text, f"the team's, {rel} on {ref}") if text else ("", "")
    path = Path(root) / rel
    try:
        return path.read_text(encoding="utf-8"), f"the team's, {rel}"
    except OSError:
        return "", ""


def built_in_text(name: str) -> str:
    item = resources.files(__package__).joinpath(*BUILT_IN, f"{name}.toml")
    return item.read_text(encoding="utf-8") if item.is_file() else ""


def read_mode(name: str, text: str, where: str) -> Mode:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return Mode(name, where, problems=[f"the mode {name} ({where}) is not valid TOML ({e}), so it adds nothing"])
    about = data.get("description")
    return Mode(name, where, about.strip() if isinstance(about, str) else "", data)


def find_mode(name: str, root: Path | None = None, base: str = "") -> Mode | None:
    """The mode called `name`: the person's own first, then the team's, then the package's; None when none is."""
    if not MODE_NAME.fullmatch(name or ""):
        return None
    path = personal_mode_path(name)
    if path.is_file():
        try:
            return read_mode(name, path.read_text(encoding="utf-8"), f"yours, {profile.display(path)}")
        except OSError as e:
            return Mode(name, "yours", problems=[f"{profile.display(path)} could not be read ({e})"])
    text, where = team_mode_text(name, root, base)
    if text:
        return read_mode(name, text, where)
    text = built_in_text(name)
    return read_mode(name, text, "built in") if text else None


def mode_names(root: Path | None = None, base: str = "") -> list[str]:
    """Every mode's name: the person's own, the team's and the package's, sorted."""
    names = {p.stem for p in (profile.config_home() / MODES_DIR).glob("*.toml")}
    names |= {item.name[:-5] for item in resources.files(__package__).joinpath(*BUILT_IN).iterdir()
              if item.name.endswith(".toml")}
    if root is not None:
        names |= {p.stem for p in (Path(root) / cli.DIR / MODES_DIR).glob("*.toml")}
        ref = f"origin/{base}" if base else ""
        if has_ref(root, ref):
            listed = _git(root, "ls-tree", "--name-only", f"{ref}:{cli.DIR}/{MODES_DIR}") or ""
            names |= {line[:-5] for line in listed.splitlines() if line.endswith(".toml")}
    return sorted(name for name in names if MODE_NAME.fullmatch(name))


def mode_layer(name: str, root=None, base: str = "") -> profile.Layer:
    """The active mode's bundle as a profile Layer, which profile.load lays between the personal profile and the
    session. An unknown mode adds nothing, and says so as a warning."""
    root = Path(root) if root else None
    found = find_mode(name, root, base)
    if found is None:
        return profile.Layer("mode", f"mode {name}", problems=[
            f"the mode {name} is not defined, so it adds nothing: `{cli.NAME} mode` lists the modes"])
    data = {key: value for key, value in found.data.items() if key not in NOT_IN_A_MODE}
    layer = profile.layer_from(data, "mode", f"mode {name} ({found.where})")
    dropped = [key for key in ("mode", "person") if key in found.data]
    layer.problems = [*found.problems, *(f"the mode {name} sets {key}, which a mode never sets, so it is not used"
                                         for key in dropped), *layer.problems]
    return layer


def mode_profile(found: Mode) -> profile.Profile:
    """A mode's own orders, as a Profile, for `colony mode show`."""
    layer = profile.layer_from({k: v for k, v in found.data.items() if k not in NOT_IN_A_MODE}, "mode",
                               f"mode {found.name}")
    return profile.Profile(settings=profile.merge(None, [layer], {}), rules=layer.rules,
                           warnings=found.problems + layer.problems)


MODE_WORD = re.compile(r"^\s*(mode\s+)?([a-z0-9][a-z0-9-]{0,39})(\s+mode)?\s*[.!]?\s*$", re.I)


def prompt_lines(config: dict, prompt: str) -> list[str]:
    """The prompt hook's part: when the person's whole message is a mode's name, such as `speed` or `mode speed`,
    tell the lead to switch it on; `mode off` switches the mode off. It never raises."""
    found = MODE_WORD.match(prompt or "")
    if not found:
        return []
    word, said = found[2].lower(), bool(found[1] or found[3])
    if word in OFF:
        return [f"The person turned the mode off: run `{cli.NAME} mode off`."] if said else []
    try:
        known = find_mode(word, profile.repo(), str(config.get("project", {}).get("base", "") or ""))
    except EXPIRED:
        return []
    if known is None:
        return []
    return [f"The person named the {word} mode: run `{cli.NAME} mode {word}`, which switches it on for this session, "
            "and follow the orders it prints."]


def mode_cmd(config: dict, args) -> int:
    """`colony mode [<name> | off | show <name> | define <name> …] [--personal]`: list the modes, switch one on for
    this session (or with --personal, for every session), switch it off, show one, or define your own."""
    words = [word for word in args.words]
    root, base = cli.repo_root(), str(config["project"].get("base", "") or "")
    if not words:
        return list_modes(config, root, base)
    first = words[0].lower()
    if first == "show":
        if len(words) != 2:
            raise cli.ColonyError(f"say which mode: `{cli.NAME} mode show <name>`")
        found = find_mode(words[1].lower(), root, base)
        if found is None:
            raise cli.ColonyError(f"no mode is called {words[1]!r}: `{cli.NAME} mode` lists them")
        print(f"The {found.name} mode ({found.where}): {found.about or 'no description'}")
        lines = profile.order_lines(mode_profile(found), "lead")
        print("\n".join(f"- {line}" for line in lines) or "- It sets nothing.")
        return 0
    if first == "define":
        return define_mode(args, words[1:], root)
    if len(words) != 1:
        raise cli.ColonyError(f"one word switches a mode on: `{cli.NAME} mode <name>`, or `{cli.NAME} mode off`")
    target = argparse.Namespace(team=False, session=not args.personal, person=args.person)
    if first in OFF:
        path, level, was = profile.change(target, lambda data, level: profile.drop_value(data, "mode"))
        print(f"The mode is {'off' if was else 'already off'}: {profile.written(path, level)}.")
    else:
        found = find_mode(first, root, base)
        if found is None:
            raise cli.ColonyError(f"no mode is called {first!r}: `{cli.NAME} mode` lists them, and `{cli.NAME} mode "
                                  f"define {first} --set <key>=<value>` makes it")
        try:
            path, level, _ = profile.change(target, lambda data, level: profile.set_value(data, "mode", found.name))
        except cli.ColonyError as e:
            if args.personal:
                raise
            raise cli.ColonyError(f"{e}; or switch it on for every session with --personal") from None
        print(f"The {found.name} mode is on ({found.where}): {profile.written(path, level)}.")
    merged = profile.load(config=config)
    print(profile.render(merged, "lead"))
    publish_quietly(config)
    return 0


def list_modes(config: dict, root: Path, base: str) -> int:
    active = profile.load(config=config)
    setting = active.settings.get("mode")
    print(f"Active mode: {setting.value} (from {setting.source})." if setting else "No mode is on.")
    for name in mode_names(root, base):
        found = find_mode(name, root, base)
        if found is not None:
            mark = " (on)" if setting and setting.value == name else ""
            print(f"- {name}{mark}, {found.where}: {found.about or 'no description'}")
    print(f"`{cli.NAME} mode <name>` switches one on for this session, `--personal` for every session, and "
          f"`{cli.NAME} mode off` switches it off. `{cli.NAME} mode show <name>` shows what it sets.")
    return 0


def define_mode(args, words: list[str], root: Path) -> int:
    """`colony mode define <name> [--set <key>=<value> …] [--rule "<rule>" …] [--about "<what it is for>"]
    [--team]`: write a mode of your own, or with --team the team's .colony/modes/<name>.toml for a pull request."""
    profile.refuse_helper()
    if len(words) != 1 or not MODE_NAME.fullmatch(words[0].lower()):
        raise cli.ColonyError(f"name the mode in one word of lowercase letters, digits and dashes: `{cli.NAME} mode "
                              "define <name> --set <key>=<value>`")
    name = words[0].lower()
    if name in OFF:
        raise cli.ColonyError(f"{name!r} switches the mode off, so it can't name a mode")
    data: dict = {}
    if args.about:
        if profile.looks_secret(args.about):
            raise cli.ColonyError("the description looks like it holds a secret, and a mode never holds one")
        data["description"] = " ".join(args.about.split())
    for pair in args.set or []:
        key_name, sep, text = pair.partition("=")
        key = profile.BY_NAME.get(key_name.strip())
        if not sep or key is None or key.name == "mode" or key.name.startswith("person."):
            raise cli.ColonyError(f"--set takes <key>=<value> with a profile key a mode may set, not {pair!r}: "
                                  f"`{cli.NAME} profile keys` lists them")
        if args.team and not key.team:
            raise cli.ColonyError(f"{key.name} is a person's own setting, which a team mode can't set")
        profile.set_value(data, key.name, profile.parse_value(key, text))
    today = datetime.now(timezone.utc).date().isoformat()
    for rule in args.rule or []:
        text = " ".join(rule.split())
        if found := profile.looks_secret(text):
            raise cli.ColonyError(f"the rule holds what looks like {found}, and a mode never holds a secret")
        profile.add_rule(data.setdefault("rules", []), text, today)
    if not any(key != "description" for key in data):
        raise cli.ColonyError("a mode sets something: give it --set <key>=<value> or --rule \"<rule>\"")
    if args.team:
        path = root / team_mode_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(profile.dumps(data, f"{cli.DISPLAY}: the team's {name} mode, switched on with `{cli.NAME} "
                                            f"mode {name}`. It changes through a reviewed pull request."),
                        encoding="utf-8")
        print(f"wrote {team_mode_path(name)}: commit it on a branch and open a pull request. The team's modes take "
              "effect when it merges.")
        return 0
    path = personal_mode_path(name)
    profile.write_profile(path, data, "mode")
    print(f"wrote {profile.display(path)}: `{cli.NAME} mode {name}` switches it on.")
    return 0


# The project summary


SUMMARY_VERSION = 1
SUMMARY_AREAS = 12  # the most areas the summary names
LANGUAGES = {".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript",
             ".mjs": "JavaScript", ".cjs": "JavaScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin",
             ".swift": "Swift", ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".c": "C", ".h": "C", ".cpp": "C++",
             ".cc": "C++", ".m": "Objective-C", ".sql": "SQL", ".css": "CSS", ".scss": "CSS", ".html": "HTML",
             ".vue": "Vue", ".svelte": "Svelte", ".sh": "Shell", ".md": "Markdown", ".mdx": "Markdown",
             ".tf": "Terraform", ".dart": "Dart", ".ex": "Elixir", ".exs": "Elixir", ".scala": "Scala",
             ".lua": "Lua", ".r": "R", ".toml": "TOML", ".yaml": "YAML", ".yml": "YAML", ".json": "JSON"}
NOT_CODE = ("Markdown", "TOML", "YAML", "JSON")  # an area's code languages come before these
ABOUT_FILES = ("README.md", "AGENTS.md", "CLAUDE.md", "readme.md")


def area(path: str) -> str:
    from colony import cycle

    return cycle.area(path)


def first_words(text: str, limit: int) -> str:
    """The first paragraph of prose in a Markdown text, on one line and cut to `limit`: no front matter, heading,
    badge, list, table, quote, code or HTML."""
    text = re.sub(r"\A---\n.*?\n---\n", "", text or "", flags=re.S)
    paragraph, fenced = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        if not line or line.startswith(("#", "|", "<", "!", "[!", ">", "@", "-", "*", "+")) or line[0].isdigit() \
                and re.match(r"\d+[.)]\s", line):
            if paragraph:
                break
            continue
        paragraph.append(line)
    words = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", " ".join(paragraph))
    words = re.sub(r"[*_`]", "", words)
    return clean(words, limit)


def describe(root: Path, ref: str, folder: str) -> str:
    """What a folder is for: the first paragraph of its README, AGENTS.md or CLAUDE.md, at `ref`."""
    for name in ABOUT_FILES:
        path = f"{folder}/{name}" if folder not in ("", ".") else name
        text = _git(root, "show", f"{ref}:{path}")
        if text:
            about = first_words(text, 160)
            if about:
                return about
    return ""


def summary_ref(root: Path, config: dict) -> str:
    """What the summary reads: origin/<base>, the merged work, when it exists, else HEAD."""
    base = str(config["project"].get("base", "") or "")
    return f"origin/{base}" if has_ref(root, f"origin/{base}" if base else "") else "HEAD"


def build_summary(root: Path, config: dict, ref: str, head: str, old: dict | None = None,
                  touched: set[str] | None = None) -> dict:
    """The summary of the repo at `ref`: what it is, its areas with their files, languages and purpose, and its
    checks. With `old` and `touched`, an area no change touched keeps the purpose read before."""
    files = [path for path in (_git(root, "ls-tree", "-r", "--name-only", ref) or "").splitlines() if path]
    counts, languages = Counter(), {}
    for path in files:
        name = area(path)
        counts[name] += 1
        language = LANGUAGES.get(Path(path).suffix.lower())
        if language:
            languages.setdefault(name, Counter())[language] += 1
    before = {item["name"]: item.get("about", "") for item in (old or {}).get("areas", []) if isinstance(item, dict)}
    areas = []
    for name, count in counts.most_common():
        if name == ".":
            continue
        reuse = old is not None and touched is not None and name in before and name not in touched
        about = before[name] if reuse else describe(root, ref, name)
        counted = (languages.get(name) or Counter()).most_common()
        top = [language for language, _ in sorted(counted, key=lambda pair: (pair[0] in NOT_CODE, -pair[1]))][:2]
        areas.append({"name": name, "files": count, "languages": top, "about": about})
    reuse_top = old is not None and touched is not None and "." not in touched and old.get("about")
    return {"version": SUMMARY_VERSION, "project": config["project"].get("name", ""), "ref": ref, "head": head,
            "built": (old or {}).get("built") if old else time.time(), "refreshed": time.time(),
            "files": len(files), "about": old["about"] if reuse_top else describe(root, ref, "."),
            "areas": areas, "checks": str(config["project"].get("checks", "") or ""),
            "fast_check": str(config["project"].get("fast_check", "") or "")}


def summary(config: dict, root: Path | None = None, rebuild: bool = False) -> dict:
    """The project summary, built once and refreshed from what changed since: the same commit reuses it whole, and a
    newer one reads again only the areas its changes touched. It lives in ~/.colony/<project>/summary.json."""
    root = Path(root) if root else cli.repo_root()
    ref = summary_ref(root, config)
    head = _git(root, "rev-parse", ref) or ""
    path = state(config, "summary")
    old = wait.read_json(path, None)
    old = old if isinstance(old, dict) and old.get("version") == SUMMARY_VERSION else None
    if old and not rebuild and old.get("head") == head and old.get("ref") == ref:
        return old
    touched = None
    if old and not rebuild and old.get("head"):
        changed = _git(root, "diff", "--name-only", old["head"], head)
        touched = {area(line) for line in changed.splitlines() if line} if changed is not None else None
    made = build_summary(root, config, ref, head, old if touched is not None else None, touched)
    wait.write_json(path, made)
    return made


def since(config: dict, root: Path, name: str, head: str, note: bool = True) -> dict | None:
    """What changed on the summary's branch since session `name` last started here: its commits, their areas and
    the newest subjects, or None when nothing did or it never started. `note` records this start."""
    path = state(config, f"{name}-seen")
    seen = wait.read_json(path, {})
    seen = seen if isinstance(seen, dict) else {}
    if note and head:
        wait.write_json(path, {"head": head, "at": time.time()})
    old = seen.get("head")
    if not old or not head or old == head:
        return None
    count = _git(root, "rev-list", "--count", f"{old}..{head}")
    if count is None:
        return None
    subjects = (_git(root, "log", "--format=%s", "-n", "3", f"{old}..{head}") or "").splitlines()
    names = (_git(root, "diff", "--name-only", old, head) or "").splitlines()
    return {"from": old[:9], "to": head[:9], "commits": int(count or 0), "subjects": subjects,
            "areas": sorted({area(line) for line in names if line} - {"."}), "at": seen.get("at")}


def summary_lines(made: dict, change: dict | None = None, short: bool = False) -> list[str]:
    """The summary as a few lines: what the project is, its areas, and what changed since this session last
    started."""
    head = f"Project {made.get('project') or 'here'}"
    head += f": {made['about']}" if made.get("about") else ""
    lines = [f"{head.rstrip('.')}. {made.get('files', 0)} files on {made.get('ref', 'HEAD')}."]
    areas = made.get("areas", [])[:6 if short else SUMMARY_AREAS]
    if areas:
        parts = []
        for item in areas:
            what = ", ".join([f"{item['files']} files", *item.get("languages", [])])
            parts.append(f"{item['name']} ({what}" + (f"; {clean(item['about'], 90)})" if item.get("about") and
                                                       not short else ")"))
        more = len(made.get("areas", [])) - len(areas)
        lines.append("Areas: " + "; ".join(parts) + (f"; and {more} more." if more > 0 else "."))
    checks = made.get("fast_check") or made.get("checks")
    if checks and not short:
        lines.append(f"Checks: {checks}.")
    if change and change.get("commits"):
        when = f", {ago(change['at'])}" if isinstance(change.get("at"), (int, float)) else ""
        newest = "; ".join(f'"{clean(s, 70)}"' for s in change.get("subjects", [])[:3])
        lines.append(f"Since this session last started{when} ({change['from']}..{change['to']}): "
                     f"{change['commits']} commit{'s' if change['commits'] != 1 else ''}"
                     + (f" in {', '.join(change['areas'][:6])}" if change.get("areas") else "")
                     + (f"; the newest: {newest}." if newest else "."))
    return lines


def summary_cmd(config: dict, args) -> int:
    """`colony summary [--rebuild] [--json]`: the project summary, refreshed from what changed since it was built."""
    root = cli.repo_root()
    made = summary(config, root, rebuild=args.rebuild)
    if args.json:
        print(json.dumps(made, ensure_ascii=False))
        return 0
    print("\n".join(summary_lines(made, since(config, root, wait.state_name(me() or cli.LEAD), made["head"],
                                                  note=False))))
    return 0


# The automatic handover


def handover_path(config: dict, name: str) -> Path:
    return state(config, f"{name}-handover")


def read_transcript(path) -> tuple[list[str], str]:
    """The person's last messages and the session's last words in a Claude Code transcript, read from its end. A
    tool's result, a command's wrapper and a hook's note are no message of the person's."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TAIL))
            data = handle.read()
    except (OSError, TypeError):
        return [], ""
    lines = data.split(b"\n")
    if size > TAIL:
        lines = lines[1:]  # the first may be cut
    said, last = [], ""
    for raw in lines:
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        content = (record.get("message") or {}).get("content") if isinstance(record.get("message"), dict) else None
        if record.get("type") == "user" and not record.get("isMeta") and not record.get("toolUseResult"):
            if isinstance(content, list):
                content = " ".join(block.get("text", "") for block in content
                                   if isinstance(block, dict) and block.get("type") == "text")
            text = str(content or "").strip()
            if text and not text.startswith(("<", "Caveat:", "[Request interrupted")):
                said.append(text)
        elif record.get("type") == "assistant" and isinstance(content, list):
            texts = [block.get("text", "") for block in content if isinstance(block, dict) and
                     block.get("type") == "text" and block.get("text", "").strip()]
            if texts:
                last = " ".join(texts)
    return [clean(text, SAID_MAX) for text in said[-SAID_KEPT:]], clean(last, LAST_MAX) if last else ""


def snapshot(config: dict, name: str, event: str, payload: dict) -> dict:
    """This session's handover as it stands: the person's last messages and its own last words from the transcript,
    the plan, the pending decisions and those taken alone, its branch and uncommitted files, and the next step."""
    from colony import decisions, presence

    old = wait.read_json(handover_path(config, name), {})
    old = old if isinstance(old, dict) else {}
    said, last = read_transcript(payload.get("transcript_path"))
    root = Path(payload.get("cwd") or ".")
    branch = _git(root, "branch", "--show-current") or ""
    dirty = len([line for line in (_git(root, "status", "--porcelain") or "").splitlines() if line.strip()])
    lead = lead_of(config) if me() == cli.LEAD else ""
    held = read_plan(config, lead) if lead else None
    snap = {"who": lead or name, "session": me(), "event": event, "at": time.time(), "computer": presence.computer(),
            "said": said or old.get("said", []), "last": last or old.get("last", ""),
            "plan": plan_lines(held) if held else [], "pending": decisions.pending_lines(config) if lead else [],
            "decided": decisions.recent_lines(config, lead) if lead else [], "branch": branch, "dirty": dirty,
            "next": next_step(held, said or old.get("said", [])), "posted": old.get("posted", "")}
    return snap


def next_step(held: dict | None, said: list[str]) -> str:
    """The step to carry on with: the plan's first task group not done, else the person's last request."""
    if held:
        group = next((g for g in held.get("groups", []) if not g.get("done_at")), None)
        if group:
            state_word = "started" if group.get("started") else "not started"
            return (f"task group {group['name']} of the plan ({state_word}; done when: "
                    f"{'; '.join(group.get('done', []))})")
    return f"the person's last request: \"{said[-1]}\"" if said else ""


def save_snapshot(config: dict, name: str, snap: dict) -> None:
    path = handover_path(config, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{os.getpid()}")
    with os.fdopen(os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as handle:
        json.dump(snap, handle, ensure_ascii=False)
    os.replace(part, path)


def handover_body(config: dict, snap: dict) -> str:
    """The posted handover, in the shape `colony handover` writes, so `colony handover --read` finds it: who, when,
    the decisions, the open questions and the next step. What the person said stays on this computer."""
    from colony import board, cycle

    decisions = "; ".join(snap.get("decided", [])[-5:]) or "none"
    pending = "; ".join(snap.get("pending", [])[:5]) or "none"
    step = snap.get("next", "")
    step = step if step.startswith("task group") else f"carry on from the automatic handover on {snap['computer']}"
    body = cycle.handover_text(snap["who"], clean(decisions, 900), clean(pending, 900), clean(step, 400),
                               board.utcnow())
    return f"{body}\n<!-- {cli.NAME}-handover automatic, {snap['event']} -->"


def post_handover(config: dict, snap: dict) -> str:
    """Post a lead's automatic handover when it says something new, through the outbox when GitHub can't take it
    now. Returns what was posted, "" for nothing."""
    from colony import guards, transport

    if not (snap.get("plan") or snap.get("pending") or snap.get("decided")):
        return ""
    key = hashlib.sha256(json.dumps([snap.get("decided"), snap.get("pending"), snap.get("next")]).encode()).hexdigest()
    if key == snap.get("posted"):
        return ""
    body = handover_body(config, snap)
    try:
        transport.send(config, cli.LEAD, body)
    except (wait.GhError, *guards.POST_FAILURES):
        guards.keep_in_outbox(config, cli.LEAD, body)
    snap["posted"] = key
    return body


def handover_lines(snap: dict, full: bool = True) -> list[str]:
    """A saved handover as lines for the next session."""
    when = datetime.fromtimestamp(snap.get("at", 0), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    why = {"compact": "before a compaction", "end": "when the session ended", "turn": "after its last turn"}
    lines = [f"Last handover ({when}, {ago(snap.get('at', 0))}, saved {why.get(snap.get('event'), 'by itself')} on "
             f"{snap.get('computer', 'this computer')}):"]
    if snap.get("next"):
        lines.append(f"- Next: {snap['next']}")
    for line in snap.get("plan", [])[:6 if full else 3]:
        lines.append(f"- Plan: {line}")
    if snap.get("pending"):
        lines.append(f"- Waiting on the person: {'; '.join(snap['pending'][:4])}")
    if snap.get("decided") and full:
        lines.append(f"- Decided alone: {'; '.join(snap['decided'][-4:])}")
    if full:
        for text in snap.get("said", []):
            lines.append(f"- The person said: \"{text}\"")
        if snap.get("last"):
            lines.append(f"- Your last words: {snap['last']}")
    if snap.get("branch"):
        lines.append(f"- Branch {snap['branch']}, {snap.get('dirty', 0)} uncommitted files.")
    return lines


def last_handover(config: dict, name: str) -> dict | None:
    held = wait.read_json(handover_path(config, name), None)
    if not isinstance(held, dict) or time.time() - float(held.get("at") or 0) > STALE_HANDOVER:
        return None
    return held


def team_comments(config: dict, number: int) -> list[dict]:
    """The comments on issue `number` that the team wrote, oldest first: by one of [people] logins, or, with none set,
    by someone GitHub says has access to the repo, as status comments are read (presence.by_team). An outsider's
    comment on a public repo never reaches a session's prompt this way."""
    from colony import presence

    out = wait.gh("api", "--paginate", f"repos/{config['project']['repo']}/issues/{number}/comments?per_page=100",
                  "--jq", ".[]")
    logins = frozenset(str(login).lower() for login in config.get("people", {}).get("logins", []))
    comments = [json.loads(line) for line in out.splitlines() if line.strip()]
    return [comment for comment in comments if isinstance(comment, dict) and presence.by_team(comment, logins)]


def posted_handover(config: dict, lead: str) -> str:
    """This lead's last handover the team posted on the coordination issue, as `colony handover --read` finds it."""
    if wait.hack(config):
        return ""
    number = wait.coordination_issue(config["project"]["repo"], config["project"]["name"])
    mine = [c.get("body", "") for c in team_comments(config, number)
            if str(c.get("body", "")).startswith(f"handover from {lead},")]
    return mine[-1] if mine else ""


# Request intake: the plan


ASKS_FOR_PLAN = re.compile(r"\b(plan first|show (me )?(the |your )?plan|before you start|wait for my (yes|ok|go)|"
                           r"run it by me|check with me first)\b", re.I)


def plan_path(config: dict, lead: str) -> Path:
    return state(config, f"plan-{lead}")


def read_plan(config: dict, lead: str) -> dict | None:
    held = wait.read_json(plan_path(config, lead), None)
    return held if isinstance(held, dict) and isinstance(held.get("groups"), list) else None


def write_plan(config: dict, lead: str, held: dict) -> None:
    wait.write_json(plan_path(config, lead), held)


def plan_lines(held: dict) -> list[str]:
    """Each task group of a plan in one line: its name, lead, folders, done-when results and where it stands."""
    lines = []
    for group in held.get("groups", []):
        where = "done" if group.get("done_at") else "started" if group.get("started") else "not started"
        if group.get("draft") and not group.get("approved"):
            where += ", the draft waits for the person's yes"
        owner = f", lead {group['lead']}" if group.get("lead") else ""
        lines.append(f"{group['name']} ({where}{owner}): folders {', '.join(group['folders'])}; done when "
                     f"{'; '.join(group['done'])}")
    return lines


def shows_first(merged: profile.Profile, request: str, asked: bool = False) -> str:
    """Why the plan is shown before it starts, or "" when it starts at once: the request asks, or the profile or the
    mode says so."""
    if asked or ASKS_FOR_PLAN.search(request or ""):
        return "the request asks to see the plan first"
    setting = merged.settings.get("intake.plan")
    if setting and setting.value == "show":
        return f"intake.plan is show (from {setting.source})"
    return ""


def plan_cmd(config: dict, args) -> int:
    """`colony plan …`: request intake (see the module's docstring)."""
    action = args.action or "show"
    lead = lead_of(config, args)
    if not lead:
        raise cli.ColonyError(f"say whose plan this is: run it as a lead, or with --person")
    if action != "show":
        if me() and me() != cli.LEAD:
            raise cli.ColonyError(f"{me()} is a helper: only a lead makes and starts a plan")
    return {"new": plan_new, "group": plan_group, "show": plan_show, "start": plan_start, "done": plan_done,
            "approve": plan_approve}[action](config, args, lead)


def plan_new(config: dict, args, lead: str) -> int:
    request = " ".join(args.request.split())
    if not request:
        raise cli.ColonyError("say the request, in quotes")
    held = read_plan(config, lead)
    if held and not args.replace and any(not g.get("done_at") for g in held["groups"]):
        raise cli.ColonyError(f"{lead} has a plan with task groups not done yet: `{cli.NAME} plan` shows it, and "
                              f"--replace starts a new one")
    merged = profile.load(config=config)
    shape = merged.value("team.shape", "lead")
    why = shows_first(merged, request, args.show_first)
    try:
        person = cli.person_of(config, args)
    except cli.ColonyError:
        person = ""
    held = {"request": args.request.strip(), "lead": lead, "person": person, "shape": shape, "show_first": why,
            "created": time.time(), "approved": None, "groups": []}
    write_plan(config, lead, held)
    most, helpers = merged.value("team.max_leads", 3), merged.value("team.helpers_per_lead", 4)
    print(f"Plan for \"{held['request']}\", kept word for word.")
    if shape == "orchestrator":
        print(f"Team shape: orchestrator. Split it into task groups, each with its own lead that runs at most "
              f"{helpers} helpers and reports to you; at most {most} leads run at once, and later groups start as "
              "earlier ones finish.")
    else:
        print(f"Team shape: lead. Split it into task groups, one card each, built by your helpers, at most {helpers} "
              "at once.")
    print("Give each group a short name, the folders it owns (no two groups share one), and up to 3 done-when "
          f"results: `{cli.NAME} plan group <name> --folders <folder>/ … --done \"<result>\" … [--helpers <n>] "
          "[--draft]`. --draft drafts it first, and builds it only after the person's yes on the draft.")
    if why:
        print(f"Then show the plan to the person ({why}): `{cli.NAME} plan show`, and start it on their yes with "
              f"`{cli.NAME} plan start --approved \"<their words, exactly>\"`.")
    else:
        print(f"Then start it at once with `{cli.NAME} plan start`, which posts the plan for the record; the person "
              "is not asked first.")
    return 0


def plan_group(config: dict, args, lead: str) -> int:
    from colony import presence

    held = read_plan(config, lead)
    if held is None:
        raise cli.ColonyError(f"no plan yet: `{cli.NAME} plan new \"<the request>\"` starts one")
    name = args.name.lower()
    if not presence.STREAM.fullmatch(name):
        raise cli.ColonyError(f"{args.name!r} is not a group name: lowercase letters, digits and dashes, such as web")
    folders = list(dict.fromkeys(presence.folder(f) for f in args.folders or []))
    done = [" ".join(text.split()) for text in args.done or [] if text.strip()]
    if not folders:
        raise cli.ColonyError("a task group owns its folders: give --folders <folder>/ …")
    if not done or len(done) > 3:
        raise cli.ColonyError("a task group has 1 to 3 done-when results: give each with --done \"<result>\"")
    merged = profile.load(config=config)
    most = merged.value("team.helpers_per_lead", 4)
    helpers = args.helpers if args.helpers is not None else min(2, most)
    if not 1 <= helpers <= most:
        raise cli.ColonyError(f"a group runs 1 to {most} helpers (team.helpers_per_lead)")
    others = [g for g in held["groups"] if g["name"] != name]
    clash = [f"{mine} overlaps {theirs} of {g['name']}" for g in others for mine in folders for theirs in g["folders"]
             if presence.overlaps(mine, theirs)]
    if clash:
        raise cli.ColonyError(f"two groups never share a folder: {'; '.join(clash)}")
    group = {"name": name, "folders": folders, "done": done, "helpers": helpers, "draft": args.draft}
    names = [g["name"] for g in held["groups"]]
    if name in names:  # a group changed keeps its place, and where it stands
        old = held["groups"][names.index(name)]
        held["groups"][names.index(name)] = {**{k: v for k, v in old.items() if k in KEPT}, **group}
    else:
        held["groups"].append(group)
    write_plan(config, lead, held)
    print(f"Task group {name}: folders {', '.join(folders)}; done when {'; '.join(done)}; {helpers} helpers"
          + ("; drafted first" if args.draft else "") + ".")
    return 0


KEPT = ("started", "lead", "done_at", "approved")  # what a changed group keeps of where it stood


def plan_show(config: dict, args, lead: str) -> int:
    held = read_plan(config, args.of or lead)
    if held is None:
        print(f"No plan for {args.of or lead}. `{cli.NAME} plan new \"<the request>\"` starts one.")
        return 0
    if getattr(args, "json", False):
        print(json.dumps(held, ensure_ascii=False))
        return 0
    groups = [g for g in held["groups"] if not args.group or g["name"] == args.group]
    print(f"Plan of {held['lead']} for \"{held['request']}\" ({held['shape']}):")
    for line in plan_lines({"groups": groups}):
        print(f"- {line}")
    if not held["groups"]:
        print(f"- no task group yet: `{cli.NAME} plan group <name> --folders … --done …`")
    if held.get("approved"):
        print(f"The person's yes: \"{held['approved']['words']}\".")
    elif held.get("show_first"):
        print(f"It starts after the person's yes ({held['show_first']}).")
    return 0


def lead_brief(config: dict, held: dict, group: dict) -> str:
    """The first prompt of a task group's lead: claim its folders, its group and done-when results, and report to the
    orchestrator."""
    orchestrator = held["lead"]
    done = " ".join(f"{i}) {text}" for i, text in enumerate(group["done"], 1))
    draft = (" This group is drafted first: write the draft only, send it to the orchestrator, and build nothing until "
             f"{orchestrator} tells you the person said yes." if group.get("draft") and not group.get("approved")
             else "")
    return (f"You lead one task group of {orchestrator}'s plan. First run `{cli.NAME} claim {group['name']} "
            f"{' '.join(group['folders'])}` inside this session, then read {cli.DIR}/playbook.md, Lead section, and "
            f"start. The request: \"{held['request']}\". Your group: {group['name']}, in "
            f"{', '.join(group['folders'])}. "
            f"Done when: {done}.{draft} Run at most {group['helpers']} helpers, and hand every hands-on task to them: "
            f"you build nothing yourself. Report to {orchestrator} with `{cli.NAME} say {orchestrator} "
            f"\"{group['name']}: <what>\"` when a done-when result is met, when you are blocked, and when the group is "
            f"done, and ask {orchestrator}, never the person, unless it tells you to. `{cli.NAME} plan show --of "
            f"{orchestrator} --group {group['name']}` shows your group again.")


def plan_start(config: dict, args, lead: str) -> int:
    held = read_plan(config, lead)
    if held is None or not held["groups"]:
        raise cli.ColonyError(f"the plan has no task group yet: `{cli.NAME} plan group <name> --folders … "
                              "--done …`")
    if held.get("show_first") and not held.get("approved") and not args.approved:
        print(f"Not started: the plan starts after the person's yes ({held['show_first']}). Show it to them:")
        plan_show(config, argparse.Namespace(of=None, group=None, json=False), lead)
        print(f"On their yes, run `{cli.NAME} plan start --approved \"<their words, exactly>\"`.")
        return 0
    if args.approved and not held.get("approved"):
        held["approved"] = {"words": args.approved, "at": time.time()}
        from colony import decisions

        decisions.record(config, kind="plan", question=f"start the plan for \"{held['request']}\"", default="start",
                         status="answered", answer=args.approved, lead=lead)
    waiting = [g for g in held["groups"] if not g.get("started") and not g.get("done_at")]
    if held["shape"] == "orchestrator":
        merged = profile.load(config=config)
        running = len([g for g in held["groups"] if g.get("started") and not g.get("done_at")])
        room = max(0, merged.value("team.max_leads", 3) - running)
        opened, placed = 0, {}
        for group in waiting[:room]:
            title = f"{config['project']['name']}-{group['name']}-lead"
            ns = argparse.Namespace(person=args.person, account=args.account, here=False, dry_run=args.dry_run)
            if not args.account:  # group leads share lead accounts before taking the last one free of leads
                from colony import capacity

                ns.account, _, ns.account_why = capacity.group_lead_account(config, cli.person_of(config, args),
                                                                            placed)
                placed.setdefault(ns.account, []).append(title)
            cli.launch(config, ns, cli.LEAD, "lead", lead_brief(config, held, group), title=title)
            if not args.dry_run:
                group["started"] = time.time()
                group["lead"] = f"{(held.get('person') or lead.split('-', 1)[0]).lower()}-{group['name']}-lead"
            opened += 1
        later = len(waiting) - opened
        print(f"Opened {opened} lead{'s' if opened != 1 else ''}, one per task group, each reporting to {lead}."
              + (f" {later} more start as groups finish (team.max_leads)." if later else ""))
        print(f"Keep `{cli.NAME} wait` running: their reports come as lines. Mark a finished group with `{cli.NAME} "
              "plan done <group>`, then start the next with `colony plan start`.")
    else:
        for i, group in enumerate(waiting, 1):
            body = (f"{held['request']}. Task group {group['name']}. Done when: "
                    + " ".join(f"{n}) {text}" for n, text in enumerate(group["done"], 1))
                    + (" Draft it first: build nothing until the person's yes." if group.get("draft") else "")
                    + f" Folders: {', '.join(group['folders'])}. predicted: M, 60 min")
            title = f"builder-{i}: {group['name']}"
            print(f"{cli.NAME} card new {shlex.quote(title)} --body {shlex.quote(body)} --size M")
            if not args.dry_run:
                group["started"] = time.time()
        helpers = sum(g["helpers"] for g in waiting)
        print(f"Run those to make the cards, then `{cli.NAME} helpers {helpers}`, and hand each card to a helper. "
              "You build nothing yourself.")
    if not args.dry_run:
        held["started"] = held.get("started") or time.time()
        write_plan(config, lead, held)
        post_plan(config, held)
        publish_quietly(config)
    return 0


def post_plan(config: dict, held: dict) -> None:
    """Post the plan on the coordination issue for the record, with its groups attached; it never stops the start."""
    from colony import board, guards, transport

    text = "\n".join([f"Request: {held['request']}", *(f"- {line}" for line in plan_lines(held))])
    body = (f"plan from {held['lead']}, {board.stamp(board.utcnow())}: {clean(held['request'], 200)}\n"
            + transport.attachment("the plan", text))
    try:
        transport.send(config, cli.LEAD, body)
    except (wait.GhError, cli.ColonyError, *guards.POST_FAILURES) as e:
        print(f"{cli.NAME}: the plan was not posted for the record: {e}", file=sys.stderr)


def plan_done(config: dict, args, lead: str) -> int:
    held = read_plan(config, lead)
    group = next((g for g in (held or {}).get("groups", []) if g["name"] == args.name.lower()), None)
    if group is None:
        raise cli.ColonyError(f"the plan has no task group {args.name!r}: `{cli.NAME} plan` shows them")
    group["done_at"] = time.time()
    write_plan(config, lead, held)
    left = [g["name"] for g in held["groups"] if not g.get("done_at")]
    waiting = [g["name"] for g in held["groups"] if not g.get("started")]
    print(f"Task group {group['name']} is done." + (f" Still going: {', '.join(left)}." if left else
                                                     " Every group is done: tell the person, with the links."))
    if waiting:
        print(f"Start the next with `{cli.NAME} plan start`: {', '.join(waiting)} wait.")
    return 0


def plan_approve(config: dict, args, lead: str) -> int:
    held = read_plan(config, lead)
    group = next((g for g in (held or {}).get("groups", []) if g["name"] == args.name.lower()), None)
    if group is None:
        raise cli.ColonyError(f"the plan has no task group {args.name!r}: `{cli.NAME} plan` shows them")
    if not group.get("draft"):
        raise cli.ColonyError(f"{group['name']} has no draft to approve: it builds at once")
    group["approved"] = {"words": args.words, "at": time.time()}
    write_plan(config, lead, held)
    from colony import decisions

    decisions.record(config, kind="gate", question=f"build the draft of task group {group['name']}",
                     default="build it", status="answered", answer=args.words, lead=lead)
    target = group.get("lead") or "its lead"
    print(f"The person's yes on {group['name']}'s draft is recorded, word for word. Tell {target}: `{cli.NAME} say "
          f"{group.get('lead') or '<its lead>'} \"approved: build {group['name']}\"`." if held["shape"] ==
          "orchestrator" else f"The person's yes on {group['name']}'s draft is recorded, word for word: cut its build "
                              "card now.")
    return 0


# Orders for helpers


ORDERS_HEAD = "orders for the helpers of {lead}"
ORDERS_FENCE = re.compile(r"(~{4,})text\n(.*?)\n\1\n", re.S)


def orders_path(config: dict, lead: str) -> Path:
    return state(config, f"{lead}-helper-orders")


def person_of_lead(lead: str) -> str:
    """The person a lead belongs to: its name starts with theirs, such as ana in ana-main-lead."""
    return lead.split("-", 1)[0] if lead else ""


def own_orders(config: dict, lead: str) -> dict:
    """The orders this lead's session passes its helpers: its standing orders for helpers, with its session and its
    mode, and, for its helpers on this computer, the approvals the person gave here at their own terminal."""
    from colony import decisions

    merged = profile.load(config=config)
    orders = profile.render(merged, "helper") if profile.order_lines(merged, "helper") else ""
    person = os.environ.get(cli.PERSON_ENV, "").lower() or person_of_lead(lead)
    approvals = decisions.live_approvals(config, person, lead) if person else []
    return {"lead": lead, "text": with_approvals(orders, approvals), "orders": orders, "at": time.time()}


def with_approvals(orders: str, approvals: list[dict]) -> str:
    """A helper's orders, then a line for each approval that covers it on this computer."""
    from colony import decisions

    lines = [orders] if orders else []
    return "\n".join(lines + [f"The person approved at their own terminal, so it runs without a permission question: "
                              f"{line}" for line in decisions.approval_lines(approvals)])


def publish_orders(config: dict, lead: str, post: bool = True) -> dict:
    """Keep this lead's orders for helpers where its helpers read them: a file on this computer, and, when its
    standing orders changed, a comment on the coordination issue for helpers on other computers. The comment carries
    the orders as text alone: an approval never travels."""
    from colony import board, transport

    held = own_orders(config, lead)
    key = hashlib.sha256(held["orders"].encode()).hexdigest()
    path = orders_path(config, lead)
    before = wait.read_json(path, {})
    held["key"], held["posted"] = key, (before or {}).get("posted", "") if isinstance(before, dict) else ""
    if post and held["posted"] != key and (held["orders"] or held["posted"]) and not wait.hack(config):
        body = (f"{ORDERS_HEAD.format(lead=lead)}, {board.stamp(board.utcnow())}\n"
                + transport.attachment("the orders", json.dumps({"orders": held["orders"]})))
        transport.send(config, cli.LEAD, body)
        held["posted"] = key
    wait.write_json(path, held)
    return held


def publish_quietly(config: dict) -> None:
    """publish_orders for this lead, saying on stderr when it can't, and never stopping the command that ran it."""
    lead = lead_of(config)
    if me() != cli.LEAD or not lead:
        return
    try:
        publish_orders(config, lead)
    except (wait.GhError, *EXPIRED) as e:
        print(f"{cli.NAME}: the orders for helpers were not published: {e}", file=sys.stderr)


def known_coordination(config: dict) -> int | None:
    """The coordination issue's number, remembered on this computer or found by its title, without making one."""
    repo = config["project"]["repo"]
    known = wait.read_json(wait.state_path(config["project"]["name"], f"{cli.LEAD}-coordination"), None)
    if isinstance(known, int):
        return known
    listed = json.loads(wait.gh("issue", "list", "--repo", repo, "--state", "open", "--search",
                                f'"{wait.COORDINATION}" in:title', "--json", "number,title", "--limit", "50") or "[]")
    numbers = sorted(issue["number"] for issue in listed if issue.get("title") == wait.COORDINATION)
    return numbers[-1] if numbers else None


def person_logins(config: dict, person: str) -> frozenset[str]:
    """A person's own logins on the code host: `[people.<person>] login`, and the [people] logins whose name is
    theirs. Empty when colony.toml names none."""
    if not person:
        return frozenset()
    table = config.get("people", {}).get(person)
    own = {str(table["login"]).lower()} if isinstance(table, dict) and table.get("login") else set()
    return frozenset(own | set(wait.person_logins(config, person)))


def published_orders(config: dict, lead: str) -> str:
    """A lead's standing orders for helpers as it last published them on the coordination issue: only from a comment
    one of the lead's own person's logins wrote, and "" when colony.toml names none of their logins, so a comment
    by an outsider or another person never reaches a helper's prompt. Anything but the orders' text is ignored."""
    logins = person_logins(config, person_of_lead(lead))
    number = known_coordination(config) if logins else None
    if number is None:
        return ""
    repo = config["project"]["repo"]
    out = wait.gh("api", "--paginate", f"repos/{repo}/issues/{number}/comments?per_page=100", "--jq", ".[]")
    comments = [json.loads(line) for line in out.splitlines() if line.strip()]
    head = ORDERS_HEAD.format(lead=lead) + ","
    for comment in reversed(comments):
        author = str((comment.get("user") or {}).get("login") or "").lower() if isinstance(comment, dict) else ""
        body = str(comment.get("body", "")) if author in logins else ""
        found = ORDERS_FENCE.search(body) if body.startswith(head) else None
        if found:
            try:
                data = json.loads(found[2].replace("&lt;!--", "<!--").replace("--&gt;", "-->"))
            except ValueError:
                return ""
            return str(data.get("orders") or "") if isinstance(data, dict) else ""
    return ""


def helper_brief(config: dict, lead: str = "", fetch: bool = False) -> str:
    """The orders a helper's first prompt carries: the lead's own, when the lead opens it on this computer; else the
    copy its lead keeps on this computer; else, with `fetch`, the standing orders its lead published on the
    coordination issue, as text alone (published_orders), with the approvals the person gave on this computer. ""
    when there are none."""
    from colony import decisions

    lead = (lead or os.environ.get(wait.LEAD_ENV, "")).lower()
    if not config.get("project", {}).get("name"):
        return ""
    try:
        if me() == cli.LEAD and (not lead or lead == lead_of(config)):
            own = lead or lead_of(config)
            return publish_orders(config, own, post=False)["text"] if own else own_orders(config, "")["text"]
        held = wait.read_json(orders_path(config, lead), None) if lead else None
        if isinstance(held, dict):
            return str(held.get("text", ""))
        if not (fetch and lead and config["project"].get("repo") and not wait.hack(config)):
            return ""
        orders = published_orders(config, lead)
        person = person_of_lead(lead)
        here = decisions.live_approvals(config, person, lead) if orders and person else []
        return with_approvals(orders, here) if orders else ""
    except (wait.GhError, *EXPIRED) as e:
        print(f"{cli.NAME}: the helper's orders were not read: {e}", file=sys.stderr)
        return ""


def orders_cmd(config: dict, args) -> int:
    """`colony orders [--publish]`: the orders this lead passes its helpers, and with --publish, publish them now."""
    lead = lead_of(config, args)
    if me() != cli.LEAD:
        print(helper_brief(config, lead) or "No orders from your lead yet.")
        return 0
    held = publish_orders(config, lead, post=args.publish)
    print(held["text"] or "No orders for helpers: the profiles set none, and the person approved nothing for them.")
    if args.publish:
        print(f"Published for {lead}'s helpers on every computer.")
    return 0


# The startup routine


def run_parts(parts: dict, deadline: float) -> dict:
    """Run each part, a function of no arguments, in its own thread, and return each result, an exception, or None
    for one not done by the deadline. The threads are daemons, so one stuck on the network never holds the exit."""
    results: dict = {}

    def run(name, part):
        try:
            results[name] = part()
        except Exception as e:  # noqa: BLE001  a part's failure is one line of the briefing, never the whole
            results[name] = e

    threads = [threading.Thread(target=run, args=item, daemon=True) for item in parts.items()]
    for thread in threads:
        thread.start()
    end = time.monotonic() + deadline
    for thread in threads:
        thread.join(max(0.0, end - time.monotonic()))
    return {name: results.get(name) for name in parts}


def leads_part(config: dict, lead: str) -> list[str]:
    from colony import presence

    alive, _, note = presence.everyone(config)
    leads = sorted((s for s in alive if s.kind == "lead"), key=lambda s: s.name)
    helpers = sorted(s.name for s in alive if s.kind == "helper" and s.lead == lead)
    lines = []
    if leads:
        lines.append("Live leads: " + "; ".join(
            f"{s.name}{' (you)' if s.name == lead else ''} on {s.computer or 'an unknown computer'}, "
            f"{', '.join(s.folders) or 'the rest of the repo'}" for s in leads) + ".")
    else:
        lines.append("Live leads: none but you.")
    lines.append(f"Your helpers: {', '.join(helpers)}." if helpers else "Your helpers: none running.")
    return lines + ([note] if note else [])


def prs_part(config: dict) -> list[str]:
    """The open pull requests, newest first. One from outside the team shows as its number alone, never its title:
    a title is anyone's text, and the briefing goes into the lead's context. The team is [people] logins when it
    names any, else whoever has access to the repo (presence.TRUSTED), as decisions.teammates reads it."""
    from colony import presence

    listed = json.loads(wait.gh("api", f"repos/{config['project']['repo']}/pulls?state=open&per_page=20") or "[]")
    listed = [pr for pr in listed if isinstance(pr, dict)] if isinstance(listed, list) else []
    if not listed:
        return ["Open pull requests: none."]
    logins = frozenset(str(login).lower() for login in config.get("people", {}).get("logins", []))

    def shown_pr(pr: dict) -> str:
        author = str((pr.get("user") or {}).get("login") or "").lower()
        team = author in logins if logins else pr.get("author_association") in presence.TRUSTED
        if not team:
            return f"#{pr.get('number')} from outside the team"
        return f"#{pr.get('number')} {clean(pr.get('title', ''), 60)}{' (draft)' if pr.get('draft') else ''}"
    shown = "; ".join(shown_pr(pr) for pr in listed[:5])
    more = f"; and {len(listed) - 5} more" if len(listed) > 5 else ""
    return [f"Open pull requests ({len(listed)}): {shown}{more}."]


def cards_part(config: dict, lead: str) -> list[str]:
    from colony import board

    if wait.hack(config) or not config.get("features", {}).get("board", True):
        return []
    found = board.find_board(config)
    if found is None:
        return []
    mine = [item for item in board.items(found) if board.is_open_card(item)
            and board.field_value(item, "Lead").lower() in (lead, cli.LEAD)]
    if not mine:
        return ["Your open cards: none."]
    shown = "; ".join(f"#{item['number']} {board.field_value(item, 'Status') or 'To do'}"
                      + (f", {board.field_value(item, 'Helper')}" if board.field_value(item, "Helper") else "")
                      + f": {clean(item['title'], 50)}" for item in mine[:6])
    return [f"Your open cards ({len(mine)}): {shown}" + (f"; and {len(mine) - 6} more." if len(mine) > 6 else ".")]


def capacity_part(config: dict, person: str) -> list[str]:
    from colony import capacity

    here = cli.running_sessions(config)
    room = capacity.limits(config, running=len(capacity.local_helpers(config, here)))
    load = "unknown" if room.get("load") is None else f"{room['load']:.1f}"
    lines = [f"This computer: {room['open_now']} more helpers now, of {room['helpers']} at once "
             f"({room['cores']} cores, load {load})" + (f"; busy: {'; '.join(room['why'])}." if room["busy"] else ".")]
    try:
        names = list(dict.fromkeys(sum(cli.person_accounts(config, person), []))) if person \
            else list(config["accounts"])
    except cli.ColonyError:
        names = list(config.get("accounts", {}))
    rooms = [cli.room_text(name, config["accounts"][name]["config_dir"]) for name in names
             if name in config["accounts"]]
    if rooms:
        lines.append("Accounts: " + "; ".join(rooms) + ".")
    from colony import accounts, forecast  # accounts missing, signed out or new, and any that runs out before a reset

    return lines + accounts.briefing_lines(config, names) + forecast.risk_lines(config, names)


def handover_part(config: dict, lead: str) -> str:
    return posted_handover(config, lead)


def briefing(config: dict, args=None, offline: bool = False, deadline: float = DEADLINE) -> list[str]:
    """The startup routine's briefing for this lead (see the module's docstring)."""
    from colony import decisions

    lead = lead_of(config, args)
    name = wait.state_name(cli.LEAD) if me() == cli.LEAD else (lead or cli.LEAD)
    try:
        person = cli.person_of(config, args or argparse.Namespace(person=None))
    except cli.ColonyError:
        person = ""
    merged = profile.load(config=config)
    setting = merged.settings.get("mode")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mode = f"Mode: {setting.value} (from {setting.source})." if setting else "Mode: none (`colony mode` lists them)."
    lines = [f"{cli.DISPLAY} briefing for {lead or 'this lead'}, {stamp}. {mode}"]
    autonomy = merged.value("decisions.autonomy", "routine")
    count = len(profile.order_lines(merged, "lead"))
    lines.append(f"Orders: {count} in force; decisions: {autonomy}"
                 + (f"; never raise: {', '.join(merged.value('decisions.never_raise'))}"
                    if merged.value("decisions.never_raise") else "")
                 + f" (`{cli.NAME} profile show` lists them)."
                 + (f" {len(merged.unresolved)} wait for the person's answer once." if merged.unresolved else ""))
    parts = {}
    if not offline and config["project"].get("repo"):
        parts = {"leads": lambda: leads_part(config, lead), "prs": lambda: prs_part(config),
                 "cards": lambda: cards_part(config, lead), "posted": lambda: handover_part(config, lead),
                 "orders": lambda: publish_orders(config, lead) if me() == cli.LEAD and lead else None}
    parts["capacity"] = lambda: capacity_part(config, person)
    parts["summary"] = lambda: summary(config)
    got = run_parts(parts, deadline)
    snap = last_handover(config, name)
    posted = got.get("posted") if isinstance(got.get("posted"), str) else ""
    if snap:
        lines += handover_lines(snap, full=True)
    if posted:
        first, *rest = posted.splitlines()
        if not snap or "automatic" not in posted:
            lines.append(f"Last posted {first}: " + "; ".join(line for line in rest if not line.startswith("<!--")))
    made = got.get("summary")
    if isinstance(made, dict):
        root = cli.repo_root()
        lines += summary_lines(made, since(config, root, name, made.get("head", "")), short=True)
    elif made is not None:
        lines.append(f"Project summary: not built ({made}).")
    for part in ("leads", "prs", "cards", "capacity"):
        result = got.get(part)
        if isinstance(result, list):
            lines += result
        elif part in got:
            lines.append(f"{part.capitalize()}: not read in time." if result is None else
                         f"{part.capitalize()}: not read ({clean(str(result), 150)}).")
    held = read_plan(config, lead) if lead else None
    if held:
        done = len([g for g in held["groups"] if g.get("done_at")])
        lines.append(f"Plan for \"{clean(held['request'], 120)}\": {done} of {len(held['groups'])} task groups done.")
    pending = decisions.pending_lines(config)
    if pending:
        lines.append(f"Waiting on the person ({len(pending)}): {'; '.join(pending[:3])}"
                     + (f"; and {len(pending) - 3} more (`{cli.NAME} decisions`)." if len(pending) > 3 else "."))
    taken = decisions.recent_lines(config, lead)
    if taken:
        lines.append(f"Decided alone since the last handover: {len(taken)} (`{cli.NAME} decisions --log`).")
    lines.append(next_line(held, snap, pending))
    return lines


def next_line(held: dict | None, snap: dict | None, pending: list[str]) -> str:
    """The briefing's last line: resume the plan, or ask the person one question."""
    if held and any(not g.get("done_at") for g in held["groups"]):
        step = next_step(held, [])
        return (f"Next: resume the plan at once, without asking: {step}. Check on each task group's lead and helpers, "
                "and leave nothing idle.")
    if snap and snap.get("next") and time.time() - float(snap.get("at") or 0) < 3 * 24 * 3600:
        return f"Next: resume from the handover, without asking first: {snap['next']}."
    if pending:
        return f"Next: ask the person one question, the oldest waiting decision: {pending[0]}."
    return ("Next: ask the person one question, \"What should we work on first?\", with your pick from the open pull "
            "requests and cards above.")


def boot_cmd(config: dict, args) -> int:
    """`colony boot [--offline] [--json]`: the startup routine's briefing."""
    lines = briefing(config, args, offline=args.offline)
    if args.json:
        print(json.dumps({"lines": lines}, ensure_ascii=False))
    else:
        print("\n".join(lines))
    return 0


def after_claim(config: dict, args) -> None:
    """The startup routine at the end of plain `colony` in a session that just became a lead: the briefing, without
    being asked. It never stops `colony`."""
    try:
        print("\n".join(["", *briefing(config, args)]))
    except (wait.GhError, *EXPIRED) as e:
        print(f"{cli.NAME}: the briefing did not run: {e}. Run `{cli.NAME} boot` once.", file=sys.stderr)


# The hooks


HOOK_EVENTS = ("start", "compact", "end", "turn", "tool")
# Each project's marker, ~/.colony/<project>/approvals.live, exists while one of its approvals is live
# (decisions.live_marker). The tool hook's gate runs Colony only while some project has one, so it costs nothing
# otherwise; the project's own approvals then decide.
APPROVALS_LIVE = f'"$HOME/.{cli.NAME}"/*/approvals.live'


def session_hook(config: dict, args) -> int:
    """`colony session-hook <event>`, which Claude Code runs: `start` (SessionStart) prints the briefing for a lead, or
    after a compaction the handover; `compact` (PreCompact) and `end` (SessionEnd) save the handover and post a lead's;
    `turn` (Stop) keeps the snapshot current; `tool` (PreToolUse) lets a call the person approved through. It always
    exits 0, and a problem goes to stderr."""
    from colony import decisions, guards

    payload = guards.hook_event()
    session = me()
    if not session:
        return 0
    name = wait.state_name(session)
    try:
        if args.event == "tool":
            answer = decisions.tool_decision(config, session, payload)
            if answer:
                print(json.dumps(answer))
        elif args.event == "start":
            source = str(payload.get("source") or "")
            snap = last_handover(config, name)
            if source == "compact":
                if snap:
                    print("\n".join([f"{cli.DISPLAY}: your conversation was compacted. Carry on from here.",
                                     *handover_lines(snap)]))
            elif session == cli.LEAD:
                print("\n".join(briefing(config, args)))
            elif snap and source == "resume":
                print("\n".join(handover_lines(snap)))
        else:
            snap = snapshot(config, name, args.event, payload)
            if args.event in ("compact", "end") and session == cli.LEAD:
                post_handover(config, snap)
            save_snapshot(config, name, snap)
    except (wait.GhError, *EXPIRED) as e:
        print(f"{cli.NAME} session-hook {args.event}: {e}", file=sys.stderr)
    return 0


def hook_command(event: str, program: str, gate: str = "") -> str:
    """A hook's shell command that runs `colony session-hook <event>` in a Colony session, skips every other one,
    and always exits 0."""
    from colony import guards

    return (f'{{ [ -n "${cli.SESSION_ENV}" ] || [ -f "{guards.IDENTITY_FILE}" ]; }} && command -v {program} '
            f'>/dev/null 2>&1 || exit 0; {gate}cd "$CLAUDE_PROJECT_DIR" 2>/dev/null && {program} session-hook {event}; '
            "exit 0")


def hook_entries(program: str) -> list[tuple[str, str | None, dict, str]]:
    """This module's hooks, in guards.hook_entries' shape: the startup routine, the automatic handover, and the
    approvals a helper's permission check reads."""
    from colony import guards

    def hook(event: str, **more) -> dict:
        gate = f'set -- {APPROVALS_LIVE}; [ -f "$1" ] || exit 0; ' if event == "tool" else ""
        return {"type": "command", "command": hook_command(event, program, gate), **more}

    return [("SessionStart", None, hook("start", timeout=guards.HOOK_TIMEOUT), "session-hook start"),
            ("PreCompact", None, hook("compact", timeout=guards.HOOK_TIMEOUT), "session-hook compact"),
            ("SessionEnd", None, hook("end", timeout=guards.HOOK_TIMEOUT), "session-hook end"),
            ("Stop", None, hook("turn", **{"async": True}), "session-hook turn"),
            ("PreToolUse", None, hook("tool", timeout=10), "session-hook tool")]


def register(sub) -> None:
    """cli.py's route to this module: boot, summary, mode, plan, orders and session-hook."""
    p = sub.add_parser("boot", help="the startup routine: orders, handover, project summary, leads, pull requests, "
                                    "cards, decisions and room, then the next step")
    p.add_argument("--offline", action="store_true", help="read nothing from GitHub")
    p.add_argument("--json", action="store_true", help="print the briefing's lines as JSON")
    p.add_argument("--person", help="whose session this is")
    p.set_defaults(run=boot_cmd)
    p = sub.add_parser("summary", help="the project summary, built once and refreshed from what changed")
    p.add_argument("--rebuild", action="store_true", help="build it again from scratch")
    p.add_argument("--json", action="store_true", help="print it as JSON")
    p.set_defaults(run=summary_cmd)
    p = sub.add_parser("mode", help="list the modes, switch one on with one word, switch it off, show or define one")
    p.add_argument("words", nargs="*", metavar="word", help="<name>, off, show <name>, or define <name>")
    p.add_argument("--personal", action="store_true", help="for every session, in your personal profile")
    p.add_argument("--team", action="store_true", help="define: the team's mode, .colony/modes/<name>.toml")
    p.add_argument("--set", action="append", metavar="KEY=VALUE", help="define: a setting the mode holds")
    p.add_argument("--rule", action="append", metavar="RULE", help="define: a rule the mode holds")
    p.add_argument("--about", help="define: what the mode is for, in one sentence")
    p.add_argument("--person", help="whose profile, when $COLONY_PERSON is not set")
    p.set_defaults(run=mode_cmd)
    p = sub.add_parser("plan", help="request intake: turn one request into task groups with owners and done-when "
                                    "results, and start them")
    p.add_argument("--person", help="whose session this is")
    p.add_argument("--account", metavar="NAME", help=cli.ACCOUNT_HELP)
    p.set_defaults(run=plan_cmd, action=None, of=None, group=None, json=False)
    actions = p.add_subparsers(dest="action", metavar="action")
    a = actions.add_parser("new", help="start a plan for one request")
    a.add_argument("request", help="the request, in quotes, word for word")
    a.add_argument("--show-first", action="store_true", help="show the plan to the person before it starts")
    a.add_argument("--replace", action="store_true", help="replace a plan whose groups aren't done")
    a = actions.add_parser("group", help="add or change one task group")
    a.add_argument("name", help="the group's short name, such as web")
    a.add_argument("--folders", nargs="+", metavar="FOLDER", help="the folders it owns")
    a.add_argument("--done", action="append", metavar="RESULT", help="a done-when result; up to 3")
    a.add_argument("--helpers", type=int, help="how many helpers its lead runs")
    a.add_argument("--draft", action="store_true", help="draft it first, and build only after the person's yes")
    a = actions.add_parser("show", help="the plan and where each group stands")
    a.add_argument("--of", metavar="LEAD", help="another lead's plan on this computer, such as your orchestrator's")
    a.add_argument("--group", help="one group alone")
    a.add_argument("--json", action="store_true", help="print it as JSON")
    a = actions.add_parser("start", help="start the groups: one lead each for an orchestrator, cards for a lead")
    a.add_argument("--approved", metavar="WORDS", help="the person's yes, word for word, when it is shown first")
    a.add_argument("--dry-run", action="store_true", help="print what it would open, and run nothing")
    a = actions.add_parser("done", help="mark a task group done")
    a.add_argument("name", help="the group")
    a = actions.add_parser("approve", help="record the person's yes on a group's draft")
    a.add_argument("name", help="the group")
    a.add_argument("words", help="the person's yes, word for word")
    for name, parser in actions.choices.items():
        parser.set_defaults(dry_run=False, replace=False, show_first=False, approved=None)
    p = sub.add_parser("orders", help="the standing orders this lead passes its helpers")
    p.add_argument("--publish", action="store_true", help="publish them now for helpers on other computers")
    p.add_argument("--person", help="whose session this is")
    p.set_defaults(run=orders_cmd)
    p = sub.add_parser("session-hook", help="the startup, handover and approvals hooks (Claude Code runs them)")
    p.add_argument("event", choices=HOOK_EVENTS)
    p.set_defaults(run=session_hook)
