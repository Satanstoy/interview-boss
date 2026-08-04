"""Tests for migration 048 (embedding_metadata) and migration registry."""

from __future__ import annotations

import sqlite3
import pytest


def _new_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


class TestMigration048EmbeddingMetadata:
    def test_migration_adds_embedding_model_and_dim_columns_to_existing_table(self):
        conn = _new_conn()
        conn.execute(
            "CREATE TABLE question_bank (id INTEGER PRIMARY KEY, embedding BLOB)"
        )
        conn.execute("INSERT INTO question_bank (id) VALUES (1)").fetchall()
        conn.commit()

        from app.db.migrations.clustering import _migration_048_embedding_metadata

        _migration_048_embedding_metadata(conn)

        cols = {r[1] for r in conn.execute("PRAGMA table_info(question_bank)")}
        assert "embedding_model" in cols
        assert "embedding_dim" in cols

    def test_migration_is_idempotent(self):
        conn = _new_conn()
        conn.execute(
            "CREATE TABLE question_bank (id INTEGER PRIMARY KEY, embedding BLOB)"
        )
        conn.commit()

        from app.db.migrations.clustering import _migration_048_embedding_metadata

        _migration_048_embedding_metadata(conn)
        _migration_048_embedding_metadata(conn)

        cols = {r[1] for r in conn.execute("PRAGMA table_info(question_bank)")}
        assert "embedding_model" in cols
        assert "embedding_dim" in cols

    def test_existing_rows_get_null_defaults(self):
        conn = _new_conn()
        conn.execute(
            "CREATE TABLE question_bank (id INTEGER PRIMARY KEY, embedding BLOB)"
        )
        conn.execute("INSERT INTO question_bank (id) VALUES (1), (2)")
        conn.commit()

        from app.db.migrations.clustering import _migration_048_embedding_metadata

        _migration_048_embedding_metadata(conn)

        rows = conn.execute(
            "SELECT id, embedding_model, embedding_dim FROM question_bank"
        ).fetchall()
        assert all(r["embedding_model"] is None for r in rows)
        assert all(r["embedding_dim"] is None for r in rows)

    def test_migration_registered_in_registry_after_047(self):
        from app.db.migrations import _MIGRATIONS

        versions = [v for v, _, _ in _MIGRATIONS]
        assert 48 in versions
        idx = versions.index(48)
        assert versions[idx - 1] == 47
