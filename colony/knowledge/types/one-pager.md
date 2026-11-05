---
type: type-definition
created: 2026-11-05
description: How to write a one-pager. Read before arguing whether a feature idea deserves a PRD.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# One-pager

A one-pager decides whether a feature idea deserves a full PRD. It opens with that recommendation, then earns it by answering five questions on a single page: what problem, for which user, why now, how we would measure success, and the biggest risks. The honest answer can be no, and a one-pager that lands on "do not build" has done its job by saving the weeks a PRD and its build would have cost. Routing test: if the owner needs a yes-or-no recommendation on writing a PRD now, write a one-pager.

## Send it elsewhere when

- The owner is still exploring the idea without asking for a recommendation. That is an [[idea-spec]].
- The decision to build is already made and you need to say what the feature does. That is a [[prd]].
- You are recording one call that was accepted, with its context and its reopen trigger. That is a [[decision-record]].
- The question is how the interface looks and behaves. That is a [[design-spec]].
- The question is how the thing gets built. That is a [[tech-design]], or an [[architecture]] page if it spans the whole system.
- You are bringing back findings from users, competitors, or data. That is a [[research-report]], which a one-pager then cites.
- You are pinning down what one {product} term means. That is a [[glossary-entry]].

## Frontmatter

```yaml
type: one-pager
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD   # set only by a verification pass, never by hand
resolution: open     # open | promoted | declined
promoted-to: <link to the PRD>   # required when resolution is promoted
```

## Skeleton

- **Recommendation.** Write the PRD, or do not, with the one reason that decides it, before any of the case below.
- **Problem.** One real situation where the current way fails, and how we know it is real.
- **Who it hurts.** The specific user this problem lands on, named as a group we can point to.
- **Why now.** What changed that makes this worth deciding today rather than later.
- **Success measure.** One number with a baseline today and a target, set before any build.
- **Biggest risks.** The few things most likely to sink this, each with how we would find out early.

## Rules

- The page must stay under 60 lines, holding the six sections and nothing else.
- After the recommendation, the case must state the problem before any solution appears, never opening with a persona sketch.
- Sentences must stay near fifteen words on average, with none opening on "There is" or "It is".
- The success measure must give a baseline value and a target value, both set now.
- Every claim about users or data must cite a [[research-report]], a [[source]] page, or read plainly as judgment.
- The page must name the strongest objection and answer it at its strongest.
- The recommendation must open the page and must be a clear yes or no, never "more research needed" without naming the exact question.
- A one-pager must never carry interface detail, build detail, or a schema.
- When the answer is yes, the writer must write the PRD, set resolution to promoted, and link the PRD in promoted-to.

## Before you publish

- Is the page under 60 lines, with all six sections present?
- Does the case state the problem before any hint of a solution?
- Is there one success number on the page, with both a baseline and a target?
- Is the strongest objection written down and answered?
- Does the page open with a clear recommendation a reader could act on today?

## Background

The convention is Marty Cagan's opportunity assessment, from Silicon Valley Product Group. We adopt its four core questions about business objective, key results, customer problem, and target market, and we add "why now" and "biggest risks" so the page carries its own timing and its own doubts. We drop the Shape Up vocabulary some teams bolt on. Words like "bet" and "appetite" fix a time budget before the problem is understood, and that is the wrong order for a page whose only output is a yes or a no on writing a PRD.

The writing follows AR 25-50, the United States Army's writing regulation and the home of BLUF, bottom line up front. The recommendation opens the page, before the case for it, so a reader who stops after one paragraph still leaves with the answer. Sentences stay near fifteen words on average, the voice stays active, and no sentence opens with "There is" or "It is". We adopt the placement and the sentence discipline, which keep the promise that a busy reader still gets the answer, and we drop the Army's memo formatting, because the vault's frontmatter and headings already fix the page shape.
