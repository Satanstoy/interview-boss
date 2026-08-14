"""
自动化测试 — 针对 BUG-001: 来源详情显示不一致
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _get_single_source_section():
    """提取当前来源详情渲染部分"""
    with open(BACKEND_ROOT.parent / 'frontend/src/components/business/QuestionCard.vue', 'r', encoding='utf-8') as f:
        content = f.read()
    idx = content.find('v-for="(src, idx) in dedupedSources"')
    assert idx != -1, "应存在 dedupedSources 来源渲染"
    # 找到该部分的结束标记
    end_idx = content.find('</template>', idx + 100)
    return content[idx:end_idx]


def _get_multi_source_section():
    """提取来源详情容器部分"""
    with open(BACKEND_ROOT.parent / 'frontend/src/components/business/QuestionCard.vue', 'r', encoding='utf-8') as f:
        content = f.read()
    idx = content.find('来源详情')
    end_idx = content.find('</template>', idx)
    return content[idx:end_idx]


class TestBug001SourceDisplayConsistency:
    """BUG-001: 高频题库来源详情显示不一致"""

    def test_single_source_entry_has_card_structure(self):
        """修复后：Single-question sources 应使用卡片布局"""
        section = _get_single_source_section()
        assert 'v-for="(src, idx) in dedupedSources"' in section, "应统一遍历去重来源"
        assert 'bg-card' in section, "应使用卡片背景色"
        assert 'rounded-md' in section, "应使用圆角卡片"
        assert 'flex items-start gap-2.5' in section, "应使用 flex 布局（卡片内来源项布局）"

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

        assert 'bg-card' in multi
        assert 'bg-card' in single, "来源详情应使用统一卡片样式"
        assert 'split-question' in multi
        assert 'split-question' in single, "应与 Multi-question 一样有独立按钮"
