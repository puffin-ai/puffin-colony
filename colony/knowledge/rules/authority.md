---
type: rule
created: 2026-11-05
description: Where every page lives, what each layer promises, how a decision is found, and how every change to a page lands through a pull request. Read before creating a page or moving one between layers.
assisted-by: claude-code:claude-fable-5
enforced-by: colony check-docs for replaced decision records and the decision log, human review in the pull request
paths:
  - "**/{knowledge}/**"
---

# Authority

## What the rule is

A page's folder is its trust signal. The folder tells every reader, human or agent, what kind of knowledge the page holds before they read a word of it.

### The layers

Every knowledge page must live in exactly one layer from the table below.

| Layer | What it holds |
| --- | --- |
| `{knowledge}/wiki/` | The decided product truth, with each [[decision-record]] beside the pages it decides |
| `{knowledge}/decisions.md` | The decision log, which `colony check-docs` writes from every decision record |
| `{knowledge}/future-work.md` and `{knowledge}/future-work/` | Ideas, deferred features, and the reason each deferred item waits |
| `{knowledge}/archive/` | Rejected ideas, retired features, and replaced names with their reasons and evidence, closed plan folders under `plans/`, and decision records replaced in full under `decisions/` |
| `{knowledge}/raw/` | Outside material frozen at capture, as [[source]] pages grouped by origin |
| `{knowledge}/research/` | [[research-report]] pages |
| `{knowledge}/specs/plans/` | Each feature's spec documents or [[feature-spec]], its [[reconciliation-report]], and each [[launch-plan]] |
| `{knowledge}/specs/checklists/` | One [[build-checklist]] per build and one [[owner-checklist]] per field |
| `{knowledge}/specs/system/` | One [[living-spec]] per capability |
| `{knowledge}/.types/` | Every [[type-definition]] and [[diagram-type]] |
| `.colony/rules/` | Every [[rule]] |

- The wiki states accepted current behavior. The [[future-work]] register makes tentative and postponed work visible on the base branch, and its opening sets how a row is written. Pull requests hold the record for single changes.
- Each knowledge layer carries a [[readme-page]] saying how its content is organized.
- A [[decision-record]] must sit in the wiki folder of the area it decides, beside the pages it decides, because a reader who opens an area finds its calls there. The vault holds no separate folder of decision records.
- An [[archive-record]] sits in the archive under `replaced`, `rejected`, or `retired`. An archived page states no current product contract and authorizes no build.
- The repository's `.ignore` file must list `{knowledge}/archive/`, so a default search returns only live pages.

### Finding a decision

The writer of a decision record must keep each way a reader finds it true:

- The title states the decision as one sentence, and the frontmatter `description` states the call and when to read it.
- The readme of the record's area folder lists it under Pages, with the call it settles.
- A replaced record opens with a link to its replacement, and the new record names what it replaces.
- `{knowledge}/decisions.md`, the decision log, lists every record by area, the active ones first and each replaced one marked. Nobody must edit it by hand, because `colony check-docs` writes it from the records and a hand edit is lost on the next run.

### One path for every change

Git is the gate for every change. A merged future-work page accepts the record of an idea or a deferral, never the idea's proposed behavior as product truth.

- Every change to any page, in any layer, must land on a branch and merge through a pull request. The owner reviews the diff, and the merge is the approval.
- An agent must write each page directly in the folder its type serves, record current accepted behavior in the wiki page that owns it, and link that page from future work without copying its requirements.
- When an agent adds an idea or defers a product feature, the agent must add or update its row in [[future-work]] in the same pull request, linking an active issue or pull request when one exists.
- An [[idea-spec]] can name open choices. A wiki page or a spec document must settle the choices its claims depend on, and no page can carry a `[NEEDS CLARIFICATION: <the question>]` marker when its pull request opens for review.
- When the owner accepts an idea's product behavior, the agent must update or create the owning wiki page and update the idea's future-work entry in the same pull request, removing the row when no open part remains.
- A page that stops being true must be rewritten or deleted in the same pull request that changes the truth, with every link to it updated, so the vault never holds two versions of one decision.
- When the owner rejects an idea, removes a feature, or replaces a name, the writer must keep an [[archive-record]] when that history prevents a mistaken reading or a repeated investigation, and remove the item's future-work row in the same change.
- A decision record that a later decision replaces must open with a line naming its replacement, because the reasoning behind a past call keeps its value. A record replaced in part stays where it is.
- A decision record must move to `{knowledge}/archive/decisions/` only when a later record replaces it in full, and that record must first restate every older part still in force.
- A plan folder must move to `{knowledge}/archive/plans/` only when its feature's [[reconciliation-report]] merged at least 7 days earlier and no acceptance, release, owner question, open pull request, or card still needs it. A [[build-checklist]] moves there once every box is ticked.
- Before a page moves to the archive, the writer must move its pending items to the live page that owns that work, and every requirement a [[living-spec]] lists as in force must stand in a live [[prd]] or [[feature-spec]].
- A [[source]] page must not change after capture, and a [[research-report]] must not change after it lands, because both record what was true on a date. A correction is a new page. Fixing a broken link and keeping a findings table current are the two exceptions.

### Research ends in rules

Research is done only when every finding binds something: a rule line with its do and its don't, a check that enforces the line, or a decision the owner records.

- A [[research-report]] with `feeds-rules: true` must not be called done while any row of its findings table lacks a rule line and a check, or the owner's recorded decision, because a finding that reaches no rule and no check binds nothing.
- The researcher must ask the owner each decision a finding needs as one question with a default, and the work must go on under the default until the owner's answer replaces it.
- The writer must map the findings table from the full list of findings, never from a summary of them, because a summary drops the findings that bind least.
- A second research pass over a question a report with `feeds-rules: true` covers must first re-check and update every row of that report's findings table against the rules and checks on the base branch.

### Long-running ideas

An item whose explanation outgrows its [[future-work]] row gets an [[idea-spec]] in `{knowledge}/future-work/`, and an item that outgrows one idea spec gets its own folder there, with a readme that maps its pages.

- The writer must link an idea spec from its row's Item cell, or the item's folder readme by Markdown path, and list each page in its folder's readme.
- The row's Stage cell names the status of the whole item, and must be a stage the register defines in bold. One accepted part does not make every page of a large item accepted, so each page states its own open choices.
- The writer must merge two rows that name one idea, and must not remove a row without linking the decision that closes it.
- When the wiki settles one part, the writer must update the row and the folder map in the same pull request, and must remove an idea spec only when an accepted wiki page replaces all of its proposal.

## Why it exists

A reader decides how much to lean on a page from where it sits. If an unsettled idea sat in the wiki, agents could mistake it for accepted behavior. If it stayed only on a private branch, agents reading the base branch could miss work already considered. Git shows who changed each record and lets the owner review every change before it lands.

## What it applies to

Every markdown page inside `{knowledge}/` and `.colony/rules/`, and every human and agent who creates, changes, moves, or deletes one.

## What is exempt

- The root pages `README.md`, `AGENTS.md`, and `CLAUDE.md`, because GitHub and agent tooling fix their place at the repository root. They still change through a pull request.
- The decision log, from the rules on hand-written pages, because `colony check-docs` writes it.

## How it is enforced

`colony check-docs` refuses a replaced decision record that names no replacement, a record replaced in full outside the archive, and a decision log that differs from what the records generate. Human review in the pull request checks the rest: the folder, the type, open question markers, future-work rows, findings tables, and stale copies.
