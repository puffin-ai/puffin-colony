---
type: readme-page
created: 2026-11-05
description: The entry page for the page type definitions. Read before writing a page of any type.
assisted-by: claude-code:claude-fable-5
---

# Page types

## What this folder holds

One definition per page type. The [[page-types]] rule lists the types and says how to pick one, and the [[type-definition]] definition says how these pages are written. Each definition ends with "## Background", which explains its convention, so a writer reads down to that heading and stops.

## Pages

### The product

- [[one-pager]]: how to argue whether an idea deserves a PRD.
- [[prd]]: how to define what one feature does and why.
- [[design-spec]]: how to describe what a user sees and what happens when they act.
- [[tech-design]]: how to propose the way a feature or area gets built.
- [[architecture]]: how to describe the structure of one whole system.
- [[building-block]]: how to describe one area of {product} as one part of the whole system.
- [[threat-model]]: how to record what one system must protect, what can go wrong, and what {product} does about each threat.
- [[runbook]]: how to write the ordered procedure for one known operation.
- [[decision-record]]: how to record one accepted call and its reasoning.
- [[glossary-entry]]: how to define one term in {product}'s vocabulary.
- [[singleton]]: how to write a document the vault holds exactly once.

### The work

- [[idea-spec]]: how to explore an idea on the base branch while its product choices stay open.
- [[archive-record]]: how to preserve an important past item, its outcome, and its original evidence.
- [[source]]: how to capture outside material and keep it frozen.
- [[research-report]]: how to report what an investigation found and turn each finding into a rule.
- [[feature-requirements]]: how to state what one feature must deliver and how each requirement is checked.
- [[feature-design]]: how to propose how one feature is built.
- [[feature-tasks]]: how to divide one feature into traced, contracted tasks.
- [[feature-spec]]: how to state what one feature built in one task delivers, on one page traced to its tests.
- [[implementation-plan]]: the retired type that divided one feature into contracted tasks, kept for existing pages.
- [[reconciliation-report]]: how to close one feature with its coverage, drift, and measures.
- [[build-checklist]]: how to track one build from its gates to its last feature.
- [[owner-checklist]]: how to hold the steps only the owner can take in one field, each naming what it blocks.
- [[launch-plan]]: how to plan one launch across its milestones, with one owner for every item.
- [[living-spec]]: how to describe one capability as it runs today.

### The vault itself

- [[rule]]: how to write a rule of the vault.
- [[type-definition]]: how to define a page type.
- [[diagram-type]]: how to define a diagram type.
- [[readme-page]]: how to write a folder's entry page.

## Not here

- The rules that bind every page: `.colony/rules/`, starting at [[page-types]] and [[authority]].
- How diagrams are drawn: the [[diagrams]] rule.
