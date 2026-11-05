# Database

Applies to every table of the service's Postgres database that holds account rows, every index on it, every migration that changes it, and every backfill, in `{service}`, and to everyone who writes or reviews one. The performance-service rule, `performance-service.md`, governs the statements and the transaction one request sends to these tables.

## Indexes

These lines govern the index behind every read of a table that holds account rows.

- The implementer must serve every filter a read applies to a table holding account rows with an index that leads with `account_id`, with the parent row's key, or with a unique hash when the read runs before the account is known.
- The implementer must follow that leading column with the filter's equality columns and then at most one range or sort column.
- The implementer must add that index in the change that adds the read.
- A query's plan is its `EXPLAIN (ANALYZE, BUFFERS)` output, which the batch's review reads for a changed read on a table that grows with users.
- The implementer must run that plan as the application role with the settings the read's transaction sets, on a table that also holds the rows of at least 100 other accounts, because the superuser and the table owner skip row security and get a different plan.
- The implementer must change the index or the query until that plan shows an index scan whose condition names the index's leading column.
- The implementer must use a partial index, which covers only the rows that match a condition, only for a condition the query states as a literal, such as a state of `waiting`.
- The implementer must build an index on a table that grows with users with `CREATE INDEX CONCURRENTLY`, in a migration of its own, because a plain build locks out every write to the table while it runs and a concurrent build cannot run inside a transaction.

## Migrations and backfills

A backfill is the part of a migration that writes values into rows that already exist.

- The implementer must run every schema change from one migration history, such as Alembic's, so every database replays the same history.
- The implementer must land a schema change the running code would notice in two steps: one release adds the new shape, and a later one removes the old shape, because the old code keeps serving requests while a migration runs.
- The implementer must create a new table's row security policy in the same revision as the table, and add a changed policy before dropping the old one, because row security defaults to deny.
- The implementer must write every revision forward only, with a `downgrade()` that raises an error naming the two-step rule, because the way back from a bad release is the previous release, never a reverse migration.
- The implementer of a backfill must name in the migration which existing rows it changes and what each one holds afterwards.
- The implementer must give each backfill a test that seeds each kind of existing row the backfill changes or leaves alone, and asserts each one's value after the migration runs.

## Column types and functions

These lines govern the type of each column and every function a migration creates.

- The implementer must store a quantity that a replay, an equality test, or a screen must reproduce to the digit as `numeric`, and must not store it as `real` or `double precision`, because a float compared for equality gives a wrong result.
- The implementer must store a short list of values as `text` under a check constraint that names each value, and must not create a native enum type, because Postgres offers no way to remove a value from one.
- The implementer must give every `SECURITY DEFINER` function a `search_path` that ends with `pg_temp`, and must revoke its execute grant from `PUBLIC` in the migration that creates it, because a definer function without both lets a caller run code with the owner's privileges.

## Why it exists

A read that no index serves scans every account's rows and slows only once the table grows, so no small test catches it. A backfill that changes rows it does not name corrupts data no test seeded: in one ten-day span, three backfills went wrong, one leaving a new nullable column unfilled, one shortening existing records, and one queuing work for every existing row.

## What is exempt

- Code that already broke a line before the line arrived, until its fix lands. A change there must not add a second instance of the same break.
