---
type: type-definition
created: 2026-11-05
description: How to write a research report. Read before reporting what an investigation found.
assisted-by: claude-code:claude-fable-5
enforced-by: human review when the report lands
---

# Research report

A research report answers a question someone asked, and it puts the answer in the first paragraph. You write one when you were sent to find something out and the finding will feed a decision nobody has made yet. The report is the evidence trail. What the research produces later feeds a PRD, a tech design, a decision record, or a glossary entry, and the report stays behind as the record of how you know. Routing test: if you are reporting what you found rather than making a call about what to do, write a research report.

## Send it elsewhere when

- The call is already made and you are recording it. That is a [[decision-record]], which links back to this report.
- You are deciding whether a feature idea deserves a [[prd]]. That is a [[one-pager]].
- You are defining what one {product} term means for good. That is a [[glossary-entry]].
- You captured outside material and added no analysis of your own. That is a [[source]] page.
- You are describing how an area gets built. That is a [[tech-design]].

## Frontmatter

```yaml
type: research-report
created: YYYY-MM-DD    # the date of the finding, used to judge staleness
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD   # set only by a verification pass, never by hand
question: <the one question this report answers, one line>
feeds-rules: true    # true on practice research, false on every other report, always present
```

Practice research sets how {product} is built: a report on best practices, a standard, or an audit of {product}'s code whose findings should become rules or checks. You set `feeds-rules: true` on such a report. Market, legal, user, and product research sets `feeds-rules: false`. Every report must state the field, so a writer cannot leave practice research unmarked by forgetting it, and a `false` shows up in review.

## Skeleton

- **Question and date.** The exact question the research went out to answer, and when.
- **Bottom line.** The answer in two or three sentences, before any evidence.
- **Evidence.** The claims that carry the answer, heaviest first, each one cited.
- **Findings and their rules.** Present only with `feeds-rules: true`. A table with one row per finding and the columns Finding, Rule line, Check, Count today, and Owner, described under Rules below.
- **My judgment.** What you think, marked as yours, kept apart from the cited claims.
- **What this does not settle.** Each open question, with what would answer it.
- **Sources.** Every source used, each with a link or a [[source]] page reference.

## Rules

- Every claim must either cite its evidence, a [[source]] page or an external link, or sit under "My judgment" where it reads as yours.
- A sentence that states a fact with no citation and no judgment marking must be cut before you publish.
- The bottom line must answer the question you were sent to answer, not a nearby one.
- The evidence must run heaviest first, not in the order you found it.
- A statement of likelihood must use one word from the ICD 203 ladder, and the same sentence must not also say how much you trust the evidence.
- Every entry under Sources must follow the ISO 690 web form: creator, title, publisher, date, viewed date, and URL.
- When sources disagree, the report must name the disagreement and let the newest source win.
- A research report informs a decision, and the call itself belongs in a decision-record.
- A writer who carries work from this report into another page must add a link to that page here, so the trail stays visible from the report. That link and the cells of the findings table are the only changes a finished report takes.
- A report with `feeds-rules: true` must hold a section headed "Findings and their rules", whose table has exactly the columns Finding, Rule line, Check, Count today, and Owner, with one row per finding the research made.
- The Rule line cell must link the rule page's section and quote the line that states the finding as a do and a don't, a must line with its must-not, or link the owner's recorded decision to leave the finding out, asked as one question with a default.
- The Check cell must name the script, the test, or the gate kind that enforces the line, or must read "review" and link the owner's recorded decision to leave the line to review. A check still to build reads "planned:", followed by what is planned and a link to the task that builds it: a Markdown link to its task issue, or a wikilink to its task's section of a [[feature-tasks]] page, such as `[[<feature>-tasks#Task 3. <name>]]`. A planned check that links neither is open, and so is a cell that reads "none". Each check the cell names before the word "planned" must exist: a file by its path in a code span, a test by its name in a code span, and a lint rule in a code span after the name of its linter, such as ruff.
- The Count today cell gives the number of breaks the check or a search finds today, and the Owner cell names who closes the row.
- A finding closes only with a rule line and a check, or with the owner's recorded decision to leave it out, and the report is not done while a row stays open, as [[authority#Research ends in rules]] sets.
- A table cell must not hold a pipe character or a wikilink with a display name, because either one splits the cell.
- The reviewer must refuse a report with `feeds-rules: true` whose findings table is missing, whose Rule line or Check cell is empty or reads "none", whose "review" check links no decision, whose rule link resolves to no page or heading, whose check cell names a file, test, or lint rule that does not exist, or whose planned check links no task issue and no task section, and must refuse a report that lacks `feeds-rules: true` or `feeds-rules: false`.
- One report must answer one question, and its file must be `{knowledge}/research/<topic>-<yyyy-mm>.md`.

## Before you publish

- Can you state the finding from the first paragraph alone, with nothing else read?
- Does every factual sentence carry a citation, or sit under "My judgment"?
- Does every likelihood use a ladder word, with trust in the evidence kept to its own sentence?
- Does the evidence run heaviest first rather than in the order you found it?
- Does `feeds-rules` sit in the frontmatter, true on practice research and false on every other report? On practice research, does every row of the findings table carry a rule line and a check, or the owner's decision?
- Are the open questions named, each with what would settle it?

## Background

The convention is BLUF, bottom line up front, from US Army writing guidance. You state the conclusion in the first two or three sentences, then the evidence that carries it, heaviest first. We adopt the front-loaded conclusion because the report is read cold and often only at the top, so the reader who stops after one paragraph still leaves with the finding. We drop the Amazon six-pager approach, which builds to its conclusion for a live meeting, because these reports are read alone and not in a room.

For statements about how likely something is, the report follows ICD 203, the analytic standard the United States intelligence community writes to. It fixes one ladder of likelihood words, and only those words carry likelihood: almost no chance, very unlikely, unlikely, roughly even chance, likely, very likely, almost certain. A sentence states either how likely a thing is or how much you trust the evidence, never both at once. The source list follows the ISO 690 web reference form: creator, title, publisher, date, the date you viewed it, and the URL. We drop the rest of ICD 203, because its sourcing rules serve classified work.
