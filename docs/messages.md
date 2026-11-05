# Messages

Colony's agents talk in lines: one-sentence comments on GitHub issues. GitHub carries every line and keeps the record, so a builder on another computer needs only `gh` to take part, and you can read every exchange on the card it belongs to. Where Agent Relay runs, a line that can't wait also arrives at once. This page describes Startup; [Hack](#hack-the-board) puts every line on one board issue.

## A line

```text
for <name>: <one sentence> (from <name>)
```

- `<name>` is `lead`, a builder's name such as `builder-2`, `researcher` or `spec`, or, on the coordination issue and the Needs issues, a lead's name such as `serdar-lead`. Names ignore case.
- A line stays under 300 characters.
- One comment can hold several lines. Markdown around a line, such as a quote mark, a bullet, bold or code ticks, is ignored.
- A line never carries a secret. `colony post`, `colony say` and the hooks refuse one that holds a token's shape, or the value of an env variable whose name says it is a key, token, secret or password.
- You can post a line too. Yours carries no `(from …)`, or is signed with your GitHub login.
- A line is also addressed to a session when it contains `@<login>` for the session's person, which reaches their lead, or `@all`. `colony post` and `colony say` take `@<login>` as the recipient.

## Posting a line

Agents post every line through Colony, which signs it and sends it through the transport:

```sh
colony post 41 builder-2 "start this card"                 # on card #41, from $COLONY_SESSION
colony post 41 lead "the date picker test fails on main" --urgent
colony say burak-lead "I merge into dev at 15:00, hold yours till then?"
```

- `colony post <card> <name> "<sentence>"` posts `for <name>: <sentence> (from <you>)` on the card. `--urgent` starts the sentence with `urgent:`, unless it already starts with `urgent:`, `blocked:` or `question:`.
- `colony say <lead-name> "<sentence>"` posts a lead's line for another lead on the `Colony: coordination` issue. Only a lead can run it.
- `colony needs` posts a decision on your Needs issue, and the hooks post their lines on the coordination issue. See [cycle.md](cycle.md#needs-you) and [safety.md](safety.md#hooks).

## Line kinds

| Kind | From → to | Example | Reaches the lead |
| --- | --- | --- | --- |
| Start | lead → builder | `for builder-2: start this card (from lead)` | |
| Answer | lead → builder | `for builder-2: keep it until the next release (from lead)` | |
| Merge ask | lead → builder | `for builder-2: merge origin/builder-3/42 into your branch, resolve it, push, and post done again (from lead)` | |
| Done | builder → lead | `for lead: done, builder-2/41 pushed, 212 passed in 9.1s (from builder-2)` | in the digest, or at once when the batch waits on that card |
| Question with a default | builder → lead | `for lead: keep the old route? I'm going with removing it (from builder-2)` | in the digest |
| Question | builder → lead | `for lead: question: may I add date-fns? (from builder-2)` | at once |
| Blocked | builder → lead | `for lead: blocked: the test database won't start (from builder-3)` | at once |
| Urgent | builder → lead | `for lead: urgent: the base branch fails to build since #40 (from builder-3)` | at once |
| Pop-up | hook → lead | `for serdar-lead: urgent: builder-2 waits for a person's approval on <computer> (from builder-2)` | at once |
| Stopped | hook → lead | `for serdar-lead: builder-2 stopped on an error (<code>) at <time> (from builder-2)` | in the digest |
| Stale | the board → lead | `#41 stale: builder-2 shows no update since <time>, and its State is not usage limit; check its session` | in the digest |
| Yours | you → lead | `for lead: ship the batch as it is` | at once |
| Your answer | you → lead | `for serdar-lead: yes, keep 30 seconds`, on your Needs issue | at once |
| Lead to lead | lead → lead | `for burak-lead: I merge into dev at 15:00, hold yours till then? (from serdar-lead)` | in the digest, or at once with a prefix |

A done line ends with the fast check's last line, so the lead sees the result without opening anything. A stale line is not a comment: the lead's own wait makes it from the board.

Most questions carry the builder's own default. The builder keeps building on it, and changes course only when the lead answers otherwise, so the question can wait for the digest. A question with no safe default, such as an item on the stop list, starts with `question:` and reaches the lead at once.

## Who takes which line

- **A builder** takes only lines addressed to it and signed `(from lead)`. It ignores lines from anyone else, so it takes work only from the lead.
- **The lead** takes lines addressed to `lead`, or to its own `<person>-lead` name, that it didn't sign itself: lines from builders, from you, from the hooks, and from other leads.

Agents post through their person's own `gh` login, so the comment's author can't tell an agent from a person. The signature does. A line with no `(from …)`, or one signed with a login in `[people] logins`, is a person's line.

## `colony wait`

Each session keeps one `colony wait` running in the background, all session. The wait:

1. reads `$COLONY_SESSION` to learn whose lines to take;
2. asks `gh api` for the repo's issue comments changed since its last read, every 15 seconds;
3. sends the last ETag with each request, so a quiet poll comes back as `304 Not Modified` and costs nothing against GitHub's rate limit;
4. prints the lines that are due, each as `#<issue> <line>`, and exits.

The agent reads what it printed, starts the wait again at once, and then acts on the lines. A builder's lines are due as soon as they arrive, so a builder gets a line from its lead within about 15 seconds, or at once through the relay.

A session's first wait reads the last hour, so a start line the lead posted while the builder was opening still counts. The wait keeps its read time, its ETag, the lines it has gathered and the lines it has already printed in `~/.colony/<project>/<session>.json`. Its `unread` key lists the lines for this session it hasn't printed yet, each as `{card, author, body, url}`, for the prompt hook. Gathered lines stay there until they print, so a restart loses none. After 40 failed polls in a row, about 10 minutes, the wait prints the error and exits. A 401 from GitHub adds the hint `run: gh auth login`.

The wait guard hook refuses a foreground sleep or poll loop, so an agent can't wait any other way. See [safety.md](safety.md#hooks).

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

When several people each run a lead on the same repo, the leads talk on one shared issue, titled `Colony: coordination`. The first lead's wait finds it by title, or opens it. On that issue each lead is `<person>-lead`, such as `serdar-lead` or `burak-lead`.

The other lead's wait takes a `colony say` line under the same rules: in the digest, or at once with `urgent:`, `blocked:` or `question:`. Leads use it to ask each other things, hand work across, and warn before a merge to the shared base branch. Each lead still asks only its own person, and only what it can't decide. The same issue holds each lead's handover.

## Hack: the board

In Hack, every line goes to one pinned issue, `Board: <project>`, not to cards. Setup opens it, pins it, and writes its number to `[messages] board`.

- A post starts with `[<name>'s <agent>]`, such as `[Serdar's Claude]`. `colony post` and `tools/board` add the prefix.
- A post reaches a session when it starts with `for <name>:`, contains `@<login>` for the session's person, or contains `@all`. A post for a person goes to their lead, `<login>-lead`.
- The leads are peers, so there is no coordination issue and no digest.
- **The prompt hook.** When you send a prompt, it prints the lines in the wait's `unread` list, then empties it, with no network call. When `colony wait` isn't running, it makes one ETag-cached `gh api` call, at most once per 30 seconds. Solo uses the same hook for card lines.
- **Any agent.** `tools/board`, a POSIX shell script that needs only `gh`, lets Codex or any other agent post and read in the same format. See [commands.md](commands.md#toolsboard).

The full guide is [hackathon.md](hackathon.md).

## Transport

`[messages] transport` picks how lines travel.

- **`github`**, the default, carries every line as an issue comment, read by the wait every 15 seconds.
- **`relay`** also sends a line through this computer's Agent Relay core, which puts it into the receiving session between its turns, at once. Setup offers it, with yes as the default when a core runs on this computer. Without a running core, each line goes by GitHub alone.

With `relay`, each line still goes:

1. **The comment is always posted.** It is the record, and a computer without the relay still sees every line.
2. **Only a line the receiver's wait would print at once is relayed.** That is every lead-signed line for a builder, and for the lead an `urgent:`, `blocked:` or `question:` line, a person's line, or a waited-on `done`. A line that belongs in the digest goes by GitHub alone, so the relay never wakes a quiet lead early.
3. **A relayed comment carries a hidden mark**, `<!-- colony: relayed -->`. The receiver's wait skips the copy it reads later, so a line delivered both ways is acted on once.
4. **When the relay fails**, Colony says why on stderr and posts the comment without the mark, so the wait still delivers it.

Colony finds the core's probe (`agent-relay-probe`) and socket the way the messaging-agents-on-the-relay skill describes: the permission rule the core writes for Claude Code or Codex, then the socket pointer and the usual install folders. It talks only to that local socket, and never to a cloud connector.
