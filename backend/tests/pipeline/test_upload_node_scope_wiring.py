"""R01/README 二对二：上传节点按服务端 policy 的 credential_scope 选择凭据。

复审缺口：extract/fill/tag/classify 节点不读 ``state["credential_scope"]``，
global（公共导入）阶段实际使用提交者本人 user 凭据。本测试锁死
"节点调用 LLM 时透传 llm_scope" 的真实调用链：

- credential_scope="global" → ``_call_llm_with_retry_messages(..., llm_scope="global")``、
  ``tag_questions_batch(..., llm_scope="global")``（内部解析全局配置，绝不读 user 配置）；
- credential_scope="user"（默认）→ 仍走 ``llm_scope="user"``，行为与旧路径一致。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.submit.extract import extract_node
from app.agents.submit.classify import classify_node


def _state(scope="user", resume=None):
    return {
        "raw_text": "面经：TCP 三次握手与滑动窗口",
        "url": "https://example.com/scope-test",
        "doc_type": "interview",
        "user_id": 101,
        "is_admin": scope == "global",
        "job_position": "后端",
        "credential_scope": scope,
        "_resume_extracted": resume,
        "extracted_data": {
            "公司": "字节",
            "面试轮次": "一面",
            "具体题目清单": ["TCP握手", "滑动窗口"],
            "考察重点": "网络",
            "难易程度": "中等",
        },
    }


def test_extract_node_global_scope_uses_global_llm_scope():
    """AC 二对二公共导入：extract 必须传 llm_scope='global'。"""

    captured = {}

    async def _fake_llm(messages, user_id=None, **kwargs):
        captured["llm_scope"] = kwargs.get("llm_scope")
        captured["user_id"] = user_id
        return '{"type": "interview", "data": {"公司": "字节", "面试轮次": "一面", "具体题目清单": ["TCP握手"], "考察重点": "网络", "难易程度": "中等"}}'

    with (
        patch(
            "app.services.llm._call_llm_with_retry_messages",
            side_effect=_fake_llm,
        ),
        patch(
            "app.services.llm.get_llm_client_for_user",
            return_value=(MagicMock(), "test-model", 30, "https://u", "openai"),
        ),
        patch("app.services.llm._should_use_response_format", return_value=False),
    ):
        result = asyncio.run(extract_node(_state(scope="global")))

    assert captured["llm_scope"] == "global", (
        "global 公共导入的 extract 必须解析系统凭据，禁止用提交者本人 Key"
    )
    assert result["extracted_data"]["具体题目清单"] == ["TCP握手"]


def test_extract_node_user_scope_defaults_to_user():
    """普通私人上传：extract 保持 llm_scope='user'（默认行为不变）。"""

    captured = {}

    async def _fake_llm(messages, user_id=None, **kwargs):
        captured["llm_scope"] = kwargs.get("llm_scope", "user")
        return '{"type": "interview", "data": {"公司": "字节", "面试轮次": "一面", "具体题目清单": ["TCP握手"], "考察重点": "网络", "难易程度": "中等"}}'

    with (
        patch(
            "app.services.llm._call_llm_with_retry_messages", side_effect=_fake_llm
        ),
        patch(
            "app.services.llm.get_llm_client_for_user",
            return_value=(MagicMock(), "test-model", 30, "https://u", "openai"),
        ),
        patch("app.services.llm._should_use_response_format", return_value=False),
    ):
        asyncio.run(extract_node(_state(scope="user")))

    assert captured["llm_scope"] == "user"


def test_classify_node_global_scope_forwards_to_tag_batch():
    """AC 二对二公共导入：classify 打标必须透传 llm_scope='global'。"""

    captured = {}

    async def _fake_tag(**kwargs):
        captured["llm_scope"] = kwargs.get("llm_scope")
        return [
            ["https://example.com/scope-test", "字节", "一面", "TCP握手", "网络", "TCP", "握手", "L2-中等"]
        ]

    with (
        patch(
            "app.services.submit_service.tag_questions_batch",
            side_effect=_fake_tag,
        ),
        patch(
            "app.db.connection.get_taxonomy_for_position",
            return_value={"configured": True, "categories": []},
        ),
    ):
        result = asyncio.run(classify_node(_state(scope="global")))

    assert captured["llm_scope"] == "global", (
        "global 公共导入的打标必须解析系统凭据，禁止用提交者本人 Key"
    )
