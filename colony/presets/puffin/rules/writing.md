# Writing

Applies to every Markdown page in this repository: the docs, the READMEs, every `AGENTS.md` and `CLAUDE.md`, the rules in `.colony/rules/`, and every person and agent who writes one. Commit messages and PR descriptions follow it too.

## What the rule is

Every page is written in plain language under ISO 24495-1, so a cold reader understands it on first read and can act on it.

### Sentences

The sentence rules come from the US Federal Plain Language Guidelines, with the paragraph cap from ASD-STE100.

- The writer must use the active voice and name who acts. The actor must be a person or a named part of the system.
- "you" must address the reader of the page, the person or agent building the product.
- The writer must call the person the product serves "the user", in the third person, never "you", and by no other name.
- The writer must not hide a verb inside a noun, so "the user accepts it" never becomes "the user's acceptance".
- The writer must use the present tense unless the sentence reports a past event.
- The writer must put one idea in each sentence and choose the everyday word over the formal one.
- The writer must explain a technical term where it first appears or link its glossary entry.
- The writer must not use wordplay, puns, clever phrasing, or metaphor, apart from a term the repository defines, used with its defined meaning.
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
- A second page that needs the same explanation must link to the section and must not repeat it.
- The writer must merge a page whose whole content fits in one paragraph back into the page it belongs to.

### Force words

The force words come from BCP 14, in lowercase.

- A sentence that states an obligation must carry exactly one of must, should, or can, and no other word, so "shall", "ought to", and "needs to" never appear.
- "must" names the only acceptable way, "should" names the default, and "can" names a free choice. A writer who departs from a "should" must state the reason.

### Fact and judgment

The split comes from Diátaxis.

- A sentence that states settled fact must state it plainly, with no hedge, and a sentence that carries judgment must be marked as judgment by its section or its wording. One sentence must not mix the two.
- A page that argues a call must use full sentences, and every bullet on it must carry a complete sentence.

### Mechanical items

- The writer must not use a semicolon or an em dash in prose. Both stay where a name or syntax requires them.
- The banned words of ISO/IEC/IEEE 29148 and INCOSE must not appear: "and/or", "etc." and open-ended phrases such as "including but not limited to", escape phrases such as "where possible", "as appropriate", "as needed", and "if necessary", and filler words such as "simply", "just", "easily", and "obviously".
- "TBD" and every placeholder like it must not appear. The one legal way to record an unknown is `[NEEDS CLARIFICATION: <the question>]`.
- Every date must be written in the ISO 8601 form YYYY-MM-DD.

### Names and Markdown

- Every concept must go by one name on every page, the one its glossary entry gives it when the repository keeps a glossary.
- A page is written in CommonMark plus the GitHub extensions: tables, task lists, strikethrough, autolinks, and callouts.
- A callout must use one of the five kinds GitHub renders, note, tip, important, warning, and caution, with no custom title.
- An image uses the CommonMark form `![alt](path)`.
- Raw HTML must not appear, because editors and GitHub render it differently.

## Why it exists

Pages are read cold, months later. Hedged wording or two names for one concept cost every reader a translation, and an obligation in soft wording lets the wrong behavior ship.

## What is exempt

- Quoted material on any page, interface strings among it, because a quotation reproduces its origin exactly.
- Outside material copied into the repository whole, such as a vendored license or a third-party skill.
- A page kept only as frozen history, such as an archived decision.
- Code blocks and frontmatter, apart from a frontmatter `description`, which is prose.
