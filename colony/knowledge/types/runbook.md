---
type: type-definition
created: 2026-11-05
description: How to write a runbook. Read before writing the ordered procedure an operator follows to perform or repair one known operation, such as a deploy and rollback, a restore drill, a move to another database host, or a breach response.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Runbook

A runbook is the ordered procedure an operator follows to perform or repair one known operation. It names the cue that starts it, what must be in hand before the first step, the numbered steps with what each one should show, how the operator knows it worked, what to do when a step fails, and who else is called. You write one when an operation matters enough that doing it from memory is a risk, such as a restore, a release rollback, or the first hour after a breach. The routing test: if an operator could follow the page step by step under stress and finish the operation, it is a runbook.

## Send it elsewhere when

- The page explains how the mechanism behind the operation is built and why. That is a [[tech-design]], and the runbook links to it.
- The page settles one choice, such as the backup window or the release cadence. That is a [[decision-record]].
- The page works out which failure is happening from its symptoms. That is a diagnosis, which the vault does not hold yet, and the runbook starts only once the failure is known.
- The page records what happened in one incident and what changes because of it. That is a postmortem, which the vault does not hold a type for yet.
- The page lists what could go wrong with a system and what {product} does about each threat. That is a [[threat-model]].

## Frontmatter

```yaml
type: runbook
operation: <the one operation this page performs or repairs>
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
owner: <the person who keeps this runbook true>
last-tested: YYYY-MM-DD    # the date an operator last ran the procedure end to end, or "never"
```

## Skeleton

- **When this runs.** The cue that starts the procedure, stated as something an operator can observe.
- **Before you start.** The access, the tools, the permissions, and anyone else who must be present, as a list.
- **The steps.** A numbered list with one action per step, each followed by the value or state the operator should see.
- **Verification.** How the operator confirms the operation worked, ending in one written completion line.
- **If a step fails.** The rollback for each step that can fail, and where to resume after an interruption.
- **Escalation and handover.** Who is called and at which point, and what an outgoing operator hands over.
- **Last tested.** The date of the last full run, who ran it, what failed during it, and what changed on the page because of it, or the word "never" with the date the first run is scheduled for.

## Rules

- One page must cover exactly one operation, named in the title and in the `operation` field.
- Every step must hold one action, and every step must state the value or state the operator should observe, never only the word "checked".
- The steps must be ordered so that no step depends on a later one.
- Every step that changes data or a running service must name its rollback under "If a step fails".
- The page must end its verification with one completion line the operator writes or says.
- The owner must run the procedure end to end at least once before the operation is needed and after every change to the steps, and record the run under "Last tested".
- The page must link the tech design and the decision records behind the operation, and must not restate their reasoning.
- The page must name no secret, no key, and no password, and must name the place an operator retrieves each one.
- A flowchart is allowed only where the steps branch, and it follows the [[diagrams]] rule.

## Before you publish

- Does the page cover one operation, named in the title and the frontmatter?
- Does every step hold one action and the value the operator should observe?
- Does every step that changes data or a running service have a rollback?
- Does the verification end in one completion line?
- Does the page carry a last tested date from a real end-to-end run, or the word "never" with the run scheduled?

## Background

This type follows the runbook as Amazon's Well-Architected operational excellence pillar defines it: a playbook investigates, and a runbook mitigates. PagerDuty draws the line by scope and lets one playbook hold several runbooks, and Google's site reliability books keep diagnosis and mitigation on one playbook page. We take Amazon's split, because it keeps diagnosis off the page an operator follows under stress. We adopt the parts Amazon's runbook practice names: an outcome, the tools, the special permissions, numbered steps, error handling, an escalation contact, and an author. From checklist design in aviation and medicine, we adopt a cue that starts the procedure and a rule for where to resume after an interruption from the FAA's guidance on checklists, fewer than ten items between pause points from A Checklist for Checklists, a response that states the value observed and a written completion line from NASA's report on normal checklists, and verification without reliance on memory from the WHO Surgical Safety Checklist. PagerDuty asks that a completed runbook be field tested, and Amazon asks that someone else on the team run it before it is trusted and that the page carry a last updated date. We adopt the field test as a last tested date apart from the last edit, because an edit is not a run.

We drop the diagnosis part of a playbook, because a page that both diagnoses and repairs grows longer than a stressed operator can follow. We drop a runbook identifier, because the page's name already identifies it. We drop one page per alert, because each page must be exercised to stay correct, one page per alert multiplies the pages to exercise, and an unexercised procedure is the failure these sources warn about most. We drop a severity block and a service overview, because severity belongs to the incident and the overview lives on the architecture and living spec pages.
