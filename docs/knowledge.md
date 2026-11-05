# The knowledge vault

The vault holds what the team decided, built and found out, as typed Markdown pages with Obsidian-style `[[links]]`. It lives at the repo root in `knowledge/`, or in the folder you pick at setup. Agents read it before they plan, and change it in the same change as the code it describes.

## Setup

Setup offers the vault as one item of its yes-or-no list, default yes. With no docs folder, the vault goes in `knowledge/`. With one, such as `docs/` or a folder of decision records, the default is to adopt it in place. You can answer with another folder instead.

1. It copies the folder templates into the vault, the page type definitions into `knowledge/.types/`, and the knowledge rules into `.colony/rules/`. It never overwrites a file already there.
2. It fills in the product's name and the app folders, and writes the first paragraph of `knowledge/README.md` from what it read in the repo.
3. In an adopted folder, it moves, renames, retypes and deletes nothing. It counts the pages with no `type`, and names that count in the setup PR as follow-up work.
4. It links each knowledge rule into `.claude/rules/`, so Claude Code loads the rule when an agent opens a matching file.
5. It adds `knowledge/archive/` to `.ignore`, so a default search finds only live pages.
6. It sets `[knowledge] vault`, writes the decision log with `colony check-docs --index`, and runs `colony check-docs`. A fresh vault passes clean.

## The layers

A page's folder tells every reader what kind of knowledge it holds, before they read a word of it.

| Folder | Answers | Holds |
| --- | --- | --- |
| `wiki/` | What we decided | The decided product truth, by area, with each decision record beside the pages it decides |
| `decisions.md` | Where a decision is | The decision log, written by `colony check-docs` |
| `future-work.md` | What we might do | Ideas and deferred work, each with its stage, why it waits, and what would reopen it |
| `specs/plans/` | What a feature had to deliver | Each feature's spec, its reconciliation report, and each launch plan |
| `specs/checklists/` | Where a build stands | One build checklist per build, and one owner checklist per field |
| `specs/system/` | What the code runs today | One living spec per capability |
| `raw/` | What outside material says | Sources, frozen as they arrived, grouped by origin |
| `research/` | What we found out | One research report per question |
| `archive/` | What we left behind | Rejected ideas, retired features, replaced names, closed plans, and decision records replaced in full |
| `.types/` | How a page is written | One definition per page type |

The wiki and `specs/system/` cover the product from two sides: what we decided, and what the code runs. A difference between them is work not yet done, or a decision not yet written down.

## Page types

Every page declares one `type` in its frontmatter, with `created` and a one-sentence `description`. A writer reads the type's definition down to its "## Background" heading before writing, and follows it. There are 29 types:

- **The product:** one-pager, prd, design-spec, tech-design, architecture, building-block, threat-model, runbook, decision-record, glossary-entry, singleton.
- **The work:** idea-spec, archive-record, source, research-report, feature-requirements, feature-design, feature-tasks, feature-spec, implementation-plan (retired, kept for old pages), reconciliation-report, build-checklist, owner-checklist, launch-plan, living-spec.
- **The vault itself:** rule, type-definition, diagram-type, readme-page.

A page that fits two types is split in two and linked. A page that fits none waits until a new type is defined. The definitions ship in [`colony/knowledge/types/`](../colony/knowledge/types/README.md).

## Sources, research and decisions

These three are easy to mix up, so the vault keeps them apart:

- **A source** is someone else's material: a vendor's docs page, a standard, a transcript. It goes in `raw/<origin>/` exactly as it arrived, and never changes after capture.
- **A research report** is what our own investigation concluded on a date: one question, the bottom line first, every claim cited. It goes in `research/`, and doesn't change after it lands. A correction is a new report.
- **A decision record** is one call the owner accepted, with its reasons. It sits in the wiki folder of the area it decides, beside the pages it decides.

A summary or a conclusion is never a source. A research finding is not a decision until a rule, a check, or the owner binds it.

## How research becomes rules

The researcher answers one question per report and writes it as a research report. A report whose findings say how the product should be built, such as a best practice, a standard or an audit of the code, sets `feeds-rules: true`. Market, legal, user and product research sets `false`.

A `feeds-rules: true` report holds a findings table, mapped from the full list of findings, never from a summary of them. Each row closes in one of three ways:

