### The rule levels, the guards and the skills

Every preset arrives in three levels, and setup writes each one: the core, always loaded; the essentials, one `AGENTS.md` per app folder; and the full rules in `{dir}/rules/`, the reviewer's checklist. Add two items to step 2's yes-or-no list:

- `hooks`, default yes: the wait guard, which refuses a foreground sleep, poll loop or watch, and two hooks that post a line for the lead when a builder waits on a permission pop-up or stops on an error, merged into `.claude/settings.json`.
- `starter-skills`, default yes: {display}'s starter skills, copied from the package into `.claude/skills/`: diagnosing-bugs, tdd, code-review, resolving-merge-conflicts, retro, implement-spec, prototype, grill-me, writing-for-agents and git-guardrails.

Follow these steps once `{dir}/{name}.toml` is written. `<preset>` is the preset from question 3.

1. **The core.** Copy `{package}/presets/<preset>/core.md` to `{dir}/core.md`, and for `own`, copy `{package}/presets/lean/core.md`. Fill its placeholders, `{fast_check}` and `{checks}` in the puffin core, with this repo's values, and cut a row of the puffin core's task table whose rule file this repo doesn't get. Change nothing else.
   - On a yes to `pointer`, load the core in every session: add the line `@{dir}/core.md` at the top of `CLAUDE.md`. When only `AGENTS.md` exists, add the line at the top of `AGENTS.md`, and create `CLAUDE.md` with the one line `@AGENTS.md`. When neither exists, create `CLAUDE.md` with the import line and the pointer line. Keep every line already there.
   - Add `{dir}/core.md` to `[gate] rules`, so the reviewer checks against it.
2. **The essentials.** For each app found in step 1, write its essentials from `{package}/presets/<preset>/essentials/`: with `puffin`, `nextjs.md` for the Next.js web app, `fastapi.md` for the Python service, and `generic.md` for any other app; with `lean`, `generic.md` for every app. Fill `{fast_check}` and `{checks}`, and the puffin files' other placeholders, with this repo's values.
   - Write it to `<app>/AGENTS.md`. When that file exists, add the essentials at its end and keep every line already there.
   - When `<app>/CLAUDE.md` doesn't exist, write it with the one line `@AGENTS.md`, so Claude Code loads the essentials when a session opens a file there.
   - For an app at the top of the repo, write the essentials to `{dir}/rules/essentials.md` instead.
   - With `own`, write none: the repo's own `AGENTS.md` and `CLAUDE.md` files in its app folders are its essentials.
3. **The rules.** With `lean`, copy every file of `{package}/presets/lean/rules/` into `{dir}/rules/`. With `puffin`, copy the files "The puffin preset" names from `{package}/presets/puffin/rules/`, and always `docs.md`, `conversation.md` and `skills.md`. With `own`, copy only `conversation.md` and `skills.md` from `{package}/presets/lean/rules/`, which the core points to, and list the repo's own rule files, such as `CONTRIBUTING.md` or a standards page, in `[gate] rules`.
4. **The hooks.** On a yes to `hooks`, run `{name} hooks install`. It merges three hooks into `.claude/settings.json`, keeping every hook and setting already there, and writes `{dir}/hooks/wait_guard.py`. Never edit `.claude/settings.json` by hand. When it fails, say why in one line and go on without the hooks.
5. **The suppressions ledger.** Run `{name} suppressions --update`. It records each file's count of lint and type suppressions, such as `# noqa`, `eslint-disable` and `@ts-expect-error`, in `{dir}/suppressions.json`. Then add ` && {name} suppressions` to the end of `checks` in `{dir}/{name}.toml`, so a batch fails when a count grows.
6. **The starter skills.** On a yes to `starter-skills`, run `{name} tools starter-skills`. It copies each skill from the package into `.claude/skills/`. `{dir}/rules/skills.md` says which skill fits which task.
