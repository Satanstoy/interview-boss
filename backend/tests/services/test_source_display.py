"""
自动化测试 — 针对 BUG-001: 来源详情显示不一致
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _get_single_source_section():
    """提取 Single-question sources 部分"""
    with open(BACKEND_ROOT / 'frontend/src/components/business/QuestionCard.vue', 'r', encoding='utf-8') as f:
        content = f.read()
    idx = content.find('Single-question sources')
    assert idx != -1, "应存在 Single-question sources 注释"
    # 找到该部分的结束标记
    end_idx = content.find('</template>', idx + 100)
    return content[idx:end_idx]


def _get_multi_source_section():
    """提取 Multi-question cluster 部分"""
    with open(BACKEND_ROOT / 'frontend/src/components/business/QuestionCard.vue', 'r', encoding='utf-8') as f:
        content = f.read()
    idx = content.find('Multi-question cluster')
    end_idx = content.find('Single-question sources')
    return content[idx:end_idx]


class TestBug001SourceDisplayConsistency:
    """BUG-001: 高频题库来源详情显示不一致"""

    def test_single_source_entry_has_card_structure(self):
        """修复后：Single-question sources 应使用卡片布局"""
        section = _get_single_source_section()
        assert '<template v-else-if="question.sources' in section, "应使用 template 包裹"
        assert 'bg-surface-50' in section, "应使用卡片背景色"
        assert 'rounded-xl' in section, "应使用圆角卡片"
        assert 'flex items-start gap-3' in section, "应使用 flex 布局"

    def test_single_source_entry_has_index(self):
        """修复后：每个来源应有编号"""
        section = _get_single_source_section()
        assert '{{ idx + 1 }}.' in section, "应显示序号"

    def test_single_source_entry_has_split_button(self):
        """修复后：应有独立按钮"""
        section = _get_single_source_section()
        assert 'split-question' in section, "应有 split-question 事件"
        assert '独立' in section, "应有独立按钮文字"

    def test_single_source_entry_has_merge_button(self):
        """修复后：应有合并到按钮"""
        section = _get_single_source_section()
        assert 'start-merge' in section, "应有 start-merge 事件"
        assert '合并到' in section, "应有合并到按钮文字"

    def test_single_source_entry_has_navigate_link(self):
        """修复后：应有跳转面经的链接"""
        section = _get_single_source_section()
        assert 'navigate-to-interview' in section, "应有跳转面经事件"
        assert '[原文]' in section, "应有原文链接"

    def test_single_source_entry_not_flat_inline(self):
        """修复后：不应使用旧的扁平 inline-flex 标签布局"""
        section = _get_single_source_section()
        assert 'px-2 py-1 rounded-md inline-flex' not in section, "不应使用旧的扁平标签布局"

    def test_both_sections_use_consistent_style(self):
        """两个来源部分应使用一致的卡片样式"""
        multi = _get_multi_source_section()
        single = _get_single_source_section()

        assert 'bg-surface-50 dark:bg-surface-700' in multi
        assert 'bg-surface-50 dark:bg-surface-700' in single, "应与 Multi-question 使用相同卡片样式"
        assert 'split-question' in multi
        assert 'split-question' in single, "应与 Multi-question 一样有独立按钮"
