"""
TDD 测试 — 面试上下文构建器

验证 build_interview_context 正确收集和格式化用户画像信息
"""
import pytest


class TestBuildContext:
    """面试上下文构建测试"""

    def test_build_context_returns_position(self, test_db):
        """应包含用户目标岗位信息"""
        from app.agents.chat.context_builder import build_interview_context
        from app.db.connection import get_db_connection

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin, personal_position) VALUES ('test_user', 'hash', 0, 'Java 后端开发')")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'test_user'").fetchone()[0]

        context, _ = build_interview_context(user_id)

        assert "Java 后端开发" in context
        assert "求职背景" in context

    def test_build_context_includes_taxonomy(self, test_db):
        """应包含岗位分类体系"""
        from app.agents.chat.context_builder import build_interview_context
        from app.db.connection import get_db_connection
        import json

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin, personal_position) VALUES ('test_user2', 'hash', 0, 'Python 开发')")
        conn.execute(
            "INSERT INTO taxonomy (position_name, categories_json, is_default, source) VALUES (?, ?, 1, 'system')",
            ("Python 开发", json.dumps([
                {"name": "Python 基础", "children": [{"name": "装饰器"}, {"name": "生成器"}]},
                {"name": "Web 框架", "children": [{"name": "Django"}, {"name": "Flask"}]},
            ], ensure_ascii=False))
        )
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'test_user2'").fetchone()[0]

        context, _ = build_interview_context(user_id)

        assert "考察类别" in context
        assert "Python 基础" in context

    def test_build_context_no_practice_returns_message(self, test_db):
        """无练习记录时应显示"尚未开始练习" """
        from app.agents.chat.context_builder import build_interview_context
        from app.db.connection import get_db_connection

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin, personal_position) VALUES ('test_user3', 'hash', 0, '测试岗位')")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'test_user3'").fetchone()[0]

        context, _ = build_interview_context(user_id)

        assert "尚未开始练习" in context

    def test_build_context_with_practice_stats(self, test_db):
        """有练习记录时应包含统计信息"""
        from app.agents.chat.context_builder import build_interview_context
        from app.db.connection import get_db_connection

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin, personal_position) VALUES ('test_user4', 'hash', 0, '测试岗位')")
        user_id = conn.execute("SELECT id FROM users WHERE username = 'test_user4'").fetchone()[0]

        # 插入题库题目
        conn.execute("INSERT INTO question_bank (question, cat1, status) VALUES ('Redis 数据结构', '中间件', 'approved')")
        qb_id = conn.execute("SELECT id FROM question_bank LIMIT 1").fetchone()[0]

        # 插入当前练习事件口径（user_practice_history 已停写）
        conn.execute(
            "INSERT INTO user_question_review "
            "(user_id, question_bank_id, state, last_score) VALUES (?, ?, 'review', ?)",
            (user_id, qb_id, 65),
        )
        review_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO practice_review_events "
            "(user_id, question_bank_id, review_id, rating, score, source) "
            "VALUES (?, ?, ?, 'good', ?, 'self_check')",
            (user_id, qb_id, review_id, 65),
        )
        conn.commit()

        context, _ = build_interview_context(user_id)

        assert "已练习" in context
        assert "65" in context or "薄弱" in context
