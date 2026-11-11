"""Tests for cockpit.py. Every check id the tool can emit must be proven to fire."""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import shutil
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "project-cockpit"
SCRIPT = SKILL / "scripts" / "cockpit.py"
sys.path.insert(0, str(SCRIPT.parent))
import cockpit  # noqa: E402

TODAY = "2026-11-10"
FIRED: set[str] = set()

GOOD_STATUS = f"""# Demo Status
*Updated: {TODAY}*

## Current State
Login works end to end (commit abc1234, `npm test` green).

## Blockers
None.

## Active TODOs
1. Add password reset.
2. Ship the audit log.

## Resume With
Open `src/auth/reset.ts` and finish `sendResetEmail`. The SMTP mock lives in `test/smtp.ts`.
"""

GOOD_ROADMAP = f"""# Demo Roadmap
*Updated: {TODAY}*

## Current: Accounts
**Objective:** Users can sign up and reset passwords.

## Next: Billing
**Objective:** Stripe checkout.

## Later: Teams
**Objective:** Shared workspaces.
"""

GOOD_CLOSEOUT = """# Login Closeout
*Closed: 2026-10-30*

## Shipped
Email and password login.

## Evidence
PR #12, commit abc1234, CI run 88 green.

## Decisions
Sessions over JWTs, for revocation.

## Changed From Plan
Dropped magic links.

## Follow-ups
Password reset.
"""


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.docs = self.project / "docs"
        self.docs.mkdir()
        self._env = {k: os.environ.get(k) for k in (
            "CLAUDE_PROJECT_DIR", "COCKPIT_ROOT", "COCKPIT_TODAY", "GIT_CEILING_DIRECTORIES")}
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.project)
        os.environ.pop("COCKPIT_ROOT", None)
        os.environ["COCKPIT_TODAY"] = TODAY
        os.environ["GIT_CEILING_DIRECTORIES"] = str(self.project.parent)  # never see an enclosing repo

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def write(self, rel: str, text: str) -> Path:
        p = self.docs / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def good(self):
        self.write("STATUS.md", GOOD_STATUS)
        self.write("ROADMAP.md", GOOD_ROADMAP)
        self.write("archive/2026-10-login.md", GOOD_CLOSEOUT)

    def checks(self, history=None) -> dict[str, str]:
        rep = cockpit.run_checks(self.docs, history=history)
        found = {f["check"]: f["level"] for f in rep.findings}
        FIRED.update(found)
        return found

    def run_cli(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cockpit.main(list(args))
        return code, out.getvalue()


class CleanSet(Base):
    def test_good_set_is_clean(self):
        self.good()
        self.assertEqual(self.checks(), {})
        code, out = self.run_cli("check")
        self.assertEqual(code, 0)
        self.assertIn("OK: 0 fail, 0 warn", out)


class StatusChecks(Base):
    def test_missing_status(self):
        self.assertEqual(self.checks(), {"status-missing": "FAIL"})
        self.assertEqual(self.run_cli("check")[0], 1)

    def test_line_cap(self):
        self.write("STATUS.md", GOOD_STATUS + "\n".join(f"- line {i}" for i in range(60)))
        self.assertEqual(self.checks()["line-cap"], "FAIL")

    def test_updated_missing(self):
        self.write("STATUS.md", GOOD_STATUS.replace(f"*Updated: {TODAY}*", ""))
        self.assertEqual(self.checks()["updated-missing"], "FAIL")

    def test_updated_invalid(self):
        self.write("STATUS.md", GOOD_STATUS.replace(TODAY, "2026-13-45"))
        self.assertEqual(self.checks()["updated-invalid"], "FAIL")

    def test_updated_future(self):
        self.write("STATUS.md", GOOD_STATUS.replace(TODAY, "2027-01-01"))
        self.assertEqual(self.checks()["updated-future"], "FAIL")

    def test_stale(self):
        self.write("STATUS.md", GOOD_STATUS.replace(TODAY, "2026-10-01"))
        self.assertEqual(self.checks(), {"stale": "WARN"})

    def test_section_missing(self):
        self.write("STATUS.md", GOOD_STATUS.replace("## Blockers", "## Problems"))
        self.assertEqual(self.checks()["section-missing"], "FAIL")

    def test_todo_cap(self):
        todos = "\n".join(f"{i}. Task {i}" for i in range(1, 9))
        self.write("STATUS.md", GOOD_STATUS.replace("1. Add password reset.\n2. Ship the audit log.", todos))
        self.assertEqual(self.checks()["todo-cap"], "FAIL")

    def test_todo_cap_ignores_comments_and_sublists(self):
        body = "<!--\n1. a\n2. b\n3. c\n4. d\n5. e\n6. f\n7. g\n8. h\n-->\n1. Real.\n   - detail one\n   - detail two"
        self.write("STATUS.md", GOOD_STATUS.replace("1. Add password reset.\n2. Ship the audit log.", body))
        self.assertNotIn("todo-cap", self.checks())

    def test_resume_empty(self):
        text = GOOD_STATUS.split("## Resume With")[0] + "## Resume With\n<!-- guidance only -->\n"
        self.write("STATUS.md", text)
        self.assertEqual(self.checks()["resume-empty"], "FAIL")

    def test_placeholder(self):
        self.write("STATUS.md", GOOD_STATUS.replace("Login works", "Not yet written. Login works"))
        self.assertEqual(self.checks(), {"placeholder": "WARN"})

    def test_hidden_char(self):
        self.write("STATUS.md", GOOD_STATUS.replace("Login", "Lo\u200bgin"))
        found = self.checks()
        self.assertEqual(found["hidden-char"], "FAIL")

    def test_hidden_tag_char(self):
        self.write("STATUS.md", GOOD_STATUS + "\U000e0049\U000e0047")
        self.assertEqual(self.checks()["hidden-char"], "FAIL")

    def test_strict_fails_on_warnings(self):
        self.write("STATUS.md", GOOD_STATUS.replace(TODAY, "2026-10-01"))
        self.assertEqual(self.run_cli("check")[0], 0)
        self.assertEqual(self.run_cli("check", "--strict")[0], 1)

    def test_json_output(self):
        self.good()
        code, out = self.run_cli("check", "--json")
        data = json.loads(out)
        self.assertEqual((code, data["ok"], data["findings"]), (0, True, []))


class RoadmapAndArchive(Base):
    def test_roadmap_two_current(self):
        self.good()
        self.write("ROADMAP.md", GOOD_ROADMAP.replace("## Next: Billing", "## Current: Billing"))
        self.assertEqual(self.checks(), {"roadmap-shape": "WARN"})

    def test_roadmap_no_current(self):
        self.good()
        self.write("ROADMAP.md", GOOD_ROADMAP.replace("## Current: Accounts", "## Accounts"))
        self.assertEqual(self.checks(), {"roadmap-shape": "WARN"})

    def test_roadmap_too_many(self):
        self.good()
        self.write("ROADMAP.md", GOOD_ROADMAP + "\n## Later: Mobile\n**Objective:** Apps.\n")
        self.assertEqual(self.checks(), {"roadmap-shape": "WARN"})

    def test_archive_name(self):
        self.good()
        self.write("archive/login-done.md", GOOD_CLOSEOUT)
        self.assertEqual(self.checks(), {"archive-name": "WARN"})

    def test_closeout_missing_section(self):
        self.good()
        self.write("archive/2026-11-billing.md", GOOD_CLOSEOUT.replace("## Changed From Plan", "## Notes"))
        self.assertEqual(self.checks(), {"closeout-incomplete": "WARN"})

    def test_closeout_empty_evidence(self):
        self.good()
        self.write("archive/2026-11-billing.md",
                   GOOD_CLOSEOUT.replace("PR #12, commit abc1234, CI run 88 green.", "<!-- todo -->"))
        self.assertEqual(self.checks(), {"closeout-incomplete": "WARN"})


class GitChecks(Base):
    def setUp(self):
        super().setUp()
        git(self.project, "init", "-q")
        self.good()
        git(self.project, "add", "-A")
        git(self.project, "commit", "-qm", "docs")

    def commit(self, msg: str) -> None:
        git(self.project, "add", "-A")
        git(self.project, "commit", "-qm", msg)

    def test_clean_repo(self):
        self.assertEqual(self.checks(history=""), {})

    def test_archive_mutated_uncommitted(self):
        self.write("archive/2026-10-login.md", GOOD_CLOSEOUT + "\nedited\n")
        self.assertEqual(self.checks()["archive-mutated"], "FAIL")

    def test_archive_deleted_uncommitted(self):
        (self.docs / "archive" / "2026-10-login.md").unlink()
        self.assertEqual(self.checks()["archive-mutated"], "FAIL")

    def test_new_closeout_is_fine(self):
        self.write("archive/2026-11-billing.md", GOOD_CLOSEOUT)
        self.assertEqual(self.checks(), {})

    def test_archive_history(self):
        self.write("archive/2026-10-login.md", GOOD_CLOSEOUT + "\nedited\n")
        self.commit("rewrite history")
        self.assertNotIn("archive-history", self.checks())
        self.assertEqual(self.checks(history="")["archive-history"], "FAIL")

    def test_archive_history_since_ref(self):
        self.write("archive/2026-10-login.md", GOOD_CLOSEOUT + "\nold edit\n")
        self.commit("old edit")
        base = subprocess.run(["git", "-C", str(self.project), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        self.write("src.txt", "code")
        self.commit("code")
        self.assertNotIn("archive-history", self.checks(history=base))

    def test_drift(self):
        (self.project / "app.py").write_text("print(1)\n")
        self.commit("feature")
        self.assertEqual(self.checks(), {"drift": "WARN"})

    def test_no_drift_while_status_is_being_edited(self):
        (self.project / "app.py").write_text("print(1)\n")
        self.commit("feature")
        self.write("STATUS.md", GOOD_STATUS.replace("Login works", "Login and signup work"))
        self.assertNotIn("drift", self.checks())


class Commands(Base):
    def test_init_full_never_overwrites(self):
        code, out = self.run_cli("init", "--name", "Demo")
        self.assertEqual(code, 0)
        for f in ("STATUS.md", "ROADMAP.md", "REFERENCE.md", "archive/.gitkeep"):
            self.assertTrue((self.docs / f).exists(), f)
        status = (self.docs / "STATUS.md").read_text()
        self.assertIn("# Demo Status", status)
        self.assertIn(f"*Updated: {TODAY}*", status)
        (self.docs / "STATUS.md").write_text("mine")
        self.run_cli("init")
        self.assertEqual((self.docs / "STATUS.md").read_text(), "mine")

    def test_init_lite(self):
        self.run_cli("init", "--tier", "lite")
        self.assertEqual(sorted(p.name for p in self.docs.iterdir()), ["STATUS.md"])

    def test_fresh_init_has_no_fails(self):
        self.run_cli("init", "--name", "Demo")
        found = self.checks()
        self.assertFalse([c for c, lvl in found.items() if lvl == "FAIL"], found)
        self.assertEqual(found.get("placeholder"), "WARN")

    def test_templates_within_caps(self):
        for name, cap in cockpit.CAPS.items():
            self.assertLessEqual(len((SKILL / "assets" / name).read_text().splitlines()), cap)

    def test_closeout(self):
        code, _ = self.run_cli("closeout", "auth-rewrite", "--month", "2026-11")
        path = self.docs / "archive" / "2026-11-auth-rewrite.md"
        self.assertEqual(code, 0)
        self.assertIn("# Auth rewrite Closeout", path.read_text())
        self.assertEqual(self.run_cli("closeout", "auth-rewrite", "--month", "2026-11")[0], 1)
        self.assertEqual(self.run_cli("closeout", "Bad Slug")[0], 2)
        self.assertEqual(self.run_cli("closeout", "ok", "--month", "2026-13")[0], 2)

    def test_root_override(self):
        other = self.project / "notes"
        other.mkdir()
        (other / "STATUS.md").write_text(GOOD_STATUS)
        os.environ["COCKPIT_ROOT"] = "notes"
        self.assertEqual(self.run_cli("check")[0], 0)


class Brief(Base):
    def brief(self, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), "brief"], capture_output=True, text=True,
                              cwd=cwd or self.project, env=os.environ.copy())

    def test_silent_without_status(self):
        res = self.brief()
        self.assertEqual((res.returncode, res.stdout), (0, ""))

    def test_prints_status_without_comments_or_hidden_chars(self):
        self.write("STATUS.md", GOOD_STATUS.replace("## Blockers", "<!-- secret guidance -->\n## Blockers")
                   .replace("Login", "Lo\u200bgin"))
        self.write("ROADMAP.md", GOOD_ROADMAP)
        res = self.brief()
        self.assertEqual(res.returncode, 0)
        self.assertIn("Project cockpit (docs/STATUS.md)", res.stdout)
        self.assertIn("Login works end to end", res.stdout)
        self.assertNotIn("secret guidance", res.stdout)
        self.assertNotIn("\u200b", res.stdout)
        self.assertIn("ROADMAP.md are in the same folder", res.stdout)

    def test_notes_drift_and_dirty_tree(self):
        git(self.project, "init", "-q")
        self.write("STATUS.md", GOOD_STATUS.replace(TODAY, "2026-10-01"))
        git(self.project, "add", "-A")
        git(self.project, "commit", "-qm", "docs")
        (self.project / "app.py").write_text("x")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-qm", "code")
        (self.project / "wip.py").write_text("y")
        out = self.brief().stdout
        self.assertIn("1 commit(s) landed after STATUS.md", out)
        self.assertIn("1 uncommitted path(s)", out)
        self.assertIn("40 days old", out)

    def test_never_fails(self):
        (self.docs / "STATUS.md").write_bytes(b"\xff\xfe not utf-8")
        res = self.brief()
        self.assertEqual(res.returncode, 0)

    def test_always_reminds_to_keep_current(self):
        self.write("STATUS.md", GOOD_STATUS)
        self.assertIn(cockpit.KEEP_CURRENT, self.brief().stdout)


class Guard(Base):
    """The Stop hook: nudge once when the project moved but STATUS.md did not."""

    def setUp(self):
        super().setUp()
        self._data = tempfile.TemporaryDirectory()  # outside the project, like ~/.claude/plugins/data
        self.addCleanup(self._data.cleanup)
        self.data = Path(self._data.name) / "plugin-data"
        git(self.project, "init", "-q")

    def guard(self, event=None, raw=None, **env) -> subprocess.CompletedProcess:
        payload = raw if raw is not None else json.dumps({"session_id": "s1", "stop_hook_active": False, **(event or {})})
        return subprocess.run([sys.executable, str(SCRIPT), "guard"], input=payload, capture_output=True, text=True,
                              cwd=self.project, env={**os.environ, "CLAUDE_PLUGIN_DATA": str(self.data), **env})

    def nudge(self, res: subprocess.CompletedProcess) -> str:
        self.assertEqual(res.returncode, 0, res.stderr)
        if not res.stdout.strip():
            return ""
        out = json.loads(res.stdout)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "Stop")
        return out["hookSpecificOutput"]["additionalContext"]

    def old_status(self, age: int = 1000) -> Path:
        p = self.write("STATUS.md", GOOD_STATUS)
        past = time.time() - age
        os.utime(p, (past, past))
        return p

    def test_silent_without_status(self):
        (self.project / "app.py").write_text("x")
        self.assertEqual(self.nudge(self.guard()), "")

    def test_silent_outside_git(self):
        shutil.rmtree(self.project / ".git")
        self.old_status()
        (self.project / "app.py").write_text("x")
        self.assertEqual(self.nudge(self.guard()), "")

    def test_nudges_once_for_dirty_code(self):
        self.old_status()
        (self.project / "app.py").write_text("x")
        msg = self.nudge(self.guard())
        self.assertIn("app.py", msg)
        self.assertIn("docs/STATUS.md", msg)
        self.assertEqual(self.nudge(self.guard()), "", "same change must not nudge twice")
        self.assertEqual(self.nudge(self.guard(COCKPIT_GUARD_MINUTES="0")), "", "even with no cooldown")

    def test_never_loops(self):
        self.old_status()
        (self.project / "app.py").write_text("x")
        self.assertEqual(self.nudge(self.guard({"stop_hook_active": True})), "")

    def test_silent_when_status_is_newer(self):
        (self.project / "app.py").write_text("x")
        past = time.time() - 1000
        os.utime(self.project / "app.py", (past, past))
        self.write("STATUS.md", GOOD_STATUS)
        self.assertEqual(self.nudge(self.guard()), "")

    def test_ignores_doc_edits(self):
        self.old_status()
        self.write("ROADMAP.md", GOOD_ROADMAP)
        self.assertEqual(self.nudge(self.guard()), "")

    def test_nudges_for_new_commit(self):
        self.old_status()
        git(self.project, "add", "docs")
        git(self.project, "commit", "-qm", "docs", "--date=2026-01-01T00:00:00")
        subprocess.run(["git", "-C", str(self.project), "commit", "--amend", "--no-edit", "-q"], check=True,
                       env={**os.environ, "GIT_COMMITTER_DATE": "2026-01-01T00:00:00", "GIT_AUTHOR_NAME": "t",
                            "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        os.utime(self.docs / "STATUS.md", (time.time() - 1000,) * 2)
        (self.project / "app.py").write_text("x")
        git(self.project, "add", "app.py")
        git(self.project, "commit", "-qm", "code")
        self.assertIn("commit ", self.nudge(self.guard()))

    def test_silent_when_status_ships_with_the_code(self):
        self.old_status()
        (self.project / "app.py").write_text("x")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-qm", "code and docs")
        os.utime(self.project / "app.py", (time.time() - 2000,) * 2)
        self.assertEqual(self.nudge(self.guard()), "")

    def test_cooldown_then_new_change(self):
        self.old_status()
        (self.project / "app.py").write_text("x")
        self.assertTrue(self.nudge(self.guard()))
        later = time.time() + 5
        (self.project / "more.py").write_text("y")
        os.utime(self.project / "more.py", (later, later))
        self.assertEqual(self.nudge(self.guard()), "", "inside the cooldown")
        self.assertIn("more.py", self.nudge(self.guard(COCKPIT_GUARD_MINUTES="0")))
        self.assertTrue(self.nudge(self.guard({"session_id": "s2"})), "a new session has its own budget")

    def test_off_switch_and_bad_input(self):
        self.old_status()
        (self.project / "app.py").write_text("x")
        self.assertEqual(self.nudge(self.guard(COCKPIT_GUARD="off")), "")
        self.assertEqual(self.nudge(self.guard(raw="not json")), "", "unreadable input: stay quiet")
        self.data.mkdir(exist_ok=True)
        (self.data / "project-cockpit-guard.json").write_text("[corrupt")
        self.assertIn("app.py", self.nudge(self.guard(raw="{}")), "a corrupt state file is rebuilt")
        self.assertEqual(self.nudge(self.guard(raw="{}")), "")


class PreCompact(Base):
    def run_hook(self) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), "precompact"], input='{"trigger": "auto"}',
                              capture_output=True, text=True, cwd=self.project, env=os.environ.copy())

    def test_silent_without_status(self):
        self.assertEqual((self.run_hook().returncode, self.run_hook().stdout), (0, ""))

    def test_instructs_the_summary(self):
        self.write("STATUS.md", GOOD_STATUS)
        res = self.run_hook()
        self.assertEqual(res.returncode, 0)
        self.assertIn("does not already record", res.stdout)
        self.assertLess(len(res.stdout), 10000)


