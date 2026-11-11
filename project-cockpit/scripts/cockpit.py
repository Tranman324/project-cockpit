#!/usr/bin/env python3
"""project-cockpit: keep a small, capped doc set that lets any fresh agent session resume cold.

Commands
  init      create the doc set from templates (never overwrites)
  check     validate caps, sections, dates, archive immutability, hidden characters
  brief     print STATUS.md plus drift notes; built for a SessionStart hook (always exits 0)
  closeout  start an archive/YYYY-MM-<slug>.md milestone closeout

The doc root defaults to <project>/docs, where <project> is $CLAUDE_PROJECT_DIR or the
current directory. Override with --root or $COCKPIT_ROOT. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"
DESCRIPTION = "Keep a small, capped doc set that lets any fresh agent session resume cold."
ASSETS = Path(__file__).resolve().parent.parent / "assets"

CAPS = {"STATUS.md": 55, "ROADMAP.md": 250, "REFERENCE.md": 200}
STATUS_SECTIONS = ("Current State", "Blockers", "Active TODOs", "Resume With")
CLOSEOUT_SECTIONS = ("Shipped", "Evidence", "Decisions", "Changed From Plan", "Follow-ups")
MAX_TODOS = 7
MAX_MILESTONES = 3
STALE_DAYS = 14
TIERS = {
    "lite": ("STATUS.md",),
    "ops": ("STATUS.md", "REFERENCE.md"),
    "full": ("STATUS.md", "ROADMAP.md", "REFERENCE.md"),
}

ARCHIVE_NAME = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
UPDATED = re.compile(r"^\*{0,2}Updated:\*{0,2}\s*(\S+?)\*{0,2}\s*$", re.I | re.M)
H2 = re.compile(r"^## +(.+?)\s*$", re.M)
COMMENT = re.compile(r"<!--.*?-->", re.S)
LIST_ITEM = re.compile(r"^(?:\d+[.)]|[-*+])\s+\S")
# Invisible or direction-changing characters can smuggle instructions past a human reviewer.
HIDDEN = re.compile("[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]")
PLACEHOLDERS = ("{{", "Not yet written.", "<milestone>", "<one line>")

# Every check id the tool can emit. The test suite proves each one fires.
CHECKS = {
    "status-missing": "STATUS.md does not exist",
    "line-cap": "a doc is over its line cap",
    "updated-missing": "STATUS.md has no 'Updated: YYYY-MM-DD' line",
    "updated-invalid": "the Updated date is not a real YYYY-MM-DD date",
    "updated-future": "the Updated date is in the future",
    "section-missing": "a required section is missing",
    "todo-cap": "Active TODOs has more than 7 items",
    "resume-empty": "Resume With has no content",
    "placeholder": "template placeholder text is still present",
    "stale": "STATUS.md has not been updated in over 14 days",
    "drift": "commits landed after STATUS.md was last committed",
    "roadmap-shape": "ROADMAP.md lacks one Current milestone or carries more than three",
    "archive-name": "an archive file is not named YYYY-MM-<slug>.md",
    "archive-mutated": "a committed archive file has uncommitted edits or deletion",
    "archive-history": "git history shows an archive file was edited, renamed, or deleted",
    "closeout-incomplete": "a closeout is missing a section or has no evidence",
    "hidden-char": "a doc contains invisible or bidirectional Unicode",
}


# ---------------------------------------------------------------- helpers

def project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def resolve_root(arg: str | None) -> Path:
    raw = Path(arg or os.environ.get("COCKPIT_ROOT") or "docs")
    return (raw if raw.is_absolute() else project_dir() / raw).resolve()


def git(root: Path, *args: str) -> str | None:
    """Run git in root. Return stdout, or None when git or the repo is unavailable."""
    try:
        res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout if res.returncode == 0 else None


def in_git(root: Path) -> bool:
    return (git(root, "rev-parse", "--is-inside-work-tree") or "").strip() == "true"


def sections(text: str) -> dict[str, str]:
    """Map each H2 title to its body (up to the next H2)."""
    marks = list(H2.finditer(text))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.setdefault(m.group(1).strip(), text[m.end():end])
    return out


def has_content(body: str) -> bool:
    return bool(COMMENT.sub("", body).strip())


def line_count(text: str) -> int:
    return len(text.splitlines())


def today() -> dt.date:
    override = os.environ.get("COCKPIT_TODAY")  # deterministic tests
    return dt.date.fromisoformat(override) if override else dt.date.today()


class Report:
    def __init__(self, root: Path):
        self.root = root
        self.findings: list[dict] = []

    def add(self, level: str, check: str, file: str, msg: str) -> None:
        assert check in CHECKS, check
        self.findings.append({"level": level, "check": check, "file": file, "message": msg})

    def fail(self, *a: str) -> None:
        self.add("FAIL", *a)

    def warn(self, *a: str) -> None:
        self.add("WARN", *a)

    @property
    def failed(self) -> bool:
        return any(f["level"] == "FAIL" for f in self.findings)


# ---------------------------------------------------------------- checks

def check_status(rep: Report, text: str) -> None:
    f = "STATUS.md"
    m = UPDATED.search(text)
    if not m:
        rep.fail("updated-missing", f, "add '*Updated: YYYY-MM-DD*' under the title")
    else:
        try:
            updated = dt.date.fromisoformat(m.group(1))
        except ValueError:
            rep.fail("updated-invalid", f, f"'{m.group(1)}' is not a YYYY-MM-DD date")
        else:
            age = (today() - updated).days
            if age < 0:
                rep.fail("updated-future", f, f"Updated {updated} is after today")
            elif age > STALE_DAYS:
                rep.warn("stale", f, f"last updated {age} days ago; verify before trusting it")

    secs = sections(text)
    for name in STATUS_SECTIONS:
        if name not in secs:
            rep.fail("section-missing", f, f"missing '## {name}'")
    todos = [ln for ln in COMMENT.sub("", secs.get("Active TODOs", "")).splitlines() if LIST_ITEM.match(ln)]
    if len(todos) > MAX_TODOS:
        rep.fail("todo-cap", f, f"{len(todos)} TODOs (cap {MAX_TODOS}); finish, cut, or move some to ROADMAP.md")
    if "Resume With" in secs and not has_content(secs["Resume With"]):
        rep.fail("resume-empty", f, "write the exact first action for the next session")


def check_roadmap(rep: Report, text: str) -> None:
    heads = [h.strip() for h in H2.findall(text)]
    current = [h for h in heads if h.lower().startswith("current:")]
    milestones = [h for h in heads if h.lower().split(":")[0] in ("current", "next", "later")]
    if len(current) != 1 or len(milestones) > MAX_MILESTONES:
        rep.warn("roadmap-shape", "ROADMAP.md",
                 f"{len(current)} Current and {len(milestones)} total milestones; want 1 Current and at most {MAX_MILESTONES}")


def check_closeout(rep: Report, rel: str, text: str) -> None:
    secs = sections(text)
    missing = [s for s in CLOSEOUT_SECTIONS if s not in secs]
    if missing:
        rep.warn("closeout-incomplete", rel, "missing " + ", ".join(f"'## {s}'" for s in missing))
    elif not has_content(secs["Evidence"]):
        rep.warn("closeout-incomplete", rel, "Evidence is empty; cite commits, test runs, or file:line")


def check_archive_git(rep: Report, root: Path, history: str | None) -> None:
    archive = root / "archive"
    if not archive.is_dir() or not in_git(root):
        return
    for line in (git(root, "status", "--porcelain", "--", str(archive)) or "").splitlines():
        code, path = line[:2], line[3:]
        if code != "??" and ("M" in code or "D" in code or "R" in code):
            rep.fail("archive-mutated", path, "archive is append-only; revert the edit and record the correction in a new closeout")
    if history is not None:
        rng = [f"{history}..HEAD"] if history else []
        out = git(root, "log", *rng, "--format=%h", "--name-status", "--diff-filter=MDR", "--", str(archive))
        changes = [ln for ln in (out or "").splitlines() if ln[:1] in ("M", "D", "R")]
        for ln in changes:
            rep.fail("archive-history", ln.split("\t")[-1], f"history shows '{ln.split(chr(9))[0]}' on an archive file")


def drift(root: Path) -> tuple[int | None, int | None]:
    """Return (commits since STATUS.md was last committed, uncommitted paths), None if unknown."""
    status = root / "STATUS.md"
    if not in_git(root):
        return None, None
    porcelain = git(root, "status", "--porcelain") or ""
    dirty = len([ln for ln in porcelain.splitlines() if ln.strip()])
    if git(root, "status", "--porcelain", "--", str(status)):
        return 0, dirty  # STATUS is being edited right now
    last = (git(root, "log", "-1", "--format=%H", "--", str(status)) or "").strip()
    if not last:
        return None, dirty
    count = (git(root, "rev-list", "--count", f"{last}..HEAD") or "").strip()
    return (int(count) if count.isdigit() else None), dirty


def run_checks(root: Path, history: str | None = None) -> Report:
    rep = Report(root)
    status = root / "STATUS.md"
    if not status.is_file():
        rep.fail("status-missing", "STATUS.md", f"no STATUS.md in {root}; run 'cockpit.py init'")
        return rep

    docs = [p for p in sorted(root.glob("*.md"))]
    archive = root / "archive"
    closeouts = sorted(archive.glob("*.md")) if archive.is_dir() else []
    for path in docs + closeouts:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        cap = CAPS.get(rel)
        if cap and line_count(text) > cap:
            rep.fail("line-cap", rel, f"{line_count(text)} lines (cap {cap}); graduate content out")
        hidden = HIDDEN.findall(text)
        if hidden:
            names = sorted({f"U+{ord(c):04X}" for c in hidden})
            rep.fail("hidden-char", rel, f"{len(hidden)} hidden character(s): {', '.join(names)}")
        if any(p in text for p in PLACEHOLDERS):
            rep.warn("placeholder", rel, "template placeholder text remains")
        if rel == "STATUS.md":
            check_status(rep, text)
        elif rel == "ROADMAP.md":
            check_roadmap(rep, text)
        elif rel.startswith("archive/"):
            if not ARCHIVE_NAME.match(path.name):
                rep.warn("archive-name", rel, "name closeouts YYYY-MM-<slug>.md")
            check_closeout(rep, rel, text)

    check_archive_git(rep, root, history)
    commits, _ = drift(root)
    if commits:
        rep.warn("drift", "STATUS.md", f"{commits} commit(s) since STATUS.md was last committed")
    return rep


# ---------------------------------------------------------------- commands

def render(name: str, **values: str) -> str:
    text = (ASSETS / name).read_text(encoding="utf-8")
    for key, val in values.items():
        text = text.replace("{{" + key + "}}", val)
    return text


def cmd_init(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    name = args.name or project_dir().name
    root.mkdir(parents=True, exist_ok=True)
    files = list(TIERS[args.tier])
    for fname in files:
        dest = root / fname
        if dest.exists():
            print(f"kept     {dest}")
            continue
        dest.write_text(render(fname, PROJECT=name, DATE=today().isoformat()), encoding="utf-8")
        print(f"created  {dest}")
    if "ROADMAP.md" in files:
        keep = root / "archive" / ".gitkeep"
        if not keep.parent.exists():
            keep.parent.mkdir(parents=True)
            keep.touch()
            print(f"created  {keep.parent}/")
    print("next: fill STATUS.md from real sources, then run 'cockpit.py check'")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    rep = run_checks(root, history=args.history)
    failed = rep.failed or (args.strict and bool(rep.findings))
    if args.json:
        print(json.dumps({"root": str(root), "ok": not failed, "findings": rep.findings}, indent=2))
    else:
        for f in rep.findings:
            print(f"{f['level']:<5} {f['file']:<28} {f['check']:<20} {f['message']}")
        fails = sum(f["level"] == "FAIL" for f in rep.findings)
        warns = len(rep.findings) - fails
        print(f"{'FAILED' if failed else 'OK'}: {fails} fail, {warns} warn ({root})")
    return 1 if failed else 0


def cmd_brief(args: argparse.Namespace) -> int:
    try:
        root = resolve_root(args.root)
        status = root / "STATUS.md"
        if not status.is_file():
            return 0
        raw = status.read_text(encoding="utf-8", errors="replace")
        text = HIDDEN.sub("", re.sub(r"[ \t]*<!--.*?-->[ \t]*\n?", "", raw, flags=re.S))
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        try:
            shown = status.relative_to(project_dir())
        except ValueError:
            shown = status
        print(f"Project cockpit ({shown.as_posix()}). Read this before anything else:\n")
        print(text)
        notes = []
        commits, dirty = drift(root)
        if commits:
            notes.append(f"{commits} commit(s) landed after STATUS.md was last committed. Check `git log` before repeating its claims.")
        if dirty:
            notes.append(f"{dirty} uncommitted path(s) in the working tree. Uncommitted work is not progress yet.")
        m = UPDATED.search(text)
        if m:
            try:
                age = (today() - dt.date.fromisoformat(m.group(1))).days
                if age > STALE_DAYS:
                    notes.append(f"STATUS.md is {age} days old. Verify it before trusting it.")
            except ValueError:
                pass
        extra = [n for n in ("ROADMAP.md", "REFERENCE.md") if (root / n).is_file()]
        if extra:
            notes.append(" and ".join(extra) + " are in the same folder. Read them only when the task needs them.")
        if notes:
            print("\nCockpit notes:")
            for n in notes:
                print(f"- {n}")
    except Exception as exc:  # a hook must never break session start
        print(f"(project-cockpit brief skipped: {exc})", file=sys.stderr)
    return 0


def cmd_closeout(args: argparse.Namespace) -> int:
    if not SLUG.match(args.slug):
        print(f"error: slug must be lowercase-hyphenated, got '{args.slug}'", file=sys.stderr)
        return 2
    root = resolve_root(args.root)
    month = args.month or today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        print(f"error: --month must be YYYY-MM, got '{month}'", file=sys.stderr)
        return 2
    dest = root / "archive" / f"{month}-{args.slug}.md"
    if dest.exists():
        print(f"error: {dest} exists; archive files are append-only", file=sys.stderr)
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    title = args.title or args.slug.replace("-", " ").capitalize()
    dest.write_text(render("CLOSEOUT.md", TITLE=title, DATE=today().isoformat()), encoding="utf-8")
    print(f"created  {dest}")
    print("next: fill it in, remove the milestone from ROADMAP.md, promote Next to Current")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cockpit.py", description=DESCRIPTION)
    p.add_argument("--version", action="version", version=f"project-cockpit {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_root(sp: argparse.ArgumentParser) -> argparse.ArgumentParser:
        sp.add_argument("--root", help="doc folder (default: $COCKPIT_ROOT or <project>/docs)")
        return sp

    s = with_root(sub.add_parser("init", help="create the doc set (never overwrites)"))
    s.add_argument("--name", help="project name for the titles (default: folder name)")
    s.add_argument("--tier", choices=sorted(TIERS), default="full",
                   help="lite = STATUS; ops = STATUS + REFERENCE; full = all three + archive/")
    s.set_defaults(func=cmd_init)

    s = with_root(sub.add_parser("check", help="validate the doc set; exit 1 on FAIL"))
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.add_argument("--strict", action="store_true", help="treat warnings as failures")
    s.add_argument("--history", nargs="?", const="", metavar="REF",
                   help="also prove from git history that archive/ only grew (optionally since REF)")
    s.set_defaults(func=cmd_check)

    s = with_root(sub.add_parser("brief", help="print STATUS.md and drift notes (hook-safe)"))
    s.set_defaults(func=cmd_brief)

    s = with_root(sub.add_parser("closeout", help="start a milestone closeout in archive/"))
    s.add_argument("slug", help="lowercase-hyphenated milestone name, e.g. auth-rewrite")
    s.add_argument("--title", help="human title (default: from slug)")
    s.add_argument("--month", help="YYYY-MM (default: this month)")
    s.set_defaults(func=cmd_closeout)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
