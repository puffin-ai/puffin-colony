# Configuration

Colony keeps its settings in `.colony/colony.toml` at the root of your repo. Setup writes it from [`colony/colony.toml.example`](../colony/colony.toml.example) and fills in every value, so you rarely edit it by hand. When you do, commit the change like any other file: every machine reads the same settings.

Each mode has its defaults in the package, in `colony/modes/<mode>.toml`. Colony reads the mode's file first, then `.colony/colony.toml`, and any key in your file overrides the default. See [modes.md](modes.md#the-defaults-files). A setting only you want on this computer goes in `.colony/colony.local.toml`, which git never tracks: see [Layers](#layers).

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
| `worktrees` | no | `".worktrees"` | Where builders, batches, fixers, the merge and the retro make every worktree. Default: `.worktrees`, inside the repo. A relative path starts from the repo's main checkout, so a command run in a worktree never nests one inside it, and a folder inside the repo is kept out of `git status` by a line in the clone's own `.git/info/exclude`, which nothing commits. A folder outside the repo still works, and the lead hears once a day that worktrees belong inside it. See [folders.md](folders.md#worktrees). |
| `fast_check` | no | `"npm test"` | A builder's quick check after each change. Setup writes it into the playbook. |
| `checks` | yes | `"python3 tools/checks.py {areas}"` | The full check a batch runs. It runs through your shell, so `&&` works. Setup adds `&& colony suppressions` to it. With `[checks] areas`, `{areas}` takes the names of the areas a round runs. |
| `backend_paths` | no | `["api/", "server/"]` | Path prefixes whose change is never TINY. |
| `generated` | no | `["src/generated/*"]` | Globs for files a build writes. When a merge conflicts only in these, Colony takes the card's side and runs `regen`. Their lines don't count toward a tier. |
| `regen` | no | `"npm run codegen"` | The command that rebuilds the generated files. |
| `check_env_file` | no | `"~/.config/myapp/check.env"` | A local file of `KEY=VALUE` lines added to the checks' environment. A relative path starts at the checkout the command runs in, and when the file isn't there, at the repo's main checkout, so a helper's worktree and the merge worktree use the main checkout's `.env.local`. Keep it out of git. Colony never prints its values. When it names a database on another computer, such as a hosted Postgres, `colony merge` and `colony batch` print a note once a day with the host alone: every check run writes to that database, and a shared one slows as runs pile up. |
| `deploy_environment` | no | `"Production"` | The GitHub deployment environment that is the live app, which hosts such as Vercel and Netlify record. `colony who` and `colony status` print its newest successful deploy and what landed on the base since. Default: `Production`. A hack config from before this key names it under `[hack]`, which still counts. |
| `install` | no | `"npm ci"` | Runs in each new worktree: the batch's, the walker's and each fixer's. |
| `trailer` | no | `"Assisted-by: claude-code:claude-opus-5-5"` | The line every batch, fixer and retro commit ends with. Default: `Assisted-by: claude-code:<the fixer's model>`. |

`check_env_file` accepts `export KEY=VALUE`, skips `#` lines, and strips quotes around a value.

## `[accounts.<name>]`

One table per Claude Code settings folder. You need at least one.

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `config_dir` | yes | `"~/.claude"` | The settings folder. `~/.claude` is Claude Code's default, and Colony leaves `CLAUDE_CONFIG_DIR` unset for it. |
| `person` | yes | `"ana"` | Whose account it is. `"any"` shares it with everyone. |
| `provider` | no | `"claude"` | The AI provider the account belongs to. `"claude"`, the default, reads its usage and sign-in from its settings folder. Any other provider uses `usage_command` and `auth_command`. |
| `usage_command` | no | `"python3 tools/usage.py"` | A command that prints the account's usage as JSON in Claude Code's shape, `{"five_hour": {"utilization": 40, "resets_at": "<ISO time>"}, "seven_day": {...}}`. It runs with the account's folder in `$COLONY_ACCOUNT_DIR`, at most once every 10 minutes. With it, any provider's account is judged for room like a Claude Code one. |
| `auth_command` | no | `"tools/signed-in.sh"` | A command that ends with 0 while the account is signed in. Its service check uses it instead of Claude Code's own sign-in check. |
| `max_busy` | no | `2` | The most helpers this account runs at once, instead of `[pool] max_busy`. |

A folder's path belongs to one computer. Put this computer's accounts, or this computer's folder for an account the team's file names, in `.colony/colony.local.toml`: `colony accounts add <name> --dir <folder>` writes it there, and `colony accounts scan` finds signed-in folders the pool lacks. See [capacity.md](capacity.md#finding-accounts).

```toml
[accounts.ana]
config_dir = "~/.claude"
person = "ana"

[accounts.ben]
config_dir = "~/.claude"
person = "ben"
```

**How a session picks its account.** `--account <name>` names one outright. Otherwise the person is `--person`, else `$COLONY_PERSON`, else the one person the config names, else the one git's user matches, else the one the `gh` login maps to through `[people.<person>] login`. Their accounts are `[people.<person>] accounts`, in order, else every account whose person is theirs or `any`. Each account's 5-hour and weekly use, with their reset times, come from its folder's `.claude.json`. An account out of 5-hour room (95%), near it (80%) with the reset over an hour off, or out of weekly room (95%) is skipped. Of the rest, the one whose weekly window resets soonest goes first, "use it or lose it", then the one with the most 5-hour room. An account with no reading comes after those, and `last_resort` accounts only when nothing else has room. Every session prints why its account was picked. `prefer_account` and `drain` are gone; an old config that has them still loads, and they do nothing. `[pool]`, below, sets the order of use, the percentages at which a session switches, the accounts kept free, and how many helpers one account runs at once. [capacity.md](capacity.md) says more.

**How much the lead tells the person.** `[people.<person>] quiet_lead = true` makes that person's lead act on notifications silently, and write to them only to converse or when they must act; its own status lines go on the board, never in chat. `colony` prints the line when it starts a lead for that person. It is false by default, and the lead keeps the person posted on progress.

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
| `max_rounds` | yes | `3` | The most rounds a batch runs, at most 3. When the last round passes its checks with review or walk findings open, each becomes a card and the PR opens listing them. Failing checks in the last round stop the batch. |
| `walk` | yes | `true` | Whether to walk the changed screens in a browser. Set `false` for a repo with no web UI. |
| `walk_paths` | no | `["web/", "app/"]` | The user-facing files, as path prefixes or globs. A round that changes none of them skips the walk, unless the last walk failed. Empty walks every round. |
| `paid_checks` | no | `"npm run eval"` | A command whose model calls cost money, such as your app's evals. A batch runs it once, in the round whose checks, review and walk pass, or in the last round when its checks pass, only while `[budget] provider_dollars` is above 0. It gets the dollars the batch has left as `COLONY_SPEND_CEILING`, must stop there, and must print `spent: $<dollars>`. The batch stops when it prints none or spends past the budget, and the PR lists what it spent. Empty by default. |
| `merge_after_fast_check` | no | `true` | Hack only. `true` lets `colony merge <branch>` push the base after the fast check passes on the merged result. Otherwise `colony merge` opens a PR. Setup asks, with yes as the default. |

## `[checks]`

Optional. It lets a batch check only the areas a change touches. Without `areas`, every round runs the whole `[project] checks`.

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `areas` | no | `{ web = ["apps/web/"], backend = ["apps/backend/"] }` | Each check area and its paths, as prefixes or globs. A round runs the areas its changed paths are in; a changed path no area names runs every area. The area names fill `{areas}` in `[project] checks`. |
| `all` | no | `"all"` | What `{areas}` takes when every area runs. Empty joins every area's name. |
| `skip` | no | `["docs/", "*.md"]` | Paths whose change runs no check, such as docs. A round that changes only these skips the checks. |
| `rerun` | no | `"cd apps/backend && uv run pytest {test}"` | A failing test whose every failure reason names a timeout or a time limit runs once more by itself with this command, `{test}` its id as the output named it. It counts only when it fails again, and the round passes on its reruns only when nothing else in the output failed. Empty reruns nothing. |
| `minutes` | no | `41` | A run of every area's minutes, the yardstick for the minutes `minutes.md` says a narrowed round saved. Without it, the batch's own run of every area. |

These keys make checks proportional, fast and never repeated. [checks.md](checks.md) says how each works. Every one is optional, and a config with none of them checks the way it always did.

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `scope` | no | `"related"` | What a check runs: `"related"`, the tests for the change and the guards beside the fast check; `"areas"`, the check command for the areas the change touches; or `"full"`, `[project] checks` for every area. Default: `"related"` once `related` is set, else `"areas"`. `--full` asks for the full suite. |
| `related` | no | `"uv run pytest {tests}"` | The command that runs the tests for a change. `{tests}` takes the tests found for the change and the guards, and `{files}` the changed files, for a runner that finds tests itself, such as `"npx vitest related {files} --run"`. As a table of check areas, each area gets its own command and its own paths: `{ web = { run = "npx vitest run {tests}", in = "apps/web" }, api = "uv run pytest {tests}" }`, where `in` is the folder it runs in and its paths start from. |
| `guards` | no | `["tests/test_architecture.py"]` | The guard tests, such as architecture tests, which run with every related check: paths, folders, test ids or globs. As a table of check areas, an area's guards run when the change touches that area. |
| `tests` | no | `{ "setup.cfg" = ["tests/"] }` | Tests for files whose tests aren't named after them, as a path or glob and its tests. |
| `budgets` | no | `{ fast = 120, checks = 300, full = 0 }` | How many seconds a command follows each kind of check before it leaves it running in the background and returns: `fast` for `colony fast-check`, `checks` for `colony check run`, `full` for the full suite. 0 sends it to the background at once. Default: 300, 300 and 0. |
| `caps` | no | `{ full = 3600 }` | A run past its kind's cap, in seconds, is stopped and counts as failed; a batch round past its cap stops the batch. Every command that runs a check follows it: `fast` holds `colony fast-check`, `colony merge`'s check and a fast gate's batch round, `checks` holds `colony check run` and a batch round, and `full` the full suite. A batch's run on its start commit and its reruns stop at the round's cap too. Default: no cap. |
| `reuse` | no | `true` | Whether a pass on the same code with the same command is reused instead of run again. Default `true`. |
| `failure` | no | `'^BROKEN: '` | A regular expression for the repo's own failure line, beside the ones Colony knows, so its first failure shows at once. |
| `locks` | no | `["test-db"]` | Locks every check run holds a slot of while it runs, besides `tests`, for things only one run can use at a time, such as a shared test database. `[locks.<name>] slots` sets how many runs share each. See [checks.md](checks.md#every-check-fast-or-in-the-background). |

## `[leads]`

Optional. When a lead counts as silent, and when a gone lead drops from the registry. See [folders.md](folders.md).

| Key | Default | What it does |
| --- | --- | --- |
| `silent_minutes` | `120` | A lead whose own session has done nothing this long is silent, though its wait keeps its status fresh. Its folders can be borrowed or claimed, and the rest of the repo taken over, each with a line that tells it. An ask for its folders is granted then. |
| `drop_after_hours` | `72` | A lead gone this long, with no status and no heartbeat, drops from the registry with its loans, and `colony who` stops listing it. |

## `[ci]`

Optional. How `colony ci` starts the project's CI on a commit, and what it does with the result. See [checks.md](checks.md#ci-on-any-commit).

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `start` | no | `"gh workflow run ci.yml --ref {branch}"` | The command that starts your CI on a commit, with `{sha}`, `{short}`, `{branch}` and `{repo}` filled in. Empty, the default: Colony pushes the commit to a branch of its own, which starts any CI that runs on a push, unless a branch on origin already holds it. |
| `branch` | no | `"ci/{short}"` | The branch that push makes, deleted once CI ends, and only while it still holds the commit Colony pushed. Default `"colony-ci/{short}"`. It must name the commit with `{short}` or `{sha}` and nothing else, so each commit gets a branch of its own, and it may never be a protected branch: the base, the default branch, a `[safety] protect` pattern or a long-lived branch. Colony refuses any other. |
| `cancel_superseded` | no | `true` | Cancel the runs on older commits of the same branch, which the newer commit made pointless. Default `true`. |
| `post` | no | `true` | Post the result on the commit's pull request, else on the commit. Default `true`. |
| `poll_seconds` | no | `20` | How often it reads the commit's checks. Default 20. |
| `start_minutes` | no | `10` | How long it waits for a first check to show before it says how to start CI. Default 10. |
| `wait_minutes` | no | `120` | The longest it watches. Default 120. |

## `[walk]`

Optional.

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `browser` | no | `"agent-browser"` | The walker's browser: `"playwright"`, the Playwright MCP and the default, or `"agent-browser"`, the [agent-browser](https://github.com/vercel-labs/agent-browser) CLI, which the walker runs through Bash with no MCP server loaded. |
| `screens` | no | `{ "/calendar" = ["apps/web/src/calendar/"] }` | Each screen and the paths that feed it. A round walks only the screens its changed files feed, and the walker traces any other changed `walk_paths` file to its screens. |
| `minutes`, `cost` | no | `27`, `6` | A full walk's minutes and dollars, the yardstick for what a skipped or narrowed walk saved in `minutes.md`. |

## `[budget]`

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `provider_dollars` | yes | `0` | Model spend allowed inside your app's own checks and evals. Raise it only with the person's yes. |
| `use_api_key` | no | `false` | `true` lets the lead and builders bill `ANTHROPIC_API_KEY`. Otherwise Colony drops it, so sessions use the account's subscription. |

At `0`, the checks run without `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` in their environment. Above `0`, those keys stay for the checks. Colony reads the value itself only for `[gate] paid_checks`, whose ceiling it sets. Agents treat any spend above it as a stop-list item that needs your yes.

Whatever the budget, Colony removes `ANTHROPIC_API_KEY` from the reviewer's, walker's, fixers' and retro's environment, so they always run on your Claude Code login and never bill an API key.

## `[messages]`

How lines travel between sessions. See [messages.md](messages.md).

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `board` | no | `12` | Hack only. The number of the pinned `Board: <project>` issue, which setup opens and pins. Every line goes there instead of to cards. |
| `lead_digest_minutes` | no | `10` | How long the lead's wait gathers lines before it prints them as a digest. A line that can't wait prints at once: `urgent:`, `blocked:` and `question:` lines, your lines, and `done` for a card the batch waits on. |
| `max_line` | no | `300` | The most characters a line's sentence holds. A longer note goes as a file, with `--attach`. Default 300. |
| `start_ack_minutes` | no | `10` | How long a lead's `start:` line waits for the helper's wait to acknowledge it before it goes again. `0` asks for no acknowledgement. Default 10. |
| `start_resends` | no | `2` | How many times an unacknowledged start line goes again before the lead hears it at once. Default 2. |
| `nudge` | no | `"auto"` | When `colony post` and `colony say` nudge the recipient's cmux workspace on this computer: `"off"`, `"auto"` for a recipient whose wait isn't running here, or `"always"`. `--nudge` nudges once whatever it says. Default `"off"`. |
| `redeliver_minutes` | no | `60` | After a compaction or a restart, how far back the SessionStart hook shows the lines a session was shown and hasn't acknowledged with `colony ack`. `0` shows none. Default 60. |
| `check_names` | no | `true` | Refuse a line for a name no learned, live or registered session has. Default true. |
| `refuse_local_paths` | no | `true` | Refuse a line that names a path on this computer, which a session on another computer can't read: anything under `~/`, or an absolute path that names a file or folder here, such as `/tmp/x.md`, read without a line, column or anchor after it, so `/tmp/x.md:12` and `/tmp/x.md#L4` count. A path nothing here has, such as the web route `/home/feed`, and a device such as `/dev/null` pass. Default true. |

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
| `title` | `"Demo Colony"` | The board's title, which `colony board init` gives it and every command finds it by. Default: `Colony: <name>`. |

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
| `risk` | `{ payments = ["src/ledger/"] }` | Extra path fragments per risk kind, for code the built-in list misses. A path an entry starts, such as `REVIEW.md` or `guide/`, is never docs, so it stays on the list. |
| `tiny_folders` | `["apps/web/", "apps/site/"]` | When set, the only folders a TINY change's code may be in. Any other non-docs file, a test or a root file too, makes it at least SMALL. |
| `structure_files` | `["apps/*/src/screens/*.screen.tsx"]` | Globs (`*` crosses folders) of page, layout or route files, beside the built-in `app/**/page`, `layout` and `route` files. A new one is a FEATURE. Moving or deleting one, or any file under `feature_folders`, is never TINY. |
| `feature_triggers` | see below | The repo's own FEATURE lines, each `{ path, why, added, removed, line }` |
| `stale_hours` | `2.5` | How long a card In progress can go without an update before the lead gets a `stale:` line |

Each `feature_triggers` entry names a file glob, `path`, the reason `--why` prints, `why`, and a regular expression, `added`, `removed` or both. `added` makes the change a FEATURE when it finds something, its first group or else the whole match, more often in the file's added lines than in its removed ones, so moving or editing a line keeps no trigger unless what the pattern captures changes. `removed` reads the other way, for a name that leaves a list. `line`, optional, limits both to the lines it matches. Triggers read test files too.

```toml
[[cycle.feature_triggers]]
why = "a new registry key"
path = "src/commands/registry.py"
added = '^\s*"([a-z_]+)"\s*:\s*Entry\('

[[cycle.feature_triggers]]
why = "a name leaving the held-back list"
path = "src/tools/list.py"
line = '^\s*HELD\b'
removed = '"([^"]+)"'
```

## `[limits]`

The anti-bloat limits that `colony card new` and `colony tidy` keep. See [cycle.md](cycle.md#tidy). Each is a whole number.

| Key | Default | What it does |
| --- | --- | --- |
| `open_cards_per_lead` | `10` | The most open cards one lead may have, by the board's Lead field. `colony card new` refuses past it. |
| `stale_days` | `7` | After this many days with no update, `colony tidy` closes a card, or moves it to future-work when its work never started |
| `issue_comments` | `200` | At this many comments, the coordination issue or a Needs issue closes with a summary of its open items, and a fresh one goes on |
| `archive_days` | `7` | After this many days Done, or closed, `colony tidy` archives a board item |
| `board_comments` | `300` | Hack mode: at this many comments, the next post closes the board, opens a fresh `Board: <project>` issue that links the old one, and pins it. `tools/board` follows it. |

## `[suppressions]`

| Key | Example | What it does |
| --- | --- | --- |
| `paths` | `["src", "tests"]` | The folders `colony suppressions` counts. Default: every tracked file. |

## `[tools]`

`colony tools` prints this table after it writes the tools you accepted, and setup adds it. It records `mcp`, the MCP servers, and `skills`, the skill folders. The commands don't read it.

## Standing orders

How a session works for its person and the team, such as how much a lead decides alone or when the full suite runs, lives in profiles, not in `colony.toml`: your personal profile, the team profile `.colony/team.toml`, and session settings. [profiles.md](profiles.md) has the format and how they combine.

| Name | Example | What it does |
| --- | --- | --- |
| `COLONY_CONFIG_HOME` | `~/dotfiles/colony` | The folder that holds your personal profile. Without it: `%APPDATA%\colony` on Windows, else `$XDG_CONFIG_HOME/colony`, else `~/.config/colony`. |

## `[pool]`

Optional. The team's rules for its pool of accounts. Every key has a default. See [capacity.md](capacity.md#the-account-pool).

| Key | Default | What it does |
| --- | --- | --- |
| `order` | `"reset"` | The order accounts with room are used in: `"reset"`, the soonest weekly reset first, so usage about to expire gets spent, then the most 5-hour room; or `"listed"`, the person's own order in `[people.<person>] accounts`. |
| `out_at` | `95` | A window at or past this percent has no room, and a new session switches to the next account. |
| `near_at` | `80` | A 5-hour window at or past this percent, with its reset more than `near_hours` away, is skipped too. |
| `near_hours` | `1` | How far off a reset must be for `near_at` to skip the account. |
| `reserve` | `[]` | Accounts kept free: never picked, used only when named with `--account`. A session that runs on one anyway is named to its lead. |
| `max_busy` | `3` | The most helpers one account runs at once, on every computer together. `colony helpers`, `colony open` and `colony join` open no helper past it. |
| `wave` | `3` | How many helpers `colony helpers <n> --open` opens at once. The rest open in later waves. |
| `wave_seconds` | `60` | The pause between waves. |
| `stale_minutes` | `15` | A usage reading older than this never places a session: its account's room counts as unknown, and its old numbers are not used. At least 10, since a reading is fetched again once it is 10 minutes old. See [capacity.md](capacity.md#fresh-readings). |
| `share_lead_accounts` | `false` | How helpers use the account a live lead or orchestrator runs on. False uses it last: helpers share it only when no other account fits one, at most one fewer than its cap, and only while the lead keeps 10% of each window until it resets, with one warning. True treats it as any other account. To keep helpers off an account always, put it in `reserve`. See [capacity.md](capacity.md#the-leads-own-account). |
| `helper_rate` | `10` | The percent of the 5-hour window one busy helper uses an hour, a guess the fit check uses only until readings show the account's real rate. `0` checks only against measured rates. See [capacity.md](capacity.md#plan-around-resets). |
| `scan_folders` | `["~/.claude", "~/.claude-*", "~/.claude_*"]` | Where `colony accounts scan` looks for signed-in settings folders the pool lacks. See [capacity.md](capacity.md#finding-accounts). |

```toml
[pool]
order = "reset"
reserve = ["admin"]
max_busy = 3
```

## `[subagents]`

Optional. How many subagents one Colony session runs at once. The subagent guard, a hook, refuses a call past it. Builders run as helpers, never as subagents; see [capacity.md](capacity.md#builders-are-helpers-never-subagents) and [safety.md](safety.md#the-subagent-guard).

| Key | Default | What it does |
| --- | --- | --- |
| `max_running` | `2` | The most subagents one session runs at once. `0` lets none run. The guard reads `.colony/colony.local.toml` first, then `.colony/colony.toml`. |

```toml
[subagents]
max_running = 2
```

## `[machine]`

Optional. What one helper, test run and build needs on this computer, and what stays free for the person. Colony reads the cores, memory, free disk and load itself, and sets from these how many helpers, test runs and builds run at once. See [capacity.md](capacity.md#this-computer).

| Key | Default | What it does |
| --- | --- | --- |
| `helper_gb` | `1` | The memory one helper session needs, in GB. |
| `test_gb`, `build_gb` | `2`, `2` | The memory one test run or one build needs, in GB. |
| `test_cores`, `build_cores` | `2`, `2` | The cores one test run or one build keeps busy. |
| `keep_free_gb` | `2` | Memory left for the person and the system, in GB. |
| `keep_free_disk_gb` | `10` | Below this much free disk where worktrees go, the computer counts as busy. |
| `busy_load` | `1` | At or past this load per core, the computer counts as busy: no new helper opens, and test runs and builds drop toward one at a time. |
| `max_helpers` | `[project] max_builders` | The most helpers on this computer, whatever its size. |
| `max_tests`, `max_builds` | none | The most test runs or builds at once, whatever the computer's size. |

## `[services]`

Optional. A check for each service the team relies on, such as an AI provider, a cloud CLI, the code host or a package registry, or a local service your work needs, such as a test database. Colony always checks each account whose folder is on this computer, and `gh auth status`, unless `builtin = false`. `colony services` runs every check, and the lead's wait runs each one on its own schedule and says when one fails. It is one table for every command: `colony crash-report` and `colony resume` judge each `[services.<name>]` by the same check and pass condition, and `colony resume` runs the `restart` of one that fails ([`[recover]`](#recover)). See [capacity.md](capacity.md#service-checks).

| Key | Default | What it does |
| --- | --- | --- |
| `builtin` | `true` | Whether to check each account and GitHub besides your own checks. |

Each `[services.<name>]` table, named in lowercase letters, digits and dashes:

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `check` | yes | `"aws sts get-caller-identity"` | The command that checks the service. It runs through your shell, in the repo's top folder, where its `restart` runs too. Its output is read, never printed. |
| `exit` | no | `0` | The exit code that passes. Default `0`. |
| `expect` | no | `"Logged in"` | A regular expression the output must match. |
| `at_least`, `at_most` | no | `500` | The first number in the output must be at least, or at most, this, such as requests left on an API. |
| `every_minutes` | no | `30` | How often the lead's wait runs it. Default 30. |
| `timeout` | no | `20` | Seconds it may run. Default 20. |
| `fix` | no | `"aws sso login"` | What the person does when it fails. The alert names it. |
| `restart` | no | `"docker compose up -d db"` | For a local service, a command that brings it back when its check fails. `colony resume` runs it, in the repo's top folder for up to 5 minutes, then the check again; the checks here never do. |

```toml
[services.aws]
check = "aws sts get-caller-identity"
fix = "aws sso login"

[services.github-api]
check = "gh api rate_limit --jq .resources.core.remaining"
at_least = 500
fix = "wait for GitHub's hourly reset"

[services.db]
check = "pg_isready -h localhost -p 5432"
restart = "docker compose up -d db"
```

## `[locks]`

Optional. Each `[locks.<name>]` table sets one named lock's `slots`, how many runs may hold it at once, 1 by default. A lock needs no table to work: `colony lock <name> -- <command>` makes it. The locks `tests` and `builds` take this computer's test runs and builds at once as their slots. See [capacity.md](capacity.md#locks).

```toml
[locks.test-db]
slots = 1
```

## `[safety]`

What the merge guard lets agents land, and which branches it protects. See [safety.md](safety.md#the-merge-guard). Both keys take branch names and patterns, such as `release/*`. A table with neither key, or no table, is the safe default: agents merge nothing and open pull requests.

| Key | Default | What it does |
| --- | --- | --- |
| `merge_into` | `[]` | The branches agents may merge pull requests into, such as `["dev"]`. It never allows a push: the push guard refuses every push into a protected branch, named in `merge_into` or not. The guard counts a branch only when both this working copy and the copy on GitHub's default branch name it, read with `gh api`, so it takes effect once you merge it into the default branch. When GitHub can't be read, nothing is allowed. A force push or a deletion of the base stays refused. |
| `protect` | `[]` | More branches no agent may push to, such as `["staging", "release/*"]`. The base and the repo's default branch are always protected. `colony safety protect` puts the same branches under a GitHub ruleset. |

## `[recover]`

What `colony crash-report` and `colony resume` look at. See [safety.md](safety.md#recovery).

| Key | Default | What it does |
| --- | --- | --- |
| `within_hours` | `24` | How far back both look for sessions that showed life. `--within` overrides it. |

Both also read the [`[services]`](#services) tables, the same ones `colony services` checks. The crash report names each one whose check fails, judged by its exit code, `expect`, `at_least` and `at_most` within its `timeout`, and `colony resume` runs its `restart`, then its check again. A table with no `restart` is named, for you to start by hand.

## `[watch]`

Optional. How the team watch, the reporting rhythm, the watchdog and the status page behave. Every key has a default. See [watch.md](watch.md).

| Key | Default | What it does |
| --- | --- | --- |
| `idle_minutes` | `20` | A session that has done nothing this long, with no reason given, is idle, and its lead hears of it. |
| `report_minutes` | `30` | A working helper sends a report at least this often. Its own wait reminds it, and its lead hears when it misses two. |
| `agent_minutes` | `45` | How long a helper's own helper agent may run. The helper hears past it, and its lead past twice it. |
| `intent_hours` | `4` | A wait or a hold with no end time is checked after this long. |
| `late_after` | `1` | A card In progress past this many times its predicted minutes is late, and its lead hears once, and once more at twice that. |
| `every_minutes` | `2` | How often the lead's wait and the watchdog look at the team. |
| `page` | `true` | Whether the watchdog keeps the status page, the pinned `Colony: status` issue. |
| `page_minutes` | `5` | How often the status page may change. |
| `watchdog` | `true` | Whether the lead's wait starts the watchdog when none runs on its computer. |
| `escalate_minutes` | `60` | A lead idle with no helper busy and no reason given, this long past `idle_minutes`, has its person mentioned on GitHub. |
| `quit_hours` | `24` | A watchdog started without `--stay` ends after this long with no session alive on its computer. |

```toml
[watch]
idle_minutes = 30
report_minutes = 45
page = false
```

## Layers

Colony reads three layers, each over the one before, and a table merges key by key:

1. the mode's defaults, in the package's `colony/modes/<mode>.toml`;
2. `.colony/colony.toml`, the team's, which git tracks;
3. `.colony/colony.local.toml`, this computer's own, which git never tracks. The main checkout's counts in every worktree of the clone, and a worktree's own, when it has one, counts over it.

Put a setting only you want here, such as `[checks] caps = { fast = 600 }`, in the local file, so no tracked file changes, and an upgrade or a pull never meets it. `colony config local` makes the file and keeps it out of git; `colony config local --from-edits` moves your uncommitted edits of `.colony/colony.toml` into it. `colony config` shows the layers and every note.

### Old settings

When a release renames or removes a setting, Colony reads the old one at its new place, or skips it, and says so with its replacement, once a day where a lead starts and where a batch starts, and every time in `colony config`. A command never stops on it. `colony config migrate`, which `colony upgrade` runs, rewrites `.colony/colony.toml`: it moves a renamed key and comments out a removed one with the reason.

| Old setting | Now |
| --- | --- |
| `[project] web_checks` | Gone: name each check area's paths in `[checks] areas`, and put `{areas}` in `[project] checks`. |
| `[hack] deploy_environment` | `[project] deploy_environment`. |
| `[people.<person>] prefer_account` | Gone: `[pool] order` and `[people.<person>] accounts` set which account goes first. |
| `[people.<person>] drain` | Gone: `[pool] reserve` keeps an account free, and `[pool] out_at` says when a session switches. |

## `[cards]`

Optional. How the lead's wait treats the lead's queue of To do cards. See [cycle.md](cycle.md#the-leads-queue).

| Key | Default | What it does |
| --- | --- | --- |
| `auto_start` | `"waits"` | Which ready cards the lead's wait starts by itself, for the helper the card's title names, when that helper is live and free: `"waits"`, a card whose `Waits for:` cards just landed; `"all"`, any ready card; `"off"`, none, so the lead hands out each one. |
| `remind_minutes` | `60` | How long before the lead's wait names the same queued card again, while the queue and the free helpers stay the same. |

```toml
[cards]
auto_start = "waits"
remind_minutes = 60
```

## `[testers]`

Optional. How testers share a release's findings list. See [testing.md](testing.md#the-findings-list).

| Key | Default | What it does |
| --- | --- | --- |
| `claim_minutes` | `60` | How long a tester's claim on a card holds with no result. After it, the card is free for another tester, so a tester that stopped never keeps one. |

The test accounts and fixtures the person prepared live in `.colony/fixtures.toml`, which `colony fixtures add` writes. See [testing.md](testing.md#test-accounts-and-fixtures).

## Releases and branch health

Optional. These keys set the release, the merge freeze, the long-lived branches, the shared branch's health, steps for the person, and plain status messages. [releases.md](releases.md) says how each works.

The branches come from `[project]`:

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `integration` | no | `"dev"` | Where the team's work gathers: the branch a release is cut from and comes back into. Default: the base. |
| `release` | no | `"main"` | The branch a release goes into. Default: origin's default branch, when that differs from the integration branch. |
| `deploy_workflow` | no | `"deploy.yml"` | The workflow `colony release --after` watches on the release branch until it ends. |

### `[release]`

| Key | Default | What it does |
| --- | --- | --- |
| `freeze` | `true` | `colony release` freezes the integration branch for every person's leads while the release's checks run. |
| `freeze_hours` | `12` | How long a freeze lasts unless it is lifted first, so a forgotten one never blocks the team for long. |
| `migrations` | `[]` | Paths or globs of the project's migrations, such as `["db/changes/*"]`, besides the ones Colony knows by their path, such as `migrations/` or `.sql`. The release's description lists them. |
| `long_lived` | `[]` | Other long-lived branches each release goes into too, such as `["staging"]`. `colony release --after` and `colony branches --sync` bring the release branch into each. |

### `[health]`

| Key | Default | What it does |
| --- | --- | --- |
| `branches` | the integration branch | The shared branches `colony health` keeps green. |
| `source` | `"auto"` | Where a commit's result comes from: `"ci"` the code host's checks, `"local"` the full suite on this computer, `"auto"` CI when the commit has any checks, else the suite here. |
| `every_minutes` | `60` | How often `colony health watch` looks. |
| `pause` | `true` | A red branch pauses every lead's `colony merge` and `colony batch` until it passes again, except named fixes. |

### `[steps]`

| Key | Default | What it does |
| --- | --- | --- |
| `issue` | `0` | The issue that holds the person steps. `0` finds the open `Colony: person steps` issue, or opens one. |
| `dry_runs` | `{}` | The project's own dry runs, as command starts and their tests, such as `{ "./deploy.sh" = "./deploy.sh --check" }`. They come before the ones Colony knows. |

### `[plain]`

| Key | Default | What it does |
| --- | --- | --- |
| `allow` | `[]` | Words `colony plain check` lets through, such as the project's own names in capitals. |
| `jargon` | `[]` | The team's own shorthand, which `colony plain check` flags. |

```toml
[project]
integration = "dev"
release = "main"

[release]
long_lived = ["staging"]
migrations = ["db/changes/*"]

[health]
source = "ci"
```

## What the sessions' environment holds

Colony sets these for every interactive session: the lead, each builder, the researcher and the spec agent. You don't set them yourself.

| Name | Value |
| --- | --- |
| `COLONY_SESSION` | `lead`, the builder's name, `researcher` or `spec` |
| `COLONY_PERSON` | Whose session it is |
| `COLONY_LEAD` | The lead's name, such as `ana-engine-lead`, on a lead from `colony claim` and on each of its helpers. A helper belongs to this lead. |
| `COLONY_ACCOUNT` | The account Colony opened the session on, which its checks compare with the one it runs on |
| `CLAUDE_CONFIG_DIR` | The picked settings folder, left unset for `~/.claude` |
| `CLAUDE_CODE_RETRY_WATCHDOG` | `1`. Without it, the prompt hook says so once a day. |
| `CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS` | `21600000`, the longest the retry watchdog waits: 6 hours |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | `250000` |

`--dry-run` prints these names, never their values. The hooks run only in a session that has `COLONY_SESSION`. `colony whoami --json` prints the session's name, kind, lead, person and stream for a repo's own tools.
