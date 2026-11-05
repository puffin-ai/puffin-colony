# Essentials

Every change in this folder obeys the lines below, beside the core in `.colony/core.md`. The full rules in `.colony/rules/` are the reviewer's checklist, and each line names the rule that holds it in full.

## Checks

- Per change: `{fast_check}`.
- Per batch: `{checks}`, which `colony batch` runs with a fresh review.

## The lines every change here obeys

1. You must keep the change inside the card's folders and to one concern, and must make a new card for anything else you find. (`coding.md`)
2. You must search for an existing helper, type or component before you write one, and must import it, never copy it. (`coding.md`)
3. You must change every caller in the same change when you rename or reshape a function, and must add no compatibility shim before the first release. (`coding.md`)
4. You must check input at the edge of the system, and must never catch an error only to hide it. (`coding.md`)
5. You must give a bug fix a test that fails without the fix, and new logic a test of each rule it promises. (`testing.md`)
6. You must keep tests fast and deterministic: a fixed clock, seed and time zone, and no real network or paid service. (`testing.md`)
7. You must check the caller's right on the server before you read or change a record, and must keep secrets out of code, logs and commits. (`security.md`)
8. You must not run a query or an outside call inside a loop over rows, and must page every list that can grow. (`performance.md`)
9. You must make every action work with the keyboard and give every control a name, and must check touch or layout work at phone width, 390 by 844. (`accessibility.md`)
10. You must commit as `type(scope): what changed` on your own branch, and must never push to the base branch. (`git.md`)
