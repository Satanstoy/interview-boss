"""Clustering domain migrations: 032, 033, 034, 035 + _classify_e_question helper."""

import json
import logging

logger = logging.getLogger("interview-boss")


def _migration_032_embedding_column(conn):
    """Add embedding BLOB column to question_bank for vector pre-filtering."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info('question_bank')")
    columns = [info[1] for info in cursor.fetchall()]
    if "embedding" not in columns:
        conn.execute("ALTER TABLE question_bank ADD COLUMN embedding BLOB")
    logger.info("已为 question_bank 添加 embedding BLOB 列")


def _migration_033_cluster_id(conn):
    """Add cluster_id column to question_bank for explicit cluster identification."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info('question_bank')")
    columns = [info[1] for info in cursor.fetchall()]
    if "cluster_id" not in columns:
        conn.execute(
            "ALTER TABLE question_bank ADD COLUMN cluster_id INTEGER DEFAULT NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_qb_cluster_id ON question_bank(cluster_id)"
        )
    # 回填: 每条存活记录的 cluster_id = 自身 id（即自己就是聚类代表）
    conn.execute(
        "UPDATE question_bank SET cluster_id = id "
        "WHERE cluster_id IS NULL AND deleted_at IS NULL"
    )
    logger.info("已为 question_bank 添加 cluster_id 列并回填")


def _migration_034_backfill_confidence(conn):
    """回填充 merge_history 中 confidence=0 的记录。

    使用 embedding 相似度估算置信度:
    - 从 survivor 的 embedding 和 merged_questions 文本编码计算相似度
    - 如果没有 embedding 可用，使用文本精确匹配规则
    """
    import numpy as np

    # 检查 merge_history 表是否存在
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "merge_history" not in tables:
        logger.info("migration_034: merge_history 表不存在，跳过回填")
        return

    zero_rows = conn.execute(
        "SELECT id, survivor_id, merged_questions, confidence "
        "FROM merge_history WHERE confidence = 0 AND is_rolled_back = 0"
    ).fetchall()

    if not zero_rows:
        logger.info("migration_034: 没有 confidence=0 的记录需要回填")
        return

    updated = 0
    for row in zero_rows:
        history_id = row[0]
        survivor_id = row[1]
        merged_q_text = row[2] or "[]"

        try:
            merged_qs = json.loads(merged_q_text)
        except Exception:
            merged_qs = []

        # 尝试通过 embedding 计算置信度
        survivor_emb = None
        survivor_row = conn.execute(
            "SELECT embedding, question, original_questions FROM question_bank WHERE id = ?",
            (survivor_id,),
        ).fetchone()

        new_confidence = 0.0

        if survivor_row and survivor_row[0]:
            survivor_emb = np.frombuffer(survivor_row[0], dtype=np.float32)
            # 对每个 merged question 编码并计算相似度
            try:
                from app.services.embedding_service import (
                    encode_texts,
                    compute_confidence_from_embeddings,
                )

                if merged_qs:
                    merged_embs = encode_texts(merged_qs)
                    confidences = [
                        compute_confidence_from_embeddings(survivor_emb, merged_embs[i])
                        for i in range(len(merged_qs))
                    ]
                    new_confidence = max(confidences) if confidences else 0.0
            except Exception as e:
                logger.warning(
                    f"migration_034: embedding 计算失败 (id={history_id}): {e}"
                )
                new_confidence = 0.0

        # Fallback: 如果 embedding 不可用，用文本匹配估算
        if new_confidence == 0.0 and survivor_row:
            survivor_q = survivor_row[1] or ""
            survivor_oqs = []
            try:
                survivor_oqs = json.loads(survivor_row[2]) if survivor_row[2] else []
            except Exception:
                pass
            all_survivor_texts = set([survivor_q] + survivor_oqs)
            for mq in merged_qs:
                if mq in all_survivor_texts:
                    new_confidence = 0.90
                    break
                # 部分匹配
                for st in all_survivor_texts:
                    if mq and st and (mq in st or st in mq):
                        new_confidence = 0.80
                        break
            if new_confidence == 0.0:
                new_confidence = 0.70  # 无法确定时给一个保守值

        if new_confidence > 0:
            conn.execute(
                "UPDATE merge_history SET confidence = ? WHERE id = ?",
                (new_confidence, history_id),
            )
            updated += 1

    logger.info(
        f"migration_034: 回填了 {updated}/{len(zero_rows)} 条 confidence=0 的记录"
    )


# E2.算法手撕 关键词（匹配到这些词的归入 E2）
_E2_KEYWORDS = [
    "算法",
    "手撕",
    "手写",
    "排序",
    "动态规划",
    "贪心",
    "回溯",
    "二分",
    "滑动窗口",
    "双指针",
    "BFS",
    "DFS",
    "遍历",
    "递归",
    "拓扑",
    "股票",
    "背包",
    "子序列",
    "子数组",
    "字符串匹配",
    "合并",
    "搜索",
    "解题",
    "思路",
    "口述",
    "环",
]

# E1.数据结构 关键词（匹配到这些词的归入 E1）
_E1_KEYWORDS = [
    "数据结构",
    "LRU",
    "LFU",
    "链表",
    "二叉树",
    "红黑树",
    "B+树",
    "B树",
    "堆",
    "栈",
    "队列",
    "哈希",
    "跳表",
    "并查集",
    "Trie",
    "前缀树",
    "线段树",
    "设计一个支持",
    "设计一个",
]


