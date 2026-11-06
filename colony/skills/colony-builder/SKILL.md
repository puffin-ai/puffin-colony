---
name: colony-builder
description: A Puffin Colony builder's steps. Use when you are a helper (builder) in this repo, because COLONY_SESSION is your builder name or colony join made this session a helper, and before you start the wait, take a card, make its change, run the fast check, or post a done line or a question to the lead.
---

# Colony builder

Read `.colony/playbook.md`, the Builder section, or the Hack section in hack mode, and follow it literally. Its Lines and Stop list sections bind you too. This skill adds only what a builder needs beyond it.

- Before you edit a folder, read its `AGENTS.md` or `CLAUDE.md` when it has one, or `.colony/rules/essentials.md` for an app at the top of the repo: its numbered lines are the ones every change there obeys. The full rules in `.colony/rules/` are the reviewer's checklist, so open one only when a line points you there.
- Run the fast check only. Write no reports or screenshots, and start no subagents. The one exception is touch or layout work, which you check in a browser at phone width, 390 by 844.
- When you are unsure how a library behaves, read `.colony/rules/docs.md` when it exists, and look the call up before you guess.
- Keep the change inside the card's folders. Anything else you find goes to the lead as a question with your default: `colony post <n> lead "question: <what you found>? I'm going with <your default>"`.
- Your lines to the lead are only `done`, `question:`, `blocked:` and `urgent:`. Progress goes on the board, `colony board set <n> Last_update=now`, never in a line.
- You belong to one lead, `$COLONY_LEAD`. Take a card with `colony take <n>`, which refuses one outside your lead's folders, and work only there. Never ask the person anything.
