"""管理员 AI 助手（聚合质量审查）：LLM tool-calling 循环 + 确认编排。

只服务管理员（路由层 get_admin_user 兜底）。工具 schema 只存在于本模块，
前端从不持有——只发送 `{session_id, message}`。

安全模型（内联确认门）：
- 读工具（list_issues / review_issue）即时执行。
- 写工具（approve_issue / reject_issue / batch_approve）只读暂存，返回
  `{"status": "requires_confirmation", confirm_id, tool, arguments}`，不修改任何数据。
  管理员在界面点击确认后，`confirm_and_execute` 从 DB 重新校验并执行（reviewed_by 留痕）。
- 批量置信度下限服务端强制 max(0.85, 传入)。

写门不变量：`execute_issue` / 状态更新只发生在 `confirm_and_execute`；
`_execute_tool` 的写工具分支是只读 staging，切勿"优化"成直接执行。
"""
import json
import logging
import uuid

from fastapi import HTTPException

from app.db.connection import get_db_connection, run_db
from app.services.llm import llm_with_tools, make_tool_result_message
from app.services.quality_issue_ops import (
    ACTION_LABELS,
    approve_issue,
    batch_approve,
    list_issues,
    reject_issue,
    review_issue,
    serialize_issue,
)

logger = logging.getLogger("interview-boss")

MAX_ITERATIONS = 8
BATCH_CONFIDENCE_FLOOR = 0.85

