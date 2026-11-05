---
type: type-definition
created: 2026-11-05
description: How to write a readme page. Read before adding an entry page to a folder.
assisted-by: claude-code:claude-fable-5
enforced-by: colony check-docs for the folder map, human review in the pull request
---

# Readme page

A readme page is a folder's entry page. It says what the folder holds, how the content inside is organized, and gives one line per page saying what that page answers. It carries no knowledge of its own: the product facts live on the pages it points at. Write one when a folder holds several pages, or when a reader entering the folder needs to know how it is arranged before adding to it. Routing test: if the page teaches the reader about the folder rather than about the product, it is a readme page.

## Send it elsewhere when

- The page explains the idea the folder is about. That belongs in a [[glossary-entry]] for a single term, or in the [[prd]], [[tech-design]], or [[architecture]] page that owns the idea, and the readme links to it.
- The page sets a rule that binds everything in the folder. That is a [[rule]] page in `.colony/rules/`, and the readme links to it.
- The page describes how the whole system fits together. That is an [[architecture]] page.
- The page records one accepted call and why. That is a [[decision-record]].
- The page carries a product claim plus a list of links. Split it. The claim moves to the page that owns it, and the links stay on the readme.

## Frontmatter

```yaml
type: readme-page
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD        # set only by a verification pass, never by hand
```

## Skeleton

- `# <Folder name>` The name of the area as a plain noun phrase.
- `## What this folder holds` One or two sentences on what sits here, linking the rule or page that governs it rather than restating it.
- `## How it is organized` How content inside the folder is arranged: the subfolders, what goes where, and any naming the folder adds. Write it only when the folder has structure to explain.
- `## Pages` One line per page that stays in the folder: the link, then what that page answers, in a few words. Past ten lines, group them under small headings. A folder whose pages churn skips this section.
- `## Not here` The neighbouring folders a reader may have wanted, each a link. Write this only when readers land here by mistake.

## Rules

1. The file must be named `README.md` and must sit inside the folder it describes.
2. The readme must carry no fact that a page inside the folder carries, and no product claim of its own. What it owns is the folder: what it holds, how it is arranged, and where its pages are.
3. Every page that stays in the folder must have a line under Pages, and every line must resolve to a page that exists.
4. Each line must say what its page answers, not repeat the page title.
5. You must update the readme in the same change that adds, moves, or removes a page in its folder.
6. The writer must split a folder once its readme's Pages section passes 25 lines. Move a group into a subfolder with its own readme and leave one line here pointing at it.

## Before you publish

- Is the file named `README.md`, sitting inside the folder it describes?
- Is the page free of product claims and of any fact one of its own pages states?
- Does every page that stays in the folder have a line, and does every line open a page that exists?
- Does each line say what its page answers, so a reader picks one without opening two?
- Is the Pages section at 25 lines or fewer?

## Background

The convention is the README file from software practice, a fixed uppercase name at the top of a folder that orients whoever opens it, which hosts like GitHub render automatically when the folder is browsed. For the page map we adopt the Map of Content convention from Nick Milo's Linking Your Thinking, a note whose links are grouped and ordered on purpose, curating access instead of restricting it. We adopt the fixed name for the automatic rendering, and the curated map because it guides a reader without hiding anything. We drop the software README's installation and licensing boilerplate, because a vault folder is not a software package, and we drop the Wikipedia portal habit of pasting excerpts from the linked pages, because a pasted excerpt is a second copy that goes stale on its own.
