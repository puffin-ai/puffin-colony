---
type: singleton
created: YYYY-MM-DD
description: The register of {product}'s future ideas and deferred features, each with its stage, the reason it waits, and what would reopen it. Read before proposing product work, to find what has been considered and why it waits.
---

# Future work

This register makes possible and postponed product work visible on the base branch. An entry does not define product behavior or authorize a build. The [[authority]] rule gives this page its status. The register follows the idea backlog convention: one entry per possible product item, one stage for the whole item, and links to active work without copying its status.

## Stages

An **idea** is still open for a product decision. **Exploring** means the owner can develop the proposal while its feature stays outside the current release. **Planned** means an agreed feature will build the item, and the row links that feature's pages. **Reserved** means a named feature holds the item for its own build, and the Stage cell names that feature. **Deferred** means someone chose to leave the work outside the current scope. A deferred entry records why it waits and what would reopen it without promising that it will ship.

A row must use only a stage this section defines in bold, and a new stage must be defined here before a row uses it.

## How a row is written

Each item starts as one row. When an [[idea-spec]] sits directly in `future-work/`, the Item cell links to that page. When an item has its own folder, the Item cell links to the folder README, which maps its pages. An idea's Next decision cell names the choice that would advance it. A deferred item's Next decision cell names the event that would reopen it. The Current record cell links to accepted current behavior or supporting evidence.

Every row must fill its Why it waits cell and its Next decision cell, because a row with neither cannot be judged or reopened. An empty Related work cell means this register has no issue or pull request link for the item. It does not prove that nobody is working on it, so an agent checks live issues and pull requests before starting work.

## Items

Each area's rows sit under one `###` heading, named as the wiki names the area and added with the area's first row, in a table with these columns:

| Item | Stage | Why it waits | Next decision or revisit trigger | Current record | Related work |
| --- | --- | --- | --- | --- | --- |
