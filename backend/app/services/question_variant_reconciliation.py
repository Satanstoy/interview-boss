"""公共题库原始题目的全局归属、历史修复与写入防护。

``question_original_items`` 只保证同一题簇内不重复，历史上因此出现了
同一原始题目挂在多个题簇的情况。本模块提供三类能力：

* 扫描跨题簇的规范化原始题目；
* 在一个事务中把一个原始题目归并到明确的规范题簇，并关闭重复待审卡；
* 在新写入前用“全局扫描 + 唯一 claim 表”阻止再次跨题簇写入。

本模块不替人工决定语义相似题的归属。执行修复时必须显式传入
``normalized_question -> canonical question_bank id`` 映射。
"""

from __future__ import annotations

from collections import defaultdict
import json
import logging
from typing import Any, Mapping

from app.services.clustering.clusterer import _normalize_question_text

logger = logging.getLogger("interview-boss")

PUBLIC_QB_WHERE = "owner_id IS NULL AND deleted_at IS NULL AND status = 'approved'"


class VariantOwnershipConflict(RuntimeError):
    """A normalized original question is already owned by another cluster."""

    def __init__(self, question: str, owners: list[dict[str, Any]]):
        self.question = question
        self.owners = owners
        owner_ids = ", ".join(str(item["question_bank_id"]) for item in owners)
        super().__init__(
            f"原始题目已归属其他题簇: {question!r} (question_bank_id={owner_ids})"
        )


def normalize_original_question(text: str) -> str:
    """Use the same lightweight normalization as the clustering matcher."""

    return _normalize_question_text(str(text or ""))


def _json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _source_entry_for(source_entries: list, index: int, question: str) -> dict:
    """Return a copied source entry while tolerating legacy misalignment."""

    candidate = source_entries[index] if index < len(source_entries) else None
    if not isinstance(candidate, dict) or (
        candidate.get("question")
        and candidate.get("question") != question
    ):
        candidate = next(
            (
                item
                for item in source_entries
                if isinstance(item, dict) and item.get("question") == question
            ),
            None,
        )
    if not isinstance(candidate, dict):
        candidate = {"question": question, "sources": []}
    copied = dict(candidate)
    copied["question"] = question
    copied["sources"] = [
        dict(item)
        for item in copied.get("sources", [])
        if isinstance(item, dict) and item.get("url")
    ]
    return copied


def _load_original_entries(row: Any) -> tuple[list[str], list[dict]]:
    originals = [
        str(question).strip()
        for question in _json_list(row["original_questions"])
        if str(question or "").strip()
    ]
    source_entries = _json_list(row["original_question_sources"])
    entries = [
        _source_entry_for(source_entries, index, question)
        for index, question in enumerate(originals)
    ]
    return originals, entries


