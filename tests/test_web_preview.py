"""HTTP regressions for the local scenario preview adapter."""

from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from examples.prd_eda_be.web_server import make_web_server


KIT = Path(__file__).resolve().parents[1]
FIXTURES = KIT / "examples/prd_eda_be"
sys.path.insert(0, str(KIT / ".agents/skills/check/scripts"))
from verify_evidence import snapshot, write_evidence


@contextmanager
def running_server(evidence_dir=None):
    server = make_web_server(evidence_dir=evidence_dir)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def fetch(base, path, *, payload=None, raw=None):
    if payload is not None:
        raw = json.dumps(payload).encode("utf-8")
    call = Request(base + path, data=raw, headers={"Content-Type": "application/json"})
    try:
        with urlopen(call, timeout=3) as response:
            return response.status, response.headers, response.read()
    except HTTPError as error:
        return error.code, error.headers, error.read()


def fixture_rows(name):
    import csv
    with (FIXTURES / name).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


class WebPreviewTest(unittest.TestCase):
    def test_bootstrap_returns_real_synthetic_fixtures(self):
        with running_server() as base:
            status, headers, raw = fetch(base, "/api/bootstrap")
        data = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIs(data["simulation"], True)
        self.assertEqual(data["datasets"]["raw"], fixture_rows("raw.csv"))
        self.assertEqual(data["revisions"]["p2"]["contract"]["revision"], "D2")

    def test_existing_p1_and_p2_logic_is_reused(self):
        with running_server() as base:
            status1, _, body1 = fetch(base, "/api/kpi/p1", payload={"rows": fixture_rows("raw.csv")})
            status2, _, body2 = fetch(base, "/api/kpi/p2", payload={"rows": fixture_rows("approved.csv")})
            rejected, _, error = fetch(base, "/api/kpi/p2", payload={"rows": fixture_rows("raw.csv")})
        self.assertEqual((status1, status2, rejected), (200, 200, 422))
        self.assertEqual(json.loads(body1)["kpi"], 7.2)
        self.assertEqual(json.loads(body2)["kpi"], 8)
        self.assertEqual(json.loads(body2)["contract_revision"], "D2")
        self.assertEqual(json.loads(error)["error"]["code"], "validation_error")

    def test_bad_json_is_rejected(self):
        with running_server() as base:
            status, _, body = fetch(base, "/api/kpi/p1", raw=b'{"rows":')
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "invalid_request")

    def test_static_assets_have_expected_content_and_mime(self):
        routes = [
            ("/", FIXTURES / "ui/index.html", "text/html"),
            ("/app.css", FIXTURES / "ui/app.css", "text/css"),
            ("/app.js", FIXTURES / "ui/app.js", "text/javascript"),
            ("/theme.css", KIT / ".agents/skills/frontend/assets/theme.css", "text/css"),
        ]
        if any(not path.is_file() for _, path, _ in routes):
            self.skipTest("Frontend assets have not been created yet")
        with running_server() as base:
            for route, path, mime in routes:
                with self.subTest(route=route):
                    status, headers, body = fetch(base, route)
                    self.assertEqual(status, 200)
                    self.assertEqual(body, path.read_bytes())
                    self.assertIn(mime, headers["Content-Type"])
                    self.assertIn("utf-8", headers["Content-Type"])
                    self.assertEqual(headers["Cache-Control"], "no-store")

    def test_unknown_routes_do_not_expose_files_or_directories(self):
        with running_server() as base:
            for path in ["/backend.py", "/ui/", "/../backend.py", "/api/kpi/p9"]:
                with self.subTest(path=path):
                    status, _, _ = fetch(base, path)
                    self.assertEqual(status, 404)

    def test_unknown_post_route_is_rejected(self):
        with running_server() as base:
            status, _, _ = fetch(base, "/api/kpi/p9", payload={"rows": []})
        self.assertEqual(status, 404)

    def test_evidence_without_a_directory_is_unavailable(self):
        with running_server() as base:
            status, _, body = fetch(base, "/api/evidence?record=p2")
        self.assertEqual(status, 200)
        self.assertIs(json.loads(body)["available"], False)

    def test_missing_evidence_files_are_unavailable(self):
        with tempfile.TemporaryDirectory() as scratch:
            with running_server(scratch) as base:
                status, _, body = fetch(base, "/api/evidence?record=p1")
        self.assertEqual(status, 200)
        self.assertIs(json.loads(body)["available"], False)

    def test_evidence_record_query_is_allowlisted(self):
        with running_server() as base:
            for path in ["/api/evidence", "/api/evidence?record=../backend.py",
                         "/api/evidence?record=p1&record=p2", "/api/evidence?record=p2&path=x"]:
                with self.subTest(path=path):
                    status, _, _ = fetch(base, path)
                    self.assertEqual(status, 400)

    def test_evidence_endpoint_runs_the_real_gate(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            inputs = {}
            for role in ["prd", "contract", "data", "code", "tests"]:
                path = root / (role + ".txt")
                path.write_text(role + " P1", encoding="utf-8")
                inputs[role] = [path.name]
            context = root / "verification-context.json"
            context.write_text(json.dumps({
                "schema_version": 1, "inputs": inputs, "required_ac": ["R1-AC1"],
            }), encoding="utf-8")
            passed = root / "passed.json"
            passed.write_text(json.dumps({
                "command": ["python", "fixture_test.py"], "returncode": 0,
                "checks": [{"id": "B01", "ac_ids": ["R1-AC1"], "status": "PASS"}],
            }), encoding="utf-8")
            write_evidence(root / "evidence-P1.json", snapshot(context), passed)
            (root / "prd.txt").write_text("prd P2", encoding="utf-8")
            write_evidence(root / "evidence-P2.json", snapshot(context), passed)
            failed = root / "failed.json"
            failed.write_text(json.dumps({
                "command": ["python", "fixture_test.py"], "returncode": 1,
                "checks": [{"id": "B01", "ac_ids": ["R1-AC1"], "status": "FAIL"}],
            }), encoding="utf-8")
            write_evidence(root / "evidence-intentional-failure.json", snapshot(context), failed)
            with running_server(root) as base:
                for record, expected in [("p1", "STALE_INPUTS"), ("p2", None), ("failure", "EXECUTION_FAILED")]:
                    with self.subTest(record=record):
                        status, _, body = fetch(base, "/api/evidence?record=" + record)
                        result = json.loads(body)
                        self.assertEqual(status, 200)
                        self.assertIs(result["available"], True)
                        if expected is None:
                            self.assertEqual(result["verdict"]["status"], "PASS")
                        else:
                            self.assertEqual(result["verdict"]["status"], "BLOCKED")
                            self.assertEqual(result["verdict"]["reason"], expected)


if __name__ == "__main__":
    unittest.main()
