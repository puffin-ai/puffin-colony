---
type: type-definition
created: 2026-11-05
description: How to write a reconciliation report, the page that closes one feature with its coverage, drift, and measures. Read before closing a feature or checking what one actually built.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Reconciliation report

A reconciliation report records the outcome of one FEATURE, with every task it took. It records requirement coverage, differences from the feature's spec documents, and the measures the build produced. The change that delivers the feature's last task carries the report, under [[docs-life-cycle#Close]]. The spec documents record intent and the report records the verified result. Routing test: if the page reports how one feature's build actually went, it is a reconciliation report.

## Send it elsewhere when

- You are stating, designing, or dividing the feature. That is its [[feature-requirements]], [[feature-design]], or [[feature-tasks]] page, and this report links all three.
- You are describing a capability as it exists after the work. That is a [[living-spec]].
- You are recording one accepted call and the reasoning behind it. That is a [[decision-record]], and the report links it.
- You are reporting what an investigation found. That is a [[research-report]].

## Frontmatter

```yaml
type: reconciliation-report
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
feature: <the feature this report belongs to, one line>
```

## Skeleton

- `## Outcome`. The verified behavior and tested revision in a short paragraph, linking the feature's spec documents and every [[living-spec]] the feature touched.
- `## Coverage`. The coverage table: every requirement of the [[feature-requirements]] page, with its identifier, the tests covering the agreed behavior, and each outcome.
- `## Drift`. Every place the build differed from the spec documents and the tasks' contracts: what they said, what was built, and why, each linking its [[decision-record]] where one exists. The word "None" when nothing drifted.
- `## Measures`. The review rounds and confirmed findings of the batch's pull request, with each card's predicted and actual time, which the lead reads from git, GitHub, and `colony stats` under [[docs-life-cycle#Measures]], with the observation cutoff. Future events are pending and missing values are unavailable.
- `## Evidence`. Links to the merge commit of each task's change, to the batch's pull request, and to the test run, with the release scope and a link to any release record under [[docs-life-cycle#Release and learning]].

## Rules

1. A report must cover one feature. Its title names the feature and ends with the word "reconciliation", so its file name pairs with the spec documents' names.
2. A report must link its feature's three spec documents and must not restate their content, because they are read together and a copy drifts. A feature planned with an [[implementation-plan]] links that page instead.
3. The coverage table must list every requirement the report covers, its available identifier, the tests covering it, and each outcome, with a requirement that has no test reported apart from a test that did not run.
4. The Drift section must record every difference between the spec documents and what was built, each with its reason, and must state "None" when there is none, because silence cannot be told apart from omission.
5. The writer must take the measures from git and GitHub under [[docs-life-cycle#Measures]] and must record none by hand.
6. A report must link only pages already merged on the base branch or introduced or revised in its pull request. A report must remain unchanged after its merge, apart from fixing a link when a linked page is renamed.

## Before you publish

- Does the title name the feature and end with "reconciliation"?
- Does the coverage table list every requirement the report covers, keeping a requirement with no test apart from a test that did not run?
- Does Drift record every difference with its reason, or state "None"?
- Does Measures carry the measures read from git and GitHub, with its observation cutoff, unavailable values, and pending future events stated?
- Does Evidence state the release scope, with every page link resolving on the base branch or in the same pull request?

## Background

The convention is the as-built record from engineering practice, where a separate document records what was constructed so that intent and outcome both survive. We adopt one report per feature beside the feature's spec documents, with evidence that lets a reviewer check the result. The report links the spec document revisions used for implementation and records subsequent differences. We add the measures defined by [[docs-life-cycle#Measures]]. We drop the report per task, because each card's done line and merge commit already record its outcome, and a separate closing pull request, because the batch's pull request already examines the completed result.
