# Testing

Applies to every change that alters behavior.

## Must

- A bug fix carries a regression test that fails without the fix and passes with it.
- New logic carries a test of what it promises: each rule, branch and edge the card names.
- A style or copy change carries no new test.
- Test behavior through the public surface: the function's arguments and result, the endpoint's request and response, what the user sees and does.
- Put each test next to the tests of the same code, in the repo's test folder, named the way its neighbors are.
- Give each test one reason to fail, and a name that says what it shows.
- Keep tests fast and deterministic: fix the clock, the random seed and the time zone, and use no real network.
- Build test data with the repo's own factories or fixtures when they exist.
- For touch or layout work, check the screen in a browser at phone width, 390×844, as well as in the test.
- Run the fast check before every commit, and the full check before a batch.

## Must not

- Delete, skip or loosen a failing test to make a change pass. When an expectation is wrong, change it in the same commit as the behavior, and say why in the message.
- Mock the code under test, or assert on private details that a refactor would change without changing behavior.
- Let a test reach a paid service or a real provider.
- Leave a test that passes whether or not the change is there.
- Sleep in a test to wait for something: wait on the event itself.
