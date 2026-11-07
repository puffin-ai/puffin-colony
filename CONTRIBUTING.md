# Contributing to Puffin Colony

Thank you for helping. Bug reports, ideas and pull requests are all welcome.

## Before you start

- For a bug, open an issue with the bug form: what you ran, what you expected, and what happened.
- For a new feature, open an issue with the feature form first, so we can agree on the shape before you write code.
- For a security problem, don't open an issue. Follow [SECURITY.md](SECURITY.md).

## Set up

You need Python 3.11 or later, [uv](https://docs.astral.sh/uv/), and `git`. Clone the repo, then run the tests:

```sh
uv run --with pytest pytest -q tests
```

Colony uses only the Python standard library, so there is nothing else to install. The tests use real `git` repositories in temporary folders and stub `gh`, `claude` and `cmux`, so they need no network and no accounts.

## Make a change

- **One concern per pull request.** A fix, a feature or a docs change, small enough to review in one sitting.
- **Add a test.** A bug fix comes with a test that fails without it, and new behavior comes with a test that shows it.
- **Keep the standard library only.** Ask in an issue before you add a dependency.
- **Update the docs.** A change to a command or a setting updates [docs/commands.md](docs/commands.md) or [docs/configuration.md](docs/configuration.md) in the same pull request.
- **Write plainly.** Short sentences and everyday words, in the code's comments and in the docs.

Run the full tests before you open the pull request, and fill in its template.

## Code of conduct

Everyone who takes part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
