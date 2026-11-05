---
type: type-definition
created: 2026-11-05
description: How to write a building block, the page that describes one area of {product} as one part of the whole system, with its purpose and responsibility, its interfaces and structure, its quality and performance targets, and its open risks. Read before writing or updating the technical design of an area in the product's technical design.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Building block

A building block page describes one area of {product} as one part of the whole running system. It says what the area is responsible for, what enters and leaves it, how its components fit together, which limits and targets it is built to meet, and which risks remain open. The pages together hold the detail behind the product's technical design, a [[singleton]] that summarizes each area in a few lines and links its page. Write one for each area of that page, and keep it current as the area's design changes. Routing test: if the page describes one area's part in the whole system and summarizes the decisions that shape it, it is a building block.

## Send it elsewhere when

- The page proposes how one feature or area gets built while the choices are still open. That is a [[tech-design]], and the building block links it once it settles.
- The page records one accepted call and its reasoning. That is a [[decision-record]], and the building block links it.
- The page describes the Context and Container views of the whole system. That is the one [[architecture]] page, and the building block links it.
- The page states what a feature does for the user and why. That is a [[prd]], and the building block cites its identifiers.
- The page describes a capability as it runs today. That is a [[living-spec]].

## Frontmatter

```yaml
type: building-block
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
area: <the area of the product this building block describes, one line>
```

## Skeleton

- **Title.** The area's name followed by "building block", which for a billing area reads "Billing building block".
- **Opening.** One paragraph saying what the area is and naming its place on the technical design.
- `## Purpose and responsibility`. What the area owns and what it leaves to other areas.
- `## Interfaces and structure`. What enters and leaves the area, and one subsection per component or mechanism, with the diagrams the [[diagrams]] rule allows.
- `## Quality and performance targets`. The limits and targets the area is built to meet, each stated so a reviewer can check it, with the requirement identifier behind it.
- `## Open risks`. The limitations the area accepts and the risks that remain, each with what would reopen it.
- `## The records that bind it`. One line per decision record, tech design, PRD, and research report the page states, each with the fact it contributes.

## Rules

1. A building block must cover exactly one area, named in the `area` frontmatter field and in the title.
2. Every decided fact on the page must link the record that decides it. A fact the owner settled whose record is not yet written must name the owner's answer by its number, and the gate that writes the record must be open on the build checklist.
3. The page must state a fact in the same words as the record that decides it, and a pull request that changes that record must update this page in the same pull request.
4. The page must stay under the line budget of [[writing]], and detail that outgrows it moves to the area's tech design with a link.
5. Every diagram must follow the [[diagrams]] rule.

## Before you publish

- Does the page cover one area, named in its title and its `area` field?
- Does it hold the five sections of the skeleton, in order?
- Does every decided fact link the record that decides it?
- Is every target stated so a reviewer can check it, with its requirement identifier?
- Is the page under the line budget, with its diagrams following the diagrams rule?

## Background

This type follows the building block view of arc42, the architecture documentation template. We adopt its black box template, which describes one part by its purpose and responsibility, its interfaces, its quality and performance characteristics, and its open risks, because those four headings answer what a reader asks before changing one part. We adopt arc42's rule of relevance over completeness, so a building block states what a reader needs to build or change the area and leaves the rest to the pages it links. From ISO/IEC/IEEE 42010 we adopt the rule that the conventions every part follows are declared once, on the technical design, and each part links the records that bind it.

We drop arc42's other eleven sections as page sections, because the vault holds that material on its own page types, and the building block links those pages. We drop the white box nesting below one level, because a vault page stays under the line budget of [[writing]] and deeper detail belongs to the area's tech designs.
