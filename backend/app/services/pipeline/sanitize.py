"""
数据清洗：剔除纯数字等明显噪声；黑名单**只标记不丢题**（AC-019）。

历史问题：黑名单按子串过滤，把“Redis 持久化有哪些优缺点”这类技术题一并删除，
且删除没有记录。现在 HR 类表述只加 ``mark="needs_review"`` 标记，条目保留。
"""

import re
from typing import List, Dict

from app.core.config import CLUSTER_BATCH_SIZE
from app.services.extraction_integrity import classify_question

BATCH_SIZE = CLUSTER_BATCH_SIZE

# 保留旧常量名以兼容既有导入，但不再用于删除
_BLACKLIST_PHRASES = [
    "自我介绍",
    "反问",
    "想问我",
    "职业规划",
    "加班",
    "薪资",
    "为什么离职",
    "优缺点",
]

_NOISE_PATTERN = re.compile(r"^[\d\s\-.,，。、;；:：!！?？]+$")


def sanitize_batch(batch: List[Dict]) -> tuple[List[Dict], List[Dict]]:
    """清洗批次：纯数字等噪声剔除；疑似 HR 题只标记保留。

    返回 ``(clean, filtered)``；``len(clean) + len(filtered) == len(batch)``。
    """
    clean: List[Dict] = []
    filtered: List[Dict] = []
    for item in batch:
        q = (item.get("question") or "").strip()
        if _NOISE_PATTERN.match(q):
            filtered.append(item)
            continue
        needs_review, reason = classify_question(q)
        if needs_review:
            item = {**item, "mark": "needs_review", "mark_reason": reason}
        clean.append(item)
    return clean, filtered