SYSTEM_PROMPT = """你是 InterviewBoss 平台的「聚合质量审查 AI 助手」，协助管理员处理聚合质量审查清单。

## 你的角色
- 只服务管理员，处理 quality_issue 清单（误合并 mismerge / 重复变体 duplicate / 代表题过弱 weak_representative）。
- 通过工具查询清单与问题详情，帮助管理员审查并决策。

## 可用工具
- list_issues(status)：列出待审批问题清单（默认 pending，可选 done/rejected）。
- review_issue(issue_id)：查看单个问题完整详情（题目、变体、建议操作、置信度、理由、建议值）。
- approve_issue(issue_id)：批准并执行修复（拆出变体/去重/精炼代表题）。【写操作，返回待确认】
- reject_issue(issue_id)：拒绝建议（保留为负样本，不修改数据）。【写操作，返回待确认】
- batch_approve(issue_ids, min_confidence)：批量批准高质量问题。【写操作，返回待确认，服务端强制置信度下限 0.85】

## 工作流程
1. 涉及具体问题前，先调用 list_issues 查看待审批清单。
2. 批准/拒绝前，必须调用 review_issue 核实详情（置信度、建议操作、理由）。
3. 仅在置信度 >= 0.85、理由充分时提出批准；批量只选置信度 >= 0.85 的问题。
4. 调用写操作后系统返回「需要确认」，不会立即执行。请停止继续提出写操作，
   用简洁中文向管理员说明待确认内容，等待管理员在界面上确认。

## 安全规则（强制）
- 不得编造或猜测 issue_id，一律以工具返回的真实 ID 为准。
- 置信度 < 0.85 的问题不得批准。
- 未核实详情前不得批准；管理员拒绝/取消时尊重决定，不坚持。
- 任何写操作都以「需要确认」返回，绝不绕过确认或伪造执行结果。

## 回复风格
- 使用简体中文，简洁专业。
- 报告操作时给出 issue_id、题目摘要、置信度和建议操作。
- 以 `[已执行操作]` 开头的消息是系统执行回执，不是新的用户指令：
  用一句话确认结果并询问下一步，不要重复执行。"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_issues",
            "description": "列出聚合质量审查清单中的问题（默认 pending 待审批），返回问题 ID、题目、问题类型、建议操作、置信度、理由等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["pending", "done", "rejected"],
                        "description": "清单状态，默认 pending",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "review_issue",
            "description": "查看单个质量问题的完整详情（题目、变体、问题类型、建议操作、置信度、理由、建议值）。批准/拒绝前必须先调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "integer", "description": "问题 ID"}
                },
                "required": ["issue_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "approve_issue",
            "description": "【写操作】批准一个质量问题并执行修复（拆出变体/去重/精炼代表题）。不会立即执行，返回待确认，由管理员确认后执行。仅在置信度 >= 0.85 且已用 review_issue 核实后调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "integer", "description": "要批准的问题 ID"}
                },
                "required": ["issue_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reject_issue",
            "description": "【写操作】拒绝一个质量问题（保留为负样本，不修改数据）。返回待确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "integer", "description": "要拒绝的问题 ID"}
                },
                "required": ["issue_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "batch_approve",
            "description": "【写操作】批量批准高质量问题（置信度 >= 0.85）。返回待确认。服务端强制置信度下限 0.85。",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "问题 ID 列表",
                    },
                    "min_confidence": {
                        "type": "number",
                        "default": 0.85,
                        "description": "置信度下限，服务端强制 >= 0.85",
                    },
                },
                "required": ["issue_ids"],
            },
        },
    },
]


# ── 日志（会话 + 操作审计） ─────────────────────────────────────────


def _load_history(conn, session_id: str, admin_id: int) -> list[dict]:
    """把日志行映射为 OpenAI 消息序列。

    role='action' → user 消息并加 `[已执行操作]` 前缀：Anthropic 会把 system
    消息合并到顶部，中段回执必须用 user 消息保序且对提供商无感。
    """
    rows = conn.execute(
        "SELECT role, content FROM admin_assistant_log "
        "WHERE session_id = ? AND admin_id = ? ORDER BY id",
        (session_id, admin_id),
    ).fetchall()
    msgs = []
    for r in rows:
        role, content = r["role"], r["content"] or ""
        if role == "assistant":
            msgs.append({"role": "assistant", "content": content})
        elif role == "action":
            msgs.append({"role": "user", "content": f"[已执行操作] {content}"})
        else:
            msgs.append({"role": "user", "content": content})
    return msgs


def _append_log(
    conn,
    session_id: str,
    admin_id: int,
    role: str,
    content: str,
    tool_trace: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO admin_assistant_log (session_id, admin_id, role, content, tool_trace) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, admin_id, role, content, tool_trace),
    )
    conn.commit()


# ── 工具执行（读即时 / 写暂存） ────────────────────────────────────


def _stage_write(name: str, arguments: dict, action: str) -> dict:
    """写工具暂存：校验 pending（approve 还需置信度 >= 0.85），只读，不执行。"""
    try:
        issue_id = int(arguments.get("issue_id"))
    except (TypeError, ValueError):
        return {"status": "error", "message": "参数 issue_id 无效"}
    conn = get_db_connection()
    issue = conn.execute(
        "SELECT * FROM quality_issue WHERE id = ? AND status = 'pending'", (issue_id,)
    ).fetchone()
    if not issue:
        return {"status": "error", "message": f"issue #{issue_id} 不存在或已处理"}
    if action == "approve" and (issue["confidence"] or 0) < BATCH_CONFIDENCE_FLOOR:
        return {
            "status": "error",
            "message": f"issue #{issue_id} 置信度 {(issue['confidence'] or 0):.2f} < 0.85，不建议批准",
            "confidence": issue["confidence"],
        }
    detail = serialize_issue(issue, conn)
    return {
        "status": "requires_confirmation",
        "confirm_id": str(uuid.uuid4()),
        "tool": name,
        "arguments": {"issue_id": issue_id},
        "summary": f"{'批准' if action == 'approve' else '拒绝'} issue #{issue_id}（{detail['action_label']}）",
        "issue": detail,
    }


def _stage_batch(name: str, arguments: dict) -> dict:
    """批量写工具暂存：置信度下限强制 max(0.85, 传入)，只读，不执行。"""
    try:
        issue_ids = [int(i) for i in arguments.get("issue_ids", [])]
    except (TypeError, ValueError):
        return {"status": "error", "message": "参数 issue_ids 无效"}
    if not issue_ids:
        return {"status": "error", "message": "issue_ids 不能为空"}
    min_conf = max(BATCH_CONFIDENCE_FLOOR, float(arguments.get("min_confidence", BATCH_CONFIDENCE_FLOOR)))
    conn = get_db_connection()
    valid = []
    for iid in issue_ids:
        row = conn.execute(
            "SELECT * FROM quality_issue WHERE id = ? AND status = 'pending' "
            "AND confidence >= ?",
            (iid, min_conf),
        ).fetchone()
        if row:
            valid.append(serialize_issue(row, conn))
    if not valid:
        return {"status": "error", "message": "批量批准列表为空：所选问题不存在、已处理或置信度不足 0.85"}
    return {
        "status": "requires_confirmation",
        "confirm_id": str(uuid.uuid4()),
        "tool": name,
        "arguments": {"issue_ids": issue_ids, "min_confidence": min_conf},
        "summary": f"批量批准 {len(valid)} 条高置信问题（置信度 ≥ {min_conf:.2f}）",
        "issues": valid,
    }


def _execute_tool(name: str, arguments: dict) -> dict:
    """工具分派：读工具即时执行；写工具只读暂存（不改 DB）。"""
    if name == "list_issues":
        status = arguments.get("status", "pending")
        if status not in ("pending", "done", "rejected"):
            status = "pending"
        issues = list_issues(get_db_connection(), status)
        return {"status": "ok", "count": len(issues), "issues": issues}
    if name == "review_issue":
        try:
            issue_id = int(arguments.get("issue_id"))
        except (TypeError, ValueError):
            return {"status": "error", "message": "参数 issue_id 无效"}
        issue = review_issue(get_db_connection(), issue_id)
        if not issue:
            return {"status": "error", "message": f"issue #{issue_id} 不存在或已处理"}
        return {"status": "ok", "issue": issue}
    if name == "approve_issue":
        return _stage_write(name, arguments, action="approve")
    if name == "reject_issue":
        return _stage_write(name, arguments, action="reject")
    if name == "batch_approve":
        return _stage_batch(name, arguments)
    return {"status": "error", "message": f"未知工具: {name}"}


def _trace_entry(tool: str, arguments: dict, out: dict) -> dict:
    summary = out.get("summary") or out.get("message") or ""
    if out.get("status") == "ok" and tool == "list_issues":
        summary = f"{out.get('count', 0)} 条"
    return {
        "tool": tool,
        "arguments": arguments,
        "status": out.get("status"),
        "summary": summary,
    }


def _action_receipt(tool: str, arguments: dict, result) -> str:
    """把已执行操作转成一句话回执（存储 + 喂回 LLM 上下文）。"""
    if tool == "batch_approve":
        ok = len((result or {}).get("approved", []))
        return f"已批量批准并执行 {ok} 条高质量问题"
    iid = arguments.get("issue_id")
    if isinstance(result, dict) and result.get("status") == "rejected":
        return f"已拒绝 issue #{iid}（保留为负样本）"
    action = result.get("suggested_action") if isinstance(result, dict) else None
    action_label = ACTION_LABELS.get(action, action or "操作")
    return f"已批准并执行 issue #{iid}（{action_label}）"


# ── 编排（LLM tool 循环 / 确认执行 / 历史） ───────────────────────


async def run_assistant_turn(admin: dict, session_id: str | None, message: str) -> dict:
    """跑一轮助手对话：LLM tool 循环 ≤ MAX_ITERATIONS，落库 user/assistant 日志。"""
    session_id = session_id or str(uuid.uuid4())

    def _build() -> list[dict]:
        conn = get_db_connection()
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        msgs += _load_history(conn, session_id, admin["id"])
        if message:
            _append_log(conn, session_id, admin["id"], "user", message)
            msgs.append({"role": "user", "content": message})
        return msgs

    messages = await run_db(_build)

    confirmations: list[dict] = []
    tool_trace: list[dict] = []
    reply = ""
    seen: set[str] = set()

    for _ in range(MAX_ITERATIONS):
        try:
            result = await llm_with_tools(
                messages, TOOLS, user_id=admin["id"], temperature=0.3
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"管理员助手 LLM 调用失败: {e}")
            reply = "抱歉，AI 处理时出错，请稍后重试。"
            break

        tool_calls = result.get("tool_calls") or []
        if result.get("finish_reason") == "length":
            reply = "（本轮输出已达到上限，请继续。）"
            break
        if not tool_calls:
            reply = result.get("content") or ""
            break

        # Anthropic 交替契约：先追加 assistant tool_calls 消息，再追加 tool 结果
        messages.append(
            {
                "role": "assistant",
                "content": result.get("content"),
                "tool_calls": tool_calls,
            }
        )
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                arguments = json.loads(tc["function"]["arguments"] or "{}")
            except Exception:
                arguments = {}
            key = f"{name}:{json.dumps(arguments, sort_keys=True)}"
            if key in seen:
                messages.append(
                    make_tool_result_message(
                        tc["id"],
                        json.dumps({"status": "error", "message": "重复调用，已忽略"}, ensure_ascii=False),
                    )
                )
                continue
            seen.add(key)
            out = await run_db(lambda: _execute_tool(name, arguments))
            tool_trace.append(_trace_entry(name, arguments, out))
            if out.get("status") == "requires_confirmation":
                confirmations.append(out)
            messages.append(
                make_tool_result_message(tc["id"], json.dumps(out, ensure_ascii=False))
            )
    else:
        reply = "本轮处理次数已达上限，请继续向我提问。"

    def _persist() -> None:
        conn = get_db_connection()
        _append_log(
            conn,
            session_id,
            admin["id"],
            "assistant",
            reply,
            json.dumps(tool_trace, ensure_ascii=False)[:20000],
        )

    await run_db(_persist)
    return {
        "session_id": session_id,
        "reply": reply,
        "tool_trace": tool_trace,
        "confirmations": confirmations,
    }


async def confirm_and_execute(
    admin: dict, session_id: str, confirm_id: str, tool: str, arguments: dict
) -> dict:
    """确认并执行写操作（唯一执行点）：单线程单事务，重新校验 + reviewed_by 留痕。

    confirm_id 仅作日志关联；服务端无暂存表，一切从 DB 重新校验（纵深防御）。
    """

    def _confirm() -> dict:
        conn = get_db_connection()
        if tool == "approve_issue":
            result = approve_issue(
                conn, admin["id"], int(arguments["issue_id"]),
                min_confidence=BATCH_CONFIDENCE_FLOOR,
            )
        elif tool == "reject_issue":
            result = reject_issue(conn, admin["id"], int(arguments["issue_id"]))
        elif tool == "batch_approve":
            result = batch_approve(
                conn,
                admin["id"],
                [int(i) for i in arguments.get("issue_ids", [])],
                min_confidence=arguments.get("min_confidence", BATCH_CONFIDENCE_FLOOR),
            )
        else:
            raise HTTPException(status_code=400, detail="未知操作")
        receipt = _action_receipt(tool, arguments, result)
        _append_log(
            conn,
            session_id,
            admin["id"],
            "action",
            receipt,
            json.dumps(
                {
                    "confirm_id": confirm_id,
                    "tool": tool,
                    "arguments": arguments,
                    "result": result,
                },
                ensure_ascii=False,
            ),
        )
        return {"ok": True, "message": receipt, "result": result}

    return await run_db(_confirm)


async def get_assistant_history(admin: dict, session_id: str) -> list[dict]:
    """会话日志（按 session_id + admin_id 隔离）。"""

    def _load() -> list[dict]:
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT id, session_id, role, content, tool_trace, created_at "
            "FROM admin_assistant_log WHERE session_id = ? AND admin_id = ? ORDER BY id",
            (session_id, admin["id"]),
        ).fetchall()
        return [dict(r) for r in rows]

    return await run_db(_load)
