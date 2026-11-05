---
type: type-definition
created: 2026-11-05
description: How to write an evolving idea spec. Read before expanding a register entry while product behavior is still undecided.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Idea spec

An idea spec explores one coherent part of a possible feature while its product behavior remains open. Several idea specs can serve one [[future-work]] item when it has several open questions. Each page gives an agent enough context to continue that part without treating the proposal as a requirement. The writer must add an idea spec when an item outgrows its register row. Routing test: if the page shows an unresolved product choice for one part of an idea, it is an idea spec.

## Send it elsewhere when

- The owner wants a yes-or-no recommendation on writing a PRD. That is a [[one-pager]].
- The feature is accepted and needs testable requirements. That is a [[prd]] in the wiki.
- A short idea still fits in one register row. That belongs in [[future-work]].
- The page maps a large idea's files. That is a [[readme-page]] in the idea's folder.
- The page divides an agreed feature into build tasks. That is a [[feature-tasks]] page.
- The page describes running behavior. That is a [[living-spec]].
- The page reports outside findings. That is a [[research-report]].

## Frontmatter

```yaml
type: idea-spec
created: YYYY-MM-DD
description: <what the idea explores and when to read it, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
```

## Skeleton

- **Idea.** One paragraph saying what this part might do and who it might serve.
- **Why consider it.** The problem and the evidence or judgment that makes it worth exploring.
- **What is known.** Links to accepted wiki decisions and relevant research, without copying their claims.
- **Possible shape.** The current proposal, labeled as tentative.
- **Open choices.** Each unresolved product choice and what would settle it.
- **Next decision.** The decision that would move the idea forward or defer it, with any condition for revisiting it.
- **Related work.** Links to an active issue, branch, or pull request when one exists.

## Rules

The [[authority#Long-running ideas]] section governs register links, item stages, folder maps, and accepted decisions.

- An idea spec must sit under `{knowledge}/future-work/`.
- The page must explore one coherent part of a possible feature.
- The writer must mark every proposed behavior as tentative.
- The writer must not assign PRD requirement identifiers.
- The writer must link each accepted constraint to its wiki page.
- The writer must not copy the requirement text.
- The writer must name the open choices and the evidence or owner's decision that would settle each one.
- The writer must not claim that an absent work link proves no work is active.

## Before you publish

- Does the page explore one coherent part of a possible feature?
- Can a reader distinguish accepted constraints from tentative behavior?
- Does every open choice name how it will be settled?
- Does the page link accepted constraints without copying requirement text?
- Is the page free of PRD identifiers and claims about running behavior?

## Background

This type adapts the opportunity assessment in [[one-pager]] and the alternatives and open choices of [[tech-design]]. It keeps the problem, evidence, possible approach, and unresolved decisions for one part so another agent can continue the exploration. It drops the one-pager's yes-or-no recommendation and fixed length because the owner may want to develop a large idea before deciding its final scope. It drops the tech design's buildable contract because no implementation has been agreed.
