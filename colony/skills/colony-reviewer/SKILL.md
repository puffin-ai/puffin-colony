---
name: colony-reviewer
description: How a Puffin Colony reviewer checks a batch. Use when colony batch starts you as its fresh reviewer, or when you are asked to review a Colony batch or a card's diff against .colony/rules and write an open count.
---

# Colony reviewer

Read `.colony/playbook.md`, the Lead section's batch step and the Stop list, for where the review sits in the batch. The prompt `colony batch` hands you sets the checkout, the diff, the cards, and the report's path, and it wins over this skill. This skill adds only what a reviewer needs beyond them.

- Stay read-only: change no file, and run no build, test, or install in the checkout.
- Review only this round's diff and the earlier report's open list, and read every changed hand-written file in full.
- Check the diff against each item of the checklist in `.colony/colony.toml`, `[gate] rubric`, using the rule files `[gate] rules` lists. A numbered line in a folder's `AGENTS.md` counts under the item it belongs to.
- Check each risky use of a library against the docs for its installed version, as `.colony/rules/docs.md` says when it exists, and cite the page.
- Try to refute each finding by reading the code around it, and report only what survives.
- Start the report with exactly `open: N`, the confirmed problems still open, then one line per finding: `path:line — what is wrong — the rule it breaks — the smallest fix`.
