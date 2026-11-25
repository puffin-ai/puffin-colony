"""What keeps a line from going astray, around `colony post`, `colony say` and `colony wait`.

- **Names.** Every wait learns the session names it reads on GitHub: each status comment's name and lead, and each
  line's `(from <name>)`. It keeps them in ~/.colony/<project>/names.json. A line for a name that no learned, live or
  registered session has is refused, with the nearest names (check_name), so a misspelled lead name never swallows
  lines. Until a wait on this computer has learned a name, nothing is refused.
- **One session per lead.** A named lead's post or say needs the lead's claim on this computer: the heartbeat must
  hold this session's token ($COLONY_LEAD_TOKEN), so a second session never posts under a lead's name (check_holder).
- **The sender's note.** A line posted from an agent session carries a hidden note naming the session that sent it:
  a short hash of its session id, its computer, and its lead claim's mark (sender_note). A start line's note also
  asks for an acknowledgement, which the helper's wait gives as an `eyes` reaction (wait.send_acks). The lead's wait
  sends an unacknowledged start again, up to [messages] start_resends times, and then raises it (start_check).
- **No local paths.** A line reaches sessions on other computers, so a line that names a path on this computer, such
  as /tmp/notes.md or ~/x, is refused: attach the file with --attach, which puts its text on GitHub (check_paths).
- **Redelivery.** Each wait records the lines it printed in ~/.colony/<project>/<session>-delivered.json. After a
  session compacts its conversation or starts again, the SessionStart hook shows the ones printed since the session's
  last `colony ack`, within [messages] redeliver_minutes (redeliver_text).
- **A nudge.** Optionally, a short pointer typed into the recipient's cmux workspace on this computer (nudge.py).

The commands `colony ack`, `colony redeliver`, `colony waits` and `colony nudge` come in through register.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from colony import cli, portable

MAX_LINE = 300  # the default for [messages] max_line, wait.MAX_LINE
START_ACK_MINUTES = 10  # how long a start line waits for its acknowledgement before it goes again
START_RESENDS = 2  # how many times a start line goes again before the lead hears it was never acknowledged
START_CHECK_EVERY = 60  # the lead's wait checks its unacknowledged starts at most this often
START_DROP = 24 * 3600  # a start no check could settle in a day is dropped
REDELIVER_MINUTES = 60
REDELIVER_MAX = 20  # the most lines one redelivery shows
KEEP_DELIVERED = 50
KEEP_NAMES = 1000
AGENT_SESSION_ENVS = (cli.CLAUDE_SESSION_ENV, f"{cli.NAME.upper()}_AGENT_SESSION")  # an agent session's own id
# A path a sentence may name on this computer: under the home folder (~/), an absolute path of two folders or more,
# or a Windows drive's. local_path keeps the ones that are on this computer.
LOCAL_PATH = re.compile(r"(?<![\w.:/~-])(?:~/|/(?=[^\s/]+/)|[A-Za-z]:\\)\S*")


def setting(config: dict, key: str, default):
    """One [messages] setting, or its default."""
    value = (config.get("messages") or {}).get(key, default)
    return default if value is None else value


def max_line(config: dict) -> int:
    """[messages] max_line: the most characters a line's sentence holds, 300 by default."""
    value = setting(config, "max_line", MAX_LINE)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise cli.ColonyError(f"[messages] max_line is a whole number of characters, such as {MAX_LINE}, not {value!r}")
    return value


def ack_minutes(config: dict) -> float:
    """[messages] start_ack_minutes: how long a start line waits for its acknowledgement; 0 asks for none."""
    value = setting(config, "start_ack_minutes", START_ACK_MINUTES)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise cli.ColonyError(f"[messages] start_ack_minutes is a number of minutes, 0 for none, not {value!r}")
    return float(value)


def short_hash(text: str) -> str:
    """A short, stable mark of a value that stays on this computer, such as a session id."""
    return hashlib.sha256(text.encode()).hexdigest()[:12] if text else ""


# Names: who a line may go to


def names_path(project: str) -> Path:
    from colony import wait

    return wait.state_path(project, "names")


def kind_of(name: str) -> str:
    """A session's kind by its name alone: a lead's name is `lead` or ends in `-lead`."""
    return "lead" if name == cli.LEAD or name.endswith(f"-{cli.LEAD}") else "helper"


