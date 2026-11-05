---
type: rule
created: 2026-11-05
description: The rules for file and folder names, name uniqueness, and link integrity, with Obsidian-style wikilinks. Read before creating, renaming, or linking a page.
assisted-by: claude-code:claude-fable-5
enforced-by: colony check-docs for resolving links and inbound links, human review in the pull request
paths:
  - "**/{knowledge}/**"
  - "**/.colony/rules/**"
---

# Naming and links

## What the rule is

A name is a page's address. A wikilink, written `[[page-name]]` or `[[page-name#Heading]]` as Obsidian reads it, resolves by file name, so the names are what holds the vault's link graph together.

- Every file and folder name inside `{knowledge}/` and `.colony/rules/` must use kebab-case: lowercase letters, digits, and single hyphens between words.
- A page's file name must be a kebab-case form of its title, shortened only from the end, except the year-and-month ending the rules below set.
- Every file name must be unique across the whole vault, its type definitions and its rules included, because a wikilink resolves by file name and a duplicate makes every link to that name ambiguous. The readme rule below carves out the only exception.
- A file name must not carry a version marker or a status word, such as "v2", "final", "new", or "old", because git holds the history.
- Every [[research-report]] must end its file name with the year and month of its creation in the form YYYY-MM, because a report records what was found on a date, and the name carries the date into every link to it.
- A [[feature-requirements]], [[feature-design]], [[feature-tasks]], or [[reconciliation-report]] page whose feature name recurs can end its file name the same way, so repeated work never collides on one name.
- Every [[readme-page]] must be named `README.md`, and a wikilink must never point at one, because the name repeats in every folder and can never resolve to one page. A readme is linked by its path in a markdown link.
- Every wikilink must resolve to a page in the vault, a type definition, or a rule.
- Every page other than a readme must be linked from at least one other page, because a page no link reaches is a page no reader finds.
- The writer who renames a page must fix every inbound link to it in the same change.

## Why it exists

When two files share a name, every link to that name stops meaning one thing, and the reader cannot tell which page they were sent to. When a file name drifts from its page title, a reader who saw the title cannot find the page by its link. A link that resolves nowhere teaches the reader that links cannot be trusted, and after that every link in the vault gets double-checked by hand. The one allowed duplicate stays harmless because a readme may never be a wikilink's target: it is reached by path.

## What it applies to

Every file and folder inside `{knowledge}/` and `.colony/rules/`, and every human and agent who creates, renames, or links one.

## What is exempt

- The root pages `README.md`, `AGENTS.md`, and `CLAUDE.md`, because GitHub and agent tooling fix their uppercase names.
- Files inside `.github/`, `.claude/`, and `.obsidian/`, because their tools fix their names and shapes.
- External URLs in markdown links, because the vault cannot keep the outside web resolving.

## How it is enforced

`colony check-docs`, in the mode the repository sets, refuses a wikilink that resolves to no page and a page that no other page links. Human review in the pull request checks what the script leaves to people: that every name is kebab-case and unique, that a new name is a kebab-case form of its page's title, that no wikilink points at a readme, and that a link naming a heading finds that heading on its target page.
