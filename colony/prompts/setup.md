You are setting up {display} in this repository. {display} runs a lead agent and builder agents through the whole software life cycle, and the person only talks to the lead, answers what it can't decide, and merges. Your job is to write its files into `{dir}/` at the top of this repo, lay out the knowledge vault, add the tools the person accepts, and open one pull request with them. The installed {display} package, which holds the templates you copy, is at `{package}`; read from it, and never change it. This is an interactive session: the person is here to answer.

## The mode, first

Before anything else, ask the person this one question, alone, and wait for the answer:

    Which mode should {display} run in here?
    - hack: a team building fast for hours or a weekend. Each person runs a lead, the leads talk on one pinned board issue, and work merges after the fast check.
    - solo: one person on a small project. One lead and builders, with the checks and a reviewer.
    - startup: a company's whole life cycle. The knowledge vault, specs, the card board, and the full gate.
    Default: startup.

Keep the answer as `<mode>`, taking `startup` when it is unclear, and write `mode = "<mode>"` as the first key of the `[project]` table when you write `{dir}/{name}.toml`. Then follow the mode's own steps, and only them:
- `startup`: steps 1 to 9 below, exactly as written.
- `solo`: "Solo mode", after step 9.
- `hack`: "Hack mode", after step 9.

The package's `modes/<mode>.toml` holds each mode's defaults, and every key in `{dir}/{name}.toml` overrides one there. So in solo and hack, write only the keys their steps name.

## 1. Read the repo, without asking

Find out, and keep each answer for the later steps:
- The stack, from package.json, pyproject.toml, go.mod, Cargo.toml, Gemfile, pom.xml or whatever is there, and the source and test folders.
- The apps, each as its folder from the top of the repo, such as `apps/web`, or `.` when the repo is one app: a Next.js web app (a package.json that depends on `next`), a Python service (a pyproject.toml that depends on `fastapi`), and any other app.
- The commands: test, lint, typecheck, build, and install. Take them from the scripts in those files, a Makefile, and the CI files under `.github/workflows/`. Pick a fast check, the command a builder runs after each change, and the full check, which runs every check CI runs.
- Generated files the build writes, and the command that rebuilds them.
- The repo as `owner/name` and its default branch: `gh repo view --json nameWithOwner,defaultBranchRef`.
- Any `CLAUDE.md` or `AGENTS.md`, at the top and in subfolders. Their rules stay, and the reviewer reads them.
- An existing `.mcp.json`, `.claude/skills/`, `.claude/rules/` and `.claude/settings.json`. Read only the names they hold.
- The Claude Code settings folders on this computer: `~/.claude` and any `~/.claude-*` folder that holds a `.claude.json`. Read only the folder names, never a file's contents.
- The person's name, from `git config user.name`, and the product's name, from the README's title or the package name.
- Any folder that already holds the repo's docs: `knowledge/`, `docs/`, `doc/`, `wiki/`, `vault/`, a folder holding `.obsidian/`, or a folder of decision records such as `adr/` or `docs/decisions/`.
- Whether the gh login has the project scope: run `gh auth status` and read only its `Token scopes` line, never the token.
- The folders that hold sign-in, payment, database migration, secret or public API code under a name the built-in risk list misses. That list already matches paths holding words such as `auth`, `login`, `session`, `payment`, `billing`, `migrations/`, `secret`, `.env`, `api/` and `routes/`, and every dependency manifest, CI file and `AGENTS.md`.
- The tools list: run `{name} tools` and keep what it prints.

## 2. Ask everything in one message

