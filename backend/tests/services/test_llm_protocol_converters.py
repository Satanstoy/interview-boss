"""三种协议的纯转换/响应归一化契约测试。"""


def test_responses_input_preserves_text_and_image_parts():
    from app.services.llm import _convert_messages_to_responses_input

    items = _convert_messages_to_responses_input(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看这张图"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AAA", "detail": "high"},
                    },
                ],
            }
        ]
    )

    assert items == [
        {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": "看这张图"},
                {"type": "input_image", "image_url": "data:image/png;base64,AAA", "detail": "high"},
            ],
        }
    ]


def test_anthropic_text_extraction_concatenates_all_text_blocks():
    from app.services.llm import _extract_anthropic_text

    class Block:
        def __init__(self, block_type, text=None):
            self.type = block_type
            self.text = text

    response = type(
        "Response",
        (),
        {"content": [Block("text", "前半"), Block("tool_use"), Block("text", "后半")]},
    )()

    assert _extract_anthropic_text(response) == "前半后半"


def test_responses_tool_call_usage_is_normalized():
    from app.services.llm import normalize_cache_usage

    usage = type(
        "Usage",
        (),
        {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "input_tokens_details": type("Details", (), {"cached_tokens": 80})(),
        },
    )()

    assert normalize_cache_usage(usage) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "cached_input_tokens": 80,
        "cache_write_input_tokens": None,
        "cache_read_input_tokens": None,
    }
