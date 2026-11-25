"""Folders: one lead registry that every copy of the repo reads, loans and borrows of folders between leads, one owner
for the rest of the repo, and one place for worktrees.

The registry. Each lead claims folders and files with `colony claim`. This computer keeps the claims in one file,
`<git common dir>/colony/leads.json`: git keeps that folder for the clone and every worktree of it, so the main
checkout and each helper's worktree read the same file, and no claim needs a commit or a pull request. Each lead's
status comment (presence.py) carries its folders, whether it holds the rest of the repo, its loans and its borrows to
the code host, where every computer reads them. So a reader takes another computer's lead from its live status, and a
lead of this computer from this file (local_view). The registry from before, the repo's `.colony/leads.toml`, is
read once, while this file isn't there yet.

The rest of the repo. A lead that claims no folders holds the rest of the repo: every path no other live lead holds.
One live lead holds it at a time (rest_owner). A second claim with no folders is refused while the first one lives
and acts, and takes the rest over once that one is gone or silent.

Loans and borrows. `colony lend <lead> <path> ... --card N` lends paths a lead holds to another lead for named cards,
so that lead's helpers may take those cards. `colony borrow <path> ... --card N` asks the lead that holds the paths
for such a loan, with a line. When that lead is silent, the paths are borrowed at once, with a line that tells it; an
ask the holder leaves unanswered until it goes silent is granted then (settle).

Silent and gone. A lead is silent when its own session has done nothing for `[leads] silent_minutes`, though its wait
still keeps its status fresh. A silent lead's folders can be borrowed or claimed, and its rest of the repo taken over,
each with a line that tells it. A lead gone for `[leads] drop_after_hours` drops from this computer's registry with its
loans, and `colony who` stops listing it.

Worktrees. Every worktree Colony makes or suggests sits in `[project] worktrees`, `.worktrees` inside the repo by
default. A relative folder starts from the main checkout, so a command run in a worktree never nests one in it, and
git's own exclude file keeps it out of `git status`. `colony worktree add` makes one there, and `colony worktree check`
names any worktree outside it, with the command that moves it in.
"""
from __future__ import annotations

import contextlib
import os
import re
import shlex
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from colony import cli, portable, presence, wait

DEFAULTS = {"silent_minutes": 120, "drop_after_hours": 72}
STORE = "leads.json"  # in <git common dir>/colony/
OLD_FILE = "leads.toml"  # the registry before, in the repo's .colony/, read once
WORKTREES = ".worktrees"  # [project] worktrees when the config names none: inside the repo
WORKTREE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
GRANTS = ("lent", "borrowed", "asks")  # the registry's lists of loans, borrows and open asks


# Settings


def settings(config: dict) -> dict:
    """`[leads]`, each key with its default."""
    table = config.get("leads") or {}
    return {**DEFAULTS, **{key: value for key, value in table.items() if key in DEFAULTS}}


def validate(config: dict) -> None:
    """Refuse `[leads]` keys this version doesn't know, and values that aren't a number above 0."""
    table = config.get("leads") or {}
    if not isinstance(table, dict):
        raise cli.ColonyError("[leads] is a table, such as silent_minutes = 120")
    for key, value in table.items():
        if key not in DEFAULTS:
            raise cli.ColonyError(f"[leads] has no key {key!r}: its keys are {', '.join(DEFAULTS)}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise cli.ColonyError(f"[leads] {key} is a number above 0")


# Where the clone keeps its shared files


KNOWN: dict[str, Path] = {}  # each folder's git common dir, once found: git is asked once per folder per command


def common_dir(start: Path | None = None) -> Path:
    """The clone's git common dir, which the main checkout and every worktree of it share."""
    where = str(start or Path.cwd())
    if where in KNOWN:
        return KNOWN[where]
    found = cli._out(["git", "-C", where, "rev-parse", "--path-format=absolute", "--git-common-dir"])
    if not found:
        raise cli.ColonyError(f"run {cli.NAME} inside a clone of your repo: this folder is not in a git checkout")
    KNOWN[where] = Path(found)
    return KNOWN[where]


def main_checkout(start: Path | None = None) -> Path | None:
    """The clone's main checkout, the folder that holds its .git, from any worktree of it; None outside git."""
    try:
        common = common_dir(start)
    except cli.ColonyError:
        return None
    return common.parent if common.name == ".git" else None


def exclude(line: str, start: Path | None = None) -> bool:
    """Add a line to the clone's own exclude file, <git common dir>/info/exclude, which every worktree reads and
    nothing commits. Returns whether it added it."""
    path = common_dir(start) / "info" / "exclude"
    lines = path.read_text().splitlines() if path.exists() else []
    if line in lines:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([*lines, line]) + "\n")
    return True


# The registry


def store_path() -> Path:
    """This clone's lead registry, <git common dir>/colony/leads.json."""
    return common_dir() / cli.NAME / STORE


def empty() -> dict:
    return {"leads": {}, "seen": {}, "since": {}, "rest": [], "lent": [], "borrowed": [], "asks": []}


