"""Serve the local weekly brief and start its two existing browser demos on demand.

Run from any directory:
    python -X utf8 E:/AAOCA_Works/reports/weekly_progress_demo_2026-09-29.py

This helper reads existing snapshots. It does not edit clinical input or output files.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
from queue import Empty, Queue
import socket
import subprocess
import sys
from threading import Lock, Thread
import time
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
PAGE = Path(__file__).with_name("weekly_progress_2026-09-29.html")
SNAPSHOT = ROOT / "data" / "derived" / "v0.1_full"
GOLD = ROOT / "data" / "gold_sets" / "aao_pdf_pages_v1"
WORKBOOK = ROOT / "data" / "review" / "aaoca_exception_review_v1" / "AAOCA_exception_review.xlsx"
HOST = "127.0.0.1"
PORT = 8790
SOURCE_PATHS = {
    "CONTEXT.md",
    "SESSION_LOG.md",
    "case_explorer/README.md",
    "docs/gold_set_review.md",
    "reports/aaoca_exception_scan_2026-09-26.md",
    "reports/aaoca_management_rules_v1_2026-09-26.md",
    "reports/gold_set_sampling_2026-09-25.md",
    "reports/structure_segmentation_validation_2026-09-25.md",
    "data/derived/v0.1_full/run_metadata.json",
    "data/derived/aaoca_management_rules_v1/run_metadata.json",
    "data/derived/aaoca_management_rules_v1/management_evidence.csv",
    "data/derived/aaoca_management_rules_v1/management_summary.csv",
    "reports/aaoca_management_llm_trial_2026-09-29.md",
    "data/gold_sets/aao_pdf_pages_v1/manifest.json",
}


def available_port() -> int:
    with socket.socket() as server:
        server.bind((HOST, 0))
        return server.getsockname()[1]


class DemoManager:
    def __init__(self) -> None:
        self.lock = Lock()
        self.running: dict[str, tuple[subprocess.Popen[str], str]] = {}

    def start(self, name: str) -> str:
        with self.lock:
            existing = self.running.get(name)
            if existing and existing[0].poll() is None:
                return existing[1]
            port = available_port()
            if name == "explorer":
                command = [sys.executable, "-u", "-X", "utf8", "-m", "case_explorer",
                           "--data-root", str(ROOT / "data" / "derived"),
                           "--run", str(SNAPSHOT),
                           "--sidecar-root", str(ROOT / "data" / "derived"),
                           "--port", str(port)]
            elif name == "gold":
                command = [sys.executable, "-u", "-X", "utf8", str(ROOT / "scripts" / "gold_set.py"),
                           "review", "--run", str(SNAPSHOT), "--gold-dir", str(GOLD),
                           "--port", str(port)]
            else:
                raise ValueError("Unknown demo")

            process = subprocess.Popen(
                command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            assert process.stdout is not None
            lines: Queue[str] = Queue()

            def collect() -> None:
                assert process.stdout is not None
                for line in process.stdout:
                    lines.put(line.rstrip())

            Thread(target=collect, daemon=True).start()
            last_lines: list[str] = []
            deadline = time.monotonic() + 25
            try:
                while time.monotonic() < deadline:
                    try:
                        line = lines.get(timeout=0.25)
                    except Empty:
                        if process.poll() is not None:
                            break
                        continue
                    last_lines.append(line)
                    last_lines = last_lines[-4:]
                    if name == "explorer":
                        try:
                            receipt = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if receipt.get("status") == "ready":
                            url = receipt["url"]
                            break
                    elif line.startswith("Open http://127.0.0.1:"):
                        url = line.removeprefix("Open ")
                        break
                else:
                    raise RuntimeError("演示服务启动超时")
                if process.poll() is not None:
                    raise RuntimeError("演示服务已退出")
                parsed = urlsplit(url)
                if parsed.scheme != "http" or parsed.hostname != HOST or parsed.port != port:
                    raise RuntimeError("演示服务返回了无效地址")
            except Exception as exc:
                process.terminate()
                detail = " | ".join(last_lines[-2:])
                raise RuntimeError(f"{exc}: {detail}" if detail else str(exc)) from exc
            self.running[name] = (process, url)
            return url

    def close(self) -> None:
        with self.lock:
            for process, _ in self.running.values():
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()


DEMOS = DemoManager()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            self.respond(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/health":
            body = json.dumps({"status": "ready", "demo_apps": ["explorer", "gold", "workbook"]}).encode()
            self.respond(200, body, "application/json; charset=utf-8")
        elif path in {"/launch/explorer", "/launch/gold"}:
            try:
                url = DEMOS.start(path.rsplit("/", 1)[-1])
            except Exception as exc:
                self.respond(503, f"演示启动失败：{exc}".encode("utf-8"), "text/plain; charset=utf-8")
                return
            self.send_response(302)
            self.send_header("Location", url)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/launch/workbook":
            try:
                if not WORKBOOK.is_file():
                    raise FileNotFoundError("复核工作簿不存在")
                os.startfile(WORKBOOK)
            except (OSError, AttributeError) as exc:
                self.respond(503, f"工作簿打开失败：{exc}".encode("utf-8"), "text/plain; charset=utf-8")
                return
            body = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
                    "<title>复核工作簿</title><body style='font:20px system-ui;padding:3rem'>"
                    "复核工作簿已在本机打开。可以关闭这个标签页。</body></html>").encode("utf-8")
            self.respond(200, body, "text/html; charset=utf-8")
        elif path.startswith("/source/"):
            relative = unquote(path.removeprefix("/source/"))
            source = (ROOT / relative).resolve()
            if relative not in SOURCE_PATHS or not source.is_relative_to(ROOT) or not source.is_file():
                self.respond(404, b"Not found", "text/plain; charset=utf-8")
                return
            content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type == "application/json":
                content_type += "; charset=utf-8"
            self.respond(200, source.read_bytes(), content_type)
        elif path == "/favicon.ico":
            self.respond(204, b"", "image/x-icon")
        else:
            self.respond(404, b"Not found", "text/plain; charset=utf-8")

    def respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Open http://{HOST}:{PORT}/", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        DEMOS.close()


if __name__ == "__main__":
    main()
