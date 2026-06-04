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
