---
type: rule
created: 2026-11-05
description: The rule for every diagram in the vault, Mermaid or SVG. Read before choosing a diagram type, drawing one, or reviewing one.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
paths:
  - "**/{knowledge}/**"
---

# Diagrams

## What the rule is

Every diagram in the vault uses one of the defined types below. Mermaid draws the process, state, message, record, and system views. An Euler diagram uses an editable SVG for category relationships. A diagram exists to make a mechanism graspable at a glance.

### Choosing the type

- The writer must give every diagram exactly one type from the table below.
- The writer must match the type to the content before drawing, because a wrong choice is the one mistake careful drawing cannot fix.
- A writer whose content fits no type must stop, propose the new diagram type, research the recognized notation for that kind of content, and draw only after the type is added to the table and its [[diagram-type]] definition is written in `{knowledge}/.types/`.
- Three or more independent conditions combining into outcomes must be a Markdown table beside one box, because nested diamonds need a path per combination and a table makes gaps and overlaps visible.

| Diagram type        | Purpose                                                                     | Convention           | Syntax                     |
| ------------------- | --------------------------------------------------------------------------- | -------------------- | -------------------------- |
| Flowchart           | Shows one process moving through steps and decisions                        | ISO 5807             | Mermaid `flowchart`        |
| Sequence diagram    | Shows parties exchanging messages over time                                 | UML 2.5.1            | Mermaid `sequenceDiagram`  |
| State diagram       | Shows the conditions one object rests in and the events that move it        | Harel statecharts    | Mermaid `stateDiagram-v2`  |
| Entity relationship | Shows the entities in the data model and how they relate                    | Crow's foot notation | Mermaid `erDiagram`        |
| C4 view             | Shows the structure of one system at one zoom level                         | C4 model             | Mermaid `C4Context`, `C4Container`, `C4Component` |
| Euler diagram       | Shows categories overlapping, containing one another, or remaining separate | Euler set notation   | Editable SVG               |

The row of a type is its definition until a [[diagram-type]] page is written for it. A type that needs its own rules, or a carve-out from this page, must have that page first.

### Excluded on purpose

- Class diagrams. Code describes itself, and a diagram of it goes stale the day the code changes. If one is ever needed, it is generated from the code.
- Gantt charts, timelines, kanban boards, and quadrant charts. Planning and tracking live in the issue tracker and its board.
- Journey maps. They enter a [[research-report]] when real user research exists.
- Mindmaps. A diagram with no convention cannot be reviewed against anything.
- Pie charts and other data charts. Evidence numbers sit in Markdown tables, where a reviewer can check each value.

### Every diagram

- A diagram must make one claim. A diagram that needs two abstraction levels, two legends, or two reading axes is two diagrams. When content outgrows the page, the writer must collapse a run of steps into one named box and draw its interior separately rather than shrink the diagram.
- A diagram must carry a title in its Mermaid frontmatter, a `title:` line inside a `---` block at the top of the source, with `accTitle` and `accDescr` for screen readers.
- A diagram must carry an introductory prose sentence ending in a colon.
- The surrounding prose must state the flow in words, so a reader who cannot see the diagram loses nothing.
- The writer must keep edge crossings at two or fewer.
- The writer must split a diagram that cannot stay under the crossing limit rather than tweak it.
- A node must keep exactly one name across every diagram and the prose, so a box called "Validate command" is never "check command" elsewhere.
- Every arrow must be one-directional.
- An arrow must carry a label wherever the relationship is not obvious, with the label wording matching the arrow's direction.
- A legend must be a Markdown table below the diagram, written whenever color or an unusual shape carries meaning, because Mermaid has no legend construct and a legend built from a subgraph breaks layout.

### Color

- A diagram must use at most three colors, encoding exactly one dimension, with the mapping stated in the legend table below the diagram.
- Styling must use `classDef`, never external CSS and never `linkStyle` by index, which silently restyles the wrong edge when edges reorder.
- A diagram must still read in grayscale, with shape and position carrying the structure and color only reinforcing it.
- The palette is green `fill:#dff3e4,stroke:#2f7d4f`, amber `fill:#fdf0d5,stroke:#b8860b`, and red `fill:#fbe0e0,stroke:#b03030`, all with `color:#123`.

### Renderer limits

- A diagram must use nothing newer than Mermaid 11.13, the version Obsidian bundles, because GitHub lags releases by a year or more. The writer can check any renderer's version by rendering a code block containing only the word `info`.
- That rules out `swimlane-beta`, the ELK renderer, and invisible `~~~` links.
- The layout levers are `curve` with `linear` preferred for process flows, `nodeSpacing` and `rankSpacing`, extra dashes to lengthen an edge, and edge declaration order. Nothing else.
- An Euler diagram must render as a local SVG image in both Obsidian and GitHub before it is published.

## Why it exists

A diagram carries authority, so a wrong type or an unreadable layout misleads a reader more than no diagram would. Edge crossings measurably damage comprehension, which is the one strong empirical result in graph readability (Purchase, 1997). A diagram written past what the renderer supports fails silently, leaving a broken block where the page promised a shape.

## What it applies to

Every diagram on every page inside `{knowledge}/`, and every human and agent who draws one. Most diagrams sit on [[tech-design]], [[architecture]], and [[design-spec]] pages, whose definitions link here.

## What is exempt

- Diagrams inside [[source]] pages. Captured outside material is frozen, so a diagram arrives exactly as its author drew it and stays that way.
- A C4 view's styling mechanism and layout levers. Mermaid's C4 keywords ignore `classDef` and the general layout levers, so a C4 view styles each element with `UpdateElementStyle` and lays out by declaration order. The palette and color rules still bind it.
- An Euler diagram's format, accessibility fields, styling mechanism, and layout levers. Its editable SVG, image alternative text, `title`, and `desc` replace a Mermaid block and its frontmatter, `accTitle`, and `accDescr`. SVG fill and stroke attributes replace `classDef`, and explicit contour coordinates replace graph layout levers. The palette, legend, prose explanation, and other applicable checks still bind it.

## How it is enforced

Human review in the pull request. Before merging, the reviewer runs this checklist, and a no on any question is a defect to fix first:

1. Does it have a title, and is the diagram's type and scope clear from it?
2. Is there an introductory sentence in the prose, and does the prose state the flow in words?
3. Is the type one of the types in the table, and right for the content?
4. Does every element have a name, and does every name match the prose?
5. Is every arrow one-directional, and labeled where the relationship is not obvious?
6. Are crossings at two or fewer?
7. Are colors at most three, encoding one dimension, explained in a legend table, and dispensable in grayscale?
8. Does the diagram pass the checks of its type's [[diagram-type]] page, where one exists?
9. Does it render as a local SVG image in Obsidian and GitHub, or use nothing newer than Mermaid 11.13 when it is a Mermaid diagram?
