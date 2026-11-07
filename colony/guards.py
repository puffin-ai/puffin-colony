"""colony suppressions and colony hooks: the guards a repo keeps on its agents.

`colony suppressions` holds each file's count of lint and type suppressions to `.colony/suppressions.json`, a record
that only shrinks. `colony hooks install` merges five hooks into `.claude/settings.json`, keeping the hooks already
there: the wait guard (hooks/wait_guard.py, copied into `.colony/hooks/`), two that post a line on the coordination
issue, `asking` when a builder waits on a permission pop-up and `stopped` when a turn ends on an error, and the prompt
hook, `unread`, which shows a session the lines addressed to it that it hasn't read, when it starts and before each
prompt. Every mode installs all five.

A hook's line that can't post, because gh fails, waits in the outbox, ~/.colony/<project>/outbox.json, and the next
hook run or wait poll on the computer posts it, oldest first (flush_outbox), so it is never lost. The prompt hook also
says, at most once a day, when the session runs without CLAUDE_CODE_RETRY_WATCHDOG, which Colony sets for its
sessions so a usage limit or a dropped connection never ends a turn for good.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shlex
import subprocess
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from colony import cli, portable

LEDGER = "suppressions.json"  # in .colony/
GUARD = "wait_guard.py"  # in the package's hooks/, copied to .colony/hooks/
ASKING_REPEAT = 600  # a builder posts at most one asking line per 10 minutes
ERROR_CODE = re.compile(r"[a-z_]{1,40}")
UNREAD_EVERY = 30  # with no wait running, the prompt hook reads GitHub itself at most once per 30 seconds
WAIT_FRESH = 60  # a wait whose last poll is under a minute old is running, and the prompt hook leaves GitHub to it
HOOK_TIMEOUT = 20  # seconds Claude Code gives the prompt hook before it goes on without it
OUTBOX = "outbox"  # ~/.colony/<project>/outbox.json: the hooks' lines that failed to post, oldest first
WATCHDOG_ENV = "CLAUDE_CODE_RETRY_WATCHDOG"
WATCHDOG_EVERY = 24 * 3600  # the prompt hook says a session runs without the watchdog at most once a day
# The starter skills shipped in skills/ beside the role skills, which setup offers.
STARTER_SKILLS = ("diagnosing-bugs", "tdd", "code-review", "resolving-merge-conflicts", "retro", "implement-spec",
                  "prototype", "grill-me", "writing-for-agents", "git-guardrails")

PY = (".py", ".pyi")
JS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".vue", ".svelte", ".astro")
CSS = (".css", ".scss", ".sass", ".less")
JVM = (".java", ".kt", ".kts", ".scala")
# Each kind of suppression: its name in the record, its pattern, and the file endings it is read in.
KINDS = [(kind, re.compile(pattern), endings) for kind, pattern, endings in (
    ("noqa", r"(?i)#\s*(?:(?:ruff|flake8):\s*)?noqa\b", PY),  # ruff and flake8 take it in any case
    ("type-ignore", r"#\s*type:\s*ignore\b", PY),
    ("pyright-ignore", r"#\s*pyright:\s*ignore\b", PY),
    ("pylint-disable", r"#\s*pylint:\s*disable", PY),
    ("xfail", r"\bxfail\b", PY),
    ("test-skip", r"\bpytest\.(?:mark\.skip(?:if)?\b|skip\(|importorskip\()|\bunittest\.skip|@mark\.skip", PY),
    ("eslint-disable", r"\b(?:eslint|oxlint)-disable", JS),
    ("biome-ignore", r"biome-ignore", JS + CSS),
    ("ts-expect-error", r"@ts-expect-error", JS + CSS),
    ("ts-ignore", r"@ts-ignore", JS + CSS),
    ("ts-nocheck", r"@ts-nocheck", JS),
    ("test-skip", r"\b(?:test|it|describe|suite|setup|teardown|\w+Test)\.(?:skip|todo|fixme|skipIf)\b(?:\.each)?\s*\("
                  r"|\b(?:test|it|describe|suite)\(\s*[\"'`][^\"'`]*[\"'`]\s*,\s*\{[^}]*\b(?:skip|todo)\s*:", JS + CSS),
    ("stylelint-disable", r"stylelint-disable", JS + CSS),
    ("nolint", r"//\s*nolint\b", (".go",)),
    ("test-skip", r"\bt\.Skip(?:f|Now)?\(", (".go",)),
    ("allow", r"#!?\[allow\(", (".rs",)),
    ("test-skip", r"#\[ignore\b", (".rs",)),
    ("rubocop-disable", r"rubocop:disable", (".rb",)),
    ("suppress-warnings", r"@SuppressWarnings\b", JVM),
    ("test-skip", r"@(?:Disabled|Ignore)\b", JVM),
    ("swiftlint-disable", r"swiftlint:disable", (".swift",)),
    ("shellcheck-disable", r"shellcheck\s+disable", (".sh", ".bash", ".zsh")),
    ("pragma-warning", r"#pragma\s+warning\s+disable", (".cs",)),
)]

Counts = dict[str, dict[str, int]]  # path -> kind -> count, holding only the files and kinds that occur


def tracked_files(root: Path, paths: list[str]) -> list[str]:
    """The repo's tracked files under `paths` (the whole repo when empty), relative to its top."""
    run = subprocess.run(["git", "ls-files", "-z", "--", *paths], cwd=root, capture_output=True, text=True)
    if run.returncode:
        raise cli.ColonyError(f"git ls-files failed: {run.stderr.strip()[:200]}")
    return [path for path in run.stdout.split("\0") if path]