class Package(unittest.TestCase):
    def test_skill_frontmatter(self):
        text = (SKILL / "SKILL.md").read_text()
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        self.assertTrue(m)
        fm = dict(re.findall(r'^(\w+): "?(.*?)"?$', m.group(1), re.M))
        self.assertEqual(fm["name"], "project-cockpit")
        self.assertTrue(fm["description"].startswith("Use when"))
        self.assertLessEqual(len(fm["description"]), 200)
        self.assertEqual(fm["license"], "MIT")

    def test_versions_agree(self):
        plugin = json.loads((SKILL / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(plugin["version"], cockpit.VERSION)
        self.assertIn(f"version: {cockpit.VERSION}", (SKILL / "SKILL.md").read_text())

    def test_marketplace_points_at_plugin(self):
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        entry = market["plugins"][0]
        self.assertTrue((ROOT / entry["source"] / ".claude-plugin" / "plugin.json").exists())
        self.assertEqual(entry["name"], json.loads((SKILL / ".claude-plugin" / "plugin.json").read_text())["name"])

    def test_hooks_call_the_script(self):
        hooks = json.loads((SKILL / "hooks" / "hooks.json").read_text())["hooks"]
        for event, sub in (("SessionStart", "brief"), ("PreCompact", "precompact"), ("Stop", "guard")):
            with self.subTest(event=event):
                cmd = hooks[event][0]["hooks"][0]["command"]
                self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/cockpit.py", cmd)
                self.assertTrue(cmd.endswith(f" {sub}"))
        self.assertEqual(hooks["SessionStart"][0]["matcher"], "startup|resume|clear|compact")

    def test_relative_links_and_referenced_files_exist(self):
        for md in ROOT.rglob("*.md"):
            if ".git" in md.parts:
                continue
            for target in re.findall(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)", md.read_text()):
                with self.subTest(file=str(md.relative_to(ROOT)), link=target):
                    self.assertTrue((md.parent / target.split("#")[0]).exists())
        for ref in re.findall(r"`((?:references|scripts|assets)/[\w./-]+)`", (SKILL / "SKILL.md").read_text()):
            with self.subTest(ref=ref):
                self.assertTrue((SKILL / ref).exists())


def load_tests(loader, standard_tests, pattern):
    """Run every test, then prove each check id fired at least once (a check no test hits is untested)."""
    suite = unittest.TestSuite([standard_tests])

    class Coverage(unittest.TestCase):
        def test_every_check_fires(self):
            self.assertEqual(set(cockpit.CHECKS) - FIRED, set(), "checks no test exercised")

    suite.addTests(loader.loadTestsFromTestCase(Coverage))
    return suite


if __name__ == "__main__":
    unittest.main(verbosity=2)
