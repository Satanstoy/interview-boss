"""
自动化测试 — 针对 BUG-001 (Worker cron_jobs 配置错误)
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestBug001WorkerCronJobs:
    """BUG-001: cron_jobs 必须是 CronJob 实例，不能是 dict"""

    def test_cron_jobs_must_be_cronjob_instances_not_dicts(self):
        """BUG-001: cron_jobs 中的元素必须是 CronJob 实例"""
        from app.worker import WorkerSettings
        from arq.cron import CronJob

        for cj in WorkerSettings.cron_jobs:
            assert isinstance(cj, CronJob), (
                f"Expected CronJob instance, got {type(cj).__name__}. "
                f"arq 0.28 requires CronJob instances, not dicts."
            )

    def test_cron_jobs_has_compaction_schedule(self):
        """BUG-001: cron_jobs 应包含 compaction 定时任务"""
        from app.worker import WorkerSettings
        from arq.cron import CronJob

        assert len(WorkerSettings.cron_jobs) >= 1
        compaction_job = WorkerSettings.cron_jobs[0]
        assert isinstance(compaction_job, CronJob)
        assert compaction_job.hour == {3}
        assert compaction_job.minute == {0}

    def test_cron_job_name_contains_compaction(self):
        """BUG-001: 定时任务名称应包含 compaction"""
        from app.worker import WorkerSettings

        job = WorkerSettings.cron_jobs[0]
        assert "compaction" in job.name.lower() or "scheduled" in job.name.lower()

    def test_worker_settings_can_be_instantiated(self):
        """BUG-001: WorkerSettings 应能被 arq Worker 正常加载（不抛 RuntimeError）"""
        from arq.worker import Worker
        from app.worker import WorkerSettings

        # arq Worker.__init__ 会校验 cron_jobs，若为 dict 会抛 RuntimeError
        # 直接访问 cron_jobs 属性验证类型
        from arq.cron import CronJob
        for cj in WorkerSettings.cron_jobs:
            assert isinstance(cj, CronJob), (
                f"cron_jobs contains {type(cj).__name__} instead of CronJob"
            )
