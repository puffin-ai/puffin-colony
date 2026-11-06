# Explained simply

This page tells the whole of Puffin Colony as one story. Then it says what each part of the story is in real life. For every detail, read [overview.md](overview.md).

## The story

You are the boss of a puffin colony.

You don't catch fish yourself. You tell the lead puffin what you want: "I'd like a bigger nest, and please fix the leaky corner."

The lead puffin thinks about the job. It cuts it into small jobs, and writes each one on a card. Then it gives each card to a helper puffin.

Each helper puffin has its own corner of the nest. It works only there, so it never bumps into another helper. When a job is too big to hold in its head, a helper sends little chicks to look things up, and the chicks come back with a short answer.

Every few seconds, each puffin looks up at the notice board to see if there is a note for it. Most notes can wait. A note that says "urgent" gets read at once.

When the helpers say they are done, two more puffins come in. The checker puffin reads every change with fresh eyes. The tester puffin walks through the nest and pokes at everything, the way you would. Each mistake they find goes back to the puffin who made it. Then they check again. They keep going until there are no mistakes left.

Then the lead puffin brings you one finished thing and asks: "Is this what you wanted?" You say yes, and it is done.

The lead also writes down what it learned, so next time the colony knows more. And if your friend runs a colony next door, your lead puffin and their lead puffin talk over the fence.

Your job is to decide. The puffins do the chores.

## What each part really is

| In the story | In real life |
| --- | --- |
| You, the boss | You. You talk only to your lead, answer what it can't decide, and merge. |
| The lead puffin | The lead: the Claude Code session you type into. It sizes each request, plans, and hands out work. |
| Helper puffins | Builders: more Claude Code sessions, such as `builder-2`. Each builds one card at a time on its own branch. |
| A helper's corner of the nest | The folders and the git branch a builder works in, so builders don't collide. |
| The chicks | Subagents. A builder sends them to search code or check a page in a browser, and gets back a short summary. |
| A card | A GitHub issue for one small job, with up to 3 "done when" results. |
| The notice board | The board: a GitHub Project that shows where each card is and who has it. |
| Looking up every few seconds | The watcher: every session checks GitHub every 15 seconds for lines addressed to it. Urgent lines arrive at once. |
| The checker puffin | The reviewer: a fresh Claude Code session each round, which reads only that round's changes and the open problems. |
| The tester puffin | The tests and the walk: your test suite, plus a real browser that clicks through the app like a person. |
| Sending mistakes back | Fixers: each open problem goes back to the builder whose card made it, round after round, until 0 are open. |
| The one finished thing | The pull request: one PR per batch, with the problems found in each round, the minutes and the cost. |
| Writing down what it learned | The vault: `knowledge/`, pages of research, specs and decisions in your repo. The retro turns each lesson into a rule and a check. |
| The colony next door | Other leads: each person on a team runs their own lead, and the leads talk on one shared GitHub issue. |

## Where to go next

- [The README](../README.md), to install it and start.
- [overview.md](overview.md), for every part on one page, with diagrams.
- [how-it-works.md](how-it-works.md), for each step and the command behind it.
