"""Small OpenAI-compatible provider for the disposable real-stack E2E.

It never calls the network.  The failure marker is intentionally available so
the same stack can exercise provider-error observability without real secrets.
"""

from __future__ import annotations

import json
import re
import threading
import time
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


class _StubCallLedger:
    """Thread-safe call counter with per-marker fault release for real-stack tests."""

    def __init__(self, fail_markers=()):
        self._fail_markers = set(fail_markers)
        self._released = set()
        self._counts = {}
        self._access_count = 0
        self._status_counts = {}
        self._marker_status_counts = {}
        self._parallel_answer_active = 0
        self._parallel_answer_max_active = 0
        self._parallel_answer_markers = {}
        self._lock = threading.Lock()

    def record(self, marker: str) -> bool:
        """Count one physical HTTP request and return whether it should fail."""
        with self._lock:
            self._counts[marker] = self._counts.get(marker, 0) + 1
            return marker in self._fail_markers and marker not in self._released

    def release(self, marker: str) -> None:
        with self._lock:
            self._released.add(marker)

    def is_released(self, marker: str) -> bool:
        with self._lock:
            return marker in self._released

    def count(self, marker: str) -> int:
        with self._lock:
            return self._counts.get(marker, 0)

    def record_http_access(self) -> None:
        with self._lock:
            self._access_count += 1

    def record_http_status(self, status: int, marker: str | None = None) -> None:
        with self._lock:
            key = str(status)
            self._status_counts[key] = self._status_counts.get(key, 0) + 1
            if marker:
                marker_counts = self._marker_status_counts.setdefault(marker, {})
                marker_counts[key] = marker_counts.get(key, 0) + 1

    def begin_parallel_answer(self, marker: str) -> None:
        with self._lock:
            self._parallel_answer_active += 1
            self._parallel_answer_max_active = max(
                self._parallel_answer_max_active, self._parallel_answer_active
            )
            self._parallel_answer_markers[marker] = (
                self._parallel_answer_markers.get(marker, 0) + 1
            )

    def end_parallel_answer(self) -> None:
        with self._lock:
            self._parallel_answer_active = max(0, self._parallel_answer_active - 1)

    def reset(self) -> None:
        with self._lock:
            self._released.clear()
            self._counts.clear()
            self._access_count = 0
            self._status_counts.clear()
            self._marker_status_counts.clear()
            self._parallel_answer_active = 0
            self._parallel_answer_max_active = 0
            self._parallel_answer_markers.clear()

    def counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def access(self) -> dict:
        with self._lock:
            return {
                "requests": self._access_count,
                "statuses": dict(self._status_counts),
                "marker_statuses": {
                    marker: dict(statuses)
                    for marker, statuses in self._marker_status_counts.items()
                },
                "parallel_answers": {
                    "active": self._parallel_answer_active,
                    "max_active": self._parallel_answer_max_active,
                    "markers": dict(self._parallel_answer_markers),
                },
            }


_AC011_MARKERS = tuple(f"AC011_QUESTION_{ordinal:02d}" for ordinal in range(1, 11))
_AC013_MARKERS = (
    "AC013_AUTH_401",
    "AC013_PERMISSION_403",
    "AC013_RATE_429",
    "AC013_FORMAT_INVALID",
    "AC013_TIMEOUT_ONCE",
)
_AC024_MARKER = "AC024_LEGACY_JD_REAL_STACK"
_AC024_INTERVIEW_MARKER = "AC024_ORDINARY_INTERVIEW_REAL_STACK"
_CALL_LEDGER = _StubCallLedger(
    fail_markers={
        "AC011_QUESTION_09",
        "AC011_QUESTION_10",
        "AC013_RATE_429",
    }
)


