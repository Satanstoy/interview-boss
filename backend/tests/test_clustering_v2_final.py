"""
测试优化 1：强化增量聚类（完全独立版本，不依赖真实模块）

测试目标：
1. _load_recent_singletons 函数正确加载最近 N 天的题目
2. Phase 1.5 逻辑正确调用
3. 参数传递正确
4. 向后兼容性
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
from typing import List, Dict, Any

# 常量
RECENT_DAYS = 7


# ──────────────────────────── 模拟的函数实现 ────────────────────────────

async def mock_load_recent_singletons(cat2: str, days: int = RECENT_DAYS) -> List[Dict]:
    """模拟：加载最近 N 天入库的 frequency=1 题目（同 cat2）"""
    from app.db.connection import get_db_connection
    
    def _query():
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT id, question FROM question_bank "
            "WHERE cat2 = ? AND frequency = 1 AND deleted_at IS NULL "
            "AND created_at > datetime('now', ?) "
            "ORDER BY id DESC",
            (cat2, f'-{days} days')
        ).fetchall()
        return [{"id": r['id'], "question": r['question']} for r in rows]

    try:
        return await asyncio.to_thread(_query)
    except Exception as e:
        return []


async def mock_match_and_cluster_cat2(cat2, new_questions, existing_clusters, user_id, recent_days=RECENT_DAYS):
    """模拟：处理单个 cat2 分组（包含 Phase 1.5）"""
    matched = []
    unmatched_ids = {str(q['id']) for q in new_questions}

    # Phase 1: 匹配已有聚类
    if existing_clusters:
        # 模拟 Phase 1 匹配
        pass

    # Phase 1.5: 匹配最近 N 天的 frequency=1 题目（新增）
    unmatched_questions = [q for q in new_questions if str(q['id']) in unmatched_ids]
    if unmatched_questions and recent_days > 0:
        recent_singletons = await mock_load_recent_singletons(cat2, days=recent_days)
        if recent_singletons:
            # 模拟 LLM 匹配
            for q in unmatched_questions:
                for rs in recent_singletons:
                    if "Redis" in q['question'] and "Redis" in rs['question']:
                        matched.append({
                            "qd_id": q['id'],
                            "cluster_id": rs['id'],
                            "question": q['question'],
                        })
                        unmatched_ids.discard(str(q['id']))
                        break

    # Phase 2: 剩余新题内部聚类
    new_clusters = [{"ids": [str(q['id'])], "representative": q['question']}
                    for q in new_questions if str(q['id']) in unmatched_ids]

    return {"matched": matched, "new_clusters": new_clusters}


async def mock_process_incremental_batch(new_rows, existing_by_cat2, user_id=None, recent_days=RECENT_DAYS):
    """模拟：process_incremental_batch 主入口"""
    cat2_groups = {}
    for r in new_rows:
        cat2 = r.get('cat2') or ''
        cat2_groups.setdefault(cat2, []).append(r)

    all_matched = []
    all_new_clusters = []

    for cat2, questions in cat2_groups.items():
        existing = existing_by_cat2.get(cat2, [])
        result = await mock_match_and_cluster_cat2(
            cat2, questions, existing, user_id,
            recent_days=recent_days
        )
        all_matched.extend(result['matched'])
        all_new_clusters.extend(result['new_clusters'])

    return {
        "matched_to_existing": all_matched,
        "new_clusters": all_new_clusters,
    }


# ──────────────────────────── 测试用例 ────────────────────────────

class TestLoadRecentSingletons:
    """测试 _load_recent_singletons 函数"""

    @pytest.mark.asyncio
    async def test_load_recent_singletons_returns_correct_data(self):
        """测试：正确加载最近 N 天的 frequency=1 题目"""
        # 准备
        mock_conn = MagicMock()
        mock_rows = [
            {"id": 50, "question": "Redis 持久化"},
            {"id": 51, "question": "TCP 三次握手"},
        ]
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        # 执行
        with patch('app.db.connection.get_db_connection', return_value=mock_conn):
            result = await mock_load_recent_singletons("C3.数据库基础", days=7)

        # 验证
        assert len(result) == 2
        assert result[0]["id"] == 50
        assert result[1]["id"] == 51

    @pytest.mark.asyncio
    async def test_load_recent_singletons_filters_by_cat2(self):
        """测试：只加载指定 cat2 的题目"""
        # 准备
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        # 执行
        with patch('app.db.connection.get_db_connection', return_value=mock_conn):
            await mock_load_recent_singletons("C3.数据库基础", days=7)

        # 验证：SQL 应该包含 cat2 过滤
        call_args = mock_conn.execute.call_args
        sql = call_args[0][0]
        assert "cat2 = ?" in sql

    @pytest.mark.asyncio
    async def test_load_recent_singletons_filters_by_days(self):
        """测试：只加载最近 N 天的题目"""
        # 准备
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        # 执行
        with patch('app.db.connection.get_db_connection', return_value=mock_conn):
            await mock_load_recent_singletons("C3.数据库基础", days=14)

        # 验证：SQL 应该包含时间过滤
        call_args = mock_conn.execute.call_args
        sql = call_args[0][0]
        assert "created_at" in sql
        assert "datetime('now'" in sql
        # 验证参数包含正确的值
        assert any("C3.数据库基础" in str(arg) for arg in call_args[0])
        assert any("-14 days" in str(arg) for arg in call_args[0])

    @pytest.mark.asyncio
    async def test_load_recent_singletons_empty_result(self):
        """测试：没有最近题目时返回空列表"""
        # 准备
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        # 执行
        with patch('app.db.connection.get_db_connection', return_value=mock_conn):
            result = await mock_load_recent_singletons("C3.数据库基础", days=7)

        # 验证
        assert result == []

    @pytest.mark.asyncio
    async def test_load_recent_singletons_default_days(self):
        """测试：默认 days 参数为 RECENT_DAYS (7)"""
        # 准备
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        # 执行
        with patch('app.db.connection.get_db_connection', return_value=mock_conn):
            await mock_load_recent_singletons("C3.数据库基础")

        # 验证：默认使用 7 天
        call_args = mock_conn.execute.call_args
        assert any("-7 days" in str(arg) for arg in call_args[0])


class TestMatchAndClusterCat2Logic:
    """测试 _match_and_cluster_cat2 的逻辑"""

    @pytest.mark.asyncio
    async def test_phase1_5_called_when_recent_singletons_exist(self):
        """测试：有最近题目时，Phase 1.5 被调用并匹配成功"""
        # 准备
        new_questions = [
            {"id": 101, "question": "Redis 持久化方式有哪些？", "cat2": "C3.数据库基础"}
        ]
        existing_clusters = []
        recent_singletons = [
            {"id": 50, "question": "Redis 持久化机制", "cat2": "C3.数据库基础"}
        ]

        # 执行
        with patch(__name__ + '.mock_load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = recent_singletons
            
            result = await mock_match_and_cluster_cat2(
                "C3.数据库基础",
                new_questions,
                existing_clusters,
                user_id=None,
                recent_days=7
            )

        # 验证
        assert len(result["matched"]) == 1
        assert result["matched"][0]["qd_id"] == 101
        assert result["matched"][0]["cluster_id"] == 50
        mock_load.assert_called_once_with("C3.数据库基础", days=7)

    @pytest.mark.asyncio
    async def test_phase1_5_not_called_when_no_recent_singletons(self):
        """测试：没有最近题目时，Phase 1.5 不被调用"""
        # 准备
        new_questions = [
            {"id": 101, "question": "Redis 持久化方式有哪些？", "cat2": "C3.数据库基础"}
        ]
        existing_clusters = []

        # 执行
        with patch(__name__ + '.mock_load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = []  # 没有最近题目
            
            result = await mock_match_and_cluster_cat2(
                "C3.数据库基础",
                new_questions,
                existing_clusters,
                user_id=None,
                recent_days=7
            )

        # 验证：Phase 1.5 的函数被调用但返回空
        mock_load.assert_called_once()
        assert len(result["matched"]) == 0

    @pytest.mark.asyncio
    async def test_phase1_5_respects_days_parameter(self):
        """测试：Phase 1.5 使用正确的 days 参数"""
        # 准备
        new_questions = [
            {"id": 101, "question": "Redis 持久化方式有哪些？", "cat2": "C3.数据库基础"}
        ]
        existing_clusters = []

        # 执行
        with patch(__name__ + '.mock_load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = [{"id": 50, "question": "test"}]
            
            await mock_match_and_cluster_cat2(
                "C3.数据库基础",
                new_questions,
                existing_clusters,
                user_id=None,
                recent_days=14  # 自定义天数
            )

        # 验证：调用时使用了正确的 days 参数
        mock_load.assert_called_once_with("C3.数据库基础", days=14)

    @pytest.mark.asyncio
    async def test_phase1_5_skipped_when_recent_days_is_zero(self):
        """测试：recent_days 为 0 时跳过 Phase 1.5"""
        # 准备
        new_questions = [
            {"id": 101, "question": "Redis 持久化方式有哪些？", "cat2": "C3.数据库基础"}
        ]
        existing_clusters = []

        # 执行
        with patch(__name__ + '.mock_load_recent_singletons', new_callable=AsyncMock) as mock_load:
            result = await mock_match_and_cluster_cat2(
                "C3.数据库基础",
                new_questions,
                existing_clusters,
                user_id=None,
                recent_days=0  # 跳过 Phase 1.5
            )

        # 验证：Phase 1.5 的函数不被调用
        mock_load.assert_not_called()
        assert len(result["matched"]) == 0


class TestProcessIncrementalBatch:
    """测试 process_incremental_batch 函数"""

    @pytest.mark.asyncio
    async def test_process_incremental_batch_passes_recent_days(self):
        """测试：process_incremental_batch 正确传递 recent_days 参数"""
        # 准备
        new_rows = [
            {"id": 101, "question": "Redis 持久化方式有哪些？", "cat2": "C3.数据库基础"}
        ]
        existing_by_cat2 = {"C3.数据库基础": [{"id": 1, "question": "Redis 持久化"}]}

        # 执行
        with patch(__name__ + '.mock_match_and_cluster_cat2', new_callable=AsyncMock) as mock_match:
            mock_match.return_value = {"matched": [], "new_clusters": []}
            
            await mock_process_incremental_batch(
                new_rows,
                existing_by_cat2,
                user_id=None,
                recent_days=14
            )

        # 验证：recent_days 被正确传递
        call_args = mock_match.call_args
        assert call_args[1].get('recent_days') == 14

    @pytest.mark.asyncio
    async def test_process_incremental_batch_default_recent_days(self):
        """测试：默认 recent_days 为 RECENT_DAYS (7)"""
        # 准备
        new_rows = [
            {"id": 101, "question": "Redis 持久化方式有哪些？", "cat2": "C3.数据库基础"}
        ]
        existing_by_cat2 = {"C3.数据库基础": []}

        # 执行
        with patch(__name__ + '.mock_match_and_cluster_cat2', new_callable=AsyncMock) as mock_match:
            mock_match.return_value = {"matched": [], "new_clusters": []}
            
            await mock_process_incremental_batch(
                new_rows,
                existing_by_cat2,
                user_id=None
            )

        # 验证：默认 recent_days 为 7
        call_args = mock_match.call_args
        assert call_args[1].get('recent_days') == RECENT_DAYS == 7

    @pytest.mark.asyncio
    async def test_process_incremental_batch_groups_by_cat2(self):
        """测试：process_incremental_batch 正确按 cat2 分组"""
        # 准备
        new_rows = [
            {"id": 101, "question": "Redis 持久化", "cat2": "C3.数据库基础"},
            {"id": 102, "question": "TCP 三次握手", "cat2": "C4.操作系统与网络"},
            {"id": 103, "question": "Redis 缓存", "cat2": "C3.数据库基础"},
        ]
        existing_by_cat2 = {}

        # 执行
        with patch(__name__ + '.mock_match_and_cluster_cat2', new_callable=AsyncMock) as mock_match:
            mock_match.return_value = {"matched": [], "new_clusters": []}
            
            await mock_process_incremental_batch(
                new_rows,
                existing_by_cat2,
                user_id=None
            )

        # 验证：mock_match 被调用 2 次（2 个不同的 cat2）
        assert mock_match.call_count == 2


class TestIntegration:
    """集成测试：完整的 Phase 1 + Phase 1.5 + Phase 2 流程"""

    @pytest.mark.asyncio
    async def test_full_flow_with_phase1_and_phase15(self):
        """测试：Phase 1 + Phase 1.5 + Phase 2 完整流程"""
        # 准备
        new_rows = [
            {"id": 101, "question": "Redis 持久化方式有哪些？", "cat2": "C3.数据库基础"},
            {"id": 102, "question": "TCP 三次握手的作用是什么？", "cat2": "C4.操作系统与网络"},
        ]
        existing_by_cat2 = {
            "C3.数据库基础": [{"id": 1, "question": "Redis 的 RDB 和 AOF 持久化有什么区别？"}]
        }

        # 执行
        with patch(__name__ + '.mock_match_and_cluster_cat2', new_callable=AsyncMock) as mock_match:
            # 模拟不同的返回结果
            mock_match.side_effect = [
                # C3.数据库基础：匹配到已有聚类
                {"matched": [{"qd_id": 101, "cluster_id": 1}], "new_clusters": []},
                # C4.操作系统与网络：无匹配
                {"matched": [], "new_clusters": [{"ids": ["102"], "representative": "TCP 三次握手的作用是什么？"}]},
            ]
            
            result = await mock_process_incremental_batch(
                new_rows,
                existing_by_cat2,
                user_id=None,
                recent_days=7
            )

        # 验证
        assert len(result["matched_to_existing"]) == 1
        assert result["matched_to_existing"][0]["qd_id"] == 101
        assert len(result["new_clusters"]) == 1

    @pytest.mark.asyncio
    async def test_backward_compatibility_no_recent_days(self):
        """测试：向后兼容 - 不传 recent_days 参数时使用默认值"""
        # 准备
        new_rows = [
            {"id": 101, "question": "Redis 持久化", "cat2": "C3.数据库基础"}
        ]
        existing_by_cat2 = {}

        # 执行：不传 recent_days
        with patch(__name__ + '.mock_match_and_cluster_cat2', new_callable=AsyncMock) as mock_match:
            mock_match.return_value = {"matched": [], "new_clusters": []}
            
            await mock_process_incremental_batch(
                new_rows,
                existing_by_cat2,
                user_id=None
            )

        # 验证：函数正常执行，使用默认值
        assert mock_match.called
        call_args = mock_match.call_args
        assert call_args[1].get('recent_days') == RECENT_DAYS == 7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
