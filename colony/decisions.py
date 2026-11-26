"""Human decisions: what a lead asks the person, what it decides alone and logs, and what the person approved
(docs/decisions.md).

- **Ask only about real decisions.** `colony ask` is the one way a lead asks the person. Each question has a kind:
  `scope` (what is built), `product` (a choice no doc settles), `stop` (an item on the stop list), `gate` (a draft
  the person approves before it is built) or `routine` (anything a lead can settle itself). The person's
  `decisions.autonomy` and the kind decide what happens (policy): the lead holds that work until the answer, keeps
  working on its default while it waits, or decides alone and logs the decision. A routine question is never asked
  unless the person asked to be asked everything, and a stop or gate question is always asked and always held.
- **Don't raise, and budgets.** A question about a topic on the person's `decisions.never_raise` list is never asked
  (`colony never-raise` keeps the list), and `colony spend` holds every session to `budgets.dollars_per_day`.
- **Check teammates' work first.** Before a question goes to the person, `colony ask` looks for an earlier answer to
  the same question, open issues and pull requests about it, and a live lead whose folders it names, and stops when
  it finds one, so the lead reads that first.
- **One place for pending decisions.** Every question goes on the person's `Needs <Person>` issue with its full
  explanation attached, and every answer is recorded word for word, there and in the ledger on this computer,
  ~/.colony/<project>/decisions.json. `colony decisions` lists what waits, and `colony answer` records an answer.
- **Approval gates.** A `gate` question carries a draft; its build waits for the person's yes (`approved`).
- **Approvals reach helpers.** The person approves at their own terminal, never through an agent: `colony approve`
  refuses unless it runs at an interactive terminal outside any agent's session, and the person types yes. Each
  approval is a set of Claude Code permission rules (check_rule) kept in this computer's Colony state for at most a
  day. The PreToolUse hook (boot.session_hook) lets a matching call of that person's leads and helpers here through,
  so a helper's permission check doesn't stop what the person already said yes to. It only ever allows: a guard that
  refuses a call still refuses it. Nothing on the code host ever carries an approval.

Python 3.11+ standard library only.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path, PurePath, PurePosixPath
from urllib.parse import urlparse

from colony import cli, profile, wait

KINDS = {
    "scope": "what is built: its goal, its size, or what is left out",
    "product": "a product or screen choice no doc settles",
    "stop": "an item on the stop list: spending, a secret, deleting data, a dependency, or a merge",
    "gate": "a draft the person approves before it is built",
    "routine": "how to build it: anything a lead can settle from the code, the docs and the team's work",
}
HOLD, GO, DECIDE, NOT_RAISED = "hold", "go", "decide", "not raised"
PENDING, ANSWERED, DECIDED, TOOK_DEFAULT, WITHDRAWN = "pending", "answered", "decided", "took the default", "withdrawn"
YES = re.compile(r"^\W*(yes|yep|yeah|y|ok|okay|sure|approved?|go( ahead)?|lgtm|do it|ship it|sounds good)\b", re.I)
NO = re.compile(r"^\W*(no|nope|n|don'?t|do not|not yet|reject(ed)?|stop|hold off)\b", re.I)
SIMILAR = 0.6  # the share of words two questions hold in common to count as the same question
STOPWORDS = frozenset("""a an and are as at be but by can do does for from has have how i if in into is it its keep
make may me my not of on or our should so than that the their them then there these this those to use was we what
when where which while who why will with would you your yes no""".split())
APPROVAL_HOURS, APPROVAL_MOST = 8.0, 24.0  # how long an approval lasts by default, and at most
RULE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\((.*)\))?$", re.S)
FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit", "Read")  # tools an approval names with a path pattern
BARE_TOOLS = ("Read", "Glob", "Grep", "WebSearch")  # the only tools an approval may name alone: they change nothing
DOMAIN = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")
JOINS = re.compile(r"[;&|<>`\n\r]|\$\(")  # a command with any of these is never matched by an approval
NOTE = f"{cli.NAME}-decision"


def me() -> str:
    return os.environ.get(cli.SESSION_ENV, "").lower()


def lead_only(command: str) -> None:
    """Only the lead talks with the person, so only the lead asks, records an answer or approves."""
    if me() != cli.LEAD:
        raise cli.ColonyError(f"{command} is for the lead: a helper sends its question to its lead on its card, "
                              f"`{cli.NAME} post <n> lead \"question: …? I'm going with <default>\"`")


def lead_of(config: dict, args=None) -> str:
    from colony import boot

    return boot.lead_of(config, args)


def person_of(config: dict, args=None) -> str:
    try:
        return cli.person_of(config, args or argparse.Namespace(person=None)).lower()
    except cli.ColonyError:
        return ""


def now_text(at: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if at is None else at, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# The ledger


def ledger_path(config: dict) -> Path:
    return wait.state_path(config["project"]["name"], "decisions")


def read_ledger(config: dict) -> dict:
    held = wait.read_json(ledger_path(config), {})
    held = held if isinstance(held, dict) else {}
    items = held.get("items")
    return {"next": int(held.get("next") or 1), "items": [i for i in items if isinstance(i, dict)]
            if isinstance(items, list) else []}


def change_ledger(config: dict, edit):
    """Read the ledger under its lock, let `edit` change it, write it back, and return what `edit` returned."""
    path = ledger_path(config)
    with profile.locked(path):
        held = read_ledger(config)
        result = edit(held)
        wait.write_json(path, held)
    return result


def record(config: dict, *, kind: str, question: str, default: str, status: str, lead: str, why: str = "",
           options=(), verdict: str = "", answer: str | None = None, person: str = "", issue: int | None = None,
           **more) -> dict:
    """Add one decision to the ledger, numbered D1 up on this computer, and return it."""
    def edit(held: dict) -> dict:
        item = {"id": f"D{held['next']}", "kind": kind, "question": question, "default": default, "why": why,
                "options": list(options), "status": status, "verdict": verdict, "lead": lead, "person": person,
                "at": time.time(), "issue": issue, **more}
        if answer is not None:
            item["answer"] = {"words": answer, "at": time.time(), "how": "said in chat"}
            item["yes"] = reads_yes(answer)
        held["next"] += 1
        held["items"].append(item)
        return item
    return change_ledger(config, edit)


def find(held: dict, ref: str) -> dict:
    ref = ref.strip().upper()
    ref = ref if ref.startswith("D") else f"D{ref}"
    found = next((item for item in held["items"] if item.get("id") == ref), None)
    if found is None:
        raise cli.ColonyError(f"there is no decision {ref}: `{cli.NAME} decisions --all` lists them")
    return found


def reads_yes(words: str) -> bool | None:
    """Whether the person's words say yes, no, or neither clearly (None)."""
    if YES.match(words or ""):
        return True
    if NO.match(words or ""):
        return False
    return None


