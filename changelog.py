#!/usr/bin/env python3
"""release-kit changelog: build a Keep-a-Changelog section from git history since the last tag.

Usage:
  python changelog.py [REPO] [--since REF] [--version X.Y.Z] [--write] [--json]

Zero dependencies (Python 3.8+ and git). Understands Conventional Commits
(feat:, fix:, feat(scope)!:, BREAKING CHANGE) and falls back to plain-English
verbs (Add/Fix/Remove/Update...) for repos that don't use them.
"""
import argparse, datetime, json, os, re, subprocess, sys

CATS = ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security", "Other"]
PREFIX = {
    "feat": "Added", "feature": "Added", "add": "Added", "new": "Added", "implement": "Added", "initial": "Added",
    "fix": "Fixed", "bugfix": "Fixed", "hotfix": "Fixed", "resolve": "Fixed",
    "perf": "Changed", "refactor": "Changed", "change": "Changed", "update": "Changed",
    "improve": "Changed", "docs": "Changed", "doc": "Changed", "style": "Changed", "rename": "Changed",
    "deprecate": "Deprecated",
    "remove": "Removed", "delete": "Removed", "drop": "Removed", "revert": "Removed",
    "security": "Security",
}
SKIP = {"chore", "ci", "test", "tests", "build", "wip", "merge", "release", "bump"}
CC = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<desc>.+)$")


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "git failed")
    return r.stdout


def last_tag(repo):
    try:
        return git(repo, "describe", "--tags", "--abbrev=0").strip() or None
    except RuntimeError:
        return None


def commits(repo, since):
    rng = [since + "..HEAD"] if since else ["HEAD"]
    out = git(repo, "log", *rng, "--no-merges", "--format=%H%x1f%s%x1f%b%x1e")
    for rec in out.split("\x1e"):
        if not rec.strip():
            continue
        h, s, b = (rec.strip("\n").split("\x1f") + ["", ""])[:3]
        yield h.strip(), s.strip(), b.strip()


def _verb_match(word, key):
    return word in (key, key + "s", key + "es", key + "d", key + "ed")


def classify(subject, body=""):
    """Return (category or None to skip, description, is_breaking)."""
    breaking = "BREAKING CHANGE" in body or "BREAKING-CHANGE" in body
    m = CC.match(subject)
    if m:
        t = m.group("type").lower()
        breaking = breaking or bool(m.group("bang"))
        desc = m.group("desc").strip()
        if m.group("scope"):
            desc = "**%s:** %s" % (m.group("scope"), desc)
        if t in SKIP and not breaking:
            return None, desc, breaking
        if t in PREFIX:
            return PREFIX[t], desc, breaking
        # Unknown prefix such as "CLI:" is a label, not a commit type: keep the full subject.
    words = subject.split()
    first = words[0].lower().rstrip(":,") if words else ""
    if first in SKIP or subject.lower().startswith("merge "):
        return None, subject, breaking
    for key, cat in PREFIX.items():
        if _verb_match(first, key):
            return cat, subject, breaking
    return "Other", subject, breaking


def build(repo, since):
    sections, breaking_notes = {}, []
    for h, s, b in commits(repo, since):
        cat, desc, brk = classify(s, b)
        if brk:
            breaking_notes.append(desc)
        if cat:
            sections.setdefault(cat, []).append((desc, h))
    for items in sections.values():
        items.reverse()  # oldest first reads better in release notes
    return sections, breaking_notes


def suggest_version(tag, sections, breaking):
    m = re.match(r"^(v?)(\d+)\.(\d+)\.(\d+)", tag or "")
    if not m:
        return "0.1.0"
    p = m.group(1)
    a, b, c = int(m.group(2)), int(m.group(3)), int(m.group(4))
    if breaking and a > 0:
        return "%s%d.0.0" % (p, a + 1)
    if breaking or sections.get("Added"):
        return "%s%d.%d.0" % (p, a, b + 1)
    return "%s%d.%d.%d" % (p, a, b, c + 1)


def render(version, date, sections, breaking_notes):
    lines = ["## [%s] - %s" % (version.lstrip("v"), date), ""]
    if breaking_notes:
        lines += ["### BREAKING CHANGES", ""] + ["- " + d for d in breaking_notes] + [""]
    for cat in CATS:
        items = sections.get(cat)
        if items:
            lines += ["### " + cat, ""] + ["- %s (%s)" % (d, h[:7]) for d, h in items] + [""]
    if not sections and not breaking_notes:
        lines += ["_No user-facing changes._", ""]
    return "\n".join(lines)


HEADER = ("# Changelog\n\nAll notable changes to this project are documented in this file.\n"
          "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),\n"
          "and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).\n\n")


def prepend(path, section):
    if os.path.exists(path):
        old = open(path, encoding="utf-8").read()
        i = old.find("\n## ")
        new = (old[:i + 1] + section + "\n" + old[i + 1:]) if i >= 0 else (old.rstrip() + "\n\n" + section)
    else:
        new = HEADER + section
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate a Keep-a-Changelog section from git history.")
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--since", help="git ref to start from (default: last tag)")
    ap.add_argument("--version", help="version label (default: suggested semver bump)")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--write", action="store_true", help="prepend into REPO/CHANGELOG.md")
    ap.add_argument("--json", action="store_true", help="print machine-readable output")
    a = ap.parse_args(argv)
    try:
        since = a.since or last_tag(a.repo)
        sections, breaking = build(a.repo, since)
    except RuntimeError as e:
        print("error: " + str(e), file=sys.stderr)
        return 2
    version = a.version or suggest_version(since, sections, breaking)
    section = render(version, a.date, sections, breaking)
    if a.json:
        print(json.dumps({"since": since, "suggested_version": version, "breaking": breaking,
                          "sections": {k: [{"text": d, "commit": h} for d, h in v] for k, v in sections.items()}},
                         indent=2))
    else:
        print(section)
    if a.write:
        prepend(os.path.join(a.repo, "CHANGELOG.md"), section)
    return 0


if __name__ == "__main__":
    sys.exit(main())
