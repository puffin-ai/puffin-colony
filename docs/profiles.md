# Profiles: standing orders

A standing order is a rule or a setting a session follows without being told again, such as "never merge, open a pull request" or "wait 30 minutes for my answer". Colony keeps standing orders in profiles, so a new session starts already knowing how you and your team work, with no onboarding.

There are three levels. Your **personal profile** follows you into every repo. The **team profile** lives in the repo and applies to everyone. **Session settings** apply to one session alone. `colony profile show` lists every order in force and where each came from.

## The three levels

| Level | Where it lives | Who changes it | Committed |
| --- | --- | --- | --- |
| Personal | `profile.toml` in your user config folder (below) | You, with `colony prefer` and `colony profile set`, or by hand | Never |
| Team | `.colony/team.toml` in the repo | The team, through a reviewed pull request | Yes |
| Session | `~/.colony/sessions/<session id>.profile.toml`, beside the session's identity | You, with `--session` | Never |

**Your user config folder** is the first of these that applies:

1. `$COLONY_CONFIG_HOME`, when it is set.
2. On Windows, `%APPDATA%\colony`.
3. `$XDG_CONFIG_HOME/colony`, when `XDG_CONFIG_HOME` is set.
4. `~/.config/colony`.

Outside Claude Code, a session file is `~/.colony/<project>/<session>.profile.toml` instead, by the session's name.

**The team profile in force is the copy on `origin/<base>`**, the branch pull requests go to. A change to `.colony/team.toml` takes effect only when its pull request merges, so the team's orders change only through review. When your working copy differs, `colony profile show` says so. A repo with no `origin/<base>` uses the working copy, and `show` says that too. `colony profile init` writes the file with every team key commented out, and setup runs it.

## The format

A profile is a TOML file of settings in tables, plus free-text rules. Every key is optional.

```toml
mode = "speed"                  # personal and session only

[person]
role = "owner"                  # personal only

[decisions]
autonomy = "routine"
answer_wait_minutes = 30
without_answer = "hold"
never_raise = ["the office move"]

[tests]
full_suite = "release"

[merge]
policy = "pr"

[[rules]]
id = 1
text = "Answer first, then explain."
added = "2026-11-24"
from = "correction"
```

Colony writes `[person] name`, whose profile it is, and `[person] setup`, the day setup ran. A personal profile also keeps `[answers]`, your answers where the team's orders and yours disagree, and `[imported] declined`, the imported items you said no to. `colony profile keys` prints every key.

| Key | Kind | When the team's and yours differ | What it says |
| --- | --- | --- | --- |
| `person.role` | text | personal only | Your role on the team, such as owner or designer |
| `mode` | text | personal and session only | The named mode your sessions start in. A mode is a bundle of these settings, switched on with one word |
| `team.shape` | `lead` or `orchestrator` | you are asked once | `lead` runs its own helpers; `orchestrator` runs one lead per task group, and each lead reports to it |
| `team.max_leads` | whole number | the smaller wins | The most leads that run at once |
| `team.helpers_per_lead` | whole number | the smaller wins | The most helpers each lead runs |
| `decisions.autonomy` | `ask`, `routine` or `unattended` | the stricter wins | How much a lead decides alone: ask before every decision, decide routine choices and ask real ones, or decide everything with its recommended default and log each one |
| `decisions.answer_wait_minutes` | whole number | you are asked once | How long a lead waits for your answer |
| `decisions.without_answer` | `hold` or `default` | the stricter wins | With no answer in time: park that work and go on, or take the recommended default and log it |
| `decisions.never_raise` | list | both apply | Topics never to raise with you |
| `monitoring.check_minutes` | whole number | the smaller wins | How often a lead checks on its helpers and the team |
| `monitoring.report` | `quiet`, `progress` or `detailed` | you are asked once | How a lead keeps you posted |
| `pool.accounts` | list | only what both name applies | The AI accounts to use, by their names in `colony.toml`, in your order, as `[people.<person>] accounts` lists them there. Names only, never a credential |
| `pool.order` | `reset` or `listed` | you are asked once | Which account goes first: the one whose weekly window resets soonest, or your listed order |
| `pool.out_at` | 1 to 100 | the smaller wins | The percent of a usage window at which an account counts as out of room, and a session switches to the next one |
| `pool.max_busy` | whole number | the smaller wins | The most helpers busy on one account at once |
| `machine.max_helpers` | whole number | the smaller wins | The most helpers on one computer |
| `machine.max_tests` | whole number | the smaller wins | The most test runs at once on one computer |
| `machine.busy_load` | number, 0.1 or more | the smaller wins | The load per core at which a computer counts as busy, and less work starts |
| `tests.full_suite` | `change`, `batch` or `release` | the stricter wins | When the full suite runs: after every change, once per batch, or only at release, with the tests for the changed code and the guard tests in between |
| `tests.time_cap_minutes` | whole number | you are asked once | The longest a check may block anyone; a longer one runs in the background |
| `merge.policy` | `pr` or `branches` | the stricter wins | `pr`: agents open pull requests and you merge. `branches`: agents may merge into the branches `merge.branches` names |
| `merge.branches` | list | only what both name applies | The branches agents may merge into |
| `writing.style` | text | both apply | How agents write messages, docs, commits and pull requests |
| `writing.language` | text | you are asked once | The language a lead writes to you in |
| `budgets.dollars_per_day` | dollars | the smaller wins | The most a session spends a day on paid services and model calls without your yes |

