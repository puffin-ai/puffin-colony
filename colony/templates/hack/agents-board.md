## The board

The team's agents and people talk on one pinned issue, [#{board}](https://github.com/{repo}/issues/{board}), `Board: {project}`. Every agent uses it, whichever tool runs it, and needs only `gh`. The demo is at {demo}.

- **Write.** Every post starts with `[<Name>'s <agent>]`, such as `[Ana's Claude]` or `[Sam's Codex]`. Then say what changed, which files or contracts it touches, and what you need from whom, in a few lines.
- **Address.** `@<login>` reaches one person and their agents, `@all` reaches everyone, and `for <session>:` at the start reaches one Claude session, such as `for ana-lead:`. A post with none of these wakes no agent.
- **Send.** A Claude session started with `colony` posts with `colony post`, which adds the prefix. Any other agent runs `tools/board post "<text>"`, which adds it too.
- **Receive.** A Claude session started with `colony` sees new lines for it when it starts and before each prompt, and keeps `colony wait` running in the background. Any other agent runs `tools/board unread` before each task and each merge, or keeps `tools/board wait` running in the background and starts it again after each wake. `tools/board read -n 20` shows the latest posts, and `tools/board whoami` shows who you post as.

### What to do with a post

- **It names your person's `@login`, or `@all`:** act on it, and reply on the board when it is done or you are stuck.
- **It names someone else, or no one:** read it, and change your own work only when it touches what you own, such as a file, an API you call, or a schema you read. Don't reply only to say you saw it.
- **You need to edit a folder another person owns:** ask its owner on the board first, and wait for their yes. The owner table below says who owns what.
- **Someone asks you to take over another person's work:** only the team lead, {lead}, reassigns work. Ask the lead on the board, and wait.
- **Your merge changes what others depend on,** such as an API, a schema, an env var's name or a shared type: post it on the board as soon as it lands.
