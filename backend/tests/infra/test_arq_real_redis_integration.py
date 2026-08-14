"""
真实 Redis + ARQ worker 集成测试（audit finding D3）

背景：test_arq_integration.py 的 ARQ 关键路径纯 mock-only，任务队列可靠性无保障。
本文件在 docker compose 的 test 服务（depends_on 真实 redis:7.4-alpine）内，
连接真实 Redis，验证「ARQ 真实入队 → worker 真实消费 → 任务结果可见」关键路径。

默认 skip：仅当 RUN_REAL_REDIS=1 时才运行，避免默认套件依赖真实 Redis。
密码读取优先级：
  1. REDIS_PASSWORD_FILE 指向的文件
  2. REDIS_PASSWORD 环境变量
两者都不可得则跳过。
"""
import os
import uuid

import pytest

SKIP_REASON = "set RUN_REAL_REDIS=1 to run real-redis integration tests"

REAL_REDIS = os.environ.get("RUN_REAL_REDIS") == "1"


def _load_redis_password() -> str:
    """密码优先从 REDIS_PASSWORD_FILE 指向的文件读取，其次 REDIS_PASSWORD。"""
    path = os.environ.get("REDIS_PASSWORD_FILE") or ""
    if path.strip():
        try:
            with open(path.strip(), encoding="utf-8") as secret_file:
                pw = secret_file.read().strip()
                if pw:
                    return pw
        except OSError:
            pass
    return (os.environ.get("REDIS_PASSWORD") or "").strip()


def _real_redis_dsn() -> str:
    """构造指向 compose redis 服务的 DSN（REDIS_HOST 默认 redis）。"""
    from urllib.parse import quote

    host = os.environ.get("REDIS_HOST") or "redis"
    password = _load_redis_password()
    if password:
        return f"redis://:{quote(password, safe='')}@{host}:6379/0"
    return f"redis://{host}:6379/0"


def _require_real_redis():
    """skip 条件：RUN_REAL_REDIS=1 且能拿到连接密码。"""
    if not REAL_REDIS:
        pytest.skip(SKIP_REASON)
    if not _load_redis_password():
        pytest.skip(
            "REDIS_PASSWORD_FILE 文件与 REDIS_PASSWORD 环境变量都不可用，无法连接真实 Redis"
        )


# 一个极简的真实消费任务：只返回固定结果，便于断言「worker 真实执行了」。
async def real_redis_echo_task(ctx, payload: str):
    return {"status": "ok", "payload": payload, "consumed": True}


class TestRealRedisARQIntegration:
    """T-D3: 真实 Redis + ARQ worker 关键路径集成测试"""

    # 每个测试进程用独立的队列名，绝不触碰生产 arq:queue。
    _QUEUE_NAME = f"arq:real-redis-test-{uuid.uuid4().hex[:8]}"

    def setup_method(self):
        _require_real_redis()

    async def _consume_once(self, queue_name: str):
        """用独立队列、burst 模式真实消费一次队列里的任务。"""
        from arq.worker import Worker
        from arq.connections import RedisSettings

        settings = RedisSettings.from_dsn(_real_redis_dsn())
        worker = Worker(
            functions=[real_redis_echo_task],
            queue_name=queue_name,
            redis_settings=settings,
            handle_signals=False,
            burst=True,
            max_tries=1,
            job_timeout=30,
            keep_result=60,
            poll_delay=0.01,
            queue_read_limit=10,
        )
        await worker.main()
        await worker.close()

    @pytest.mark.asyncio
    async def test_enqueue_consume_result_critical_path(self):
        """关键路径：真实入队 → worker 真实消费 → 结果可见。"""
        from arq.connections import create_pool, RedisSettings

        settings = RedisSettings.from_dsn(_real_redis_dsn())
        pool = await create_pool(settings, default_queue_name=self._QUEUE_NAME)
        try:
            # 1. 真实入队
            payload = f"hello-real-redis-{uuid.uuid4().hex[:6]}"
            job = await pool.enqueue_job("real_redis_echo_task", payload)
            assert job is not None, "enqueue_job 未返回 Job（真实 Redis 入队失败）"

            # 2. worker 真实消费一次
            await self._consume_once(self._QUEUE_NAME)

            # 3. 结果可见（独立连接轮询 redis，验证任务结果已持久化）
            import asyncio

            result = None
            for _ in range(30):
                result = await job.result(timeout=2)
                if result is not None:
                    break
                await asyncio.sleep(0.2)
            assert result == {"status": "ok", "payload": payload, "consumed": True}, (
                f"worker 消费结果不匹配: {result}"
            )
        finally:
            await pool.aclose()

    @pytest.mark.asyncio
    async def test_enqueue_job_is_durable_in_redis(self):
        """入队后任务应真实写入 Redis 队列（queue zset 可读）。"""
        from arq.connections import create_pool, RedisSettings

        settings = RedisSettings.from_dsn(_real_redis_dsn())
        pool = await create_pool(settings, default_queue_name=self._QUEUE_NAME)
        try:
            job = await pool.enqueue_job("real_redis_echo_task", "durable-check")
            assert job is not None, "enqueue_job 未返回 Job（真实 Redis 入队失败）"
            job_id = getattr(job, "job_id", None)
            assert job_id, "入队后未拿到 job_id，任务未写入 Redis"
            # ARQ 把任务写入 <job_id> 对应的持久化 key + 队列 zset(score=入队毫秒时间戳)。
            # 用 zscore 验证 job_id 成员确实落进队列。
            score = await pool.zscore(self._QUEUE_NAME, job_id)
            assert score is not None, "Redis 队列中读不到该 job_id，任务未真实入队"
        finally:
            await pool.aclose()
