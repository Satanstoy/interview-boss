"""
TDD 测试：ARQ Worker 模块

测试 Redis 连接配置、Worker 配置、任务入队和执行。
遵循红-绿-重构循环。
"""
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestRedisConfig:
    """T-001: Redis 连接配置测试"""

    def test_redis_settings_from_default_url(self):
        """默认 REDIS_URL 应正确创建 RedisSettings"""
        from arq.connections import RedisSettings
        settings = RedisSettings.from_dsn("redis://localhost:6379/0")
        assert settings.host == "localhost"
        assert settings.port == 6379
        assert settings.database == 0

    def test_redis_settings_from_custom_url(self):
        """自定义 REDIS_URL 应正确解析"""
        from arq.connections import RedisSettings
        settings = RedisSettings.from_dsn("redis://192.168.1.100:6380/2")
        assert settings.host == "192.168.1.100"
        assert settings.port == 6380
        assert settings.database == 2

    def test_get_redis_url_from_env(self):
        """应从环境变量读取 REDIS_URL"""
        with patch.dict(os.environ, {"REDIS_URL": "redis://test:6379/1"}):
            # 重新导入以读取新的环境变量
            import importlib
            import app.worker
            importlib.reload(app.worker)
            assert app.worker.REDIS_URL == "redis://test:6379/1"

    def test_get_redis_url_default(self):
        """未设置 REDIS_URL 时应使用默认值"""
        with patch.dict(os.environ, {}, clear=True):
            if "REDIS_URL" in os.environ:
                del os.environ["REDIS_URL"]
            import importlib
            import app.worker
            importlib.reload(app.worker)
            assert app.worker.REDIS_URL == "redis://localhost:6379/0"


class TestRedisPool:
    """T-002: Redis 连接池创建测试"""

    @pytest.mark.asyncio
    async def test_create_redis_pool(self):
        """应能创建 Redis 连接池（通过 worker 的 _get_redis_pool）"""
        import app.worker
        with patch("app.worker._get_redis_pool") as mock_pool_fn:
            mock_pool = MagicMock()
            mock_pool_fn.return_value = mock_pool
            pool = await app.worker._get_redis_pool()
            assert pool is not None


class TestWorkerSettings:
    """T-003: ARQ Worker 配置测试"""

    def test_worker_settings_class_exists(self):
        """WorkerSettings 类应存在"""
        from app.worker import WorkerSettings
        assert WorkerSettings is not None

    def test_worker_has_functions(self):
        """Worker 应注册任务函数"""
        from app.worker import WorkerSettings
        assert hasattr(WorkerSettings, 'functions')
        assert len(WorkerSettings.functions) == 5

    def test_worker_has_lifecycle_hooks(self):
        """Worker 应有启动和关闭钩子"""
        from app.worker import WorkerSettings
        assert hasattr(WorkerSettings, 'on_startup')
        assert hasattr(WorkerSettings, 'on_shutdown')
        assert callable(WorkerSettings.on_startup)
        assert callable(WorkerSettings.on_shutdown)

    def test_worker_resource_limits_for_2c4g(self):
        """T-010: 2c4g 服务器资源限制配置"""
        from app.worker import WorkerSettings
        assert WorkerSettings.job_timeout == 900  # 15 分钟超时
        assert WorkerSettings.max_tries == 2  # 最多重试 2 次
        assert WorkerSettings.keep_result == 3600  # 结果保留 1 小时
        assert WorkerSettings.queue_read_limit == 10  # 每次最多读 10 个任务


