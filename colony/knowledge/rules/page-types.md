---
type: rule
created: 2026-11-05
description: The rule that gives every page exactly one type. Read before creating a page or judging where content belongs.
assisted-by: claude-code:claude-fable-5
enforced-by: colony check-docs for a known type, human review in the pull request
paths:
  - "**/{knowledge}/**"
---

# Page types

## What the rule is

Every page carries a `type` field in its frontmatter. The type says what kind of document the page is, and its definition sits in `{knowledge}/.types/` under the type's own name.

- The writer must give every page exactly one type from the table below and record it in the `type` field.
- The writer must choose the type before writing.
- The writer must not change a page's type for the life of the page.
- The writer must follow the type's definition, reading it down to its "## Background" heading before writing.
- A writer whose page fits more than one type must split it into one page per type and link the pages.
- A writer whose content fits no type must stop, propose the new type, research the recognized convention for that kind of document, and write the content only after the type is added to the table.

| Type                      | Purpose                                                                         | Convention                                     |
| ------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------- |
| [[idea-spec]]             | Explores one coherent part of an idea before its behavior is accepted           | Opportunity assessment, design proposal        |
| [[one-pager]]             | Argues whether a feature idea is worth defining in a PRD                        | Opportunity assessment, BLUF                   |
| [[prd]]                   | Defines what one feature does and why                                           | Modern PRD, EARS                               |
| [[design-spec]]           | Describes how one feature looks and behaves for the user                        | UX specification, Microsoft and Google UI text |
| [[tech-design]]           | Proposes how one feature or area will be built                                  | Google design doc                              |
| [[architecture]]          | Describes the structure of one whole system                                     | C4, arc42                                      |
| [[building-block]]        | Describes one area of {product} as one part of the whole system                 | arc42 building block view, ISO/IEC/IEEE 42010  |
| [[threat-model]]          | Records what one system must protect, what can go wrong, and the response to each threat | Threat Modeling Manifesto four questions, STRIDE, LINDDUN |
| [[runbook]]               | Gives the ordered procedure for performing or repairing one known operation     | Runbook and checklist design, Well-Architected, SRE |
| [[decision-record]]       | Records one accepted decision and the reasoning behind it                       | Nygard ADR                                     |
| [[archive-record]]        | Preserves one important rejected idea, retired feature, or replaced name        | Searchable idea archive, decision history      |
| [[research-report]]       | Reports the findings of one investigation, conclusion first                     | BLUF, ICD 203, ISO 690                         |
| [[feature-requirements]]  | States what one feature must deliver, linking the PRD requirements it serves    | Spec-driven development specification, EARS    |
| [[feature-design]]        | Proposes how one feature of a build is put together                             | Spec-driven development technical plan, Google design doc |
| [[feature-tasks]]         | Divides one feature into traced, contracted tasks                               | Spec-driven development tasks                  |
| [[feature-spec]]          | States what one feature built in one task delivers, traced to its tests         | Spec-driven development specification          |
| [[implementation-plan]]   | Retired, kept for the pages a repository wrote with it before                   | Spec-driven development change spec            |
| [[reconciliation-report]] | Closes one feature with its coverage, drift, and measures                       | As-built record                                |
| [[build-checklist]]       | Tracks one build from its gates to its last feature                             | Launch readiness checklist, work breakdown structure, checklist design |
| [[owner-checklist]]       | Holds the steps only the owner can take in one field, each naming what it blocks | Launch readiness checklist, checklist design  |
| [[launch-plan]]           | Takes {product} to one launch through milestones, with one owner for every item | Launch readiness checklist, responsibility assignment matrix |
| [[living-spec]]           | Describes one capability of the system as built                                 | Living documentation, as-built record          |
| [[glossary-entry]]        | Defines one term in {product}'s vocabulary                                      | Domain glossary, ISO 704                       |
| [[rule]]                  | States one rule of the vault and how it is enforced                             | W3C QA Framework, BCP 14                       |
| [[type-definition]]       | Defines how pages of one type are written                                       | Document type definition                       |
| [[diagram-type]]          | Defines how diagrams of one type are drawn                                      | Document type definition                       |
| [[readme-page]]           | Orients readers entering one folder and maps its pages                          | README convention, Map of Content              |
| [[source]]                | Preserves outside material exactly as it arrived                                | Archiving practice, APA quotation              |
| [[singleton]]             | Holds a document the vault has exactly one of                                   | Chosen per document                            |

## Why it exists

The rule exists to standardize the vault's documents. When every page follows a known shape, a writer starts from a proven structure instead of inventing one, and a reader finds the same information in the same place on every page of that kind. Without the standard, each page takes its own form, and review has nothing fixed to check it against.

## What it applies to

Every markdown page inside `{knowledge}/` and `.colony/rules/`, and every human and agent who writes one.

## What is exempt

None.

## How it is enforced

`colony check-docs` refuses a page whose `type` is missing or names no type in `{knowledge}/.types/`, in the mode the repository sets. Human review in the pull request checks that the frontmatter and the skeleton match the type's definition, and that the content matches the type's purpose.
