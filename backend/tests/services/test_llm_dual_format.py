"""
测试 LLM 双格式支持（OpenAI / Anthropic）及多模态能力

运行: cd /root/sj/interview-boss/backend && /root/.local/bin/uv run pytest tests/test_llm_dual_format.py -v -s
"""

import pytest
import os

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from pathlib import Path
BACKEND_ROOT = Path(__file__).resolve().parents[2]


from openai import AsyncOpenAI
from anthropic import AsyncAnthropic


API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "")
MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "mimo-v2.5-pro")
LIVE_LLM_ENABLED = os.environ.get("RUN_LIVE_LLM_TESTS") == "1" and bool(API_KEY and OPENAI_BASE_URL)
live_llm_required = pytest.mark.live_llm

ANTHROPIC_BASE_URL = OPENAI_BASE_URL.replace("/v1", "/anthropic") if "/v1" in OPENAI_BASE_URL else OPENAI_BASE_URL + "/anthropic"

TINY_RED_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)
TINY_RED_PNG_DATA_URI = f"data:image/png;base64,{TINY_RED_PNG_B64}"


# ─────────────────────────────────────────────────
# 1. 提供商检测单元测试（不调用 API）
# ─────────────────────────────────────────────────

class TestProviderDetection:

    def test_detect_openai(self):
        from app.services.llm import _detect_provider
        assert _detect_provider("https://example.com/v1") == "openai"
        assert _detect_provider("https://api.openai.com/v1") == "openai"

    def test_detect_anthropic(self):
        from app.services.llm import _detect_provider
        assert _detect_provider("https://example.com/anthropic") == "anthropic"
        assert _detect_provider("https://api.anthropic.com") == "anthropic"

    def test_detect_empty(self):
        from app.services.llm import _detect_provider
        assert _detect_provider("") == "openai"
        assert _detect_provider(None) == "openai"

    def test_should_use_response_format(self):
        from app.services.llm import _should_use_response_format
        assert _should_use_response_format("https://example.com/v1") is True
        assert _should_use_response_format("https://example.com/anthropic") is False

    def test_make_client_openai(self):
        from app.services.llm import _make_client
        c = _make_client("test-key", "https://example.com/v1", 10.0, "openai")
        assert isinstance(c, AsyncOpenAI)

    def test_make_client_anthropic(self):
        from app.services.llm import _make_client
        c = _make_client("test-key", "https://example.com/anthropic", 10.0, "anthropic")
        assert isinstance(c, AsyncAnthropic)

    def test_convert_messages_basic(self):
        from app.services.llm import _convert_openai_messages_to_anthropic
        messages = [
            {"role": "system", "content": "你是一个助手"},
            {"role": "user", "content": "你好"},
        ]
        system_text, anthropic_msgs = _convert_openai_messages_to_anthropic(messages)
        assert system_text == "你是一个助手"
        assert len(anthropic_msgs) == 1
        assert anthropic_msgs[0]["role"] == "user"

    def test_convert_messages_multimodal(self):
        from app.services.llm import _convert_openai_messages_to_anthropic
        messages = [
            {"role": "system", "content": "你是一个助手"},
            {"role": "user", "content": [
                {"type": "text", "text": "描述这张图片"},   # OpenAI 格式用 "text" key
                {"type": "image_url", "image_url": {"url": TINY_RED_PNG_DATA_URI}},
            ]},
        ]
        system_text, anthropic_msgs = _convert_openai_messages_to_anthropic(messages)
        assert system_text == "你是一个助手"
        user_content = anthropic_msgs[0]["content"]
        assert len(user_content) == 2
        assert user_content[0]["type"] == "text"
        assert user_content[1]["type"] == "image"
        assert user_content[1]["source"]["media_type"] == "image/png"

    def test_extract_anthropic_text_with_thinking_block(self):
        """ThinkingBlock 出现在响应中时，应提取 TextBlock 的内容"""
        from app.services.llm import _extract_anthropic_text
        from unittest.mock import MagicMock

        # 简单对象模拟：ThinkingBlock 无 .text，TextBlock 有 .text
        class FakeThinking:
            type = "thinking"
        class FakeText:
            type = "text"
            def __init__(self, t): self.text = t

        resp = MagicMock()
        resp.content = [FakeThinking(), FakeText("你好")]
        assert _extract_anthropic_text(resp) == "你好"

    def test_extract_anthropic_text_single_text(self):
        from app.services.llm import _extract_anthropic_text
        from anthropic.types import TextBlock
        from unittest.mock import MagicMock

        resp = MagicMock()
        resp.content = [TextBlock(type="text", text="OK")]
        assert _extract_anthropic_text(resp) == "OK"


# ─────────────────────────────────────────────────
# 2. OpenAI 格式真实 API 调用
# ─────────────────────────────────────────────────

