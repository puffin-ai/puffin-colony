---
type: type-definition
created: 2026-11-05
description: How to write a PRD. Read before defining what a feature does and why.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# PRD

A PRD, short for product requirements document, states what one feature does and why it exists. You write one after a feature idea has cleared its one-pager and the team agrees it is worth building, but nobody has yet written down what "built" would mean. The page holds the problem, the user who has it, the goals, the requirements with their identifiers, and the measures that will tell you it worked. Routing test: if you can write the whole page without naming a single screen, table, or file, it belongs here.

## Send it elsewhere when

- You are still arguing whether to build the thing at all. That is a [[one-pager]].
- You are describing layout, wording, states, or what happens on each tap. That is a [[design-spec]].
- You are choosing how one area gets built. That is a [[tech-design]].
- You are showing how whole systems fit together. That is an [[architecture]] page.
- You are recording one accepted call and what it costs. That is a [[decision-record]].
- You are reporting what an investigation found. That is a [[research-report]].
- You are pinning down what one {product} word means. That is a [[glossary-entry]].

## Frontmatter

```yaml
type: prd
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
```

## Skeleton

- `## Problem`. The gap or pain in plain words, and the evidence that shows it is real.
- `## Target user`. Who feels this problem, described by their situation rather than their demographics.
- `## Goals and non-goals`. What the feature must achieve, and what it deliberately will not attempt.
- `## Requirements`. Statements of behavior, grouped under one `###` subsection per category. Each statement carries its identifier and is testable on its own.
- `## Out of scope`. Nearby work a reader might expect here and where it actually lives.
- `## Success metrics`. The measures that will show the feature worked, each one measurable and free of technology.

## Rules

1. A PRD must cover one feature, and the page title must name that feature.
2. The writer must assign each requirement a stable identifier following the feature's existing naming scheme or a consistent scheme stated in the pull request. The owner decides the requirement's meaning under [[docs-life-cycle#Human decisions and agent work]].
3. Every requirement identifier must appear once, and a removed requirement must keep its identifier with the single word "retired" as its text, because later work cites the identifiers.
4. Each requirement must be a single statement that a reviewer can turn into one test.
5. Each requirement must use one of the five EARS shapes, with every condition before the behavior.
6. Each requirement must carry exactly one force word, must, should, or can, with the [[writing]] meanings.
7. A requirement must not contain a superlative, a comparison with no reference point, or a vague quantity, so a word like best, faster, or several must become a number or be cut.
8. A PRD must contain no implementation detail, no code, and no file paths.
9. Every PRD must state at least one non-goal.
10. Success metrics must be measurable and must name no technology.
11. The requirements must be grouped into categories, one subsection per category with a plain name, and each requirement sits in exactly one category.

## Before you publish

- Can a reader name the problem, the user, and at least one non-goal after one read?
- Does every requirement carry its identifier, use one EARS shape, carry one force word, and stand testable on its own?
- Does every requirement sit inside exactly one named category subsection?
- Is the page clear of screens, code, file paths, and build choices?
- Can each success metric be measured without knowing how the feature was built?

## Background

This type follows the standard modern PRD. We adopt its six-part shape, because each part answers a question a reviewer asks before build starts: problem, target user, goals and non-goals, testable requirements that carry identifiers, out of scope, and success metrics. We drop release dates, staffing, launch plans, and any table linking the document to build tasks. How a requirement travels from here into plans, tests, and living specs is the [[docs-life-cycle]] rule's job, so this definition stops at the document itself.

The requirement sentences follow EARS, the easy approach to requirements syntax. EARS gives every requirement one of five shapes: a statement that always holds, "When" for a triggering event, "While" for a lasting state, "If" and "then" for an unwanted event, and "Where" for an optional part of the product. The condition always comes before the behavior, and the behavior carries exactly one force word with its [[writing]] meaning. From ISO/IEC/IEEE 29148, the requirements standard, we adopt four checks on every requirement, unambiguous, singular, feasible, and verifiable, and its ban on vague words. We drop the process machinery of both, because it serves contract projects with many teams, not a vault with one.
