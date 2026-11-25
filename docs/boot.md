# Starting a session

You open a session and start working at once. You don't tell the lead again who it is, how your team works, which accounts to use or what happened last time: your standing orders, the last handover and the state of the team come to it by themselves. This page covers the parts that make that work: the startup routine, the project summary, the automatic handover, modes, request intake, and the orders a lead passes its helpers. Your standing orders themselves are in [profiles.md](profiles.md), and what a lead asks you is in [decisions.md](decisions.md).

## The startup routine

When a session becomes a lead, Colony runs the startup routine without being asked: at the end of plain `colony` inside the session, at the end of `colony claim`, and from the SessionStart hook when a lead's session resumes. `colony boot` runs it again by hand, and `--offline` skips GitHub.

It reads, side by side and within 12 seconds:

1. **Your standing orders**, merged from the team profile, your personal profile, the active mode and the session ([profiles.md](profiles.md)).
2. **The last handover**: the automatic one this computer saved, and the last one posted on `Colony: coordination` for this lead.
3. **The project summary**, refreshed from what changed since it was built, and what changed since this session last started.
4. **The live leads on every computer**, from their status comments, and your helpers.
5. **The open pull requests** and **your open cards** on the board.
6. **The plan**, when one is open, and **the decisions that wait on you**.
7. **This computer's room** for helpers, and **each of your accounts' room**, from [capacity](capacity.md).

Then it prints a short briefing. Its first line names the active mode. A part not read in time says so, and the rest goes on. Its last line is the next step, and it is one of two things:

- **Resume.** When a plan has task groups not done, or the last handover names a next step from the last three days, the lead carries on at once and asks nothing first.
- **One question.** Otherwise the lead asks you one question: the oldest decision that waits on you, or "What should we work on first?" with its pick from the open pull requests and cards.

A briefing looks like this:

```
Puffin Colony briefing for ana-main-lead, 2026-11-24 09:00 UTC. Mode: unattended (from personal).
Orders: 14 in force; decisions: unattended; never raise: the office move (`colony profile show` lists them).
Last handover (2026-11-23 18:40 UTC, 14 h ago, saved when the session ended on Ana-Laptop):
- Next: task group web of the plan (started; done when: the screen loads)
Project demo: Demo plans your week for you. 412 files on origin/main.
Areas: web (230 files, TypeScript); api (120 files, Python); docs (40 files, Markdown).
Since this session last started, 14 h ago (a1b2c3d4e..e4f5a6b7c): 9 commits in web, docs; the newest: "web: the login screen".
Live leads: ana-main-lead (you) on Ana-Laptop, the rest of the repo; sam-web-lead on PC-2, web/.
Your helpers: builder-1, builder-2.
Open pull requests (2): #212 Login screen; #214 Docs for the API (draft).
This computer: 2 more helpers now, of 4 at once (8 cores, load 2.1).
Accounts: main: 5h 40%, week 63% (resets Sat 10:00 UTC).
Plan for "Ship the new onboarding": 1 of 3 task groups done.
Next: resume the plan at once, without asking: task group web of the plan (started; done when: the screen loads).
```

## The project summary

The summary replaces "explore the repo". Colony builds it once from git: what the project is, from the top README; each area, its file count, its main languages and its purpose, from that folder's README or AGENTS.md; and the checks. It reads `origin/<base>`, the merged work, when it exists, else `HEAD`.

It is refreshed, not rebuilt. On the same commit it is reused whole. On a newer one, only the areas a change touched are read again. Each session also hears what changed since it last started on this computer: the commits, their areas and the newest subjects. `colony summary` prints it, and `--rebuild` builds it again from scratch. It lives in `~/.colony/<project>/summary.json`.

## The automatic handover

Every session hands over by itself, so a compaction, a crash or a closed window loses nothing:

| When | What Colony does |
| --- | --- |
| After every turn (the Stop hook) | Keeps the session's snapshot current on this computer, so a crash leaves the last turn's |
| Before a compaction (PreCompact) | Saves the handover, and posts a lead's on `Colony: coordination` |
| When the session ends (SessionEnd) | The same |
| When the session starts again after a compaction (SessionStart) | Prints the handover, so the session carries on from its `Next:` line |
| When a lead starts again | The briefing shows it |

A handover holds the next step, the plan's task groups, the decisions that wait on you and the ones taken alone, the branch and its uncommitted files, your last three messages and the session's last words. It is saved in `~/.colony/<project>/<session>-handover.json`, which only you can read. What you said stays on this computer: the posted handover, in the shape `colony handover` writes, carries only the decisions, the open questions and the next step, and is posted only when one of them changed. A handover that can't post waits in the outbox. `colony handover` still posts one by hand.

## Modes

A mode is a bundle of standing orders switched on with one word: `colony mode orchestrator`, `colony mode unattended`, `colony mode plan-first` or `colony mode speed`, or one you or your team define. [profiles.md](profiles.md#modes) lists what each sets and how to define your own. They are not the same as a repo's Hack, Solo or Startup mode in `colony.toml` ([modes.md](modes.md)), which picks Colony's defaults for the whole repo.

## Request intake

You say what you want in one sentence. The lead turns it into a plan, with `colony plan`, before any card:

1. `colony plan new "<the request>"` keeps your words and says the team shape and limits from your orders.
2. The lead splits it into task groups. Each has a short name, the folders it owns, which no other group shares, up to 3 done-when results, and how many helpers it runs: `colony plan group web --folders web/ --done "the screen loads" --helpers 2`.
3. `colony plan start` starts the work. It shows you the plan first only when you asked for that in the request, such as "show me the plan first", or your orders or mode say `intake.plan = "show"`. Then it starts on your yes, kept word for word: `colony plan start --approved "<your words>"`.

What starting means depends on `team.shape`:

- **A lead** gets one card per group, which it hands to its helpers.
- **An orchestrator** opens one lead per group, as its own session named `<project>-<group>-lead`. Each claims its group's folders, runs its own helpers, builds nothing itself, and reports to the orchestrator with `colony say`. At most `team.max_leads` run at once, and the next starts as a group finishes, with `colony plan done <group>` and `colony plan start` again.

A group made with `--draft` is drafted first, and built only after your yes on the draft, which `colony plan approve <group> "<your words>"` records. `colony plan show` shows where each group stands, and `--of <lead>` shows another lead's plan on this computer, such as a group lead reading its orchestrator's.

## Orders reach helpers

A helper starts with its lead's standing orders for helpers, such as when the full suite runs, whether it may merge, how to write and what you approved for it, in its first prompt. The lead keeps them on its computer for a helper that joins there, and posts them on `Colony: coordination`, only when they change, for a helper that joins on another computer. `colony orders` prints them, and `--publish` posts them now.

## The hooks

`colony hooks install` adds these with Colony's other hooks, and the plugin carries them too. Each runs `colony session-hook <event>`, only in a Colony session, and always lets the session go on:

| Hook | Event | What it does |
| --- | --- | --- |
| SessionStart | `start` | The briefing for a lead; the handover after a compaction |
| PreCompact | `compact` | Saves the handover, and posts a lead's |
| SessionEnd | `end` | The same |
| Stop | `turn` | Keeps the snapshot current, in the background |
| PreToolUse | `tool` | Lets through a call you approved ([decisions.md](decisions.md#approvals-reach-helpers)). It runs only while an approval is live |
