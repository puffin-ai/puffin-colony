# Messages

Colony's agents talk in lines: one-sentence comments on GitHub issues. GitHub carries every line and keeps the record, so a builder on another computer needs only `gh` to take part, and you can read every exchange on the card it belongs to. This page describes Startup; [Hack](#hack-the-board) puts every line on one board issue.

## A line

```text
for <name>: <one sentence> (from <name>)
```

- `<name>` is `lead`, a builder's name such as `builder-2`, `researcher` or `spec`, or, on the coordination issue and the Needs issues, a lead's name such as `ana-lead`. Names ignore case.
- A line's sentence is at most 300 characters, or what `[messages] max_line` sets. What Colony adds around it, `for <name>:` and `(from <you>)`, doesn't count. A longer note goes as a file attached under the line: see [Attached files](#attached-files).
- One comment can hold several lines. Markdown around a line, such as a quote mark, a bullet, bold or code ticks, is ignored.
- A line never carries a secret. `colony post`, `colony say` and the hooks refuse one that holds a token's shape, or the value of an env variable whose name says it is a key, token, secret or password.
- You can post a line too. Yours carries no `(from …)`, or is signed with your GitHub login.
- A line is also addressed to a session when it contains `@<login>` for the session's person, which reaches their lead, or `@all`. `colony post` and `colony say` take `@<login>` as the recipient.
- A line never names a path on one computer, such as `/tmp/notes.md` or `~/plan.md`, because the session that reads it may run on another computer. `colony post` and `colony say` refuse one, and point to `--attach`.

## Posting a line

Agents post every line through Colony, which signs it and sends it through the transport:

```sh
colony post 41 builder-2 "start: this card"                # on card #41, from $COLONY_SESSION
colony post 41 lead "the date picker test fails on main" --urgent
colony say sam-lead "I merge into dev at 15:00, hold yours till then?"
```

- `colony post <card> <name> "<sentence>"` posts `for <name>: <sentence> (from <you>)` on the card. `--urgent` starts the sentence with `urgent:`, unless it already starts with `urgent:`, `blocked:` or `question:`.
- Both print each line they posted as `#<issue> <line>`, then, on stderr, which thread it went to and the comment's link, such as `colony: posted on the coordination issue: https://github.com/…#issuecomment-…`. The coordination issue moves to a fresh one when it fills, so the link is the one that always finds the line.
- `colony say <lead-name> "<sentence>"` posts a lead's line for another lead on the `Colony: coordination` issue. Only a lead can run it.
- `colony needs` posts a decision on your Needs issue, and the hooks post their lines on the coordination issue. See [cycle.md](cycle.md#needs-you) and [safety.md](safety.md#hooks).
- The coordination issue and each Needs issue close at 200 comments, with a comment listing their open items, and a fresh issue with the same title goes on. `colony say`, `colony needs` and `colony handover` check the count before they post. See [cycle.md](cycle.md#tidy).

## Line kinds

A line from a builder to its lead is only `done`, `question:`, `blocked:` or `urgent:`. A line from the lead to a builder is only `start:`, `answer:`, `stop:` or `urgent:`. `colony post` refuses any other, since progress belongs in the board's fields, which wake no one. Lead-to-lead lines, `colony say`, and a lead's lines for `@<login>` or `@all` are free text. A line's sentence is at most 300 characters, or what `[messages] max_line` sets; the `for <name>: … (from <you>)` that Colony adds around it doesn't count. `colony post` and `colony say` take several sentences too, each its own line, and post them as one comment, so either all of them go out or none does.

| Kind | From → to | Example | Reaches the lead |
| --- | --- | --- | --- |
| Start | lead → builder | `for builder-2: start: this card (from lead)` | |
| Answer | lead → builder | `for builder-2: answer: keep it until the next release (from lead)` | |
| Merge ask | lead → builder | `for builder-2: start: merge origin/builder-3/42 into your branch, resolve it, push, and post done again (from lead)` | |
| Done | builder → lead | `for lead: done, builder-2/41 pushed, 212 passed in 9.1s (from builder-2)` | in the digest, or at once when the batch waits on that card |
| Question | builder → lead | `for lead: question: keep the old route? I'm going with removing it (from builder-2)` | at once |
| Blocked | builder → lead | `for lead: blocked: the test database won't start (from builder-3)` | at once |
| Urgent | builder → lead | `for lead: urgent: the base branch fails to build since #40 (from builder-3)` | at once |
| Pop-up | hook → lead | `for ana-lead: urgent: builder-2 waits for a person's approval on <computer> (from builder-2)` | at once |
| Stopped | hook → lead | `for ana-lead: builder-2 stopped on an error (<code>) at <time> (from builder-2)` | in the digest |
| Stuck | a helper's status → lead | `urgent: auth's Bash call has waited 11 minutes for an answer, likely a permission prompt in its window on Ana-Mac: answer it there, or open the helper again` | at once, once per stretch |
| Slept | the lead's wait | `urgent: this computer slept for 40 minutes, so its helpers, merges and waits stopped: check them` | at once |
| Stale | the board → lead | `#41 stale: builder-2 shows no update since <time>; check its session`, or for a background helper `claude agents` lists as blocked, `` #41 stale: builder-2 waits on a prompt in its background session, with no update since <time>; answer it with `claude attach <id>` `` | in the digest |
| Yours | you → lead | `for lead: ship the batch as it is` | at once |
| Your answer | you → lead | `for ana-lead: yes, keep 30 seconds`, on your Needs issue | at once |
| Lead to lead | lead → lead | `for sam-lead: I merge into dev at 15:00, hold yours till then? (from ana-lead)` | in the digest, or at once with a prefix |

A done line ends with the fast check's last line, so the lead sees the result without opening anything. A stale line is not a comment: the lead's own wait makes it from the board.

Most questions carry the builder's own default. The builder keeps building on it, and changes course only when the lead answers otherwise, so the question can wait for the digest. A question with no safe default, such as an item on the stop list, starts with `question:` and reaches the lead at once.

## Who takes which line

- **A builder** takes only lines addressed to it and signed `(from lead)`. It ignores lines from anyone else, so it takes work only from the lead.
- **The lead** takes lines addressed to `lead`, or to its own `<person>-lead` name, that it didn't sign itself: lines from builders, from you, from the hooks, and from other leads.
- **The lead also takes a line for one of its own helpers that it didn't sign**, marked `redirected:`, such as `#41 redirected: for builder-1: also fix the footer`. So a line you or another agent write to a builder directly is never lost. A redirected line from you can't wait. A line signed by the lead, or `(from lead)`, isn't redirected, and neither is a line for another lead's helper. A helper belongs to the lead its `$COLONY_LEAD` names, which its status comment carries. A lead from before lead names counts the helpers that ran a wait on its computer.

Agents post through their person's own `gh` login, so the comment's author can't tell an agent from a person. The signature does. A line with no `(from …)`, or one signed with a login in `[people] logins`, is a person's line.

## `colony wait`

Each session keeps one `colony wait` running in the background, all session. The wait:

1. reads `$COLONY_SESSION` to learn whose lines to take;
2. asks `gh api` for the repo's issue comments changed since its last read, every 15 seconds, through one copy every wait on this computer shares, `~/.colony/polls/<repo>.json`, so a computer reads GitHub once per 15 seconds however many sessions it runs; when GitHub answers with its rate limit, the wait sleeps until the limit resets, up to 10 minutes, says so once, and goes on;
3. sends the last ETag with each request, so a quiet poll comes back as `304 Not Modified` and costs nothing against GitHub's rate limit;
4. prints the lines that are due, each as `#<issue> <line>`, and exits.

The agent reads what it printed, starts the wait again at once, and then acts on the lines. A session keeps one wait: a newer one takes over, and the older one stops, printing that a newer wait runs, so the agent starts no other. See [One wait per session](#one-wait-per-session). When a full issue moves to a fresh one, its closing note copies the open lines as `carried: …`, which wake no one a second time. A builder's lines are due as soon as they arrive, so a builder gets a line from its lead within about 15 seconds.

A session's first wait reads the last hour, so a start line the lead posted while the builder was opening still counts. The wait keeps its read time, its ETag, the lines it has gathered and the lines it has already printed in `~/.colony/<project>/<session>.json`. Its `unread` key lists the lines for this session it hasn't printed yet, each as `{card, author, body, url}`, for the prompt hook. Gathered lines stay there until they print, so a restart loses none. After 40 failed polls in a row, about 10 minutes, the wait prints the error and exits. A 401 from GitHub adds the hint `run: gh auth login`.

At each poll the wait also posts the outbox, `~/.colony/<project>/outbox.json`: the hooks' lines that couldn't post because `gh` failed, oldest first. The next hook run posts them too, so a hook's line is never lost.

The wait guard hook refuses a foreground sleep or poll loop, so an agent can't wait any other way. See [safety.md](safety.md#hooks).

### Follow mode

`colony wait --follow` never exits on its lines. It prints each line as soon as it is due, one per output line and flushed at once, and goes on polling, so a session starts its wait once and never has to start it again. Run it where your agent tool streams a running command's output to the agent; in Claude Code, that is the Monitor tool. Everything else stays the same: the lead's digest, the heartbeat at every poll, the status comment, the outbox and the stale and silent checks.

A following wait ends only when a newer wait for the same session takes over, or on a terminate signal. When GitHub fails `GIVE_UP` times in a row, about 10 minutes, it prints the error once and keeps trying, then prints `colony wait: GitHub reads again` when a read works. Without `--follow`, `colony wait` works as it always did: it prints the lines that are due and exits.

### One wait per session

A session keeps one wait. When a new `colony wait` starts for a session that already has one, the new wait stops the older one at once with a terminate signal, which the older one ends on cleanly. Before it signals, it reads the older process's command line and checks that it is a `colony wait`, so a process id the system reused for another program is never touched. Where it can't check, as on Windows, the older wait stops at its next poll instead, as before.

Every running wait is listed in `~/.colony/<project>/waits/<pid>.json`. `colony waits` prints them: which session each waits for, whether it is the one listening or a leftover, and whether it follows. It also lists any `colony wait` running on the computer that no list names, such as one from an older Colony. `colony waits --stop <pid>` stops one wait by its exact process id, and `colony waits --stop-leftovers` stops this project's leftovers, each by its id. Neither ever stops a process by a name pattern, and each refuses a process id that isn't a `colony wait`.

## Getting every line through

Each of these keeps a line from going astray. They work on any computer, through GitHub, and need nothing more than `gh`.

### Names that exist

Every wait learns the session names it reads in the team's own comments, those from `[people] logins` or, with none listed, from people GitHub says have access to the repo: each status comment's name and lead, and each line's `(from <name>)`. A stranger's comment on a public repo teaches no name. It keeps them in `~/.colony/<project>/names.json`. `colony post` and `colony say` refuse a line for a name that no learned, live or registered session has, and name the nearest ones, such as `did you mean ana-engine-lead?`. Besides the learned names, a name counts when this computer has its heartbeat, its wait, or a helper the lead just opened, or when `.colony/leads.toml` holds it. `lead`, your own lead, `@<login>` and `@all` always pass.

Until a wait on the computer has learned a name, nothing is refused. `--allow-unknown` sends to a session that is opening right now, and `[messages] check_names = false` turns the check off. A name a status comment gives as a lead, such as an orchestrator's, counts as a lead for `colony say`, even without `-lead` at its end.

### One session per lead, and the sender on every line

Only one session acts as a given lead. A named lead's `colony post` and `colony say` need its claim on this computer: when the lead's heartbeat holds another session's token, fresh or stale, the command refuses, and says to claim the lead again with `colony claim`. With no heartbeat on this computer, nothing is refused.

A line posted from an agent session carries a hidden note at the end of its comment, which no wait reads as a line: the sender's name, a short hash of the agent session's id (never the id itself), the computer, and its lead claim's mark, a short hash of the claim's token (never the token). A session's id is `$CLAUDE_CODE_SESSION_ID`, or `$COLONY_AGENT_SESSION` for another agent tool. A command run outside an agent session and outside a lead's claim, such as yours in a terminal, adds no note.

The lead's wait reads the notes. When a line signed with its own name, posted since its claim began, carries another claim's mark, it raises at once: `urgent: a line signed ana-main-lead on #41 came from another session, on Ana-Mac, not this one: …`.

### Start lines that need an acknowledgement

A lead's `start:` line from an agent session asks for an acknowledgement in its note. The helper's wait gives it as soon as it prints the line, or once the prompt hook showed it: an `eyes` reaction on the comment, which wakes no one. The lead's wait checks each start line it sent, at most once a minute, and counts only a reaction from the team: from a login in `[people] logins`, or with none listed, from someone GitHub says collaborates on the repo. Agents react through their person's login, so a stranger's reaction never counts. One that has no such reaction after `[messages] start_ack_minutes` (10) goes again, the same line in a new comment, up to `start_resends` times (2). After that the lead hears it at once: `urgent: builder-2 has not acknowledged the start line on #41 after 3 sends in 30 minutes: …`. A helper that already printed a start shows a repeat of it no second time, and acknowledges it again. `start_ack_minutes = 0` asks for no acknowledgement.

### A nudge for an idle session

A session whose wait isn't running reads no line until something wakes it. `colony nudge <name>` types one short pointer into that session's cmux workspace on this computer and presses Enter, so the prompt hook shows the session its unread lines. Then it reads the screen and checks the pointer left the prompt box, and presses Enter again, up to three times, when it still sits there unsent. It reports `submitted`, or why not. cmux refuses to type over a draft someone is writing, or into a question that waits, and the nudge says so.

The workspace is the one titled with the session's name, or `<project>-<name>`, as `colony open` names it; `--workspace` names another. Without cmux, or with no such workspace on this computer, there is no nudge, and the line still went out. `colony post` and `colony say` take `--nudge` to nudge once, and `[messages] nudge` sets when they nudge by themselves: `off` (the default), `auto`, for a recipient whose wait isn't running on this computer, or `always`. By the setting alone, a recipient with no workspace on this computer, such as a lead on another one, gets no nudge, quietly.

### Redelivery after a compaction or a restart

Each wait notes the lines it printed in `~/.colony/<project>/<session>-delivered.json`, and so does the prompt hook for the lines it shows. When a session compacts its conversation, is resumed, cleared or starts again, the SessionStart hook prints the lines shown to it since its last `colony ack`, within `[messages] redeliver_minutes` (60), at most 20, under a heading that says some may be done already. `colony ack` says the session has acted on every line shown so far, and `colony redeliver` prints the unacknowledged ones at any time.

### Attached files

`colony post` and `colony say` take `--attach <file>`, or `--attach -` for stdin. The file's text goes in the same comment, under the lines, in a folded block, so a note too long for a line reaches every computer through GitHub. A wait never reads a line after the attachment starts, and adds to the line it prints how to read the file: `[attached file: gh api repos/<repo>/issues/comments/<id> --jq .body]`. The sender's note counts only at the comment's very end, so a note inside a file is never read.

An attachment is checked as `colony share` checks a file:

- a link is refused, since its name can hide a secret file;
- so is a file whose real path passes through a folder or a name that holds secrets, such as `~/.ssh`, `.env` or a `.pem`;
- so is text that holds a secret's shape, in UTF-8 or UTF-16, a file that isn't UTF-8 text, and one over 1 MB or 60,000 characters;
- on a public repo, where anyone can read the comment, a file is refused unless `--public` says it may be public, which you add only when your person says so; `colony say --private --attach <file>` sends it to the private board instead.

The file's `<!--` and `-->` arrive as `&lt;!--` and `--&gt;`, so nothing in it can open or close a hidden part of the comment.

### Leads on many computers

Leads and orchestrators on different computers, and different people's, stay in touch through GitHub alone. Each one's status comment shows the others its state, `colony who` lists them, `colony say` reaches any of them, and a note goes as an attached file, never as a path on one computer. Every wait reads every line on the repo, so a line reaches its session wherever it runs.

## Presence: heartbeats and status comments

Every session a person opens is a lead, named `<person>-<stream>-lead`, such as `ana-engine-lead`, with its folders in the clone's registry, which every worktree reads, and in its status comment, which every computer reads ([folders.md](folders.md)). Helpers belong to one lead, and carry its name in `$COLONY_LEAD`. See the playbook's Leads and helpers section.

- **On this computer,** a lead's wait writes `~/.colony/<project>/<lead>.heartbeat` at each poll, every 15 seconds, with its name, account, a token and the time. Under 2 minutes old, the lead is alive. The heartbeat is also the lock on that name: it is written under a file lock, and only when it is missing, stale, or holds the writer's own token, `$COLONY_LEAD_TOKEN`. A lead from before lead names keeps `lead.heartbeat`.
- **Across computers,** each lead and helper keeps one status comment on the coordination issue, or the board in hack mode, edited in place every 5 minutes: name, person, computer, account, folders, and its accounts' 5-hour and weekly room. It never adds a second comment. A status older than 15 minutes counts as gone.
- `colony who` lists every live lead and helper. `colony status` prints this computer's leads with their account and heartbeat age.

## The quiet lead

A lead that wakes on every line spends its time and tokens on interruptions. So the lead's wait gathers lines and prints them together as a digest, at the end of the first `lead_digest_minutes` (10 by default) that gathered one.

The digest prints at once, with everything gathered so far, when a line can't wait:

- its sentence starts with `urgent:`, `blocked:` or `question:`;
- it is a person's line;
- it is a `done` line for a card the batch is waiting on.

The lead tells its wait which cards the batch is waiting on:

```sh
colony wait --waiting-on 41,42     # done lines for #41 and #42 come at once
colony wait --waiting-on ""        # clears the list
```

The list stays until the lead changes it. At most every 10 minutes, the lead's wait also reads the board and gathers a `stale:` line for each card with no update in 2.5 hours.

## Lead to lead

When several people each run a lead on the same repo, the leads talk on one shared issue, titled `Colony: coordination`. The first lead's wait finds it by title, or opens it. On that issue each lead is `<person>-lead`, such as `ana-lead` or `sam-lead`.

The other lead's wait takes a `colony say` line under the same rules: in the digest, or at once with `urgent:`, `blocked:` or `question:`. `colony say --urgent` adds `urgent:`; a lead marks a line so only when work stops on it, such as a blocked helper or a question that holds a card.

A helper's line for `lead` reaches its own lead only. A helper that carries its lead's name, `$COLONY_LEAD`, posts the line for that name, and a lead's wait leaves a `for lead:` line from another lead's helper, by that helper's status comment, to that lead. Leads use it to ask each other things, hand work across, and warn before a merge to the shared base branch. Each lead still asks only its own person, and only what it can't decide. The same issue holds each lead's handover.

## Hack: the board

In Hack, every line goes to one pinned issue, `Board: <project>`, not to cards. Setup opens it, pins it, and writes its number to `[messages] board`.

- A post starts with `[<name>'s <agent>]`, such as `[Ana's Claude]`. `colony post` and `tools/board` add the prefix.
- A post reaches a session when it starts with `for <name>:`, contains `@<login>` for the session's person, or contains `@all`. A post for a person goes to their lead, `<login>-main-lead`.
- The leads are peers, so there is no coordination issue and no digest.
- **The prompt hook.** When you send a prompt, it prints the lines in the wait's `unread` list, then empties it, with no network call. When `colony wait` isn't running, it makes one ETag-cached `gh api` call, at most once per 30 seconds. Solo uses the same hook for card lines.
- **Any agent.** `tools/board`, a POSIX shell script that needs only `gh`, lets Codex or any other agent post and read in the same format. See [commands.md](commands.md#toolsboard).

The full guide is [hackathon.md](hackathon.md).

## Where talk happens

- **About a card:** comments on that card's issue.
- **Lead to lead:** the one coordination issue, `Colony: coordination`.
- **A decision for a person:** their Needs issue, `Needs <Person>`.
- **The board** shows status only, in its fields. It never carries a message.

Agents never open an issue to message each other. Each session's `colony wait` shows it only the lines addressed to it. Every line goes as a GitHub comment, read within the wait's 15-second poll, and `transport.send` is the one place in the code that posts it.
