---
type: type-definition
created: 2026-11-05
description: How to write a feature spec, the one page of FEATURE work built in one task, which states the problem, the behavior with its requirement identifiers, the constraints, the non-goals, and the acceptance checks that trace each requirement to its tests, in at most 12,000 bytes. Read before planning FEATURE work that one task builds.
assisted-by: claude-code:claude-fable-5
enforced-by: colony check-docs for the size cap, human review in the pull request
---

# Feature spec

A feature spec states what one feature built in one task must deliver and how a reviewer will know it did, on one page. It replaces the three spec documents for FEATURE work that one task builds, under [[docs-life-cycle#Plan]], because a one-task feature has no task order to plan and no design large enough for a page of its own. The page links each [[prd]] requirement the feature delivers by its identifier, numbers the requirements no PRD owns, and traces every requirement to the tests that prove it. Routing test: if the page states what one feature built in one task must deliver and how each requirement is checked, it is a feature spec.

## Send it elsewhere when

- The feature is built in several tasks. That is a [[feature-requirements]], a [[feature-design]], and a [[feature-tasks]] page.
- The page defines what a product area does and why, for every feature that touches it. That is a [[prd]] in the wiki, and this page links it.
- The page describes what the user sees and what happens when they act. That is a [[design-spec]].
- The page records one accepted call that outlives the feature. That is a [[decision-record]].
- The page describes the capability as it runs after the work. That is a [[living-spec]].

## Frontmatter

```yaml
type: feature-spec
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
feature: <the feature this page specifies, one line>
code: <two to five capital letters that prefix this page's own requirement identifiers>
```

## Skeleton

- **Title.** The feature's name followed by "spec".
- `## Problem`. Who gains what, why it matters now, and the build or checklist the feature belongs to, in a short paragraph readable on its own.
- `## Behavior`. Each requirement as one list item. A PRD requirement names its identifier and links the PRD. A requirement no PRD owns is stated in full under an identifier built from the `code` field. Each item nests its acceptance criteria.
- `## Constraints`. The limits the build must respect, such as a performance budget, a privacy line, or a decision record it follows, each linked to its home.
- `## Non-goals`. The nearby work a reader might expect here, and the feature or page that owns each part.
- `## Acceptance checks`. A table with one row per requirement of the Behavior section, in its order, under the columns Requirement and Tests. The Requirement cell holds the identifier, and the Tests cell names the tests that prove it.

## Rules

1. A feature spec must cover one feature built in one task, named in its title and its `feature` field, and must sit alone in its folder under `{knowledge}/specs/plans/`, beside only the feature's [[reconciliation-report]].
2. The page must stay at or under 12,000 bytes, because a feature that needs more is built in several tasks and takes the three spec documents.
3. The writer must link each PRD requirement by its identifier and must not copy its text, because a second copy of a requirement can drift.
4. A requirement no PRD owns must carry an identifier built from the `code` field and a two-digit number, as in `SKEL-01`, and must be one testable statement carrying exactly one force word, in the form the [[prd]] type sets.
5. Every requirement of the Behavior section must appear in the Acceptance checks table with at least one test, and the table must name no identifier the Behavior section lacks.
6. The page must not choose a file, a function, a table, or a library unless a linked [[decision-record]] has already fixed it, because the build owns those choices.
7. A change whose implementation departs from the page must update the page in the same change, following [[docs-life-cycle#Contract and test changes]].
8. The owner must approve the Behavior section before the feature's card is cut, under [[docs-life-cycle#Plan]].

## Before you publish

- Does the title name one feature that one task builds, and does the page sit alone in its folder?
- Does the page stay at or under 12,000 bytes?
- Is every PRD requirement linked by its identifier, with no copied text?
- Does every requirement carry acceptance criteria and a row in the Acceptance checks table that names a test?
- Does every identifier in the Acceptance checks table appear in the Behavior section?

## Background

This type follows the specification of spec-driven development, cut to one page for work one task builds. From that practice we adopt the page that states what and why before how, the acceptance criteria beside each requirement, and the trace from each requirement to the tests that prove it. We drop the separate design and task pages, because a one-task feature has one task and its design fits in the build's own review. We cap the page at 12,000 bytes, because the one quantitative evaluation of spec-driven development found a small quality gain bought with a 55 percent increase in time, and Osmani advises matching the spec's detail to the task.
