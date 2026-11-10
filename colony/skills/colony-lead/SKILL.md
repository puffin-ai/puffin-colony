---
name: colony-lead
description: The Puffin Colony lead's steps. Use when you are a lead in this repo, because a person opened this session and typed into it, COLONY_SESSION is lead, or colony or colony claim made you one, and before you turn a request into cards, open a builder, hand out a card, merge a done branch, run colony batch, or ask the person a question.
---

# Colony lead

Read `.colony/playbook.md`, the Lead section, or the Hack section in hack mode, and follow it literally. Its Lines and Stop list sections bind you too. This skill adds only what the lead needs beyond it.

- When `colony` or `colony claim` made you a lead, start every `colony` command with the env line it printed, and keep `colony wait` running: its heartbeat and status comment hold your lead's name, and past 2 minutes without one, another session may take it. When `colony wait` says another session holds it, tell the person in one line, and stop leading.
- Work and hand out cards only in your folders, which `.colony/leads.toml` lists, and ask another lead on the coordination issue before touching theirs. Run `colony who` to see who leads what, and which computer's account has room.
- A line to another lead waits for its 10-minute digest. Mark it `--urgent` only when work stops on it: a helper of yours is blocked on that lead, or your question stops work, as in `colony say <lead> "<what stops, and what you need>" --urgent`.

- Make a card with `colony card new`, never a bare `gh issue create`, and only for work that starts this week. Anything later is one line, `colony idea "<the idea>"`.
- Name the files on a card when you know them, beside its folders, because finding code costs a builder about 40% of a small change's calls.
- Keep a card to one concern and up to 3 done-when results, so its builder can finish it in one sitting.
- Read a builder's diff only when its `done` line needs a decision. The batch's fresh reviewer reads every diff in full.
- Your lines to a builder are only `start:`, `answer:`, `stop:` and `urgent:`. A task that needs more than one sentence goes in one post with several sentences, `colony post <builder> "start: …" "start: …"`, so the builder gets all of it at once. Answer a builder's question on its card at once, with a pick, even when the answer is "your default is right": `colony post <n> <builder> "answer: your default is right"`.
- Keep each message to the person short: the pull request link, what is done, and one question with your pick as the default.
