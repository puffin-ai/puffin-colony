---
name: resolving-merge-conflicts
description: Resolve a merge or rebase that stopped on conflicts, keeping both sides' intent. Use when git reports a conflict on your branch, or when the lead's line asks you to merge another branch into yours and resolve it.
---

# Resolving merge conflicts

1. **See the state.** Run `git status` to see whether a merge or a rebase is under way and which files conflict, and `git log --oneline --graph -20` to see the two lines of history.
2. **Find why each side changed.** For each conflicting hunk, read the commits behind both sides (`git log -p <side> -- <file>`), and the cards they belong to. Know what each change was for before you touch it.
3. **Resolve each hunk.** Keep both intents where they fit together. Where they can't, keep the one the merge is for, and note the trade-off in the commit message. Invent no new behavior.
4. **Rebuild generated files.** For a file the build writes, listed under `generated` in `.colony/colony.toml`, take either side, then run its `regen` command. Never merge a generated file by hand.
5. **Run the checks.** Run the fast check, and the tests of every file that conflicted. Fix what the merge broke.
6. **Finish.** Stage the files and commit, or run `git rebase --continue` until every commit is applied. Push your branch, and post `done` again on the card with the fast check's last line.

On your own branch, finish the merge; don't abort it. The lead's batch worktree is the one place that aborts a merge, because the lead hands the conflict to the builder who owns the branch.
