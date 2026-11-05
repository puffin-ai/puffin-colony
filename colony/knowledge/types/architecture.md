---
type: type-definition
created: 2026-11-05
description: How to write an architecture page. Read before describing how a whole system fits together.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Architecture

An architecture page is the standing description of how one system fits together. It names the system's parts, the boundary around each one, and what crosses between them. You write it when the technical decisions for that system have been made and before the code exists, so that the shape is settled and reviewable while it is still cheap to change. One page covers one system, and it stays the page you update as that system changes rather than a snapshot you replace. The routing test: if the page answers "what are the pieces of this system and how do they fit," it is an architecture page, and if it answers anything narrower, it belongs to a sibling type.

## Send it elsewhere when

- The page explains how one feature or one area is built inside the system. That is a [[tech-design]].
- The page settles one choice, with its context, its consequences, and the trigger that reopens it. That is a [[decision-record]], and this page links to it.
- The page says what a feature does for a user and why. That is a [[prd]].
- The page describes how a screen looks and behaves. That is a [[design-spec]].
- The page compares options and reaches a conclusion from evidence. That is a [[research-report]], and the decision it feeds is a [[decision-record]].
- The page defines one term used across {product}. That is a [[glossary-entry]].

## Frontmatter

```yaml
type: architecture
system: <name of the one system this page covers>
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD
```

## Skeleton

- **What this system does.** The system's job in plain words, and who or what depends on it.
- **Context.** A Mermaid diagram of the system as one box, with the people and outside systems around it, and a prose paragraph naming every arrow.
- **Containers.** A Mermaid diagram of the runnable parts inside the system, and a paragraph per part saying what it holds and what it is responsible for.
- **What crosses each boundary.** Every flow in and out, each one named with its source, its destination, and what it carries.
- **Decisions behind this shape.** Each significant choice as one line with a link to its decision-record.
- **Quality goals.** The few properties this shape is built to hold, each one stated so a reviewer can tell whether it holds.
- **Known limits.** What this shape does not do well, and what would force a rework.

## Rules

- One page must cover exactly one system, named in the `system` frontmatter field.
- Every diagram must follow the [[diagrams]] rule and stay above the Code level of the C4 model.
- Every arrow in a diagram must carry a label saying what crosses it.
- Every fact a diagram shows must also appear in the prose, so the page survives a diagram failing to render.
- Every significant choice must link to its decision-record, and a choice with no decision-record must not be argued on this page.
- A term must keep one name across the prose, the diagrams, and the linked pages.
- A page must not name a specific class, function, file, or database table.

## Before you publish

- Does the page cover one system, and does the title name that system?
- Is every arrow in every diagram labeled, and is every diagram at Context, Container, or Component level?
- Does the prose state everything the diagrams show, without needing the diagrams to be readable?
- Does every significant choice on the page carry a link to its decision-record?
- Is the page free of class names, file paths, and table names?

## Background

This type follows the C4 model for its diagrams, drawn as C4 view blocks, inside a light arc42 page shape. From C4 we adopt the altitude discipline, meaning each diagram answers one question at one zoom level and pushes finer detail down. We use the Context level, which shows the system as one box with the people and outside systems around it, and the Container level, which shows the deployable and runnable parts inside it. Component level appears only where a part is genuinely hard to understand from the outside. We drop the Code level entirely, because code is the truth about itself and a page describing it goes stale.

From arc42 we adopt a small set of sections, because a fixed short shape puts the same information in the same place on every architecture page. We drop the rest of its template, which is built for large organisations and adds sections nobody here would read. C4 is notation-independent, so we drop its rendering tools and draw every diagram as a Mermaid text block under the [[diagrams]] rule, which keeps the page plain markdown that reads and diffs anywhere.
