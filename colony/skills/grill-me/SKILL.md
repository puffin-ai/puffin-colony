---
name: grill-me
description: Interview the person relentlessly about a plan, a design or an idea until every decision in it is settled. Use when the person asks to be grilled, wants a plan stress-tested, or wants their thinking challenged before any card is made.
---

# Grill me

Interview the person until you share one understanding of the plan. Map it as a **design tree**: each decision branches into the decisions that hang off it.

## Rounds

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are settled: the questions you can ask now without guessing at answers you haven't heard. Ask the whole frontier in one round, numbered, each with your recommended answer, then wait for the person's answers. This is the one kind of reply that asks several questions at once, because the person asked for the grilling.

    Q1. <title>: <the question, with its choices when it has some>
    My pick: <your recommended answer, and why in one line>

    Q2. <title>: <the question>
    My pick: <answer>

Each round's answers move the frontier outward. A question whose answer depends on another question still open belongs to a later round.

## Facts are yours, decisions are theirs

Look up every fact yourself, in the code, the docs, the issues or the tools, and never ask the person for one. A lookup still running is an open prerequisite: only the questions that depend on it wait for it, so ask the rest of the frontier now. Put every decision to the person.

## Done

The grilling is done when the frontier is empty: every branch visited and nothing silently assumed. Then write the settled tree back in a few lines, and act on it only after the person confirms it, as cards, or as a spec when the work is a feature.
