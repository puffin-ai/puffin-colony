---
type: type-definition
created: 2026-11-05
description: How to write a launch plan, the page that takes {product} to one launch through its milestones, with exit criteria for each milestone and one owner for every item. Read before creating or updating the launch plan.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Launch plan

A launch plan is the page that takes {product} to one launch. A launch is the moment {product} opens to a new group of people, such as its first testers or the public. The page holds the milestones on the way, the exit criteria that say when each milestone is done, how a change reaches the base branch, and every item of work grouped by its owner and its milestone. The owner, the agents, and the people building {product} read it to know what to do next and how far the launch has come. Write one when the owner sets a launch and the work spans several builds, several features, and several owners. Routing test: if the page assigns the whole road to a launch across builds and owners, it is a launch plan.

## Send it elsewhere when

- The page tracks one build from its gates to its last feature. That is a [[build-checklist]], and the launch plan links it.
- The page states, designs, or divides one feature. That is the feature's [[feature-requirements]], [[feature-design]], or [[feature-tasks]] page, and an item of the launch plan links it.
- The page is an ordered procedure an operator follows. That is a [[runbook]].
- The page records one accepted call. That is a [[decision-record]].
- The page states why {product} exists or how it wins. That is a [[singleton]] such as the vision or the strategy.

## Frontmatter

```yaml
type: launch-plan
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-reviewed: YYYY-MM-DD    # the date of the last full review of every item
```

## Skeleton

- **Title.** The product's or the launch's name followed by "launch plan", such as "{product} version 1 launch plan". The file name then differs from this definition's, as [[naming-and-links]] requires.
- **Opening.** What the launch is, who set it and when, the conventions the page follows, and where the live claims and status reports sit.
- `## Milestones`. One subsection per milestone, in order, each with a short purpose and its exit criteria as boxes.
- `## How a change reaches the base branch`. The steps every change takes from a branch to the base branch, and what each pull request shows the owner.
- `## How the agents work together`. The working rules every owner of items follows, person or agent.
- `## Who does what`. A table of every owner, the owner's job, and what the owner owns.
- One `##` section per owner, with what the owner owns, followed by one subsection per milestone that holds the owner's items as boxes.
- `## After the launch`. The work the plan leaves out, each with where it waits.

## Rules

1. A launch plan must cover exactly one launch, named in its opening.
2. Every milestone must end in exit criteria, each a box a reviewer can confirm by looking at the base branch, a pull request, or a running system.
3. Every item must have exactly one owner and sit under exactly one milestone.
4. A box may be ticked only in a pull request that delivers or links the item's evidence.
5. An item that moves to another milestone, or leaves the plan, must have its reason posted where the live claims sit before the change merges.
6. Each feature an item builds in several tasks must have its spec documents under [[docs-life-cycle#Plan]], and the item must link them once they exist.
7. The whole plan must be reviewed at every milestone, and the review date must be written in `last-reviewed`.

## Before you publish

- Does the page cover one launch, named in its opening?
- Does every milestone end in exit criteria a reviewer can confirm?
- Does every item have exactly one owner and one milestone?
- Is every ticked box backed by a pull request that delivers or links its evidence?
- Is `last-reviewed` set to the date of the last full review?

## Background

This type follows the launch readiness checklist of Google's site reliability practice for its milestones, a responsibility assignment matrix for its items, and the task list syntax of GitHub for its boxes.

From the launch readiness checklist we adopt exit criteria a reviewer can check, grouped under a small number of milestones, and the rule that an item earns its place only when a milestone needs it. From the responsibility assignment matrix we adopt exactly one owner for every item, so no item is shared and none is orphaned. From GitHub we adopt the box written as `- [ ]` and ticked as `- [x]`, because GitHub renders it and counts the ticked boxes.

We drop the dates and the critical path of a project schedule, because the pull requests carry the dates and the owners choose their own order inside a milestone. We drop the consulted and informed roles of the matrix, because the board carries every conversation. We drop the per-feature life cycle boxes of a build checklist, because each feature's own pages carry its life cycle.
