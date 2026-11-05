---
type: type-definition
created: 2026-11-05
description: How to write a threat model. Read before recording what one system must protect, who could attack it, how, and what {product} does about each threat.
assisted-by: claude-code:claude-fable-5
enforced-by: human review in the pull request
---

# Threat model

A threat model is the standing record of what can go wrong with one system's security and privacy, and what {product} does about each thing. It names the data the system protects, draws where that data crosses a trust boundary, lists the threats at each crossing, gives each threat a response, and names the risks {product} accepts. You write it when a system's architecture exists and before its code ships, and you revisit it whenever the system changes shape. The routing test: if the page answers "what could an attacker or a failure do to this system, and what do we do about it," it is a threat model.

## Send it elsewhere when

- The page describes the parts of a system and how they connect. That is an [[architecture]] page, and the threat model draws on it.
- The page settles one security choice, such as a second sign-in factor or a key service. That is a [[decision-record]], and the threat model links to it from the threat it answers.
- The page designs how one control is built, such as the rule for fetching an outside address. That is a [[tech-design]].
- The page states what the product promises about data. That is a [[prd]], such as the privacy requirements.
- The page is an ordered procedure an operator follows when a threat happens. That is a [[runbook]].
- The page reports what an investigation found about attacks or law. That is a [[research-report]].

## Frontmatter

```yaml
type: threat-model
system: <name of the one system this page covers>
created: YYYY-MM-DD
description: <what the page is and when to read it, the key use first, at most 1024 characters>
assisted-by: <agent>:<model>    # present only when an agent helped write the page
last-verified: YYYY-MM-DD    # set only by a verification pass, never by hand
last-revisited: YYYY-MM-DD    # the date of the last revisit under the triggers below
```

## Skeleton

- **What this model covers.** The system in plain words, the [[architecture]] page it models, and the date of the architecture it read.
- **The data we protect.** A table with one row per kind of data: where it may be stored, where it may travel, where it may be processed, and the property that matters most, which is confidentiality, integrity, or availability.
- **The system model.** One C4 view at the container level where each trust boundary is a boundary block and each arrow names the data that crosses it, then a paragraph naming every arrow and every boundary, then a table of trust levels, one per kind of actor, each with an identifier.
- **Assumptions.** A numbered list, each assumption written so a reviewer can check it later.
- **Threats.** A table with one row per threat: an identifier, the boundary crossing or part it attaches to, its STRIDE or LINDDUN category, and what goes wrong in one concrete sentence.
- **Responses.** A table with one row per threat identifier: the response, which is mitigate, eliminate, transfer, or accept, the control that delivers it with a link to the page that designs it, and the check that shows the control works.
- **Accepted risks.** A table with one row per accepted threat: who accepted it, the reason, and the date it is next rechecked.
- **Did we do a good enough job.** The review questions answered in full sentences: does the model match what is built, is every boundary crossing covered, does every threat have a response, and does every mitigation have a check.
- **When this is revisited.** The triggers that reopen the model, and the date of the last revisit.

## Rules

- One page must cover exactly one system, named in the `system` frontmatter field, and that system must have an [[architecture]] page.
- Every arrow in the model must cross or stay inside a named trust boundary, and every arrow that crosses one must carry at least one threat row.
- Every threat must carry exactly one response, and every response other than accept must link the page that designs its control.
- Every accepted risk must name who accepted it, the reason, and a recheck date, and a risk accepted for longer than a year must be accepted again.
- Every diagram must follow the [[diagrams]] rule and its C4 view row, and the prose must state everything the diagram shows.
- The page must be revisited when a new boundary crossing ships, when the architecture page changes a container, and after any security incident, and the revisit must update `last-revisited`.
- A threat's category must come from STRIDE for security threats and from LINDDUN for privacy threats, and a threat may carry one of each.
- The page must name no secret, no key, no address a person could attack, and no working exploit.

## Before you publish

- Does the page cover one system with an architecture page, named in the frontmatter?
- Does every boundary-crossing arrow in the model carry at least one threat row?
- Does every threat carry one response, and does every response other than accept link the page that designs its control?
- Does every accepted risk name who accepted it, the reason, and a recheck date?
- Does the page name its revisit triggers and the date it was last revisited?

## Background

This type follows the four questions of the Threat Modeling Manifesto: what are we working on, what can go wrong, what are we going to do about it, and did we do a good enough job. Adam Shostack's Four Question Framework asks the same first three and ends with "did we do a good job", and we keep the Manifesto's "good enough". We adopt the five contents the OWASP threat modeling pages name for the document: a description of the system, its assumptions, the threats, a response for each threat, and a way of validating the model. We adopt Microsoft's STRIDE categories for security threats and LINDDUN's categories for privacy threats, because a product that holds personal data needs its privacy threats named, and STRIDE has no category for collecting too much. We adopt the four responses Shostack names, mitigate, eliminate, transfer, and accept, and the SSDF's rule that an accepted risk carries its reason and is re-evaluated. We adopt NIST SP 800-154's step of naming where each kind of data may be stored, sent, and processed.

We drop the asset register, because the OWASP process page itself treats assets as a distraction and naming the data carries the same value. We drop threat trees and attack graphs, because the threat table carries what they show in a form a reviewer reads line by line. We drop numeric risk scores such as DREAD, because the OWASP cheat sheet notes that likelihood and impact resist calculation, and a false number misleads. We drop the separate dependency and entry point tables, because every labeled arrow crossing a boundary already names them. We draw the model as a C4 view at the container level with each trust boundary as a boundary block, because the vault's diagram types hold no data flow diagram and the container view already names the parts a threat attaches to.
