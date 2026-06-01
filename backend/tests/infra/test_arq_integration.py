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
             patch("app.worker.enqueue_cluster_task") as mock_arq:

            mock_tag.return_value = [["q1", "c1", "c2", "tags", "L2"]]
            mock_enqueue.return_value = 1
            mock_should.return_value = True
            mock_arq.return_value = MagicMock(job_id="arq-job-123")

            result = await process_interview_tag_then_maybe_cluster(
                interview_id=1, url="http://test.com", company="TestCo",
                round_="一面", questions_list="问题1\n问题2",
                user_id=1
            )

            # 打标签应同步完成
            mock_tag.assert_called_once()
            mock_enqueue.assert_called_once()

            # 聚类应通过 ARQ 调度（不直接调用 cluster_batch）
            mock_arq.assert_called_once_with(1, 1)
            mock_cluster.assert_not_called()  # 不应直接调用聚类
            mock_dequeue.assert_not_called()  # 不应直接取出队列

            assert result["tagged_count"] == 1

    @pytest.mark.asyncio
    async def test_process_interview_falls_back_when_arq_unavailable(self):
        """ARQ 不可用时应回退到内联聚类"""
        from app.services.pipeline import process_interview_tag_then_maybe_cluster

        with patch("app.services.pipeline.tag_interview") as mock_tag, \
             patch("app.services.pipeline.enqueue_questions") as mock_enqueue, \
             patch("app.services.pipeline.should_trigger_clustering") as mock_should, \
             patch("app.services.pipeline.dequeue_batch") as mock_dequeue, \
             patch("app.services.pipeline.cluster_batch") as mock_cluster, \
             patch("app.services.pipeline.mark_batch_done") as mock_done, \
             patch("app.worker.enqueue_cluster_task", side_effect=Exception("Redis 连接失败")):

            mock_tag.return_value = [["q1", "c1", "c2", "tags", "L2"]]
            mock_enqueue.return_value = 1
            mock_should.return_value = True
            mock_dequeue.return_value = [{"queue_id": 1, "qd_id": 10, "question": "test"}]
            mock_cluster.return_value = 5

            result = await process_interview_tag_then_maybe_cluster(
                interview_id=1, url="http://test.com", company="TestCo",
                round_="一面", questions_list="问题1",
                user_id=1
            )

            # ARQ 失败后应回退到内联聚类
            mock_dequeue.assert_called_once()
            mock_cluster.assert_called_once()
            mock_done.assert_called_once()
            assert result["clustered"] is True
            assert result["new_qb_count"] == 5

    @pytest.mark.asyncio
    async def test_force_cluster_uses_arq(self):
        """全量重建应通过 ARQ 调度"""
        from app.services.pipeline import force_cluster_all_pending

        with patch("app.worker.enqueue_force_cluster_task") as mock_arq:
            mock_arq.return_value = MagicMock(job_id="arq-force-456")

            result = await force_cluster_all_pending(user_id=1)

            mock_arq.assert_called_once_with(1)
            assert result["status"] == "queued"
            assert result["job_id"] == "arq-force-456"

    @pytest.mark.asyncio
    async def test_force_cluster_falls_back_when_arq_unavailable(self):
        """ARQ 不可用时全量重建应回退到内联执行"""
        from app.services.pipeline import force_cluster_all_pending

        with patch("app.worker.enqueue_force_cluster_task", side_effect=Exception("Redis 连接失败")), \
             patch("app.services.pipeline.dequeue_batch") as mock_dequeue, \
             patch("app.services.pipeline.cluster_batch") as mock_cluster, \
             patch("app.services.pipeline.mark_batch_done") as mock_done:

            mock_dequeue.side_effect = [
                [{"queue_id": 1, "qd_id": 10, "question": "test"}],
                []  # 第二次调用返回空，结束循环
            ]
            mock_cluster.return_value = 5

            result = await force_cluster_all_pending(user_id=1)

            # 应回退到内联执行
            assert result["batches"] == 1
            assert result["new_qb_count"] == 5
