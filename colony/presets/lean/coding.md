# Coding

Applies to every change to source code.

## Must

- Keep each change to the card's folders and to one concern. Make a second card for anything else you find.
- Search the code for an existing helper, type or component before writing a new one, and use it.
- Keep one source of truth for each fact: a constant, a type, a schema. Import it; never copy it.
- Change every caller when you change a function's name, arguments or return shape.
- Follow the patterns the nearest files already use: naming, folder layout, error handling, formatting.
- Name things for what they hold or do, in the words the product uses.
- Handle each error where you can do something useful with it, and let the rest reach the caller with its cause.
- Check input at the edge of the system: requests, files, environment, user input. Trust it inside.
- Write a comment only where the code can't say why: a workaround, a limit, a non-obvious rule.
- Delete code, files and flags the change leaves unused.
- Run the fast check before every commit, and fix what it reports.

## Must not

- Add, remove or upgrade a dependency without the person's yes.
- Add a compatibility shim before the first release: a redirect, an alias, a re-export, a fallback reader for an old shape.
- Catch an error only to hide it, or return a default that makes a failure look like success.
- Leave debug output, commented-out code, or a TODO without a card number.
- Silence a linter, type checker or test to get a change through.
- Write a file that a build generates, except by running the command that generates it.
- Reformat code the card doesn't touch.
