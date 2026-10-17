"""AC-019 / UR-019：提取不静默漏题。

固定输入：Redis 持久化优缺点、线程池优缺点、个人优缺点、TCP 握手四题。

契约（contracts.md §2.3）：

- 完整提取结果保留 4 个 ordinal；技术两题（含“优缺点”）不得删除；
- 个人优缺点可以标 HR 题，但本期默认保留；
- 模型输出 null/数字/重复 ordinal 要 schema 拒绝或明确标待确认，
  不能把字符串迭代成单字题；
- counts 守恒：extracted == retained + excluded（needs_review 是正交标记）。
"""

from __future__ import annotations

import pytest

from app.services.extraction_integrity import (
    ExtractionSchemaError,
    classify_question,
    normalize_extracted_questions,
)
from app.services.pipeline.sanitize import sanitize_batch

FIXED_INPUT = [
    "Redis 持久化方案（RDB/AOF）各有什么优缺点？",
    "线程池有哪些优缺点？参数怎么设置？",
    "你有什么优缺点？",
    "TCP 三次握手的过程是什么？",
]


# ── 不静默漏题 ───────────────────────────────────────────────


def test_all_four_fixed_questions_survive_extraction():
    result = normalize_extracted_questions(FIXED_INPUT)
    questions = result["questions"]
    assert [q["ordinal"] for q in questions] == [1, 2, 3, 4]
    texts = [q["question"] for q in questions]
    assert any("Redis" in t for t in texts), "技术题不得因“优缺点”被删除"
    assert any("线程池" in t for t in texts), "技术题不得因“优缺点”被删除"
    assert any("TCP" in t for t in texts)


def test_personal_strength_weakness_kept_but_marked():
    result = normalize_extracted_questions(FIXED_INPUT)
    personal = next(q for q in result["questions"] if "你有什么优缺点" in q["question"])
    assert personal["retained"] is True
    assert personal["needs_review"] is True or personal["needs_review"] is False
    if personal["needs_review"]:
        assert personal["review_reason"]


def test_technical_优缺点_not_marked_hr():
    result = normalize_extracted_questions(FIXED_INPUT)
    for q in result["questions"]:
        if "Redis" in q["question"] or "线程池" in q["question"]:
            assert classify_question(q["question"])[0] is False


def test_counts_are_conserved():
    result = normalize_extracted_questions(FIXED_INPUT)
    counts = result["counts"]
    assert counts["extracted"] == 4
    assert counts["retained"] + counts["excluded"] == counts["extracted"]
    assert counts["needs_review"] <= counts["retained"]


# ── schema 拒绝而不是丢题 ────────────────────────────────────


def test_null_item_is_rejected_not_dropped():
    with pytest.raises(ExtractionSchemaError):
        normalize_extracted_questions(["TCP 三次握手", None])


def test_numeric_item_is_rejected_not_dropped():
    with pytest.raises(ExtractionSchemaError):
        normalize_extracted_questions([42])


def test_string_input_is_not_iterated_into_characters():
    """模型把清单返回成字符串时，必须报结构错误，不能拆成单字题。"""

    with pytest.raises(ExtractionSchemaError):
        normalize_extracted_questions("TCP三次握手")


def test_duplicate_ordinals_are_rejected():
    with pytest.raises(ExtractionSchemaError):
        normalize_extracted_questions(
            [
                {"ordinal": 1, "question": "TCP 三次握手"},
                {"ordinal": 1, "question": "TCP 四次挥手"},
            ]
        )


def test_explicit_ordinal_gaps_are_preserved_not_renumbered():
    """过滤不能重新编号：恢复时不能把序号写到别的题上。"""

    result = normalize_extracted_questions(
        [
            {"ordinal": 1, "question": "TCP 三次握手"},
            {"ordinal": 7, "question": "Redis 持久化优缺点"},
        ]
    )
    assert [q["ordinal"] for q in result["questions"]] == [1, 7]


# ── sanitize 不再吞掉黑名单题 ────────────────────────────────


def test_sanitize_batch_keeps_blacklist_questions_as_marked():
    batch = [
        {"question": "线程池有哪些优缺点？"},
        {"question": "TCP 三次握手"},
        {"question": "12345"},
    ]
    clean, filtered = sanitize_batch(batch)
    texts = [item["question"] for item in clean]
    assert any("优缺点" in t for t in texts), "黑名单只做标记，不得丢题"
    assert any("TCP" in t for t in texts)
    # 纯数字噪声仍被剔除，但计入 filtered（守恒）
    assert [item["question"] for item in filtered] == ["12345"]
    assert len(clean) + len(filtered) == len(batch)


