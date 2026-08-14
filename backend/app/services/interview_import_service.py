"""Post-session MCP interview import lifecycle.

The service deliberately keeps the import staging model separate from native
chat turns until analysis succeeds.  That makes retries safe and prevents an
incomplete external transcript from looking like a native InterviewBoss
session.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from difflib import SequenceMatcher
from typing import Any

from app.db.connection import get_db_connection, get_user_job_position
from app.services.job_lifecycle import create_interview_import_analysis_job


MAX_CHUNK_CHARS = 200_000
MAX_IMPORT_TITLE_CHARS = 200
MAX_CONTEXT_CHARS = 50_000
MAX_EXTERNAL_ANALYSIS_CHARS = 100_000
IMPORT_ORIGIN = "external_mcp"
CONVERSATION_NAMESPACE = uuid.UUID("e6a03f9a-3a1d-4ac1-8f67-3a7c88b9ad7a")


class InterviewImportError(Exception):
    """Base error that can be rendered as a machine-readable MCP error."""

    code = "INTERVIEW_IMPORT_ERROR"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        retryable: bool | None = None,
        failed_chunks: list[dict[str, Any]] | None = None,
    ):
        super().__init__(message)
        if code:
            self.code = code
        if retryable is not None:
            self.retryable = retryable
        self.failed_chunks = failed_chunks or []


class ImportAccessError(InterviewImportError):
    code = "IMPORT_NOT_FOUND"


class ImportChunkConflict(InterviewImportError):
    code = "CHUNK_CONFLICT"


class ImportAnalysisError(InterviewImportError):
    code = "ANALYSIS_FAILED"
    retryable = True


def _json_loads(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _bounded_text(value: Any, *, name: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise InterviewImportError(
            f"{name} too long",
            code="INVALID_ARGUMENT",
            retryable=False,
        )
    return text


def _summary(row) -> dict[str, Any]:
    return {
        "import_id": row["id"],
        "status": row["status"],
        "title": row["title"],
        "job_position": row["job_position"],
        "company": row["company"],
        "interview_round": row["interview_round"],
        "recruiting_season": row["recruiting_season"],
        "job_id": row["job_id"],
        "conversation_id": row["conversation_id"],
        "analysis_attempt": row["analysis_attempt"],
        "error_code": row["error_code"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def _load_owned_import(conn, user_id: int, import_id: str):
    row = conn.execute(
        "SELECT * FROM interview_imports WHERE id = ? AND user_id = ?",
        (str(import_id), int(user_id)),
    ).fetchone()
    if not row:
        raise ImportAccessError("interview import does not exist")
    return row


def _load_import_for_analysis(conn, import_id: str):
    row = conn.execute(
        "SELECT * FROM interview_imports WHERE id = ?", (str(import_id),)
    ).fetchone()
    if not row:
        raise ImportAnalysisError("interview import does not exist", retryable=False)
    return row


def _profile_snapshot(conn, user_id: int, context: dict[str, Any]) -> tuple[dict, int | None, str | None]:
    context = dict(context or {})
    _, current_position = get_user_job_position(int(user_id))

    resume_id = context.get("resume_id")
    resume_text = None
    if resume_id:
        resume_row = conn.execute(
            "SELECT id, raw_text FROM user_resumes WHERE id = ? AND user_id = ?",
            (int(resume_id), int(user_id)),
        ).fetchone()
        if not resume_row:
            raise InterviewImportError(
                "resume does not belong to the current user",
                code="INVALID_RESUME",
            )
    else:
        resume_row = conn.execute(
            "SELECT id, raw_text FROM user_resumes WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (int(user_id),),
        ).fetchone()
    if resume_row:
        resume_id = int(resume_row["id"])
        resume_text = resume_row["raw_text"] or ""

    pref = conn.execute(
        "SELECT batch FROM user_recruitment_pref WHERE user_id = ?", (int(user_id),)
    ).fetchone()
    season_row = conn.execute(
        "SELECT value FROM user_profile WHERE key = 'active_season'"
    ).fetchone()
    snapshot = {
        **context,
        "job_position": _bounded_text(
            context.get("job_position") or current_position,
            name="job_position",
            limit=100,
        ),
        "company": _bounded_text(context.get("company"), name="company", limit=200),
        "interview_round": _bounded_text(
            context.get("interview_round") or context.get("round"),
            name="interview_round",
            limit=100,
        ),
        "recruiting_season": _bounded_text(
            context.get("recruiting_season")
            or (pref["batch"] if pref else "")
            or (season_row["value"] if season_row else ""),
            name="recruiting_season",
            limit=100,
        ),
        "resume_id": resume_id,
    }
    return snapshot, resume_id, resume_text


def start_import(
    user_id: int,
    *,
    client_request_id: str | None = None,
    title: str | None = None,
    context: dict[str, Any] | None = None,
    external_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or idempotently resume one external interview import."""
    request_id = _bounded_text(
        client_request_id or uuid.uuid4().hex,
        name="client_request_id",
        limit=128,
    )
    if not request_id:
        raise InterviewImportError("client_request_id is required", code="INVALID_ARGUMENT")
    title_text = _bounded_text(title, name="title", limit=MAX_IMPORT_TITLE_CHARS)
    context_json = _json_dump(context or {})
    external_json = _json_dump(external_analysis or {})
    if len(context_json) > MAX_CONTEXT_CHARS:
        raise InterviewImportError("context too long", code="INVALID_ARGUMENT")
    if len(external_json) > MAX_EXTERNAL_ANALYSIS_CHARS:
        raise InterviewImportError("external analysis too long", code="INVALID_ARGUMENT")

    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM interview_imports WHERE user_id = ? AND client_request_id = ?",
            (int(user_id), request_id),
        ).fetchone()
        if existing:
            return _summary(existing)

        snapshot, resume_id, resume_text = _profile_snapshot(conn, int(user_id), context or {})
        import_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO interview_imports (
                id, user_id, client_request_id, title, job_position, company,
                interview_round, recruiting_season, resume_id, resume_text,
                context_json, external_analysis_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                import_id,
                int(user_id),
                request_id,
                title_text,
                snapshot["job_position"],
                snapshot["company"],
                snapshot["interview_round"],
                snapshot["recruiting_season"],
                resume_id,
                resume_text,
                _json_dump(snapshot),
                external_json,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM interview_imports WHERE id = ?", (import_id,)
        ).fetchone()
    return _summary(row)