def clean_grant(item) -> dict | None:
    """One loan, borrow or ask as the registry keeps it, or None when it is broken."""
    if not isinstance(item, dict):
        return None
    grant = {key: str(item[key]).lower() for key in ("from", "to", "by") if isinstance(item.get(key), str)
             and cli.SESSION_NAME.fullmatch(str(item[key]).lower())}
    paths = item.get("paths")
    cards = item.get("cards")
    grant["paths"] = [str(path) for path in paths if isinstance(path, str) and path] if isinstance(paths, list) else []
    grant["cards"] = [int(card) for card in cards if isinstance(card, int) and not isinstance(card, bool)] \
        if isinstance(cards, list) else []
    grant["at"] = presence.clean_number(item.get("at"))
    if isinstance(item.get("why"), str):
        grant["why"] = presence.clean_text(item["why"])
    return grant if grant["paths"] else None


def normal(data) -> dict:
    """The registry with every part in its shape, whatever the file held."""
    out = empty()
    data = data if isinstance(data, dict) else {}
    leads = data.get("leads")
    for name, lead in (leads.items() if isinstance(leads, dict) else []):
        if isinstance(lead, dict):
            folders = lead.get("folders")
            out["leads"][str(name)] = {"person": str(lead.get("person") or ""),
                                       "folders": [str(f) for f in folders] if isinstance(folders, list) else []}
    for key in ("seen", "since"):
        times = data.get(key)
        out[key] = {str(name): presence.clean_number(at) for name, at in (times.items() if isinstance(times, dict)
                                                                         else []) if name in out["leads"]}
    rest = data.get("rest")
    out["rest"] = [str(name) for name in rest if name in out["leads"]] if isinstance(rest, list) else []
    for key in GRANTS:
        given = data.get(key)
        out[key] = [grant for item in (given if isinstance(given, list) else []) if (grant := clean_grant(item))]
    return out


def imported() -> dict:
    """The registry from before, the repo's tracked .colony/leads.toml, the main checkout's first, else {}. The clock
    that drops a long-gone lead starts now for each lead it names."""
    roots = [root for root in (main_checkout(), cli.repo_root()) if root]
    for root in dict.fromkeys(roots):
        try:
            data = tomllib.loads((root / cli.DIR / OLD_FILE).read_text())
        except (OSError, tomllib.TOMLDecodeError):
            continue
        leads = data.get("leads")
        if isinstance(leads, dict):
            now = time.time()
            return {"leads": leads, "seen": {str(name): now for name in leads}}
    return {}


def load() -> dict:
    """This clone's registry: its file, else the one from before (imported), else an empty one."""
    data = wait.read_json(store_path(), None)
    return normal(imported() if data is None else data)


@contextlib.contextmanager
def changing():
    """Read the registry under its lock, let the caller change it, and write it whole when the block ends, so two
    commands at once never lose each other's change."""
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "a") as handle, portable.lock(handle):
        data = load()
        yield data
        for key in ("seen", "since"):
            data[key] = {name: at for name, at in data[key].items() if name in data["leads"]}
        data["rest"] = [name for name in dict.fromkeys(data["rest"]) if name in data["leads"]]
        data["lent"] = [g for g in data["lent"] if g.get("from") in data["leads"]]
        data["borrowed"] = [g for g in data["borrowed"] if g.get("by") in data["leads"]]
        data["asks"] = [g for g in data["asks"] if g.get("by") in data["leads"]]
        wait.write_json(path, data)


def leads() -> dict[str, dict]:
    """Each lead this clone's registry holds, with its person and folders."""
    return load()["leads"]


def write_leads(given: dict[str, dict]) -> None:
    """Replace the registry's leads, keeping each kept lead's times, rest, loans and borrows."""
    with changing() as data:
        data["leads"] = {str(name): {"person": str(lead.get("person", "")),
                                     "folders": [str(f) for f in lead.get("folders", [])]}
                         for name, lead in given.items()}
        now = time.time()
        for name in data["leads"]:
            data["seen"].setdefault(name, now)


def mine(name: str, data: dict | None = None) -> dict:
    """What the registry says of one lead: its folders, whether it holds the rest, since when, and its grants."""
    data = data or load()
    lead = data["leads"].get(name, {})
    return {"folders": list(lead.get("folders", [])), "rest": name in data["rest"],
            "since": data["since"].get(name, 0.0),
            "lent": [strip(g) for g in data["lent"] if g.get("from") == name],
            "borrowed": [strip(g) for g in data["borrowed"] if g.get("by") == name],
            "asks": [strip(g) for g in data["asks"] if g.get("by") == name]}


def strip(grant: dict) -> dict:
    """A grant without the lead it belongs to, as its lead's status carries it."""
    return {key: value for key, value in grant.items() if key not in ("by",) and not (key == "from" and "to" in grant)}


def seen(name: str, now: float | None = None) -> None:
    """Note that a lead of this computer was alive now, which keeps it from being dropped."""
    with changing() as data:
        if name in data["leads"]:
            data["seen"][name] = time.time() if now is None else now


# Who holds what


