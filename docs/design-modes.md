# Puffin Colony modes: Hack, Solo, Startup

Setup's first question is the mode, which is `mode = "hack" | "solo" | "startup"` in `[project]`. Each mode's defaults come from `colony/modes/<mode>.toml`, and the repo's colony.toml overrides any key. Today's whole system is `startup`, and an existing config with no mode counts as `startup`.

Ideas taken from azizu06/hackathon-agent-board, which has no license, so we take ideas only and write our own code: a prompt-time hook, @login addresses, an owner table, and an any-agent script.

## The modes

| | Hack | Solo | Startup |
| --- | --- | --- | --- |
| For | A team, hours or a weekend | One person, a small project | A company's whole life cycle |
| Leads | One per person, peer to peer, named `<login>-lead` | One | One per person, with a digest |
| Builders | Optional; each person's lead may open them | Yes | Yes |
| Messages | One pinned board issue, with @login and @all mentions, the prompt hook, instant relay where it runs | Card lines, the prompt hook | Card lines, the coordination issue, the digest, relay |
| Owner table | Yes, per person, in AGENTS.md | No | Optional |
| Gate | The fast check only. `colony merge <branch>` merges into the base after a passing fast check, when setup's yes allows it. `--review` adds one reviewer before the demo | Checks plus a reviewer. The walk is optional | Checks, reviewer and walk, until 0 open |
| Knowledge, specs, research, board, retro | No | No (can be turned on) | Yes |
| Rules | A hack core: about 300 words of honesty, ownership and board duties | lean | lean, puffin or own |
| Setup questions | Team logins and names, who owns which folders, base branch (default main), may agents merge after the fast check (default yes), demo time | Base branch, rules | As today |

## Ownership (helpers work in parallel; touch only your files)

| Helper | Owns |
| --- | --- |
| H1 core | `colony/cli.py`, `colony/batch.py`, `colony/wait.py`, `colony/transport.py`, `colony/modes/*.toml`, a new `colony/merge.py`, `tests/test_modes.py`, `tests/test_merge.py`, plus updates to the existing tests these files break |
| H2 hack content | `colony/prompts/setup.md` (a mode step plus the hack branch), `colony/templates/hack/` (the AGENTS.md board and owner sections and the board issue template), `colony/scripts/board` (a POSIX sh any-agent script), `colony/guards.py` (the prompt hook), `colony/presets/hack/core.md`, `tests/test_hack.py`, `tests/test_board_script.py` |
| H3 docs | README.md (a modes section and a hackathon quick start), `docs/modes.md`, `docs/hackathon.md` (a one-page guide), and updates to how-it-works, configuration and commands |

## Contracts between helpers

- **Unread cache (H1 writes, H2's hook reads).**
  - `colony wait` keeps `~/.colony/<project>/<session>.json`, with a key `unread`: a list of `{card, author, body, url}` for lines addressed to this session (by name, @login or @all) that it hasn't printed yet.
  - The prompt hook prints those lines, then empties `unread`. It makes no network call.
  - When `colony wait` isn't running, the hook makes one ETag-cached `gh api` call, no more than once per 30 seconds.
- **Addresses (H1).** A line is addressed to a session when it starts with `for <name>:`, or contains `@<login>` for the session's person, or `@all`. For a person: in hack mode, their lead receives it. `colony post` and `colony say` accept `@login` as the recipient.
- **Hack board (H2 creates, H1 reads).**
  - Setup creates the issue `Board: <project>` from the template, pins it, and writes its number to `[messages] board = N`.
  - In hack mode, every line goes to the board, not to cards.
  - A post starts with `[<name>'s <agent>]`, as in `[Serdar's Claude]`. `colony post` adds the prefix itself.
- **`colony merge <branch>` (H1).**
  - Only in hack mode, and only when `[gate] merge_after_fast_check = true`.
  - It fetches, merges the branch into the base locally, runs the fast check, and pushes the base only when the check passes.
  - Otherwise it opens a PR. It never force-pushes.
- **The any-agent script (H2).**
  - `colony/scripts/board` is POSIX sh plus `gh` only, so Codex or any agent can take part. Setup copies it to `tools/board` in hack mode.
  - Its commands: `post "<text>"`, `unread`, `wait [--interval S]` (default 30), `read [-n N]` and `whoami`.
  - It writes the same post format, so Claude and non-Claude agents interoperate on one board.

## For every helper

- Standard-library Python 3.11+ (the board script is POSIX sh), with no dependency.
- Never `shell=True`, except for config command strings. Never print env values.
- The whole suite stays green: `uv run --with pytest pytest -q tests`. Startup mode must behave exactly as today, and the existing tests prove it.
- Commit only your files, with `feat(modes): …` or `docs(modes): …`, ending with `Assisted-by: claude-code:claude-fable-5`.
- Don't push, and start no agent.
