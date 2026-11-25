"""Real-use testing across people and computers: the registry of the test accounts and fixtures a person prepared,
and one findings list per release that every tester keeps current through the code host.

- `.colony/fixtures.toml` lists the test accounts and the fixtures, such as seeded data or a sandbox, that a person
  prepared, by reference only: what each one is, where it lives, its login name, and where its secret is kept, never
  the secret itself (looks_secret refuses one). `colony fixtures` lists them, `colony fixtures add` records one, and
  `colony fixtures remove` drops one. Testers and leads read it before they ask for anything, and `colony needs`
  refuses to ask the person for a test account or test data while the registry holds some (check_question), unless
  `--new-fixture` says the registry lacks what is needed.
- `colony findings` keeps one findings issue per release on the code host, so testers on any computer share it:
  `open` finds or makes it with the release's cards, `next` claims the next card nobody holds, `claim` takes one by
  number or renews the tester's own claim, `free` hands one back, `report` records a pass, a fail or a block, and
  `show` prints the list. Each step is one comment, and every command rewrites the issue's list from all of them, so
  whoever is alive keeps it current, and no one tester or lead owns it. When two testers claim one card, the earlier
  comment wins; a claim with no result after `[testers] claim_minutes` lapses, so a tester that stopped frees its card
  for the others. When two testers make the issue at once, the older one is the list, and the newer closes as its
  duplicate.
"""
from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from colony import board, cli, wait

REGISTRY = "fixtures.toml"
TABLES = {"account": "accounts", "fixture": "fixtures"}
KEYS = ("what", "where", "login", "secret_at", "how", "note", "by", "added")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
HEADER = """\
# The test accounts and fixtures a person prepared, which testers and leads reuse before they ask for new ones.
# References only: what each one is, where it lives, its login name, and where its secret is kept, such as a
# password manager's entry. Never a password, a token or any other secret. `colony fixtures add` writes this file.
"""
# A question for the person about test accounts or test data, which the registry may answer already.
FIXTURE_QUESTION = re.compile(r"\btest(?:ing)?[\s-]+(?:accounts?|users?|logins?|data|fixtures?|cards?|"
                              r"environments?|credentials?)\b|\bfixtures?\b|\bseed(?:ed)?\s+data\b|\bsandbox\b", re.I)

CLAIM_MINUTES = 60
FINDINGS_PAGES = 3  # pages of 100 newest open issues a findings command reads to find the release's findings issue
FINDINGS_MARK = f"{cli.NAME}-findings"
FINDINGS_DATA = re.compile(rf"<!--\s*{FINDINGS_MARK}\s+(\{{.*?\}})\s*-->", re.S)
EVENT = re.compile(r"^findings:\s*(claim|free|pass|fail|blocked)\s+#(\d+)(?::\s*(.*?))?\s*\(by ([^()\n]+)\)\s*$",
                   re.I | re.M)
RESULTS = ("pass", "fail", "blocked")


# The registry of test accounts and fixtures


def registry_path(root: Path | None = None) -> Path:
    """The registry, .colony/fixtures.toml at the top of the repo."""
    return (root or cli.repo_root()) / cli.DIR / REGISTRY


def read_registry(path: Path | None = None) -> dict[str, dict[str, dict]]:
    """The registry as {"accounts": {name: entry}, "fixtures": {name: entry}}, empty when there is no file."""
    path = path or registry_path()
    found: dict[str, dict[str, dict]] = {table: {} for table in TABLES.values()}
    if not path.exists():
        return found
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise cli.ColonyError(f"{path}: {e}") from None
    for table in TABLES.values():
        for name, entry in (data.get(table) or {}).items():
            if isinstance(entry, dict):
                found[table][name] = {key: str(value) for key, value in entry.items() if key in KEYS}
    return found


