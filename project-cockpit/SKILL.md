---
name: project-cockpit
description: "Use when starting, resuming, or wrapping up work on a long-running project. Keeps a capped STATUS/ROADMAP/REFERENCE doc set so a fresh session resumes cold from one short file."
version: 1.0.0
author: Jeremy Tran
license: MIT
---

# Project Cockpit

Long sessions decay: compaction drops decisions, and the next session relearns the project from a transcript. The fix is a small doc set the agent reads first and keeps current. With the docs current, the transcript is disposable: `/clear` costs nothing.

## The doc set

All in `docs/` (override with `--root` or `$COCKPIT_ROOT`). One fact, one home.

- `STATUS.md`: **now**. The cockpit, read every session. Max 55 lines. Sections: Current State, Blockers, Active TODOs (max 7), Resume With.
- `ROADMAP.md`: **next**. The Current milestone plus Next and Later. Max 250 lines.
- `REFERENCE.md`: **always**. Architecture, terms, workflows, Decisions, Ruled Out, Gotchas. Max 200 lines; beyond that, split into `reference/<topic>.md`.
- `archive/YYYY-MM-<slug>.md`: **then**. One closeout per finished milestone. Append-only.

Tiers: `lite` (STATUS only) for quiet projects, `ops` (STATUS + REFERENCE) for running systems, `full` for active builds. Start small; promote when a doc earns its place.

`scripts/cockpit.py` (in this skill's folder, Python 3.9+, no dependencies) scaffolds, checks, and briefs. Caps are measured by `check`, never estimated.

## Session start

1. **Load STATUS.md.** If a `Project cockpit (...)` block is already in context, the SessionStart hook loaded it; skip the read.
2. **Trust test.** Docs are a cache; the repo is truth. Before repeating any status claim, clear every cockpit note: commits since STATUS was committed, uncommitted paths, or an old Updated date each mean "check `git log` and `git status` first."
3. Open ROADMAP.md only for milestone work, REFERENCE.md only for a lookup, archive/ only for history.

## While working: write at the moment of change

Sessions end abruptly, so record state the moment it changes, not "at the end."

- A fix goes green, a blocker clears, a TODO finishes: update STATUS.md in that same turn.
- A lasting choice: one dated line in REFERENCE.md Decisions, with the reason. To change a decision, append a new line naming the date it supersedes; the old line stays.
- A hypothesis proven wrong: one line in Ruled Out, with the proof. A ruled-out item is closed; reopen it only with new evidence.
- **No evidence, no claim.** Done, fixed, and verified each cite a commit, a test run, or `file:line`.

## Wrap up

Triggers: the user says wrap up, hand off, or stop; before `/compact` or `/clear`; the context feels heavy.

1. Rewrite STATUS.md: Updated date, Current State, Blockers, TODOs, Resume With. Prune as you go: finished TODOs and cleared blockers leave.
2. Resume With passes the cold-start test: an agent holding only this file takes the right first action. It names the file, command, or branch, plus the trap that would bite.
3. Run `python3 scripts/cockpit.py check`. Done when it prints `OK`.
4. Commit the docs with the code they describe.

## Milestone done

1. `python3 scripts/cockpit.py closeout <slug>`, then fill Shipped, Evidence, Decisions, Changed From Plan, Follow-ups.
2. Delete the milestone from ROADMAP.md. Promote Next to Current and add a new Later.
3. Point STATUS.md at the new Current milestone.

A committed closeout is frozen. Corrections go in a new closeout or a REFERENCE.md decision; `check` fails on edits.

## Bootstrap

1. `python3 scripts/cockpit.py init --name "<Project>" --tier <lite|ops|full>`. It never overwrites.
2. Seed STATUS.md from real sources: README, `git log -20`, open issues, existing docs. Real open work, not a blank start; write `Unknown` where the sources are silent.
3. Wire it into the agent per `references/setup.md`: a two-line pointer in CLAUDE.md or AGENTS.md, and the SessionStart hook if this skill was copied rather than installed as a plugin.
4. `check` prints `OK`; commit.

## Rules

- STATUS is for the next session, not a diary. History goes to archive/.
- Absolute dates (`2026-11-10`), never "yesterday."
- Name where a secret lives, never its value.
- On a cap failure, graduate content (finished work to archive/, stable facts to REFERENCE) rather than compressing words.

`check` reference: `--json` for machines, `--strict` to fail on warnings, `--history [REF]` to prove from git that archive/ only ever grew. Exit 1 on any FAIL.
