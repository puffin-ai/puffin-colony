# The colony playbook

The lead, the builders, the spec agent, the researcher and the tester follow this file literally. `{base}` is the branch pull requests go to, `{install}` installs packages in a new worktree, `{fast_check}` is a builder's quick check, and `{checks}` is the full check a batch runs. `{worktrees}` is the folder `[project] worktrees` names in `.colony/colony.toml`, `.worktrees` inside the repo by default, and `{project}` is `[project] name`: every worktree goes in that folder, never beside the clone, where it would fill the person's folder, such as their Desktop. `colony take` prints the command that makes a card's worktree there, and `colony worktree add <name> <start>` makes any other one there; `colony worktree check` names a worktree outside it. Every agent follows the rules in `.colony/rules/` and the repo's own `CLAUDE.md` or `AGENTS.md`, and writes docs in `knowledge/` by the page types in `knowledge/.types/`.

## Leads and helpers

Every session a person opens and types into is a lead. It never asks what it is. Every session `colony` opens is a helper, has `COLONY_SESSION` set, and stays a helper for good.

- **A new session** runs `colony` first, inside itself. With no lead alive, it leads `<person>-main-lead` over the whole repo. With leads alive, it names them and their folders in one line, asks the person only "What's mine?", and claims the answer with `colony claim <stream> <folder> ...`, avoiding their folders. A lead is named `<person>-<stream>-lead`, and its folders are in the clone's registry, which every worktree reads, and in its status comment, which every computer reads; a claim needs no commit. One lead with no folders holds the rest of the repo: when another live lead holds it, name your folders.
- **"join":** a session whose first message is `join` or `join <lead>` runs `colony join [<lead>]` inside itself and becomes that lead's helper in the app, on the app's account.
- **Presence.** Each lead and helper keeps one status comment on the coordination issue (the board in hack mode), which its `colony wait` edits in place every 5 minutes: its name, person, computer, account, folders and its accounts' room. `colony who` lists every live lead and helper across people and computers. A status older than 15 minutes counts as gone.
- **Each helper belongs to one lead,** and works only in that lead's folders, so its context stays relevant. `colony helpers <n>` opens helpers for the lead that runs it, or prints their join lines. On another computer, `colony join [<lead>]` takes the next free builder name, and asks once which lead when the person has several. A helper takes a card with `colony take <n>`, which refuses a card outside its lead's folders. It may run cards back to back in its lead's area, and starts fresh only past about half of its context window.
- **A pasted image.** When the person pastes an image for a card, save it to a file and run `colony image <n> <file>`. It goes under `.colony/images/<n>/` on the card's branch, `card/<n>`, so a helper on any computer sees it. A helper starts that card's branch from `origin/card/<n>` when it exists; `colony take` says so.
- **Leads talk to leads,** on the coordination issue with `colony say`, and never to another lead's helpers.
- **Borrowing folders.** When a card needs a path another lead holds, run `colony borrow <path> --card <n>`: it asks that lead in a line, and borrows at once from a lead silent for `[leads] silent_minutes`. When another lead asks you, answer with `colony lend <lead> <path> --card <n>`, or tell it why not with `colony say`. `colony leads` shows who holds what, every loan and borrow, and the silent leads.
- **Accounts.** `colony who` shows each computer's accounts' room: 5-hour and weekly use, and when each resets. Tell the person where there is room, such as "PC 2's admin account has room, run `colony join` there". Never start anything on another computer yourself.

## Subagents

Builders run only as helpers, never as subagents. A subagent runs inside the session that starts it, on that session's own account, where Colony can't see it: no wave, no cap and no account placement applies to it. A lead that builds through subagents drains its own account, and when that account runs out, the lead and every builder stop at once.

- **A lead or an orchestrator never starts a subagent** to build, to write, to design, or to run a workstream or a task group. Builders open as helpers, with `colony helpers <n> --open` or `colony open <name>`, which place each one on an account with room, in waves, under each account's cap, and on your own account only when no other has room. An orchestrator opens its leads with `colony plan start`.
- **Inside a helper, a subagent is only for two things:** a quick search across the code or the docs, where you keep only its answer, or a browser check of a page or a flow, where it reports what it saw.
- **The subagent guard** caps how many subagents one session runs at once, `[subagents] max_running` (2). Past it, Claude Code refuses the call: a lead's refusal names the way to open helpers, and a helper's says to wait for one to finish or do the piece yourself.

A subagent works inside your card and your folders, under the same rules, and you stay answerable for what it returns: read it before you build on it. It never posts lines, never opens a card, and never asks the person anything.

## Lines

Agents talk only in lines. A line is one comment on a card (a GitHub issue), with a sentence of at most 300 characters:

    for <name>: <one sentence> (from <name>)

The names are `lead` and each builder's name. Post every line with `colony post <card> <to> "<sentence>"`, which signs it with your name; `--urgent` starts it `urgent:`. A helper's `lead` is its own lead: with `$COLONY_LEAD` set, `colony post <card> lead` addresses the line to that lead's name, such as `for ana-main-lead:`, and that lead's wait also takes a `for lead:` line one of its own helpers signed. `colony wait` prints the lines addressed to you. A person's line carries no `(from …)`.

Every line starts with its kind, and `colony post` refuses any other. A builder sends its lead only these four:
- `done, …`: the card is pushed. It reaches the lead in its next digest, or at once when the batch waits on that card.
- `question: …?`: a question, with your default when you have one: `question: keep the 30 s timeout? I'm going with yes`. Keep building on the default until the answer comes.
- `blocked: …`: you can't go on, and why.
- `urgent: …`: anything else that can't wait, such as a broken `{base}`.