def write_registry(data: dict[str, dict[str, dict]], path: Path | None = None) -> None:
    """Write the registry, each entry's keys in KEYS order, as TOML basic strings."""
    path = path or registry_path()
    lines = [HEADER]
    for table in TABLES.values():
        for name in sorted(data.get(table, {})):
            lines.append(f"[{table}.{name}]")
            lines += [f"{key} = {json.dumps(data[table][name][key], ensure_ascii=False)}" for key in KEYS
                      if data[table][name].get(key)]
            lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip("\n") + "\n")


def looks_secret(text: str) -> str | None:
    """What in a value looks like a secret, named and never shown (profile.looks_secret)."""
    from colony import profile

    return profile.looks_secret(text)


def entry_text(name: str, entry: dict) -> str:
    """One registry entry in a line, such as `staging-admin: an admin on staging; login: qa@example.test`."""
    parts = [entry.get("what", "")]
    for key, label in (("where", "where"), ("login", "login"), ("secret_at", "secret kept in"), ("how", "how"),
                       ("note", "note")):
        if entry.get(key):
            parts.append(f"{label}: {entry[key]}")
    return f"{name}: " + "; ".join(part for part in parts if part)


def registry_lines(data: dict[str, dict[str, dict]]) -> list[str]:
    """The registry as `colony fixtures` prints it, or one line saying it is empty."""
    lines = []
    for kind, table in TABLES.items():
        entries = data.get(table, {})
        if entries:
            lines.append(f"Test {table} ({len(entries)}):" if kind == "account" else f"Fixtures ({len(entries)}):")
            lines += [f"- {entry_text(name, entries[name])}" for name in sorted(entries)]
    return lines or [f"No test account or fixture is recorded yet: when the person prepares one, record it with "
                     f"`{cli.NAME} fixtures add`."]


def names(data: dict[str, dict[str, dict]]) -> list[str]:
    """Every entry's name, accounts first."""
    return [name for table in TABLES.values() for name in sorted(data.get(table, {}))]


def check_question(question: str, root: Path | None = None) -> None:
    """Refuse a question for the person about test accounts or test data while the registry holds some, so a lead
    reuses what the person prepared instead of asking again; `colony needs --new-fixture` asks anyway."""
    if not FIXTURE_QUESTION.search(question or ""):
        return
    try:
        data = read_registry(registry_path(root))
    except cli.ColonyError:
        return
    held = names(data)
    if held:
        raise cli.ColonyError(f"the person prepared test accounts and fixtures already: {', '.join(held)}. Read them "
                              f"with `{cli.NAME} fixtures` and reuse one; when none fits, ask again with --new-fixture, "
                              "and say what the registry lacks")


def fixtures_list(config: dict, args) -> int:
    """`colony fixtures [list] [--json]`: the test accounts and fixtures the person prepared."""
    data = read_registry()
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    print("\n".join(registry_lines(data)))
    return 0


def fixtures_add(config: dict, args) -> int:
    """`colony fixtures add account|fixture <name> --what … [--where …] [--login …] [--secret-at …] [--how …]
    [--note …]`: record one, or replace the one with that name. It refuses anything that looks like a secret."""
    if not NAME.fullmatch(args.name):
        raise cli.ColonyError(f"{args.name!r} is not a name: letters, digits, dashes and underscores, such as "
                              "staging-admin")
    values = {"what": args.what, "where": args.where, "login": args.login, "secret_at": args.secret_at,
              "how": args.how, "note": args.note}
    entry = {key: " ".join(str(value).split()) for key, value in values.items() if value and str(value).strip()}
    if not entry.get("what"):
        raise cli.ColonyError("say what it is with --what, such as --what \"an admin account on staging\"")
    for key, value in entry.items():
        if found := looks_secret(value):
            raise cli.ColonyError(f"--{key.replace('_', '-')} holds what looks like {found}, and the registry never "
                                  "holds a secret: name where the secret is kept with --secret-at instead")
    try:
        entry["by"] = cli.person_of(config, args)
    except cli.ColonyError:
        pass
    entry["added"] = board.utcnow().strftime("%Y-%m-%d")
    path = registry_path()
    data = read_registry(path)
    table = TABLES[args.kind]
    other = next((t for t in TABLES.values() if t != table and args.name in data[t]), None)
    if other:
        raise cli.ColonyError(f"{args.name} is one of the {other} already: remove it first, or pick another name")
    replaced = args.name in data[table]
    data[table][args.name] = entry
    write_registry(data, path)
    print(f"{'updated' if replaced else 'recorded'} {args.kind} {entry_text(args.name, entry)}")
    print(f"Commit {cli.DIR}/{REGISTRY} with your next change, so every computer reads it.")
    return 0