def test_sanitize_marks_hr_style_without_dropping():
    batch = [{"question": "请做一下自我介绍"}, {"question": "TCP 三次握手"}]
    clean, filtered = sanitize_batch(batch)
    assert len(clean) == 2
    assert all("mark" not in item or item.get("mark") in (None, "needs_review") for item in clean)


# ── 真实 extract 节点接入 schema 校验（R05）────────────────


async def test_extract_node_rejects_string_list_instead_of_splitting_chars():
    """R05：实际 extract 节点对字符串清单抛 MODEL_OUTPUT_INVALID，不拆单字。"""

    from unittest.mock import patch

    from app.agents.submit.extract import extract_node
    from app.services.extraction_integrity import ExtractionSchemaError

    from unittest.mock import AsyncMock, MagicMock

    mock_llm = AsyncMock(
        return_value='{"type": "interview", "data": {"具体题目清单": "TCP 三次握手，Redis 持久化"}}'
    )

    state = {
        "doc_type": "interview",
        "user_id": 101,
        "raw_text": "面经",
        "image_data": [],
        "url": "",
        "season": "",
        "llm_call_count": 0,
    }
    with (
        patch("app.services.llm._call_llm_with_retry_messages", mock_llm),
        patch("app.services.llm._should_use_response_format", return_value=False),
        patch(
            "app.services.llm.get_llm_client_for_user",
            return_value=(MagicMock(), "test-model", 30, "", "openai"),
        ),
    ):
        with pytest.raises(ExtractionSchemaError) as exc_info:
            await extract_node(state)
        assert getattr(exc_info.value, "code", "") == "MODEL_OUTPUT_INVALID"


async def test_extract_node_rejects_null_question_list_instead_of_accepting_empty():
    """R05：null 清单是 schema 错误，不得被 ``or []`` 静默变成空结果。"""

    from unittest.mock import AsyncMock, MagicMock, patch

    from app.agents.submit.extract import extract_node
    from app.services.extraction_integrity import ExtractionSchemaError

    mock_llm = AsyncMock(
        return_value='{"type":"interview","data":{"具体题目清单":null}}'
    )
    state = {
        "doc_type": "interview",
        "user_id": 101,
        "raw_text": "面经",
        "image_data": [],
        "url": "",
        "season": "",
        "llm_call_count": 0,
    }
    with (
        patch("app.services.llm._call_llm_with_retry_messages", mock_llm),
        patch("app.services.llm._should_use_response_format", return_value=False),
        patch(
            "app.services.llm.get_llm_client_for_user",
            return_value=(MagicMock(), "test-model", 30, "", "openai"),
        ),
    ):
        with pytest.raises(ExtractionSchemaError):
            await extract_node(state)


