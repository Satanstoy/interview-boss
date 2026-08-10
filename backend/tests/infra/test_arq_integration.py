"""
TDD 测试：ARQ 与 FastAPI 集成

验证聚类任务通过 ARQ 异步调度，不阻塞 HTTP 响应。
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestPipelineARQIntegration:
    """T-011: FastAPI 集成测试"""

    @pytest.mark.asyncio
    async def test_process_interview_uses_arq_for_clustering(self):
        """聚类任务应通过 ARQ 异步调度，而非内联执行"""
        from app.services.pipeline import process_interview_tag_then_maybe_cluster

        with patch("app.services.pipeline.tag_interview") as mock_tag, \
             patch("app.services.pipeline.enqueue_questions") as mock_enqueue, \
             patch("app.services.pipeline.should_trigger_clustering") as mock_should, \
             patch("app.services.pipeline.dequeue_batch") as mock_dequeue, \
             patch("app.services.pipeline.cluster_batch") as mock_cluster, \
             patch("app.services.pipeline.mark_batch_done") as mock_done, \
             patch("app.services.pipeline.queue._run_cluster_batch_in_background", new=AsyncMock(return_value=True)) as mock_arq:

            mock_tag.return_value = [["q1", "c1", "c2", "tags", "L2"]]
            mock_enqueue.return_value = 1
            mock_should.return_value = True

            result = await process_interview_tag_then_maybe_cluster(
                interview_id=1, url="http://test.com", company="TestCo",
                round_="一面", questions_list="问题1\n问题2",
                user_id=1
            )

            # 打标签应同步完成
            mock_tag.assert_called_once()
            mock_enqueue.assert_called_once()

            # 聚类应通过 ARQ 调度（不直接调用 cluster_batch）
            mock_arq.assert_awaited_once_with(user_id=1)
            mock_cluster.assert_not_called()  # 不应直接调用聚类
            mock_dequeue.assert_not_called()  # 不应直接取出队列

            assert result["tagged_count"] == 1

    @pytest.mark.asyncio
    async def test_process_interview_keeps_queue_when_arq_unavailable(self):
        """攒批调度失败时不在 Web 进程内执行聚类。"""
        from app.services.pipeline import process_interview_tag_then_maybe_cluster

        with patch("app.services.pipeline.tag_interview") as mock_tag, \
             patch("app.services.pipeline.enqueue_questions") as mock_enqueue, \
             patch("app.services.pipeline.should_trigger_clustering") as mock_should, \
             patch("app.services.pipeline.dequeue_batch") as mock_dequeue, \
             patch("app.services.pipeline.cluster_batch") as mock_cluster, \
             patch("app.services.pipeline.mark_batch_done") as mock_done, \
             patch("app.services.pipeline.queue._run_cluster_batch_in_background", new=AsyncMock(side_effect=Exception("Redis 连接失败"))):

            mock_tag.return_value = [["q1", "c1", "c2", "tags", "L2"]]
            mock_enqueue.return_value = 1
            mock_should.return_value = True

            result = await process_interview_tag_then_maybe_cluster(
                interview_id=1, url="http://test.com", company="TestCo",
                round_="一面", questions_list="问题1",
                user_id=1
            )

            # 题目仍留在 analysis_queue，等待后续 dispatcher 补偿
            mock_dequeue.assert_not_called()
            mock_cluster.assert_not_called()
            mock_done.assert_not_called()
            assert result["clustered"] is False
            assert result["new_qb_count"] == 0

    @pytest.mark.asyncio
    async def test_force_cluster_uses_durable_arq_job(self, test_db):
        """全量重建应先落库，再通过 ARQ 调度"""
        from app.services.pipeline import force_cluster_all_pending

        with patch("app.worker.enqueue_cluster_rebuild_job", new=AsyncMock(
            return_value=MagicMock(job_id="arq-force-456")
        )) as mock_arq:
            result = await force_cluster_all_pending(user_id=1)

            mock_arq.assert_awaited_once_with(1)
            assert result["status"] == "queued"
            assert result["arq_job_id"] == "arq-force-456"
            row = test_db.execute(
                "SELECT job_type, status FROM jobs WHERE id = ?", (result["job_id"],)
            ).fetchone()
            assert tuple(row) == ("cluster_rebuild", "queued")

    @pytest.mark.asyncio
    async def test_force_cluster_remains_pending_when_arq_unavailable(self, test_db):
        """ARQ 不可用时全量重建应保留 pending，等待 dispatcher 补偿"""
        from app.services.pipeline import force_cluster_all_pending

        with patch("app.worker.enqueue_cluster_rebuild_job", new=AsyncMock(
            side_effect=Exception("Redis 连接失败")
        )), \
             patch("app.services.pipeline.dequeue_batch") as mock_dequeue, \
             patch("app.services.pipeline.cluster_batch") as mock_cluster:
            result = await force_cluster_all_pending(user_id=1)

            assert result["status"] == "pending"
            assert test_db.execute(
                "SELECT status FROM jobs WHERE id = ?", (result["job_id"],)
            ).fetchone()[0] == "pending"
            mock_dequeue.assert_not_called()
            mock_cluster.assert_not_called()
