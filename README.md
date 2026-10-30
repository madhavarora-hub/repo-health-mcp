# repo-health-mcp

An MCP server with no dependencies that lets Claude (or any MCP client) check a repository's health:

| Tool | What it does |
|---|---|
| `readme_score` | Scores the README from 0 to 100 and lists the fixes, each with its point value |
| `repo_hygiene` | Checks for LICENSE, CI workflow, SECURITY.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, .gitignore and CHANGELOG |
| `changelog_preview` | Read-only preview of the next Keep-a-Changelog section and the suggested semver bump since the last tag |

Requires Python 3.8+ and git. Nothing to install. All checks run locally and nothing leaves your machine.

## Setup (3 steps)

1. Unzip to a folder, e.g. `~/mcp/repo-health/`.
2. Register it with Claude Code:
   `claude mcp add repo-health -- python ~/mcp/repo-health/server.py`
   (Claude Desktop: add `{"command": "python", "args": ["/full/path/server.py"]}` under `mcpServers`.)
3. Ask: *"Check the health of this repo and fix the top 3 issues."*

## Tests

`python -m unittest test_server` runs the unit tests and an end-to-end stdio protocol test.

License: MIT.

---
Built by Dansen-1, an AI agent operated by Dansen AI.
