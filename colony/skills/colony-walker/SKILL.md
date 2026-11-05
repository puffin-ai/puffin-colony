---
name: colony-walker
description: How a Puffin Colony walker checks a batch's screens in a browser. Use when colony batch starts you as its walker, or when you are asked to walk a Colony batch's changed flows in a browser and write a walk pass or fail report.
---

# Colony walker

Read `.colony/playbook.md`, the Lead section's batch step, for where the walk sits in the batch. The prompt `colony batch` hands you sets the checkout, the cards, and the report's path, and it wins over this skill. This skill adds only what a walker needs beyond them.

- Drive the browser through the Playwright MCP tools when this repo's `.mcp.json` lists `playwright`, and otherwise through the browser tool the session has.
- Start your own stack from the walk checkout, and stop it when you are done. Leave every other checkout alone.
- Take the flows from the cards' done-when lists, and walk each one from a fresh load at desktop 1280 by 800 and at phone 390 by 844 with touch input, in light and dark.
- Time every interaction a card names, and record the figure beside its flow.
- Start the report with exactly `walk: pass` when every flow passes, or `walk: fail`, then one line per flow, then each failure with its screenshot path, then any console errors.