def _validate_chunk_args(
    stream_type: str,
    chunk_index: int,
    total_chunks: int,
    content: str,
    content_hash: str | None,
) -> tuple[str, int, int, str, str]:
    stream = str(stream_type or "").strip()
    if stream not in {"turns", "transcript"}:
        raise InterviewImportError("unsupported stream_type", code="INVALID_ARGUMENT")
    try:
        index = int(chunk_index)
        total = int(total_chunks)
    except (TypeError, ValueError):
        raise InterviewImportError("chunk index and total must be integers", code="INVALID_ARGUMENT")
    if total <= 0 or total > 10_000 or index < 0 or index >= total:
        raise InterviewImportError("invalid chunk range", code="INVALID_ARGUMENT")
    text = str(content or "")
    if not text:
        raise InterviewImportError("chunk content is empty", code="INVALID_ARGUMENT")
    if len(text) > MAX_CHUNK_CHARS:
        raise InterviewImportError("chunk is too large", code="CHUNK_TOO_LARGE")
    actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    supplied_hash = str(content_hash or actual_hash).strip().lower()
    if supplied_hash != actual_hash:
        raise InterviewImportError(
            "content_hash does not match chunk content",
            code="CHUNK_HASH_MISMATCH",
            retryable=True,
            failed_chunks=[
                {"stream_type": stream, "chunk_index": index, "expected_hash": actual_hash}
            ],
        )
    return stream, index, total, text, actual_hash


