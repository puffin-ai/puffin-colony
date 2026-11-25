# Releases and branch health

Colony drafts the release pull request from the merged work, pauses new landings while the release is checked, and can release a chosen part of the work. After a release, it brings the release back into the other long-lived branches through pull requests. It watches the shared branch, tells the lead whose change broke it, and pauses landings while it fails. It hands the person the steps only a person can take, tested first and kept on the code host. And it checks status messages for internal shorthand before they reach the person.

The code is in `colony/release.py`, `colony/freeze.py`, `colony/branches.py`, `colony/health.py`, `colony/steps.py` and `colony/plain.py`. The settings are in [configuration.md](configuration.md#releases-and-branch-health), and the commands are in [commands.md](commands.md#releases-and-branch-health).

## Why

In one long run, a team of leads learned these lessons the hard way:

- A release description written by hand missed a migration and a removed test.
- A merge that landed while the release's checks ran forced another long run of them.
- A release had to take everything waiting, even work that wasn't ready to go out.
- The long-lived branches drifted apart, and the drift turned into conflicts at release time.
- The shared branch stayed red for hours, and nobody knew whose change broke it.
- Steps handed to the person were untested, lived in a chat, and didn't say who should take them.
- Status messages used internal shorthand, such as task codes and arrows, that the person had to ask about.

## The branches

Colony names no branch itself. It reads each one from the config, with a default:

| Branch | Setting | Default | What it is |
| --- | --- | --- | --- |
| The base | `[project] base` | none: it is required | Where pull requests go |
| The integration branch | `[project] integration` | the base | Where the team's work gathers. A release is cut from it and comes back into it |
| The release branch | `[project] release` | origin's default branch, when that differs from the integration branch | Where a release goes, such as `main` when work gathers on `dev` |
| Other long-lived branches | `[release] long_lived` | none | Branches each release goes into too, such as a staging branch |

A project with only one long-lived branch has nothing to release into, so `colony release` asks you to set `[project] release`.

Colony reads origin's default branch as this clone knows it. If you change the default branch on the code host, run `git remote set-head origin --auto` once to update the clone.

## The release pull request

`colony release` opens one pull request from the integration branch into the release branch. It never merges it: a person does.

Its description is drafted from the merged work, in these sections:

- **What changed.** Each pull request merged into the integration branch whose merge commit the release branch lacks, with its lead: the board's Lead field of the cards it closes, else its author. Then the commits that came another way, such as a direct push, each with its subject. A merge that only brought the release branch back in counts as no work of its own.
- **Migrations.** Each migration a piece of work adds, changes or removes. A file is a migration when its path looks like one, such as `migrations/0002.sql` or `schema.prisma`, or when it matches `[release] migrations`, such as `["db/changes/*"]`.
- **Tests removed or changed.** Each test file a piece of work removed or changed, and how many it added.
- **Checks on the release's head.** The code host's checks on the head commit, from any CI, with each failure named and linked. Then the results this computer's ledger keeps for the same commit or the same code. With no result yet, it names the commands that start one.
- **Left for a later release.** For a partial release, the work that stays behind.
- **Other leads' work.** Each piece of work another lead made.
- **After the merge.** What `colony release --after` does next.

A pull request's own description adds to the Migrations and Tests sections: the lines under a heading that names migrations, or removed or changed tests, such as a batch's `## Removed tests`. A line that only says "none", or looks like a secret, is left out. When the description would pass the code host's limit, these quoted lines go first, then the end is cut.

Only a pull request from a branch on the repo itself counts as the release, never one from a fork, whatever its branch is called. A check command that looks like it holds a secret stays out of the description.

`colony release --print` prints the description and opens nothing. `colony release --refresh` rewrites the open release pull request's description from the work and the checks as they are now, for example once CI has finished.

Before it opens the pull request, `colony release` posts one `@all` line that names each other lead whose work the release carries, so any of them can say at once that a piece must wait.

## The merge freeze

While a release's checks run, a merge into the integration branch would force them to run again. So `colony release` freezes the integration branch first, for every person's leads.

A freeze is a hold on one branch. The holds live on the code host, in origin's `refs/colony/holds`, so every computer reads the same ones, whoever's leads run there. A change reads the holds and pushes only while the ref is still where it was read, so two computers never lose each other's change.

There are three kinds of hold:

| Kind | Who puts it | How it ends |
| --- | --- | --- |
| `release` | `colony release` | `colony release --after`, `colony freeze off`, or by itself after `[release] freeze_hours` (12) |
| `freeze` | A lead or the person, with `colony freeze on` | `colony freeze off`, or by itself after `[release] freeze_hours`, or `--hours` |
| `red` | `colony health`, when the branch fails its checks | When the branch passes again, or `colony freeze off --red` for a false alarm |

While a branch is held, `colony merge` refuses to land on it, and `colony batch` refuses to start a batch into it. The refusal says who holds it, why and until when. A fix still gets through once it is named: `colony freeze allow <branch>`, or a card as its number. Each change to a hold posts one `@all` line, so every lead hears it. `colony freeze check <name>` answers with its exit code, for other tools such as a merge guard.

`colony merge` and `colony batch` land on `[project] base`. Before they land, they read the holds on the base, and on the integration branch when you set it apart, since the team's work reaches it from the base. An agent's `gh pr merge`, or a GitHub tool's merge, into a branch `[safety] merge_into` allows goes through the merge guard, which reads origin's holds the same way before it lets the merge run, and refuses it while a hold covers the branch, unless the hold names the pull request's branch or card. When origin's holds can't be read, the merge guard refuses too. So a freeze on either one pauses every lead's landings. A person who merges in GitHub's web page isn't stopped: only `colony safety protect`'s ruleset binds people too.

When origin's holds can't be read, `colony merge` and `colony batch` go ahead with a note, since each fetches origin next and stops there anyway when origin is down. When the release pull request fails to open, `colony release` lifts the freeze it just put and says so. `[release] freeze = false` turns the release's freeze off.

## Releasing a chosen part

`colony release --only 12 --only 14` releases those pull requests alone. `colony release --lead sam-lead` releases one lead's work, and `--lead me` your own.

Colony cuts a new branch, `<project>/release-<date>`, from the release branch. It copies each chosen pull request's change onto it, oldest first, pushes that branch, and opens the release pull request from it. The rest of the work stays on the integration branch for a later release, and the description lists it under "Left for a later release". Nothing is frozen, since the integration branch isn't what goes out.

When a chosen pull request builds on work that isn't chosen, its change doesn't apply alone. Colony stops, names the files, and changes neither branch. Add the pull request it builds on with `--only`, or release the whole integration branch.

## After the release

Once a person has merged the release, `colony release --after`:

1. Refuses while the release pull request is still open, and when no release was ever merged.
2. Lifts the release's freeze on the integration branch, and tells every lead.
3. Opens a pull request that brings the release branch back into the integration branch, and one into each `[release] long_lived` branch that lacks it.
4. Watches the run of `[project] deploy_workflow` on the release branch's head until it ends, and exits with its result.

## Long-lived branches in step

`colony branches` shows how far each long-lived branch is from the release branch. It also counts the commits that sit on one long-lived branch alone, in no other, since those are the ones that conflict at release time. `colony branches --sync` opens the pull requests that bring the release branch into each branch that lacks it.

Colony never merges into a long-lived branch, and never pushes to one. It builds each change in its merge worktree, one merge at a time on this computer, and pushes a branch of its own, `<project>/sync-<from>-into-<to>-<time>`. A person merges the pull request.

- An open sync pull request for the same two branches is reused, and brought up to the newest release branch when it lacks it.
- A conflict only in `[project] generated` files takes the release branch's side and runs `[project] regen`.
- Any other conflict leaves the branch holding the release branch alone, and the description names each file to settle.

## Keeping the shared branch green

`colony health run` looks at the newest commit of each shared branch, `[health] branches` (the integration branch by default), and finds out whether it passes its checks. `[health] source` says how:

| Source | Where the result comes from |
| --- | --- |
| `auto` (the default) | The code host's checks on the commit when it has any, else the full suite on this computer |
| `ci` | The code host's checks on the commit, from any CI |
| `local` | The full suite on this computer, `[project] checks` for every area, run in the background |

A result on a commit is read again, never run again: the ledger keeps it.

When a branch fails, Colony finds the likely cause. It reads the failing tests' files and finds the pull requests that changed one of those tests, or a file one of them covers. With no such match, the suspects are the pull requests merged since the branch last passed. It sends each suspect's lead one line, naming the failure and the pull request, and every lead one `@all` line. With `[health] pause` on, the default, it puts a `red` hold on the branch, so every lead's `colony merge` and `colony batch` pause until it passes again, except the fixes `colony freeze allow` names. Each red commit is told once, across every computer, since the hold on origin names it.

When the branch passes again, Colony lifts the hold and tells every lead.

`colony health watch` runs that every `[health] every_minutes` (60), and every 2 minutes while a run is going. Run it as one lead's background command. A look that fails, as when origin can't be reached, is tried again in 2 minutes. With nothing new on a branch, a look costs one fetch. To run it on a schedule elsewhere, such as a nightly CI job, run `colony health run`: it exits 0 when green, 1 when red, and 3 while the checks are still running. `colony health status` prints what each branch last showed on this computer, and what is held.

## Steps for the person

Some steps only a person can take: a cloud sign-in, applying infrastructure, a payment, or a setting only an owner can change. `colony step add "<what>" --run "<command>" --who <person>` hands one over.

1. **It tests the step first, where it can.** `--check "<command>"` runs a command that shows the step will work. Without one, Colony runs the dry-run form of the step's own command, when it knows one:

   | The step runs | Colony tests it with |
   | --- | --- |
   | `terraform apply`, `tofu apply` | `terraform plan`, `tofu plan` |
   | `pulumi up` | `pulumi preview` |
   | `kubectl apply`, `kubectl delete` | the same, with `--dry-run=server` |
   | `helm upgrade`, `helm install` | the same, with `--dry-run` |
   | `npm publish`, `pnpm publish`, `cargo publish` | the same, with `--dry-run` |
   | `ansible-playbook` | the same, with `--check` |
   | `rsync`, `git push`, `aws ec2` | the same, with `--dry-run` |
   | `make` | `make -n` |

   An approval flag, such as `-auto-approve` or `--yes`, is dropped from the test. `[steps] dry_runs` adds the project's own, such as `{ "./deploy.sh" = "./deploy.sh --check" }`. A command with pipes, `;`, `&&` or redirects gets none. The test runs from the top of the repo. Colony never runs the step's own command.

   A failing test stops the hand-over and shows the test's last line, unless `--anyway`, which hands it over with the failure noted. `--no-check` hands it over untested and says so. A step with no test says so plainly.
2. **It keeps the step on the code host**, as one comment on the issue `Colony: person steps` (`[steps] issue` names another). Every computer and every person reads the same list.
3. **It says who does the step:** a person, mentioned by their login so the code host tells them, or `anyone`, or `agent`.

It then prints one plain line to tell the person. `colony step list` prints the open steps, and `--who <person>` one person's. `colony step done <n>` marks one done by editing its comment. A step never holds a secret: text that looks like one is refused.

On a public repo anyone can open an issue or comment, so only the team's own count. A comment is a step only when one of `[people] logins` wrote it, or, with none set, someone GitHub says has access to the repo. The steps issue is the one a team login opened, or, with none set, the login `gh` runs as on this computer. `[steps] issue` names the issue outright.

## Plain status messages

The person reads a lead's status between other work. Internal shorthand makes them stop and ask. `colony plain check "<message>"` names each thing a person may not understand, with how to say it instead:

- an arrow, such as `->`;
- a chat abbreviation, such as `w/` or `fyi`;
- an internal code, such as `TD236`, or a helper's name, such as `builder-2`;
- a commit id;
- one of Colony's own words, such as worktree;
- a short form in capitals that the message never spells out;
- a sentence over 30 words.

Links and text in backticks, such as a command to run, are left alone. `[plain] allow` lets the project's own names through, and `[plain] jargon` adds the team's own shorthand. It exits 1 when it finds something.

`colony plain templates` prints a plain message for each common status: work done, a blocked step, a choice, a release, a failing branch and a person's step. `colony plain fill <name> key=value …` fills one in and checks it.
