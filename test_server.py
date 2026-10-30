import json, os, shutil, subprocess, sys, tempfile, unittest
import server

HERE = os.path.dirname(os.path.abspath(__file__))


def git(d, *a):
    subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)


class Repo(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, rel, text="x\n"):
        p = os.path.join(self.d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_readme_missing_and_full(self):
        self.assertEqual(server.readme_score({"path": self.d})["score"], 0)
        self.write("README.md", "# Demo\n\nDemo is a small tool that does one useful thing very well indeed.\n\n"
                   "## Installation\n\n```\npip install demo\n```\n\n## Usage\n\nRun it. See [docs](https://example.com).\n\n"
                   "## Contributing\n\nPRs welcome.\n\n## License\n\nMIT\n")
        r = server.readme_score({"path": self.d})
        self.assertEqual(r["score"], 100, r["fixes"])

    def test_readme_partial(self):
        self.write("README.md", "# Demo\n")
        r = server.readme_score({"path": self.d})
        self.assertEqual(r["score"], 10)
        self.assertIn("usage", [f["check"] for f in r["fixes"]])

    def test_hygiene(self):
        self.write("LICENSE")
        self.write(".github/workflows/ci.yml")
        self.write(".github/SECURITY.md")
        r = server.repo_hygiene({"path": self.d})
        self.assertEqual(r["found"]["ci"], ".github/workflows/ci.yml")
        self.assertEqual(r["found"]["security_policy"], ".github/SECURITY.md")
        self.assertIsNone(r["found"]["contributing"])
        self.assertEqual(r["passed"], 3)

    def test_changelog_preview(self):
        git(self.d, "init", "-q")
        git(self.d, "config", "user.name", "t")
        git(self.d, "config", "user.email", "t@example.com")
        git(self.d, "config", "commit.gpgsign", "false")
        git(self.d, "commit", "-q", "--allow-empty", "-m", "initial")
        git(self.d, "tag", "v0.1.0")
        git(self.d, "commit", "-q", "--allow-empty", "-m", "feat: add export")
        r = server.changelog_preview({"path": self.d})
        self.assertEqual(r["suggested_version"], "v0.2.0")
        self.assertIn("add export", r["markdown"])
        self.assertFalse(os.path.exists(os.path.join(self.d, "CHANGELOG.md")))  # read-only


class Protocol(unittest.TestCase):
    def test_handle(self):
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
        self.assertEqual(init["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(server.handle({"jsonrpc": "2.0", "id": 2, "method": "nope"})["error"]["code"], -32601)
        bad = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "readme_score", "arguments": {"path": "/no/such/dir"}}})
        self.assertTrue(bad["result"]["isError"])

    def test_stdio_end_to_end(self):
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "repo_hygiene", "arguments": {"path": HERE}}},
        ]
        p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "server.py")], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        out = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
        self.assertEqual([o["id"] for o in out], [1, 2, 3], p.stderr)
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "repo-health")
        self.assertEqual(sorted(t["name"] for t in out[1]["result"]["tools"]), ["changelog_preview", "readme_score", "repo_hygiene"])
        self.assertFalse(out[2]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