1. **A rule line.** One must line and the must-not that goes with it, written into its rule page in `.colony/rules/` or into an area's `AGENTS.md`, on the research branch.
2. **A check.** The test, lint rule or script that enforces the line, with its count of breaks today. A small check is built on the same branch. A larger one gets an issue titled `check: <what it checks>`, and the row links it as planned.
3. **A decision.** When a finding needs a call only the owner can make, the researcher posts it with `colony needs` and a default. The work goes on under the default until the owner's answer replaces it.

The report is not done while any row lacks a rule line and a check, or a recorded decision. A second pass over the same question first re-checks every row of the old table against the rules and checks on the base branch.

The retro after each batch works the same way: each lesson becomes a rule line plus a check, or a decision. See [cycle.md](cycle.md#retro).

## The decision log

`knowledge/decisions.md` lists every decision record in the vault. Nobody writes it by hand: `colony check-docs` builds it from the records.

- It has one section per wiki area, then General. Each line is `- [[record]]: <the first sentence of its description>`.
- In each section, the active records come first, then the replaced ones, each marked with what replaced it.
- A record is replaced when its opening line says so and links the replacement, such as `Replaced by [[new-record]]`, or when it sits in the archive.
- The new record's opening line names what it replaces: `This record replaces [[old-record]]`.
- A record replaced in part stays beside its current record. A record replaced in full moves to `archive/decisions/`, once the new record restates every older part still in force.

Every full run of `colony check-docs` rewrites the log, and fails when the log it found differed. Commit the new file, and the next run passes.

## The rules

Setup copies seven knowledge rules into `.colony/rules/`. Each loads by path: when an agent opens a page in the vault, or a file in an app folder for the two that cover code.

| Rule | What it sets | Loads in |
| --- | --- | --- |
| `authority.md` | Which layer each page lives in, how a decision is found, and that every change lands through a PR | the vault |
| `page-types.md` | The type table, and how to pick one | the vault |
| `docs-life-cycle.md` | Where pages enter the cycle: research and specs before cards, living specs and wiki in the same change as code, one docs commit per batch | the vault and the apps |
| `writing.md` | How pages read: active voice, one idea per sentence, everyday words, and must, should or can for an obligation | the vault and the rules |
| `naming-and-links.md` | File and folder names, unique names, and `[[links]]` that resolve | the vault and the rules |
| `diagrams.md` | How to choose, draw and review a Mermaid or SVG diagram | the vault |
| `code-documentation.md` | Docstrings, comments, TODOs and suppression comments in code | the apps |

Two lines from `docs-life-cycle.md` bind every batch. A builder updates the living spec and the wiki pages in the same change as the code they describe. And each batch carries one docs commit that brings the wiki and living specs in line with what the batch changed, with `colony check-docs` run on the batch's tree before its PR opens.

## `colony check-docs`

| Check | Default | What it checks |
| --- | --- | --- |
| `page_types` | fail | Every page declares a type that `.types/` defines |
| `links` | fail | Every `[[link]]` and relative link resolves, to its heading too, and no two pages share a name |
| `orphans` | fail | Another page links to every page. The repo's `README.md`, `AGENTS.md` and `CLAUDE.md` count. |
| `readme_maps` | fail | Every folder README links each page and subfolder beside it |
| `code_paths` | fail | Every repo path a live page names in code ticks exists. Plans, research, sources and the archive are exempt. |
| `size_caps` | warn | Each type's size cap, such as 25,000 characters for a living spec |
| `dated_caps` | fail | A cap with a `from` date holds every page created on or after that day |
| `copied_text` | fail | No paragraph of 20 words or more stands on two pages. Sources and the archive are exempt. |
| `rule_budget` | fail | Every rule stays within its size budget, 12,000 characters by default |
| `replaced_records` | fail | A replaced decision record says so and links its replacement, and one replaced in full sits in the archive |
| `decision_log` | fail | `decisions.md` is what the decision records generate |

Each check's mode is `off`, `warn` or `fail`, set in `[knowledge]`. See [configuration.md](configuration.md#knowledge). The run prints each problem as `path:line: what is wrong`, then one count per check, and exits 1 when a check set to `fail` found a problem.

- `--staged` checks only the staged pages, with the six checks that read one page at a time: page types, links, code paths, both caps, and the rule budget. It suits a pre-commit hook.
- `--strict` turns every `warn` into `fail`.
- `--index` only rewrites the decision log.
