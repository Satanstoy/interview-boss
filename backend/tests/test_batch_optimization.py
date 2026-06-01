"""
测试优化 2：增大 batch size（降本）

测试目标：
1. _merge_small_groups 函数正确合并小组
2. 合并后的 batch 不超过 MAX_BATCH_SIZE
3. 跨 cat2 合并时包含 cat2 信息
"""
import pytest
from typing import List, Dict

# 常量
MAX_BATCH_SIZE = 80


# ──────────────────────────── 模拟的函数实现 ────────────────────────────

def mock_merge_small_groups(cat2_groups: Dict[str, List[Dict]], max_size: int = MAX_BATCH_SIZE) -> List[Dict]:
    """模拟：贪心合并小组，直到总量接近 max_size"""
    merged_batches = []
    current_batch = []
    current_cats = []
    
    # 按组大小降序排列（大组优先）
    sorted_groups = sorted(cat2_groups.items(), key=lambda x: len(x[1]), reverse=True)
    
    for cat2, group in sorted_groups:
        if len(current_batch) + len(group) <= max_size:
            current_batch.extend(group)
            current_cats.append(cat2)
        else:
            if current_batch:
                merged_batches.append({
                    "items": current_batch,
                    "cat2s": current_cats
                })
            current_batch = list(group)
            current_cats = [cat2]
    
    if current_batch:
        merged_batches.append({
            "items": current_batch,
            "cat2s": current_cats
        })
    
    return merged_batches


# ──────────────────────────── 测试用例 ────────────────────────────

class TestMergeSmallGroups:
    """测试 _merge_small_groups 函数"""

    def test_merge_small_groups_basic(self):
        """测试：基本合并逻辑"""
        # 准备：两个小组，总数 < 80
        cat2_groups = {
            "A": [{"id": i, "question": f"Q{i}"} for i in range(10)],
            "B": [{"id": i+100, "question": f"Q{i+100}"} for i in range(5)],
        }

        # 执行
        result = mock_merge_small_groups(cat2_groups)

        # 验证：两个组应该合并成一个 batch（10 + 5 = 15 < 80）
        assert len(result) == 1
        assert len(result[0]["items"]) == 15
        assert set(result[0]["cat2s"]) == {"A", "B"}

    def test_merge_small_groups_respects_max_size(self):
        """测试：合并后的 batch 不超过 MAX_BATCH_SIZE"""
        # 准备：两个组，总数 > 80
        cat2_groups = {
            "A": [{"id": i, "question": f"Q{i}"} for i in range(50)],
            "B": [{"id": i+100, "question": f"Q{i+100}"} for i in range(40)],
        }

        # 执行
        result = mock_merge_small_groups(cat2_groups)

        # 验证：50 + 40 = 90 > 80，应该分成两个 batch
        assert len(result) == 2
        assert len(result[0]["items"]) == 50
        assert result[0]["cat2s"] == ["A"]
        assert len(result[1]["items"]) == 40
        assert result[1]["cat2s"] == ["B"]

    def test_merge_small_groups_greedy(self):
        """测试：贪心策略 - 优先合并大组"""
        # 准备：三个组，A(50) + B(40) = 90 > 80，不能合并；C(30) 单独
        cat2_groups = {
            "A": [{"id": i, "question": f"Q{i}"} for i in range(50)],
            "B": [{"id": i+100, "question": f"Q{i+100}"} for i in range(40)],
            "C": [{"id": i+200, "question": f"Q{i+200}"} for i in range(30)],
        }

        # 执行
        result = mock_merge_small_groups(cat2_groups)

        # 验证：50 + 40 = 90 > 80，不能合并；40 + 30 = 70 <= 80，可以合并
        assert len(result) == 2
        # 第一个 batch：A（50）
        assert len(result[0]["items"]) == 50
        assert result[0]["cat2s"] == ["A"]
        # 第二个 batch：B + C（40 + 30 = 70）
        assert len(result[1]["items"]) == 70
        assert set(result[1]["cat2s"]) == {"B", "C"}

    def test_merge_small_groups_single_large_group(self):
        """测试：单个大组不合并"""
        # 准备：一个大组
        cat2_groups = {
            "A": [{"id": i, "question": f"Q{i}"} for i in range(100)],
        }

        # 执行
        result = mock_merge_small_groups(cat2_groups)

        # 验证：100 > 80，单独一个 batch
        assert len(result) == 1
        assert len(result[0]["items"]) == 100
        assert result[0]["cat2s"] == ["A"]

    def test_merge_small_groups_multiple_small_groups(self):
        """测试：多个小组合并"""
        # 准备：四个组
        cat2_groups = {
            "A": [{"id": i, "question": f"Q{i}"} for i in range(10)],
            "B": [{"id": i+100, "question": f"Q{i+100}"} for i in range(15)],
            "C": [{"id": i+200, "question": f"Q{i+200}"} for i in range(20)],
            "D": [{"id": i+300, "question": f"Q{i+300}"} for i in range(25)],
        }

        # 执行
        result = mock_merge_small_groups(cat2_groups)

        # 验证：25 + 20 + 15 + 10 = 70 < 80，全部合并
        assert len(result) == 1
        assert len(result[0]["items"]) == 70
        assert set(result[0]["cat2s"]) == {"A", "B", "C", "D"}

    def test_merge_small_groups_empty_groups(self):
        """测试：空组处理"""
        # 准备：空字典
        cat2_groups = {}

        # 执行
        result = mock_merge_small_groups(cat2_groups)

        # 验证：返回空列表
        assert result == []

    def test_merge_small_groups_custom_max_size(self):
        """测试：自定义 max_size"""
        # 准备：两个组
        cat2_groups = {
            "A": [{"id": i, "question": f"Q{i}"} for i in range(30)],
            "B": [{"id": i+100, "question": f"Q{i+100}"} for i in range(20)],
        }

        # 执行：使用较小的 max_size
        result = mock_merge_small_groups(cat2_groups, max_size=40)

        # 验证：30 + 20 = 50 > 40，应该分成两个 batch
        assert len(result) == 2
        assert len(result[0]["items"]) == 30
        assert len(result[1]["items"]) == 20

    def test_merge_small_groups_preserves_item_data(self):
        """测试：合并后保留原始数据"""
        # 准备：两个组
        cat2_groups = {
            "A": [
                {"id": 1, "question": "Q1", "cat2": "A"},
                {"id": 2, "question": "Q2", "cat2": "A"},
            ],
            "B": [
                {"id": 3, "question": "Q3", "cat2": "B"},
            ],
        }

        # 执行
        result = mock_merge_small_groups(cat2_groups)

        # 验证：数据完整保留
        assert len(result) == 1
        items = result[0]["items"]
        assert len(items) == 3
        assert items[0]["id"] == 1
        assert items[1]["id"] == 2
        assert items[2]["id"] == 3