def count(root: Path, paths: list[str]) -> Counts:
    """Count each kind of suppression in each file."""
    counts: Counts = {}
    for path in paths:
        kinds = [(kind, pattern) for kind, pattern, endings in KINDS if path.lower().endswith(endings)]
        if not kinds or not (root / path).is_file():
            continue
        text = (root / path).read_text(encoding="utf-8", errors="replace")
        found: Counter[str] = Counter()
        for kind, pattern in kinds:
            found[kind] += len(pattern.findall(text))
        kept = {kind: number for kind, number in sorted(found.items()) if number}
        if kept:
            counts[path] = kept
    return counts


def compare(counts: Counts, record: Counts) -> tuple[list[str], list[str]]:
    """The lines naming each count above its record, and each record a count fell below."""
    rises, falls = [], []
    for path in sorted(set(counts) | set(record)):
        now, recorded = counts.get(path, {}), record.get(path, {})
        for kind in sorted(set(now) | set(recorded)):
            seen, allowed = now.get(kind, 0), recorded.get(kind, 0)
            if seen > allowed:
                rises.append(f"{path}: {seen} {kind}, the record allows {allowed}")
            elif seen < allowed:
                falls.append(f"{path}: {seen} {kind}, the record holds {allowed}")
    return rises, falls


def shrink(counts: Counts, record: Counts) -> Counts:
    """Lower each record to today's count, never raising one or adding a file."""
    lowered: Counts = {}
    for path, recorded in record.items():
        kept = {kind: low for kind, allowed in recorded.items() if (low := min(allowed, counts.get(path, {}).get(kind, 0)))}
        if kept:
            lowered[path] = kept
    return lowered


def load_ledger(path: Path) -> Counts:
    """Read the record, `{"<path>": {"<kind>": <count>}}`."""
    try:
        record = json.loads(path.read_text())
    except ValueError as e:
        raise cli.ColonyError(f"{path} is not valid JSON ({e}): fix it, then run this again") from None
    if not isinstance(record, dict) or not all(isinstance(kinds, dict) for kinds in record.values()):
        raise cli.ColonyError(f'{path} must map each file to its counts, such as {{"src/a.py": {{"noqa": 1}}}}')
    return record


