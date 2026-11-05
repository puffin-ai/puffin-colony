# Performance

Applies to how fast every page of the Next.js web app, `{web_app}`, loads and moves: every file of its source folder and its `next.config.ts`, and every person and agent who writes or reviews one. The performance-service rule, `performance-service.md`, covers the service's read routes. The reviewer checks each line against the diff and the figures the batch quotes.

A figure in milliseconds or kilobytes is measured on a production build that `next build` and `next start` serve against the local stack, in desktop Chromium. A browser walk is clicking through that build in Chromium with the developer tools recording. These lines were reviewed against Next.js 16 and TanStack Query 5.

## Navigation

A client navigation swaps the page inside the layouts it shares with the last page, and a document load starts the whole page again.

- The implementer must render every link to a page of the app with `next/link`.
- The implementer must pass `render={<Link href={...} />}` when a library's `render` prop draws a link to a page of the app.
- The implementer can use a plain `<a href>` for a download, a new tab, an outside address, a route handler, and a deliberate reload such as signing out.
- The implementer must name the reason in a comment beside every plain `<a href>` that points at a page of the app.
- The implementer must draw a frame that several pages share, such as a sidebar or a tab rail, in the `layout.tsx` those pages share.
- The implementer must not render a shared frame from a `page.tsx`, because the frame then draws again on every tab switch.
- The implementer must mark the open tab in a Client Component that reads the address through `usePathname` or `useSelectedLayoutSegment`, since a layout does not re-render on a client navigation.
- The implementer must make every tab switch paint the destination's loading state or its content within 150 milliseconds of the click.
- The implementer must make every tab switch show the destination's own data within 1 second.
- The implementer should leave a link's `prefetch` at its default, so the click paints from memory.
- The implementer must not send a full prefetch, through a `prefetch` prop set to `true`, a hover or focus `prefetch`, `unstable_dynamicOnHover`, or a full `router.prefetch`, outside one read-ahead budget module, because a full prefetch spends the account's service reads.
- The implementer should show a pending mark through `useLinkStatus` on a link whose destination was not prefetched.
- The implementer must stop a move that would lose unsaved edits through the `onNavigate` handler of `<Link>` or the app's one navigation guard.
- The implementer must not add another way to stop a move.

## Server reads

A Server Component renders on the server and sends no code to the browser. Every `page.tsx` and `layout.tsx` is one unless its file starts with `"use client"`.

- The implementer must keep every `page.tsx` and `layout.tsx` a Server Component.
- On a full page load, the implementer must read a page's first data in its Server Component and pass it to the Client Components that draw it.
- The implementer must serve a client navigation from the browser's query cache, and must read on the server only on a full page load.
- The implementer must not read the service's data inside a `useEffect` or `useLayoutEffect` body, through a service read, `fetch`, or a query client's fetch.
- The implementer can use an effect for a subscription, a timer, the DOM, or a browser-only API, with a comment naming that reason where the code does not.
- The implementer must compute a value that props or state already determine during render.
- The implementer must not copy such a value into state from an effect.
- The implementer must start every independent read before awaiting any of them.
- The implementer must await each read in the component that draws its answer, or pass the read's promise to that component.
- The implementer can await the reads one component draws together, with `Promise.all` or `Promise.allSettled`.
- The implementer must start a read after another read only when it uses a value from that read's answer.
- The implementer must send every server read through the one server session loader or through a function wrapped in React `cache()` at module scope, so a read is sent once per request.
- The implementer must not call the app's own API forwarder from server code.
- The implementer must not keep an account's data in a module-scope value in server code, because one server process serves every account.
- The implementer must check that the user may see a page's data in that page's server read or in the service, because the proxy skips prefetches and a layout does not re-render on a client navigation.
- The implementer must not leave that check to a layout or the proxy alone.
- The implementer must await a read in a `layout.tsx` only when its answer decides a redirect or a refusal before the page draws.
- The implementer must start every other read a layout needs without awaiting it and read its answer under a Suspense boundary.
- The implementer must keep every page's time to first byte, TTFB, at or under 800 milliseconds.
- The implementer should send logging and usage events the page does not draw through `after()` on the server or `navigator.sendBeacon` in the browser.

