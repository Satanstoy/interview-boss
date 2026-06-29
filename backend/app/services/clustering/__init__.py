"""聚类服务：增量匹配 + 内部聚类 + 全量重聚类

原 clustering.py 拆分为：
  - prompts.py      — 提示词常量与置信度阈值
  - clusterer.py    — 聚类引擎（_cluster_unmatched, cluster_three_stage_v2）
  - matcher.py      — 增量匹配（process_incremental_batch, match_new_questions, scan_personal_duplicates）
  - full_recluster.py — 全量重聚类（full_recluster_hybrid）
"""
import asyncio  # noqa: F401 — kept for backward-compat (tests patch app.services.clustering.asyncio)

# ── prompts ──
from app.services.clustering.prompts import (
    MATCH_EXISTING_PROMPT,
    CLUSTER_NEW_PROMPT,
    VALIDATE_MERGES_PROMPT,
    VALIDATION_CONFIDENCE_THRESHOLD,
    DIRECT_ACCEPT_CONFIDENCE_THRESHOLD,
)

# ── clusterer ──
from app.services.clustering.clusterer import (
    _cluster_unmatched,
    cluster_three_stage_v2,
    _normalize_question_text,
    _union_find,
    _union_merge,
    _format_new_questions,
)

# ── matcher ──
from app.services.clustering.matcher import (
    process_incremental_batch,
    match_new_questions,
    scan_personal_duplicates,
    generate_unified_question,
    calculate_dynamic_recent_days,
    _match_and_cluster_cat2,
    _validate_merges,
    _load_recent_singletons,
    _extract_id,
    _safe_confidence,
    _build_matched_item,
    _apply_exact_candidate_matches,
    _extract_raw_matches,
    _partition_matches_by_risk,
    _format_existing_clusters,
    _scan_async,
)

# ── full_recluster ──
from app.services.clustering.full_recluster import (
    full_recluster_hybrid,
)

# ── re-exports from app.services.llm (used by pipeline/batch.py) ──
from app.services.llm import _call_llm_with_retry, _extract_json

# ── re-exports from app.db.connection (used by tests patching this module) ──
from app.db.connection import get_db_connection

__all__ = [
    # prompts
    "MATCH_EXISTING_PROMPT",
    "CLUSTER_NEW_PROMPT",
    "VALIDATE_MERGES_PROMPT",
    "VALIDATION_CONFIDENCE_THRESHOLD",
    "DIRECT_ACCEPT_CONFIDENCE_THRESHOLD",
    # clusterer
    "_cluster_unmatched",
    "cluster_three_stage_v2",
    "_normalize_question_text",
    "_union_find",
    "_union_merge",
    "_format_new_questions",
    # matcher
    "process_incremental_batch",
    "match_new_questions",
    "scan_personal_duplicates",
    "generate_unified_question",
    "calculate_dynamic_recent_days",
    "_match_and_cluster_cat2",
    "_validate_merges",
    "_load_recent_singletons",
    "_extract_id",
    "_safe_confidence",
    "_build_matched_item",
    "_apply_exact_candidate_matches",
    "_extract_raw_matches",
    "_partition_matches_by_risk",
    "_format_existing_clusters",
    "_scan_async",
    # full_recluster
    "full_recluster_hybrid",
    # re-exports from app.services.llm
    "_call_llm_with_retry",
    "_extract_json",
    # re-exports from app.db.connection
    "get_db_connection",
]
