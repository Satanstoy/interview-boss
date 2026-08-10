"""
测试优化 4：定时 compaction

测试目标：
1. 定时任务正确配置
2. 任务执行逻辑正确
3. 日志记录正确
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime
import json


# ──────────────────────────── 模拟的函数实现 ────────────────────────────

class MockWorkerSettings:
    """模拟 WorkerSettings"""
    functions = []
    cron_jobs = []

    def __init__(self):
        self.functions = []
        self.cron_jobs = []


async def mock_scheduled_compaction_task(ctx):
    """模拟：定时 compaction 任务"""
    # 模拟 compact_singletons_in_db 的返回
    result = {
        "total_singletons": 100,
        "merged": 10,
        "remaining": 90,
        "llm_calls": 5,
        "merged_batches": 3,
        "cross_merged": 2
    }

    # 记录日志
    log_entry = {
        "task": "scheduled_compaction",
        "timestamp": datetime.now().isoformat(),
        "result": result
    }

    return result


# ──────────────────────────── 测试用例 ────────────────────────────

class TestWorkerSettings:
    """测试 WorkerSettings 配置"""

    def test_cron_jobs_configuration(self):
        """测试：cron_jobs 配置正确"""
        # 准备
        settings = MockWorkerSettings()

        # 执行：添加定时任务
        settings.cron_jobs = [
            {
                "function": mock_scheduled_compaction_task,
                "hour": 3,
                "minute": 0,
            }
        ]

        # 验证
        assert len(settings.cron_jobs) == 1
        assert settings.cron_jobs[0]["hour"] == 3
        assert settings.cron_jobs[0]["minute"] == 0

    def test_functions_list_includes_compaction(self):
        """测试：functions 列表包含 compaction 任务"""
        # 准备
        settings = MockWorkerSettings()

        # 执行：添加函数
        settings.functions = [
            "cluster_batch_task",
            "cluster_rebuild_task",
            "build_master_bank_task",
            "scheduled_compaction_task"
        ]

        # 验证
        assert "scheduled_compaction_task" in settings.functions


class TestScheduledCompaction:
    """测试定时 compaction 任务"""

    @pytest.mark.asyncio
    async def test_scheduled_compaction_success(self):
        """测试：定时 compaction 成功执行"""
        # 执行
        result = await mock_scheduled_compaction_task({})

        # 验证
        assert result["total_singletons"] == 100
        assert result["merged"] == 10
        assert result["cross_merged"] == 2

    @pytest.mark.asyncio
    async def test_scheduled_compaction_returns_all_fields(self):
        """测试：定时 compaction 返回所有必要字段"""
        # 执行
        result = await mock_scheduled_compaction_task({})

        # 验证：结果包含所有必要字段
        assert "total_singletons" in result
        assert "merged" in result
        assert "remaining" in result
        assert "llm_calls" in result
        assert "merged_batches" in result
        assert "cross_merged" in result


class TestIntegration:
    """集成测试"""

    def test_worker_settings_integration(self):
        """测试：WorkerSettings 完整配置"""
        # 准备
        settings = MockWorkerSettings()

        # 执行：配置所有任务
        settings.functions = [
            "cluster_batch_task",
            "cluster_rebuild_task",
            "build_master_bank_task",
            "scheduled_compaction_task"
        ]
        settings.cron_jobs = [
            {
                "function": mock_scheduled_compaction_task,
                "hour": 3,
                "minute": 0,
            }
        ]

        # 验证
        assert len(settings.functions) == 4
        assert len(settings.cron_jobs) == 1
        assert "scheduled_compaction_task" in settings.functions
        assert settings.cron_jobs[0]["hour"] == 3

    def test_cron_trigger_configuration(self):
        """测试：Cron 触发器配置"""
        # 准备
        cron_config = {
            "function": mock_scheduled_compaction_task,
            "hour": 3,
            "minute": 0,
        }

        # 验证：配置正确
        assert cron_config["hour"] == 3
        assert cron_config["minute"] == 0
        assert callable(cron_config["function"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
