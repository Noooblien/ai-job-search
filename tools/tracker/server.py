"""127.0.0.1-only HTTP server for the job tracker UI.

No portal submissions. Mutations only update local tracker files.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from tracker.store import TrackerStore

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY = 64 * 1024
STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_FILE_ROOTS = ("cv", "cover_letters", "documents/applications")
ALLOWED_FILE_SUFFIXES = {".pdf", ".tex", ".md"}


def _json_bytes(payload: Any, status: int = 200) -> tuple[int, bytes, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, body, "application/json; charset=utf-8"


def _error(message: str, status: int) -> tuple[int, bytes, str]:
    return _json_bytes({"error": message}, status)


class TrackerHandler(BaseHTTPRequestHandler):
    store: TrackerStore
    static_dir: Path

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return False
        if host.startswith("["):
            end = host.find("]")
            hostname = host[1:end] if end != -1 else ""
        else:
            hostname = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        return hostname in {"127.0.0.1", "localhost", "::1"}

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("Request body too large")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON object required")
        return data

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._send(*_error("Host not allowed", 403))
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in {"/", "/index.html"}:
            self._send_static("index.html", "text/html; charset=utf-8")
            return
        if path == "/api/state":
            self._send(*_json_bytes(self.store.snapshot()))
            return
        if path.startswith("/api/"):
            self._send(*_error("Not found", 404))
            return
        if path.startswith("/files/"):
            self._send_local_file(path[len("/files/") :])
            return
        name = posixpath.basename(path)
        if name in {"styles.css", "app.js"}:
            ctype = "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8"
            self._send_static(name, ctype)
            return
        self._send(*_error("Not found", 404))

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._send(*_error("Host not allowed", 403))
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in {"/api/submit", "/api/auto-apply", "/api/apply-online"}:
            self._send(*_error("This tracker never submits applications to job portals.", 405))
            return
        try:
            body = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(*_error(str(exc), 400))
            return
        try:
            if path == "/api/inbox/status":
                snapshot = self.store.set_inbox_status(
                    str(body.get("key") or ""),
                    str(body.get("status") or ""),
                )
                self._send(*_json_bytes(snapshot))
                return
            if path == "/api/mark-applied":
                snapshot = self.store.mark_applied(
                    str(body.get("key") or ""),
                    notes=str(body.get("notes") or ""),
                    channel=str(body.get("channel") or "online"),
                    sector=str(body.get("sector") or ""),
                )
                self._send(*_json_bytes(snapshot))
                return
            if path == "/api/application/status":
                snapshot = self.store.set_application_status(
                    str(body.get("company") or ""),
                    str(body.get("role") or ""),
                    str(body.get("status") or ""),
                    notes=body.get("notes"),
                )
                self._send(*_json_bytes(snapshot))
                return
        except KeyError as exc:
            self._send(*_error(str(exc), 404))
            return
        except ValueError as exc:
            self._send(*_error(str(exc), 400))
            return
        self._send(*_error("Not found", 404))

    def _send_static(self, name: str, content_type: str) -> None:
        path = (self.static_dir / name).resolve()
        if path.parent != self.static_dir.resolve() or not path.is_file():
            self._send(*_error("Not found", 404))
            return
        self._send(200, path.read_bytes(), content_type)

    def _send_local_file(self, rel: str) -> None:
        rel = unquote(rel).lstrip("/")
        candidate = (self.store.root / rel).resolve()
        root = self.store.root.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            self._send(*_error("Not found", 404))
            return
        allowed = False
        for prefix in ALLOWED_FILE_ROOTS:
            try:
                candidate.relative_to(root / prefix)
                allowed = True
                break
            except ValueError:
                continue
        if not allowed or not candidate.is_file() or candidate.suffix.lower() not in ALLOWED_FILE_SUFFIXES:
            self._send(*_error("Not found", 404))
            return
        ctype = {
            ".pdf": "application/pdf",
            ".tex": "text/plain; charset=utf-8",
            ".md": "text/markdown; charset=utf-8",
        }[candidate.suffix.lower()]
        self._send(200, candidate.read_bytes(), ctype)


def make_server(root: Path, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    class BoundHandler(TrackerHandler):
        pass

    BoundHandler.store = TrackerStore(root)
    BoundHandler.static_dir = STATIC_DIR
    server = ThreadingHTTPServer((HOST, port), BoundHandler)
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local job tracker UI. Binds to 127.0.0.1. Never auto-applies.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repo root (default: this repository)",
    )
    args = parser.parse_args(argv)
    if args.port < 1 or args.port > 65535:
        print("Port out of range", file=sys.stderr)
        return 2
    server = make_server(args.root, args.port)
    url = f"http://{HOST}:{server.server_port}/"
    print(f"Job tracker (localhost only): {url}", flush=True)
    print("This UI never submits applications. Open a posting and apply yourself.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
