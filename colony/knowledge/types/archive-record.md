---
type: type-definition
created: 2026-11-05
description: How to preserve an important rejected idea, retired feature, or replaced name without presenting it as current product truth. Read before adding a record to the archive.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Archive record

An archive record preserves one important feature, idea, or name that {product} rejected, retired, or replaced. It explains the former scope, the outcome, and the evidence a later reader needs before repeating the investigation or proposing the same thing. Routing test: if the reader needs to know what happened to something outside current product truth and active future work, write an archive record.

## Send it elsewhere when

- The idea remains possible or postponed. That belongs in Future Work under [[authority]].
- The page makes a new call. That is a [[decision-record]], and an archive record links to it.
- The page states current product behavior. That belongs in the wiki under its owning page type.
- The page captures outside material or reports research. Those remain [[source]] and [[research-report]] pages in their original layers.

## Frontmatter

```yaml
type: archive-record
created: YYYY-MM-DD
description: <what the former item was and when to read its history>
assisted-by: <agent>:<model>    # present only when an agent helped
item-kind: feature | idea | name
outcome: rejected | retired | replaced
```

## Skeleton

- `# <Item>` The name or former scope, without a status word in the filename.
- `## Former scope` What was considered or accepted, written in the past tense. Distinguish a product decision from evidence that it shipped.
- `## Outcome and reason` What happened and why, citing the owner's decision or another authoritative record. Give a date only when that record supplies it.
- `## Evidence` Links to the decision, research, raw sources, and related work that exist. State when no separate research was recorded.
- `## Replacement` The current definition, behavior, or decision that replaces the item, or an explicit statement that no replacement was chosen.
- `## Reopen if` The recorded trigger, or an explicit statement that none was set and a new owner decision is needed.

## Rules

- The writer must place the record in `{knowledge}/archive/<outcome>/`, using `replaced`, `rejected`, or `retired`, and link it from that outcome folder's README. The containing folder must match the outcome field.
- The writer must use `rejected` for something considered but never adopted, `retired` for an adopted feature or behavior that was removed, and `replaced` for a former name or approach replaced by another. A retired record can still link a different behavior that now serves the need.
- The writer must archive an item only when an explicit decision supports the outcome. A deferred feature or a feature absent from one release is not a rejected feature.
- The writer must preserve items whose history prevents a mistaken interpretation, repeated investigation, or reversal without its original evidence. Routine edits remain in Git and their pull requests. An alternative mentioned on a decision record warrants a separate archive record only when its reason or evidence remains useful.
- The writer must link original evidence without moving, rewriting, or copying its body. Retiring a proposal changes no source or research finding's validity by itself.
- The writer must update current wiki pages and remove an item's active Future Work row in the same change when a new decision closes that item completely.
- The record grants no permission to build. A reopened item follows [[authority]] through a new decision or Future Work entry, which links back here.

## Before you publish

1. Does one record cover exactly one feature, idea, or former name?
2. Does an explicit decision support the outcome and any recorded date?
3. Are the reason, original evidence, and replacement or absence of one discoverable?
4. Is the former scope distinct from current behavior and from a claim that it shipped?
5. Does the record preserve the original evidence and carry its recorded revisit trigger or state that none was set?

## Background

The convention combines the durable, searchable idea archive product teams keep, with the reason and replacement links of a [[decision-record]]. We adopt a short record of the outcome and its evidence so a reader can reconstruct the choice. We leave delivery tracking to the linked issue or pull request and leave original research and decisions in their owning layers, because copying those pages would create competing records.
