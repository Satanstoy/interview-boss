"""The operations runbook must cover the audit's common failure classes."""

from pathlib import Path


RUNBOOK = Path(__file__).resolve().parents[3] / "docs/runbooks/operations.md"


def test_operations_runbook_has_symptom_mitigation_and_verification_sections():
    source = RUNBOOK.read_text()

    for heading in (
        "数据库不可用或锁",
        "Redis 不可用",
        "Worker offline / 队列积压",
        "LLM 5xx、超时与 rate limit",
        "磁盘耗尽与容器 OOM",
        "备份、恢复与回滚",
    ):
        assert heading in source
    for phrase in ("症状", "止损", "验证", "恢复", "数据影响", "回滚条件", "事后记录"):
        assert phrase in source


def test_destructive_runbook_steps_require_backup_and_confirmation():
    source = RUNBOOK.read_text()

    assert "clear-db" in source
    assert "备份前置" in source
    assert "确认" in source
    assert "docker compose ps" in source
    assert "df -h" in source
