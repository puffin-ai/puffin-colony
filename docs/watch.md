# Watching the team

A team of sessions needs someone to notice when one of them stops: a helper that went quiet, a lead that sat idle for hours, a card that runs far past its prediction. This page says how Colony watches, so a person doesn't have to. It flags only a session that is idle without a reason, so a session that waits on purpose never raises a false alarm. Every setting here is under `[watch]` in [configuration.md](configuration.md#watch), and every command is in [commands.md](commands.md#watch).

`colony watch` shows it all at once: each lead and helper with what it does and why, its last report and its helper agents, then what is worth a look, then the cards' progress.

## Intent: saying what you do and why

Each session says what it is doing with `colony intent`:

| Intent | Example | What the watch does |
| --- | --- | --- |
| `working` | `colony intent working "#41"` | Expects a report at least every `report_minutes`. |
| `waiting` | `colony intent waiting "#42 to land" --on ben-web-lead` | Raises nothing, until its end time passes, or the session it waits on stops. |
| `holding` | `colony intent holding "merges until the release checks pass" --for 90` | The same as waiting. |
| `done` | `colony intent done` | Raises nothing. |

`waiting` and `holding` need a reason. `--for <minutes>` gives the wait an end time; without one, the watch checks on it after `intent_hours` (4). `--on <session>` names the session you wait on, so the watch tells your lead when that session is gone, out of usage, idle or done. `colony intent clear` drops the intent, and `colony intent` alone prints it.

Colony sets the intent by itself at two moments: `colony take <n>` sets `working` on the card, and a helper's `done` line sets `waiting` for its next card, from its lead. A session stopped on its usage limit counts as waiting for the reset, and a lead whose helpers work counts as waiting on them.

The intent lives in `~/.colony/<project>/<session>-intent.json`, and goes out in the session's status comment at the wait's next poll, so a lead on another computer sees it. A reason is one line of at most 120 characters, and Colony refuses one that names a path on your computer, since the status comment is on GitHub.

## What the watch flags

The lead's wait looks at its helpers every `every_minutes` (2), and adds a line only for:

- **idle:** a helper that has done nothing for `idle_minutes` (20) and gave no reason. Its transcript says when it last acted.
- **quiet:** a working helper that missed two reports in a row.
- **overdue:** a wait or a hold past its end time.
- **stalled:** a wait on a session that is gone, out of usage, idle or done.
- **agent:** a helper's own helper agent that has run past twice `agent_minutes`.

These lines wait for the lead's digest, and each shows once per stretch: the same helper idle for longer raises no second line, and one that works and then goes quiet again raises a new one. A session waiting, holding or done on purpose raises nothing, and neither does one stopped on its usage limit, which Colony wakes when the limit resets ([capacity.md](capacity.md#when-a-usage-limit-resets)). A helper whose tool call waits on a permission prompt has its own `urgent:` line.

The lead is watched too. When the lead itself has done nothing for `idle_minutes`, no helper of its is busy, and it gave no reason, its own wait wakes it with one `urgent:` line. A lead that has finished, or waits for the person, says so with `colony intent`.

The watch reads no screen and matches no words in what a session prints. It reads the intent each session gives, its transcript's times, its usage-limit record, and its status comment.

## The reporting rhythm

A working helper sends a short report at least every `report_minutes` (30):

```sh
colony report "the login form passes its tests; the phone layout is next"
```

The report goes out in its status comment, sets its intent to `working` when it was anything else, and stamps the card's Last update on the board. When a report is due, the helper's own wait reminds it with one line. When it misses two, its lead hears a `quiet:` line. Progress still never goes in a line to the lead.

## Helper agents

A helper may start helper agents of its own, such as Claude Code's subagents. The watch finds each one that runs, from the helper's transcript folder: what it does, when it started and when it last moved. They show in the helper's status comment, in `colony watch` and on the status page.

When one runs past `agent_minutes` (45), the helper's own wait tells it with one `urgent:` line, and again past twice that: the helper reads the agent's output and stops it unless it is about to finish. Past twice the limit, the lead hears an `agent:` line too. Colony can't stop an agent inside another session itself, so the helper stops it with its own agent tool.

## Progress and time estimates

Every card has a prediction, such as `predicted: S, 20 min`. Its time runs from the lead's `start: this card` line to the helper's `done` line. `colony progress` lists your cards, and `--all` every lead's:

