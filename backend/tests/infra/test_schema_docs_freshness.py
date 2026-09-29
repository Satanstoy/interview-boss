"""Schema docs must be generated from the live migration registry."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "generate_schema_docs.py"
DOC = ROOT / "docs" / "architecture" / "schema.md"


def test_schema_generator_and_document_track_the_live_registry():
    from app.db.migrations import _MIGRATIONS

    assert SCRIPT.exists()
    assert DOC.exists()
    source = DOC.read_text()
    latest_version, latest_name, _ = _MIGRATIONS[-1]

    assert f"Latest migration: {latest_version} ({latest_name})" in source
    assert "admin_audit_log" in source
    assert "foreign_key_check: 0" in source


def test_schema_freshness_check_passes():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "ADMIN_PASSWORD": "schema-test-password",
            # 干净环境下 git 需要显式信任该仓库（否则 dubious ownership，
            # 生成的 source commit 变成 unknown，检查必然失败）
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": str(ROOT),
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
