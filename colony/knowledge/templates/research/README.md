---
type: readme-page
created: YYYY-MM-DD
description: The entry page for the research layer, listing every research report. Read to find what has already been investigated before starting a new question.
---

# Research

## What this folder holds

Finished [[research-report]] pages, each a permanent record of what one investigation found and when. The [[authority]] rule says what this layer promises, and its [[authority#Research ends in rules]] section says when a report is done.

## How it is organized

- Reports sit flat in this folder, one question per report, each named `<topic>-<yyyy-mm>.md`, and each one gets its line under Pages in the same change that adds it.
- Every report states `feeds-rules: true` or `feeds-rules: false` in its frontmatter, as the [[research-report]] definition sets.
- A report with `feeds-rules: true` holds a findings table in which every finding becomes a rule line with its do and its don't, a check that enforces it, or a decision the owner recorded after being asked one question with a default. A planned check links the task that builds it, either its task issue or its task's section of a [[feature-tasks]] page.
- A question that recurs gets its own folder once its reports accumulate, born never in advance, and its existing reports move in at that moment.

## Pages

No reports yet. Each report gets its line here, newest first, in the change that adds it.

## Not here

- Captured outside material. That is a [[source]] page in [raw](../raw/README.md), and the report cites it.
- The position we decided to act on. A report records what was found on a date, and the decided truth that came out of it lives in the [wiki](../wiki/README.md).
