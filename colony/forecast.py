"""Plan around resets: each account's burn rate from successive live readings, overall and per busy helper, a forecast
of when each of its windows runs out, and whether one more helper fits before the account's next reset
(docs/capacity.md#plan-around-resets).

- **Readings.** Each fresh reading of an account on this computer is kept for a day, with how many helpers ran on the
  account then, in ~/.colony/<project>/usage-history.json (record). The lead's wait takes one every OBSERVE_EVERY,
  and `colony capacity` and every wave of helpers keep theirs too.
- **Burn rate.** Over the last RATE_SPAN of one window, how many percent its use rose an hour, and that divided by the
  helpers it ran meanwhile (burn). Two readings of the same window at least MIN_SPAN apart make a rate: usage comes
  in whole percents, so a short span of the slow weekly window would read one step as a fast pace.
- **Forecast.** At that pace, when the window reaches [pool] out_at, and whether that comes before its reset
  (outlook).
- **Fit.** Before a helper opens on an account, the pace with that helper there too: the account's own rate per
  helper, else the pool's average, else [pool] helper_rate. A helper that would run the account out more than
  FIT_SLACK before a reset goes to another account, or waits for the reset (fits, next_reset).
- **Warnings.** The lead's wait says ahead of time, in plain words, when an account's helpers run it out before its
  reset, and how many helpers to move where (lead_part). It counts the helpers on this computer.

Python 3.11+ standard library only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from colony import capacity, cli, wait

HISTORY = "usage-history"  # ~/.colony/<project>/usage-history.json
KEPT = 24 * 3600  # readings older than this are dropped
MOST = 400  # the most readings kept per account
SAME_READING = 30  # two readings taken within this many seconds of each other are one
RATE_SPAN = {"five_hour": 60 * 60, "seven_day": 24 * 3600}  # how far back a window's burn rate looks
MIN_SPAN = {"five_hour": 15 * 60, "seven_day": 3 * 3600}  # two readings at least this far apart make a rate
SAME_WINDOW = 10 * 60  # two readings whose resets differ by less than this read one window
FIT_SLACK = 15 * 60  # running out less than this before a reset still fits
OBSERVE_EVERY = 10 * 60  # how often the lead's wait takes a live reading and looks at the forecast
SOON = 30 * 60  # an account that runs out within this long gets an urgent line
WINDOW_SECONDS = {"five_hour": 5 * 3600, "seven_day": 7 * 24 * 3600}
WINDOW_NAMES = {"five_hour": "5-hour", "seven_day": "weekly"}


def clock(at: float | None, now: float | None = None) -> str:
    """A time for a line: `07:10 UTC` within a day, else `Sat 07:10 UTC`."""
    if at is None:
        return "an unknown time"
    now = time.time() if now is None else now
    form = "%H:%M UTC" if abs(at - now) < 20 * 3600 else "%a %H:%M UTC"
    return datetime.fromtimestamp(at, timezone.utc).strftime(form)


def plural(count: float, word: str) -> str:
    return f"{count:g} {word}{'' if count == 1 else 's'}"


# Readings


def history(config: dict) -> dict[str, list[dict]]:
    """Every account's kept readings, oldest first."""
    held = capacity.read(config["project"]["name"], HISTORY)
    return {name: [p for p in points if isinstance(p, dict) and isinstance(p.get("at"), (int, float))]
            for name, points in held.items() if isinstance(points, list)}


def on_this_computer(config: dict, names=None) -> list[str]:
    """The accounts, all or `names`, whose folder is on this computer."""
    accounts = config.get("accounts", {})
    return [name for name in (names if names is not None else accounts) if name in accounts
            and Path(accounts[name]["config_dir"]).expanduser().is_dir()]


