# Folders and worktrees

Each lead holds some folders of the repo, and its helpers work only there, so two teams never edit the same files at once. This page says where Colony keeps who holds what, how a lead lends or borrows folders for a card, what happens when a lead goes quiet, and where worktrees go. [configuration.md](configuration.md#leads) lists the settings, and [commands.md](commands.md#folders-and-worktrees) the commands.

## One registry for every copy of the repo

A lead claims its folders with `colony claim <stream> <folder> …`, and folders it holds no longer can't be claimed by another live lead. Colony keeps the claims in two places, and every copy of the repo reads them the same way:

- **On this computer**, in one file of the clone, `.git/colony/leads.json`. Git keeps the `.git` folder for the main checkout and every worktree of it, so a claim made in the main checkout is what a helper's worktree reads, at once. Git never tracks that folder, so a claim needs no commit and no pull request.
- **On the code host**, in each lead's status comment, which carries its folders, whether it holds the rest of the repo, and its loans and borrows. Every computer reads those comments, so a helper on another computer sees its lead's folders.

`colony take` reads the lead's folders from its live status first, and from this computer's registry when the status can't be read. Before this version, the registry was the tracked file `.colony/leads.toml`; Colony reads it once, when the new file isn't there yet, and `colony leads` says when the old file can go.

## The rest of the repo

A lead that claims no folders holds the rest of the repo: every path no other live lead holds. One live lead holds it at a time. A second claim with no folders is refused while the first lead lives and acts, and the second lead names its folders instead. The first session in a repo with no lead alive becomes `<person>-main-lead` over the rest.

A lead with no folders that doesn't hold the rest, such as one left over from before this rule, takes no card: it claims folders with `colony claim --add`, or borrows them for a card.

## Lending and borrowing for a card

A card sometimes needs a file another lead holds. Instead of moving the folder for good, a lead lends it for that card:

```sh
colony lend ben-web-lead apps/api/schema.py --card 41
```

Ben's helpers may now take card 41, though it touches `apps/api/schema.py`, and no other card. Ben's lead hears it in a line, and every computer sees the loan in the status comment. `colony lend ben-web-lead --end` takes it back.

The lead that needs the file asks for it instead:

```sh
colony borrow apps/api/schema.py --card 41
```

That posts a line to the lead that holds the path, naming the exact `colony lend` command that says yes. The ask stays open until that lead lends the path, or goes silent.

## Silent and gone leads

A lead is **silent** when its own session has done nothing for `[leads] silent_minutes`, 120 by default, though its wait still keeps its status fresh. This is the lead whose person stepped away, or whose session waits on something nobody sees. A silent lead's folders are free for the others, each time with a line that tells it:

- `colony borrow` borrows them at once, and an open ask is borrowed once the holder goes silent. The asking lead's wait settles its asks at each status edit, and `colony borrow --check` does now.
- `colony claim` may take them, and a new claim with no folders takes the rest of the repo from a silent lead that held it.

`colony who` and `colony leads` mark a silent lead with how long it has been silent.

A lead is **gone** when its status is over 15 minutes old. Its folders are free at once. A lead gone for `[leads] drop_after_hours`, 72 by default, drops from this computer's registry with its loans, and `colony who` stops listing it. `colony leads` and each claim drop them.

## Worktrees

Every worktree Colony makes or suggests sits in `[project] worktrees`, which is `.worktrees` inside the repo by default:

- A relative folder starts from the repo's main checkout, so a command run in a worktree never makes one inside it.
- A folder inside the repo is kept out of `git status` by a line in the clone's own `.git/info/exclude`, which every worktree reads and nothing commits.
- `colony take`, the batch, the merge, `colony image`, `colony share` and `colony check run --ref` make theirs there, and `colony worktree add <name> <start>` makes one there for anyone else, such as the lead's early-merge worktree.
- `colony worktree check` names any worktree outside the folder, with the `git worktree move` command that moves it in, and the lead hears once a day when there is one, or when the folder itself sits outside the repo.
