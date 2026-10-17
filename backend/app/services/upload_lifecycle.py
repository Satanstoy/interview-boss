"""上传接受生命周期（UR-003 / AC-021、AC-022）。

契约（contracts.md §2.1）：

1. 校验认证主体、target 枚举、输入类型、文件数量/MIME/字节上限；
   非法值返回明确 400/413，**不静默改 target**。
2. 文件大小先看 ``UploadFile.size``：超限在读取前拒绝，不把大文件读进内存。
3. 服务端计算 policy 与 request_hash；策略字段只能来自认证主体。
4. 原稿 + 根任务 + attempt + 首个 job **同一事务**；本模块不 commit。
5. 返回稳定 ``import_id``、``status_url``、``created``；重复同键同 hash 复用同一根任务。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass

from app.core.config import MAX_FILE_SIZE, MAX_TOTAL_UPLOAD_SIZE
from app.services.upload_credentials import UploadCredentialError
from app.services.upload_policy import (
    initial_preflight_scopes,
    resolve_upload_policy,
    sanitize_client_policy_fields,
)
from app.services.upload_repository import (
    UPLOAD_PIPELINE_VERSION_DEFAULT,
    create_attempt,
    create_or_get_import,
)

logger = logging.getLogger("interview-boss")

UPLOAD_JOB_TYPE = "submit_import"
MAX_FILES = 20
FIRST_WORK_KEY = "extract:document:v1"
SUBMIT_PHASES = ["extract", "fill", "tag", "match", "save", "cluster"]
SUPPORTED_UPLOAD_PIPELINE_VERSION = UPLOAD_PIPELINE_VERSION_DEFAULT


def _system_taxonomy_fingerprint(conn, position_name: str) -> str | None:
    """Fingerprint the system taxonomy that the upload was accepted against."""

    if not position_name:
        return None
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info('taxonomy')").fetchall()
    }
    if "tags_json" in columns:
        row = conn.execute(
            "SELECT categories_json, tags_json FROM taxonomy "
            "WHERE position_name = ? AND source = 'system' AND owner_id IS NULL",
            (position_name,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT categories_json, '[]' AS tags_json FROM taxonomy "
            "WHERE position_name = ? AND source = 'system' AND owner_id IS NULL",
            (position_name,),
        ).fetchone()
    if row is None:
        return None
    snapshot = {}
    for key in ("categories_json", "tags_json"):
        raw = row[key] or "[]"
        try:
            snapshot[key] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            snapshot[key] = raw
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def upload_execution_blocker(conn, root, policy: dict) -> tuple[str, str] | None:
    """Return a stable blocker when queued work no longer matches its source contract."""

    root = dict(root)
    if root.get("interview_id") is not None:
        source = conn.execute(
            "SELECT deleted_at FROM interview WHERE id = ?", (root["interview_id"],)
        ).fetchone()
        if source is None or source["deleted_at"] is not None:
            return (
                "SOURCE_DELETED",
                "原文已被删除或不存在，任务不会重建已删除内容；请重新提交材料。",
            )

    position_id = root.get("position_id")
    position_name = str(root.get("position_name") or "")
    position = None
    if position_id is not None:
        position = conn.execute(
            "SELECT is_deleted FROM job_positions WHERE id = ?", (position_id,)
        ).fetchone()
        if position is None or bool(position["is_deleted"]):
            return "POSITION_RETIRED", "目标岗位已下线，请选择当前有效岗位后重新提交。"
    elif position_name:
        position = conn.execute(
            "SELECT is_deleted FROM job_positions WHERE name = ?", (position_name,)
        ).fetchone()
        if position is not None and bool(position["is_deleted"]):
            return "POSITION_RETIRED", "目标岗位已下线，请选择当前有效岗位后重新提交。"

    if str(root.get("pipeline_version") or "") != SUPPORTED_UPLOAD_PIPELINE_VERSION:
        return (
            "PIPELINE_VERSION_UNSUPPORTED",
            "任务使用的处理流程版本当前不受支持；请重新提交材料以显式重新分析。",
        )

    if "taxonomy_fingerprint" in policy and position_name:
        accepted_fingerprint = policy.get("taxonomy_fingerprint") or "missing"
        current_fingerprint = _system_taxonomy_fingerprint(conn, position_name) or "missing"
        if current_fingerprint != accepted_fingerprint:
            return (
                "TAXONOMY_CHANGED",
                "岗位分类体系在任务排队后已更新；请重新提交材料以显式重新分析。",
            )
    return None


class UploadInputError(Exception):
    """输入校验失败；``status_code`` 直接决定 HTTP 400/413。"""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class UploadFileMeta:
    """一个待上传文件的元信息（内容未读入内存前即可校验）。"""

    filename: str
    content_type: str
    size: int
    mime: str | None = None


def validate_files(files) -> list[UploadFileMeta]:
    """数量、类型、单文件与总大小校验；超限在读取内容前就拒绝。"""

    meta_files = list(files or [])
    if len(meta_files) > MAX_FILES:
        raise UploadInputError("INVALID_INPUT", f"最多上传 {MAX_FILES} 个文件")

    total_size = 0
    for meta in meta_files:
        content_type = (meta.content_type or "").lower()
        if not content_type.startswith("image/"):
            raise UploadInputError("INVALID_INPUT", f"文件 {meta.filename} 不是有效的图片文件")
        if int(meta.size) > MAX_FILE_SIZE:
            raise UploadInputError(
                "FILE_TOO_LARGE",
                f"图片 {meta.filename} 超过大小限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）",
                status_code=413,
            )
        total_size += int(meta.size)
        if total_size > MAX_TOTAL_UPLOAD_SIZE:
            raise UploadInputError(
                "FILE_TOO_LARGE",
                f"上传文件总大小超过限制（最大 {MAX_TOTAL_UPLOAD_SIZE // 1024 // 1024}MB）",
                status_code=413,
            )
    return meta_files


def validate_submission(*, text: str | None, files=None) -> list[UploadFileMeta]:
    meta_files = validate_files(files)
    if not (text or "").strip() and not meta_files:
        raise UploadInputError("INVALID_INPUT", "提交内容不能为空，必须提供纯文本或至少一张图片。")
    return meta_files


def compute_request_hash(
    *,
    text: str | None = "",
    url: str | None = "",
    season: str | None = "",
    content_type: str | None = "",
    target_intent: str,
    position_id: int | None = None,
    position_name: str = "",
    files=None,
    images=None,
) -> str:
    """服务端规范化输入 hash（含图片字节 hash、目标、岗位、招聘季）。"""

    image_hashes = [
        hashlib.sha256((image or {}).get("content_b64", "").encode("ascii")).hexdigest()
        for image in (images or [])
    ]
    material = {
        "text": (text or "").strip(),
        "url": (url or "").strip(),
        "season": (season or "").strip(),
        "content_type": (content_type or "").strip().lower(),
        "target_intent": target_intent,
        "position_id": position_id,
        "position_name": position_name,
        "files": [
            {
                "filename": meta.filename,
                "size": int(meta.size),
                "mime": meta.mime,
                "content_type": (meta.content_type or "").lower(),
            }
            for meta in (files or [])
        ],
        "image_hashes": image_hashes,
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_thread_id(import_id: str, attempt_no: int, job_id) -> str:
    """LangGraph thread_id：必须唯一标识一次执行，禁止秒级时间戳。

    同秒并发上传（AC-009）靠 ``(import_id, attempt_no, job_id)`` 区分状态。
    """

    return f"{import_id}:a{int(attempt_no)}:j{job_id}"


class UploadRestoreError(Exception):
    """恢复请求被拒绝；code 对应契约 §4.4 的错误分类。"""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def resolve_root_job(conn, job_id: int):
    """沿 ``parent_job_id`` 链解析根 job；链成环或断链时不猜。"""

    seen: set[int] = set()
    current = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if current is None:
        raise UploadRestoreError("NOT_FOUND", f"任务不存在: {job_id}")
    while current["parent_job_id"]:
        parent_id = int(current["parent_job_id"])
        if parent_id in seen:
            raise UploadRestoreError(
                "LEGACY_MAPPING_AMBIGUOUS", "任务血缘存在环，需人工确认"
            )
        seen.add(parent_id)
        parent = conn.execute("SELECT * FROM jobs WHERE id = ?", (parent_id,)).fetchone()
        if parent is None:
            break
        current = parent
    return current


def _resolve_root_import_id(conn, *, job_id=None, import_id=None) -> str:
    if import_id:
        return str(import_id)
    if job_id is None:
        raise ValueError("必须提供 import_id 或 job_id")

    root_job = resolve_root_job(conn, int(job_id))
    candidates = []
    for job in (root_job,):
        if job["root_import_id"]:
            candidates.append(job["root_import_id"])
    if not candidates:
        # 沿链向上找任何已打标的 import 归属（迁移后的旧 job 可能只在部分节点上）
        node = root_job
        while node and node["root_import_id"] is None and node["parent_job_id"]:
            node = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (node["parent_job_id"],)
            ).fetchone()
        if node and node["root_import_id"]:
            candidates.append(node["root_import_id"])
    if not candidates:
        raise UploadRestoreError(
            "LEGACY_MAPPING_AMBIGUOUS",
            "该历史任务没有可解析的业务根任务，需人工确认后恢复",
        )
    return str(candidates[0])


def _plan_work_after_restore(
    conn, *, root, attempt, actor_id: int
) -> dict:
    """恢复后的工作规划：为同 root 写可派发 job（R03）。

    - 同一 root 已有在途 job（pending/queued/running）→ 幂等复用，不重复建
      （DB 部分唯一索引 uq_jobs_v2_work_active 兜底）；
    - 否则创建首个未完成 work_key 的 ``submit_import`` job，绑定
      root + attempt + work_key，payload 从根任务快照复制（含原稿/图片）。
    - 同时确保凭据预检 job 存在（R01：配置修复后恢复需重新探测）。
    """

    import_id = root["id"]
    in_flight = conn.execute(
        "SELECT id, job_type FROM jobs WHERE root_import_id = ? "
        "AND upload_attempt_id IS ? "
        "AND status IN ('pending', 'queued', 'running') ORDER BY id LIMIT 1",
        (import_id, attempt["id"]),
    ).fetchone()
    if in_flight:
        return {
            "job_id": int(in_flight["id"]),
            "created": False,
            "work_key": "credential_preflight" if in_flight["job_type"] == "credential_preflight" else FIRST_WORK_KEY,
        }

    # R01：每个恢复批次重新检查所有处理所需 scope；业务 job 由预检事务
    # 在全部 scope 成功后创建。
    from app.services.credential_preflight import create_credential_preflight_job

    policy = _loads(root["policy_json"], {}) or {}
    contribution = conn.execute(
        "SELECT status FROM public_contribution_requests WHERE id = ?",
        (root["contribution_request_id"],),
    ).fetchone() if root["contribution_request_id"] else None
    preflight_scopes = set(initial_preflight_scopes(policy))
    if contribution and contribution["status"] in (
        "approved_for_processing",
        "queued",
        "processing",
        "partially_published",
        "failed",
    ):
        preflight_scopes.add(policy.get("post_approval_credential_scope") or "global")

    preflight_job_ids = []
    for preflight_scope in ("global", "user"):
        if preflight_scope not in preflight_scopes:
            continue
        preflight_job_ids.append(create_credential_preflight_job(
            conn,
            root_import_id=import_id,
            requester_id=int(root["requester_id"]),
            credential_scope=preflight_scope,
            user_id=int(root["requester_id"]) if preflight_scope == "user" else None,
            attempt_id=attempt["id"],
        ))

    # Re-plan all still-pending root-bound clustering after attempt rollover.
    # Old queued deliveries carry the previous attempt and are cancelled by
    # restore_upload before this function is called.
    from app.services.upload_queue import collect_pending_buckets, ensure_bucket_job

    for bucket in collect_pending_buckets(conn):
        if str(bucket["root_import_id"]) == str(import_id):
            ensure_bucket_job(conn, bucket=bucket, created_by=actor_id)
    return {
        "job_id": preflight_job_ids[0] if preflight_job_ids else None,
        "preflight_job_ids": preflight_job_ids,
        "created": True,
        "work_key": "credential_preflight",
    }


_JD_MARKERS = ("岗位", "职位要求", "任职资格", "工作职责", "职位描述", "岗位职责", "负责", "要求", "经验", "薪资", "福利")


def _guess_source_type(text: str, url: str = "") -> str:
    """auto 内容启发式识别（contracts §1.1 resolved_type）：JD 特征文本
    （岗位职责/任职要求/薪资福利等）判 jd，否则 interview。URL 含 jd/job
    等标记同样加权；无信号默认 interview（与旧行为一致）。"""

    blob = f"{text} {url}".lower()
    if any(marker in blob for marker in ("岗位职责", "职位要求", "任职资格", "工作职责", "职位描述")):
        return "jd"
    if any(m for m in ("岗位", "招聘", "职位", "jd", "job/") if m in blob) and any(
        m for m in ("要求", "职责", "经验", "薪资", "福利") if m in blob
    ):
        return "jd"
    return "interview"


def _loads(raw, default=None):
    import json as _json

    try:
        return _json.loads(raw or "null")
    except Exception:
        return default


def finalize_attempt_and_aggregate_root(
    conn,
    *,
    import_id: str,
    actor_id: int,
    error_code: str | None = None,
    error_message: str | None = None,
    interview_id: int | None = None,
    lease_generation: int | None = None,
) -> dict:
    """worker 结束一次尝试后：聚合阶段检查点 → 推进根状态/revision（R04）。

    ``aggregate_status`` 是纯函数，本函数是持久化入口；根任务不再停在
    最初的 queued，完成/失败/审核都由这里统一推进 revision。

    ``lease_generation`` 为 v2 强制项（F12）：根任务写入前校验 job 租约代次，
    旧 worker（已被人接管）的迟到写入被 ``JobFenceError`` 拒绝，业务表不留痕。
    """

    from app.services.upload_status import aggregate_status, allowed_actions

    root = conn.execute(
        "SELECT * FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    if root is None:
        raise ValueError(f"根任务不存在: {import_id}")

    # F12：v2 根聚合必须显式携带 job lease generation；缺失即编程错误
    if lease_generation is None:
        raise TypeError("v2 根状态聚合必须提供 lease_generation")

    from app.services.job_lifecycle import assert_job_generation_for_aggregation

    # 找出绑定本 root 的提交 job 并校验代次（旧 worker 迟到写入被拒）
    submit_job = conn.execute(
        "SELECT id, lease_generation, status FROM jobs "
        "WHERE root_import_id = ? AND job_type = 'submit_import' "
        "ORDER BY id DESC LIMIT 1",
        (import_id,),
    ).fetchone()
    if submit_job is not None:
        assert_job_generation_for_aggregation(
            conn, int(submit_job["id"]), int(lease_generation)
        )

    rows = conn.execute(
        "SELECT stage, unit_key, status, error_code FROM upload_stage_results "
        "WHERE import_id = ? ORDER BY id",
        (import_id,),
    ).fetchall()
    review_status = None
    if root["contribution_request_id"]:
        review_row = conn.execute(
            "SELECT status FROM public_contribution_requests WHERE id = ?",
            (root["contribution_request_id"],),
        ).fetchone()
        if review_row:
            review_status = review_row["status"]

    has_succeeded = any(r["status"] == "succeeded" for r in rows)
    work_items = []
    for r in rows:
        if r["status"] == "succeeded":
            work_items.append(
                {
                    "stage": r["stage"],
                    "status": "succeeded",
                    "has_result": True,
                    "unit_key": r["unit_key"],
                }
            )
        elif r["status"] == "failed":
            work_items.append(
                {
                    "stage": r["stage"],
                    "status": "failed",
                    "has_result": False,
                    "unit_key": r["unit_key"],
                }
            )
        elif r["status"] in ("pending", "running", "needs_action"):
            work_items.append(
                {
                    "stage": r["stage"],
                    "status": r["status"],
                    "has_result": False,
                    "unit_key": r["unit_key"],
                }
            )
        elif r["status"] == "skipped":
            work_items.append(
                {
                    "stage": r["stage"],
                    "status": "succeeded",
                    "has_result": True,
                    "unit_key": r["unit_key"],
                }
            )
    # 阶段检查点为空时，按根状态兜底（尚未写检查点的旧 worker 路径）
    if not work_items:
        if error_code:
            work_items.append({"stage": "extract", "status": "failed", "has_result": False})
        elif has_succeeded or interview_id is not None:
            work_items.append(
                {"stage": "persist", "status": "succeeded", "has_result": True}
            )
        else:
            work_items.append({"stage": "extract", "status": "queued", "has_result": False})

    aggregated = aggregate_status(
        work_items,
        review_status=review_status,
        warnings=[error_message] if error_message else None,
    )
    status = aggregated["status"]
    if status == "completed" and review_status in ("pending_review", "approved_for_processing"):
        status = "waiting_review" if review_status == "pending_review" else status

    # Keep a recovery attempt active while any stage (including per-question
    # answer jobs) is queued or running. A prior successful checkpoint alone
    # must not mark the attempt complete.
    attempt = conn.execute(
        "SELECT id FROM upload_attempts WHERE import_id = ? AND status = 'active' "
        "ORDER BY attempt_no DESC LIMIT 1",
        (import_id,),
    ).fetchone()
    if attempt is not None:
        if status in ("completed", "waiting_review"):
            conn.execute(
                "UPDATE upload_attempts SET status = 'completed', "
                "completed_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'active'",
                (attempt["id"],),
            )
        elif status in ("needs_action", "partial_failed", "failed"):
            conn.execute(
                "UPDATE upload_attempts SET status = 'failed', "
                "completed_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'active'",
                (attempt["id"],),
            )

    # 错误码：优先使用本次执行错误，其次阶段结果中的错误
    final_error_code = error_code or next(
        (r["error_code"] for r in rows if r["status"] == "failed" and r["error_code"]), None
    )
    new_revision = int(root["revision"]) + 1
    update_fields = ["status = ?", "revision = ?", "updated_at = CURRENT_TIMESTAMP"]
    params: list = [status, new_revision]
    if final_error_code:
        update_fields.append("error_code = ?")
        params.append(final_error_code)
        update_fields.append("error_message = ?")
        params.append(error_message or (final_error_code if final_error_code else ""))
    else:
        update_fields.append("error_code = NULL")
        update_fields.append("error_message = NULL")
    if interview_id is not None:
        update_fields.append("interview_id = ?")
        params.append(int(interview_id))
    if status in (
        "completed",
        "failed",
        "partial_failed",
        "waiting_review",
        "needs_action",
    ):
        update_fields.append("completed_at = CURRENT_TIMESTAMP")
    else:
        update_fields.append("completed_at = NULL")
    params.append(import_id)
    conn.execute(
        f"UPDATE upload_imports SET {', '.join(update_fields)} WHERE id = ?", params
    )

    policy = _loads(root["policy_json"] or "{}", {}) or {}
    action_scope = policy.get("credential_scope", "user")
    requester_role = conn.execute(
        "SELECT is_admin FROM users WHERE id = ?", (root["requester_id"],)
    ).fetchone()
    requester_is_admin = bool(requester_role and requester_role["is_admin"])
    if status == "needs_action" and conn.execute(
        "SELECT 1 FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight' "
        "ORDER BY id DESC LIMIT 1",
        (import_id,),
    ).fetchone():
        failed_preflight = conn.execute(
            "SELECT json_extract(p.payload, '$.credential_scope') AS scope "
            "FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
            "JOIN upload_stage_results s ON s.job_id = j.id "
            "AND s.stage = 'credential_preflight' "
            "WHERE j.root_import_id = ? AND j.job_type = 'credential_preflight' "
            "AND s.status = 'failed' ORDER BY j.id DESC LIMIT 1",
            (import_id,),
        ).fetchone()
        if failed_preflight and failed_preflight["scope"] in ("user", "global"):
            action_scope = failed_preflight["scope"]

    return {
        "import_id": import_id,
        "revision": new_revision,
        "status": status,
        "stage": aggregated["stage"],
        "counts": aggregated["counts"],
        "result_available": aggregated["result_available"],
        "review_status": review_status,
        "warnings": aggregated["warnings"],
        "error": (
            {"code": final_error_code, "message": error_message or final_error_code}
            if final_error_code
            else None
        ),
        "interview_id": interview_id if interview_id is not None else root["interview_id"],
        "allowed_actions": allowed_actions(
            status,
            error_code=final_error_code,
            has_result=aggregated["result_available"],
            credential_scope=action_scope,
            is_admin=requester_is_admin,
        ),
    }


def upload_action_credential_scope(conn, *, import_id: str, fallback: str = "user") -> str:
    """Resolve which credential owner must fix a root's current model error."""

    row = conn.execute(
        "SELECT json_extract(p.payload, '$.credential_scope') AS scope "
        "FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
            "JOIN upload_stage_results s ON s.job_id = j.id "
            "AND s.stage = 'credential_preflight' "
        "WHERE j.root_import_id = ? AND j.job_type = 'credential_preflight' "
        "AND s.status = 'failed' ORDER BY j.id DESC LIMIT 1",
        (import_id,),
    ).fetchone()
    if row and row["scope"] in ("user", "global"):
        return row["scope"]
    return fallback if fallback in ("user", "global") else "user"


