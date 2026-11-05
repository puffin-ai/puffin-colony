---
type: type-definition
created: 2026-11-05
description: How to write a decision record. Read before recording one accepted call.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Decision record

A decision record captures one call that has been made, the situation that forced it, what the call costs, and the condition that would make you look at it again. Write one when a choice is settled and a reader six months from now would otherwise ask "why is it like this?" The call can be technical or product. If the question is still open, or you are gathering evidence, this is not the page yet. Routing test: if you can write the call as one sentence starting "We will" and you are not going to change it next week, write a decision record.

## Send it elsewhere when

- The choice is whether to build a feature at all. That is a [[one-pager]].
- You are describing what a feature does for a user. That is a [[prd]].
- You are describing how something is built, part by part. That is a [[tech-design]].
- You are drawing how whole systems fit together. That is an [[architecture]] page.
- You are still gathering evidence and no call has been made. That is a [[research-report]].
- You are defining what a word means in {product}. That is a [[glossary-entry]].

## Frontmatter

```yaml
type: decision-record
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
```

## Skeleton

- `# <Title>` The call itself in present tense, under 50 characters, not a topic and not a question.
- `## Context` The situation that forced the call, told as a short narrative in full paragraphs, then three link lists, each present only when it has entries. Each line is a wikilink, a colon, then how that page connects to this record, never a description of what the linked page is. No options and no arguing for the winner.
  - `### The decisions that bind` One line per earlier decision record this call builds on.
  - `### The research behind it` One line per research report whose findings fed the call.
  - `### Related designs` One line per page that carries this decision onward.
- `## The decision` One sentence, bold, active voice, starting "We will".
- `## Why` The reasons the chosen option won, one reason per bullet, strongest first, each a complete argument from the evidence.
- `## Alternatives considered` Every option you weighed and rejected, each with the specific trade-off that ruled it out.
- `## Consequences` Two bulleted lists under the labels "What this makes easier:" and "What this makes harder:". Both are required.
- `## Reopen if` One condition in the form `Reopen if: <condition>`. The word "never" is a legal condition.

## Rules

- One page must hold exactly one decision, and a page holding two must be split.
- The record must sit in the wiki folder of the area it decides, beside the pages it decides, and that folder's readme must list it, under [[authority#Finding a decision]].
- The title and the frontmatter `description` must each state the call, because a reader finds a decision by its title in the area readme and the decision log, and by its description in a search.
- The decision sentence must be bold, one sentence, and must not hedge or offer a menu.
- The page must be written in full sentences under the [[writing]] rule, and a bullet must carry a complete sentence, never a fragment.
- An accepted record's substance must never change, and a changed mind must become a new record. A format-only revision is legal, and it changes no meaning, no decision, and no date.
- When a record is replaced, the old page must stay, must open with a line naming its replacement and linking it, and the new page must name what it replaces.
- Every rejected option must sit under alternatives considered and carry the specific trade-off that ruled it out.
- The argument for the winner must sit under why, never under context or consequences.
- The writer must write the context as a short narrative followed by the link lists, and the alternatives as a bulleted list with one option per bullet.
- The writer must write the why as bullets, one reason each, strongest first.
- Every concept with a page must be linked where it is named.
- The reopen trigger must name a condition a reader can check, or the single word "never".
- The page must not use any status word in its body, because frontmatter carries the only status vocabulary.

## Before you publish

- Does the decision read as one bold sentence starting "We will"?
- Does the context carry its link lists, with every line stating a connection rather than describing the linked page?
- Does every rejected option sit under alternatives considered with the trade-off that ruled it out?
- Does the why section argue from the evidence in bullets, one reason each, strongest first?
- Are the consequences two labeled lists, with at least one entry under what this makes harder?
- Does the reopen trigger name a checkable condition, or say "never"?
- If this replaces an earlier record, do both pages link to each other and does the old one open with the line naming its replacement?

## Background

We follow the architecture decision record described by Michael Nygard in 2011: context, decision, consequences, kept short and rigidly named. Those three parts are enough for a reader six months later to reconstruct the call. We generalize it beyond architecture, so a product call uses the same page. We drop Nygard's in-body status line, because the frontmatter carries the only status vocabulary and a second one in the body would drift from it.

We add three sections Nygard does not have. The why section holds the argument for the winning option, so the context stays a description of the situation and the decision stays one sentence. The alternatives section holds every rejected option with the trade-off that ruled it out. The reopen trigger keeps a settled question settled until a named condition fires. The vault also adds fixed structure inside the sections: link lists in the context, one reason per bullet in the why, and labeled lists in the consequences, because agents retrieve sections alone and a list survives retrieval better than a paragraph.

We also adopt Nygard's writing instructions as he states them: the record runs one or two pages of full sentences in paragraphs, written as a conversation with a future developer, and bullets appear only for visual style, never as an excuse for sentence fragments.
