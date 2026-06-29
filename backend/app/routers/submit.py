import asyncio
import json
import logging
import os
import re
import openai
import magic as _magic
import base64

from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from app.core.config import MAX_FILE_SIZE, MAX_TOTAL_UPLOAD_SIZE

ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp'}
from app.core.prompts import SYSTEM_PROMPT, JD_PROMPT, INTERVIEW_PROMPT
from app.core.auth import get_current_user
from app.db.connection import get_db_connection, run_db, get_current_job_position, get_taxonomy_for_position
from app.db.operations import (
    _check_duplicate_url_sync, _insert_jd, _insert_interview,
    submit_interview_txn,
)
from app.services.llm import _should_use_response_format, _extract_json, _call_llm_with_retry_messages, get_llm_client_for_user, raw_llm_call
from app.services.utils import encode_image

from app.agents.submit.graph import stream_submit_graph

logger = logging.getLogger("interview-boss")

router = APIRouter()


# Backward-compatible re-exports — business logic moved to app.services.submit_service
from app.services.submit_service import (
    tag_questions_batch,
    incremental_update_master_bank,
    background_generate_answer,
    _get_current_position_for_user,
)


@router.post("/api/submit")
async def submit_data(
    bg_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    url: Optional[str] = Form(""),
    text: Optional[str] = Form(""),
    season: Optional[str] = Form(""),
    content_type: Optional[str] = Form(""),
    target: Optional[str] = Form(""),
    files: List[UploadFile] = File(default=[])
):
    # 输入长度限制
    if text and len(text) > 50000:
        raise HTTPException(status_code=400, detail="文本内容过长，请限制在 50000 字符以内")
    url = url.strip() if url else ""
    submit_target = (target or "personal").lower()
    if submit_target not in ("personal", "public"):
        submit_target = "personal"
    if url:
        check_owner = user['id'] if submit_target == 'personal' else None
        if await run_db(lambda: _check_duplicate_url_sync(url, owner_id=check_owner)):
            raise HTTPException(status_code=409, detail="该链接的内容已存在于数据库中，请勿重复上传！")
    if not text.strip() and (not files or len(files) == 0 or not files[0].filename):
        raise HTTPException(status_code=400, detail="提交内容不能为空，必须提供纯文本或至少一张图片。")

    try:
        # 确定内容类型和目标
        doc_type = content_type.lower() if content_type else ""
        submit_target = target.lower() if target else "personal"
        if doc_type not in ("jd", "interview"):
            doc_type = ""  # 后续由 LLM 判断
        if submit_target not in ("personal", "public"):
            submit_target = "personal"

        is_admin = user.get('is_admin', 0)

        # 根据类型选择 prompt
        if doc_type == "jd":
            system_prompt = JD_PROMPT
        elif doc_type == "interview":
            system_prompt = INTERVIEW_PROMPT
        else:
            system_prompt = SYSTEM_PROMPT  # fallback：LLM 自行判断类型

        user_content = [{"type": "text", "text": "请分析以下联合内容，保持信息连贯性，并综合整理后严格按照 JSON Schema 返回："}]
        if text.strip():
            user_content.append({"type": "text", "text": f"\n【文本内容】:\n{text}\n"})
        if files and files[0].filename:
            MAX_FILE_COUNT = 20
            if len(files) > MAX_FILE_COUNT:
                raise HTTPException(status_code=400, detail=f"最多上传 {MAX_FILE_COUNT} 个文件")
            total_size = 0
            for file in files:
                if file.content_type.startswith("image/"):
                    content = await file.read()
                    total_size += len(content)
                    # 总上传大小限制
                    if total_size > MAX_TOTAL_UPLOAD_SIZE:
                        raise HTTPException(status_code=413, detail=f"上传文件总大小超过限制（最大 {MAX_TOTAL_UPLOAD_SIZE // 1024 // 1024}MB）")
                    # 单文件大小限制
                    if len(content) > MAX_FILE_SIZE:
                        raise HTTPException(status_code=413, detail=f"图片 {file.filename} 超过大小限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）")
                    # 校验真实 MIME 类型（基于文件魔数）
                    real_mime = _magic.from_buffer(content[:2048], mime=True)
                    if real_mime not in ALLOWED_MIME_TYPES:
                        raise HTTPException(status_code=400, detail=f"文件 {file.filename} 不是有效的图片文件（检测到: {real_mime}）")
                    base64_img = encode_image(content)
                    user_content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{real_mime};base64,{base64_img}"}
                    })

        _c, _m, _t, _bu, _provider = get_llm_client_for_user(user['id'])
        llm_kwargs = dict(
            model=_m,
            temperature=0.1,
        )
        if _should_use_response_format(_bu):
            llm_kwargs["response_format"] = {"type": "json_object"}
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]
        response_text = await _call_llm_with_retry_messages(messages, user_id=user['id'], **llm_kwargs)
        parsed_data = _extract_json(response_text)

        # 兼容两种返回格式：{type, data} 或 {data}
        if not doc_type:
            doc_type = (parsed_data.get("type") or "").lower()
        data = parsed_data.get("data", {})
        saved_url = url if url else f"internal://{__import__('secrets').token_urlsafe(16)}"

        # 校验 LLM 返回的数据是否有效
        if not doc_type or not data:
            raise HTTPException(status_code=422, detail="大模型未能从内容中提取有效信息，请检查提交的内容是否包含足够的文本或图片。")

        if doc_type == "interview":
            q_list = data.get("具体题目清单", [])
            if not q_list or all(not q.strip() for q in q_list):
                raise HTTPException(status_code=422, detail="大模型未能从内容中提取到面试题目，请确认提交的是面经内容而非其他类型。")

        # 获取用户当前岗位（用于 JD/面经/题目隔离）
        current_pos = _get_current_position_for_user(user['id'])

        # 计算 owner_id 和 status
        if submit_target == 'personal':
            record_owner_id = user['id']
            record_status = 'approved'
        else:
            record_owner_id = None
            record_status = 'approved' if is_admin else 'pending'

        if doc_type == "jd":
            _ts = data.get("核心技术要求", [])
            tech_stack = "\n".join(f"{i+1}. {item}" for i, item in enumerate(_ts)) if _ts else "未提供"
            await run_db(lambda: _insert_jd(saved_url, data, tech_stack, season.strip(), owner_id=record_owner_id, status=record_status, job_position=current_pos))
            return {"status": "success", "type": "JD", "target": submit_target, "saved_data": data}

        elif doc_type == "interview":
            _ql = data.get("具体题目清单", [])
            questions = "\n".join(f"{i+1}. {item}" for i, item in enumerate(_ql)) if _ql else "未提供"

            q_list = data.get("具体题目清单", [])
            if q_list:
                try:
                    # ── 阶段 1：字段补全（LLM，事务外） ──
                    missing_fields = []
                    if data.get("公司") == "未提供":
                        missing_fields.append("公司")
                    if data.get("面试轮次") == "未提供":
                        missing_fields.append("面试轮次")
                    if data.get("难易程度") == "未提供":
                        missing_fields.append("难易程度")

                    async def retry_fill_fields():
                        if not missing_fields or len(missing_fields) > 2:
                            return
                        retry_prompt = f"""以下是从一份面经中提取的信息，但有几个字段缺失（返回了"未提供"）。
请根据已有内容推断这些缺失字段的值。

已提取的信息：
- 公司：{data.get('公司', '未提供')}
- 面试轮次：{data.get('面试轮次', '未提供')}
- 考察重点：{data.get('考察重点', '未提供')}
- 题目清单：{json.dumps(data.get('具体题目清单', []), ensure_ascii=False)}
- 难易程度：{data.get('难易程度', '未提供')}

需要补全的字段：{', '.join(missing_fields)}

请返回一个JSON对象，只包含需要补全的字段。对于难易程度，请根据题目难度判断为"简单"、"中等"或"困难"。
对于公司，请从内容中推断（如题目中提到的公司名、岗位信息等）。
对于面试轮次，请从内容中推断（如一面、二面、HR面等）。"""
                        try:
                            _rc, _rm, _rt, _rbu, _rprovider = get_llm_client_for_user(user['id'])
                            retry_kwargs = dict(
                                model=_rm,
                                messages=[
                                    {"role": "system", "content": "你是一个信息补全助手。根据已有信息推断缺失字段，返回JSON。"},
                                    {"role": "user", "content": retry_prompt}
                                ],
                                temperature=0.2,
                            )
                            if _should_use_response_format(_rbu):
                                retry_kwargs["response_format"] = {"type": "json_object"}
                            retry_text = await raw_llm_call(user['id'], **retry_kwargs)
                            retry_data = _extract_json(retry_text)
                            for field in missing_fields:
                                val = retry_data.get(field, "未提供")
                                if val and val != "未提供":
                                    data[field] = val
                                    logger.info(f"字段补全成功: {field} = {val}")
                        except Exception as e:
                            logger.warning(f"字段补全重试失败: {e}")

                    # 读取当前岗位的分类体系
                    taxonomy_config = await run_db(get_taxonomy_for_position)

                    # 字段补全先执行（可能更新公司/轮次）
                    if missing_fields:
                        await retry_fill_fields()

                    # ── 阶段 2：题目标签化（LLM，事务外） ──
                    tagged_rows = await tag_questions_batch(
                        saved_url, data.get("公司", "未提供"), data.get("面试轮次", "未提供"),
                        q_list, taxonomy_config, user_id=user['id']
                    )

                    # ── 阶段 3：单事务写入 ──
                    if submit_target == 'personal':
                        # 个人题库：走原有的匹配流程
                        from app.services.clustering import match_new_questions

                        def _load_existing_bank():
                            with get_db_connection() as conn:
                                rows = conn.execute(
                                    "SELECT id, question, cat2, sources, original_questions, original_question_sources FROM question_bank WHERE owner_id = ? AND job_position = ?",
                                    (user['id'], current_pos)
                                ).fetchall()
                                return [dict(r) for r in rows]

                        existing_bank = await run_db(_load_existing_bank)
                        existing_by_cat2 = {}
                        for r in existing_bank:
                            cat2 = r.get('cat2') or ''
                            if cat2 not in existing_by_cat2:
                                existing_by_cat2[cat2] = []
                            all_qs = [r['question']]
                            try:
                                orig = json.loads(r.get('original_questions') or '[]')
                                all_qs.extend([q for q in orig if q and q != r['question']])
                            except Exception:
                                pass
                            existing_by_cat2[cat2].append({
                                "question_bank_id": r['id'], "question": r['question'],
                                "all_questions": all_qs,
                            })
                        valid_rows = [r for r in tagged_rows if r[3].strip()]
                        new_rows_for_match = [{"id": idx, "question": r[3], "cat2": r[5] if len(r) > 5 else '', "_orig_row": r} for idx, r in enumerate(valid_rows)]
                        match_result = await match_new_questions(new_rows_for_match, existing_by_cat2)
                        idx_to_row = {idx: r for idx, r in enumerate(valid_rows)}

                        answer_tasks, _ = await run_db(lambda: submit_interview_txn(
                            saved_url, data, questions, season.strip(),
                            record_owner_id, record_status, current_pos,
                            tagged_rows, match_result["matched"], match_result["unmatched"],
                            idx_to_row, bool(is_admin), user['id'],
                            qb_owner_id=user['id']
                        ))
                        for qid, qtext in answer_tasks:
                            bg_tasks.add_task(background_generate_answer, qid, qtext, user['id'])
                    else:
                        # 公共题库：只写 interview + questions_detail，入队等待聚类
                        from app.db.operations import submit_interview_txn_tag_only
                        from app.services.pipeline import enqueue_questions, should_trigger_clustering, dequeue_batch, cluster_batch, mark_batch_done, mark_batch_failed

                        interview_id = await run_db(lambda: submit_interview_txn_tag_only(
                            saved_url, data, questions, season.strip(),
                            record_owner_id, record_status, current_pos,
                            tagged_rows
                        ))
                        enqueue_questions(interview_id)

                        # 检查是否触发聚类
                        if should_trigger_clustering():
                            batch = dequeue_batch()
                            if batch:
                                try:
                                    new_count = await cluster_batch(batch, user_id=user['id'])
                                    queue_ids = [item['queue_id'] for item in batch]
                                    mark_batch_done(queue_ids)
                                    logger.info(f"提交触发聚类完成，新增 {new_count} 个聚类")
                                except Exception as e:
                                    logger.error(f"聚类失败，回退队列状态: {e}")
                                    queue_ids = [item['queue_id'] for item in batch]
                                    mark_batch_failed(queue_ids)

                except Exception as e:
                    logger.error(f"题目标签化及更新题库失败: {e}")
                    raise HTTPException(status_code=500, detail=f"题库更新失败: {str(e)[:200]}，面经已保存但题目未入库，请使用重新分析功能")

            return {"status": "success", "type": "Interview", "target": submit_target, "saved_data": data}
        else:
            raise HTTPException(status_code=500, detail="模型返回了未知的分类类型: " + str(doc_type))
    except HTTPException:
        raise
    except openai.AuthenticationError:
        logger.error("LLM API Key 无效")
        raise HTTPException(status_code=500, detail="API Key 无效或已过期，请在系统配置中检查并更新 API Key。")
    except openai.NotFoundError as e:
        logger.error(f"LLM API 错误: {e}")
        msg = str(e)
        if 'image' in msg.lower():
            raise HTTPException(status_code=500, detail="当前模型不支持图片输入，请在系统配置中切换支持视觉的模型，或仅提交文本内容")
        raise HTTPException(status_code=500, detail="LLM 接口返回错误，请检查模型配置是否正确")
    except openai.APIConnectionError:
        logger.error("LLM 连接失败")
        raise HTTPException(status_code=500, detail="无法连接 LLM 服务，请检查 Base URL 是否正确以及网络是否可达。")
    except openai.APITimeoutError:
        logger.error("LLM 调用超时")
        raise HTTPException(status_code=500, detail="LLM 服务响应超时，请在系统配置中增大超时时间或稍后重试。")
    except openai.APIStatusError as e:
        logger.error(f"LLM API 错误: {e}")
        raise HTTPException(status_code=500, detail="LLM 接口返回错误，请查看服务端日志")
    except Exception as e:
        logger.exception("提交处理失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.post("/api/submit-stream")
async def submit_data_stream(
    bg_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    url: Optional[str] = Form(""),
    text: Optional[str] = Form(""),
    season: Optional[str] = Form(""),
    content_type: Optional[str] = Form(""),
    target: Optional[str] = Form(""),
    files: List[UploadFile] = File(default=[])
):
    """SSE 版提交端点，流式推送处理进度。"""

    # ── 输入校验 ──
    if text and len(text) > 50000:
        raise HTTPException(status_code=400, detail="文本内容过长，请限制在 50000 字符以内")
    url = (url or "").strip()
    submit_target = (target or "personal").lower()
    if submit_target not in ("personal", "public"):
        submit_target = "personal"
    if url:
        check_owner = user['id'] if submit_target == 'personal' else None
        if await run_db(lambda: _check_duplicate_url_sync(url, owner_id=check_owner)):
            raise HTTPException(status_code=409, detail="该链接的内容已存在于数据库中，请勿重复上传！")
    if not (text or "").strip() and (not files or len(files) == 0 or not files[0].filename):
        raise HTTPException(status_code=400, detail="提交内容不能为空，必须提供纯文本或至少一张图片。")

    # ── 读取文件到内存（必须在 StreamingResponse 之前完成） ──
    file_data = []
    if files and files[0].filename:
        if len(files) > 20:
            raise HTTPException(status_code=400, detail="最多上传 20 个文件")
        total_size = 0
        for file in files:
            if file.content_type.startswith("image/"):
                content = await file.read()
                total_size += len(content)
                if total_size > MAX_TOTAL_UPLOAD_SIZE:
                    raise HTTPException(status_code=413, detail=f"上传文件总大小超过限制（最大 {MAX_TOTAL_UPLOAD_SIZE // 1024 // 1024}MB）")
                if len(content) > MAX_FILE_SIZE:
                    raise HTTPException(status_code=413, detail=f"图片 {file.filename} 超过大小限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）")
                real_mime = _magic.from_buffer(content[:2048], mime=True)
                if real_mime not in ALLOWED_MIME_TYPES:
                    raise HTTPException(status_code=400, detail=f"文件 {file.filename} 不是有效的图片文件（检测到: {real_mime}）")
                file_data.append((content, real_mime))

    _user = dict(user)
    _text = text or ""
    _url = url
    _season = season or ""
    _content_type = content_type or ""
    _target = target or ""

    async def event_stream():
        try:
            doc_type = _content_type.lower() if _content_type else ""
            submit_target = _target.lower() if _target else "personal"
            if doc_type not in ("jd", "interview"):
                doc_type = ""
            if submit_target not in ("personal", "public"):
                submit_target = "personal"

            is_admin = _user.get('is_admin', 0)

            if doc_type == "jd":
                system_prompt = JD_PROMPT
            elif doc_type == "interview":
                system_prompt = INTERVIEW_PROMPT
            else:
                system_prompt = SYSTEM_PROMPT

            user_content = [{"type": "text", "text": "请分析以下联合内容，保持信息连贯性，并综合整理后严格按照 JSON Schema 返回："}]
            if _text.strip():
                user_content.append({"type": "text", "text": f"\n【文本内容】:\n{_text}\n"})
            for content, real_mime in file_data:
                base64_img = encode_image(content)
                user_content.append({"type": "image_url", "image_url": {"url": f"data:{real_mime};base64,{base64_img}"}})

            yield f"data: {json.dumps({'step': 'extract', 'message': '正在提取内容...', 'type': 'progress'})}\n\n"
            _c, _m, _t, _bu, _provider = get_llm_client_for_user(_user['id'])
            llm_kwargs = dict(model=_m, temperature=0.1)
            if _should_use_response_format(_bu):
                llm_kwargs["response_format"] = {"type": "json_object"}
            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]
            response_text = await _call_llm_with_retry_messages(messages, user_id=_user['id'], **llm_kwargs)
            parsed_data = _extract_json(response_text)

            if not doc_type:
                doc_type = (parsed_data.get("type") or "").lower()
            data = parsed_data.get("data", {})
            saved_url = _url if _url else f"internal://{__import__('secrets').token_urlsafe(16)}"

            if not doc_type or not data:
                yield f"data: {json.dumps({'type': 'error', 'message': '大模型未能从内容中提取有效信息'})}\n\n"
                return

            if doc_type == "interview":
                q_list = data.get("具体题目清单", [])
                # 过滤 LLM 误提取的非面试题目（自我介绍、反问等）
                _EXTRACT_BLACKLIST = ["自我介绍", "反问", "想问我", "职业规划", "加班", "薪资", "为什么离职", "优缺点"]
                q_list = [q for q in q_list if q.strip() and not any(b in q for b in _EXTRACT_BLACKLIST)]
                if not q_list or all(not q.strip() for q in q_list):
                    yield f"data: {json.dumps({'type': 'error', 'message': '大模型未能从内容中提取到面试题目'})}\n\n"
                    return

            current_pos = _get_current_position_for_user(_user['id'])

            if submit_target == 'personal':
                record_owner_id = _user['id']
                record_status = 'approved'
            else:
                record_owner_id = None
                record_status = 'approved' if is_admin else 'pending'

            # ── JD 路径 ──
            if doc_type == "jd":
                yield f"data: {json.dumps({'step': 'save', 'message': '正在保存 JD...', 'type': 'progress'})}\n\n"
                _ts = data.get("核心技术要求", [])
                tech_stack = "\n".join(f"{i+1}. {item}" for i, item in enumerate(_ts)) if _ts else "未提供"
                await run_db(lambda: _insert_jd(saved_url, data, tech_stack, _season.strip(), owner_id=record_owner_id, status=record_status, job_position=current_pos))
                yield f"data: {json.dumps({'type': 'done', 'doc_type': 'JD', 'target': submit_target, 'saved_data': data})}\n\n"
                return

            # ── 面经路径 ──
            if doc_type != "interview":
                yield f"data: {json.dumps({'type': 'error', 'message': '模型返回了未知的分类类型: ' + str(doc_type)})}\n\n"
                return

            _ql = data.get("具体题目清单", [])
            questions = "\n".join(f"{i+1}. {item}" for i, item in enumerate(_ql)) if _ql else "未提供"
            q_list = data.get("具体题目清单", [])
            if not q_list:
                yield f"data: {json.dumps({'type': 'done', 'doc_type': 'Interview', 'target': submit_target, 'saved_data': data})}\n\n"
                return

            try:
                # ── 阶段 2：字段补全 ──
                missing_fields = []
                if data.get("公司") == "未提供": missing_fields.append("公司")
                if data.get("面试轮次") == "未提供": missing_fields.append("面试轮次")
                if data.get("难易程度") == "未提供": missing_fields.append("难易程度")

                if missing_fields and len(missing_fields) <= 2:
                    missing_label = "、".join(missing_fields)
                    retry_prompt = f"""以下是从一份面经中提取的信息，但有几个字段缺失（返回了"未提供"）。
请根据已有内容推断这些缺失字段的值。

已提取的信息：
- 公司：{data.get('公司', '未提供')}
- 面试轮次：{data.get('面试轮次', '未提供')}
- 考察重点：{data.get('考察重点', '未提供')}
- 题目清单：{json.dumps(data.get('具体题目清单', []), ensure_ascii=False)}
- 难易程度：{data.get('难易程度', '未提供')}

需要补全的字段：{', '.join(missing_fields)}

请返回一个JSON对象，只包含需要补全的字段。对于难易程度，请根据题目难度判断为"简单"、"中等"或"困难"。
对于公司，请从内容中推断（如题目中提到的公司名、岗位信息等）。
对于面试轮次，请从内容中推断（如一面、二面、HR面等）。"""
                    try:
                        _rc, _rm, _rt, _rbu, _rprovider = get_llm_client_for_user(_user['id'])
                        retry_kwargs = dict(model=_rm, messages=[{"role": "system", "content": "你是一个信息补全助手。根据已有信息推断缺失字段，返回JSON。"}, {"role": "user", "content": retry_prompt}], temperature=0.2)
                        if _should_use_response_format(_rbu):
                            retry_kwargs["response_format"] = {"type": "json_object"}
                        retry_text = await raw_llm_call(_user['id'], **retry_kwargs)
                        retry_data = _extract_json(retry_text)
                        for field in missing_fields:
                            val = retry_data.get(field, "未提供")
                            if val and val != "未提供":
                                data[field] = val
                        yield f"data: {json.dumps({'step': 'fill', 'message': f'缺失信息已推断（{missing_label}）', 'type': 'progress'})}\n\n"
                    except Exception as e:
                        logger.warning(f"字段补全重试失败: {e}")
                        yield f"data: {json.dumps({'step': 'fill', 'message': f'信息补全失败，继续处理', 'type': 'progress'})}\n\n"
                else:
                    yield f"data: {json.dumps({'step': 'fill', 'message': '信息完整，跳过补全', 'type': 'progress'})}\n\n"

                # ── 阶段 3：题目标注 ──
                taxonomy_config = await run_db(get_taxonomy_for_position)
                tagged_rows = await tag_questions_batch(saved_url, data.get("公司", "未提供"), data.get("面试轮次", "未提供"), q_list, taxonomy_config, user_id=_user['id'])
                yield f"data: {json.dumps({'step': 'tag', 'message': f'标注完成，共 {len(tagged_rows)} 道题', 'type': 'progress'})}\n\n"

                # ── 阶段 4：写入 ──
                if submit_target == 'personal':
                    # 个人题库：走原有匹配流程
                    from app.services.clustering import match_new_questions

                    def _load_existing_bank():
                        with get_db_connection() as conn:
                            rows = conn.execute(
                                "SELECT id, question, cat2, sources, original_questions, original_question_sources FROM question_bank WHERE owner_id = ? AND job_position = ?",
                                (_user['id'], current_pos)
                            ).fetchall()
                            return [dict(r) for r in rows]
                    existing_bank = await run_db(_load_existing_bank)
                    existing_by_cat2 = {}
                    for r in existing_bank:
                        cat2 = r.get('cat2') or ''
                        if cat2 not in existing_by_cat2: existing_by_cat2[cat2] = []
                        all_qs = [r['question']]
                        try:
                            orig = json.loads(r.get('original_questions') or '[]')
                            all_qs.extend([q for q in orig if q and q != r['question']])
                        except Exception:
                            pass
                        existing_by_cat2[cat2].append({"question_bank_id": r['id'], "question": r['question'], "all_questions": all_qs})
                    valid_rows = [r for r in tagged_rows if r[3].strip()]
                    new_rows_for_match = [{"id": idx, "question": r[3], "cat2": r[5] if len(r) > 5 else '', "_orig_row": r} for idx, r in enumerate(valid_rows)]
                    match_result = await match_new_questions(new_rows_for_match, existing_by_cat2)
                    idx_to_row = {idx: r for idx, r in enumerate(valid_rows)}
                    matched_count = len(match_result["matched"])
                    unmatched_count = len(match_result["unmatched"])
                    yield f"data: {json.dumps({'step': 'match', 'message': f'匹配完成：{matched_count} 道已有题目，{unmatched_count} 道新题', 'type': 'progress'})}\n\n"

                    yield f"data: {json.dumps({'step': 'save', 'message': '正在写入题库...', 'type': 'progress'})}\n\n"
                    answer_tasks, _ = await run_db(lambda: submit_interview_txn(
                        saved_url, data, questions, _season.strip(),
                        record_owner_id, record_status, current_pos,
                        tagged_rows, match_result['matched'], match_result['unmatched'],
                        idx_to_row, bool(is_admin), _user['id'],
                        qb_owner_id=_user['id']
                    ))
                    for qid, qtext in answer_tasks:
                        bg_tasks.add_task(background_generate_answer, qid, qtext, _user['id'])
                else:
                    # 公共题库：只写 interview + questions_detail，入队等待聚类
                    from app.db.operations import submit_interview_txn_tag_only
                    from app.services.pipeline import enqueue_questions, should_trigger_clustering, dequeue_batch, cluster_batch, mark_batch_done, mark_batch_failed

                    yield f"data: {json.dumps({'step': 'match', 'message': '正在保存面经...', 'type': 'progress'})}\n\n"
                    interview_id = await run_db(lambda: submit_interview_txn_tag_only(
                        saved_url, data, questions, _season.strip(),
                        record_owner_id, record_status, current_pos,
                        tagged_rows
                    ))
                    enqueue_questions(interview_id)
                    yield f"data: {json.dumps({'step': 'match', 'message': '已加入聚类队列', 'type': 'progress'})}\n\n"

                    # 检查是否触发聚类
                    if should_trigger_clustering():
                        yield f"data: {json.dumps({'step': 'save', 'message': '触发批量聚类...', 'type': 'progress'})}\n\n"
                        batch = dequeue_batch()
                        if batch:
                            try:
                                new_count = await cluster_batch(batch, user_id=_user['id'])
                                queue_ids = [item['queue_id'] for item in batch]
                                mark_batch_done(queue_ids)
                                yield f"data: {json.dumps({'step': 'save', 'message': f'聚类完成，新增 {new_count} 个聚类', 'type': 'progress', 'new_qb_count': new_count}, ensure_ascii=False)}\n\n"
                            except Exception as e:
                                logger.error(f"聚类失败，回退队列状态: {e}")
                                queue_ids = [item['queue_id'] for item in batch]
                                mark_batch_failed(queue_ids)
                                yield f"data: {json.dumps({'step': 'save', 'message': f'聚类失败: {str(e)}', 'type': 'error'}, ensure_ascii=False)}\n\n"

            except Exception as e:
                logger.error(f"题目标签化及更新题库失败: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': f'处理失败: {str(e)[:200]}'})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'done', 'doc_type': 'Interview', 'target': submit_target, 'saved_data': data})}\n\n"

        except openai.AuthenticationError:
            logger.error("LLM API Key 无效")
            yield f"data: {json.dumps({'type': 'error', 'message': 'API Key 无效或已过期，请在系统配置中检查并更新'})}\n\n"
        except openai.NotFoundError as e:
            logger.error(f"LLM API 错误: {e}")
            msg = str(e)
            if 'image' in msg.lower():
                yield f"data: {json.dumps({'type': 'error', 'message': '当前模型不支持图片输入，请在系统配置中切换支持视觉的模型，或仅提交文本内容'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'error', 'message': 'LLM 接口返回错误，请检查模型配置是否正确'})}\n\n"
        except openai.APIConnectionError:
            logger.error("LLM 连接失败")
            yield f"data: {json.dumps({'type': 'error', 'message': '无法连接 LLM 服务，请检查 Base URL 是否正确'})}\n\n"
        except openai.APITimeoutError:
            logger.error("LLM 调用超时")
            yield f"data: {json.dumps({'type': 'error', 'message': 'LLM 服务响应超时，请稍后重试'})}\n\n"
        except openai.APIStatusError as e:
            logger.error(f"LLM API 错误: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': f'LLM 接口返回错误（{e.status_code}），请查看服务端日志'})}\n\n"
        except Exception as e:
            logger.exception("流式提交处理失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'处理失败: {str(e)[:200]}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@router.post("/api/submit-stream-v2")
async def submit_data_stream_v2(
    bg_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    url: Optional[str] = Form(""),
    text: Optional[str] = Form(""),
    season: Optional[str] = Form(""),
    content_type: Optional[str] = Form(""),
    target: Optional[str] = Form(""),
    files: List[UploadFile] = File(default=[])
):
    """SSE 版提交端点 (LangGraph 版本) — 流式推送处理进度。"""

    # ── 输入校验（与 v1 相同） ──
    if text and len(text) > 50000:
        raise HTTPException(status_code=400, detail="文本内容过长，请限制在 50000 字符以内")
    url = (url or "").strip()
    submit_target = (target or "personal").lower()
    if submit_target not in ("personal", "public"):
        submit_target = "personal"
    if url:
        check_owner = user['id'] if submit_target == 'personal' else None
        if await run_db(lambda: _check_duplicate_url_sync(url, owner_id=check_owner)):
            raise HTTPException(status_code=409, detail="该链接的内容已存在于数据库中，请勿重复上传！")
    if not (text or "").strip() and (not files or len(files) == 0 or not files[0].filename):
        raise HTTPException(status_code=400, detail="提交内容不能为空，必须提供纯文本或至少一张图片。")

    # ── 读取文件到内存 ──
    image_data = []
    if files and files[0].filename:
        if len(files) > 20:
            raise HTTPException(status_code=400, detail="最多上传 20 个文件")
        total_size = 0
        for file in files:
            if file.content_type.startswith("image/"):
                content = await file.read()
                total_size += len(content)
                if total_size > MAX_TOTAL_UPLOAD_SIZE:
                    raise HTTPException(status_code=413, detail=f"上传文件总大小超过限制（最大 {MAX_TOTAL_UPLOAD_SIZE // 1024 // 1024}MB）")
                if len(content) > MAX_FILE_SIZE:
                    raise HTTPException(status_code=413, detail=f"图片 {file.filename} 超过大小限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）")
                real_mime = _magic.from_buffer(content[:2048], mime=True)
                if real_mime not in ALLOWED_MIME_TYPES:
                    raise HTTPException(status_code=400, detail=f"文件 {file.filename} 不是有效的图片文件（检测到: {real_mime}）")
                image_data.append({"content": content, "mime": real_mime})

    input_state = {
        "raw_text": text or "",
        "image_data": image_data,
        "url": url,
        "season": season or "",
        "content_type_hint": (content_type or "").lower(),
        "target": submit_target,
        "user_id": user['id'],
        "is_admin": bool(user.get('is_admin', 0)),
        "job_position": _get_current_position_for_user(user['id']),
    }

    async def event_stream():
        result_collector = {}
        try:
            async for sse_data in stream_submit_graph(input_state, result_collector=result_collector):
                yield sse_data
        except openai.AuthenticationError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'API Key 无效或已过期，请在系统配置中检查并更新'})}\n\n"
        except openai.NotFoundError as e:
            msg = str(e)
            if 'image' in msg.lower():
                yield f"data: {json.dumps({'type': 'error', 'message': '当前模型不支持图片输入，请在系统配置中切换支持视觉的模型，或仅提交文本内容'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'error', 'message': 'LLM 接口返回错误，请检查模型配置是否正确'})}\n\n"
        except openai.APIConnectionError:
            yield f"data: {json.dumps({'type': 'error', 'message': '无法连接 LLM 服务，请检查 Base URL 是否正确'})}\n\n"
        except openai.APITimeoutError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'LLM 服务响应超时，请稍后重试'})}\n\n"
        except openai.APIStatusError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'LLM 接口返回错误（{e.status_code}），请查看服务端日志'})}\n\n"
        except Exception as e:
            logger.exception("LangGraph 流式提交处理失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'处理失败: {str(e)[:200]}'})}\n\n"
        finally:
            # 派发后台 AI 答案生成
            for qid, qtext in result_collector.get("answer_tasks", []):
                bg_tasks.add_task(background_generate_answer, qid, qtext, result_collector.get("user_id"))

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


# ── 上传任务化接口（后台 Job 模式） ──

SUBMIT_PHASES = ["extract", "fill", "tag", "match", "save", "cluster"]


@router.post("/api/submit-jobs")
async def create_submit_job(
    user: dict = Depends(get_current_user),
    url: Optional[str] = Form(""),
    text: Optional[str] = Form(""),
    season: Optional[str] = Form(""),
    content_type: Optional[str] = Form(""),
    target: Optional[str] = Form(""),
    files: List[UploadFile] = File(default=[])
):
    """创建上传导入后台任务。校验输入 → 存 payload → 创建 job → 入队执行。"""

    # ── 输入校验（与 submit-stream-v2 相同） ──
    if text and len(text) > 50000:
        raise HTTPException(status_code=400, detail="文本内容过长，请限制在 50000 字符以内")
    url = (url or "").strip()
    submit_target = (target or "personal").lower()
    if submit_target not in ("personal", "public"):
        submit_target = "personal"
    if url:
        check_owner = user['id'] if submit_target == 'personal' else None
        if await run_db(lambda: _check_duplicate_url_sync(url, owner_id=check_owner)):
            raise HTTPException(status_code=409, detail="该链接的内容已存在于数据库中，请勿重复上传！")
    if not (text or "").strip() and (not files or len(files) == 0 or not files[0].filename):
        raise HTTPException(status_code=400, detail="提交内容不能为空，必须提供纯文本或至少一张图片。")

    # ── 读取文件到内存 ──
    image_data = []
    if files and files[0].filename:
        if len(files) > 20:
            raise HTTPException(status_code=400, detail="最多上传 20 个文件")
        total_size = 0
        for file in files:
            if file.content_type.startswith("image/"):
                content = await file.read()
                total_size += len(content)
                if total_size > MAX_TOTAL_UPLOAD_SIZE:
                    raise HTTPException(status_code=413, detail=f"上传文件总大小超过限制（最大 {MAX_TOTAL_UPLOAD_SIZE // 1024 // 1024}MB）")
                if len(content) > MAX_FILE_SIZE:
                    raise HTTPException(status_code=413, detail=f"图片 {file.filename} 超过大小限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）")
                real_mime = _magic.from_buffer(content[:2048], mime=True)
                if real_mime not in ALLOWED_MIME_TYPES:
                    raise HTTPException(status_code=400, detail=f"文件 {file.filename} 不是有效的图片文件（检测到: {real_mime}）")
                # 图片序列化为 base64 以便存入 payload
                image_data.append({
                    "content_b64": base64.b64encode(content).decode('ascii'),
                    "mime": real_mime,
                })

    # 构建 payload
    payload = {
        "raw_text": text or "",
        "image_data": image_data,
        "url": url,
        "season": season or "",
        "content_type_hint": (content_type or "").lower(),
        "target": submit_target,
        "user_id": user['id'],
        "is_admin": bool(user.get('is_admin', 0)),
        "job_position": _get_current_position_for_user(user['id']),
    }

    # ── 创建 job + 存 payload（单事务） ──
    def _create_job():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            try:
                cursor.execute(
                    "INSERT INTO jobs (job_type, status, created_by, progress_total) VALUES ('submit_import', 'pending', ?, ?)",
                    (user['id'], len(SUBMIT_PHASES))
                )
                job_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
                    (job_id, json.dumps(payload, ensure_ascii=False))
                )
                conn.commit()
                return job_id
            except Exception:
                conn.rollback()
                raise

    job_id = await run_db(_create_job)

    # ── 入队后台执行 ──
    # Worker 在当前部署中是按需 profile，不默认启动。上传任务默认在
    # backend 进程内后台执行，避免 Redis 入队成功但无人消费导致 pending 卡死。
    arq_scheduled = False
    if os.environ.get("SUBMIT_JOBS_USE_ARQ", "").lower() in ("1", "true", "yes"):
        try:
            from app.worker import enqueue_submit_import_job
            await enqueue_submit_import_job(job_id)
            arq_scheduled = True
            logger.info(f"上传导入任务已通过 ARQ 调度: job_id={job_id}")
        except Exception as e:
            logger.warning(f"ARQ 调度失败，回退到 asyncio.create_task: {e}")

    if not arq_scheduled:
        from app.worker import submit_import_task
        asyncio.create_task(submit_import_task({}, job_id))
        logger.info(f"上传导入任务已在 backend 后台执行: job_id={job_id}")

    return {"job_id": job_id, "status": "pending", "message": "上传任务已创建"}


@router.get("/api/submit-jobs/active")
async def get_active_submit_jobs(user: dict = Depends(get_current_user)):
    """查询当前用户未完成的上传导入任务。"""
    def _query():
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, job_type, status, progress_current, progress_total, progress_message, created_at, updated_at "
                "FROM jobs WHERE created_by = ? AND job_type = 'submit_import' AND status IN ('pending', 'running') "
                "ORDER BY created_at DESC",
                (user['id'],)
            ).fetchall()
            return [dict(r) for r in rows]

    return await run_db(_query)
