---
type: type-definition
created: 2026-11-05
description: How to write an owner checklist, the page that holds the steps only the owner can take in one field, such as legal or the platform approvals, each naming the build feature or the point it blocks. Read before creating or updating the owner's steps in a field, or before naming a step a build feature waits on.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Owner checklist

An owner checklist holds the steps only the owner can take in one field, such as legal, the platform approvals, or the accounts and keys. Each step is a gate: a feature of a [[build-checklist]] or a point such as the first invitation cannot pass until the step holds. The owner takes the steps, the agent ticks each box with the evidence the owner gave, and a build checklist links the step that blocks each of its features. Write one when the owner's steps in a field outgrow a line in a build checklist, or when a new field gains its first step. Routing test: if the page lists the steps only the owner can take in one field, each naming what it blocks, it is an owner checklist.

## Send it elsewhere when

- The page tracks one build from its first feature to its last. That is a [[build-checklist]], which links the owner's steps here.
- The page is an ordered procedure that performs one known operation. That is a [[runbook]], and a step links it.
- The page records one accepted call. That is a [[decision-record]].
- The page states what one feature must deliver. That is a [[feature-requirements]] page.

## Frontmatter

```yaml
type: owner-checklist
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
field: <the field this checklist covers, one line>
last-reviewed: YYYY-MM-DD    # the date of the last full review of every item
```

## Skeleton

- **Title.** The field's name followed by "checklist", as in "Legal checklist".
- `## What this tracks`. The field, who takes the steps and who ticks the boxes, and the interval of the full review, in a short paragraph readable on its own.
- `## Steps`. One `###` subsection per stage of the field, each holding at most nine items, the most critical first. Each item is a task list box followed by the question in bold, the action that answers it, what it blocks, its owner, and a pointer to the page that explains it.
- `## Changes`. One line per change to the list itself, dated, with its reason.

## Rules

1. An owner checklist must cover exactly one field, named in the `field` frontmatter field and in the title.
2. Every item must name one action with an observable result, its owner, and the page that explains it.
3. Every item must name what it blocks: a feature of a named build checklist with the life cycle step that cannot finish without it, or a point such as the first invitation.
4. The agent must tick a box only in the pull request that delivers the item's evidence, and the ticked line must name that evidence.
5. A step must sit in exactly one owner checklist, and a build checklist must link to it there.
6. A change to an item's scope, wording, or field must be recorded under Changes with its reason.
7. The whole list must be reviewed at least once a quarter, and the review date must be written in `last-reviewed`.

## Before you publish

- Does the page cover one field, named in its title and its `field` field?
- Does every item name an action, what it blocks, an owner, and a pointer?
- Does every subsection hold at most nine items, with the most critical first?
- Is every ticked box backed by named evidence?
- Does every step a build feature waits on appear here once, with the build checklist linking to it?

## Background

This type follows the same sources as the [[build-checklist]] gates. From Google's launch practice we adopt the item shape, a question paired with the action that answers it and a pointer to the page that explains it, and the grouping of items under named themes, since Google's own list runs by theme from architecture to external dependencies. A field here is one such theme. From checklist design we adopt groups of fewer than ten items, the most critical items first, and the confirm-after-doing form, where the owner acts first and the list confirms it. From GitHub we adopt the task list syntax, a box written as `- [ ]` and ticked as `- [x]`.

We put the owner's steps in one page per field, instead of one section per build, because one step can block features in two builds, and the owner works through a field at once, such as every legal step with counsel.

We drop the build list, the life cycle boxes, and the completion line of a [[build-checklist]], because an owner checklist tracks steps that have no build of their own and stay open until each holds. We drop the pause points that follow a build's order, because a field's steps follow the stages of that field instead. We drop the launch review's pass-or-fail verdict, as the build checklist does, because a step either holds with evidence or stays open with its next action named.
