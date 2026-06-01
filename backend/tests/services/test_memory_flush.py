"""
TDD 测试 — Pre-compaction 记忆刷盘（O-1）

设计哲学来源: OpenClaw 的 "flush before discard" 不变量
在上下文压缩触发前，将 session notes 中的重要信息持久化到 memories 表。
"""
import pytest


class TestFlushNeeded:
    """判断是否需要记忆刷盘"""

    def test_flush_needed_high_utilization_with_notes(self, test_db):
        """高利用率 + 有 session notes → 需要刷盘"""
        from app.services.chat_service import flush_needed

        assert flush_needed(
            session_notes="[weakness] Redis 缓存策略不熟悉",
            utilization_pct=85.0,
        ) is True

    def test_flush_needed_low_utilization(self, test_db):
        """低利用率 → 不需要刷盘"""
        from app.services.chat_service import flush_needed

        assert flush_needed(
            session_notes="[weakness] Redis 缓存策略不熟悉",
            utilization_pct=50.0,
        ) is False

    def test_flush_needed_empty_notes(self, test_db):
        """空 session notes → 不需要刷盘"""
        from app.services.chat_service import flush_needed

        assert flush_needed(
            session_notes="",
            utilization_pct=85.0,
        ) is False

    def test_flush_needed_whitespace_only_notes(self, test_db):
        """纯空白 session notes → 不需要刷盘"""
        from app.services.chat_service import flush_needed

        assert flush_needed(
            session_notes="   \n  ",
            utilization_pct=85.0,
        ) is False


class TestFlushSessionToMemories:
    """从 session notes 提取并保存到 memories"""

    def test_flush_extracts_weakness(self, test_db):
        """应从 notes 中提取 weakness 并保存"""
        from app.services.chat_service import flush_session_to_memories, get_memories

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('flush_user1', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'flush_user1'").fetchone()[0]

        notes = "[weakness] Redis 缓存策略不熟悉\n[weakness] 系统设计薄弱"
        saved = flush_session_to_memories(user_id, notes)

        assert saved == 2
        memories = get_memories(user_id, memory_type="weakness")
        contents = [m["content"] for m in memories]
        assert any("Redis" in c for c in contents)
        assert any("系统设计" in c for c in contents)

    def test_flush_extracts_strength(self, test_db):
        """应从 notes 中提取 strength 并保存"""
        from app.services.chat_service import flush_session_to_memories, get_memories

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('flush_user2', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'flush_user2'").fetchone()[0]

        notes = "[strength] Java 多线程理解深入"
        saved = flush_session_to_memories(user_id, notes)

        assert saved == 1
        memories = get_memories(user_id, memory_type="strength")
        assert "Java 多线程" in memories[0]["content"]

    def test_flush_extracts_topics(self, test_db):
        """应从 notes 中提取 topics 并保存为 preference"""
        from app.services.chat_service import flush_session_to_memories, get_memories

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('flush_user3', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'flush_user3'").fetchone()[0]

        notes = "[topics] Redis, MySQL, JVM"
        saved = flush_session_to_memories(user_id, notes)

        assert saved == 1
        memories = get_memories(user_id, memory_type="preference")
        assert "Redis" in memories[0]["content"]

    def test_flush_idempotent(self, test_db):
        """重复 flush 相同 notes 不应重复保存"""
        from app.services.chat_service import flush_session_to_memories, get_memories

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('flush_user4', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'flush_user4'").fetchone()[0]

        notes = "[weakness] 缓存策略不熟悉"
        flush_session_to_memories(user_id, notes)
        flush_session_to_memories(user_id, notes)

        memories = get_memories(user_id, memory_type="weakness")
        assert len(memories) == 1

    def test_flush_ignores_pending_notes(self, test_db):
        """应忽略 [pending] 标签的临时笔记"""
        from app.services.chat_service import flush_session_to_memories

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('flush_user5', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'flush_user5'").fetchone()[0]

        notes = "[pending] 候选人正在回答: Redis\n[weakness] 缓存策略不熟悉"
        saved = flush_session_to_memories(user_id, notes)

        assert saved == 1  # 只有 weakness，没有 pending

    def test_flush_empty_notes(self, test_db):
        """空 notes 应返回 0"""
        from app.services.chat_service import flush_session_to_memories

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('flush_user6', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'flush_user6'").fetchone()[0]

        assert flush_session_to_memories(user_id, "") == 0
