# Git

Applies to every branch, commit and pull request.

## Must

- Make each card's change on its own branch, `<builder>/<card number>`, in its own worktree, cut from the latest `origin/<base>`.
- Commit in small steps that each build and pass the fast check.
- Write each commit message as `type(scope): what changed`, with a type such as `feat`, `fix`, `refactor`, `test`, `docs` or `chore`, and a body that says why when the title can't.
- Push only your own branch, and post one `done` line on the card after the push.
- Merge `origin/<base>` into your branch, or the branch another builder names, when the lead asks, resolve the conflict, and push again.
- Keep generated files out of a hand merge: take one side, then run the command that rebuilds them.
- Write each pull request description with what changed, why, how it was tested, and anything the reviewer should look at first.
- Open one pull request per batch into the base branch, and leave the merge to the person.

## Must not

- Push to the base branch, or merge into it.
- Force-push a branch someone else has built on.
- Rewrite history that is already pushed, except on your own branch before anyone uses it.
- Commit a secret, an `.env` file, a build output, or a file the card didn't change.
- Delete a branch, a tag or a worktree that isn't yours.
- Skip a hook or a check with `--no-verify`.
