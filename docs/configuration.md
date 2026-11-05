# Configuration

Colony keeps its settings in `.colony/colony.toml` at the root of your repo. Setup writes it from [`colony/colony.toml.example`](../colony/colony.toml.example) and fills in every value, so you rarely edit it by hand. When you do, commit the change like any other file: every machine reads the same settings.

Paths may start with `~`. Every command checks the required keys when it starts, and names the missing one in a single line, such as `colony.toml: [project] needs 'checks'`.

## `[project]`

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `name` | yes | `"myapp"` | A short name. It starts session titles (`myapp-lead`), branch names (`myapp/batch-2026-11-05`) and worktree names. |
| `repo` | yes | `"owner/myapp"` | The GitHub repo, as `owner/name`. Cards, lines and PRs live here. |
| `base` | yes | `"main"` | The branch PRs go to. Colony never pushes to it. |
| `preset` | no | `"lean"` | The rules setup copied: `lean`, `puffin` or `own`. A record for you; the commands don't read it. |
| `max_builders` | no | `4` | How many builders the lead opens on this machine. More join from other computers with `colony join`. |
| `worktrees` | yes | `"~/worktrees"` | Where batches and fixers make their worktrees. Pick a folder outside the clone. |
| `fast_check` | no | `"npm test"` | A builder's quick check after each change. Setup writes it into the playbook. |
| `checks` | yes | `"npm run lint && npm run typecheck && npm test"` | The full check a batch runs. It runs through your shell, so `&&` works. |
| `web_checks` | no | `"npm run lint && npm test"` | A lighter check for a round that changed no `backend_paths` file, once a full run has passed. Empty means every round runs `checks`. |
| `backend_paths` | no | `["api/", "server/"]` | Path prefixes whose change needs the full checks. A fixer whose findings touch them runs the full checks too. |
| `generated` | no | `["src/generated/*"]` | Globs for files a build writes. When a merge conflicts only in these, Colony takes the card's side and runs `regen`. |
| `regen` | no | `"npm run codegen"` | The command that rebuilds the generated files. |
| `check_env_file` | no | `"~/.config/myapp/check.env"` | A local file of `KEY=VALUE` lines added to the checks' environment. A relative path starts at the repo root. Keep it out of git. Colony never prints its values. |
| `install` | no | `"npm ci"` | Runs in each new worktree: the batch's, the walker's and each fixer's. |

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

**How a session picks its account.** The person is `--person`, else `$COLONY_PERSON`, else the one person the file names, else the one whose name matches your git user. Among that person's accounts and the `any` ones, folders this computer has come first. The lowest saved 5-hour usage wins, and the earlier table wins a tie. With no saved usage, the first one wins.

Most teams list one account per person. Spreading one person's work across several seats may conflict with [Anthropic's terms](https://www.anthropic.com/legal), so check them before you list more than one for yourself.

## `[roles]`

Each of the five roles needs a `model` and an `effort`.

| Role | Runs as | Default effort | What it does |
| --- | --- | --- | --- |
| `lead` | interactive | `high` | Talks with you, writes cards, merges, runs the gate |
| `builder` | interactive | `medium` | Builds one card at a time |
| `reviewer` | headless, fresh each round | `high` | Reviews the round's diff against the rubric and rules |
| `walker` | headless | `medium` | Walks the changed flows in a browser |
| `fixer` | headless, one per card | `medium` | Fixes the findings routed to its card |

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `model` | yes | `"claude-opus-5-5"` | The model the role runs on |
| `effort` | yes | `"medium"` | Claude Code's effort level for the role, such as `medium` or `high` |
| `agent` | no | `"ui-check"` | For a headless role, a Claude Code subagent to run as (`claude -p --agent <name>`). The lead and builders ignore it. |

```toml
[roles]
lead     = { model = "claude-opus-5-5", effort = "high" }
builder  = { model = "claude-opus-5-5", effort = "medium" }
reviewer = { model = "claude-opus-5-5", effort = "high" }
walker   = { model = "claude-opus-5-5", effort = "medium", agent = "ui-check" }
fixer    = { model = "claude-opus-5-5", effort = "medium" }
```

## `[gate]`

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `rubric` | yes | `["bugs", "security and privacy", "tests", "performance", "accessibility"]` | The reviewer's checklist. Its report gives each item's open count. It is a checklist, not a score. |
| `rules` | no | `[".colony/rules/*.md", "CLAUDE.md"]` | The files the reviewer checks against. Setup lists the preset's rules and your own `CLAUDE.md` and `AGENTS.md`. |
| `max_rounds` | yes | `5` | The most rounds a batch runs. A last round that still has findings stops the batch. |
| `walk` | yes | `true` | Whether to walk the changed screens in a browser. Set `false` for a repo with no web UI. |
| `walk_paths` | no | `["web/", "app/"]` | Path prefixes. A round that changes none of them skips the walk, unless the last walk failed. Empty walks every round. |

## `[budget]`

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `provider_dollars` | yes | `0` | Model spend allowed inside your app's own checks and evals. Raise it only with the person's yes. |

At `0`, the checks run without `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` in their environment. Above `0`, those keys stay for the checks. Colony reads only whether the value is 0. Agents treat any spend above it as a stop-list item that needs your yes.

Whatever the budget, Colony removes `ANTHROPIC_API_KEY` from the reviewer's, walker's and fixers' environment, so they always run on your Claude Code login and never bill an API key. The lead and builders inherit the shell you start `colony` from, so start it from a shell without that key.

## `[messages]`

How lines travel between sessions. See [messages.md](messages.md).

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `transport` | no | `"github"` | How lines travel. `"github"`, the default, posts and polls issue comments. `"relay"`, delivery through Agent Relay with GitHub as the record, is on the [roadmap](roadmap.md) and stops the wait until it is built. |
| `lead_digest_minutes` | no | `10` | How long the lead's wait gathers lines before it prints them as a digest. A line that can't wait prints at once: `urgent:`, `blocked:` and `question:` lines, your lines, and `done` for a card the batch waits on. |

## `[people]`

| Key | Required | Example | What it does |
| --- | --- | --- | --- |
| `logins` | no | `["ana-gh", "ben-gh"]` | The team's GitHub logins. Agents post through their person's own login, so the lead tells a person's line from an agent's by its signature. A line signed with one of these logins counts as a person's line, and reaches the lead at once. |

## Keys the example leaves out

| Table | Key | What it does |
| --- | --- | --- |
| `[project]` | `trailer` | The line every batch and fixer commit ends with. Default: `Assisted-by: claude-code:<the fixer's model>`. |

## What the sessions' environment holds

Colony sets these for the lead and each builder. You don't set them yourself.

| Name | Value |
| --- | --- |
| `COLONY_SESSION` | `lead`, or the builder's name |
| `COLONY_PERSON` | Whose session it is |
| `CLAUDE_CONFIG_DIR` | The picked settings folder, left unset for `~/.claude` |
| `CLAUDE_CODE_RETRY_WATCHDOG` | `1` |
| `CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS` | `21600000`, the longest the retry watchdog waits: 6 hours |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | `250000` |

`--dry-run` prints these names, never their values.

## Added in 0.1

| Key | Default | What it does |
| --- | --- | --- |
| `budget.use_api_key` | `false` | `true` lets sessions bill `ANTHROPIC_API_KEY`. Otherwise Colony drops it, so sessions use the account's subscription. |