def refresh_completed_upload_roots(conn, import_ids) -> list[dict]:
    """Refresh roots after asynchronous child work, without racing a live submit worker.

    The submit worker owns aggregation while its job is running. Once it has
    completed, queue workers may safely re-aggregate the same root using that
    submit job's fence generation. Roots without a completed submit job (legacy
    data or a still-running import) are left to their normal submit finalizer.
    """

    reports = []
    for import_id in sorted({str(item) for item in (import_ids or []) if item}):
        submit_job = conn.execute(
            "SELECT id, lease_generation FROM jobs WHERE root_import_id = ? "
            "AND job_type = 'submit_import' AND status = 'completed' "
            "ORDER BY id DESC LIMIT 1",
            (import_id,),
        ).fetchone()
        if submit_job is None:
            continue
        reports.append(
            finalize_attempt_and_aggregate_root(
                conn,
                import_id=import_id,
                actor_id=0,
                lease_generation=int(submit_job["lease_generation"]),
            )
        )
    return reports


def restore_upload(conn, *, actor_id: int, import_id: str | None = None, job_id=None) -> dict:
    """恢复同一业务任务：已有活跃批次直接返回，否则创建新批次。

    只重建未完成/失败/失效的工作；已成功阶段的检查点由 worker 复用。
    """

    root_import_id = _resolve_root_import_id(conn, job_id=job_id, import_id=import_id)
    root = conn.execute(
        "SELECT * FROM upload_imports WHERE id = ?", (root_import_id,)
    ).fetchone()
    if root is None:
        raise UploadRestoreError("NOT_FOUND", "任务不存在")
    if int(root["requester_id"]) != int(actor_id):
        # 不区分“不存在”与“无权”，避免泄露他人任务存在性
        raise UploadRestoreError("NOT_FOUND", "任务不存在")

    try:
        policy = json.loads(root["policy_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        policy = {}
    blocker = upload_execution_blocker(conn, root, policy)
    if blocker:
        raise UploadRestoreError(*blocker)

    # AC-026：恢复必须有仍在保留期内的输入快照；不能把清空后的 {} 复制进新 job。
    try:
        recovery_payload = json.loads(root["payload_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        recovery_payload = None
    expiry = root["payload_expires_at"]
    expired = bool(
        expiry
        and conn.execute(
            "SELECT datetime(?) <= datetime('now')", (expiry,)
        ).fetchone()[0]
    )
    if not isinstance(recovery_payload, dict) or not recovery_payload or expired:
        raise UploadRestoreError(
            "SOURCE_EXPIRED",
            "原稿恢复资料已过期或不可用；请重新提交原始材料",
        )

    # 已完成的根任务不需要恢复（R03：结果可打开，不重复执行）
    if root["status"] == "completed":
        return {
            "import_id": root_import_id,
            "attempt_id": None,
            "attempt_no": int(root["current_attempt_no"] or 0),
            "created_attempt": False,
            "status": root["status"],
            "status_url": f"/api/upload-imports/{root_import_id}",
        }

    # R01：预检被阻塞（needs_action）时，pending 的提取 job 不是真实工作——
    # 取消它（终态 failed），让恢复重新预检 + 重建提取 job（配置修复后同 root 继续）。
    if root["status"] == "needs_action":
        conn.execute(
            "UPDATE jobs SET status = 'failed', worker_id = NULL, locked_until = NULL, "
            "last_error = '凭据预检未通过，等待重新预检', "
            "completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
            "WHERE root_import_id = ? AND job_type = 'submit_import' "
            "AND status IN ('pending', 'queued', 'running')",
            (root_import_id,),
        )
        conn.execute(
            "UPDATE jobs SET status = 'cancelled', worker_id = NULL, locked_until = NULL, "
            "arq_job_id = NULL, last_error = '凭据预检阻塞，等待重新预检', "
            "completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
            "WHERE root_import_id = ? AND job_type = 'cluster_batch' "
            "AND status IN ('pending', 'queued')",
            (root_import_id,),
        )

    active = conn.execute(
        "SELECT * FROM upload_attempts WHERE import_id = ? AND status = 'active' "
        "ORDER BY attempt_no DESC LIMIT 1",
        (root_import_id,),
    ).fetchone()

    def _finalize_attempt(a):
        """关闭一个没有在途工作的 attempt（失败/耗尽 → failed）。"""

        conn.execute(
            "UPDATE upload_attempts SET status = 'failed', completed_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'active'",
            (a["id"],),
        )

    created_attempt = False
    if active is not None:
        in_flight = conn.execute(
            "SELECT id FROM jobs WHERE root_import_id = ? AND upload_attempt_id = ? "
            "AND status IN ('pending', 'queued', 'running') ORDER BY id LIMIT 1",
            (root_import_id, active["id"]),
        ).fetchone()
        if in_flight is not None:
            attempt = active
            created_attempt = False
        else:
            # 该 attempt 已无在途工作（全部终态失败/耗尽）：收尾后开新批次
            _finalize_attempt(active)
            try:
                attempt = create_attempt(conn, import_id=root_import_id, requested_by=actor_id)
                created_attempt = True
            except sqlite3.IntegrityError:
                # 并发恢复：另一方已建立 active attempt，读取它而不是新建
                attempt = conn.execute(
                    "SELECT * FROM upload_attempts WHERE import_id = ? AND status = 'active' "
                    "ORDER BY attempt_no DESC LIMIT 1",
                    (root_import_id,),
                ).fetchone()
                if attempt is None:
                    raise
                created_attempt = False
    else:
        try:
            attempt = create_attempt(conn, import_id=root_import_id, requested_by=actor_id)
            created_attempt = True
        except sqlite3.IntegrityError:
            # 并发恢复：另一方已建立 active attempt，读取它而不是新建
            attempt = conn.execute(
                "SELECT * FROM upload_attempts WHERE import_id = ? AND status = 'active' "
                "ORDER BY attempt_no DESC LIMIT 1",
                (root_import_id,),
            ).fetchone()
            if attempt is None:
                raise
            created_attempt = False

    conn.execute(
        "UPDATE upload_imports SET current_attempt_no = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (attempt["attempt_no"], root_import_id),
    )

    if created_attempt:
        conn.execute(
            "UPDATE jobs SET status = 'cancelled', worker_id = NULL, locked_until = NULL, "
            "arq_job_id = NULL, last_error = '恢复批次更换，重新规划聚类工作', "
            "completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
            "WHERE root_import_id = ? AND job_type = 'cluster_batch' "
            "AND upload_attempt_id IS NOT ? AND status IN ('pending', 'queued')",
            (root_import_id, attempt["id"]),
        )

    # R03：为本次恢复规划可执行工作（幂等：已有在途 job 就不重复建）
    planned = _plan_work_after_restore(
        conn, root=root, attempt=attempt, actor_id=actor_id
    )

    return {
        "import_id": root_import_id,
        "attempt_id": attempt["id"],
        "attempt_no": attempt["attempt_no"],
        "created_attempt": created_attempt,
        "planned_job_id": planned["job_id"],
        "planned_work_key": planned["work_key"],
        "status": root["status"],
        "status_url": f"/api/upload-imports/{root_import_id}",
    }


def accept_upload(
    conn,
    *,
    actor_id: int,
    actor_is_admin: bool,
    idempotency_key: str,
    target_intent: str,
    source_type: str = "interview",
    text: str | None = "",
    url: str | None = "",
    season: str | None = "",
    content_type: str | None = "",
    position_id: int | None = None,
    position_name: str = "",
    files=None,
    images=None,
    entry: str = "api",
    policy_overrides=None,
    job_position: str = "",
    credential_loaders=None,
) -> dict:
    """在调用方事务内接受一次上传；同幂等键同 hash 复用同一根任务。"""

    # 客户端策略字段一律拒绝，不信任请求体里的 is_admin/owner_id 等
    sanitize_client_policy_fields(policy_overrides)

    policy = resolve_upload_policy(
        actor_id=actor_id,
        actor_is_admin=bool(actor_is_admin),
        target_intent=target_intent,
        source_type=source_type,
        position_id=position_id,
        position_name=position_name,
        entry=entry,
    )
    policy_snapshot = policy.to_policy_json()
    if position_name:
        policy_snapshot["taxonomy_fingerprint"] = (
            _system_taxonomy_fingerprint(conn, position_name) or "missing"
        )

    meta_files = validate_submission(text=text, files=files)
    request_hash = compute_request_hash(
        text=text,
        url=url,
        season=season,
        content_type=content_type,
        target_intent=policy.target_intent,
        position_id=position_id,
        position_name=position_name,
        files=meta_files,
        images=images,
    )

    payload = {
        "raw_text": text or "",
        "image_data": list(images or []),
        "url": url or "",
        "season": season or "",
        "content_type_hint": (content_type or "").lower(),
        "target": policy.write_scope,
        "target_intent": policy.target_intent,
        "user_id": actor_id,
        "is_admin": bool(actor_is_admin),
        "job_position": job_position,
        "entry": entry,
    }

    # resolved_type：auto 时按内容启发式识别（contracts §1.1），
    # 明确 hint（jd/interview）直接采用；private 段落在远程调用前落库。
    content_hint = (content_type or "").strip().lower()
    if content_hint in ("jd", "interview"):
        resolved_type = content_hint
    elif content_hint in ("", "auto"):
        resolved_type = _guess_source_type(text or "", url or "")
    else:
        resolved_type = source_type or "interview"

    import_id, created = create_or_get_import(
        conn,
        requester_id=actor_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        target_intent=policy.target_intent,
        source_type=source_type,
        resolved_type=resolved_type,
        position_id=position_id,
        position_name=position_name,
        pipeline_version=UPLOAD_PIPELINE_VERSION_DEFAULT,
        policy_json=json.dumps(policy_snapshot, ensure_ascii=False),
        payload_json=json.dumps(payload, ensure_ascii=False),
    )

    # 在接受事务里校验 policy 要求的全部 scope。缺配置也要保留 attempt 与
    # durable preflight jobs；任何业务 job 都等真实 provider ping 全部成功后
    # 才由 create_initial_submit_job_if_ready 创建。
    credential_error = None
    required_scopes = initial_preflight_scopes(policy)
    if created:
        from app.services.upload_credentials import resolve_upload_credentials

        for scope in required_scopes:
            try:
                resolve_upload_credentials(
                    credential_scope=scope,
                    user_id=actor_id if scope == "user" else None,
                    stage="extract",
                    user_config_loader=(credential_loaders or {}).get("user"),
                    global_config_loader=(credential_loaders or {}).get("global"),
                )
            except UploadCredentialError as exc:
                credential_error = credential_error or exc

    preflight_job_ids = []
    if created:
        attempt = create_attempt(conn, import_id=import_id, requested_by=actor_id)
        attempt_no = int(attempt["attempt_no"])
        conn.execute(
            "UPDATE upload_imports SET current_attempt_no = ?, "
            "status = ?, revision = revision + 1, error_code = ?, error_message = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (
                attempt_no,
                "needs_action" if credential_error else "queued",
                credential_error.code if credential_error else None,
                str(credential_error)[:500] if credential_error else None,
                import_id,
            ),
        )
        from app.services.credential_preflight import create_credential_preflight_job

        for scope in required_scopes:
            preflight_job_ids.append(create_credential_preflight_job(
                conn,
                root_import_id=import_id,
                requester_id=actor_id,
                credential_scope=scope,
                user_id=actor_id if scope == "user" else None,
                attempt_id=attempt["id"],
            ))
    else:
        attempt_row = conn.execute(
            "SELECT id, attempt_no FROM upload_attempts WHERE import_id = ? "
            "ORDER BY attempt_no DESC LIMIT 1",
            (import_id,),
        ).fetchone()
        attempt_no = int(attempt_row["attempt_no"]) if attempt_row else 0
        if attempt_row:
            preflight_job_ids = [
                int(row["id"])
                for row in conn.execute(
                    "SELECT id FROM jobs WHERE root_import_id = ? AND upload_attempt_id = ? "
                    "AND job_type = 'credential_preflight' "
                    "AND status IN ('pending','queued','running') ORDER BY id",
                    (import_id, attempt_row["id"]),
                ).fetchall()
            ]

    root = conn.execute(
        "SELECT status, revision, error_code, error_message, policy_json "
        "FROM upload_imports WHERE id = ?",
        (import_id,),
    ).fetchone()
    job_row = conn.execute(
        "SELECT id, job_type FROM jobs WHERE root_import_id = ? "
        "AND upload_attempt_id IS (SELECT id FROM upload_attempts WHERE import_id = ? "
        "ORDER BY attempt_no DESC LIMIT 1) "
        "AND job_type IN ('credential_preflight','submit_import') "
        "AND status IN ('pending','queued','running') ORDER BY "
        "CASE job_type WHEN 'credential_preflight' THEN 0 ELSE 1 END, id LIMIT 1",
        (import_id, import_id),
    ).fetchone()
    job_id = int(job_row["id"]) if job_row else None
    dispatch_jobs = [
        {"job_id": int(row["id"]), "job_type": row["job_type"]}
        for row in conn.execute(
            "SELECT id, job_type FROM jobs WHERE root_import_id = ? "
            "AND upload_attempt_id IS (SELECT id FROM upload_attempts WHERE import_id = ? "
            "ORDER BY attempt_no DESC LIMIT 1) AND status = 'pending' "
            "AND job_type IN ('credential_preflight','submit_import') ORDER BY id",
            (import_id, import_id),
        ).fetchall()
    ]
    if credential_error is None and root["error_code"]:
        from app.services.upload_lifecycle import upload_action_credential_scope

        scope = upload_action_credential_scope(
            conn,
            import_id=import_id,
            fallback=policy.credential_scope,
        )
        credential_error = UploadCredentialError(
            root["error_code"],
            scope=scope,
            action="configure_system_model" if scope == "global" else "configure_user_model",
            message=root["error_message"] or root["error_code"],
        )

    return {
        "import_id": import_id,
        "created": created,
        "job_id": job_id,
        "job_type": job_row["job_type"] if job_row else None,
        "preflight_job_ids": preflight_job_ids,
        "dispatch_jobs": dispatch_jobs,
        "error": (
            {
                "code": credential_error.code,
                "message": str(credential_error),
                "retryable": credential_error.retryable,
                "action": credential_error.action,
                "scope": credential_error.scope,
            }
            if credential_error is not None
            else None
        ),
        "attempt_no": attempt_no,
        "status": root["status"],
        "revision": root["revision"],
        "status_url": f"/api/upload-imports/{import_id}",
        "policy": policy.to_policy_json(),
    }


def assert_upload_business_commit(conn, *, import_id, job_id, generation, input_version):
    """Fence actual business writes inside their SQLite transaction."""
    from app.services.job_lifecycle import JobFenceError, assert_job_fence

    if import_id and (job_id is None or generation is None or input_version is None):
        raise JobFenceError("上传业务提交缺少执行身份或输入版本", job_id=job_id, generation=generation)
    if job_id is not None:
        assert_job_fence(conn, job_id, generation)
    if not import_id:
        return
    job = conn.execute("SELECT root_import_id FROM jobs WHERE id=?", (job_id,)).fetchone()
    root = conn.execute("SELECT * FROM upload_imports WHERE id=?", (import_id,)).fetchone()
    if not root or not job or job["root_import_id"] != import_id:
        raise JobFenceError("任务与上传根不匹配", job_id=job_id, generation=generation)
    if int(root["input_version"]) != int(input_version):
        raise JobFenceError("上传输入版本已改变", job_id=job_id, generation=generation)
    blocker = upload_execution_blocker(conn, root, json.loads(root["policy_json"] or "{}"))
    if blocker or root["error_code"] in {"SOURCE_DELETED", "POSITION_RETIRED", "TAXONOMY_CHANGED"}:
        raise JobFenceError("上传来源或执行上下文已失效", job_id=job_id, generation=generation)
