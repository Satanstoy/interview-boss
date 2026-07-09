"""Verify mechanical question fallback has been removed.

Task 2: 移除机械题干 Fallback
"""


def test_format_bank_question_fallback_removed():
    """机械题干 fallback 应被移除，不存在 _format_bank_question_fallback 函数。"""
    import importlib

    mod = importlib.import_module("app.agents.chat.answer")
    assert not hasattr(mod, "_format_bank_question_fallback"), (
        "_format_bank_question_fallback 已被移除，不应存在"
    )
