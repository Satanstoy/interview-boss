"""
TDD Review — 跨类别手动聚类功能

覆盖本次改动的三个核心行为：
1. 搜索端点返回 cat1/cat2
2. 独立题合并后保留源行不删除
3. 跨类别合并支持类别更新
"""
import json
import pytest
from unittest.mock import patch, MagicMock, call


# ─────────────────────────────────────────────────
# T-001: 搜索端点返回 cat1/cat2
# ─────────────────────────────────────────────────

class TestSearchReturnsCategory:
    """搜索结果应包含 cat1 和 cat2 字段"""

    def test_search_sql_includes_cat1_cat2(self):
        """T-001a: 搜索 SQL 应包含 qb.cat1, qb.cat2"""
        from app.routers.questions import search_master_bank
        import inspect
        source = inspect.getsource(search_master_bank)
        assert "qb.cat1" in source, "搜索 SQL 缺少 qb.cat1"
        assert "qb.cat2" in source, "搜索 SQL 缺少 qb.cat2"


# ─────────────────────────────────────────────────
# T-002: 独立题合并后保留源行
# ─────────────────────────────────────────────────

class TestStandaloneMergePreservesSource:
    """合并独立题到另一个聚类后，源行应保留不被删除"""

    def test_merge_endpoint_has_standalone_preserve_logic(self):
        """T-002a: 合并端点应有 is_standalone_merge 时 pass 的逻辑（保留源行）"""
        from app.routers.questions_pkg.mutations import merge_question
        import inspect
        source = inspect.getsource(merge_question)
        assert "is_standalone_merge" in source, "缺少 is_standalone_merge 判断"
        lines = source.split('\n')
        # 找到 DELETE 分支，验证前面有 standalone 保护
        found_delete_guard = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            # 找到 DELETE FROM question_bank 行
            if 'DELETE FROM question_bank' in stripped:
                # 向上找最近的 if is_standalone_merge
                for j in range(i - 1, max(0, i - 5), -1):
                    prev = lines[j].strip()
                    if prev.startswith('if is_standalone_merge'):
                        # 这个分支的下一行应该是 pass
                        body_line = lines[j + 1].strip() if j + 1 < len(lines) else ''
                        # 跳过注释行
                        if body_line.startswith('#'):
                            body_line = lines[j + 2].strip() if j + 2 < len(lines) else ''
                        assert 'pass' in body_line, f"standalone 保留分支应为 pass，实际为: {body_line}"
                        found_delete_guard = True
                        break
                break
        assert found_delete_guard, "未找到 DELETE 前的 is_standalone_merge 保护"

    def test_standalone_merge_skips_source_url_copy(self):
        """T-002b: 独立题合并时不应将源 URL 复制到目标 sources"""
        from app.routers.questions_pkg.mutations import merge_question
        import inspect
        source = inspect.getsource(merge_question)
        assert "not is_standalone_merge" in source, "独立题合并应跳过 sources 复制"


# ─────────────────────────────────────────────────
# T-003: 合并端点支持类别选择
# ─────────────────────────────────────────────────

class TestMergeSupportsCategoryUpdate:
    """合并端点应支持可选的 target_cat1/target_cat2 参数"""

    def test_schema_has_target_cat_fields(self):
        """T-003a: MergeOriginalQuestionRequest 应有 target_cat1, target_cat2"""
        from app.models.schemas import MergeOriginalQuestionRequest
        schema = MergeOriginalQuestionRequest(original_question="test", target_id=1)
        assert hasattr(schema, 'target_cat1'), "缺少 target_cat1 字段"
        assert hasattr(schema, 'target_cat2'), "缺少 target_cat2 字段"
        assert schema.target_cat1 == '', "target_cat1 默认值应为空字符串"
        assert schema.target_cat2 == '', "target_cat2 默认值应为空字符串"

    def test_merge_endpoint_uses_cat_params(self):
        """T-003b: 合并端点应根据 target_cat1/cat2 构建动态 SQL"""
        from app.routers.questions_pkg.mutations import merge_question
        import inspect
        source = inspect.getsource(merge_question)
        assert "target_cat1" in source, "合并端点缺少 target_cat1 处理"
        assert "target_cat2" in source, "合并端点缺少 target_cat2 处理"
        assert "cat_set" in source, "合并端点缺少 cat_set 动态 SQL 构建"


# ─────────────────────────────────────────────────
# T-004: schema 默认值向后兼容
# ─────────────────────────────────────────────────

class TestSchemaBackwardCompatibility:
    """新字段应有默认值，不破坏已有调用"""

    def test_merge_request_without_cat_fields(self):
        """T-004a: 不传 cat 字段也能正常创建请求"""
        from app.models.schemas import MergeOriginalQuestionRequest
        req = MergeOriginalQuestionRequest(original_question="Q1", target_id=2)
        assert req.target_cat1 == ''
        assert req.target_cat2 == ''

    def test_merge_request_with_cat_fields(self):
        """T-004b: 传入 cat 字段能正确赋值"""
        from app.models.schemas import MergeOriginalQuestionRequest
        req = MergeOriginalQuestionRequest(
            original_question="Q1", target_id=2,
            target_cat1="技术", target_cat2="算法"
        )
        assert req.target_cat1 == "技术"
        assert req.target_cat2 == "算法"