```text
- #41 (builder-2), In progress: 34 of 20 predicted min so far, past its prediction. dark mode switch
- #43, To do: predicted 30 min, not started. date picker on phones
Progress: 2 done, 1 in review, 2 in progress, 3 to do. About 70 minutes of predicted work is left; with 2 helpers at once, it ends near 15:40 UTC. #41 is past the prediction, so the estimate is low.
```

The estimate adds the minutes left on each card In progress and the predictions of the cards To do, and divides by the helpers working at once. A card past its prediction, or one with none, makes the estimate low, and the line says so.

When a card In progress passes `late_after` (1) times its prediction, the lead's wait adds one `late:` line, and one more at twice that, which asks what holds it up. Each card's issue is read once per change; `~/.colony/<project>/progress.json` keeps what was read.

## The watchdog

The watchdog is one process per project on each computer. It keeps watching when every session has stopped, such as when the orchestrator, or every lead, has hit its usage limit. It runs apart from every Claude Code session, with none of their identity, so a session that stops, hits its limit or closes leaves it running.

Each pass, every `every_minutes`, it:

1. starts again a wait that stopped: a session on this computer whose wait stopped while the session sits idle is woken with a prompt to start its wait again, unless it said it is done or waits for its usage limit;
2. tells an idle session about a background task of its that something stopped from outside, such as the agent tool or a crash, with what to start again. It reads the task files recovery keeps, and says what the session's own Stop hook would say at the end of its next turn, so the session hears it once ([safety.md](safety.md#recovery));
3. when no lead's wait runs on this computer, does that wait's part: wakes the sessions whose usage limit reset, and after a sleep starts again what stopped ([capacity.md](capacity.md#sleep-and-wake));
4. mentions a lead's person on GitHub, so their phone hears it, when the lead has sat idle with no helper busy, on any computer, and no reason given, for `escalate_minutes` (60) past `idle_minutes`;
5. keeps the status page current.

The lead's wait starts the watchdog by itself when `[watch] watchdog` is on (the default) and none runs on its computer. `colony watchdog start` starts it by hand, and `colony watchdog status` says whether it runs, its last pass and its log. Started so, it ends after `quit_hours` (24) with no session alive on the computer.

For a watchdog the computer keeps running across restarts and logins, run `colony watchdog install`. On macOS it writes a launchd agent, `~/Library/LaunchAgents/com.colony.watchdog.<project>.plist`, and on Linux a systemd user unit, each set to start at login and again whenever it ends. Both carry your PATH and HOME, and nothing else from your environment. `colony watchdog uninstall` removes it. On other systems, `install` says which command to have the computer run at login.

`colony watchdog stop` ends it by its exact process id, from its heartbeat, `~/.colony/<project>/watchdog.json`. One runs per project on each computer: a second start says one runs already.

## The status page

The status page is one pinned issue, `Colony: status`, whose body the watchdog keeps current: a link the person can open on a phone. It shows what is worth a look, the cards' progress with their predictions and when the work left ends, and each lead and helper with what it does and why, its last report and its helper agents.

The watchdog writes it at most every `page_minutes` (5), only when something changed, and at least every 30 minutes so a reader sees it is alive. `colony watch --page` writes it at once and prints its link. Colony makes the issue the first time, and pins it when the repo has room for one more pinned issue. Set `[watch] page = false` to keep no page.

The page holds what the status comments already hold, plus card numbers and titles: never a path on a computer, a command's output, or a secret. On a public repo, anyone can read it, as they can the status comments.

## Helper chatter

A helper that has nothing to do, or a wave of helpers joining, can send many lines that say little. The lead's wait folds them, so real results and questions reach the lead:

- A helper's line that only says it is idle, free, standing by or waiting for a card waits for the digest, even when it starts `urgent:` or `blocked:`, so it never wakes the lead by itself.
- When the digest prints, those lines become one, such as `chatter: builder-2 and builder-3 said they have nothing to do (4 lines folded)`. Several `joined:` lines become one, and a line that came several times shows once, with its count.
- A done line, a question, a person's line and every other line stay as they are.

`colony watch --folded` prints the folded lines, the newest 100. A helper with nothing to do says so with `colony intent waiting "<what>"`, which reaches the lead's watch with no line at all.
