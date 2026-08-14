"""
TDD 测试：ARQ Worker 模块

测试 Redis 连接配置、Worker 配置、任务入队和执行。
遵循红-绿-重构循环。
"""
import os
import pytest
from contextlib import contextmanager
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
        assert len(WorkerSettings.functions) >= 6

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
    async def test_enqueue_cluster_batch_job(self):
        """应能将持久化聚类攒批任务入队"""
        from app.worker import enqueue_cluster_batch_job
        with patch("app.worker_enqueue._get_redis_pool") as mock_pool_fn:
            mock_pool = AsyncMock()
            mock_pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="test-job-123"))
            mock_pool_fn.return_value = mock_pool

            job = await enqueue_cluster_batch_job(job_id=1)
            assert job is not None
            mock_pool.enqueue_job.assert_called_once_with(
                "cluster_batch_task", 1
            )

    @pytest.mark.asyncio
    async def test_enqueue_cluster_rebuild_job(self):
        """应能将持久化全量重建任务入队"""
        from app.worker import enqueue_cluster_rebuild_job
        with patch("app.worker_enqueue._get_redis_pool") as mock_pool_fn:
            mock_pool = AsyncMock()
            mock_pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="test-job-456"))
            mock_pool_fn.return_value = mock_pool

            job = await enqueue_cluster_rebuild_job(job_id=1)
            assert job is not None
            mock_pool.enqueue_job.assert_called_once_with(
                "cluster_rebuild_task", 1
            )


class TestTaskExecution:
    """持久化 worker 任务执行测试"""

    @pytest.mark.asyncio
    async def test_cluster_rebuild_task_claims_and_completes_durable_job(self, test_db):
        """全量重建 worker 必须 claim/进度/完成同一条 jobs 记录。"""
        from contextlib import contextmanager
        from app.worker import cluster_rebuild_task

        cursor = test_db.execute(
            "INSERT INTO jobs (job_type, status, progress_total) "
            "VALUES ('cluster_rebuild', 'pending', 1)"
        )
        job_id = cursor.lastrowid
        test_db.execute(
            "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
            (job_id, '{"user_id": 1}'),
        )
        test_db.commit()

        @contextmanager
        def _test_connection():
            yield test_db

        # Load modules that bind get_db_connection before replacing the app
        # connector with this test-only context manager.
        import app.services.pipeline  # noqa: F401

        with patch("app.db.connection.get_db_connection", _test_connection), \
             patch("app.services.pipeline.dequeue_batch", side_effect=[
                 [{"queue_id": 1, "qd_id": 10, "question": "test"}], []
             ]), \
             patch("app.services.pipeline.cluster_batch", new=AsyncMock(return_value=5)) as mock_cluster, \
             patch("app.services.pipeline.mark_batch_done") as mock_done:
            result = await cluster_rebuild_task({}, job_id)

        assert result["status"] == "done"
        assert result["processed"] == 1
        assert mock_cluster.await_count == 1
        mock_done.assert_called_once_with([1])
        assert test_db.execute(
            "SELECT status FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()[0] == "completed"

    @pytest.mark.asyncio
    async def test_interview_reprocess_task_is_durable(self, test_db):
        """面经重分析的 LLM 阶段也必须由 durable worker 执行。"""
        from contextlib import contextmanager
        from app.services.job_lifecycle import create_interview_reprocess_job
        from app.worker import interview_reprocess_task

        test_db.execute(
            "INSERT INTO interview (id, url, company, round, questions_list, job_position) "
            "VALUES (1, 'internal://1', '测试公司', '一面', '1. 什么是幂等？', '后端')"
        )
        job_id, _ = create_interview_reprocess_job(test_db, 1, user_id=None)
        test_db.commit()

        @contextmanager
        def _test_connection():
            yield test_db

        import app.services.pipeline  # noqa: F401

        tagged_rows = [[
            "internal://1", "测试公司", "一面", "什么是幂等？",
            "后端", "基础", "幂等", "简单",
        ]]
        with patch("app.db.connection.get_db_connection", _test_connection), \
             patch("app.services.pipeline.tag_interview", new=AsyncMock(return_value=tagged_rows)) as mock_tag, \
             patch("app.services.pipeline.enqueue_questions", return_value=1), \
             patch("app.services.pipeline._run_cluster_batch_in_background", new=AsyncMock(return_value=True)):
            result = await interview_reprocess_task({}, job_id)

        assert result["status"] == "completed"
        mock_tag.assert_awaited_once()
        row = test_db.execute(
            "SELECT status, result FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        assert row["status"] == "completed"
        assert '"tagged_count": 1' in row["result"]


class TestDurableJobDispatcher:
    @pytest.mark.asyncio
    async def test_dispatcher_includes_rebuild_and_embedding_jobs(self, test_db):
        """Redis 短暂不可用后，dispatcher 也应接管重建类任务。"""
        from app.worker import scheduled_submit_job_dispatch_task

        test_db.executemany(
            "INSERT INTO jobs (job_type, status, created_by) VALUES (?, 'pending', ?)",
            [
                ("build_master_bank", 1),
                ("recompute_embedding", 1),
                ("reprocess_interview", 1),
            ],
        )
        test_db.commit()

        @contextmanager
        def _test_connection():
            yield test_db

        with patch("app.db.connection.get_db_connection", _test_connection), patch(
            "app.worker_scheduled.enqueue_build_job",
            new=AsyncMock(return_value=MagicMock(job_id="arq-build-1")),
        ) as mock_build, patch(
            "app.worker_scheduled.enqueue_recompute_embedding_job",
            new=AsyncMock(return_value=MagicMock(job_id="arq-embedding-1")),
        ) as mock_embedding:
            with patch(
                "app.worker_scheduled.enqueue_interview_reprocess_job",
                new=AsyncMock(return_value=MagicMock(job_id="arq-reprocess-1")),
            ) as mock_reprocess:
                result = await scheduled_submit_job_dispatch_task({})

        assert result["dispatched"] == 3
        mock_build.assert_awaited_once()
        mock_embedding.assert_awaited_once()
        mock_reprocess.assert_awaited_once()
        rows = test_db.execute(
            "SELECT job_type, status, arq_job_id FROM jobs "
            "WHERE job_type IN ('build_master_bank', 'recompute_embedding', 'reprocess_interview') "
            "ORDER BY job_type"
        ).fetchall()
        assert [(row["job_type"], row["status"]) for row in rows] == [
            ("build_master_bank", "queued"),
            ("recompute_embedding", "queued"),
            ("reprocess_interview", "queued"),
        ]
