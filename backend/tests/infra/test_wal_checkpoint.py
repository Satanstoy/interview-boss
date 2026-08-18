"""WAL checkpoint 纪律测试(ADR 0046 / spec M5 Task 5)。

目标:每天低峰显式 checkpoint(PASSIVE→TRUNCATE),防止自动 checkpoint 被
常驻读者堵住导致 WAL 长期超阈值(实测 11MB)后,checkpoint 爆志阻塞读端。
"""
import sqlite3

from app.worker_scheduled import wal_checkpoint_now


def _wal_path(db):
    return db.with_suffix(db.suffix + "-wal")


def test_checkpoint_truncates_wal_after_writes(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (x INTEGER)")
    for i in range(4000):
        conn.execute("INSERT INTO t VALUES (?)", (i,))
    conn.commit()
    wal = _wal_path(db)
    assert wal.exists() and wal.stat().st_size > 0

    res = wal_checkpoint_now(conn)

    assert res["busy"] == 0
    assert res["truncate"] is not None
    # TRUNCATE 后 -wal 应基本归零(小于一页)
    assert wal.stat().st_size < 4096
    conn.close()


def test_checkpoint_skips_truncate_when_busy(tmp_path, monkeypatch):
    """PASSIVE 后 busy 非 0(存在读者):只做 PASSIVE,不执行 TRUNCATE。"""
    import app.worker_scheduled as ws_mod

    conn = sqlite3.connect(tmp_path / "t_busy.db")
    monkeypatch.setattr(ws_mod, "_run_passive", lambda c, m: (3, 10, 0))
    truncate_calls = {"n": 0}
    orig_truncate = ws_mod._run_truncate

    def spy(c):
        truncate_calls["n"] += 1
        return orig_truncate(c)

    monkeypatch.setattr(ws_mod, "_run_truncate", spy)
    res = ws_mod.wal_checkpoint_now(conn)
    assert res["busy"] == 3
    assert res["truncate"] is None
    assert truncate_calls["n"] == 0
    conn.close()


def test_checkpoint_truncates_when_idle(tmp_path, monkeypatch):
    """PASSIVE 后 busy==0:执行 TRUNCATE。"""
    import app.worker_scheduled as ws_mod

    monkeypatch.setattr(ws_mod, "_run_passive", lambda c, m: (0, 5, 5))
    monkeypatch.setattr(ws_mod, "_run_truncate", lambda c: [0, 0, 5])
    res = ws_mod.wal_checkpoint_now(sqlite3.connect(tmp_path / "t_idle.db"))
    assert res["truncate"] == [0, 0, 5]


def test_checkpoint_idempotent_on_empty_wal(tmp_path):
    """空 WAL 执行不报错,TRUNCATE 幂等。"""
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()

    res = wal_checkpoint_now(conn)
    assert res["busy"] == 0
    conn.close()
