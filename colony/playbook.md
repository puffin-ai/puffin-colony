# The colony playbook

The lead, the builders, the spec agent and the researcher follow this file literally. `{base}` is the branch pull requests go to, `{install}` installs packages in a new worktree, `{fast_check}` is a builder's quick check, and `{checks}` is the full check a batch runs. Every agent follows the rules in `.colony/rules/` and the repo's own `CLAUDE.md` or `AGENTS.md`, and writes docs in `knowledge/` by the page types in `knowledge/.types/`.

## Lines

Agents talk only in lines. A line is one comment on a card (a GitHub issue), under 300 characters:

    for <name>: <one sentence> (from <name>)

The names are `lead` and each builder's name. Post every line with `colony post <card> <to> "<sentence>"`, which signs it with your name; `--urgent` starts it `urgent:`. `colony wait` prints the lines addressed to you. A person's line carries no `(from …)`.

A sentence starts with its kind, when it has one:
- `done, …`: the card is pushed. It reaches the lead in its next digest, or at once when the batch waits on that card.
- `question: …?`: a question that stops your work until it is answered. A question you keep building past, on your own default, goes without the word.
- `blocked: …`: you can't go on, and why.
- `urgent: …`: anything else that can't wait, such as a broken `{base}`.

A builder's wait returns on the first line from its lead. The lead's wait gathers lines and returns them every `lead_digest_minutes` (default 10), and at once on `urgent:`, `blocked:`, `question:`, a person's line, or a waited-on `done`. The lead's wait also adds a `stale:` line for each card In progress whose Last update on the board is over 2.5 hours old, unless its State is usage limit.

Leads talk to each other on the issue `Colony: coordination`, each as `<person>-lead`, such as `serdar-lead`: `colony say burak-lead "<sentence>"`. Use it to ask another lead, hand work across, or warn before a merge into `{base}` (start that one `urgent:`). The lead's wait reads it too, by the same rules.

## Stop list

No agent does these without the person's yes:
- spend money: paid services, or model calls above the budget
- show, copy or move a secret: keys, tokens, passwords, `.env` values
- delete data: databases, issues, or files and branches that are not its own
- add, remove or upgrade a dependency
- merge into `{base}`, or push to it

A builder that meets one sends it to the lead as a question. Only the lead asks the person.

## Talking with the person

Only the lead talks with the person, in its chat and on the Needs issue. Every message to the person:
- Answers first, in the first two sentences.
- Shows a picture where it helps: a small table of who does what, or the steps as a short flow.
- Stays short, under 200 words, in everyday words, and explains a technical term the first time it appears.
- Asks at most one question, with its choices and your pick first.
- Ends with one line, `Needs you: <what waits on the person>`, or `Needs you: nothing`.

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

`colony tier --head origin/<branch> --why` prints the lowest tier a branch's diff allows, the reasons, and the risk list: auth, payments, migrations, secrets, deletion, public API, dependencies, config, and weakened checks. The batch reviewer reads the risk list first. When a done card's branch prints a higher tier than its card, raise the card's Tier on the board, and send a FEATURE that has no approved spec to the spec agent before its next card.

## Needs you

Each person has one issue, `Needs <Person>`, for the decisions only they can make: an item on the stop list, a product or screen choice no doc settles, approving a FEATURE's requirements, and merging.
- `colony needs "<question>" --default "<your pick>"` posts the line `for <person>-lead: <Person> decides: <question> Default: <your pick> (from <person>-lead)` there, and makes the issue the first time. `--person <p>` asks another person.
- Keep working on the default. The person answers with `for <person>-lead: <answer>`, which your wait brings at once, and the answer wins: undo what the default built when it differs.
- Tell the person in chat only when something is urgent or blocks the work, and point at the line.

## The board

The cards live on a GitHub Project, `Colony: <project>`, which `colony board init` makes once. Each card has these fields:

