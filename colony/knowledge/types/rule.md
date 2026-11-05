---
type: type-definition
created: 2026-11-05
description: How to write a rule page. Read before adding a vault rule or restructuring one.
assisted-by: claude-code:claude-fable-5
enforced-by: colony check-docs for the code paths a rule names and the rule budget, human review in the pull request
---

# Rule

A rule page states one rule area of the vault. It says what the rule is, why it exists in terms of what breaks when the rule is broken, and what enforces it. Write one when the same instruction has to hold across many pages and many writing sessions, so it needs one home that every other page links to instead of restating. A rule page governs how the vault works. Routing test: if the page tells a writer or an agent how to work inside this vault, it is a rule, and if it tells a reader something true about {product}, it belongs on a product page instead.

## Send it elsewhere when

- The page records one call that was made once, with its context and its reopen trigger. That is a [[decision-record]]. A decision freezes on the day it is accepted. A rule stays current by being edited.
- The page defines what a {product} term means. That is a [[glossary-entry]], because it is a fact about the product.
- The page only points a reader at other pages in a folder. That is a [[readme-page]], which carries navigation and no requirements.
- The page describes how a system is built or how a feature behaves. That is [[architecture]], [[tech-design]], [[prd]], or [[design-spec]], all of which describe the product rather than the vault.

## Frontmatter

```yaml
type: rule
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD   # set only by a verification pass, never by hand
enforced-by: human review in the pull request   # the human gate, or a script named by path
paths:   # present only on a slice, one quoted glob per line
  - "**/{apps}/**/tests/**"
reviewed-against:   # present only on a rule tied to a framework's behavior, one quoted stamp per line
  - "next@16.4"
```

## Skeleton

- **Title.** The area the rule governs as a plain noun phrase, such as "Naming and links". Never the rule sentence, never a question.
- **What the rule is.** The requirements, one per sentence, each naming who acts and ending on something a reviewer can check.
- **Why it exists.** The cost of breaking the rule, in plain words, in two or three sentences.
- **What it applies to.** The files, folders, or people the rule reaches, written as facts that carry no force of their own.
- **What is exempt.** Every case the rule deliberately does not cover, each with its reason. Write "none" when there are none.
- **How it is enforced.** The named script that checks it, or the named human gate that catches it. Name what runs today.

## Rules

- Each rule area must live on exactly one page, and every other page must link to that page instead of restating the rule.
- The root `AGENTS.md` and each area `AGENTS.md` are the one exception: each can state a rule line in one sentence that links the line's home, because an agent reads those files before any rule page loads.
- Every requirement sentence must name who acts and end on an outcome a reviewer can check.
- The page must state the cost of breaking the rule, because a rule with no stated cost gets treated as taste.
- The page must name an enforcer, either a script by path or a human gate by name, and must not name a check that does not exist yet.
- The writer must name in a code span only a repository path that exists, and must fix every such path a move breaks, because a rule that names a moved file binds nothing. `colony check-docs` warns on a path that is gone.
- The page must not contain product facts, and product pages must not contain vault rules.
- Escape phrases must not appear, as the [[writing]] rule requires, and "generally" is banned on rule pages as well, because an escape phrase cannot be checked.
- The writer must change a rule by editing its page, never by adding a second page about the same area.
- The writer must keep the rules within the rule budget `colony check-docs` sets, because every line an agent loads costs it time on every task.
- Every rule page must itself obey every rule the rules folder states.

## Slices

A slice is a rule page whose frontmatter lists `paths`, the globs of the files it governs. Claude Code loads a slice into a session when the agent reads or edits a file one of its globs matches, through the slice's link in `.claude/rules/`. A rule page with no `paths` loads only through a link to it.

- The writer must give a rule page `paths` when the rule governs files that its globs can name.
- The writer must write each glob on its own line, in double quotes, starting with `**/`, so the glob matches the same file in a worktree that sits inside the main checkout.
- Each glob must match at least one file, because a glob that matches nothing drops its rule from the folder it was meant for without a sound.
- The writer must link every slice from `.claude/rules/` with a relative symbolic link of the same name, such as `.claude/rules/testing.md` pointing at `../../.colony/rules/testing.md`, and must never copy a slice's text there, because one rule keeps one home.
- A slice should stay under 25,000 characters, because Claude Code loads it whole on every matching read.
- The writer must keep every frontmatter value of a slice free of a colon followed by a space, because Claude Code then reads no frontmatter and loads the slice in every session.

## Framework stamps

A framework stamp records the version of a package a rule's text was last checked against, so a framework upgrade that changes the behavior the rule describes lets review catch the old line before it misleads an agent.

- The writer must give a rule a `reviewed-against` field when the rule states a decision tied to a framework's behavior, with one stamp for each such package.
- Each stamp must read `package@major.minor` when the rule cites a minor version, and `package@major` when it cites only a major.
- The writer must quote each stamp, because a package name that starts with `@` breaks the frontmatter unquoted.
- A writer who moves a stamp must first read the package's upgrade guide and update every line of the rule the new version changes.
- The reviewer must refuse a stamp in neither form, and must flag a stamp whose package no manifest installs, an installed major past the stamp, and an installed minor past a stamp that cites a minor.

## Before you publish

- Does every requirement name who acts and end on a checkable outcome?
- Does the page state the cost of breaking the rule in plain words?
- Does the page name a script by path or a human gate by name that enforces it today?
- Is this the only page in the vault that states this rule area?
- Does this page obey every rule the rules folder states, including its own?

## Background

Rule pages follow the W3C QA Framework specification guidelines for shape, and BCP 14 (RFC 2119 with RFC 8174) for force words. From the QA Framework we adopt four things, because together they let a reviewer check a rule instead of interpreting it: state the scope, name what has to conform, write every requirement in one consistent form, and end by naming the check. From BCP 14 we adopt the three levels of obligation and drop the uppercase spellings, because the [[writing]] rule already reserves the plain lowercase words must, should, and can for that purpose. We drop the QA Framework's conformance-clause machinery, because a vault with one maintainer does not need formal conformance classes.
