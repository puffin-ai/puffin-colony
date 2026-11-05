---
name: colony-lead
description: The Puffin Colony lead's steps. Use when you are this repo's lead (COLONY_SESSION is lead, or colony hi said this session claimed the lead), and before you turn a request into cards, open a builder, hand out a card, merge a done branch, run colony batch, or ask the person a question.
---

# Colony lead

Read `.colony/playbook.md`, the Lead section, and follow it literally. Its Lines and Stop list sections bind you too. This skill adds only what the lead needs beyond it.

- When `colony hi` made you the lead, start every `colony` command with the env line it printed, and keep `colony wait` running: its heartbeat holds the lead, and past 2 minutes without one, another session may take it. When `colony wait` says another session holds the lead, you are no longer the lead: tell the person in one line, and stop leading.

- Name the files on a card when you know them, beside its folders, because finding code costs a builder about 40% of a small change's calls.
- Keep a card to one concern and up to 3 done-when results, so its builder can finish it in one sitting.
- Read a builder's diff only when its `done` line needs a decision. The batch's fresh reviewer reads every diff in full.
- Answer a builder's question on its card at once, with a pick, even when the answer is "your default is right".
- Keep each message to the person short: the pull request link, what is done, and one question with your pick as the default.
