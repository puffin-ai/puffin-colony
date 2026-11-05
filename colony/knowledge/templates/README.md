---
type: readme-page
created: YYYY-MM-DD
description: The entry page for {product}'s knowledge vault, naming its layers and the question each one answers. Read first when entering the vault, and before deciding which layer a new page belongs in.
---

# Knowledge

## What this folder holds

Everything the team knows about {product}, held in layers that each answer one question. The [[authority]] rule says which layer a page belongs to and what each layer promises, and the [[page-types]] rule says which type each page takes.

{product} is <one paragraph that setup writes from the repository: what the product does, for whom, and which apps it runs as>.

## How it is organized

Each layer answers one question, and a page belongs to the layer whose question it answers.

- **What we decided.** `wiki/` holds the decided product truth, grouped by area, with each decision record beside the pages it decides.
- **What we might do.** `future-work.md` registers ideas and deferred work, each with its stage, the reason it waits, and what would reopen it.
- **What we built.** `specs/` holds each feature's spec documents and its reconciliation report under `plans/`, the build checklists under `checklists/`, and one living spec per capability of the running system under `system/`.
- **What we found out.** `raw/` holds outside material exactly as it arrived, one source page per capture, grouped by origin. `research/` holds what our own investigations concluded, each finding turned into a rule, a check, or a decision.
- **What we left behind.** `archive/` holds the history behind rejected ideas, retired features, and replaced names, with closed plan folders and the decision records a later record replaced in full.

The wiki and `specs/system/` cover the same product from two sides. The wiki records the behavior we decided on, and `specs/system/` records the behavior the code runs, so a difference between the two is work not yet done or a decision not yet written down.

### Finding a decision

A decision record's title is the decision as one sentence, its area's readme lists it, and its description states the call. A replaced record links its replacement. `decisions.md`, at the top of this folder, is the decision log: `colony check-docs` writes it from every decision record, grouped by area, with the active records first and each replaced record marked. Nobody edits the log by hand.

## Pages

- [decisions](decisions.md): every decision record by area, the active ones first, written by `colony check-docs`.
- [future-work](future-work.md): which ideas and deferred features remain open, and why each waits.
- [wiki](wiki/README.md): what {product} is and what we have decided, area by area.
- [specs](specs/README.md): what each feature had to deliver, how its build went, and what each capability does now.
- [research](research/README.md): what each investigation found and the rules it produced.
- [raw](raw/README.md): the outside material we captured, by origin.
- [archive](archive/README.md): why an idea was rejected, a feature retired, or a name replaced.

## Not here

- The rules that bind every page: `.colony/rules/`, starting at [[authority]] and [[page-types]].
- The definition each page type follows: `.types/`, starting at [[type-definition]].