class TestTaskEnqueue:
    """T-004: 任务入队测试"""

    @pytest.mark.asyncio
    async def test_enqueue_cluster_task(self):
        """应能将聚类任务入队"""
        from app.worker import enqueue_cluster_task
        with patch("app.worker._get_redis_pool") as mock_pool_fn:
            mock_pool = AsyncMock()
            mock_pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="test-job-123"))
            mock_pool_fn.return_value = mock_pool

            job = await enqueue_cluster_task(interview_id=1, user_id=1)
            assert job is not None
            mock_pool.enqueue_job.assert_called_once_with(
                "cluster_questions_task", 1, 1
            )

    @pytest.mark.asyncio
    async def test_enqueue_force_cluster_task(self):
        """应能将全量重建任务入队"""
        from app.worker import enqueue_force_cluster_task
        with patch("app.worker._get_redis_pool") as mock_pool_fn:
            mock_pool = AsyncMock()
            mock_pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="test-job-456"))
            mock_pool_fn.return_value = mock_pool

            job = await enqueue_force_cluster_task(user_id=1)
            assert job is not None
            mock_pool.enqueue_job.assert_called_once_with(
                "force_cluster_all_task", 1
            )


class TestTaskExecution:
    """T-005 + T-006: 任务执行测试"""

    @pytest.mark.asyncio
    async def test_cluster_task_with_batch(self):
        """T-005: 有 pending 任务时应执行聚类"""
        from app.worker import cluster_questions_task
        mock_ctx = MagicMock()

        with patch("app.services.pipeline.dequeue_batch") as mock_dequeue, \
             patch("app.services.pipeline.cluster_batch") as mock_cluster, \
             patch("app.services.pipeline.mark_batch_done") as mock_done, \
             patch("app.services.pipeline.mark_batch_failed") as mock_failed:

            mock_dequeue.return_value = [
                {"queue_id": 1, "qd_id": 10, "question": "test", "url": "http://test.com"}
            ]
            mock_cluster.return_value = 5  # new_count

            result = await cluster_questions_task(mock_ctx, interview_id=1, user_id=1)
            assert result["status"] == "done"
            assert result["new_count"] == 5
            mock_done.assert_called_once()

    @pytest.mark.asyncio
    async def test_cluster_task_empty_queue(self):
        """T-006: 队列为空时应返回 empty 状态"""
        from app.worker import cluster_questions_task
        mock_ctx = MagicMock()

        with patch("app.services.pipeline.dequeue_batch") as mock_dequeue:
            mock_dequeue.return_value = []

            result = await cluster_questions_task(mock_ctx, interview_id=1, user_id=1)
            assert result["status"] == "empty"
            assert result["new_count"] == 0

    @pytest.mark.asyncio
    async def test_cluster_task_failure_marks_pending(self):
        """T-007: 聚类失败时应将队列状态重置为 pending"""
        from app.worker import cluster_questions_task
        mock_ctx = MagicMock()

        with patch("app.services.pipeline.dequeue_batch") as mock_dequeue, \
             patch("app.services.pipeline.cluster_batch") as mock_cluster, \
             patch("app.services.pipeline.mark_batch_failed") as mock_failed:

            mock_dequeue.return_value = [
                {"queue_id": 1, "qd_id": 10, "question": "test"}
            ]
            mock_cluster.side_effect = Exception("LLM API 超时")

            with pytest.raises(Exception, match="LLM API 超时"):
                await cluster_questions_task(mock_ctx, interview_id=1, user_id=1)

            mock_failed.assert_called_once_with([1])

    @pytest.mark.asyncio
    async def test_force_cluster_all_task(self):
        """T-009: 全量重建任务应处理所有 pending 队列"""
        from app.worker import force_cluster_all_task
        mock_ctx = MagicMock()

        with patch("app.services.pipeline.dequeue_batch") as mock_dequeue, \
             patch("app.services.pipeline.cluster_batch") as mock_cluster, \
             patch("app.services.pipeline.mark_batch_done") as mock_done:
            mock_dequeue.side_effect = [
                [{"queue_id": 1, "qd_id": 10, "question": "test"}],
                [{"queue_id": 2, "qd_id": 11, "question": "test2"}],
                [{"queue_id": 3, "qd_id": 12, "question": "test3"}],
                [],
            ]
            mock_cluster.return_value = 5

            result = await force_cluster_all_task(mock_ctx, user_id=1)
            assert result["batches"] == 3
            assert result["new_qb_count"] == 15
            assert mock_cluster.call_count == 3
            assert mock_done.call_count == 3
