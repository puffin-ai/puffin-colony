---
type: type-definition
created: 2026-11-05
description: How to write a build checklist, the page that tracks one build of {product} from the gates that must hold before its first line of code to the last capability it delivers. Read before creating or updating the checklist of a build.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Build checklist

A build checklist is the one page that tracks a build of {product} from start to finish. A build is the construction of one runnable part of the system, such as a backend service. The page holds the build list, which names every capability the build delivers in the order it is built, with one box for each step of the life cycle, and names the gates, which are the conditions a feature cannot pass without. A gate that is a step only the owner can take lives in the [[owner-checklist]] of its field, and the build list links it. The owner and the agent tick through it together, and it is the page a reader opens to see where the build stands. Write one after the owner starts the build's life cycle, as its first planning work under [[docs-life-cycle#Plan]]. Routing test: if the page tracks the whole of one build as a list of confirmable items, it is a build checklist.

## Send it elsewhere when

- The page states, designs, or divides one feature. That is the feature's [[feature-requirements]], [[feature-design]], or [[feature-tasks]] page, and the build list links its tasks page.
- The page closes one feature with its coverage, drift, and measures. That is a [[reconciliation-report]], and the build list links it.
- The page is an ordered procedure an operator follows to perform or repair one known operation. That is a [[runbook]].
- The page proposes how a feature or an area is built. That is a [[tech-design]], and a gate or a build item links it.
- The page lists the steps only the owner can take in one field. That is an [[owner-checklist]], and the build list links each step that blocks a feature.
- The page records one accepted call. That is a [[decision-record]].
- The page describes a capability as it runs today. That is a [[living-spec]].

## Frontmatter

```yaml
type: build-checklist
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
build: <the runnable part this checklist tracks, one line>
last-reviewed: YYYY-MM-DD    # the date of the last full review of every item
```

## Skeleton

- **Title.** The build's name followed by "build checklist", which for the deployment reads "Deployment build checklist".
- `## What this tracks`. The build, the outcome it delivers, the start cue, who ticks the boxes and who confirms a gate, and the interval of the full review, in a short paragraph readable on its own.
- `## Gates`, present only when the build has a gate that belongs to it alone, such as the owner's confirmation of its build order. The owner's steps in a field live in an [[owner-checklist]] instead. One subsection per pause point, each holding at most nine items, the most critical first. The pause points that must hold before the build writes its first line of code come first, and the pause points that must hold before the build's first release to users come last. Each item is a task list box followed by the question in bold, the action that answers it, its owner, and a pointer to the page or pull request that explains it.
- `## Build list`. The features of the build in build order, each one a feature that one [[feature-tasks]] page divides. Each feature is a task list box naming the feature, the capabilities it delivers, the requirement families it serves with links to their PRDs, its design pages, and its [[feature-tasks]] page once it exists, followed by one nested box for each life cycle step: Agree the outcome, Inspect and plan, Build, Verify, and Release and learn. A build whose features reach users together through one release leaves out the Release and learn box, and its What this tracks names the feature or the build that carries that release. The feature's tasks page cites every requirement identifier the feature serves.
- `## Completion`. The written completion line that says when the checklist is complete.
- `## Changes`. One line per change to the list itself, dated, with its reason and its pull request.

## Rules

1. A build checklist must cover exactly one build, named in the `build` frontmatter field and in the title.
2. Every item must name one action with an observable result, its owner, and the page or pull request that explains it, because an item that names no action leaves its reader unsure what to do.
3. A box may be ticked only in the pull request that delivers the item's evidence, and the ticked line must name that evidence by pull request number or by the page it produced.
4. A gate subsection must hold at most nine items, and a larger group must be split into two pause points. A step only the owner can take in a field must sit in the [[owner-checklist]] of that field, and the build list must link it, not copy it. A gate that belongs to the build alone, such as the owner's confirmation of its build order, stays in its Gates section.
5. The build list must hold every capability of the build exactly once, under the feature that delivers it, and a capability outside the build must not appear on it.
6. A change to an item's scope, order, or wording must be recorded under Changes with its reason, and an item removed from the list must be recorded there too.
7. The whole list must be reviewed at least once a quarter, and the review date must be written in `last-reviewed`.

## Before you publish

- Does the page cover one build, named in its title and its `build` field?
- Does every item name an action, an owner, and a pointer to the page or pull request behind it?
- Does every gate subsection hold at most nine items, with the most critical first, and does every owner step a feature waits on link its owner checklist?
- Does the build list hold every capability of the build once, under a feature with its life cycle boxes?
- Is every ticked box backed by a named pull request or page?

## Background

This type follows the launch readiness checklist of Google's site reliability practice for its gates, the work breakdown structure of project management practice for its build list, and checklist design from aviation and surgical practice for its form.

From the launch checklist and the production readiness review we adopt the item shape, a question paired with a concrete action and a pointer to the page that explains it, the grouping of items under a small number of named themes, the rule that an item earns its place only when its importance can be shown, and the two rhythms of upkeep, small corrections as work happens and one full review of the whole list at a fixed interval. From the work breakdown structure we adopt the decomposition by deliverable, the rule that the list covers the whole of the build and nothing outside it, items that never overlap, one named owner for each item, acceptance criteria for each item, and a list that changes only through a reviewed change, which in this vault is a pull request. From checklist design we adopt a stated purpose before the first item, a start cue that cannot be missed, pause points that group items at natural breaks in the work, fewer than ten items at each pause point, the most critical items first, a written completion line, and the confirm-after-doing form, where the work is done first and the list confirms it. From GitHub we adopt the task list syntax, a box written as `- [ ]` and ticked as `- [x]`, because GitHub renders it and counts the ticked boxes.

We drop the pass-or-fail verdict of a readiness review, because a gate either holds with evidence or stays open with its next action named. We drop the cost accounts, schedules, and control accounts of the work breakdown structure, because the vault tracks outcomes and the pull requests carry the dates. We drop the typography, card sizes, and read-aloud rules of printed checklists, because the page is read on a screen and ticked in a pull request. We keep the gate that the software readiness sources warn can harden into a phase gate, because the owner confirms a build's gates before its first code, and the rules below keep it honest with evidence, a named owner, and a full review at a fixed interval.
