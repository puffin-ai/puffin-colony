# Launch orchestrator compared with Colony, 2026-11

This page compares two ways of running Claude Code on Puffin Calendar. The first is the way Burak's launch workstream ran on 2026-11-05 and 2026-11-06: one orchestrator, `launch-orchestrator`, with builders, testers and a researcher, on the branch `launch/integration`, under workstream issue #1243 and the Needs issue #1244. The second is Colony 0.2.0, which Puffin PR #1466 moves Puffin onto. Each section says what the launch workstream does, what Colony does, which is better, and why.

The evidence comes from the launch workstream's real runs, from Colony's own docs and published numbers, and from Colony's code at `8d0551a`. Where no run measured something, the section says so.

## Summary

Colony is the better base. Its gate, its line rules, its tidy, its account picking, its retro and its coordination issue each fix a problem the launch workstream met by hand on 2026-11-06. The launch workstream does six things Colony can't do yet:

- **A fast gate.** It ships a batch on the required checks alone, when Burak asks for speed.
- **Paid checks.** It runs real model calls inside a spend ceiling the person approved.
- **Releases.** It releases `dev` into `main`, then watches the staging deploy.
- **Testing the live app.** A tester checks staging after a release.
- **A start check.** It confirms each new session is working within minutes of opening it.
- **Done lines at once.** Each done line reaches the orchestrator immediately, so a merge follows within 30 seconds.

Section 4 turns each of those into a change to Colony, together with five smaller fixes.

## Facts the comparison uses

| Fact | Value | Source |
| --- | --- | --- |
| Colony's tests | 663 passed in 52.5 s | `uv run --with pytest pytest -q tests` on 2026-11-06 |
| Colony's code | 6,918 lines of Python in `colony/*.py`, standard library only | `wc -l` |
| PR #1466 | +2,718 and -4,793 lines in 60 files, into `dev`, still open | `gh pr view 1466` |
| Launch batch 1, 2026-11-05 | 4 cards, 1.5 to 18.5 wall minutes each, 1.3M to 31.8M tokens each, one fresh reviewer with no findings | `reports/launch-batch-2026-11-05.md` |
| Launch cards, 2026-11-06 | 16 cards. From the start line to the done line, S cards took 3 to 16 minutes, M cards 3 to 26, and the one L card 30. | Start and done comments on #1524 to #1548 |
| Predictions, 2026-11-06 | S 20 to 30 minutes, M 30 to 75, L 90. Every card finished under its prediction, most by 3 to 10 times. | The same cards' `predicted:` lines |
| Done line to merge | 0.3, 0.4 and 0.5 minutes for #1545, #1544 and #1546 | The done comment's time against the merge commit's time |
| Colony's first batch, 2026-11-05 | 10 cards, open problems 7 to 0 in 4 rounds, about 2.5 hours, mostly checks; the walk caught 4 phone bugs the tests missed | `docs/faq.md` |
| Colony's second batch, 2026-11-05 | 2 cards to an open PR in about 66 minutes; $9.58 at API prices, of which the walk was $5.90, the review $2.38 and the fixes $1.30 | `docs/faq.md` |

## 3. The comparison

### Roles: lead, helpers, subagents

- **Launch:** one orchestrator per person, `launch-orchestrator`. Builders, testers, a researcher and a reviewer are separate sessions, each named `launch-<role>-<n>`, each in its own worktree and cmux window. The worker brief tells a worker to start no subagent. The orchestrator starts one fresh reviewer subagent per batch.
- **Colony:** one lead per person per stream, such as `burak-main-lead`. Helpers belong to one lead through `$COLONY_LEAD`. Helpers may use subagents for pieces of a card. The reviewer, walker, fixers and retro run headless from `colony batch`.
- **Better:** Colony. Its ownership model, one lead per stream with folders in `.colony/leads.toml`, gives a person two leads over separate folders, which the launch workstream can't do. Testers are the gap: Colony has a walker for a local browser, and no role that tests a deployed app (change 7).
- **Evidence:** no run measured subagents against no subagents. The launch builders finished 16 cards on 2026-11-06 without them, most under 16 minutes.

