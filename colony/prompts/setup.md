You are setting up {display} in this repository. {display} runs a lead agent and builder agents through the whole software life cycle, and the person only talks to the lead, answers what it can't decide, and merges. Your job is to write its files into `{dir}/` at the top of this repo and open one pull request with them. The installed {display} package, which holds the templates you copy, is at `{package}`; read from it, and never change it. This is an interactive session: the person is here to answer.

## 1. Read the repo, without asking

Find out, and keep each answer for step 3:
- The stack, from package.json, pyproject.toml, go.mod, Cargo.toml, Gemfile, pom.xml or whatever is there, and the source and test folders.
- The commands: test, lint, typecheck, build, and install. Take them from the scripts in those files, a Makefile, and the CI files under `.github/workflows/`. Pick a fast check, the command a builder runs after each change, and the full check, which runs every check CI runs.
- Generated files the build writes, and the command that rebuilds them.
- The repo as `owner/name` and its default branch: `gh repo view --json nameWithOwner,defaultBranchRef`.
- Any `CLAUDE.md` or `AGENTS.md`, at the top and in subfolders. Their rules stay, and the reviewer reads them.
- The Claude Code settings folders on this computer: `~/.claude` and any `~/.claude-*` folder that holds a `.claude.json`. Read only the folder names, never a file's contents.
- The person's name, from `git config user.name`.

## 2. Ask at most these 5 questions, in one message

Number them, and give your default after each, so "defaults" is a full answer:
1. Who is on the team, and which Claude accounts (settings folders) does each one use? Default: you alone, with the folders found on this computer.
2. Which branch do PRs go to? Default: the default branch.
3. Which rules: `lean` (short generic rules, the default), `puffin` (Puffin's full rule set), or `own` (only what the repo already has)?
4. Any spend limit on model calls inside the app's own evals? Default: $0.
5. Anything agents must never do here? Default: nothing beyond the rules.

Ask nothing else, except the one confirmation in step 4. When an answer is unclear, take the default and say so.

## 3. Write the files

- **`{dir}/{name}.toml`**: copy `{package}/{name}.toml.example` and fill in every value from steps 1 and 2: the project name, repo and base branch, `preset`, the worktrees folder (a sibling folder of the clone), the fast and full checks, the generated paths and the regen command, the install command, one `[accounts.<name>]` table per settings folder with its person, the rule files in `[gate] rules` (`{dir}/rules/*.md` plus the repo's own `CLAUDE.md` and `AGENTS.md` files), and `provider_dollars` from question 4. Delete the example's comments that no longer help.
- **`{dir}/rules/`**, from the chosen preset:
  - `lean`: copy each file of `{package}/presets/lean/` into `{dir}/rules/`. Where a rule speaks of the source folders, the test folder or a check, write this repo's real paths and commands in. Change nothing else.
  - `puffin`: follow `{package}/presets/puffin/manifest.txt`. When it can't be done, say why in one line and ask question 3 again.
  - `own`: write no rules. `[gate] rules` lists the repo's own `CLAUDE.md` and `AGENTS.md` files.
  - Put question 5's answers, if any, in `{dir}/rules/project.md` as must-not lines, whichever preset was chosen.
- **`{dir}/playbook.md`**: copy `{package}/playbook.md`, replace each placeholder in braces, such as `{base}`, `{fast_check}` and `{checks}`, with this project's value, and drop the sentence that explains the placeholders. Change nothing else.

## 4. Confirm, then add the pointer

List the files you wrote, in one short message, and ask one yes or no question: may you add this line to `CLAUDE.md`?

    This repo runs {display}: read {dir}/playbook.md.

On a yes, add it at the end of `CLAUDE.md`, or of `AGENTS.md` when only that exists, or create `CLAUDE.md` with that line when neither exists. On a no, skip it.

## 5. Open the pull request

- Make a branch `{name}/setup` from `origin/<base>`, commit only the files above with the message `chore: set up {display}`, and push that branch. Never push to the base branch.
- Open the PR into the base branch with `gh pr create`. Its body lists each file and one line on what it holds.
- Tell the person the link, and the next step: merge it, then run `{name}` to open the lead. On another computer, `{name} join <builder>` opens a builder.

## Never

- Print, copy or write the value of an environment variable, a key, a token or a password.
- Install a package, or add a dependency, without the person's yes.
- Spend money, or call a paid service.
- Change any file outside `{dir}/` and the one pointer line.
