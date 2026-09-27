from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .repository import CompatibilityError, SnapshotRegistry


STATIC_ROOT = Path(__file__).with_name("static")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class CaseExplorerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], registry: SnapshotRegistry) -> None:
        super().__init__(address, CaseExplorerHandler)
        self.registry = registry


class CaseExplorerHandler(BaseHTTPRequestHandler):
    server: CaseExplorerServer
    server_version = "AAOCACaseExplorer/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")

    def _security_headers(self, *, api: bool = False) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store" if api else "no-cache")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'self'; frame-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )

    def _json(self, value: Any, status: int = HTTPStatus.OK) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._security_headers(api=True)
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, status: int, code: str, message: str) -> None:
        self._json({"error": {"code": code, "message": message}}, status)

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return origin in {f"http://{host}", f"https://{host}"}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/"):
                self._handle_api_get(parsed.path, parse_qs(parsed.query))
            else:
                self._serve_static(parsed.path)
        except KeyError as exc:
            self._error(HTTPStatus.NOT_FOUND, "not_found", f"Unknown record: {exc.args[0]}")
        except FileNotFoundError as exc:
            self._error(HTTPStatus.NOT_FOUND, "source_missing", str(exc))
        except CompatibilityError as exc:
            self._error(HTTPStatus.CONFLICT, "snapshot_incompatible", str(exc))
        except (ValueError, TypeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not self._same_origin():
            self._error(HTTPStatus.FORBIDDEN, "origin_rejected", "Cross-origin requests are not allowed")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 64 * 1024:
                raise ValueError("Request body is too large")
            payload = json.loads(self.rfile.read(length) or b"{}")
            if parsed.path == "/api/runs/select":
                run_key = str(payload.get("run_key") or "")
                if not run_key:
                    raise ValueError("run_key is required")
                self._json(self.server.registry.select(run_key))
                return
            self._error(HTTPStatus.NOT_FOUND, "not_found", "Unknown API route")
        except KeyError as exc:
            self._error(HTTPStatus.NOT_FOUND, "run_not_found", f"Unknown compatible run: {exc.args[0]}")
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
        except CompatibilityError as exc:
            self._error(HTTPStatus.CONFLICT, "snapshot_incompatible", str(exc))

    def _handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/health":
            snapshot = self.server.registry.snapshot()
            self._json(
                {
                    "status": "degraded" if self.server.registry.reload_error else "ok",
                    "run": snapshot.run_key,
                    "loaded_at": snapshot.loaded_at,
                    "reload_error": self.server.registry.reload_error,
                }
            )
            return
        if path == "/api/bootstrap":
            self._json(self.server.registry.bootstrap())
            return
        if path == "/api/runs":
            self._json({"runs": self.server.registry.runs_public()})
            return

        snapshot = self.server.registry.snapshot()
        if path == "/api/patients":
            one = lambda name, default="": query.get(name, [default])[0]
            self._json(
                snapshot.list_patients(
                    query=one("query"),
                    section_type=one("section_type"),
                    parse_status=one("parse_status"),
                    management=one("management"),
                    review_required=one("review_required"),
                    sort=one("sort", "latest_desc"),
                    offset=int(one("offset", "0")),
                    limit=int(one("limit", "50")),
                )
            )
            return
        if path.startswith("/api/patients/"):
            patient_id = unquote(path.removeprefix("/api/patients/"))
            self._json(snapshot.patient_detail(patient_id))
            return
        if path.startswith("/api/sections/"):
            section_id = unquote(path.removeprefix("/api/sections/"))
            self._json(snapshot.section_detail(section_id))
            return
        if path.startswith("/api/documents/") and path.endswith("/pdf"):
            document_id = unquote(path.removeprefix("/api/documents/")[: -len("/pdf")])
            self._serve_pdf(snapshot.pdf_path(document_id))
            return
        self._error(HTTPStatus.NOT_FOUND, "not_found", "Unknown API route")

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else unquote(request_path.lstrip("/"))
        candidate = (STATIC_ROOT / relative).resolve()
        try:
            candidate.relative_to(STATIC_ROOT.resolve())
        except ValueError:
            self._error(HTTPStatus.FORBIDDEN, "path_rejected", "Invalid static path")
            return
        if not candidate.is_file():
            if "." not in Path(relative).name:
                candidate = STATIC_ROOT / "index.html"
            else:
                self._error(HTTPStatus.NOT_FOUND, "not_found", "Static asset not found")
                return
        payload = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _serve_pdf(self, path: Path) -> None:
        size = path.stat().st_size
        range_header = self.headers.get("Range", "")
        start, end = 0, size - 1
        status = HTTPStatus.OK
        if range_header.startswith("bytes="):
            raw = range_header.removeprefix("bytes=").split(",", 1)[0]
            left, _, right = raw.partition("-")
            if left:
                start = int(left)
                end = int(right) if right else end
            elif right:
                start = max(0, size - int(right))
            if start < 0 or start >= size or end < start:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self._security_headers(api=True)
                self.end_headers()
                return
            end = min(end, size - 1)
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self._security_headers(api=True)
        self.end_headers()
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                block = handle.read(min(1024 * 1024, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve a dynamic, local-only browser for AAOCA derived snapshots."
    )
    parser.add_argument(
        "--data-root",
        default="data/derived",
        help="Directory containing one or more completed pipeline snapshots (default: data/derived)",
    )
    parser.add_argument(
        "--run",
        help="Optional exact completed snapshot directory. Without this, the newest compatible run is selected.",
    )
    parser.add_argument(
        "--sidecar-root",
        help="Directory to search for hash-matched management sidecars (default: --data-root)",
    )
    parser.add_argument(
        "--include-identifiers",
        action="store_true",
        help="Load private/patient_linkage.csv for local name and hospital-ID display/search.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Loopback host only (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Local TCP port (default: 8765)")
    parser.add_argument(
        "--reload-interval",
        type=float,
        default=2.0,
        help="Seconds between atomic source-change checks (default: 2)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.host not in LOOPBACK_HOSTS:
        print("error: case_explorer only binds to a loopback host", file=sys.stderr)
        return 2
    try:
        registry = SnapshotRegistry(
            args.data_root,
            run=args.run,
            sidecar_root=args.sidecar_root,
            include_identifiers=args.include_identifiers,
            reload_interval=args.reload_interval,
        )
        server = CaseExplorerServer((args.host, args.port), registry)
    except (CompatibilityError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    host, port = server.server_address[:2]
    receipt = {
        "status": "ready",
        "url": f"http://{host}:{port}/",
        "run": registry.snapshot().run_key,
        "identifiers_loaded": registry.snapshot().include_identifiers,
        "management_sidecar": registry.snapshot().sidecar is not None,
    }
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

