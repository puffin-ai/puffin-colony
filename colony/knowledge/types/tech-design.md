---
type: type-definition
created: 2026-11-05
description: How to write a tech design. Read before proposing how a feature or area gets built.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Tech design

A tech design says how one feature or one area of {product} is built, while the build is still open to change. You write one when a decision about construction is about to be made and the reasoning matters to more than one person: the data it holds, the parts that move it, the failure modes, and the designs that lost. It is a proposal. The routing test: if a builder could pick up the page and construct the thing, and a reviewer could argue with the choices in it, it is a tech design.

## Send it elsewhere when

- The page covers how the whole system fits together rather than one buildable piece. That is an [[architecture]] page, one per system.
- The page records one settled call with its consequences and its reopen trigger. That is a [[decision-record]]. A tech design cites decision records instead of restating them.
- The page says what the feature does for a user and why it is worth doing. That is a [[prd]].
- The page describes what the interface looks like and how it behaves. That is a [[design-spec]].
- The page reports what an investigation found, conclusion first, with sources. That is a [[research-report]].
- The page defines one {product} term. That is a [[glossary-entry]].

## Frontmatter

```yaml
type: tech-design
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified:       # set only by a verification pass, never by hand
```

## Skeleton

- **Context.** A lead of one or two sentences naming the design's place in the system, written timelessly, then three link lists, each present only when it has entries. Each line is a wikilink, a colon, then how that page connects to this one, never a description of what the linked page is. No goals, no design, and no drafting history here.
  - **The decisions that bind.** One line per decision record this design must obey.
  - **The research behind it.** One line per research report whose findings this design follows.
  - **Related designs.** One line per neighboring page, stating where the boundary between the pages runs.
- **Goals and non-goals.** Two short lists. Each non-goal is a real candidate goal set aside for a reason, never the negation of a goal.
- **The proposed design.** Titled subsections, one per part of the design: the data first, then each moving part, then the trade-offs. A subsection opens with at most one short paragraph, and its details sit in bullet lists or tables. Include one diagram of the design, drawn under the [[diagrams]] rule, inside the subsection it explains.
- **Alternatives considered.** Each design that could have worked, and for each one the concrete reason it lost.
- **Cross-cutting concerns.** A bullet list ordered by importance, most important first. Each bullet carries one concern in complete sentences, and data, privacy, and failure modes each appear.

## Rules

- The page must cover one feature or one area, and its title must name that feature or area.
- Every non-goal must be a candidate goal set aside with a stated reason.
- Every alternative must carry the concrete trade-off that made it lose.
- Every diagram must follow the [[diagrams]] rule, and the page must state in prose whatever the diagram shows.
- Field lists, schemas, and interface definitions must stay in code, and the page links to them rather than copying them.
- A cross-cutting promise that already lives on another page must be linked, not restated.
- Every concept with a page must be linked where it is named, and a term used across pages earns a [[glossary-entry]] as its link target.
- An enumeration of three or more parallel items must be a list, never an inline prose series.
- The page must be written timelessly, so the order in which pages were drafted never appears, and a claim about another page states the standing relationship in the present tense.

## Before you publish

- Does the page cover exactly one feature or area, named in the title?
- Does the context carry its link lists, with every line stating a connection rather than describing the linked page?
- Is every enumeration of three or more items a list rather than a sentence, and does every proposed-design subsection cover one part?
- Is every named concept that has a page linked where it is named?
- Is every non-goal a real goal you set aside, with the reason written down?
- Does every alternative say why it lost?
- Does the prose still carry the design if the Mermaid diagram fails to render?
- Are the cross-cutting concerns bullets ordered by importance, answering data, privacy, and failure modes, each checkable?

## Background

This type follows the Google-style design doc, described by Malte Ubl in "Design Docs at Google." We adopt its five sections and its purpose: a proposal written while the design can still change, where goals and non-goals and alternatives considered carry the real weight, because the reasoning outlives the code. We drop its free-form length and its optional sections, because a vault needs pages that look alike. On top of Ubl's sections the vault adds fixed structure inside them: link lists in the context, one subsection per part of the design, and ranked cross-cutting bullets, because agents retrieve sections alone and a list survives retrieval better than a paragraph. Diagrams are drawn as Mermaid blocks under the [[diagrams]] rule, and the writer chooses each diagram's type from that rule's table to fit the content, so the diagram lives in the page and stays reviewable in the pull request.
