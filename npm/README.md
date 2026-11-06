# puffin-colony

One command that runs a repo's whole software life cycle with Claude Code: a lead, builders, and a gate of checks,
review and a browser walk.

```sh
npx puffin-colony
```

Run it in your repo. The first time, it sets the repo up; every time after, it opens the lead.

Puffin Colony is a Python tool. This package is a small wrapper with no dependencies: it runs
`uvx puffin-colony`, or `python3 -m colony` when uv is missing and the Python package is installed. If neither
works, it says how to install [uv](https://docs.astral.sh/uv/):

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

To install the command for good, `npm install -g puffin-colony` gives you `colony` and `puffin-colony`.

Every way to install, and the docs: https://github.com/puffin-ai/puffin-colony

MIT, Puffin Studios, Inc.
