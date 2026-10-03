"""Small OpenAI-compatible provider for the disposable real-stack E2E.

It never calls the network.  The failure marker is intentionally available so
the same stack can exercise provider-error observability without real secrets.
"""

from __future__ import annotations

import json
import re
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


def _collect_message_text(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [part for item in value for part in _collect_message_text(item)]
    if isinstance(value, dict):
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            return [value["text"]]
        return [part for item in value.values() for part in _collect_message_text(item)]
    return []


def _extract_unmatched_ids(prompt_text: str) -> list[str]:
    question_section = prompt_text.rsplit("【待匹配的新题目】", 1)[1]
    question_section = question_section.split("请输出 JSON", 1)[0]
    found = re.findall(r"(?m)^\s*\[(\d+)\]\s+", question_section)
    # Some repair prompts include the original user prompt more than once.
    # The matcher contract is one outcome per ID, so preserve order and emit
    # each distinct question ID once.
    return list(dict.fromkeys(found))


def _match_exact_questions(prompt_text: str) -> dict:
    """Return deterministic exact-text matches for matcher prompts.

    The real-stack stub only reuses an existing canonical when the question
    text is identical. Everything else is explicitly reported as unmatched,
    matching the production prompt's one-outcome-per-question contract.
    """
    if "【已有标准题库】" not in prompt_text or "【待匹配的新题目】" not in prompt_text:
        return {"matches": [], "unmatched": []}

    existing_section = prompt_text.rsplit("【已有标准题库】", 1)[1].split(
        "【待匹配的新题目】", 1
    )[0]
    # The real prompt mentions this marker in its introductory instructions
    # before the actual section. Parse the final marker, which starts the
    # question list; otherwise candidate IDs leak into `unmatched`.
    new_section = prompt_text.rsplit("【待匹配的新题目】", 1)[1].split(
        "请输出 JSON", 1
    )[0]

    def read_questions(section: str, *, has_labels: bool) -> list[tuple[str, str]]:
        questions = []
        for line in section.splitlines():
            match = re.match(r"^\s*\[(\d+)\]\s+(.+?)\s*$", line)
            if not match:
                continue
            question_id, question = match.groups()
            if has_labels:
                question = re.sub(r"^\[[^\]]+\]\s+", "", question, count=1)
            questions.append((question_id, question))
        return questions

    canonical_by_text = {}
    for canonical_id, question in read_questions(existing_section, has_labels=True):
        canonical_by_text.setdefault(question, canonical_id)

    matches = []
    unmatched = []
    seen_ids = set()
    for question_id, question in read_questions(new_section, has_labels=False):
        if question_id in seen_ids:
            continue
        seen_ids.add(question_id)
        canonical_id = canonical_by_text.get(question)
        if canonical_id is None:
            unmatched.append(question_id)
        else:
            matches.append(
                {"new_id": question_id, "cluster_id": canonical_id, "confidence": 0.99}
            )
    return {"matches": matches, "unmatched": unmatched}


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
        prompt_text = "\n".join(_collect_message_text(messages))
        if "E2E_FAIL_PROVIDER" in serialized:
            self._send_json(503, {"error": {"message": "stub provider failure"}})
            return

        if "AC029_PUBLIC_SHARE_REAL_STACK" in prompt_text and "请分析以下联合内容" in prompt_text:
            content = json.dumps(
                {
                    "type": "interview",
                    "data": {
                        "公司": "AC029 隔离公司",
                        "面试轮次": "AC029 一面",
                        "考察重点": "Agent 与 LLM 应用",
                        "难易程度": "中等",
                        "具体题目清单": [
                            {"ordinal": 10, "question": "Agent 与普通工作流的核心区别是什么？"},
                            {"ordinal": 20, "question": "多智能体系统如何设计任务协作？"},
                            {"ordinal": 30, "question": "RAG 检索结果不相关时如何定位问题？"},
                            {
                                "ordinal": 40,
                                "question": "Agent 执行链路出现死循环如何自动恢复？ "
                                "AC029_FAIL_PUBLIC_ORDINAL_40",
                            },
                            {"ordinal": 50, "question": "MCP 与 Function Calling 有哪些区别？"},
                        ],
                    },
                },
                ensure_ascii=False,
            )
        elif "AC028_UPLOAD_RECOVERY_REAL_STACK" in serialized and "公共参考答案" in serialized:
            content = (
                "### 核心结论\n"
                "TCP 三次握手通过 SYN、SYN-ACK、ACK 建立可靠连接，确认双方收发能力并协商初始序列号。\n\n"
                "### 建连过程\n"
                "1. 客户端发送 SYN 并进入 SYN-SENT。\n"
                "2. 服务端返回 SYN-ACK 并进入 SYN-RECEIVED。\n"
                "3. 客户端确认 ACK 后进入 ESTABLISHED，服务端收到 ACK 后也进入 ESTABLISHED。\n\n"
                "### 设计原因\n"
                "双向确认可以降低旧连接报文造成错误建连的可能，并让双方确认对方的初始序列号。"
            )
        elif "AC028_UPLOAD_RECOVERY_REAL_STACK" in serialized and "面试题聚类专家" in serialized:
            content = json.dumps({"clusters": []}, ensure_ascii=False)
        elif "AC028_UPLOAD_RECOVERY_REAL_STACK" in serialized and "面试题去重专家" in serialized:
            content = json.dumps({"matches": []}, ensure_ascii=False)
        elif "AC028_UPLOAD_RECOVERY_REAL_STACK" in serialized and "一级大类" not in serialized:
            content = json.dumps(
                {
                    "type": "interview",
                    "data": {
                        "公司": "AC028 隔离恢复演练",
                        "面试轮次": "一面",
                        "考察重点": "上传任务恢复",
                        "难易程度": "中等",
                        "具体题目清单": [
                            {
                                "ordinal": 1,
                                "question": "AC028 恢复后结果题",
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            )
        elif "AC029_FAIL_PUBLIC_ORDINAL_40" in prompt_text and "一级大类" in prompt_text:
            content = json.dumps(
                {
                    "questions": [
                        {
                            "id": index,
                            "题目": question,
                            "一级大类": "B.Agent与LLM应用",
                            "二级子类": "B1.Agent架构与范式",
                            "考点标签": "Agent架构设计",
                            "难度标签": "L2-中等",
                        }
                        for index, question in enumerate(
                            [
                                "Agent 与普通工作流的核心区别是什么？",
                                "多智能体系统如何设计任务协作？",
                                "RAG 检索结果不相关时如何定位问题？",
                                "Agent 执行链路出现死循环如何自动恢复？ "
                                "AC029_FAIL_PUBLIC_ORDINAL_40",
                                "MCP 与 Function Calling 有哪些区别？",
                            ]
                        )
                    ]
                },
                ensure_ascii=False,
            )
        elif "请为以下题目列表标记" in prompt_text or "questions" in serialized and "一级大类" in serialized:
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
        elif "面试题去重专家" in prompt_text:
            if "【待匹配的新题目】" in prompt_text:
                content = json.dumps(_match_exact_questions(prompt_text), ensure_ascii=False)
            else:
                content = json.dumps({"matches": []}, ensure_ascii=False)
        elif "面试题聚类专家" in prompt_text:
            content = json.dumps({"clusters": []}, ensure_ascii=False)
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
