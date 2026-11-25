"""Helper chatter: what the lead's wait folds, so real results and questions reach the lead and chatter doesn't.

A helper that has nothing to do, or a wave of helpers joining, can send many lines that say little: "idle", "ready
for the next card", "waiting for a task", one `joined:` line each, or the same line twice. The lead's wait runs two
steps over the lines it gathered (wait._wait calls them):

- calm: a helper's chatter line can wait for the lead's digest, even when it starts `urgent:` or `blocked:`, so it
  never wakes the lead by itself.
- fold: when the lines print, the chatter lines from helpers become one line that names them, the `joined:` lines
  become one, and a line that came several times shows once with its count. A done line, a question, a person's line
  and anything else stay as they are.

The folded lines are kept in ~/.colony/<project>/<lead>-folded.json, the newest FOLDED_KEPT, and `colony watch
--folded` prints them. A helper says it is idle with `colony intent waiting "<what>"`, which reaches the lead's watch
without a line at all.
"""
from __future__ import annotations

import re
import time

from colony import cli, wait

FOLDED_KEPT = 100
# A sentence that only says its helper has nothing to do: it starts so, after the line's kind, and says nothing else
# of substance. A question never matches, and neither does a sentence that only mentions the word, such as "the idle
# timeout test fails".
CHATTER = re.compile(
    r"^(?:(?:urgent|blocked)\s*:\s*)?(?:[\w.-]+\s+(?:is|am)\s+|i\s+am\s+|i'm\s+|now\s+)?(?:still\s+|now\s+)?"
    r"(?:idle(?=\s*$|\s*[,.;!]|\s+(?:and|now|again|until|since|waiting|for\b))"
    r"|free(?:\s+(?:for|to\s+take)\s+(?:a|the\s+next|another|new|more)\s+(?:card|task|work))"
    r"|standing\s+by|ready\s+for\s+(?:a|the\s+next|another|new|more)\s+(?:card|task|work)"
    r"|waiting\s+for\s+(?:a|the\s+next|another|new|more|my\s+next)\s+(?:card|task|start|work)"
    r"|nothing\s+(?:left\s+)?to\s+do|no\s+(?:card|task|work)\s+(?:left|yet|to\s+do))\b", re.I)
KIND = re.compile(r"^(done|question|answer|start|stop|joined|redirected)\b", re.I)


def parts(text: str) -> tuple[str, str, bool]:
    """A gathered line, `#<card> <line>`, as its sender and its sentence, and whether the lead's wait redirected it."""
    line = text.partition(" ")[2] if text.startswith("#") else text
    signed = wait.SIGNED.search(line)
    sentence = wait.SIGNED.sub("", wait.sentence_of(line.removeprefix(wait.REDIRECTED))).strip()
    return signed[1].lower() if signed else "", sentence, line.startswith(wait.REDIRECTED)


def from_helper(sender: str, people: frozenset[str] = frozenset()) -> bool:
    """Whether a line's sender is a helper: signed, and not a lead, Colony itself, or a person."""
    return bool(sender) and sender != cli.LEAD and not sender.endswith(f"-{cli.LEAD}") and sender != cli.NAME \
        and sender not in people


def is_chatter(text: str, people: frozenset[str] = frozenset()) -> bool:
    """Whether a gathered line is a helper's chatter: from a helper, of no kind that matters, and saying only that it
    has nothing to do."""
    sender, sentence, redirected = parts(text)
    return not redirected and from_helper(sender, people) and not KIND.match(sentence) \
        and not sentence.rstrip().endswith("?") and CHATTER.match(sentence) is not None


def calm(pending: list, people: frozenset[str] = frozenset()) -> list:
    """The lead's gathered lines, with each helper's chatter line set to wait for the digest."""
    return [[text, False] if cant_wait and is_chatter(str(text), people) else [text, cant_wait]
            for text, cant_wait in pending]


def fold(project: str, lead: str, lines: list[str], people: frozenset[str] = frozenset(),
         now: float | None = None) -> list[str]:
    """The lines the lead's wait prints, with chatter, `joined:` lines and repeats folded, each fold one line where its
    first line stood. The folded lines are kept for `colony watch --folded`. It never raises."""
    try:
        return _fold(project, lead, lines, people, now)
    except Exception:  # folding never costs the lead a line
        return lines


def _fold(project, lead, lines, people, now) -> list[str]:
    idle, joined, counts, order = [], [], {}, []
    for text in lines:
        sender, sentence, redirected = parts(text)
        if is_chatter(text, people):
            idle.append((sender, text))
            key = "idle"
        elif from_helper(sender, people) and sentence.lower().startswith("joined") and not redirected:
            joined.append((sender, text))
            key = "joined"
        else:
            key = text
            counts[text] = counts.get(text, 0) + 1
        if key not in order:
            order.append(key)
    out, folded = [], []
    for key in order:
        if key == "idle":
            names = sorted({sender for sender, _ in idle})
            if len(idle) == 1:
                out.append(idle[0][1])
                continue
            out.append(f"chatter: {listed(names)} said {'it has' if len(names) == 1 else 'they have'} nothing to do "
                       f"({len(idle)} lines folded; `{cli.NAME} watch --folded` shows them)")
            folded += [text for _, text in idle]
        elif key == "joined":
            if len(joined) == 1:
                out.append(joined[0][1])
                continue
            out.append(f"joined: {listed(sorted({sender for sender, _ in joined}))} ({len(joined)} lines folded)")
            folded += [text for _, text in joined]
        else:
            out.append(key if counts[key] == 1 else f"{key} ({counts[key]} times)")
            folded += [key] * (counts[key] - 1)
    if folded:
        keep(project, lead, folded, now)
    return out


def listed(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"


def path(project: str, lead: str):
    return wait.state_path(project, f"{lead}-folded")


def keep(project: str, lead: str, lines: list[str], now: float | None = None) -> None:
    """Add folded lines to the lead's record of them, the newest FOLDED_KEPT."""
    at = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(time.time() if now is None else now))
    held = wait.read_json(path(project, lead), [])
    held = [item for item in held if isinstance(item, str)] if isinstance(held, list) else []
    wait.write_json(path(project, lead), (held + [f"{at} {line}" for line in lines])[-FOLDED_KEPT:])


def folded(project: str, lead: str) -> list[str]:
    """The folded lines on record, oldest first, or a note when there are none."""
    held = wait.read_json(path(project, lead), [])
    held = [item for item in held if isinstance(item, str)] if isinstance(held, list) else []
    return held or ["No line was folded yet."]
