# Web app essentials

This is the web app, `{web_app}`: Next.js with React and TanStack Query. Every change in this folder obeys the lines below. The full rules in `.colony/rules/` are the reviewer's checklist, and each line names the rule and the section that hold it in full.

## Checks

- Per change: `{fast_check}`.
- Per batch: `{checks}`, which `colony batch` runs with a fresh review and a browser walk of each changed screen.
- When you are unsure how a library behaves, read `.colony/rules/docs.md` before you guess.

## The lines every change here obeys

1. You must read a page's first data in its Server Component on a full load and pass it down, must never read the service in a `useEffect`, and must mark `"use client"` only on leaf components that need state or events. (`performance.md`, Server reads)
2. You must hand server data to the query cache with `initialDataUpdatedAt` and a `staleTime` above 0, and must invalidate every key a write changes. (`performance.md`, Requests sent once, and `full-stack.md`, Freshness after a write)
3. You must keep each route's first-load JavaScript at or under 300 KB compressed, and must load heavy libraries lazily. (`performance.md`, Client Components and the bundle)
4. You must let a `layout.tsx` await only the session read and the request APIs, and must give every segment whose page awaits a read a `loading.tsx`. (`performance.md`, Loading states and streaming)
5. You must draw a shared frame once in its `layout.tsx` with only the providers every page needs, and must link every app page with `next/link`. (`performance.md`, Navigation)
6. You must build every surface from a part of the app's shared component library, and must add a missing part to the library before a screen uses it. (`design-principles.md`, In a Next.js web app)
7. You must keep each feature's reads and writes in its own folder's hooks, and must import no other feature's private modules. (`design-principles.md`, In a Next.js web app)
8. You must write every date and time through the app's one formatter in the user's zone, and must never read the device's zone. (`coding.md`, Lines the web app follows)
9. You must never write outside text into the page as HTML, and must draw a model's text through its one renderer. (`coding.md`, Lines the web app follows)
10. You must read and write the service only through the types generated from its contract, regenerated in the change that changes the contract. (`full-stack.md`, The contract)
11. You must send each write through its feature's write hook with the revision it read and one operation identifier, reused only when the same command is resent. (`full-stack.md`, The forwarder and the write path)
12. You must return focus to a control that stays when the pressed one leaves, give every control a name, and announce outcomes in a live region mounted empty from first paint. (`accessibility.md`, Keyboard and focus, and Announcements and refusals)
13. You must await or catch every promise a handler or timer starts, so a rejection ends in a shown refusal. (`coding.md`, Lines the web app follows)
14. You must give a bug fix or new logic a test that fails without the change, and must check touch or layout work in a browser at phone width, 390 by 844. (`testing.md`, In both apps)
