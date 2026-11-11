# Project Cockpit

**Long agent sessions forget. This makes forgetting free.**

Project Cockpit is a skill for Claude Code (and any agent that reads `SKILL.md`) that keeps a small, capped set of project docs current, so a brand-new session picks up a long-running project from one 55-line file instead of a bloated transcript. Compaction stops hurting, `/clear` becomes safe, and the next session starts warm.

```
docs/
├── STATUS.md      now     the cockpit: state, blockers, TODOs, Resume With   ≤ 55 lines
├── ROADMAP.md     next    current milestone + the next two                   ≤ 250 lines
├── REFERENCE.md   always  architecture, decisions, ruled-out, gotchas        ≤ 200 lines
└── archive/       then    one frozen closeout per finished milestone         append-only
```

## Why it works

- **A brief, not a transcript.** A SessionStart hook puts `STATUS.md` back in context at startup, on `--resume`, after `/clear`, and right after compaction. That is exactly when the agent has lost its memory.
- **Updates don't depend on memory.** The skill says to write state the moment it changes. Two hooks catch what slips through:
  - **Stop:** when a turn ends with code newer than `STATUS.md`, the agent gets one short note to update it, or to say nothing changed. It nudges once per change, at most every 20 minutes, and never loops.
  - **PreCompact:** before auto-compaction, it tells the summary to keep every decision, fix, and blocker not yet in `STATUS.md`, and to make updating it the first action afterward.
- **Caps force curation.** Every doc has a hard line limit. When one fills up, finished work moves to the archive and stable facts move to the reference. Nobody gets to just write smaller.
- **The repo outranks the docs.** The brief counts the commits since `STATUS.md` was last committed and flags uncommitted work. The agent checks `git` before it repeats a stale claim.
- **History cannot be rewritten.** Closeouts are append-only, and decisions are superseded, never edited. `check --history` replays git to prove the archive only ever grew.
- **No evidence, no claim.** Anything marked done or fixed cites a commit, a test run, or `file:line`. Disproven hypotheses go in a Ruled Out list, so nobody burns an afternoon re-investigating them.
- **Cheap to carry.** About 90 tokens always loaded and about 1.7k when the skill fires, per `claude plugin details`. Each hook ran in about 90 to 120 ms in testing. The Stop hook adds a turn only when docs are actually behind.

## Install

**Claude Code plugin** (the skill and all three hooks in one step):

```
/plugin marketplace add Tranman324/project-cockpit
/plugin install project-cockpit@project-cockpit
```

**Or copy the folder:**

```bash
git clone https://github.com/Tranman324/project-cockpit.git
cp -r project-cockpit/project-cockpit ~/.claude/skills/
```

Codex, Cursor, Hermes, and other agents can load the `project-cockpit/` folder directly. See [setup](project-cockpit/references/setup.md) for the `CLAUDE.md` / `AGENTS.md` pointer, a manual hook, and CI.

## Use

In a project, ask your agent to *set up the project cockpit*. It scaffolds the docs and seeds them from the README, `git log`, and open issues. After that the skill runs itself: it reads the brief at start, records state the moment it changes, and rewrites `STATUS.md` when you wrap up or before you `/compact` or `/clear`.

The script works on its own too. It is Python 3.9+, standard library only:

```bash
python3 project-cockpit/scripts/cockpit.py init --name "Acme API" --tier full   # never overwrites
python3 project-cockpit/scripts/cockpit.py check                                  # exit 1 on any FAIL
python3 project-cockpit/scripts/cockpit.py check --json --history origin/main     # CI mode
python3 project-cockpit/scripts/cockpit.py closeout auth-rewrite                  # archive/YYYY-MM-auth-rewrite.md
python3 project-cockpit/scripts/cockpit.py brief                                  # what the SessionStart hook prints
```

The Stop hook (`guard`) works only in git repos and ignores edits inside `docs/`. Tune it with `COCKPIT_GUARD_MINUTES` (default 20), or turn it off with `COCKPIT_GUARD=off`.

`check` enforces the line caps, the required STATUS sections, a real and recent `Updated:` date, at most seven TODOs, a non-empty Resume With, one Current milestone, closeout naming and evidence, and archive immutability. It also catches invisible or bidirectional Unicode, which can hide instructions from a human reviewer. Every check has a test that proves it fires.

## What a good STATUS.md looks like

```markdown
# Acme API Status
*Updated: 2026-11-10*

## Current State
Auth v2 is live behind the `auth_v2` flag for 10% of traffic (PR #212, dashboard p95 140 ms).
Billing webhooks are stubbed; nothing charges yet.

## Blockers
- Stripe live keys: waiting on finance (Dana).

## Active TODOs
1. Raise `auth_v2` to 50% after 48 h without 5xx regressions.
2. Replace the webhook stub in `billing/webhooks.py` with signature verification.
3. Delete the legacy session table once v2 reaches 100%.

## Resume With
Run `make test-billing` (2 failing, both in `test_webhooks.py`). The fixtures expect
the old event schema; update `fixtures/stripe/*.json` first, not the handler.
```

## Development

```bash
python3 -m unittest discover -s tests -v
claude plugin validate . --strict && claude plugin validate ./project-cockpit --strict
```

## Credits

The STATUS / ROADMAP / REFERENCE / archive pattern grew out of the project system behind [Athena](https://github.com/Tranman324), Jeremy Tran's AI operations partner. The append-only, supersede-don't-edit, evidence-required, and ruled-out rules borrow from ideas in Erik Ryden's ledger design.

## License

MIT. See [LICENSE](LICENSE).