def silent_for(status, now: float) -> float:
    """How many seconds a lead's own session has done nothing, by its status's last activity; 0 when unknown."""
    active = getattr(status, "active", 0.0) or 0.0
    return max(0.0, now - active) if active else 0.0


def silent(config: dict, status, now: float | None = None) -> bool:
    """Whether a live lead is silent: its session has done nothing for `[leads] silent_minutes`."""
    now = time.time() if now is None else now
    return status.kind == "lead" and silent_for(status, now) >= float(settings(config)["silent_minutes"]) * 60


def holds_rest(status) -> bool:
    """Whether a lead claims the rest of the repo: it says so, or, from before this version, it holds no folders."""
    return status.kind == "lead" and (status.rest or (not status.folders and not status.since))


def rest_owner(config: dict, alive: list, now: float | None = None, skip: str = "") -> str:
    """The one live lead that holds the rest of the repo, or "": of the leads that claim it, a lead that isn't silent
    first, then the one that claimed it first, then by name."""
    now = time.time() if now is None else now
    claims = [s for s in alive if holds_rest(s) and s.name != skip]
    claims.sort(key=lambda s: (silent(config, s, now), s.since or 0.0, s.name))
    return claims[0].name if claims else ""


def covered(path: str, held: list[str]) -> bool:
    """Whether a path sits in one of the held paths: in a folder, or the very file."""
    return presence.inside(path, held)


def local_view(alive: list) -> list:
    """The live statuses with this computer's own leads as its registry has them now: a claim or a loan made a
    moment ago shows before the lead's status comment carries it."""
    try:
        data = load()
    except cli.ColonyError:
        return alive
    here = presence.computer()
    for status in alive:
        if status.kind == "lead" and status.name in data["leads"] and status.computer in (here, ""):
            held = mine(status.name, data)
            status.folders, status.rest, status.since = held["folders"], held["rest"], held["since"] or status.since
            status.lent, status.borrowed = held["lent"], held["borrowed"]
    return alive


def view_of(alive: list, name: str):
    """A lead's live status, else what this computer's registry says of it, else None."""
    found = next((s for s in alive if s.kind == "lead" and s.name == name), None)
    if found is not None:
        return found
    data = load()
    if name not in data["leads"]:
        return None
    held = mine(name, data)
    return presence.Status(name, "lead", person=data["leads"][name]["person"], folders=held["folders"],
                           rest=held["rest"], since=held["since"], lent=held["lent"], borrowed=held["borrowed"])


def lent_to(alive: list, lead: str, card: int) -> list[str]:
    """The paths live leads lent `lead` for card `card`, and the paths `lead` borrowed for it."""
    paths = [path for s in alive if s.kind == "lead" and s.name != lead for grant in s.lent
             if grant.get("to") == lead and card in grant.get("cards", []) for path in grant.get("paths", [])]
    me = view_of(alive, lead)
    if me is not None:
        paths += [path for grant in me.borrowed if card in grant.get("cards", []) for path in grant.get("paths", [])]
    return list(dict.fromkeys(paths))


def why_not_take(config: dict, alive: list, lead: str, card: int, paths: list[str], now: float | None = None) -> str:
    """Why a helper of `lead` may not take card `card`, whose `Folders:` line names `paths`, or "" when it may. A
    lead with folders takes cards inside them; the lead that holds the rest of the repo takes cards outside every
    other live lead's folders; a lead with neither takes none. Paths lent or borrowed for the card count as its own."""
    now = time.time() if now is None else now
    extra = lent_to(alive, lead, card)
    me = view_of(alive, lead)
    own = list(me.folders) if me is not None else []
    if own:
        outside = [path for path in paths if not covered(path, own + extra)]
        if outside:
            return (f"card #{card} touches {', '.join(outside)}, outside {lead}'s folders ({', '.join(own)}): post "
                    f"`question:` to {lead}, which can borrow them for the card with `{cli.NAME} borrow`, and take no "
                    "card outside them")
        return ""
    owner = rest_owner(config, alive, now)
    if owner and owner != lead:
        if all(covered(path, extra) for path in paths):
            return ""
        return (f"{lead} holds no folders, and {owner} holds the rest of the repo: {lead} claims this card's folders "
                f"with `{cli.NAME} claim --add`, or borrows them with `{cli.NAME} borrow`, before a helper takes it")
    held = [(path, theirs, other) for other, owned in presence.held_by_others(alive, lead).items()
            for path in paths for theirs in owned if presence.overlaps(path, theirs) and not covered(path, extra)]
    if held:
        path, _, other = held[0]
        return (f"card #{card} touches {path}, which {other} holds: post `question:` to {lead}, which can borrow it "
                f"with `{cli.NAME} borrow`, and take no card in another lead's folders")
    return ""


