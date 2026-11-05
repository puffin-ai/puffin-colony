---
name: implement-spec
description: Turn an approved spec into cards, run them through builders in parallel, and land them in one batch pull request. Use when you are the lead and a spec's requirements are approved, or when the person asks you to implement a spec or a feature's task list.
---

# Implement a spec

The goal is one batch pull request that implements the whole spec. Start only when the person has approved the spec's requirements; before that, the spec goes back to them.

## The tasks are a graph

The spec's tasks are not a list of steps. They are a **task graph**: some tasks block others. At any moment the **frontier** is every task whose blockers are done, and every frontier task can be built now, in parallel.

## Steps

1. **Read the spec**: its requirements, its design and its tasks, enough to draw the graph. Note each task's blockers and the folders it touches.
2. **Explore once, when the tasks need it.** Read the code and the library docs the tasks lean on, and write the findings in one notes file the cards can point to, so each builder starts building instead of searching.
3. **Make a card per task** on the frontier, titled `<builder>: <what>`, with the task's done-when results, its folders and files, and **context pointers**: a link to the spec's section, the notes file, and the commits it builds on. Point; don't copy the spec into the card. Give tasks that touch the same folders to the same builder.
4. **Hand the frontier out** at once, one card per free builder, and open more builders up to `max_builders` when the frontier is wide.
5. **Merge each done card** into the batch worktree as the playbook says. When a merge moves the frontier, make and hand out the newly ready cards at once, so no builder waits.
6. **Run the batch** when every task is done, or every 3 to 5 cards: `colony batch --name <batch> --card <n>=<branch> ...`. Give each problem it can't fix to the card that owns it.
7. **Report** the pull request link to the person, with each requirement and the card that built it, and any requirement left out with the reason.

## Done

Every task in the graph has a done card, every requirement in the spec maps to a card and a test, the batch printed `done`, and its pull request names the spec.