def upload_import_chunk(
    user_id: int,
    import_id: str,
    *,
    stream_type: str,
    chunk_index: int,
    total_chunks: int,
    content: str,
    content_hash: str | None = None,
) -> dict[str, Any]:
    """Store one resumable chunk; identical retries are successful no-ops."""
    stream, index, total, text, digest = _validate_chunk_args(
        stream_type, chunk_index, total_chunks, content, content_hash
    )
    with get_db_connection() as conn:
        row = _load_owned_import(conn, user_id, import_id)
        if row["status"] != "uploading":
            raise InterviewImportError(
                "chunks can only be uploaded while the import is uploading",
                code="IMPORT_NOT_WRITABLE",
                retryable=False,
            )
        existing = conn.execute(
            "SELECT content_hash, total_chunks, content FROM interview_import_chunks "
            "WHERE import_id = ? AND stream_type = ? AND chunk_index = ?",
            (str(import_id), stream, index),
        ).fetchone()
        if existing:
            if (
                existing["content_hash"] != digest
                or int(existing["total_chunks"]) != total
                or existing["content"] != text
            ):
                raise ImportChunkConflict(
                    "same chunk index was already uploaded with different content",
                    retryable=False,
                    failed_chunks=[{"stream_type": stream, "chunk_index": index}],
                )
            return {
                "import_id": str(import_id),
                "stream_type": stream,
                "chunk_index": index,
                "accepted": True,
                "idempotent": True,
            }

        conflicting_total = conn.execute(
            "SELECT DISTINCT total_chunks FROM interview_import_chunks "
            "WHERE import_id = ? AND stream_type = ?",
            (str(import_id), stream),
        ).fetchall()
        if conflicting_total and any(int(item[0]) != total for item in conflicting_total):
            raise InterviewImportError(
                "total_chunks changed for an existing stream",
                code="CHUNK_TOTAL_CONFLICT",
                failed_chunks=[{"stream_type": stream, "chunk_index": index}],
            )
        conn.execute(
            "INSERT INTO interview_import_chunks "
            "(import_id, stream_type, chunk_index, total_chunks, content_hash, content) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(import_id), stream, index, total, digest, text),
        )
        conn.execute(
            "UPDATE interview_imports SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (str(import_id),),
        )
        conn.commit()
    return {
        "import_id": str(import_id),
        "stream_type": stream,
        "chunk_index": index,
        "accepted": True,
        "idempotent": False,
    }


def _stream_state(conn, import_id: str) -> tuple[dict[str, list[int]], list[dict[str, Any]]]:
    rows = conn.execute(
        "SELECT stream_type, chunk_index, total_chunks FROM interview_import_chunks "
        "WHERE import_id = ? ORDER BY stream_type, chunk_index",
        (str(import_id),),
    ).fetchall()
    received: dict[str, list[int]] = {"turns": [], "transcript": []}
    missing: list[dict[str, Any]] = []
    totals: dict[str, int] = {}
    for row in rows:
        stream = row["stream_type"]
        received.setdefault(stream, []).append(int(row["chunk_index"]))
        totals.setdefault(stream, int(row["total_chunks"]))
    for stream, total in totals.items():
        missing_indexes = [index for index in range(total) if index not in received[stream]]
        if missing_indexes:
            missing.append({"stream_type": stream, "chunk_indexes": missing_indexes})
    return received, missing