def learn_names(comments: list, people: frozenset[str] = frozenset()) -> dict[str, str]:
    """The session names these comments show, each with its kind: a status comment's name and its lead, and each
    line's `(from <name>)`, from the team's own comments alone (presence.by_team), so on a public repo no stranger can
    make a name look real."""
    from colony import presence, wait

    found: dict[str, str] = {}
    for comment in comments:
        if not presence.by_team(comment, people):
            continue
        body = comment.get("body") or ""
        status = presence.parse(body) if presence.MARK in body else None
        if status:
            found[status.name.lower()] = status.kind
            if status.lead and cli.SESSION_NAME.fullmatch(status.lead.lower()):
                found.setdefault(status.lead.lower(), "lead")
        for raw in wait.strip_extras(body).splitlines():
            signed = wait.SIGNED.search(wait.MARKUP.sub("", wait.PREFIX.sub("", wait.MARKUP.sub("", raw))))
            if signed and cli.SESSION_NAME.fullmatch(signed[1].lower()):
                found.setdefault(signed[1].lower(), kind_of(signed[1].lower()))
    return found


def remember_names(project: str, state: dict) -> None:
    """Move the names a poll learned (state["learned"]) into ~/.colony/<project>/names.json. A lead stays a lead."""
    from colony import wait

    learned = state.pop("learned", None)
    if not isinstance(learned, dict) or not learned:
        return
    path = names_path(project)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path.with_suffix(".lock"), "a") as handle, portable.lock(handle):
            known = wait.read_json(path, {})
            known = known if isinstance(known, dict) else {}
            now = time.time()
            for name, kind in learned.items():
                old = known.get(name) if isinstance(known.get(name), dict) else {}
                known[name] = {"kind": "lead" if old.get("kind") == "lead" else str(kind), "at": now}
            newest = sorted(known.items(), key=lambda item: item[1].get("at", 0))[-KEEP_NAMES:]
            wait.write_json(path, dict(newest))
    except OSError as e:
        print(f"{cli.NAME} wait: the names it learned were not kept: {e}", file=sys.stderr)


def local_names(project: str) -> dict[str, str]:
    """The sessions this computer knows without GitHub: each lead's heartbeat, each wait's listener and state file,
    the helpers a lead opened, and the leads in .colony/leads.toml."""
    from colony import presence, wait

    folder = wait.state_path(project, cli.LEAD).parent
    found: dict[str, str] = {}
    if folder.is_dir():
        for path in folder.glob("*.heartbeat"):
            beat = wait.read_json(path, None)
            name = str(beat.get("session") or path.stem) if isinstance(beat, dict) else path.stem
            found[name.lower()] = "lead"
        for path in folder.glob("*-listener.json"):
            name = path.name.removesuffix("-listener.json")
            found.setdefault(name, kind_of(name))
        for path in folder.glob("*-opened.json"):
            opened = wait.read_json(path, {})
            for name in opened if isinstance(opened, dict) else []:
                found.setdefault(str(name).lower(), "helper")
    try:
        for name in presence.registry():
            found[str(name).lower()] = "lead"
    except (cli.ColonyError, OSError):
        pass
    return {name: kind for name, kind in found.items() if cli.SESSION_NAME.fullmatch(name)}


def known(config: dict) -> dict[str, str] | None:
    """Every session name this computer knows, with its kind, or None before any wait here has learned a name, when
    no name can be refused yet."""
    from colony import wait

    project = config["project"]["name"]
    learned = wait.read_json(names_path(project), {})
    if not isinstance(learned, dict) or not learned:
        return None
    found = {name: str(value.get("kind", kind_of(name))) for name, value in learned.items() if isinstance(value, dict)}
    for name, kind in local_names(project).items():
        found[name] = "lead" if "lead" in (kind, found.get(name)) else kind
    return found


def known_lead(config: dict, name: str) -> bool:
    """Whether a name is a lead's by what this computer learned, such as an orchestrator's name without `-lead`."""
    return (known(config) or {}).get(name) == "lead"


def check_name(config: dict, args, me: str, sender: str, to: str, own_lead: bool = False) -> None:
    """Refuse a line for a session name no learned, live or registered session has, naming the nearest ones.
    `lead`, the sender's own lead (`own_lead`), @<login> and @all always pass, and so does every name with
    --allow-unknown or [messages] check_names = false."""
    from colony import wait

    if getattr(args, "allow_unknown", False) or not setting(config, "check_names", True) or own_lead:
        return
    if to.startswith("@") or to in (cli.LEAD, me, sender) or to == os.environ.get(wait.LEAD_ENV, "").lower():
        return
    names = known(config)
    if names is None or to in names:
        return
    close = difflib.get_close_matches(to, list(names), n=3, cutoff=0.6)
    hint = f"did you mean {' or '.join(close)}?" if close else \
        f"the names it knows are {', '.join(sorted(names)[:10])}."
    raise cli.ColonyError(f"no live or registered session is named {to}: {hint} `{cli.NAME} who` lists the live "
                          f"ones; for a session opening right now, send again with --allow-unknown")