def save_ledger(path: Path, record: Counts) -> None:
    """Write the record in path order, one file's counts per group of lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {name: dict(sorted(kinds.items())) for name, kinds in sorted(record.items())}
    path.write_text(json.dumps(ordered, indent=2) + "\n")


def suppressions(config: dict, args) -> int:
    """`colony suppressions [--update]`: fail when a file's count of a kind rises above the record, or falls below it
    until --update writes the lower count. --update never raises a count or adds a file; the first run records."""
    root = cli.repo_root()
    path = root / cli.DIR / LEDGER
    counts = count(root, tracked_files(root, list(config.get("suppressions", {}).get("paths", []))))
    total = sum(sum(kinds.values()) for kinds in counts.values())
    if not path.exists():
        if not args.update:
            raise cli.ColonyError(f"{cli.DIR}/{LEDGER} is missing: run `{cli.NAME} suppressions --update` to record "
                                  "today's counts")
        save_ledger(path, counts)
        print(f"recorded {total} suppressions in {len(counts)} files in {cli.DIR}/{LEDGER}")
        return 0
    record = load_ledger(path)
    rises, falls = compare(counts, record)
    if args.update and falls:
        save_ledger(path, shrink(counts, record))
        print(f"lowered {len(falls)} records in {cli.DIR}/{LEDGER}")
    for line in rises:
        print(f"RISE {line}")
    if rises:
        print("A suppression silences a check, and no agent weakens a check to make it pass: fix the finding, or ask "
              "the person.")
        return 1
    if falls and not args.update:
        for line in falls:
            print(f"FALL {line}")
        print(f"Run `{cli.NAME} suppressions --update` to lower the record.")
        return 1
    print(f"{total} suppressions in {len(counts)} files, none above the record.")
    return 0


def python_command(path: str, *args: str, root: str = "$CLAUDE_PROJECT_DIR") -> str:
    """A hook's shell command that runs a script under `root` with the first Python it finds, and skips a missing
    script."""
    run = " ".join(f'"{part}"' for part in ("$f", *args))
    return (f'f="{root}/{path}"; [ -f "$f" ] || exit 0; if python3 -V >/dev/null 2>&1; then exec python3 '
            f"{run}; elif python -V >/dev/null 2>&1; then exec python {run}; else exec py -3 {run}; fi")


PLUGIN_BIN = '"${CLAUDE_PLUGIN_ROOT}/bin/colony"'  # the plugin's own `colony`: a hook's PATH lacks the plugin's bin/


def colony_command(action: str, program: str = cli.NAME) -> str:
    """A hook's shell command that runs `colony hooks <action>` in a Colony session, and skips every other one."""
    return (f'[ -n "${cli.SESSION_ENV}" ] && command -v {program} >/dev/null 2>&1 || exit 0; '
            f'cd "$CLAUDE_PROJECT_DIR" && exec {program} hooks {action}')


def quiet_command(action: str, program: str = cli.NAME) -> str:
    """A hook's shell command that runs `colony hooks <action>` in a Colony session, skips every other one, and always
    exits 0: a UserPromptSubmit hook that exits 2 would erase the person's prompt."""
    return (f'[ -n "${cli.SESSION_ENV}" ] && command -v {program} >/dev/null 2>&1 || exit 0; '
            f'cd "$CLAUDE_PROJECT_DIR" 2>/dev/null && {program} hooks {action}; exit 0')


def step_aside(marker: str, ready: str) -> str:
    """The start of a plugin hook's command: exit when the repo's settings carry the same hook from `colony hooks
    install`, found by its `marker`, and `ready` says that hook can run, so each hook runs once."""
    files = " ".join(f'"$CLAUDE_PROJECT_DIR/.claude/{name}"' for name in ("settings.json", "settings.local.json"))
    return f"{ready} && grep -qsF {shlex.quote(marker)} {files} && exit 0; "


