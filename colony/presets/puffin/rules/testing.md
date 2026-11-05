# Testing

Applies to every test in the Python service's test folder, `{service}`, and the web app's tests, `{web_app}`, and to every person and agent who writes or reviews one. The reviewer checks each line against the diff and names the changed lines no test covers.

## In both apps

- The implementer must give every promised behavior a test that fails without the change: a bug fix carries a regression test, new logic carries a test, and a style change carries none.
- The implementer must give each test one state-changing act and a name stating the behavior it checks.
- The implementer must make every test fail when the behavior its name states breaks, and must not assert on a value only the test's own arrangement wrote.
- The implementer must assert observable outcomes at the unit's contract surface, and must not assert internal structure, call sequences, or collaborator interactions, so a correct redesign of the internals passes the same tests unchanged.
- The implementer should prefer sociable tests, meaning tests that run against real collaborating objects rather than doubles, at service boundaries.
- The implementer must never read the real clock, sleep, or set a real timer in a test.
- The implementer must keep every test away from real model providers and paid services.
- The implementer must write a test's files only under its temporary folder, and must not write into the source folders.
- The implementer must not add a retry plugin or a rerun marker, because a rerun hides a flaky test.
- A removed, skipped, or weakened test waits for the person's explicit yes, and the reviewer refuses one without it.

## In a Python service, `{service}`

- The implementer must mark async test modules with `pytestmark = pytest.mark.anyio`, and must not install or configure pytest-asyncio, because the two plugins' auto modes conflict and this stack's own libraries run on AnyIO.
- The implementer must give every test a size, small or medium, through the suite's markers, and must not let a small test reach the database, a network socket, or a new process, or finish more than 100 milliseconds of sleep in all, because a CPU limit cannot see a sleep.
- The implementer must keep a small test's call under 100 milliseconds of CPU time and a medium test's call under 2 seconds of CPU time, because a slow suite ends an agent's session on its limits. The limit counts the CPU time of the test's process and of the children it waits for, because a busy machine stretches the wall clock of a test that does little work. A 30-second timeout stays every test's wall-clock limit.
- The implementer must run pytest with strict markers, so an unknown marker fails, and with every warning raised as an error.
- The implementer must give every warning filter a comment that names its upstream issue.
- The implementer must test agent behavior through the agent framework's test doubles, such as Pydantic AI's `Agent.override` with `TestModel` or `FunctionModel`, and must turn every real model request into an error in the root conftest, such as with `ALLOW_MODEL_REQUESTS = False`.
- The implementer of a test that needs real provider traffic must record it as a VCR cassette with pytest-recording, must add the request body to the cassette matcher, and must keep every credential header out of the cassette, because the default matcher ignores bodies and a drifted request keeps passing silently.
- The implementer must control wall-clock time with time-machine.
- The implementer must give code that measures a duration on a monotonic clock its clock as an argument, defaulting to the real one, and must drive that clock with a fake in the test, because time-machine does not move the monotonic clock.
- The implementer may block the event loop in an async test's arrangement, before its act, because no request waits on the loop while a test builds its state. Ruff's `ASYNC` rules still read every async test, so the arrangement makes such a call in a synchronous fixture or helper.
- The implementer must sign a service, API, or contract test's account in through the test support's direct sign-in helper, and only the sign-in tests use the real sign-in routes.
- The implementer must build a service, API, or contract test's starting state through the test support's builders wherever a command produces that state, and must perform only the one act the test checks.
- The implementer must build a starting state that every test in a module only reads once per module, with each test's writes rolled back, unless a test commits through another connection or starts a process.
- The implementer must start a real process only for an entry point's start test, a streaming test, a signal or shutdown test, a race between processes, an isolation test, or a load run.
- The implementer must test the database against a real Postgres container with per-test rollback, never against SQLite.
- The implementer of a migration that moves or rewrites rows must add a test that upgrades a database holding rows to its revision and checks them.
- The implementer of code that turns a local time into an instant must test it on both daylight-saving changes of a zone that has them.
- The implementer of a framework upgrade must keep a round-trip test passing on data the previous version stored, and must not regenerate that recording in the upgrade.
- The implementer must keep a benchmark's or an evaluation's checker free of imports from the code it checks, because a checker that shares that code passes its bugs.
- The implementer must test streaming delivery, disconnects, and backpressure, meaning the server slowing when a client cannot read fast enough, against a real server process, because the in-process transports buffer entire streams.

## In a Next.js web app, `{web_app}`

- The implementer must run every web test through the runner the app's `npm test` invokes, and must not add a second test runner.
- The implementer must control time with the suite's fixture clock.
- The implementer must keep every shared account description in one fixtures folder, and each fixture builder the web tests share in one support folder.
- The implementer must keep production code free of imports from fixtures and tests.
- The implementer must assert what the user or the caller can observe.
- The implementer must not read a source file's text in a test outside the architecture tests, because such a test passes while the screen breaks.
- The implementer must find an element in a component test by its role and its accessible name, or by its `data-slot`, and must not assert a class name, because the user never sees a class and a restyle would then fail a test whose behavior still holds. The architecture tests can read class names when the stylesheet contract is their subject.
- The implementer must put the decision a key, pointer, or gesture handler makes in a pure function of the event and the state, and must test that function, because the test runner draws markup without a browser and cannot press a key.

## Why it exists

A test suite that can silently call a paid provider, drift from the requests it claims to check, or pass while the stream it cannot observe breaks protects nothing while every test passes. The query order in the web app comes from [Testing Library](https://testing-library.com/docs/queries/about#priority) and the stable selectors of [GitHub's Primer](https://github.com/primer/react/blob/main/contributor-docs/adrs/adr-023-stable-selectors-api.md).

## What is exempt

- An evaluation suite's real-model runs, which carry their own budget and the person's yes.
- A live check that runs by hand against a running service and never in the default test run, from the real clock line, when the real clock is its subject.
- Tests that already broke a line before the line arrived, until a change to the test fixes it. A change to such a test must not add another instance.
