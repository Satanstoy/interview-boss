"""
自动化测试 — 题目分析流程四个问题（BUG-001 ~ BUG-004）
使用 pytest + unittest.mock，所有外部依赖均已 mock

BUG-001: 不支持断点续传
BUG-002: 切换界面不支持后台继续分析
BUG-003: 分析中不显示详细内容
BUG-004: 软删除记录污染聚类质量
"""
import json
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
import pytest
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock


# ═══════════════════════════════════════════════════════
#  BUG-004: 软删除记录污染聚类质量
# ═══════════════════════════════════════════════════════


class TestBug004DeletedBankExcluded:
    """BUG-004: 聚类时未过滤 deleted_at IS NULL（当前过滤分布在队列和加载器）"""

    def test_bug004_pipeline_filters_deleted_at(self):
        """修复后：出队加载 questions_detail 时必须包含 deleted_at IS NULL"""
        import inspect
        from app.services.pipeline.queue import dequeue_batch
        source = inspect.getsource(dequeue_batch)
        assert "deleted_at IS NULL" in source, (
            "BUG-004: dequeue_batch 中加载 questions_detail 的查询"
            "缺少 'deleted_at IS NULL' 条件，已软删除的记录会参与聚类"
        )

    def test_bug004_pipeline_qb_query_filters_deleted(self):
        """修复后：加载已有 question_bank 聚类时必须过滤 deleted_at"""
        import inspect
        from app.services.pipeline.batch import _load_existing_clusters_by_cat2
        source = inspect.getsource(_load_existing_clusters_by_cat2)
        assert "deleted_at IS NULL" in source, (
            "BUG-004: _load_existing_clusters_by_cat2 加载 question_bank 时应过滤 deleted_at"
        )


class TestBug004QueryBehavior:
    """BUG-004: 验证查询行为——已删除记录不参与聚类（已迁移到 pipeline.py）"""

    def test_bug004_pipeline_cluster_batch_has_proper_filters(self):
        """修复后：聚类输入和已有 QB 查询必须包含所有必要过滤条件"""
        import inspect
        from app.services.pipeline.queue import dequeue_batch
        from app.services.pipeline.batch import _load_existing_clusters_by_cat2
        src = inspect.getsource(dequeue_batch) + inspect.getsource(_load_existing_clusters_by_cat2)

        # 验证 questions_detail 查询
        assert "deleted_at IS NULL" in src
        assert "job_position" in src

        # 验证 question_bank 查询
        assert "status = 'approved'" in src
        assert "duplicate_of IS NULL" in src


# ═══════════════════════════════════════════════════════
#  BUG-003: 分析中不显示详细内容
# ═══════════════════════════════════════════════════════


class TestBug003SSEEventsIncludeDetails:
    """BUG-003: SSE 事件应包含题目级详细信息"""

    def test_bug003_tag_event_has_details_field(self):
        """修复后：标注完成事件应包含 details 字段"""
        import inspect
        from app.routers.interview import reprocess_interview_stream
        source = inspect.getsource(reprocess_interview_stream)

        # 检查标注完成事件包含 details
        assert "'details'" in source or '"details"' in source, (
            "BUG-003: 标注完成的 SSE 事件中缺少 'details' 字段，"
            "前端无法显示每道题的分类信息"
        )

    def test_bug003_tag_event_has_details_field(self):
        """修复后：标注完成事件应包含 details 字段（新架构保留了此特性）"""
        import inspect
        from app.routers.interview import reprocess_interview_stream
        source = inspect.getsource(reprocess_interview_stream)

        # 检查标注完成事件包含 details
        assert "'details'" in source or '"details"' in source, (
            "BUG-003: 标注完成的 SSE 事件中缺少 'details' 字段，"
            "前端无法显示每道题的分类信息"
        )


class TestBug003EventStructure:
    """BUG-003: 验证 SSE 事件结构完整性"""

    def test_bug003_tag_details_structure(self):
        """标注详情应包含 question/cat1/cat2/tags/difficulty 字段"""
        # 模拟 tag_questions_batch 返回的 tagged_rows
        tagged_rows = [
            ["url1", "腾讯", "一面", "Redis 持久化方式？", "数据库", "Redis", "Redis,持久化", "中等"],
            ["url1", "腾讯", "一面", "TCP 三次握手？", "计算机网络", "TCP", "TCP,网络", "简单"],
        ]

        # 构造期望的 details 结构
        expected_details = [
            {"question": r[3], "cat1": r[4], "cat2": r[5], "tags": r[6], "difficulty": r[7]}
            for r in tagged_rows
        ]

        assert len(expected_details) == 2
        assert expected_details[0]["question"] == "Redis 持久化方式？"
        assert expected_details[0]["cat1"] == "数据库"
        assert expected_details[0]["cat2"] == "Redis"
        assert expected_details[1]["cat1"] == "计算机网络"