def record(config: dict, name: str, helpers: int | None = None, now: float | None = None,
           held: dict | None = None) -> bool:
    """Keep an account's reading, as of when it was read, with the helpers it runs now when known. A reading already
    kept is kept once. Returns whether it kept a new one; `held`, when given, is the history to add to, unsaved."""
    now = time.time() if now is None else now
    found = capacity.windows(config, name)
    age = capacity.reading_age(config, name, now)
    if not found or age is None:
        return False
    at = now - age
    point: dict = {"at": round(at, 1), "helpers": helpers}
    for window in WINDOW_NAMES:
        if window in found:
            used, resets = found[window]
            point[window] = [used, resets.timestamp() if resets else None]
    save = held is None
    held = history(config) if held is None else held
    points = [p for p in held.get(name, []) if now - float(p["at"]) < KEPT]
    if points and abs(float(points[-1]["at"]) - at) < SAME_READING:
        if helpers is None or points[-1].get("helpers") is not None:
            return False
        points[-1]["helpers"] = helpers  # the same reading, now with its helpers
    else:
        points.append(point)
    held[name] = points[-MOST:]
    if save:
        wait.write_json(capacity.state(config["project"]["name"], HISTORY), held)
    return True


def record_all(config: dict, counts: dict | None = None, names=None, now: float | None = None) -> None:
    """Keep the reading of each account on this computer, all or `names`, with its helpers from `counts`."""
    held = history(config)
    kept = [record(config, name, len(counts.get(name, ())) if counts is not None else None, now, held)
            for name in on_this_computer(config, names)]
    if any(kept):
        wait.write_json(capacity.state(config["project"]["name"], HISTORY), held)


def observe(config: dict, names=None, counts: dict | None = None, now: float | None = None) -> None:
    """Take a live reading of each account on this computer, all or `names` (cli.refresh_usage), and keep it."""
    found = on_this_computer(config, names)
    cli.refresh_usage([config["accounts"][name]["config_dir"] for name in found])
    record_all(config, counts, found, now)


# Burn rate and forecast


@dataclass
class Burn:
    """How fast one window fills: percent of the window an hour, over `span` seconds."""

    rate: float
    helpers: float | None  # the helpers the account ran meanwhile, on average, when known
    span: float

    @property
    def per_helper(self) -> float | None:
        return self.rate / self.helpers if self.helpers is not None and self.helpers >= 1 else None


def burn(points: list[dict], window: str) -> Burn | None:
    """A window's burn rate from an account's kept readings: from the oldest reading of the newest one's window within
    RATE_SPAN to the newest, at least MIN_SPAN apart, else None. A window not started yet, with no reset time, burns
    nothing."""
    marked = [(float(p["at"]), p[window][0], p[window][1], p.get("helpers")) for p in points
              if isinstance(p.get(window), list) and len(p[window]) == 2]
    if not marked:
        return None
    last_at, last_used, last_reset, _ = marked[-1]

    def same(reset) -> bool:
        if reset is None or last_reset is None:
            return reset is None and last_reset is None
        return abs(reset - last_reset) < SAME_WINDOW

    chosen = [m for m in marked if same(m[2]) and last_at - m[0] <= RATE_SPAN[window]]
    span = last_at - chosen[0][0]
    if span < MIN_SPAN[window]:
        return None
    counted = [m[3] for m in chosen if isinstance(m[3], (int, float))]
    return Burn(max(0.0, last_used - chosen[0][1]) / (span / 3600), sum(counted) / len(counted) if counted else None,
                span)


def per_helper(config: dict, name: str, held: dict | None = None,
               pool: capacity.Policy | None = None) -> tuple[float | None, str]:
    """The 5-hour window's percent one busy helper uses an hour on an account, and where that comes from: its own
    readings, else the average of the pool's, else [pool] helper_rate, None when that is 0."""
    held = history(config) if held is None else held
    own = burn(held.get(name, []), "five_hour")
    if own is not None and own.per_helper is not None:
        return own.per_helper, "its own readings"
    rates = [found.per_helper for other, points in held.items() if other in config.get("accounts", {})
             and (found := burn(points, "five_hour")) is not None and found.per_helper is not None]
    if rates:
        return sum(rates) / len(rates), "the pool's readings"
    pool = pool or capacity.policy(config)
    return (pool.helper_rate, "the [pool] helper_rate guess") if pool.helper_rate > 0 else (None, "")


