# Performance of the service

Applies to every path operation of the Python service's API, every store function a request calls, and every service cache, in `{service}`, and to everyone who writes or reviews them. A read route answers a GET. Each budget is a lab figure, at or under the production target. The database rule, `database.md`, governs indexes, and the performance rule, `performance.md`, the web app.

## Statements a request sends

A statement is one SQL command sent while answering a request.

- The implementer must read each kind of row a request needs with one statement for all the answer's records, read each row at most once per request, and pass it to every helper that uses it.
- The implementer must select only the used columns from a row holding a JSON or binary column the answer does not read.
- The implementer must declare every ORM relationship with `lazy="raise"`, and load it with `selectinload` or `joinedload` in the query that reads it.
- The implementer must keep every read route at or under 15 statements a request, the session check and the rate-limit count included. A route that needs more states its own cap and the reason beside its test.
- The implementer who changes a read route must give it a test that counts every statement of one request, `set_config` included, asserts the cap, and asserts equal counts for an account holding one of every collection the route loops over and one holding 20 of each.

## Transactions and connections

- The implementer must read a route's whole answer in one transaction, opened through the one helper that sets the caller's account.
- The implementer must open the database session a streaming answer uses inside its generator, because a session a dependency injects closes before the first event or holds a connection for the whole stream.
- The implementer must not take a row lock, such as `SELECT … FOR UPDATE`, inside a GET.
- The implementer must limit a GET's writes to the session's last use, the rate-limit count, and each write whose reason the code cites beside it, and queue other work a read discovers to run after the answer.
- The implementer must set every database setting with `set_config(name, value, true)`, never a session-level `SET`, so a transaction-mode connection pooler stays possible.
- The implementer must set `statement_timeout` local to every transaction, 5 seconds for the API and 60 for any other process.
- The implementer must build every engine with `pool_use_lifo=True`, and hold a connection only for the transaction that needs it.

## Caching

- The implementer must add a cache only for a measured need, and record its key, its lifetime, and its reason beside its code in the same change.
- The implementer must key a cached value built from an account's rows by the account and the revision of those rows, keep it from every other account, and bound an in-process cache by entry count and a lifetime of at most five minutes.
- The implementer must send `Cache-Control: private, no-store` on every session route's answer, and `public`, `max-age`, or `stale-while-revalidate` only on an answer holding no account's data.
- The implementer must build an `ETag`, the version tag a client sends back, from every input the answer reads, the clock included, test that changing each input changes it, and run the session check and the rate-limit count before answering `304 Not Modified`.

## The shape of an answer

- The implementer must shape a read route so one page section waits on one request, and add no route answering part of an existing route's answer for the same page.
- The implementer must validate and encode an answer over 100 KB in the worker thread that read it and return the bytes.

## Work kept off the request path

- The implementer must not run a solve, a model call, an outside call, or a heavy computation inside a GET.
- The implementer must compute a value a read would derive per record or per request in the write or job that changes its inputs, and store it with their revision.

## Read route budgets

The local benchmark sends 5 warm-up then 50 sequential requests to one route on the local stack, as the heaviest test account, timed from send to last byte.

- The implementer must run it with the one-minute load average below half the core count.
- The implementer must keep every read route at or under 100 milliseconds at the 95th percentile, unless its test states a higher budget and why, and each route within three times its budget at 4 requests at once.
- The implementer must send a `Server-Timing` header with application time, database time, and statement count on every answer outside production, and never from production.
- The reviewer must refuse a change that raises a count or a 95th percentile past its budget, raises a route's count already past its cap at all, or raises a 95th percentile already past its budget by over 10 percent on the median of 5 runs.

## Why it exists

One Python process serves many requests at once, so a slow read slows its neighbors. One measured read took 3.3 seconds with 171 statements while its statement test passed, because the test's account held one of each collection.

## What is exempt

- From the budgets, background jobs and command routes, which carry their own targets.
- Test code, under the testing rule.
- An OAuth redirect route, from a GET's row lock, write, and outside call limits, because under RFC 6749 the provider returns the browser with a GET. It can delete the flow's authorization request, write the connection with its sealed credential, and queue the first read's jobs.
- Code that already broke a line before the line arrived, until its fix lands. A change there must not grow a count at all, or a timing by over 10 percent.
