"""Disposable, pass-through proxy for AC-010 transport fault injection.

Successful upload task responses always come from the real backend. The proxy
can only return a test 500 or cut a real SSE response after its first complete
snapshot frame; all forwarded event evidence is reduced to safe status fields.
"""

from __future__ import annotations

import http.client
import json
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


UPSTREAM_HOST = os.environ.get("AC010_UPSTREAM_HOST", "backend")
UPSTREAM_PORT = int(os.environ.get("AC010_UPSTREAM_PORT", "8000"))
CONTROL_TOKEN = os.environ.get("AC010_CONTROL_TOKEN", "")
TRUNCATE_DELAY_SECONDS = float(os.environ.get("AC010_TRUNCATE_DELAY_SECONDS", "4"))
LOCK = threading.Lock()
REQUESTS: deque[dict] = deque(maxlen=500)
EVENTS: deque[dict] = deque(maxlen=500)
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
SNAPSHOT_FIELDS = ("import_id", "revision", "status", "stage", "progress", "counts")


def record_request(entry: dict) -> None:
    with LOCK:
        REQUESTS.append({"at": time.time(), **entry})


def record_event(path: str, mode: str, frame: bytes) -> None:
    text = frame.decode("utf-8", errors="replace")
    if text.startswith(":"):
        item = {"path": path, "mode": mode, "event": "heartbeat"}
    else:
        event_name = "message"
        event_id = None
        data_lines: list[str] = []
        for line in text.splitlines():
            if line.startswith("event:"):
                event_name = line.partition(":")[2].strip()
            elif line.startswith("id:"):
                event_id = line.partition(":")[2].strip()
            elif line.startswith("data:"):
                data_lines.append(line.partition(":")[2].lstrip())
        item = {"path": path, "mode": mode, "event": event_name, "id": event_id}
        if data_lines:
            try:
                payload = json.loads("\n".join(data_lines))
                item["snapshot"] = {
                    field: payload[field] for field in SNAPSHOT_FIELDS if field in payload
                }
            except (json.JSONDecodeError, TypeError):
                item["event"] = "invalid-json"
    with LOCK:
        EVENTS.append({"at": time.time(), **item})


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "AC010FaultProxy/1.0"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _send_json(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlsplit(self.path).path
        if path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if path == "/__ac010/events":
            if not CONTROL_TOKEN or self.headers.get("X-AC010-Control") != CONTROL_TOKEN:
                self._send_json(404, {"detail": "not found"})
                return
            with LOCK:
                self._send_json(200, {"requests": list(REQUESTS), "events": list(EVENTS)})
            return
        self._proxy()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        self._proxy()

    def do_PUT(self) -> None:  # noqa: N802 - stdlib handler API
        self._proxy()

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib handler API
        self._proxy()

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        self._proxy()

    def _proxy(self) -> None:
        path = urlsplit(self.path).path
        mode = self.headers.get("X-AC010-Fault", "")
        is_upload_task_request = path == "/api/upload-imports" or path.startswith(
            "/api/upload-imports/"
        )
        is_stream = path.endswith("/stream")

        if mode == "delay-401" and self.command == "GET" and path == "/api/upload-imports":
            time.sleep(3)
            record_request({"method": self.command, "path": path, "mode": mode, "status": 401})
            self._send_json(401, {"detail": "AC010 delayed unauthorized response"})
            return

        is_retry = self.command == "POST" and path.endswith("/retry")
        is_task_read = self.command == "GET" and is_upload_task_request and not is_stream
        if mode == "http-500" and (is_task_read or is_retry):
            record_request({"method": self.command, "path": path, "mode": mode, "status": 500})
            detail = (
                "AC010 injected task recovery failure"
                if is_retry
                else "AC010 injected task GET failure"
            )
            self._send_json(500, {"detail": detail})
            return

        body = None
        length = self.headers.get("Content-Length")
        if length:
            body = self.rfile.read(int(length))
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_HEADERS and key.lower() != "x-ac010-fault"
        }
        connection = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=600)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            upstream = connection.getresponse()
            record_request(
                {"method": self.command, "path": path, "mode": mode, "status": upstream.status}
            )
            self.send_response(upstream.status)
            for key, value in upstream.getheaders():
                if key.lower() not in HOP_HEADERS and key.lower() not in {"content-length", "server", "date"}:
                    self.send_header(key, value)
            self.end_headers()

            if mode == "truncate-after-snapshot" and self.command == "GET" and is_stream:
                self._forward_first_frame_then_cut(upstream, path, mode)
                return

            pending = b""
            while True:
                chunk = upstream.read1(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
                if is_stream:
                    pending += chunk
                    while b"\n\n" in pending:
                        frame, pending = pending.split(b"\n\n", 1)
                        record_event(path, mode, frame + b"\n\n")
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            return
        finally:
            connection.close()

    def _forward_first_frame_then_cut(
        self, upstream: http.client.HTTPResponse, path: str, mode: str
    ) -> None:
        pending = b""
        while True:
            chunk = upstream.read1(4096)
            if not chunk:
                return
            pending += chunk
            marker = pending.find(b"\n\n")
            if marker < 0:
                continue
            frame = pending[: marker + 2]
            self.wfile.write(frame)
            self.wfile.flush()
            record_event(path, mode, frame)
            time.sleep(TRUNCATE_DELAY_SECONDS)
            return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8081), Handler)
    server.serve_forever()
