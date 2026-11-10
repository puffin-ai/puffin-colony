# Messages

Colony's agents talk in lines: one-sentence comments on GitHub issues. GitHub carries every line and keeps the record, so a builder on another computer needs only `gh` to take part, and you can read every exchange on the card it belongs to. This page describes Startup; [Hack](#hack-the-board) puts every line on one board issue.

## A line

```text
for <name>: <one sentence> (from <name>)
```

- `<name>` is `lead`, a builder's name such as `builder-2`, `researcher` or `spec`, or, on the coordination issue and the Needs issues, a lead's name such as `ana-lead`. Names ignore case.
- A line's sentence is at most 300 characters. What Colony adds around it, `for <name>:` and `(from <you>)`, doesn't count.
- One comment can hold several lines. Markdown around a line, such as a quote mark, a bullet, bold or code ticks, is ignored.
- A line never carries a secret. `colony post`, `colony say` and the hooks refuse one that holds a token's shape, or the value of an env variable whose name says it is a key, token, secret or password.
- You can post a line too. Yours carries no `(from …)`, or is signed with your GitHub login.
- A line is also addressed to a session when it contains `@<login>` for the session's person, which reaches their lead, or `@all`. `colony post` and `colony say` take `@<login>` as the recipient.

## Posting a line

Agents post every line through Colony, which signs it and sends it through the transport:

```sh
colony post 41 builder-2 "start: this card"                # on card #41, from $COLONY_SESSION
colony post 41 lead "the date picker test fails on main" --urgent
colony say sam-lead "I merge into dev at 15:00, hold yours till then?"
```

- `colony post <card> <name> "<sentence>"` posts `for <name>: <sentence> (from <you>)` on the card. `--urgent` starts the sentence with `urgent:`, unless it already starts with `urgent:`, `blocked:` or `question:`.
- `colony say <lead-name> "<sentence>"` posts a lead's line for another lead on the `Colony: coordination` issue. Only a lead can run it.
- `colony needs` posts a decision on your Needs issue, and the hooks post their lines on the coordination issue. See [cycle.md](cycle.md#needs-you) and [safety.md](safety.md#hooks).
- The coordination issue and each Needs issue close at 200 comments, with a comment listing their open items, and a fresh issue with the same title goes on. `colony say`, `colony needs` and `colony handover` check the count before they post. See [cycle.md](cycle.md#tidy).

## Line kinds

A line from a builder to its lead is only `done`, `question:`, `blocked:` or `urgent:`. A line from the lead to a builder is only `start:`, `answer:`, `stop:` or `urgent:`. `colony post` refuses any other, since progress belongs in the board's fields, which wake no one. Lead-to-lead lines, `colony say`, and a lead's lines for `@<login>` or `@all` are free text. A line's sentence is at most 300 characters; the `for <name>: … (from <you>)` that Colony adds around it doesn't count. `colony post` and `colony say` take several sentences too, each its own line, and post them as one comment, so either all of them go out or none does.

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
| Stale | the board → lead | `#41 stale: builder-2 shows no update since <time>; check its session` | in the digest |
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

The agent reads what it printed, starts the wait again at once, and then acts on the lines. A session keeps one wait: a newer one takes over, and the older one stops at its next poll, printing that a newer wait runs, so the agent starts no other. When a full issue moves to a fresh one, its closing note copies the open lines as `carried: …`, which wake no one a second time. A builder's lines are due as soon as they arrive, so a builder gets a line from its lead within about 15 seconds.

A session's first wait reads the last hour, so a start line the lead posted while the builder was opening still counts. The wait keeps its read time, its ETag, the lines it has gathered and the lines it has already printed in `~/.colony/<project>/<session>.json`. Its `unread` key lists the lines for this session it hasn't printed yet, each as `{card, author, body, url}`, for the prompt hook. Gathered lines stay there until they print, so a restart loses none. After 40 failed polls in a row, about 10 minutes, the wait prints the error and exits. A 401 from GitHub adds the hint `run: gh auth login`.

At each poll the wait also posts the outbox, `~/.colony/<project>/outbox.json`: the hooks' lines that couldn't post because `gh` failed, oldest first. The next hook run posts them too, so a hook's line is never lost.

The wait guard hook refuses a foreground sleep or poll loop, so an agent can't wait any other way. See [safety.md](safety.md#hooks).

## Presence: heartbeats and status comments

Every session a person opens is a lead, named `<person>-<stream>-lead`, such as `ana-engine-lead`, with its folders in `.colony/leads.toml`. Helpers belong to one lead, and carry its name in `$COLONY_LEAD`. See the playbook's Leads and helpers section.

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
