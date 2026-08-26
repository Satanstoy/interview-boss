"""Small OpenAI-compatible provider for the disposable real-stack E2E.

It never calls the network.  The failure marker is intentionally available so
the same stack can exercise provider-error observability without real secrets.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _json_response(content: str, model: str = "real-stack-stub") -> dict:
    return {
        "id": "chatcmpl-real-stack-stub",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class StubHandler(BaseHTTPRequestHandler):
    server_version = "InterviewBossE2EStub/1.0"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "provider": "stub"})
            return
        if self.path == "/v1/models":
            self._send_json(
                200,
                {"object": "list", "data": [{"id": "real-stack-stub", "object": "model"}]},
            )
            return
        self._send_json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"message": "invalid json"}})
            return

        messages = payload.get("messages") or []
        serialized = json.dumps(messages, ensure_ascii=False)
        if "E2E_FAIL_PROVIDER" in serialized:
            self._send_json(503, {"error": {"message": "stub provider failure"}})
            return

        if "请为以下题目列表标记" in serialized or "questions" in serialized and "一级大类" in serialized:
            content = json.dumps(
                {
                    "questions": [
                        {
                            "id": 0,
                            "题目": "E2E stub question",
                            "一级大类": "B.Agent与LLM应用",
                            "二级子类": "B1.Agent架构与范式",
                            "考点标签": "Agent架构设计",
                            "难度标签": "L2-中等",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        else:
            content = json.dumps(
                {
                    "type": "JD",
                    "data": {
                        "公司": "InterviewBoss Stub",
                        "岗位名称": "后端工程师",
                        "薪资范围": "未提供",
                        "核心技术要求": ["Python", "SQLite"],
                        "加分项": "熟悉异步任务",
                    },
                },
                ensure_ascii=False,
            )
        self._send_json(200, _json_response(content, payload.get("model", "real-stack-stub")))

    def log_message(self, format: str, *args: object) -> None:
        print(f"stub {self.command} {self.path} {args[1] if len(args) > 1 else ''}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), StubHandler).serve_forever()
