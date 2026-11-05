# Roadmap

What comes next, in rough order. Nothing here has a date yet. Each item keeps today's rules: Python standard library only, no push to your base branch, and no spend without a yes.

## More presets

Today there are `lean`, `puffin` and `own`, each in three levels. Next:

- stack presets that add the essentials a stack needs, such as a Rails app, a Go service, or a React Native app;
- more essentials for the `puffin` preset beyond Next.js and FastAPI.

## A hosted dashboard

`colony status` shows one batch on one machine, and the board shows the cards. The plan is a page that shows every batch across your machines and your team: the cards, each round's open count and walk, the steps running now, and the minutes and cost so far, read from the reports and stats Colony already writes.

## A PyPI release

Today you install from GitHub:

```sh
uv tool install git+https://github.com/Puffin-Calendar/puffin-colony
```

Once the repo is public, Colony will ship on PyPI as `puffin-colony`, so this works:

```sh
uv tool install puffin-colony      # or: pipx install puffin-colony
```
