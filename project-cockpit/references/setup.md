# Setup

## Claude Code

**Plugin install** (recommended): the plugin registers the SessionStart hook for you.

```
/plugin marketplace add Tranman324/project-cockpit
/plugin install project-cockpit@project-cockpit
```

**Copy install:** put this folder at `~/.claude/skills/project-cockpit/` (all projects) or `<repo>/.claude/skills/project-cockpit/` (one project). Claude Code loads `SKILL.md` as a skill, and the bundled `.claude-plugin/plugin.json` makes it load `hooks/hooks.json` too. Start a new session, then confirm the hook with `claude plugin details project-cockpit@skills-dir` (look for `Hooks (1) SessionStart`). If it is missing, add the hook to `.claude/settings.json` by hand:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact",
        "hooks": [
          { "type": "command", "command": "python3 \"$HOME/.claude/skills/project-cockpit/scripts/cockpit.py\" brief" }
        ]
      }
    ]
  }
}
```

The hook fires on startup, `--resume`, `/clear`, and after compaction, so STATUS.md is back in context exactly when memory was lost. It prints nothing in a repo without `docs/STATUS.md`, and it always exits 0, so it is safe to install globally. On Windows, change `python3` to `python` if that is how Python is installed.

**Pointer:** add these two lines to the project's `CLAUDE.md` so the skill fires even without the hook:

```markdown
Project state lives in docs/STATUS.md (read first), docs/ROADMAP.md, and docs/REFERENCE.md.
Keep them current with the project-cockpit skill.
```

**Working rhythm:** when STATUS.md is current, prefer `/clear` over a long `/compact` chain. A fresh session plus a 55-line brief beats a summary of a summary.

## Codex, Cursor, Hermes, and other agents

Point the agent's skill loader at this folder, or paste the two pointer lines into `AGENTS.md`. Agents without a session hook run `python3 <skill-folder>/scripts/cockpit.py brief` as their first step.

## CI (optional)

Fail a pull request that breaks a cap or edits a closeout:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
- run: python3 path/to/project-cockpit/scripts/cockpit.py check --history origin/${{ github.base_ref }}
```

Drop the ref to replay the whole history. `--history` needs full history (`fetch-depth: 0`).
