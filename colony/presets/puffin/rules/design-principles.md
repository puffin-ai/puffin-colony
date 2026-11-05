# Design principles

Applies to every design choice in the production code of the Python service, `{service}`, and the web app, `{web_app}`, and to every person and agent who writes or reviews it. Each principle binds through its stated effect, never through a principle's name. The reviewer checks each line against the diff.

## In both apps

- The implementer must shape every module as a deep module, one whose interface is smaller and simpler than the implementation behind it.
- The implementer must merge or reshape a module whose interface restates its implementation.
- The implementer must encode every constraint on a request, a stored record, or a tool argument in a type or a schema field, so the checker proves it.
- The implementer must attach a comment to every constraint left in a runtime check, stating why a type could not carry it.
- The implementer must hold an invariant over stored rows, such as one value in force at a time or one position per parent, in a database constraint, and must not hold it only in application code that a second write path can skip.
- The implementer must point every import from an outer layer to an inner layer, never the reverse.
- The implementer must keep the product's own rules in a folder named `domain` in every app, so the same rule is found under the same name everywhere and the copies can be compared and, one day, reduced to one owner.
- The implementer who creates the first package boundary must add an import contract for it in the same change, such as an import-linter contract or a boundary gate rule, so a wrong-direction import fails the lint run instead of waiting on a reviewer.
- The implementer must define a seam, meaning the point where one part of the code is swapped for another in a test, as a protocol or an interface.
- The implementer must use inheritance only where the checker verifies an implementation against a base class.
- The implementer must not build for a presumed future need, which is the scope Fowler gives YAGNI, short for you are not going to need it, and code stays easy to change rather than pre-extended.
- The implementer must not export a name that no other file imports, because an export left behind after a move reads as a live interface.
- The implementer should leave duplicated code in place until the same knowledge appears in a third place.
- The implementer must keep exactly one source of truth for every fact, and search for an existing helper before writing one.
- The implementer must move or rename a module, an address, a field, or a name in one change that updates every caller and deletes the old one, until the first release to users.
- The implementer must not add a redirect, a re-export, a second name, or a fallback reader that keeps an old module, address, field, or name working before that release, because no user holds the old one yet and the shim stays behind as a second source of truth. The full-stack rule, `full-stack.md`, sets how a field the service sends changes after that release.
- The implementer who changes a file that another app copies must make the same change to the copy in the same pull request, or must state in the pull request description why the copy keeps its own version, because copies are known duplication.
- The implementer must keep a computation whose result must replay, such as a solve or a model fit, free of reads and writes, and reach the store only from the job around it, so the result replays from its saved inputs.
- The implementer must choose the plainer construct when two constructs do the same work.
- The implementer must answer a reviewer's clarity objection by replacing the flagged construct or by commenting why it is needed.
- The reviewer must argue every design objection from its effect on the code, never from a principle's name. This rule adopts neither SOLID, the five-principle checklist from object-oriented design, nor any numeric size limit, nor any comment-density target.

## In a Python service, `{service}`

- The implementer must build every SQL statement in the one store package or in a migration, so every statement the service sends can be found, counted, and indexed in one package.
- The implementer must reach a table that a library owns, such as a job queue's table, only through the store module that wraps it, because a statement written in a string crosses layers where an import contract cannot see it.
- The implementer must reach the store from a path operation only through the read module or the write module of the route's product area, so each area's reads sit in one module.
- The implementer must hand a service to the code that uses it as an argument or on the runtime object its entry point builds, because a module global that a setter fills at start fails only when the code first runs.
- The implementer must keep an API answer's shape in its Pydantic model alone, so a store function returns typed records and one builder makes the model from them.

## In a Next.js web app, `{web_app}`

- The implementer must give each fact about the browser that two or more screens read, such as whether a key press belongs to a field, whether the device asks for reduced motion, and whether the device is online, one function in the shared library folder, and must read the fact only through that function.
- The implementer must give each feature folder its own read and write hooks on the one browser query cache, so a screen reaches its feature's data without another feature's module.
- The implementer must express the looks or states of one component that cannot hold together as one prop with a union type, such as `variant`, `size`, or `status`, and must not add a boolean prop for a look or a state that another prop already excludes.
- The implementer must build every surface of a screen from a part of the app's shared component library, and must add a missing part there, with its catalog entry when the library keeps one, before a screen uses it.
- The implementer must fix a depth, shadow, or legibility problem of a shared part inside the library, through its tokens and its layers, and must not override the part in one screen.
- The implementer must keep a sheet's primary action in its pinned footer, in view at 390 by 659 and at 1280 by 720 without a scroll.
- The implementer must hold the state of a screen or a flow whose stages exclude each other as one discriminated union keyed by `kind`, and must derive every other value from it during render.

## Why it exists

Principles enforced as checklists produce compliance instead of quality. The measured failure modes of principled codebases are over-decomposition and wrong abstractions, and these lines block both. One web pass found the test of whether a key belongs to a field written five ways and the reduced motion query read in 18 places, and found 35 of 102 copied files differing from their originals, so a fix in one copy left the other broken. Two booleans that cannot both hold let a component draw a state nobody designed, which is why [shadcn/ui](https://github.com/shadcn-ui/ui/blob/main/apps/v4/registry/new-york-v4/ui/button.tsx), [GitHub's Primer](https://github.com/primer/react/blob/main/contributor-docs/adrs/adr-004-children-as-api.md), and the React guide to [choosing the state structure](https://react.dev/learn/choosing-the-state-structure) each name one prop or one union instead.

## What is exempt

- Test code, which the testing rule, `testing.md`, governs.
- Generated code and database migration files, which carry their generator's shape and are reviewed for effect, not for form.
- Opaque fallbacks a surface draws under the user's reduced transparency or increased contrast setting, from the shared-part lines, because those fallbacks follow the user's own setting.
- Code that already broke a line before the line arrived, until the change that fixes it lands. A change to that code must not add a second instance of the same break.
