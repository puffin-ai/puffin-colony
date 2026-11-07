# Security policy

## Reporting a vulnerability

Please report a security problem privately, through GitHub's security advisories: open [a new advisory](https://github.com/puffin-ai/puffin-colony/security/advisories/new) on this repository. Don't open a public issue or pull request for it.

Say what the problem is, how to reproduce it, and what an attacker could do with it. We will answer in the advisory, work on a fix there, and credit you when it is published, unless you ask us not to.

## Supported versions

Fixes go into the latest release only. Upgrade to it before you report, when you can.

## What Colony touches

Colony runs on your own machine. It shells out to `git`, `gh`, `claude` and `cmux` with your own accounts, and it never stores a token. [docs/safety.md](docs/safety.md) describes its guards, such as never pushing to your base branch.
