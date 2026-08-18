"""TDD 测试 — 简历优化 SSE 端点"""
import json
from pathlib import Path
from unittest.mock import patch

FIXTURES_DIR = Path(__file__).parent / "fixtures"


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

    def test_optimize_stream_failure_emits_error_and_no_persist(self, client, test_db, monkeypatch):
        """T-206: 流式阶段 LLM 异常 → error 事件且不落库"""
        async def fake_raw_llm_call(user_id, **kwargs):
            return json.dumps(["要点"], ensure_ascii=False)

        async def fake_stream_raise(messages, user_id=None, **kwargs):
            raise RuntimeError("模拟 LLM 故障")
            yield

        app = self._auth()
        try:
            self._seed_resume(test_db)
            with patch("app.routers.profile_pkg.resume.raw_llm_call", fake_raw_llm_call), \
                 patch("app.routers.profile_pkg.resume.stream_llm_messages", fake_stream_raise):
                response = client.post(
                    "/api/profile/resume/optimize", json={"position": "后端工程师"}
                )

            assert response.status_code == 200
            events = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data: ")]
            assert events[0]["type"] == "points"
            assert events[-1]["type"] == "error"
            assert "优化失败" in events[-1]["message"]

            from app.services import resume_service
            assert resume_service.get_optimization(1) is None
        finally:
            app.dependency_overrides.clear()

    def test_optimize_invalid_points_json_degrades_to_empty(self, client, test_db, monkeypatch):
        """T-207: 要点 JSON 解析失败 → points 为空数组但流程继续"""
        async def fake_raw_llm_call_bad(user_id, **kwargs):
            return "not json at all"

        async def fake_stream(messages, user_id=None, **kwargs):
            yield "# 优化版"

        app = self._auth()
        try:
            self._seed_resume(test_db)
            with patch("app.routers.profile_pkg.resume.raw_llm_call", fake_raw_llm_call_bad), \
                 patch("app.routers.profile_pkg.resume.stream_llm_messages", fake_stream):
                response = client.post(
                    "/api/profile/resume/optimize", json={"position": "后端工程师"}
                )

            events = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data: ")]
            assert events[0]["type"] == "points"
            assert events[0]["points"] == []
            assert events[-1]["type"] == "done"

            from app.services import resume_service
            opt = resume_service.get_optimization(1)
            assert opt is not None
            assert opt["points"] == []
        finally:
            app.dependency_overrides.clear()