## Loading states and streaming

Streaming is the server sending the page in parts, the frame and loading states first and each part's content as its read answers.

- The implementer must give every route segment whose page awaits a read a `loading.tsx`, in that segment's folder or a parent folder below the root.
- The implementer must count every read a `layout.tsx` awaits against the 800 millisecond TTFB budget.
- The implementer must draw each `loading.tsx` and each Suspense fallback as a skeleton at the size and position of the content that replaces it, and must use a spinner only inside one module.
- The implementer should wrap a read the page's main content does not use, such as a count in a sidebar, in its own Suspense boundary.
- The implementer must call `redirect()`, `notFound()`, and `forbidden()` before the first Suspense boundary of the response, so the response carries its real status code.
- The implementer must place a `<Suspense>` boundary in the parent of the async component it waits for.
- The implementer must not return a `<Suspense>` boundary from inside the async component it waits for, because its fallback never shows.
- The implementer must call `redirect()` outside every `try` block, because a `catch` swallows the redirect.

## Requests sent once

These lines keep one page load from sending the same service read twice.

- The implementer must make each page load send every service read at most once, counting the server render and the browser together.
- The implementer must await a browser read that is already in flight, also after a deadline passes.
- The implementer must hand data the server read to the browser's query cache through `HydrationBoundary`, or through `initialData` together with `initialDataUpdatedAt`.
- The implementer must not pass `initialData` without `initialDataUpdatedAt`, because the query then treats a server read of any age as fresh.
- The implementer must give every query that receives server data a `staleTime` above 0.
- The implementer must not draw a query's answer in the Server Component that prefetched it.
- The implementer must read a query ahead through `queryClient.query(options)` on a TanStack Query version that has it, and must not call the `prefetchQuery`, `fetchQuery`, or `ensureQueryData` calls that version deprecates.
- The implementer must get the browser's `QueryClient` from one maker module.
- The implementer must create every zustand store with `createStore` from `zustand/vanilla` inside a provider.
- The implementer must give a zustand store that persists to browser storage `skipHydration: true` and rehydrate it after mount.
- The implementer must not read or write a zustand store from a Server Component.

## Client Components and the bundle

A Client Component's file, or an importer's file, starts with `"use client"`, and its code ships to the browser. First-load JavaScript is the compressed size of the scripts a page's first HTML names.

- The implementer must put `"use client"` on the smallest component that needs browser state, an effect, or an event handler.
- The implementer must pass a Server Component into a Client Component as `children` or another prop.
- The implementer must pass a Client Component only the fields it draws, apart from the data handed to the query cache through `HydrationBoundary` or `initialData`, because every prop is written into the page's HTML.
- The implementer must keep each route's first-load JavaScript at or under 300 kilobytes compressed.
- The implementer must keep a new signed-in route's own scripts, above the shell every signed-in route loads, at or under 50 kilobytes compressed, and must not grow a route already past its budget.
- The implementer must load a library that a page does not draw in its first paint, such as a dialog's contents or an animation library, through `next/dynamic` or React `lazy()` declared at module scope.
- The implementer must not statically import, from any module the browser loads, a module that another file loads through `next/dynamic`, `lazy()`, or `import()`, because one static import puts its code back in the first load.
- The implementer must give every lazily loaded component a fallback of the size it will take.
- The implementer must mount in a shared layout only the providers every page under it uses, and load the rest lazily.
- The implementer must not add a static import of a generated validator to a Client Component.
- The implementer must load a validator the browser runs with `import()` of a literal path at the point where the read answers, because a path built from a variable makes the build bundle every file the path could match.
- The implementer must import a library's modules directly, or through a package on the `optimizePackageImports` list, so a barrel file that re-exports the whole library never reaches the bundle.
- The implementer must import `server-only` in every module that reads a cookie, a header, a secret, or the service's origin, so the build fails when client code imports it.

