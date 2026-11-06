# Configuration

Colony keeps its settings in `.colony/colony.toml` at the root of your repo. Setup writes it from [`colony/colony.toml.example`](../colony/colony.toml.example) and fills in every value, so you rarely edit it by hand. When you do, commit the change like any other file: every machine reads the same settings.

Each mode has its defaults in the package, in `colony/modes/<mode>.toml`. Colony reads the mode's file first, then `.colony/colony.toml`, and any key in your file overrides the default. See [modes.md](modes.md#the-defaults-files).

Paths may start with `~`. Every command checks the required keys when it starts, and names the missing one in a single line, such as `colony.toml: [project] needs 'checks'`. Every table below `[budget]` is optional, and each of its keys has a default.

## `[project]`

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `mode` | no | `"hack"` | The mode: `"hack"`, `"solo"` or `"startup"`. Setup asks it first. It picks the defaults file, and what runs: see [modes.md](modes.md). Without it, `startup`. |
| `name` | yes | `"myapp"` | A short name. It starts session titles (`myapp-lead`), branch names (`myapp/batch-2026-11-05`), worktree names, and the board's title. |
| `repo` | yes | `"owner/myapp"` | The GitHub repo, as `owner/name`. Cards, lines and PRs live here, and the board belongs to its owner. |
| `base` | yes | `"main"` | The branch PRs go to. Colony never pushes to it, except `colony merge` in Hack with `[gate] merge_after_fast_check = true`. |
| `preset` | no | `"lean"` | The rules setup copied: `lean`, `puffin` or `own`. A record for you; the commands don't read it. |
| `max_builders` | no | `4` | How many builders the lead opens on this machine. More join from other computers with `colony join`. |
| `worktrees` | yes | `"~/worktrees"` | Where batches, fixers and the retro make their worktrees. Pick a folder outside the clone. |
| `fast_check` | no | `"npm test"` | A builder's quick check after each change. Setup writes it into the playbook. |
| `checks` | yes | `"npm run lint && npm run typecheck && npm test"` | The full check a batch runs. It runs through your shell, so `&&` works. Setup adds `&& colony suppressions` to it. |
| `web_checks` | no | `"npm run lint && npm test"` | A lighter check for a round that changed no `backend_paths` file, once a full run has passed. Empty means every round runs `checks`. |
| `backend_paths` | no | `["api/", "server/"]` | Path prefixes whose change needs the full checks. A change there is never TINY. |
| `generated` | no | `["src/generated/*"]` | Globs for files a build writes. When a merge conflicts only in these, Colony takes the card's side and runs `regen`. Their lines don't count toward a tier. |
| `regen` | no | `"npm run codegen"` | The command that rebuilds the generated files. |
| `check_env_file` | no | `"~/.config/myapp/check.env"` | A local file of `KEY=VALUE` lines added to the checks' environment. A relative path starts at the repo root. Keep it out of git. Colony never prints its values. |
| `install` | no | `"npm ci"` | Runs in each new worktree: the batch's, the walker's and each fixer's. |
| `trailer` | no | `"Assisted-by: claude-code:claude-opus-5-5"` | The line every batch, fixer and retro commit ends with. Default: `Assisted-by: claude-code:<the fixer's model>`. |

`check_env_file` accepts `export KEY=VALUE`, skips `#` lines, and strips quotes around a value.

## `[accounts.<name>]`

One table per Claude Code settings folder. You need at least one.

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `config_dir` | yes | `"~/.claude"` | The settings folder. `~/.claude` is Claude Code's default, and Colony leaves `CLAUDE_CONFIG_DIR` unset for it. |
| `person` | yes | `"ana"` | Whose account it is. `"any"` shares it with everyone. |

```toml
[accounts.ana]
config_dir = "~/.claude"
person = "ana"

[accounts.ben]
config_dir = "~/.claude"
person = "ben"
```

**How a session picks its account.** `--account <name>` names one outright. Otherwise the person is `--person`, else `$COLONY_PERSON`, else the one person the config names, else the one git's user matches, else the one the `gh` login maps to through `[people.<person>] login`. Their accounts are `[people.<person>] accounts`, in order, else every account whose person is theirs or `any`. Each account's 5-hour and weekly use, with their reset times, come from its folder's `.claude.json`. An account out of 5-hour room (95%), near it (80%) with the reset over an hour off, or out of weekly room (95%) is skipped. Of the rest, the one whose weekly window resets soonest goes first, "use it or lose it", then the one with the most 5-hour room. An account with no reading comes after those, and `last_resort` accounts only when nothing else has room. Every session prints why its account was picked. `prefer_account` and `drain` are gone; an old config that has them still loads, and they do nothing.