# One session per lead


def check_holder(config: dict, me: str, sender: str) -> None:
    """Refuse a named lead's line from a session that doesn't hold the lead's claim on this computer: the lead's
    heartbeat holds another token, fresh or stale. With no heartbeat here, or one with no token, nothing is refused."""
    from colony import wait

    if me != cli.LEAD or not wait.named():
        return
    beat = wait.read_heartbeat(config["project"]["name"], sender)
    held, token = (beat or {}).get("token", ""), os.environ.get(wait.TOKEN_ENV, "")
    if not beat or not held or held == token:
        return
    if wait.fresh(beat):
        raise cli.ColonyError(f"{sender} is held by another session, {beat.get('session', 'a lead')} on account "
                              f"{beat.get('account', 'unknown')}, whose heartbeat is {int(time.time() - beat['at'])} s "
                              f"old: only that session posts as {sender}")
    raise cli.ColonyError(f"another session claimed {sender} last on this computer, so this one doesn't post as it: "
                          f"claim it again with `{cli.NAME} claim`, which takes it once the other's heartbeat is "
                          "stale, then post")


# No local paths


def check_paths(config: dict, said: list[str]) -> None:
    """Refuse a sentence that names a path on this computer, which a session on another computer can't read:
    attach the file instead. [messages] refuse_local_paths = false turns it off."""
    if not setting(config, "refuse_local_paths", True):
        return
    for sentence in said:
        found = local_path(sentence)
        if found:
            raise cli.ColonyError(f"a line reaches sessions on other computers, where {found} doesn't exist: send "
                                  f"the file's text with --attach {found}, or name a path in the repo")


def local_path(sentence: str) -> str:
    """The first path a sentence names on this computer: one under the home folder (~/), or an absolute path that
    names a file or folder here, so its first folder is here too. "" for none: a web route such as /home/feed, or any
    path nothing here has, passes, whatever folders this computer happens to have."""
    for found in LOCAL_PATH.finditer(sentence):
        path = found[0].rstrip(".,;:!?)]}'\"`")
        if path.startswith("~/"):
            return path
        try:
            if os.path.exists(path):
                return path
        except (OSError, ValueError):
            continue
    return ""


def check_lines(config: dict, args, me: str, sender: str, to: str, said: list[str], own_lead: bool = False) -> None:
    """Every check a post or say runs before it posts: no local path, a known name, and the lead's own claim."""
    check_paths(config, said)
    check_name(config, args, me, sender, to, own_lead)
    check_holder(config, me, sender)


# The comment: lines, attachment and the sender's note


ATTACH_BYTES = 1_000_000  # a file over this is refused before it is read


def read_attachment(given: str) -> tuple[str, str]:
    """An attachment's name and text: a file, or stdin for `-`, with share.py's checks. A link is refused, since its
    name can hide a secret file; so is a file whose resolved path passes through a folder or a name that holds
    secrets, such as ~/.ssh or .env, a file that isn't UTF-8 text, and text that holds a secret's shape, in UTF-8 or
    UTF-16."""
    from colony import share, transport

    if given == "-":
        name, data = "stdin", sys.stdin.read().encode("utf-8", "replace")
    else:
        path = Path(given).expanduser()
        if path.is_symlink():
            raise cli.ColonyError(f"{given} is a link, and colony never attaches one: a link's name can hide a secret "
                                  "file; attach the file itself")
        source = path.resolve()
        if not source.is_file():
            raise cli.ColonyError(f"{given} is not a file")
        if share.SECRET_FOLDERS & {part.lower() for part in source.parts} or \
                any(share.SECRET_FILES.match(part) for part in source.parts):
            raise cli.ColonyError(f"{given} is a kind of file that holds secrets, or sits in a folder that does, so "
                                  "it is never attached")
        if source.stat().st_size > ATTACH_BYTES:
            raise cli.ColonyError(f"{given} is over {ATTACH_BYTES // 1_000_000} MB: attach a part of it, or share it "
                                  "with a link")
        try:
            name, data = source.name, source.read_bytes()
        except OSError as e:
            raise cli.ColonyError(f"{given} can't be read: {e}") from None
    texts = [data.decode("utf-8", "replace")]
    utf16 = data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in data[:4096]
    if utf16:
        texts.append(data.decode("utf-16", "replace"))  # a secret in UTF-16 has a NUL between its letters
    if any(transport.holds_secret(text) for text in texts):
        raise cli.ColonyError(f"{given} holds a secret's shape, and a line never carries a secret")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is None or utf16:
        raise cli.ColonyError(f"{given} is not text, so it can't be attached: share it with a link")
    return name, text


