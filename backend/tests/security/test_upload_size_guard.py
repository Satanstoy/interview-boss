"""Regression tests for the upload size-guard fix (cf418f2).

Before the fix, three upload endpoints (audio transcribe / chat PDF extract /
resume upload) did not check size before file.read(), so oversized bodies were
fully buffered into memory before being rejected (memory amplification + DoS).

Expected fixed behaviour (what these tests pin down):
- Content-Length (UploadFile.size) is rejected up-front, before file.read();
- oversized uploads get an HTTP 413;
- the key regression point: when over the limit, the downstream service
  (deepgram transcribe / resume text-extract) is NEVER reached and file.read()
  is never awaited — proving "early rejection" rather than "read-then-reject".

Covers the three fixed endpoints:
- audio.transcribe_audio           25MB limit
- chat.extract_pdf                 10MB limit
- resume.upload_resume             10MB limit

Everything is mocked; never touches real Deepgram / LLM / filesystem.
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

_USER = {"id": 1, "username": "upload_test", "bank_mode": "public"}

# 音频路由在导入时引入 deepgram 包；test-runtime 未装该包则只能跳过音频用例。
try:  # pragma: no cover - 环境探测
    import deepgram  # noqa: F401

    _HAS_DEEGRAM = True
except ImportError:
    _HAS_DEEGRAM = False


def _oversized_file(size: int, filename: str = "big.pdf"):
    """Build a fake UploadFile whose Content-Length (size) exceeds the limit.

    .read() is mocked to actually return data so that, if the early guard is
    removed, the downstream buffering would run and read.assert_not_awaited()
    would catch the regression.
    """
    f = AsyncMock()
    f.filename = filename
    f.size = size                     # simulates Content-Length
    f.read = AsyncMock(return_value=b"x" * 1024)
    return f


@pytest.mark.skipif(not _HAS_DEEGRAM, reason="test-runtime 未安装 deepgram 包，音频路由无法导入")
class TestAudioTranscribeSizeGuard:
    """POST /api/audio/transcribe rejects oversized audio up front."""

    async def test_oversized_audio_returns_413_before_service_call(self):
        """Content-Length over 25MB -> 413, deepgram is never reached."""
        from app.routers.audio import transcribe_audio, MAX_AUDIO_UPLOAD_BYTES

        too_big = _oversized_file(MAX_AUDIO_UPLOAD_BYTES + 1, "big.mp3")
        with patch("app.routers.audio.deepgram_service") as dg:
            with pytest.raises(HTTPException) as exc:
                await transcribe_audio(file=too_big, language="zh", model="nova-3", user=_USER)
        assert exc.value.status_code == 413
        too_big.read.assert_not_awaited()          # up-front rejection, no buffering
        dg.transcribe_audio.assert_not_awaited()   # downstream never reached
        dg.validate_audio_file.assert_not_called()

    async def test_audio_within_limit_passes_size_guard(self):
        """At the limit the size guard must not reject (no early exit)."""
        from app.routers.audio import transcribe_audio, MAX_AUDIO_UPLOAD_BYTES

        ok = _oversized_file(MAX_AUDIO_UPLOAD_BYTES, "ok.mp3")
        with patch("app.routers.audio.deepgram_service") as dg:
            dg.validate_audio_file.return_value = (False, "格式不支持")
            with pytest.raises(HTTPException) as exc:
                await transcribe_audio(file=ok, language="zh", model="nova-3", user=_USER)
        # 400 comes from validate_audio_file (not the size guard) -> size check passed
        assert exc.value.status_code == 400
        assert "不支持" in exc.value.detail


class TestChatPdfExtractSizeGuard:
    """POST /api/chat/extract-pdf rejects oversized PDF up front."""

    async def test_oversized_pdf_returns_413_before_extract(self):
        """Content-Length over 10MB -> 413, text extraction is never called."""
        from app.routers.chat import extract_pdf, _MAX_PDF_UPLOAD_BYTES

        too_big = _oversized_file(_MAX_PDF_UPLOAD_BYTES + 1, "big.pdf")
        with patch("app.routers.chat.resume_service") as rs:
            with pytest.raises(HTTPException) as exc:
                await extract_pdf(file=too_big, user=_USER)
        assert exc.value.status_code == 413
        too_big.read.assert_not_awaited()
        rs.extract_pdf_text.assert_not_called()

    async def test_pdf_within_limit_passes_size_guard(self):
        """A PDF at the limit is not rejected by the size guard."""
        from app.routers.chat import extract_pdf, _MAX_PDF_UPLOAD_BYTES

        ok = _oversized_file(_MAX_PDF_UPLOAD_BYTES, "ok.pdf")
        with patch("app.routers.chat.resume_service") as rs:
            rs.extract_pdf_text.return_value = "提取到的文本"
            result = await extract_pdf(file=ok, user=_USER)
        assert result["status"] == "success"
        rs.extract_pdf_text.assert_called_once()


class TestResumeUploadSizeGuard:
    """POST /api/profile/resume rejects oversized resume PDF up front."""

    async def test_oversized_resume_returns_413_before_extract(self):
        """Content-Length over 10MB -> 413, no extraction / no DB write."""
        from app.routers.profile_pkg.resume import upload_resume, _MAX_RESUME_UPLOAD_BYTES

        too_big = _oversized_file(_MAX_RESUME_UPLOAD_BYTES + 1, "big.pdf")
        # resume_service 在函数内被惰性导入，直接 patch 服务函数本身
        with patch("app.services.resume_service.extract_pdf_text") as rs:
            with pytest.raises(HTTPException) as exc:
                await upload_resume(file=too_big, user=_USER)
        assert exc.value.status_code == 413
        too_big.read.assert_not_awaited()
        rs.assert_not_called()

    async def test_resume_within_limit_passes_size_guard(self):
        """A resume at the limit is not rejected by the size guard."""
        from app.routers.profile_pkg.resume import upload_resume, _MAX_RESUME_UPLOAD_BYTES

        ok = _oversized_file(_MAX_RESUME_UPLOAD_BYTES, "ok.pdf")
        with patch("app.services.resume_service.extract_pdf_text") as extract, \
             patch("app.services.resume_service.save_resume", return_value=1) as save:
            extract.return_value = "姓名：张三"
            result = await upload_resume(file=ok, user=_USER)
        assert result["status"] == "success"
        extract.assert_called_once()
        save.assert_called_once()