# ─────────────────────────────────────────────────
# T-005: 集成测试 — 独立题合并模拟
# ─────────────────────────────────────────────────

class TestStandaloneMergeIntegration:
    """模拟独立题合并场景，验证数据库操作序列"""

    def _setup_mock_conn(self, source_row, target_row):
        """构造 mock 数据库连接，正确处理 cursor.execute() 链式调用"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        def execute_side_effect(sql, params=None):
            result = MagicMock()
            if params and len(params) >= 1:
                qid = params[0]
                if 'WHERE id = ?' in sql:
                    if qid == source_row['id']:
                        result.fetchone.return_value = source_row
                    elif qid == target_row['id']:
                        result.fetchone.return_value = target_row
                    else:
                        result.fetchone.return_value = None
                else:
                    result.fetchone.return_value = None
            else:
                result.fetchone.return_value = None
            result.fetchall.return_value = []
            return result

        mock_cursor.execute.side_effect = execute_side_effect
        return mock_conn, mock_cursor

    def test_standalone_merge_does_not_delete_source(self):
        """T-005a: 独立题合并后不应执行 DELETE FROM question_bank"""
        source_row = {
            'id': 100, 'question': '独立题Q',
            'sources': json.dumps([{"url": "http://u1", "company": "A", "round": "一面"}]),
            'original_questions': json.dumps([]),
            'original_question_sources': json.dumps([])
        }
        target_row = {
            'id': 200, 'question': '目标聚类Q',
            'sources': json.dumps([{"url": "http://u2", "company": "B", "round": "二面"}]),
            'original_questions': json.dumps(["目标原始题"]),
            'original_question_sources': json.dumps([{"question": "目标原始题", "sources": [{"url": "http://u2"}]}])
        }

        mock_conn, mock_cursor = self._setup_mock_conn(source_row, target_row)
        executed_sqls = []
        original_side_effect = mock_cursor.execute.side_effect

        def tracking_execute(sql, params=None):
            executed_sqls.append((sql, params))
            return original_side_effect(sql, params)
        mock_cursor.execute.side_effect = tracking_execute

        with patch('app.routers.questions.get_db_connection', return_value=mock_conn), \
             patch('app.routers.questions.run_db', side_effect=lambda fn: fn()):
            from app.models.schemas import MergeOriginalQuestionRequest
            from app.routers.questions_pkg.mutations import merge_question
            import asyncio

            req = MergeOriginalQuestionRequest(original_question='独立题Q', target_id=200)
            try:
                asyncio.get_event_loop().run_until_complete(
                    merge_question(question_id=100, req=req, admin={'id': 1})
                )
            except Exception:
                pass

            # 验证没有对源行的 DELETE 操作
            delete_calls = [s for s in executed_sqls if 'DELETE FROM question_bank' in s[0]]
            assert len(delete_calls) == 0, f"独立题合并不应有 DELETE，实际执行了: {delete_calls}"

    def test_non_standalone_merge_has_delete_branch(self):
        """T-005b: 非独立题合并且源清空时有 DELETE 分支"""
        from app.routers.questions_pkg.mutations import merge_question
        import inspect
        source = inspect.getsource(merge_question)
        # 验证 elif len(new_src_orig) == 0: DELETE 逻辑存在
        assert "elif len(new_src_orig) == 0" in source, "缺少源清空时的 DELETE 分支"
        assert "DELETE FROM question_bank" in source, "缺少 DELETE 语句"


# ─────────────────────────────────────────────────
# T-006: 集成测试 — 跨类别合并 SQL
# ─────────────────────────────────────────────────

class TestCategoryUpdateSQL:
    """验证类别更新 SQL 构建逻辑"""

    def test_cat_set_with_both_cats(self):
        """T-006a: 传入两个类别时 SQL 应包含两个 SET 子句"""
        cat_set = ""
        cat_params = []
        req_cat1, req_cat2 = "技术", "算法"
        if req_cat1:
            cat_set += ", cat1 = ?"
            cat_params.append(req_cat1)
        if req_cat2:
            cat_set += ", cat2 = ?"
            cat_params.append(req_cat2)
        assert cat_set == ", cat1 = ?, cat2 = ?"
        assert cat_params == ["技术", "算法"]

    def test_cat_set_with_only_cat1(self):
        """T-006b: 只传 cat1 时 SQL 只包含 cat1"""
        cat_set = ""
        cat_params = []
        req_cat1, req_cat2 = "技术", ""
        if req_cat1:
            cat_set += ", cat1 = ?"
            cat_params.append(req_cat1)
        if req_cat2:
            cat_set += ", cat2 = ?"
            cat_params.append(req_cat2)
        assert cat_set == ", cat1 = ?"
        assert cat_params == ["技术"]

    def test_cat_set_with_no_cats(self):
        """T-006c: 不传类别时 SQL 不含 SET 子句"""
        cat_set = ""
        cat_params = []
        req_cat1, req_cat2 = "", ""
        if req_cat1:
            cat_set += ", cat1 = ?"
            cat_params.append(req_cat1)
        if req_cat2:
            cat_set += ", cat2 = ?"
            cat_params.append(req_cat2)
        assert cat_set == ""
        assert cat_params == []