Most teams list one account per person. Spreading one person's work across several seats may conflict with [Anthropic's terms](https://www.anthropic.com/legal), so check them before you list more than one for yourself.

## `[roles]`

Each role takes a `model` and an `effort`. The first five are required. `spec` and `researcher` are optional, and need both keys when you add them.

| Role | Required | Runs as | Default effort | What it does |
| --- | --- | --- | --- | --- |
| `lead` | yes | interactive | `high` | Talks with you, picks tiers, writes cards, merges, runs the gate |
| `builder` | yes | interactive | `medium` | Builds one card at a time |
| `reviewer` | yes | headless, fresh each round | `high` | Reviews the round's diff against the rubric and rules |
| `walker` | yes | headless | `medium` | Walks the changed flows in a browser |
| `fixer` | yes | headless, one per card | `medium` | Fixes the findings routed to its card |
| `spec` | no | interactive, opened by `colony spec` | the builder's | Writes a FEATURE's requirements, design and tasks from `.colony/prompts/spec.md`. Without it, it takes the builder's settings. |
| `researcher` | no | interactive, opened by `colony research` | the builder's | Answers one outside question from `.colony/prompts/researcher.md`. Without it, it takes the builder's settings. |
| `retro` | no | headless, after a batch | the reviewer's | Turns a batch's lessons into rules and checks. Without it, `colony retro` uses the reviewer's settings. |

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `model` | yes | `"claude-opus-5-5"` | The model the role runs on |
| `effort` | yes | `"medium"` | Claude Code's effort level for the role, such as `medium` or `high` |
| `agent` | no | `"ui-check"` | For a headless role, a Claude Code subagent to run as (`claude -p --agent <name>`). The interactive roles ignore it. |
| `permission_mode` | no | `"auto"` | For the interactive roles, Claude Code's permission mode. Default `auto`. Headless roles always run in `auto`. |

```toml
[roles]
lead       = { model = "claude-opus-5-5", effort = "high" }
builder    = { model = "claude-opus-5-5", effort = "medium" }
reviewer   = { model = "claude-opus-5-5", effort = "high" }
walker     = { model = "claude-opus-5-5", effort = "medium", agent = "ui-check" }
fixer      = { model = "claude-opus-5-5", effort = "medium" }
spec       = { model = "claude-opus-5-5", effort = "high" }
researcher = { model = "claude-opus-5-5", effort = "high" }
```

## `[gate]`

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `rubric` | yes | `["bugs", "security and privacy", "tests", "performance", "accessibility"]` | The reviewer's checklist. Its report gives each item's open count. It is a checklist, not a score. |
| `rules` | no | `[".colony/core.md", ".colony/rules/*.md", "CLAUDE.md"]` | The files the reviewer and the retro check against. Setup lists the core, the preset's rules, and your own `CLAUDE.md` and `AGENTS.md`. |
| `max_rounds` | yes | `5` | The most rounds a batch runs. A last round that still has findings stops the batch. |
| `walk` | yes | `true` | Whether to walk the changed screens in a browser. Set `false` for a repo with no web UI. |
| `walk_paths` | no | `["web/", "app/"]` | Path prefixes. A round that changes none of them skips the walk, unless the last walk failed. Empty walks every round. |
| `merge_after_fast_check` | no | `true` | Hack only. `true` lets `colony merge <branch>` push the base after the fast check passes on the merged result. Otherwise `colony merge` opens a PR. Setup asks, with yes as the default. |

## `[budget]`

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `provider_dollars` | yes | `0` | Model spend allowed inside your app's own checks and evals. Raise it only with the person's yes. |
| `use_api_key` | no | `false` | `true` lets the lead and builders bill `ANTHROPIC_API_KEY`. Otherwise Colony drops it, so sessions use the account's subscription. |

At `0`, the checks run without `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` in their environment. Above `0`, those keys stay for the checks. Colony reads only whether the value is 0. Agents treat any spend above it as a stop-list item that needs your yes.

Whatever the budget, Colony removes `ANTHROPIC_API_KEY` from the reviewer's, walker's, fixers' and retro's environment, so they always run on your Claude Code login and never bill an API key.

## `[messages]`

How lines travel between sessions. See [messages.md](messages.md).

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `board` | no | `12` | Hack only. The number of the pinned `Board: <project>` issue, which setup opens and pins. Every line goes there instead of to cards. |
| `lead_digest_minutes` | no | `10` | How long the lead's wait gathers lines before it prints them as a digest. A line that can't wait prints at once: `urgent:`, `blocked:` and `question:` lines, your lines, and `done` for a card the batch waits on. |

## `[people]`

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `logins` | no | `["ana-gh", "ben-gh"]` | The team's GitHub logins. Agents post through their person's own login, so the lead tells a person's line from an agent's by its signature. A line signed with one of these logins counts as a person's line, and reaches the lead at once. |

## `[knowledge]`

The knowledge vault and its checks. See [knowledge.md](knowledge.md).

| Key | Example | What it does |
| --- | --- | --- |
| `vault` | `"knowledge"` | The vault's folder, from the repo root. Default `knowledge`. |
| `<check>` | `orphans = "warn"` | One check's mode: `off`, `warn` or `fail`. The checks are `page_types`, `links`, `orphans`, `readme_maps`, `code_paths`, `size_caps`, `dated_caps`, `copied_text`, `rule_budget`, `replaced_records` and `decision_log`. Every check fails by default except `size_caps`, which warns. A misspelled check name is an error. |
| `caps` | `{ living-spec = 25000, prd = { chars = 15000, from = "2026-11-05" } }` | Size caps per page type, in characters. A cap with `from` holds only pages created on or after that day, under `dated_caps`. The defaults are 25,000 for `living-spec` and `design-spec`, 12,000 for `feature-spec`, and 3,000 for a README's text above its `## Pages`. |
| `rules` | `[".colony/rules"]` | The folders that hold rules, which pages may link as `[[name]]` and the rule budget counts. Default `[".colony/rules"]`. |
| `rule_chars` | `12000` | Each rule's size budget in characters. Default 12,000. |
| `rule_budgets` | `{ performance = 16000 }` | A budget for one rule, by its file name. The example sets this one for the `puffin` preset's long `performance.md`. |
| `code_roots` | `["src", "apps"]` | The top folders whose paths `code_paths` checks. Default: every top folder of the repo. |
| `copy_words` | `20` | The shortest paragraph, in words, that `copied_text` compares. Default 20. |
| `plugins` | `["tools/docs_checks.py"]` | The repo's own checks, as Python files in the repo. Each file has `CHECKS`, its checks with their default modes, an optional `ONE_PAGE` for the ones `--staged` runs, and `run(check, repo, vault, files)`, which returns `(path, line, message)` problems. Its checks take modes here like the built-in ones, and count in the same tally. A plug-in that crashes fails the run. |

```toml
[knowledge]
vault = "knowledge"
orphans = "warn"
caps = { living-spec = 25000 }
```

## `[board]`

| Key | Example | What it does |
| --- | --- | --- |
| `number` | `7` | The number of a GitHub Project the repo's owner already has, to use as the card board. (Hack's board issue is `[messages] board`.) Without it, Colony finds the owner's open project titled `Colony: <name>`, which `colony board init` makes. |