The `pool.*` and `machine.*` keys have the names and units of the same keys in `colony.toml`'s `[pool]` and `[machine]` tables, so one name means one thing in both places.

For a choice, the stricter value is the one listed first: `ask` before `routine`, `hold` before `default`, `change` before `batch`, `pr` before `branches`.

## How the levels combine

On your side, a session setting beats a mode's, and a mode's beats your personal profile. The team profile applies to everyone, and where it and your side disagree, the key's rule in the table above decides:

- **The stricter wins**, for a choice with an order, such as `decisions.autonomy`.
- **The smaller wins**, for a limit, such as `machine.max_helpers`.
- **Both apply**, for lists of things to avoid and for writing style.
- **Only what both name applies**, for lists of things allowed, such as `merge.branches`. When the two lists share nothing, you are asked.
- **You are asked once**, where neither side is stricter, such as `decisions.answer_wait_minutes`. Until you answer, the team's value applies. Your lead asks you once, and `colony profile resolve <key> team|mine` records your answer in your personal profile. It is asked again only when either side's value changes. A session setting counts as your answer for that session.

Free-text rules from every level all apply. The orders a session sees say which rule settled each disagreement, such as "the team's says ask, ana's says unattended: the stricter, the team's, applies".

## Setup, asked once

The first time a lead starts for you, it asks a short set of questions, each with a default, and writes your personal profile. It never asks again. In a terminal, `colony profile setup` asks the questions itself. In an agent's session it prints them for the lead to ask in one message, and the lead writes your answers with `colony profile setup --set <key>=<value> ...`, or `--defaults`. A question you skip keeps a value your profile already holds, else takes Colony's default, unless the team profile sets that key: then nothing is written, so the team's value and its later changes apply to you. `colony profile setup --again` asks again.

## Learning from corrections

When you correct a lead, it offers once to keep the correction as a standing order, and on your yes runs `colony prefer add "<the rule>" --correction`. The prompt hook reminds the lead when your message reads like a correction. `colony prefer list` shows every rule in force with its ref, such as `p3` for your third personal rule, `t1` for the team's first and `s2` for a session's, and `colony prefer remove <ref>` drops one.

## Importing your preferences

`colony profile import` looks for preferences you already gave your agent tool: each Claude settings folder's `CLAUDE.md`, Claude Code's feedback and user memories for this repo, Codex's `AGENTS.md` and Gemini's `GEMINI.md`. `--from <file>` reads another file. Each list item and paragraph becomes a candidate with a short id. Nothing is added without your yes: in a terminal it asks about each one, and in an agent's session it lists them for the lead to ask, then `--accept <id>,<id> --decline <id>,<id>` records your answers. A declined item is never offered again, and an item that looks like a secret is never offered at all.

## Privacy

- Your personal profile lives outside every repo and is never committed. When its folder sits inside a git checkout that doesn't ignore it, such as a dotfiles repo, `colony profile show` says so.
- Personal and session files are readable by you alone.
- The team profile changes only through a reviewed pull request, since Colony reads the copy on `origin/<base>`.
- No profile holds a secret. A value or rule that looks like a key or a token is refused when you write it, and dropped when a file holds one, with a note that never shows it. Keep secrets in your secret store, and name the store in a rule instead.

## Seeing the orders

`colony profile show` lists the files read, every setting with its value and where it came from, every rule with its ref, and any note. `--json` prints the same as one JSON object, `--team-only` the team's orders alone, and `--orders` the standing-order text a session starts with, for a lead or, with `--role helper`, for a helper. A helper gets only the orders that concern its work, such as tests, merges, writing and budgets, and never asks you anything.

## Live changes

A change reaches the sessions already running, not only new ones. When a session starts, the prompt hook shows its standing orders once. After that, each session's `colony wait` looks at the profiles every minute, and a change ends the wait at once with the orders that are new and the ones that no longer apply. A session without a running wait sees the change before its next prompt. A change shows once: the hook and the wait share what each session has seen.

## Many people, one team

Each person's leads follow that person's profile, and the team profile applies to everyone. On a computer several people share under one login, each person's own profile is `people/<person>.toml` in the user config folder, and a `profile.toml` that names another person never binds your sessions. In work between people, such as a line to another person's lead, the team profile alone binds: `colony profile show --team-only` shows it.

## For tools that start sessions

`colony/profile.py` has a small Python API, described in its docstring:

- `load(root=None, person=None, *, config=None, session=True, layers=(), team_only=False)` returns the merged `Profile` for one session. `layers` takes extra levels, such as a mode's bundle built with `layer_from`, that sit between the personal profile and the session.
- `render(profile, role="lead")` returns the standing-order text for a lead's or a helper's start prompt.
- `show_lines(profile)`, `needs_setup(person)`, `QUESTIONS`, `change_lines(config, me)`, `watcher(config, me)` and `looks_secret(text)` cover the rest.
