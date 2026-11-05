---
name: code-review
description: Review a diff against a fixed point on two separate axes, the repo's standards and the card or spec it implements. Use when you check your own branch before posting done, when someone asks to review a branch, a pull request or work in progress outside colony batch, or when they say review since a commit.
---

# Code review

Two axes, kept apart:

- **Standards**: does the diff follow this repo's written rules?
- **Spec**: does the diff do what its card or spec asked for, and only that?

A change can pass one and fail the other: code that follows every rule but builds the wrong thing, or code that does exactly what the card asked but breaks the repo's conventions. Reporting them apart stops one from hiding the other. A batch's fresh review is the `colony-reviewer` skill's job; this one is for a review before that.

## 1. Pin the fixed point

Use the commit, branch or tag you were given, else `origin/<base>`. Check it resolves with `git rev-parse <point>`, and that `git diff <point>...HEAD` is not empty; stop here on a bad ref or an empty diff. Note the commits with `git log <point>..HEAD --oneline`.

## 2. Find the spec

In order: the card the branch belongs to (`gh issue view <n>`), issue numbers in the commit messages, a spec page the card links, or a path you were given. With none, the Spec axis reports "no spec available".

## 3. Find the standards

`.colony/core.md`, the `AGENTS.md` of each folder the diff touches, the rules in `.colony/rules/` that the diff's subject names, and any other written standard in the repo. On top of them, always check the smell baseline below. The repo's written rule wins over a smell, and each smell is a judgement call, never a hard violation. Skip anything a linter or type checker already enforces.

- **Mysterious name**: a name that doesn't say what the thing holds or does. Rename it; if no honest name comes, the design is unclear.
- **Duplicated code**: the same logic in two hunks or files. Pull out the shared shape and call it from both.
- **Feature envy**: a function that reaches into another object's data more than its own. Move it onto that data.
- **Data clumps**: the same few fields travelling together. Make them one type.
- **Primitive obsession**: a string or number standing in for a domain idea. Give the idea its own small type.
- **Repeated switches**: the same branch on the same type in several places. Use one map or one polymorphic call.
- **Shotgun surgery**: one change forces edits across many files. Gather what changes together.
- **Divergent change**: one module edited for several unrelated reasons. Split it.
- **Speculative generality**: options, parameters or hooks the spec doesn't need. Delete them.
- **Message chains**: `a.b().c().d()` that the caller shouldn't depend on. Hide the walk behind one call.
- **Middle man**: a layer that only passes calls on. Call the real target.
- **Refused bequest**: a subclass that ignores most of what it inherits. Use composition.

## 4. Review each axis on its own

Do the Standards pass, then the Spec pass, each from a fresh read of the diff.

- **Standards**: each place the diff breaks a written rule, citing the file and the rule, and each smell you see, named and quoted. Mark which are hard violations and which are judgement calls.
- **Spec**: each requirement that is missing or partial, each behavior nobody asked for, and each requirement that looks built but wrong, quoting the spec line for each.

Keep each report under 400 words.

## 5. Report

Put the two reports under `## Standards` and `## Spec`, as written. Don't merge or rerank findings across the axes. End with one line: the number of findings on each axis and the worst one within each. Fix a hard violation on your own branch before you post done; send a judgement call you disagree with to the lead as a question with your default.