### Cards and batches

- **Launch:** one card per change, with at most three done-when results, its folders and a prediction. Cards hang under workstream issue #1243 as sub-issues. A batch is every hand-over merged into `launch/integration` since the last gate.
- **Colony:** the same card shape through `colony card new`, which refuses past 10 open cards per lead and refuses a duplicate. No sub-issues. A batch is a named set of card branches that `colony batch` merges into its own branch.
- **Better:** Colony.
- **Evidence:** on 2026-11-06 GitHub refused to add card #1543 under #1243: "Parent cannot have more than 100 sub-issues". Colony's flat board has no such limit, and its `tidy` closes cards with no update for 7 days.

### Messages and their speed

- **Launch:** `tools/session_watcher.py wait` polls GitHub about every 15 seconds. The orchestrator's wait ends on every line for it, so it acts on each done line at once.
- **Colony:** `colony wait` polls the same way, with ETags, so a quiet poll costs nothing. The lead's wait gathers lines into a digest every 10 minutes, `lead_digest_minutes`. Questions, blocked and urgent lines, a person's lines, and done lines for cards in `--waiting-on` print at once. Line kinds are fixed: a builder posts only done, question, blocked or urgent, and the lead posts only start, answer or urgent.
- **Better:** Colony for cost and discipline, the launch workstream for merge speed.
- **Evidence:** the launch orchestrator merged #1545, #1544 and #1546 within 0.3 to 0.5 minutes of their done lines. Under Colony's defaults, a done line for a card the lead has not put in `--waiting-on` waits up to 10 minutes (change 2). No run measured the tokens the digest saves.

### The gate: checks, reviewer, browser walk, open problems to 0

