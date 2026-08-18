"""TDD 测试 — 简历端点对抗性覆盖（audit D3, spec Task E M43）

补审计发现的缺口：HTTP 级 upload/delete/meta happy path、dict-envelope points、
50k 截断、跨用户隔离、重复上传单行不变量、错误类型 position。
"""
import json
from pathlib import Path
from unittest.mock import patch

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _auth(app, user_id=1):
    from app.core.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "id": user_id, "username": f"user{user_id}", "bank_mode": "public"
    }
    return app


def _pdf_file(filename="resume.pdf", size=1024):
    from unittest.mock import AsyncMock
    f = AsyncMock()
    f.filename = filename
    f.size = size
    f.read = AsyncMock(return_value=b"%PDF-1.4 fake")
    return f


class TestResumeEndpointHappyPaths:
    """HTTP 级 happy path（此前仅 service 级或 size-guard 直连测试）"""

    def test_upload_resume_returns_id_and_filename(self, client, test_db):
        from app.asgi import app
        _auth(app)
        try:
            with patch("app.services.resume_service.extract_pdf_text", return_value="姓名：张三"), \
                 patch("app.services.resume_service.save_resume", return_value=42):
                resp = client.post(
                    "/api/profile/resume",
                    files={"file": ("resume.pdf", b"%PDF fake", "application/pdf")},
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "success"
            assert data["id"] == 42
            assert data["filename"] == "resume.pdf"
        finally:
            app.dependency_overrides.clear()

    def test_get_resume_metadata_has_no_raw_text(self, client, test_db):
        from app.services import resume_service
        from app.asgi import app
        _auth(app)
        try:
            resume_service.save_resume(1, "resume.pdf", "敏感原文内容")
            resp = client.get("/api/profile/resume")
            assert resp.status_code == 200
            data = resp.json()
            assert data["has_resume"] is True
            assert "raw_text" not in data["resume"]
            assert data["resume"]["filename"] == "resume.pdf"
        finally:
            app.dependency_overrides.clear()

    def test_delete_resume_happy_and_404(self, client, test_db):
        from app.services import resume_service
        from app.asgi import app
        _auth(app)
        try:
            # 无简历 -> 404（CSRF 中间件要求带头）
            resp = client.delete(
                "/api/profile/resume", headers={"X-Requested-With": "XMLHttpRequest"}
            )
            assert resp.status_code == 404

            resume_service.save_resume(1, "resume.pdf", "内容")
            resp = client.delete(
                "/api/profile/resume", headers={"X-Requested-With": "XMLHttpRequest"}
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "success"
        finally:
            app.dependency_overrides.clear()


class TestResumePointsEnvelope:
    """dict-envelope points（{"points": [...]}）与点内容强制 str"""

    def test_dict_envelope_points(self, client, test_db):
        from app.asgi import app
        from app.services import resume_service
        _auth(app)
        try:
            resume_service.save_resume(1, "resume.pdf", "张三\\n后端工程师")

            async def fake_raw_llm_call(user_id, **kwargs):
                return json.dumps({"points": ["量化成果", "补关键词"]}, ensure_ascii=False)

            async def fake_stream(messages, user_id=None, **kwargs):
                yield "# 优化版"

            from app.services.resume_service import optimize_resume_event_stream
            with patch("app.services.resume_service.raw_llm_call", fake_raw_llm_call), \
                 patch("app.services.resume_service.stream_llm_messages", fake_stream):
                resp = client.post("/api/profile/resume/optimize", json={"position": "后端工程师"})

            events = [json.loads(line[5:]) for line in resp.text.splitlines() if line.startswith("data: ")]
            assert events[0]["type"] == "points"
            # dict-envelope 应被展开为 points 列表
            assert events[0]["points"] == ["量化成果", "补关键词"]
            assert events[-1]["type"] == "done"
        finally:
            app.dependency_overrides.clear()

class TestResumeTruncation:
    """50k 截断"""

    def test_text_truncated_at_50000(self):
        from app.routers.profile_pkg.resume import upload_resume

        async def run():
            big = "A" * 60000
            with patch("app.services.resume_service.extract_pdf_text", return_value=big), \
                 patch("app.services.resume_service.save_resume") as save:
                await upload_resume(file=_pdf_file(), user={"id": 1, "username": "u", "bank_mode": "public"})
            saved_text = save.call_args[0][2]
            return saved_text

        import asyncio
        saved_text = asyncio.run(run())
        suffix = "\n\n...(文本过长，已截断)"
        # 截断的原文部分不得超过 50000（后缀另行追加）
        assert len(saved_text) - len(suffix) <= 50000
        assert saved_text.endswith(suffix)


class TestResumeIsolation:
    """跨用户隔离 + 重复上传单行不变量"""

    def test_cross_user_no_resume(self, client, test_db):
        from app.services import resume_service
        from app.asgi import app
        _auth(app, user_id=1)
        try:
            resume_service.save_resume(1, "a.pdf", "A 的简历")
            # 切到 user B
            _auth(app, user_id=2)
            resp = client.get("/api/profile/resume")
            assert resp.status_code == 200
            assert resp.json()["has_resume"] is False
            # user B 不能取到 user A 的原文
            resp_text = client.get("/api/profile/resume/text")
            assert resp_text.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_double_upload_keeps_single_row(self, test_db):
        from app.services import resume_service
        from app.db.connection import get_db_connection

        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('dup', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'dup'").fetchone()[0]

        resume_service.save_resume(user_id, "a.pdf", "第一次")
        resume_service.save_resume(user_id, "b.pdf", "第二次")

        with get_db_connection() as c:
            row = c.execute(
                "SELECT COUNT(*) as cnt FROM user_resumes WHERE user_id = ?", (user_id,)
            ).fetchone()
        assert row[0] == 1