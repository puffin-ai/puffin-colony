---
type: type-definition
created: 2026-11-05
description: How to write a feature's requirements page, the first of the three spec documents of FEATURE work built in several tasks, which links every PRD requirement the feature delivers, gives each one its acceptance criteria, numbers the requirements no PRD owns, and records the answers to every open question. Read before stating what a feature must deliver, or before writing its design.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Feature requirements

A feature requirements page states what one feature must deliver and how a reviewer will know it did. It is the first of the feature's three spec documents, written under [[docs-life-cycle#Plan]] and approved by the owner before any card is cut, and the [[feature-design]] and the [[feature-tasks]] pages build on it. The page links each [[prd]] requirement the feature delivers by its identifier, adds the acceptance criteria that decide whether the feature meets it, and numbers the requirements that no PRD owns. It also records the answer to every question the requirements left open. Routing test: if the page states what one feature must deliver and how each requirement is checked, it is a feature requirements page.

## Send it elsewhere when

- The page defines what a product area does and why, for every feature that touches it. That is a [[prd]] in the wiki, and this page links it.
- The page describes what the user sees and what happens when they act. That is a [[design-spec]].
- The page proposes how the feature is built. That is a [[feature-design]].
- The page divides the feature into tasks. That is a [[feature-tasks]] page.
- The page records one accepted call that outlives the feature. That is a [[decision-record]].
- The page describes the capability as it runs after the work. That is a [[living-spec]].

## Frontmatter

```yaml
type: feature-requirements
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
feature: <the feature these requirements belong to, one line>
code: <two to five capital letters that prefix this page's own requirement identifiers>
```

## Skeleton

- **Title.** The feature's name followed by "requirements".
- `## What this delivers`. The feature's outcome in a short paragraph readable on its own: who gains what, why it matters now, and the build or checklist the feature belongs to.
- `## Requirements`. One `###` subsection per source. A subsection named for a [[prd]] lists each of its requirements the feature delivers, each line naming the identifier and linking the PRD, with the requirement's acceptance criteria nested under it. A subsection named "Requirements no PRD owns" states each such requirement in full under an identifier built from the `code` field, with its acceptance criteria nested under it.
- `## Clarifications`. Each question the requirements left open, with its answer, who gave it, and the date, in the order the questions were settled. The word "None" when nothing was open.
- `## Out of scope`. The nearby work a reader might expect here, and the feature or page that owns each part.

## Rules

1. A requirements page must cover one feature, named in its title and its `feature` field.
2. The writer must link each PRD requirement by its identifier and must not copy its text, because a second copy of a requirement can drift.
3. A product requirement the feature needs and no PRD holds must be added to the PRD that owns the area in the knowledge commits before this page, and linked from this page.
4. A requirement no PRD owns must carry an identifier built from the `code` field and a two-digit number, as in `SKEL-01`, and must be one testable statement carrying exactly one force word, in the form the [[prd]] type sets.
5. Every requirement must carry at least one acceptance criterion, and each criterion must name an observable result that a test or a check can decide.
6. The writer must mark each open question with `[NEEDS CLARIFICATION: <the question>]` and must replace the marker with the recorded answer under Clarifications before the [[feature-design]] is written.
7. The page must not choose a file, a function, a table, or a library, because those choices belong to the [[feature-design]]. A requirement can name a product or a version that a [[decision-record]] has already fixed, and it links that record.
8. A requirement must be added, changed, or removed only through a pull request that also updates the [[feature-tasks]] page's traceability, so every requirement keeps its task and its test.
9. The owner must approve the Requirements and Clarifications sections before the [[feature-design]] is written and before any card is cut, because a card built on an unapproved requirement builds the wrong thing.

## Before you publish

- Does the title name one feature, and does What this delivers stand on its own?
- Is every PRD requirement linked by its identifier, with no copied text?
- Does every requirement no PRD owns carry an identifier from the `code` field, one force word, and a testable statement?
- Does every requirement carry at least one acceptance criterion that a test or a check can decide?
- Is every open question answered under Clarifications, with no marker left?
- Is the page free of design choices, naming a product or a version only where a linked decision record fixed it?

## Background

This type follows the specification of spec-driven development. GitHub's Specify phase writes what is being built and why, with what success looks like, before any technical choice. Microsoft's teams capture business goals, user requirements, edge cases, and acceptance tests in the specification, and they clarify ambiguities and unanswered questions as a stage of their own before the plan. Anthropic's requirements spec flags the areas of concern for a person to resolve before engineering plans against it.

From these we adopt the page that states what and why before how, the acceptance criteria beside each requirement, and a recorded answer for every clarified question. We link each PRD requirement instead of copying it, because two copies of one requirement drift apart, and a requirement the PRD lacks goes into the PRD. A requirement no PRD owns, such as platform work no user sees, follows the [[prd]] type's statement form. We drop the generated user journeys of the Specify phase, because a [[design-spec]] owns what the user sees. We keep each page as short as its feature allows, because the one quantitative evaluation of spec-driven development found a small quality gain bought with a 55 percent increase in time, and Osmani advises matching the spec's detail to the task.