@pytest.mark.asyncio
@live_llm_required
class TestOpenAIFormat:

    async def test_simple_chat(self):
        """OpenAI /chat/completions 格式文本调用"""
        client = AsyncOpenAI(api_key=API_KEY, base_url=OPENAI_BASE_URL, timeout=30.0)
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个助手，直接回答，不要多余内容"},
                {"role": "user", "content": "回复两个字：你好"}
            ],
            temperature=0.0,
            max_tokens=30,
        )
        text = response.choices[0].message.content.strip()
        print(f"\n[OpenAI 格式] 模型回复: '{text}'")
        # 有些模型可能返回空，但 API 调用成功即算通过
        assert response.choices[0].finish_reason in ("stop", "length"), \
            f"异常 finish_reason: {response.choices[0].finish_reason}"

    async def test_json_response_format(self):
        """OpenAI response_format=json_object"""
        client = AsyncOpenAI(api_key=API_KEY, base_url=OPENAI_BASE_URL, timeout=30.0)
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "严格输出JSON"},
                {"role": "user", "content": '输出 {"ok": true}'}
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=50,
        )
        text = response.choices[0].message.content.strip()
        print(f"\n[OpenAI JSON] 模型回复: {text}")
        assert "{" in text, "JSON 模式返回不含 {"

    async def test_multimodal_openai(self):
        """OpenAI 多模态 — 预期 404（模型不支持图片）"""
        client = AsyncOpenAI(api_key=API_KEY, base_url=OPENAI_BASE_URL, timeout=30.0)
        try:
            response = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "这张图片是什么颜色？只回答颜色。"},
                        {"type": "image_url", "image_url": {"url": TINY_RED_PNG_DATA_URI}},
                    ]
                }],
                temperature=0.0,
                max_tokens=20,
            )
            text = response.choices[0].message.content.strip()
            print(f"\n[OpenAI 多模态] 模型回复: {text}")
            pytest.skip("模型意外支持多模态")
        except Exception as e:
            err_msg = str(e)
            print(f"\n[OpenAI 多模态] 预期报错: {err_msg}")
            assert "image" in err_msg.lower() or "404" in err_msg or "not found" in err_msg.lower(), \
                f"非预期的错误类型: {err_msg}"


# ─────────────────────────────────────────────────
# 3. Anthropic 格式真实 API 调用
# ─────────────────────────────────────────────────

@pytest.mark.asyncio
@live_llm_required
class TestAnthropicFormat:

    async def test_simple_chat(self):
        """Anthropic /v1/messages 格式文本调用"""
        client = AsyncAnthropic(api_key=API_KEY, base_url=ANTHROPIC_BASE_URL, timeout=30.0)
        response = await client.messages.create(
            model=MODEL_NAME,
            max_tokens=30,
            system="你是一个助手，直接回答，不要多余内容",
            messages=[{"role": "user", "content": "回复两个字：你好"}],
            temperature=0.0,
        )
        from app.services.llm import _extract_anthropic_text
        text = _extract_anthropic_text(response)
        print(f"\n[Anthropic 格式] 模型回复: '{text}'")
        print(f"[Anthropic 格式] block types: {[b.type for b in response.content]}")
        assert response.stop_reason in ("end_turn", "max_tokens", "stop_sequence"), \
            f"异常 stop_reason: {response.stop_reason}"

    async def test_multimodal_anthropic(self):
        """Anthropic 多模态 — 预期 404（模型不支持图片）"""
        client = AsyncAnthropic(api_key=API_KEY, base_url=ANTHROPIC_BASE_URL, timeout=30.0)
        try:
            response = await client.messages.create(
                model=MODEL_NAME,
                max_tokens=20,
                system="你是一个助手",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "这张图片是什么颜色？"},
                        {"type": "image", "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": TINY_RED_PNG_B64,
                        }},
                    ]
                }],
                temperature=0.0,
            )
            from app.services.llm import _extract_anthropic_text
            text = _extract_anthropic_text(response)
            print(f"\n[Anthropic 多模态] 模型回复: {text}")
            pytest.skip("模型意外支持多模态")
        except Exception as e:
            err_msg = str(e)
            print(f"\n[Anthropic 多模态] 预期报错: {err_msg}")
            assert "image" in err_msg.lower() or "404" in err_msg or "not found" in err_msg.lower(), \
                f"非预期的错误类型: {err_msg}"


# ─────────────────────────────────────────────────
# 4. 后端 llm.py 封装测试
# ─────────────────────────────────────────────────

@pytest.mark.asyncio
@live_llm_required
class TestBackendLLMWrapper:

    async def test_raw_call_openai(self):
        """raw_llm_call 走当前配置（默认 OpenAI）"""
        from app.services.llm import raw_llm_call
        result = await raw_llm_call(
            user_id=None,
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个助手，直接回答"},
                {"role": "user", "content": "说两个字：OK"}
            ],
            temperature=0.0,
            max_tokens=20,
        )
        print(f"\n[raw_llm_call OpenAI] 回复: '{result}'")
        # API 调用成功即通过，模型可能返回空（属于模型行为）
        assert isinstance(result, str), f"返回类型异常: {type(result)}"

    async def test_call_llm_with_retry(self):
        """_call_llm_with_retry（当前配置）"""
        from app.services.llm import _call_llm_with_retry
        result = await _call_llm_with_retry(
            prompt="请回复：测试成功",
            system_msg="你是一个助手，只回答用户要求的内容",
            user_id=None,
        )
        print(f"\n[_call_llm_with_retry] 回复: '{result}'")
        assert isinstance(result, str)

    async def test_raw_call_anthropic_via_backend(self):
        """raw_llm_call 模拟 Anthropic 配置（临时覆盖全局 client + LLM_BASE_URL）"""
        from app.services.llm import _make_client
        import app.services.llm as llm_mod
        import app.core.config as config_mod

        orig_client = llm_mod.client
        orig_base_url = config_mod.LLM_BASE_URL
        llm_mod.client = _make_client(API_KEY, ANTHROPIC_BASE_URL, 30.0, "anthropic")
        config_mod.LLM_BASE_URL = ANTHROPIC_BASE_URL  # 让 _detect_provider 返回 "anthropic"

        try:
            result = await llm_mod.raw_llm_call(
                user_id=None,
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": "你是一个助手，直接回答"},
                    {"role": "user", "content": "说两个字：OK"}
                ],
                temperature=0.0,
                max_tokens=30,
            )
            print(f"\n[raw_llm_call Anthropic] 回复: '{result}'")
            assert isinstance(result, str), f"返回类型异常: {type(result)}"
        finally:
            llm_mod.client = orig_client
            config_mod.LLM_BASE_URL = orig_base_url