@dataclass
class Outlook:
    """One window's forecast at a pace: when it reaches [pool] out_at, against when it resets."""

    account: str
    window: str
    used: float
    resets: float  # when it resets, as Unix time; a window not started yet resets one window after now
    rate: float | None  # percent an hour at the pace counted, None when no pace is known
    out: float | None  # when it reaches out_at, None when it never fills at this pace or no pace is known
    source: str = ""  # where the pace came from
    known_reset: bool = True  # false for a window not started, whose reset is one window after now, a guess

    @property
    def short(self) -> bool:
        """Whether it runs out more than FIT_SLACK before it resets."""
        return self.out is not None and self.out < self.resets - FIT_SLACK


def outlook(config: dict, name: str, window: str, helpers: int | None = None, now: float | None = None,
            pool: capacity.Policy | None = None, held: dict | None = None, running: int | None = None) -> Outlook | None:
    """A window's forecast, or None when the account has no reading of it. With `helpers` None, at the pace its
    readings show; else at the pace with that many helpers busy, where `running` helpers run on it now: its measured
    rate plus each helper more at the rate one helper uses (per_helper). The weekly window scales its own measured
    rate by the helpers alone."""
    now = time.time() if now is None else now
    pool = pool or capacity.policy(config)
    found = capacity.windows(config, name).get(window)
    if found is None:
        return None
    used, resets = found
    resets_at = resets.timestamp() if resets else now + WINDOW_SECONDS[window]
    held = history(config) if held is None else held
    measured = burn(held.get(name, []), window)
    rate, source = (measured.rate, "its readings") if measured else (None, "")
    if helpers is not None:
        # With a measured rate, it already holds the helpers it ran meanwhile; with none, every helper is a guess.
        before = running if running is not None else helpers
        counted = (measured.helpers if measured.helpers is not None else before) if measured is not None else 0
        if window == "five_hour":
            each, source = per_helper(config, name, held, pool)
            if each is not None:
                rate = max(0.0, (measured.rate if measured else 0.0) + (helpers - counted) * each)
        elif measured is not None and counted:
            rate = measured.rate * helpers / counted
    out = None
    if used >= pool.out_at:
        out = now
    elif rate and rate > 0:
        out = now + (pool.out_at - used) / rate * 3600
    return Outlook(name, window, used, resets_at, rate, out, source, resets is not None)


def fits(config: dict, name: str, helpers: int, pool: capacity.Policy | None = None,
         now: float | None = None) -> tuple[bool, str]:
    """Whether `helpers` busy helpers on an account last until each window resets, give or take FIT_SLACK, with a
    short why. An account whose reading is missing or stale fits, since nothing says otherwise."""
    now = time.time() if now is None else now
    pool = pool or capacity.policy(config)
    if capacity.stale(config, name, pool, now) is not None:
        return True, ""
    held = history(config)
    for window in WINDOW_NAMES:
        found = outlook(config, name, window, helpers, now, pool, held, running=helpers - 1)
        if found is not None and found.short:
            return False, (f"{plural(helpers, 'helper')} on {name} would run its {WINDOW_NAMES[window]} window out "
                           f"around {clock(found.out, now)}, before it resets at {clock(found.resets, now)} "
                           f"({found.rate:.0f}% an hour, by {found.source})")
    five = outlook(config, name, "five_hour", helpers, now, pool, held, running=helpers - 1)
    return True, (f"it lasts to its 5-hour reset at {clock(five.resets, now)} with them"
                  if five is not None and five.rate else "")


