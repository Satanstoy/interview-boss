"""
数据清洗：剔除纯数字、非面试话术等脏数据
"""

import re
from typing import List, Dict

from app.core.config import CLUSTER_BATCH_SIZE

BATCH_SIZE = CLUSTER_BATCH_SIZE

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


def sanitize_batch(batch: List[Dict]) -> tuple[List[Dict], List[Dict]]:
    """清洗批次：剔除纯数字和非面试话术。返回 (clean, filtered)"""
    clean, filtered = [], []
    for item in batch:
        q = (item.get("question") or "").strip()
        if re.match(r"^[\d\s\-.,，。、;；:：!！?？]+$", q):
            filtered.append(item)
            continue
        if any(phrase in q for phrase in _BLACKLIST_PHRASES):
            filtered.append(item)
            continue
        clean.append(item)
    return clean, filtered