def hook_entries(plugin: bool = False) -> list[tuple[str, str | None, dict, str]]:
    """Colony's hooks: (event, matcher, hook, the marker that finds the hook in a settings file). The `plugin`'s run
    the wait guard and `colony` from the plugin's own copy, where `colony hooks install` copies the guard into the
    repo and runs the `colony` on PATH. Where the repo's own copy of a hook can run, the plugin's steps aside."""
    guard = f"colony/hooks/{GUARD}" if plugin else f"{cli.DIR}/hooks/{GUARD}"
    root = "${CLAUDE_PLUGIN_ROOT}" if plugin else "$CLAUDE_PROJECT_DIR"
    program = PLUGIN_BIN if plugin else cli.NAME
    unread_hook = {"type": "command", "command": quiet_command("unread", program), "timeout": HOOK_TIMEOUT}
    entries = [
        ("PreToolUse", "Bash", {"type": "command", "command": python_command(guard, root=root)}, guard),
        ("Notification", "permission_prompt",
         {"type": "command", "command": colony_command("asking", program), "async": True}, f"{cli.NAME} hooks asking"),
        ("StopFailure", None, {"type": "command", "command": colony_command("stopped", program), "async": True},
         f"{cli.NAME} hooks stopped"),
        ("UserPromptSubmit", None, unread_hook, f"{cli.NAME} hooks unread"),
        ("SessionStart", None, dict(unread_hook), f"{cli.NAME} hooks unread"),
    ]
    if not plugin:
        return entries
    # The repo's guard needs only its copied script, and its other hooks need the `colony` on PATH.
    repo_guard = f'[ -f "$CLAUDE_PROJECT_DIR/{cli.DIR}/hooks/{GUARD}" ]'
    on_path = f"command -v {cli.NAME} >/dev/null 2>&1"
    return [(event, matcher, {**hook, "command": step_aside(mine, repo_guard if GUARD in mine else on_path)
                              + hook["command"]}, marker)
            for (event, matcher, hook, marker), (*_, mine) in zip(entries, hook_entries())]


PLUGIN_HOOKS = "hooks/hooks.json"  # in the package: the plugin's hooks (.claude-plugin/plugin.json names it)


def plugin_hooks() -> dict:
    """The plugin's hooks file: the hooks `colony hooks install` writes, in the hooks.json form Claude Code reads
    from a plugin. tests/test_plugin.py keeps the shipped file equal to it."""
    hooks: dict[str, list] = {}
    for event, matcher, hook, _ in hook_entries(plugin=True):
        hooks.setdefault(event, []).append({**({"matcher": matcher} if matcher else {}), "hooks": [hook]})
    hooks["SessionStart"].append({"hooks": [{"type": "command", "command": first_run_command()}]})
    return {"description": f"{cli.DISPLAY}'s hooks, the ones `{cli.NAME} hooks install` writes, and its first run",
            "hooks": hooks}


UV_INSTALLER = "https://astral.sh/uv/install.sh"  # Astral's official installer, which puts uv in ~/.local/bin
UV_HOME_BIN = "$HOME/.local/bin/uv"  # where that installer puts uv, which bin/colony looks in too


def first_run_command() -> str:
    """The plugin's SessionStart hook: the plugin's bin/colony runs Colony through uv, so when the computer has no uv,
    install it with Astral's official installer and say so in one line. With uv in place it says nothing, and it
    always exits 0."""
    def say(message: str) -> str:
        event = {"systemMessage": message,
                 "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": message}}
        return f"printf '%s\\n' {shlex.quote(json.dumps(event))}"
    installed = say(f"{cli.DISPLAY} installed uv, which runs the {cli.NAME} command, with Astral's installer "
                    f"({UV_INSTALLER}).")
    failed = say(f"{cli.DISPLAY} could not install uv, which runs the {cli.NAME} command: install it from "
                 f"https://docs.astral.sh/uv/ and start a new session.")
    have_uv = f'command -v uv >/dev/null 2>&1 || [ -x "{UV_HOME_BIN}" ]'
    return (f"{have_uv} && exit 0; "
            f"if command -v curl >/dev/null 2>&1; then curl -LsSf {UV_INSTALLER}; else wget -qO- {UV_INSTALLER}; fi "
            f"2>/dev/null | sh >/dev/null 2>&1; "
            f"if {have_uv}; then {installed}; else {failed}; fi; exit 0")


