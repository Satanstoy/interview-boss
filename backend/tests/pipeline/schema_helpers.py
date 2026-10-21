import importlib.util
import json
import sqlite3
from pathlib import Path

from app.db.migrations import run_migrations


def create_pipeline_db():
    generator_path = Path(__file__).resolve().parents[3] / "scripts/generate_schema_docs.py"
    spec = importlib.util.spec_from_file_location("pipeline_schema_bootstrap", generator_path)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    generator._bootstrap_legacy_tables(conn)
    run_migrations(conn)
    return conn


def sync_pipeline_sources(conn):
    from app.db.question_bank_sources import sync_question_bank_sources

    for row in conn.execute("SELECT * FROM question_bank").fetchall():
        sync_question_bank_sources(
            conn.cursor(), row["id"], json.loads(row["sources"] or "[]"),
            json.loads(row["original_questions"] or "[]"),
            json.loads(row["original_question_sources"] or "[]"),
        )
