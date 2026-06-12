"""
测试优化 1：强化增量聚类（Phase 1.5 - 匹配最近 7 天的 frequency=1 题目）
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from app.services.clustering import (
    process_incremental_batch,
    _match_and_cluster_cat2,
    _cluster_unmatched,
    _validate_merges,
    _load_recent_singletons,
    RECENT_DAYS
)


@pytest.fixture
def mock_db_connection():
    """模拟数据库连接"""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []
    return mock_conn


@pytest.fixture
def sample_new_questions():
    """示例新题目"""
    return [
        {"id": 101, "question": "Redis 持久化方式有哪些？", "cat2": "C3.数据库基础"},
        {"id": 102, "question": "TCP 三次握手的作用是什么？", "cat2": "C4.操作系统与网络"},
    ]


@pytest.fixture
def sample_existing_clusters():
    """示例已有聚类"""
    return {
        "C3.数据库基础": [
            {"id": 1, "question": "Redis 的 RDB 和 AOF 持久化有什么区别？"},
        ]
    }


@pytest.fixture
def sample_recent_singletons():
    """示例最近 7 天的 frequency=1 题目"""
    return [
        {"id": 50, "question": "介绍一下 Redis 持久化机制", "cat2": "C3.数据库基础"},
        {"id": 51, "question": "TCP 为什么是三次握手？", "cat2": "C4.操作系统与网络"},
    ]


class TestLoadRecentSingletons:
    """测试 _load_recent_singletons 函数"""

    @pytest.mark.asyncio
    async def test_load_recent_singletons_returns_correct_data(self, mock_db_connection):
        """测试：正确加载最近 N 天的 frequency=1 题目"""
        # 准备
        mock_rows = [
            {"id": 50, "question": "Redis 持久化"},
            {"id": 51, "question": "TCP 三次握手"},
        ]
        mock_db_connection.execute.return_value.fetchall.return_value = mock_rows

        # 执行
        with patch('app.services.clustering.get_db_connection', return_value=mock_db_connection):
            result = await _load_recent_singletons("C3.数据库基础", days=7)

        # 验证
        assert len(result) == 2
        assert result[0]["id"] == 50
        assert result[1]["id"] == 51

    @pytest.mark.asyncio
    async def test_load_recent_singletons_filters_by_cat2(self, mock_db_connection):
        """测试：只加载指定 cat2 的题目"""
        # 准备
        mock_db_connection.execute.return_value.fetchall.return_value = []

        # 执行
        with patch('app.services.clustering.get_db_connection', return_value=mock_db_connection):
            await _load_recent_singletons("C3.数据库基础", days=7)

        # 验证：SQL 应该包含 cat2 过滤
        call_args = mock_db_connection.execute.call_args
        sql = call_args[0][0]
        assert "cat2 = ?" in sql

    @pytest.mark.asyncio
    async def test_load_recent_singletons_filters_by_days(self, mock_db_connection):
        """测试：只加载最近 N 天的题目"""
        # 准备
        mock_db_connection.execute.return_value.fetchall.return_value = []

        # 执行
        with patch('app.services.clustering.get_db_connection', return_value=mock_db_connection):
            await _load_recent_singletons("C3.数据库基础", days=7)

        # 验证：SQL 应该包含时间过滤
        call_args = mock_db_connection.execute.call_args
        sql = call_args[0][0]
        assert "created_at" in sql
        assert "datetime('now'" in sql

    @pytest.mark.asyncio
    async def test_load_recent_singletons_empty_result(self, mock_db_connection):
        """测试：没有最近题目时返回空列表"""
        # 准备
        mock_db_connection.execute.return_value.fetchall.return_value = []

        # 执行
        with patch('app.services.clustering.get_db_connection', return_value=mock_db_connection):
            result = await _load_recent_singletons("C3.数据库基础", days=7)

        # 验证
        assert result == []


class TestMatchAndClusterCat2:
    """测试 _match_and_cluster_cat2 函数（包含 Phase 1.5）"""

    @pytest.mark.asyncio
    async def test_exact_existing_match_skips_llm(self, sample_new_questions):
        """完全相同的候选题直接匹配，不调用 LLM"""
        new_questions = [sample_new_questions[0]]
        existing_clusters = [{"id": 1, "question": "Redis持久化方式有哪些?"}]

        with patch('app.services.clustering._load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = []
            with patch('app.services.clustering._call_llm_with_retry', new_callable=AsyncMock) as mock_llm:
                result = await _match_and_cluster_cat2(
                    "C3.数据库基础",
                    new_questions,
                    existing_clusters,
                    user_id=None,
                    recent_days=0,
                )

        assert len(result["matched"]) == 1
        assert result["matched"][0]["cluster_id"] == "1"
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_phase1_5_matches_recent_singletons(self, sample_new_questions, sample_existing_clusters, sample_recent_singletons):
        """测试：Phase 1.5 能匹配到最近 7 天的相似题"""
        new_questions = [sample_new_questions[0]]
        existing_clusters = []

        mock_llm_response = '{"matches": [{"new_id": "101", "cluster_id": "50"}]}'

        with patch('app.services.clustering._load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = sample_recent_singletons
            with patch('app.services.clustering._call_llm_with_retry', new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = mock_llm_response
                with patch('app.services.clustering._extract_json') as mock_json:
                    mock_json.return_value = {"matches": [{"new_id": "101", "cluster_id": "50"}]}
                    # Mock _validate_merges to pass through
                    with patch('app.services.clustering._validate_merges', new_callable=AsyncMock) as mock_validate:
                        mock_validate.return_value = ([{"new_id": "101", "cluster_id": "50"}], {("101", "50"): 0.95})

                        result = await _match_and_cluster_cat2(
                            "C3.数据库基础",
                            new_questions,
                            existing_clusters,
                            user_id=None
                        )

        # 验证
        assert len(result["matched"]) == 1
        assert result["matched"][0]["qd_id"] == 101
        assert result["matched"][0]["cluster_id"] == "50"

    @pytest.mark.asyncio
    async def test_phase1_5_not_called_when_no_recent(self, sample_new_questions):
        """测试：没有最近题目时不调用 Phase 1.5"""
        # 准备
        new_questions = [sample_new_questions[0]]
        existing_clusters = []

        # 执行
        with patch('app.services.clustering._load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = []  # 没有最近题目
            with patch('app.services.clustering._call_llm_with_retry', new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = '{"clusters": []}'
                with patch('app.services.clustering._extract_json') as mock_json:
                    mock_json.return_value = {"clusters": []}
                    
                    result = await _match_and_cluster_cat2(
                        "C3.数据库基础",
                        new_questions,
                        existing_clusters,
                        user_id=None
                    )

        # 验证：只有 1 道题时，Phase 2 不需要调用 LLM（直接返回单题结果）
        # _call_llm_with_retry 应该不被调用
        assert mock_llm.call_count == 0

    @pytest.mark.asyncio
    async def test_phase1_5_respects_days_parameter(self, sample_new_questions, sample_recent_singletons):
        """测试：Phase 1.5 使用正确的 days 参数"""
        # 准备
        new_questions = [sample_new_questions[0]]
        existing_clusters = []

        # 执行
        with patch('app.services.clustering._load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = sample_recent_singletons
            with patch('app.services.clustering._call_llm_with_retry', new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = '{"matches": []}'
                with patch('app.services.clustering._extract_json') as mock_json:
                    mock_json.return_value = {"matches": []}
                    
                    await _match_and_cluster_cat2(
                        "C3.数据库基础",
                        new_questions,
                        existing_clusters,
                        user_id=None,
                        recent_days=14  # 自定义天数
                    )

        # 验证：调用时使用了正确的 days 参数
        mock_load.assert_called_once_with("C3.数据库基础", days=14)


class TestClusterUnmatchedFastPath:
    """测试未匹配题内部聚类的零成本路径"""

    @pytest.mark.asyncio
    async def test_exact_duplicate_questions_skip_llm(self):
        questions = [
            {"id": 1, "question": "TCP 三次握手的作用是什么？"},
            {"id": 2, "question": "TCP三次握手的作用是什么?"},
            {"id": 3, "question": "Redis 缓存穿透是什么？"},
        ]

        with patch('app.services.clustering._call_llm_with_retry', new_callable=AsyncMock) as mock_llm:
            clusters = await _cluster_unmatched(questions, user_id=None)

        assert any(set(c["ids"]) == {"1", "2"} for c in clusters)
        assert any(c["ids"] == ["3"] for c in clusters)
        mock_llm.assert_not_called()


class TestValidateMergesBatching:
    """测试二次验证分块"""

    @pytest.mark.asyncio
    async def test_validate_merges_splits_large_batches(self):
        matches = [{"new_id": str(i), "cluster_id": str(1000 + i)} for i in range(25)]
        new_questions = [{"id": i, "question": f"问题 {i}"} for i in range(25)]
        existing_clusters = [{"id": 1000 + i, "question": f"问题 {i} 变体"} for i in range(25)]
        validations_1 = [
            {"new_id": str(i), "cluster_id": str(1000 + i), "valid": True, "confidence": 0.95}
            for i in range(20)
        ]
        validations_2 = [
            {"new_id": str(i), "cluster_id": str(1000 + i), "valid": True, "confidence": 0.95}
            for i in range(20, 25)
        ]

        with patch('app.services.clustering._call_llm_with_retry', new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = ["{}", "{}"]
            with patch('app.services.clustering._extract_json') as mock_json:
                mock_json.side_effect = [
                    {"validations": validations_1},
                    {"validations": validations_2},
                ]
                validated, confidence_map = await _validate_merges(
                    matches, new_questions, existing_clusters, user_id=None
                )

        assert len(validated) == 25
        assert confidence_map[("24", "1024")] == 0.95
        assert mock_llm.call_count == 2


class TestProcessIncrementalBatch:
    """测试 process_incremental_batch 函数（主入口）"""

    @pytest.mark.asyncio
    async def test_process_incremental_batch_passes_recent_days(self, sample_new_questions, sample_existing_clusters):
        """测试：process_incremental_batch 正确传递 recent_days 参数"""
        # 准备
        mock_result = {
            "matched": [],
            "new_clusters": [{"ids": ["101"], "representative": "Redis 持久化方式有哪些？"}]
        }

        # 执行
        with patch('app.services.clustering._match_and_cluster_cat2', new_callable=AsyncMock) as mock_match:
            mock_match.return_value = mock_result
            await process_incremental_batch(
                sample_new_questions,
                sample_existing_clusters,
                user_id=None,
                recent_days=14
            )

        # 验证：recent_days 被正确传递
        call_args = mock_match.call_args
        assert call_args[1].get('recent_days') == 14 or call_args[0][3] == 14

    @pytest.mark.asyncio
    async def test_process_incremental_batch_default_recent_days(self, sample_new_questions, sample_existing_clusters):
        """测试：默认 recent_days 为 7"""
        # 准备
        mock_result = {
            "matched": [],
            "new_clusters": [{"ids": ["101"], "representative": "Redis 持久化方式有哪些？"}]
        }

        # 执行
        with patch('app.services.clustering._match_and_cluster_cat2', new_callable=AsyncMock) as mock_match:
            mock_match.return_value = mock_result
            await process_incremental_batch(
                sample_new_questions,
                sample_existing_clusters,
                user_id=None
            )

        # 验证：默认 recent_days 为 7
        call_args = mock_match.call_args
        recent_days = call_args[1].get('recent_days') or call_args[0][3] if len(call_args[0]) > 3 else None
        assert recent_days == RECENT_DAYS == 7


class TestIntegration:
    """集成测试：完整的 Phase 1 + Phase 1.5 + Phase 2 流程"""

    @pytest.mark.asyncio
    async def test_full_flow_with_phase1_and_phase15(self, sample_new_questions):
        """测试：候选池一次匹配已有聚类 + 最近题目"""
        # 准备
        new_questions = sample_new_questions
        existing_clusters = [
            {"id": 1, "question": "Redis 的 RDB 和 AOF 持久化有什么区别？"},
        ]
        recent_singletons = [
            {"id": 50, "question": "TCP 为什么是三次握手？", "cat2": "C4.操作系统与网络"},
        ]

        match_response = '{"matches": [{"new_id": "101", "cluster_id": "1", "confidence": 0.95}, {"new_id": "102", "cluster_id": "50", "confidence": 0.95}]}'
        phase2_response = '{"clusters": []}'

        # 执行
        with patch('app.services.clustering._load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = recent_singletons
            with patch('app.services.clustering._call_llm_with_retry', new_callable=AsyncMock) as mock_llm:
                mock_llm.side_effect = [match_response, phase2_response]
                with patch('app.services.clustering._extract_json') as mock_json:
                    mock_json.side_effect = [
                        {"matches": [
                            {"new_id": "101", "cluster_id": "1", "confidence": 0.95},
                            {"new_id": "102", "cluster_id": "50", "confidence": 0.95},
                        ]},
                        {"clusters": []}
                    ]
                    with patch('app.services.clustering._validate_merges', new_callable=AsyncMock) as mock_validate:
                        mock_validate.return_value = (
                            [
                                {"new_id": "101", "cluster_id": "1"},
                                {"new_id": "102", "cluster_id": "50"},
                            ],
                            {("101", "1"): 0.95, ("102", "50"): 0.95},
                        )

                        result = await _match_and_cluster_cat2(
                            "C3.数据库基础",
                            new_questions,
                            existing_clusters,
                            user_id=None
                        )

        # 验证
        assert len(result["matched"]) == 2
        # 第一道题匹配到已有聚类
        assert any(m["qd_id"] == 101 and m["cluster_id"] == "1" for m in result["matched"])
        # 第二道题匹配到最近题目
        assert any(m["qd_id"] == 102 and m["cluster_id"] == "50" for m in result["matched"])

    @pytest.mark.asyncio
    async def test_phase1_failure_does_not_block_phase15(self, sample_new_questions, sample_recent_singletons):
        """测试：已有聚类输入异常兼容，不影响最近题加载"""
        # 准备
        new_questions = [sample_new_questions[0]]
        existing_clusters = {
            "C3.数据库基础": [{"id": 1, "question": "Redis 持久化"}]
        }

        # 执行
        with patch('app.services.clustering._load_recent_singletons', new_callable=AsyncMock) as mock_load:
            mock_load.return_value = sample_recent_singletons
            with patch('app.services.clustering._call_llm_with_retry', new_callable=AsyncMock) as mock_llm:
                mock_llm.side_effect = ['{"matches": []}', '{"clusters": []}']
                with patch('app.services.clustering._extract_json') as mock_json:
                    mock_json.side_effect = [
                        {"matches": []},
                        {"clusters": []}
                    ]
                    
                    result = await _match_and_cluster_cat2(
                        "C3.数据库基础",
                        new_questions,
                        existing_clusters,
                        user_id=None
                    )

        # 验证：Phase 1.5 仍然被执行
        assert mock_load.called

    @pytest.mark.asyncio
    async def test_backward_compatibility_no_recent_days(self, sample_new_questions, sample_existing_clusters):
        """测试：向后兼容 - 不传 recent_days 参数时使用默认值"""
        # 准备
        mock_result = {
            "matched": [],
            "new_clusters": []
        }

        # 执行：不传 recent_days
        with patch('app.services.clustering._match_and_cluster_cat2', new_callable=AsyncMock) as mock_match:
            mock_match.return_value = mock_result
            await process_incremental_batch(
                sample_new_questions,
                sample_existing_clusters,
                user_id=None
            )

        # 验证：函数正常执行，使用默认值
        assert mock_match.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
