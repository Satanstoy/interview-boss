"""Durable lifecycle helpers for the AI Evaluation System 1.0."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def manifest_digest(manifest: dict[str, Any]) -> str:
    """Return the stable content digest for an immutable manifest."""
    return hashlib.sha256(_json_dumps(manifest).encode("utf-8")).hexdigest()


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _decode_manifest(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def create_release(
    conn: sqlite3.Connection,
    *,
    release_key: str,
    release_type: str,
    version: str,
    manifest: dict[str, Any],
    target_type: str = "",
    display_name: str = "",
    judge_model: str = "",
    git_sha: str = "",
    image_digest: str = "",
    config_digest: str = "",
    created_by: int | None = None,
) -> dict[str, Any]:
    """Create a draft Release and persist its canonical manifest snapshot."""
    if not release_key.strip():
        raise ValueError("release_key 不能为空")
    if not isinstance(manifest, dict):
        raise ValueError("manifest 必须是 JSON object")

    manifest_json = _json_dumps(manifest)
    digest = manifest_digest(manifest)
    try:
        cursor = conn.execute(
            """
            INSERT INTO eval_releases (
                release_key, release_type, version, target_type, display_name,
                manifest_json, manifest_digest, judge_model, git_sha,
                image_digest, config_digest, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                release_key,
                release_type,
                version,
                target_type,
                display_name,
                manifest_json,
                digest,
                judge_model,
                git_sha,
                image_digest,
                config_digest,
                created_by,
            ),
        )
    except sqlite3.IntegrityError as exc:
        if "release_key" in str(exc):
            raise ValueError("release_key 已存在") from exc
        raise

    row = conn.execute(
        "SELECT * FROM eval_releases WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _row_dict(row) or {}


def create_benchmark_suite(
    conn: sqlite3.Connection,
    *,
    release_id: int,
    suite_key: str,
    target_type: str,
    judge_model: str = "",
    description: str = "",
) -> dict[str, Any]:
    try:
        cursor = conn.execute(
            """
            INSERT INTO eval_benchmark_suites
                (release_id, suite_key, target_type, judge_model, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (release_id, suite_key, target_type, judge_model, description),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Benchmark Suite 已存在或 Release 无效") from exc
    row = conn.execute(
        "SELECT * FROM eval_benchmark_suites WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _row_dict(row) or {}


def create_benchmark_case(
    conn: sqlite3.Connection,
    *,
    suite_id: int,
    case_key: str,
    scenario_key: str,
    input_snapshot: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    snapshot_json = _json_dumps(input_snapshot)
    contract_json = _json_dumps(contract)
    input_digest = hashlib.sha256(
        f"{snapshot_json}\n{contract_json}".encode("utf-8")
    ).hexdigest()
    try:
        cursor = conn.execute(
            """
            INSERT INTO eval_benchmark_cases
                (suite_id, case_key, scenario_key, input_snapshot_json,
                 contract_json, input_digest)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (suite_id, case_key, scenario_key, snapshot_json, contract_json, input_digest),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Benchmark Case 已存在或 Suite 无效") from exc
    row = conn.execute(
        "SELECT * FROM eval_benchmark_cases WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _row_dict(row) or {}


def _item_seed(seed: int, case_id: int, replication_index: int) -> int:
    payload = f"{seed}:{case_id}:{replication_index}".encode("utf-8")
    # SQLite INTEGER is a signed 64-bit value.
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**63 - 1)


def _create_legacy_eval_run(
    conn: sqlite3.Connection,
    *,
    created_by: int | None,
    target_release_id: int,
    benchmark_suite_release_id: int,
    eval_protocol_release_id: int,
    judge_release_id: int,
    simulator_harness_release_id: int,
    candidate_simulator_release_id: int,
    replication_count: int = 5,
    seed: int = 1,
    environment_fingerprint: str = "",
    comparison_group: str = "",
    idempotency_key: str | None = None,
    require_published: bool = False,
) -> dict[str, Any]:
    """Create a target-scoped Run with an immutable Batch and Case Items."""
    if replication_count < 1:
        raise ValueError("replication_count 必须大于 0")

    suite = conn.execute(
        "SELECT * FROM eval_benchmark_suites WHERE release_id = ?",
        (benchmark_suite_release_id,),
    ).fetchone()
    if suite is None:
        raise ValueError("Benchmark Suite Release 不存在")

    release_ids = (
        target_release_id,
        benchmark_suite_release_id,
        eval_protocol_release_id,
        judge_release_id,
        simulator_harness_release_id,
        candidate_simulator_release_id,
    )
    if len(set(release_ids)) != len(release_ids):
        raise ValueError("评测上下文中的 Release 必须各自独立")
    placeholders = ",".join("?" for _ in release_ids)
    release_count = conn.execute(
        f"SELECT COUNT(*) FROM eval_releases WHERE id IN ({placeholders})", release_ids
    ).fetchone()[0]
    if release_count != len(set(release_ids)):
        raise ValueError("评测上下文包含不存在的 Release")
    release_rows = conn.execute(
        f"SELECT * FROM eval_releases WHERE id IN ({placeholders})", release_ids
    ).fetchall()
    release_by_id = {row["id"]: row for row in release_rows}
    expected_types = {
        target_release_id: "target",
        benchmark_suite_release_id: "benchmark_suite",
        eval_protocol_release_id: "eval_protocol",
        judge_release_id: "judge",
        simulator_harness_release_id: "simulator_harness",
        candidate_simulator_release_id: "candidate_simulator",
    }
    for release_id, expected_type in expected_types.items():
        if release_by_id[release_id]["release_type"] != expected_type:
            raise ValueError(f"Release 类型不匹配: 需要 {expected_type}")
        if require_published and release_by_id[release_id]["status"] != "published":
            raise ValueError("官方评测只能绑定已发布 Release")
    target_type = release_by_id[target_release_id]["target_type"]
    if target_type and suite["target_type"] and target_type != suite["target_type"]:
        raise ValueError("Target 与 Benchmark Suite 的 target_type 不一致")
    for release_id in (simulator_harness_release_id, candidate_simulator_release_id):
        component_target_type = release_by_id[release_id]["target_type"]
        if component_target_type and target_type and component_target_type != target_type:
            raise ValueError("评测组件的 target_type 不一致")
    suite_judge_model = suite["judge_model"] or ""
    judge_model = release_by_id[judge_release_id]["judge_model"] or ""
    if suite_judge_model and judge_model and suite_judge_model != judge_model:
        raise ValueError("Benchmark Suite 与 Judge 的 judge_model 不一致")

    cases = conn.execute(
        """
        SELECT id FROM eval_benchmark_cases
        WHERE suite_id = ? AND active = 1
        ORDER BY id
        """,
        (suite["id"],),
    ).fetchall()
    if not cases:
        raise ValueError("Benchmark Suite 没有可执行的 Case")

    fingerprint_payload = {
        "target_release_id": target_release_id,
        "benchmark_suite_release_id": benchmark_suite_release_id,
        "eval_protocol_release_id": eval_protocol_release_id,
        "judge_release_id": judge_release_id,
        "simulator_harness_release_id": simulator_harness_release_id,
        "candidate_simulator_release_id": candidate_simulator_release_id,
        "case_ids": [row["id"] for row in cases],
        "replication_count": replication_count,
        "seed": seed,
        "environment_fingerprint": environment_fingerprint,
    }
    batch_fingerprint = hashlib.sha256(
        _json_dumps(fingerprint_payload).encode("utf-8")
    ).hexdigest()

    try:
        batch_cursor = conn.execute(
            """
            INSERT INTO eval_batches (
                batch_fingerprint, target_release_id, benchmark_suite_release_id,
                eval_protocol_release_id, judge_release_id,
                simulator_harness_release_id, candidate_simulator_release_id,
                environment_fingerprint, seed, replication_count, total_items,
                created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_fingerprint,
                target_release_id,
                benchmark_suite_release_id,
                eval_protocol_release_id,
                judge_release_id,
                simulator_harness_release_id,
                candidate_simulator_release_id,
                environment_fingerprint,
                seed,
                replication_count,
                len(cases) * replication_count,
                created_by,
            ),
        )
        batch_id = batch_cursor.lastrowid
        run_cursor = conn.execute(
            """
            INSERT INTO eval_runs (
                batch_id, target_release_id, benchmark_suite_release_id,
                eval_protocol_release_id, judge_release_id,
                simulator_harness_release_id, candidate_simulator_release_id,
                comparison_group, idempotency_key, total_items, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                target_release_id,
                benchmark_suite_release_id,
                eval_protocol_release_id,
                judge_release_id,
                simulator_harness_release_id,
                candidate_simulator_release_id,
                comparison_group,
                idempotency_key,
                len(cases) * replication_count,
                created_by,
            ),
        )
        run_id = run_cursor.lastrowid
        for case in cases:
            for replication_index in range(1, replication_count + 1):
                conn.execute(
                    """
                    INSERT INTO eval_items
                        (run_id, case_id, replication_index, seed)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        case["id"],
                        replication_index,
                        _item_seed(seed, case["id"], replication_index),
                    ),
                )
    except sqlite3.IntegrityError as exc:
        if "batch_fingerprint" in str(exc):
            raise ValueError("相同评测上下文的 Batch 已存在") from exc
        if "idempotency" in str(exc):
            raise ValueError("idempotency_key 已存在") from exc
        raise

    result = _row_dict(
        conn.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
    ) or {}
    result["batch_id"] = batch_id
    result["batch_fingerprint"] = batch_fingerprint
    return result


def _release_snapshot(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data.get("id"),
        "release_key": data.get("release_key"),
        "release_type": data.get("release_type"),
        "version": data.get("version"),
        "target_type": data.get("target_type") or "",
        "manifest": _decode_manifest(data.get("manifest_json")),
        "manifest_digest": data.get("manifest_digest") or "",
        "git_sha": data.get("git_sha") or "",
        "image_digest": data.get("image_digest") or "",
        "config_digest": data.get("config_digest") or "",
    }


def _create_dual_axis_eval_run(
    conn: sqlite3.Connection,
    *,
    created_by: int | None,
    target_release_id: int,
    evaluation_release_id: int,
    replication_count: int,
    seed: int,
    environment_fingerprint: str,
    comparison_group: str,
    idempotency_key: str | None,
    require_published: bool,
) -> dict[str, Any]:
    if replication_count < 1:
        raise ValueError("replication_count 必须大于 0")
    rows = conn.execute(
        "SELECT * FROM eval_releases WHERE id IN (?, ?)",
        (target_release_id, evaluation_release_id),
    ).fetchall()
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != 2:
        raise ValueError("Target Release 或 Evaluation Release 不存在")
    target = by_id[target_release_id]
    evaluation = by_id[evaluation_release_id]
    if target["release_type"] != "target":
        raise ValueError("target_release_id 必须指向 Target Release")
    if evaluation["release_type"] != "evaluation":
        raise ValueError("evaluation_release_id 必须指向 Evaluation Release")
    if target["target_type"] and evaluation["target_type"] and target["target_type"] != evaluation["target_type"]:
        raise ValueError("Target 与 Evaluation Release 的 target_type 不一致")
    if require_published and (
        target["status"] != "published" or evaluation["status"] != "published"
    ):
        raise ValueError("官方评测只能绑定已发布 Target Release 和 Evaluation Release")

    suite = conn.execute(
        "SELECT * FROM eval_benchmark_suites WHERE release_id = ?",
        (evaluation_release_id,),
    ).fetchone()
    if suite is None:
        raise ValueError("Evaluation Release 没有关联 Benchmark")
    cases = conn.execute(
        """
        SELECT id, case_key, scenario_key, input_snapshot_json, contract_json, input_digest
        FROM eval_benchmark_cases
        WHERE suite_id = ? AND active = 1
        ORDER BY id
        """,
        (suite["id"],),
    ).fetchall()
    if not cases:
        raise ValueError("Evaluation Release 没有可执行的 Benchmark Case")

    snapshot = {
        "schema_version": 1,
        "target_release": _release_snapshot(target),
        "evaluation_release": _release_snapshot(evaluation),
        "resolved": {
            "replication_count": replication_count,
            "seed": seed,
            "environment_fingerprint": environment_fingerprint,
            "comparison_group": comparison_group,
            "case_ids": [row["id"] for row in cases],
        },
        "cases": [
            {
                "id": row["id"],
                "case_key": row["case_key"],
                "scenario_key": row["scenario_key"],
                "input_snapshot": _decode_manifest(row["input_snapshot_json"]),
                "contract": _decode_manifest(row["contract_json"]),
                "input_digest": row["input_digest"],
            }
            for row in cases
        ],
    }
    snapshot_json = _json_dumps(snapshot)
    fingerprint_payload = {
        "target_release_id": target_release_id,
        "evaluation_release_id": evaluation_release_id,
        "case_ids": [row["id"] for row in cases],
        "replication_count": replication_count,
        "seed": seed,
        "environment_fingerprint": environment_fingerprint,
    }
    batch_fingerprint = hashlib.sha256(
        _json_dumps(fingerprint_payload).encode("utf-8")
    ).hexdigest()

    try:
        batch_cursor = conn.execute(
            """
            INSERT INTO eval_batches (
                batch_fingerprint, target_release_id, evaluation_release_id,
                benchmark_suite_release_id, eval_protocol_release_id,
                judge_release_id, simulator_harness_release_id,
                candidate_simulator_release_id, environment_fingerprint, seed,
                replication_count, total_items, snapshot_json, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_fingerprint,
                target_release_id,
                evaluation_release_id,
                evaluation_release_id,
                evaluation_release_id,
                evaluation_release_id,
                evaluation_release_id,
                evaluation_release_id,
                environment_fingerprint,
                seed,
                replication_count,
                len(cases) * replication_count,
                snapshot_json,
                created_by,
            ),
        )
        batch_id = batch_cursor.lastrowid
        run_cursor = conn.execute(
            """
            INSERT INTO eval_runs (
                batch_id, target_release_id, evaluation_release_id,
                benchmark_suite_release_id, eval_protocol_release_id,
                judge_release_id, simulator_harness_release_id,
                candidate_simulator_release_id, comparison_group,
                idempotency_key, total_items, snapshot_json, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                target_release_id,
                evaluation_release_id,
                evaluation_release_id,
                evaluation_release_id,
                evaluation_release_id,
                evaluation_release_id,
                evaluation_release_id,
                comparison_group,
                idempotency_key,
                len(cases) * replication_count,
                snapshot_json,
                created_by,
            ),
        )
        run_id = run_cursor.lastrowid
        for case in cases:
            for replication_index in range(1, replication_count + 1):
                conn.execute(
                    "INSERT INTO eval_items (run_id, case_id, replication_index, seed) VALUES (?, ?, ?, ?)",
                    (run_id, case["id"], replication_index, _item_seed(seed, case["id"], replication_index)),
                )
    except sqlite3.IntegrityError as exc:
        if "batch_fingerprint" in str(exc):
            raise ValueError("相同评测上下文的 Batch 已存在") from exc
        if "idempotency" in str(exc):
            raise ValueError("idempotency_key 已存在") from exc
        raise

    result = _row_dict(
        conn.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
    ) or {}
    result["batch_id"] = batch_id
    result["batch_fingerprint"] = batch_fingerprint
    return result


def create_eval_run(
    conn: sqlite3.Connection,
    *,
    created_by: int | None,
    target_release_id: int,
    evaluation_release_id: int | None = None,
    benchmark_suite_release_id: int | None = None,
    eval_protocol_release_id: int | None = None,
    judge_release_id: int | None = None,
    simulator_harness_release_id: int | None = None,
    candidate_simulator_release_id: int | None = None,
    replication_count: int = 5,
    seed: int = 1,
    environment_fingerprint: str = "",
    comparison_group: str = "",
    idempotency_key: str | None = None,
    require_published: bool = False,
) -> dict[str, Any]:
    """Create a run using the dual-axis model, with legacy read compatibility."""
    if evaluation_release_id is not None:
        return _create_dual_axis_eval_run(
            conn,
            created_by=created_by,
            target_release_id=target_release_id,
            evaluation_release_id=evaluation_release_id,
            replication_count=replication_count,
            seed=seed,
            environment_fingerprint=environment_fingerprint,
            comparison_group=comparison_group,
            idempotency_key=idempotency_key,
            require_published=require_published,
        )
    legacy_ids = (
        benchmark_suite_release_id,
        eval_protocol_release_id,
        judge_release_id,
        simulator_harness_release_id,
        candidate_simulator_release_id,
    )
    if any(value is None for value in legacy_ids):
        raise ValueError("必须提供 evaluation_release_id")
    return _create_legacy_eval_run(
        conn,
        created_by=created_by,
        target_release_id=target_release_id,
        benchmark_suite_release_id=benchmark_suite_release_id,
        eval_protocol_release_id=eval_protocol_release_id,
        judge_release_id=judge_release_id,
        simulator_harness_release_id=simulator_harness_release_id,
        candidate_simulator_release_id=candidate_simulator_release_id,
        replication_count=replication_count,
        seed=seed,
        environment_fingerprint=environment_fingerprint,
        comparison_group=comparison_group,
        idempotency_key=idempotency_key,
        require_published=require_published,
    )


def append_event(
    conn: sqlite3.Connection,
    run_id: int,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one durable event; callers commit the enclosing transaction."""
    sequence = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM eval_events WHERE run_id = ?",
        (run_id,),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO eval_events (run_id, sequence, event_type, payload_json)
        VALUES (?, ?, ?, ?)
        """,
        (run_id, sequence, event_type, _json_dumps(payload or {})),
    )
    return {
        "sequence": sequence,
        "event_type": event_type,
        "payload": payload or {},
    }


def list_events_after(
    conn: sqlite3.Connection, run_id: int, *, after_sequence: int = 0
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT sequence, event_type, payload_json
        FROM eval_events
        WHERE run_id = ? AND sequence > ?
        ORDER BY sequence
        """,
        (run_id, after_sequence),
    ).fetchall()
    return [
        {
            "sequence": row["sequence"],
            "event_type": row["event_type"],
            "payload": json.loads(row["payload_json"] or "{}"),
        }
        for row in rows
    ]
