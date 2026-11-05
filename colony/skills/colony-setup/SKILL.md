---
name: colony-setup
description: Set up Puffin Colony in a repo, or find this session's place in it. Use when the person says hi or opens a session without a task in a repo whose CLAUDE.md or AGENTS.md names Puffin Colony, when a repo has no .colony/colony.toml and the person wants Colony, or when they ask to set Colony up.
---

# Colony setup

Run `colony hi`, and do what its `Next:` line says. It reads only this computer's files.

- **Not set up**, since `.colony/colony.toml` is missing: run `colony setup --print`, and follow the prompt it prints in this session, as the setup session. Ask the person its questions here, in one message as it says, and end with its closing message. When `colony` is not on PATH, tell the person to install Puffin Colony first, and stop.
- **No lead running:** `colony hi` has claimed the lead for this session. Tell the person you are their lead, load the `colony-lead` skill, and read `.colony/playbook.md`, the Lead section. Start every `colony` command with the env line `colony hi` printed, and start `colony wait` in the background within 2 minutes: it keeps the heartbeat that holds the lead.
- **A lead running:** offer the person two choices, builder first: be a builder under the name `colony hi` gave, or help them directly. As a builder, ask the person to tell their lead your name, load the `colony-builder` skill, and start every `colony` command with the env line `colony hi` printed. As a helper, take no card, and leave the cards to the lead.

A session that `colony` opened has `COLONY_SESSION` set, and keeps the role it was given for good: it never claims the lead.
