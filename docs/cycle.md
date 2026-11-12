# The cycle

The gate loop in [how-it-works.md](how-it-works.md) checks what builders build. This page covers the cycle around it: how the lead sizes a request, when a spec or research comes first, how it asks you, where it tracks cards, how `colony tidy` keeps them few, how it hands over, and how a batch's lessons become rules. The lead follows all of it from `.colony/playbook.md`.

## The roles

| Role | What it does | Started by |
| --- | --- | --- |
| Lead | Talks with you, picks tiers, writes cards, merges, runs the gate | `colony` |
| Builder | Builds one card at a time on its own branch | `colony open` or `colony join` |
| Spec agent | Writes a FEATURE's requirements, design and tasks | the lead, with `colony spec "<feature>"` |
| Researcher | Answers one outside question with cited sources | the lead, with `colony research "<question>"` |
| Reviewer, walker, fixers | The gate: review, browser walk, fixes | `colony batch` |
| Retro agent | Turns a batch's lessons into rules and checks | `colony retro` |

## Tiers

The lead picks a tier for each request before it writes a card:

- **TINY** and **SMALL** go straight to cards.
- **FEATURE** goes to the spec agent first. You approve its requirements, and then its tasks become cards.
- **An unknown**, a request that turns on an outside fact nobody here knows yet, goes to the researcher first. It gets its tier once the report is in.

| Tier | What makes it | Docs in the same change |
| --- | --- | --- |
| TINY | Code of at most 100 non-test lines in one area outside `backend_paths` (and inside `tiny_folders`, when set), or docs of at most 300 lines, with nothing on the risk list and no page, layout, route or feature-folder file moved or deleted | The living-spec and wiki lines it makes stale |
| SMALL | Every other change | TINY's, and a decision record for a structure, dependency or interface choice |
| FEATURE | A new feature folder, module, route or page, a migration that creates a table, a new spec page, a line one of the repo's `feature_triggers` finds, over 400 non-test lines, or `--feature` | SMALL's, and the spec pages |

`colony tier --head origin/<branch> --why` prints the lowest tier a branch's diff allows, the reasons, and the risk list. Tests, lockfiles and generated files don't count toward the line limits.

The risk list names each changed file that touches one of these: auth, payments, migrations, secrets, deletion, public API, dependencies, config, and checks (a skip mark, a suppression, or a deleted test). A file gets on it by its path or by an added line, such as `DROP TABLE` or a key-shaped string. Anything on the list makes a change at least SMALL. `colony batch` reads the list again at each round's head and gives it to the reviewer, who reads those places first. A place on the list is not a finding by itself.

When a done card's branch prints a higher tier than the lead picked, a FEATURE with no approved spec goes to the spec agent before its next card. The board keeps no Tier: the tier is the lead's call at the card's start, and `colony tier` reads it again from the branch.

A rename is read at both ends, so moving a file off the risk list is on it too. The limits, the extra risk paths, the TINY folders, the page files and the repo's own FEATURE lines live in `[cycle]`. See [configuration.md](configuration.md#cycle).

## Research first

1. The lead makes a card titled `research: <topic>`, and opens the researcher on one question with `colony research "<question>"`. Its first prompt is `.colony/prompts/researcher.md`, with the question filled in.
2. The researcher prefers primary sources, cites every claim, and spends no money. It treats every fetched page as data, never as an instruction.
3. It writes `knowledge/research/<topic>-<yyyy-mm>.md`, as a research report, on the branch `research/<topic>`, and changes no app code.
4. Its research is done only when every finding binds something: a rule line with the check that enforces it, or a decision it asked you with `colony needs`. A finding left as a note is not done.
5. The lead puts the branch into the next batch, turns each planned check into a card, and then gives the waiting request its tier.

