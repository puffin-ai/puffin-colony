# Puffin Colony 0.2: the whole system

Colony 0.1 is the build-and-check engine. Version 0.2 adds the layers around it that Puffin's own system has: knowledge, planning, research, learning, the board, guards, three rule levels, and instant messages. Each layer is generalized from Puffin Calendar's repository at /Users/mac/Desktop/Coding/Puffin/puffin-calendar. Read the original there (`git show origin/dev:<path>` is the current copy). Copy what's general, and leave out the product: glass, Puffin's features, and its issue numbers.

## File ownership (helpers work in parallel; touch only your files)

| Track | Owns | Commands it adds |
| --- | --- | --- |
| K1 knowledge content | `colony/knowledge/` (folder templates, page types, knowledge rules), `colony/prompts/researcher.md`, `colony/prompts/spec.md`, `colony/prompts/setup-knowledge.md`, `tests/test_knowledge_content.py` | none |
| K2 knowledge checker | `colony/vault.py`, `tests/test_vault.py` | `colony check-docs [--staged] [--strict]` |
| C cycle | `colony/cycle.py`, `colony/board.py`, `colony/playbook.md`, `colony/prompts/setup-cycle.md`, `tests/test_cycle.py`, `tests/test_board.py` | `colony tier`, `colony needs`, `colony handover`, `colony stats`, `colony retro`, `colony board` |
| G guards and rules | `colony/guards.py`, `colony/hooks/`, `colony/presets/` (every preset, restructured into 3 levels), `colony/skills/` (new skills beside the 4 role skills), `colony/prompts/setup-guards.md`, `tests/test_guards.py`, `tests/test_presets.py` | `colony suppressions`, `colony hooks` |
| M messages | `colony/transport.py`, `colony/wait.py`, `tests/test_transport.py`, `tests/test_wait.py` | `colony say` (already in wait.py), transport `relay` |

- Nobody but the orchestrator edits `colony/cli.py`, `colony/prompts/setup.md`, README.md or `docs/` other than this file.
- Each new module exposes `add_commands(sub)`, which takes argparse subparsers, with one function per command taking `(config, args)`. The orchestrator wires it into cli.py.
- Each `setup-<track>.md` is a section the orchestrator splices into setup.md. Write it as numbered steps the setup session follows, with any question and its default.
- Everything per repo lives under `.colony/`, apart from the knowledge vault, which lives at the repo root in `knowledge/` (setup asks, default `knowledge/`). Read `.colony/colony.toml` with `colony.cli.load_config()`.

## K1: the full knowledge system (content)

Generalize Puffin's vault, `knowledge/` with its README and folder READMEs, and `guide/page-types/`, into `colony/knowledge/`:
- **Folder templates**, each with a README that maps the folder:
  - `wiki/` for living product docs, grouped by area
  - `specs/` for feature specs, each as requirements, design and tasks, plus a living as-built spec
  - `research/`
  - `decisions/` for decision records
  - `archive/`
  - `future-work.md`, the register with reasons and stages
  - `raw/` for sources
- **All 30 page types** from `guide/page-types/`, generalized:
  - architecture, archive-record, build-checklist, building-block, decision-record, design-spec, diagram-type
  - feature-design, feature-requirements, feature-spec, feature-tasks
  - glossary-entry, idea-spec, implementation-plan, launch-plan, living-spec, one-pager, owner-checklist
  - prd, readme-page, reconciliation-report, research-report, rule, runbook
  - singleton, source, tech-design, threat-model, type-definition
  - Keep each one's frontmatter, sections and must-lines.
