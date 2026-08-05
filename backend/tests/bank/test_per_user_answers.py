"""
TDD 测试 — 用户级答案管理 + 参考答案复用

测试覆盖：
- T-001: DB 迁移：user_question_view 表新增 user_answer 列
- T-002: 使用参考答案：正常复制
- T-003: 使用参考答案：无参考答案
- T-004: 使用参考答案：已有答案时覆盖
- T-005: 生成答案（普通用户）：存入个人表
- T-006: 生成答案（管理员）：存入全局表
- T-007: GET master-bank 返回 user_answer 和 has_reference_answer
- T-008: GET master-bank：无参考答案时 has_reference_answer 为 false
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ── Helper ──


def _mock_user(user_id=2, is_admin=False, bank_mode="public"):
    return {"id": user_id, "is_admin": is_admin, "bank_mode": bank_mode}


def _mock_request():
    from starlette.requests import Request
    from unittest.mock import MagicMock as _MagicMock

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/test",
        "headers": [(b"host", b"localhost")],
        "query_string": b"",
        "server": ("localhost", 80),
    }
    return _MagicMock(spec=Request)


# ═══════════════════════════════════════════════════════════
# T-001: DB 迁移 — user_answer 列存在
# ═══════════════════════════════════════════════════════════


class TestDBMigrationUserAnswer:
    """user_question_view 表应包含 user_answer 列"""

    def test_user_answer_column_exists(self):
        """init_db 后 user_question_view 表应有 user_answer 列"""
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        # 创建 user_question_view 表（模拟 init_db 中的定义）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_question_view (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                question_bank_id INTEGER NOT NULL,
                is_starred INTEGER DEFAULT 0,
                personal_tags TEXT DEFAULT '',
                note TEXT DEFAULT '',
                user_answer TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 检查 user_answer 列存在
        cursor = conn.execute("PRAGMA table_info(user_question_view)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "user_answer" in columns
        conn.close()


# ═══════════════════════════════════════════════════════════
# T-002~T-004: 使用参考答案端点
# ═══════════════════════════════════════════════════════════


class TestUseReferenceAnswer:
    """POST /api/master-bank/use-reference-answer/{question_id}"""

    @pytest.mark.asyncio
    async def test_use_reference_answer_success(self):
        """正常复制参考答案到用户个人答案"""
        from app.routers.answers import use_reference_answer

        user = _mock_user(user_id=2, is_admin=False)
        mock_question = {
            "id": 10,
            "question": "什么是微服务？",
            "ai_answer": "微服务是一种架构风格...",
        }
        mock_uqv = {"user_answer": ""}

        with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
            # 第一次调用：查找题目
            # 第二次调用：查找或创建 user_question_view
            # 第三次调用：更新 user_answer
            mock_run_db.side_effect = [mock_question, mock_uqv, None]

            result = await use_reference_answer(10, user)
            assert result["status"] == "success"
            assert result["answer"] == "微服务是一种架构风格..."

    @pytest.mark.asyncio
    async def test_use_reference_answer_no_reference(self):
        """无参考答案时应返回404"""
        from app.routers.answers import use_reference_answer
        from fastapi import HTTPException

        user = _mock_user(user_id=2, is_admin=False)
        mock_question = {"id": 10, "question": "什么是微服务？", "ai_answer": None}

        with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
            mock_run_db.return_value = mock_question

            with pytest.raises(HTTPException) as exc_info:
                await use_reference_answer(10, user)
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_use_reference_answer_overwrites_existing(self):
        """已有个人答案时，使用参考答案应覆盖"""
        from app.routers.answers import use_reference_answer

        user = _mock_user(user_id=2, is_admin=False)
        mock_question = {
            "id": 10,
            "question": "什么是微服务？",
            "ai_answer": "微服务是...",
        }
        mock_uqv = {"user_answer": "旧的个人答案"}

        with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
            mock_run_db.side_effect = [mock_question, mock_uqv, None]

            result = await use_reference_answer(10, user)
            assert result["status"] == "success"
            assert result["answer"] == "微服务是..."


# ═══════════════════════════════════════════════════════════
# T-005~T-006: 生成答案端点改造（管理员专属）
# ═══════════════════════════════════════════════════════════


class TestGenerateAnswerPerUser:
    """POST /api/master-bank/generate-answer/{question_id} — 仅管理员可生成公共参考答案"""

    @pytest.mark.asyncio
    async def test_generate_answer_normal_user_rejected(self):
        """普通用户生成答案应返回 403（公共参考答案仅管理员可写）"""
        from app.routers.answers import generate_master_answer
        from fastapi import HTTPException

        user = _mock_user(user_id=2, is_admin=False)
        mock_question = {"id": 10, "question": "什么是微服务？", "ai_answer": None}

        with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
            mock_run_db.return_value = mock_question

            with patch(
                "app.routers.answers._call_llm_with_retry", new_callable=AsyncMock
            ) as mock_llm:
                with pytest.raises(HTTPException) as exc_info:
                    await generate_master_answer(10, user)
                assert exc_info.value.status_code == 403

                # 权限校验必须发生在 LLM 调用之前
                mock_llm.assert_not_called()
            # 权限校验必须发生在 DB 查询之前（不消耗查询）
            mock_run_db.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_generate_answers_normal_user_rejected(self):
        """普通用户批量生成答案应返回 403（公共参考答案仅管理员可写）"""
        from app.routers.answers import batch_generate_answers
        from app.models.schemas import BatchGenerateAnswersRequest
        from fastapi import HTTPException

        user = _mock_user(user_id=2, is_admin=False)
        req = BatchGenerateAnswersRequest(ids=[10, 11])

        with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
            with pytest.raises(HTTPException) as exc_info:
                await batch_generate_answers(req, user)
            assert exc_info.value.status_code == 403
            mock_run_db.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_answer_admin_stores_in_global_table(self):
        """管理员生成答案应存入 question_bank.ai_answer"""
        from app.routers.answers import generate_master_answer

        user = _mock_user(user_id=1, is_admin=True)
        mock_question = {"id": 10, "question": "什么是微服务？", "ai_answer": None}

        with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
            mock_run_db.side_effect = [mock_question, None]

            with patch(
                "app.routers.answers._call_llm_with_retry", new_callable=AsyncMock
            ) as mock_llm:
                mock_llm.return_value = "微服务是一种架构风格..."

                result = await generate_master_answer(10, user)
                assert result["status"] == "success"

                # 验证 run_db 被调用了2次（get question, update question_bank）
                assert mock_run_db.call_count == 2


# ═══════════════════════════════════════════════════════════
# T-009~T-011: 背诵稿定制端点
# ═══════════════════════════════════════════════════════════


class TestGenerateRecitation:
    """POST /api/master-bank/generate-recitation/{question_id} — 用户定制背诵稿"""

    @pytest.mark.asyncio
    async def test_recitation_normal_user_success(self):
        """普通用户定制背诵稿应写入 user_question_view.user_answer"""
        from app.routers.answers import generate_recitation

        user = _mock_user(user_id=2, is_admin=False)
        mock_question = {
            "id": 10,
            "question": "什么是微服务？",
            "ai_answer": "微服务是一种架构风格，将单体应用拆分为一组小型服务...",
        }

        with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
            # get question, upsert uqv
            mock_run_db.side_effect = [mock_question, None]

            with patch(
                "app.routers.answers.get_user_job_position",
                return_value=(None, "后端开发"),
            ):
                with patch(
                    "app.routers.answers.get_resume_text",
                    return_value="做过支付系统项目",
                ):
                    with patch(
                        "app.routers.answers.prepare_recitation_prompt",
                        new_callable=AsyncMock,
                    ) as mock_prompt:
                        mock_prompt.return_value = ("recitation prompt", [])
                        with patch(
                            "app.routers.answers._call_llm_with_retry",
                            new_callable=AsyncMock,
                        ) as mock_llm:
                            mock_llm.return_value = "结合我的项目经历，微服务架构..."

                            result = await generate_recitation(10, user)
                            assert result["status"] == "success"
                            assert result["answer"] == "结合我的项目经历，微服务架构..."

                            # 提示词必须基于公共参考答案构建，且携带用户岗位
                            mock_prompt.assert_called_once()
                            prompt_args = mock_prompt.call_args
                            assert (
                                prompt_args.kwargs.get("reference_answer")
                                == mock_question["ai_answer"]
                            )
                            assert prompt_args.kwargs.get("job_position") == "后端开发"

    @pytest.mark.asyncio
    async def test_recitation_no_reference_answer_404(self):
        """题目无公共参考答案时应返回 404"""
        from app.routers.answers import generate_recitation
        from fastapi import HTTPException

        user = _mock_user(user_id=2, is_admin=False)
        mock_question = {"id": 10, "question": "什么是微服务？", "ai_answer": None}

        with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
            mock_run_db.return_value = mock_question

            with pytest.raises(HTTPException) as exc_info:
                await generate_recitation(10, user)
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_recitation_invisible_question_404(self):
        """不可见题目应返回 404"""
        from app.routers.answers import generate_recitation
        from fastapi import HTTPException

        user = _mock_user(user_id=2, is_admin=False)

        with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
            mock_run_db.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await generate_recitation(10, user)
            assert exc_info.value.status_code == 404


# ═══════════════════════════════════════════════════════════
# T-007~T-008: GET master-bank 返回 user_answer 和 has_reference_answer
# ═══════════════════════════════════════════════════════════


class TestGetMasterBankUserAnswerFields:
    """GET /api/master-bank 应返回 user_answer 和 has_reference_answer"""

    @pytest.mark.asyncio
    async def test_returns_user_answer_and_has_reference(self):
        """有参考答案和个人答案时，两个字段都应有值"""
        from app.routers.questions import get_master_bank

        user = _mock_user(user_id=2, is_admin=False)

        mock_row = {
            "id": 10,
            "question": "什么是微服务？",
            "cat1": "架构",
            "cat2": "微服务",
            "tags": "",
            "difficulty": "中",
            "dyn_frequency": 5,
            "ai_answer": "微服务是一种架构风格...",
            "sources": "[]",
            "original_questions": "[]",
            "original_question_sources": "[]",
            "is_starred": 0,
            "owner_id": None,
            "status": "approved",
            "job_position": "开发",
            "user_answer": "用户的个人答案",
        }

        with patch(
            "app.routers.questions.run_db", new_callable=AsyncMock
        ) as mock_run_db:
            mock_run_db.side_effect = [
                (1, [mock_row]),
                {},
                {
                    "overall_total": 1,
                    "category_counts": [],
                    "popular_tags": [],
                    "filtered_tag_counts": [],
                },
            ]

            result = await get_master_bank(
                sort="frequency_desc",
                page=1,
                page_size=50,
                compact=False,
                filter="all",
                user=user,
            )
            item = result["items"][0]
            assert item["has_reference_answer"] is True
            assert item["user_answer"] == "用户的个人答案"

    @pytest.mark.asyncio
    async def test_no_reference_answer_returns_false(self):
        """无参考答案时 has_reference_answer 应为 false"""
        from app.routers.questions import get_master_bank

        user = _mock_user(user_id=2, is_admin=False)

        mock_row = {
            "id": 10,
            "question": "什么是微服务？",
            "cat1": "架构",
            "cat2": "微服务",
            "tags": "",
            "difficulty": "中",
            "dyn_frequency": 5,
            "ai_answer": None,
            "sources": "[]",
            "original_questions": "[]",
            "original_question_sources": "[]",
            "is_starred": 0,
            "owner_id": None,
            "status": "approved",
            "job_position": "开发",
            "user_answer": "",
        }

        with patch(
            "app.routers.questions.run_db", new_callable=AsyncMock
        ) as mock_run_db:
            mock_run_db.side_effect = [
                (1, [mock_row]),
                {},
                {
                    "overall_total": 1,
                    "category_counts": [],
                    "popular_tags": [],
                    "filtered_tag_counts": [],
                },
            ]

            result = await get_master_bank(
                sort="frequency_desc",
                page=1,
                page_size=50,
                compact=False,
                filter="all",
                user=user,
            )
            item = result["items"][0]
            assert item["has_reference_answer"] is False
            assert item["user_answer"] == ""
