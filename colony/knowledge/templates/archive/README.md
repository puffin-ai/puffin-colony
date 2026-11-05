---
type: readme-page
created: YYYY-MM-DD
description: The entry page for the vault's history, covering the records behind rejected ideas, retired features, and replaced names, the closed plan folders, and the decision records a later record replaced in full. Read to find why {product} changed a decision, to interpret older material, or before moving a page here.
---

# Archive

## What this folder holds

The historical [[archive-record]] pages whose reasons, evidence, or replacements remain useful, and the pages that moved here once they stopped binding: closed plan folders and decision records replaced in full. The [[authority]] rule defines this layer's boundary and when a page moves here.

## How it is organized

- `replaced/`, `rejected/`, and `retired/` hold one archive record per item. The record's outcome field matches its containing folder.
- `plans/` holds each closed feature plan folder under its own name, and each build checklist with every box ticked.
- `decisions/` holds each [[decision-record]] whose opening line names the record that replaced it in full. A record replaced in part stays beside its current record in the wiki.

Each subfolder is born by the first page moved or written into it, with a readme that maps its pages. A moved page keeps its type and its file name, so every wikilink to it still resolves. The repository's `.ignore` file leaves this folder out of a default search, so a search reaches an archived page only when it names the archive folder.

Keep a record when its history helps explain an important change, prevents repeated investigation, or makes older material understandable. Routine edits remain in Git and their pull requests. Original sources and research remain in their existing folders.

## Pages

No records yet. Each subfolder gets its line here in the change that creates it.

## Not here

- Current accepted behavior belongs in the [wiki](../wiki/README.md).
- Open ideas and deferred features belong in the [future work register](../future-work.md).
- Open feature plans stay in [plans](../specs/plans/README.md) until the authority rule moves them.
- Original outside material stays in [raw](../raw/README.md), and completed investigations stay in [research](../research/README.md).
