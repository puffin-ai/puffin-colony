---
name: git-guardrails
description: Set up a Claude Code hook that refuses destructive git commands, such as a force push, a push to the base branch, reset --hard, clean -f or branch -D, before they run. Use when the person wants git safety hooks, or wants agents kept from destroying work with git.
---

# Git guardrails

A PreToolUse hook reads each Bash call before it runs, and exit code 2 refuses it. This one refuses:

- a force push: `--force`, `-f`, `--force-with-lease`, or a `+` refspec
- a push to the base branch, `base` in `.colony/colony.toml`
- `git reset --hard`
- `git clean -f`
- `git branch -D`
- `git checkout .` and `git restore .`, which drop every change

A builder's push of its own branch, `git push origin <builder>/<card>`, still runs.

## Steps

1. **Ask the scope**, as a question with the default: this repo only, in `.claude/` (the default), or every repo on this computer, in `~/.claude/`.
2. **Write the script** below to `.claude/hooks/git_guard.py`, or `~/.claude/hooks/git_guard.py`, and make it executable.
3. **Add the hook** to `.claude/settings.json`, or `~/.claude/settings.json`. Merge it into the `hooks.PreToolUse` list, and keep every key and hook already there:

       {"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/git_guard.py\""}]}

   For the personal scope, the command is `python3 ~/.claude/hooks/git_guard.py`.
4. **Ask about the list**: does the person want a pattern added or removed? Edit `BLOCKED` to match.
5. **Verify it.** Write a test call to a file, because a guard reads the whole command line, then run `python3 .claude/hooks/git_guard.py < call.json` for each case: `{"tool_input": {"command": "git push --force origin x"}}` must exit 2 with a refusal on stderr, and `{"tool_input": {"command": "git push origin builder-1/12"}}` must exit 0. Quote both results.

## The script

```python
#!/usr/bin/env python3
"""Refuse destructive git commands before Claude Code runs them: exit 2, with the reason on stderr."""
import json
import os
import re
import sys
import tomllib
from pathlib import Path

BLOCKED = [
    (r"\bpush\b.*(\s--force\b|\s--force-with-lease\b|\s-f\b|\s\+\S)", "a force push"),
    (r"\breset\b.*\s--hard\b", "git reset --hard"),
    (r"\bclean\b.*\s-[a-zA-Z]*f", "git clean -f"),
    (r"\bbranch\b.*\s-D\b", "git branch -D"),
    (r"\b(checkout|restore)\b(\s+--)?\s+\.(\s|$)", "dropping every change"),
]


def base_branch() -> str:
    config = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / ".colony" / "colony.toml"
    try:
        return tomllib.loads(config.read_text())["project"]["base"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "main"


def main() -> int:
    try:
        command = json.load(sys.stdin)["tool_input"]["command"]
    except (ValueError, KeyError, TypeError):
        return 0
    base = re.escape(base_branch())
    rules = BLOCKED + [(rf"\bpush\b.*[\s:]{base}(\s|$)", "a push to the base branch")]
    for part in re.split(r"&&|\|\||;|\n", command):
        if not re.search(r"\bgit\b", part):
            continue
        for pattern, what in rules:
            if re.search(pattern, part):
                sys.stderr.write(f"git guard: refused {what}. Ask the lead, who asks the person.\n")
                return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
