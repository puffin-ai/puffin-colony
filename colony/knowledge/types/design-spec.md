---
type: type-definition
created: 2026-11-05
description: How to write a design spec. Read before describing what a user sees and what happens when they act.
assisted-by: claude-code:claude-fable-5
enforced-by: colony check-docs for the size cap, human review in the pull request
---

# Design spec

A design spec says how one feature looks and behaves for the user using it. It walks the flows, names every screen, and writes down what each screen shows when it is empty, loading, broken, or done. It sits beside a PRD: the PRD says what the feature does and why, and the design spec says what the user sees and what happens when they act. Write one after the PRD is agreed and before build starts, or alongside the design work as the screens settle. Routing test: if the page answers "what does the user see, and what happens when they act", it is a design spec.

## Send it elsewhere when

- The page argues why the feature matters or what it has to do. That is the [[prd]], which owns the problem, the scope, and the success measures.
- The page says how the feature is built behind the screen. That is the [[tech-design]].
- The page is still asking whether to build the thing at all. That is the [[one-pager]].
- The page settles one contested call and needs its consequences and a reopen trigger on record. That is the [[decision-record]].
- The page reports what usability testing or user interviews found. That is the [[research-report]].

## Frontmatter

```yaml
type: design-spec
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
prd: "[[<the PRD file name>]]"   # the PRD this spec serves
design-file: <url>           # present only when a design tool file exists for the feature
split-from: <page-name>      # present only on a page cut from a split design spec, the split page's file name without .md
```

## Skeleton

- **Summary.** The feature in two or three sentences, with a link to the PRD it serves.
- **Flows.** Each path a user takes through the feature, step by step, from entry point to end. A flow drawn as a diagram is a flowchart under the [[diagrams]] rule.
- **Screens.** One subsection per screen. What it shows, what a user can do on it, and where each action leads.
- **States.** For each screen: empty, loading, error, and success. What shows, and what the user can do next.
- **Edge cases.** The odd inputs and unusual conditions, each with the behavior we chose.
- **Copy notes.** Every string the user reads, in final words, with the tone or constraint behind it.
- **Open questions.** What is still undecided, and what will settle it.

## Rules

- The page must name the PRD in the frontmatter and in the summary, without restating its reasoning.
- Every screen must carry all four states, or one line saying why a state cannot happen there.
- Where the feature has a design file, the page must link it by URL.
- The page must carry no exported image, because an image goes stale and hides its words from a reader who cannot see it.
- Pixel values, color values, and type sizes must stay out, because they live in the design tool or in the code.
- User-visible copy must appear in the words the user will read, never as a description of what the text says.
- A main instruction must be a short imperative.
- Actions that sit together must read in parallel.
- Phrasing must say what to do rather than what not to do.
- A quoted string must use sentence case unless it reproduces a proper name, and it must match the shipped string letter for letter. The [[writing]] rule exempts quoted interface strings from its language rules.
- The page must name the behavior of every control it introduces, including what happens when the control fails.
- Components, data sources, and libraries must stay out, because those belong to the tech-design.
- Every open question names what will settle it.
- A design spec must stay at or under 25,000 bytes, because an agent reads a screen's page whole before it changes the screen.
- A writer who splits a design spec must move each sentence and requirement identifier into exactly one new page, give each new page a `split-from` field naming the split page, and update every link to the split page in the same change.

## Before you publish

- Does the page name the PRD it serves, in the frontmatter and in the summary?
- Does every screen carry empty, loading, error, and success, or a line saying why one cannot happen?
- Where a design-file link exists, does it resolve, and does it point at the current file?
- Is every string the user reads written out in final words?
- Can a builder work from this page without asking you what happens after any action?

## Background

We follow standard UX specification practice. We adopt its core, because these are the parts that describe behavior rather than pixels, which the design tool cannot hold: the flows, the screens, the four states every screen has (empty, loading, error, success), the edge cases, and the copy. We drop the redlines, meaning the marked-up measurements designers hand to builders. Spacing, color values, and type sizes stay in the design tool, or in the code when no design tool is in use. Exported images stay out of the vault, because a copy in the vault goes stale the day its source changes and nobody notices. The page links to the design file when the feature has one and spends its words on behavior, which neither the tool nor the code states.

The strings a user reads follow the current Microsoft and Google style guides for interface text. The main instruction on a screen is a short imperative. Actions that sit together are phrased in parallel. Phrasing is positive, saying what to do rather than what not to do. Labels and titles use sentence case. A string quoted in the page is the exact string that ships, letter for letter, in quotation marks.