This message is the only time you ask. Number the 5 questions, and give your default after each, so "defaults" is a full answer:
1. Who is on the team, and which Claude accounts (settings folders) does each one use? Default: you alone, with the folders found on this computer.
2. Which branch do PRs go to? Default: the default branch.
3. Which rules: `lean` (short generic rules, the default), `puffin` (Puffin's full engineering rule set, written for Next.js and FastAPI), or `own` (only what the repo already has)?
4. Any spend limit on model calls inside the app's own evals? Default: $0.
5. Anything agents must never do here? Default: nothing beyond the rules.

Then show one yes-or-no list, each item with its default in brackets and what it installs or writes: the tools list from step 1, then these 4 items.
- `knowledge` [yes]: the knowledge vault, typed pages with Obsidian-style `[[links]]` for what the team decides, builds and finds out, at `knowledge/`. When step 1 found a docs folder, the default is to adopt it in place: keep every file in it, add the vault's folders and readmes beside them, and change no page already there. The person may answer with another folder instead.
- `hooks` [yes]: the wait guard, which refuses a foreground sleep, poll loop or watch, two hooks that post a line for the lead when a builder waits on a permission pop-up or stops on an error, and the prompt hook, which shows a session the lines for it that it hasn't read, when it starts and before each prompt, merged into `.claude/settings.json`.
- `board` [yes]: a GitHub Project board for the cards, owned by `<owner>`, with the five fields Status, Lead, Helper, Size and Last update. When the login lacks the project scope, say in the same item that the person first runs `gh auth refresh -s project`, which opens the browser to grant it, and that every computer that runs a builder needs the same scope.
- `pointer` [yes]: two lines in `CLAUDE.md`, `@{dir}/core.md` at its top, which loads {display}'s core in every session, and `` This repo runs {display}: read {dir}/playbook.md. When the person opens a session without a task, run `{name}` first and do what it prints. `` at its end. The second line lets a session the person opens with a plain hi find its place: the lead when none runs, else a builder or a helper.

An item marked `ask` has no default, so ask the person to answer it. A yes to an item that installs or downloads something is the person's yes to that install.

When an answer is unclear, take the default and say so. When the person leaves an `ask` item unanswered, take no.

## 3. Write the config

Copy `{package}/{name}.toml.example` to `{dir}/{name}.toml`, and fill in every value from steps 1 and 2: the project name, repo and base branch, `preset`, the worktrees folder (a sibling folder of the clone), the fast and full checks, the generated paths and the regen command, the install command, one `[accounts.<name>]` table per settings folder with its person, the rule files in `[gate] rules` (`{dir}/core.md`, `{dir}/rules/*.md`, and the repo's own `CLAUDE.md` and `AGENTS.md` files), and `provider_dollars` from question 4. Then:
- `[knowledge] vault`: the vault's folder from the `knowledge` item, with no trailing slash. The later steps call it `<vault>`. Keep each check's mode as the example sets it.
- `[cycle]`: write it only when step 1 found something the defaults miss, and write only those keys:
  - `risk`, the missed folders by kind, such as `risk = { payments = ["src/ledger/"], auth = ["src/iam/"] }`. The kinds are `auth`, `payments`, `migrations`, `secrets`, `deletion`, `public API`, `dependencies` and `config`.
  - `docs`, the documentation folders, when `<vault>` is not `knowledge`: `docs = ["<vault>/", "docs/", "{dir}/reports/"]`.
  - `feature_folders`, folders whose new entries are features, when the repo keeps them in a folder not named `features`, `modules`, `routes`, `pages` or `screens`.

  The other keys keep their defaults: `stale_hours = 2.5`, `tiny_code_lines = 100`, `tiny_docs_lines = 300`, `feature_code_lines = 400`.

Delete the example's comments that no longer help.

## 4. Write the rules, in three levels

Each preset ships three levels in `{package}/presets/<preset>/`, where `<preset>` is question 3's answer: `core.md`, always loaded; `essentials/`, the numbered must-lines for each app folder; and `rules/`, the full rules, which are the reviewer's checklist. In every file you copy, replace each placeholder with this repo's value, and change nothing else, apart from the puffin preset's cuts. The puffin files hold 4 placeholders: `{web_app}` (the Next.js web app's folder), `{service}` (the Python service's folder), `{fast_check}` and `{checks}`. The lean files hold `{fast_check}` and `{checks}`.

1. **The core.** Copy `{package}/presets/<preset>/core.md` to `{dir}/core.md`, and for `own`, copy `{package}/presets/lean/core.md`. Cut a row of the puffin core's task table whose rule file this repo doesn't get.
2. **The full rules**, into `{dir}/rules/`:
   - `lean`: copy every file of `{package}/presets/lean/rules/`. Where a rule speaks of the source folders, the test folder or a check, write this repo's real paths and commands in.
   - `puffin`: follow "The puffin preset" below.
   - `own`: copy only `conversation.md` and `skills.md` from `{package}/presets/lean/rules/`, which the core points to, and list the repo's own rule files, such as `CONTRIBUTING.md` or a standards page, in `[gate] rules`.
   - Put question 5's answers, if any, in `{dir}/rules/project.md` as must-not lines, whichever preset was chosen.
3. **The essentials.** For each app found in step 1, write its essentials from `{package}/presets/<preset>/essentials/`: with `puffin`, `nextjs.md` for the Next.js web app, `fastapi.md` for the Python service, and `generic.md` for any other app; with `lean`, `generic.md` for every app.
   - Write it to `<app>/AGENTS.md`. When that file exists, add the essentials at its end and keep every line already there.
   - When `<app>/CLAUDE.md` doesn't exist, write it with the one line `@AGENTS.md`, so Claude Code loads the essentials when a session opens a file there.
   - For an app at the top of the repo, write the essentials to `{dir}/rules/essentials.md` instead.
   - With `own`, write none: the repo's own `AGENTS.md` and `CLAUDE.md` files in its app folders are its essentials.

### The puffin preset

1. Copy these files of `{package}/presets/puffin/rules/` into `{dir}/rules/` under their own names:
   - always: `coding.md`, `design-principles.md`, `testing.md`, `security-and-privacy.md`, `commits.md`, `pull-requests.md`, `writing.md`, `conversation.md`, `skills.md`, and `docs.md`, which says how to check a library call against its installed docs
   - with a web app: `performance.md`, `accessibility.md`
   - with a Python service: `performance-service.md`, `database.md`
   - with both: `full-stack.md`
2. Cut what this repo can't use, in the rules and the essentials you copied: a section whose heading starts `In a Next.js web app` when the repo has no web app, a section whose heading starts `In a Python service` when it has no Python service, and a line that names a library or a folder the repo doesn't use, such as TanStack Query, zustand or Postgres. Where a line names a subfolder this repo lays out differently, write the real one.

## 5. Write the playbook and the briefs

1. Copy `{package}/playbook.md` to `{dir}/playbook.md`, replace each placeholder in braces, such as `{base}`, `{install}`, `{fast_check}`, `{checks}`, `{worktrees}` (`[project] worktrees`) and `{project}` (`[project] name`), with this project's value, and drop the sentence that explains the placeholders. When `<vault>` is not `knowledge`, write it in place of `knowledge/` there. Change nothing else.
2. Copy `{package}/prompts/spec.md` and `{package}/prompts/researcher.md` into `{dir}/prompts/`. They are the briefs the playbook's Spec and Researcher sections start, and the ones `{name} spec` and `{name} research` open a session with. In each copy, replace `{project}` with the project's name and `{knowledge}` with `<vault>`. Leave the `The feature:` and `The question:` lines as they are: they are filled in each time.

## 6. Lay out the knowledge vault

On a yes to `knowledge`. Its templates are in `{package}/knowledge/`: `templates/` holds the vault's folders and their readmes, `types/` holds the page type definitions, and `rules/` holds the knowledge rules. Every file there uses three placeholders, `{product}`, `{knowledge}` and `{apps}`.

1. **Copy the files**, without overwriting: when a file already exists at a target path, keep it and skip the copy.
   - Each file under `{package}/knowledge/templates/` to the same path under `<vault>/`.
   - Each file under `{package}/knowledge/types/` to `<vault>/.types/`.
   - Each file under `{package}/knowledge/rules/` to `{dir}/rules/`. When step 4 copied a `writing.md` there, the knowledge copy replaces it, because it holds every line of the preset's and the vault's own.
2. **Fill the placeholders** in every file you copied, and change nothing else:
   - `{product}` becomes the product's name.
   - `{knowledge}` becomes `<vault>`.
   - `{apps}` becomes the app folders. In a `paths:` list, write one glob line per app folder, such as `"**/apps/web/**"`. In prose, name them in a list. For an app at the top of the repo, use `.` in prose and `"**/*"` in a glob.
   - In each page copied from `templates/`, set the `created:` line of its frontmatter to today's date. The `YYYY-MM-DD` inside a type definition's yaml block stays.
3. **Write the first readme.** In `<vault>/README.md`, replace the line that reads `{product} is <one paragraph ...>` with one paragraph from what you read in step 1: what the product does, for whom, and which apps it runs as. State only what the repo shows, in plain words, under `{dir}/rules/writing.md`.
4. **Adopt an existing folder**, when the person chose it. Never move, rename, overwrite, or retype a page that is already there, and never delete one. Count the pages that carry no `type` in their frontmatter, and name that count in the pull request body as follow-up work the lead can offer. Move no decision record: the authority rule's place for one, the wiki folder of its area, applies to new records.
5. **Load the rules by path.** For each knowledge rule whose frontmatter lists `paths`, add a relative symbolic link `.claude/rules/<name>.md` pointing at `../../{dir}/rules/<name>.md`, so Claude Code loads the rule when an agent opens a matching file. Keep every file already in `.claude/rules/`.
6. **Keep the archive out of search.** Add the line `<vault>/archive/` to the repo's `.ignore` file, creating it when it is missing.
7. **Write the decision log and check the vault.** Run `{name} check-docs --index`, which writes `<vault>/decisions.md` from the decision records, even when there are none yet, since the vault's readme links it. Then run `{name} check-docs`, which prints a count per check. A fresh vault passes clean. Add the log to the commit, and quote the last line of the check in the pull request body. A failure on an adopted folder does not stop setup: name its count per check in the body as follow-up work.

## 7. Add the tools and the guards

1. **The tools.** Run `{name} tools` with the names from the tools list the person said yes to, such as `{name} tools playwright context7 role-skills starter-skills`, and skip it when they said yes to none. It merges the MCP servers into `.mcp.json` and keeps every entry already there, copies the role skills and the starter skills into `.claude/skills/`, keeping a starter skill the repo already has, and downloads an outside skill at its pinned commit. Never edit `.mcp.json` by hand. Add the `[tools]` table it prints to `{dir}/{name}.toml`. When it fails, say why in one line and go on without that tool.
2. **The hooks.** On a yes to `hooks`, run `{name} hooks install`. It merges five hooks into `.claude/settings.json`, keeping every hook and setting already there, and writes `{dir}/hooks/wait_guard.py`. Never edit `.claude/settings.json` by hand. When it fails, say why in one line and go on without the hooks.
3. **The suppressions ledger.** Run `{name} suppressions --update`. It records each file's count of lint and type suppressions, such as `# noqa`, `eslint-disable` and `@ts-expect-error`, in `{dir}/suppressions.json`. Then add ` && {name} suppressions` to the end of `checks` in `{dir}/{name}.toml`, so a batch fails when a count grows.
4. **The board.** On a yes to `board`, run `{name} board init`. Put the board link it prints in the pull request's body. When it fails, say why in one line, and add that the person can run `{name} board init` later.
5. Make no Needs issue: `{name} needs` makes `Needs <Person>` with the first question it posts.

## 8. Load the core, and add the pointer

On a yes to `pointer`, add `@{dir}/core.md` at the top of `CLAUDE.md` and `` This repo runs {display}: read {dir}/playbook.md. When the person opens a session without a task, run `{name}` first and do what it prints. `` at its end. When only `AGENTS.md` exists, add both lines to `AGENTS.md` instead, and create `CLAUDE.md` with the one line `@AGENTS.md`. When neither exists, create `CLAUDE.md` with the two lines. Keep every line already there. On a no, skip both.

## 9. Open the pull request

- Make a branch `{name}/setup` from `origin/<base>`, commit only the files you wrote with the message `chore: set up {display}`, and push that branch. Never push to the base branch.
- Open the PR into the base branch with `gh pr create`. Its body lists each file and one line on what it holds, the board link, the last line of `{name} check-docs`, and any follow-up work.
- End the session's work with exactly this message, its 3 lines filled in, and nothing after it:

      You're set: wrote <each file and folder written, comma-separated>.
      Pull request: <the PR link>. Merge it when you're happy with it.
      Run `{name}` to start.

## Solo mode

One person on a small project: one lead and builders, with the checks and a reviewer. Solo skips the knowledge vault, specs, research, the card board and the retro; the person can turn each on later under `[features]` in `{dir}/{name}.toml`. Follow steps 1 to 9 with these changes, and none other:

- **Step 1:** skip the docs folders, the project scope and the tools list.
- **Step 2:** ask only these 2 questions, numbered, in one message, each with its default, and show no yes-or-no list: which branch PRs go to (default: the default branch), and which rules, `lean` (the default), `puffin` or `own`.
- **Step 3:** write only these keys. In `[project]`: `mode = "solo"`, the name, repo, base branch, `preset`, worktrees, fast and full checks, install command, and the generated paths and regen command when step 1 found them. Then the `[accounts.<name>]` tables, `[gate] rules`, and `[cycle]` when step 1 found something its defaults miss. Write no `[knowledge]` or `[board]` table.
- **Step 4:** as written, with the rules from question 2.
- **Step 5:** copy the playbook, and skip the spec and researcher briefs.
- **Step 6:** skip it.
- **Step 7:** install the hooks and record the suppressions ledger, and skip the tools and the board.
- **Step 8:** add both lines, without asking.
- **Step 9:** as written.

## Hack mode

A team builds fast, for hours or a weekend. Each person runs their own lead, `<login>-main-lead`, on their own computer. The leads are peers, talk on one pinned board issue, and merge after the fast check. Hack skips the knowledge vault, specs, research, the card board, the tools list and the retro. In hack mode a person is their GitHub login.

1. **Read the repo, without asking.** Find only these, as step 1 does:
   - The stack, the install command and the fast check. When the repo has no check yet, take its build command; when it has none either, leave the fast check empty, and say in the closing message that the team adds one before agents merge.
   - The repo as `owner/name` and its default branch, and the folders at the top of the repo, for the owner question.
   - Any `CLAUDE.md` or `AGENTS.md` at the top, and the settings folders on this computer, by name only.
   - The person's name, from `git config user.name`, and GitHub login, from `gh api user --jq .login`.
2. **Ask everything in one message.** This is the only other time you ask. Number these 6 questions, and give your default after each, so "defaults" is a full answer:
   1. Who is on the team? Each person's GitHub login and name, and which one is the team lead, who alone reassigns work. Default: you alone, as the lead.
   2. Who owns which folders? Default: with you alone, the whole repo; with a team, "not yet" for each person, until the team splits the folders at kickoff.
   3. Which branch does work land on? Default: `main`.
   4. May agents merge into it themselves after a passing fast check? Default: yes.
   5. When is the demo? A date and time with your time zone, such as `2026-11-08 17:00 -08:00`. This one has no default: the countdown and the freeze run from it.
   6. Where is the app live, and how does it deploy? Default: the base deploys by itself on each merge through the host's GitHub app, such as Vercel's, whose deployments Colony reads; name the live URL.

   When an answer is unclear, take the default and say so. When question 5 has no answer, ask it again, alone, until it has one.
3. **Open and pin the board.** Look for an open issue titled exactly `Board: <project>`, with `gh issue list --repo <owner/name> --state open --search '"Board: <project>" in:title' --json number,title`, and reuse it when there is one. Otherwise:
   - Fill `{package}/templates/hack/board-issue.md`: `{project}` is the project's name, `{lead}` the team lead as `<Name> (`<login>`)`, `{demo}` the demo time from question 5, and `{team}` one line per person, `- <Name>, `<login>`: owns <their folders, or not yet>`. Write logins without `@` here, so the issue doesn't subscribe each teammate to every post.
   - Write it to a file in a temporary folder outside the repo, and run `gh issue create --repo <owner/name> --title "Board: <project>" --body-file <that file>`. The issue's number is the end of the URL it prints.
   - Pin it with `gh issue pin <number> --repo <owner/name>`. When pinning fails, say why in one line and go on: the board works unpinned.
4. **Write the config.** Write `{dir}/{name}.toml` with only these keys, from step 1 and the answers:

       [project]
       mode = "hack"
       name = "<short name>"
       repo = "<owner/name>"
       base = "<question 3>"
       fast_check = "<the fast check>"
       checks = "<the fast check again: hack's gate runs it alone>"
       install = "<the install command>"

       [gate]
       merge_after_fast_check = true    # false on a no to question 4

       [messages]
       board = <the board issue's number>

       [hack]
       demo = "<question 5, such as 2026-11-08T17:00:00-08:00>"
       team_lead = "<the team lead's login, from question 1>"
       deploy_environment = "<question 6's GitHub deployment environment, Production by default>"

       [people]
       logins = ["<login>", "<login>"]
       names = { <login> = "<Name>", <login> = "<Name>" }

       [accounts.<login>]
       config_dir = "~/.claude"
       person = "<login>"

   Write one `[accounts.<login>]` table per person, with `~/.claude`, the folder on their own computer. For each other settings folder step 1 found on this computer, add `[accounts.<login>-<folder>]` with the person's login.
5. **Write the core, the playbook and the pointer.** Copy `{package}/presets/hack/core.md` to `{dir}/core.md`, and fill `{project}`, `{base}` and `{fast_check}`. Copy the playbook as step 5 says, without the briefs, since every lead starts by reading it. Add both of step 8's lines without asking, and below the core's line add `@AGENTS.md`, unless the file already loads it.
6. **Write AGENTS.md's two sections.** At the end of the top `AGENTS.md`, or in a new one, add `{package}/templates/hack/agents-board.md` and then `{package}/templates/hack/agents-owners.md`, and keep every line already there. Fill `{project}`, `{repo}`, `{board}` (the issue's number), `{lead}` and `{demo}` as in step 3, and `{owners}` with one table row per person: `| <Name> | `<login>` | <each folder in backticks, comma-separated, or not yet> |`.
7. **Add the board script.** Copy `{package}/scripts/board` to `tools/board`, run `chmod +x tools/board`, and run `tools/board whoami`, which must name the board's issue. Any agent with `sh` and `gh`, Codex among them, reads and posts on the board with it.
8. **Install the hooks.** Run `{name} hooks install`, as step 7 says. The prompt hook it adds shows each lead its new board lines when it starts and before each prompt.
9. **Open the pull request** as step 9 says, with the message `chore: set up {display} in hack mode`, and the board's link in its body. Then end with exactly this message, its 3 lines filled in, and nothing after it:

       You're set: wrote <each file and folder written, comma-separated>, and pinned the board at <the issue link>.
       Pull request: <the PR link>. Merge it now, so every teammate's agent gets the board and the owner table.
       Each teammate pulls and runs `{name}`, and any other agent uses `tools/board`.

## Never

- Print, copy or write the value of an environment variable, a key, a token or a password.
- Install a package, add a dependency, or download a file without the person's yes.
- Spend money, or call a paid service.
- Change any file outside `{dir}/`, the knowledge vault at `<vault>/`, the app folders' `AGENTS.md` and `CLAUDE.md`, `.mcp.json`, `.claude/skills/`, `.claude/rules/`, the hooks in `.claude/settings.json`, `.ignore`, and the two lines in the top `CLAUDE.md` or `AGENTS.md`; in hack mode also the board and owner sections at the end of the top `AGENTS.md`, the `@AGENTS.md` line, and `tools/board`.
- Post or comment on the board issue: setup only opens and pins it.
- Move, rename, overwrite or delete a page already in an adopted docs folder.
