# Coding

Applies to every line of production code in the Python service, `{service}`, and the TypeScript web app, `{web_app}`, and to everyone who writes or reviews it. The reviewer checks each line against the diff. The testing rule, `testing.md`, governs test code.

## In both apps

- The implementer must name a type, field, route, file, or folder for a product concept by the one word the team uses for that concept everywhere, never a word a naming decision retired.
- The implementer must raise or throw typed errors, and turn an error that two or more handlers raise into its answer in one place.
- The implementer must keep user-facing error text to what happened and what the user can do, with no internal detail.
- The implementer must give every call to another service a deadline and a ceiling on its answer's size.
- The implementer must retry an outside call at one point only, such as the provider's SDK for a model call, with at most three attempts and no retry of a validation or access refusal.
- The implementer must log the request identifier of every model provider response, and treat an error in a model's stream after its 200 as a failed turn.
- The implementer must keep each model tool's name unchanged after the first release to users, because saved conversations and evaluations name it.

## In a Python service, `{service}`

### What the service's tools enforce

Every change must pass these, configured in the service's `pyproject.toml`:

- ruff, which refuses a blocking call in async code (`ASYNC`), a naive datetime (`DTZ`), a bare except, an exception name without the Error suffix (`N818`), a broad catch (`BLE001`) outside a route handler, a background-task wrapper, or a lifespan handler that re-raises or converts it, an assert on input (`S101`), a pickle load (`S301`), and a log line outside the one logging module (`TID251`).
- strict pyright, which needs every public function annotated and every override marked `typing.override`, with each suppression naming its reason.
- `ruff format`, which settles formatting, and the reviewer must not raise a preference it accepts.

### Async and requests

- The implementer must write path operations and dependencies as async functions, and route every blocking call inside async code through `anyio.to_thread.run_sync`.
- The implementer must run every await in the cleanup after a cancellation inside `anyio.move_on_after` with `shield=True`.
- The implementer must start concurrent work in an AnyIO task group bounded by an AnyIO timeout, with no `asyncio.gather`, `asyncio.wait_for`, `asyncio.create_task`, or asyncio lock, event, semaphore, or queue.
- The implementer must stream server-sent events through `fastapi.sse.EventSourceResponse`, never `sse-starlette`.
- The implementer must let FastAPI serialize an answer through its declared return type, with no other JSON response class such as `ORJSONResponse`.
- The implementer must use `BackgroundTasks` only for work whose loss a sweep or the user's retry recovers, and put other work that follows an answer on the job queue.
- The implementer must declare each dependency once, as an `Annotated` alias beside the function it calls, and name that alias in every path operation that uses it.
- The implementer must validate a path operation's answer into its model inside the worker thread that read its rows, off the event loop.
- The implementer must set `extra="forbid"` on every request body model, declaring only the fields a client may write.
- The implementer must validate every JSON value entering the process, from a provider, a webhook, or a sealed or JSON column, with a Pydantic model or a module-level `TypeAdapter`, never a cast.
- The implementer must import at run time every name a Pydantic annotation uses, never under `if TYPE_CHECKING:`.
- The implementer must read every setting through a settings class in the one settings module, never `os.environ` or `os.getenv` elsewhere.
- The implementer must keep production code in the service's source folder and tests in its test folder.
- The implementer must not run the service with Python's optimize flags, which strip docstrings that FastAPI and the model tools read at run time.

### Errors and outside calls

- The implementer must take all key agreement, key derivation, encryption, and signing from the cryptography library or a package on it, never a hand-written primitive or record framing.

### Time

- The implementer must construct only timezone-aware datetimes, resolved through the IANA rules, with `date`, `datetime`, and `zoneinfo`.
- The implementer must turn a local date into the instant its day opens through one helper, so every caller crosses midnight and a daylight-saving change the same way.
- The implementer must store an instant in UTC beside its IANA zone name, never a UTC offset in place of the zone.

### Transactions and jobs

