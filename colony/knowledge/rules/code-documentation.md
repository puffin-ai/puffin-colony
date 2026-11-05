---
type: rule
created: 2026-11-05
description: How code is documented in every app, covering docstrings, comments, TODOs, and suppression comments, with the runtime rules for endpoint docstrings and a model's tool descriptions. Read before documenting code or reviewing its documentation.
assisted-by: claude-code:claude-fable-5
enforced-by: the repository's linters and type checkers where configured, colony suppressions for suppression comments, human review in code review
paths:
  - "**/{apps}/**"
---

# Code documentation

## What the rule is

Code documentation can be runtime data as well as documentation: a web framework can publish an endpoint's docstring in its API description, and a model reads a tool's description as part of its prompt. A mistake there changes what the API publishes or what the model is told.

- The implementer must add a comment only for what the code cannot say, and must change a comment in the same commit as the code it describes.
- The implementer must not commit commented-out code.
- The implementer must write every TODO as a colon, an issue link, and a description.
- The implementer must name the specific rule in every suppression comment, and the reason when the language's form carries one.
- The implementer must not add a comment that marks code as departing from the wiki. The batch's docs commit changes the wiki page the code departs from, under [[docs-life-cycle#The batch's docs commit]].
- The reviewer must not approve a change carrying a TODO without an issue link, a blanket noqa, or a blanket type-ignore.

### In a Python app

- The implementer must document every public class, method, and function with a Google-convention docstring written as prose, with every type in the annotation and none repeated in the docstring.
- The implementer of an endpoint in a framework that publishes docstrings, such as FastAPI, must write its docstring as user-facing Markdown for the API page, with parameter documentation on the field declarations, never in an Args section that would leak as raw text.

### For a model's tools

- The implementer must give every tool a model can call an authored description and a description on every field of its argument model, and must not let a tool's text come from a function docstring, because a docstring written for people is not written for the model.
- The implementer must ship an edit of a tool's description as its own change, because it changes what the model is told and invalidates any cached prompt prefix that holds it.

### In a TypeScript or JavaScript app

- The implementer must document every exported function and type of a reusable module with a comment stating what it does and what it takes.
- The implementer must document nothing the types already say.
- The implementer must name the rule and the reason in every suppression comment, so a lint ignore names its rule and a `@ts-expect-error` states why.

## Why it exists

A wrong docstring is worse than none, measured directly on model behavior, and a stale comment raises the near-term bug risk of the change that left it stale. Where documentation is runtime data, a documentation mistake is also a product mistake, because it changes what the model is told and what the API publishes.

## What it applies to

Every docstring, comment, TODO, and suppression comment under `{apps}/`, and every human and agent who writes or reviews one. The docstring rules bind Python code, and the tool rules bind code that hands tools to a model.

## What is exempt

- Test code carries no mandatory docstrings, and the suppression and commented-out-code requirements still bind it.
- Modules, packages, magic methods, and init methods carry no mandatory docstring.
- Generated code and migration files, reviewed for effect rather than form.

## How it is enforced

The repository's linters enforce what they are configured for: in a Python app, ruff's pydocstyle family with the google convention for docstrings, its TD family for the TODO form, its ERA family for commented-out code, and its PGH family for blanket suppressions, with the type checker reporting an ignore comment that does nothing. In a TypeScript app, the linter refuses an ignore comment with no reason, and the compiler refuses an expect-error comment that suppresses nothing. `colony suppressions` refuses a file whose suppression comments grow past its recorded count. Human review in code review checks the same-commit comment requirement, the endpoint docstrings, the tool descriptions, and the own-change rule for edits of a tool's description.
