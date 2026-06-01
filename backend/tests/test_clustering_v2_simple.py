"""
测试优化 1：强化增量聚类（简化版本，避免依赖问题）
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock, MagicMock
from datetime import datetime, timedelta
from typing import List, Dict, Any

# 常量
RECENT_DAYS = 7
MAX_CONCURRENCY = 2


# ──────────────────────────── Mock 函数 ────────────────────────────

async def _load_recent_singletons(cat2: str, days: int = RECENT_DAYS) -> List[Dict]:
    """加载最近 N 天入库的 frequency=1 题目（同 cat2）"""
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
            result = await _load_recent_singletons("C3.数据库基础", days=7)

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
            await _load_recent_singletons("C3.数据库基础", days=7)

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
            await _load_recent_singletons("C3.数据库基础", days=7)

        # 验证：SQL 应该包含时间过滤
        call_args = mock_conn.execute.call_args
        sql = call_args[0][0]
        assert "created_at" in sql
        assert "datetime('now'" in sql

    @pytest.mark.asyncio
    async def test_load_recent_singletons_empty_result(self):
        """测试：没有最近题目时返回空列表"""
        # 准备
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        # 执行
        with patch('app.db.connection.get_db_connection', return_value=mock_conn):
            result = await _load_recent_singletons("C3.数据库基础", days=7)

        # 验证
        assert result == []


class TestMatchAndClusterCat2Logic:
    """测试 _match_and_cluster_cat2 的逻辑（不调用真实 LLM）"""

    @pytest.mark.asyncio
    async def test_phase1_5_called_when_recent_singletons_exist(self):
        """测试：有最近题目时，Phase 1.5 被调用"""
        # 准备
        new_questions = [
            {"id": 101, "question": "Redis 持久化方式有哪些？", "cat2": "C3.数据库基础"}
        ]
        existing_clusters = []
        recent_singletons = [
            {"id": 50, "question": "Redis 持久化机制", "cat2": "C3.数据库基础"}
        ]

        # 模拟 LLM 调用
        mock_llm_response = '{"matches": [{"new_id": "101", "cluster_id": "50"}]}'
        mock_extract_json = {"matches": [{"new_id": "101", "cluster_id": "50"}]}

        # 执行
        with patch('app.services.clustering._load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = recent_singletons
            with patch('app.services.clustering._call_llm_with_retry', new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = mock_llm_response
                with patch('app.services.clustering._extract_json') as mock_json:
                    mock_json.return_value = mock_extract_json
                    
                    # 导入要测试的函数
                    from app.services.clustering import _match_and_cluster_cat2
                    
                    result = await _match_and_cluster_cat2(
                        "C3.数据库基础",
                        new_questions,
                        existing_clusters,
                        user_id=None,
                        recent_days=7
                    )

        # 验证
        assert len(result["matched"]) == 1
        assert result["matched"][0]["qd_id"] == 101
        assert result["matched"][0]["cluster_id"] == "50"
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
        with patch('app.services.clustering._load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = []  # 没有最近题目
            with patch('app.services.clustering._call_llm_with_retry', new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = '{"clusters": []}'
                with patch('app.services.clustering._extract_json') as mock_json:
                    mock_json.return_value = {"clusters": []}
                    
                    from app.services.clustering import _match_and_cluster_cat2
                    
                    result = await _match_and_cluster_cat2(
                        "C3.数据库基础",
                        new_questions,
                        existing_clusters,
                        user_id=None,
                        recent_days=7
                    )

        # 验证：只有 1 道题时，Phase 2 不需要调用 LLM（直接返回单题结果）
        assert mock_llm.call_count == 0

    @pytest.mark.asyncio
    async def test_phase1_5_respects_days_parameter(self):
        """测试：Phase 1.5 使用正确的 days 参数"""
        # 准备
        new_questions = [
            {"id": 101, "question": "Redis 持久化方式有哪些？", "cat2": "C3.数据库基础"}
        ]
        existing_clusters = []

        # 执行
        with patch('app.services.clustering._load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = [{"id": 50, "question": "test"}]
            with patch('app.services.clustering._call_llm_with_retry', new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = '{"matches": []}'
                with patch('app.services.clustering._extract_json') as mock_json:
                    mock_json.return_value = {"matches": []}
                    
                    from app.services.clustering import _match_and_cluster_cat2
                    
                    await _match_and_cluster_cat2(
                        "C3.数据库基础",
                        new_questions,
                        existing_clusters,
                        user_id=None,
                        recent_days=14  # 自定义天数
                    )

        # 验证：调用时使用了正确的 days 参数
        mock_load.assert_called_once_with("C3.数据库基础", days=14)


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
        
        mock_result = {
            "matched": [],
            "new_clusters": [{"ids": ["101"], "representative": "Redis 持久化方式有哪些？"}]
        }

        # 执行
        with patch('app.services.clustering._match_and_cluster_cat2', new_callable=AsyncMock) as mock_match:
            mock_match.return_value = mock_result
            from app.services.clustering import process_incremental_batch
            
            await process_incremental_batch(
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
        
        mock_result = {
            "matched": [],
            "new_clusters": []
        }

        # 执行
        with patch('app.services.clustering._match_and_cluster_cat2', new_callable=AsyncMock) as mock_match:
            mock_match.return_value = mock_result
            from app.services.clustering import process_incremental_batch
            
            await process_incremental_batch(
                new_rows,
                existing_by_cat2,
                user_id=None
            )

        # 验证：默认 recent_days 为 7
        call_args = mock_match.call_args
        assert call_args[1].get('recent_days') == RECENT_DAYS == 7


class TestIntegration:
    """集成测试"""

    @pytest.mark.asyncio
    async def test_full_flow_with_phase1_and_phase15(self):
        """测试：Phase 1 + Phase 1.5 + Phase 2 完整流程"""
        # 准备
        new_questions = [
            {"id": 101, "question": "Redis 持久化方式有哪些？", "cat2": "C3.数据库基础"},
            {"id": 102, "question": "TCP 三次握手的作用是什么？", "cat2": "C4.操作系统与网络"},
        ]
        existing_clusters = [
            {"id": 1, "question": "Redis 的 RDB 和 AOF 持久化有什么区别？"}
        ]
        recent_singletons = [
            {"id": 50, "question": "TCP 为什么是三次握手？", "cat2": "C4.操作系统与网络"}
        ]

        # 模拟返回
        phase1_response = {"matches": [{"new_id": "101", "cluster_id": "1"}]}
        phase15_response = {"matches": [{"new_id": "102", "cluster_id": "50"}]}
        phase2_response = {"clusters": []}

        # 执行
        with patch('app.services.clustering._load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = recent_singletons
            with patch('app.services.clustering._call_llm_with_retry', new_callable=AsyncMock) as mock_llm:
                mock_llm.side_effect = [
                    '{"matches": [{"new_id": "101", "cluster_id": "1"}]}',
                    '{"validations": [{"new_id": "101", "cluster_id": "1", "valid": true}]}',
                    '{"matches": [{"new_id": "102", "cluster_id": "50"}]}',
                    '{"clusters": []}'
                ]
                with patch('app.services.clustering._extract_json') as mock_json:
                    mock_json.side_effect = [
                        phase1_response,
                        {"validations": [{"new_id": "101", "cluster_id": "1", "valid": True}]},
                        phase15_response,
                        phase2_response
                    ]
                    
                    from app.services.clustering import _match_and_cluster_cat2
                    
                    result = await _match_and_cluster_cat2(
                        "C3.数据库基础",
                        new_questions,
                        existing_clusters,
                        user_id=None,
                        recent_days=7
                    )

        # 验证
        assert len(result["matched"]) == 2
        # 第一道题匹配到已有聚类
        assert any(m["qd_id"] == 101 and m["cluster_id"] == "1" for m in result["matched"])
        # 第二道题匹配到最近题目
        assert any(m["qd_id"] == 102 and m["cluster_id"] == "50" for m in result["matched"])

    @pytest.mark.asyncio
    async def test_phase1_failure_does_not_block_phase15(self):
        """测试：Phase 1 失败不影响 Phase 1.5 执行"""
        # 准备
        new_questions = [
            {"id": 101, "question": "Redis 持久化方式有哪些？", "cat2": "C3.数据库基础"}
        ]
        existing_clusters = [
            {"id": 1, "question": "Redis 持久化"}
        ]
        recent_singletons = [
            {"id": 50, "question": "Redis 持久化机制", "cat2": "C3.数据库基础"}
        ]

        # 执行
        with patch('app.services.clustering._load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = recent_singletons
            with patch('app.services.clustering._call_llm_with_retry', new_callable=AsyncMock) as mock_llm:
                # Phase 1 抛出异常，Phase 1.5 和 Phase 2 正常
                mock_llm.side_effect = [
                    Exception("LLM 调用失败"),  # Phase 1 失败
                    '{"matches": [{"new_id": "101", "cluster_id": "50"}]}',  # Phase 1.5 成功
                    '{"clusters": []}'  # Phase 2
                ]
                with patch('app.services.clustering._extract_json') as mock_json:
                    mock_json.side_effect = [
                        {"matches": [{"new_id": "101", "cluster_id": "50"}]},
                        {"clusters": []}
                    ]
                    
                    from app.services.clustering import _match_and_cluster_cat2
                    
                    result = await _match_and_cluster_cat2(
                        "C3.数据库基础",
                        new_questions,
                        existing_clusters,
                        user_id=None,
                        recent_days=7
                    )

        # 验证：Phase 1.5 仍然被执行并匹配成功
        assert len(result["matched"]) == 1
        assert result["matched"][0]["qd_id"] == 101
        assert result["matched"][0]["cluster_id"] == "50"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
