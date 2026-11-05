---
type: rule
created: 2026-11-05
description: The language rules every page of the vault and every rule follows. Read before writing or reviewing any page.
assisted-by: claude-code:claude-fable-5
enforced-by: colony check-docs for the page size caps and copied paragraphs, human review in the pull request
paths:
  - "**/{knowledge}/**"
  - "**/.colony/rules/**"
---

# Writing

## What the rule is

Every page is written in plain language under ISO 24495-1, so a cold reader understands it on first read and can act on it. A type's definition can add a stricter standard on top of these rules and must not relax them.

### Sentences

The sentence rules come from the US Federal Plain Language Guidelines, with the paragraph cap from ASD-STE100.

- The writer must use the active voice and name who acts. The actor must be a person or a named part of the system.
- "you" must address the reader of the page, the person or agent building {product}, because the root `AGENTS.md` already binds "you" to the agent.
- The writer must call the person {product} serves "the user", in the third person, never "you", and by no other name.
- The writer must not hide a verb inside a noun, so "the user accepts it" never becomes "the user's acceptance".
- The writer must use the present tense unless the sentence reports a past event.
- The writer must put one idea in each sentence and choose the everyday word over the formal one.
- The writer must explain a technical term where it first appears or link its glossary entry.
- The writer must not use wordplay, puns, clever phrasing, or metaphor, apart from a term the vault defines, used with its defined meaning.
- The writer must state the positive claim and stop, with no contrasting denial appended, such as "through a pull request, and never a dashboard". A contrast that carries its own fact becomes a second sentence.
- The writer must keep each paragraph to one topic and at most six sentences.

### Structure

Agents retrieve sections, not pages, so a section must stand alone.

- The writer must not skip a heading level.
- Every section must name its own subject in its heading and its first sentence, with no opener such as "as mentioned above".
- A heading must not open with a pronoun such as "it" or "they".
- A constraint must sit in the same section as the instruction it constrains.
- A table must stay flat, with no meaning carried only by the position of its rows and columns.
- A page must stay under 500 lines, and a page that outgrows that budget must split into linked pages.
- Detail pushed to another page must sit one link away and stop there.
- The writer must write an explanation as a section of the page it belongs to, and give it its own page only when it outgrows one paragraph or its page outgrows the line budget.
- A second page that needs the same explanation must link to the section, in the form `[[page#Heading]]`, and must not repeat it.
- The writer must merge a page whose whole content fits in one paragraph back into the page it belongs to.
- Every page must carry a frontmatter `description` that says what the page is and when to read it, with the key use first, in at most 1,024 characters.

### Force words

The force words come from BCP 14, in lowercase.

- A sentence that states an obligation must carry exactly one of must, should, or can, and no other word, so "shall", "ought to", and "needs to" never appear.
- "must" names the only acceptable way, "should" names the default, and "can" names a free choice. A writer who departs from a "should" must state the reason.

### Fact and judgment

The split comes from Diátaxis.

- A sentence that states settled fact must state it plainly, with no hedge, and a sentence that carries judgment must be marked as judgment by its section or its wording. One sentence must not mix the two.
- A page that argues a call must use full sentences, and every bullet on it must carry a complete sentence.

### Mechanical items

Review checks these items on every vault and rule page.

- The writer must not use a semicolon or an em dash in prose. Both stay where a name or syntax requires them.
- The banned words of ISO/IEC/IEEE 29148 and INCOSE must not appear: "and/or", "etc." and open-ended phrases such as "including but not limited to", escape phrases such as "where possible", "as appropriate", "as needed", and "if necessary", and filler words such as "simply", "just", "easily", and "obviously".
- "TBD" and every placeholder like it must not appear. The one legal way to record an unknown is `[NEEDS CLARIFICATION: <the question>]`.
- Every date must be written in the ISO 8601 form YYYY-MM-DD.

### Names and Markdown

- Every concept must go by the one name its glossary entry gives it, on every page.
- A page is written in CommonMark plus the GitHub extensions, tables, task lists, strikethrough, and autolinks, and exactly two Obsidian forms, wikilinks and callouts.
- A callout must use one of the five kinds GitHub renders, note, tip, important, warning, and caution, with no custom title.
- An Obsidian embed of a page or a section must not appear. An image uses the CommonMark form `![alt](path)`.
- Raw HTML must not appear, because Obsidian and GitHub render it differently.

## Why it exists

The vault is read cold, months later. Hedged wording or two names for one concept cost every reader a translation, and an obligation in soft wording lets the wrong behavior ship.

## What it applies to

Every markdown page inside `{knowledge}/` and `.colony/rules/`, the root pages `README.md` and `AGENTS.md`, and every human and agent who writes one. The definitions for [[prd]], [[one-pager]], [[glossary-entry]], [[research-report]], [[decision-record]], [[design-spec]], [[source]], and [[rule]] add a stricter standard.

## What is exempt

- The body of a [[source]] page, the page budget included, because it is outside material frozen at capture.
- Quoted material on any page, interface strings in a [[design-spec]] among it, because a quotation reproduces its origin exactly.
- The page budget of a [[build-checklist]], because one build's list can outgrow it and splitting it hides where the build stands.
- A page under `{knowledge}/archive/`, because it is frozen history.
- Outside material copied into the repository whole, such as a vendored license or a third-party skill, because it is not the repository's own writing.
- Code blocks and frontmatter, apart from the frontmatter `description`, which is prose.

## How it is enforced

`colony check-docs` checks the page size caps and refuses a paragraph copied from another page, in the mode the repository sets. Human review in the pull request reads for the mechanical items, the banned words, dates, wordplay, and metaphor, checks force words, and flags each sentence read twice.
