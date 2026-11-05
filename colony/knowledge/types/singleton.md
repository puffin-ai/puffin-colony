---
type: type-definition
created: 2026-11-05
description: How to write a singleton. Read before creating a document the vault has exactly one of.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Singleton

A singleton is a document the vault has exactly one of. Vision and strategy are the first two. It is written once, with the owner, and it has no template and no writer subagent. Write one when {product} needs a standing document that can only exist once. Routing test: if a second page on the same subject could never make sense, it is a singleton.

## Send it elsewhere when

- The document would repeat for each feature, system, or term. That is one of the repeating types in [[page-types]].
- The page records one accepted call and the reasoning behind it. That is a [[decision-record]].
- The page states a rule of the vault. That is a [[rule]].

## Frontmatter

```yaml
type: singleton
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD   # set only by a verification pass, never by hand
```

## Skeleton

- **Title.** The document's name as a plain noun phrase, such as "Vision".
- **Body.** The sections of the convention chosen for this document, agreed with the owner before writing begins.

## Rules

- The vault must hold exactly one page for each singleton subject, and a second page on that subject must not be created.
- The owner must approve the document and its convention before the page is written.
- The writer must name the chosen convention on the page, so a reviewer can check the page against it.
- Content that would repeat for another feature, system, or term must move to its repeating type.

## Before you publish

- Is this the only page in the vault on this document's subject?
- Did the owner approve this document and its convention before it was written?
- Does the page name its convention and follow it?
- Is the content free of material that belongs to a repeating type?
- Is the subject one the vault can only ever hold once?

## Background

The convention is chosen per document. Each singleton follows the recognized practice for its own kind, so a vision document follows product vision practice and a strategy document follows product strategy practice. The convention is researched and agreed with the owner before writing starts, the same way a new type is researched before it is added to the table.
