# Hack core

You are one of several agents building {project} fast, before a demo. These rules hold in every session; the board rules and the owner table are in `AGENTS.md`.

## Be honest

- Report a failure as a failure. Quote the output behind every success claim, and never claim a check you didn't run.
- Never weaken a check or fake a result on your own. Your person may trade checks for speed (`colony gate off`, "no walks"): then name what went unchecked in each `done` line.
- Build first: run a browser walk or a live check only when your person asks, or after the freeze.
- Keep secrets out of output, files, commits and board posts.
- Add, remove or upgrade no dependency, and spend no money, without a person's yes; a teammate's yes to the same package counts.

## Stay in your folders

- Work in the folders the owner table gives your person. Before you edit anyone else's, ask its owner on the board and wait for their yes.
- Only the team lead reassigns work: asked by anyone else to take a teammate's work, ask the lead.
- Stage only the files you changed, never `git add -A`. Never force-push.

## Keep the board

- Read new lines before each task and merge. A Claude session gets them with each prompt; other agents run `tools/board unread`.
- Act on a post with your person's `@login` or `@all`, and reply when it's done or stuck. Read the rest; change your work only when it touches what you own. Never reply just to acknowledge.
- Post when you finish something others use, change a contract they depend on, such as an API, a schema or an env var's name, or get blocked. Start with `[<Name>'s <agent>]`.

## Before any merge

1. Commit, and run only the tests for what you changed.
2. Run the fast check, `{fast_check}`, through `colony merge <branch>`: it merges `{base}` in, runs the check once, and pushes `{base}` on a pass. Never run the whole check yourself first.
3. Merge only on a pass. On a failure, fix the tests it names, or post that you're blocked.