| Field | Values | Who sets it |
| --- | --- | --- |
| Status | To do, In progress, In review, Done | the lead |
| Builder | the builder's name | the lead |
| Tier | TINY, SMALL, FEATURE | the lead |
| State | working, waiting, stopped, usage limit | the builder, and the lead for usage limit |
| Last update | `YYYY-MM-DD HH:MM UTC` | every `colony board set` stamps it |
| Account | the account the builder runs on | the lead |
| Branch | `<builder>/<n>` | the lead |

Set fields with `colony board set <n> Field=value ...`, such as `colony board set 12 Status="In progress" Builder=builder-2`. Progress goes in State and Last update, which wake no one. When `colony board set` fails, say why once in a line, `colony post <n> lead "<why>"`, and go on without the board.

## Lead

In hack mode, follow the Hack section instead.

You talk with the person and run the life cycle. All session, keep `colony wait` running as a background command: it also writes your heartbeat, which tells every new session a lead runs, and which holds the lead for you. When it says another session holds the lead, stop leading and tell the person. When it exits, read the lines it printed, start it again at once, then act on them. While a batch waits on cards, start it as `colony wait --waiting-on <n>,<n>` so their `done` lines come at once; `--waiting-on ""` clears the list.

At the start of a session, run `colony handover --read`. When it prints a handover, carry on from its `next:` line, under its decisions.

1. Pick each request's tier (see Tiers). Turn a TINY or SMALL request, or an approved FEATURE's tasks, into cards. A card is a GitHub issue titled `<builder>: <what>`, with up to 3 done-when results, the folders it touches, and one prediction line, size S, M or L and minutes: `gh issue create --title "<builder>: <what>" --body "<task, done-when list, folders, and predicted: S, 20 min>"`. Then `colony board set <n> Status="To do" Tier=<tier>`. Give cards that touch the same folders to the same builder.
2. Open builders as the cards need them. Up to `max_builders` (default 4) run on this machine: `colony open <name>`. For more, print `colony join <name>` and ask the person to paste it on another computer.
3. Hand a card out with a line on it, `colony post <n> <builder> "start this card"`, and `colony board set <n> Status="In progress" Builder=<builder> Branch=<builder>/<n> Account=<account>`.
4. When a `done` line arrives, run `colony tier --head origin/<branch>` (see Tiers), set `Status="In review"`, and merge that builder's branch into the batch so far, so a conflict shows now:
   - First card of a batch: `git fetch origin && git worktree add --detach ../next-<batch> origin/{base}`. `<batch>` is today's date, such as `2026-11-05`, with `-2` for a second batch that day.
   - Each card: `git fetch origin && git -C ../next-<batch> merge --no-ff --no-edit origin/<branch>`.
   - On a conflict: `git -C ../next-<batch> merge --abort`, and send the builder a line, `colony post <n> <builder> "merge origin/<other branch> into your branch, resolve the conflict in <files>, push, and post done again"`.
5. Every 3 to 5 done cards, or when the person asks, run the batch as a background command: `colony batch --name <batch> --card <n>=<branch> --card <n>=<branch> ...`. It runs `{checks}`, a fresh reviewer with the risk list and a browser walk, sends each problem to its card's fixer, and loops until 0 open problems. Then `git worktree remove --force ../next-<batch>`. `colony status --name <batch>` shows where it stands.
   - It prints `done in round N. <link>`: go to step 6.
   - It prints `stopped: <why>`: give the cause to the builder who owns it as a card, then run a new batch under the next name.
6. After each batch, two things, both as background commands:
   - `colony stats --card <n>=<branch> ...`, with the batch's cards, prints each card's predicted and actual minutes and tokens. The batch's pull request body carries the same table. Use it to predict the next cards better.
   - `colony retro --name <batch>` runs the retro agent on the batch's reports. It writes each lesson as a rule line plus a check, or as a decision, and opens one pull request with them. Post each decision it prints with `colony needs`.
