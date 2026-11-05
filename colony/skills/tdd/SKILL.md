---
name: tdd
description: Test-first development, one red-to-green slice at a time, with tests worth keeping. Use when you build new logic or fix a bug and its card asks for tests, when someone says red-green-refactor or test-first, or when you are unsure what a good test of a change looks like.
---

# Test-driven development

The loop is red, then green: a failing test, then just enough code to pass it. This page is what makes the tests worth keeping. Read it before the first test of a change, and come back to it on each slice.

## What a good test is

A good test checks behavior through the public surface: a function's arguments and result, an endpoint's request and answer, what a person sees and does. It reads like a line of the spec, such as "a member can't see another team's invoice", and it survives a refactor that keeps the behavior.

```python
# Good: checks what the caller sees, with an expected value written out by hand.
def test_total_adds_each_line():
    assert total([Line(price=10), Line(price=5)]) == 15

# Bad: the expected value is computed the way the code computes it, so it can never disagree.
def test_total_adds_each_line():
    lines = [Line(price=10), Line(price=5)]
    assert total(lines) == sum(line.price for line in lines)
```

## Seams

A **seam** is the public boundary a test stands on. Tests live at seams, never against internals. The card's done-when results name the behaviors; pick the seam that shows each one, and write the seams down before the first test. When a seam is unclear, send the lead a question with your pick, and keep going on it.

## Mocks

Mock only at the edge of the system: a paid or outside service, the clock, randomness, and sometimes the file system or the database (prefer a test database). Never mock your own modules or the code under test. Make an edge easy to stand in for by passing it in:

```ts
// Easy to replace in a test: the client comes in as an argument.
async function chargeOrder(order: Order, payments: Payments) {
  return payments.charge(order.total);
}
```

Prefer one small function per outside call, such as `getUser(id)` and `listOrders(userId)`, over one generic `fetch(path)`, so each stand-in returns one shape.

## Signs of a bad test

- **Tied to the implementation**: it mocks an internal part, calls a private function, checks call counts or order, or reads the database instead of the interface. It breaks on a refactor that changes no behavior.
- **Tautological**: the expected value restates the code, so it passes by construction. Take expected values from a known literal, a worked example or the spec.
- **Horizontal**: all tests written first, then all code. Bulk tests check imagined behavior. Work in **vertical slices**: one test, one piece of code, repeat, each slice a **tracer bullet** that learns from the last.

## The loop

1. Write one failing test at an agreed seam, and run it: watch it fail for the reason you expect.
2. Write only enough code to pass it. Add nothing the next test hasn't asked for.
3. Run the test and the fast check, and watch them pass.
4. Take the next slice.

Refactoring is not a step of the loop. Do it after the slices pass, as its own commit, with the tests green before and after.

## Done

Every done-when result on the card has a test that failed before the change and passes after it, every test sits beside the tests of the same code and is named for the behavior it shows, and no test reaches a real network, a paid service or the real clock.
