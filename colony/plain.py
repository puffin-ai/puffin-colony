"""colony plain: status messages to the person in plain words, with no internal shorthand.

The person reads a lead's status between other work, and internal shorthand, such as a task code, an arrow or a
chat abbreviation, makes them stop and ask. Two things help:

- Templates (TEMPLATES): a short message for each common status, such as work done, a blocked step, a choice, a
  release or a failing branch, written in everyday words. `colony plain templates` prints them, and `colony plain
  fill <name> key=value …` fills one in and checks it.
- A check (findings): `colony plain check "<message>"` names each thing a person may not understand, with how to
  say it instead: an arrow, a chat abbreviation, an internal code such as TD236, a short form in capitals that the
  message never spells out, a commit id, a helper's name, one of Colony's own words such as worktree, and a
  sentence over MAX_WORDS words. Links and text in backticks, such as a command to run, are left alone. `[plain]
  allow` lets the project's own names through, and `[plain] jargon` adds the team's own shorthand. It exits 1 when
  it finds something.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple

from colony import cli

MAX_WORDS = 30  # a sentence longer than this is split
URL = re.compile(r"https?://\S+")
CODE_SPAN = re.compile(r"`[^`]*`")
ARROW = re.compile(r"→|⇒|⟶|->|=>")
SHORTHAND = ("w/", "w/o", "b/c", "thx", "fyi", "tbd", "wip", "lgtm", "ptal", "afaik", "imo", "iirc", "eta", "aka",
             "approx", "pls", "plz", "tldr", "tl;dr", "atm", "rn", "nvm")
# An internal code starts with a capital: two to four letters and a number, such as TD236 or WS-12, or one letter and
# two digits or more, such as T52. A version such as v2, or a seat such as B2, is not one.
CODE = re.compile(r"(?<![\w/.-])([A-Z][A-Za-z]{1,3}-?\d{1,5}[a-z]?|[A-Z]-?\d{2,5}[a-z]?)(?![\w/-])")
ACRONYM = re.compile(r"(?<![\w/.-])([A-Z][A-Z]{1,5})(s?)(?![\w/-])")
COMMIT = re.compile(r"(?<![\w/.-])([0-9a-f]{7,40})(?![\w/-])")
HELPER = re.compile(r"\b((?:builder|helper|fixer|reviewer|walker|tester)-\d+)\b", re.I)
INTERNAL = ("worktree", "worktrees", "ledger", "refspec", "first-parent", "fast-forward", "HEAD", "sha", "SHA",
            "TINY", "SMALL", "FEATURE")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
ALLOW = {word.lower() for word in (
    "PR", "CI", "API", "URL", "UI", "UX", "OK", "ID", "AI", "CPU", "GPU", "RAM", "PDF", "CSV", "JSON", "HTML", "CSS",
    "SQL", "HTTP", "HTTPS", "DNS", "SSH", "USB", "FAQ", "UTC", "GMT", "AM", "PM", "US", "UK", "EU", "GB", "MB", "KB",
    "TB", "OS", "VPN", "SMS", "QA", "TV", "IT", "README", "CLI", "AWS", "GCP", "CEO", "CTO", "CFO", "HR", "PS", "S3",
    "EC2", "IPv4", "IPv6", "UTF8", "utf-8", "MP3", "MP4", "H1", "H2", "H3", "x86", "arm64", "Q1", "Q2", "Q3", "Q4", "2FA")}


class Finding(NamedTuple):
    """One thing a person may not understand: the words, what kind of thing they are, and how to say it instead."""
    words: str
    kind: str
    advice: str


# The templates: each status a lead sends often, in everyday words. Each {name} is filled in by the lead.
TEMPLATES = {
    "status": "{done}. Next, {next}. Needs you: {needs}.",
    "done": "{change} is finished, and its checks passed. Next, {next}.",
    "blocked": "{work} has stopped, because {reason}. To go on, {who} needs to {action}. Meanwhile, I am working on "
               "{meanwhile}.",
    "decision": "I need your choice on {topic}. You can {option_a}, or {option_b}. I recommend {pick}, because {why}. "
                "Until you answer, I am going with {pick}.",
    "release": "The release is ready for you to read and merge: {link}. It carries {count}. {migrations} {tests} Its "
               "checks {checks}.",
    "red": "The shared branch {branch} has failed its checks since {since}. The likely cause is {cause}, and {lead} is "
           "fixing it. New work waits until the branch passes again.",
    "person_step": "One step needs you, {who}: {what}. It was {tested}. The details are here: {link}. Tell me when it "
                   "is done.",
}


class _Blank(dict):
    def __missing__(self, key: str) -> str:
        return f"<{key}>"


def fill(name: str, **values: str) -> str:
    """A template with its blanks filled in; a blank given no value stays as <name>."""
    if name not in TEMPLATES:
        raise cli.ColonyError(f"no status template {name!r}: the templates are {', '.join(TEMPLATES)}")
    return TEMPLATES[name].format_map(_Blank({key: str(value).strip() for key, value in values.items()}))


def settings(config: dict | None) -> dict:
    """`[plain]`: the words the check lets through, and the team's own shorthand it flags."""
    table = (config or {}).get("plain") or {}
    allow, jargon = table.get("allow") or [], table.get("jargon") or []
    for key, value in (("allow", allow), ("jargon", jargon)):
        if not isinstance(value, list) or not all(isinstance(word, str) for word in value):
            raise cli.ColonyError(f"[plain] {key} is a list of words, such as [\"Puffin\"]")
    return {"allow": {word.lower() for word in allow}, "jargon": list(jargon)}


def visible(text: str) -> str:
    """The words a person reads as words: the message without its links and its text in backticks."""
    return CODE_SPAN.sub(" ", URL.sub(" ", text))