def age(item: dict) -> str:
    return f"{cli.ago(max(0.0, time.time() - float(item.get('at') or 0)))} ago"


def pending_lines(config: dict) -> list[str]:
    """Each decision that waits on the person, oldest first, in one line."""
    try:
        items = read_ledger(config)["items"]
    except (OSError, ValueError, KeyError):
        return []
    return [f"{i['id']} {i['question']} (default: {i['default']}, asked {age(i)})" for i in items
            if i.get("status") == PENDING]


def recent_lines(config: dict, lead: str, hours: float = 24) -> list[str]:
    """The decisions `lead` took alone in the last `hours`, one line each."""
    try:
        items = read_ledger(config)["items"]
    except (OSError, ValueError, KeyError):
        return []
    since = time.time() - hours * 3600
    return [f"{i['id']} {i['question']}: {i['default']}" for i in items if i.get("lead") == lead
            and i.get("status") in (DECIDED, TOOK_DEFAULT) and float(i.get("at") or 0) >= since]


# What a lead does with a question


def policy(kind: str, autonomy: str) -> str:
    """Whether a lead holds that work for the answer, keeps going on its default while it waits, or decides alone
    and logs it, by the question's kind and the person's decisions.autonomy."""
    if kind in ("stop", "gate") or autonomy == "ask":
        return HOLD
    if kind == "routine":
        return DECIDE
    if autonomy == "unattended":
        return GO if kind == "scope" else DECIDE
    return GO