Every computer's `gh` login needs the project scope for the board: `gh auth refresh -s project`.

## `[cycle]`

Tiers and stale cards. See [cycle.md](cycle.md). Setup writes this table only when your repo needs something the defaults miss.

| Key | Default | What it does |
| --- | --- | --- |
| `tiny_code_lines` | `100` | The most non-test code lines a TINY change holds |
| `tiny_docs_lines` | `300` | The most docs lines a TINY change holds |
| `feature_code_lines` | `400` | Over this many non-test code lines, a change is a FEATURE |
| `docs` | `["knowledge/", "docs/", ".colony/reports/"]` | The documentation folders. Their lines count as docs, and a new page under `<folder>/specs/` makes a FEATURE. |
| `feature_folders` | `[]` | Folders whose new entries are features, beside those named `features`, `modules`, `routes`, `pages` and `screens` |
| `risk` | `{ payments = ["src/ledger/"] }` | Extra path fragments per risk kind, for code the built-in list misses |
| `stale_hours` | `2.5` | How long a card In progress can go without an update before the lead gets a `stale:` line |

## `[limits]`

The anti-bloat limits that `colony card new` and `colony tidy` keep. See [cycle.md](cycle.md#tidy). Each is a whole number.

| Key | Default | What it does |
| --- | --- | --- |
| `open_cards_per_lead` | `10` | The most open cards one lead may have, by the board's Lead field. `colony card new` refuses past it. |
| `stale_days` | `7` | After this many days with no update, `colony tidy` closes a card, or moves it to future-work when its work never started |
| `issue_comments` | `200` | At this many comments, the coordination issue or a Needs issue closes with a summary of its open items, and a fresh one goes on |
| `archive_days` | `7` | After this many days Done, or closed, `colony tidy` archives a board item |

## `[suppressions]`

| Key | Example | What it does |
| --- | --- | --- |
| `paths` | `["src", "tests"]` | The folders `colony suppressions` counts. Default: every tracked file. |

## `[tools]`

`colony tools` prints this table after it writes the tools you accepted, and setup adds it. It records `mcp`, the MCP servers, and `skills`, the skill folders. The commands don't read it.

## What the sessions' environment holds

Colony sets these for every interactive session: the lead, each builder, the researcher and the spec agent. You don't set them yourself.

| Name | Value |
| --- | --- |
| `COLONY_SESSION` | `lead`, the builder's name, `researcher` or `spec` |
| `COLONY_PERSON` | Whose session it is |
| `CLAUDE_CONFIG_DIR` | The picked settings folder, left unset for `~/.claude` |
| `CLAUDE_CODE_RETRY_WATCHDOG` | `1` |
| `CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS` | `21600000`, the longest the retry watchdog waits: 6 hours |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | `250000` |

`--dry-run` prints these names, never their values. The hooks run only in a session that has `COLONY_SESSION`.
