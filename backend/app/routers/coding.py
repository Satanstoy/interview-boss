import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from app.core.auth import get_current_user
from app.core.prompts import CODING_REVIEW_PROMPT, CODING_HINT_PROMPT
from app.db.connection import get_db_connection, run_db
from app.models.schemas import CodingSubmitRequest
from app.services.llm import _extract_json, stream_llm_messages

logger = logging.getLogger("interview-boss")
router = APIRouter()

VALID_LANGUAGES = {"python", "c", "java"}
VALID_MODES = {"full_review", "hint"}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}


@router.get("/api/coding/problems")
async def get_coding_problems(
    difficulty: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """获取编程题目列表（支持难度/标签筛选、分页）"""
    def _query():
        with get_db_connection() as conn:
            conditions = ["is_active = 1"]
            params = []
            if difficulty and difficulty in VALID_DIFFICULTIES:
                conditions.append("difficulty = ?")
                params.append(difficulty)
            if tag:
                conditions.append("tags LIKE ?")
                params.append(f"%{tag}%")

            where = " AND ".join(conditions)
            offset = (page - 1) * page_size

            total = conn.execute(
                f"SELECT COUNT(*) FROM coding_problems WHERE {where}", params
            ).fetchone()[0]

            rows = conn.execute(
                f"SELECT id, title, difficulty, tags, expected_complexity, source FROM coding_problems WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
                params + [page_size, offset]
            ).fetchall()

            problems = []
            for r in rows:
                d = dict(r)
                try:
                    d['tags'] = json.loads(d['tags']) if d['tags'] else []
                except Exception:
                    d['tags'] = []
                problems.append(d)

            return {"total": total, "page": page, "page_size": page_size, "problems": problems}

    return await run_db(_query)


@router.get("/api/coding/problems/{problem_id}")
async def get_coding_problem(problem_id: int, user: dict = Depends(get_current_user)):
    """获取单道题目详情"""
    def _query():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, title, description, difficulty, tags, expected_complexity, source, supported_languages FROM coding_problems WHERE id = ? AND is_active = 1",
                (problem_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="题目不存在")
            d = dict(row)
            try:
                d['tags'] = json.loads(d['tags']) if d['tags'] else []
            except Exception:
                d['tags'] = []
            try:
                d['supported_languages'] = json.loads(d['supported_languages']) if d['supported_languages'] else ["python", "c", "java"]
            except Exception:
                d['supported_languages'] = ["python", "c", "java"]
            return d

    try:
        return await run_db(_query)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("获取题目详情失败")
        raise HTTPException(status_code=500, detail="获取题目失败")


@router.post("/api/coding/submit")
async def submit_coding_code(req: CodingSubmitRequest, user: dict = Depends(get_current_user)):
    """提交代码，触发 AI 评审（SSE 流式返回）"""
    # 校验
    if req.language not in VALID_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"不支持的语言: {req.language}，支持: {', '.join(VALID_LANGUAGES)}")
    if req.mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"无效模式: {req.mode}，支持: {', '.join(VALID_MODES)}")
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="代码不能为空")

    # 获取题目信息
    def _get_problem():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, title, description, expected_complexity FROM coding_problems WHERE id = ? AND is_active = 1",
                (req.problem_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="题目不存在")
            return dict(row)

    try:
        problem = await run_db(_get_problem)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("获取题目失败")
        raise HTTPException(status_code=500, detail="获取题目失败")

    # 获取 hint 历史（渐进提示模式）
    hint_round = 0
    hint_history_section = ""
    if req.mode == "hint" and req.parent_submission_id:
        def _get_hint_chain():
            with get_db_connection() as conn:
                parent = conn.execute(
                    "SELECT id, hint_round, ai_feedback, parent_submission_id FROM coding_submissions WHERE id = ? AND user_id = ?",
                    (req.parent_submission_id, user['id'])
                ).fetchone()
                if not parent:
                    return 0, ""
                chain = []
                current = dict(parent)
                while current:
                    chain.append(current)
                    if current['parent_submission_id']:
                        current = conn.execute(
                            "SELECT id, hint_round, ai_feedback, parent_submission_id FROM coding_submissions WHERE id = ? AND user_id = ?",
                            (current['parent_submission_id'], user['id'])
                        ).fetchone()
                        if current:
                            current = dict(current)
                        else:
                            break
                    else:
                        break
                chain.reverse()
                round_num = len(chain) + 1
                if not chain:
                    return round_num, ""
                history_lines = ["## 之前的提示历史"]
                for i, item in enumerate(chain, 1):
                    history_lines.append(f"\n### 第 {i} 次提示")
                    history_lines.append(item.get('ai_feedback', ''))
                return round_num, "\n".join(history_lines)

        hint_round, hint_history_section = await run_db(_get_hint_chain)

    # 构建 prompt
    if req.mode == "full_review":
        prompt = CODING_REVIEW_PROMPT.format(
            problem_title=problem['title'],
            expected_complexity=problem['expected_complexity'] or "未指定",
            problem_description=problem['description'],
            language=req.language,
            user_code=req.code[:10000],
        )
    else:
        prompt = CODING_HINT_PROMPT.format(
            hint_round=hint_round,
            problem_title=problem['title'],
            expected_complexity=problem['expected_complexity'] or "未指定",
            problem_description=problem['description'],
            language=req.language,
            user_code=req.code[:10000],
            hint_history_section=hint_history_section,
        )

    messages = [
        {"role": "system", "content": "你是一位资深的技术面试官，专注于算法和数据结构面试。"},
        {"role": "user", "content": prompt},
    ]

    # SSE 流式返回
    def _sse(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def event_stream():
        full_response = ""
        try:
            yield _sse({"type": "step", "message": "正在分析代码..."})

            async for chunk in stream_llm_messages(messages, user_id=user['id']):
                full_response += chunk
                yield _sse({"type": "chunk", "content": chunk})

            # 解析最终 JSON
            result = _extract_json(full_response)

            if req.mode == "full_review":
                feedback_text = result.get("feedback", "")
                scores = result.get("scores", {})
                reference_answer = result.get("reference_answer", "")
                error_categories = result.get("error_categories", [])
                complexity_analysis = result.get("complexity_analysis", "")
                if complexity_analysis:
                    feedback_text += f"\n\n**复杂度分析：** {complexity_analysis}"
            else:
                feedback_text = result.get("hint", "")
                scores = result.get("scores", {})
                reference_answer = ""
                error_categories = result.get("error_categories", [])

            # 校验
            valid_categories = {"syntax", "logic", "algorithm", "complexity", "style"}
            error_categories = [c for c in error_categories if c in valid_categories]
            valid_scores = {k: max(1, min(5, int(v))) for k, v in scores.items()
                           if k in {"syntax", "logic", "algorithm", "complexity", "style"}}
            total_score = sum(valid_scores.values()) * 4 if valid_scores else 0

            # 写入数据库
            def _save():
                with get_db_connection() as conn:
                    conn.execute(
                        """INSERT INTO coding_submissions
                           (user_id, problem_id, language, code, mode, hint_round,
                            parent_submission_id, ai_feedback, error_categories, is_passed,
                            scores, reference_answer, total_score)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            user['id'], req.problem_id, req.language, req.code,
                            req.mode, hint_round, req.parent_submission_id,
                            feedback_text, json.dumps(error_categories, ensure_ascii=False),
                            1 if total_score >= 60 else 0,
                            json.dumps(valid_scores, ensure_ascii=False),
                            reference_answer, total_score,
                        )
                    )
                    conn.commit()
                    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            submission_id = await run_db(_save)

            yield _sse({
                "type": "done",
                "submission_id": submission_id,
                "scores": valid_scores,
                "total_score": total_score,
                "reference_answer": reference_answer,
                "error_categories": error_categories,
                "mode": req.mode,
                "hint_round": hint_round,
            })

        except Exception as e:
            logger.exception("AI 评审失败")
            yield _sse({"type": "error", "message": "AI 评审服务异常，请稍后重试"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.get("/api/coding/submissions")
async def get_coding_submissions(
    problem_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """获取用户提交历史"""
    def _query():
        with get_db_connection() as conn:
            conditions = ["user_id = ?"]
            params = [user['id']]
            if problem_id:
                conditions.append("problem_id = ?")
                params.append(problem_id)

            where = " AND ".join(conditions)
            offset = (page - 1) * page_size

            total = conn.execute(
                f"SELECT COUNT(*) FROM coding_submissions WHERE {where}", params
            ).fetchone()[0]

            rows = conn.execute(
                f"""SELECT s.id, s.problem_id, s.language, s.mode, s.hint_round,
                           s.error_categories, s.is_passed, s.created_at,
                           p.title as problem_title, p.difficulty
                    FROM coding_submissions s
                    JOIN coding_problems p ON s.problem_id = p.id
                    WHERE {where}
                    ORDER BY s.created_at DESC
                    LIMIT ? OFFSET ?""",
                params + [page_size, offset]
            ).fetchall()

            submissions = []
            for r in rows:
                d = dict(r)
                try:
                    d['error_categories'] = json.loads(d['error_categories']) if d['error_categories'] else []
                except Exception:
                    d['error_categories'] = []
                submissions.append(d)

            return {"total": total, "page": page, "page_size": page_size, "submissions": submissions}

    return await run_db(_query)


@router.get("/api/coding/submissions/{submission_id}")
async def get_coding_submission(submission_id: int, user: dict = Depends(get_current_user)):
    """获取单条提交详情"""
    def _query():
        with get_db_connection() as conn:
            row = conn.execute(
                """SELECT s.*, p.title as problem_title, p.difficulty, p.expected_complexity
                   FROM coding_submissions s
                   JOIN coding_problems p ON s.problem_id = p.id
                   WHERE s.id = ? AND s.user_id = ?""",
                (submission_id, user['id'])
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="提交记录不存在")
            d = dict(row)
            try:
                d['error_categories'] = json.loads(d['error_categories']) if d['error_categories'] else []
            except Exception:
                d['error_categories'] = []
            return d

    try:
        return await run_db(_query)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("获取提交详情失败")
        raise HTTPException(status_code=500, detail="获取提交详情失败")


@router.get("/api/coding/error-stats")
async def get_coding_error_stats(user: dict = Depends(get_current_user)):
    """获取用户错误统计（按 category 聚合）"""
    def _query():
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT error_categories FROM coding_submissions WHERE user_id = ? AND is_passed = 0 AND error_categories != '[]'",
                (user['id'],)
            ).fetchall()

            stats = {}
            for r in rows:
                try:
                    categories = json.loads(r['error_categories'])
                    for cat in categories:
                        stats[cat] = stats.get(cat, 0) + 1
                except Exception:
                    continue

            # 总提交数和通过数
            total = conn.execute(
                "SELECT COUNT(*) FROM coding_submissions WHERE user_id = ?", (user['id'],)
            ).fetchone()[0]
            passed = conn.execute(
                "SELECT COUNT(*) FROM coding_submissions WHERE user_id = ? AND is_passed = 1", (user['id'],)
            ).fetchone()[0]

            return {
                "error_stats": stats,
                "total_submissions": total,
                "passed_submissions": passed,
            }

    return await run_db(_query)
