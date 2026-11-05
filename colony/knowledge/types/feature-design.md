---
type: type-definition
created: 2026-11-05
description: How to write a feature's design page, the second of the three spec documents of FEATURE work built in several tasks, which proposes how the feature is built, from its components, interfaces, and data to its failure handling and test approach, checks the design against the vault's rules, and records the alternatives and risks. Read before deciding how a feature is built, or before writing its tasks.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Feature design

A feature design page proposes how one feature is built. It is the second of the feature's three spec documents, written under [[docs-life-cycle#Plan]] after the [[feature-requirements]] page has no open question. It names the components, the interfaces, the data, the failure handling, and the test approach the feature needs, and it shows how the design satisfies each rule that binds it. It builds on the area's [[tech-design]] and [[building-block]] pages and links them. Routing test: if the page proposes how one feature of a build is put together, it is a feature design page.

## Send it elsewhere when

- The page proposes how a whole area is built, for every feature that touches it. That is a [[tech-design]] in the wiki, and this page links it.
- The page states what the feature must deliver. That is a [[feature-requirements]] page.
- The page divides the feature into tasks. That is a [[feature-tasks]] page.
- The page records one accepted call that other features rely on. That is a [[decision-record]] in the wiki, and this page links it.
- The page describes what the user sees. That is a [[design-spec]].

## Frontmatter

```yaml
type: feature-design
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
feature: <the feature this design belongs to, one line>
```

## Skeleton

- **Title.** The feature's name followed by "design".
- `## Context`. A lead of one or two sentences naming what the design builds, then four link lists: the [[feature-requirements]] page, the [[tech-design]], [[building-block]], and [[decision-record]] pages the design builds on, the [[research-report]] pages that hold the best practice, the industry standard, the golden path, and the conventions the design follows, and the rules that bind it. Each line is a wikilink, a colon, then what the page gives the design.
- `## The design`. Titled subsections in this order: the data, each component or interface with what enters and leaves it, the failure handling, and the test approach that names which test layer proves which requirement. A diagram follows the [[diagrams]] rule.
- `## Rules check`. One line per rule that binds the design, naming the rule and how the design meets it, and a departure from an area's design naming the [[decision-record]] that allows it.
- `## Alternatives considered`. Each design that could have worked, with the concrete reason it lost.
- `## Risks`. What the design could break or leave exposed, and how the design or a task answers each one.

## Rules

1. A design page must cover one feature, named in its title and its `feature` field.
2. The design must address every requirement of the [[feature-requirements]] page, and the test approach must name the test layer that proves each one.
3. The writer must link an area's [[tech-design]] and must not restate it, because a second copy of a design drifts.
4. A choice that other features will rely on must be recorded as a [[decision-record]] in the wiki, in the knowledge commits before this page, and linked from this page.
5. The design must follow the best practice, the industry standard, the golden path, and the conventions that apply to its kind of work, linking the [[research-report]] that holds each, and a departure must state its reason. A practice the vault does not hold yet must be researched first, under [[docs-life-cycle#Ground]].
6. The Rules check must name every rule in `.colony/rules/` that governs the code or the pages the feature changes.
7. A departure from an area's [[tech-design]] must name the [[decision-record]] that allows it, and that record must be committed as knowledge before this page when it does not exist yet.
8. The page must not divide the work into tasks, because the [[feature-tasks]] page holds the order of the work.

## Before you publish

- Does the title name one feature, and does Context link its requirements page and every area design it builds on?
- Does the design address every requirement, with a test layer named for each?
- Is every area design linked, with no restated content?
- Does the design link the research behind the practice, the standard, the golden path, and the conventions it follows?
- Does the Rules check name each binding rule and how the design meets it?
- Is every departure from an area design backed by a linked decision record?
- Are the alternatives and the risks each stated with a concrete reason or answer?

## Background

This type follows the technical plan of spec-driven development, scaled down from the [[tech-design]] type's design document. GitHub's Plan phase takes the stack, the architecture, the constraints, and the organization's standards and turns the specification into a technical plan. Microsoft agrees a constitution of architectural principles, governance requirements, security standards, and development limitations before any specification is written, and every plan answers to it. Anthropic asks the planning session what the change could break, which step is most risky, and which options were set aside.

From these we adopt the design written after the requirements and before the tasks, a check of the design against the vault's rules, which are the repository's constitution, and the recorded alternatives and risks. From the [[tech-design]] type we keep the data first and the trade-offs named. We drop the restatement of an area's design, because the area's [[tech-design]] already holds it and a second copy drifts, so this page links it and records only the feature's own choices.
