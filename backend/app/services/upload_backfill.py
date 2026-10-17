"""AC-023 / UR-023：历史数据迁移演练（dry-run 优先，不猜测重放）。

契约（contracts.md §5）：

- 对旧 ``submit_import`` 按 parent 链建立 root；环/断链/多活跃后代/跨 owner
  一律列入报告，**不猜测**；
- ``completed`` job 仅在 ``result.interview_id`` 存在且归属匹配时关联；
- 迁移脚本默认 dry-run，输出 counts、候选 ID、冲突原因，不输出题干/图片/Key；
- ``--apply`` 必须有匹配的 manifest hash；重复运行不增加实体或 attempt。
"""

from __future__ import annotations

import hashlib
import json

LEGACY_ROOT_PREFIX = "legacy-job-"


class ManifestMismatch(Exception):
    code = "STATE_CONFLICT"


def _chain_map(conn) -> dict[int, list[int]]:
    """root_job_id → 后代 job id 列表（含自身）。"""

    rows = conn.execute(
        "SELECT id, parent_job_id FROM jobs WHERE job_type = 'submit_import' ORDER BY id"
    ).fetchall()
    parents = {
        int(row["id"]): (int(row["parent_job_id"]) if row["parent_job_id"] else None)
        for row in rows
    }

    def root_of(job_id: int) -> int:
        seen: set[int] = set()
        current = job_id
        while parents.get(current) is not None:
            if current in seen:
                return -1  # 环
            seen.add(current)
            current = parents[current]
        return current

    chains: dict[int, list[int]] = {}
    cycles: set[int] = set()
    for job_id in parents:
        root = root_of(job_id)
        if root == -1:
            cycles.add(job_id)
            continue
        chains.setdefault(root, []).append(job_id)
    for chain in chains.values():
        chain.sort()
    if cycles:
        chains[-1] = sorted(cycles)
    return chains