class TestIntegration:
    """集成测试"""

    def test_realistic_scenario(self):
        """测试：真实场景 - 23 个 cat2 分组"""
        # 准备：模拟真实数据分布
        cat2_groups = {
            "B2.RAG系统设计": [{"id": i, "question": f"Q{i}"} for i in range(16)],
            "B1.Agent架构与范式": [{"id": i, "question": f"Q{i}"} for i in range(100, 114)],
            "C2.框架与中间件": [{"id": i, "question": f"Q{i}"} for i in range(200, 211)],
            "B6.评估安全与优化": [{"id": i, "question": f"Q{i}"} for i in range(300, 307)],
            "C3.数据库基础": [{"id": i, "question": f"Q{i}"} for i in range(400, 406)],
            "E1.算法手撕与数据结构": [{"id": i, "question": f"Q{i}"} for i in range(500, 506)],
            "B3.工具调用与协议集成": [{"id": i, "question": f"Q{i}"} for i in range(600, 605)],
            "B7.AI Coding与代码智能": [{"id": i, "question": f"Q{i}"} for i in range(700, 705)],
            "其他": [{"id": i, "question": f"Q{i}"} for i in range(800, 805)],
            "C1.编程语言基础": [{"id": i, "question": f"Q{i}"} for i in range(900, 904)],
            "B8.模型与框架选型": [{"id": i, "question": f"Q{i}"} for i in range(1000, 1004)],
            "A1.项目介绍与背景": [{"id": i, "question": f"Q{i}"} for i in range(1100, 1104)],
            "B4.记忆与上下文管理": [{"id": i, "question": f"Q{i}"} for i in range(1200, 1203)],
            "D2.高并发与限流": [{"id": i, "question": f"Q{i}"} for i in range(1300, 1303)],
            "D1.缓存设计与优化": [{"id": i, "question": f"Q{i}"} for i in range(1400, 1403)],
            "A2.系统架构设计": [{"id": i, "question": f"Q{i}"} for i in range(1500, 1502)],
            "A4.反思与改进": [{"id": i, "question": f"Q{i}"} for i in range(1600, 1602)],
            "B5.Prompt工程": [{"id": i, "question": f"Q{i}"} for i in range(1700, 1701)],
            "C4.操作系统与网络": [{"id": i, "question": f"Q{i}"} for i in range(1800, 1801)],
            "A3.难点攻关与优化": [{"id": i, "question": f"Q{i}"} for i in range(1900, 1901)],
        }

        # 执行
        result = mock_merge_small_groups(cat2_groups)

        # 验证：所有 batch 都不超过 MAX_BATCH_SIZE
        for batch in result:
            assert len(batch["items"]) <= MAX_BATCH_SIZE

        # 统计
        total_items = sum(len(batch["items"]) for batch in result)
        original_items = sum(len(group) for group in cat2_groups.values())
        assert total_items == original_items

        # 打印统计
        print(f"\n原始分组数: {len(cat2_groups)}")
        print(f"合并后 batch 数: {len(result)}")
        print(f"每个 batch 的题目数: {[len(b['items']) for b in result]}")
        print(f"每个 batch 的 cat2 数: {[len(b['cat2s']) for b in result]}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
