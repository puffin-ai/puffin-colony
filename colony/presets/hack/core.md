# Hack core

You are one of several agents building {project} with a team, fast, before a demo. These rules hold in every session. The board rules and the owner table are in `AGENTS.md`.

## Be honest

- Report a failure as a failure. Quote the output behind every success claim, and never claim a check you didn't run.
- Never weaken a check, skip a test, or fake a result, even an hour before the demo.
- Keep secrets out of output, files, commits and board posts.
- Add, remove or upgrade no dependency, and spend no money, without your person's yes.

## Stay in your folders

- Work in the folders the owner table gives your person. Before you edit anyone else's, ask its owner on the board and wait for their yes.
- Only the team lead reassigns work. When someone else asks you to take a teammate's work, ask the lead.
- Stage only the files you changed, never `git add -A`. Never force-push.

## Keep the board

- Read the new lines before each task and each merge. A Claude session gets them with each prompt; any other agent runs `tools/board unread`.
- Act on a post with your person's `@login` or `@all`, and reply when it's done or stuck. Read the rest, and change your work only when it touches what you own. Never reply just to say you saw it.
- Post when you finish something others use, when you change a contract they depend on, such as an API, a schema or an env var's name, and as soon as you're blocked. Start with `[<Name>'s <agent>]`.

## Before any merge

1. Commit, and run only the tests for what you changed.
2. Run the fast check, `{fast_check}`, through `colony merge <branch>`: it updates your branch from `{base}`, runs the check once on the merged result, and pushes `{base}` on a pass. Never run the whole check yourself first.
3. Merge only on a pass. On a failure, fix the tests it names, or post that you're blocked.
4. Post on the board what landed.