def plan_backfill(conn) -> dict:
    """只读规划：返回 counts、候选与歧义清单 + manifest hash。"""

    chains = _chain_map(conn)
    imports_created = 0
    attempts_created = 0
    jobs_linked = 0
    candidates: list[dict] = []
    ambiguous: list[dict] = []

    for root_id, member_ids in sorted(chains.items()):
        if root_id == -1:
            ambiguous.append({"reason": "cycle_in_parent_chain", "job_ids": member_ids})
            continue

        existing = conn.execute(
            "SELECT id FROM upload_imports WHERE id = ?", (f"{LEGACY_ROOT_PREFIX}{root_id}",)
        ).fetchone()
        already_linked = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE root_import_id IS NOT NULL AND id IN (%s)"
            % ",".join("?" * len(member_ids)),
            member_ids,
        ).fetchone()[0]

        root_job = conn.execute("SELECT * FROM jobs WHERE id = ?", (root_id,)).fetchone()
        if root_job is None:
            ambiguous.append({"reason": "missing_parent", "root_job_id": root_id, "job_ids": member_ids})
            continue
        members = conn.execute(
            "SELECT id, created_by, status FROM jobs WHERE id IN (%s)"
            % ",".join("?" * len(member_ids)), member_ids,
        ).fetchall()
        if any(row["created_by"] != root_job["created_by"] for row in members):
            ambiguous.append({"reason": "cross_owner_chain", "root_job_id": root_id, "job_ids": member_ids})
            continue
        active = [row["id"] for row in members if row["status"] in ("pending", "queued", "running")]
        if active:
            ambiguous.append({"reason": "multiple_active_descendants" if len(active) > 1 else "active_legacy_chain",
                              "root_job_id": root_id, "job_ids": active})
            continue
        if root_job["status"] != "completed":
            ambiguous.append({"reason": "legacy_mapping_ambiguous", "root_job_id": root_id})
            continue
        interview_id = None
        if root_job["result"]:
            try:
                interview_id = (json.loads(root_job["result"]) or {}).get("interview_id")
            except (TypeError, json.JSONDecodeError):
                interview_id = None

        if root_job["created_by"] is None:
            ambiguous.append({"reason": "missing_created_by", "root_job_id": root_id})
            continue

        if root_job["status"] == "completed" and interview_id is not None:
            interview = conn.execute(
                "SELECT owner_id FROM interview WHERE id = ? AND deleted_at IS NULL",
                (interview_id,),
            ).fetchone()
            if interview is None:
                ambiguous.append(
                    {
                        "reason": "result_interview_missing",
                        "root_job_id": root_id,
                        "interview_id": interview_id,
                    }
                )
                continue
            if interview["owner_id"] not in (None, root_job["created_by"]):
                ambiguous.append(
                    {
                        "reason": "owner_mismatch",
                        "root_job_id": root_id,
                        "interview_id": interview_id,
                    }
                )
                continue

        if root_job["status"] == "completed" and interview_id is None:
            ambiguous.append({"reason": "completed_without_interview", "root_job_id": root_id})
            continue

        candidates.append(
            {
                "root_job_id": root_id,
                "job_ids": member_ids,
                "import_id": f"{LEGACY_ROOT_PREFIX}{root_id}",
                "interview_id": interview_id,
                "already_linked_jobs": int(already_linked),
            }
        )
        if existing is None:
            imports_created += 1
            attempts_created += 1
        jobs_linked += len(member_ids) - int(already_linked)

    payload = {
        "chains_scanned": len(chains),
        "imports_created": imports_created,
        "attempts_created": attempts_created,
        "jobs_linked": jobs_linked,
        "candidates": candidates,
        "ambiguous": ambiguous,
    }
    payload["manifest_hash"] = hashlib.sha256(
        json.dumps(
            {
                "candidates": [(c["root_job_id"], tuple(c["job_ids"])) for c in candidates],
                "ambiguous": ambiguous,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return payload


def apply_backfill(conn, *, manifest: dict, expected_manifest_hash: str | None = None) -> dict:
    """按 manifest 幂等应用；重复运行不新增实体。"""

    current = plan_backfill(conn)
    if expected_manifest_hash is not None and current["manifest_hash"] != expected_manifest_hash:
        raise ManifestMismatch(
            f"manifest 已变化: expected={expected_manifest_hash} current={current['manifest_hash']}"
        )

    created_imports = 0
    created_attempts = 0
    linked_jobs = 0
    for candidate in current["candidates"]:
        import_id = candidate["import_id"]
        root_job = conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (candidate["root_job_id"],)
        ).fetchone()
        inserted = conn.execute(
            "INSERT OR IGNORE INTO upload_imports (id, requester_id, idempotency_key, "
            "request_hash, target_intent, source_type, pipeline_version, status, interview_id, "
            "current_attempt_no) VALUES (?, ?, ?, ?, 'private', 'interview', 'legacy', "
            "'completed', ?, 1)",
            (
                import_id,
                root_job["created_by"],
                f"legacy:{candidate['root_job_id']}",
                f"legacy:{candidate['root_job_id']}",
                candidate["interview_id"],
            ),
        )
        if inserted.rowcount:
            created_imports += 1
            conn.execute(
                "INSERT OR IGNORE INTO upload_attempts (import_id, attempt_no, status, requested_by) "
                "VALUES (?, 1, 'completed', ?)",
                (import_id, root_job["created_by"]),
            )
            created_attempts += 1
        attempt_id = conn.execute(
            "SELECT id FROM upload_attempts WHERE import_id = ? AND attempt_no = 1",
            (import_id,),
        ).fetchone()[0]
        if candidate["job_ids"]:
            placeholders = ",".join("?" * len(candidate["job_ids"]))
            linked = conn.execute(
                f"UPDATE jobs SET root_import_id = ?, upload_attempt_id = ? "
                f"WHERE id IN ({placeholders}) AND root_import_id IS NULL",
                (import_id, attempt_id, *candidate["job_ids"]),
            )
            linked_jobs += linked.rowcount

    return {
        "imports_created": created_imports,
        "attempts_created": created_attempts,
        "jobs_linked": linked_jobs,
        "ambiguous": current["ambiguous"],
    }