def _classify_e_question(question_text: str) -> str:
    """根据题目文本判断属于 E1.数据结构 还是 E2.算法手撕

    规则: E1 数据结构关键词权重更高（+2），因为"手撕 LRU"本质是数据结构题。
    只有纯粹的算法题（无数据结构关键词）才归入 E2。
    """
    text = question_text.lower()
    e1_score = sum(2 for kw in _E1_KEYWORDS if kw.lower() in text)
    e2_score = sum(1 for kw in _E2_KEYWORDS if kw.lower() in text)
    if e1_score > 0:
        return "E1.数据结构"
    if e2_score > 0:
        return "E2.算法手撕"
    # 无匹配时默认 E1
    return "E1.数据结构"


def _migration_035_split_e_category(conn):
    """将 E1.算法手撕与数据结构 和 E1.算法手撕 拆分为 E1.数据结构 + E2.算法手撕"""
    rows = conn.execute(
        "SELECT id, question, cat2 FROM question_bank "
        "WHERE cat2 IN ('E1.算法手撕与数据结构', 'E1.算法手撕') AND deleted_at IS NULL"
    ).fetchall()

    e1_count = 0
    e2_count = 0
    for row in rows:
        qb_id, question, old_cat2 = row[0], row[1], row[2]
        new_cat2 = _classify_e_question(question)
        if new_cat2 != old_cat2:
            conn.execute(
                "UPDATE question_bank SET cat2 = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_cat2, qb_id),
            )
        if new_cat2 == "E1.数据结构":
            e1_count += 1
        else:
            e2_count += 1

    # 同步更新 questions_detail 表
    detail_rows = conn.execute(
        "SELECT id, question FROM questions_detail "
        "WHERE cat2 IN ('E1.算法手撕与数据结构', 'E1.算法手撕')"
    ).fetchall()
    for dr in detail_rows:
        new_cat2 = _classify_e_question(dr[1] or "")
        conn.execute(
            "UPDATE questions_detail SET cat2 = ? WHERE id = ?", (new_cat2, dr[0])
        )

    logger.info(
        f"migration_035: 拆分 E 分类完成 — E1.数据结构={e1_count}, E2.算法手撕={e2_count}"
    )


def _migration_037_backfill_embeddings(conn):
    """Compatibility hook for embedding backfill migrations.

    Embeddings are generated lazily by the clustering pipeline. Keeping this
    idempotent function importable lets audit tooling verify that the migration
    hook exists without forcing model downloads during normal DB initialization.
    """
    logger.info("migration_037_backfill_embeddings: embeddings are backfilled lazily")


def _ensure_column(conn, table_name: str, column_name: str, column_sql: str) -> None:
    columns = {
        row[1] for row in conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    }
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


def _migration_039_merge_review_tables(conn):
    """Create merge review tables used by admin audit, feedback, and rollback."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS merge_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            survivor_id INTEGER NOT NULL,
            merged_ids TEXT NOT NULL,
            merged_questions TEXT NOT NULL,
            pre_snapshot TEXT,
            post_snapshot TEXT,
            operation_type TEXT DEFAULT 'auto',
            phase TEXT DEFAULT '',
            confidence REAL DEFAULT 0,
            cat2 TEXT DEFAULT '',
            operator_id INTEGER,
            is_rolled_back INTEGER DEFAULT 0,
            rolled_back_at TIMESTAMP,
            rolled_back_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (survivor_id) REFERENCES question_bank(id) ON DELETE SET NULL,
            FOREIGN KEY (operator_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (rolled_back_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    for column_name, column_sql in [
        ("pre_snapshot", "TEXT"),
        ("post_snapshot", "TEXT"),
        ("operation_type", "TEXT DEFAULT 'auto'"),
        ("phase", "TEXT DEFAULT ''"),
        ("confidence", "REAL DEFAULT 0"),
        ("cat2", "TEXT DEFAULT ''"),
        ("operator_id", "INTEGER"),
        ("is_rolled_back", "INTEGER DEFAULT 0"),
        ("rolled_back_at", "TIMESTAMP"),
        ("rolled_back_by", "INTEGER"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]:
        _ensure_column(conn, "merge_history", column_name, column_sql)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS merge_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merge_history_id INTEGER,
            question_bank_id INTEGER,
            feedback_type TEXT NOT NULL,
            comment TEXT,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (merge_history_id) REFERENCES merge_history(id) ON DELETE SET NULL,
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_merge_history_survivor ON merge_history(survivor_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_merge_history_cat2 ON merge_history(cat2)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_merge_feedback_history ON merge_feedback(merge_history_id)"
    )
    logger.info("migration_039: merge_history/merge_feedback 表已就绪")


def _migration_048_embedding_metadata(conn):
    """Add embedding_model/embedding_dim columns to question_bank.

    Lets us tell apart 512-dim ONNX vectors from 1024-dim bge-m3 API vectors so
    mixed-dimension data can be detected and rebuilt instead of silently fed
    to a mismatched FAISS index.
    """
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    if "embedding_model" not in columns:
        conn.execute(
            "ALTER TABLE question_bank ADD COLUMN embedding_model TEXT DEFAULT NULL"
        )
    if "embedding_dim" not in columns:
        conn.execute(
            "ALTER TABLE question_bank ADD COLUMN embedding_dim INTEGER DEFAULT NULL"
        )
    logger.info("migration_048: question_bank.embedding_model/embedding_dim 列已就绪")


def _migration_066_cluster_label(conn):
    """Add cluster_label column to question_bank.

    实验结论 P2：聚类匹配 prompt 带 LLM 生成的语义标签（标签摘要记忆方案），
    候选展示格式从「[ID] 代表题」升级为「[ID] [标签] 代表题」（标签缺失时回退）。
    """
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    if "cluster_label" not in columns:
        conn.execute(
            "ALTER TABLE question_bank ADD COLUMN cluster_label TEXT DEFAULT NULL"
        )
    logger.info("migration_066: question_bank.cluster_label 列已就绪")
