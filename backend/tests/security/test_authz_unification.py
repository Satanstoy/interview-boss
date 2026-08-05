"""
鉴权收敛回归测试（spec: docs/specs/2026-08-05-authz-unification.md）

契约：跨归属访问必须失败（cross-tenant access attempts must fail）。
覆盖 L3（bank_mode 透传）、H1（detail IDOR）、L1（save-user-answer 可见性）。
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException


def _mock_user(user_id=2, is_admin=False, bank_mode="public"):
    return {
        "id": user_id,
        "username": "test",
        "is_admin": is_admin,
        "bank_mode": bank_mode,
    }


def _ensure_user(test_db, user_id, is_admin=0):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
        "VALUES (?, ?, ?, ?)",
        (user_id, f"user{user_id}", "test-hash", is_admin),
    )
    test_db.commit()


def _insert_private_question(test_db, owner_id=999, status="approved"):
    from app.core.prompts import DEFAULT_TAXONOMY

    _ensure_user(test_db, owner_id)
    test_db.execute(
        "INSERT INTO question_bank (question, cat1, cat2, owner_id, status, job_position) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "他人私有题",
            "A.项目经验",
            "A1",
            owner_id,
            status,
            DEFAULT_TAXONOMY["job_position"],
        ),
    )
    test_db.commit()
    return test_db.execute("SELECT last_insert_rowid()").fetchone()[0]


class TestGetCurrentUserBankMode:
    """L3: get_current_user 必须从 DB 返回 bank_mode（否则题库过滤恒为 public）"""

    @pytest.mark.asyncio
    async def test_returns_bank_mode(self, client):
        from app.core.auth import get_current_user

        mock_req = MagicMock()
        mock_req.headers = {"authorization": "Bearer fake_token"}

        with patch(
            "app.core.auth.decode_token", return_value={"user_id": 1, "type": "access"}
        ):
            result = await get_current_user(mock_req)

        assert "bank_mode" in result
        assert result["bank_mode"] == "public"  # admin seed 默认值


class TestQuestionDetailVisibility:
    """H1: GET /api/master-bank/{id}/detail 必须带可见性过滤"""

    @pytest.mark.asyncio
    async def test_other_user_private_question_404(self, client, test_db):
        from app.routers.questions import get_question_detail

        qid = _insert_private_question(test_db, owner_id=999)
        user = _mock_user(user_id=2, is_admin=False)

        with pytest.raises(HTTPException) as exc_info:
            await get_question_detail(qid, user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_public_question_visible(self, client, test_db):
        from app.routers.questions import get_question_detail
        from app.core.prompts import DEFAULT_TAXONOMY

        test_db.execute(
            "INSERT INTO question_bank (question, cat1, cat2, status, job_position) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "公共题",
                "A.项目经验",
                "A1",
                "approved",
                DEFAULT_TAXONOMY["job_position"],
            ),
        )
        test_db.commit()
        qid = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]
        user = _mock_user(user_id=2, is_admin=False)

        result = await get_question_detail(qid, user)
        assert result["id"] == qid

    @pytest.mark.asyncio
    async def test_own_private_question_visible(self, client, test_db):
        from app.routers.questions import get_question_detail

        qid = _insert_private_question(test_db, owner_id=2)
        user = _mock_user(user_id=2, is_admin=False)

        result = await get_question_detail(qid, user)
        assert result["id"] == qid


class TestEditQuestionOwnership:
    """M3: 编辑权限唯一化 — 个人题仅本人可编辑，admin 也不能改他人个人题"""

    @pytest.mark.asyncio
    async def test_owner_can_edit_own_private_question(self, client, test_db):
        from app.routers.questions import edit_question
        from app.models.schemas import UpdateQuestionRequest

        qid = _insert_private_question(test_db, owner_id=2)
        user = _mock_user(user_id=2, is_admin=False)

        result = await edit_question(qid, UpdateQuestionRequest(tags="Redis"), user)
        assert result is not None

    @pytest.mark.asyncio
    async def test_admin_cannot_edit_other_user_private_question(self, client, test_db):
        from app.routers.questions import edit_question
        from app.models.schemas import UpdateQuestionRequest

        qid = _insert_private_question(test_db, owner_id=999)
        user = _mock_user(user_id=1, is_admin=True)

        with pytest.raises(HTTPException) as exc_info:
            await edit_question(qid, UpdateQuestionRequest(tags="Redis"), user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_regular_user_cannot_edit_other_private_question(
        self, client, test_db
    ):
        from app.routers.questions import edit_question
        from app.models.schemas import UpdateQuestionRequest

        qid = _insert_private_question(test_db, owner_id=999)
        user = _mock_user(user_id=2, is_admin=False)

        with pytest.raises(HTTPException) as exc_info:
            await edit_question(qid, UpdateQuestionRequest(tags="Redis"), user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_edit_public_question(self, client, test_db):
        from app.routers.questions import edit_question
        from app.models.schemas import UpdateQuestionRequest
        from app.core.prompts import DEFAULT_TAXONOMY

        test_db.execute(
            "INSERT INTO question_bank (question, cat1, cat2, status, job_position) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "公共题",
                "A.项目经验",
                "A1",
                "approved",
                DEFAULT_TAXONOMY["job_position"],
            ),
        )
        test_db.commit()
        qid = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]
        user = _mock_user(user_id=1, is_admin=True)

        result = await edit_question(qid, UpdateQuestionRequest(tags="Redis"), user)
        assert result is not None


class TestCustomDeckOwnership:
    """M2: 自定义题单纯私有 — 他人（含 public 存量）不可见、不可增删题目"""

    @staticmethod
    def _seed_public_deck(test_db, owner_id=1, deck_key="deck-a"):
        _ensure_user(test_db, owner_id)
        test_db.execute(
            "INSERT INTO practice_decks (deck_key, name, description, deck_type, owner_id, visibility) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (deck_key, "公开题单", "", "custom", owner_id, "public"),
        )
        test_db.commit()

    @pytest.mark.asyncio
    async def test_other_user_cannot_see_public_deck(self, client, test_db):
        from app.services.practice_deck_service import get_deck_definition

        self._seed_public_deck(test_db, owner_id=1, deck_key="deck-a")
        conn = test_db

        deck = get_deck_definition(conn, 2, "deck-a")
        assert deck is None

    @pytest.mark.asyncio
    async def test_owner_can_see_own_deck(self, client, test_db):
        from app.services.practice_deck_service import get_deck_definition

        self._seed_public_deck(test_db, owner_id=1, deck_key="deck-a")
        conn = test_db

        deck = get_deck_definition(conn, 1, "deck-a")
        assert deck is not None
        assert deck["kind"] == "custom"

    @pytest.mark.asyncio
    async def test_other_user_cannot_add_item_to_public_deck(self, client, test_db):
        from app.services.practice_deck_service import add_deck_item
        from app.core.prompts import DEFAULT_TAXONOMY

        self._seed_public_deck(test_db, owner_id=1, deck_key="deck-a")
        test_db.execute(
            "INSERT INTO question_bank (question, cat1, cat2, status, job_position) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "公共题",
                "A.项目经验",
                "A1",
                "approved",
                DEFAULT_TAXONOMY["job_position"],
            ),
        )
        test_db.commit()
        qid = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]

        with pytest.raises(KeyError):
            add_deck_item(test_db, 2, "deck-a", qid)

    @pytest.mark.asyncio
    async def test_owner_can_add_item_to_own_deck(self, client, test_db):
        from app.services.practice_deck_service import add_deck_item
        from app.core.prompts import DEFAULT_TAXONOMY

        self._seed_public_deck(test_db, owner_id=1, deck_key="deck-a")
        test_db.execute(
            "INSERT INTO question_bank (question, cat1, cat2, status, job_position) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "公共题",
                "A.项目经验",
                "A1",
                "approved",
                DEFAULT_TAXONOMY["job_position"],
            ),
        )
        test_db.commit()
        qid = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]

        result = add_deck_item(test_db, 1, "deck-a", qid)
        assert result["question_id"] == qid

    @pytest.mark.asyncio
    async def test_list_decks_does_not_include_other_user_deck(self, client, test_db):
        from app.services.practice_deck_service import list_decks

        self._seed_public_deck(test_db, owner_id=1, deck_key="deck-a")
        conn = test_db

        decks = list_decks(conn, 2)
        assert all(d["key"] != "deck-a" for d in decks)


class TestBuildPersonalMerge:
    """M1: 非 admin 的 build-personal 合并不得触碰公共题库数据"""

    @staticmethod
    def _seed(client, test_db, is_admin_owner=True):
        from app.core.prompts import DEFAULT_TAXONOMY

        pos = DEFAULT_TAXONOMY["job_position"]
        _ensure_user(test_db, 2)
        test_db.execute(
            "INSERT INTO question_bank (question, cat1, cat2, status, job_position, frequency, sources) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("公共题", "A.项目经验", "A1", "approved", pos, 5, "[]"),
        )
        test_db.commit()
        pub_id = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]
        test_db.execute(
            "INSERT INTO question_bank (question, cat1, cat2, status, job_position, owner_id, sources) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("个人题", "A.项目经验", "A1", "approved", pos, 2, "[]"),
        )
        test_db.commit()
        personal_id = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]
        return pub_id, personal_id

    @pytest.mark.asyncio
    async def test_non_admin_merge_does_not_touch_public_question(
        self, client, test_db
    ):
        from app.routers.bank_build import build_personal_bank

        pub_id, personal_id = self._seed(client, test_db)

        async def _consume(streaming_response):
            chunks = []
            async for chunk in streaming_response.body_iterator:
                chunks.append(chunk)
            return "".join(chunks)

        user = _mock_user(user_id=2, is_admin=False)
        with patch(
            "app.routers.bank_build.match_new_questions", new_callable=AsyncMock
        ) as mock_match:
            mock_match.return_value = {
                "matched": [{"new_id": 0, "question_bank_id": pub_id}],
                "unmatched": [],
            }
            response = await build_personal_bank(user)
            await _consume(response)

        row = test_db.execute(
            "SELECT frequency, sources FROM question_bank WHERE id = ?", (pub_id,)
        ).fetchone()
        assert row["frequency"] == 5  # 公共题 frequency 未被修改
        assert row["sources"] == "[]"

        personal_exists = test_db.execute(
            "SELECT 1 FROM question_bank WHERE id = ?", (personal_id,)
        ).fetchone()
        assert personal_exists is not None  # 个人题未被删除

    @pytest.mark.asyncio
    async def test_admin_merge_still_merges_into_public(self, client, test_db):
        from app.routers.bank_build import build_personal_bank

        pub_id, personal_id = self._seed(client, test_db)

        async def _consume(streaming_response):
            async for chunk in streaming_response.body_iterator:
                pass

        user = _mock_user(user_id=2, is_admin=True)
        with patch(
            "app.routers.bank_build.match_new_questions", new_callable=AsyncMock
        ) as mock_match:
            mock_match.return_value = {
                "matched": [{"new_id": 0, "question_bank_id": pub_id}],
                "unmatched": [],
            }
            response = await build_personal_bank(user)
            await _consume(response)

        row = test_db.execute(
            "SELECT frequency FROM question_bank WHERE id = ?", (pub_id,)
        ).fetchone()
        assert row["frequency"] == 1  # 合并后 frequency = 1（original_questions 长度）
        personal_exists = test_db.execute(
            "SELECT 1 FROM question_bank WHERE id = ?", (personal_id,)
        ).fetchone()
        assert personal_exists is None  # 个人题已并入公共题并删除


class TestTrashScope:
    """L4: 管理员回收站仅见公共题，个人题回收站仅本人可见"""

    @pytest.mark.asyncio
    async def test_admin_trash_only_public(self, client, test_db):
        from app.routers.questions_pkg.bulk import get_master_bank_trash
        from app.core.prompts import DEFAULT_TAXONOMY

        pos = DEFAULT_TAXONOMY["job_position"]
        # 公共题（已删除）
        test_db.execute(
            "INSERT INTO question_bank (question, cat1, cat2, status, job_position, deleted_at) "
            "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            ("已删公共题", "A.项目经验", "A1", "approved", pos),
        )
        # 他人个人题（已删除）
        _insert_private_question(test_db, owner_id=999)
        test_db.execute(
            "UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP WHERE owner_id = 999"
        )
        test_db.commit()

        user = _mock_user(user_id=1, is_admin=True)
        result = await get_master_bank_trash(user)

        assert len(result["items"]) == 1
        assert result["items"][0]["owner_id"] is None

    @pytest.mark.asyncio
    async def test_regular_user_trash_only_own(self, client, test_db):
        from app.routers.questions_pkg.bulk import get_master_bank_trash
        from app.core.prompts import DEFAULT_TAXONOMY

        pos = DEFAULT_TAXONOMY["job_position"]
        test_db.execute(
            "INSERT INTO question_bank (question, cat1, cat2, status, job_position, deleted_at) "
            "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            ("已删公共题", "A.项目经验", "A1", "approved", pos),
        )
        qid = _insert_private_question(test_db, owner_id=2)
        test_db.execute(
            "UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (qid,),
        )
        test_db.commit()

        user = _mock_user(user_id=2, is_admin=False)
        result = await get_master_bank_trash(user)

        assert len(result["items"]) == 1
        assert result["items"][0]["owner_id"] == 2


class TestPracticeActionsVisibility:
    """L3 遗留：practice 域动作（收藏/复习/加题单）必须与列表口径一致（all）"""

    @pytest.mark.asyncio
    async def test_toggle_star_own_private_question_ok(self, client, test_db):
        from app.routers.practice import toggle_star

        qid = _insert_private_question(test_db, owner_id=2)
        user = _mock_user(user_id=2, is_admin=False, bank_mode="public")

        result = await toggle_star(qid, user)
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_toggle_star_other_user_private_question_404(self, client, test_db):
        from app.routers.practice import toggle_star
        from fastapi import HTTPException

        qid = _insert_private_question(test_db, owner_id=999)
        user = _mock_user(user_id=2, is_admin=False, bank_mode="public")

        with pytest.raises(HTTPException) as exc_info:
            await toggle_star(qid, user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_review_own_private_question_ok(self, client, test_db):
        from app.routers.practice import review_practice_question
        from app.models.schemas import PracticeReviewRequest

        qid = _insert_private_question(test_db, owner_id=2)
        user = _mock_user(user_id=2, is_admin=False, bank_mode="public")
        req = PracticeReviewRequest(question_id=qid, rating="good")

        result = await review_practice_question(req, user)
        assert result["question_id"] == qid

    @pytest.mark.asyncio
    async def test_add_deck_item_own_private_question_ok(self, client, test_db):
        from app.routers.practice import add_practice_deck_item
        from app.models.schemas import PracticeDeckItemRequest

        qid = _insert_private_question(test_db, owner_id=2)
        _ensure_user(test_db, 2)
        test_db.execute(
            "INSERT INTO practice_decks (deck_key, name, deck_type, owner_id, visibility) "
            "VALUES (?, ?, ?, ?, ?)",
            ("my-deck", "我的题单", "custom", 2, "private"),
        )
        test_db.commit()
        user = _mock_user(user_id=2, is_admin=False, bank_mode="public")
        req = PracticeDeckItemRequest(question_id=qid)

        result = await add_practice_deck_item("my-deck", req, user)
        assert result["question_id"] == qid


class TestSaveUserAnswerVisibility:
    """L1: save-user-answer 只允许对可见题目写入"""

    @pytest.mark.asyncio
    async def test_invisible_question_404(self, client, test_db):
        from app.routers.answers import save_user_answer

        qid = _insert_private_question(test_db, owner_id=999)
        user = _mock_user(user_id=2, is_admin=False)

        with pytest.raises(HTTPException) as exc_info:
            await save_user_answer(qid, {"answer": "背诵稿"}, user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_own_question_save_success(self, client, test_db):
        from app.routers.answers import save_user_answer

        qid = _insert_private_question(test_db, owner_id=2)
        user = _mock_user(user_id=2, is_admin=False)

        result = await save_user_answer(qid, {"answer": "我的背诵稿"}, user)
        assert result["status"] == "success"
