# Real-use testing

After a release deploys, a tester checks its cards on the deployed app, the way a person would use it. The lead opens one with `colony tester "<the release pull request>"`, and the person can open more on other computers. This page covers what the testers share: the test accounts and fixtures the person prepared, and one findings list per release.

## Test accounts and fixtures

A person often prepares test accounts and test data before testing starts, such as an admin account on staging, a shop seeded with orders, or a sandbox payment account. Colony keeps a list of them, the registry, in `.colony/fixtures.toml`. It is committed with the repo, so every tester and every lead on every computer reads the same list, and reuses what is there instead of asking the person again.

The registry holds references only: what each one is, where it lives, its login name, how to make or reset it, and where its secret is kept, such as a password manager's entry. It never holds a password, a token or any other secret: `colony fixtures add` refuses a value that looks like one.

```sh
colony fixtures add account staging-admin --what "an admin account on staging" --where staging \
  --login qa-admin@example.test --secret-at "the team vault, entry QA admin"
colony fixtures add fixture seeded-shop --what "a shop with 40 orders" --how "make seed-shop"
colony fixtures
```

- `colony fixtures` lists them, and `--json` prints them for a script. `colony fixtures remove <name>` drops one. Adding a name again replaces it.
- Commit `.colony/fixtures.toml` with your next change, so the other computers read it.
- `colony findings open` prints the registry for each tester before it starts, and the tester's brief tells it to use these first.
- `colony needs` refuses a question about test accounts or test data while the registry holds any, and names them, so the lead reuses one. When none fits, the lead asks again with `--new-fixture`, and says what the registry lacks.

## The findings list

Each release has one findings issue on the code host, titled `test: findings for the release #<n>`. Every tester shares it, on any computer: each one claims a card, tests it, records the result, and takes the next.

| Step | Command |
| --- | --- |
| Find the release's findings issue, or make it with the release's cards | `colony findings open <release>`. The cards are the ones each batch the release lists closes, or the ones `--card <n>` names. |
| Claim the next card that no tester holds and none has tested | `colony findings next <release>` |
| Record what you saw | `colony findings report <release> <card> pass\|fail\|blocked "<what you saw>"`. A fail or a block needs the note. |
| Claim one card by its number, such as a blocked one to test again, or renew your own claim | `colony findings claim <release> <card>` |
| Hand a card back, untested | `colony findings free <release> <card>` |
| Bring the list up to date and print it | `colony findings show <release>` |

**How it stays current.** Each claim and each result is one comment on the issue, such as `findings: fail #12: the button does nothing on a phone (by tester on laptop)`. Every command reads all of them and rewrites the issue's table, its counts, and its sections of failures and blocked cards. So the list is current while any tester works, and no one tester or lead owns it. Only the team's issue and the team's comments count: the logins in `[people] logins`, or, with none, people with access to the repo. An issue anyone else opens with the same title is never the list, and a card's title or a note can't change the list's hidden copy of its cards.

**Races.** When two testers claim the same card at once, the earlier comment wins, and `colony findings next` moves the other one on to the next card. When two testers open the list at once and each makes an issue, the one that then sees the older issue closes its own as a duplicate and uses the older one.

**Testers that stop.** A claim with no result lapses after `[testers] claim_minutes`, 60 by default, so a tester that stopped frees its card for the others. A tester on a long card renews its claim with `colony findings claim` again.

**When it is done.** When every card has a result, the command that recorded the last one prints the `done` line for the lead, on the release pull request. The lead turns each failure into a card, and closes the findings issue once every failure has its card.

A tester is named by its session and its computer, such as `tester on laptop`; `--as <name>` names it otherwise.
