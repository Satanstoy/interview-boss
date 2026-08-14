"""Durable side-effect 与读模型服务 - 从 chat_service 机械抽取。

职责:side-effect job 的 claim/complete/fail、记忆抽取 job、CandidateSet、
面试事件与 assistant generation 读模型。

共享原始块来自 chat_common,避免循环依赖。
"""
import json
import logging
import hashlib
import uuid
from app.db.connection import get_db_connection
from app.services.chat_common import (
    ConversationNotFound,
    SideEffectConflict,
    SIDE_EFFECT_MAX_ATTEMPTS,
)

logger = logging.getLogger("interview-boss")


def _side_effect_job_dict(row) -> dict:
    payload = {}
    try:
        parsed = json.loads(row["payload_json"] or "{}")
        payload = parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    result = dict(row)
    result["payload"] = payload
    result.pop("payload_json", None)
    return result


def get_side_effect_job(job_id: str, user_id: int | None = None) -> dict | None:
    with get_db_connection() as conn:
        where = ["id = ?"]
        params: list[object] = [job_id]
        if user_id is not None:
            where.append("user_id = ?")
            params.append(user_id)
        row = conn.execute(
            "SELECT id, kind, user_id, conversation_id, source_turn_id, payload_json, status, "
            "attempts, available_at, locked_at, finished_at, last_error, created_at "
            "FROM chat_side_effect_jobs WHERE " + " AND ".join(where),
            params,
        ).fetchone()
    return _side_effect_job_dict(row) if row else None


def claim_side_effect_job(
    *,
    worker_id: str,
    kind: str | None = None,
    source_turn_id: str | None = None,
) -> dict | None:
    """Claim one ready job; the claim is durable across worker restarts."""
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        where = [
            "status IN ('pending', 'failed')",
            "available_at <= CURRENT_TIMESTAMP",
        ]
        params: list[object] = []
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if source_turn_id:
            where.append("source_turn_id = ?")
            params.append(source_turn_id)
        row = conn.execute(
            "SELECT id FROM chat_side_effect_jobs WHERE " + " AND ".join(where) + " "
            "ORDER BY available_at ASC, created_at ASC LIMIT 1",
            params,
        ).fetchone()
        if not row:
            conn.rollback()
            return None
        updated = conn.execute(
            "UPDATE chat_side_effect_jobs SET status = 'running', attempts = attempts + 1, "
            "locked_at = CURRENT_TIMESTAMP, last_error = NULL WHERE id = ? "
            "AND status IN ('pending', 'failed')",
            (row["id"],),
        )
        if updated.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
    job = get_side_effect_job(row["id"])
    if job:
        job["worker_id"] = worker_id
    return job