def merge_hooks(path: Path) -> tuple[list[str], list[str]]:
    """Merge Colony's hooks into a Claude Code settings file, keeping every other key and every hook already there,
    and return the events whose hook was added and those whose hook was brought up to date.

    A Colony hook already in the file, found by its marker, is updated in place. A file that is not a JSON object with
    a `hooks` object of lists is left as it is, with an error that says so.
    """
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except ValueError as e:
            raise cli.ColonyError(f"{path} is not valid JSON ({e}): fix it, then run this again") from None
    if not isinstance(data, dict) or not isinstance(data.setdefault("hooks", {}), dict):
        raise cli.ColonyError(f"{path} must hold a JSON object with a hooks object: fix it, then run this again")
    added, updated = [], []
    for event, matcher, hook, marker in hook_entries():
        groups = data["hooks"].setdefault(event, [])
        if not isinstance(groups, list):
            raise cli.ColonyError(f"{path}: hooks.{event} must be a list: fix it, then run this again")
        mine = [entry for group in groups if isinstance(group, dict) for entry in group.get("hooks", [])
                if isinstance(entry, dict) and marker in str(entry.get("command", ""))]
        if not mine:
            groups.append({**({"matcher": matcher} if matcher else {}), "hooks": [hook]})
            added.append(event)
        elif any(entry != hook for entry in mine):
            for entry in mine:
                entry.clear()
                entry.update(hook)
            updated.append(event)
    if added or updated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")
    return added, updated


def install(config: dict, args) -> int:
    """`colony hooks install`: merge Colony's hooks into .claude/settings.json, and copy the wait guard into
    .colony/hooks/. Every mode gets the same five hooks."""
    root = cli.repo_root()
    # --local writes this machine's settings.local.json, which git ignores, so the hooks don't reach a CI job.
    name = "settings.local.json" if getattr(args, "local", False) else "settings.json"
    settings, guard = root / ".claude" / name, root / cli.DIR / "hooks" / GUARD
    events = ", ".join(event for event, *_ in hook_entries())
    if args.dry_run:
        print(f"hooks plan for {root}:")
        print(f"  .claude/{name}: merge the {events} hooks, keeping every hook already there")
        print(f"  {cli.DIR}/hooks/{GUARD}: the wait guard, copied from the package")
        print("Nothing ran.")
        return 0
    added, updated = merge_hooks(settings)
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text(resources.files(__package__).joinpath("hooks", GUARD).read_text())
    guard.chmod(0o755)
    done = f"added {', '.join(added) or 'nothing'}" + (f", updated {', '.join(updated)}" if updated else "")
    print(f"wrote .claude/{name}: {done}, and kept every hook already there")
    print(f"wrote {cli.DIR}/hooks/{GUARD}")
    return 0


def hook_event() -> dict:
    """The JSON event Claude Code passes a hook on stdin, or an empty one when stdin holds no JSON object."""
    try:
        event = {} if sys.stdin.isatty() else json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return {}
    return event if isinstance(event, dict) else {}


def outbox_path(config: dict) -> Path:
    """The outbox: ~/.colony/<project>/outbox.json."""
    from colony import wait

    return wait.state_path(config["project"]["name"], OUTBOX)


