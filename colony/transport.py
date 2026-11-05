"""How a line travels: always as a GitHub issue comment, the record every wait reads, and with [messages]
transport = "relay" also through this computer's Agent Relay core, which puts it into the receiving session between
turns, at once.

The relay carries only a line the receiving wait would print at once (wait.taken), so it never wakes a quiet lead
before its digest. A relayed line's comment carries MARK, and a relay wait skips the copy it reads, so a line
delivered both ways is acted on once, on any computer. When the relay fails, the comment alone carries the line.
The probe and socket are found as the messaging-agents-on-the-relay skill says; Colony never uses a cloud connector.

In hack mode every line goes to the pinned board issue, `[messages] board`, after the poster's prefix,
`[<Name>'s Claude]`. An `@<login>` line relays to that person's lead, `<login>-lead`, and an `@all` line goes by
GitHub alone.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

from colony import cli, wait

KINDS = ("github", "relay")
MARK = f"<!-- {cli.NAME}: relayed -->"
PROBE = "agent-relay-probe"
TIMEOUT = 15
PROBE_FOLDERS = (".agentworkforce/desktop/bin", ".agentworkforce/relay/bin", ".local/bin")
APP_HELPERS = Path("/Applications/Agent Relay.app/Contents/Helpers")
POINTER = ".agentworkforce/desktop/relay-socket"
APP_SOCKET = "Library/Application Support/com.agentrelay.desktop/run/relay.sock"
CLAUDE_RULE = re.compile(r"Bash\((\S+) relay agents --socket '([^']+)'\)")
CODEX_RULE = re.compile(r'\[\s*"([^"]+)",\s*"relay",\s*"agents",\s*"--socket",\s*"([^"]+)"\s*\]')
SECRET = re.compile(r"\b(gh[pousr]_\w{20,}|github_pat_\w{20,}|sk-[\w-]{20,}|xox[abprs]-[\w-]{10,}|AKIA[0-9A-Z]{16}"
                    r"|AIza[\w-]{35})|-----BEGIN [A-Z ]*PRIVATE KEY")
SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|KEY", re.I)


def kind(config: dict) -> str:
    """The [messages] transport: "github", the default, or "relay"."""
    name = config.get("messages", {}).get("transport", "github")
    if name not in KINDS:
        raise cli.ColonyError(f'[messages] transport is "github" or "relay", not {name!r}')
    return name


def holds_secret(text: str) -> str | None:
    """What in the text looks like a secret, a token's shape or a secret env var's value (named, never shown)."""
    if SECRET.search(text):
        return "a token"
    for key, value in os.environ.items():
        if SECRET_NAME.search(key) and len(value) >= 16 and value in text:
            return f"the value of ${key}"
    return None


def _executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def find_relay() -> tuple[str, str] | None:
    """Agent Relay's probe and socket, as the skill finds them: the rule the core writes for Claude Code, then the one
    for Codex, then the socket pointer (or the usual socket) and the first probe in the usual places or on PATH."""
    home = Path.home()
    settings = wait.read_json(Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude") / "settings.json", {})
    allow = settings.get("permissions", {}).get("allow", []) if isinstance(settings, dict) else []
    rules = [str(rule) for rule in allow] if isinstance(allow, list) else []
    try:
        rules.append((Path(os.environ.get("CODEX_HOME") or home / ".codex") / "rules" / "agent-relay.rules").read_text())
    except OSError:
        pass
    for rule in rules:
        found = CLAUDE_RULE.fullmatch(rule) or CODEX_RULE.search(rule)
        if found and _executable(Path(found[1])):
            return found[1], found[2]
    try:
        sock = (home / POINTER).read_text().splitlines()[0].strip()
    except (OSError, IndexError):
        sockets = [home / APP_SOCKET, Path(os.environ.get("XDG_RUNTIME_DIR", "/nonexistent")) / "agent-relay/relay.sock",
                   Path(f"/run/user/{os.getuid()}/agent-relay/relay.sock")]
        sock = next((str(path) for path in sockets if path.is_socket()), "")
    on_path = shutil.which(PROBE)
    places = [home / folder / PROBE for folder in PROBE_FOLDERS] + ([Path(on_path)] if on_path else [])
    probe = next((str(path) for path in [*places, APP_HELPERS / "Agent Relay Helper", APP_HELPERS / PROBE]
                  if _executable(path)), "")
    return (probe, sock) if probe and sock else None


def listening(path: str) -> bool:
    """Whether a process accepts on the Unix socket at `path`. It connects and closes, and sends nothing."""
    try:
        if not stat.S_ISSOCK(os.stat(path).st_mode):
            return False
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(2)
            conn.connect(path)
        return True
    except OSError:
        return False


def relay_available() -> bool:
    """Whether this computer runs an Agent Relay core: its probe is found and its socket answers."""
    found = find_relay()
    return found is not None and listening(found[1])


def _not_relayed(why: str) -> bool:
    print(f"{cli.NAME}: the relay didn't take the line, so it goes by GitHub alone: {why[:200]}", file=sys.stderr)
    return False


def relay(to: str, text: str) -> bool:
    """Send `text` to the session `to` with the skill's command, `PROBE relay send --socket SOCKET --to NAME --body
    TEXT`, and say whether the core took it. When it didn't, stderr says why."""
    found = find_relay()
    if found is None or not listening(found[1]):
        return _not_relayed("no Agent Relay core is running on this computer")
    probe, sock = found
    try:
        run = subprocess.run([probe, "relay", "send", "--socket", sock, "--to", to, "--body", text],
                             capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return _not_relayed(f"the probe timed out after {TIMEOUT} seconds")
    except (OSError, subprocess.SubprocessError) as e:
        return _not_relayed(str(e))
    try:
        answer = json.loads(run.stdout)
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        answer = {}
    if run.returncode == 0 and answer.get("ok") is True:
        return True
    error = answer.get("error")
    return _not_relayed(json.dumps(error) if error else run.stderr.strip() or run.stdout.strip() or f"exit {run.returncode}")


def board_issue(config: dict) -> int:
    """The hack board's issue number, [messages] board, which setup writes when it opens and pins the issue."""
    number = config.get("messages", {}).get("board")
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise cli.ColonyError("hack mode posts every line on the board issue: set [messages] board to its number in "
                              f"{cli.DIR}/{cli.CONFIG_NAME} (setup opens and pins it)")
    return number


def prefix(config: dict) -> str:
    """A board post's prefix, `[<Name>'s Claude]`, for this session's person ($COLONY_PERSON, else the one person)."""
    person = os.environ.get(cli.PERSON_ENV) or cli.default_person(config)
    return f"[{wait.display_name(config, person)}'s {wait.AGENT}]"


def relay_name(config: dict, to: str) -> str | None:
    """The session the relay delivers a line for `to` to: `to` itself, `<login>-lead` for `@<login>` in hack mode,
    where a person's lead has their login's name, and none for `@all` or another mode's `@<login>`."""
    if not to.startswith("@"):
        return to
    login = to[1:]
    return f"{login}-{cli.LEAD}" if wait.hack(config) and login != wait.ALL else None


def due_at_once(config: dict, to: str, line: str, card: int) -> bool:
    """Whether the wait of the session `to` (a relay_name) would print `line`, on issue `card`, at once (wait.taken):
    a builder's line, a line that can't wait, or any line for a lead whose digest is 0, as in hack mode."""
    if to == cli.LEAD or to.endswith(f"-{cli.LEAD}"):
        me = wait.lead_session(config, to)
    else:  # a lead's builder: in hack mode, its lead is the sender's person's
        me = wait.builder_session(config, to, os.environ.get(cli.PERSON_ENV, "") if wait.hack(config) else "")
    no_digest = me.name == cli.LEAD and wait.digest_seconds(config) <= 0
    return any(at_once or no_digest for _, at_once in wait.taken(line, me, str(card)))


def send(config: dict, to: str, line: str, card: int | None = None) -> int:
    """Post `line` for `to` (a session, `@<login>` or `@all`) on issue `card`, or on the coordination issue when None,
    and return the issue. In hack mode the line goes to the board issue instead, after the poster's prefix.

    The comment is the record. With transport = "relay", a line due at once goes through the relay first, and its
    comment then carries MARK. When the relay fails, the comment goes without MARK, so the wait still delivers it.
    """
    relay_on = kind(config) == "relay"
    why = holds_secret(line)
    if why:
        raise cli.ColonyError(f"a line never carries a secret, and this one holds {why}")
    repo, to = config["project"]["repo"], to.lower()
    if wait.hack(config):
        number, body = board_issue(config), f"{prefix(config)} {line}"
    else:
        number = int(card) if card is not None else wait.coordination_issue(repo, config["project"]["name"])
        body = line
    target = relay_name(config, to)
    relayed = relay_on and target is not None and due_at_once(config, target, line, number) and \
        relay(target, f"#{number} {body}")
    try:
        wait.gh("issue", "comment", str(number), "--repo", repo, "--body", f"{body}\n{MARK}" if relayed else body)
    except wait.GhError as e:
        if relayed:
            raise wait.GhError(f"the relay delivered the line, but GitHub kept no record of it: {e}") from None
        raise
    return number