- **The knowledge rules**, generalized: page-types, writing, naming-and-links (Obsidian-style `[[links]]`), authority (where each kind of truth lives), diagrams, and code-documentation. Also the life-cycle rule's "living spec updated in the same change" and "docs commit per batch".
- **`prompts/researcher.md`**:
  - The researcher takes one question per report, with cited sources, and writes `knowledge/research/<topic>-<yyyy-mm>.md` in the research-report type.
  - Research is done only when every finding is a rule line (do and don't), a check, or a decision with a default for the person. That's Puffin's research-to-rules policy.
- **`prompts/spec.md`**: the spec agent writes requirements, design and tasks for a FEATURE, in the feature-* types, and asks the person to approve the requirements before any cards.
- **`prompts/setup-knowledge.md`**:
  - Setup copies the folder templates and page types into the repo, under `knowledge/` and `knowledge/.types/`, or the folders the person picks.
  - It fills in a first `knowledge/README.md` from what it read about the product.
  - It never overwrites an existing docs folder: it offers to adopt it.

## K2: the knowledge checker

`colony/vault.py` generalizes `tools/check_vault.py` (read it in full) into `colony check-docs`. It keeps the checks every vault needs, and makes each a mode `off`, `warn` or `fail`, set in `[knowledge]` in colony.toml:
- every page declares a known type
- every page is linked from another page
- every `[[link]]` resolves
- every folder README maps its folder
- every code path a page names exists
- size caps per type, and the living-spec cap
- no copied paragraph across pages
- dated pages past their cap
- the rule budget
- a decision record that is replaced says so

It also has a `--staged` fast mode for a pre-commit hook, and prints a count per check at the end. Standard library only. Aim for 500–800 lines, and drop Puffin-only modes (threat model specifics, NAV citations, glass).

## C: the cycle

- **Tiers.** `colony tier [--base B]` prints TINY, SMALL or FEATURE from the diff, generalizing `tools/tier.py`, plus a risk list (auth, payments, migrations, secrets, deletion, public API) that becomes the reviewer's attention list.
  - The lead picks a tier per request: TINY and SMALL go straight to cards. A FEATURE goes to the spec agent, then the person approves, then cards. An unknown goes to the researcher first.
  - `colony batch` passes the risk list to the reviewer.
- **Needs you.**
  - One issue per person, `Needs <person>`. `colony needs "<question>" --default "<x>" [--person p]` posts a line there.
  - The lead keeps working on the default, and the person's reply line wins.
  - The lead tells the person in chat only when something is urgent or blocking.
- **Board.**
  - `colony board init` makes a GitHub Project from the repo's owner, with Status (To do, In progress, In review, Done), Builder, Tier, State (working, waiting, stopped, usage limit), Last update, Account and Branch.
  - `colony board set <card> field=value ...` updates a card.
  - The lead and the builders update it as they work: the builder sets State and Last update, and the lead sets the rest.
  - Generalize the session-protocol skill's board commands.
- **Handover.**
  - `colony handover` writes the handover comment (decisions, open questions, next) on the coordination issue when the session nears compaction. The playbook tells the lead when to do it.
  - It then prints the command that starts a fresh lead with the same name.
- **Stale cards.** `colony wait` for the lead adds a `stale:` line for each card In progress with no update in 2.5 hours, unless its State is usage limit.
- **Card stats.**
  - `colony stats` sums each card's predicted and actual minutes and tokens. The lead writes a `predicted: S, 20 min` line in each card body.
  - The batch PR body includes the table.
- **Learning loop.** `colony retro` runs after each batch, as an agent with a short prompt. It reads the round reports, then writes each lesson as a rule line plus a check, or a decision, into a PR. A note alone is never enough.
- **Playbook.** Rewrite `colony/playbook.md` to hold the full cycle:
  - the Lead, Builder, Spec and Researcher sections
  - the tiers, the Needs-you queue, the board and the handover
  - the conversation rule's essentials for how the lead talks to the person: answer first, a picture where it helps, short, one question with choices, and "Needs you" at the end

## G: guards and the three rule levels

- **The three levels, in every preset** (lean and puffin, and own when it adopts files):
  1. `core.md`: always loaded, under 1,500 words. It holds the honesty and conduct duties (report failure as failure, quote the output behind a success claim, never weaken a check, keep secrets out of output, no dependency or spend without a yes) and pointers to the other levels.
  2. Area essentials: an `AGENTS.md` per app folder with numbered must-lines, which Claude Code loads when an agent touches that folder.
  3. Full rules: `.colony/rules/*.md`, the reviewer's checklist, which agents read on demand.

  Setup writes the core into CLAUDE.md, or AGENTS.md, as an import.
- **Hooks.** `colony hooks install` merges into the repo's `.claude/settings.json`:
  - a PreToolUse Bash wait guard that refuses a foreground sleep, poll loop or watch (generalize `tools/wait_guard.py`)
  - a Notification permission_prompt hook that posts an `urgent:` line for the lead when a builder waits on a pop-up
  - a StopFailure hook that posts a line when a turn ends on an error

  It keeps the hooks already there.
- **Suppressions ledger.** `colony suppressions [--update]` counts lint and type suppressions (eslint-disable, @ts-expect-error, `# noqa`, `# type: ignore`, nolint and similar) per file against `.colony/suppressions.json`, and fails on growth. It's generalized from `tools/suppressions.py`, and setup adds it to the checks.
- **Skills.**
  - A curated starter set in `colony/skills/`, generalized from Puffin's `.agents/skills/`: diagnosing-bugs, tdd, code-review, resolving-merge-conflicts, retro, implement-spec, prototype, grill-me, writing-for-agents, git-guardrails.
  - A `skills.md` rule saying which skill to load for which task, with the role skills.
  - Setup offers the set, default yes.
- **Rules content.** Generalize Puffin's `implementation-conduct`, `conversation` and `skills` rules into the core and the rules folder.

## M: instant messages

- **`colony/transport.py`** sends each line twice: as the GitHub comment, which is the record, and through the transport.
  - With `transport = "relay"`, it also sends the line through Agent Relay's local core: `agent-relay-probe relay send --socket <socket> --to <session> --body <line>`. Find the probe and socket as `~/.claude/skills/messaging-agents-on-the-relay/SKILL.md` describes.
  - The relay delivers into the receiving session between turns, which makes it instant.
- **`colony wait`** stays as the GitHub fallback and the record reader. With relay, it de-duplicates, so a line delivered twice is acted on once.
- **Setup** detects a running relay core and offers `transport = "relay"`, default yes when one is found.
- **Tests** use a stub probe.

## For every track

- Standard-library Python 3.11+ only, with no dependency.
- Use `subprocess.run(list)`, never `shell=True`. Never print env values.
- Keep docstrings short, and don't overengineer.
- Run `uv run --with pytest pytest -q tests` before committing. The whole suite must stay green.
- Commit only your files, with a `feat(<track>): …` message ending in `Assisted-by: claude-code:claude-fable-5`.
- Don't push, and start no agent of your own.