@contextmanager
def outbox_lock(config: dict, block: bool = True):
    """Hold the outbox's file lock, and yield whether it is held: a flush that finds another one running skips."""
    path = outbox_path(config).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle, portable.lock(handle, block) as got:
        yield got


def read_outbox(config: dict) -> list[dict]:
    """The outbox's lines, each `{to, line, at}`, oldest first; an unreadable entry is left out."""
    from colony import wait

    items = wait.read_json(outbox_path(config), [])
    return [item for item in items if isinstance(item, dict) and item.get("to") and item.get("line")] \
        if isinstance(items, list) else []


def write_outbox(config: dict, items: list[dict]) -> None:
    """Write the outbox whole, or remove it when it is empty."""
    from colony import wait

    if items:
        wait.write_json(outbox_path(config), items)
    else:
        outbox_path(config).unlink(missing_ok=True)


# What a post that GitHub or gh refused raises: its line waits in the outbox. Any other ColonyError, such as a line
# that holds a secret, would fail again, so its line is never kept.
POST_FAILURES = (OSError, ValueError, KeyError, subprocess.SubprocessError)


def flush_outbox(config: dict) -> int:
    """Post the outbox's lines, oldest first, and return how many posted. The first that fails again stays, with every
    later one, for the next hook run or wait poll. It never raises, and skips while another flush runs."""
    from colony import transport, wait

    try:
        if not outbox_path(config).exists():
            return 0
        with outbox_lock(config, block=False) as held:
            if not held:
                return 0
            items, sent = read_outbox(config), 0
            for item in items:
                try:
                    transport.send(config, item["to"], item["line"])
                except (wait.GhError, *POST_FAILURES) as e:
                    print(f"{cli.NAME}: {len(items) - sent} lines wait in the outbox, {outbox_path(config)}: {e}",
                          file=sys.stderr)
                    break
                except cli.ColonyError as e:
                    print(f"{cli.NAME}: an outbox line can never post, and is dropped: {e}", file=sys.stderr)
                sent += 1
            write_outbox(config, items[sent:])
            return sent
    except (OSError, ValueError, KeyError) as e:
        print(f"{cli.NAME}: the outbox was not read: {e}", file=sys.stderr)
        return 0


def keep_in_outbox(config: dict, to: str, line: str) -> None:
    """Add a line to the end of the outbox."""
    with outbox_lock(config):
        write_outbox(config, [*read_outbox(config), {"to": to, "line": line, "at": time.time()}])


def post(config: dict, to: str, sentence: str, sender: str) -> int:
    """Post `for <to>: <sentence> (from <sender>)` on the coordination issue, where the lead's wait reads it, through
    transport.send, after the outbox's older lines. A line gh can't post, or one behind lines still waiting, goes to
    the end of the outbox."""
    from colony import transport, wait

    line = f"for {to}: {sentence} (from {sender})"
    flush_outbox(config)
    try:
        if read_outbox(config):
            raise wait.GhError("older lines still wait to post")
        number = transport.send(config, to, line)
    except (wait.GhError, *POST_FAILURES) as e:
        try:
            keep_in_outbox(config, to, line)
        except OSError as kept:
            print(f"{cli.NAME} hooks: the line was not posted: {e}, nor kept: {kept}", file=sys.stderr)
            return 1
        print(f"{cli.NAME} hooks: the line was not posted: {e}. It waits in {outbox_path(config)}, and the next hook "
              f"or wait posts it.", file=sys.stderr)
        return 1
    except cli.ColonyError as e:
        print(f"{cli.NAME} hooks: the line was not posted: {e}", file=sys.stderr)
        return 1
    print(f"#{number} {line}")
    return 0


def session_names(config: dict, args) -> tuple[str, str, str]:
    """This session's name, its person, and its lead's name on the coordination issue, such as ana-lead."""
    me = os.environ.get(cli.SESSION_ENV, "").lower()
    try:
        person = cli.person_of(config, args).lower()
    except cli.ColonyError:
        return me, "", cli.LEAD  # several people and no COLONY_PERSON: every lead takes a line for `lead`
    return me, person, f"{person}-{cli.LEAD}"