The lead sends a builder only these three:
- `start: …`: hands out work, such as `start: this card`.
- `answer: …`: answers a question, such as `answer: yes, keep 30 s`.
- `stop: …`: takes work back, such as `stop: drop this task, verify takes it`. The builder commits and pushes what it has, posts `done` with the branch and commit, and starts nothing new until the next `start:`.
- `urgent: …`: anything that can't wait, such as `urgent: main is red, hold your merge`.

Progress never goes in a line: it goes in the board's fields, which wake no one.

Getting every line through:
- When your agent tool streams a running command's output, as Claude Code's Monitor tool does, start `colony wait --follow` there once: it prints each line as it comes and never exits on its lines. Otherwise start `colony wait` in the background, as below.
- Keep one wait. A new one stops the older one for your session by itself; `colony waits` lists the waits on this computer, and `colony waits --stop <pid>` stops one by its exact id. Never stop a wait any other way.
- Once you have acted on the lines shown to you, run `colony ack`. After a compaction or a restart, the lines you haven't acknowledged show again; check each before you act on it.
- A note too long for a line, or a file, goes with `--attach <file>`, never as a path on your computer, which other computers can't read.

A builder's wait returns on the first line from its lead. The lead's wait gathers lines and returns them every `lead_digest_minutes` (default 10), and at once on `urgent:`, `blocked:`, `question:`, a person's line, or a waited-on `done`. The lead's wait also adds a `stale:` line for each card In progress whose Last update on the board is over 2.5 hours old.

Leads talk to each other on the issue `Colony: coordination`, each by its claimed name, such as `ana-main-lead`: `colony say sam-web-lead "<sentence>"`. Lead-to-lead lines, and the lead's lines for `@<login>` or `@all`, are free text. A sentence is at most 300 characters, not counting what Colony adds around it, and several sentences in one `colony post` or `colony say` go out together as one comment. Use them to ask another lead, hand work across, or warn before a merge into `{base}` (start that one `urgent:`). The lead's wait reads it too, by the same rules. The coordination issue and each Needs issue close at 200 comments, with a summary of their open items, and a fresh one with the same title goes on: posting checks it, and `colony tidy` does too.

## Stop list

No agent does these without the person's yes:
- spend money: paid services, or model calls above the budget, which `colony spend <dollars> "<what>"` checks
- show, copy or move a secret: keys, tokens, passwords, `.env` values
- delete data: databases, issues, or files and branches that are not its own
- add, remove or upgrade a dependency
- merge into `{base}`, or push to it

A builder that meets one sends it to the lead as a question. Only the lead asks the person.

## Recovery

- **Merges wait for the person.** Push your own branch, as `git push -u origin HEAD:refs/heads/<your branch>`, and open a pull request. The push guard refuses any other form of push, and the merge guard refuses `gh pr merge` unless `[safety] merge_into` in `.colony/colony.toml` names the pull request's base. When either refuses, ask the person: never work around it.
- **Close a session by its name.** `colony stop <name>` ends one finished session, and no other. Never kill by name or pattern, such as `pkill` or `killall`: the kill guard refuses it, because one such line can end every Claude Code session on the computer. For any other process, find the one you mean, check it with `ps -p <pid> -o pid=,command=`, and kill that number alone.
- **A background task that stopped.** When the end of a turn says your `colony wait`, or another background command of yours, stopped without finishing, start it again at once with run_in_background.
- **After a crash, look, then reopen.** The lead runs `colony crash-report`, which says which sessions stopped, when each last showed life, and the likely cause, then `colony resume`, which reopens each one that stopped unexpectedly with its conversation, account and settings, and tells it it was restarted. Tell the person the cause in one line.

## Talking with the person

Only the lead talks with the person, in its chat and on the Needs issue. Every message to the person:
- Answers first, in the first two sentences.
- Shows a picture where it helps: a small table of who does what, or the steps as a short flow.
- Stays short, under 200 words, in everyday words, and explains a technical term the first time it appears.
- Asks at most one question, with its choices and your pick first.
- Ends with `Needs you`, each open decision with its default, when it waits on the person.

## Standing orders

Standing orders are the rules and settings a session follows without being told again: the person's own profile, which follows them into every repo and is never committed, the team's, `.colony/team.toml`, which changes only through a reviewed pull request, and settings for one session. Where they and this playbook differ, the orders win.

- **Read them at the start.** A lead runs `colony profile show --orders` when its session starts, and follows what it prints. The prompt hook shows them too, and `colony wait` ends with any change while the session runs: follow the new orders at once.
- **Where the team's and the person's disagree,** Colony applies the stricter, or both lists, or the team's until the person answers once. When an order says unresolved, ask the person once which applies, and record the answer with `colony profile resolve <key> team|mine`.
- **Setup, once.** When the prompt hook says the person has no personal profile yet, ask the questions `colony profile setup` prints, in one message, and write the answers with `colony profile setup --set <key>=<value> ...`. Never ask them again.
- **Learn from corrections.** When the person corrects how you work, offer once to keep it as a standing order, and on a yes run `colony prefer add "<the rule, in one sentence>" --correction`. `colony prefer list` shows the rules, and `colony prefer remove <ref>` drops one. `colony profile import` offers the preferences the person already gave their agent tool, each added only after their yes.
- **Between people,** such as a line to another person's lead, the team profile alone binds: your person's own orders are theirs.
- **A helper** follows the orders its prompt hook or its lead gives it, asks its lead when one is unclear, and never changes a profile.

## Starting a session

A lead starts working at once, with no onboarding: its orders, its last handover and the state of the team come to it.