def explained(text: str, short: str) -> bool:
    """Whether the message spells a short form out: it stands in brackets after the words, or brackets follow it."""
    return f"({short})" in text or re.search(rf"\b{re.escape(short)}\s*\(", text) is not None


def findings(text: str, config: dict | None = None) -> list[Finding]:
    """Each thing in a message a person may not understand, once each, in the order the rules run."""
    s = settings(config)
    allow = ALLOW | s["allow"]
    seen: set[str] = set()
    found: list[Finding] = []

    def add(words: str, kind: str, advice: str) -> None:
        if words.lower() not in seen:
            seen.add(words.lower())
            found.append(Finding(words, kind, advice))

    words = visible(text)
    for arrow in ARROW.findall(words):
        add(arrow, "an arrow", "Write a sentence instead, such as \"which leads to\" or \"then\".")
    for word in SHORTHAND:
        if re.search(rf"(?<![\w/]){re.escape(word)}(?![\w/])", words, re.I):
            add(word, "a chat abbreviation", "Write it out in full words.")
    for word in [*INTERNAL, *s["jargon"]]:
        flags = 0 if word.isupper() else re.I
        if word.lower() not in s["allow"] and re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", words, flags):
            add(word, "an internal word", "Say what it means in everyday words.")
    for name in HELPER.findall(words):
        add(name, "a helper's name", "Say what the work was, not which helper did it.")
    for sha in COMMIT.findall(words):
        if re.search(r"\d", sha) and re.search(r"[a-f]", sha):
            add(sha, "a commit id", "Say what changed instead; put the link after it if they need one.")
    for code in CODE.findall(words):
        if code.lower() not in allow and code.lower() not in seen:
            add(code, "an internal code", "Say what it is in words, such as the task's name.")
    for short, plural in ACRONYM.findall(words):
        if short.lower() in allow or short.lower() in seen or short in INTERNAL or explained(text, short):
            continue
        add(short + plural, "a short form", f"Spell {short} out the first time, with the short form in brackets "
                                            "after it.")
    for sentence in SENTENCE.split(" ".join(words.split())):
        count = len(sentence.split())
        if count > MAX_WORDS:
            add(sentence[:40] + "…", "a long sentence", f"It has {count} words: split it into two.")
    return found


def report(found: list[Finding]) -> str:
    """The findings as the person's lead reads them."""
    if not found:
        return "plain: it reads plainly."
    lines = [f"plain: {len(found)} thing{'' if len(found) == 1 else 's'} to fix before this reaches the person:"]
    return "\n".join(lines + [f"- \"{f.words}\": {f.kind}. {f.advice}" for f in found])


def warning(found: list[Finding]) -> str:
    """The findings as a warning beside a message that already went to the person."""
    head = (f"Warning: the person may not understand {len(found)} thing{'' if len(found) == 1 else 's'} in this "
            f"message, which went out anyway. Write the next one plainly (`{cli.NAME} plain check` reads a draft):")
    return "\n".join([head] + [f"- \"{f.words}\": {f.kind}. {f.advice}" for f in found])


def warn(config: dict | None, text: str) -> list[Finding]:
    """Check a message that reaches the person, from `colony ask`, `colony needs`, or a post or say to @login, and
    print a warning beside it for each finding (warning). It never stops the message: its callers run it after the
    message went out, and a check that fails prints nothing, so a false alarm never stops work."""
    try:
        found = findings(text, config)
    except (cli.ColonyError, ValueError, TypeError, re.error):
        return []
    if found:
        print(warning(found))
    return found


def run(config: dict, args) -> int:
    """`colony plain check|templates|fill`."""
    if args.action == "templates":
        names = [args.name] if args.name else list(TEMPLATES)
        for name in names:
            if name not in TEMPLATES:
                raise cli.ColonyError(f"no status template {name!r}: the templates are {', '.join(TEMPLATES)}")
            print(f"{name}: {TEMPLATES[name]}")
        return 0
    if args.action == "fill":
        values = {}
        for pair in args.values:
            key, sep, value = pair.partition("=")
            if not sep or not key:
                raise cli.ColonyError(f"give each blank as name=value, such as next=\"the release\", not {pair!r}")
            values[key] = value
        text = fill(args.name, **values)
        print(text)
        found = findings(text, config)
        if found:
            print(report(found), file=sys.stderr)
        return 1 if found else 0
    if args.file:
        try:
            text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        except OSError as e:
            raise cli.ColonyError(f"the message could not be read from {args.file}: {e.strerror or e}") from None
    else:
        text = " ".join(args.text)
    if not text.strip():
        raise cli.ColonyError("give the message to check, in quotes, or --file <path>")
    found = findings(text, config)
    print(report(found))
    return 1 if found else 0


def register(sub) -> None:
    """The `plain` command and its actions."""
    p = sub.add_parser("plain", help="check a message to the person for internal shorthand, or print the plain "
                                     "status templates")
    actions = p.add_subparsers(dest="action", metavar="action", required=True)
    a = actions.add_parser("check", help="name each thing in a message a person may not understand, with how to say "
                                         "it instead; exit 1 when there is one")
    a.add_argument("text", nargs="*", help="the message, in quotes")
    a.add_argument("--file", help="read the message from this file, or - for standard input")
    a.set_defaults(run=run, action="check")
    a = actions.add_parser("templates", help="print the status templates, or one by name")
    a.add_argument("name", nargs="?", help="one template, such as blocked")
    a.set_defaults(run=run, action="templates")
    a = actions.add_parser("fill", help="fill a template in, print it, and check it")
    a.add_argument("name", help="the template, such as blocked")
    a.add_argument("values", nargs="*", metavar="name=value", help="each blank's words")
    a.set_defaults(run=run, action="fill")
