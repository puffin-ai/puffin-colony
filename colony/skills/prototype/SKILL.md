---
name: prototype
description: Build throwaway code that answers one design question, as a clickable logic demo or as switchable screen variants. Use when someone wants to check that a state model or a piece of logic feels right before building it, or to see a few different designs of a screen before choosing one.
---

# Prototype

A prototype is **throwaway code that answers a question**. The question decides its shape, so name it first:

- **"Does this logic feel right?"**: a state model, a set of rules, a data shape. Build a logic demo.
- **"What should this look like?"**: a screen or a part of one. Build screen variants.

When the question is unclear and nobody can say, pick by the code around it, a module for logic and a page for a screen, and write your assumption at the top of the prototype.

## Rules for both

1. **Marked throwaway.** Put it next to the code it is for, with `prototype` in its name, inside the repo's own layout.
2. **One command to run**: a script in the repo's task runner for variants, or one HTML file to open for a demo.
3. **No persistence.** State lives in memory. When the question is about storage, use a scratch database or file named `prototype-wipe-me`.
4. **No polish**: no tests, no error handling past what it needs to run, no abstractions.
5. **Show the state** after every action, or on every switch of variant.
6. **Capture it when done.** Fold the validated decision into the real code, push the prototype to a throwaway branch, `prototype/<name>`, never into the base branch, and put that branch and the answer on the card.

## A logic demo

1. **State the question** in one paragraph at the top of the page, where the reader sees it.
2. **Write the logic as a small pure module** in one `<script>` block: a reducer `(state, action) => state`, a state machine, or a few pure functions, whichever fits the question. It touches no page element, so it can move into the real code later.
3. **Build one self-contained HTML file**: no framework, no build, no server, so anyone opens it by double-click. Use the domain's words, not the code's. From top to bottom: the title and the question; the current state as a readable panel, with what just changed marked; one button per action, always available; and tabs of guided walkthroughs, each a short scenario with its steps as buttons, starting from a fixed state. Pick the happy path, a tricky edge, and an attempt at something that should be refused.
4. **Hand it over**, and listen for "that shouldn't be possible": those are the bugs in the idea.

## Screen variants

1. **Pick the host.** Prefer an existing page: render the variants on its route, behind a `?variant=` search parameter, with its real data, frame and density. Make a new route, with `prototype` in its path, only when nothing could host it.
2. **Draft 3 variants** by default, 5 at most. They differ in structure (layout, hierarchy, the main action), not only in color or copy, and each uses the repo's own components. Share a header, never a layout.
3. **Wire one switcher** on the route: the variant from the search parameter, `A` by default, each variant its own component.
4. **Add a floating bar** at the bottom center: a previous arrow, the variant's key and name, and a next arrow, which wrap around and update the search parameter through the router. The left and right keys switch too, except while a text field has focus. Hide the bar in production builds.
5. **Hand over the link** with the variant keys. The answer is often a mix: the header from B, the list from C.

Variants stay read-only: point any write at a stub. When one wins, rebuild it properly in the real page, with tests, and push the rest to the throwaway branch.
