---
type: readme-page
created: YYYY-MM-DD
description: The entry page for feature specs, build checklists, and the system as built. Read before planning a FEATURE or changing code.
---

# Specs

## What this folder holds

Each feature's spec and build record, the build checklists, and the description of the system as built. The [[authority]] rule gives each subfolder its standing, and the [[docs-life-cycle]] rule governs work that becomes code.

## How it is organized

- `plans/` holds the feature records the [[docs-life-cycle#Plan]] section requires, grouped by feature because a feature can cross areas.
- `plans/<feature>/` holds one feature's spec. A FEATURE built in several cards has three spec documents: the [[feature-requirements]] page states what it must deliver, the [[feature-design]] page states how it is built, and the [[feature-tasks]] page divides it into tasks. A FEATURE one card builds has one [[feature-spec]] instead. The folder also holds the feature's [[reconciliation-report]], which records the outcome with its coverage, drift, and measures. The folder shares the feature's name and is created with the spec on the feature's branch.
- `plans/<launch>/` holds the [[launch-plan]] of one launch: its milestones, their exit criteria, and every item with its one owner.
- `checklists/` holds one [[build-checklist]] per build, and one [[owner-checklist]] per field, the steps only the owner can take.
- `system/` holds one [[living-spec]] per capability, the current state of that part of the product, written by the builder in every change that alters it.
- `system/` mirrors the wiki's area folders: living specs group into `system/<area>/`, each folder born by the first spec written into it, one level deep. Walking the wiki and `system/` side by side shows the drift, decided but not built in one direction, built but undocumented in the other.
- A feature folder carries no readme, because the pages it holds are known in advance and the plans readme's line already names them.

## Pages

- [plans](plans/README.md): what each feature had to deliver, how it was built and divided into tasks, and how its build went.
- [checklists](checklists/README.md): where each build stands, and which owner steps it waits on.
- [system](system/README.md): what each built capability does now.