def fixtures_remove(config: dict, args) -> int:
    """`colony fixtures remove <name>`: drop one entry."""
    path = registry_path()
    data = read_registry(path)
    table = next((t for t in TABLES.values() if args.name in data[t]), None)
    if table is None:
        raise cli.ColonyError(f"the registry has no {args.name}: it holds {', '.join(names(data)) or 'nothing'}")
    del data[table][args.name]
    write_registry(data, path)
    print(f"removed {args.name}. Commit {cli.DIR}/{REGISTRY} with your next change.")
    return 0


# The findings list


def claim_minutes(config: dict) -> int:
    """[testers] claim_minutes, the minutes a claim holds a card with no result: 60 by default."""
    value = (config.get("testers", {}) or {}).get("claim_minutes", CLAIM_MINUTES)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise cli.ColonyError(f"[testers] claim_minutes must be a whole number of at least 1, not {value!r}")
    return value


def release_number(value: str) -> int:
    """A release pull request's number, from its number, `#<n>` or its link."""
    found = re.search(r"#?(\d+)/?$", str(value).strip())
    if not found:
        raise cli.ColonyError(f"{value!r} names no pull request: give its number or its link")
    return int(found[1])


def findings_title(release: int) -> str:
    """The findings issue's title, the one the tester's brief has always used."""
    return f"test: findings for the release #{release}"


def me(args) -> str:
    """Who this tester is in the list: its session's name on this computer, such as `tester on laptop`, or --as."""
    from colony import presence

    given = " ".join(str(getattr(args, "as_name", "") or "").split())
    if given:
        if re.search(r"[()\n]", given):
            raise cli.ColonyError("--as is a name without brackets")
        return given
    return f"{os.environ.get(cli.SESSION_ENV) or cli.TESTER} on {presence.computer()}"


@dataclass
class Event:
    """One findings comment: claim, free, pass, fail or blocked, for a card, by a tester, at a time."""

    kind: str
    card: int
    by: str
    at: datetime
    note: str = ""


@dataclass
class CardState:
    """Where one card stands: its result and note, who reported it, and who holds it now and since when."""

    number: int
    title: str = ""
    result: str = ""
    note: str = ""
    by: str = ""
    holder: str = ""
    since: datetime | None = None
    lapsed: str = ""


@dataclass
class Findings:
    """A release's findings issue: its number, the release, its cards with their titles, and its body."""

    number: int
    release: int
    cards: list[dict] = field(default_factory=list)
    body: str = ""


def moment(text: str) -> datetime:
    """A GitHub time, such as 2026-11-05T10:00:00Z."""
    return datetime.fromisoformat(str(text).replace("Z", "+00:00"))


def events_of(comments: list[dict], logins: frozenset[str]) -> list[Event]:
    """The findings events in the issue's comments, oldest first: only the team's comments count."""
    from colony import presence

    found = []
    for comment in sorted(comments, key=lambda c: (c.get("created_at", ""), c.get("id", 0))):
        if not presence.by_team(comment, logins):
            continue
        for kind, card, note, by in EVENT.findall(comment.get("body") or ""):
            found.append(Event(kind.lower(), int(card), by.strip(), moment(comment["created_at"]), (note or "").strip()))
    return found


