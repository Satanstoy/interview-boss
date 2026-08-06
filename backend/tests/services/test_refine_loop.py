"""答案生成质量 loop（Critic → Revise）测试：PASS 提前停、ISSUES 修订、异常回退草稿。"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.answer_enrichment import _extract_question, refine_answer

_SOURCES = [
    {
        "title": "Redis 官方文档",
        "url": "https://redis.io/docs",
        "snippet": "Redis 是一个内存数据结构存储系统，支持字符串、哈希、列表等类型。",
        "published_at": "2026-01-01",
    }
]
_DRAFT = "草稿答案内容"


def _critic_response(verdict, issues=None):
    return json.dumps({"verdict": verdict, "issues": issues or []}, ensure_ascii=False)


async def test_refine_returns_draft_unchanged_when_critic_passes():
    """critic 输出 PASS 时直接返回草稿，revise 不被调用"""
    with patch(
        "app.services.answer_enrichment._call_llm_with_retry", new_callable=AsyncMock
    ) as mock_llm:
        mock_llm.return_value = _critic_response("PASS")
        result, issues = await refine_answer(
            "prompt", _DRAFT, _SOURCES, user_id=1, max_rounds=2
        )
    assert result == _DRAFT
    assert issues == []
    assert mock_llm.call_count == 1


async def test_refine_revises_once_when_issues_and_then_passes():
    """critic 报问题 → revise 一次 → 第二轮 critic PASS → 返回修订稿"""
    revised = "修订后的答案"
    with patch(
        "app.services.answer_enrichment._call_llm_with_retry", new_callable=AsyncMock
    ) as mock_llm:
        mock_llm.side_effect = [
            _critic_response(
                "ISSUES", [{"problem": "事实不准确", "evidence": "资料 1"}]
            ),
            revised,
            _critic_response("PASS"),
        ]
        result, issues = await refine_answer(
            "prompt", _DRAFT, _SOURCES, user_id=1, max_rounds=2
        )
    assert result == revised
    assert issues[0]["problem"] == "事实不准确"
    assert mock_llm.call_count == 3


async def test_refine_stops_at_max_rounds_even_if_issues_remain():
    """连续 ISSUES 时最多跑 max_rounds 轮（1 次 critic + 1 次 revise），不无限循环"""
    revised_a = "修订 A"
    revised_b = "修订 B"
    with patch(
        "app.services.answer_enrichment._call_llm_with_retry", new_callable=AsyncMock
    ) as mock_llm:
        mock_llm.side_effect = [
            _critic_response("ISSUES", [{"problem": "p1", "evidence": "资料 1"}]),
            revised_a,
            _critic_response("ISSUES", [{"problem": "p2", "evidence": "资料 2"}]),
            revised_b,
        ]
        result, _ = await refine_answer(
            "prompt", _DRAFT, _SOURCES, user_id=1, max_rounds=2
        )
    assert result == revised_b
    assert mock_llm.call_count == 4


async def test_refine_returns_draft_when_critic_json_invalid():
    """critic 返回非法 JSON → 回退草稿（不再多花 revise 调用）"""
    with patch(
        "app.services.answer_enrichment._call_llm_with_retry", new_callable=AsyncMock
    ) as mock_llm:
        mock_llm.return_value = "这根本不是 JSON"
        result, issues = await refine_answer(
            "prompt", _DRAFT, _SOURCES, user_id=1, max_rounds=2
        )
    assert result == _DRAFT
    assert issues == []
    assert mock_llm.call_count == 1


async def test_refine_returns_draft_when_llm_raises():
    """LLM 异常 → 回退草稿，不影响主流程"""
    with patch(
        "app.services.answer_enrichment._call_llm_with_retry", new_callable=AsyncMock
    ) as mock_llm:
        mock_llm.side_effect = RuntimeError("LLM down")
        result, issues = await refine_answer(
            "prompt", _DRAFT, _SOURCES, user_id=1, max_rounds=2
        )
    assert result == _DRAFT
    assert issues == []


async def test_refine_no_sources_skips_critic():
    """无搜索来源时（纯模型知识）不跑 critic，直接返回草稿——不浪费调用"""
    with patch(
        "app.services.answer_enrichment._call_llm_with_retry", new_callable=AsyncMock
    ) as mock_llm:
        result, _ = await refine_answer("prompt", _DRAFT, [], user_id=1, max_rounds=2)
    assert result == _DRAFT
    mock_llm.assert_not_called()


async def test_refine_treats_unknown_verdict_as_pass():
    """critic 返回未知 verdict（如 OK）→ 按 PASS 处理，不触发 revise"""
    with patch(
        "app.services.answer_enrichment._call_llm_with_retry", new_callable=AsyncMock
    ) as mock_llm:
        mock_llm.return_value = _critic_response("OK", [{"problem": "p", "evidence": "e"}])
        result, issues = await refine_answer(
            "prompt", _DRAFT, _SOURCES, user_id=1, max_rounds=2
        )
    assert result == _DRAFT
    assert issues == []
    assert mock_llm.call_count == 1


def test_extract_question_extracts_between_markers():
    """有 marker 时提取 USER_CONTENT 内的面试题原文"""
    prompt = (
        "prefix\n===USER_CONTENT_START===\nRedis 的数据结构有哪些？\n"
        "===USER_CONTENT_END===\nsuffix"
    )
    assert _extract_question(prompt) == "Redis 的数据结构有哪些？"


def test_extract_question_falls_back_to_first_300_chars():
    """无 marker 时回退到 prompt 前 300 字"""
    assert _extract_question("") == ""
    long_prompt = "题" * 500
    assert _extract_question(long_prompt) == "题" * 300


async def test_generate_master_answer_uses_refine_loop():
    """单题生成：写库前调用 refine_answer（max_rounds=2），落库的是修订稿"""
    from app.routers.answers import generate_master_answer

    user = {"id": 1, "is_admin": True}
    mock_question = {"id": 10, "question": "什么是微服务？", "ai_answer": None}
    sources = [
        {"title": "Redis 官方文档", "url": "https://redis.io/docs", "snippet": "x"}
    ]

    def _exec(fn):
        return fn()

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
        mock_run_db.side_effect = _exec
        with patch("app.routers.answers.get_db_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_conn.__enter__.return_value = mock_conn
            mock_conn.__exit__.return_value = None
            mock_conn.execute.return_value.fetchone.return_value = mock_question
            mock_get_conn.return_value = mock_conn
            with patch(
                "app.routers.answers.prepare_answer_prompt", new_callable=AsyncMock
            ) as mock_prep:
                mock_prep.return_value = ("prompt", sources)
                with patch(
                    "app.routers.answers.refine_answer", new_callable=AsyncMock
                ) as mock_refine:
                    mock_refine.return_value = ("修订后的答案", [])
                    with patch(
                        "app.routers.answers._call_llm_with_retry",
                        new_callable=AsyncMock,
                    ) as mock_llm:
                        mock_llm.return_value = "草稿答案"
                        result = await generate_master_answer(10, user)

    assert result["answer"] == "修订后的答案"
    mock_refine.assert_awaited_once()
    # max_rounds=2（单题允许 2 轮）
    assert mock_refine.call_args.kwargs.get("max_rounds") == 2
