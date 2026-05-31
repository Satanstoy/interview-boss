"""Compaction test: pre-stats → compact → post-stats → merge_history"""
import asyncio
import json
import sqlite3
import sys
import os

# bypass proxy for LLM calls
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "interview-boss.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def query(sql, params=()):
    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_one(sql, params=()):
    conn = get_conn()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def print_stats(label: str):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    total = query_one("SELECT COUNT(*) as cnt FROM question_bank WHERE deleted_at IS NULL AND owner_id IS NULL AND status='approved'")["cnt"]
    freq1 = query_one("SELECT COUNT(*) as cnt FROM question_bank WHERE deleted_at IS NULL AND owner_id IS NULL AND status='approved' AND frequency=1")["cnt"]
    freq_gt1 = query_one("SELECT COUNT(*) as cnt FROM question_bank WHERE deleted_at IS NULL AND owner_id IS NULL AND status='approved' AND frequency>1")["cnt"]

    print(f"  总题数 (approved, no owner):  {total}")
    print(f"  frequency = 1 (孤岛):         {freq1}")
    print(f"  frequency > 1 (已有聚合):     {freq_gt1}")
    print(f"  孤岛占比:                     {freq1/total*100:.1f}%" if total > 0 else "  (empty)")

    return {"total": total, "freq1": freq1, "freq_gt1": freq_gt1}


def print_cat2_top10():
    print(f"\n  按 cat2 统计孤岛 (freq=1) 分布 TOP 10:")
    print(f"  {'-'*45}")
    rows = query("""
        SELECT cat2, COUNT(*) as cnt
        FROM question_bank
        WHERE deleted_at IS NULL AND owner_id IS NULL AND status='approved' AND frequency=1
        GROUP BY cat2
        ORDER BY cnt DESC
        LIMIT 10
    """)
    for r in rows:
        cat = r["cat2"] or "(null)"
        print(f"    {cat:<30s} {r['cnt']:>5d}")
    if not rows:
        print("    (no singletons found)")


def print_merge_history():
    print(f"\n{'='*60}")
    print(f"  merge_history 合并记录")
    print(f"{'='*60}")

    rows = query("""
        SELECT id, survivor_id, merged_ids, merged_questions,
               operation_type, phase, confidence, cat2, created_at
        FROM merge_history
        ORDER BY id
    """)

    if not rows:
        print("  (no merge history records)")
        return

    print(f"  共 {len(rows)} 条记录:\n")
    for r in rows:
        merged_ids = r["merged_ids"]
        try:
            mids = json.loads(merged_ids) if merged_ids else []
        except:
            mids = merged_ids

        try:
            mqs = json.loads(r["merged_questions"]) if r["merged_questions"] else []
        except:
            mqs = r["merged_questions"]

        print(f"  [{r['id']}] survivor={r['survivor_id']}  merged={mids}")
        print(f"       phase={r['phase']}  type={r['operation_type']}  conf={r['confidence']}")
        print(f"       cat2={r['cat2']}  time={r['created_at']}")
        # show merged questions briefly
        if isinstance(mqs, list) and mqs:
            for mq in mqs[:3]:
                q = mq if isinstance(mq, str) else str(mq)[:80]
                print(f"         ← {q[:80]}")
            if len(mqs) > 3:
                print(f"         ... and {len(mqs)-3} more")
        print()


async def main():
    # ── Step 1: Pre-compaction stats ──
    pre = print_stats("优化前状态")
    print_cat2_top10()

    # ── Step 2: Check merge_history exists ──
    try:
        cnt = query_one("SELECT COUNT(*) as cnt FROM merge_history")
        print(f"\n  merge_history 表存在, 当前 {cnt['cnt']} 条记录")
    except Exception as e:
        print(f"\n  ERROR: merge_history 表不存在: {e}")
        sys.exit(1)

    # ── Step 3: Run compaction ──
    print(f"\n{'='*60}")
    print(f"  开始运行 compact_singletons_in_db() ...")
    print(f"  (NO_PROXY=* 已设置，LLM 调用将绕过代理)")
    print(f"{'='*60}\n")

    from app.services.pipeline.batch import compact_singletons_in_db

    result = await compact_singletons_in_db()

    print(f"\n  compact_singletons_in_db 返回结果:")
    for k, v in result.items():
        print(f"    {k}: {v}")

    # ── Step 4: Post-compaction stats ──
    post = print_stats("优化后状态")
    print_cat2_top10()

    # ── Step 5: Compare ──
    print(f"\n{'='*60}")
    print(f"  优化效果对比")
    print(f"{'='*60}")
    print(f"  总题数:       {pre['total']} → {post['total']}  (减少 {pre['total']-post['total']})")
    print(f"  孤岛(freq=1): {pre['freq1']} → {post['freq1']}  (减少 {pre['freq1']-post['freq1']})")
    print(f"  聚合(freq>1): {pre['freq_gt1']} → {post['freq_gt1']}  (增加 {post['freq_gt1']-pre['freq_gt1']})")
    if pre['total'] > 0:
        print(f"  孤岛占比:     {pre['freq1']/pre['total']*100:.1f}% → {post['freq1']/post['total']*100:.1f}%" if post['total'] > 0 else "")

    # ── Step 6: Merge history ──
    print_merge_history()


if __name__ == "__main__":
    asyncio.run(main())
