#!/usr/bin/env python3
"""
批量回填 question_bank 表中缺失的 embedding 向量。

用法：
  docker compose exec backend uv run python backend/scripts/backfill_embeddings.py
  docker compose exec backend uv run python backend/scripts/backfill_embeddings.py --dry-run
  docker compose exec backend uv run python backend/scripts/backfill_embeddings.py --limit 100 --batch-size 32
"""

from __future__ import annotations

import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_embeddings")

SQL_FETCH = (
    "SELECT id, question FROM question_bank "
    "WHERE deleted_at IS NULL AND status = 'approved' AND embedding IS NULL "
    "ORDER BY id"
)
SQL_UPDATE = "UPDATE question_bank SET embedding = ? WHERE id = ?"


def backfill(
    *, dry_run: bool = False, limit: int | None = None, batch_size: int = 32
) -> None:
    from app.db.connection import get_db_connection
    from app.services.embedding_service import encode_texts

    with get_db_connection() as conn:
        rows = conn.execute(SQL_FETCH).fetchall()
    if limit:
        rows = rows[:limit]

    logger.info(f"待回填题目数: {len(rows)}")
    if not rows:
        logger.info("无需回填")
        return

    if dry_run:
        logger.info("[DRY-RUN] 不会实际写入")
        for row in rows[:5]:
            logger.info(f"  id={row[0]}, question={row[1][:50]}...")
        return

    total_updated = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        questions = [r[1] for r in batch]
        ids = [r[0] for r in batch]

        try:
            vectors = encode_texts(questions)
        except Exception as e:
            logger.error(f"编码批次 {i // batch_size + 1} 失败: {e}")
            continue

        with get_db_connection() as conn:
            for qid, vec in zip(ids, vectors):
                blob = vec.astype(np.float32).tobytes()
                conn.execute(SQL_UPDATE, (blob, qid))
            conn.commit()

        total_updated += len(batch)
        logger.info(f"  已处理 {total_updated}/{len(rows)}")

    logger.info(f"✅ 回填完成，共 {total_updated} 条")


def main() -> None:
    parser = argparse.ArgumentParser(description="批量回填 embedding")
    parser.add_argument("--dry-run", action="store_true", help="预览模式")
    parser.add_argument("--limit", type=int, default=None, help="最多处理 N 条")
    parser.add_argument("--batch-size", type=int, default=32, help="每批编码数量")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run, limit=args.limit, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