def holders(config: dict, alive: list, me: str, paths: list[str], now: float | None = None) -> dict[str, list[str]]:
    """Which live lead holds each path, other than `me`: the lead whose folders overlap it, else, for a path no lead's
    folders hold and `me` neither, the lead that holds the rest of the repo."""
    now = time.time() if now is None else now
    found: dict[str, list[str]] = {}
    me_view = view_of(alive, me)
    mine_now = list(me_view.folders) if me_view is not None else []
    owner = rest_owner(config, alive, now)
    for path in paths:
        if covered(path, mine_now):
            continue
        named = [other for other, owned in presence.held_by_others(alive, me).items()
                 if any(presence.overlaps(path, theirs) for theirs in owned)]
        if not named and owner and owner != me:
            named = [owner]
        for other in named:
            found.setdefault(other, []).append(path)
    return found


# Telling another lead


def tell(config: dict, to: str, sentence: str, sender: str) -> None:
    """Post a line to another lead; a post that fails says so on stderr, since the registry changed either way."""
    from colony import transport

    try:
        transport.send(config, to, wait.compose(to, sentence, sender))
    except (cli.ColonyError, OSError, ValueError, KeyError) as e:
        print(f"{cli.NAME}: {to} didn't hear it: {e}", file=sys.stderr)


def show_now(config: dict, args, name: str) -> None:
    """Edit the lead's status comment now, not at the next 5-minute edit, so every computer sees the change."""
    path = wait.state_path(config["project"]["name"], f"{name}-status")
    state = wait.read_json(path, {})
    state = state if isinstance(state, dict) else {}
    state.pop("status_at", None)
    try:
        presence.keep(config, presence.mine(config, args, name, "lead"), state)
        wait.write_json(path, state)
    except (cli.ColonyError, OSError, ValueError, KeyError) as e:
        print(f"{cli.NAME}: the status comment shows it at the next `{cli.NAME} wait`: {e}", file=sys.stderr)


def my_lead() -> str:
    """The lead this session holds, $COLONY_LEAD, or a ColonyError."""
    name = os.environ.get(wait.LEAD_ENV, "").lower()
    if not name or os.environ.get(cli.SESSION_ENV, "").lower() != cli.LEAD:
        raise cli.ColonyError(f"a lead lends and borrows folders: first claim one, `{cli.NAME} claim <stream> "
                              "<path> ...`")
    return name


def cards_text(cards: list[int]) -> str:
    return ", ".join(f"#{card}" for card in cards)


def paths_text(paths: list[str]) -> str:
    return ", ".join(paths)


# Asks that wait for an answer


def settle(config: dict, name: str, alive: list, now: float | None = None) -> list[str]:
    """Answer `name`'s open asks from what the holders' live statuses say: an ask the holder lent drops; an ask whose
    holder is silent or gone is borrowed now, with a line that tells the holder. Returns one line per change."""
    now = time.time() if now is None else now
    changes, told = [], []
    with changing() as data:
        keep = []
        for ask in data["asks"]:
            if ask.get("by") != name:
                keep.append(ask)
                continue
            holder = next((s for s in alive if s.kind == "lead" and s.name == ask.get("from")), None)
            if holder is not None and all(any(grant.get("to") == name and card in grant.get("cards", [])
                                              and covered(path, grant.get("paths", [])) for grant in holder.lent)
                                          for path in ask["paths"] for card in ask["cards"]):
                changes.append(f"{ask['from']} lent {paths_text(ask['paths'])} for {cards_text(ask['cards'])}")
                continue
            if holder is not None and not silent(config, holder, now):
                keep.append(ask)
                continue
            why = (f"{ask['from']} has been silent for {int(silent_for(holder, now) // 60)} minutes"
                   if holder is not None else f"{ask['from']} is gone")
            data["borrowed"].append({"by": name, "from": ask["from"], "paths": ask["paths"], "cards": ask["cards"],
                                     "at": now, "why": why})
            changes.append(f"borrowed {paths_text(ask['paths'])} for {cards_text(ask['cards'])}, since {why}")
            if holder is not None:
                told.append((ask["from"], f"borrowed: {name} uses {paths_text(ask['paths'])} for "
                                          f"{cards_text(ask['cards'])}, since you were silent past its ask; answer "
                                          f"{name} to have them back"))
        data["asks"] = keep
    for to, sentence in told:
        tell(config, to, sentence, name)
    return changes


def settle_quietly(config: dict, name: str) -> None:
    """The lead's wait settles its open asks at each status edit: it reads the statuses only when it has one open."""
    try:
        if not mine(name)["asks"]:
            return
        alive, _, _ = presence.everyone(config)
        for line in settle(config, name, alive):
            print(f"{cli.NAME}: {line}", flush=True)
    except (cli.ColonyError, OSError, ValueError, KeyError) as e:
        print(f"{cli.NAME}: the open asks were not settled: {e}", file=sys.stderr)


# Dropping long-gone leads


def prune(config: dict, alive: list, now: float | None = None) -> list[str]:
    """Drop from this clone's registry each lead gone, by its status and this computer's record, for
    `[leads] drop_after_hours`, with its rest, loans, borrows and asks, and each grant older than that. The clock of a
    lead this computer never saw starts now. Returns the dropped leads."""
    now = time.time() if now is None else now
    after = float(settings(config)["drop_after_hours"]) * 3600
    statuses = {s.name: s for s in alive if s.kind == "lead"}
    dropped = []
    with changing() as data:
        for name in list(data["leads"]):
            if name in statuses:
                data["seen"][name] = now
                continue
            last = data["seen"].get(name) or data["since"].get(name)
            if not last:
                data["seen"][name] = now
            elif now - last >= after:
                del data["leads"][name]
                dropped.append(name)
        for key in GRANTS:
            data[key] = [g for g in data[key] if not g.get("at") or now - g["at"] < after]
    return dropped