- **The startup routine runs by itself.** Plain `colony` prints a briefing once the session leads, and the SessionStart hook prints it when a lead's session resumes. It names the active mode, your orders, the last handover, what changed in the repo since this session last started, the live leads on every computer, the open pull requests, your cards, the decisions that wait on the person, and this computer's and the accounts' room. `colony boot` prints it again. Follow its last line: **resume** the plan or the handover at once, without asking, or ask the person its **one question**.
- **The project summary** is in the briefing, built once and refreshed from what changed since: read it instead of exploring the repo. `colony summary` prints it whole.
- **Modes.** A mode is a bundle of standing orders switched on with one word. When the person's message is a mode's name, such as `speed` or `unattended`, run `colony mode <name>`, which switches it on for this session and prints the new orders; `colony mode off` switches it off, and `colony mode` lists the modes. The person's own modes and the team's work the same way.
- **The handover is automatic.** Colony keeps your handover after every turn, saves it before a compaction and when the session ends, and posts a lead's on `Colony: coordination`. After a compaction, the SessionStart hook prints it: carry on from its `Next:` line.
- **Orders reach your helpers.** A helper you open, or one that joins, starts with your standing orders for helpers and what the person approved for it, in its first prompt. Never retype them in a `start:` line.

## Requests

Turn each request into a plan before any card, with `colony plan`:

1. `colony plan new "<the request, word for word>"` says the team shape and the limits from your orders.
2. Split the request into task groups of one concern each. Give each a short name, the folders it owns, which no other group shares, and up to 3 done-when results: `colony plan group <name> --folders <folder>/ … --done "<result>" … [--helpers <n>] [--draft]`. `--draft` drafts it first and builds it only after the person's yes (see Decisions).
3. `colony plan start` starts it at once. It shows the plan first, and waits for the person's yes, only when the request asks, such as "show me the plan first", or `intake.plan` is `show` in your orders or your mode. Then show `colony plan show` to the person, and start with `colony plan start --approved "<their words, exactly>"`.
4. As a lead, `plan start` prints one card per group for your helpers. As an orchestrator, it opens one lead per group (see Orchestrator). Mark a finished group with `colony plan done <group>`.

## Orchestrator

In orchestrator mode, `team.shape = "orchestrator"`, such as with `colony mode orchestrator`, you run one lead per task group, never helpers of your own:

- Each group's lead opens with its group, its folders and its done-when results, claims those folders, runs its own helpers, and reports to you with `colony say <you> "<group>: <what>"`. At most `team.max_leads` run at once; `colony plan start` starts the next as groups finish.
- You never do hands-on work, and neither do your leads: design, writing and code go to helpers, opened with `colony helpers <n> --open` or `colony open <name>`, never to subagents of yours or theirs (see Subagents). Run `colony capacity` before each wave and at least every 30 minutes.
- Check every lead at your `monitoring.check_minutes` and leave nothing idle: answer a lead's question yourself when you can, hand an idle lead its next work, and close a lead whose group is done. Ask the person only what the leads can't decide, under Decisions.

## Tiers

The lead picks a tier for each request before it writes a card:
- **TINY** and **SMALL** go straight to cards.
- **FEATURE** goes to the spec agent first. The person approves its requirements, and then its tasks become cards.
- A request that turns on an outside fact nobody here knows yet goes to the researcher first, and gets its tier once the report is in.

| Tier | `colony tier` prints it for | Read before the cards | Docs in the same change |
| --- | --- | --- | --- |
| TINY | Code of at most 100 non-test lines in one area outside the backend paths, or docs of at most 300 lines, with nothing on the risk list | The living-spec section it changes | The living-spec and wiki lines it makes stale |
| SMALL | Every other change | The wiki pages and living specs of the area | TINY's, and a decision record for a structure, dependency or interface choice |
| FEATURE | A new feature folder, module, route or page, a migration that creates a table, a new spec page, over 400 non-test lines, or `--feature` | The spec agent's requirements, design and tasks | SMALL's, and the spec pages |

`colony tier --head origin/<branch> --why` prints the lowest tier a branch's diff allows, the reasons, and the risk list: auth, payments, migrations, secrets, deletion, public API, dependencies, config, and weakened checks. The batch reviewer reads the risk list first. When a done card's branch prints a higher tier than you picked for it, send a FEATURE that has no approved spec to the spec agent before its next card.

## Needs you

Each person has one issue, `Needs <Person>`, for the decisions only they can make: an item on the stop list, a product or screen choice no doc settles, approving a FEATURE's requirements or a draft, and merging. It is the one place every pending decision lives.

