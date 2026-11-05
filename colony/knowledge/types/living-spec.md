---
type: type-definition
created: 2026-11-05
description: How to write a living spec. Read before describing a capability of the system as built, or before changing an area of the code.
assisted-by: claude-code:claude-fable-5
enforced-by: colony check-docs for the size cap, human review in the pull request
---

# Living spec

A living spec describes one capability of the system as it is built right now. You write one in the pull request that first builds its capability, and you change it in every pull request that changes the behavior it describes. It is the page an agent reads before touching that area of the code. Where a [[prd]] says what was decided, a living spec says what is running, and the gap between the two is the work not yet done. Routing test: if the page must change whenever the code's behavior changes, it is a living spec.

## Send it elsewhere when

- You are defining what a feature should do and why. That is a [[prd]].
- You are proposing how an area will be built. That is a [[tech-design]], because a living spec describes only what was built.
- You are describing the structure of the whole system. That is an [[architecture]] page.
- You are dividing a feature into tasks. That is a [[feature-tasks]] page.
- You are recording what one feature actually built and how it differed from its plan. That is a [[reconciliation-report]].
- You are specifying how a feature should look and behave for the user. That is a [[design-spec]].

## Frontmatter

```yaml
type: living-spec
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
split-from: <page-name>      # present only on a page cut from a split living spec, the split page's file name without .md
```

## Skeleton

- `## What it does now`. The capability in a short paragraph, present tense, as built.
- `## Requirements in force`. One list item per requirement currently implemented, holding its identifier and a link to the [[prd]] or requirements page that holds its text. For existing behavior without a PRD, the agreed behavior and its source under [[docs-life-cycle#Plan]].
- `## How it works`. The behavior and interfaces, at the level an agent needs before changing this area.
- `## Governed by`. The wiki pages that govern the capability, each linked.

## Rules

1. A living spec must cover one capability, and the page title must name it.
2. The page must describe only what is built, so a decided but unimplemented behavior stays in its [[prd]] until a task brings it here.
3. The writer must list each requirement in force by its identifier, linked to the [[prd]] that holds its text, and must not copy the text, because a copy drifts from its home. For existing behavior without a PRD, the writer must record the missing formal requirements and link the agreed behavior in the pull request under [[docs-life-cycle#Plan]].
4. The pull request that changes this capability's behavior must change this page in the same pull request.
5. A living spec must not carry plan detail or evidence, because the pull requests and the feature's [[reconciliation-report]] already hold them, and the page's own history holds every pull request that changed it.
6. A living spec must stay at or under 25,000 bytes, because an agent reads it whole before it changes the capability. A capability that outgrows the cap splits into sub-capability pages that its folder README lists.
7. A writer who splits a living spec must move each sentence and requirement identifier into exactly one new page, give each new page a `split-from` field naming the split page, and update every link to the split page in the same change.

## Before you publish

- Does the page describe the capability as it runs today, with nothing aspirational?
- Does each requirement in force carry its identifier and a link to its [[prd]], with no copied text, and with missing formal requirements and sources for agreed existing behavior recorded under the life cycle rule?
- Is this update part of the pull request that changed the behavior?
- Does the page link its governing wiki pages, and does it stay at or under 25,000 bytes?
- Is the page free of plan detail its pull requests already carry?

## Background

The convention is living documentation, the practice where a system's documentation is kept accurate by updating it inside every change instead of in a separate pass, joined with the as-built record from engineering practice, where drawings are corrected after construction so they match what was actually built. We adopt the sync rule, the page changes with the behavior it describes, because documentation updated separately is documentation that drifts. We drop living documentation's generation tooling, where pages are produced from code or tests by machine, because these pages carry judgment about what matters, and generation cannot.
