"""
TDD 测试 — 跨对话会话搜索（O-2）

设计哲学来源: Hermes 的 FTS5 会话搜索 + Claude Code 的 LLM 选记忆
用户开始新面试时，搜索历史对话中的相关面试经验。
"""
import pytest


class TestSearchPastSessions:
    """跨对话历史搜索"""

    def test_search_finds_matching_sessions(self, test_db):
        """按关键词搜索应返回包含该关键词的历史对话"""
        from app.services.chat_service import (
            create_conversation, save_message, search_past_sessions,
        )

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('search_user1', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'search_user1'").fetchone()[0]

        # 创建历史对话
        conv = create_conversation(user_id, "free_practice", title="Redis 面试练习")
        save_message(conv["id"], "user", "Redis 的五种数据结构是什么？")
        save_message(conv["id"], "assistant", "Redis 支持 String、List、Hash、Set、Sorted Set...")

        results = search_past_sessions(user_id, ["Redis"])

        assert len(results) >= 1
        assert any("Redis" in r["summary"] for r in results)

    def test_search_no_results(self, test_db):
        """搜索不存在的话题应返回空列表"""
        from app.services.chat_service import search_past_sessions

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('search_user2', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'search_user2'").fetchone()[0]

        results = search_past_sessions(user_id, ["不存在的技术XYZ"])

        assert results == []

    def test_search_respects_limit(self, test_db):
        """结果数应受 limit 参数限制"""
        from app.services.chat_service import (
            create_conversation, save_message, search_past_sessions,
        )

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('search_user3', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'search_user3'").fetchone()[0]

        # 创建 5 个对话
        for i in range(5):
            conv = create_conversation(user_id, "free_practice", title=f"Java 面试 #{i}")
            save_message(conv["id"], "user", f"Java 多线程问题 {i}")
            save_message(conv["id"], "assistant", f"回答 {i}")

        results = search_past_sessions(user_id, ["Java"], limit=3)

        assert len(results) <= 3

    def test_search_excludes_current_conversation(self, test_db):
        """搜索应排除当前对话"""
        from app.services.chat_service import (
            create_conversation, save_message, search_past_sessions,
        )

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('search_user4', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'search_user4'").fetchone()[0]

        conv1 = create_conversation(user_id, "free_practice", title="MySQL 面试")
        save_message(conv1["id"], "user", "MySQL 索引优化")

        conv2 = create_conversation(user_id, "free_practice", title="当前 MySQL 面试")
        save_message(conv2["id"], "user", "MySQL 事务隔离级别")

        results = search_past_sessions(user_id, ["MySQL"], exclude_conv_id=conv2["id"])

        assert all(r["conversation_id"] != conv2["id"] for r in results)

    def test_search_returns_conversation_metadata(self, test_db):
        """搜索结果应包含对话标题和时间"""
        from app.services.chat_service import (
            create_conversation, save_message, search_past_sessions,
        )

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('search_user5', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'search_user5'").fetchone()[0]

        conv = create_conversation(user_id, "free_practice", title="Spring 面试")
        save_message(conv["id"], "user", "Spring IOC 容器原理")

        results = search_past_sessions(user_id, ["Spring"])

        assert len(results) >= 1
        r = results[0]
        assert "conversation_id" in r
        assert "title" in r
        assert "summary" in r
        assert "created_at" in r


class TestFormatSessionRecall:
    """格式化搜索结果为上下文字符串"""

    def test_format_returns_readable_string(self, test_db):
        """应格式化为可读的上下文文本"""
        from app.services.chat_service import format_session_recall

        sessions = [
            {
                "conversation_id": "abc",
                "title": "Redis 面试",
                "summary": "讨论了 Redis 缓存策略和穿透问题",
                "created_at": "2026-05-20",
            }
        ]
        result = format_session_recall(sessions)

        assert "Redis" in result
        assert "历史面试" in result or "面试" in result

    def test_format_empty_list(self, test_db):
        """空列表应返回空字符串"""
        from app.services.chat_service import format_session_recall

        assert format_session_recall([]) == ""

    def test_format_multiple_sessions(self, test_db):
        """多个结果应全部格式化"""
        from app.services.chat_service import format_session_recall

        sessions = [
            {"conversation_id": "a", "title": "Redis 面试", "summary": "缓存策略", "created_at": "2026-05-20"},
            {"conversation_id": "b", "title": "MySQL 面试", "summary": "索引优化", "created_at": "2026-05-19"},
        ]
        result = format_session_recall(sessions)

        assert "Redis" in result
        assert "MySQL" in result
