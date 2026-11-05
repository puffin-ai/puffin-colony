# Presets

A preset is the set of rules your agents follow. Setup asks which one you want (question 3), copies it into `.colony/rules/`, and lists the files in `[gate] rules` so the reviewer checks every batch against them.

Your own `CLAUDE.md` and `AGENTS.md` always count, whichever preset you pick. Setup keeps their rules, and the reviewer reads them too.

| Preset | Pick it when |
| --- | --- |
| `lean` (default) | You want short, sensible rules now and will grow them later. |
| `puffin` | You want a full engineering system, written for a Next.js app and a Python service. |
| `own` | Your repo already has the rules it needs in `CLAUDE.md` or `AGENTS.md`. |

## `lean`

Six short files, each under 400 words, written fresh and generic. Each has a "Must" list and a "Must not" list. Setup fills in your real source folders, test folder and check commands, and changes nothing else.

| File | Applies to | Covers |
| --- | --- | --- |
| `coding.md` | every change to source code | staying in the card's folders, reusing what exists, one source of truth, no compatibility shims, no dependency change without a yes |
| `testing.md` | every change that alters behavior | a regression test for each bug fix, a test for new logic, none for a style change; fast, deterministic tests; a phone-width browser check for touch or layout work |
| `security.md` | input, accounts, data and secrets | checks on the server, scoped queries, validated input, no secrets in logs or output, outside text treated as data |
| `performance.md` | request paths, screens and loops over data | few round trips, indexes, paged lists, slow work in the background, measured before and after |
| `accessibility.md` | everything a person sees or touches | native elements, keyboard and focus, contrast, 44-point touch targets, checks at phone and desktop width |
| `git.md` | branches, commits and PRs | one branch and worktree per card, small commits, never pushing to the base branch, one PR per batch |

Read the files themselves in [`colony/presets/lean/`](../colony/presets/lean/) for every line.

## `puffin`

Puffin Calendar's engineering system, minus the product. It ships in the package, in [`colony/presets/puffin/`](../colony/presets/puffin/), with Puffin's own names already taken out. It is far longer than `lean`, about 15,000 words, because every line names its reason.

- **Frontend rules:** performance, full stack, accessibility, coding, design principles, and testing.
- **Backend rules:** service performance, security and privacy, and database.
- **Process rules:** commits, pull requests and writing.
- **Essentials for each app:** an area file in each app's folder, with the numbered must-lines every change there obeys, each naming the rule that holds it in full. A Next.js app gets the Next.js, React and TanStack Query lines. A Python service gets the FastAPI, Pydantic, SQLAlchemy and Postgres lines. Any other app gets the generic lines.
- **A docs guide** that sends the reviewer, and any unsure builder, to the docs for the installed version: `node_modules/next/dist/docs/` for Next.js, and Context7 for other libraries.

Setup fills in your app folders and your check commands. Pick it when your stack is close to Puffin's: a Next.js web app, a Python service, or both.

## `own`

No new rules. `[gate] rules` lists your repo's `CLAUDE.md` and `AGENTS.md` files, and the reviewer checks against them.

Pick this when your rules are already written down. When they are thin, the reviewer has little to check against, and `lean` is the safer start.

## Your must-not lines

Question 5 asks what agents must never do in your repo. Setup writes each answer as a must-not line in `.colony/rules/project.md`, whichever preset you pick. Add lines there any time.

## Change the rules later

Everything in `.colony/rules/` is yours. Edit a file, add one, or delete one, and update `[gate] rules` when you add a file outside the listed patterns. Commit the change, and the next batch's reviewer uses it.

To switch to another preset, replace the files in `.colony/rules/` and set `preset` in `colony.toml` to match. To start setup over, remove `.colony/` on a new branch and run `colony`.

## How rules load

Rules load on demand. An edit loads only its area's short file, and the full set is the reviewer's checklist. On Puffin Calendar's first batch, this cost 14% less per session than loading every rule each time.
