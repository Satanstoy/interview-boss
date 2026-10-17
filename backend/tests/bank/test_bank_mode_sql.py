"""
历史 SQL 语法回归，以及真实 JWT/HTTP/SQLite 的 personal → mine 读取验证。
其他历史单元用例沿用既有 mock；个人题库行为不 mock 路由、权限或 SQL 写入。
"""

import pytest
from unittest.mock import patch, MagicMock


class TestBug001MixedModeSQL:
    """BUG-001: master_bank.py 混合模式 SQL 括号不匹配"""

    @pytest.mark.asyncio
    async def test_bug001_mixed_mode_sql_syntax_error(self):
        """修复前：混合模式 SQL 应有语法错误（括号不匹配）"""
        with patch("app.db.queries.get_user_job_position") as mock_pos:
            mock_pos.return_value = (1, "测试岗位")

            from app.routers.questions import _build_bank_where_clause

            user = {"id": 1, "bank_mode": "mixed", "is_admin": True}

            from_clause, where_clause, params = _build_bank_where_clause(user)

            # 检查括号匹配
            open_count = where_clause.count("(")
            close_count = where_clause.count(")")

            # 修复前：右括号比左括号多 1（BUG 存在）
            if close_count > open_count:
                pytest.fail(
                    f"BUG-001 确认：SQL 括号不匹配！"
                    f"左括号: {open_count}, 右括号: {close_count}"
                    f"\nSQL: {where_clause}"
                )

    @pytest.mark.asyncio
    async def test_bug001_mixed_mode_sql_should_be_valid(self):
        """修复后：混合模式 SQL 应该括号匹配"""
        with patch("app.db.queries.get_user_job_position") as mock_pos:
            mock_pos.return_value = (1, "测试岗位")

            from app.routers.questions import _build_bank_where_clause

            user = {"id": 1, "bank_mode": "mixed", "is_admin": True}

            from_clause, where_clause, params = _build_bank_where_clause(user)

            # 验证括号匹配
            open_count = where_clause.count("(")
            close_count = where_clause.count(")")
            assert open_count == close_count, (
                f"括号不匹配: ({open_count} vs {close_count})"
            )

            # mixed → all 口径（duplicate_of 镜像机制已废除）
            assert "((qb.owner_id IS NULL AND qb.status" in where_clause
            assert "OR qb.owner_id = ?)" in where_clause
            assert "qb.duplicate_of" not in where_clause
            assert "AND qb.deleted_at IS NULL" in where_clause

    def test_bug001_personal_mode_sql_valid(self, client, test_db):
        """Mine lists the owner's private/pending rows and excludes other banks."""
        from app.core.auth import create_access_token

        position = test_db.execute(
            "INSERT INTO job_positions(name) VALUES ('personal-mode-position')"
        ).lastrowid
        for uid in (7701, 7702):
            test_db.execute(
                "INSERT INTO users(id,username,password_hash,current_position_id,bank_mode) "
                "VALUES (?,?,'TEST_HASH',?,'personal')",
                (uid, f"personal-mode-{uid}", position),
            )
        for qid, owner, status, submitter in (
            (701, 7701, "approved", None),
            (702, None, "pending", 7701),
            (703, None, "approved", None),
            (704, 7702, "approved", None),
            (705, None, "pending", 7702),
        ):
            test_db.execute(
                "INSERT INTO question_bank(id,question,owner_id,status,submitted_by,job_position) "
                "VALUES (?, ?, ?, ?, ?, 'personal-mode-position')",
                (qid, f"personal-mode-{qid}", owner, status, submitter),
            )
            test_db.execute(
                "INSERT INTO question_position(question_id,position_id) VALUES (?,?)",
                (qid, position),
            )
        test_db.commit()
        response = client.get(
            "/api/master-bank?filter=mine",
            headers={"Authorization": "Bearer " + create_access_token(
                {"user_id": 7701, "type": "access"}
            )},
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 2
        assert {row["id"] for row in response.json()["items"]} == {701, 702}
        # Preserve the legacy personal -> mine mapping without mocking SQL or
        # coupling the assertion to its parameter count/implementation text.
        from app.routers.questions import _build_bank_where_clause

        user = dict(test_db.execute("SELECT * FROM users WHERE id=7701").fetchone())
        from_clause, where_clause, params = _build_bank_where_clause(user)
        rows = test_db.execute(f"SELECT qb.id {from_clause} {where_clause}", params)
        assert {row["id"] for row in rows} == {701, 702}

    @pytest.mark.asyncio
    async def test_bug001_public_mode_sql_valid(self):
        """公共模式 SQL 应该正确（无 bug）"""
        with patch("app.db.queries.get_user_job_position") as mock_pos:
            mock_pos.return_value = (1, "测试岗位")

            from app.routers.questions import _build_bank_where_clause

            user = {"id": 1, "bank_mode": "public", "is_admin": True}

            from_clause, where_clause, params = _build_bank_where_clause(user)

            assert "qb.owner_id IS NULL" in where_clause
            assert "qb.status = " in where_clause
            assert "qb.deleted_at IS NULL" in where_clause
            assert params == [1]  # [pos_id]


class TestBug002AnalyticsFilter:
    """BUG-002: analytics.py 缺少软删除过滤"""

    @pytest.mark.asyncio
    async def test_bug002_personal_mode_missing_deleted_at(self):
        """修复前：个人模式缺少 deleted_at IS NULL 过滤"""
        with patch("app.db.queries.get_user_job_position") as mock_pos:
            mock_pos.return_value = (1, "测试岗位")

            from app.routers.analytics import _build_analytics_bank_filter

            user = {"id": 1, "bank_mode": "personal", "is_admin": False}

            join_clause, where_clause, params = _build_analytics_bank_filter(user)

            # 修复前：缺少 deleted_at IS NULL
            if "deleted_at IS NULL" not in where_clause:
                pytest.fail(
                    f"BUG-002 确认：个人模式缺少 deleted_at IS NULL 过滤"
                    f"\nWHERE: {where_clause}"
                )

    @pytest.mark.asyncio
    async def test_bug002_personal_mode_should_have_deleted_at(self):
        """修复后：个人模式应有 deleted_at IS NULL 过滤"""
        with patch("app.db.queries.get_user_job_position") as mock_pos:
            mock_pos.return_value = (1, "测试岗位")

            from app.routers.analytics import _build_analytics_bank_filter

            user = {"id": 1, "bank_mode": "personal", "is_admin": False}

            join_clause, where_clause, params = _build_analytics_bank_filter(user)

            assert "deleted_at IS NULL" in where_clause, "应包含软删除过滤"

    @pytest.mark.asyncio
    async def test_bug002_mixed_mode_missing_deleted_at(self):
        """修复前：混合模式缺少 deleted_at IS NULL 过滤"""
        with patch("app.db.queries.get_user_job_position") as mock_pos:
            mock_pos.return_value = (1, "测试岗位")

            from app.routers.analytics import _build_analytics_bank_filter

            user = {"id": 1, "bank_mode": "mixed", "is_admin": True}

            join_clause, where_clause, params = _build_analytics_bank_filter(user)

            # 修复前：缺少 deleted_at IS NULL
            if "deleted_at IS NULL" not in where_clause:
                pytest.fail(
                    f"BUG-002 确认：混合模式缺少 deleted_at IS NULL 过滤"
                    f"\nWHERE: {where_clause}"
                )

    @pytest.mark.asyncio
    async def test_bug002_mixed_mode_should_have_deleted_at(self):
        """修复后：混合模式应有 deleted_at IS NULL 过滤"""
        with patch("app.db.queries.get_user_job_position") as mock_pos:
            mock_pos.return_value = (1, "测试岗位")

            from app.routers.analytics import _build_analytics_bank_filter

            user = {"id": 1, "bank_mode": "mixed", "is_admin": True}

            join_clause, where_clause, params = _build_analytics_bank_filter(user)

            assert "deleted_at IS NULL" in where_clause, "应包含软删除过滤"
            # 混合模式还应有括号匹配的 OR 条件
            assert "((qb.owner_id IS NULL" in where_clause

    @pytest.mark.asyncio
    async def test_bug002_public_mode_missing_deleted_at(self):
        """修复前：公共模式缺少 deleted_at IS NULL 过滤"""
        with patch("app.db.queries.get_user_job_position") as mock_pos:
            mock_pos.return_value = (1, "测试岗位")

            from app.routers.analytics import _build_analytics_bank_filter

            user = {"id": 1, "bank_mode": "public", "is_admin": True}

            join_clause, where_clause, params = _build_analytics_bank_filter(user)

            # 修复前：缺少 deleted_at IS NULL
            if "deleted_at IS NULL" not in where_clause:
                pytest.fail(
                    f"BUG-002 确认：公共模式缺少 deleted_at IS NULL 过滤"
                    f"\nWHERE: {where_clause}"
                )

    @pytest.mark.asyncio
    async def test_bug002_public_mode_should_have_deleted_at(self):
        """修复后：公共模式应有 deleted_at IS NULL 过滤"""
        with patch("app.db.queries.get_user_job_position") as mock_pos:
            mock_pos.return_value = (1, "测试岗位")

            from app.routers.analytics import _build_analytics_bank_filter

            user = {"id": 1, "bank_mode": "public", "is_admin": True}

            join_clause, where_clause, params = _build_analytics_bank_filter(user)

            assert "deleted_at IS NULL" in where_clause, "应包含软删除过滤"


class TestFallbackPaths:
    """测试没有 position_id 时的 fallback 路径"""

    @pytest.mark.asyncio
    async def test_fallback_mixed_mode_sql_valid(self):
        """fallback 路径的混合模式 SQL 应该正确"""
        with patch("app.db.queries.get_user_job_position") as mock_pos:
            mock_pos.return_value = (None, "测试岗位")  # 无 position_id

            from app.routers.questions import _build_bank_where_clause

            user = {"id": 1, "bank_mode": "mixed", "is_admin": True}

            from_clause, where_clause, params = _build_bank_where_clause(user)

            # fallback 路径的 SQL 应该括号匹配
            open_count = where_clause.count("(")
            close_count = where_clause.count(")")
            assert open_count == close_count, (
                f"括号不匹配: ({open_count} vs {close_count})"
            )

            # fallback 路径的 all 口径（duplicate_of 镜像机制已废除）
            assert "((qb.owner_id IS NULL" in where_clause
            assert "OR qb.owner_id = ?)" in where_clause
            assert "qb.duplicate_of" not in where_clause
            assert "qb.deleted_at IS NULL" in where_clause


class TestMasterBankListParamOrder:
    """题库列表追加 user_question_view JOIN 时，参数顺序不能打乱岗位过滤。"""

    def test_splits_position_join_param_before_where_params(self):
        from app.routers.questions import _split_join_and_where_params

        from_clause = (
            "FROM question_bank qb JOIN question_position qp "
            "ON qb.id = qp.question_id AND qp.position_id = ?"
        )

        join_params, where_params = _split_join_and_where_params(
            from_clause, [7, 42, "%前端%"]
        )

        assert join_params == [7]
        assert where_params == [42, "%前端%"]

    def test_keeps_fallback_params_as_where_params(self):
        from app.routers.questions import _split_join_and_where_params

        join_params, where_params = _split_join_and_where_params(
            "FROM question_bank qb", [42, "前端"]
        )

        assert join_params == []
        assert where_params == [42, "前端"]
