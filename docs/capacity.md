# Capacity: accounts, limits and the computer

A team runs many sessions at once, on one or more AI accounts and one or more computers. This page says how Colony shares that out: which account each session uses, how many helpers open at once, what happens when an account hits its usage limit, how the team hears about expired sign-ins, how much one computer runs at once, how runs share a thing only one can use, and what happens after a computer sleeps. Every setting here is in [configuration.md](configuration.md), and every command in [commands.md](commands.md#capacity).

`colony capacity` shows all of it in one place: this computer's cores, memory, free disk and load, how many helpers, test runs and builds it runs at once, each account's room with how old its reading is, its helpers and its forecast, the accounts kept for a live lead, the sessions waiting for a limit to reset, and the locks held. It takes a live reading of every account first. `--json` prints the same for a script or another command. `colony accounts` lists every account on each computer; see [Finding accounts](#finding-accounts).

## The account pool

An account is one AI login a session can run on. For Claude Code it is a settings folder, such as `~/.claude` or `~/.claude-work`. Each person lists their accounts in order, `[people.<person>] accounts`, with the ones used only when nothing else has room in `last_resort`.

`[pool]` holds the team's rules for that pool:

- **The order of use.** `order = "reset"`, the default, uses the account whose weekly window resets soonest first, so usage about to expire gets spent. `order = "listed"` uses the person's own order: the first account with room.
- **When to switch.** An account with any window at or past `out_at` percent (95 by default) has no room. One whose 5-hour window is at or past `near_at` (80) with its reset more than `near_hours` (1) away is skipped too.
- **Accounts kept free.** An account in `reserve` is never picked. A session uses it only when you name it with `--account`.
- **Helpers per account.** At most `max_busy` helpers (3 by default) run on one account at once, so they don't all hit its limit together. One account can set its own `max_busy`.

Any provider can be in the pool. A Claude Code account's usage comes from its settings folder. Any other account names a `usage_command`, which prints its usage in the same shape Claude Code saves, `{"five_hour": {"utilization": 40, "resets_at": "<ISO time>"}, "seven_day": {...}}`, and Colony judges it the same way.

## Helpers in waves

`colony helpers <n> --open` opens `[pool] wave` helpers now (3 by default). It starts the rest in the background, as `colony open-later`, which opens one more wave every `wave_seconds` (60). Each helper opens on the person's best account that is under its `max_busy`, and only while this computer has room for another helper. When no account is under its cap, or the computer is busy, the next wave waits. After an hour with no room, the lead gets one line saying how many helpers didn't open. The waves log to `~/.colony/<project>/helpers-waves.log`.

`colony open <name>` and `colony join` follow the same caps for one helper. When every account is at its cap, they refuse and say so. `--account` always opens on the account you name.

A wave never opens a helper on an account where it would run the account out before its reset ([Plan around resets](#plan-around-resets)), and never on a live lead's own account while you have others ([The lead's own account](#the-leads-own-account)). When no account can take one more helper before its reset, or every account is out of room, the wave opens fewer, and the background run starts the rest right after the soonest reset, without counting that wait against its hour of patience.

## Builders are helpers, never subagents

Every builder runs as a helper Colony opens, with `colony helpers <n> --open` or `colony open <name>`, so it gets an account with room, a place in a wave and a slot under its account's cap. A subagent runs inside the session that starts it, on that session's own account, where none of this applies and the watch can't count it. When a lead builds through subagents, they all drain the lead's own 5-hour window, and when it runs out, the lead and every builder stop at once.

So a lead or an orchestrator never starts a subagent to build, and a helper starts one only for a quick search or a browser check. The subagent guard holds every Colony session to `[subagents] max_running` (2) at once, and tells a lead past it how to open helpers instead; see [safety.md](safety.md#the-subagent-guard).

## The lead's own account

While you have other accounts, no helper opens on the account a live lead or orchestrator runs on, so the coordinator is never cut off by its own team. When the others are at their caps, a new helper waits for one to finish; when they are out of room, it waits for the soonest reset. When every account you have runs a lead or the orchestrator, no helper opens, and Colony says so and names the two ways out: set `[pool] share_lead_accounts = true`, or add an account with `colony accounts scan`.

In orchestrator mode, `colony plan start` places the group leads so one account stays free of leads for helpers: a group lead takes an account no lead runs on only while another such account stays free, and otherwise shares an account that already runs a lead, the orchestrator's or another group lead's, with room. With two accounts, the orchestrator and every group lead share the first, and helpers open on the second. With one account, `--account`, or `[pool] share_lead_accounts = true`, group leads take the plain pick. Colony knows those accounts from the lead that runs the command, each lead's heartbeat on this computer, and each live lead's status comment, on any computer, since an account's window is the same wherever it is signed in.

Most people have one AI account, so a lead's account is not closed to helpers for good. When it is your only account, `colony helpers --open`, `colony open` and `colony join` let helpers share it, with two limits that leave the lead room:

- **A lower cap:** at most one fewer helper than the account's cap, and at least one. With the default `max_busy` of 3, two helpers share the lead's account.
- **The lead's share of each window:** the fit check ([Plan around resets](#plan-around-resets)) counts the lead as one more busy session while no rate is measured, and opens a helper there only while the lead keeps 10% of each window until the window resets. A lead's account that is out of room takes no helper.

When that starts, Colony prints one plain warning, such as `Warning: account main is ana-main-lead's own, and the only account you have, so helpers share it: at most 2 at once, one fewer than its cap, and only while the lead keeps 10% of each window until it resets.` Past the lower cap, a new helper is refused, with why.

`--account <name>` still opens where you say. `[pool] share_lead_accounts = true` treats a lead's account as any other, with its full cap, also while you have others. To keep helpers off an account always, the lead's or any other, put it in `[pool] reserve`, which stays strict. `colony capacity` marks each account kept for a lead.

The same rule holds for every session Colony starts beside a lead: a researcher, spec agent or tester opens as a helper does, and `colony helpers <n>` asks you about the account its first helper would open on. A batch's reviewers, fixers and walkers keep off a live lead's own account too, from the leads this computer knows, and a rate-limited one moves only to another account. `colony join --in-session` makes the session that runs it a helper on the account it already runs on, which no session can change: on a live lead's own account, it says so in one line.

## Fresh readings

A usage reading is a copy saved when it was fetched, and an old copy looks just like a new one. So Colony fetches a live reading before it places a session, and every room line says how old its reading is, such as `main: 5h 40% (resets 23:50 UTC), week 63% (resets Sat 10:00 UTC), read 3 min ago`. That line shows in `colony who`, in every status comment, in the briefing, in `colony capacity`, in `colony watch` and on the status page.

A reading older than `[pool] stale_minutes` (15) never places a session. When a live fetch fails, such as for an account signed out or a computer offline, the account's room counts as unknown, its old numbers are not used, and it comes after every account with a fresh reading. A reading is fetched again once it is 10 minutes old, so `stale_minutes` is 10 at the least.

The lead runs `colony capacity` before it opens helpers and at least every 30 minutes while they run, and quotes an account's usage only with how old its reading is. Its wait also takes a live reading of every account on its computer every 10 minutes.

## Plan around resets

Each fresh reading of an account on this computer is kept for a day, with how many helpers ran on the account then, in `~/.colony/<project>/usage-history.json`. From them Colony works out each window's **burn rate**: how many percent its use rose an hour over the last hour of the 5-hour window, or the last day of the weekly one, and that rate divided by the helpers it ran, the **rate per busy helper**. Two readings of one window make a rate when they are at least 15 minutes apart for the 5-hour window, or 3 hours for the weekly one: usage comes in whole percents, so a shorter span of the slow weekly window would read one step as a fast pace.

At that pace, the **forecast** says when each window reaches `[pool] out_at`, and whether that comes before the window resets. `colony capacity` and `colony accounts` show it beside each account's reset times, such as `5-hour: runs out around 07:10 UTC, before it resets at 09:39 UTC (18.0% an hour); 6.0% an hour per busy helper, over 3.0 helpers`.

**Before a helper opens,** Colony checks it fits: the account's pace with one more helper there, from the account's own rate per helper, else the pool's average, else `[pool] helper_rate` (10% of the 5-hour window an hour), a guess used only until readings show the real rate. When the account would run out more than 15 minutes before a reset, the helper goes to the next account where it fits. When none fits, it waits, and the background run opens it right after the soonest reset. Set `helper_rate = 0` to check only against measured rates. `--account` opens where you say.

**The lead's wait warns ahead,** in plain words, once when the forecast first shows an account running out before its reset, and once more, as `urgent:`, when that is under 30 minutes away. It names the fewest helpers to move and the account with room for them, such as:

```
account main runs out around 07:10 UTC at its pace (30% of its 5-hour window an hour, with 3 helpers here), and that window resets at 09:39 UTC: move 2 helpers to team, which has room for them: as each finishes its card, stop it with `colony stop <name>`, and open the next one with `colony open <name> --account team`
```

When no account has room, it says to open no more helpers there and let the ones there finish. The warning counts the helpers on the lead's computer. The briefing names any account that runs out before its reset too.

## Finding accounts

`colony accounts` lists every account in the pool. Each one on this computer shows whether it is signed in, its live usage and reset times, how old the reading is, its helpers against its cap, and its forecast. An account whose folder is missing here says so. The accounts on other computers show as their sessions' status comments last showed them, with how long ago. New signed-in settings folders here come last.

`colony accounts scan` looks where `[pool] scan_folders` says (`~/.claude`, `~/.claude-*` and `~/.claude_*` by default) for signed-in settings folders that no `[accounts.<name>]` table names, and offers to add each one, named after its folder, such as `work` for `~/.claude-work`. In a terminal it asks for each; elsewhere it prints the command; `--add` adds them all. It finds Claude Code folders: an account of another provider is added by hand, with its `usage_command` and `auth_command`.

`colony accounts add <name> --dir <folder> [--person <person>]` writes the account into this computer's own layer, `.colony/colony.local.toml`, never the shared `.colony/colony.toml`, since a folder's path belongs to one computer. For an account the team's file already names, it writes only this computer's folder for it. The config must still load with it, or nothing changes. When `[people.<person>] accounts` lists that person's accounts by name, add the new one there too.

The briefing flags any of your accounts that is missing on this computer or signed out, and any new signed-in folder not yet in the pool. The lead's wait flags, in its digest, an account whose folder leaves this computer and a new folder that appears. An expired sign-in is the service check's to flag, as an `urgent:` line; with `[services] builtin = false`, the wait flags that too.

## When a usage limit resets

When a session's turn ends on its account's usage limit, Claude Code runs the StopFailure hook. Colony notes the session, its account and when that account resets, in `~/.colony/<project>/limited.json`.

Once the reset time has passed and the account has room again, Colony wakes the session, the least forceful way that works:

1. When the session's own `colony wait` still runs, it prints a line saying the limit reset, which wakes the session.
2. Otherwise the lead's wait, or `colony wake --follow`, wakes it. A background session that sits idle is stopped with `claude stop` and opened again under its own id, the way `colony resume` opens one ([safety.md](safety.md#recovery)): `claude --resume` on the account that holds its conversation, in the folder it started in, in cmux or the background, with a prompt to carry on. An idle session in a cmux window gets the prompt typed in. A session that is busy, or waits on a person's answer, is left alone.

`colony wake --follow` starts by itself when the hook notes a limit, or when a wait sees one noted, and stops once no session waits for a reset. Only one runs per project on each computer. It needs no lead and no wait, so a session still wakes when every wait on the computer ended during the limit.

## Service checks

Work stops when a sign-in expires or a limit runs out on any service the team relies on. Each service gets a check: a command and a pass condition. By default it passes when the command ends with 0. A check can also ask for text in the output, `expect`, or for its first number to be at least or at most a value, such as requests left on an API.

Colony always checks each account whose folder is on this computer (signed in, and with room) and GitHub's `gh auth status`. Add your own in `[services.<name>]`, such as a cloud CLI, a package registry, another AI provider or a local test database. Your own checks run in the repo's top folder. A local service's table can add `restart`, the command that starts it again, which `colony resume` runs when its check fails ([safety.md](safety.md#recovery)). `colony services` runs them all now. The lead's wait runs each one every `every_minutes` (30), and raises one `urgent:` line when a check starts to fail, with its `fix`, and one line when it passes again. Colony never prints a check's output, since a sign-in command can print a token.

## The right account

A session's account comes from the settings folder that holds its own transcript, `<folder>/projects/*/<session id>.jsonl`. The environment alone can be wrong: a background session can carry another session's `CLAUDE_CONFIG_DIR`. When no folder holds the transcript, `$CLAUDE_CONFIG_DIR` decides, with `~` expanded and links followed.

Colony opens each session with `COLONY_ACCOUNT`, the account it picked. When a session runs on another account than that one, or on an account `[pool] reserve` keeps free that nobody named for it, its lead gets one `urgent:` line saying so. `colony who`, `colony status` and every status comment show the account the session really runs on.

## This computer

Colony reads this computer with the Python standard library alone: its cores, its total and free memory (from `/proc/meminfo` on Linux, `sysctl` and `vm_stat` on macOS, and the system's memory call on Windows), the free disk where worktrees go, and its load (the 1-minute load average, or on Windows the share of busy cores).

From that it sets what runs at once:

- **Helpers:** the total memory past `keep_free_gb`, divided by `helper_gb`, at most the cores and `max_helpers` (`[project] max_builders` by default, 4).
- **Test runs and builds:** the cores not busy now divided by `test_cores` or `build_cores`, and the free memory divided by `test_gb` or `build_gb`, at least 1 each.

The computer is **busy** while its load per core is at or past `busy_load`, its free memory leaves less than one helper's share, or its free disk is under `keep_free_disk_gb`. While it is busy, no new helper opens here, test runs and builds drop toward 1, and the lead hears one line when it turns busy and one when it calms down.

## Locks

Some things only one run can use at a time, such as a shared local test database or a fixed port. Run such a command under a named lock:

```sh
colony lock test-db -- pytest -q
```

A second run waits for the lock, says who holds it, and gives up after `--wait` minutes (30 by default). A lock can have several slots, `[locks.<name>] slots` or `--slots`, so that many runs go at once; the command gets its slot number in `$COLONY_LOCK_SLOT`, so each run can use its own database or port. The locks `tests` and `builds` take this computer's test runs and builds at once as their slots. Everything else runs in parallel as far as the computer allows.

A lock is a file per slot in `~/.colony/locks/`, shared by every repo on the computer. A run that crashes frees its slot at once. `colony lock --list` names each held lock, who holds it and for how long.

Every check run that `colony fast-check`, `colony check run` or a batch starts holds a slot of `tests` by itself. To lock a check for every helper on something more, name the lock in `[checks] locks`, such as `locks = ["test-db"]`, and the command gets its slot in `$COLONY_LOCK_SLOT_TEST_DB`; see [checks.md](checks.md#every-check-fast-or-in-the-background). Or put the lock in the command itself, such as `fast_check = "colony lock test-db -- npm test"`.

## Sleep and wake

A computer that sleeps stops every process on it. Colony notices a sleep by comparing two clocks: the wall clock, which runs through sleep, and an awake clock, which doesn't. A restart of the computer shows as the awake clock going back.

The lead's wait and `colony wake --follow` both watch for it. After a sleep or a restart, they start again what stopped:

- each background helper Colony saw running before (it notes them every 5 minutes) that no longer runs opens again under its own id, as `colony resume` opens one;
- each idle helper whose wait stopped is woken, as for a reset limit;
- a helper in a window that closed is named, with `colony open <name>` to open it again.

`colony stop` removes the sessions it stops from that note, so a sleep never opens them again. After waking a computer whose lead wasn't running, run `colony wake --after-sleep` to do the same by hand.