def attached(config: dict, args) -> str:
    """The comment's attached file for --attach, or "". On a public repo, where anyone can read the comment, it is
    refused unless --public says the file may be public, or `say --private` sends it to the private board."""
    from colony import private, transport

    if not getattr(args, "attach", None):
        return ""
    name, text = read_attachment(args.attach)
    if not getattr(args, "public", False) and not getattr(args, "private", False) and private.is_public(config):
        raise cli.ColonyError(f"{config['project']['repo']} is public, so anyone could read {name}: add --public to "
                              f"attach it anyway, only when your person says it may be public, or send it with "
                              f"`{cli.NAME} say --private`")
    return transport.attachment(name, text)


def sender_note(config: dict, sender: str, starts: bool) -> dict | None:
    """The sender's note for a comment, or None outside an agent session and outside a lead's claim, where there is
    no session to name. It holds the sender's name, a short hash of the agent session's id, the computer, the lead
    claim's mark, and for a start line, the request for an acknowledgement."""
    from colony import presence, wait

    session = next((os.environ[name] for name in AGENT_SESSION_ENVS if os.environ.get(name)), "")
    token = os.environ.get(wait.TOKEN_ENV, "")
    if not session and not token:
        return None
    note = {"from": sender, "session": short_hash(session), "computer": presence.computer(),
            "claim": wait.claim_of(token)}
    if starts and ack_minutes(config) > 0:
        note["ack"] = True
    return note


def body(config: dict, args, text: str, sender: str, starts: bool) -> str:
    """A post's comment: its lines, then the attached file (--attach), then the sender's note."""
    from colony import transport

    parts = [text, *filter(None, [attached(config, args)])]
    note = sender_note(config, sender, starts)
    if note:
        parts.append(transport.sender_note(note))
    return "\n\n".join(parts)


def after_post(config: dict, args, sent: int, to: str, where: str, body: str = "") -> None:
    """What a post or say does once its comment `sent` (transport.Sent) is out: say on stderr where it went, with its
    link, since the coordination issue moves to a fresh one when it fills; track a start line that asks for an
    acknowledgement; and nudge the recipient when asked."""
    from colony import nudge, wait

    url, comment = getattr(sent, "url", ""), getattr(sent, "comment", None)
    if url:
        print(f"{cli.NAME}: posted on {where}: {url}", file=sys.stderr)
    if body and comment is not None and wait.note_of(body).get("ack") is True:
        record_start(config, sent, to, body)
    nudge.after_post(config, args, to, int(sent))


# Start lines that wait for an acknowledgement


def starts_path(project: str, name: str) -> Path:
    from colony import wait

    return wait.state_path(project, f"{name}-starts")


def record_start(config: dict, sent, to: str, body: str) -> None:
    """Remember a start line that asks for an acknowledgement, for the lead's wait to check (start_check)."""
    from colony import wait

    project, name = config["project"]["name"], wait.state_name(cli.LEAD)
    note = wait.note_of(body)
    text = wait.without_note(body)
    item = {"comment": sent.comment, "card": int(sent), "to": to, "text": text, "note": note, "at": time.time(),
            "first": time.time(), "sends": 1}
    try:
        with starts_lock(project, name):
            items = read_starts(project, name)
            wait.write_json(starts_path(project, name), [*items, item])
    except OSError as e:
        print(f"{cli.NAME}: the start line went out, and its acknowledgement won't be checked: {e}", file=sys.stderr)


@contextmanager
def starts_lock(project: str, name: str):
    """Hold the start lines' file lock, so a post adding one and a wait checking them never lose each other's."""
    path = starts_path(project, name).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle, portable.lock(handle):
        yield


def read_starts(project: str, name: str) -> list[dict]:
    from colony import wait

    items = wait.read_json(starts_path(project, name), [])
    return [item for item in items if isinstance(item, dict) and isinstance(item.get("comment"), int)] \
        if isinstance(items, list) else []


