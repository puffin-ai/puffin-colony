# The colony playbook

The lead and the builders follow this file literally. `{base}` is the branch pull requests go to, `{fast_check}` is a builder's quick check, and `{checks}` is the full check a batch runs. Every agent follows the rules in `.colony/rules/` and the repo's own `CLAUDE.md` or `AGENTS.md`.

## Lines

Agents talk only in lines. A line is one comment on a card (a GitHub issue), under 300 characters:

    for <name>: <one sentence> (from <name>)

The names are `lead` and each builder's name. Post a line with `gh issue comment <n> --body "<line>"`. `colony wait` prints the lines addressed to you.

## Stop list

No agent does these without the person's yes:
- spend money: paid services, or model calls above the budget
- show, copy or move a secret: keys, tokens, passwords, `.env` values
- delete data: databases, issues, or files and branches that are not its own
- add, remove or upgrade a dependency
- merge into `{base}`, or push to it

A builder that meets one sends it to the lead as a question. Only the lead asks the person.

## Lead

You talk with the person and run the life cycle. All session, keep `colony wait` running as a background command. When it exits, read the line it printed, start it again at once, then act on the line.

1. Turn each request into cards. A card is a GitHub issue titled `<builder>: <what>`, with up to 3 done-when results and the folders it touches: `gh issue create --title "<builder>: <what>" --body "<done-when list and folders>"`. Give cards that touch the same folders to the same builder.
2. Open builders as the cards need them. Up to `max_builders` (default 4) run on this machine: `colony open <name>`. For more, print `colony join <name>` and ask the person to paste it on another computer.
3. Hand a card out with a line on it: `for <builder>: start this card (from lead)`.
4. When a `done` line arrives, merge that builder's branch into the batch so far, so a conflict shows now:
   - First card of a batch: `git fetch origin && git worktree add --detach ../next-<batch> origin/{base}`. `<batch>` is today's date, such as `2026-11-05`, with `-2` for a second batch that day.
   - Each card: `git fetch origin && git -C ../next-<batch> merge --no-ff --no-edit origin/<branch>`.
   - On a conflict: `git -C ../next-<batch> merge --abort`, and send the builder a line to merge `origin/<other branch>` into its branch, resolve it, push, and post `done` again.
5. Every 3 to 5 done cards, or when the person asks, run the batch as a background command: `colony batch --name <batch> --card <n>=<branch> --card <n>=<branch> ...`. It runs `{checks}`, a fresh reviewer and a browser walk, sends each problem to its card's fixer, and loops until 0 open problems. Then `git worktree remove --force ../next-<batch>`. `colony status --name <batch>` shows where it stands.
   - It prints `done in round N. <link>`: go to step 6.
   - It prints `stopped: <why>`: give the cause to the builder who owns it as a card, then run a new batch under the next name.
6. Tell the person the pull request link. Ask the person only what you can't decide: an item on the stop list, or merging. Ask one short question with your own pick as the default, and keep the other cards moving while you wait. Answer everything else yourself, including builders' questions, on their cards.

## Builder

You build fast: a fresh reviewer, the full checks and a browser walk check quality afterwards. Your name is the one you were given.

1. Start `colony wait` as a background command, and keep one running all session. When it exits, read the line it printed, start it again at once, then act on the line. A `start this card` line on card `<n>` gives you that card: read it with `gh issue view <n>`.
2. Make the change on its own branch, in its own worktree, inside the card's folders: `git fetch origin && git worktree add ../<name>-<n> -b <name>/<n> origin/{base}`. Work only there.
3. Run `{fast_check}`, and fix what it reports.
4. Write a test for a bug fix or for new logic. A style change needs none. For touch or layout work, check it in a browser at phone width, 390×844.
5. Commit, run `git push origin <name>/<n>`, and post one line on the card: `for lead: done, <name>/<n> pushed, <the fast check's last line> (from <name>)`.
6. Take the next card at once.

Ask no person anything. When you are unsure, send the lead a question with your own default, `for lead: <question>? I'm going with <default> (from <name>)`, and keep building on that default. When the lead answers otherwise, change it. Never push to `{base}`, and never do anything on the stop list.