def next_reset(config: dict, person: str, now: float | None = None) -> float | None:
    """The soonest 5-hour reset still to come among the person's accounts that [pool] reserve doesn't keep free: when
    helpers that fit nowhere now can start."""
    now = time.time() if now is None else now
    pool = capacity.policy(config)
    names = [n for n in dict.fromkeys(sum(cli.person_accounts(config, person), [])) if n not in pool.reserve]
    resets = [resets.timestamp() for name in on_this_computer(config, names)
              for _, resets in [capacity.windows(config, name).get("five_hour", (0.0, None))]
              if resets is not None and resets.timestamp() > now]
    return min(resets) if resets else None


# Lines


def pace_text(found: Outlook | None, now: float) -> str:
    """One window's forecast in words."""
    if found is None:
        return ""
    label = WINDOW_NAMES[found.window]
    if found.rate is None:
        span = MIN_SPAN[found.window]
        apart = f"{span // 3600} hours" if span >= 3600 else f"{span // 60} minutes"
        return f"{label}: no pace yet, which two readings {apart} apart give"
    pace = f"{found.rate:.1f}% an hour"
    if found.out is not None and found.short:
        return f"{label}: runs out around {clock(found.out, now)}, before it resets at {clock(found.resets, now)} ({pace})"
    return f"{label}: lasts to its reset at {clock(found.resets, now)} ({pace})"


def summary(config: dict, name: str, helpers: int | None = None, now: float | None = None) -> str:
    """An account's forecast for `colony capacity` and `colony accounts`: each window at the pace its readings show,
    with the rate per busy helper when known."""
    now = time.time() if now is None else now
    pool = capacity.policy(config)
    if (old := capacity.stale(config, name, pool, now)) is not None:
        return f"no forecast: its reading is {cli.ago(old)} old"
    held = history(config)
    parts = [text for window in WINDOW_NAMES if (text := pace_text(outlook(config, name, window, None, now, pool,
                                                                            held), now))]
    own = burn(held.get(name, []), "five_hour")
    if own is not None and own.per_helper is not None:
        parts.append(f"{own.per_helper:.1f}% an hour per busy helper, over {own.helpers:.1f} helpers")
    return "; ".join(parts) or "no forecast: no reading"


def account_lines(config: dict, now: float | None = None, relative: bool = True) -> list[str]:
    """Each account on this computer with its room, how old its reading is, and its forecast, for `colony watch` and
    the status page. `relative` says the age as `read 3 min ago`; otherwise as the time it was read, which stays
    true on a page that changes only every few minutes. A reading past [pool] stale_minutes says so."""
    now = time.time() if now is None else now
    pool = capacity.policy(config)
    lines = []
    for name in on_this_computer(config):
        found = capacity.windows(config, name)
        if not found:
            lines.append(f"{name}: no reading")
            continue
        parts = [f"{short} {found[window][0]:g}%" + (f" (resets {clock(found[window][1].timestamp(), now)})"
                                                      if found[window][1] else "")
                 for window, short in cli.WINDOWS.items() if window in found]
        age = capacity.reading_age(config, name, now)
        read = "" if age is None else (f", read {cli.ago(age)} ago" if relative else f", read at {clock(now - age, now)}")
        text = f"{name}: {', '.join(parts)}{read}"
        if capacity.stale(config, name, pool, now) is not None:
            text += f": stale, past [pool] stale_minutes ({pool.stale_minutes:g}), so placement counts its room unknown"
        else:
            five = outlook(config, name, "five_hour", None, now, pool)
            if five is not None and five.short and five.known_reset:
                text += f"; runs out around {clock(five.out, now)}, before it resets at {clock(five.resets, now)}"
        lines.append(text)
    return lines