def team_check(config: dict):
    """Whether a GitHub login is the team's: one of [people] logins, or with none listed, a collaborator on the repo,
    as GitHub says. Each login is asked once per check."""
    from colony import wait

    logins = {str(login).lower() for login in (config.get("people") or {}).get("logins", [])}
    repo, asked = config["project"]["repo"], {}

    def check(login: str) -> bool:
        login = login.lower()
        if logins or not login:
            return login in logins
        if login not in asked:
            try:
                wait.gh("api", f"repos/{repo}/collaborators/{login}")
                asked[login] = True
            except wait.GhError:
                asked[login] = False  # GitHub answers 404 for anyone who isn't one
        return asked[login]
    return check


def acknowledged(repo: str, comment: int, team) -> bool:
    """Whether a start line's comment has a reaction from the team (`team`, team_check), which is how a helper's wait
    acknowledges it. Agents react through their person's login, so a stranger's reaction on a public repo never
    counts."""
    import json

    from colony import wait

    reactions = json.loads(wait.gh("api", f"repos/{repo}/issues/comments/{comment}/reactions?per_page=100") or "[]")
    return any(team(str(((reaction.get("user") or {}).get("login")) or ""))
               for reaction in (reactions if isinstance(reactions, list) else []) if isinstance(reaction, dict))


