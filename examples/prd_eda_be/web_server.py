"""Serve the local scenario UI and its existing contract-driven API."""

import argparse
import csv
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit


FIXTURES = Path(__file__).resolve().parent
KIT = FIXTURES.parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / ".agents/skills/check/scripts"))

from examples.prd_eda_be.backend import make_handler
from verify_evidence import verify


def read_json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def read_rows(name):
    with (FIXTURES / name).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def make_web_server(host="127.0.0.1", port=0, evidence_dir=None):
    """Return an unstarted preview server with a fixed route allowlist."""
    revisions = {
        "p1": {"prd": read_json("prd-v1.json"), "contract": read_json("contract-v1.json")},
        "p2": {"prd": read_json("prd-v2.json"), "contract": read_json("contract-v2.json")},
    }
    handlers = {
        revision: make_handler(value["prd"], value["contract"])
        for revision, value in revisions.items()
    }
    bootstrap = {
        "simulation": True,
        "revisions": revisions,
        "datasets": {"raw": read_rows("raw.csv"), "approved": read_rows("approved.csv")},
    }
    assets = {
        "/": (FIXTURES / "ui/index.html", "text/html; charset=utf-8"),
        "/app.css": (FIXTURES / "ui/app.css", "text/css; charset=utf-8"),
        "/app.js": (FIXTURES / "ui/app.js", "text/javascript; charset=utf-8"),
        "/theme.css": (KIT / ".agents/skills/frontend/assets/theme.css", "text/css; charset=utf-8"),
    }
    records = {
        "p1": "evidence-P1.json",
        "p2": "evidence-P2.json",
        "failure": "evidence-intentional-failure.json",
    }
    evidence_root = Path(evidence_dir).resolve() if evidence_dir is not None else None

    class Handler(handlers["p1"]):
        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/api/bootstrap":
                self.respond(200, bootstrap)
                return
            if parsed.path == "/api/evidence":
                query = parse_qs(parsed.query, keep_blank_values=True)
                choices = query.get("record", [])
                if set(query) != {"record"} or len(choices) != 1 or choices[0] not in records:
                    self.error(400, "invalid_request", "Choose p1, p2, or failure")
                    return
                record = choices[0]
                if evidence_root is None:
                    self.respond(200, {"available": False, "record": record, "message": "검증 기록 폴더가 지정되지 않았습니다."})
                    return
                context_path = evidence_root / "verification-context.json"
                evidence_path = evidence_root / records[record]
                if not context_path.is_file() or not evidence_path.is_file():
                    self.respond(200, {"available": False, "record": record, "message": "저장된 검증 기록이 없습니다."})
                    return
                try:
                    verdict = verify(context_path, evidence_path)
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    verdict = {"status": "BLOCKED", "reason": "INVALID_ARTIFACT"}
                self.respond(200, {"available": True, "record": record, "verdict": verdict})
                return
            asset = assets.get(parsed.path)
            if asset is None:
                self.error(404, "not_found", "Unknown endpoint")
                return
            path, content_type = asset
            try:
                body = path.read_bytes()
            except OSError:
                self.error(404, "not_found", "Preview asset unavailable")
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            revision = {"/api/kpi/p1": "p1", "/api/kpi/p2": "p2"}.get(urlsplit(self.path).path)
            if revision is None:
                self.error(404, "not_found", "Unknown endpoint")
                return
            original_path = self.path
            self.path = "/kpi"
            try:
                handlers[revision].do_POST(self)
            finally:
                self.path = original_path

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    server = make_web_server(args.host, args.port, args.evidence_dir)
    print(f"Local preview: http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