def _dedupe_sources(sources: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(dict(source))
    return result


def _merge_source_entry(entries: list[dict], question: str, sources: list[dict]) -> None:
    key = normalize_original_question(question)
    target = next(
        (
            item
            for item in entries
            if normalize_original_question(item.get("question", "")) == key
        ),
        None,
    )
    if target is None:
        entries.append({"question": question, "sources": _dedupe_sources(sources)})
        return
    target["sources"] = _dedupe_sources(
        list(target.get("sources") or []) + list(sources or [])
    )


def _entry_urls(entry: dict) -> set[str]:
    return {
        str(source.get("url"))
        for source in entry.get("sources", [])
        if isinstance(source, dict) and source.get("url")
    }


def _table_exists(conn, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
    )


def scan_cross_cluster_variant_groups(conn) -> list[dict]:
    """Find normalized original questions present in multiple public clusters."""

    groups: dict[str, list[dict]] = defaultdict(list)
    rows = conn.execute(
        "SELECT id, question, cat1, cat2, job_position, original_questions, "
        "original_question_sources FROM question_bank WHERE " + PUBLIC_QB_WHERE + " ORDER BY id"
    ).fetchall()
    for row in rows:
        originals, source_entries = _load_original_entries(row)
        for index, question in enumerate(originals):
            normalized = normalize_original_question(question)
            if not normalized:
                continue
            groups[normalized].append(
                {
                    "question_bank_id": row["id"],
                    "question": row["question"],
                    "cat1": row["cat1"],
                    "cat2": row["cat2"],
                    "job_position": row["job_position"],
                    "variant_index": index,
                    "original_question": question,
                    "source_entry": source_entries[index],
                }
            )

    result = []
    for normalized, occurrences in groups.items():
        cluster_ids = sorted({item["question_bank_id"] for item in occurrences})
        if len(cluster_ids) < 2:
            continue
        result.append(
            {
                "normalized_question": normalized,
                "cluster_ids": cluster_ids,
                "occurrences": occurrences,
            }
        )
    return sorted(
        result,
        key=lambda item: (
            item["cluster_ids"][0],
            item["normalized_question"],
        ),
    )


def _active_variant_owners(conn, normalized_question: str) -> list[dict]:
    owners = []
    rows = conn.execute(
        "SELECT id, original_questions FROM question_bank WHERE " + PUBLIC_QB_WHERE
    ).fetchall()
    for row in rows:
        for question in _json_list(row["original_questions"]):
            if normalize_original_question(question) == normalized_question:
                owners.append(
                    {
                        "question_bank_id": row["id"],
                        "question_text": str(question),
                    }
                )
                break
    return owners


def _ensure_ownership_table(conn) -> None:
    if _table_exists(conn, "question_variant_owners"):
        return
    # Keeps the service safe for a rolling deployment where the application
    # code is newer than the database migration.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS question_variant_owners ("
        "normalized_question TEXT PRIMARY KEY, question_bank_id INTEGER NOT NULL, "
        "question_text TEXT NOT NULL, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )


def claim_original_question_owner(conn, question: str, question_bank_id: int) -> str:
    """Atomically claim a normalized original question for one cluster.

    The full JSON scan catches legacy rows before the registry is rebuilt. The
    primary-key claim table closes the race between two concurrent writers.
    """

    normalized = normalize_original_question(question)
    if not normalized:
        return normalized
    _ensure_ownership_table(conn)
    owners = [
        owner
        for owner in _active_variant_owners(conn, normalized)
        if owner["question_bank_id"] != question_bank_id
    ]
    if owners:
        raise VariantOwnershipConflict(question, owners)

    existing = conn.execute(
        "SELECT question_bank_id FROM question_variant_owners "
        "WHERE normalized_question = ?",
        (normalized,),
    ).fetchone()
    if existing and existing[0] != question_bank_id:
        # The registry may contain a stale owner after a manual repair. If no
        # active JSON owner exists, the current writer can safely take it over.
        active = [
            owner
            for owner in _active_variant_owners(conn, normalized)
            if owner["question_bank_id"] != question_bank_id
        ]
        if active:
            raise VariantOwnershipConflict(question, active)
        conn.execute(
            "UPDATE question_variant_owners SET question_bank_id = ?, question_text = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE normalized_question = ?",
            (question_bank_id, question, normalized),
        )
        return normalized

    conn.execute(
        "INSERT OR IGNORE INTO question_variant_owners "
        "(normalized_question, question_bank_id, question_text) VALUES (?, ?, ?)",
        (normalized, question_bank_id, question),
    )
    owner = conn.execute(
        "SELECT question_bank_id FROM question_variant_owners "
        "WHERE normalized_question = ?",
        (normalized,),
    ).fetchone()
    if owner and owner[0] != question_bank_id:
        raise VariantOwnershipConflict(question, [
            {"question_bank_id": owner[0], "question_text": question}
        ])
    return normalized


def assert_no_other_variant_owner(
    conn, question: str, excluded_cluster_ids: set[int] | None = None
) -> str:
    """Fail if an active public cluster other than an allowed source owns q."""

    normalized = normalize_original_question(question)
    excluded = set(excluded_cluster_ids or set())
    owners = [
        owner
        for owner in _active_variant_owners(conn, normalized)
        if owner["question_bank_id"] not in excluded
    ]
    if owners:
        raise VariantOwnershipConflict(question, owners)
    return normalized


def transfer_original_question_owner(
    conn, question: str, from_question_bank_id: int, to_question_bank_id: int
) -> str:
    """Move a source question's claim during an atomic cluster merge."""

    normalized = normalize_original_question(question)
    if not normalized:
        return normalized
    _ensure_ownership_table(conn)
    owners = [
        owner
        for owner in _active_variant_owners(conn, normalized)
        if owner["question_bank_id"] not in {from_question_bank_id, to_question_bank_id}
    ]
    if owners:
        raise VariantOwnershipConflict(question, owners)
    conn.execute(
        "INSERT INTO question_variant_owners "
        "(normalized_question, question_bank_id, question_text) VALUES (?, ?, ?) "
        "ON CONFLICT(normalized_question) DO UPDATE SET question_bank_id = excluded.question_bank_id, "
        "question_text = excluded.question_text, updated_at = CURRENT_TIMESTAMP",
        (normalized, to_question_bank_id, question),
    )
    return normalized


def rebuild_variant_ownership(conn) -> dict:
    """Rebuild claims; conflicting historical groups remain unclaimed."""

    _ensure_ownership_table(conn)
    groups: dict[str, list[dict]] = defaultdict(list)
    rows = conn.execute(
        "SELECT id, original_questions FROM question_bank WHERE " + PUBLIC_QB_WHERE
    ).fetchall()
    for row in rows:
        for question in _json_list(row["original_questions"]):
            normalized = normalize_original_question(question)
            if normalized:
                groups[normalized].append(
                    {"question_bank_id": row["id"], "question_text": str(question)}
                )

    conn.execute("DELETE FROM question_variant_owners")
    owned = 0
    conflicts = 0
    for normalized, owners in groups.items():
        cluster_ids = {owner["question_bank_id"] for owner in owners}
        if len(cluster_ids) != 1:
            conflicts += 1
            continue
        owner = owners[0]
        conn.execute(
            "INSERT INTO question_variant_owners "
            "(normalized_question, question_bank_id, question_text) VALUES (?, ?, ?)",
            (normalized, owner["question_bank_id"], owner["question_text"]),
        )
        owned += 1
    return {"owned": owned, "conflicts": conflicts}


def _sync_normalized_tables(conn, qb_id: int) -> None:
    """Synchronize JSON and normalized source tables for one question bank row."""

    row = conn.execute(
        "SELECT sources, original_questions, original_question_sources "
        "FROM question_bank WHERE id = ?",
        (qb_id,),
    ).fetchone()
    if not row:
        return
    sources = _dedupe_sources(_json_list(row["sources"]))
    originals = [str(item).strip() for item in _json_list(row["original_questions"]) if str(item or "").strip()]
    source_entries = _json_list(row["original_question_sources"])
    # A merge can remove an original question while leaving its provenance
    # entry behind.  Normalize the JSON side before syncing the relational
    # side so orphaned source URLs cannot keep the two representations apart.
    original_set = set(originals)
    cleaned_source_entries = [
        item
        for item in source_entries
        if isinstance(item, dict) and item.get("question") in original_set
    ]
    if cleaned_source_entries != source_entries:
        conn.execute(
            "UPDATE question_bank SET original_question_sources = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(cleaned_source_entries, ensure_ascii=False), qb_id),
        )
        source_entries = cleaned_source_entries
    entry_by_question = {
        str(item.get("question")): item
        for item in source_entries
        if isinstance(item, dict) and item.get("question")
    }

    if _table_exists(conn, "question_sources"):
        desired_urls = {source["url"] for source in sources}
        for existing in conn.execute(
            "SELECT id, url FROM question_sources WHERE question_bank_id = ? "
            "AND deleted_at IS NULL",
            (qb_id,),
        ).fetchall():
            if existing["url"] not in desired_urls:
                conn.execute(
                    "UPDATE question_sources SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (existing["id"],),
                )
        for source in sources:
            existing = conn.execute(
                "SELECT id FROM question_sources WHERE question_bank_id = ? AND url = ?",
                (qb_id, source["url"]),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE question_sources SET company = ?, round = ?, deleted_at = NULL WHERE id = ?",
                    (source.get("company", ""), source.get("round", ""), existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO question_sources "
                    "(question_bank_id, url, company, round) VALUES (?, ?, ?, ?)",
                    (qb_id, source["url"], source.get("company", ""), source.get("round", "")),
                )

    if not _table_exists(conn, "question_original_items"):
        return

    desired_questions = set(originals)
    existing_items = conn.execute(
        "SELECT id, question_text FROM question_original_items "
        "WHERE question_bank_id = ? AND deleted_at IS NULL",
        (qb_id,),
    ).fetchall()
    for existing in existing_items:
        if existing["question_text"] not in desired_questions:
            if _table_exists(conn, "question_original_item_sources"):
                conn.execute(
                    "UPDATE question_original_item_sources SET deleted_at = CURRENT_TIMESTAMP "
                    "WHERE original_item_id = ? AND deleted_at IS NULL",
                    (existing["id"],),
                )
            conn.execute(
                "UPDATE question_original_items SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
                (existing["id"],),
            )

    for question in originals:
        item = conn.execute(
            "SELECT id FROM question_original_items "
            "WHERE question_bank_id = ? AND question_text = ?",
            (qb_id, question),
        ).fetchone()
        if item:
            item_id = item["id"]
            conn.execute(
                "UPDATE question_original_items SET deleted_at = NULL WHERE id = ?",
                (item_id,),
            )
        else:
            item_id = conn.execute(
                "INSERT INTO question_original_items "
                "(question_bank_id, question_text) VALUES (?, ?)",
                (qb_id, question),
            ).lastrowid

        if not _table_exists(conn, "question_original_item_sources"):
            continue
        desired = _dedupe_sources(
            (entry_by_question.get(question) or {}).get("sources", [])
        )
        desired_urls = {source["url"] for source in desired}
        for existing_source in conn.execute(
            "SELECT id, url FROM question_original_item_sources "
            "WHERE original_item_id = ? AND deleted_at IS NULL",
            (item_id,),
        ).fetchall():
            if existing_source["url"] not in desired_urls:
                conn.execute(
                    "UPDATE question_original_item_sources SET deleted_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (existing_source["id"],),
                )
        for source in desired:
            existing_source = conn.execute(
                "SELECT id FROM question_original_item_sources "
                "WHERE original_item_id = ? AND url = ?",
                (item_id, source["url"]),
            ).fetchone()
            if existing_source:
                conn.execute(
                    "UPDATE question_original_item_sources SET company = ?, round = ?, deleted_at = NULL "
                    "WHERE id = ?",
                    (source.get("company", ""), source.get("round", ""), existing_source["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO question_original_item_sources "
                    "(original_item_id, url, company, round) VALUES (?, ?, ?, ?)",
                    (item_id, source["url"], source.get("company", ""), source.get("round", "")),
                )


def sync_all_normalized_tables(conn) -> int:
    """Make normalized source tables match the JSON source-of-truth columns."""

    rows = conn.execute(
        "SELECT id FROM question_bank WHERE " + PUBLIC_QB_WHERE + " ORDER BY id"
    ).fetchall()
    for row in rows:
        _sync_normalized_tables(conn, row["id"])
    return len(rows)


def _write_cluster_json(conn, qb_id: int, originals: list[str], entries: list[dict], sources: list[dict]) -> None:
    conn.execute(
        "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, "
        "sources = ?, frequency = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (
            json.dumps(originals, ensure_ascii=False),
            json.dumps(entries, ensure_ascii=False),
            json.dumps(_dedupe_sources(sources), ensure_ascii=False),
            max(1, len(originals)),
            qb_id,
        ),
    )
    _sync_normalized_tables(conn, qb_id)


def _pending_issue_ids_for_group(conn, group: dict) -> list[int]:
    index_text = {
        (item["question_bank_id"], item["variant_index"]): item["original_question"]
        for item in group["occurrences"]
    }
    ids = []
    cluster_ids = group["cluster_ids"]
    placeholders = ",".join("?" * len(cluster_ids))
    rows = conn.execute(
        "SELECT id, qb_id, variant_index, source_question FROM quality_issue "
        f"WHERE status = 'pending' AND qb_id IN ({placeholders}) "
        "AND variant_index IS NOT NULL",
        cluster_ids,
    ).fetchall()
    for row in rows:
        text = row["source_question"] or index_text.get(
            (row["qb_id"], row["variant_index"]), ""
        )
        if normalize_original_question(text) == group["normalized_question"]:
            ids.append(row["id"])
    return ids


def _close_group_issues(conn, group: dict, reviewed_by: int | None) -> int:
    issue_ids = _pending_issue_ids_for_group(conn, group)
    if not issue_ids:
        return 0
    reason = (
        "[系统归属修复] 原始题目已统一归属到 question_bank_id="
        f"{group['canonical_id']}，不再逐条执行拆分建议。"
    )
    placeholders = ",".join("?" * len(issue_ids))
    params: list[Any] = [reason, reviewed_by, *issue_ids]
    conn.execute(
        "UPDATE quality_issue SET status = 'rejected', reason = ?, "
        "reviewed_at = datetime('now'), reviewed_by = ? "
        f"WHERE id IN ({placeholders}) AND status = 'pending'",
        params,
    )
    return len(issue_ids)


def _reconcile_group(conn, group: dict) -> tuple[set[int], int]:
    canonical_id = group["canonical_id"]
    affected = set(group["cluster_ids"])
    canonical_row = conn.execute(
        "SELECT * FROM question_bank WHERE id = ? AND " + PUBLIC_QB_WHERE,
        (canonical_id,),
    ).fetchone()
    if not canonical_row:
        raise ValueError(f"规范题簇不存在或不是公共有效题簇: {canonical_id}")

    canonical_originals, canonical_entries = _load_original_entries(canonical_row)
    canonical_sources = _json_list(canonical_row["sources"])
    for occurrence in group["occurrences"]:
        if occurrence["question_bank_id"] == canonical_id:
            continue
        source_entry = occurrence["source_entry"]
        _merge_source_entry(
            canonical_entries,
            occurrence["original_question"],
            source_entry.get("sources", []),
        )
        canonical_sources.extend(source_entry.get("sources", []))

    if not any(
        normalize_original_question(question) == group["normalized_question"]
        for question in canonical_originals
    ):
        first = next(
            item
            for item in group["occurrences"]
            if item["question_bank_id"] != canonical_id
        )
        canonical_originals.append(first["original_question"])
        # _merge_source_entry above added its sources to an existing entry only
        # when the canonical entry already existed; add it now for a new item.
        _merge_source_entry(
            canonical_entries,
            first["original_question"],
            first["source_entry"].get("sources", []),
        )

    _write_cluster_json(
        conn, canonical_id, canonical_originals, canonical_entries, canonical_sources
    )

    for cluster_id in group["cluster_ids"]:
        if cluster_id == canonical_id:
            continue
        row = conn.execute(
            "SELECT * FROM question_bank WHERE id = ? AND " + PUBLIC_QB_WHERE,
            (cluster_id,),
        ).fetchone()
        if not row:
            continue
        originals, entries = _load_original_entries(row)
        removed_urls = set()
        kept_originals = []
        kept_entries = []
        for question, entry in zip(originals, entries):
            if normalize_original_question(question) == group["normalized_question"]:
                removed_urls.update(_entry_urls(entry))
                continue
            kept_originals.append(question)
            kept_entries.append(entry)
        remaining_urls = set()
        for entry in kept_entries:
            remaining_urls.update(_entry_urls(entry))
        sources = [
            source
            for source in _json_list(row["sources"])
            if source.get("url") not in removed_urls or source.get("url") in remaining_urls
        ]
        _write_cluster_json(conn, cluster_id, kept_originals, kept_entries, sources)

    return affected, len(group["occurrences"])


def reconcile_cross_cluster_variants(
    conn,
    canonical_by_key: Mapping[str, int],
    *,
    dry_run: bool = True,
    reviewed_by: int | None = None,
) -> dict:
    """Reconcile explicitly mapped duplicate groups.

    No commit is performed. ``dry_run=True`` is fully read-only; callers should
    wrap an execute call in one transaction and commit only after validation.
    """

    groups = scan_cross_cluster_variant_groups(conn)
    report = {
        "dry_run": dry_run,
        "groups_found": len(groups),
        "groups_processed": 0,
        "groups_skipped": 0,
        "variants_moved": 0,
        "issues_closed": 0,
        "groups": [],
    }
    changed_clusters = set()
    for group in groups:
        normalized = group["normalized_question"]
        canonical_id = canonical_by_key.get(normalized)
        item = {
            "normalized_question": normalized,
            "cluster_ids": group["cluster_ids"],
            "canonical_id": canonical_id,
            "occurrences": len(group["occurrences"]),
        }
        if canonical_id not in group["cluster_ids"]:
            item["status"] = "skipped_missing_canonical"
            report["groups_skipped"] += 1
            report["groups"].append(item)
            continue
        group["canonical_id"] = canonical_id
        issue_ids = _pending_issue_ids_for_group(conn, group)
        item["pending_issue_ids"] = issue_ids
        if dry_run:
            item["status"] = "would_reconcile"
            report["groups"].append(item)
            report["groups_processed"] += 1
            report["variants_moved"] += sum(
                occurrence["question_bank_id"] != canonical_id
                for occurrence in group["occurrences"]
            )
            continue

        affected, moved = _reconcile_group(conn, group)
        changed_clusters.update(affected)
        report["groups_processed"] += 1
        report["variants_moved"] += moved - sum(
            occurrence["question_bank_id"] == canonical_id
            for occurrence in group["occurrences"]
        )
        report["issues_closed"] += _close_group_issues(conn, group, reviewed_by)
        item["status"] = "reconciled"
        report["groups"].append(item)

    if not dry_run:
        from app.services.cluster_review_lifecycle import mark_clusters_review_pending

        mark_clusters_review_pending(
            conn, sorted(changed_clusters), "cross_cluster_variant_reconciliation"
        )
        report["ownership"] = rebuild_variant_ownership(conn)
    return report
