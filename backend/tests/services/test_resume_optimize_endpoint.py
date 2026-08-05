"""TDD 测试 — 简历优化 SSE 端点"""
import json
from unittest.mock import patch


class TestResumeOptimizeEndpoint:
    """POST /api/profile/resume/optimize 与相关 GET 端点"""

    def _auth(self):
        from app.asgi import app
        from app.core.auth import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1, "username": "opt_user", "bank_mode": "public"
        }
        return app

    def _seed_resume(self, test_db):
        from app.services import resume_service
        resume_service.save_resume(1, "resume.pdf", "张三\n后端工程师\n3年经验")

    def test_optimize_requires_resume(self, client, test_db, monkeypatch):
        """T-201: 未上传简历时 400"""
        app = self._auth()
        try:
            response = client.post("/api/profile/resume/optimize", json={"position": "后端工程师"})
            assert response.status_code == 400
        finally:
            app.dependency_overrides.clear()

    def test_optimize_requires_position(self, client, test_db, monkeypatch):
        """T-202: position 缺失时 400"""
        app = self._auth()
        try:
            self._seed_resume(test_db)
            response = client.post("/api/profile/resume/optimize", json={})
            assert response.status_code == 400
        finally:
            app.dependency_overrides.clear()

    def test_optimize_streams_points_delta_done(self, client, test_db, monkeypatch):
        """T-203: SSE 事件顺序 points → delta → done，且结果存库"""
        from app.routers.profile_pkg.resume import optimize_resume_event_stream

        async def fake_raw_llm_call(user_id, **kwargs):
            return json.dumps(["量化成果", "补关键词"], ensure_ascii=False)

        async def fake_stream(messages, user_id=None, **kwargs):
            for chunk in ["# 张三", "\n## 工作经历", "\n量化成果"]:
                yield chunk

        app = self._auth()
        try:
            self._seed_resume(test_db)
            with patch("app.routers.profile_pkg.resume.raw_llm_call", fake_raw_llm_call), \
                 patch("app.routers.profile_pkg.resume.stream_llm_messages", fake_stream):
                response = client.post(
                    "/api/profile/resume/optimize", json={"position": "后端工程师"}
                )

            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]

            events = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data: ")]
            types = [e["type"] for e in events]
            assert types == ["points", "delta", "delta", "delta", "done"]
            assert events[0]["points"] == ["量化成果", "补关键词"]
            assert "".join(e["content"] for e in events if e["type"] == "delta") == "# 张三\n## 工作经历\n量化成果"

            from app.services import resume_service
            opt = resume_service.get_optimization(1)
            assert opt is not None
            assert opt["position"] == "后端工程师"
            assert opt["points"] == ["量化成果", "补关键词"]
            assert "量化成果" in opt["optimized_text"]
        finally:
            app.dependency_overrides.clear()

    def test_get_optimization_endpoint(self, client, test_db):
        """T-204: GET /api/profile/resume/optimization 返回存库结果"""
        from app.services import resume_service
        app = self._auth()
        try:
            resume_service.save_resume(1, "r.pdf", "张三")
            resume_service.save_optimization(1, "后端工程师", ["要点"], "# 张三\n新版")
            response = client.get("/api/profile/resume/optimization")
            assert response.status_code == 200
            data = response.json()
            assert data["has_optimization"] is True
            assert data["optimization"]["position"] == "后端工程师"
            assert data["optimization"]["points"] == ["要点"]
            assert "新版" in data["optimization"]["optimized_text"]
        finally:
            app.dependency_overrides.clear()

    def test_get_resume_text_endpoint(self, client, test_db):
        """T-205: GET /api/profile/resume/text 返回原文"""
        app = self._auth()
        try:
            self._seed_resume(test_db)
            response = client.get("/api/profile/resume/text")
            assert response.status_code == 200
            assert response.json()["raw_text"] == "张三\n后端工程师\n3年经验"
        finally:
            app.dependency_overrides.clear()
