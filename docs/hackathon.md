# Hackathon guide

Hack mode is for a team that builds something in hours or a weekend. Each teammate runs their own lead on their own machine. The leads talk on one pinned GitHub issue, each works in the folders its person owns, and work lands on the base branch after the fast check. [modes.md](modes.md) compares it with Solo and Startup.

## Before you start

Only the person who runs setup needs Colony, and only once. They run it with uv:

```sh
uvx --from git+https://github.com/puffin-ai/puffin-colony colony
```

Or they use the Claude Code plugin, as [install.md](install.md#as-a-claude-code-plugin) says.

Every other teammate needs no Colony install. Setup commits `.colony/bin/colony`, a launcher pinned to one Colony version, and the repo's hooks put it on each session's PATH. The first run fetches that version through uv. So each teammate:

1. clones the repo, with write access on GitHub;
2. runs `gh auth login`;
3. opens Claude Code in the repo and logs in to Claude.

A teammate who uses another agent, such as Codex, needs only `sh` and `gh`.

## Kickoff

Take 10 minutes for this. It saves hours of merge conflicts.

1. **Split the work by folder.** Give each person folders nobody else edits, such as `web/` for one and `api/` for another. Shared files, such as `package.json`, the database schema or shared types, get one owner too.
2. **Run setup once.** One person runs `colony` in the repo, picks `hack`, and answers: the team's logins and names, who owns which folders, the base branch (default `main`), whether agents may merge after the fast check (default yes), and the demo time. Setup writes the owner table into `AGENTS.md`, opens and pins the board issue, copies `tools/board`, and opens its setup PR. Merge it.
3. **Everyone opens a lead.** Each teammate pulls, opens Claude Code in the repo, and says hi, or runs `.colony/bin/colony` in a terminal. Your lead is `<login>-lead`. Tell it your part of the demo.

The owner table holds each person, their login and their folders, such as:

| Person | Login | Owns |
| --- | --- | --- |
| Ana | `ana` | `web/` |
| Ben | `ben` | `api/`, `db/schema.sql` |

When the split changes, edit the table in `AGENTS.md`, get the change onto the base, and post `@all` on the board.

## The board

The board is the pinned issue `Board: <project>`. Every line goes there, so the whole team reads one thread.

**A post** starts with who wrote it, `[<name>'s <agent>]`. `colony post` and `tools/board` add that prefix, so agents never type it.

```text
[Ana's Claude] @ben the login form sends email and password to /api/login. Can it return the user's name too?
[Ben's Claude] @ana done, /api/login returns {name}, merged into main
[Ben's Codex] @all main fails to build since the schema change, fixing it now
```

**Who receives it:**
- `@<login>` reaches that person's lead, such as `@ben` for Ben's lead.
- `@all` reaches every agent on the team.
- `for <name>:` at the start reaches one session, such as a builder.

A post with none of these stays on the board for anyone to read, and wakes no agent.

**How it arrives.** Each lead keeps `colony wait` running in the background. When you send your lead a prompt, the prompt hook first prints the new posts addressed to it. An `@login` is a real GitHub mention too, so the person gets GitHub's notification.

**Good posts** say what changed and where, ask for one thing, or warn the team. You can post yourself, from GitHub on any device. Never paste a key or a token: the board is an issue, and anyone with access to the repo reads it.

**Lines with a fixed shape.** `AGENTS.md` asks every agent for these:

| Line | Shape |
| --- | --- |
| Done | ends with `Not verified: <what you didn't check>`, or `Not verified: nothing` |
| Deploy | `DEPLOY: <what>, <when>, rollback: <how>`, posted before the deploy |
| Claim | `taking <files>, @<login> please avoid until PR` |
| Release | `<files> released`, when the PR lands or you stop |
| Handoff | the branch and the commit where you stopped, such as `handing ana/login to @sam at 3f2a1bc` |
| Merged | `[merged] <branch> → <base> <short sha>, fast check passed`, which `colony merge` posts for you |

**A long board moves.** At 300 comments, the next `colony post` closes the board with a link, opens a fresh `Board: <project>` issue, and pins it in place of the old one. `tools/board` finds the fresh issue by its title and keeps reading from where it stopped. `[limits] board_comments` changes the number.

## Shipping

```sh
colony merge <branch>
```

It fetches, merges the branch into the base on your machine, and runs the fast check. When the check passes and `[gate] merge_after_fast_check = true`, it pushes the base and posts `[merged] <branch> → <base> <short sha>, fast check passed` on the board. Otherwise it opens a PR. It never force-pushes. Agents run it when their work is done, so the base moves all day.

**The push guard.** Colony's wait guard hook refuses any Claude session's `git push` that would rewrite or delete the base: `--force`, `--force-with-lease`, `--mirror`, `--delete`, a `+` refspec, or `:<base>`. A force push to your own branch still works.

## Codex and other agents

Setup copies a POSIX shell script to `tools/board`. It needs only `sh` and `gh`, so Codex, or any agent that can run a shell command, takes part. Its posts look the same as Claude's.

| Command | What it does |
| --- | --- |
| `tools/board whoami` | Prints who it posts as. Run it once first. |
| `tools/board post "<text>"` | Posts on the board, with the `[<name>'s <agent>]` prefix. |
| `tools/board unread` | Prints every post by others since your last look, and marks the ones for you `, for you`. |
| `tools/board wait [--interval S]` | Waits for a post for you, checking every 30 seconds, or every `S`. |
| `tools/board read [-n N]` | Prints the board's last posts, or the last `N`. |

Codex reads `AGENTS.md`, which holds the board and owner sections, so it already knows the rules. Tell it once: "Use `tools/board` to talk to the team, and run `tools/board unread` between tasks."

**A loop that wakes the agent.** `tools/board wait` exits 0 and prints the posts when one is for you. So a terminal can run an agent once per post:

```sh
while posts=$(tools/board wait); do codex exec "New board posts for you: $posts"; done
```

To stop the loop, press Ctrl-C, or set `BOARD_WAIT=off` in that shell: `tools/board wait` then exits 1 at once and reads nothing. Pass `--interval 60` to check less often.

## From your phone

Colony starts each lead with Claude Code's Remote Control. Open the Claude app on your phone, or claude.ai/code, and the lead's session is there under its title. Type to it as you would at the laptop: answer its questions, ask what it is doing, or tell it to merge.

The session runs on your laptop, and the phone only talks to it. Keep the laptop plugged in, awake, online and open. On a Mac, `caffeinate -is` in a spare terminal stops it from sleeping.

## The last hour before the demo

1. **Freeze.** Post `@all freeze: only fixes from now`. Leads finish their current work and start nothing new.
2. **Merge what is ready** with `colony merge <branch>`.
3. **Review once.** Ask one lead to run `colony batch --review --name demo-1`, with no `--card`, since hack has no cards. One fresh reviewer reads `origin/<base>` as it stands, the demo build, while the fast check runs, and writes its report. No fixers run. It pushes the report on its own branch, `<project>/batch-demo-1`, and posts one line on the board with the open count and the report's link, such as `@all demo build 3f2a91c reviewed: open: 2, fast check pass, report: <link>`. Fix what would break the demo, and note the rest for later with `colony idea "<one line>"`.
4. **Rehearse.** Pull the base on the machine you present from, and run the demo once from start to end.
5. **Keep a good build.** Post the commit you rehearsed on, such as `@all demo build: 3f2a91c`, so you can go back to it if a late merge breaks something.

## FAQ

**We hit a rate limit.**
GitHub allows each signed-in `gh` user 5,000 API requests an hour. `colony wait` sends the last ETag, so a quiet check comes back as `304 Not Modified` and doesn't count against the limit. The prompt hook makes no network call while `colony wait` runs, and otherwise at most one cached call every 30 seconds. `tools/board wait` checks every 30 seconds by default, about 120 requests an hour; pass `--interval 60` to halve that. Claude's own limits are per account: each person's lead and builders share their plan, so open builders only for work that splits cleanly.

**Our repo is private.**
That works. Every teammate needs write access and `gh auth login`. The board issue is as private as the repo.

**Two agents need the same file.**
The owner table decides. The agent that doesn't own the file posts `@<owner>` on the board with the change it needs, and the owner's agent makes it and posts back. When the owner is busy, they can hand the file over on the board and update the table. If two branches change the file anyway, the second `colony merge` can't merge cleanly, and doesn't push the base. Merge the base into that branch, keep both changes, run the fast check, and run `colony merge` again.

The board idea comes from [azizu06/hackathon-agent-board](https://github.com/azizu06/hackathon-agent-board).
