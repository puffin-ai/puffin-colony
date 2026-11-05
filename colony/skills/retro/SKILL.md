---
name: retro
description: A retrospective that turns what went wrong in a batch or a session into rule lines, checks and decisions. Use when a batch has merged, when colony retro starts you, or when the person asks what went wrong and how to stop it happening again.
---

# Retro

You improve the agents' **environment**, so the next run goes better: the files they read, the checks that catch them, and the tools they call. Read the `writing-for-agents` skill first, for how to write what agents read.

## Steps

1. **Read the primary sources** of the batch or session you were given, the current one when none was named: the batch's round reports under `.colony/`, its cards and their lines, the review's findings, the pull request, and the session's own transcript when you have it.
2. **Find the candidates** in each category below. Each candidate names what happened, with a quote or a link, and how often.
   - **Navigation**: an agent took long to find a file or a fact. Would a pointer in an essentials file, or a file named on the card, have found it?
   - **Checks**: an agent made a mistake a lint rule, a type, a test or a script could catch. Name the check.
   - **Review rules**: the reviewer missed something, or flagged something no rule supports. Add, sharpen or delete a line in `.colony/rules/`.
   - **Always-loaded text**: `.colony/core.md` or an `AGENTS.md` holds a line that belongs in a rule or a check, or has grown long.
   - **Tool economy**: an agent made an expensive call, read a huge output, or repeated a search. Name a cheaper route.
   - **No-ops**: a line that changes nothing the agent would do anyway. Delete it.
   - **Information access**: an agent lacked something it needed, such as a log, a dev server's output, or read access to a service.
3. **Turn every lesson into a change.** A lesson is done only as one of these:
   - a rule line, with what to do and what not to do, in the file at the right level
   - a check that fails on the mistake, with a test that shows it fails
   - a decision for the person, with your default, posted with `colony needs`
   A note alone is never enough.
4. **Open one pull request** with the rule lines and the checks, and list the decisions in its description. Order everything by how much it cost: the worst first.

## Where a lesson goes

- The implementing agent carries the most context: it explores, writes and debugs. The reviewer carries the least: it reads a diff. So a standard belongs in the reviewer's rules, `.colony/rules/`, not in the always-loaded core.
- `.colony/core.md` and each `AGENTS.md` load on every turn of every agent in their scope. Add a line there only when every agent needs it every time, and prefer a pointer to a rule over the rule itself.
- A rule file is read on demand. When one grows past a few hundred lines, split it by subject and point to the parts.
- A skill's description is always loaded and its body is not, so a procedure some tasks need belongs in a skill.
- A check beats a line of text every time it can be written: it never goes unread.
