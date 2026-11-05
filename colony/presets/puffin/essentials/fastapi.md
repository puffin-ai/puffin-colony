# Service essentials

This is the service, `{service}`: Python with FastAPI, Pydantic, SQLAlchemy, and Postgres. Every change in this folder obeys the lines below. The full rules in `.colony/rules/` are the reviewer's checklist, and each line names the rule and the section that hold it in full.

## Checks

- Per change: `{fast_check}`, with the tests that match the change.
- Per batch: `{checks}`, which `colony batch` runs with a fresh review.
- When you are unsure how a library behaves, read `.colony/rules/docs.md` before you guess.

## The lines every change here obeys

1. You must keep every read route at its statement cap, with each kind of row loaded in one statement and each row read once. (`performance-service.md`, Statements a request sends)
2. A GET must only read: no row lock, no write but the session's last use and the rate-limit count, and no solve, model call, or outside call. An OAuth redirect route is the one exception. (`performance-service.md`, Transactions and connections, and Work kept off the request path)
3. You must build every SQL statement in the store package or a migration. (`design-principles.md`, In a Python service)
4. You must commit a transaction only in the code that opened it. (`coding.md`, Transactions and jobs)
5. You must define each answer in its Pydantic model, and must export the contract and regenerate the web app's types in the same change. (`design-principles.md`, In a Python service, and `full-stack.md`, The contract)
6. You must check the caller's right inside every route and every `SECURITY DEFINER` function, and must give every route that names a record a cross-account test. (`security-and-privacy.md`, Account data, and `full-stack.md`, Tests across the boundary)
7. You must make every write, job, and message safe to repeat: a write carries the revision it read and an operation identifier, a repeat answers the first result and finishes every step, and a message leaves only after its record commits. (`coding.md`, Transactions and jobs, and `full-stack.md`, The forwarder and the write path)
8. You must turn a local midnight into an instant only through the one helper for it, and must store an instant in UTC beside its IANA zone name. (`coding.md`, Time)
9. You must re-check the user's switch and AI permission inside the transaction that keeps or sends their data. (`security-and-privacy.md`, Account data)
10. You must parse every outside or stored JSON value through its Pydantic model or a `TypeAdapter`, never a cast. (`coding.md`, Async and requests)
11. You must give a model call that reads outside text no tool that writes, sends, or deletes, must hand it outside text only as a labeled tool result, and must build instructions only from the one prompt module. (`security-and-privacy.md`, Model calls and outside text)
12. You must give a bug fix or new logic a test that fails without the change. (`testing.md`, In both apps)

## Facts the code does not show

- You must mark async test modules with the AnyIO marker and never use pytest-asyncio. (`testing.md`, In a Python service)
- Endpoint docstrings go to the OpenAPI export, and a model tool's description goes to the model, so both are load-bearing text.
- You must not change dependencies or the lockfile without the person's yes, because the version ranges are deliberate.