- The implementer must commit the record of a message to another system before it leaves, never sending from a transaction that can still roll back.
- The implementer must make every queued job safe to run twice, and test the second run.
- The implementer must run every query on a table holding a user's rows under the account its transaction sets.
- The implementer must commit a transaction only in the code that opened it, and work that commits once per item must take the session factory and open one transaction per item.
- The implementer must not read an ORM row after the commit that ended its transaction.
- The implementer must pass an integer seed drawn from the account to every random draw a fit makes, never `random_state=None` or a global seed.
- The implementer must keep a fitted model as typed values in a table, never in a format that runs code when it loads, such as pickle, joblib, or cloudpickle.

## In a Next.js web app, `{web_app}`

### What the web app's gates enforce

Every change must pass the web app's check script, whose gates enforce:

- strict TypeScript, and every escape from it, such as a cast or a non-null assertion, names its reason beside it.
- the contract gate: files under a `generated` folder are regenerated from the contract and never edited by hand.
- the token gate: every color literal sits in the token stylesheet or the one color helper, apart from the logo's brand colors.
- the boundary gate: shared folders such as `src/components/`, `src/ui/`, and `src/lib/` import nothing from `src/app/` or `src/features/`, a route's underscore-named private folder is imported only inside its route, production code imports no fixture or test, and imports form no cycle.
- Biome, which settles formatting and makes every `dangerouslySetInnerHTML` carry a suppression naming its reason, and the reviewer must not raise a preference it accepts.

### Lines the web app follows

- Every file a change touches must pass TypeScript with `noUncheckedIndexedAccess` on.
- The implementer must end every `switch` over a union with a `default` branch that assigns the value to a variable typed `never`.
- The implementer must type a value from outside the program, such as a storage read, `JSON.parse`, message data, or a caught error, as `unknown`, and narrow it with a type guard or a generated validator. The full-stack rule, `full-stack.md`, governs the service's answers.
- The implementer must keep each feature's screens, hooks, and modules in its own feature folder, a primitive two features draw in the shared component folder, and a module two features read in the shared library folder. Routes and features can import all three.
- The implementer must take every font size from the rem type scale, never pixels.
- The implementer must put every `:hover` style inside `@media (hover: hover)`, apart from a rule that gives the rest and hover states one look.
- The implementer must take every shared control word a screen shows, such as Save or Cancel, from one vocabulary module, never a hand-typed copy.
- The implementer must construct every date and time in the user's zone, never the machine's, and format each one a user reads through one formatting module with the account's clock, date format, and week start, never `toLocale*String` or `Intl.DateTimeFormat` elsewhere.
- The implementer must await or catch every promise a handler or a timer starts.
- The implementer must redirect only to an address fixed in code.
- The typed error and error text lines bind the web app too.
- The implementer must give each top-level section of the app an `error.tsx` beside its `layout.tsx`, and wrap each region that can fail alone, such as a chat panel, a chart, or a side panel, in a `catchError` boundary from `next/error` whose fallback keeps its size and offers Try again through `retry`.
- The implementer must pass every outside address, from the service, a model, or the user, through one link parser before it reaches an `href`, `window.open`, or `location`.
- The implementer must escape outside text before `innerHTML` or `dangerouslySetInnerHTML`, or clean it to a fixed tag list keeping only a parsed link with its `target` and `rel`.
- The implementer must draw a model's reply through one renderer that builds elements, never HTML, and add no second renderer.
- The implementer must not animate a layout property such as `width`, `height`, `margin`, `padding`, or a grid track, and should animate `transform` and `opacity`.
- The implementer must serve each signed-in section at the address its folder under `src/app/` gives it, never rewritten in the proxy, `next.config.ts`, or a page.
- The implementer must parse and write a page's search parameters in one module in the route's private folder, with one union type per parameter.

## Why it exists

A blocking async call is this stack's most common production defect, and a swallowed exception or a naive datetime surfaces weeks later. In the web app, an unchecked address can run script, and one failed panel without a boundary blanks the whole page.

## What is exempt

- Test code, which the testing rule governs, though the async and datetime lines bind tests.
- Generated code and migration files, reviewed for effect rather than form.
- Code that already broke a line before the line arrived, until its fix lands. A change there must not add a second instance of the same break.
