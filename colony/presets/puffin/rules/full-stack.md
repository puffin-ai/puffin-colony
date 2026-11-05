# Full stack

Applies to every place where the web app, `{web_app}`, and the Python service, `{service}`, meet: the contract, refusals, the forwarder and the write path, the request identifier, freshness after a write, cookies, and the tests that keep both sides in step, and to every person and agent who writes or reviews one of them. The reviewer checks each line against the diff.

These names hold on this page:
- The contract is the service's committed OpenAPI export, the one description of every route, and the web app's types and validators are generated from it.
- The forwarder is the web app's one route handler that passes every browser call under the API prefix to the service.
- The transport is the web app's one HTTP client module, and every client the web app builds sits on it.
- The refusal body is the one error shape the contract declares for every answer with a status of 400 or higher.

## The contract

- The implementer must change a route, a request shape, or an answer shape in the service first, and must commit the regenerated export and every file the generator writes from it in the same change.
- The implementer must not name a route, a field, or a refusal code in the web app's production code before the committed export declares it, because the forwarder then admits a call that no contract test covers.
- The implementer must change the export only by adding a route, an optional request field, an answer field, or a refusal code once the first release to users has shipped, because an open browser tab keeps running the bundle it loaded while the service deploys a newer export.
- The implementer must remove or rename a field in two releases once the first release to users has shipped. The first release makes the web app stop sending and reading the field while the service still accepts and sends it, and the second removes it from the service.
- The implementer must remove or rename a field in one change before the first release to users, with the service, the export, and the web app changed together and no fallback reader left, as the design principles rule, `design-principles.md`, sets for every move.
- The implementer must keep every constraint the export states, such as a length, a pattern, a range, or a list of allowed values, in the generated validator built from it, so the browser refuses what the service refuses.
- The implementer must send every new call from the web app to the service through the transport, which checks each answer with the export's generated validator before any code reads it.
- The implementer must give each component schema of the export the name its web type should carry, because the generator names each type and its validator after the schema's name.
- The implementer must give every route a rate-limit ceiling in the one limits table, and must not add a route without one.

## Refusals

- The implementer must answer every refusal that reaches the browser with the refusal body, carrying a code from the export's code set, a bounded message, and optional details, at the actual HTTP status.
- The implementer must name each field a refusal concerns by its path in the refusal's details, so the screen marks that field.
- The implementer must not put a value the caller sent into a refusal's message or details.
- The implementer must keep the API's request body cap at 1 MiB in one guard, and must not exempt a route from that guard.
- The implementer must throw only the one service error class from the web app's service modules.
- The implementer must turn a failed call into what a screen shows only through one failure function, so one failure reads the same on every screen.

## The forwarder and the write path

The performance rule, `performance.md`, sets how a server render reads the service directly. These lines govern the browser's path.

- The implementer must admit a route through the forwarder only from the generated route table.
- The implementer must name each header the forwarder passes, in either direction, together with a pattern its value must match.
- The implementer must log every fault the forwarder raises itself, such as a missing setting, with its request identifier.
- The implementer must answer such a fault with a refusal body whose code names the fault.
- The implementer must send every write a signed-in session makes from the browser through the forwarder with the session's write token.
- The implementer must refuse in the service every request other than a GET on a session route that lacks its session's write token, and must not exempt a route from that check, because the cookie's SameSite setting only helps.
- The implementer must not turn off FastAPI's strict content-type check on a JSON body, because that check blocks a cross-site form post.
- The implementer must send each write through its feature's write hook with the revision it read and one operation identifier, and must reuse that identifier only when the same command is resent.
- The implementer must have the service refuse a stale revision and a reused operation identifier that carries another command, and must answer a repeat of the same command with the first write's result after finishing every step of that write.
- The implementer must not add a Server Action that writes under a session, because the forwarder's origin check and the service's write token guard the forwarder's path alone.
- The implementer must check authorization inside every Server Function, a function marked `"use server"` that the browser calls as a POST to its page's route, because that call does not pass through the page that rendered it.
- The implementer can read through a Server Action only to keep the user's words out of a page address, such as a list search, because Next.js queues a page's Server Actions and runs them one after another.

## The request identifier

The API process makes one identifier for every request and returns it in the `X-Request-ID` header.

- The implementer must pass the service's `X-Request-ID` through the forwarder on every answer, the forwarder's own refusal of a failed service answer included.
- The implementer must keep that identifier on every service error the transport builds from an answer.
- The implementer must send that identifier with each failed-request report and crash report the browser sends, so the report lands beside the service's own lines for that request.
- The implementer must not send the service an `X-Request-ID` from the forwarder or from a server read, because the service makes its own for every request and trusts none a caller names.
- The implementer who turns on a trace store must have the forwarder and each server read start a new W3C `traceparent` for every incoming request, and must not continue one the browser sent, because the browser is an untrusted caller.

## Freshness after a write

The performance-service rule, `performance-service.md`, keeps every session route's answer out of shared caches, so the browser's query cache is the one layer that keeps an account's answers between requests.

- The implementer must build each query key through a key function exported beside the read it names, with the account identifier as the key's second element, so a writer, a read-ahead, and sign-out reach every key an account holds.
- The implementer must, after a write succeeds, write the answer the write returned into the query cache or invalidate every query key whose answer the write changed, in the module that sends the write.
- The implementer must roll back an optimistic change on screen when the service refuses its write.

## Cookies

- The implementer must give every new cookie the service sets the `__Host-` prefix, with `Secure`, `Path=/`, and no `Domain`, so no other host under the product's domain can set or replace it.

## Tests across the boundary

- The implementer who changes the forwarder or the transport must give each changed behavior a test that sends a call through it with a fake `fetch` and asserts what the browser receives.
- The implementer must type every fake service answer a web test builds with the export's generated type, so a contract change that breaks the fake fails the typecheck.
- The implementer who adds a route whose path names a record must add a test in which another account's session asks for that record and receives the status and body a request for a missing record receives.

## Why it exists

The web app and the service deploy apart, and a browser tab keeps the bundle it loaded, so a change that breaks the contract breaks open tabs before any test sees it. A second client, a second error class, or a route listed by hand beside the export makes one failure read two ways and lets through a call that no contract test checks. A request identifier that stops at the forwarder leaves a user's report with nothing to find the service's lines by.

## What is exempt

- A query key whose read decides which account the page is signed in with, from the account identifier as its second element, because it cannot name that account.
- Code that already broke a line before the line arrived, until the change that fixes it lands. A change to that code must not add a second instance of the same break.
