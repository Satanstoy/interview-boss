"""题库重建备份工具测试(ADR 0046 / spec M5 Task 6)。

WAL 模式下 shutil.copy2 只拷贝主库,漏掉 -wal 未合并帧,是不一致快照;
在线备份 sqlite3.Connection.backup() 生成一致性快照。
"""
import shutil
import sqlite3

from app.worker import _backup_db_online


def test_online_backup_contains_uncheckpointed_wal(tmp_path):
    src = str(tmp_path / "s.db")
    conn = sqlite3.connect(src)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")  # 阻止自动 checkpoint,帧全部留在 WAL
    conn.execute("CREATE TABLE t (x)")
    for i in range(2000):
        conn.execute("INSERT INTO t VALUES (?)", (i,))
    conn.commit()
    assert (tmp_path / "s.db-wal").stat().st_size > 0

    backup = str(tmp_path / "online.db")
    _backup_db_online(src, backup)

    bc = sqlite3.connect(backup)
    assert bc.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2000
    bc.close()
    conn.close()


def test_legacy_copy2_misses_wal_frames(tmp_path):
    src = str(tmp_path / "s.db")
    conn = sqlite3.connect(src)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE t (x)")
    for i in range(2000):
        conn.execute("INSERT INTO t VALUES (?)", (i,))
    conn.commit()

    legacy = str(tmp_path / "legacy.db")
    shutil.copy2(src, legacy)
    lc = sqlite3.connect(legacy)
    try:
        n = lc.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    except sqlite3.OperationalError:
        n = -1  # 表定义也留在 WAL,主库缺失
    lc.close()
    conn.close()
    assert n < 2000
