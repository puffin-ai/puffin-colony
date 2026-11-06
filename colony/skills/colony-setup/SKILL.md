---
name: colony-setup
description: What a session a person opened does first in a repo that runs Puffin Colony, or should. Use when the person says hi or opens a session without a task in a repo whose CLAUDE.md or AGENTS.md names Puffin Colony, when the first message is join or join <lead>, when a repo has no .colony/colony.toml and the person wants Colony, or when they ask to set Colony up.
---

# Colony setup

A session a person opens and types into is a lead, and never asks what it is. Run `colony hi`, and do what its `Next:` line says.

- **Not set up**, since `.colony/colony.toml` is missing: run `colony setup --print`, and follow the prompt it prints in this session, asking the person its questions here, once. When `colony` is not on PATH, tell the person to install Puffin Colony first, and stop.
- **No lead alive:** `colony hi` made this session `<person>-main-lead`. Start every `colony` command with the env line it printed, start `colony wait` in the background within 2 minutes, load the `colony-lead` skill, and ask the person what they want.
- **Leads alive:** say in one line who leads what, ask the person only "What's mine?", then run `colony claim <stream> <folder> ...` for their answer, avoiding the folders the live leads hold. Then carry on as above.
- **The first message is `join` or `join <lead>`:** run `colony join [<lead>] --in-session` instead, and be that lead's helper: load the `colony-builder` skill, and never ask the person anything.

A session `colony` opened has `COLONY_SESSION` set, and keeps its role for good.