def start_check(config: dict, project: str, name: str):
    """The lead's check of its start lines, or None with [messages] start_ack_minutes = 0. Each start line not
    acknowledged within start_ack_minutes goes again, the same line in a new comment, up to start_resends times;
    then the check returns an `urgent:` line for the lead and forgets it. It reads GitHub at most once a minute,
    and a failed read tries again at the next check."""
    from colony import transport, wait

    minutes = ack_minutes(config)
    if minutes <= 0:
        return None
    resends = setting(config, "start_resends", START_RESENDS)
    if isinstance(resends, bool) or not isinstance(resends, int) or resends < 0:
        raise cli.ColonyError(f"[messages] start_resends is a whole number, such as {START_RESENDS}, not {resends!r}")
    repo, last = config["project"]["repo"], [0.0]

    def check(now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        if now - last[0] < START_CHECK_EVERY or not starts_path(project, name).exists():
            return []
        last[0] = now
        lines, settled, kept, team = [], set(), [], team_check(config)
        for item in read_starts(project, name):
            if now - float(item.get("at", 0)) < minutes * 60:
                continue
            settled.add(item["comment"])
            try:
                if acknowledged(repo, item["comment"], team):
                    continue
            except (cli.ColonyError, OSError, ValueError):
                if now - float(item.get("first", item.get("at", 0))) < START_DROP:
                    kept.append(item)
                continue
            sends = int(item.get("sends", 1))
            if sends > resends:
                lines.append(f"urgent: {item['to']} has not acknowledged the start line on #{item['card']} after "
                             f"{sends} sends in {int((now - float(item.get('first', now))) // 60)} minutes: check its "
                             f"session with {cli.NAME} who, open it again, or give the card to another helper")
                continue
            note = {**(item.get("note") or {}), "resent": sends}
            try:
                sent = transport.send(config, item["to"], f"{item['text']}\n\n{transport.sender_note(note)}",
                                      card=item["card"])
            except (cli.ColonyError, OSError, ValueError) as e:
                print(f"{cli.NAME} wait: a start line for {item['to']} was not sent again, the next check tries: {e}",
                      file=sys.stderr)
                kept.append(item)
                continue
            if getattr(sent, "comment", None) is not None:
                kept.append({**item, "comment": sent.comment, "at": now, "sends": sends + 1})
        try:
            with starts_lock(project, name):
                fresh = [item for item in read_starts(project, name) if item["comment"] not in settled]
                wait.write_json(starts_path(project, name), fresh + kept)
        except OSError as e:
            print(f"{cli.NAME} wait: the start lines' list was not kept: {e}", file=sys.stderr)
        return lines
    return check


# Redelivery after a compaction or a restart


def delivered_path(project: str, name: str) -> Path:
    from colony import wait

    return wait.state_path(project, f"{name}-delivered")


def acked_path(project: str, name: str) -> Path:
    from colony import wait

    return wait.state_path(project, f"{name}-acked")


def record_delivered(project: str, name: str, lines: list[str], now: float | None = None) -> None:
    """Note the lines a session was just shown, for redelivery after it compacts or starts again. The newest
    KEEP_DELIVERED from the last day stay."""
    from colony import wait

    now = time.time() if now is None else now
    path = delivered_path(project, name)
    try:
        items = wait.read_json(path, [])
        items = [item for item in items if isinstance(item, dict) and now - float(item.get("at", 0)) < 86400] \
            if isinstance(items, list) else []
        wait.write_json(path, [*items, *({"text": line, "at": now} for line in lines)][-KEEP_DELIVERED:])
    except (OSError, ValueError, TypeError) as e:
        print(f"{cli.NAME}: the delivered lines were not noted for redelivery: {e}", file=sys.stderr)


def unacknowledged(config: dict, name: str, now: float | None = None) -> list[str]:
    """The lines shown to a session since its last `colony ack`, within [messages] redeliver_minutes, newest last."""
    from colony import wait

    now = time.time() if now is None else now
    project = config["project"]["name"]
    minutes = setting(config, "redeliver_minutes", REDELIVER_MINUTES)
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes <= 0:
        return []
    acked = wait.read_json(acked_path(project, name), 0)
    floor = max(float(acked) if isinstance(acked, (int, float)) else 0.0, now - minutes * 60)
    items = wait.read_json(delivered_path(project, name), [])
    lines = [str(item.get("text")) for item in items if isinstance(item, dict) and float(item.get("at", 0)) > floor] \
        if isinstance(items, list) else []
    return list(dict.fromkeys(lines))[-REDELIVER_MAX:]


WHY = {"compact": "compacted its conversation", "resume": "was resumed", "clear": "was cleared"}


def redeliver_text(config: dict, me: str, source: str = "") -> str:
    """The redelivery a session sees when it starts again: its unacknowledged lines under one heading, or ""."""
    from colony import wait

    lines = unacknowledged(config, wait.state_name(me))
    if not lines:
        return ""
    why = WHY.get(source, "started")
    return (f"Lines {cli.NAME} delivered to {me} before this session {why}, not acknowledged with `{cli.NAME} ack`. "
            f"Some may be done already, so check each before you act on it, then run `{cli.NAME} ack`:\n"
            + "\n".join(lines))


def redeliver_hook(config: dict, me: str, event: dict, shown: list[str]) -> None:
    """The prompt hook's part (guards.unread): on SessionStart, after a compaction, resume, clear or a fresh start,
    print the session's unacknowledged lines; then note the lines the hook just showed as delivered. It never
    raises."""
    from colony import wait

    try:
        if event.get("hook_event_name") == "SessionStart":
            text = redeliver_text(config, me, str(event.get("source") or ""))
            if text:
                print(text)
        if shown:
            record_delivered(config["project"]["name"], wait.state_name(me), shown)
    except (cli.ColonyError, OSError, ValueError, KeyError, TypeError) as e:
        print(f"{cli.NAME} hooks unread: {e}", file=sys.stderr)


def session_name() -> str:
    me = os.environ.get(cli.SESSION_ENV, "").lower()
    if not me:
        raise cli.ColonyError(f"set {cli.SESSION_ENV} to this session's name, such as lead")
    return me


def ack(config: dict, args) -> int:
    """`colony ack`: the session has acted on every line shown to it so far, so a compaction or restart shows only
    newer ones again."""
    from colony import wait

    me = session_name()
    count = len(unacknowledged(config, wait.state_name(me)))
    wait.write_json(acked_path(config["project"]["name"], wait.state_name(me)), time.time())
    print(f"{me}: {count} delivered line{'s' if count != 1 else ''} acknowledged; after a compaction or a restart, "
          "only newer lines show again")
    return 0


def redeliver(config: dict, args) -> int:
    """`colony redeliver`: print the lines shown to this session since its last `colony ack`."""
    me = session_name()
    text = redeliver_text(config, me)
    print(text or f"No unacknowledged lines for {me}.")
    return 0


def register(sub) -> None:
    """cli.py's route to the messages workstream's commands: `ack`, `redeliver`, `waits` and `nudge`."""
    from colony import nudge, waits

    p = sub.add_parser("ack", help="say this session acted on the lines shown so far, so a compaction or restart shows "
                                   "only newer ones again")
    p.set_defaults(run=ack)
    p = sub.add_parser("redeliver", help="print the lines shown to this session since its last colony ack")
    p.set_defaults(run=redeliver)
    waits.add_commands(sub)
    nudge.add_commands(sub)
