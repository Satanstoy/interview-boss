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
        env={"PATH": "/usr/bin:/bin", "ADMIN_PASSWORD": "schema-test-password"},
    )

    assert result.returncode == 0, result.stdout + result.stderr