class StubHandler(BaseHTTPRequestHandler):
    server_version = "InterviewBossE2EStub/1.0"

    def _send_json(self, status: int, payload: dict) -> None:
        if getattr(self, "_is_model_call", False):
            _CALL_LEDGER.record_http_status(status, getattr(self, "_model_marker", None))
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # The timeout scenario intentionally outlives the client's deadline.
            pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/__e2e/calls":
            self._send_json(200, {"counts": _CALL_LEDGER.counts()})
            return
        if self.path == "/__e2e/access":
            self._send_json(200, _CALL_LEDGER.access())
            return
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
        if self.path == "/__e2e/reset":
            _CALL_LEDGER.reset()
            self._send_json(200, {"status": "reset"})
            return

        self._is_model_call = self.path == "/v1/chat/completions"
        if self._is_model_call:
            _CALL_LEDGER.record_http_access()

        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"message": "invalid json"}})
            return

        messages = payload.get("messages") or []
        serialized = json.dumps(messages, ensure_ascii=False)
        prompt_text = "\n".join(_collect_message_text(messages))

        ac013_marker = next((marker for marker in _AC013_MARKERS if marker in prompt_text), None)
        parallel_answer_marker = next(
            (
                marker
                for marker in (
                    "AC017_PARALLEL_ANSWER_A",
                    "AC017_PARALLEL_ANSWER_B",
                )
                if marker in prompt_text
            ),
            None,
        )
        ac024_marker = _AC024_MARKER if _AC024_MARKER in prompt_text else None
        ac024_interview_marker = (
            _AC024_INTERVIEW_MARKER if _AC024_INTERVIEW_MARKER in prompt_text else None
        )
        self._model_marker = (
            ac013_marker or parallel_answer_marker or ac024_marker or ac024_interview_marker
        )
        if parallel_answer_marker:
            _CALL_LEDGER.begin_parallel_answer(parallel_answer_marker)
            try:
                release_deadline = time.monotonic() + 180
                while (
                    not _CALL_LEDGER.is_released(parallel_answer_marker)
                    and time.monotonic() < release_deadline
                ):
                    time.sleep(0.025)
                if not _CALL_LEDGER.is_released(parallel_answer_marker):
                    self._send_json(504, {"error": {"message": "AC017 release gate timed out"}})
                    return
                answer = f"{parallel_answer_marker}_RESULT: isolated answer for its own question."
                self._send_json(
                    200,
                    _json_response(answer, payload.get("model", "real-stack-stub")),
                )
            finally:
                _CALL_LEDGER.end_parallel_answer()
            return
        if ac024_marker and "请分析以下联合内容" in prompt_text:
            content = json.dumps(
                {
                    "type": "jd",
                    "data": {
                        "公司": "AC024_PRIVATE_COMPANY_SENTINEL",
                        "岗位名称": "AC024 Legacy JD platform engineer",
                        "薪资范围": "AC024_PRIVATE_SALARY_SENTINEL",
                        "核心技术要求": ["AC024_PUBLIC_TECH_GO"],
                        "加分项": "AC024_PUBLIC_BONUS_SQL",
                        "联系人": "AC024_PRIVATE_CONTACT_SENTINEL",
                    },
                },
                ensure_ascii=False,
            )
            self._send_json(200, _json_response(content, payload.get("model", "real-stack-stub")))
            return
        if ac024_interview_marker and "请分析以下联合内容" in prompt_text:
            content = json.dumps(
                {
                    "type": "interview",
                    "data": {
                        "公司": "AC024_ORDINARY_INTERVIEW_COMPANY",
                        "面试轮次": "AC024 legacy compatibility round",
                        "考察重点": "AC024 ordinary interview path",
                        "难易程度": "中等",
                        "具体题目清单": [
                            {
                                "ordinal": 1,
                                "question": "AC024_ORDINARY_INTERVIEW_QUESTION_MARKER: explain transaction isolation.",
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            )
            self._send_json(200, _json_response(content, payload.get("model", "real-stack-stub")))
            return
        if ac024_interview_marker and "请为以下题目列表标记" in prompt_text:
            content = json.dumps(
                {
                    "questions": [
                        {
                            "id": 0,
                            "题目": "AC024_ORDINARY_INTERVIEW_QUESTION_MARKER: explain transaction isolation.",
                            "一级大类": "C.基础工程能力",
                            "二级子类": "C3.数据库基础",
                            "考点标签": "事务隔离",
                            "难度标签": "L2-中等",
                        }
                    ]
                },
                ensure_ascii=False,
            )
            self._send_json(200, _json_response(content, payload.get("model", "real-stack-stub")))
            return
        ac013_should_fail = False
        if ac013_marker and "请分析以下联合内容" in prompt_text:
            ac013_should_fail = _CALL_LEDGER.record(ac013_marker)
            physical_call = _CALL_LEDGER.count(ac013_marker)
            if ac013_marker == "AC013_AUTH_401":
                self._send_json(401, {"error": {"message": "invalid api key"}})
                return
            if ac013_marker == "AC013_PERMISSION_403":
                self._send_json(403, {"error": {"message": "permission denied"}})
                return
            if ac013_marker == "AC013_RATE_429":
                if ac013_should_fail:
                    self._send_json(429, {"error": {"message": "stub rate limit"}})
                    return
                content = json.dumps(
                    {
                        "type": "interview",
                        "data": {
                            "公司": "AC013 限流恢复演练",
                            "面试轮次": "一面",
                            "考察重点": "限流后的手动恢复",
                            "难易程度": "中等",
                            "具体题目清单": [
                                {"ordinal": 1, "question": "如何处理模型 API 的限流？"}
                            ],
                        },
                    },
                    ensure_ascii=False,
                )
                self._send_json(200, _json_response(content, payload.get("model", "real-stack-stub")))
                return
            if ac013_marker == "AC013_FORMAT_INVALID":
                self._send_json(
                    200,
                    _json_response(
                        "{ invalid AC013_PRIVATE_RESPONSE_SENTINEL",
                        payload.get("model", "real-stack-stub"),
                    ),
                )
                return
            if ac013_marker == "AC013_TIMEOUT_ONCE" and physical_call == 1:
                time.sleep(12)

        if "公共参考答案" in prompt_text:
            answer_marker = next((item for item in _AC011_MARKERS if item in prompt_text), None)
            if answer_marker:
                if _CALL_LEDGER.record(answer_marker):
                    self._send_json(503, {"error": {"message": "AC011 temporary answer failure"}})
                    return
                content = f"{answer_marker}_ANSWER：这是可复核的隔离候选答案。"
                self._send_json(200, _json_response(content, payload.get("model", "real-stack-stub")))
                return
            if _AC024_INTERVIEW_MARKER in prompt_text:
                content = (
                    "AC024 ordinary interview answer: explain the transaction boundary, "
                    "isolation level, and a concrete verification case."
                )
                self._send_json(200, _json_response(content, payload.get("model", "real-stack-stub")))
                return

        if ac013_marker == "AC013_TIMEOUT_ONCE" and "请分析以下联合内容" in prompt_text:
            content = json.dumps(
                {
                    "type": "interview",
                    "data": {
                        "公司": "AC013 超时恢复演练",
                        "面试轮次": "一面",
                        "考察重点": "超时后的幂等恢复",
                        "难易程度": "中等",
                        "具体题目清单": [
                            {"ordinal": 1, "question": "超时后如何保证上传结果幂等？"}
                        ],
                    },
                },
                ensure_ascii=False,
            )
            self._send_json(200, _json_response(content, payload.get("model", "real-stack-stub")))
            return

        if "AC011_ANSWER_PARTIAL_REAL_STACK" in prompt_text and "请分析以下联合内容" in prompt_text:
            content = json.dumps(
                {
                    "type": "interview",
                    "data": {
                        "公司": "AC011 部分答案恢复演练",
                        "面试轮次": "一面",
                        "考察重点": "仅恢复失败答案",
                        "难易程度": "中等",
                        "具体题目清单": [
                            {"ordinal": index, "question": f"AC011_QUESTION_{index:02d} 题目 {index}"}
                            for index in range(1, 11)
                        ],
                    },
                },
                ensure_ascii=False,
            )
            self._send_json(200, _json_response(content, payload.get("model", "real-stack-stub")))
            return

        if "AC011_ANSWER_PARTIAL_REAL_STACK" in prompt_text and "请为以下题目列表标记" in prompt_text:
            content = json.dumps(
                {
                    "questions": [
                        {
                            "id": index,
                            "题目": f"AC011_QUESTION_{index + 1:02d} 题目 {index + 1}",
                            "一级大类": "C.基础工程能力",
                            "二级子类": "C1.系统设计",
                            "考点标签": "失败恢复",
                            "难度标签": "L2-中等",
                        }
                        for index in range(10)
                    ]
                },
                ensure_ascii=False,
            )
            self._send_json(200, _json_response(content, payload.get("model", "real-stack-stub")))
            return

        if self.path == "/__e2e/release":
            marker = str(payload.get("marker") or "")
            if marker not in {
                *_AC011_MARKERS,
                *_AC013_MARKERS,
                "AC017_PARALLEL_ANSWER_A",
                "AC017_PARALLEL_ANSWER_B",
            }:
                self._send_json(400, {"error": {"message": "unknown marker"}})
                return
            _CALL_LEDGER.release(marker)
            self._send_json(200, {"status": "released", "marker": marker})
            return

        if "E2E_FAIL_PROVIDER" in serialized:
            self._send_json(503, {"error": {"message": "stub provider failure"}})
            return

        if "AC007_OWNER_RETRY_REAL_STACK" in prompt_text and "请分析以下联合内容" in prompt_text:
            content = json.dumps(
                {
                    "type": "interview",
                    "data": {
                        "公司": "AC007_OWNER_RETRY_REAL_STACK 公司",
                        "面试轮次": "一面",
                        "考察重点": "数据库事务与隔离级别",
                        "难易程度": "中等",
                        "具体题目清单": [
                            {
                                "ordinal": 1,
                                "question": "AC007 checkpoint question: explain database transaction isolation.",
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            )
        elif (
            "AC007_OWNER_RETRY_REAL_STACK" in prompt_text
            and "一级大类" in prompt_text
            and "请为以下题目列表标记" in prompt_text
        ):
            content = json.dumps(
                {
                    "questions": [
                        {
                            "id": 0,
                            "题目": "AC007 checkpoint question: explain database transaction isolation.",
                            "一级大类": "C.基础工程能力",
                            "二级子类": "C3.数据库基础",
                            "考点标签": "事务隔离",
                            "难度标签": "L2-中等",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        elif "AC009_USER_A_REAL_STACK" in prompt_text and "请分析以下联合内容" in prompt_text:
            content = json.dumps(
                {
                    "type": "interview",
                    "data": {
                        "公司": "AC009_USER_A 公司",
                        "面试轮次": "A 用户一面",
                        "考察重点": "A 用户隔离验收",
                        "难易程度": "中等",
                        "具体题目清单": [
                            {"ordinal": 101, "question": "AC009_USER_A 专属问题：解释事务隔离。"}
                        ],
                    },
                },
                ensure_ascii=False,
            )
        elif "AC009_USER_B_REAL_STACK" in prompt_text and "请分析以下联合内容" in prompt_text:
            content = json.dumps(
                {
                    "type": "interview",
                    "data": {
                        "公司": "AC009_USER_B 公司",
                        "面试轮次": "B 用户二面",
                        "考察重点": "B 用户隔离验收",
                        "难易程度": "困难",
                        "具体题目清单": [
                            {"ordinal": 202, "question": "AC009_USER_B 专属问题：解释消息幂等。"}
                        ],
                    },
                },
                ensure_ascii=False,
            )
        elif "AC009_USER_A_REAL_STACK" in prompt_text and "请为以下题目列表标记" in prompt_text:
            content = json.dumps(
                {"questions": [{"id": 0, "题目": "AC009_USER_A 专属问题：解释事务隔离。", "一级大类": "C.基础工程能力", "二级子类": "C3.数据库基础", "考点标签": "事务隔离", "难度标签": "L2-中等"}]},
                ensure_ascii=False,
            )
        elif "AC009_USER_B_REAL_STACK" in prompt_text and "请为以下题目列表标记" in prompt_text:
            content = json.dumps(
                {"questions": [{"id": 0, "题目": "AC009_USER_B 专属问题：解释消息幂等。", "一级大类": "C.基础工程能力", "二级子类": "C3.数据库基础", "考点标签": "消息幂等", "难度标签": "L3-困难"}]},
                ensure_ascii=False,
            )
        elif "AC029_PUBLIC_SHARE_REAL_STACK" in prompt_text and "请分析以下联合内容" in prompt_text:
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
        elif (
            "AC001_TASK_LOCATOR_REAL_STACK" in prompt_text
            and "请分析以下联合内容" in prompt_text
        ):
            content = json.dumps(
                {
                    "type": "interview",
                    "data": {
                        "公司": "AC001_TASK_LOCATOR_REAL_STACK 公司",
                        "面试轮次": "AC001 P2 一面",
                        "考察重点": "异步任务幂等恢复",
                        "难易程度": "中等",
                        "具体题目清单": [
                            {
                                "ordinal": 1,
                                "question": "AC001_TASK_LOCATOR_REAL_STACK：系统怎样验证异步任务的幂等恢复？",
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            )
        elif (
            "AC001_TASK_LOCATOR_REAL_STACK" in prompt_text
            and "请为以下题目列表标记" in prompt_text
        ):
            content = json.dumps(
                {
                    "questions": [
                        {
                            "id": 0,
                            "题目": "AC001_TASK_LOCATOR_REAL_STACK：系统怎样验证异步任务的幂等恢复？",
                            "一级大类": "Fixture",
                            "二级子类": "Fixture",
                            "考点标签": "AC001_TASK_LOCATOR_REAL_STACK",
                            "难度标签": "L2-中等",
                        }
                    ]
                },
                ensure_ascii=False,
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
        elif (
            ("AC016 question A:" in prompt_text or "AC016_FAIL_PUBLIC_B:" in prompt_text)
            and "请为以下题目列表标记" in prompt_text
        ):
            questions = []
            for question in (
                "AC016 question A: how does a distributed lock prevent stale writes?",
                "AC016_FAIL_PUBLIC_B: how should a queue consumer enforce idempotency?",
            ):
                if question in prompt_text:
                    questions.append(
                        {
                            "id": 0,
                            "题目": question,
                            "一级大类": "C.基础工程能力",
                            "二级子类": "C3.分布式基础",
                            "考点标签": "幂等与并发控制",
                            "难度标签": "L2-中等",
                        }
                    )
            content = json.dumps({"questions": questions}, ensure_ascii=False)
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
        elif "AC009_USER_A 专属问题" in prompt_text:
            content = (
                "AC009_USER_A_ANSWER：按照隔离级别解释可见性边界，并指出并发事务的校验步骤。"
            )
        elif "AC009_USER_B 专属问题" in prompt_text:
            content = (
                "AC009_USER_B_ANSWER：使用幂等键约束重复消息，并说明如何验证重试结果。"
            )
        elif "AC009_USER_A_REAL_STACK" in prompt_text or "AC009_USER_B_REAL_STACK" in prompt_text:
            content = (
                "该答案只属于当前上传人的隔离测试记录。请结合题目逐步说明依据、"
                "关键边界和验证方法，不引用另一位用户的数据。"
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
