"""fix_source_consistency.py 数据修复脚本逻辑测试。

合并重复面经的逻辑已委托 app.services.interview_merge_service
（其行为由 test_interview_merge_service.py 覆盖），此处只测脚本
自身的 url_signature 回填与 internal:// 报告。
"""

import importlib.util
import os
import sqlite3

import pytest

_script_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts",
    "fix_source_consistency.py",
)
_spec = importlib.util.spec_from_file_location("fix_source_consistency", _script_path)
fixer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixer)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE interview (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT, url_signature TEXT DEFAULT '', deleted_at TIMESTAMP
        )"""
    )
    c.execute(
        """CREATE TABLE jd (
            id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT,
            url_signature TEXT DEFAULT '', deleted_at TIMESTAMP
        )"""
    )
    c.execute(
        """CREATE TABLE question_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_bank_id INTEGER, url TEXT, company TEXT DEFAULT '',
            round TEXT DEFAULT '', deleted_at TIMESTAMP
        )"""
    )
    yield c
    c.close()


def _insert(conn, table, **kwargs):
    cols = ", ".join(kwargs)
    marks = ", ".join(["?"] * len(kwargs))
    cur = conn.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(kwargs.values())
    )
    return cur.lastrowid


def test_backfill_url_signatures(conn):
    """空签名记录回填；internal:// 与生产 _extract_url_signature 行为一致归 generic"""
    _insert(conn, "interview", url="https://www.xiaohongshu.com/explore/69ebf7ec000000001f0075ba?xsec_token=ABnKvS1dmNyhjo86JVSTRWDa9kCagyzHcr_C6-9rTrydU=", url_signature="")
    _insert(conn, "interview", url="internal://5ildmcA5aKMt3W5UeGHkzQ", url_signature="")
    _insert(conn, "jd", url="https://www.xiaohongshu.com/explore/69e9d944000000001b0213b2?xsec_token=ABZNTazy289-2Z16bmk6sG9KZO4klivnIaRQmBU0Sew0c=", url_signature="")

    n = fixer.backfill_url_signatures(conn, dry_run=False)
    assert n == 3  # 两条 xhs + internal:// 也获得 generic 签名
    rows = conn.execute("SELECT url_signature FROM interview").fetchall()
    sigs = [r[0] for r in rows]
    assert "xhs:69ebf7ec000000001f0075ba" in sigs
    assert "generic:5ildmcA5aKMt3W5UeGHkzQ" in sigs
    jd_sig = conn.execute("SELECT url_signature FROM jd").fetchone()[0]
    assert jd_sig == "xhs:69e9d944000000001b0213b2"


def test_backfill_skips_existing_signature(conn):
    _insert(conn, "interview", url="https://x.com/a", url_signature="nc:1")
    n = fixer.backfill_url_signatures(conn, dry_run=False)
    assert n == 0


def test_report_internal_sources(conn):
    _insert(conn, "interview", url="internal://a")
    _insert(conn, "interview", url="https://x.com/a")
    _insert(conn, "jd", url="internal://b")
    _insert(conn, "question_sources", question_bank_id=1, url="internal://c")
    interview_n, jd_n, qs_n = fixer.report_internal_sources(conn)
    assert (interview_n, jd_n, qs_n) == (1, 1, 1)