def long_gone(config: dict, statuses: list, now: float | None = None) -> tuple[list, int]:
    """The gone statuses `colony who` lists, and how many it leaves out because they went over `[leads]
    drop_after_hours` ago."""
    now = time.time() if now is None else now
    after = float(settings(config)["drop_after_hours"]) * 3600
    shown = [s for s in statuses if now - s.at < after]
    return shown, len(statuses) - len(shown)


# Claims


def claim_check(config: dict, alive: list, name: str, paths: list[str], now: float | None = None) -> list[tuple[str, str]]:
    """Refuse paths another live lead holds, unless that lead is silent; refuse the rest of the repo, `paths` empty,
    while another lead that isn't silent holds it. Returns the silent leads whose folders or rest this claim takes,
    each with what, for the lines that tell them."""
    now = time.time() if now is None else now
    taken, clash = [], []
    for lead, owned in presence.held_by_others(alive, name).items():
        status = next(s for s in alive if s.name == lead and s.kind == "lead")
        hits = [f"{path} overlaps {theirs} of {lead}" for path in paths for theirs in owned
                if presence.overlaps(path, theirs)]
        if hits and silent(config, status, now):
            taken.append((lead, paths_text([path for path in paths if any(presence.overlaps(path, theirs)
                                                                           for theirs in owned)])))
        elif hits:
            clash += hits
    if clash:
        raise cli.ColonyError(f"another live lead holds those folders: {'; '.join(clash)}. Pick other folders, or "
                              f"borrow them for a card with `{cli.NAME} borrow`")
    if not paths:
        owner = rest_owner(config, alive, now, skip=name)
        if owner:
            status = next(s for s in alive if s.name == owner and s.kind == "lead")
            if not silent(config, status, now):
                raise cli.ColonyError(f"{owner} holds the rest of the repo, and one lead holds it at a time: claim "
                                      f"folders instead, `{cli.NAME} claim <stream> <folder> ...`")
            taken.append((owner, "the rest of the repo"))
    return taken


def record_claim(config: dict, alive: list, name: str, person: str, paths: list[str]) -> list[str]:
    """Write a lead's claim to the registry: its person and paths, and the rest of the repo when it names none, with
    the time; drop the long-gone leads first. Returns the leads it dropped."""
    dropped = prune(config, alive)
    now = time.time()
    with changing() as data:
        data["leads"][name] = {"person": person, "folders": paths}
        data["since"][name] = now
        data["seen"][name] = now
        data["rest"] = [lead for lead in data["rest"] if lead != name] + ([name] if not paths else [])
    return dropped


def tell_taken(config: dict, name: str, taken: list[tuple[str, str]]) -> None:
    """Tell each silent lead what a claim took from it."""
    minutes = int(settings(config)["silent_minutes"])
    for lead, what in taken:
        tell(config, lead, f"claimed: {name} took {what}, since you were silent for {minutes} minutes or more; "
                           f"answer {name} to talk it over", name)


# colony lend, colony borrow, colony leads


def lend(config: dict, args) -> int:
    """`colony lend <lead> <path> ... --card N`: lend paths this lead holds to another lead for the named cards, so
    that lead's helpers may take them. `--end` ends the loans to that lead, for the named cards or all."""
    me = my_lead()
    to = args.to.lower()
    if not cli.SESSION_NAME.fullmatch(to) or to == me:
        raise cli.ColonyError(f"lend to another lead by its name, such as ben-web-lead, not {args.to!r}")
    cards = sorted(set(args.card or []))
    if args.end:
        with changing() as data:
            before = len(data["lent"])
            data["lent"] = [g for g in data["lent"] if not (g.get("from") == me and g.get("to") == to
                                                            and (not cards or set(g["cards"]) & set(cards)))]
            ended = before - len(data["lent"])
        print(f"Ended {ended} loan{'s' if ended != 1 else ''} to {to}.")
        if ended:
            show_now(config, args, me)
            tell(config, to, f"lend ended: {me} takes back what it lent"
                             + (f" for {cards_text(cards)}" if cards else ""), me)
        return 0
    if not args.paths or not cards:
        raise cli.ColonyError(f"name the paths and the cards: `{cli.NAME} lend {to} <path> ... --card <n>`")
    paths = list(dict.fromkeys(presence.folder(path) for path in args.paths))
    alive, _, note = presence.everyone(config)
    if note:
        print(note, file=sys.stderr)
    me_view = view_of(alive, me)
    own = list(me_view.folders) if me_view is not None else []
    if own:
        not_mine = [path for path in paths if not covered(path, own)]
    elif rest_owner(config, alive) in ("", me):  # the rest of the repo: every path no other live lead holds
        others = [theirs for owned in presence.held_by_others(alive, me).values() for theirs in owned]
        not_mine = [path for path in paths if any(presence.overlaps(path, theirs) for theirs in others)]
    else:
        not_mine = paths
    if not_mine:
        raise cli.ColonyError(f"{me} doesn't hold {paths_text(not_mine)}: lend only what it holds")
    with changing() as data:
        data["lent"].append({"from": me, "to": to, "paths": paths, "cards": cards, "at": time.time()})
    print(f"{me} lends {paths_text(paths)} to {to} for {cards_text(cards)}.")
    show_now(config, args, me)
    tell(config, to, f"lent: {me} lends {paths_text(paths)} for {cards_text(cards)}, so your helpers may take "
                     f"{'that card' if len(cards) == 1 else 'those cards'}", me)
    return 0