class TestChatExtractPdf:
    """POST /api/chat/extract-pdf 复用 resume_service 提取逻辑"""

    def _auth(self):
        from app.asgi import app
        from app.core.auth import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1, "username": "opt_user", "bank_mode": "public"
        }
        return app

    def test_extract_pdf_uses_resume_service(self, client, test_db):
        """T-301: /api/chat/extract-pdf 使用 resume_service.extract_pdf_text（pdfplumber）"""
        app = self._auth()
        try:
            fixture = FIXTURES_DIR / "chinese_resume.pdf"
            assert fixture.exists()
            with patch("app.routers.chat.resume_service.extract_pdf_text") as mock_extract:
                mock_extract.return_value = "教育背景\n项目"
                with open(fixture, "rb") as f:
                    response = client.post(
                        "/api/chat/extract-pdf",
                        files={"file": ("resume.pdf", f.read(), "application/pdf")},
                        headers={"X-Requested-With": "XMLHttpRequest"},
                    )

            assert response.status_code == 200
            assert response.json() == {"status": "success", "text": "教育背景\n项目"}
            mock_extract.assert_called_once()
        finally:
            app.dependency_overrides.clear()

    def test_extract_pdf_rejects_non_pdf(self, client, test_db):
        """T-302: 非 PDF 文件 400"""
        app = self._auth()
        try:
            response = client.post(
                "/api/chat/extract-pdf",
                files={"file": ("resume.txt", b"hello", "text/plain")},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            assert response.status_code == 400
        finally:
            app.dependency_overrides.clear()

    def test_extract_pdf_empty_text_400(self, client, test_db):
        """T-303: 提取为空（扫描件）400"""
        app = self._auth()
        try:
            fixture = FIXTURES_DIR / "chinese_resume.pdf"
            with patch("app.routers.chat.resume_service.extract_pdf_text") as mock_extract:
                mock_extract.return_value = ""
                with open(fixture, "rb") as f:
                    response = client.post(
                        "/api/chat/extract-pdf",
                        files={"file": ("resume.pdf", f.read(), "application/pdf")},
                        headers={"X-Requested-With": "XMLHttpRequest"},
                    )
            assert response.status_code == 400
        finally:
            app.dependency_overrides.clear()

class TestPdfExtractOffload:
    """Task B (M40): async 路由中的 pdfplumber 解析必须经 asyncio.to_thread 离开事件循环"""

    async def test_upload_resume_offloads_extract_to_thread(self):
        from unittest.mock import AsyncMock, patch
        from app.routers.profile_pkg.resume import upload_resume

        f = AsyncMock()
        f.filename = "resume.pdf"
        f.size = 1024
        f.read = AsyncMock(return_value=b"%PDF-1.4 fake")

        with patch("app.services.resume_service.extract_pdf_text", return_value="姓名：张三") as extract, \
             patch("app.services.resume_service.save_resume", return_value=7) as save, \
             patch("app.routers.profile_pkg.resume.asyncio.to_thread") as to_thread:
            to_thread.side_effect = lambda fn, *a, **k: fn(*a, **k)  # 同步执行以便断言
            result = await upload_resume(file=f, user={"id": 1, "username": "u", "bank_mode": "public"})

        assert result["status"] == "success"
        # asyncio 是全局单例：run_db 内部的 asyncio.to_thread 也走同一 mock，
        # 因此断言存在一次「以 extract_pdf_text 为第一参数」的 offload 调用即可
        assert any(
            call.args[0] is extract for call in to_thread.call_args_list
        ), "extract_pdf_text 必须经 asyncio.to_thread 离开事件循环"
        save.assert_called_once()

    async def test_chat_extract_pdf_offloads_extract_to_thread(self):
        from unittest.mock import AsyncMock, patch
        from app.routers.chat import extract_pdf

        f = AsyncMock()
        f.filename = "resume.pdf"
        f.size = 1024
        f.read = AsyncMock(return_value=b"%PDF-1.4 fake")

        with patch("app.services.resume_service.extract_pdf_text", return_value="教育背景") as extract, \
             patch("app.routers.chat.asyncio.to_thread") as to_thread:
            to_thread.side_effect = lambda fn, *a, **k: fn(*a, **k)
            result = await extract_pdf(file=f, user={"id": 1, "username": "u", "bank_mode": "public"})

        assert result["status"] == "success"
        assert any(
            call.args[0] is extract for call in to_thread.call_args_list
        ), "extract_pdf_text 必须经 asyncio.to_thread 离开事件循环"


class TestResumeOptimizeMaxTokens:
    """Task C (M41): 优化全文阶段 stream_llm_messages 必须显式下发 max_tokens"""

    def _auth(self):
        from app.asgi import app
        from app.core.auth import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1, "username": "opt_user", "bank_mode": "public"
        }
        return app

    async def test_text_phase_passes_max_tokens(self):
        """全文流式调用带 max_tokens，避免服务端默认值截断优化版"""
        import json as _json
        from app.routers.profile_pkg.resume import optimize_resume_event_stream

        captured = {}

        async def fake_raw_llm_call(user_id, **kwargs):
            return _json.dumps(["量化成果"], ensure_ascii=False)

        async def fake_stream(messages, user_id=None, **kwargs):
            captured["kwargs"] = kwargs
            yield "# 优化版"

        app = self._auth()
        try:
            from app.services import resume_service
            resume_service.save_resume(1, "resume.pdf", "张三\n后端工程师")
            with patch("app.routers.profile_pkg.resume.raw_llm_call", fake_raw_llm_call), \
                 patch("app.routers.profile_pkg.resume.stream_llm_messages", fake_stream):
                events = [
                    _json.loads(line[5:])
                    for line in ("".join([
                        d async for d in optimize_resume_event_stream({"id": 1, "username": "opt_user"}, "后端工程师")
                    ])).splitlines() if line.startswith("data: ")
                ]
        finally:
            app.dependency_overrides.clear()

        assert any(e["type"] == "done" for e in events)
        assert captured.get("kwargs", {}).get("max_tokens", 0) >= 4096, \
            "全文阶段必须显式下发 max_tokens（防服务端默认值截断）"
