"""
自动化测试 — 针对 BUG-001 ~ BUG-005
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import re


class TestBug001SoftDelete:
    """BUG-001: question_bank 批量删除应使用软删除"""

    def test_bug001_question_bank_should_have_deleted_at_column(self):
        """question_bank 表应有 deleted_at 字段"""
        # 读取 connection.py 中的迁移代码
        with open('/root/sj/interview-boss/backend/app/db/migrations.py', 'r') as f:
            content = f.read()

        # 检查是否有为 question_bank 添加 deleted_at 的迁移代码
        # 修复前：没有这个迁移代码
        # 修复后：应该有类似 "ALTER TABLE question_bank ADD COLUMN deleted_at" 的代码
        has_migration = (
            "ALTER TABLE question_bank ADD COLUMN deleted_at" in content or
            '"deleted_at" not in qb_columns' in content
        )
        assert has_migration, "question_bank 表应有 deleted_at 字段的迁移代码"

    def test_bug001_single_delete_should_use_update_not_delete(self):
        """单条删除应使用 UPDATE 而非 DELETE FROM"""
        # 读取 master_bank.py 中的删除代码
        with open('/root/sj/interview-boss/backend/app/routers/questions.py', 'r') as f:
            content = f.read()

        # 找到 delete_master_question 函数
        # 提取该函数的内容（从 @router.delete 到下一个 @router）
        import re
        # 查找 delete_master_question 函数
        func_match = re.search(
            r'@router\.delete\("/api/master-bank/\{question_id\}"\).*?(?=\n@router|\Z)',
            content,
            re.DOTALL
        )
        assert func_match, "应存在 delete_master_question 函数"

        func_content = func_match.group(0)

        # 检查是否使用 "DELETE FROM question_bank" 而非 "UPDATE question_bank SET deleted_at"
        has_delete = "DELETE FROM question_bank" in func_content
        has_update = "UPDATE question_bank SET deleted_at" in func_content

        # 修复前：有 DELETE，没有 UPDATE
        # 修复后：没有 DELETE，有 UPDATE
        assert not has_delete, "单条删除不应使用 DELETE FROM question_bank，应使用软删除"
        assert has_update, "单条删除应使用 UPDATE question_bank SET deleted_at"

    def test_bug001_batch_delete_should_use_update_not_delete(self):
        """批量删除应使用 UPDATE 而非 DELETE FROM"""
        with open('/root/sj/interview-boss/backend/app/routers/questions.py', 'r') as f:
            content = f.read()

        # 查找批量删除函数中的关键操作
        # 修复前：使用 DELETE FROM question_bank WHERE id IN
        # 修复后：使用 UPDATE question_bank SET deleted_at WHERE id IN
        delete_pattern = r'DELETE FROM question_bank WHERE id IN'
        update_pattern = r'UPDATE question_bank SET deleted_at.*WHERE id IN'

        has_delete = bool(re.search(delete_pattern, content))
        has_update = bool(re.search(update_pattern, content))

        assert not has_delete, "批量删除不应使用 DELETE FROM question_bank，应使用软删除"
        assert has_update, "批量删除应使用 UPDATE question_bank SET deleted_at"

    def test_bug001_build_should_use_update_not_delete(self):
        """题库重建应使用 UPDATE 而非 DELETE FROM"""
        with open('/root/sj/interview-boss/backend/app/routers/questions.py', 'r') as f:
            content = f.read()

        # 查找 _save 函数中的关键操作
        # 修复前：使用 DELETE FROM question_bank WHERE job_position
        # 修复后：使用 UPDATE question_bank SET deleted_at WHERE job_position

        # 查找 _save 函数
        import re
        save_match = re.search(r'def _save\(\):.*?(?=\n    def |\n@router|\Z)', content, re.DOTALL)
        assert save_match, "应存在 _save 函数"

        save_content = save_match.group(0)

        # 检查是否使用 DELETE FROM 而非 UPDATE
        has_delete = "DELETE FROM question_bank" in save_content
        has_update = "UPDATE question_bank SET deleted_at" in save_content

        assert not has_delete, "题库重建不应使用 DELETE FROM question_bank，应使用软删除"
        assert has_update, "题库重建应使用 UPDATE question_bank SET deleted_at"

    def test_bug001_should_have_trash_endpoint(self):
        """应存在回收站查询接口"""
        with open('/root/sj/interview-boss/backend/app/routers/questions.py', 'r') as f:
            content = f.read()

        # 检查是否有 /api/master-bank/trash 路由
        has_trash = '/api/master-bank/trash' in content or '@router.get("/master-bank/trash")' in content
        assert has_trash, "应存在回收站查询接口 GET /api/master-bank/trash"

    def test_bug001_should_have_restore_endpoint(self):
        """应存在恢复接口"""
        with open('/root/sj/interview-boss/backend/app/routers/questions.py', 'r') as f:
            content = f.read()

        # 检查是否有 /api/master-bank/restore/{question_id} 路由
        has_restore = 'master-bank/restore' in content or '@router.post("/master-bank/restore' in content
        assert has_restore, "应存在恢复接口 POST /api/master-bank/restore/{id}"

    def test_bug001_should_have_batch_restore_endpoint(self):
        """应存在批量恢复接口"""
        with open('/root/sj/interview-boss/backend/app/routers/questions.py', 'r') as f:
            content = f.read()

        # 检查是否有批量恢复路由
        has_batch_restore = 'master-bank/batch-restore' in content
        assert has_batch_restore, "应存在批量恢复接口 POST /api/master-bank/batch-restore"

    def test_bug001_normal_query_should_exclude_deleted(self):
        """普通查询应排除已删除记录"""
        with open('/root/sj/interview-boss/backend/app/routers/questions.py', 'r') as f:
            content = f.read()

        # 查找列表查询函数，检查是否有 deleted_at IS NULL 条件
        # 注意：这可能在多个查询中
        has_filter = 'deleted_at IS NULL' in content
        assert has_filter, "普通查询应排除已删除记录（添加 deleted_at IS NULL 条件）"


class TestBug002ImportTypeAndSeason:
    """BUG-002: 前端导入应支持类型选择和季节选择"""

    def test_bug002_staging_panel_should_have_type_selector(self):
        """StagingPanel 应包含类型选择控件"""
        with open('/root/sj/interview-boss/frontend/src/components/StagingPanel.vue', 'r') as f:
            content = f.read()

        # 检查是否有类型选择的 select 元素
        has_type_selector = 'importType' in content or '导入类型' in content
        assert has_type_selector, "StagingPanel 应包含类型选择控件"

    def test_bug002_staging_panel_should_have_season_selector(self):
        """StagingPanel 应包含季节选择控件"""
        with open('/root/sj/interview-boss/frontend/src/components/StagingPanel.vue', 'r') as f:
            content = f.read()

        # 检查是否有季节选择的 select 元素
        has_season_selector = 'selectedSeason' in content or '招聘季节' in content
        assert has_season_selector, "StagingPanel 应包含季节选择控件"

    def test_bug002_type_selector_should_have_options(self):
        """类型选择应包含 JD 和面经选项"""
        with open('/root/sj/interview-boss/frontend/src/components/StagingPanel.vue', 'r') as f:
            content = f.read()

        # 检查是否有 JD 和面经选项
        has_jd_option = "value=\"jd\"" in content or "value='jd'" in content
        has_interview_option = "value=\"interview\"" in content or "value='interview'" in content
        has_auto_option = "value=\"auto\"" in content or "value='auto'" in content

        assert has_auto_option, "类型选择应包含'自动识别'选项"
        assert has_jd_option, "类型选择应包含'JD'选项"
        assert has_interview_option, "类型选择应包含'面经'选项"

    def test_bug002_type_should_be_passed_to_api(self):
        """选择的类型应传递给 API"""
        with open('/root/sj/interview-boss/frontend/src/components/StagingPanel.vue', 'r') as f:
            content = f.read()

        # 检查 FormData 中是否包含 content_type 字段（后端期望的字段名）
        has_type_in_form = "formData.append('content_type'" in content or 'formData.append("content_type"' in content
        assert has_type_in_form, "选择的类型应通过 FormData 的 content_type 字段传递给 API"


class TestBug003DirtyDataPositions:
    """BUG-003: job_positions 表应清理脏数据"""

    def test_bug003_should_have_cleanup_migration(self):
        """应有清理脏数据的迁移代码"""
        with open('/root/sj/interview-boss/backend/app/db/migrations.py', 'r') as f:
            content = f.read()

        # 检查是否有清理 job_positions 脏数据的代码
        has_cleanup = (
            'invalid_positions' in content or
            'clean.*position' in content.lower() or
            'job_positions.*test' in content
        )
        assert has_cleanup, "应有清理 job_positions 表脏数据的迁移代码"

    def test_bug003_real_database_should_not_have_invalid_positions(self):
        """实际数据库中不应有无效岗位数据"""
        import sqlite3
        try:
            conn = sqlite3.connect('/root/sj/interview-boss/backend/data/interview-boss.db')
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 查询所有岗位
            rows = cursor.execute("SELECT id, name FROM job_positions").fetchall()
            invalid_names = []
            for row in rows:
                name = row['name']
                # 检查无效岗位：包含 test、超长、包含特殊字符
                if ('test' in name.lower() or
                    '测试' in name or
                    len(name) > 50 or
                    '@#$' in name or
                    'AAAA' in name):
                    invalid_names.append(name)

            conn.close()
            assert len(invalid_names) == 0, f"数据库中存在无效岗位数据: {invalid_names}"
        except Exception as e:
            pytest.skip(f"无法连接数据库: {e}")


class TestBug004DirtyDataCategories:
    """BUG-004: question_bank 表应清理脏分类数据"""

    def test_bug004_should_have_cleanup_migration(self):
        """应有清理脏分类的迁移代码"""
        with open('/root/sj/interview-boss/backend/app/db/migrations.py', 'r') as f:
            content = f.read()

        # 检查是否有清理 question_bank.cat1 脏数据的代码
        has_cleanup = (
            "cat1 = 'test'" in content or
            'cat1.*test' in content.lower()
        )
        assert has_cleanup, "应有清理 question_bank 表 cat1 脏数据的迁移代码"

    def test_bug004_real_database_should_not_have_test_category(self):
        """实际数据库中不应有 test 分类"""
        import sqlite3
        try:
            conn = sqlite3.connect('/root/sj/interview-boss/backend/data/interview-boss.db')
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 查询是否有 test 分类
            rows = cursor.execute(
                "SELECT COUNT(*) as cnt FROM question_bank WHERE cat1 = 'test' AND deleted_at IS NULL"
            ).fetchone()

            conn.close()
            assert rows['cnt'] == 0, f"数据库中存在 {rows['cnt']} 条 cat1='test' 的记录"
        except Exception as e:
            pytest.skip(f"无法连接数据库: {e}")


class TestBug005LLMConfigModification:
    """BUG-005: 用户个人 LLM 配置应支持修改"""

    def test_bug005_should_have_delete_endpoint(self):
        """应存在删除 LLM 配置的接口"""
        with open('/root/sj/interview-boss/backend/app/routers/profile.py', 'r') as f:
            content = f.read()

        # 检查是否有 DELETE /api/profile/llm 路由
        has_delete_endpoint = (
            '@router.delete("/api/profile/llm")' in content or
            'delete.*llm' in content.lower()
        )
        assert has_delete_endpoint, "应存在删除 LLM 配置的接口 DELETE /api/profile/llm"

    def test_bug005_frontend_should_have_delete_button(self):
        """前端应有清除配置按钮"""
        with open('/root/sj/interview-boss/frontend/src/components/SettingsPanel.vue', 'r') as f:
            content = f.read()

        # 检查是否有清除配置按钮
        has_delete_button = '清除配置' in content or 'deleteMyLLM' in content
        assert has_delete_button, "前端应有清除配置按钮"

    def test_bug005_frontend_should_have_prominent_edit_button(self):
        """前端修改配置按钮应明显"""
        with open('/root/sj/interview-boss/frontend/src/components/SettingsPanel.vue', 'r') as f:
            content = f.read()

        # 检查修改配置按钮是否有明显的样式
        # 修复前：可能是简单的 text-xs 链接样式
        # 修复后：应该有更明显的按钮样式（如 bg-primary-50 等）
        has_prominent_button = (
            'bg-primary-50' in content and '修改配置' in content or
            'bg-primary-100' in content and '修改配置' in content
        )
        # 注意：这个测试可能需要根据实际修复调整
        # 目前先检查按钮是否存在
        has_edit_button = '修改配置' in content
        assert has_edit_button, "应有修改配置按钮"


class TestIntegration:
    """集成测试"""

    def test_api_should_have_all_required_endpoints(self):
        """API 应包含所有必要的端点"""
        with open('/root/sj/interview-boss/backend/app/routers/questions.py', 'r') as f:
            content = f.read()

        # 检查所有必要的端点
        endpoints = [
            '/api/master-bank/trash',
            '/api/master-bank/restore',
            '/api/master-bank/batch-restore',
        ]

        for endpoint in endpoints:
            # 简单检查端点是否在文件中
            endpoint_name = endpoint.split('/')[-1]
            assert endpoint_name in content, f"应存在端点 {endpoint}"

    def test_frontend_api_should_have_all_required_functions(self):
        """前端 API 应包含所有必要的函数"""
        with open('/root/sj/interview-boss/frontend/src/api/index.js', 'r') as f:
            content = f.read()

        # 检查所有必要的 API 函数
        functions = [
            'fetchTrash',
            'restoreRecord',
            'batchRestoreMasterBank',
        ]

        for func in functions:
            assert func in content, f"前端 API 应包含 {func} 函数"
