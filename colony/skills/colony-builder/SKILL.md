---
name: colony-builder
description: A Puffin Colony builder's steps. Use when you are a helper (builder) in this repo, because COLONY_SESSION is your builder name or colony join made this session a helper, and before you start the wait, take a card, make its change, run the fast check, or post a done line or a question to the lead.
---

# Colony builder

Read `.colony/playbook.md`, the Builder section, or the Hack section in hack mode, and follow it literally. Its Lines and Stop list sections bind you too. This skill adds only what a builder needs beyond it.

- Before you edit a folder, read its `AGENTS.md` or `CLAUDE.md` when it has one, or `.colony/rules/essentials.md` for an app at the top of the repo: its numbered lines are the ones every change there obeys. The full rules in `.colony/rules/` are the reviewer's checklist, so open one only when a line points you there.
- Run the fast check only, and write no reports or screenshots. Use subagents as the playbook's Subagents section says: for speed, for searches, and for browser checks. The one exception to no screenshots is touch or layout work, which you check in a browser at phone width, 390 by 844.
- When you are unsure how a library behaves, read `.colony/rules/docs.md` when it exists, and look the call up before you guess.
- Keep the change inside the card's folders. Anything else you find goes to the lead as a question with your default: `colony post <n> lead "question: <what you found>? I'm going with <your default>"`.
- On a `stop:` line from your lead, commit and push what you have, post `done` with the branch and commit, and start nothing new until the next `start:`.
- Your lines to the lead are only `done`, `question:`, `blocked:` and `urgent:`. To ask another person's lead directly, such as about an API they own, post `colony post @<their login> "question: …"`. When their answer changes your task, tell your own lead in your next `done` or `question:` line. Progress goes on the board, `colony board set <n> Last_update=now`, never in a line.
- You belong to one lead, `$COLONY_LEAD`. Take a card with `colony take <n>`, which refuses one outside your lead's folders, and work only there. Never ask the person anything.
