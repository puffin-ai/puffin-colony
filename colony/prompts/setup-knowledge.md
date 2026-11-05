## The knowledge vault

The knowledge vault holds what the team decided, built and found out, as typed pages with Obsidian-style `[[links]]`. Its templates are in `{package}/knowledge/`: `templates/` holds the vault's folders and their readmes, `types/` holds the page type definitions, and `rules/` holds the knowledge rules. Every file there uses three placeholders, `{product}`, `{knowledge}` and `{apps}`, which you fill in step 4.

1. **Look for docs, without asking.** Find any folder that already holds the repo's docs: `knowledge/`, `docs/`, `doc/`, `wiki/`, `vault/`, a folder holding `.obsidian/`, or a folder of decision records such as `adr/` or `docs/decisions/`. Keep the product's name, from the README's title or the package name, and the app folders from step 1.
2. **Ask, in the step 2 message.** Add one numbered question: "Where does the knowledge vault live?"
   - When no docs folder exists, the default is `knowledge/`.
   - When one exists, the default is to adopt it in place: keep every file in it, add the vault's folders and readmes beside them, and change no page already there. The other answers are a new `knowledge/` beside it, or another folder the person names.
3. **Copy the files.** Call the vault folder `<vault>`, with no trailing slash. Copy without overwriting: when a file already exists at a target path, keep it and skip the copy.
   - Each file under `{package}/knowledge/templates/` to the same path under `<vault>/`.
   - Each file under `{package}/knowledge/types/` to `<vault>/.types/`.
   - Each file under `{package}/knowledge/rules/` to `{dir}/rules/`. When the preset copied a `writing.md` there in this run, the knowledge copy replaces it, because it holds every line of the preset's and the vault's own.
4. **Fill the placeholders** in every file you copied, and change nothing else:
   - `{product}` becomes the product's name.
   - `{knowledge}` becomes `<vault>`.
   - `{apps}` becomes the app folders. In a `paths:` list, write one glob line per app folder, such as `"**/apps/web/**"`. In prose, name them in a list. For an app at the top of the repo, use `.` in prose and `"**/*"` in a glob.
   - In each page copied from `templates/`, set the `created:` line of its frontmatter to today's date. The `YYYY-MM-DD` inside a type definition's yaml block stays.
5. **Write the first readme.** In `<vault>/README.md`, replace the line that reads `{product} is <one paragraph ...>` with one paragraph from what you read in step 1: what the product does, for whom, and which apps it runs as. State only what the repo shows, in plain words, under `{dir}/rules/writing.md`.
6. **Adopt an existing folder**, when the person chose it. Never move, rename, overwrite, or retype a page that is already there, and never delete one. Count the pages that carry no `type` in their frontmatter, and name that count in the pull request body as follow-up work the lead can offer. Move no decision record: the authority rule's place for one, the wiki folder of its area, applies to new records.
7. **Load the rules by path.** For each knowledge rule whose frontmatter lists `paths`, add a relative symbolic link `.claude/rules/<name>.md` pointing at `../../{dir}/rules/<name>.md`, so Claude Code loads the rule when an agent opens a matching file. Keep every file already in `.claude/rules/`.
8. **Keep the archive out of search.** Add the line `<vault>/archive/` to the repo's `.ignore` file, creating it when it is missing.
9. **Record the folder** in `{dir}/{name}.toml`: set `vault = "<vault>"` in its `[knowledge]` table.
10. **Write the decision log and check the vault.** Run `{name} check-docs --index`, which writes `<vault>/decisions.md` from the decision records, even when there are none yet, since the vault's readme links it. Then run `{name} check-docs`, which prints a count per check. A fresh vault passes clean. Add the log to the commit, and quote the last line of the check in the pull request body. A failure on an adopted folder does not stop setup: name its count per check in the body as follow-up work.

Add every file and link from this section to the pull request's file list. Default for the whole section: yes, with the vault at `knowledge/`, or the existing docs folder adopted in place.