def standing(cards: list[dict], events: list[Event], now: datetime, lapse: timedelta) -> dict[int, CardState]:
    """Each card's state after the events: the last result counts; a claim holds a card nobody holds, so the earlier
    of two claims wins; the holder's own claim again renews its hold; a claim lapses after `lapse` with no result; a
    result or a free ends its tester's hold."""
    states = {int(card["number"]): CardState(int(card["number"]), card.get("title", "")) for card in cards}
    for event in events:
        state = states.setdefault(event.card, CardState(event.card))
        held = state.holder and state.since is not None and event.at - state.since < lapse
        if event.kind == "claim":
            if not held or state.holder == event.by:
                state.holder, state.since, state.lapsed = event.by, event.at, ""
        elif event.kind == "free":
            if state.holder == event.by:
                state.holder, state.since = "", None
        else:
            state.result, state.note, state.by = event.kind, event.note, event.by
            if not held or state.holder == event.by:
                state.holder, state.since = "", None
    for state in states.values():
        if state.holder and state.since is not None and now - state.since >= lapse:
            state.lapsed, state.holder, state.since = state.holder, "", None
    return states


def safe(text: str) -> str:
    """Text made safe for the findings issue's body: one line, with `<` and `>` as entities, so a card's title or a
    note can never open or close an HTML comment, and never plant a hidden copy of its own (data_of)."""
    return " ".join(str(text).split()).replace("<", "&lt;").replace(">", "&gt;")


def cell(text: str) -> str:
    """Text made safe for one Markdown table cell."""
    return safe(text).replace("|", "\\|")


