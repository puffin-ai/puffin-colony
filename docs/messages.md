# Messages

Colony's agents talk in lines: one-sentence comments on GitHub issues. There is no server. GitHub carries every line and keeps the record, so a builder on another computer needs only `gh` to take part, and you can read every exchange on the card it belongs to.

## A line

```text
for <name>: <one sentence> (from <name>)
```

- `<name>` is `lead`, a builder's name such as `builder-2`, or, on the coordination issue, a lead's name such as `serdar-lead`. Names ignore case.
- A line stays under 300 characters.
- An agent posts it on the card it is about: `gh issue comment <n> --body "<line>"`.
- One comment can hold several lines. Markdown around a line, such as a quote mark, a bullet, bold or code ticks, is ignored.
- You can post a line too. Yours carries no `(from …)`, or is signed with your GitHub login.

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
| Yours | you → lead | `for lead: ship the batch as it is` | at once |
| Lead to lead | lead → lead | `for burak-lead: I merge into dev at 15:00, hold yours till then? (from serdar-lead)` | in the digest, or at once with a prefix |

A done line ends with the fast check's last line, so the lead sees the result without opening anything.

Most questions carry the builder's own default. The builder keeps building on it, and changes course only when the lead answers otherwise, so the question can wait for the digest. A question with no safe default, such as an item on the stop list, starts with `question:` and reaches the lead at once.

## Who takes which line

- **A builder** takes only lines addressed to it and signed `(from lead)`. It ignores lines from anyone else, so it takes work only from the lead.
- **The lead** takes lines addressed to `lead`, or to its own `<person>-lead` name, that it didn't sign itself: lines from builders, from you, and from other leads.

Agents post through their person's own `gh` login, so the comment's author can't tell an agent from a person. The signature does. A line with no `(from …)`, or one signed with a login in `[people] logins`, is a person's line.

## `colony wait`

Each session keeps one `colony wait` running in the background, all session. The wait:

1. reads `$COLONY_SESSION` to learn whose lines to take;
2. asks `gh api` for the repo's issue comments changed since its last read, every 15 seconds;
3. sends the last ETag with each request, so a quiet poll comes back as `304 Not Modified` and costs nothing against GitHub's rate limit;
4. prints the lines that are due, each as `#<issue> <line>`, and exits.

The agent reads what it printed, starts the wait again at once, and then acts on the lines. A builder's lines are due as soon as they arrive, so a builder gets a line from its lead within about 15 seconds.

A session's first wait reads the last hour, so a start line the lead posted while the builder was opening still counts. The wait keeps its read time, its ETag, the lines it has gathered and the lines it has already printed in `~/.colony/<project>/<session>.json`. Gathered lines stay there until they print, so a restart loses none. After 40 failed polls in a row, about 10 minutes, the wait prints the error and exits. A 401 from GitHub adds the hint `run: gh auth login`.

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

The list stays until the lead changes it.

## Lead to lead

When several people each run a lead on the same repo, the leads talk on one shared issue, titled `Colony: coordination`. The first lead's wait finds it by title, or opens it. On that issue each lead is `<person>-lead`, such as `serdar-lead` or `burak-lead`.

A lead posts a line for another lead with `colony say`:

```sh
colony say burak-lead "I merge into dev at 15:00, hold yours till then?"
```

That posts `for burak-lead: I merge into dev at 15:00, hold yours till then? (from serdar-lead)` on the coordination issue. Only a lead can run `say`. A builder posts its lines on its card, for its own lead.

The other lead's wait takes the line under the same rules: in the digest, or at once with `urgent:`, `blocked:` or `question:`. Leads use it to ask each other things, hand work across, and warn before a merge to the shared base branch. Each lead still asks only its own person, and only what it can't decide.

## Transport

`[messages] transport = "github"`, the default, carries every line through GitHub issue comments, as above.

A relay transport is on the [roadmap](roadmap.md). With it, machines that run Agent Relay will deliver lines to each other at once, and GitHub will stay the record. Until it is built, `transport = "relay"` stops the wait with a one-line message.