def asking(config: dict, args) -> int:
    """`colony hooks asking`, the Notification hook for permission_prompt: an urgent line for the builder's lead, at
    most once per 10 minutes. The lead posts none, because its own pop-up is in front of its person."""
    from colony import wait

    hook_event()  # read and dropped: a prompt can quote a command, a path or a token, so it stays in the window
    me, _, lead = session_names(config, args)
    if not me or me == cli.LEAD:
        return 0
    last_path = wait.state_path(config["project"]["name"], f"{me}-asking")
    last = wait.read_json(last_path, 0)
    if isinstance(last, (int, float)) and time.time() - last < ASKING_REPEAT:
        return 0
    wait.write_json(last_path, time.time())
    return post(config, lead, f"urgent: {me} waits for a person's approval on {platform.node()[:60]}", me)


def stopped(config: dict, args) -> int:
    """`colony hooks stopped`, the StopFailure hook: a line saying the turn ended on an error, for a builder's lead,
    or for the lead's person. It names the error's code word alone, never text that could quote a secret."""
    error = str(hook_event().get("error") or "")
    me, person, lead = session_names(config, args)
    if not me:
        return 0
    cause = error if ERROR_CODE.fullmatch(error) else "unknown error"
    at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if me == cli.LEAD:
        sender = lead if person else cli.LEAD
        return post(config, person or cli.LEAD, f"{sender} stopped on an error ({cause}) at {at}", sender)
    return post(config, lead, f"{me} stopped on an error ({cause}) at {at}", me)


