---
type: type-definition
created: 2026-11-05
description: How to write a type definition. Read before adding a page type to the table.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Type definition

A type definition defines how pages of one type are written. It states the type's purpose, the convention it follows, the frontmatter its pages carry, the sections they hold, the rules that bind them, and the checks that pass them for publishing. Write one when a new type is added to the table in [[page-types]], because a type without a definition cannot be checked. Routing test: if the page tells a writer how to write pages of one type, it is a type definition.

## Send it elsewhere when

- The page states a requirement that reaches pages of every type, such as naming or linking. That is a [[rule]].
- The page guides readers to the pages inside one folder. That is a [[readme-page]].
- The page defines a term in {product}'s vocabulary. That is a [[glossary-entry]].
- The page defines how diagrams of one type are drawn, rather than pages. That is a [[diagram-type]].

## Frontmatter

```yaml
type: type-definition
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
enforced-by: human review in the pull request
```

## Skeleton

- **Opening.** What the type is, when to write one, and a one-sentence routing test.
- **Send it elsewhere when.** The sibling types a writer might confuse with this one, each with the case that belongs to it.
- **Frontmatter.** The exact fields a page of this type carries, as a yaml block.
- **Skeleton.** The sections a page of this type holds, in order, each with what it contains.
- **Rules.** The requirements that bind every page of this type.
- **Before you publish.** Five yes-or-no checks, where any no means the page is not done.
- **Background.** The recognized convention the type follows, what we adopt from it, and what we drop, each with its reason. It comes last, so a writer reads down to it and stops.

## Rules

- Each type in the table in [[page-types]] must have exactly one type definition.
- The definition must name the recognized convention the type follows, what is adopted, and what is dropped.
- Every rule the definition states must be checkable by a reviewer reading one page of the type.
- The definition must carry exactly five publish checks, each answerable yes or no.
- Until a type has a template, the writer must use the definition as the template.
- The definition must hold its convention under "## Background" as its last section, because every part above it binds the page and the convention only explains them.

## Before you publish

- Does the table in [[page-types]] list this type?
- Does the definition carry all seven parts of the skeleton?
- Is the type anchored to a recognized convention, with the adopted and dropped parts stated?
- Is every rule checkable by a reviewer reading one page of the type?
- Are there exactly five publish checks, each answerable yes or no?

## Background

The convention is the document type definition, from SGML and XML practice, where a class of documents is defined by the structure a valid instance must have. We adopt the idea: one definition per type, stating the required parts and the rules a page must satisfy before it counts as valid. We drop the machine syntax, because these definitions are read by people and checked by review.
