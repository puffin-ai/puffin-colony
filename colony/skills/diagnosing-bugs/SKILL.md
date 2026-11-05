---
name: diagnosing-bugs
description: A loop for hard bugs and slowdowns, from a red feedback loop to a regression test. Use when something is broken, throws, fails, flakes or got slow, when a check fails for a reason you can't see, or when someone says diagnose or debug.
---

# Diagnosing bugs

Work the phases in order. Skip one only when you can say why, and say it in your report.

## Redact first

You will show commands, output and captured requests. Write `<REDACTED>` in place of every key, token, password and `.env` value before you show anything. Build loops that read a secret from the environment, so it never appears in what you show, and quote only the lines of a capture that carry the signal.

## 1. Build a feedback loop that goes red

This is the whole skill. A **tight** loop that goes **red** on this bug and green once it is fixed finds the cause; without one, reading code won't. Spend most of your effort here. Ways to build one, roughly in this order:

1. A failing test at whatever seam reaches the bug: unit, integration or end to end.
2. A `curl` or HTTP script against a running dev server.
3. A command with a fixture input, its output diffed against a known-good copy.
4. A headless browser script that drives the screen and checks the page, the console or the network.
5. A captured request, payload or event log, replayed through the code path on its own.
6. A throwaway harness: the smallest part of the system that runs the failing path in one call.
7. A fuzz loop of random inputs, when the bug is "sometimes wrong".
8. A bisect script, when the bug appeared between two known states: `git bisect run <script>`.
9. A differential loop: the same input through the old and the new version, outputs diffed.

Then tighten it: faster (skip unrelated setup, narrow the test), sharper (check the exact symptom, not "didn't crash"), and deterministic (fix the clock, the seed, the time zone and the network). For a flaky bug, raise the reproduction rate instead: loop the trigger a hundred times, add load, narrow the timing window. A bug that shows half the time can be debugged; one that shows once in a hundred can't yet.

Phase 1 is done when you can name **one command** you have already run, with its redacted output, that drives the real code path, checks the reported symptom, gives the same verdict every run, and finishes in seconds. Until then, form no theory.

When you can't build a loop, stop and say so. List what you tried, and send the lead a question with your default: the environment that shows the bug, a redacted capture, or exact steps for the person to follow and what to report back.

## 2. Reproduce, then minimise

Run the loop and watch it go red. Check that it fails the way the report says, not in a nearby way: the wrong bug gets the wrong fix. Then cut inputs, callers, settings, data and steps one at a time, rerunning after each cut, until every element left is needed for the failure.

## 3. Rank hypotheses

Write 3 to 5 hypotheses, ranked, before you test any. Each one predicts something: "If X is the cause, changing Y makes the bug go away." A hypothesis that predicts nothing is a hunch: sharpen it or drop it. When someone on the card knows the area, post the ranked list; keep going on your own ranking meanwhile.

## 4. Probe

Tie each probe to one prediction, and change one thing at a time. Prefer a debugger or a REPL; next, a few logs at the boundaries that tell the hypotheses apart. Tag every debug log with one prefix, such as `[DEBUG-a4f2]`, so one search removes them all. For a slowdown, measure first, with a timing harness, a profiler or a query plan, and bisect on the number.

## 5. Fix with a regression test

Find the seam where a test exercises the bug the way the real caller does. Turn the minimised case into a failing test there, watch it fail, fix the code, watch it pass, and rerun the phase 1 loop on the original case. When no seam reaches the real pattern, that is a finding: say so on the card instead of writing a test that can't catch it.

## 6. Clean up

Done means all of these hold:

- the phase 1 loop passes on the original case
- the regression test passes, or the missing seam is written on the card
- no `[DEBUG-` line is left: search for the prefix
- throwaway harnesses are deleted
- the commit message and the `done` line name the cause that turned out true