- **Launch:** each hand-over runs `agent_checks.py --fast` before its merge. Under Burak's fast path of 2026-11-06, a batch shipped on the three required checks alone, with no reviewer or walk. Paid real-model tests and a staging tester ran after.
- **Colony:** `colony batch` runs the full checks, a fresh reviewer and a browser walk each round, and fixers until 0 problems are open. It stops on repeated failures or `max_rounds`.
- **Better:** Colony for quality. The launch workstream for speed when the person asks for it, and for the problems only a real model or the live app shows.
- **Evidence:**
  - Colony's first batch took about 2.5 hours, mostly checks, and its walk caught 4 phone bugs that tests missed.
  - On 2026-11-06 the launch fast checks passed on a change that broke the frontend bundle gate: `/student` grew 1,052 bytes and `/student/blocks/[block]` 1,153 bytes past the 1,024-byte margin. CI caught it after the merge into `dev` (run 42283199058). Colony's full checks per round would have caught it before the PR.
  - The same day, the weeks change (#1544) passed every local check. Only the paid run with the real model showed it: 7 of 9 first answers were refused, and one read failed. Neither system's gate would catch that today (change 4).
  - The staging test (#1548) found 3 bugs that the tests missed: a second upload ends the first syllabus read, an ended term refuses the plan with no reason, and onboarding adds a saved goal again. Colony has no step for this (change 7).

### Merging into dev and main

- **Launch:** hand-overs merge into `launch/integration`, batches into `dev`, and a bundle pull request from `dev` into `main`, which only a person merges or tells the orchestrator to merge. After the merge, the orchestrator merges `main` back into `dev`, starts or watches the staging release, and starts a tester.
- **Colony:** a batch opens one PR into `base`. Colony never pushes to `base`, except `colony merge` in Hack. It has no second branch and no release step.
- **Better:** the launch workstream, for a repo that releases from `main`.
- **Evidence:** on 2026-11-06, merging `main` into `dev` and starting the staging release (`staging.yml` with `hold=true`) were steps by hand. Serdar's batch #1537 rode along inside bundle #1531 without a word to Serdar's lead, because the comment on his PR was refused by the permission check (changes 5 and 6).

### Accounts and usage limits

- **Launch:** the orchestrator picks an account per session by hand: builder-32 on `admin@`, builder-33 and tester-6 on `engineering@`. The retry watchdog waits out a limit.
- **Colony:** each session picks the account with room from the saved 5-hour and weekly usage, the one whose weekly window resets soonest first, and prints why. `colony who` shows every account's room across computers.
- **Better:** Colony.
- **Evidence:** no limit stall was measured on 2026-11-06. Colony's pick needs no person and no orchestrator tokens.

### Stuck sessions and permission pop-ups

- **Launch:** two hooks post an urgent line on a waiting pop-up and a line on a turn that ends on an error. The board check reports a card with no update in 2.5 hours. The orchestrator also checks each new session within minutes of starting it, from its process, its branch and its screen.
- **Colony:** the same two hooks, an outbox so a hook's line is never lost, a heartbeat every 15 seconds, a status comment every 5 minutes, and the same 2.5-hour stale line.
- **Better:** Colony's hooks, and the launch workstream's start check.
- **Evidence:** on 2026-11-06 the stale check reported #1532 as stale 5 hours after its builder had finished, because the card stayed In progress after the merge. Colony's playbook moves a card to In review by hand, so the same false alarm can happen (change 1). The orchestrator's start checks confirmed builder-33 and tester-6 were working two minutes after each start. Colony has no check that a new helper started at all (change 8).

### Two people's leads side by side

- **Launch:** lines between workstreams go on the other workstream's issue. On 2026-11-06 Serdar's colony batches merged into `dev` through their own pull requests, and the two streams met only in `dev`.
- **Colony:** leads talk on one `Colony: coordination` issue with `colony say`, warn each other before a merge to the shared base, and post handovers there. `@login` and `@all` reach a person's lead.
- **Better:** Colony.
- **Evidence:** on 2026-11-06 the launch merge into `dev` met a conflict in `contracts/generated/manifest.json` with Serdar's batch, which the orchestrator fixed by exporting the contract again and regenerating. Colony's batch takes the card's side in a conflict only in generated files and runs `regen`. Its lead's own merges into the base don't yet (change 9).

### Knowledge, specs and research

- **Launch:** the vault under `knowledge/`, checked by `tools/check_vault.py`. Research reports are written by the orchestrator or a researcher; on 2026-11-06, `syllabus-reading-research-2026-11.md` recorded the paid tests. Decisions go to Needs Burak, #1244.
- **Colony:** the same vault, checked by `colony check-docs` with Puffin's own checks as a plug-in. A researcher's report is done only when every finding binds a rule with its check, or a decision. `colony retro` turns each batch's lessons into a rule and a check in one PR. `colony idea` keeps ideas out of issues.
- **Better:** Colony.
- **Evidence:** PR #1466 reports that `colony check-docs --strict` and the old tool give the same records on dev and on a seeded tree where all 48 checks fire. The launch workstream's lessons of 2026-11-06 live in an orchestrator's memory files, which no other session reads.

### Anti-bloat: card limits, stale cards, tidy

- **Launch:** no card limit, no duplicate check, and no tidy. Workstream issue #1243 carries every card as a sub-issue.
- **Colony:** 10 open cards per lead, a duplicate refusal, `tidy` after every batch, issue rotation at 200 comments, archive after 7 days Done, and removal of clean worktrees.
- **Better:** Colony.
- **Evidence:** #1243 hit GitHub's 100 sub-issue cap. On Burak's Mac, `scratchpad/carry/` holds 46 launch worktrees, the orchestrator's and each builder's, tester's, researcher's and reviewer's, with no step that removes them.

### Speed and cost per card

- **Launch:** batch 1 measured each card's wall minutes, active minutes and tokens with `tools/card_stats.py`: 1.5 to 18.5 minutes, 1.3M to 31.8M tokens, and 0.43 to 0.79 of the predicted tokens. On 2026-11-06 the 16 cards took 3 to 33 minutes. The paid syllabus tests cost about $4.16 with Burak's approval, tracked by hand.
- **Colony:** `colony stats` measures the same, and the batch PR adds a minutes table with each step's cost. The second batch cost $9.58 at API prices, of which the walk was 62%.
- **Better:** even. Colony puts cost in the PR, while the launch workstream adds the account per card.
- **Evidence:** every launch card on 2026-11-06 finished under its prediction, most by 3 to 10 times, and neither system calibrates its predictions from its stats (change 10).

## 4. What Colony lacks, and the change for each

Each change names the file and what it should do. The first six come from the comparison above. Changes 11 and 12 come from Burak's standing rules, and he may add more.

| # | What is missing | File | The change |
| --- | --- | --- | --- |
| 1 | A finished card stays In progress, and the stale check then raises a false alarm | `colony/cli.py`, `post` | When a builder posts `done` on card N, set N's Status to In review and stamp Last update, in the same call |
| 2 | A done line can wait up to 10 minutes in the lead's digest | `colony/wait.py` | Print a `done` line at once whenever the lead has no batch running, and keep the digest for the other kinds |
| 3 | No fast gate for a batch the person wants shipped quickly | `colony/batch.py`, `colony/cli.py` | `colony batch --fast` runs the full checks once, with no reviewer, walk or fixers, opens the PR when they pass, and writes `gate: fast` in the PR body |
| 4 | No real-model check inside an approved spend | `colony/batch.py`, `[gate]` in `colony/modes/startup.toml` | `[gate] paid_checks = "<command>"` runs only when `[budget] provider_dollars` is above 0, passes the remaining dollars as `COLONY_SPEND_CEILING`, stops at the ceiling, and writes the dollars spent in the PR |
| 5 | No release from the base into the release branch | `colony/cli.py`, `colony/merge.py`, a new `colony/release.py` | `colony release` opens one PR from `base` into `[project] release`, with each batch PR since the last release in its body. After a person merges it, `colony release --after` merges the release branch back into `base` and watches the workflow `[project] deploy_workflow` until it ends |
| 6 | Another lead's batch ships inside a release without a word | `colony/release.py` | Before it opens the release PR, `colony release` posts one `colony say @all` line naming each other lead whose batch is in `base` and not yet released, and lists those batches in the PR body |
| 7 | No role that tests the deployed app | `colony/playbook.md`, a new `colony/prompts/tester.md`, `[roles] tester` | A tester opened after a release checks the release's cards on the deployed app, posts `blocked:` for a person's step such as admitting an account, and posts its results as one findings issue |
| 8 | No check that a new helper started | `colony/cli.py`, `open` and `join`; `colony/wait.py` | The lead's wait expects each opened helper's status comment within 5 minutes, and gathers an `urgent:` line naming the helper when none comes |
| 9 | A conflict only in generated files stops the lead's own merges | `colony/merge.py` | `colony sync <branch>` merges `origin/<base>` into the branch, takes either side in a conflict only in `generated` files, runs `regen`, and stops on any other conflict |
| 10 | Predictions stay 3 to 10 times too long | `colony/cycle.py`, `stats` and `card new` | `colony stats --calibrate` prints the median actual minutes per size over the last 30 cards, and `card new` prints that median beside the prediction |
| 11 | Burak's rule: act on notifications silently, and write to the person only to converse or when they must act | `colony/playbook.md`, Lead section | Add that rule. The lead's own status lines go on the board, never in chat |
| 12 | Burak's rule: builders are fast and never overtest | `colony/playbook.md`, Builder section | One test per done-when result, the fast check once, and the done line at once, as `predicted:` assumes |

Colony also gets one thing wrong for this repo: `cmux` is not on the orchestrator shell's PATH on Burak's Mac (`command not found: cmux`); it lives at `/Applications/cmux.app/Contents/Resources/bin/cmux`. `colony/cli.py` should look there before it falls back to background sessions.

## 5. What Puffin should take from each

- **From Colony:** the line kinds, the digest, the outbox, the account pick, the card limit and duplicate check, tidy, the coordination issue, the retro, and the gate's rounds until 0 open, for every batch that is not a fast one.
- **From the launch workstream:** the fast gate, paid checks inside an approved ceiling, the release into `main` with the watch of staging, the staging tester, the start check, and done lines at once.