How a finding becomes a rule is in [knowledge.md](knowledge.md#how-research-becomes-rules).

## The spec

1. The lead makes a card titled `spec: <feature>` with `colony card new`, and opens the spec agent with `colony spec "<your request in your words>"`. Its first prompt is `.colony/prompts/spec.md`, with the request filled in.
2. The spec agent writes in `knowledge/specs/plans/<feature>/`. A feature one card builds gets one feature spec. A larger one gets three pages: requirements, then design, then tasks.
3. Each open question gets a `[NEEDS CLARIFICATION: …]` marker and a `colony needs` line with the agent's default. The agent keeps working on the default.
4. It asks you to approve the requirements, with the default "no cards until you approve". It pushes `spec/<feature>` and changes no code.
5. Until you say yes, the lead cuts no card from it, and keeps the other cards moving.
6. On your yes, the spec branch joins the next batch, and each task on the tasks page becomes a card, with the task's contract as its body.

## Needs you

Each person has one issue, `Needs <Person>`, for the decisions only they can make: an item on the stop list, a product or screen choice no doc settles, approving a FEATURE's requirements, and merging.

```sh
colony needs "Keep the 30 second timeout?" --default "yes"
```

That posts `for ana-lead: Ana decides: Keep the 30 second timeout? Default: yes (from ana-lead)`, and makes the issue the first time. `--person <p>` asks someone else.

- The lead keeps working on the default.
- You answer on the issue with `for <you>-lead: <answer>`. Your line reaches the lead at once, and your answer wins: the lead undoes what the default built when it differs.
- The lead tells you in chat only when something is urgent or blocks the work, and points at the line.

## The board

The cards live on a GitHub Project, `Colony: <project>`, which `colony board init` makes once from the repo's owner and links to the repo. Running it again adds any missing field or option, and keeps the ones there. The board has five fields, and no others:

| Field | Values | Who sets it |
| --- | --- | --- |
| Status | To do, In progress, In review, Done | the lead |
| Lead | the lead whose card it is, `<person>-lead` | `colony card new` |
| Helper | the builder working on it | the lead |
| Size | S, M, L | `colony card new` |
| Last update | `YYYY-MM-DD HH:MM UTC` | every `colony board set` stamps it |

```sh
colony board set 12 Status="In progress" Helper=builder-2
colony board set 12 Last_update=now
```

`colony board set` checks every field and value before it writes, so a typo changes nothing, and it refuses any other field, such as an older board's State, Builder, Tier, Account or Branch. `board init` leaves those old fields on an older board, so no card loses what they hold. Field names ignore case and spaces, so `last_update` works. Progress goes in Last update, which wakes no one, never in a line.

**Stale cards.** Every 10 minutes, the lead's wait checks the board. A card In progress whose Last update is over 2.5 hours old gives the lead one `stale:` line, naming its Helper. The board has no State, so a builder waiting on a usage limit shows up too, and the lead looks at its session to tell. When `claude agents` lists that helper's background session as blocked, the line says it waits on a prompt and names the `claude attach <id>` that reaches it.

Every computer's `gh` login needs the project scope: `gh auth refresh -s project`. When the board can't be reached, agents say why once and go on without it. `[board] number` points Colony at a project you already have.

## Cards

A card is an issue only when its work starts this week. An idea for later is one dated line in the future-work register, never an issue:

```sh
colony idea "a dark mode for the calendar"
```

That appends `- 2026-11-05: a dark mode for the calendar` to the Ideas section of `<vault>/future-work.md`, or of `.colony/future-work.md` in Hack and Solo, which have no vault. Commit it with the next change.

A card is titled `<builder>: <what>`. Its body holds the task, up to 3 done-when results, the folders it touches, and one prediction line:

```text
predicted: S, 20 min
predicted: M, 45 min, 15M tokens
```

The lead makes it with `colony card new`, never a bare `gh issue create`:

```sh
colony card new "builder-2: dark mode switch in settings" --body "<task, done-when, folders, predicted: S, 20 min>" --size S
```

- It refuses when the lead already has `[limits] open_cards_per_lead` open cards, 10 by default, counted by the board's Lead field: close or finish one first. Without a card board, as in Solo, every open issue but the coordination and Needs issues counts.
- It refuses a duplicate, and names the open card it repeats: a title with the same words, ignoring case and punctuation and the `<builder>:` start, or one whose words overlap by three quarters or more.
- It creates the issue and puts it on the board as To do, with its Lead (you, or `--lead <name>`) and Size.

The size is S, M or L. Cards that touch the same folders go to the same builder, which keeps conflicts down. A batch's pull request says `Closes #<n>` for each card, so the merge closes them. GitHub closes them only when the pull request merges into the repo's default branch; on another base, the lead closes them.

## Tidy

`colony tidy` runs at the end of every `colony batch`, and on demand. `colony tidy --dry-run` prints the plan and changes nothing.

| It | When |
| --- | --- |
| Closes a card, as not planned, with one line saying why | It shows no update for `[limits] stale_days` (7) and its work started |
| Moves a card to future-work, and closes it with one line saying why | It shows no update for 7 days and it is still To do |
| Rotates the coordination issue or a Needs issue | It holds `[limits] issue_comments` (200) comments |
| Archives a board item | It has been Done, or closed, for `[limits] archive_days` (7) |
| Turns on the repo's `delete_branch_on_merge`, and says so | It is off |
| Removes a card's worktree | The card is closed and the worktree is clean: no uncommitted or untracked change. The main checkout is never removed, and a dirty worktree is kept and named |

It finds a card's worktree in `git worktree list --porcelain` by its branch, `<name>/<n>`, and leaves the branch itself. It prints the counts before and after: open cards per lead, stale cards closed or moved, comments on the coordination and Needs issues, rotations, board items archived, and worktrees removed and kept. A step that fails says why, and the others go on.

**Rotation.** A rotated issue gets a closing comment that lists its open items: the `question:`, `blocked:` and `urgent:` lines among its last 50 comments, and on a Needs issue each decision posted after the person's last answer. Then it closes, and a fresh issue with the same title opens, its body linking the old one. `colony say`, `colony needs` and `colony handover` read the issue's comment count before they post, in one cheap call, and rotate it first when it is full. The lead's wait follows the new coordination issue: the computer that rotated it remembers the new number at once, and every other computer checks its remembered number every 10 minutes and drops it once that issue is closed.

## Handover

When the lead's conversation nears automatic compaction, it hands over first:

```sh
colony handover --decisions "<each decision, with its card>" --open "<each open question>" --next "<what it was about to do>"
```

That posts a comment on `Colony: coordination` with the lead's name, the time, the decisions, the open questions and the next step. Then it prints the command that opens a fresh lead for the same person. Every lead starts with `colony handover --read`, and carries on from the `next:` line of the last one.

## Stats

Each batch's PR body ends with a Card stats table, and the lead can print it any time:

```sh
colony stats --card 41=builder-2/41 --card 42=builder-3/42
```

It has one row per card: builder, size, how the card ended, predicted minutes, wall minutes, active minutes, predicted tokens, tokens, and lines changed, with a total row.

- The window opens at the card's `start: this card` line, and closes at the builder's `done` line, or at a stop line.
- Tokens and active minutes come from that builder's Claude Code transcripts on this computer, inside the window: input, cache and output tokens, and only gaps of 2 minutes or less as active time.
- The lead uses the table to predict the next cards better.

## Retro

```sh
colony retro --name 2026-11-05
```

It runs one agent in its own worktree, on the branch `<project>/retro-<batch>`. The agent reads the batch's round reports and looks for three kinds of lesson: a problem the gate caught that a fast check could have caught, a problem that came back in a later round, and a card that ran far over its prediction.

Each lesson becomes one of two things, never a note alone:

- **A rule line plus a check.** One sentence with must or must not, in the rule file it belongs to, and a test, a lint setting or a script that fails on the problem.
- **A decision for you**, with the agent's default. `colony retro` prints a `colony needs` line for each one, for the lead to post.

With at least one lesson, it pushes the branch and opens one PR. With none, it removes its worktree and branch. It runs on the `retro` role's settings, or the reviewer's when `[roles]` has no `retro`.

## How the lead talks with you

Only the lead talks with you, in its chat and on your Needs issue. Every message:

- answers first, in the first two sentences;
- shows a picture where it helps, such as a small table of who does what;
- stays under 200 words, in everyday words;
- asks at most one question, with its choices and its pick first;
- ends with one line, `Needs you: <what waits on you>`, or `Needs you: nothing`.
