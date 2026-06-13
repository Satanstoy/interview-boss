"""测试 LLM tool calling 基础设施（OpenAI / Anthropic 双格式）

纯函数测试不依赖 API，集成测试需要真实 API key。
运行: docker compose exec backend pytest tests/services/test_llm_tool_calling.py -v -s
"""

import json
import pytest
from unittest.mock import MagicMock


# ─────────────────────────────────────────────────
# 1. Tool Schema 转换（纯函数）
# ─────────────────────────────────────────────────


class TestConvertToolsToAnthropic:

    def test_basic_conversion(self):
        from app.services.llm import _convert_tools_to_anthropic

        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_questions",
                    "description": "搜索面试题",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "搜索关键词"},
                        },
                        "required": ["query"],
                    },
                },
            }
        ]
        result = _convert_tools_to_anthropic(openai_tools)

        assert len(result) == 1
        assert result[0]["name"] == "search_questions"
        assert result[0]["description"] == "搜索面试题"
        assert result[0]["input_schema"]["type"] == "object"
        assert "query" in result[0]["input_schema"]["properties"]

    def test_multiple_tools(self):
        from app.services.llm import _convert_tools_to_anthropic

        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "tool_a",
                    "description": "A",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "tool_b",
                    "description": "B",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "string", "enum": ["a", "b"]},
                        },
                        "required": ["x"],
                    },
                },
            },
        ]
        result = _convert_tools_to_anthropic(openai_tools)
        assert len(result) == 2
        assert result[0]["name"] == "tool_a"
        assert result[1]["name"] == "tool_b"
        assert "x" in result[1]["input_schema"]["properties"]
        assert result[1]["input_schema"]["required"] == ["x"]

    def test_empty_tools(self):
        from app.services.llm import _convert_tools_to_anthropic
        assert _convert_tools_to_anthropic([]) == []


# ─────────────────────────────────────────────────
# 2. 消息格式转换（含 tool_calls / tool role）
# ─────────────────────────────────────────────────