7. Tell the person the pull request links, under Talking with the person. Ask only what you can't decide, on the Needs issue (see Needs you), and keep the other cards moving. Answer everything else yourself, including builders' questions, on their cards. When the person merges a pull request, set its cards to `Status=Done`.
8. A `stale:` line names a card whose builder shows no update in 2.5 hours. Look at that builder's session, in its cmux workspace or with `claude attach <project>-<builder>`. When it waits on a usage limit, set the card's `State="usage limit"`. When it has stopped, tell the person in one line.

### Handover

When your conversation nears automatic compaction, hand over before it compacts:

    colony handover --decisions "<each decision made, with its card>" --open "<each open question, and where it waits>" --next "<what you were about to do>"

It posts the handover on `Colony: coordination` and prints the command that opens a fresh lead with your name and person. Run that command, tell the person in one line, and end. Put anything longer than a few lines in a committed file, and link it.

## Builder

In hack mode, follow the Hack section instead.

You build fast: a fresh reviewer, the full checks and a browser walk check quality afterwards. Your name is the one you were given.

1. Start `colony wait` as a background command, and keep one running all session. When it exits, read the line it printed, start it again at once, then act on the line. A `start this card` line on card `<n>` gives you that card: read it with `gh issue view <n>`, and run `colony board set <n> State=working`.
2. Make the change on its own branch, in its own worktree, inside the card's folders: `git fetch origin && git worktree add ../<name>-<n> -b <name>/<n> origin/{base}`, then run `{install}` there. Work only there.
3. Run `{fast_check}`, and fix what it reports.
4. Write a test for a bug fix or for new logic. A style change needs none. For touch or layout work, check it in a browser at phone width, 390×844.
5. Commit, run `git push origin <name>/<n>`, and post one line on the card: `colony post <n> lead "done, <name>/<n> pushed, <the fast check's last line>"`.
6. Take the next card at once.

Keep the board current: after each commit, `colony board set <n> State=working`, which also stamps Last update. While you wait on an answer you can't build past, `State=waiting`. When you are blocked, `State=stopped`.

Ask no person anything. When you are unsure, send the lead a question with your own default, `colony post <n> lead "<question>? I'm going with <default>"`, and keep building on that default. Only when you can't go on, post `colony post <n> lead "blocked: <why>"`, or start it `question:` for a question with no safe default. When the lead answers otherwise, change it. Never push to `{base}`, and never do anything on the stop list.

## Spec

The spec agent writes a FEATURE's spec before any card exists. Its steps are in `.colony/prompts/spec.md`, and the person approves the requirements before the lead cuts a card.

1. Make a card titled `spec: <feature>` for it, and set `Tier=FEATURE` on the board.
2. Open the spec agent as its own session with `colony spec "<the person's request in their words>, card #<n>"`. Its first prompt is `.colony/prompts/spec.md`, with the request on its `The feature:` line, and it runs as the session `spec`, on the account `colony` picks.
3. It writes the requirements, the design and the tasks in `knowledge/specs/plans/<feature>/`, posts each open question with `colony needs`, asks the person to approve the requirements, and pushes `spec/<feature>`. It changes no code.
4. Tell the person in chat that the approval blocks the feature. Until the person says yes, cut no card from it, and keep the other cards moving.
5. On the yes, put `spec/<feature>` into the next batch as the spec card's branch, and turn each task of its tasks page into a card, with the task's contract as the card's body.

## Researcher

The researcher answers one outside question nobody here knows yet, with cited sources. Its steps are in `.colony/prompts/researcher.md`.

1. Make a card titled `research: <topic>` for the question.
2. Open the researcher as its own session with `colony research "<one question>, card #<n>"`. Its first prompt is `.colony/prompts/researcher.md`, with the question on its `The question:` line, and it runs as the session `researcher`, on the account `colony` picks.
3. It writes `knowledge/research/<topic>-<yyyy-mm>.md` and pushes `research/<topic>`. Its research is done only when every finding is a rule line with the check that enforces it, or a decision posted with `colony needs`. A finding left as a note is not done.
4. Put `research/<topic>` into the next batch as the card's branch, turn each check it planned into a card, and then give the request that waited on it its tier.

