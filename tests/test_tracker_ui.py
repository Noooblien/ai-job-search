"""Tests for the local job tracker UI.

The tracker is a localhost cockpit over seen_jobs.json and
job_search_tracker.csv. It must never grow a portal-submit path.
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS = REPO_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from tracker.server import HOST, make_server  # noqa: E402
from tracker.store import TrackerStore, TRACKER_FIELDS  # noqa: E402

COMMAND_FILE = REPO_ROOT / ".grok" / "commands" / "tracker.md"
INDEX = TOOLS / "tracker" / "static" / "index.html"


def _write_seen(root: Path, seen: dict) -> None:
    path = root / "job_scraper" / "seen_jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"seen": seen}, indent=2) + "\n", encoding="utf-8")


SAMPLE_JOB = {
    "https://example.com/jobs/protocol": {
        "title": "Protocol Engineer",
        "company": "Acme Chain",
        "url": "https://example.com/jobs/protocol",
        "first_seen": "2026-08-01",
        "fit": "high",
        "status": "ranked",
        "portal": "linkedin-search",
        "location": "Remote",
        "rank_score": 81,
        "rank_verdict": "strong fit",
    }
}


class TrackerStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "CLAUDE.md").write_text("**Name:** Test Candidate\n", encoding="utf-8")
        _write_seen(self.root, SAMPLE_JOB)
        self.store = TrackerStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_reads_inbox(self):
        snap = self.store.snapshot()
        self.assertEqual(snap["workspace"], "Test Candidate")
        self.assertEqual(len(snap["jobs"]), 1)
        job = snap["jobs"][0]
        self.assertEqual(job["company"], "Acme Chain")
        self.assertEqual(job["rank_score"], 81)
        self.assertEqual(snap["stats"]["inbox_ranked"], 1)
        self.assertEqual(snap["stats"]["pipeline_total"], 0)

    def test_skip_updates_seen_jobs_only(self):
        self.store.set_inbox_status("https://example.com/jobs/protocol", "skipped")
        seen = json.loads((self.root / "job_scraper" / "seen_jobs.json").read_text())
        self.assertEqual(seen["seen"]["https://example.com/jobs/protocol"]["status"], "skipped")
        self.assertFalse((self.root / "job_search_tracker.csv").exists())

    def test_cannot_mark_applied_via_inbox_status(self):
        with self.assertRaises(ValueError):
            self.store.set_inbox_status("https://example.com/jobs/protocol", "applied")

    def test_mark_applied_writes_tracker_row(self):
        self.store.mark_applied("https://example.com/jobs/protocol", notes="submitted via careers page")
        snap = self.store.snapshot()
        self.assertEqual(snap["jobs"][0]["status"], "applied")
        self.assertEqual(len(snap["applications"]), 1)
        row = snap["applications"][0]
        self.assertEqual(row["company"], "Acme Chain")
        self.assertEqual(row["role"], "Protocol Engineer")
        self.assertEqual(row["status"], "applied")
        self.assertEqual(row["source"], "https://example.com/jobs/protocol")
        self.assertIn("submitted via careers page", row["notes"])
        header = (self.root / "job_search_tracker.csv").read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(header, ",".join(TRACKER_FIELDS))

    def test_application_status_update(self):
        self.store.mark_applied("https://example.com/jobs/protocol")
        self.store.set_application_status("Acme Chain", "Protocol Engineer", "interview")
        row = self.store.load_tracker()[0]
        self.assertEqual(row["status"], "interview")
        self.assertEqual(self.store.snapshot()["stats"]["pipeline_interview"], 1)

    def test_unknown_job_key_errors(self):
        with self.assertRaises(KeyError):
            self.store.set_inbox_status("missing", "skipped")


class TrackerServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "CLAUDE.md").write_text("**Name:** Test Candidate\n", encoding="utf-8")
        _write_seen(self.root, SAMPLE_JOB)
        cv = self.root / "cv" / "main_example.tex"
        cv.parent.mkdir(parents=True, exist_ok=True)
        cv.write_text("% example\n", encoding="utf-8")
        secret = self.root / ".grok" / "config.toml"
        secret.parent.mkdir(parents=True, exist_ok=True)
        secret.write_text("secret = true\n", encoding="utf-8")
        self.httpd = make_server(self.root, port=0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def _conn(self, host="127.0.0.1"):
        return HTTPConnection(host, self.port, timeout=5)

    def _json(self, method, path, body=None, host="127.0.0.1"):
        conn = self._conn()
        headers = {"Host": f"{host}:{self.port}"}
        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=headers)
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        data = json.loads(raw.decode("utf-8")) if raw else {}
        return res.status, data

    def test_binds_localhost_only(self):
        self.assertEqual(self.httpd.server_address[0], HOST)
        self.assertEqual(HOST, "127.0.0.1")

    def test_state_and_home(self):
        status, data = self._json("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(data["workspace"], "Test Candidate")
        conn = self._conn()
        conn.request("GET", "/", headers={"Host": f"127.0.0.1:{self.port}"})
        res = conn.getresponse()
        html = res.read().decode("utf-8")
        conn.close()
        self.assertEqual(res.status, 200)
        self.assertIn("Never auto-applies", html)

    def test_foreign_host_rejected(self):
        status, data = self._json("GET", "/api/state", host="evil.example")
        self.assertEqual(status, 403)
        self.assertIn("Host", data["error"])

    def test_auto_apply_endpoints_are_gone(self):
        for path in ("/api/submit", "/api/auto-apply", "/api/apply-online"):
            status, data = self._json("POST", path, {})
            self.assertEqual(status, 405, path)
            self.assertIn("never submits", data["error"].lower())

    def test_mark_applied_roundtrip(self):
        status, data = self._json(
            "POST",
            "/api/mark-applied",
            {"key": "https://example.com/jobs/protocol"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["stats"]["pipeline_total"], 1)
        self.assertEqual(data["applications"][0]["status"], "applied")

    def test_files_allow_cv_but_not_escape(self):
        conn = self._conn()
        conn.request("GET", "/files/cv/main_example.tex", headers={"Host": f"127.0.0.1:{self.port}"})
        res = conn.getresponse()
        body = res.read()
        conn.close()
        self.assertEqual(res.status, 200)
        self.assertIn(b"% example", body)

        conn = self._conn()
        conn.request("GET", "/files/../.grok/config.toml", headers={"Host": f"127.0.0.1:{self.port}"})
        res = conn.getresponse()
        res.read()
        conn.close()
        self.assertEqual(res.status, 404)


class TrackerCommandFileTests(unittest.TestCase):
    def test_command_file_exists(self):
        self.assertTrue(COMMAND_FILE.exists(), f"{COMMAND_FILE} not found")

    def test_command_file_starts_with_correct_header(self):
        text = COMMAND_FILE.read_text(encoding="utf-8")
        first_line = text.lstrip().splitlines()[0]
        self.assertTrue(
            first_line.startswith("# /tracker"),
            f"Command file must start with '# /tracker', got: {first_line!r}",
        )

    def test_ui_refuses_auto_apply_in_copy(self):
        html = INDEX.read_text(encoding="utf-8")
        self.assertIn("Never auto-applies", html)
        py = (TOOLS / "tracker" / "server.py").read_text(encoding="utf-8")
        self.assertIn("never submits applications to job portals", py.lower())
        self.assertNotIn("linkedin.com/jobs/apply", py)


if __name__ == "__main__":
    unittest.main()
