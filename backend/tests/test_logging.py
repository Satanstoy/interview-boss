# backend/tests/test_logging.py
"""structlog 日志系统测试"""
import json
import logging
import os
import structlog
import pytest


@pytest.fixture(autouse=True)
def _restore_logging():
    """每个测试后恢复日志配置，避免测试间干扰"""
    original_config = structlog.get_config()
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    yield
    if original_config:
        structlog.configure(**original_config)
    root.handlers = original_handlers
    root.setLevel(original_level)


def test_structlog_json_output(monkeypatch, capsys):
    """生产环境：日志输出为 JSON 格式，包含 event/level/timestamp"""
    monkeypatch.setenv("ENV", "production")

    from app.core.logging_config import setup_logging
    setup_logging()

    logger = logging.getLogger("interview-boss")
    logger.info("test_event", extra={"key": "value"})

    captured = capsys.readouterr()
    lines = [l for l in captured.out.strip().split('\n') if l.strip()]
    assert len(lines) >= 1

    log_entry = json.loads(lines[-1])
    assert log_entry["event"] == "test_event"
    assert log_entry["level"] == "info"
    assert "timestamp" in log_entry


def test_structlog_console_output(monkeypatch, capsys):
    """开发环境：日志输出为彩色人类可读格式"""
    monkeypatch.delenv("ENV", raising=False)

    from app.core.logging_config import setup_logging
    setup_logging()

    logger = logging.getLogger("interview-boss")
    logger.info("dev_test_event")

    captured = capsys.readouterr()
    assert "dev_test_event" in captured.out
    lines = [l for l in captured.out.strip().split('\n') if l.strip()]
    assert not lines[-1].startswith('{')


def test_existing_logger_calls_work():
    """现有 290 处 logging.getLogger('interview-boss') 调用无需修改"""
    logger = logging.getLogger("interview-boss")
    logger.info("compatibility_test")
    logger.warning("compatibility_warning")
    logger.error("compatibility_error")


def test_contextvars_request_id_propagation(monkeypatch, capsys):
    """request_id 通过 contextvars 自动传播到所有日志"""
    monkeypatch.setenv("ENV", "production")

    from app.core.logging_config import setup_logging
    setup_logging()

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="test123")

    logger = logging.getLogger("interview-boss")
    logger.info("context_test")

    captured = capsys.readouterr()
    lines = [l for l in captured.out.strip().split('\n') if l.strip()]
    log_entry = json.loads(lines[-1])
    assert log_entry.get("request_id") == "test123"

    structlog.contextvars.clear_contextvars()


# ── 请求日志中间件测试 ──

import asyncio
import json
import logging
from starlette.requests import Request
from starlette.responses import Response


@pytest.mark.asyncio
async def test_request_log_adds_request_id_to_response():
    """中间件应在响应头中添加 X-Request-ID"""
    from app.middleware.request_log import log_requests

    async def mock_call_next(request):
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/test",
        "query_string": b"",
        "headers": [],
    }
    request = Request(scope)

    response = await log_requests(request, mock_call_next)

    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) == 8


@pytest.mark.asyncio
async def test_request_log_binds_contextvars(monkeypatch, capsys):
    """中间件应将 request_id 绑定到 contextvars"""
    monkeypatch.setenv("ENV", "production")
    from app.core.logging_config import setup_logging
    setup_logging()

    from app.middleware.request_log import log_requests

    async def mock_call_next(request):
        logger = logging.getLogger("interview-boss")
        logger.info("inside_handler")
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/test",
        "query_string": b"",
        "headers": [],
    }
    request = Request(scope)

    response = await log_requests(request, mock_call_next)

    captured = capsys.readouterr()
    lines = [l for l in captured.out.strip().split('\n') if l.strip()]
    handler_logs = [l for l in lines if "inside_handler" in l]
    assert len(handler_logs) >= 1
    log_entry = json.loads(handler_logs[0])
    assert "request_id" in log_entry


# ── 前端错误上报端点测试 ──

from fastapi.testclient import TestClient


def test_error_report_endpoint_accepts_batch(client):
    """POST /api/error-report 应接受批量错误并返回 ok"""
    payload = {
        "errors": [
            {
                "level": "error",
                "message": "Cannot read properties of null",
                "url": "http://localhost/practice",
                "source": "PracticePanel.vue",
                "lineno": 391,
                "timestamp": "2026-06-05T14:30:00Z",
            },
            {
                "level": "error",
                "message": "Network error",
                "url": "http://localhost/chat",
                "timestamp": "2026-06-05T14:30:01Z",
            },
        ]
    }

    response = client.post("/api/error-report", json=payload)
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_error_report_endpoint_handles_empty_body(client):
    """空 errors 数组也应返回 ok"""
    response = client.post("/api/error-report", json={"errors": []})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_error_report_endpoint_handles_malformed_json(client):
    """畸形 JSON 不应导致 500"""
    response = client.post(
        "/api/error-report",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    # 应返回 ok: False 或 422，不应该是 500
    assert response.status_code in (200, 422)
