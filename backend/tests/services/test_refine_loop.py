"""答案生成质量 loop（Critic → Revise）测试：PASS 提前停、ISSUES 修订、异常回退草稿。"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.answer_enrichment import (
    _answer_length_limit,
    _build_revise_prompt,
    _extract_question,
    _ensure_inline_source_citation,
    _normalise_answer_headings,
    refine_answer,
)

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


def test_revise_prompt_carries_source_urls_for_inline_citations():
    prompt = _build_revise_prompt(
        "Redis 为什么快？",
        _DRAFT,
        [{"problem": "缺少正文引用", "evidence": "质量标准第 8 条"}],
        _SOURCES,
    )
    assert "https://redis.io/docs" in prompt
    assert "URL 必须逐字取自上面的资料" in prompt


def test_inline_source_citation_fallback_links_first_prose_line():
    answer = "### 一句话记忆\nRedis 把热点数据放在内存里，读写路径更短。\n\n### 易错点\n不要把持久化当成缓存。"
    result = _ensure_inline_source_citation(answer, _SOURCES)
    assert "[Redis 官方文档](https://redis.io/docs)" in result
    assert result.index("Redis 官方文档") < result.index("### 易错点")


def test_inline_source_citation_fallback_does_not_duplicate_valid_link():
    answer = "Redis 是内存数据结构存储系统。[文档](https://redis.io/docs)"
    assert _ensure_inline_source_citation(answer, _SOURCES) == answer


def test_normalise_answer_headings_removes_gpt_style_labels():
    answer = (
        "**核心解法：**\n先做限流。\n\n"
        "### 2. 落地要点\n用 Redis 扛住热点。\n\n"
        "**务实收尾**\n最后说明边界。\n\n"
        "2. **落地要点**：把消息写进队列。\n"
        "* **务实收尾**：说明跨机房边界。\n"
        "**核心解法：**先做限流。"
    )
    result = _normalise_answer_headings(answer)
    assert "核心解法" not in result
    assert "落地要点" not in result
    assert "务实收尾" not in result
    assert "### 先把思路捋清楚" in result
    assert "### 真正做起来看这几处" in result
    assert "### 最后看边界" in result
    assert "2. 真正做起来看这几处：把消息写进队列。" in result
    assert "* 最后看边界：说明跨机房边界。" in result
    assert "### 先把思路捋清楚\n先做限流。" in result


def test_normalise_answer_headings_does_not_touch_code_blocks_or_specific_titles():
    answer = "```text\n### 核心解法\n```\n\n### Redis 为什么会击穿\n内容"
    assert _normalise_answer_headings(answer) == answer


async def test_refine_returns_draft_unchanged_when_critic_passes():
    """critic 输出 PASS 时直接返回草稿，revise 不被调用"""
    with patch(
        "app.services.answer_enrichment._call_llm_with_retry", new_callable=AsyncMock
    ) as mock_llm:
        mock_llm.return_value = _critic_response("PASS")
        result, issues = await refine_answer(
            "prompt", _DRAFT, _SOURCES, user_id=1, max_rounds=2
        )
    assert result.startswith(_DRAFT)
    assert "[Redis 官方文档](https://redis.io/docs)" in result
    assert issues == []
    assert mock_llm.call_count == 1
    # critic 必须开启深度思考（关思考会让审查变宽松，漏报问题）
    assert mock_llm.call_args.kwargs.get("thinking") is True


async def test_refine_passes_global_scope_to_all_quality_calls():
    """公共答案质量审查和修订必须继续使用全局 LLM 配置。"""
    with patch(
        "app.services.answer_enrichment._call_llm_with_retry", new_callable=AsyncMock
    ) as mock_llm:
        mock_llm.side_effect = [
            _critic_response(
                "ISSUES", [{"problem": "需要更短", "evidence": "标准 2"}]
            ),
            "修订后的答案",
            _critic_response("PASS"),
        ]
        result, _ = await refine_answer(
            "prompt",
            _DRAFT,
            _SOURCES,
            user_id=1014,
            max_rounds=2,
            llm_scope="global",
        )

    assert result.startswith("修订后的答案")
    assert "[Redis 官方文档](https://redis.io/docs)" in result
    assert all(
        call.kwargs.get("llm_scope") == "global"
        for call in mock_llm.call_args_list
    )


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
    assert result.startswith(revised)
    assert "[Redis 官方文档](https://redis.io/docs)" in result
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
    assert result.startswith(revised_b)
    assert "[Redis 官方文档](https://redis.io/docs)" in result
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
    assert result.startswith(_DRAFT)
    assert "[Redis 官方文档](https://redis.io/docs)" in result
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
    assert result.startswith(_DRAFT)
    assert "[Redis 官方文档](https://redis.io/docs)" in result
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
        mock_llm.return_value = _critic_response(
            "OK", [{"problem": "p", "evidence": "e"}]
        )
        result, issues = await refine_answer(
            "prompt", _DRAFT, _SOURCES, user_id=1, max_rounds=2
        )
    assert result.startswith(_DRAFT)
    assert "[Redis 官方文档](https://redis.io/docs)" in result
    assert issues == []
    assert mock_llm.call_count == 1


async def test_refine_forces_revision_when_draft_too_long():
    """critic PASS 但草稿超过确定性字数上限 → 强制注入字数 ISSUE 并 revise"""
    long_draft = "字" * 800
    revised = "字" * 400
    with patch(
        "app.services.answer_enrichment._call_llm_with_retry", new_callable=AsyncMock
    ) as mock_llm:
        mock_llm.side_effect = [
            _critic_response("PASS"),
            revised,
            _critic_response("PASS"),
        ]
        result, issues = await refine_answer(
            "prompt", long_draft, _SOURCES, user_id=1, max_rounds=2
        )
    assert result.startswith(revised)
    assert "[Redis 官方文档](https://redis.io/docs)" in result
    assert any("超出" in i.get("problem", "") for i in issues)
    assert mock_llm.call_count == 3


def test_complex_engineering_question_gets_larger_hard_ceiling():
    question = "Agent 记忆怎么进行管理，用什么存储结构比较好？"
    assert _answer_length_limit(question) == 1200
    assert _answer_length_limit("什么是 Redis？") == 700


async def test_refine_skips_length_check_for_short_draft():
    """critic PASS 且字数合规 → 不额外调用 revise"""
    short_draft = "字" * 300
    with patch(
        "app.services.answer_enrichment._call_llm_with_retry", new_callable=AsyncMock
    ) as mock_llm:
        mock_llm.return_value = _critic_response("PASS")
        result, _ = await refine_answer(
            "prompt", short_draft, _SOURCES, user_id=1, max_rounds=2
        )
    assert result.startswith(short_draft)
    assert "[Redis 官方文档](https://redis.io/docs)" in result
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
    """单题接口只创建 durable job；refine loop 在 ARQ worker 内执行。"""
    from app.routers.answers import generate_master_answer

    user = {"id": 1, "is_admin": True}
    mock_question = {"id": 10, "question": "什么是微服务？", "ai_answer": None}
    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db, \
         patch("app.routers.answers._queue_answer_job", new_callable=AsyncMock) as mock_queue:
        mock_run_db.return_value = mock_question
        mock_queue.return_value = {"status": "queued", "job_id": 10}
        result = await generate_master_answer(10, user)

    assert result == {"status": "queued", "job_id": 10}
    mock_queue.assert_awaited_once_with(
        "generate_answer",
        10,
        mock_question["question"],
        1,
        llm_scope="global",
        search_scope="public",
        skip_search=True,
    )
