"""
TDD 测试 — 简历记忆单一事实源同步（audit D9, spec Task A M39）

红-绿-重构：resume_service.save_resume/delete_resume 尚未同步停用
chat_memories 简历记忆；recall_memories 尚未以 user_resumes 为事实源。
"""
from unittest.mock import patch


class TestResumeChatMemorySync:
    """save/delete 简历时同步停用 chat_memories 简历记忆"""

    def _make_user(self, test_db, name):
        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, 'hash', 0)", (name,))
        conn.commit()
        return conn.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()[0]

    def test_save_resume_deactivates_stale_resume_memory(self, test_db):
        """T-A1: 先有旧简历记忆，save_resume 新简历后旧记忆不再被返回"""
        from app.services import resume_service
        from app.services.chat_memory_service import save_resume_memory, get_resume_memory

        user_id = self._make_user(test_db, "a1_user")
        save_resume_memory(user_id, "旧简历内容")
        assert get_resume_memory(user_id) == "旧简历内容"

        resume_service.save_resume(user_id, "new.pdf", "新简历内容")

        # 旧 resume 记忆必须被停用（单一事实源在 user_resumes；chat 记忆可能为 None 或已更新）
        current = get_resume_memory(user_id)
        assert current is None or "旧简历" not in current

    def test_delete_resume_deactivates_resume_memory(self, test_db):
        """T-A2: delete_resume 后 chat 简历记忆为 None（已删除简历的 PII 不再召回）"""
        from app.services import resume_service
        from app.services.chat_memory_service import save_resume_memory, get_resume_memory

        user_id = self._make_user(test_db, "a2_user")
        resume_service.save_resume(user_id, "r.pdf", "内容")
        save_resume_memory(user_id, "简历记忆")
        assert get_resume_memory(user_id) == "简历记忆"

        resume_service.delete_resume(user_id)

        assert get_resume_memory(user_id) is None

    async def test_recall_memories_prefers_user_resumes(self):
        """T-A3: chat agent recall 简历时优先 user_resumes，而非过期的 chat 记忆"""
        from app.agents.chat.nodes import recall_memories

        state = {
            "user_id": 1,
            "user_message": "你好",
            "mode": "free_practice",
            "conversation_id": "c1",
        }
        with patch("app.services.chat_service.get_resume_memory", return_value="旧简历"), \
             patch("app.services.resume_service.get_resume_text", return_value="新简历"):
            result = await recall_memories(state)

        assert result["resume_summary"] == "新简历"

    async def test_recall_memories_falls_back_to_chat_memory(self):
        """T-A4: 无 user_resumes 时回退到 chat 记忆（兼容旧对话）"""
        from app.agents.chat.nodes import recall_memories

        state = {
            "user_id": 2,
            "user_message": "你好",
            "mode": "free_practice",
            "conversation_id": "c2",
        }
        with patch("app.services.chat_service.get_resume_memory", return_value="对话中上传的简历"), \
             patch("app.services.resume_service.get_resume_text", return_value=None):
            result = await recall_memories(state)

        assert result["resume_summary"] == "对话中上传的简历"
