---
type: type-definition
created: 2026-11-05
description: How to write a feature's tasks page, the third of the three spec documents of FEATURE work built in several tasks, which divides the feature into ordered tasks, gives each task its contract and its tests, ticks one box per task as the feature's own checklist, and traces every requirement to a task and a test. Read before dividing a feature into tasks, before starting a task, or before changing a task's contract.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Feature tasks

A feature tasks page divides one feature into the tasks that build it, in build order, each landing in the change that delivers it. It is the third of the feature's three spec documents, written under [[docs-life-cycle#Plan]] from the [[feature-requirements]] and the [[feature-design]] pages. Each task carries a contract that its change is reviewed against, and the page's checklist holds one box per task, so the page is the feature's own checklist. A traceability table maps every requirement to the tasks that deliver it and the tests that prove it, and review reads that table. Routing test: if the page divides one feature into contracted tasks, it is a feature tasks page.

## Send it elsewhere when

- The page states what the feature must deliver. That is a [[feature-requirements]] page.
- The page proposes how the feature is built. That is a [[feature-design]] page.
- The page tracks a whole build across its features. That is a [[build-checklist]], and it links this page.
- The page records what the feature built and how it differed from its tasks. That is a [[reconciliation-report]], and it links this page.
- The page describes the capability as it runs after the work. That is a [[living-spec]].

## Frontmatter

```yaml
type: feature-tasks
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
feature: <the feature these tasks build, one line>
```

## Skeleton

- **Title.** The feature's name followed by "tasks".
- `## Checklist`. One task list box per task in build order, written as `- [ ] Task N. <name>`, and ticked as `- [x] Task N. <name>: <branch> <merge commit>` in the change that delivers the task.
- `## Tasks`. One `### Task N. <name>` subsection per task, holding its contract as a list: the behavior, the surface it changes, the inputs, the outputs, the requirement identifiers it serves, the tests that prove it, the acceptance checks, and what it waits for.
- `## Traceability`. A table with one row per requirement of the [[feature-requirements]] page, in its order, under the columns Requirement, Tasks, and Tests. The Requirement cell holds the identifier, the Tasks cell names the task numbers that deliver it, and the Tests cell names the tests that prove it.
- `## Revisions`. Each accepted change to a task's contract after the page was first committed, dated, with its reason and its change. The word "None" when no contract has changed.

## Rules

1. A tasks page must cover one feature, named in its title and its `feature` field, and must sit in the folder of its [[feature-requirements]] and [[feature-design]] pages.
2. Every task must land in its own change, built from one card, and must carry the full contract the Tasks section names, because the merge is reviewed against that contract.
3. Every requirement of the [[feature-requirements]] page must appear in the Traceability table with at least one task and at least one test, and the table must name no identifier that page lacks.
4. A box must be ticked only in the change that delivers its task, naming its branch and its merge commit.
5. The change that delivers the feature's last task must link the feature's [[reconciliation-report]] from the Checklist.
6. A change whose implementation departs from a task's contract must update it in the same change and record the change under Revisions, following [[docs-life-cycle#Contract and test changes]].
7. A task must be added, removed, or reordered only through a change that records the change under Revisions.

## Before you publish

- Does the title name one feature, and does the page sit beside its requirements and design pages?
- Does the Checklist hold one box per task, in the order of the Tasks section?
- Does every task carry the full contract, with its requirement identifiers and its tests?
- Does every requirement appear in the Traceability table with a task and a test, and no identifier the requirements page lacks?
- Is every change to a merged contract recorded under Revisions?

## Background

This type follows the task breakdown of spec-driven development. GitHub's Tasks phase breaks the specification and the plan into small, reviewable chunks, each one something that can be implemented and tested in isolation. Microsoft breaks the work into traceable tasks and validates the alignment between the requirements and the plans before any code is written. Anthropic's committed plan names the files that change, the order of the work, the risks, and the proof, and it is updated in the same commit when the implementation departs from it.

From these we adopt the ordered small tasks, the proof named for each, the traceability from requirement to task to test with a check that runs before any code, and the update of the page in the same change that departs from it. From the retired [[implementation-plan]] type we keep the contract each task is reviewed against. We drop the generated parallel markers and the per-task prompts of the tools, because one builder builds one card at a time here.