## Responsiveness and layout shift

Interaction to next paint, INP, is the time from a click, tap, or key press to the next frame. Largest contentful paint, LCP, is the time until the largest visible element is drawn. Cumulative layout shift, CLS, measures how far content moves while the page settles.

- The implementer must keep every page's LCP at or under 2.5 seconds, its INP at or under 200 milliseconds, and its CLS at or under 0.1.
- The implementer must wrap a state update that re-renders a whole screen or grid, such as changing a view, in `startTransition`.
- The implementer must pass a typed value that re-renders a whole screen or grid, such as a search query, through `useDeferredValue`.
- The implementer should give each row of a list that can grow past 50 rows `content-visibility: auto` and a `contain-intrinsic-size`.
- The implementer must send each page's INP from the browser with the element the user touched and its longest phase, input delay, processing, or presentation.
- The implementer must split a task the browser runs for more than 50 milliseconds after an interaction, by yielding with `scheduler.yield()` and a `setTimeout` fallback.

## The proxy

The proxy is the app's `proxy.ts`, the function Next.js 16 runs on the Node.js runtime before it renders each page request.

- The implementer must keep the proxy to work the request alone decides: headers, the script nonce, rewrites, and redirects read from the address or a cookie's presence.
- The implementer must not make a network call, a database query, or a service read in the proxy.
- The implementer must keep the proxy's matcher excluding `_next/`, `api/`, files with an extension, and prefetch requests.

## Fonts and images

- The implementer must call each `next/font` loader once, in one font definitions module, and import its result everywhere.
- The implementer must load every font through `next/font`.
- The implementer must keep a page's first-paint fonts at or under 100 kilobytes compressed, and must not preload a face for a script the page does not show.
- The implementer must draw every raster image through `next/image` with `width` and `height`, or with `fill` and `sizes`.
- The implementer must mark the image that is a page's largest element with `preload` or `fetchPriority="high"`.

## The rendering mode a nonce sets

A script policy that gives each page request its own nonce cannot hold on a page built ahead of its request, so Cache Components and Partial Prerendering stay off while it does.

- The implementer must keep every page rendered per request while the script policy uses a per-request nonce.
- The implementer must keep `cacheComponents` and `partialPrefetching` off in `next.config.ts` while the policy uses a nonce, with each set to `false` once a Next.js release turns it on by default.
- The implementer must not add `export const dynamic`, `revalidate`, or `fetchCache` to a segment while the policy uses a nonce.
- The implementer must state the reason and the measurement that supports it in a comment beside every key under `experimental` in `next.config.ts`.
- The implementer must remove a `next.config.ts` key whose value equals its documented default.

## Measuring a page before merge

A cold load is a page load with an empty browser cache. The batch's walk loads each changed page on a production build and reports its first-load JavaScript, LCP, INP, CLS, TTFB, and tab switch times, as the median of 5 runs, and the batch's pull request quotes them.

- The reviewer must refuse a change that raises a page's figure past its budget, that raises the first-load JavaScript or the duplicate service reads of a page already past its budget at all, or that raises any other figure of such a page by more than 10 percent on the median of 5 runs.

## Why it exists

A slow page is the first thing a user notices. One measured home page waited 2.9 seconds for its first byte, shipped about 745 kilobytes of compressed JavaScript, and sent its main read three times.

## What is exempt

- Development-only routes that a production build leaves out.
- Route handlers, the `route.ts` files, from the navigation, loading state, and bundle lines, because they draw no page.
- Test code, which the testing rule, `testing.md`, governs.
- A read in an effect that can run only in the browser, with a comment on the call's line or the line above that says "browser-only read because" or "browser-only read:" and why, in at least three words.
- Code that already broke a line before the line arrived, until its fix lands. A change to that code is held to the last line of the measuring section.