def complete_import(user_id: int, import_id: str) -> dict[str, Any]:
    """Seal uploaded chunks and create a durable asynchronous analysis job."""
    with get_db_connection() as conn:
        row = _load_owned_import(conn, user_id, import_id)
        if row["status"] in {"queued", "processing", "completed"}:
            return _summary(row)
        if row["status"] != "uploading":
            raise InterviewImportError("import is not ready to complete", code="IMPORT_NOT_WRITABLE")
        received, missing = _stream_state(conn, import_id)
        if missing:
            raise InterviewImportError(
                "some chunks are still missing",
                code="MISSING_CHUNKS",
                retryable=True,
                failed_chunks=missing,
            )
        if not received["turns"] and not received["transcript"]:
            raise InterviewImportError(
                "at least one transcript stream is required",
                code="EMPTY_IMPORT",
                retryable=True,
            )
        attempt = int(row["analysis_attempt"] or 0) + 1
        job_id, _ = create_interview_import_analysis_job(
            conn, str(import_id), int(user_id), attempt
        )
        conn.execute(
            "UPDATE interview_imports SET status = 'queued', job_id = ?, "
            "analysis_attempt = ?, error_code = NULL, error_message = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (job_id, attempt, str(import_id)),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM interview_imports WHERE id = ?", (str(import_id),)
        ).fetchone()
    result = _summary(row)
    result["job_id"] = job_id
    return result


def get_import_status(user_id: int, import_id: str) -> dict[str, Any]:
    with get_db_connection() as conn:
        row = _load_owned_import(conn, user_id, import_id)
        received, missing = _stream_state(conn, import_id)
        result = _summary(row)
        result.update({"received_chunks": received, "missing_chunks": missing})
        if row["job_id"]:
            job = conn.execute(
                "SELECT id, status, progress_current, progress_total, progress_message, "
                "result, last_error AS error, attempts FROM jobs WHERE id = ? AND created_by = ?",
                (row["job_id"], int(user_id)),
            ).fetchone()
            result["job"] = dict(job) if job else None
        else:
            result["job"] = None
    return result


def retry_import_analysis(user_id: int, import_id: str) -> dict[str, Any]:
    with get_db_connection() as conn:
        row = _load_owned_import(conn, user_id, import_id)
        if row["status"] == "completed":
            return _summary(row)
        if row["status"] in {"queued", "processing"}:
            raise InterviewImportError("analysis is already running", code="ANALYSIS_IN_PROGRESS")
        if row["status"] != "failed":
            raise InterviewImportError(
                "only a failed analysis can be retried", code="ANALYSIS_NOT_RETRYABLE"
            )
        received, missing = _stream_state(conn, import_id)
        if missing:
            raise InterviewImportError(
                "some chunks are still missing",
                code="MISSING_CHUNKS",
                retryable=True,
                failed_chunks=missing,
            )
        attempt = int(row["analysis_attempt"] or 0) + 1
        old_job_id = row["job_id"]
        job_id, _ = create_interview_import_analysis_job(
            conn,
            str(import_id),
            int(user_id),
            attempt,
            parent_job_id=int(old_job_id) if old_job_id else None,
        )
        conn.execute(
            "UPDATE interview_imports SET status = 'queued', job_id = ?, "
            "analysis_attempt = ?, error_code = NULL, error_message = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (job_id, attempt, str(import_id)),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM interview_imports WHERE id = ?", (str(import_id),)
        ).fetchone()
    result = _summary(row)
    result["job_id"] = job_id
    return result


def _normalize_question(text: str) -> str:
    return re.sub(r"[\W_]+", "", str(text or ""), flags=re.UNICODE).lower()