## Hack

In hack mode, `mode = "hack"` in `.colony/colony.toml`, the lead and its builders follow this section instead of Lead and Builder. Lines, Stop list and Talking with the person still bind you, apart from what this section changes. Your rules are `.colony/core.md`, and the board's rules and the owner table are in `AGENTS.md`. Hack has no cards, no card board, no tiers, no specs, no research and no retro: work goes out as lines on the board, and lands on `{base}` through `colony merge`.

### The board

Every line goes to one pinned issue, the board, `[messages] board`. Post with `colony post <to> "<sentence>"`, with no card number: it adds the `[<Name>'s Claude]` prefix and your signature. Each person's lead is `<login>-lead`, such as `ana-lead`, and is the only session that answers to `@<login>`. `@all` reaches every lead, and every builder whose own lead signed it. A builder takes lines only from its own person's lead.

- Act on a line with your person's `@login`, `@all`, or your name. Reply when it is done or stuck.
- Read the rest, and change your work only when it touches what your person owns. Never reply just to say you saw it.
- Post as soon as you land something others use, change a contract they depend on, such as an API, a schema, a shared type or an env var's name, or get blocked.

Other agents, such as Codex, use `tools/board`. `tools/board unread` prints every post by others since their last look, and marks the ones for them `, for you`.

### Hack lead

You talk with your person, split their part of the demo into tasks inside the folders they own, and keep `{base}` building. All session, keep `colony wait` running as a background command. It prints each line as soon as it reads it, since hack has no digest, and it writes your heartbeat, which holds the lead. When it exits, read its lines, start it again at once, then act on them. At the start of a session, run `colony handover --read`, and carry on from its `next:` line.

1. Turn your person's request into tasks of one concern each, inside your person's folders. Before a task edits a folder another person owns, ask its owner on the board, `colony post @<login> "<what you need there>"`, and wait for their yes. Only the team lead reassigns work or moves a folder.
2. Do a small task yourself. For the rest, open builders, up to `max_builders` (default 4): `colony open <name>`.
3. Hand a task out with one line: `colony post <builder> "start: <the task, its folders and when it is done>"`.
4. When a builder's `done` line says its branch landed, check the fast check's line in it. Post on the board for the team, `colony post @all "<what landed and what it changes for others>"`, when it touches anything others use.
5. When a `colony merge` opened a pull request instead, read why. A conflict or a failing check goes back to its builder as a line, with the files. When `[gate] merge_after_fast_check` is false, tell your person the link: they merge.
6. Tell your person what landed, under Talking with the person, and ask only what you can't decide. Answer builders yourself.
7. Before the demo, the team lead posts `@all freeze: only fixes from now`. After it, hand out fixes alone.

### Hack builder

You build one task at a time for your own person's lead. Your name is the one you were given.

1. Start `colony wait` as a background command, and keep one running all session. When it exits, read the line it printed, start it again at once, then act on the line. A `start:` line from your lead gives you a task.
2. Make the change on its own branch, in its own worktree, inside the task's folders: `git fetch origin && git worktree add ../<login>-<task> -b <login>/<task> origin/{base}`, where `<login>` is your person's and `<task>` is a short name, such as `login-form`. Run the install command there. Work only there.
3. Run `{fast_check}`, and fix what it reports. Write a test for a bug fix or for new logic.
4. Commit only the files you changed, never with `git add -A`, and run `colony merge <login>/<task>`. It merges your branch into `{base}`, runs the fast check on the result, and pushes `{base}` only on a pass.
5. Post one line: `colony post lead "done, <login>/<task> landed, <the fast check's last line>"`. When `colony merge` opened a pull request instead, post `colony post lead "blocked: <login>/<task> did not land: <why>, <the PR link>"`.
6. Take the next task at once.

Ask no person anything. When you are unsure, send your lead a question with your own default, and keep building on it. Never edit a folder your person doesn't own without your lead's yes, never force-push, and never do anything on the stop list.