def borrow(config: dict, args) -> int:
    """`colony borrow <path> ... --card N`: ask the lead that holds the paths to lend them for the named cards. A
    silent lead's paths are borrowed at once. `--check` settles the open asks, and `--return` gives back what this
    lead borrowed and drops its asks, for the named cards or all."""
    me = my_lead()
    cards = sorted(set(args.card or []))
    if args.give_back:
        with changing() as data:
            back = [g for g in data["borrowed"] if g.get("by") == me and (not cards or set(g["cards"]) & set(cards))]
            data["borrowed"] = [g for g in data["borrowed"] if g not in back]
            data["asks"] = [g for g in data["asks"] if not (g.get("by") == me and (not cards or
                                                                                  set(g["cards"]) & set(cards)))]
        for grant in back:
            tell(config, grant["from"], f"returned: {me} gives back {paths_text(grant['paths'])}", me)
        print(f"{me} gave back {len(back)} borrow{'s' if len(back) != 1 else ''}.")
        show_now(config, args, me)
        return 0
    alive, _, note = presence.everyone(config)
    if note:
        print(note, file=sys.stderr)
    if args.check:
        changes = settle(config, me, alive)
        print("\n".join(changes) if changes else "No open ask changed.")
        if changes:
            show_now(config, args, me)
        return 0
    if not args.paths or not cards:
        raise cli.ColonyError(f"name the paths and the cards: `{cli.NAME} borrow <path> ... --card <n>`")
    paths = list(dict.fromkeys(presence.folder(path) for path in args.paths))
    now = time.time()
    found = holders(config, alive, me, paths, now)
    free = [path for path in paths if not any(path in held for held in found.values())]
    lines, told = [], []
    minutes = int(settings(config)["silent_minutes"])
    with changing() as data:
        if me not in data["leads"]:
            raise cli.ColonyError(f"{me} is not in this computer's registry: run `{cli.NAME} claim` again here")
        for holder, held in found.items():
            status = next(s for s in alive if s.name == holder and s.kind == "lead")
            if silent(config, status, now):
                why = f"{holder} has been silent for {int(silent_for(status, now) // 60)} minutes"
                data["borrowed"].append({"by": me, "from": holder, "paths": held, "cards": cards, "at": now,
                                         "why": why})
                lines.append(f"Borrowed {paths_text(held)} from {holder} for {cards_text(cards)}, since {why}.")
                told.append((holder, f"borrowed: {me} uses {paths_text(held)} for {cards_text(cards)}, since you "
                                     f"were silent; answer {me} to have them back"))
            else:
                data["asks"].append({"by": me, "from": holder, "paths": held, "cards": cards, "at": now})
                lines.append(f"Asked {holder} for {paths_text(held)} for {cards_text(cards)}. Once it lends them, or "
                             f"has been silent for {minutes} minutes, `{cli.NAME} borrow --check` settles the ask, "
                             "and the wait does it too.")
                told.append((holder, f"borrow: {me} asks for {paths_text(held)} for {cards_text(cards)}: `{cli.NAME} "
                                     f"lend {me} {' '.join(held)} {' '.join(f'--card {c}' for c in cards)}` says yes; "
                                     f"silent for {minutes} minutes counts as a yes"))
    for line in lines:
        print(line)
    if free:
        print(f"No live lead holds {paths_text(free)}: claim {'it' if len(free) == 1 else 'them'} with "
              f"`{cli.NAME} claim --add {' '.join(free)}`.")
    for to, sentence in told:
        tell(config, to, sentence, me)
    if found:
        show_now(config, args, me)
    return 0


def grant_text(grant: dict, word: str) -> str:
    who = grant.get("to") or grant.get("from") or ""
    return f"{word} {paths_text(grant['paths'])} {'to' if 'to' in grant else 'from'} {who} for {cards_text(grant['cards'])}"


