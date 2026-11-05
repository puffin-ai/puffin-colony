---
type: readme-page
created: YYYY-MM-DD
description: The entry page for the wiki layer, {product}'s decided product truth and the decision records behind it. Read before looking for what is settled or adding to it.
---

# Wiki

## What this folder holds

The decided product truth, and the [[decision-record]] pages that settled it. The [[authority]] rule says what the wiki promises and how a change to it lands.

## How it is organized

Pages group by subject, never by document type.

- `product/` holds the pages that describe the whole product rather than one area, such as the vision and the strategy, each a [[singleton]].
- `glossary/` holds one [[glossary-entry]] per term of {product}'s vocabulary.
- `<area>/` holds one product area, or the platform every product area runs inside. An area folder is born by the first page written into it, never in advance, and is named from the vocabulary the glossary defines.
- `<area>/<feature>/` holds the pages of one feature of the area, even a feature of one page. A page about the area's shared machinery gets a folder for that subject the same way. Two levels is the maximum, and a feature that outgrows its own readme is raised to an area of its own, not nested deeper.
- Each decision record sits in the folder of the area or feature it decides, beside the pages it decides. The wiki holds no separate folder of decision records.
- Each folder carries its own readme listing its pages, its decision records among them, each with the call it settles. A decision record replaced in full moves to the archive under the [[authority]] rule.

## Pages

No pages yet. Each folder gets its line here in the change that creates it.

## Not here

- Ideas and deferred work: the [future work register](../future-work.md).
- What the code runs today: [specs](../specs/README.md), under `system/`.
- What an investigation found: [research](../research/README.md).