def words_of(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9'-]*", (text or "").lower()) if w not in STOPWORDS and len(w) > 2}


def similarity(a: str, b: str) -> float:
    one, two = words_of(a), words_of(b)
    return len(one & two) / max(1, min(len(one), len(two))) if one and two else 0.0


def never_raised(text: str, topics) -> str:
    """The topic on the don't-raise list a text is about, or ""."""
    lower = " ".join((text or "").lower().split())
    for topic in topics or []:
        words = words_of(topic)
        if topic.lower().strip() and (topic.lower().strip() in lower or (words and words <= words_of(text))):
            return topic
    return ""


def earlier(config: dict, question: str) -> dict | None:
    """An earlier decision on this computer that asked the same question and has its answer."""
    done = [i for i in read_ledger(config)["items"] if i.get("status") in (ANSWERED, DECIDED, TOOK_DEFAULT)]
    scored = sorted(((similarity(question, i.get("question", "")), i) for i in done), key=lambda pair: pair[0])
    return scored[-1][1] if scored and scored[-1][0] >= SIMILAR else None


def keywords(text: str) -> list[str]:
    """Up to four of a text's longest words, to search the team's issues and pull requests with."""
    words = sorted(words_of(text), key=lambda w: (-len(w), w))
    return [w for w in words if len(w) >= 4][:4]


def teammates(config: dict, question: str, lead: str) -> list[str]:
    """What the team already has on a question, one line each: open issues and pull requests that match it, and
    each live lead whose folders it names. It never raises: GitHub that can't be read finds nothing."""
    from colony import presence

    found = []
    words = keywords(question)
    repo = config["project"].get("repo", "")
    if len(words) >= 2 and repo:
        try:
            listed = json.loads(wait.gh("search", "issues", " ".join(words), "--repo", repo, "--include-prs",
                                        "--state", "open", "--json", "number,title,isPullRequest,author,"
                                        "authorAssociation", "--limit", "10") or "[]")
        except (wait.GhError, OSError, ValueError):
            listed = []
        logins = frozenset(str(login).lower() for login in config.get("people", {}).get("logins", []))
        for issue in listed if isinstance(listed, list) else []:
            title = str(issue.get("title", ""))
            author = str((issue.get("author") or {}).get("login") or "").lower()
            team = author in logins if logins else issue.get("authorAssociation") in presence.TRUSTED
            if not team or title.startswith(("Needs ", wait.COORDINATION)):
                continue  # an outsider's issue never steers a lead
            kind = "pull request" if issue.get("isPullRequest") else "issue"
            found.append(f"#{issue.get('number')} {title} (open {kind}): read it first")
    try:
        alive, _, _ = presence.everyone(config)
    except (cli.ColonyError, OSError, ValueError, KeyError):
        alive = []
    lower = question.lower()
    for status in alive:
        if status.kind != "lead" or status.name == lead:
            continue
        named = [f for f in status.folders if len(f.strip("/")) >= 3 and f.strip("/").lower() in lower]
        if named:
            found.append(f"{status.name} leads {', '.join(named)}: ask it first, `{cli.NAME} say {status.name} "
                         "\"<your question>\"`")
    return found


def explanation(item: dict, lead: str) -> str:
    """A decision's full explanation, which goes with it on the Needs issue."""
    lines = [f"{item['id']}: {item['question']}", "",
             f"Kind: {item['kind']}, {KINDS.get(item['kind'], item['kind'])}.", "",
             f"Why it needs you: {item['why']}"]
    if item.get("options"):
        lines += ["", "The choices:", *(f"- {option}" for option in item["options"])]
    pick = f"The lead's pick: {item['default']}."
    pick += (" The lead holds that work until you answer." if item["verdict"] == HOLD else
             " The lead keeps working on it until you answer, and your answer wins.")
    lines += ["", pick, "", f"To answer, comment `for {lead}: {item['id']} <your answer>`, or tell {lead} in chat."]
    return "\n".join(lines)


def needs_issue(config: dict, person: str) -> int:
    from colony import cycle, tidy

    body = (f"The decisions only {cycle.person_title(person)} makes, one line each with the lead's pick and its full "
            "explanation attached. The lead keeps working on the pick unless the line says it holds. Answer with a "
            "comment `for <the lead's name>: <the decision's id> <your answer>`, and your answer wins.")
    return tidy.keep_short(config, cycle.find_issue(config["project"]["repo"], cycle.needs_title(person), body))


def comment(config: dict, number: int, body: str) -> None:
    from colony import transport

    if found := transport.holds_secret(body) or profile.looks_secret(body):
        raise cli.ColonyError(f"the decision holds what looks like {found}, and a decision never carries a secret")
    wait.gh("issue", "comment", str(number), "--repo", config["project"]["repo"], "--body", body)


def post_question(config: dict, item: dict, person: str, lead: str) -> int:
    """Post a decision on the person's Needs issue: its line, with the full explanation attached."""
    from colony import cycle, transport

    line = cycle.needs_line(lead, person, f"{item['id']}: {item['question']}", item["default"], lead)
    number = needs_issue(config, person)
    note = f"<!-- {NOTE} {json.dumps({'id': item['id'], 'status': PENDING})} -->"
    comment(config, number, f"{line}\n{transport.attachment(item['id'] + ' explained', explanation(item, lead))}\n"
                            f"{note}")
    return number


def post_record(config: dict, item: dict, sentence: str, full: str = "") -> None:
    """Post one record line for a decision on the Needs issue it was asked on, signed by the lead, so it wakes no
    one; `full` is attached when the line had to cut it. It never stops the command."""
    from colony import transport

    lead = item.get("lead") or cli.LEAD
    person = item.get("person") or ""
    if not person:
        return
    room = wait.MAX_LINE - len(f"for {lead}:  (from {lead})") - 1
    text = sentence if len(sentence) <= room else sentence[:room - 4] + "...\""
    note = f"<!-- {NOTE} {json.dumps({'id': item['id'], 'status': item['status']})} -->"
    body = f"for {lead}: {text} (from {lead})"
    if full and text != sentence:
        body += "\n" + transport.attachment(f"{item['id']} in full", full)
    try:
        comment(config, item.get("issue") or needs_issue(config, person), f"{body}\n{note}")
    except (wait.GhError, OSError, ValueError) as e:
        print(f"{cli.NAME}: the record was not posted on the Needs issue: {e}", file=sys.stderr)


def ask_cmd(config: dict, args) -> int:
    """`colony ask "<question>" --default "<pick>" --kind <kind> --why "<why it needs the person>" [--option …]
    [--checked]`: the one way a lead asks the person (see the module's docstring). It ends with 1 when it stopped to
    let the lead read the team's work first, else 0."""
    lead_only("ask")
    question, default = " ".join(args.question.split()), " ".join(args.default.split())
    if not question or not default:
        raise cli.ColonyError("ask takes a question and its --default, your pick")
    merged = profile.load(config=config)
    lead, person = lead_of(config, args), (args.needs_person or person_of(config, args))
    why = " ".join((args.why or "").split())
    if args.why_file:
        why = Path(args.why_file).read_text(encoding="utf-8").strip()
    topic = never_raised(f"{question} {why}", merged.value("decisions.never_raise", []))
    if topic:
        item = record(config, kind=args.kind, question=question, default=default, status=DECIDED, lead=lead,
                      person=person, why=why, verdict=NOT_RAISED, topic=topic)
        if args.kind in ("stop", "gate"):
            print(f"Not raised: \"{topic}\" is on the person's don't-raise list, and this needs their yes, so it is "
                  f"not done either: it waits until they raise it ({item['id']}, logged).")
        else:
            print(f"Not raised: \"{topic}\" is on the person's don't-raise list. Decide it yourself: go with "
                  f"{default} ({item['id']}, logged).")
        return 0
    verdict = policy(args.kind, merged.value("decisions.autonomy", "routine"))
    if verdict == DECIDE:
        item = record(config, kind=args.kind, question=question, default=default, status=DECIDED, lead=lead,
                      person=person, why=why, options=args.option or [], verdict=DECIDE)
        print(f"Decided alone, not asked: a {args.kind} question under decisions.autonomy "
              f"{merged.value('decisions.autonomy', 'routine')}. Go with {default} ({item['id']}, logged; "
              f"`{cli.NAME} decisions --log` lists them).")
        return 0
    if not args.checked:
        found = earlier(config, question)
        if found:
            said = (found.get("answer") or {}).get("words") or found.get("default")
            print(f"Not asked: {found['id']} asked the same, {age(found)}, and its answer is: \"{said}\". Follow it, "
                  f"or ask again with --checked when this differs.")
            return 1
        seen = teammates(config, question, lead)
        if seen:
            print("Not asked yet: the team may have this already. Read these first:")
            print("\n".join(f"- {line}" for line in seen))
            print(f"When they don't answer it, run the same `{cli.NAME} ask` again with --checked.")
            return 1
    if not why:
        raise cli.ColonyError("explain it in full: --why \"<what it is about, what each choice means, and why your "
                              "pick>\", or --why-file <file>")
    item = record(config, kind=args.kind, question=question, default=default, status=PENDING, lead=lead,
                  person=person, why=why, options=args.option or [], verdict=verdict)
    try:
        number = post_question(config, item, person, lead)
    except cli.ColonyError:
        change_ledger(config, lambda held: held["items"].remove(find(held, item["id"])))
        raise
    change_ledger(config, lambda held: find(held, item["id"]).update(issue=number))
    if verdict == HOLD:
        print(f"Asked as {item['id']} on #{number}: hold that work until the person answers, and go on with other "
              "work.")
    else:
        wait_minutes = merged.value("decisions.answer_wait_minutes", 30)
        after = ("take your pick for good and log it" if merged.value("decisions.without_answer", "hold") == "default"
                 else "hold that work")
        print(f"Asked as {item['id']} on #{number}: keep working on {default}; the answer wins. With no answer in "
              f"{wait_minutes} minutes, {after}.")
    from colony import plain

    plain.warn(config, " ".join([question, why, *(args.option or []), f"My pick is {default}."]))  # never stops it
    return 0


def decisions_cmd(config: dict, args) -> int:
    """`colony decisions [--log | --all] [--json]`: the decisions that wait on the person, each with its age and what
    to do when it is past its wait; --log those taken alone; --all every one."""
    items = read_ledger(config)["items"]
    if args.log:
        shown = [i for i in items if i.get("status") in (DECIDED, TOOK_DEFAULT)]
    elif args.all:
        shown = items
    else:
        shown = [i for i in items if i.get("status") == PENDING]
    if args.json:
        print(json.dumps(shown, ensure_ascii=False))
        return 0
    if not shown:
        print("Nothing waits on the person." if not (args.log or args.all) else "No decisions yet.")
        return 0
    merged = profile.load(config=config)
    limit = merged.value("decisions.answer_wait_minutes", 30) * 60
    takes = merged.value("decisions.without_answer", "hold") == "default"
    for item in shown:
        status = item.get("status")
        line = f"{item['id']} ({item['kind']}, {status}, {age(item)}): {item['question']} Pick: {item['default']}."
        if status == PENDING and time.time() - float(item.get("at") or 0) > limit:
            line += (f" Past its wait: take the pick, `{cli.NAME} answer {item['id']} --took-default`."
                     if takes and item.get("verdict") == GO else " Past its wait: hold that work, and go on with "
                                                                    "other work.")
        if item.get("answer"):
            line += f" Answer ({item['answer'].get('how', '')}): \"{item['answer']['words']}\""
        print(line)
    return 0


def answer_cmd(config: dict, args) -> int:
    """`colony answer <id> "<the person's words>" | --took-default | --withdraw`: record the person's answer exactly
    as they said it, or that no answer came in time and the pick stands, or take the question back."""
    lead_only("answer")
    chosen = [bool(args.words), args.took_default, args.withdraw]
    if sum(chosen) != 1:
        raise cli.ColonyError("give the person's words, in quotes, or --took-default, or --withdraw")
    merged = profile.load(config=config)
    minutes = merged.value("decisions.answer_wait_minutes", 30)

    def edit(held: dict) -> dict:
        item = find(held, args.id)
        if item.get("status") != PENDING:
            raise cli.ColonyError(f"{item['id']} is {item.get('status')}, so it waits on nobody")
        if args.words:
            item["status"] = ANSWERED
            item["answer"] = {"words": args.words, "at": time.time(),
                              "how": "on the Needs issue" if args.on_issue else "said in chat"}
            item["yes"] = reads_yes(args.words)
        elif args.took_default:
            if item.get("kind") in ("stop", "gate"):
                raise cli.ColonyError(f"{item['id']} needs the person's yes: a {item['kind']} question is never taken "
                                      "on its default")
            item["status"] = TOOK_DEFAULT
            item["answer"] = {"words": None, "at": time.time(), "how": f"no answer in {minutes} minutes"}
        else:
            item["status"] = WITHDRAWN
        return dict(item)

    item = change_ledger(config, edit)
    person = item.get("person") or ""
    if args.words:
        print(f"{item['id']} answered, recorded word for word: \"{args.words}\"")
        if item.get("kind") == "gate":
            print({True: "That is a yes: build it.", False: "That is a no: build nothing of it."}.get(
                item.get("yes"), "It reads as neither yes nor no: ask once more what they want, before building."))
        post_record(config, item, f"{cli_title(person)} answered {item['id']} ({item['answer']['how']}): "
                                  f"\"{args.words}\"", full=args.words)
    elif args.took_default:
        print(f"{item['id']}: no answer in {minutes} minutes, so the pick stands, {item['default']}, logged.")
        post_record(config, item, f"{item['id']}: no answer in {minutes} minutes, so the pick stands: "
                                  f"{item['default']}")
    else:
        print(f"{item['id']} taken back.")
        post_record(config, item, f"{item['id']} is taken back: it needs no answer")
    return 0


def cli_title(person: str) -> str:
    from colony import cycle

    return cycle.person_title(person) if person else "The person"


def approved(config: dict, ref: str) -> bool:
    """Whether decision `ref` holds the person's yes."""
    try:
        item = find(read_ledger(config), ref)
    except cli.ColonyError:
        return False
    return item.get("status") == ANSWERED and item.get("yes") is True


# Don't raise, and the budget


def never_raise_cmd(config: dict, args) -> int:
    """`colony never-raise ["<topic>"] [--remove] [--team]`: the topics never raised with the person: list them, add
    one, or take one off."""
    if not args.topic:
        merged = profile.load(config=config)
        topics = merged.value("decisions.never_raise", [])
        setting = merged.settings.get("decisions.never_raise")
        print(f"Never raised ({setting.source}): {', '.join(topics)}." if topics else "No topic is on the list.")
        return 0
    topic = " ".join(args.topic.split())
    if found := profile.looks_secret(topic):
        raise cli.ColonyError(f"the topic holds what looks like {found}, and a profile never holds a secret")
    target = argparse.Namespace(team=args.team, session=False, person=getattr(args, "person", None))

    def edit(data: dict, level: str) -> bool:
        held = data.get("decisions", {}).get("never_raise", []) if isinstance(data.get("decisions"), dict) else []
        held = [t for t in held if isinstance(t, str)]
        kept = [t for t in held if t.lower() != topic.lower()] if args.remove else \
            [*held, *([] if topic.lower() in (t.lower() for t in held) else [topic])]
        if kept:
            profile.set_value(data, "decisions.never_raise", kept)
        else:
            profile.drop_value(data, "decisions.never_raise")
        return kept != held

    path, level, changed = profile.change(target, edit)
    what = ("taken off" if args.remove else "added") if changed else ("was not on the list" if args.remove
                                                                       else "was on the list already")
    print(f"\"{topic}\" {what}: {profile.written(path, level)}")
    return 0


def spend_path(config: dict) -> Path:
    return wait.state_path(config["project"]["name"], "spend")


def spend_cmd(config: dict, args) -> int:
    """`colony spend <dollars> "<what>" [--approved <id>]`: check a spend against today's budget,
    budgets.dollars_per_day, and record it. Past the budget it ends with 1 and records nothing, unless the person
    said yes to it in a decision."""
    if args.dollars <= 0:
        raise cli.ColonyError("spend takes the dollars it costs, more than 0")
    what = " ".join(args.what.split())
    merged = profile.load(config=config)
    budget = float(merged.value("budgets.dollars_per_day", 0) or 0)
    today = date.today().isoformat()
    path = spend_path(config)
    with profile.locked(path):
        held = wait.read_json(path, {})
        held = {today: held.get(today, [])} if isinstance(held, dict) else {today: []}
        spent = sum(float(item.get("dollars", 0)) for item in held[today] if isinstance(item, dict))
        if spent + args.dollars > budget:
            if not args.approved or not approved(config, args.approved):
                ask = (f"`{cli.NAME} ask \"spend ${args.dollars:g} on {what}?\" --default \"no\" --kind stop --why "
                       "\"<what it buys and why>\"`")
                print(f"Over today's budget: ${spent:g} of ${budget:g} spent, and this is ${args.dollars:g}. Ask the "
                      f"person first, {ask}, then run this again with --approved <its id> on their yes.")
                return 1
        held[today].append({"dollars": args.dollars, "what": what, "by": me() or "", "at": time.time(),
                            **({"approved": args.approved.upper()} if args.approved else {})})
        wait.write_json(path, held)
    print(f"Recorded ${args.dollars:g} for {what}: ${spent + args.dollars:g} of ${budget:g} spent today"
          + (f", past the budget on the person's yes ({args.approved.upper()})." if spent + args.dollars > budget
             else "."))
    return 0


# Approvals that reach helpers


def approvals_path(config: dict) -> Path:
    return wait.state_path(config["project"]["name"], "approvals")


def live_marker(config: dict) -> Path:
    """A file that exists while one of this project's approvals is live, ~/.colony/<project>/approvals.live, so the
    tool hook costs nothing while no project has one (boot.APPROVALS_LIVE). Each project keeps its own: one with no
    live approval never touches another's."""
    return approvals_path(config).with_name("approvals.live")


def read_approvals(config: dict) -> list[dict]:
    held = wait.read_json(approvals_path(config), [])
    return [item for item in held if isinstance(item, dict)] if isinstance(held, list) else []


def write_approvals(config: dict, items: list[dict]) -> None:
    path = approvals_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{os.getpid()}")
    with os.fdopen(os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as handle:
        json.dump(items, handle, ensure_ascii=False)
    os.replace(part, path)
    mark(config, any(is_live(item) for item in items))


def mark(config: dict, live: bool) -> None:
    marker = live_marker(config)
    if live:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    else:
        marker.unlink(missing_ok=True)


def is_live(item: dict, now: float | None = None) -> bool:
    return not item.get("revoked") and float(item.get("until") or 0) > (time.time() if now is None else now)


def applies(item: dict, session: str, person: str, lead: str) -> bool:
    """Whether an approval covers a session: it is live, it is its person's own, and it names that session's lead, or
    none, and that session, or every one."""
    if not is_live(item) or not all(valid_rule(rule) for rule in item.get("rules") or [None]):
        return False
    if str(item.get("person") or "").lower() != (person or "").lower():
        return False
    if item.get("lead") and item["lead"] != lead:
        return False
    only = item.get("only") or []
    return not only or session in only


def live_approvals(config: dict, person: str, lead: str = "") -> list[dict]:
    """The approvals in force for the person's sessions on this computer, or with `lead`, for that lead's."""
    return [item for item in read_approvals(config) if is_live(item) and str(item.get("person") or "").lower() ==
            (person or "").lower() and (not lead or not item.get("lead") or item["lead"] == lead)]


def approval_lines(items: list[dict]) -> list[str]:
    """Each approval as one line: its rules, for whom, and until when."""
    lines = []
    for item in items:
        who = [f"{item['lead']}'s sessions"] if item.get("lead") else []
        who += [f"only {', '.join(item['only'])}"] if item.get("only") else []
        lines.append(f"{item['id']}: {', '.join(item['rules'])}" + (f" ({'; '.join(who)})" if who else "")
                     + f", until {now_text(item['until'])}")
    return lines


def check_rule(rule: str) -> str:
    """A Claude Code permission rule an approval may hold, checked: `Bash(<command>)` or `Bash(<command>:*)`, which
    names its command; `WebFetch(domain:<domain>)`; a file tool with a relative path pattern, such as
    `Edit(docs/**)`; or one of BARE_TOOLS alone. Anything wider, such as a tool with no argument, is refused."""
    rule = str(rule).strip()
    found = RULE.match(rule)
    if not found:
        raise cli.ColonyError(f"{rule!r} is not a permission rule, such as Bash(npm run migrate:*) or "
                              "WebFetch(domain:example.com)")
    tool, arg = found[1], found[2]
    if arg is None:
        if tool not in BARE_TOOLS:
            raise cli.ColonyError(f"{tool} alone would allow every call of it: name its command, domain or path, "
                                  f"such as Bash(npm run migrate:*); only {', '.join(BARE_TOOLS)} may stand alone")
        return rule
    if tool == "Bash":
        command = arg.removesuffix(":*").strip()
        if not command or "*" in command or JOINS.search(command):
            raise cli.ColonyError("a Bash approval names one command, such as Bash(npm run migrate:*): never every "
                                  "command, a wildcard, or commands joined together")
    elif tool == "WebFetch":
        if not arg.startswith("domain:") or not DOMAIN.fullmatch(arg[len("domain:"):].lower()):
            raise cli.ColonyError("a WebFetch approval names one domain, such as WebFetch(domain:example.com)")
    elif tool in FILE_TOOLS:
        parts = PurePosixPath(arg).parts
        if not arg.strip() or "\\" in arg or arg.startswith(("/", "~")) or ".." in parts or not parts:
            raise cli.ColonyError(f"a {tool} approval names a path pattern inside the repo, such as {tool}(docs/**): "
                                  "never an absolute path, ~ or ..")
    else:
        raise cli.ColonyError(f"an approval covers Bash, WebFetch and the file tools ({', '.join(FILE_TOOLS)}), "
                              f"each with its argument, or {', '.join(BARE_TOOLS)} alone; not {tool}")
    return rule


def valid_rule(rule) -> bool:
    try:
        check_rule(rule)
    except cli.ColonyError:
        return False
    return True


def segments_match(pattern: tuple, parts: tuple) -> bool:
    """Whether a path's segments match a pattern's: each `*` stays inside one segment, and `**` stands for any number
    of whole segments."""
    if not pattern:
        return not parts
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        return any(segments_match(rest, parts[i:]) for i in range(len(parts) + 1))
    return bool(parts) and fnmatch.fnmatchcase(parts[0], head) and segments_match(rest, parts[1:])


def path_matches(pattern: str, path: str, cwd: str) -> bool:
    """Whether a file tool's path matches an approval's pattern: the path, resolved against the session's folder with
    its links followed, must stay inside that folder and hold no `..`, and its segments must match the pattern's."""
    if not cwd or not path or ".." in PurePath(path).parts:
        return False
    root = os.path.realpath(cwd)
    full = os.path.realpath(os.path.join(root, path))
    try:
        if os.path.commonpath([root, full]) != root or full == root:
            return False
    except ValueError:  # another drive, on Windows
        return False
    return segments_match(PurePosixPath(arg_path(pattern)).parts, PurePath(os.path.relpath(full, root)).parts)


def arg_path(pattern: str) -> str:
    return pattern.strip().removeprefix("./")


def matches(rule: str, tool: str, given: dict, cwd: str = "") -> bool:
    """Whether a tool call matches an approval's rule, which must pass check_rule: a Bash command exactly, or by its
    start with `:*`, and only a single command, never one joined to others; a web fetch by its domain; a file tool by
    its path (path_matches); a tool of BARE_TOOLS by its name."""
    if not valid_rule(rule):
        return False
    found = RULE.match(rule.strip())
    if found[1] != tool:
        return False
    arg = found[2]
    if arg is None:
        return tool in BARE_TOOLS
    if tool == "Bash":
        command = " ".join(str(given.get("command", "")).split())
        if not command or JOINS.search(str(given.get("command", ""))):
            return False
        if arg.endswith(":*"):
            start = " ".join(arg[:-2].split())
            return command == start or command.startswith(start + " ")
        return command == " ".join(arg.split())
    if tool == "WebFetch":
        host = (urlparse(str(given.get("url", ""))).hostname or "").lower()
        domain = arg[len("domain:"):].lower()
        return bool(host) and (host == domain or host.endswith("." + domain))
    path = str(given.get("file_path") or given.get("notebook_path") or given.get("path") or "")
    return path_matches(arg, path, cwd)


def tool_decision(config: dict, session: str, payload: dict) -> dict | None:
    """The PreToolUse hook's answer: allow a call that an approval the person made at their own terminal covers for
    this session, with the approval named, or None to leave it to the usual checks."""
    lead = os.environ.get(wait.LEAD_ENV, "").lower() or lead_of(config)
    person = os.environ.get(cli.PERSON_ENV, "").lower() or person_of(config)
    tool, given = str(payload.get("tool_name") or ""), payload.get("tool_input") or {}
    if not isinstance(given, dict):
        return None
    items = read_approvals(config)
    if not any(is_live(item) for item in items):
        mark(config, False)
        return None
    for item in items:
        if not applies(item, session, person, lead):
            continue
        for rule in item["rules"]:
            if matches(rule, tool, given, str(payload.get("cwd") or "")):
                return {"hookSpecificOutput": {
                    "hookEventName": "PreToolUse", "permissionDecision": "allow",
                    "permissionDecisionReason": f"{cli_title(person)} approved this at their own terminal "
                                                f"({item['id']}, {rule})."}}
    return None


# Approvals the person gives at their own terminal


AGENT_ENV = ("CLAUDECODE", cli.SESSION_ENV, cli.CLAUDE_SESSION_ENV)  # what an agent's command carries


def at_own_terminal() -> bool:
    """Whether this command runs at the person's own terminal: its input and output are a terminal, and nothing in its
    environment says an agent's session runs it."""
    from colony import portable

    if any(os.environ.get(name) for name in AGENT_ENV):
        return False
    return portable.is_terminal(sys.stdin) and portable.is_terminal(sys.stdout)


def approve_cmd(config: dict, args) -> int:
    """`colony approve "<rule>" … [--for <hours>] [--only <session> …] [--lead <lead>]`, `colony approve --list`,
    `colony approve --revoke <id>`: the person, at their own terminal, lets the permission checks of their leads and
    helpers on this computer through a call each rule covers, until it expires. An agent can list approvals, and
    never make or revoke one."""
    person = person_of(config, args)
    if args.list:
        items = live_approvals(config, person)
        print("\n".join(approval_lines(items)) or "No approval is in force.")
        return 0
    if not at_own_terminal():
        raise cli.ColonyError("an approval is given by the person, at their own terminal: run `colony approve` there "
                              "yourself. An agent's session can't make or revoke one")
    if not person:
        raise cli.ColonyError("say whose approval this is: --person <you>")
    items = read_approvals(config)
    if args.revoke:
        ref = args.revoke.strip().upper()
        hit = [item for item in items if item.get("id") == ref and str(item.get("person")).lower() == person]
        if not hit:
            raise cli.ColonyError(f"there is no approval {ref} of yours: `{cli.NAME} approve --list` lists them")
        for item in hit:
            item["revoked"] = time.time()
        write_approvals(config, items)
        print(f"{ref} revoked: it lets nothing through from now on.")
        return 0
    rules = [check_rule(rule) for rule in args.rules]
    hours = args.hours if args.hours is not None else APPROVAL_HOURS
    if not 0 < hours <= APPROVAL_MOST:
        raise cli.ColonyError(f"an approval lasts more than 0 and at most {APPROVAL_MOST:g} hours")
    only = list(dict.fromkeys(name.lower() for name in args.only or []))
    if not all(cli.SESSION_NAME.fullmatch(name) for name in only):
        raise cli.ColonyError("--only names a session, such as builder-2 or lead")
    lead = (args.lead or "").lower()
    whom = (f"{lead} and its helpers" if lead else f"every lead and helper of {person}'s here") + \
        (f", only {', '.join(only)}" if only else "")
    print(f"This lets {whom} run, without a permission question, for {hours:g} hours:")
    print("\n".join(f"  {rule}" for rule in rules))
    if input("Type yes to approve: ").strip().lower() != "yes":
        print("Not approved: nothing changed.")
        return 1
    number = 1 + max([int(i["id"][1:]) for i in items if re.fullmatch(r"A\d+", str(i.get("id")))] + [0])
    item = {"id": f"A{number}", "rules": rules, "person": person, "lead": lead, "only": only, "at": time.time(),
            "until": time.time() + hours * 3600}
    write_approvals(config, [*items, item])
    print(f"Approved {approval_lines([item])[0]}. `{cli.NAME} approve --revoke {item['id']}` ends it.")
    return 0


def register(sub) -> None:
    """cli.py's route to this module: ask, decisions, answer, never-raise, spend and allow."""
    p = sub.add_parser("ask", help="the lead asks the person a real decision, with its full explanation; routine "
                                   "ones are decided and logged")
    p.add_argument("question", help="the question, in quotes")
    p.add_argument("--default", required=True, help="your pick, which the lead works on or takes")
    p.add_argument("--kind", required=True, choices=tuple(KINDS), help="scope, product, stop, gate or routine")
    p.add_argument("--why", help="what it is about, what each choice means, and why your pick")
    p.add_argument("--why-file", metavar="FILE", help="the explanation, from a file")
    p.add_argument("--option", action="append", metavar="CHOICE", help="one choice and what it means; repeat it")
    p.add_argument("--checked", action="store_true", help="you read the team's work it found, and it doesn't answer")
    p.add_argument("--person", dest="needs_person", help="whose decision it is, when not this session's person")
    p.set_defaults(run=ask_cmd, person=None)
    p = sub.add_parser("decisions", help="the decisions that wait on the person, in one place")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--log", action="store_true", help="the decisions taken alone")
    group.add_argument("--all", action="store_true", help="every decision")
    p.add_argument("--json", action="store_true", help="print them as JSON")
    p.set_defaults(run=decisions_cmd)
    p = sub.add_parser("answer", help="record the person's answer to a decision, word for word")
    p.add_argument("id", help="the decision, such as D4")
    p.add_argument("words", nargs="?", help="the person's words, exactly as they said them")
    p.add_argument("--on-issue", action="store_true", help="they answered on the Needs issue, not in chat")
    p.add_argument("--took-default", action="store_true", help="no answer came in time, so the pick stands")
    p.add_argument("--withdraw", action="store_true", help="the question needs no answer any more")
    p.set_defaults(run=answer_cmd)
    p = sub.add_parser("never-raise", help="the topics never raised with the person: list, add or take one off")
    p.add_argument("topic", nargs="?", help="the topic, in quotes")
    p.add_argument("--remove", action="store_true", help="take it off the list")
    p.add_argument("--team", action="store_true", help="the team profile's list, through a reviewed pull request")
    p.add_argument("--person", help="whose profile, when $COLONY_PERSON is not set")
    p.set_defaults(run=never_raise_cmd)
    p = sub.add_parser("spend", help="check a spend against today's budget, and record it")
    p.add_argument("dollars", type=float, help="what it costs, in dollars")
    p.add_argument("what", help="what it buys, in quotes")
    p.add_argument("--approved", metavar="ID", help="the decision in which the person said yes to it")
    p.set_defaults(run=spend_cmd)
    p = sub.add_parser("approve", help="the person, at their own terminal: let their sessions here run what a "
                                       "permission rule covers, until it expires")
    p.add_argument("rules", nargs="*", metavar="rule", help="a Claude Code permission rule, such as "
                                                            "Bash(npm run migrate:*)")
    p.add_argument("--for", dest="hours", type=float, metavar="HOURS",
                   help=f"how long it lasts, {APPROVAL_HOURS:g} hours by default, at most {APPROVAL_MOST:g}")
    p.add_argument("--only", action="append", metavar="SESSION", help="only this session, such as builder-2; repeat")
    p.add_argument("--lead", help="only this lead and its helpers, such as ana-main-lead")
    p.add_argument("--list", action="store_true", help="the approvals in force")
    p.add_argument("--revoke", metavar="ID", help="end one at once, such as A2")
    p.add_argument("--person", help="whose approval, when $COLONY_PERSON is not set")
    p.set_defaults(run=approve_cmd)
