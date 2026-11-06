# FAQ

## Questions

**Does it need many Claude accounts?**
No. It uses yours. One account runs the lead, the builders, the gate, the spec agent and the researcher. `colony.toml` can list more than one settings folder, so that each person on a team uses their own account. Spreading one person's work across several seats may conflict with [Anthropic's terms](https://www.anthropic.com/legal), so check them before you do it.

**Can a hackathon team use it?**
Yes, in Hack mode. Each teammate runs a lead on their own machine, the leads talk on one pinned issue with `@login` mentions, and work lands after the fast check with `colony merge <branch>`. For one person, Solo keeps the lead, builders, checks and a reviewer, and leaves the rest off. See [modes.md](modes.md) and [hackathon.md](hackathon.md).

**Which stacks does it support?**
Any repo on GitHub whose checks run from a shell command. Setup reads `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `Gemfile`, `pom.xml` and your CI files to find them. The gate names failing tests for pytest and for JavaScript runners such as Vitest and Jest, and sums up other failures from the output. The browser walk needs a web UI: set `walk = false` for a library or a service. It runs on macOS, Linux and Windows (with Git for Windows, see [install.md](install.md#on-windows)), and uses [cmux](https://github.com/manaflow-ai/cmux) for new workspaces when it is installed.

**How much does it cost?**
Colony itself costs nothing. Its agents run on your Claude Code plan, so a batch uses your plan's usage. Several agents run at once, so a batch uses it faster than one session would. Every step's minutes and the cost Claude Code reports go into the PR, and `colony stats` shows each card's tokens. Model calls inside your app's own evals stay at $0 unless you raise `provider_dollars`.

**Can I keep my own rules?**
Yes. Pick `own`, and your `CLAUDE.md` and `AGENTS.md` are the essentials and the rules, with a short core above them. With `lean` or `puffin`, your files still count, and the reviewer checks against both. Everything in `.colony/` is yours to edit. See [presets.md](presets.md).

**Can I keep my own docs folder?**
Yes. When setup finds one, its default is to adopt it in place. It keeps every page, adds the vault's folders and readmes beside them, and changes no page already there. See [knowledge.md](knowledge.md).

**Can I see what it will do first?**
Yes. `colony --dry-run` prints the setup plan or the lead's command line. `colony batch --dry-run …` prints every branch, command and filled-in prompt of a batch. `colony hooks install --dry-run` and `colony retro --dry-run` print their plans too.

**What if a batch gets stuck?**
It stops when the checks fail the same way two rounds in a row, when a fixer commits nothing, when a merge conflicts outside generated files, or after `max_rounds` rounds. It commits its reports first, and the lead turns the cause into a new card.

**What if a builder goes quiet?**
A card In progress whose Last update on the board is over 2.5 hours old gives the lead a `stale:` line. The board has no State, so the lead looks at that builder's session to tell a usage limit from a stop. After 7 days with no update, `colony tidy` closes the card, or moves it to future-work when its work never started. See [cycle.md](cycle.md#the-board).

## Numbers from the first batches

These come from one team's first batch: Puffin Calendar, on 2026-11-05. It is one run, not a benchmark, and your numbers will differ.

| What | Result |
| --- | --- |
| Open problems across 10 cards | 7 → 0, over 4 fix rounds |
| Phone bugs the browser walk caught that tests missed | 4 |
| Time per fix card | 1 to 25 minutes, median about 5 |
| Cost per session after loading rules on demand | 14% less |
| A tiny change | about 2 minutes |
| The whole batch | about 2.5 hours, mostly checks |

The same day, in one team's second batch, Colony ran on its own for the first time, with nobody relaying messages:

| What | Result |
| --- | --- |
| Setup on Puffin's repo | 2.6 minutes and $1.00. It wrote the config, playbook, skills and one AGENTS.md row, and opened its own setup PR |
| Two cards, from the job to an open PR | about 66 minutes. The lead opened a builder and handed out the cards. It answered the builder's question on the card in minutes, then ran the gate |
| The gate | open problems 1 → 0 in 2 rounds, with the walk and the checks passing both times |
| Agent cost | $9.58 at API prices: $5.90 walk, $2.38 review, $1.30 fix |

## How it compares

Colony is narrower than most of these. It sets up the whole loop in your repo with one command: the knowledge vault, the rules, the tiers, the board and the gate. It keeps every task and message on GitHub issues, so builders on other machines and other people's leads can join. And it doesn't open the PR until checks, a fresh reviewer and a real browser walk agree that 0 problems are open.

Each of these does something better:

| Project | What it is | What it does better |
| --- | --- | --- |
| [Claude Code agent teams](https://code.claude.com/docs/en/agent-teams) | Built into Claude Code, experimental. A lead session spawns teammates that share a task list. | Nothing to install. Messages arrive at once, teammates talk to each other directly, and you can talk to any teammate. |
| [metaswarm](https://github.com/dsifry/metaswarm) | 18 agent personas in a 9-phase flow from issue to merged PR. | A different model reviews each change, coverage gates block the PR, and a design review comes before code. Runs on Gemini CLI and Codex too. |
| [Gas Town](https://github.com/steveyegge/gastown) | A workspace manager where a Mayor agent coordinates many workers. | Built for 20 to 30 agents at once, with a merge queue and git-backed work tracking (Beads) that survives restarts. Works with several agent CLIs. |
| [Compound Engineering](https://github.com/EveryInc/compound-engineering-plugin) | Every's plugin: plan, work, review, then compound what you learned. | The compound step turns each lesson into notes the next task reuses. Detailed planning, and it converts to many other coding tools. |
| [gstack](https://github.com/garrytan/gstack) | Garry Tan's role skills: product and design review, engineering review, QA, browse and ship. | Product thinking before code, and you drive each step yourself. A fast browser tool for QA. |
| [Conductor](https://www.conductor.build) | A Mac app that runs Claude Code and Codex in parallel workspaces. | A real interface for watching many agents, reading their diffs and opening PRs. Its cloud option keeps agents running after you close the laptop. |
| [Claude Squad](https://github.com/smtg-ai/claude-squad) | A terminal UI that runs many agents in tmux, each in its own worktree. | Simple, and works with any terminal agent: Claude Code, Codex, Gemini or Aider. You steer every session yourself. |
| [BMAD Method](https://github.com/bmad-code-org/BMAD-METHOD) | An agile method with PM, architect and developer agents and many workflows. | Deep planning documents, a large community, and a process that scales from a small fix to a large project. |
| [Spec Kit](https://github.com/github/spec-kit) | GitHub's toolkit for spec-driven development. | A clear spec-first method that works with many agents, and specs that stay in the repo as the record. |
| [superpowers](https://github.com/obra/superpowers) | Jesse Vincent's skills library: test first, debugging, brainstorming, planning, and subagent work. | Makes one session better at the craft, with a large, tested skill set that works in several tools. |

Several of these combine with Colony. A superpowers skill or a Spec Kit spec can sit under a Colony card.