def save_state(path: Path, state: dict) -> None:
    """Write a wait's state file whole, through a temporary file, so a wait reading it never sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}")
    temporary.write_text(json.dumps(state))
    os.replace(temporary, path)


def read_unread(config: dict, args, me: str) -> list[dict]:
    """The unread cache's lines for the session `me`, taken out of its state file (see `unread`)."""
    from colony import wait

    path = wait.state_path(config["project"]["name"], wait.state_name(me))
    state = wait.read_json(path, {})
    state = state if isinstance(state, dict) else {}
    now = time.time()
    running = now - float(state.get("polled_at") or 0) < WAIT_FRESH
    if not running and now - float(state.get("hook_polled_at") or 0) >= UNREAD_EVERY:
        state["hook_polled_at"] = now  # before the call, so a hanging network is tried again only after the interval
        save_state(path, state)
        flush_outbox(config)  # a running wait flushes it at each poll
        state.setdefault("since", (datetime.now(timezone.utc) - wait.LOOKBACK).strftime("%Y-%m-%dT%H:%M:%SZ"))
        state.setdefault("pending", [])
        try:
            wait.poll(config["project"]["repo"], state, wait.session(config, args, me))
        except (cli.ColonyError, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
            print(f"{cli.NAME} hooks unread: GitHub was not read, and the hook tries again in {UNREAD_EVERY} seconds: "
                  f"{e}", file=sys.stderr)
        save_state(path, state)
    entries = [entry for entry in state.get("unread") or [] if isinstance(entry, dict)]
    if not entries:
        return []
    if running:
        # The wait owns the file: read it again just before writing, and take out only the lines shown here. The
        # wait drops them from its own gathered lines when it next reads the file (wait.drop_shown).
        state = wait.read_json(path, {})
        state = state if isinstance(state, dict) else {}
        state["unread"] = [entry for entry in state.get("unread") or [] if entry not in entries]
    else:
        shown = {wait.unread_text(entry) for entry in entries}
        state["unread"] = []
        state["pending"] = [item for item in state.get("pending", []) if not item or item[0] not in shown]
        state["listed"] = [text for text in state.get("listed", []) if text not in shown]
    save_state(path, state)
    return entries


def watchdog_note(config: dict, me: str, now: float | None = None) -> str:
    """The line that says this session runs without CLAUDE_CODE_RETRY_WATCHDOG, at most once a day per session, else
    an empty string."""
    from colony import wait

    if os.environ.get(WATCHDOG_ENV, "").strip() not in ("", "0", "false"):
        return ""
    now = time.time() if now is None else now
    path = wait.state_path(config["project"]["name"], f"{wait.state_name(me)}-watchdog")
    last = wait.read_json(path, 0)
    if isinstance(last, (int, float)) and now - last < WATCHDOG_EVERY:
        return ""
    wait.write_json(path, now)
    return (f"{me} runs without {WATCHDOG_ENV}=1, so a usage limit or a dropped connection can end a turn for good: "
            f"reopen it through `{cli.NAME}`, which sets it (this note shows once a day).")


def unread(config: dict, args) -> int:
    """`colony hooks unread`, the UserPromptSubmit and SessionStart hook: print the lines addressed to this session that
    it hasn't read, then empty the unread cache they came from.

    The cache is `unread` in the state file `colony wait` keeps, ~/.colony/<project>/<session>.json. While a wait runs,
    which its last poll (`polled_at`, under WAIT_FRESH seconds old) shows, the hook makes no network call. Otherwise it
    reads GitHub itself through wait.poll, with the wait's read time and ETag, at most once per UNREAD_EVERY seconds,
    so the lines it shows never print again in a later wait. It never stops the prompt: a problem goes to stderr."""
    from colony import wait

    hook_event()  # read and dropped: the prompt stays in the window
    me = os.environ.get(cli.SESSION_ENV, "").lower()
    if not me:
        return 0
    try:
        note = watchdog_note(config, me)
    except (OSError, ValueError, KeyError) as e:
        note = ""
        print(f"{cli.NAME} hooks unread: {e}", file=sys.stderr)
    if note:
        print(note)
    try:
        entries = read_unread(config, args, me)
    except (cli.ColonyError, OSError, ValueError, KeyError, TypeError) as e:
        print(f"{cli.NAME} hooks unread: {e}", file=sys.stderr)
        return 0
    if entries:
        print(f"Unread lines for {me}, which colony wait won't print again:")
        print("\n".join(wait.unread_text(entry) for entry in entries))
    return 0


def add_commands(sub) -> None:
    """cli.py's route to this module: `suppressions`, and `hooks install`, `hooks asking`, `hooks stopped` and
    `hooks unread`."""
    p = sub.add_parser("suppressions", help=f"count lint and type suppressions per file against "
                                            f"{cli.DIR}/{LEDGER}, and fail on growth")
    p.add_argument("--update", action="store_true",
                   help="lower the record to today's counts (it never raises one); the first run records them")
    p.set_defaults(run=suppressions)
    hooks = sub.add_parser("hooks", help="the wait guard, the lines a builder posts on a pop-up or an error, and the "
                                         "prompt hook")
    actions = hooks.add_subparsers(dest="action", metavar="action", required=True)
    p = actions.add_parser("install", help="merge Colony's hooks into .claude/settings.json, keeping the hooks there")
    p.add_argument("--dry-run", action="store_true", help="print what it would write, and run nothing")
    p.add_argument("--local", action="store_true",
                   help="write .claude/settings.local.json, this machine's only, instead of the shared settings.json")
    p.set_defaults(run=install)
    p = actions.add_parser("asking", help="the Notification hook: an urgent line for the lead (Claude Code runs it)")
    p.set_defaults(run=asking)
    p = actions.add_parser("stopped", help="the StopFailure hook: a line for the lead (Claude Code runs it)")
    p.set_defaults(run=stopped)
    p = actions.add_parser("unread", help="the prompt hook: the lines this session hasn't read, when it starts and "
                                          "before each prompt (Claude Code runs it)")
    p.set_defaults(run=unread)
