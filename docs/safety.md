# Safety

Colony gives agents real work in your repo. They read code, run commands, start your stack, commit and push. This page says what Colony never does, what its agents ask you first, and what you should know before your first batch.

Some guarantees are locks in Colony's code. Others are rules the agents follow. This page keeps the two apart.

## Locks in the code

- **It never pushes to your base branch.** A batch makes one push, naming its own branch in full: `refs/heads/<project>/batch-<name>`. It refuses to push any branch that is the base branch or doesn't start with `<project>/batch-`. Fixers commit and never push. Setup pushes only `colony/setup`.
- **It never prints env values.** `--dry-run` prints the names of the variables it would set, never their values. The values in `check_env_file` go only into the checks' environment.
- **The gate's agents never bill an API key.** The reviewer, walker and fixers run with `ANTHROPIC_API_KEY` removed from their environment, so they always run on your Claude Code login.
- **Your checks get no provider keys at a zero budget.** While `provider_dollars` is 0, the checks run without `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`, so your app's own evals can't spend.
- **A batch can't loop for ever.** It stops after `max_rounds`, when the checks fail the same way twice in a row, when a fixer commits nothing, or when an agent fails twice.
- **Removed tests are shown.** The PR body lists every test file the batch deletes, so a test can't vanish without you seeing it.
- **Setup reads settings folders by name only.** It never reads the files inside them.

## Rules the agents follow: the stop list

No agent does these without your yes:

- spend money: paid services, or model calls above the budget;
- show, copy or move a secret: keys, tokens, passwords, `.env` values;
- delete data: databases, issues, or files and branches that aren't its own;
- add, remove or upgrade a dependency;
- merge into the base branch, or push to it.

A builder that meets one sends it to the lead as a question. Only the lead asks you, in one short question with its own pick as the default.

The stop list lives in `.colony/playbook.md`, and the `lean` rules repeat it. These are instructions, not locks: a model can still get one wrong. The locks above, and the second locks below, are there for that case.

## What the agents can do

- **The reviewer, walker and fixers** run headless with `claude -p --permission-mode auto`. That is Claude Code's auto mode, where a classifier approves or blocks each action instead of asking you. Each works in its own worktree. The reviewer is told to change nothing, the walker to leave the batch's worktree alone, and fixers not to push.
- **The lead and builders** run interactive, under your own Claude Code permission settings. They ask what your settings say to ask. They inherit the shell you start `colony` from.
- **Every lead and builder starts with Remote Control**, under a title such as `myapp-lead`, so you can follow it from your Claude account.

## Second locks you should add

- **Protect your base branch on GitHub.** Require a pull request and a review. Then even a mistaken push is refused.
- **Start `colony` from a shell without `ANTHROPIC_API_KEY`,** so the lead and builders use your login too.
- **Keep `.env` files and `check_env_file` out of git.**
- **Run `--dry-run` first,** for setup and for your first batch.
- **Read the PR's "Removed tests" section** before you merge.

## What leaves your machine

- **Code and prompts go to Anthropic,** the same as in any Claude Code session.
- **Cards, lines and PRs go to your GitHub repo.** On a public repo they are public, so keep secrets and personal data out of them.
- **The batch reports are committed** to the batch branch: the review, walk and check summaries, the minutes and the PR body. The raw logs stay local.
- **Context7,** when you accept it, sends library lookups to its service. Playwright runs on your machine.

## Accounts

Colony uses your Claude Code login. Most teams list one account per person in `colony.toml`. Spreading one person's work across several seats may conflict with [Anthropic's terms](https://www.anthropic.com/legal), so check them before you list more than one for yourself.
