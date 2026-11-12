# Essentials

Every change in this folder obeys the lines below. The full rules in `.colony/rules/` are the reviewer's checklist, and each line names the rule that holds it in full.

## Checks

- Per change: `{fast_check}`.
- Per batch: `{checks}`, which `colony batch` runs with a fresh review.
- When you are unsure how a library behaves, read `.colony/rules/docs.md` before you guess.

## The lines every change here obeys

1. You must search for an existing helper, type, or component before you write one, and must keep one source of truth for every fact. (`design-principles.md`)
2. You must move or rename a module, a field, or a name in one change that updates every caller and deletes the old one, and must add no redirect, re-export, alias, or fallback reader before the first release to users. (`design-principles.md`)
3. You must check every value from outside the program, a request, a file, a provider's answer, or a stored JSON value, into a typed shape at the edge, never a cast. (`coding.md`)
4. You must raise typed errors, handle each one where something useful can happen, and must never catch an error only to hide it. (`coding.md`)
5. You must give every call to another service a deadline and a ceiling on its answer's size, and must retry it at one point only. (`coding.md`)
6. You must make every write, job, and message safe to repeat, and must send a message only after its record commits. (`coding.md`)
7. You must check the caller's right inside every handler that names a record, and must give it a test in which another account asks for that record. (`security-and-privacy.md`)
8. You must keep keys, tokens, passwords, and `.env` values out of logs, the browser, and the repository. (`security-and-privacy.md`)
9. You must store an instant in UTC beside its IANA zone name. (`coding.md`)
10. You must give a bug fix or new logic a test that fails without the change, and must never read the real clock, sleep, or reach a real provider in a test. (`testing.md`)
11. You must not add, remove, or upgrade a dependency without the person's yes. (`.colony/playbook.md`, Stop list)
12. You must add no shim before the first release to users, such as a redirect, a re-export, an alias, or a fallback reader for an old shape, and must change every caller instead and delete the old name. (`design-principles.md`)