def complete_side_effect_job(job_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.execute(
            "UPDATE chat_side_effect_jobs SET status = 'completed', "
            "finished_at = CURRENT_TIMESTAMP, locked_at = NULL "
            "WHERE id = ? AND status = 'running'",
            (job_id,),
        )
        conn.commit()
        return cursor.rowcount == 1


def fail_side_effect_job(job_id: str, error: str, *, retry: bool = True) -> bool:
    """Retry transient failures with bounded exponential backoff."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT attempts FROM chat_side_effect_jobs WHERE id = ? AND status = 'running'",
            (job_id,),
        ).fetchone()
        if not row:
            return False
        attempts = int(row["attempts"] or 0)
        terminal = not retry or attempts >= SIDE_EFFECT_MAX_ATTEMPTS
        status = "dead_letter" if terminal else "failed"
        delay = min(300, 2 ** max(0, attempts - 1))
        conn.execute(
            "UPDATE chat_side_effect_jobs SET status = ?, last_error = ?, locked_at = NULL, "
            "finished_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END, "
            "available_at = CASE WHEN ? THEN available_at ELSE datetime('now', ?) END "
            "WHERE id = ?",
            (
                status,
                str(error or "side_effect_failed")[:500],
                terminal,
                terminal,
                f"+{delay} seconds",
                job_id,
            ),
        )
        conn.commit()
        return True


def commit_memory_extraction_job(
    job_id: str,
    memories: list[dict],
    note_parts: list[str],
) -> dict:
    """Validate and atomically persist extracted memories plus session notes."""
    allowed_types = {"weakness", "strength", "preference", "topic"}
    accepted: list[dict] = []
    for item in memories or []:
        if not isinstance(item, dict):
            continue
        memory_type = str(item.get("type") or "").strip()
        content = str(item.get("content") or "").strip()
        if memory_type not in allowed_types or not content or len(content) > 500:
            continue
        accepted.append({"type": memory_type, "content": content})

    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        job = conn.execute(
            "SELECT * FROM chat_side_effect_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if not job:
            conn.rollback()
            raise LookupError("side-effect job not found")
        if job["status"] == "completed":
            conn.rollback()
            return {"status": "completed", "memory_count": 0, "notes_updated": False}
        if job["status"] != "running":
            conn.rollback()
            raise SideEffectConflict("side_effect_job")
        source_turn = conn.execute(
            "SELECT status FROM chat_turns WHERE id = ? AND conversation_id = ? AND user_id = ?",
            (job["source_turn_id"], job["conversation_id"], job["user_id"]),
        ).fetchone()
        if not source_turn or source_turn["status"] != "completed":
            conn.execute(
                "UPDATE chat_side_effect_jobs SET status = 'skipped', finished_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (job_id,),
            )
            conn.commit()
            return {"status": "skipped", "memory_count": 0, "notes_updated": False}

        memory_count = 0
        for item in accepted:
            content = item["content"]
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            exists = conn.execute(
                "SELECT id FROM chat_memories WHERE user_id = ? AND content_hash = ? "
                "AND is_active = 1 AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)",
                (job["user_id"], content_hash),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO chat_memories (user_id, memory_type, content, source, summary, "
                "source_turn_id, source_job_id, memory_schema_version, content_hash) "
                "VALUES (?, ?, ?, 'auto_extract', ?, ?, ?, 1, ?)",
                (
                    job["user_id"],
                    item["type"],
                    content,
                    content[:77] + "..." if len(content) > 80 else content,
                    job["source_turn_id"],
                    job_id,
                    content_hash,
                ),
            )
            memory_count += 1

        notes_updated = False
        notes = [str(note).strip() for note in note_parts or [] if str(note).strip()]
        if notes:
            conversation = conn.execute(
                "SELECT session_notes, session_notes_version FROM chat_conversations "
                "WHERE id = ? AND user_id = ?",
                (job["conversation_id"], job["user_id"]),
            ).fetchone()
            if not conversation:
                conn.rollback()
                raise ConversationNotFound("conversation not found")
            current = conversation["session_notes"] or ""
            combined = "\n".join(part for part in (current, "\n".join(notes)) if part)
            if len(combined) > 2000:
                combined = "\n".join(combined.splitlines()[-80:])[-2000:]
            version = int(conversation["session_notes_version"] or 0)
            updated = conn.execute(
                "UPDATE chat_conversations SET session_notes = ?, session_notes_version = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ? "
                "AND session_notes_version = ?",
                (
                    combined,
                    version + 1,
                    job["conversation_id"],
                    job["user_id"],
                    version,
                ),
            )
            if updated.rowcount != 1:
                conn.rollback()
                raise SideEffectConflict("session_notes", version)
            notes_updated = True

        conn.execute(
            "UPDATE chat_side_effect_jobs SET status = 'completed', finished_at = CURRENT_TIMESTAMP, "
            "locked_at = NULL WHERE id = ? AND status = 'running'",
            (job_id,),
        )
        conn.commit()
    return {
        "status": "completed",
        "memory_count": memory_count,
        "notes_updated": notes_updated,
    }


def create_candidate_set(
    *,
    user_id: int,
    conversation_id: str,
    source: str,
    items: list[dict],
    expires_at: str,
    source_turn_id: str | None = None,
    schema_version: int = 1,
) -> str:
    """Persist a server-owned candidate set containing references, not authority text."""
    normalized = []
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        try:
            question_id = int(item.get("id", item.get("question_id")))
        except (TypeError, ValueError):
            continue
        normalized.append(
            {
                "question_id": question_id,
                "rank": int(item.get("rank", index)),
                "source": str(item.get("source") or source),
            }
        )
    candidate_set_id = str(uuid.uuid4())
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO chat_candidate_sets "
            "(id, user_id, conversation_id, source, source_turn_id, items_json, schema_version, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                candidate_set_id,
                user_id,
                conversation_id,
                source,
                source_turn_id,
                json.dumps(normalized, ensure_ascii=False),
                schema_version,
                expires_at,
            ),
        )
        conn.commit()
    return candidate_set_id


def get_candidate_set(
    candidate_set_id: str, user_id: int, conversation_id: str
) -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM chat_candidate_sets WHERE id = ? AND user_id = ? AND conversation_id = ?",
            (candidate_set_id, user_id, conversation_id),
        ).fetchone()
        if not row:
            return None
        if (
            row["status"] == "available"
            and row["expires_at"]
            <= conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
        ):
            conn.execute(
                "UPDATE chat_candidate_sets SET status = 'expired' WHERE id = ?",
                (candidate_set_id,),
            )
            conn.commit()
            return None
    try:
        items = json.loads(row["items_json"] or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        items = []
    result = dict(row)
    result["items"] = items if isinstance(items, list) else []
    result.pop("items_json", None)
    return result


def consume_candidate_set(
    candidate_set_id: str,
    *,
    user_id: int,
    conversation_id: str,
    selected_item_id: int,
) -> dict:
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM chat_candidate_sets WHERE id = ? AND user_id = ? AND conversation_id = ?",
            (candidate_set_id, user_id, conversation_id),
        ).fetchone()
        if not row:
            conn.rollback()
            raise LookupError("candidate set not found")
        if (
            row["status"] != "available"
            or row["expires_at"]
            <= conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
        ):
            conn.execute(
                "UPDATE chat_candidate_sets SET status = 'expired' WHERE id = ? AND status = 'available'",
                (candidate_set_id,),
            )
            conn.commit()
            raise ValueError("candidate set is unavailable")
        items = json.loads(row["items_json"] or "[]")
        selected = next(
            (
                item
                for item in items
                if int(item.get("question_id", 0)) == int(selected_item_id)
            ),
            None,
        )
        if not selected:
            conn.rollback()
            raise ValueError("selected question is not in candidate set")
        conn.execute(
            "UPDATE chat_candidate_sets SET status = 'consumed', selected_item_id = ?, "
            "consumed_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'available'",
            (selected_item_id, candidate_set_id),
        )
        conn.commit()
    return selected


def resolve_candidate_question(
    candidate_set_id: str,
    *,
    user_id: int,
    conversation_id: str,
    selected_item_id: int,
) -> dict:
    """Consume a candidate reference, then reload authoritative question content."""
    selected = consume_candidate_set(
        candidate_set_id,
        user_id=user_id,
        conversation_id=conversation_id,
        selected_item_id=selected_item_id,
    )
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, question, cat1, cat2, tags, difficulty, sources "
            "FROM question_bank WHERE id = ? AND deleted_at IS NULL AND status = 'approved'",
            (selected["question_id"],),
        ).fetchone()
    if not row:
        raise LookupError("candidate question is no longer authoritative")
    return dict(row)


def append_interview_event(
    *,
    user_id: int,
    conversation_id: str,
    turn_id: str,
    event_key: str,
    event_type: str,
    payload: dict,
    schema_version: int = 1,
) -> int:
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO interview_events "
            "(user_id, conversation_id, turn_id, event_key, event_type, payload_json, schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                conversation_id,
                turn_id,
                event_key,
                event_type,
                json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
                schema_version,
            ),
        )
        conn.commit()
        if cursor.rowcount:
            return int(cursor.lastrowid)
        row = conn.execute(
            "SELECT id FROM interview_events WHERE turn_id = ? AND event_key = ?",
            (turn_id, event_key),
        ).fetchone()
        return int(row["id"])


def get_interview_events(
    conversation_id: str, user_id: int | None = None
) -> list[dict]:
    with get_db_connection() as conn:
        where = ["conversation_id = ?"]
        params: list[object] = [conversation_id]
        if user_id is not None:
            where.append("user_id = ?")
            params.append(user_id)
        rows = conn.execute(
            "SELECT id, user_id, conversation_id, turn_id, event_key, event_type, "
            "payload_json, schema_version, created_at FROM interview_events WHERE "
            + " AND ".join(where)
            + " ORDER BY id ASC",
            params,
        ).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        try:
            payload = json.loads(item.pop("payload_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        item["payload"] = payload if isinstance(payload, dict) else {}
        events.append(item)
    return events


def fold_interview_events(events: list[dict]) -> dict:
    """Fold domain events into a deterministic lifecycle/coverage read model."""
    state = "technical"
    coverage: dict[str, int] = {}
    last_turn_id = None
    transitions = {
        "technical": {"candidate_question", "final_summary", "closed"},
        "candidate_question": {"final_summary", "closed"},
        "final_summary": {"closed"},
        "closed": set(),
    }
    for event in events or []:
        payload = event.get("payload") if isinstance(event, dict) else {}
        payload = payload if isinstance(payload, dict) else {}
        last_turn_id = event.get("turn_id") or last_turn_id
        if event.get("event_type") == "coverage":
            phase = str(payload.get("phase") or "").strip()
            if payload.get("counts_toward_target") is True and phase:
                coverage[phase] = coverage.get(phase, 0) + 1
        elif event.get("event_type") == "state_transition":
            target = str(payload.get("to") or "")
            if target in transitions.get(state, set()):
                state = target
    return {"state": state, "coverage": coverage, "last_turn_id": last_turn_id}


def record_assistant_generation(
    *,
    user_id: int,
    conversation_id: str,
    turn_id: str,
    message_id: int,
    source_turn_id: str,
    contract_hash: str = "",
    evidence_refs: list[str] | None = None,
    parent_generation_id: str | None = None,
) -> str:
    generation_id = str(uuid.uuid4())
    with get_db_connection() as conn:
        if parent_generation_id is None:
            parent = conn.execute(
                "SELECT id FROM assistant_generations WHERE conversation_id = ? AND visible = 1 "
                "ORDER BY created_at DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()
            parent_generation_id = parent["id"] if parent else None
        conn.execute(
            "UPDATE assistant_generations SET visible = 0 WHERE conversation_id = ?",
            (conversation_id,),
        )
        conn.execute(
            "INSERT INTO assistant_generations "
            "(id, user_id, conversation_id, turn_id, message_id, parent_generation_id, "
            "source_turn_id, contract_hash, evidence_refs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                generation_id,
                user_id,
                conversation_id,
                turn_id,
                message_id,
                parent_generation_id,
                source_turn_id,
                contract_hash,
                json.dumps(evidence_refs or [], ensure_ascii=False),
            ),
        )
        conn.commit()
    return generation_id


def get_current_assistant_generation(conversation_id: str, user_id: int) -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM assistant_generations WHERE conversation_id = ? AND user_id = ? "
            "AND visible = 1 ORDER BY created_at DESC LIMIT 1",
            (conversation_id, user_id),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result["evidence_refs"] = json.loads(result.pop("evidence_refs_json") or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        result["evidence_refs"] = []
    return result
