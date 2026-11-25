# Capacity: accounts, limits and the computer

A team runs many sessions at once, on one or more AI accounts and one or more computers. This page says how Colony shares that out: which account each session uses, how many helpers open at once, what happens when an account hits its usage limit, how the team hears about expired sign-ins, how much one computer runs at once, how runs share a thing only one can use, and what happens after a computer sleeps. Every setting here is in [configuration.md](configuration.md), and every command in [commands.md](commands.md#capacity).

`colony capacity` shows all of it in one place: this computer's cores, memory, free disk and load, how many helpers, test runs and builds it runs at once, each account's room and helpers, the sessions waiting for a limit to reset, and the locks held. `--json` prints the same for a script or another command.

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