def _parse_turns(raw: str | None, raw_transcript: str | None) -> list[dict[str, Any]]:
    if raw and raw.strip():
        parsed = _json_loads(raw, None)
        if not isinstance(parsed, list):
            raise ImportAnalysisError("turns stream must be a JSON array", code="INVALID_TURNS")
        turns: list[dict[str, Any]] = []
        for index, item in enumerate(parsed, start=1):
            if not isinstance(item, dict):
                raise ImportAnalysisError("each turn must be an object", code="INVALID_TURNS")
            speaker = str(item.get("speaker") or item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if speaker not in {"interviewer", "candidate", "system"} or not content:
                raise ImportAnalysisError(
                    "turn speaker must be interviewer, candidate, or system and content is required",
                    code="INVALID_TURNS",
                )
            turns.append(
                {
                    "sequence": int(item.get("sequence") or index),
                    "speaker": speaker,
                    "content": content,
                    "question_id": item.get("question_id"),
                    "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                }
            )
        return turns
    if raw_transcript and raw_transcript.strip():
        return [{"sequence": 1, "speaker": "system", "content": raw_transcript.strip(), "question_id": None, "metadata": {"raw_fallback": True}}]
    raise ImportAnalysisError("no interview content was uploaded", code="EMPTY_IMPORT", retryable=True)


def _visible_question(conn, user_id: int, question_id: Any) -> dict[str, Any] | None:
    try:
        question_id = int(question_id)
    except (TypeError, ValueError):
        return None
    row = conn.execute(
        "SELECT id, question FROM question_bank "
        "WHERE id = ? AND deleted_at IS NULL AND status = 'approved' "
        "AND (owner_id IS NULL OR owner_id = ?)",
        (question_id, int(user_id)),
    ).fetchone()
    return dict(row) if row else None


def _match_question(conn, user_id: int, turn: dict[str, Any]) -> tuple[int | None, str | None, str]:
    candidate = _visible_question(conn, user_id, turn.get("question_id")) if turn.get("question_id") is not None else None
    if candidate:
        similarity = SequenceMatcher(
            None,
            _normalize_question(turn["content"]),
            _normalize_question(candidate["question"]),
        ).ratio()
        if similarity >= 0.85:
            return int(candidate["id"]), candidate["question"], "question_bank"
        return None, None, "external_question"

    normalized = _normalize_question(turn["content"])
    if not normalized:
        return None, None, "external_question"
    rows = conn.execute(
        "SELECT id, question FROM question_bank "
        "WHERE deleted_at IS NULL AND status = 'approved' "
        "AND (owner_id IS NULL OR owner_id = ?)",
        (int(user_id),),
    ).fetchall()
    for row in rows:
        if _normalize_question(row["question"]) == normalized:
            return int(row["id"]), row["question"], "question_bank"
    return None, None, "external_question"


def _report(turns: list[dict[str, Any]], external_analysis: dict[str, Any]) -> dict[str, Any]:
    questions = []
    for index, turn in enumerate(turns):
        if turn["speaker"] != "interviewer":
            continue
        answer = ""
        if index + 1 < len(turns) and turns[index + 1]["speaker"] == "candidate":
            answer = turns[index + 1]["content"]
        questions.append(
            {
                "sequence": turn["sequence"],
                "question_id": turn.get("matched_question_id"),
                "question_text": turn.get("matched_question_text") or turn["content"],
                "question_source": turn.get("question_source", "external_question"),
                "answer": answer,
            }
        )
    matched = sum(1 for item in questions if item["question_id"] is not None)
    return {
        "schema_version": 1,
        "analysis_source": "interview_boss_import_v1",
        "summary": {
            "turn_count": len(turns),
            "question_count": len(questions),
            "answer_count": sum(1 for turn in turns if turn["speaker"] == "candidate"),
            "matched_question_count": matched,
            "external_question_count": len(questions) - matched,
        },
        "official_analysis": {
            "status": "generated",
            "score": None,
            "note": "官方报告基于导入的结构化面试记录生成；外部评分仅作为外部分析保留。",
        },
        "questions": questions,
        "external_analysis": external_analysis or {},
    }


def _project_native_record(
    conn,
    row,
    user_id: int,
    turns: list[dict[str, Any]],
    report: dict[str, Any],
) -> str:
    conversation_id = str(uuid.uuid5(CONVERSATION_NAMESPACE, str(row["id"])))
    context_snapshot = _json_loads(row["context_json"], {})
    metadata = {
        "origin": IMPORT_ORIGIN,
        "import_id": row["id"],
        "sealed": True,
        "context_snapshot": context_snapshot,
        "external_analysis": _json_loads(row["external_analysis_json"], {}),
        "official_report": report,
        "analysis_attempt": row["analysis_attempt"],
    }
    title = row["title"] or "GPT 模拟面试"
    conn.execute(
        "INSERT OR IGNORE INTO chat_conversations "
        "(id, user_id, mode, title, resume_text, status, job_position, metadata) "
        "VALUES (?, ?, 'free_practice', ?, ?, 'active', ?, ?)",
        (
            conversation_id,
            int(user_id),
            title,
            row["resume_text"],
            row["job_position"],
            _json_dump(metadata),
        ),
    )
    message_count = conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()[0]
    if not message_count:
        role_map = {"interviewer": "assistant", "candidate": "user", "system": "system"}
        for turn in turns:
            message_metadata = {
                "origin": IMPORT_ORIGIN,
                "import_id": row["id"],
                "sequence": turn["sequence"],
                "question_id": turn.get("matched_question_id"),
                "question_source": turn.get("question_source", "external_question"),
                **turn.get("metadata", {}),
            }
            conn.execute(
                "INSERT INTO chat_messages "
                "(conversation_id, role, content, token_count, metadata) VALUES (?, ?, ?, 0, ?)",
                (
                    conversation_id,
                    role_map[turn["speaker"]],
                    turn["content"],
                    _json_dump(message_metadata),
                ),
            )
    for turn in turns:
        question_id = turn.get("matched_question_id")
        if question_id is not None:
            conn.execute(
                "INSERT INTO interview_asked_questions "
                "(user_id, conversation_id, question_id) "
                "SELECT ?, ?, ? WHERE NOT EXISTS ("
                "SELECT 1 FROM interview_asked_questions WHERE conversation_id = ? AND question_id = ?)",
                (int(user_id), conversation_id, int(question_id), conversation_id, int(question_id)),
            )
    conn.execute(
        "UPDATE chat_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (conversation_id,),
    )
    return conversation_id


def analyze_import(import_id: str, job_id: int | None = None) -> dict[str, Any]:
    """Analyze a complete import and atomically publish its native projection."""
    try:
        with get_db_connection() as conn:
            row = _load_import_for_analysis(conn, import_id)
            if row["status"] == "completed":
                return _summary(row)
            if row["status"] not in {"queued", "processing"}:
                raise ImportAnalysisError(
                    "import is not queued for analysis",
                    code="ANALYSIS_NOT_READY",
                    retryable=False,
                )
            if job_id is not None and row["job_id"] and int(row["job_id"]) != int(job_id):
                raise ImportAnalysisError("analysis job is stale", code="STALE_ANALYSIS_JOB", retryable=False)
            conn.execute(
                "UPDATE interview_imports SET status = 'processing', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (str(import_id),),
            )
            chunks = conn.execute(
                "SELECT stream_type, content FROM interview_import_chunks "
                "WHERE import_id = ? ORDER BY stream_type, chunk_index",
                (str(import_id),),
            ).fetchall()
            turns_raw = "".join(row["content"] for row in chunks if row["stream_type"] == "turns")
            transcript_raw = "".join(row["content"] for row in chunks if row["stream_type"] == "transcript")
            turns = _parse_turns(turns_raw, transcript_raw)
            for turn in turns:
                if turn["speaker"] == "interviewer":
                    qid, qtext, source = _match_question(conn, int(row["user_id"]), turn)
                    turn["matched_question_id"] = qid
                    turn["matched_question_text"] = qtext
                    turn["question_source"] = source
            external_analysis = _json_loads(row["external_analysis_json"], {})
            report = _report(turns, external_analysis)
            conversation_id = _project_native_record(
                conn, row, int(row["user_id"]), turns, report
            )
            conn.execute(
                "UPDATE interview_imports SET status = 'completed', conversation_id = ?, "
                "report_json = ?, error_code = NULL, error_message = NULL, "
                "completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conversation_id, _json_dump(report), str(import_id)),
            )
            conn.commit()
            completed = conn.execute(
                "SELECT * FROM interview_imports WHERE id = ?", (str(import_id),)
            ).fetchone()
        return _summary(completed)
    except InterviewImportError:
        with get_db_connection() as conn:
            row = _load_import_for_analysis(conn, import_id)
            if row["status"] != "completed":
                error = _last_error()
                conn.execute(
                    "UPDATE interview_imports SET status = 'failed', error_code = ?, "
                    "error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (error["code"], error["message"], str(import_id)),
                )
                conn.commit()
        raise
    except Exception as exc:
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE interview_imports SET status = 'failed', error_code = 'ANALYSIS_FAILED', "
                "error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (str(exc)[:500], str(import_id)),
            )
            conn.commit()
        raise ImportAnalysisError("interview import analysis failed", retryable=True) from exc


def _last_error() -> dict[str, str]:
    import sys

    error = sys.exc_info()[1]
    if isinstance(error, InterviewImportError):
        return {"code": error.code, "message": str(error)[:500]}
    return {"code": "ANALYSIS_FAILED", "message": str(error)[:500]}


def list_interview_records(user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM interview_imports WHERE user_id = ? AND status = 'completed' "
            "ORDER BY completed_at DESC, created_at DESC LIMIT ?",
            (int(user_id), safe_limit),
        ).fetchall()
    return [_summary(row) for row in rows]


def get_interview_record(
    user_id: int, import_id: str, *, include_raw: bool = False
) -> dict[str, Any]:
    with get_db_connection() as conn:
        row = _load_owned_import(conn, user_id, import_id)
        result = _summary(row)
        result["context_snapshot"] = _json_loads(row["context_json"], {})
        result["external_analysis"] = _json_loads(row["external_analysis_json"], {})
        result["report"] = _json_loads(row["report_json"], None)
        if row["conversation_id"]:
            messages = conn.execute(
                "SELECT id, role, content, token_count, metadata, created_at "
                "FROM chat_messages WHERE conversation_id = ? ORDER BY id ASC",
                (row["conversation_id"],),
            ).fetchall()
            result["messages"] = [
                {
                    "id": item["id"],
                    "role": item["role"],
                    "content": item["content"],
                    "token_count": item["token_count"],
                    "metadata": _json_loads(item["metadata"], {}),
                    "created_at": item["created_at"],
                }
                for item in messages
            ]
        if include_raw:
            chunks = conn.execute(
                "SELECT stream_type, chunk_index, content FROM interview_import_chunks "
                "WHERE import_id = ? ORDER BY stream_type, chunk_index",
                (str(import_id),),
            ).fetchall()
            result["raw_transcript"] = "".join(
                item["content"] for item in chunks if item["stream_type"] == "transcript"
            )
            result["structured_turns_json"] = "".join(
                item["content"] for item in chunks if item["stream_type"] == "turns"
            )
    return result


def get_interview_report(user_id: int, import_id: str) -> dict[str, Any] | None:
    with get_db_connection() as conn:
        row = _load_owned_import(conn, user_id, import_id)
        if row["status"] != "completed":
            return None
        return _json_loads(row["report_json"], None)


def get_candidate_profile(user_id: int, *, include_resume: bool = False) -> dict[str, Any]:
    with get_db_connection() as conn:
        _, position = get_user_job_position(int(user_id))
        resume = conn.execute(
            "SELECT id, filename, raw_text, created_at FROM user_resumes "
            "WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (int(user_id),),
        ).fetchone()
        pref = conn.execute(
            "SELECT graduation_year, batch, pace, daily_capacity "
            "FROM user_recruitment_pref WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
    profile = {
        "job_position": position,
        "recruiting": dict(pref) if pref else {},
        "resume": (
            {
                "id": resume["id"],
                "filename": resume["filename"],
                "created_at": resume["created_at"],
                **({"raw_text": resume["raw_text"]} if include_resume else {}),
            }
            if resume
            else None
        ),
    }
    return profile
