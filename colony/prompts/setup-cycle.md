## The cycle: tiers, the board and the Needs issues

1. Read, without asking:
   - Whether the gh login has the project scope: run `gh auth status` and read only its `Token scopes` line, never the token.
   - The folders that hold sign-in, payment, database migration, secret or public API code under a name the built-in risk list misses. That list already matches paths holding words such as `auth`, `login`, `session`, `payment`, `billing`, `migrations/`, `secret`, `.env`, `api/` and `routes/`, and every dependency manifest, CI file and `AGENTS.md`.
   - The knowledge folder the knowledge steps chose, `knowledge/` by default.
2. Add one item to step 2's yes-or-no list: `board`, default yes, "a GitHub Project board for the cards, owned by `<owner>`, with the fields Status, Builder, Tier, State, Last update, Account and Branch". When the login lacks the project scope, say in the same item that the person first runs `gh auth refresh -s project`, which opens the browser to grant it, and that every computer that runs a builder needs the same scope.
3. Write a `[cycle]` table into `{dir}/{name}.toml` only when step 1 found something the defaults miss, and write only those keys:
   - `risk`, the missed folders by kind, such as `risk = { payments = ["src/ledger/"], auth = ["src/iam/"] }`. The kinds are `auth`, `payments`, `migrations`, `secrets`, `deletion`, `public API`, `dependencies` and `config`.
   - `docs`, the documentation folders, when the knowledge folder is not `knowledge/`: `docs = ["<folder>/", "docs/", "{dir}/reports/"]`.
   - `feature_folders`, folders whose new entries are features, when the repo keeps them in a folder not named `features`, `modules`, `routes`, `pages` or `screens`.
   The other keys keep their defaults: `stale_hours = 2.5`, `tiny_code_lines = 100`, `tiny_docs_lines = 300`, `feature_code_lines = 400`.
4. Copy `{package}/prompts/spec.md` and `{package}/prompts/researcher.md` into `{dir}/prompts/`, the briefs the playbook's Spec and Researcher sections start. In each copy, replace `{project}` with the project's name and `{knowledge}` with the knowledge folder, without its last slash. Leave the `The feature:` and `The question:` lines as they are: the lead fills them in each time.
5. When the knowledge folder is not `knowledge/`, write it in place of `knowledge/` in `{dir}/playbook.md`, and change nothing else there.
6. On a yes to `board`, once `{dir}/{name}.toml` is written, run `{name} board init`. Put the board link it prints in the pull request's body. When it fails, say why in one line, and add that the person can run `{name} board init` later.
7. Make no Needs issue: `{name} needs` makes `Needs <Person>` with the first question it posts.
