#!/usr/bin/env python3
"""repo-health-mcp: a zero-dependency stdio MCP server for repository health checks.

Tools:
  readme_score       score a repo's README (0-100) and list concrete fixes
  repo_hygiene       check LICENSE, CI, SECURITY.md, CONTRIBUTING, CODE_OF_CONDUCT, .gitignore, CHANGELOG
  changelog_preview  preview the next Keep-a-Changelog section and suggested semver bump (read-only)

Transport: newline-delimited JSON-RPC 2.0 over stdin/stdout (MCP stdio). Python 3.8+ and git.
"""
import glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changelog as cl  # noqa: E402  (bundled from release-kit)

NAME, VERSION = "repo-health", "0.1.0"
SUPPORTED = ["2025-06-18", "2025-03-26", "2024-11-05"]

README_CHECKS = [
    ("title", r"^#\s+\S", "Add a top-level '# Project name' heading", 10),
    ("description", r"^(?![#`>|\-*\s])\S.{40,}", "Add a one-paragraph description of what the project does", 15),
    ("install", r"^#+.*(install|setup)", "Add an Installation / Setup section", 15),
    ("usage", r"^#+.*(usage|quick ?start|getting started|example)", "Add a Usage / Quick start section", 20),
    ("code_block", r"^```", "Include at least one fenced code example", 10),
    ("license", r"^#+.*licen[cs]e|^licen[cs]e:", "Add a License section", 10),
    ("contributing", r"contribut", "Explain how to contribute (or link CONTRIBUTING.md)", 10),
    ("links", r"\]\(https?://", "Link to docs, homepage or CI status", 10),
]


def _repo(args):
    path = os.path.abspath(os.path.expanduser((args or {}).get("path") or "."))
    if not os.path.isdir(path):
        raise ValueError("not a directory: " + path)
    return path


def _first(path, patterns):
    for p in patterns:
        hits = sorted(glob.glob(os.path.join(path, p)))
        if hits:
            return os.path.relpath(hits[0], path).replace("\\", "/")
    return None


def readme_score(args):
    path = _repo(args)
    rel = _first(path, ["README.md", "README.MD", "Readme.md", "readme.md", "README.rst", "README.txt", "README"])
    if not rel:
        return {"file": None, "score": 0, "max": 100, "fixes": [{"check": "exists", "fix": "Create README.md", "points": 100}]}
    with open(os.path.join(path, rel), encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    score, fixes = 0, []
    for name, pat, fix, pts in README_CHECKS:
        if re.search(pat, text, re.M | re.I):
            score += pts
        else:
            fixes.append({"check": name, "fix": fix, "points": pts})
    return {"file": rel, "score": score, "max": 100, "fixes": fixes}


HYGIENE = [
    ("license", ["LICENSE", "LICENSE.*", "LICENCE*", "COPYING*"], "Add a LICENSE file so others can legally use the code"),
    ("ci", [".github/workflows/*.yml", ".github/workflows/*.yaml", ".gitlab-ci.yml", ".circleci/config.yml", "azure-pipelines.yml"], "Add a CI workflow that runs the tests on every push"),
    ("security_policy", ["SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md"], "Add SECURITY.md describing how to report vulnerabilities"),
    ("contributing", ["CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md"], "Add CONTRIBUTING.md with setup and PR guidelines"),
    ("code_of_conduct", ["CODE_OF_CONDUCT.md", ".github/CODE_OF_CONDUCT.md"], "Add CODE_OF_CONDUCT.md"),
    ("gitignore", [".gitignore"], "Add a .gitignore to keep build artifacts out of the repo"),
    ("changelog", ["CHANGELOG.md", "CHANGES.md", "HISTORY.md"], "Add CHANGELOG.md (changelog_preview can draft it)"),
]


def repo_hygiene(args):
    path = _repo(args)
    checks, recs = {}, []
    for name, pats, rec in HYGIENE:
        found = _first(path, pats)
        checks[name] = found
        if not found:
            recs.append(rec)
    passed = sum(1 for v in checks.values() if v)
    return {"path": path, "passed": passed, "total": len(HYGIENE), "found": checks, "recommendations": recs}


def changelog_preview(args):
    path = _repo(args)
    since = (args or {}).get("since") or cl.last_tag(path)
    sections, breaking = cl.build(path, since)
    version = (args or {}).get("version") or cl.suggest_version(since, sections, breaking)
    return {"since": since, "suggested_version": version,
            "markdown": cl.render(version, cl.datetime.date.today().isoformat(), sections, breaking)}


_PATH = {"path": {"type": "string", "description": "Path to the repository root (default: current directory)"}}
TOOLS = {
    "readme_score": (readme_score, "Score the repository README from 0-100 and list concrete fixes with point values.",
                     {"type": "object", "properties": dict(_PATH)}),
    "repo_hygiene": (repo_hygiene, "Check for LICENSE, CI workflow, SECURITY.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, .gitignore and CHANGELOG, with recommendations.",
                     {"type": "object", "properties": dict(_PATH)}),
    "changelog_preview": (changelog_preview, "Preview (read-only) the next Keep-a-Changelog section from git commits since the last tag, plus a suggested semver version.",
                          {"type": "object", "properties": dict(_PATH, since={"type": "string", "description": "git ref to start from (default: last tag)"},
                                                               version={"type": "string", "description": "override the version label"})}),
}


def handle(msg):
    """Return a JSON-RPC response dict, or None for notifications."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if "id" not in msg:
        return None
    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if method == "initialize":
        want = params.get("protocolVersion")
        return ok({"protocolVersion": want if want in SUPPORTED else SUPPORTED[0],
                   "capabilities": {"tools": {}}, "serverInfo": {"name": NAME, "version": VERSION}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": n, "description": d, "inputSchema": s} for n, (_, d, s) in TOOLS.items()]})
    if method == "tools/call":
        name = params.get("name")
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool: %s" % name}}
        try:
            data = TOOLS[name][0](params.get("arguments") or {})
            return ok({"content": [{"type": "text", "text": json.dumps(data, indent=2)}], "isError": False})
        except Exception as e:  # tool errors are reported to the model, not as protocol errors
            return ok({"content": [{"type": "text", "text": "error: %s" % e}], "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            resp = handle(msg) if isinstance(msg, dict) else {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
