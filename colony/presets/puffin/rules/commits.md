# Commits

Applies to every git commit in this repository, and to everyone who writes one, person or agent. The reviewer checks each line against the batch's commits.

## Every commit

- A commit must hold one logical change, and one whose description grows long must be split.
- The subject must be in the imperative present tense, passing the test sentence "If applied, this commit will *the subject*."
- The subject should stay near 50 characters and must not pass 72.
- The subject must not end with a period, and its text after the prefix must stay lowercase, apart from names that carry their own case.
- A blank line must separate the subject, the body, and the trailer block.
- The body must state why the change was made, and a commit whose reason is plain from its subject can carry no body.
- The body must wrap at 72 columns.
- The subject and the body must follow the writing rule, `writing.md`.
- Trailers must sit alone in the final paragraph, because git's trailer parser drops every trailer in a paragraph mixed with prose.
- A commit an agent helped produce must carry `Assisted-by: <agent>:<model>`, such as `Assisted-by: claude-code:claude-opus-5-5`.
- `Co-authored-by` must name only a person.
- An agent can commit and push only the work the person has authorized, under the person's git identity.
- No commit carries `Signed-off-by` unless the repository adopts the Developer Certificate of Origin, and then every commit carries it.

## The subject line

- The subject must follow Conventional Commits 1.0.0: a type, an optional scope in parentheses, `!` for a breaking change, then a colon, a space, and the description.
- The type must come from commitlint's closed list: build, chore, ci, docs, feat, fix, perf, refactor, revert, style, test.
- A scope must be a noun from the list in the repository's commitlint configuration, when it has one, and a commit that crosses scopes carries none.
- A breaking change must carry both the `!` and a `BREAKING CHANGE: <description>` footer.
- Release automation must pin the `conventionalcommits` parser preset, because the default preset cannot read `!`.
- A pull request that squash-merges must carry a title that obeys the subject rules.

## Why it exists

The message is the only record of why the repository changed that survives every refactor, and studies at ICSE in 2022 and 2023 tied messages that skip the why to defect-prone files. A header can stand in for substance, so this rule puts the burden on the body.

## What is exempt

- Messages git generates. A merge commit keeps git's subject, and a revert keeps git's `Revert "<subject>"` form plus one sentence saying why.
