# Pull requests

Applies to every pull request (PR) description an agent writes in this repository, a batch's PR from `colony batch` among them. The commits rule, `commits.md`, governs the title.

## What the rule is

The agent writes the description like a clear message to a teammate. The reader can see what went wrong, what changed, and why the change makes sense without reading the conversation first.

- The agent must start the description with a one- or two-sentence summary of the problem and the change.
- The agent must explain what was not working before listing the changes.
- The agent must use short, descriptive headings to separate the problem, the changes, and the reasoning behind them.
- The agent must order the sections by what the reader has to act on, with the decisions awaiting the reader placed right after the opening summary.
- The agent must use bullet points for distinct changes, with each bullet explaining what changed and how it addresses the problem.
- The agent must describe the result in words the person reviewing the PR understands.
- The agent should use a relaxed, friendly tone, like explaining the work to a teammate.
- The agent should use natural phrasing and contractions.
- The agent must explain how research shaped a decision when research informed the change, linking the relevant sources and naming their limits.
- The agent must explain how it validated the change, including what reviewers found, what was corrected, and what remains unverified.
- The agent must list a batch's changes, one line per card, and how the batch's checks, review, and walk checked them, with the open problems by round.
- The agent should keep validation beside the reasoning it supports when a separate checks section would repeat it.
- The agent must preserve the evidence and reasoning the person needs when shortening a description.
- The agent must state any decision the person needs to make before accepting the change, explaining in plain words what it is about, what changes with each answer, and what to say.
- The agent must write a list of items as one item per line, because a list folded into a paragraph is unreadable on a phone.
- The agent must link detailed logs and review records when their full contents would distract from the explanation.
- The agent must check that the opening summary, headings, and bullets explain the final change before publishing the description.

## Why it exists

Reviewers lose context when a description lists edits without explaining the problem. They cannot judge a decision when its supporting evidence and limits are missing.

## What is exempt

None.
