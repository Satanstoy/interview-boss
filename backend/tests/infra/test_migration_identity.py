"""Migration identities must survive databases shipped by parallel branches."""
import sqlite3

import pytest

from app.db import migrations

LEGACY_NAMES = {
    121: 'onboarding', 122: 'onboarding_revision',
    123: 'user_owned_fk_cleanup', 124: 'onboarding_actions',
    125: 'evaluation_review_identity', 126: 'evaluation_worker_claim',
}


def legacy_database(monkeypatch):
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    registry = migrations._MIGRATIONS
    with monkeypatch.context() as patch:
        patch.setattr(migrations, '_MIGRATIONS', [m for m in registry if m[0] <= 120])
        migrations.run_migrations(conn)
    for version, name in LEGACY_NAMES.items():
        conn.execute('INSERT INTO schema_version(version,name) VALUES (?,?)', (version, name))
    conn.execute("INSERT INTO interview(id,company,status) VALUES (9001,'preserve-me','approved')")
    conn.commit()
    return conn


def test_reconcile_shipped_legacy_identities_without_losing_history(monkeypatch):
    conn = legacy_database(monkeypatch)
    before = [tuple(r) for r in conn.execute('SELECT * FROM schema_version ORDER BY version')]
    migrations.run_migrations(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'upload_imports', 'upload_attempts', 'question_resolutions', 'question_promotion_requests'} <= tables
    row = conn.execute('SELECT company,publish_status FROM interview WHERE id=9001').fetchone()
    assert tuple(row) == ('preserve-me', 'published')
    assert [tuple(r) for r in conn.execute('SELECT * FROM schema_version WHERE version<=126 ORDER BY version')] == before
    schema = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    versions = [tuple(r) for r in conn.execute('SELECT * FROM schema_version ORDER BY version')]
    migrations.run_migrations(conn)
    assert [tuple(r) for r in conn.execute('SELECT * FROM schema_version ORDER BY version')] == versions
    assert conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == schema
    assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    conn.close()


def test_unknown_identity_fails_before_applying_any_migration(monkeypatch):
    conn = legacy_database(monkeypatch)
    conn.execute("UPDATE schema_version SET name='unknown-release' WHERE version=123")
    conn.commit()
    before = conn.total_changes
    with pytest.raises(RuntimeError, match='123.*unknown-release'):
        migrations.run_migrations(conn)
    assert conn.total_changes == before
    conn.close()


def test_duplicate_registry_versions_fail_before_applying(monkeypatch):
    conn = sqlite3.connect(':memory:')
    monkeypatch.setattr(migrations, '_MIGRATIONS', [(1, 'a', lambda c: None), (1, 'b', lambda c: None)])
    with pytest.raises(RuntimeError, match='Duplicate migration version'):
        migrations.run_migrations(conn)
    assert not conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()


@pytest.mark.parametrize("last_legacy", range(121, 127))
def test_legacy_prefix_reconciles_before_dependent_new_migrations(monkeypatch, last_legacy):
    conn = legacy_database(monkeypatch)
    conn.execute('DELETE FROM schema_version WHERE version>?', (last_legacy,))
    conn.commit()
    migrations.run_migrations(conn)
    assert conn.execute("SELECT name FROM schema_version WHERE version=121").fetchone()[0] == 'onboarding'
    assert conn.execute('SELECT COUNT(*) FROM upload_stage_results').fetchone()[0] == 0
    assert conn.execute('SELECT publish_status FROM interview WHERE id=9001').fetchone()[0] == 'published'
    conn.close()