def hidden(data: dict) -> str:
    """The hidden copy as JSON with `<` and `>` escaped, which JSON reads back as they were, so no title in it can
    end the HTML comment that holds it."""
    return json.dumps(data, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")


def render(findings: Findings, states: dict[int, CardState]) -> str:
    """The findings issue's body: how to take part, the table of cards, the counts, the failures, and the hidden
    copy of the release and its cards that every command reads back."""
    n = findings.release
    rows = ["| Card | Result | Tester | Note |", "| --- | --- | --- | --- |"]
    for number in sorted(states):
        state = states[number]
        if state.result:
            result, who = state.result, state.by
        elif state.holder:
            result, who = "testing", f"{state.holder}, since {state.since:%H:%M} UTC" if state.since else state.holder
        else:
            result, who = "not tested", (f"claim by {state.lapsed} lapsed" if state.lapsed else "")
        rows.append(f"| #{number} {cell(state.title)} | {result} | {cell(who)} | {cell(state.note)} |")
    counts = {kind: sum(1 for s in states.values() if s.result == kind) for kind in RESULTS}
    tested = sum(counts.values())
    failures = [f"- #{s.number} {safe(s.title)}: {safe(s.note or 'no note')} ({safe(s.by)})" for s in states.values()
                if s.result == "fail"]
    blocked = [f"- #{s.number} {safe(s.title)}: {safe(s.note or 'no note')} ({safe(s.by)})" for s in states.values()
               if s.result == "blocked"]
    data = {"release": n, "cards": [{"number": number, "title": states[number].title} for number in sorted(states)]}
    parts = [f"Findings for the release #{n}, which every tester keeps through `{cli.NAME} findings`: claim a card "
             f"with `{cli.NAME} findings next {n}`, test it, and record what you saw with `{cli.NAME} findings report "
             f"{n} <card> pass|fail|blocked \"<what you saw>\"`. Each command rewrites this list from the comments "
             "below, so it stays current while any tester is at work.", "", *rows, "",
             f"{tested} of {len(states)} cards tested: {counts['pass']} pass, {counts['fail']} fail, "
             f"{counts['blocked']} blocked."]
    if failures:
        parts += ["", "## Failures", *failures]
    if blocked:
        parts += ["", "## Blocked", *blocked]
    parts += ["", f"<!-- {FINDINGS_MARK} {hidden(data)} -->"]
    return "\n".join(parts)


def data_of(body: str) -> dict:
    """The hidden copy of the release and its cards in a findings issue's body, or {}. Only the last one counts,
    which render writes at the very end."""
    found = FINDINGS_DATA.findall(body or "")
    try:
        data = json.loads(found[-1]) if found else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def findings_issues(config: dict, release: int) -> list[dict]:
    """The release's open findings issues that the team opened, oldest first, from the newest open issues. A plain
    listing, not a search: GitHub's search index lags behind a new issue, and a tester on another computer must find
    it at once. It reads the REST list, which names each issue's author, so an issue anyone else opens with the same
    title is never the list, as only the team's comments count on it (events_of)."""
    from colony import presence

    title, logins, found = findings_title(release), team_logins(config), []
    for page in range(1, FINDINGS_PAGES + 1):
        listed = json.loads(wait.gh("api", f"repos/{config['project']['repo']}/issues?state=open&sort=created&"
                                           f"direction=desc&per_page=100&page={page}") or "[]")
        listed = listed if isinstance(listed, list) else []
        found += [issue for issue in listed if isinstance(issue, dict) and "pull_request" not in issue
                  and issue.get("title") == title and presence.by_team(issue, logins)]
        if len(listed) < 100:
            break
    return sorted(found, key=lambda issue: issue["number"])


def find_findings(config: dict, release: int) -> Findings | None:
    """The release's open findings issue, the oldest when there are two, so every tester keeps to the same one, or
    None."""
    mine = findings_issues(config, release)
    if not mine:
        return None
    issue = mine[0]
    cards = [card for card in data_of(issue.get("body", "")).get("cards", []) if isinstance(card, dict)
             and isinstance(card.get("number"), int)]
    return Findings(issue["number"], release, cards, issue.get("body", ""))


def need_findings(config: dict, release: int) -> Findings:
    """The release's findings issue, or an error that says to open it."""
    found = find_findings(config, release)
    if found is None:
        raise cli.ColonyError(f"the release #{release} has no findings issue yet: run `{cli.NAME} findings open "
                              f"{release}`")
    return found


def release_cards(config: dict, release: int) -> list[int]:
    """The cards a release carries: each `Closes #<n>` in its pull request's body, and in the body of each pull
    request it lists, which is how a release lists its batches."""
    from colony import cards

    repo = config["project"]["repo"]
    try:
        pull = json.loads(wait.gh("pr", "view", str(release), "--repo", repo, "--json", "body") or "{}")
    except (cli.ColonyError, ValueError):
        raise cli.ColonyError(f"#{release} is no pull request here: name its cards with --card") from None
    body = pull.get("body") or ""
    found = [int(n) for n in cards.CLOSING.findall(body)]
    for listed in re.findall(r"^\s*[-*]\s*#(\d+)\b", body, re.M):
        try:
            inner = json.loads(wait.gh("pr", "view", listed, "--repo", repo, "--json", "body") or "{}")
        except (cli.ColonyError, ValueError):
            continue
        found += [int(n) for n in cards.CLOSING.findall(inner.get("body") or "")]
    return list(dict.fromkeys(found))


def titles(config: dict, numbers: list[int]) -> dict[int, str]:
    """Each card's title, read once."""
    found = {}
    for number in numbers:
        try:
            found[number] = json.loads(wait.gh("issue", "view", str(number), "--repo", config["project"]["repo"],
                                               "--json", "title") or "{}").get("title", "")
        except (cli.ColonyError, ValueError):
            found[number] = ""
    return found


def comments(config: dict, number: int) -> list[dict]:
    """Every comment on the findings issue, one JSON object per line from gh."""
    out = wait.gh("api", "--paginate", f"repos/{config['project']['repo']}/issues/{number}/comments?per_page=100",
                  "--jq", ".[]")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def team_logins(config: dict) -> frozenset[str]:
    """The team's logins from [people] logins, lowercased."""
    return frozenset(str(login).lower() for login in config.get("people", {}).get("logins", []))


def refresh(config: dict, findings: Findings, now: datetime | None = None) -> dict[int, CardState]:
    """Read every findings comment, work out each card's state, and rewrite the issue's list when it changed. Any
    tester's command does this, so the list stays current while any of them is alive."""
    now = now or board.utcnow()
    events = events_of(comments(config, findings.number), team_logins(config))
    states = standing(findings.cards, events, now, timedelta(minutes=claim_minutes(config)))
    body = render(findings, states)
    if body != findings.body:
        wait.gh("issue", "edit", str(findings.number), "--repo", config["project"]["repo"], "--body", body)
        findings.body = body
    findings.cards = [{"number": number, "title": states[number].title} for number in sorted(states)]
    return states


def post_event(config: dict, findings: Findings, kind: str, card: int, by: str, note: str = "") -> None:
    """Post one findings comment, such as `findings: fail #41: the switch resets (by tester on laptop)`."""
    note = " ".join(note.split())
    text = f"findings: {kind} #{card}" + (f": {note}" if note else "") + f" (by {by})"
    wait.gh("issue", "comment", str(findings.number), "--repo", config["project"]["repo"], "--body", text)


def summary(states: dict[int, CardState]) -> str:
    """The counts in one line, such as `3 of 5 cards tested: 2 pass, 1 fail, 0 blocked`."""
    counts = {kind: sum(1 for s in states.values() if s.result == kind) for kind in RESULTS}
    return (f"{sum(counts.values())} of {len(states)} cards tested: {counts['pass']} pass, {counts['fail']} fail, "
            f"{counts['blocked']} blocked")


def done_hint(findings: Findings, states: dict[int, CardState]) -> str:
    """What the tester who records the last result posts for the lead."""
    counts = {kind: sum(1 for s in states.values() if s.result == kind) for kind in RESULTS}
    return (f'every card has a result: post `{cli.NAME} post {findings.release} lead "done, findings in '
            f'#{findings.number}: {counts["pass"]} of {len(states)} cards pass, {counts["fail"]} failures, '
            f'{counts["blocked"]} blocked"`')


def findings_open(config: dict, args) -> int:
    """`colony findings open <release> [--card N ...]`: find or make the release's findings issue, with its cards,
    and print them and the prepared test accounts and fixtures."""
    release, repo = release_number(args.release), config["project"]["repo"]
    found = find_findings(config, release)
    wanted = list(dict.fromkeys(args.card or [])) or ([] if found and found.cards else release_cards(config, release))
    made = False
    if found is None:
        named = titles(config, wanted)
        cards = [{"number": number, "title": named.get(number, "")} for number in wanted]
        if not cards:
            raise cli.ColonyError(f"the release #{release} names no card: name them with --card <n>")
        body = render(Findings(0, release, cards), standing(cards, [], board.utcnow(), timedelta(minutes=1)))
        url = wait.gh("issue", "create", "--repo", repo, "--title", findings_title(release), "--body", body)
        number = int(url.strip().rstrip("/").rsplit("/", 1)[-1])
        first = find_findings(config, release)
        if first is not None and first.number != number:  # a tester on another computer made one at the same time
            wait.gh("issue", "close", str(number), "--repo", repo, "--reason", "not planned", "--comment",
                    f"A duplicate of #{first.number}, which another tester made first: the findings go there.")
            print(f"another tester made #{first.number} for the release #{release} first: closed #{number}, the "
                  "same list, as its duplicate")
            found = first
        else:
            found, made = Findings(number, release, cards, body), True
            print(f"made the findings issue #{found.number} for the release #{release}")
    have = {card["number"] for card in found.cards}
    added = [number for number in wanted if number not in have]
    if added:
        named = titles(config, added)
        found.cards += [{"number": number, "title": named.get(number, "")} for number in added]
    if not made:
        print(f"the release #{release}'s findings issue is #{found.number}" +
              (f"; added {', '.join(f'#{n}' for n in added)}" if added else ""))
    if not found.cards:
        raise cli.ColonyError(f"the release #{release} names no card: add them with --card <n>")
    states = refresh(config, found)
    for number in sorted(states):
        print(f"  #{number} {states[number].title}: {states[number].result or 'not tested'}")
    print(summary(states))
    print("Prepared test accounts and fixtures, to use before you ask for any:")
    print("\n".join(f"  {line}" for line in registry_lines(read_registry())))
    print(f"Next: `{cli.NAME} findings next {release}` claims a card for you.")
    return 0


def claim_card(config: dict, findings: Findings, card: int, by: str) -> tuple[bool, dict[int, CardState]]:
    """Claim one card and read back whether this tester holds it: the earlier claim wins a race."""
    post_event(config, findings, "claim", card, by)
    states = refresh(config, findings)
    return states.get(card, CardState(card)).holder == by, states


def findings_next(config: dict, args) -> int:
    """`colony findings next <release>`: claim the next card no tester holds and none has tested, and print it."""
    findings, by = need_findings(config, release_number(args.release)), me(args)
    states = refresh(config, findings)
    held = [s for s in states.values() if s.holder == by]
    if held:
        print(f"yours already: #{held[0].number} {held[0].title}: test it, then record it with `{cli.NAME} findings "
              f"report {findings.release} {held[0].number} pass|fail|blocked \"<what you saw>\"`")
        return 0
    tried = set()
    while True:
        free = [s for s in sorted(states.values(), key=lambda s: s.number)
                if not s.result and not s.holder and s.number not in tried]
        if not free:
            break
        card = free[0].number
        tried.add(card)
        won, states = claim_card(config, findings, card, by)
        if won:
            print(f"yours: #{card} {states[card].title}: test its done-when results, then record it with "
                  f"`{cli.NAME} findings report {findings.release} {card} pass|fail|blocked \"<what you saw>\"`")
            return 0
        print(f"#{card} went to {states[card].holder}, who claimed it first; trying the next card")
    others = [s for s in states.values() if s.holder]
    print(f"nothing left to claim: {summary(states)}" +
          (f"; {len(others)} still being tested by {', '.join(sorted({s.holder for s in others}))}" if others else ""))
    if not others and all(s.result for s in states.values()):
        print(done_hint(findings, states))
    return 0


def findings_claim(config: dict, args) -> int:
    """`colony findings claim <release> <card>`: claim one card by number, such as a blocked one to test again."""
    findings, by = need_findings(config, release_number(args.release)), me(args)
    won, states = claim_card(config, findings, args.card, by)
    holder = states.get(args.card, CardState(args.card)).holder
    if not won:
        raise cli.ColonyError(f"#{args.card} is held by {holder or 'another tester'}: take another with "
                              f"`{cli.NAME} findings next {findings.release}`")
    print(f"yours: #{args.card} {states[args.card].title}")
    return 0


def findings_free(config: dict, args) -> int:
    """`colony findings free <release> <card>`: hand a card you hold back, untested, so another tester takes it."""
    findings, by = need_findings(config, release_number(args.release)), me(args)
    states = refresh(config, findings)
    holder = states.get(args.card, CardState(args.card)).holder
    if holder != by:
        raise cli.ColonyError(f"#{args.card} is not yours to free: " +
                              (f"{holder} holds it" if holder else "nobody holds it"))
    post_event(config, findings, "free", args.card, by)
    states = refresh(config, findings)
    print(f"#{args.card} is free for another tester. {summary(states)}")
    return 0


def findings_report(config: dict, args) -> int:
    """`colony findings report <release> <card> pass|fail|blocked "<what you saw>"`: record a card's result."""
    findings, by = need_findings(config, release_number(args.release)), me(args)
    note = " ".join(args.note.split())
    if args.result != "pass" and not note:
        raise cli.ColonyError(f"a {args.result} needs what you saw: the steps, what you expected and what happened")
    if args.card not in {card["number"] for card in findings.cards}:
        findings.cards.append({"number": args.card, "title": titles(config, [args.card]).get(args.card, "")})
    post_event(config, findings, args.result, args.card, by, note)
    states = refresh(config, findings)
    print(f"#{args.card} {args.result}. {summary(states)}")
    if all(s.result for s in states.values()):
        print(done_hint(findings, states))
    return 0


def findings_show(config: dict, args) -> int:
    """`colony findings show <release>`: bring the list up to date and print it."""
    findings = need_findings(config, release_number(args.release))
    states = refresh(config, findings)
    print(f"#{findings.number} {findings_title(findings.release)}")
    for number in sorted(states):
        state = states[number]
        status = state.result or (f"testing by {state.holder}" if state.holder else "not tested")
        print(f"  #{number} {state.title}: {status}" + (f": {state.note}" if state.note else ""))
    print(summary(states))
    return 0


def register(sub) -> None:
    """cli.py's route to this module: `colony fixtures` and `colony findings`."""
    p = sub.add_parser("fixtures", help="the test accounts and fixtures the person prepared, by reference only: "
                                        "list, add or remove one")
    p.add_argument("--json", action="store_true", help="print the registry as JSON")
    p.set_defaults(run=fixtures_list)
    fx = p.add_subparsers(dest="fixtures_command", metavar="fixtures-command")
    q = fx.add_parser("list", help="list them")
    q.add_argument("--json", action="store_true", help="print the registry as JSON")
    q.set_defaults(run=fixtures_list)
    q = fx.add_parser("add", help="record a test account or a fixture the person prepared; never a secret")
    q.add_argument("kind", choices=tuple(TABLES), help="account or fixture")
    q.add_argument("name", help="a short name, such as staging-admin")
    q.add_argument("--what", required=True, help="what it is, such as \"an admin account on staging\"")
    q.add_argument("--where", help="where it lives, such as staging or the sandbox")
    q.add_argument("--login", help="an account's login name or address, which is not a secret")
    q.add_argument("--secret-at", dest="secret_at", help="where its password or key is kept, such as a password "
                                                         "manager's entry; never the secret itself")
    q.add_argument("--how", help="how to make or reset a fixture, such as a command")
    q.add_argument("--note", help="anything else a tester needs")
    q.add_argument("--person", help="who prepared it, you by default")
    q.set_defaults(run=fixtures_add)
    q = fx.add_parser("remove", help="drop one by its name")
    q.add_argument("name", help="its name")
    q.set_defaults(run=fixtures_remove)

    p = sub.add_parser("findings", help="testers: the release's findings list on the code host, shared by every "
                                        "tester on every computer")
    fd = p.add_subparsers(dest="findings_command", metavar="findings-command", required=True)
    q = fd.add_parser("open", help="find or make the release's findings issue, with its cards")
    q.add_argument("release", help="the release pull request's number or link")
    q.add_argument("--card", action="append", type=board.card_number, metavar="N",
                   help="a card to test, instead of the ones the release names; repeat for each")
    q.set_defaults(run=findings_open)
    for name, run, text in (("next", findings_next, "claim the next card no tester holds, and print it"),
                            ("show", findings_show, "bring the list up to date and print it")):
        q = fd.add_parser(name, help=text)
        q.add_argument("release", help="the release pull request's number or link")
        if name == "next":
            q.add_argument("--as", dest="as_name", help="your name in the list, `<session> on <computer>` by default")
        q.set_defaults(run=run)
    for name, run, text in (("claim", findings_claim, "claim one card by its number, such as a blocked one to test "
                                                      "again; your own claim again renews it"),
                            ("free", findings_free, "hand a card you hold back, untested, for another tester")):
        q = fd.add_parser(name, help=text)
        q.add_argument("release", help="the release pull request's number or link")
        q.add_argument("card", type=board.card_number, help="the card")
        q.add_argument("--as", dest="as_name", help="your name in the list, `<session> on <computer>` by default")
        q.set_defaults(run=run)
    q = fd.add_parser("report", help="record a card's result: pass, fail or blocked, with what you saw")
    q.add_argument("release", help="the release pull request's number or link")
    q.add_argument("card", type=board.card_number, help="the card")
    q.add_argument("result", choices=RESULTS, help="pass, fail, or blocked on a step only a person can take")
    q.add_argument("note", nargs="?", default="", help="what you saw: for a fail, the steps, what you expected and "
                                                       "what happened; for a block, the step and whose it is")
    q.add_argument("--as", dest="as_name", help="your name in the list, `<session> on <computer>` by default")
    q.set_defaults(run=findings_report)