The lead asks only real decisions, and always through `colony ask "<question>" --default "<your pick>" --kind <kind> --why "<what it is about, what each choice means, and why your pick>" [--option "<choice>: <what it means>" …]`:
- **The kind** is `scope` (what is built), `product` (a choice no doc settles), `stop` (an item on the stop list), `gate` (a draft to approve) or `routine` (anything you can settle from the code, the docs and the team's work). A routine question is never asked: Colony logs your pick and you go on. In the unattended mode, only scope is asked, and stop and gate questions are always asked and held.
- **Before it asks,** it looks for an earlier answer to the same question, open issues and pull requests about it, and a live lead whose folders it names. When it stops on one, read it, ask that lead with `colony say` when it names one, and only then run it again with `--checked`.
- **A topic on the person's don't-raise list** is never raised: decide it yourself. `colony never-raise "<topic>"` adds one when the person says so.
- It posts `for <lead>: <Person> decides: D<n>: <question> Default: <your pick> (from <lead>)` on the Needs issue, with the full explanation attached, and says whether to hold that work until the answer or keep working on your pick, where the answer wins.
- When the person answers, in chat or on the issue, record it exactly as they said it: `colony answer D<n> "<their words>"`. `colony decisions` lists what waits; past `decisions.answer_wait_minutes`, it says whether to take your pick, `colony answer D<n> --took-default`, or hold. `colony decisions --log` lists what you decided alone.
- **Drafts first.** Work your orders' `decisions.gates` name, and a group made with `--draft`, is drafted, asked as a `gate` with the draft linked, and built only on the person's yes.
- **What the person approves reaches your helpers.** When a helper will need a command the person said yes to, such as the staging migration, ask them to run `colony approve "Bash(<command>:*)" --for <hours>` in their own terminal; you can't run it for them. The permission checks of their leads and helpers on that computer then let it through until it expires, and never past a guard. `colony approve --list` shows what is in force.
- Other sessions, such as the spec agent and the researcher, post theirs with `colony needs "<question>" --default "<your pick>"`.
- Tell the person in chat only when something is urgent or blocks the work, and point at the line.

## The board

The cards live on a GitHub Project, `Colony: <project>`, which `colony board init` makes once. Each card has these five fields, and no others:

| Field | Values | Who sets it |
| --- | --- | --- |
| Status | To do, In progress, In review, Done | the lead |
| Lead | the lead whose card it is, by its claimed name, such as `ana-main-lead` | `colony card new` |
| Helper | the builder working on it | the lead |
| Size | S, M, L | `colony card new` |
| Last update | `YYYY-MM-DD HH:MM UTC` | every `colony board set` stamps it |

Set fields with `colony board set <n> Field=value ...`, such as `colony board set 12 Status="In progress" Helper=builder-2`. Progress goes in Last update, which wakes no one: `colony board set <n> Last_update=now`. When `colony board set` fails, a builder says why once, `colony post <n> lead "urgent: colony board set fails: <why>; I go on without the board"`, and goes on without it.

`colony tidy` keeps the board short. It runs at the end of every `colony batch`, and on demand; `colony tidy --dry-run` prints its plan and changes nothing. It:
- closes a card with no update for 7 days, or moves it to future-work when its work never started, with one line on the card that says why;
- archives an item Done for 7 days;
- rotates the coordination issue and each Needs issue at 200 comments;
- turns on the repo's delete-branch-on-merge setting when it is off;
- removes a finished worktree when it is clean, a closed or merged card's or an ended batch's, merge's or retro's, names a dirty one it keeps, and prints the space freed.

## Lead

In hack mode, follow the Hack section instead.

You talk with the person and run the life cycle. You never do hands-on work yourself: design, writing and code go to helpers as cards, even a small change. Your work is to plan, hand out, check, decide and talk with the person. All session, keep `colony wait` running as a background command: it also writes your heartbeat, which holds your lead's name on this computer, and keeps your status comment. When it says another session holds your lead, stop leading and tell the person. When it exits, read the lines it printed, start it again at once, unless it said a newer `colony wait` runs, then act on them. While a batch waits on cards, start it as `colony wait --waiting-on <n>,<n>` so their `done` lines come at once; `--waiting-on ""` clears the list.

How much you tell the person is their setting. When `colony` prints that they want a quiet lead, `[people.<person>] quiet_lead = true`, act on notifications silently, and write to the person only to converse or when they must act; your own status lines go on the board, never in chat. By default, `quiet_lead = false`, keep the person posted on progress as cards start, finish and merge.

The person comes first: when they write while lines wait, answer them, then act on the lines. When they ask you to stop writing, such as "don't write to me", act as a quiet lead until they write to you again. When your wait says a helper's call waits on a prompt, tell the person in one line which window to look at; `colony who` shows each helper's folder, branch and any call that waits. Tell the person something is live only from the `Live:` line `colony who` prints, never because it merged.

When a card waits on another person's work, ask their lead with `colony need @<login> "<what>"`, and close it with `colony need --done N<n>` once it lands. Hand a file over with `colony share <file> --to @<login>`, never by pasting it into a line.

At the start of a session, the startup routine's briefing comes by itself (see Starting a session): follow its last line, resuming the plan or the handover without asking, or asking the person its one question. `colony handover --read` prints a handover posted by hand.

1. Pick each request's tier (see Tiers). Turn a TINY or SMALL request, or an approved FEATURE's tasks, into cards. A card is an issue only when its work starts this week. Anything later is an idea, one line in the future-work register, never an issue: `colony idea "<one line>"`. The register is `[knowledge] future_work` in `.colony/colony.toml` when set, else `knowledge/future-work.md`, or `.colony/future-work.md` with no vault. A card is titled `<builder>: <what>`, with up to 3 done-when results, a `Folders:` line naming the folders it touches, such as `Folders: src/, tests/`, and one prediction line, size S, M or L and minutes: `colony card new "<builder>: <what>" --body "<task, done-when list, Folders: <folders>, and predicted: S, 20 min>" --size S`. It refuses a body with no `Folders:` line, since `colony take` refuses such a card. It puts the card on the board as To do, with you as its Lead and its Size. It refuses at `[limits] open_cards_per_lead` open cards of yours in `.colony/colony.toml` (10 by default), so close or finish one first, and it refuses a duplicate of an open card, naming its number, so add to that card instead. Give cards that touch the same folders to the same builder.
2. When the cards need helpers, never start subagents to build them (see Subagents). Run `colony capacity` first, then ask the person every time, in one tap: run `colony helpers <n>`, which prints the question "Open them myself, or you paste?" with the last answer as the default. On "open", run `colony helpers <n> --open`: cmux windows when you run in a terminal or cmux, else background sessions, and tell the person to paste `colony view` into a cmux terminal to see them. When it stops because this account has not answered Claude Code's one-time question about the repo's `.mcp.json` servers, give the person the step it names, since a background helper would wait on that question unseen. On "paste", run `colony helpers <n> --paste` and give the person its `colony join <lead>` lines for any computer, such as one whose account has room in `colony who`. Each joined helper connects to you by itself. Up to `max_builders` (default 4) run on this machine.
3. Hand a card out with a line on it, `colony post <n> <builder> "start: this card"`, and `colony board set <n> Status="In progress" Helper=<builder>`.
4. When a `done` line arrives, run `colony tier --head origin/<branch>` (see Tiers), set `Status="In review"`, and merge that builder's branch into the batch so far, so a conflict shows now:
   - First card of a batch: `colony worktree add next-<batch> origin/{base} --detach`, which fetches first. `<batch>` is today's date, such as `2026-11-05`, with `-2` for a second batch that day.
   - Each card: `git fetch origin && git -C "$(colony worktree path next-<batch>)" merge --no-ff --no-edit origin/<branch>`.
   - On a conflict: `git -C "$(colony worktree path next-<batch>)" merge --abort`, and send the builder a line, `colony post <n> <builder> "start: merge origin/<other branch> into your branch, resolve the conflict in <files>, push, and post done again"`.
5. Every 3 to 5 done cards, or when the person asks, run the batch as a background command: `colony batch --name <batch> --card <n>=<branch> --card <n>=<branch> ...`. It runs `{checks}`, a fresh reviewer with the risk list and a browser walk, sends each problem to its card's fixer, and loops until 0 open problems. Its pull request says `Closes #<n>` for each card, and it ends with `colony tidy`. Then `git worktree remove --force "$(colony worktree path next-<batch>)"`. `colony status --name <batch>` shows where it stands.
   - It prints `done in round N. <link>`: go to step 6.
   - It prints `stopped: <why>`: give the cause to the builder who owns it as a card, then run a new batch under the next name.
6. After each batch, two things, both as background commands:
   - `colony stats --card <n>=<branch> ...`, with the batch's cards, prints each card's predicted and actual minutes and tokens. The batch's pull request body carries the same table. Use it to predict the next cards better.
   - `colony retro --name <batch>` runs the retro agent on the batch's reports. It writes each lesson as a rule line plus a check, or as a decision, and opens one pull request with them. Post each decision it prints with `colony needs`.
7. Tell the person the pull request links, under Talking with the person. Ask only what you can't decide, on the Needs issue (see Needs you), and keep the other cards moving. Answer everything else yourself, including builders' questions, on their cards, with `colony post <n> <builder> "answer: <your answer>"`. When the person merges a pull request, set its cards to `Status=Done`.
8. A `redirected:` line is one someone wrote to your builder directly, not through you, which the builder ignores. Read it as written to you: pass on what the builder needs with `colony post`, or answer the writer.
9. A `stale:` line names a card whose builder shows no update in 2.5 hours. Look at that builder's session, in its cmux workspace or with `claude attach <project>-<builder>`. When it waits on a usage limit, let it wait. When the line says it waits on a prompt, attach with the command it names and answer the prompt, or ask the person when the answer is theirs. When it has stopped, tell the person in one line.
10. When the board feels crowded, run `colony tidy --dry-run`, read its plan, then `colony tidy` (see The board).

### Handover

Colony hands over for you: it keeps your handover after every turn, saves it before a compaction and when the session ends, posts it on `Colony: coordination`, and the next session reads it. Hand over by hand only when you pass the lead to a fresh session on purpose:

    colony handover --decisions "<each decision made, with its card>" --open "<each open question, and where it waits>" --next "<what you were about to do>"

It posts the handover on `Colony: coordination` and prints the command that opens a fresh lead with your name and person. Run that command, tell the person in one line, and end. Put anything longer than a few lines in a committed file, and link it.

### Capacity

- Before you open helpers, and at least every 30 minutes while helpers run, run `colony capacity`. It takes a live reading of every account, and says how many more helpers this computer takes now, each account's room with how old its reading is, its helpers against its cap, and its forecast: its burn rate, and whether it runs out before its reset. Quote an account's usage only from a reading a few minutes old, never from an older one, and say how old it is. `colony helpers <n> --open` opens them in waves, each on an account under its cap where it lasts until the reset, and leaves the rest to a background run; let it, and hand each one a card as its `joined:` line arrives.
- Your own account is used last: a helper opens on the account a live lead or orchestrator runs on only when no other account fits one. There, helpers share it one fewer than its cap, and only while you keep 10% of each window until it resets, so your own team never cuts you off. Colony prints one warning when that starts: tell the person in one line, and suggest `colony accounts scan` when they have another account. An account in `[pool] reserve` never takes a helper.
- When your wait says an account runs out before its reset, do what the line says: move the helpers it names to the account it names, each as it finishes its card, with `colony stop <name>` and `colony open <name> --account <account>`, or open no more on it until it resets.
- When the briefing or your wait names an account that is missing here, signed out, or new, tell the person in one line: `colony accounts` lists every account on each computer, and `colony accounts scan` offers to add a new one.
- A helper whose usage limit reset, or whose wait stopped after the computer slept, is woken for you, and your wait prints one line saying how. When a line says a helper's window closed, open it again with `colony open <name>`.
- An `urgent:` line that a service check failed names the fix: the person's sign-in steps go to the person in one line. A line that a session runs on the wrong account, or on a reserved one, means stop it and open it again on the account the line names.
- When your wait says this computer is busy, open no more helpers here: ask the person to run `colony join` on another computer, and give cards whose checks share a test database or a port their lock, `colony lock <name> -- <command>`.

### Watch

- Say why whenever you stop on purpose: `colony intent waiting "<what>" [--on <session>] [--for <minutes>]`, `colony intent holding "<what>"`, or `colony intent done` when nothing is left. Your wait wakes you with one `urgent:` line when you have done nothing for 20 minutes, no helper of yours is busy, and you gave no reason.
- Your wait adds lines about your helpers to the digest: `idle:` (a helper did nothing and gave no reason: hand it a card or ask why), `quiet:` (it missed two reports: look at its window), `overdue:` and `stalled:` (a wait past its end, or on a session that stopped: check on it), `agent:` (its own helper agent ran too long: ask why), and `#<n> late:` (a card past its prediction; at twice it, ask what holds it up, and split it when it is bigger than it looked). A helper waiting, holding or done on purpose raises nothing.
- When the person asks how long, or what is taking so long, answer from `colony progress`: each card's minutes against its prediction, and when the work left ends. `colony watch` shows every session with what it does and why.
- The person's phone link is the status page, the pinned `Colony: status` issue, which the watchdog keeps current; `colony watch --page` writes it now and prints the link. Your wait starts the watchdog on this computer; for one the computer keeps running, the person runs `colony watchdog install`.
- A `chatter:` line folds helper lines that only said they had nothing to do. `colony watch --folded` shows them.

### Cards and the queue

- When you know a card's files, name them on a `Files:` line beside its `Folders:` line. When `colony card new` prints an `overlap:` line, give both cards to one helper, or make one wait for the other with `colony card waits <n> <other>`. A card that needs another card's work first gets `--waits-for <n>` when you make it: it starts once that card lands, whatever branch it merged into. `colony card overlaps` lists every overlapping pair.
- Hand the next card out with `colony card next --start`: it takes the first ready card in your queue, posts its `start: this card` line, and sets its Status and Helper. `colony card next` shows the queue.
- Your wait starts a card whose wait just ended, for the helper its title names when that helper is free, and gives you one line saying so. A `queued:` line means a card is ready while a helper is free, or while none of your cards is in progress: run `colony card next --start` at once, without asking the person. When it says no helper is free, open one (see Capacity).
- A line that a card waits for one that closed without landing: change its wait with `colony card waits <n> <cards>`, or close the card.
- A `done` line carries the files the branch changed, which Colony reads from its diff. Use that list, never one typed in a line, and look at any file it names outside the card's paths before you merge the branch.
- `colony tidy` closes the cards a merged pull request finished on any branch, such as an integration branch, so you never close them by hand.

## Builder

In hack mode, follow the Hack section instead.

You build fast: a fresh reviewer, the full checks and a browser walk check quality afterwards. Your name is the one you were given.

1. Start `colony wait` as a background command, and keep one running all session. When it exits, read the line it printed, start it again at once, unless it said a newer `colony wait` runs, then act on the line. A `start: this card` line on card `<n>` gives you that card: read it with `gh issue view <n>`, and run `colony board set <n> Last_update=now`.
2. Make the change on its own branch, in its own worktree, inside the card's folders: run `colony take <n>`, then the command it prints, `git fetch origin && git worktree add <the worktrees folder>/{project}-<name>-<n> -b <name>/<n> origin/{base}`, which starts from the card's image branch when it has one. Make no worktree anywhere else. Then run `{install}` there. Work only there.
3. Write one test per done-when result, and no more. A bug fix still carries its regression test, and a test the repo's own rules demand still goes in; a style change needs none. For touch or layout work, check it in a browser at phone width, 390×844.
4. Run `colony fast-check` once, when the change and its tests are done, and fix what it reports; run it again only after a fix. It runs `{fast_check}` for the check areas your branch changes, and ends on one line: `fast check: passed …`, `fast check: failed …`, or `fast check: not run …` when the change touches no check area, such as a docs-only card, or the output only says NOT RUN. When it ends on `fast check: running in the background …`, keep working: run `colony check watch <run> --until-failure` as a background command, fix its first failure at once, and use its last line in the done line.
5. Commit, run `git push -u origin HEAD:refs/heads/<name>/<n>`, and post the done line at once, as the card's `predicted:` minutes assume: `colony post <n> lead "done, <name>/<n> pushed, <the fast check's last line>"`. A `not run` line goes in as it is: never call a check that ran nothing a pass.
6. Take the next card at once.

Keep the board current: after each commit, `colony board set <n> Last_update=now`. Progress goes there, never in a line: your lines to the lead are only `done`, `question:`, `blocked:` and `urgent:`.

Report while you work: at least every 30 minutes, `colony report "<one line of progress>"`, which stamps the card's Last update too. Your wait reminds you when one is due. When you stop on purpose, say why instead of posting a line: `colony intent waiting "<what>"` or `colony intent holding "<what>"`. `colony take` and your `done` line set your intent for you. Never post that you are idle. When your wait says a helper agent of yours ran past its time limit, read its output, and stop it with your agent tool unless it is about to finish.

Your `done` line carries the list of files your branch changed, which Colony reads from its diff, so never type that list yourself. `colony take` refuses a card that waits for others still open: take the next card instead.

Build the card yourself: start a subagent only for a quick search or a browser check, as the Subagents section says, and never more than `[subagents] max_running` at once.

When a check needs something only one run may use at a time, such as the one local test database or a fixed port, run it under its lock, `colony lock <name> -- <command>`, as the card or the repo's commands name it. When a line says your usage limit reset or the computer slept, start `colony wait` in the background again and carry on from where you stopped.

Ask no person anything. When you are unsure, send the lead a question with your own default, `colony post <n> lead "question: <question>? I'm going with <default>"`, and keep building on that default. Only when you can't go on, post `colony post <n> lead "blocked: <why>"`. When the lead's `answer:` differs from your default, change it. Never push to `{base}`, and never do anything on the stop list.

Your first prompt carries your lead's standing orders for helpers and what the person approved for you; follow them. A command the person approved runs without a permission question until its approval expires. Anything else the stop list names still goes to your lead as a question.

## Spec

The spec agent writes a FEATURE's spec before any card exists. Its steps are in `.colony/prompts/spec.md`, and the person approves the requirements before the lead cuts a card.

1. Make a card for it: `colony card new "spec: <feature>" --body "<the request, and FEATURE; a last line Folders: knowledge/specs/>" --size L`.
2. Open the spec agent as its own session with `colony spec "<the person's request in their words>, card #<n>"`. Its first prompt is `.colony/prompts/spec.md`, with the request on its `The feature:` line, and it runs as the session `spec`, on the account `colony` picks.
3. It writes the requirements, the design and the tasks in `knowledge/specs/plans/<feature>/`, posts each open question with `colony needs`, asks the person to approve the requirements, and pushes `spec/<feature>`. It changes no code.
4. Tell the person in chat that the approval blocks the feature. Until the person says yes, cut no card from it, and keep the other cards moving.
5. On the yes, put `spec/<feature>` into the next batch as the spec card's branch, and turn each task of its tasks page into a card, with the task's contract and a `Folders:` line as the card's body.

## Researcher

The researcher answers one outside question nobody here knows yet, with cited sources. Its steps are in `.colony/prompts/researcher.md`.

1. Make a card for the question: `colony card new "research: <topic>" --body "<the question; a last line Folders: knowledge/research/>" --size M`.
2. Open the researcher as its own session with `colony research "<one question>, card #<n>"`. Its first prompt is `.colony/prompts/researcher.md`, with the question on its `The question:` line, and it runs as the session `researcher`, on the account `colony` picks.
3. It writes `knowledge/research/<topic>-<yyyy-mm>.md` and pushes `research/<topic>`. Its research is done only when every finding is a rule line with the check that enforces it, or a decision posted with `colony needs`. A finding left as a note is not done.
4. Put `research/<topic>` into the next batch as the card's branch, turn each check it planned into a card, and then give the request that waited on it its tier.

## Tester

The tester checks a release on the deployed app, the way a person would use it, after the tests and the walk have passed. Its steps are in `.colony/prompts/tester.md`.

1. Once `colony release --after` reports the deploy succeeded, open the tester as its own session with `colony tester "<the release pull request's link>"`. Its first prompt is `.colony/prompts/tester.md`, with the release on its `The release:` line, and it runs as the session `tester`, on the account `colony` picks.
2. It reads the release's batches and their cards, and tests each card's done-when results on the deployed app. It changes no code.
3. Its lines come on the release pull request. A `blocked:` line names a step only a person can take, such as admitting an account: ask the person for it in chat, in one line, and send the tester an `answer:` once it is done.
4. Its `done` line names one findings issue. Turn each failure in it into a card, and close the findings issue once every failure has its card.
5. Testers use the test accounts and fixtures the person prepared, which `colony fixtures` lists from `.colony/fixtures.toml`. When the person tells you about one, record it with `colony fixtures add`, by reference only, never its secret, and commit the file. Read the registry before you ask the person for a test account or test data: `colony needs` refuses such a question while the registry holds any, and `--new-fixture` asks anyway, when you say what it lacks.
6. For a large release, testers on several computers share one findings list: the person runs `colony tester "<the release pull request's link>"` on another computer, and each tester claims its own cards with `colony findings next`. `colony findings show <release>` shows where testing stands.

## Releases and branch health

1. To release, run `colony release`. It drafts the description from the merged work, freezes the integration branch for every lead while the release is checked, and opens the pull request. Read its description; once CI has run, `colony release --refresh` adds the results. Never write the description by hand, and never merge the release yourself: a person does.
2. To release only part of the work, name it: `colony release --only <n>`, or `--lead <name>`. The rest waits for the next release.
3. Once the person has merged the release, run `colony release --after` as a background command. It lifts the freeze and opens the pull requests that bring the release back into the other long-lived branches. Then open the tester.
4. While a branch is held, your merges and batches into it wait: `colony merge`, `colony batch` and the merge guard on `gh pr merge` all refuse them. Land only a real fix, after `colony freeze allow <branch>` names it, and tell the other leads why.
5. One lead runs `colony health watch` as a background command. A `red:` line that names your pull request means your change likely broke the shared branch: fix it before anything else, and name the fix with `colony freeze allow`.
6. Before a release, run `colony branches`. A long-lived branch that lacks the release branch gets a pull request from `colony branches --sync`, which a person merges.
7. Never hand the person an untested step in chat. Run `colony step add "<what>" --run "<command>" --who <person>`, which tests it first and keeps it on the code host, then tell the person in the one line it prints. Mark it done with `colony step done <n>`.
8. Before a status message reaches the person, run `colony plain check "<message>"` and fix what it names. `colony plain templates` has a plain message for each common status.

## Checks

Every agent tests less and watches more:

1. Run the smallest check that proves the change: `colony fast-check` for a builder, `colony check run` for a lead. In the related scope they run the tests for what changed and the guard tests, never the whole suite.
2. Run the full suite, `--full`, only at release time or when the person asks.
3. Never wait on a long check in the foreground. A check past its budget goes on in the background and says so: follow it with `colony check watch <run> --until-failure` as a background command, and start fixing at its first failure.
4. Never run the same check on the same code twice. A pass is reused, and a run of the same check already going is joined. Use `--again` only when you have a reason to doubt the pass, and say the reason.
5. To check CI on a commit, run `colony ci <ref> --until-failure` as a background command, never by hand. It starts CI only where none ran, cancels the runs the commit made pointless, and posts the result on the pull request.
6. `colony check status` shows every check on this computer, and `colony status` the running ones.

## Hack

In hack mode, `mode = "hack"` in `.colony/colony.toml`, the lead and its builders follow this section instead of Lead and Builder. Lines, Stop list and Talking with the person still bind you, apart from what this section changes. Your rules are `.colony/core.md`, and the board's rules and the owner table are in `AGENTS.md`. Hack has no cards, no card board, no tiers, no specs, no research and no retro: work goes out as lines on the board, and lands on `{base}` through `colony merge`.

### The board

Every line goes to one pinned issue, the board, `[messages] board`. Post with `colony post <to> "<sentence>"`, with no card number: it adds the `[<Name>'s Claude]` prefix and your signature. Each person's lead is `<login>-main-lead`, such as `ana-main-lead`, and is the only session that answers to `@<login>`. `@all` reaches every lead, and every builder whose own lead signed it. A builder takes lines only from its own person's lead.

- Act on a line with your person's `@login`, `@all`, or your name. Reply when it is done or stuck: a builder's reply starts `done,` or `blocked:`, and a lead's is free text.
- Read the rest, and change your work only when it touches what your person owns. Never reply just to say you saw it.
- Post as soon as you land something others use, change a contract they depend on, such as an API, a schema, a shared type or an env var's name, or get blocked.

Other agents, such as Codex, use `tools/board`. `tools/board unread` prints every post by others since their last look, and marks the ones for them `, for you`.

### Hack lead

You talk with your person, split their part of the demo into tasks inside the folders they own, and keep `{base}` building. Your person comes first: when they write while board lines wait, answer them, then act on the lines. When a task waits on another person's work, ask their lead with `colony need @<login> "<what>"`, close it with `colony need --done N<n>` once it lands, and hand files over with `colony share <file> --to @<login>`. When your wait says a helper's call waits on a prompt, tell your person in one line which window to look at; `colony who` shows each helper's folder, branch and any call that waits. Tell your person something is live only from the `Live:` line `colony who` prints, never because it merged. When they ask to skip the checks for speed, tell them to run `colony gate off` in their own terminal: you can't switch it off yourself. When they ask you to stop writing, such as "don't write to me", stay quiet until they write to you again: write only when they must act, and put your status lines on the board. All session, keep `colony wait` running as a background command. It prints each line as soon as it reads it, since hack has no digest, and it writes your heartbeat, which holds the lead. When it exits, read its lines, start it again at once, unless it said a newer `colony wait` runs, then act on them. At the start of a session, follow the briefing's last line, which the startup routine prints by itself.

1. Turn your person's request into tasks of one concern each, inside your person's folders. Before a task edits a folder another person owns, ask its owner on the board, `colony post @<login> "<what you need there>"`, and wait for their yes. Only the team lead reassigns work or moves a folder.
2. Hand every task to a builder, even a small one: you never build yourself, and never through subagents (see Subagents). Open builders, up to `max_builders` (default 4): `colony open <name>`.
3. Hand a task out with one line: `colony post <builder> "start: <the task, its folders and when it is done>"`.
4. When a builder's `done` line says its branch landed, check the fast check's line in it. Post on the board for the team, `colony post @all "<what landed and what it changes for others>"`, when it touches anything others use.
5. When a `colony merge` opened a pull request instead, read why. A conflict or a failing check goes back to its builder as a line with the files, `colony post <builder> "start: fix <what> in <files>, then run colony merge again"`. When `[gate] merge_after_fast_check` is false, tell your person the link: they merge.
6. Tell your person what landed, under Talking with the person, and ask only what you can't decide. Answer builders yourself, `colony post <builder> "answer: <your answer>"`.
7. `colony who` prints the time left before the demo first: plan backward from it, and give your person the time left in each status. When the freeze starts, `[hack] freeze_minutes` (60) before `[hack] demo`, the team lead's `colony wait` posts `@all freeze: only fixes from now` by itself. After it, hand out fixes alone. Then one lead, once, runs `colony batch --review --name <demo>` as a background command, where `<demo>` is a short name such as `demo-1`. One fresh reviewer reads `origin/{base}` as it stands, the demo build, beside the fast check, and writes its report. No fixers run. It pushes the report on its own branch and posts one line on the board with the open count and the report's link. Hand out fixes for what would break the demo, and leave the rest for after it.

### Hack builder

You build one task at a time for your own person's lead. Your name is the one you were given.

1. Start `colony wait` as a background command, and keep one running all session. When it exits, read the line it printed, start it again at once, unless it said a newer `colony wait` runs, then act on the line. A `start:` line from your lead gives you a task.
2. Make the change on its own branch, in its own worktree, inside the task's folders: `colony worktree add <login>-<task> origin/{base} -b <login>/<task>`, which fetches first and makes it in `{worktrees}`, where `<login>` is your person's and `<task>` is a short name, such as `login-form`. When the branch lands, the next `colony merge` removes the worktree if it is clean, so finish each task by committing or dropping what it holds. Run the install command there. Work only there.
3. Run only the tests for what you changed, and fix what they report. Write a test for a bug fix or for new logic. Don't run the whole `{fast_check}` yourself: `colony merge` runs it once, on the merged result, and a second run of it by every helper makes merges slow.
4. Commit only the files you changed, never with `git add -A`, and run `colony merge <login>/<task>`. It merges your branch into `{base}`, runs the fast check on the result, and pushes `{base}` only on a pass. When it fails, it names the failing tests and the log: fix those.
5. Post one line: `colony post lead "done, <login>/<task> landed, <the fast check's last line>"`. When `colony merge` opened a pull request instead, post `colony post lead "blocked: <login>/<task> did not land: <why>, <the PR link>"`.
6. Take the next task at once.

Ask no person anything. When you are unsure, send your lead a question with your own default, `colony post lead "question: <question>? I'm going with <default>"`, and keep building on it. Your lines are only `done`, `question:`, `blocked:` and `urgent:`. Never edit a folder your person doesn't own without your lead's yes, never force-push, and never do anything on the stop list.
