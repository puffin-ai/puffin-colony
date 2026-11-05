---
type: type-definition
created: 2026-11-05
description: How to write a diagram type definition. Read before adding a diagram type to the table.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Diagram type

A diagram type defines how diagrams of one type are drawn. It states what the diagram shows, the notation convention it follows, the syntax or image format that draws it, the rules that bind it, and the checks that pass it for review. Write one when a new diagram type is added to the table in [[diagrams]], because a diagram type without a definition cannot be checked. Routing test: if the page tells a writer how to draw diagrams of one type, it is a diagram type.

## Send it elsewhere when

- The page states a requirement that reaches every diagram, whatever its kind. That belongs in the [[diagrams]] rule.
- The page defines how pages of one type are written. That is a [[type-definition]].
- The page guides readers to the pages inside one folder. That is a [[readme-page]].

## Frontmatter

```yaml
type: diagram-type
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
enforced-by: human review in the pull request
```

## Skeleton

- **Opening.** What the diagram shows, when to draw one, and a one-sentence routing test.
- **Send it elsewhere when.** The sibling diagram types a writer might confuse with this one, each with the case that belongs to it.
- **The convention.** The recognized notation the type follows, what we adopt from it, and what we drop, each with its reason.
- **The syntax.** The Mermaid keyword or image format, what is safe at the renderer version the vault supports, and any stated carve-outs from the [[diagrams]] rule.
- **Rules.** The requirements that bind every diagram of this type.
- **Before you publish.** Five yes-or-no checks, where any no means the diagram is not done.

## Rules

- Each diagram type in the table in [[diagrams]] must have at most one diagram-type page, and a type that carves out any part of the [[diagrams]] rule must have one.
- The definition must name the recognized notation the type follows, what is adopted, and what is dropped.
- Every rule the definition states must be checkable by a reviewer reading one diagram.
- The definition must carry exactly five publish checks, each answerable yes or no.
- A carve-out from the [[diagrams]] rule must be stated in the definition and mirrored in that rule's exemptions.

## Before you publish

- Does the table in [[diagrams]] list this diagram type?
- Does the definition carry all six parts of the skeleton?
- Is the type anchored to a recognized notation, with the adopted and dropped parts stated?
- Is every rule checkable by a reviewer reading one diagram of the type?
- Are there exactly five publish checks, each answerable yes or no?

## Background

The convention is the document type definition, from SGML and XML practice, where a class of documents is defined by the structure a valid instance must have. We adopt the idea: one definition per diagram type, stating the notation, the syntax, and the rules a diagram must satisfy before it counts as valid. We drop the machine syntax, because these definitions are read by people and checked by review.
