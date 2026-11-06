# Explained simply

This page says what Puffin Colony does in plain words, using the real names for each part. For every detail, read [overview.md](overview.md).

## In seven steps

1. **You tell a lead what you want.** The lead is the Claude Code session you type into. For example: "Add a dark mode switch, and fix the date picker on phones."
2. **The lead splits it into cards and gives each card to a helper.** A card is one small job, written as a GitHub issue. A helper is another Claude Code session, such as `builder-2`.
3. **You can run lots of helpers at once, on this computer or others.** Each helper belongs to one lead, and works only in its part of the code, on its own branch. So helpers don't bump into each other.
4. **A helper uses subagents to finish faster.** Subagents are mini-workers. Each one does one piece of the card at the same time as the others, and hands back a short result. Helpers also use them to search the code and to check a page in a browser. More helpers means more cards at once. More subagents means each card finishes sooner.
5. **Colony checks everything.** It runs the tests. A fresh reviewer reads the changes. A walker clicks through the app like a person would. Each problem goes back to the helper that made it, and they check again, until 0 problems are left.
6. **The lead brings you one PR, and you merge.** A PR, or pull request, holds all the changes, with the problems found in each round, the minutes and the cost.
7. **What they learn goes in the vault, and leads can talk to other people's leads.** The vault is `knowledge/`, pages of research, specs and decisions in your repo. On a team, each person has their own lead, and the leads talk on one shared GitHub issue.

Your job is to decide. The lead and its helpers do the chores.

## Each part in one line

| Part | What it is |
| --- | --- |
| You | You talk only to your lead, answer what it can't decide, and merge. |
| Lead | The Claude Code session you type into. It sizes each request, plans, and hands out cards. |
| Helper | Another Claude Code session, such as `builder-2`. It builds one card at a time on its own branch. |
| Subagent | A mini-worker a helper starts. Many run at the same time, each on one piece, so the card finishes sooner. Each hands back a short result. |
| Card | A GitHub issue for one small job, with up to 3 "done when" results. |
| Board | A GitHub Project that shows where each card is and who has it. |
| Watcher | Every session checks GitHub every 15 seconds for lines addressed to it. Urgent lines arrive at once. |
| Reviewer | A fresh Claude Code session each round, which reads only that round's changes and the open problems. |
| Walker | A real browser that clicks through the app like a person. |
| Fixer | The helper whose card made a problem, sent back to fix it, round after round, until 0 are open. |
| PR | One pull request per batch, for you to merge. |
| Vault | `knowledge/`. The retro turns each lesson into a rule and a check. |
| Other leads | Each person on a team runs their own lead, and the leads talk on one shared GitHub issue. |

## Where to go next

- [The README](../README.md#install-once-then-pick-one-of-3-setups), to install it and pick a setup.
- [overview.md](overview.md), for every part on one page, with diagrams.
- [how-it-works.md](how-it-works.md), for each step and the command behind it.