def leads_command(config: dict, args) -> int:
    """`colony leads`: who holds what across every computer, the rest of the repo's one owner, the loans, borrows and
    open asks, the silent leads, and this computer's registry entries that are gone, after dropping the long-gone."""
    alive, gone, note = presence.everyone(config)
    if note:
        print(note, file=sys.stderr)
    now = time.time()
    dropped = prune(config, alive, now)
    owner = rest_owner(config, alive, now)
    print(f"The rest of the repo: {owner or 'no live lead holds it'}.")
    leads = sorted((s for s in alive if s.kind == "lead"), key=lambda s: s.name)
    for s in leads:
        held = ", ".join(s.folders) or ("the rest of the repo" if s.name == owner else "no folders")
        quiet = f", silent for {int(silent_for(s, now) // 60)} minutes" if silent(config, s, now) else ""
        grants = [grant_text(g, "lends") for g in s.lent] + [grant_text(g, "borrowed") for g in s.borrowed]
        print(f"- {s.name} ({s.person or 'unknown person'}, {s.computer or 'unknown computer'}{quiet}): {held}"
              + (f"; {'; '.join(grants)}" if grants else ""))
    data = load()
    asks = [g for g in data["asks"]]
    for ask in asks:
        print(f"- open ask: {ask['by']} asks {ask['from']} for {paths_text(ask['paths'])} for "
              f"{cards_text(ask['cards'])}, {cli.ago(now - ask['at'])} ago")
    names = {s.name for s in leads}
    away = [name for name in sorted(data["leads"]) if name not in names]
    if away:
        print("In this computer's registry, not alive: " + ", ".join(
            f"{name} (seen {cli.ago(now - data['seen'].get(name, now))} ago)" for name in away))
    if dropped:
        print(f"Dropped, gone for {int(settings(config)['drop_after_hours'])} hours or more: {', '.join(dropped)}.")
    old = [root / cli.DIR / OLD_FILE for root in dict.fromkeys(r for r in (main_checkout(), cli.repo_root()) if r)]
    if any(path.exists() for path in old) and store_path().exists():
        print(f"{cli.DIR}/{OLD_FILE} is no longer read: the registry lives in {store_path()}, which every worktree "
              "shares. Delete the old file in a commit once every computer runs this version.")
    return 0


# Worktrees


def worktrees_folder(config: dict) -> Path:
    """The folder every worktree goes in, `[project] worktrees`."""
    return Path(config["project"].get("worktrees") or WORKTREES).expanduser()


def in_repo(config: dict, start: Path | None = None) -> bool:
    """Whether the worktrees folder sits inside the clone's main checkout."""
    main = main_checkout(start)
    if main is None:
        return False
    try:
        worktrees_folder(config).resolve().relative_to(main.resolve())
    except ValueError:
        return False
    return True


def keep_out(folder: str | Path, main: Path | None) -> None:
    """Keep a worktrees folder inside the main checkout out of `git status`, with a line in the clone's own exclude
    file, so a worktree there never counts as an uncommitted change; nothing for a folder outside it."""
    if main is None:
        return
    try:
        relative = Path(folder).expanduser().resolve().relative_to(main.resolve()).as_posix()
    except ValueError:
        return
    if relative not in ("", "."):
        try:
            exclude(f"/{relative}/", main)
        except (cli.ColonyError, OSError):
            pass


def ready(config: dict, start: Path | None = None) -> Path:
    """Make the worktrees folder, kept out of `git status` when it sits inside the repo (keep_out). Returns it."""
    folder = worktrees_folder(config)
    folder.mkdir(parents=True, exist_ok=True)
    keep_out(folder, main_checkout(start))
    return folder


def worktree_path(config: dict, name: str) -> Path:
    """A worktree's folder, `<worktrees>/<project>-<name>`, refusing a name that would leave the worktrees folder."""
    if not WORKTREE_NAME.fullmatch(name) or ".." in name:
        raise cli.ColonyError(f"{name!r} is not a worktree name: use letters, digits, dots, dashes and underscores")
    return worktrees_folder(config) / f"{config['project']['name']}-{name}"


def listed(root: Path) -> list[dict]:
    """The clone's worktrees from `git worktree list --porcelain`, each as {path, branch}, the main checkout first."""
    run = subprocess.run(["git", "-C", str(root), "worktree", "list", "--porcelain"], capture_output=True, text=True)
    found, entry = [], {}
    for line in (run.stdout.splitlines() if run.returncode == 0 else []) + [""]:
        if not line:
            if entry.get("worktree"):
                found.append({"path": entry["worktree"], "branch": entry.get("branch", "").removeprefix("refs/heads/")})
            entry = {}
            continue
        key, _, value = line.partition(" ")
        entry[key] = value
    return found


def strays(config: dict, root: Path | None = None) -> list[dict]:
    """The worktrees outside the worktrees folder, the main checkout aside."""
    root = root or cli.repo_root()
    folder = worktrees_folder(config).resolve()
    found = []
    for tree in listed(root)[1:]:
        try:
            Path(tree["path"]).resolve().relative_to(folder)
        except ValueError:
            found.append(tree)
    return found


