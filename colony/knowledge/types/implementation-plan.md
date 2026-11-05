---
type: type-definition
created: 2026-11-05
description: The retired page type that divided one feature into contracted tasks, kept so a repository's implementation plans written before it adopted the three spec documents stay valid. Read to understand or correct an existing implementation plan. A new feature uses the three spec documents or one feature spec instead.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Implementation plan

An implementation plan is a retired type that divided one feature into ordered tasks, each with a contract. FEATURE work now takes a [[feature-requirements]] page, a [[feature-design]] page, and a [[feature-tasks]] page, or one [[feature-spec]] when one task builds it, under [[docs-life-cycle#Plan]]. No new page may take this type, and the pages that already carry it keep it, because [[page-types]] keeps a page's type for its whole life. Routing test: if the page is an existing plan that divides one feature into contracted tasks and predates the three spec documents, it is an implementation plan.

## Send it elsewhere when

- You are planning a new feature built in several tasks. That is a [[feature-requirements]], a [[feature-design]], and a [[feature-tasks]] page.
- You are planning a new feature one task builds. That is a [[feature-spec]].
- You are proposing how an area of the product gets built, apart from any one feature. That is a [[tech-design]].
- You are recording what the feature actually built and how it differed from this plan. That is a [[reconciliation-report]].
- You are describing a capability as it exists after the work. That is a [[living-spec]].

## Frontmatter

```yaml
type: implementation-plan
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
feature: <the feature this plan divides, one line>
```

## Skeleton

- `## What this delivers`. The feature and its outcome in a short paragraph, readable on its own.
- `## Requirements`. The requirements the feature implements, each cited by its identifier with a link to its [[prd]].
- `## Tasks`. The tasks in build order, each with its contract: the behavior, surface, inputs, outputs, acceptance checks, and available requirement identifiers it serves.
- `## Scope`. The [[living-spec]] pages the work touches, each linked, and each capability the work creates, named in plain text until its page exists.
- `## Sources`. The [[tech-design]], [[design-spec]], and [[research-report]] pages the plan stands on, each linked.

## Rules

1. A writer must not create a page of this type, because the three spec documents and the [[feature-spec]] replaced it.
2. An existing plan must cover one feature, and its title must name it.
3. Every task of an existing plan must keep its contract naming its behavior, surface, inputs, outputs, acceptance checks, and available requirement identifiers, because the work built from it was reviewed against that contract.
4. The writer must cite each formal requirement by its identifier and link the defining page, because a second copy of the requirement can drift.
5. A change to an existing plan must only fix a link or a fact the plan states wrongly, and the feature's [[reconciliation-report]] records how the build differed from it.

## Before you publish

- Is the page an existing plan, with no new page created under this type?
- Does the title name one feature, and does the first section state what it delivers on its own?
- Does every task keep a contract with its behavior, surface, inputs, outputs, acceptance checks, and available identifiers?
- Is every available requirement identifier linked to its [[prd]]?
- Is the change limited to a fixed link or a corrected fact, with the build's differences left to the reconciliation report?

## Background

The type followed the change spec of spec-driven development, where one document divides a change into contracted tasks, each traced to the requirements it serves. It was retired because a plan held the requirements and the tasks and left the feature's own design to the area pages, so a feature's concrete choices had no page of their own. Spec-driven development splits what a feature must deliver, how it is built, and the order of the work into three documents, and the three spec documents follow that split. We keep the type so a repository that wrote plans before the split keeps them valid, and we drop the authoring of new ones.