def _install_upload_extract_http_mock(monkeypatch, test_db, *, import_id, responses):
    import httpx
    from openai import AsyncOpenAI
    from app.services import llm
    from app.services.upload_credentials import ResolvedCredential

    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
        "VALUES (101, 'extract-repair-owner', 'x', 0)"
    )
    test_db.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, payload_json, status) "
        "VALUES (?, 101, ?, 'hash', 'private', 'interview', 'upload-pipeline-v1', "
        "'{}', '{}', 'running')",
        (import_id, import_id, ),
    )
    test_db.commit()

    response_specs = iter(responses)
    requests = []

    def handler(request):
        requests.append(request)
        spec = next(response_specs, {"status": 500})
        if spec.get("status") == 429:
            return httpx.Response(
                429,
                json={"error": {"message": "rate limited", "type": "rate_limit_error"}},
                request=request,
            )
        if spec.get("status", 200) != 200:
            return httpx.Response(spec["status"], request=request)
        return httpx.Response(
            200,
            json={
                "id": f"chatcmpl-{len(requests)}",
                "object": "chat.completion",
                "model": "repair-test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": spec["content"]},
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
            request=request,
        )

    base_url = "https://mock.example.com/v1"
    client = AsyncOpenAI(
        api_key="test-key",
        base_url=base_url,
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(llm, "_make_client", lambda *args, **kwargs: client)
    monkeypatch.setattr(
        llm,
        "_resolve_client_and_model",
        lambda user_id, llm_scope="user": (
            client,
            "repair-test-model",
            60,
            base_url,
            "openai",
        ),
    )

    async def chat_format(*args, **kwargs):
        return "chat"

    monkeypatch.setattr(llm, "resolve_api_format_async", chat_format)
    monkeypatch.setattr(llm, "_should_use_response_format", lambda _: False)
    monkeypatch.setattr(
        "app.services.upload_credentials.resolve_upload_credentials",
        lambda **kwargs: ResolvedCredential(
            scope="global",
            payer_type="system",
            payer_user_id=None,
            model="repair-test-model",
            base_url=base_url,
            provider="openai",
            config_fingerprint="extract-repair-test",
            api_key="test-key",
        ),
    )
    return client, requests


def _extract_state(import_id):
    return {
        "import_id": import_id,
        "credential_scope": "global",
        "doc_type": "interview",
        "user_id": 101,
        "raw_text": "面经原文",
        "image_data": [],
        "url": "",
        "season": "",
        "llm_call_count": 0,
    }


async def test_extract_node_repairs_invalid_structure_within_three_physical_calls(
    monkeypatch, test_db
):
    """AC-013/019：有限结构修复中的每次请求都被账本按物理次数记录。"""

    from app.agents.submit.extract import extract_node

    import_id = "imp-extract-repair"
    client, requests = _install_upload_extract_http_mock(
        monkeypatch,
        test_db,
        import_id=import_id,
        responses=[
            {"content": '{"type":"interview","data":{"具体题目清单":"TCP握手"}}'},
            {"content": '{"type":"interview","data":{"具体题目清单":"仍是字符串"}}'},
            {"content": '{"type":"interview","data":{"具体题目清单":["TCP 三次握手"]}}'},
        ],
    )
    result = await extract_node(_extract_state(import_id))

    assert result["extracted_data"]["具体题目清单"] == ["TCP 三次握手"]
    assert len(requests) == 3
    assert test_db.execute(
        "SELECT COUNT(*) FROM upload_llm_calls WHERE root_import_id = ? "
        "AND stage = 'extract' AND unit_key = 'document'",
        (import_id,),
    ).fetchone()[0] == 3
    assert test_db.execute(
        "SELECT COUNT(*) FROM upload_llm_calls WHERE root_import_id = ? "
        "AND status = 'succeeded'",
        (import_id,),
    ).fetchone()[0] == 3
    await client.close()


async def test_extract_repair_rate_limits_share_initial_call_budget(monkeypatch, test_db):
    """初次结构错+修复 429 时，不能把内层重试乘到三次预算之外。"""

    import httpx
    from openai import RateLimitError
    from tenacity import wait_none
    from app.agents.submit.extract import extract_node
    from app.services import llm

    import_id = "imp-extract-repair-429"
    client, requests = _install_upload_extract_http_mock(
        monkeypatch,
        test_db,
        import_id=import_id,
        responses=[
            {"content": '{"type":"interview","data":{"具体题目清单":"TCP握手"}}'},
            {"status": 429},
            {"status": 429},
            {"content": '{"type":"interview","data":{"具体题目清单":["第四次请求不应发出"]}}'},
        ],
    )
    monkeypatch.setattr(
        llm,
        "_call_llm_with_retry_messages",
        llm._call_llm_with_retry_messages.retry_with(wait=wait_none(), reraise=True),
    )

    with pytest.raises(RateLimitError):
        await extract_node(_extract_state(import_id))

    assert len(requests) == 3
    assert test_db.execute(
        "SELECT COUNT(*) FROM upload_llm_calls WHERE root_import_id = ?",
        (import_id,),
    ).fetchone()[0] == 3
    assert test_db.execute(
        "SELECT COUNT(*) FROM upload_llm_calls WHERE root_import_id = ? "
        "AND status = 'failed'",
        (import_id,),
    ).fetchone()[0] == 2
    await client.close()


async def test_extract_node_normalizes_mixed_ordinals():
    """R05：真实节点对 dict 清单按 ordinal 排序去重并保留全部题目。"""

    from unittest.mock import patch

    from app.agents.submit.extract import extract_node

    from unittest.mock import AsyncMock, MagicMock

    mock_llm = AsyncMock(
        return_value=(
            '{"type": "interview", "data": {"具体题目清单": ['
            '{"ordinal": 1, "question": "TCP 三次握手"}, '
            '{"ordinal": 2, "question": "Redis 持久化优缺点"}]}}'
        )
    )

    state = {
        "doc_type": "interview",
        "user_id": 101,
        "raw_text": "面经",
        "image_data": [],
        "url": "",
        "season": "",
        "llm_call_count": 0,
    }
    with (
        patch("app.services.llm._call_llm_with_retry_messages", mock_llm),
        patch("app.services.llm._should_use_response_format", return_value=False),
        patch(
            "app.services.llm.get_llm_client_for_user",
            return_value=(MagicMock(), "test-model", 30, "", "openai"),
        ),
    ):
        result = await extract_node(state)
    data = result["extracted_data"]
    assert [q for q in data["具体题目清单"]] == [
        "TCP 三次握手",
        "Redis 持久化优缺点",
    ]
    assert data["题目 ordinal"] == [1, 2]
    assert data["提取计数"]["extracted"] == 2
    assert data["提取计数"]["retained"] == 2