def notes(config: dict, start: Path | None = None) -> list[str]:
    """What a lead hears at its start about worktrees: a worktrees folder outside the repo, and worktrees outside the
    folder."""
    lines = []
    if main_checkout(start) is not None and not in_repo(config, start):
        lines.append(f"[project] worktrees is {config['project'].get('worktrees')}, outside the repo, so worktrees "
                     f"scatter where the person keeps other things: set it to \"{WORKTREES}\", inside the repo, in "
                     f"{cli.DIR}/{cli.CONFIG_NAME} or {cli.DIR}/colony.local.toml")
    try:
        found = strays(config, start)
    except (cli.ColonyError, OSError):
        found = []
    if found:
        lines.append(f"{len(found)} worktree{'s sit' if len(found) != 1 else ' sits'} outside "
                     f"{worktrees_folder(config)}: `{cli.NAME} worktree check` names them and the command that moves "
                     "each in")
    return lines


def worktree(config: dict, args) -> int:
    """`colony worktree add|path|check`: make a worktree inside the worktrees folder, print a worktree's folder, or name
    the worktrees outside it."""
    root = cli.repo_root()
    if args.action == "path":
        print((worktree_path(config, args.name) if args.name else worktrees_folder(config)).as_posix())
        return 0
    if args.action == "check":
        found = strays(config, root)
        folder = worktrees_folder(config)
        for line in notes(config, root)[:1] if not in_repo(config, root) else []:
            print(line)
        if not found:
            print(f"Every worktree sits in {folder.as_posix()}.")
            return 0
        print(f"{len(found)} worktree{'s sit' if len(found) != 1 else ' sits'} outside {folder.as_posix()}; move "
              "each in when its session is not using it:")
        for tree in found:
            target = folder / Path(tree["path"]).name
            print(f"  {tree['path']} ({tree['branch'] or 'detached'}): git worktree move {shlex.quote(tree['path'])} "
                  f"{shlex.quote(target.as_posix())}")
        return 1
    path = worktree_path(config, args.name)
    command = ["git", "worktree", "add"]
    command += ["--detach"] if args.detach else ["-b", args.branch] if args.branch else []
    command += [path.as_posix(), args.start]
    if args.dry_run:
        print("$ " + shlex.join(command))
        return 0
    ready(config, root)
    if args.start.startswith("origin/"):
        subprocess.run(["git", "-C", str(root), "fetch", "-q", "origin"], capture_output=True)
    made = subprocess.run(command, cwd=root, capture_output=True, text=True)
    if made.returncode:
        raise cli.ColonyError(f"git worktree add failed: {(made.stderr or made.stdout).strip()[:300]}")
    print(path.as_posix())
    return 0


def register(sub) -> None:
    """cli.py's route to this module: `leads`, `lend`, `borrow` and `worktree`."""
    p = sub.add_parser("leads", help="who holds which folders on every computer, the rest of the repo's owner, the "
                                     "loans and borrows, and the silent and gone leads")
    p.add_argument("--person", help="whose session this is")
    p.set_defaults(run=leads_command)
    p = sub.add_parser("lend", help="a lead: lend paths it holds to another lead for named cards, or --end a loan")
    p.add_argument("to", help="the other lead, such as ben-web-lead")
    p.add_argument("paths", nargs="*", metavar="path", help="the folders or files, inside this lead's")
    p.add_argument("--card", type=int, action="append", help="a card the loan is for; repeat for each card")
    p.add_argument("--end", action="store_true", help="end the loans to that lead, for the named cards or all")
    p.add_argument("--person", help="whose session this is")
    p.set_defaults(run=lend)
    p = sub.add_parser("borrow", help="a lead: ask the lead holding paths to lend them for named cards; a silent "
                                      "lead's are borrowed at once")
    p.add_argument("paths", nargs="*", metavar="path", help="the folders or files")
    p.add_argument("--card", type=int, action="append", help="a card the borrow is for; repeat for each card")
    p.add_argument("--check", action="store_true", help="settle the open asks: lent, or the holder went silent")
    p.add_argument("--return", dest="give_back", action="store_true",
                   help="give back what this lead borrowed, for the named cards or all")
    p.add_argument("--person", help="whose session this is")
    p.set_defaults(run=borrow)
    p = sub.add_parser("worktree", help="make a worktree inside [project] worktrees, print its folder, or check that "
                                        "every worktree sits there")
    actions = p.add_subparsers(dest="action", metavar="action", required=True)
    a = actions.add_parser("add", help="make <worktrees>/<project>-<name> at a start point, and print its folder")
    a.add_argument("name", help="the worktree's name, such as builder-2-41 or next-2026-11-05")
    a.add_argument("start", help="where it starts, such as origin/main")
    kind = a.add_mutually_exclusive_group()
    kind.add_argument("-b", dest="branch", help="the new branch it checks out")
    kind.add_argument("--detach", action="store_true", help="no branch: a detached head")
    a.add_argument("--dry-run", action="store_true", help="print the git command, and run nothing")
    a.set_defaults(run=worktree)
    a = actions.add_parser("path", help="print the worktrees folder, or one worktree's folder")
    a.add_argument("name", nargs="?", help="the worktree's name")
    a.set_defaults(run=worktree)
    a = actions.add_parser("check", help="name each worktree outside the worktrees folder, with the command that "
                                         "moves it in")
    a.set_defaults(run=worktree)
