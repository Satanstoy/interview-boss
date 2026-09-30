"""凭据预检 job 与真实 provider 探测（R01 / AC-004、AC-013）。

在 accept 的同一事务里为每个新 root 创建 ``credential_preflight`` job
（job_type 注册进 dispatcher）；worker 执行时按 policy scope 解析凭据并
做真实模型 ping：

- 成功 → ``upload_stage_results`` 的 ``preflight`` 阶段标记 succeeded，
  根任务保持可派发（queued）；
- 401 / 配置缺失 → ``MODEL_AUTH_INVALID`` / ``MODEL_CONFIG_MISSING``，根
  ``needs_action``，**不派发提取**（配置修复后走同 root 恢复）；
- provider 404 / 超时 → ``UPSTREAM_UNAVAILABLE``，阻塞但可确定性失败。

探测使用与提取完全相同的 scope 凭据（user 绝不借用 global），
``probe`` 可注入以便本地 stub 验证 401/404/超时。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("interview-boss")

PREFLIGHT_JOB_TYPE = "credential_preflight"
PREFLIGHT_STAGE = "preflight"
PREFLIGHT_PIPELINE_VERSION = "upload-pipeline-v1"


@dataclass(frozen=True)
class PreflightOutcome:
    """一次探测的判定结果（不包含任何 Key）。"""

    status: str  # ok | blocked
    error_code: str | None = None
    message: str = ""
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None


def create_credential_preflight_job(
    conn,
    *,
    root_import_id: str,
    requester_id: int,
    credential_scope: str,
    user_id: int | None,
    attempt_id: int | None,
) -> int:
    """在调用方事务内为 root 创建预检 job（幂等；同 root 只有一个在途）。"""

    existing = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND job_type = ? "
        "AND status IN ('pending', 'queued', 'running') ORDER BY id LIMIT 1",
        (root_import_id, PREFLIGHT_JOB_TYPE),
    ).fetchone()
    if existing:
        return int(existing["id"])

    payload = {
        "root_import_id": root_import_id,
        "requester_id": requester_id,
        "credential_scope": credential_scope,
        "user_id": user_id,
    }
    cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, progress_total, created_by, "
        "root_import_id, upload_attempt_id, work_key, idempotency_key) "
        "VALUES (?, 'pending', 1, ?, ?, ?, 'preflight:credential:v1', ?)",
        (
            PREFLIGHT_JOB_TYPE,
            requester_id,
            root_import_id,
            attempt_id,
            f"preflight:{root_import_id}:{credential_scope}:{attempt_id or 0}",
        ),
    )
    job_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (job_id, _json_dumps(payload)),
    )
    return job_id


def _json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def run_credential_preflight(
    conn,
    *,
    job_id: int,
    probe=None,
    user_config_loader=None,
    global_config_loader=None,
) -> PreflightOutcome:
    """执行一次预检：解析 scope 凭据 → 探测 → 落阶段结果（幂等）。

    ``probe(credential)`` 默认使用 ``app.services.upload_credentials`` 的
    真实探测客户端；测试注入 stub 验证 401/404/超时分支。
    """

    import json

    from app.services.upload_credentials import (
        UploadCredentialError,
        resolve_upload_credentials,
    )
    from app.services.upload_repository import save_stage_result

    job = conn.execute(
        "SELECT * FROM jobs WHERE id = ? AND job_type = ?",
        (job_id, PREFLIGHT_JOB_TYPE),
    ).fetchone()
    if job is None:
        raise ValueError(f"预检 job 不存在: {job_id}")
    payload_row = conn.execute(
        "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
    ).fetchone()
    payload = json.loads(payload_row["payload"]) if payload_row else {}
    root_import_id = payload.get("root_import_id")
    credential_scope = payload.get("credential_scope", "user")
    user_id = payload.get("user_id")

    # 解析凭据：与提取阶段同规则（绝不跨 scope 回退；scope 只来自服务端 policy）
    try:
        credential = resolve_upload_credentials(
            credential_scope=credential_scope,
            user_id=int(user_id) if user_id is not None and credential_scope == "user" else None,
            stage="preflight",
            user_config_loader=user_config_loader,
            global_config_loader=global_config_loader,
        )
    except UploadCredentialError as exc:
        error_code = exc.code
        _mark_blocked(conn, root_import_id, job_id, error_code, str(exc))
        return PreflightOutcome(status="blocked", error_code=error_code, message=str(exc))

    probe_fn = probe or _default_probe
    # AC-004：预检的物理调用独立记账（不存 Key/认证头，绑定指纹）；同一
    # root+stage 每次预检一个 call_key，配额由账本层原子预留。
    from app.services.upload_credentials import (
        CallLedgerConflict,
        complete_llm_call,
        reserve_llm_call,
    )
    from app.services.job_lifecycle import default_worker_id

    call_key = (
        f"preflight:{root_import_id or job_id}:{credential_scope}:"
        f"{int(_monotonic() * 1000)}"
    )
    payer_type = "user" if credential_scope == "user" else "system"
    try:
        reserve_llm_call(
            conn,
            root_import_id=root_import_id,
            stage=PREFLIGHT_STAGE,
            unit_key=f"initial:{credential_scope}",
            call_key=call_key,
            credential_scope=credential_scope,
            payer_type=payer_type,
            payer_user_id=int(user_id) if credential_scope == "user" else None,
            provider=credential.provider,
            model=credential.model,
            config_fingerprint=credential.config_fingerprint,
        )
    except CallLedgerConflict:
        # 同 call_key 已登记（幂等重跑），沿用既有行
        pass
    except Exception as exc:
        logger.warning("预检记账预留失败（不阻断探测，配额层兜底）: %s", exc)

    try:
        result = probe_fn(credential)
        if isinstance(result, dict) and result.get("status") == "ok":
            latency = int(result.get("latency_ms") or 0)
            save_stage_result(
                conn,
                import_id=root_import_id,
                stage=PREFLIGHT_STAGE,
                unit_key="credential:v1",
                input_version=1,
                pipeline_version=PREFLIGHT_PIPELINE_VERSION,
                status="succeeded",
                result_json=_json_dumps(
                    {
                        "provider": result.get("provider", credential.provider),
                        "model": credential.model,
                        "config_fingerprint": credential.config_fingerprint,
                        "latency_ms": latency,
                    }
                ),
                job_id=job_id,
            )
            try:
                complete_llm_call(
                    conn,
                    call_key=call_key,
                    status="succeeded",
                    input_tokens=0,
                    output_tokens=0,
                )
            except Exception as exc:
                logger.warning("预检记账完成失败（不阻断）: %s", exc)
            conn.execute(
                "UPDATE jobs SET status = 'completed', progress_current = 1, "
                "progress_total = 1, completed_at = CURRENT_TIMESTAMP, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (job_id,),
            )
            # 预检通过：清除 needs_action 阻塞，恢复提取派发（配置修复后同 root 继续）
            if root_import_id:
                conn.execute(
                    "UPDATE upload_imports SET status = 'queued', error_code = NULL, "
                    "error_message = NULL, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND status = 'needs_action'",
                    (root_import_id,),
                )
            return PreflightOutcome(
                status="ok",
                provider=credential.provider,
                model=credential.model,
                latency_ms=latency,
            )
        raise RuntimeError("探测未返回有效状态")
    except Exception as exc:
        text = str(exc).lower()
        if "401" in text or "invalid api key" in text or "unauthorized" in text:
            error_code = "MODEL_AUTH_INVALID"
        elif "404" in text or "not found" in text or "connection refused" in text:
            error_code = "UPSTREAM_UNAVAILABLE"
        elif "timeout" in text or "timed out" in text or "超时" in text:
            error_code = "UPSTREAM_TIMEOUT"
        else:
            error_code = "UPSTREAM_UNAVAILABLE"
        try:
            complete_llm_call(
                conn, call_key=call_key, status="failed", error_code=error_code
            )
        except Exception as ledger_exc:
            logger.warning("预检失败记账完成失败（不阻断）: %s", ledger_exc)
        _mark_blocked(conn, root_import_id, job_id, error_code, str(exc))
        return PreflightOutcome(status="blocked", error_code=error_code, message=str(exc))


def _mark_blocked(conn, root_import_id: str, job_id: int, error_code: str, message: str):
    """预检失败：记录 failed 阶段结果 + 根 needs_action + job 终态失败。"""

    from app.services.upload_repository import save_stage_result

    if root_import_id:
        save_stage_result(
            conn,
            import_id=root_import_id,
            stage=PREFLIGHT_STAGE,
            unit_key="credential:v1",
            input_version=1,
            pipeline_version=PREFLIGHT_PIPELINE_VERSION,
            status="failed",
            error_code=error_code,
            retryable=False,
            job_id=job_id,
        )
        conn.execute(
            "UPDATE upload_imports SET status = 'needs_action', error_code = ?, "
            "error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (error_code, message[:500], root_import_id),
        )
    conn.execute(
        "UPDATE jobs SET status = 'failed', last_error = ?, "
        "completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (message[:500], job_id),
    )


def _default_probe(credential):
    """真实 provider ping：用解析出的凭据做最小模型调用（可被测试 stub 替换）。"""

    from app.services.llm import build_bare_client

    client = build_bare_client(
        api_key=credential.api_key,
        base_url=credential.base_url,
        timeout=credential.timeout or 15,
    )
    started = _monotonic()
    try:
        # 最小探测：请求 models 列表（无需 token 消耗，仍能验证 401/404/连通）
        response = client.models.list()
        names = [getattr(m, "id", "") for m in getattr(response, "data", [])][:1]
        model = names[0] if names else credential.model
        return {
            "status": "ok",
            "latency_ms": int((_monotonic() - started) * 1000),
            "provider": credential.provider,
            "model": model,
            "fingerprint": credential.config_fingerprint,
        }
    except Exception as exc:
        raise RuntimeError(f"{exc}") from exc


def _monotonic():
    import time

    return time.monotonic()