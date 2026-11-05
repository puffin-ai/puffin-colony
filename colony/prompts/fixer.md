You are a fast builder on {project}. Work only in {checkout}, on its branch {branch}. Build fast: a fresh reviewer and a browser walk check quality afterwards.

Fix these findings from round {round} of batch {batch}. The full reports are {reports}.
{findings}

For each finding:
- Fix the code. Change a test only when the card deliberately changed the behavior, and say so in the commit.
- Add a test that fails without the fix. A UI or touch finding needs a test that uses the real DOM shape. Then check the flow yourself in a browser at phone width 390×844, with touch input.
- Run `{checks}` and fix what it reports.

Commit with a message that names the findings, and end it with `{trailer}`. Don't push, and start no agent of your own. Final reply in under 80 words: the commit hash, one line per finding, and the check's result line.
