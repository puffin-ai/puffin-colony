---
name: writing-for-agents
description: How to write a document an agent reads, so it takes the same path every run. Use when you create or edit a skill, a rule in .colony/rules/, .colony/core.md, or a CLAUDE.md or AGENTS.md.
---

# Writing for agents

This is the reference for any document an agent consumes: a skill, a rule, the core, an `AGENTS.md` or `CLAUDE.md`, or a page reached by a pointer. The packaging differs; the writing doesn't. The aim is a predictable process: the agent takes the same path through the document every run.

## The two loads

Every document and pointer you add spends one of two budgets:

- **Context load**: what sits in the agent's window every turn, whether or not it fires, such as an `AGENTS.md` line or a skill's description.
- **Cognitive load**: what the person must remember exists and when to reach for it. Spend it where the person's judgement matters.

Material behind a pointer costs only the pointer's line. Material with no pointer at all costs only cognitive load.

## Colony's three levels

Pick the level by who needs the line, and how often:

1. **`.colony/core.md`** loads for every agent on every turn. Only duties every agent needs every time go here, and pointers to the rest.
2. **An app folder's `AGENTS.md`** loads when an agent opens a file in that folder. It holds numbered must-lines for every change there, each naming the rule that holds it in full.
3. **`.colony/rules/*.md`** load on demand and are the reviewer's checklist. A standard goes here, because the reviewer reads a diff with the least context pressure, while the builder carries the most.

A skill sits beside them: its description is always loaded, its body only when it fires, so a procedure some tasks need belongs in a skill.

## Context pointers

A **context pointer** is a line in context that names material out of context and says when to reach it: a skill's description, or an essentials line naming a rule. The pointer's wording, not its target, decides when the agent reaches the material. A needed target behind a weak pointer is a variance bug: sharpen the wording first, and inline the material only when that fails.

- Put the **leading word** first, where it triggers.
- Write **one trigger per branch**, a branch being a distinct case the document handles. Synonyms for one case are one branch written twice.
- Cut what the body already says.

## Steps and reference

A document holds **steps**, the actions in order, and **reference**, the facts consulted on demand. Rank each piece by how soon the agent needs it:

1. a step in the file
2. reference in the file
3. reference in another file, behind a pointer

Inline what every branch needs; push behind a pointer what only some branches reach. Keep a concept's definition, rules and caveats under one heading. A document too long even when every line is live is **sprawl**: disclose reference and split by branch.

## Completion criteria

End every step on a criterion that tells done from not done. A vague one, such as "understand the code", invites premature completion. A strong one is checkable and exhaustive: "every changed model has a migration and a test". Sharpen a fuzzy criterion before anything else. Split a sequence across a real hand-off only when the agent visibly rushes a step to reach the next.

## Leading words

A **leading word** is a compact idea the model already knows, such as *tight*, *red*, *tracer bullet* or *frontier*. Repeated as a word, it anchors a whole behavior in few tokens. Look for a triad or a sentence that one word can replace: "fast, deterministic, low-overhead" becomes *tight*.

Steer by the positive. A ban drags the banned behavior into view; say what to do, and keep a prohibition only as a hard guardrail, paired with the target behavior.

## Pruning

- Keep each meaning in **one source of truth**, so a change is a one-place edit.
- Treat the environment as a source of truth too: scripts, config, the folder layout, `--help`. Restate only what the agent can't find by looking, such as an unwritten convention or the reason behind a choice.
- Check every line for relevance, and delete stale layers instead of adding beside them.
- Hunt **no-ops**: a sentence the model already obeys by default. Delete the whole sentence. A word too weak to change behavior, such as *thorough*, needs a stronger one, such as *relentless*.

## Skills

- A skill's folder name is its `name`, and its `description` says what it is and the branches that trigger it, starting with "Use when". The description is always loaded, so prune it hardest.
- A skill the agent must reach on its own, or that another skill invokes, keeps a model-facing description. A skill only a person ever starts can set `disable-model-invocation: true` and costs no context.
- Colony ships each skill as one `SKILL.md`. Keep a skill in that one file, and move reference several skills share into a rule they point to.