class TestConvertMessagesWithTools:

    def test_basic_messages_no_tools(self):
        """没有 tool_calls 的普通消息应该正常转换"""
        from app.services.llm import _convert_messages_with_tools_to_anthropic

        messages = [
            {"role": "system", "content": "你是面试官"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "请介绍一下自己"},
        ]
        system_text, anthropic_msgs = _convert_messages_with_tools_to_anthropic(messages)

        assert system_text == "你是面试官"
        assert len(anthropic_msgs) == 2
        assert anthropic_msgs[0] == {"role": "user", "content": "你好"}
        assert anthropic_msgs[1] == {"role": "assistant", "content": "请介绍一下自己"}

    def test_assistant_with_tool_calls(self):
        """assistant 消息含 tool_calls 应转为 tool_use blocks"""
        from app.services.llm import _convert_messages_with_tools_to_anthropic

        messages = [
            {"role": "system", "content": "你是面试官"},
            {"role": "user", "content": "介绍一下 Redis"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_001",
                        "type": "function",
                        "function": {
                            "name": "search_questions",
                            "arguments": json.dumps({"query": "Redis 缓存"}),
                        },
                    }
                ],
            },
        ]
        system_text, anthropic_msgs = _convert_messages_with_tools_to_anthropic(messages)

        assert len(anthropic_msgs) == 2
        # user message
        assert anthropic_msgs[0]["role"] == "user"
        # assistant message with tool_use
        assistant_msg = anthropic_msgs[1]
        assert assistant_msg["role"] == "assistant"
        assert isinstance(assistant_msg["content"], list)
        assert assistant_msg["content"][0]["type"] == "tool_use"
        assert assistant_msg["content"][0]["id"] == "call_001"
        assert assistant_msg["content"][0]["name"] == "search_questions"
        assert assistant_msg["content"][0]["input"] == {"query": "Redis 缓存"}

    def test_assistant_with_text_and_tool_calls(self):
        """assistant 同时有 text 和 tool_calls"""
        from app.services.llm import _convert_messages_with_tools_to_anthropic

        messages = [
            {
                "role": "assistant",
                "content": "让我搜索一下",
                "tool_calls": [
                    {
                        "id": "call_002",
                        "type": "function",
                        "function": {
                            "name": "draw_questions",
                            "arguments": json.dumps({"count": 3}),
                        },
                    }
                ],
            },
        ]
        _, anthropic_msgs = _convert_messages_with_tools_to_anthropic(messages)

        content = anthropic_msgs[0]["content"]
        assert len(content) == 2
        assert content[0] == {"type": "text", "text": "让我搜索一下"}
        assert content[1]["type"] == "tool_use"
        assert content[1]["name"] == "draw_questions"

    def test_tool_result_message(self):
        """OpenAI role=tool 应转为 Anthropic user message with tool_result block"""
        from app.services.llm import _convert_messages_with_tools_to_anthropic

        messages = [
            {
                "role": "tool",
                "tool_call_id": "call_001",
                "content": '{"questions": [{"id": 1, "question": "什么是缓存穿透"}]}',
            },
        ]
        _, anthropic_msgs = _convert_messages_with_tools_to_anthropic(messages)

        assert len(anthropic_msgs) == 1
        msg = anthropic_msgs[0]
        assert msg["role"] == "user"
        assert isinstance(msg["content"], list)
        assert msg["content"][0]["type"] == "tool_result"
        assert msg["content"][0]["tool_use_id"] == "call_001"
        assert "缓存穿透" in msg["content"][0]["content"]

    def test_full_react_cycle_messages(self):
        """完整的 ReAct 消息序列转换"""
        from app.services.llm import _convert_messages_with_tools_to_anthropic

        messages = [
            {"role": "system", "content": "你是面试官"},
            {"role": "user", "content": "候选人回答了缓存穿透"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_100",
                        "type": "function",
                        "function": {
                            "name": "search_questions",
                            "arguments": json.dumps({"query": "缓存穿透"}),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_100",
                "content": "找到 3 道题",
            },
            {
                "role": "assistant",
                "content": "好的，我来追问一下布隆过滤器的细节。",
            },
        ]
        system_text, anthropic_msgs = _convert_messages_with_tools_to_anthropic(messages)

        assert system_text == "你是面试官"
        assert len(anthropic_msgs) == 4
        # user
        assert anthropic_msgs[0]["role"] == "user"
        # assistant with tool_use
        assert anthropic_msgs[1]["role"] == "assistant"
        assert anthropic_msgs[1]["content"][0]["type"] == "tool_use"
        # tool_result (转为 user)
        assert anthropic_msgs[2]["role"] == "user"
        assert anthropic_msgs[2]["content"][0]["type"] == "tool_result"
        # assistant final
        assert anthropic_msgs[3]["role"] == "assistant"
        assert anthropic_msgs[3]["content"] == "好的，我来追问一下布隆过滤器的细节。"


# ─────────────────────────────────────────────────
# 3. Tool Calls 提取（纯函数 + mock）
# ─────────────────────────────────────────────────


class TestExtractToolCalls:

    def test_openai_with_tool_calls(self):
        from app.services.llm import _extract_tool_calls

        # Mock OpenAI response
        mock_tc = MagicMock()
        mock_tc.id = "call_abc"
        mock_tc.function.name = "search_questions"
        mock_tc.function.arguments = '{"query": "Redis"}'

        mock_msg = MagicMock()
        mock_msg.tool_calls = [mock_tc]

        mock_choice = MagicMock()
        mock_choice.message = mock_msg

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        result = _extract_tool_calls(mock_response, "openai")
        assert result is not None
        assert len(result) == 1
        assert result[0]["id"] == "call_abc"
        assert result[0]["function"]["name"] == "search_questions"
        assert result[0]["function"]["arguments"] == '{"query": "Redis"}'

    def test_openai_without_tool_calls(self):
        from app.services.llm import _extract_tool_calls

        mock_msg = MagicMock()
        mock_msg.tool_calls = None

        mock_choice = MagicMock()
        mock_choice.message = mock_msg

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        result = _extract_tool_calls(mock_response, "openai")
        assert result is None

    def test_anthropic_with_tool_use(self):
        from app.services.llm import _extract_tool_calls

        # Mock Anthropic response with tool_use block
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.id = "toolu_001"
        mock_tool_block.name = "draw_questions"
        mock_tool_block.input = {"count": 3}

        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "让我抽题"
        # text blocks don't have type == "tool_use"
        del mock_text_block.type
        mock_text_block.text = "让我抽题"
        # Recreate properly
        mock_text_block = MagicMock(spec=["type", "text"])
        mock_text_block.type = "text"
        mock_text_block.text = "让我抽题"

        mock_response = MagicMock()
        mock_response.content = [mock_text_block, mock_tool_block]

        result = _extract_tool_calls(mock_response, "anthropic")
        assert result is not None
        assert len(result) == 1
        assert result[0]["id"] == "toolu_001"
        assert result[0]["function"]["name"] == "draw_questions"
        assert json.loads(result[0]["function"]["arguments"]) == {"count": 3}

    def test_anthropic_without_tool_use(self):
        from app.services.llm import _extract_tool_calls

        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "直接回答"

        mock_response = MagicMock()
        mock_response.content = [mock_text_block]

        result = _extract_tool_calls(mock_response, "anthropic")
        assert result is None

    def test_anthropic_multiple_tool_calls(self):
        from app.services.llm import _extract_tool_calls

        blocks = []
        for i, name in enumerate(["search_questions", "load_skill"]):
            b = MagicMock()
            b.type = "tool_use"
            b.id = f"toolu_{i}"
            b.name = name
            b.input = {"param": i}
            blocks.append(b)

        mock_response = MagicMock()
        mock_response.content = blocks

        result = _extract_tool_calls(mock_response, "anthropic")
        assert result is not None
        assert len(result) == 2
        assert result[0]["function"]["name"] == "search_questions"
        assert result[1]["function"]["name"] == "load_skill"


# ─────────────────────────────────────────────────
# 4. make_tool_result_message 辅助函数
# ─────────────────────────────────────────────────


class TestMakeToolResultMessage:

    def test_basic(self):
        from app.services.llm import make_tool_result_message

        msg = make_tool_result_message("call_001", '{"result": "ok"}')
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "call_001"
        assert msg["content"] == '{"result": "ok"}'


# ─────────────────────────────────────────────────
# 5. llm_with_tools 集成测试（需要真实 API）
# ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLLMWithToolsIntegration:

    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取指定城市的天气",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名称"},
                    },
                    "required": ["city"],
                },
            },
        }
    ]

    async def test_llm_with_tools_returns_tool_call(self):
        """LLM 应该返回 tool_calls 而不是直接回答"""
        from app.services.llm import llm_with_tools

        result = await llm_with_tools(
            messages=[
                {"role": "system", "content": "你是一个天气助手，使用工具回答问题。"},
                {"role": "user", "content": "北京今天天气怎么样？"},
            ],
            tools=self.TOOLS,
            user_id=None,
        )

        print(f"\n[llm_with_tools] result: {result}")
        # LLM 应该调用 get_weather 工具
        assert result["tool_calls"] is not None, "LLM 应该返回 tool_calls"
        assert result["finish_reason"] == "tool_calls"
        tc = result["tool_calls"][0]
        assert tc["function"]["name"] == "get_weather"
        city = json.loads(tc["function"]["arguments"]).get("city", "")
        assert "北京" in city or "beijing" in city.lower()

    async def test_llm_with_tools_no_tools_returns_text(self):
        """不传 tools 时，LLM 应该直接返回文本"""
        from app.services.llm import llm_with_tools

        result = await llm_with_tools(
            messages=[
                {"role": "system", "content": "你是一个助手，直接回答。"},
                {"role": "user", "content": "回复两个字：你好"},
            ],
            tools=[],
            user_id=None,
        )

        print(f"\n[llm_with_tools no tools] result: {result}")
        assert result["tool_calls"] is None
        assert result["content"] is not None

    async def test_llm_with_tools_full_react_cycle(self):
        """模拟完整的 ReAct 循环：LLM 调工具 → 执行 → 回传结果 → 生成回复"""
        from app.services.llm import llm_with_tools, make_tool_result_message

        messages = [
            {"role": "system", "content": "你是一个天气助手。用工具获取天气后，用一句话回答用户。"},
            {"role": "user", "content": "上海天气怎么样？"},
        ]

        # Step 1: LLM 决定调工具
        result1 = await llm_with_tools(messages=messages, tools=self.TOOLS, user_id=None)
        print(f"\n[Step 1] tool_calls: {result1['tool_calls']}")

        assert result1["tool_calls"] is not None, "Step 1: LLM 应该调用工具"
        tool_call = result1["tool_calls"][0]
        tool_call_id = tool_call["id"]

        # Step 2: 模拟工具执行结果，回传给 LLM
        messages.append({
            "role": "assistant",
            "content": result1.get("content"),
            "tool_calls": result1["tool_calls"],
        })
        messages.append(make_tool_result_message(
            tool_call_id,
            json.dumps({"city": "上海", "temp": "28°C", "weather": "晴"}, ensure_ascii=False),
        ))

        # Step 3: LLM 拿到工具结果后生成最终回复
        result2 = await llm_with_tools(messages=messages, tools=self.TOOLS, user_id=None)
        print(f"[Step 3] content: {result2['content']}")

        assert result2["content"] is not None, "Step 3: LLM 应该生成文本回复"
        assert result2["tool_calls"] is None, "Step 3: 不应该再调工具"
        assert "28" in result2["content"] or "晴" in result2["content"], \
            f"回复应包含天气数据: {result2['content']}"
