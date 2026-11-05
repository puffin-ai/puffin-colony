# Performance

Applies to every change on a request path, a screen, or a loop over data.

## Must

- Fetch what a screen or request needs in as few round trips as you can: one query with a join or a batch, not one per row.
- Add an index for each new query that filters or sorts a table that grows.
- Page or limit every list that can grow without bound.
- Do slow work (mail, files, outside calls, reports) in the background, and show the person progress.
- Cache a value only with a clear owner and a clear rule for when it expires or changes.
- Load code, images and data a screen doesn't show yet only when it is needed.
- Size images for where they show, and give each one its dimensions so the layout doesn't jump.
- Keep a response that the person waits on under about 200 ms on the server, and say so on the card when it can't be.
- Measure before and after a change made for speed, and put both figures on the card.

## Must not

- Run a query or an outside call inside a loop over rows.
- Block the main thread, the event loop or a request on work that can run elsewhere.
- Load a whole table, file or list into memory to use a few items.
- Add a dependency for speed without measuring that it helps, and without the person's yes.
- Re-render or re-fetch on every keystroke, scroll or resize without a debounce or a reason.
