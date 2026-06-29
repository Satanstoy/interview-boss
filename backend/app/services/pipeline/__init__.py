"""
两阶段流水线服务（流式增量处理）

阶段1（并发）: 面经 → tag → questions_detail + enqueue（每题一条队列记录）
阶段2（串行）: queue达到batch_size 或 全部完成 → 原量匹配 + 内部聚类 → question_bank

拆分模块:
  - sanitize.py  — 数据清洗
  - queue.py     — 队列操作
  - writer.py    — 数据库写入
  - batch.py     — 增量聚类流水线
  - compact.py   — 孤岛碎片整理(compaction)
"""
from .sanitize import BATCH_SIZE, sanitize_batch, _BLACKLIST_PHRASES
from .queue import (
    enqueue_questions,
    get_pending_count,
    get_processing_count,
    should_trigger_clustering,
    dequeue_batch,
    mark_batch_done,
    mark_batch_failed,
    STUCK_PROCESSING_THRESHOLD_MINUTES,
)
from .writer import (
    tag_and_write_details,
    apply_matched,
    insert_new_clusters,
)
from .batch import (
    cluster_batch,
    process_interview_tag_then_maybe_cluster,
    force_cluster_all_pending,
)
from .compact import compact_singletons_in_db

# 向后兼容：保留旧函数名
_sanitize_batch = sanitize_batch
tag_interview = tag_and_write_details

__all__ = [
    # sanitize
    "BATCH_SIZE", "sanitize_batch", "_sanitize_batch", "_BLACKLIST_PHRASES",
    # queue
    "enqueue_questions", "get_pending_count", "get_processing_count",
    "should_trigger_clustering", "dequeue_batch", "mark_batch_done", "mark_batch_failed",
    "STUCK_PROCESSING_THRESHOLD_MINUTES",
    # writer
    "tag_and_write_details", "tag_interview", "apply_matched", "insert_new_clusters",
    # batch
    "cluster_batch", "process_interview_tag_then_maybe_cluster",
    "force_cluster_all_pending", "compact_singletons_in_db",
]