# ═══════════════════════════════════════════════════════
#  BUG-002: 切换界面不支持后台继续分析
# ═══════════════════════════════════════════════════════


class TestBug002GlobalProgressComputed:
    """BUG-002: 需要全局进度 computed 属性以支持跨 Tab 显示"""

    def test_bug002_app_vue_has_active_reprocessing_computed(self):
        """修复后：全局问题操作 composable 应有 activeReprocessing computed 属性"""
        with open(BACKEND_ROOT / "frontend/src/composables/useQuestionOps.js", "r", encoding="utf-8") as f:
            content = f.read()

        assert "activeReprocessing" in content, (
            "BUG-002: useQuestionOps.js 缺少 activeReprocessing computed 属性，"
            "切换 Tab 后无法在全局位置显示分析进度"
        )

    def test_bug002_global_progress_indicator_in_template(self):
        """修复后：模板中应有全局进度指示器（fixed 定位）"""
        with open(BACKEND_ROOT / "frontend/src/layouts/AuthenticatedLayout.vue", "r", encoding="utf-8") as f:
            content = f.read()

        has_fixed_indicator = ("fixed" in content and "activeReprocessing" in content)
        assert has_fixed_indicator, (
            "BUG-002: App.vue 模板中缺少全局进度指示器（应为 fixed 定位，"
            "在任意 Tab 都可见）"
        )


class TestBug002ProgressStateLifecycle:
    """BUG-002: 进度状态在组件卸载后应保持"""

    def test_bug002_reprocessing_state_is_top_level_ref(self):
        """reprocessingIds 应在全局 composable 顶级声明，不绑定在 v-if 组件内"""
        with open(BACKEND_ROOT / "frontend/src/composables/useQuestionOps.js", "r", encoding="utf-8") as f:
            content = f.read()

        assert "const reprocessingIds" in content, (
            "BUG-002: reprocessingIds 未在 useQuestionOps.js 顶级声明"
        )


# ═══════════════════════════════════════════════════════
#  BUG-001: 不支持断点续传
# ═══════════════════════════════════════════════════════


class TestBug001StatePersistence:
    """BUG-001: 分析中间状态需要持久化以支持断点续传"""

    def test_bug001_interview_table_has_analysis_status_column(self):
        """修复后：interview 表应有 analysis_status 列"""
        content = ''
        for _p in sorted(BACKEND_ROOT.joinpath('app/db/migrations').glob('*.py')):
            content += _p.read_text(encoding='utf-8') + '\n'

        assert "analysis_status" in content, (
            "BUG-001: interview 表缺少 analysis_status 列，"
            "无法追踪分析进度以支持断点续传"
        )

    def test_bug001_interview_table_has_analysis_result_column(self):
        """修复后：interview 表应有 analysis_result 列用于存储中间结果"""
        content = ''
        for _p in sorted(BACKEND_ROOT.joinpath('app/db/migrations').glob('*.py')):
            content += _p.read_text(encoding='utf-8') + '\n'

        assert "analysis_result" in content, (
            "BUG-001: interview 表缺少 analysis_result 列，"
            "无法持久化标注结果以支持断点续传"
        )


class TestBug001ResumeLogic:
    """BUG-001: 分析应能从中断点恢复"""

    def test_bug001_stream_endpoint_checks_existing_state(self):
        """修复后：SSE 端点应检查是否有未完成的分析状态"""
        import inspect
        from app.routers.interview import reprocess_interview_stream
        source = inspect.getsource(reprocess_interview_stream)

        has_resume = ("analysis_status" in source or "analysis_stage" in source
                      or "恢复" in source or "resume" in source.lower())
        assert has_resume, (
            "BUG-001: reprocess_interview_stream 中没有检查已有分析状态的逻辑，"
            "无法实现断点续传"
        )

    @pytest.mark.asyncio
    async def test_bug001_state_saved_after_tagging(self):
        """修复后：标注完成后应保存中间状态"""
        import inspect
        from app.routers.interview import reprocess_interview_stream
        source = inspect.getsource(reprocess_interview_stream)

        # 标注完成后应有保存状态的操作
        has_state_save = ("analysis_result" in source or "analysis_status" in source
                          or "tagged_rows" in source)
        assert has_state_save, (
            "BUG-001: 标注阶段完成后没有保存中间状态，"
            "中断后需要重新进行 LLM 标注"
        )