def risk_lines(config: dict, names=None, now: float | None = None) -> list[str]:
    """One line per account on this computer, all or `names`, whose fresh readings show it running out before a
    reset, for the briefing."""
    now = time.time() if now is None else now
    pool = capacity.policy(config)
    held = history(config)
    lines = []
    for name in on_this_computer(config, names):
        if capacity.stale(config, name, pool, now) is not None:
            continue
        for window in WINDOW_NAMES:
            found = outlook(config, name, window, None, now, pool, held)
            if found is not None and found.short and found.known_reset:
                lines.append(f"Forecast: {name} runs out around {clock(found.out, now)} at its pace "
                             f"({found.rate:.0f}% an hour), before its {WINDOW_NAMES[window]} window resets at "
                             f"{clock(found.resets, now)}.")
                break
    return lines


def move_plan(config: dict, name: str, window: str, helpers: int, counts: dict, kept: dict, now: float,
              pool: capacity.Policy) -> str:
    """What the lead does about an account whose helpers run it out before a window resets: the fewest helpers to
    move so the rest last, and the account with room for them, or to open no more there."""
    held = history(config)
    move = helpers
    for count in range(1, helpers + 1):
        rest = outlook(config, name, window, helpers - count, now, pool, held, running=helpers)
        if rest is None or not rest.short:
            move = count
            break
    others = [other for other in on_this_computer(config) if other != name and other not in pool.reserve
              and (pool.share_lead_accounts or other not in kept)]
    for other in others:
        busy_there = len(counts.get(other, ()))
        if busy_there + move > capacity.cap(config, other, pool):
            continue
        if capacity.judge(config, other, datetime.fromtimestamp(now, timezone.utc), pool)[0] != 0:
            continue
        if fits(config, other, busy_there + move, pool, now)[0]:
            return (f"move {plural(move, 'helper')} to {other}, which has room for them: as each finishes its card, "
                    f"stop it with `{cli.NAME} stop <name>`, and open the next one with `{cli.NAME} open <name> "
                    f"--account {other}`")
    return (f"no other account has room for {plural(move, 'more helper')} before its own reset: open no more helpers "
            f"on {name}, and let the ones there finish their cards; one that stops on the limit wakes by itself at "
            "the reset")


def lead_part(config: dict, held: dict, now: float | None = None) -> list[str]:
    """The lead's wait's part, every OBSERVE_EVERY after the first: a live reading of every account on this computer,
    kept, and a line, once when the forecast first shows it and once more when it is under SOON away, for each
    account whose helpers here run a window out before it resets."""
    now = time.time() if now is None else now
    if "at" not in held:  # the first poll: the look starts one interval later, never in a short wait
        held["at"] = now
        return []
    if now - float(held["at"]) < OBSERVE_EVERY:
        return []
    held["at"] = now
    counts = capacity.busy(config, [], cli.running_sessions(config))
    observe(config, None, counts, now)
    pool, kept = capacity.policy(config), capacity.lead_accounts(config)
    warned = {key: value for key, value in (held.get("warned") or {}).items()
              if isinstance(value, list) and now - float(value[1]) < KEPT}
    lines = []
    history_ = history(config)
    for name in on_this_computer(config):
        helpers = len(counts.get(name, ()))
        if not helpers or capacity.stale(config, name, pool, now) is not None:
            continue
        for window in WINDOW_NAMES:
            found = outlook(config, name, window, helpers, now, pool, history_, running=helpers)
            if found is None or not found.short or found.rate is None or not found.known_reset:
                continue
            key = f"{name}:{window}:{int(found.resets // SAME_WINDOW)}"
            stage = "soon" if found.out - now <= SOON else "ahead"
            if (warned.get(key) or [""])[0] in (stage, "soon"):
                continue
            warned[key] = [stage, now]
            plan = move_plan(config, name, window, helpers, counts, kept, now, pool)
            lines.append(f"{'urgent: ' if stage == 'soon' else ''}account {name} runs out around "
                         f"{clock(found.out, now)} at its pace ({found.rate:.0f}% of its {WINDOW_NAMES[window]} window "
                         f"an hour, with {plural(helpers, 'helper')} here), and that window resets at "
                         f"{clock(found.resets, now)}: {plan}")
            break
    held["warned"] = warned
    return lines
