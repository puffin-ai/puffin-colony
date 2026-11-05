---
type: type-definition
created: 2026-11-05
description: How to write a glossary entry. Read before defining a term in {product}'s vocabulary.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Glossary entry

A glossary entry defines one term in {product}'s vocabulary. It is the page every other page links to when it uses that word, and it holds the term's meaning. Each core noun of the product gets one. Write one when a word already appears in more than one place and readers need a single agreed meaning for it. The routing test is this: if the page answers "what does this word mean in {product}," it is a glossary entry.

## Send it elsewhere when

- The page describes what a feature does for a user and why we are building it. Write a [[prd]].
- The page describes how the thing is built, stored, or computed. Write a [[tech-design]].
- The page argues one accepted call and its consequences. Write a [[decision-record]].
- The page reports what an investigation found. Write a [[research-report]].
- The page only lists links to other pages in its folder. Write a [[readme-page]].
- The page states a rule about the vault itself rather than about the product. Write a [[rule]].

## Frontmatter

```yaml
type: glossary-entry
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD   # set only by a verification pass, never by hand
```

## Skeleton

- **Parent line.** A link to the page above, alone on the first line.
- **Title.** The term itself, in its normal product form. No "About" and no "overview."
- **Definition.** One complete sentence, before any other text, with the term as its subject: the term, then the nearest broader concept, then what sets this term apart, written so the words after the verb could replace the term in a sentence.
- **Properties.** One section headed Properties, holding two to eight bullets, present once the term's area has settled properties and absent until then. Each bullet opens with a short bold claim that states one rule about the term, followed by at most two sentences that carry that rule and nothing else. Detail belongs to the page type that owns it, reached by link.
- **Optional relationship diagram.** Inside Properties, after its bullets, one diagram may explain the term's relationships to sibling concepts. It follows [[diagrams]] and carries its introduction, prose explanation, and legend. A small membership table may state the same relationships in text.
- **Related line.** Links to sibling terms, with no commentary.

## Rules

- The definition must be one complete sentence whose subject is the term, naming the nearest broader concept and what sets the term apart, and it must not describe a screen, a step, or a plan.
- The definition must not open with "refers to" or "is a word for", because the page defines the thing rather than the word.
- The definition must not contain the term it defines, and two entries must not define each other in a circle.
- A word gets an entry only when {product} gives it a meaning the dictionary does not, so a common word gets no entry.
- Each bullet under Properties must carry exactly one rule about the term, and its bold claim must state that rule.
- A bullet's claim must name its subject rather than open with a pronoun, so "It never expires" becomes "A session never expires", because a bullet is read alone and a pronoun then points at nothing.
- An entry carries a Properties section only when its area has settled properties, and that section must hold between two and eight bullets, because a term that needs more than eight is really two terms. Until then the entry is the definition and the Related line.
- You must not coin a new name for an existing concept, as the [[writing]] rule requires, and you must ask the owner before naming anything new.
- A term must have exactly one glossary entry, and other pages must link to it rather than restate it.
- Behavior, lifecycle, and procedure belong to a PRD, a design spec, or a decision record, and an entry must link them there rather than state them.
- The page must not name a technology, a database, a screen layout, or a release date.
- A relationship diagram and its table must explain settled category membership only. Behavior, lifecycle, and procedure belong on their owning pages.

## Before you publish

- Is the definition one complete sentence whose subject is the term, and do the words after the verb pass the substitution test, replacing the term in a sentence without changing what the sentence says?
- Does every bullet's claim state one rule and name its own subject, with none opening on a pronoun?
- Is every named concept a live link to its own entry, with nothing defined twice?
- Have you checked that no existing term already means this, so you have coined no synonym?
- Is the definition free of the term it defines?

## Background

The convention is the domain glossary, from the ubiquitous language practice in domain-driven design. Ubiquitous language means the team, the documents, and the code all use the same word for the same thing. We adopt the core of it: one term, one page, one definition, and no second name for a concept that already has one. Every other page links the entry, so a second name or a second page would split the vocabulary. We drop the single alphabetical file, because our terms carry rules and need room. We also drop the code-mapping column, because that belongs in a tech design.

The definition itself follows ISO 704, the terminology standard, for what it must contain. A definition names the nearest broader concept, then the features that set this term apart from its neighbors, and it is written so it could replace the term in a running sentence. We take three working rules from it: the definition must not contain the term it defines, it carries no requirement, and no two definitions lean on each other in a circle.

We do not take its shape from the ISO and IEC Directives Part 2. Those rules strip the article, the verb, and the closing period, because a standard prints the term on the line above its definition and the reader has it in view. A vault page is retrieved and read alone, so a definition with no subject and no verb names nothing, which the [[writing]] rule already forbids. The shape comes instead from the full-sentence definition the COBUILD dictionaries introduced in 1987, the form Wikipedia's lead sentence, the GitHub glossary, and the Kubernetes glossary all use: the term is the subject of one complete sentence that says what it is.
