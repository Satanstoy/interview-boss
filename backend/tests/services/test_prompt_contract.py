from app.core.prompts import ANSWER_PROMPT, RECITATION_PROMPT


def test_reference_answer_prompt_requires_scan_friendly_markdown():
    assert "必须使用 Markdown 三级标题和列表" in ANSWER_PROMPT
    assert "### 一句话记忆" in ANSWER_PROMPT
    assert "不能编造公司" in ANSWER_PROMPT
    assert "Markdown 链接" in ANSWER_PROMPT


def test_recitation_prompt_preserves_truth_and_readable_structure():
    assert "使用 Markdown 三级标题和列表" in RECITATION_PROMPT
    assert "不得为了“个性化”编造" in RECITATION_PROMPT
    assert "最多不超过 520" in RECITATION_PROMPT
