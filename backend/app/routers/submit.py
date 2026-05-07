import asyncio
import json
import logging
import openai
import magic as _magic

from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from app.core.config import LLM_MODEL, MAX_FILE_SIZE, MAX_TOTAL_UPLOAD_SIZE

ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp'}
from app.core.prompts import SYSTEM_PROMPT, JD_PROMPT, INTERVIEW_PROMPT, TAGGING_PROMPT, build_tagging_prompt
from app.core.auth import get_current_user
from app.db.connection import get_db_connection, run_db, get_current_job_position, get_taxonomy_for_position
from app.db.operations import _check_duplicate_url_sync, _insert_jd, _insert_interview, _insert_details
from app.services.llm import client, _should_use_response_format, _extract_json, _call_llm_with_retry_messages
from app.services.utils import encode_image, normalize_category

logger = logging.getLogger("interview-boss")

router = APIRouter()


async def tag_questions_batch(url: str, company: str, round_: str, questions: List[str], taxonomy_config: dict = None) -> List[List[str]]:
    input_data = [{"id": idx, "题目": q} for idx, q in enumerate(questions)]
    q_json = json.dumps(input_data, ensure_ascii=False)
    prompt = build_tagging_prompt(taxonomy_config) if taxonomy_config else TAGGING_PROMPT
    user_msg = prompt.replace("{questions}", q_json)

    kwargs = dict(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": "你是一个严格输出 JSON 对象的助手，格式必须为 {\"questions\": [...]}。必须输出输入数据中每一项对应的 \"id\" 字段，以便于与原输入一一对应。"},
            {"role": "user", "content": user_msg}
        ],
        temperature=0.0,
    )
    if _should_use_response_format():
        kwargs["response_format"] = {"type": "json_object"}
    from app.services.llm import _call_llm_with_retry
    raw_content = await _call_llm_with_retry(
        prompt=user_msg,
        system_msg="你是一个严格输出 JSON 对象的助手，格式必须为 {\"questions\": [...]}。必须输出输入数据中每一项对应的 \"id\" 字段，以便于与原输入一一对应。",
        response_format=kwargs.get("response_format"),
    )
    try:
        raw_items = _extract_json(raw_content).get("questions", [])
        result_map = {}
        for item in raw_items:
            if isinstance(item, dict) and "id" in item:
                try:
                    item_id = int(item["id"])
                    result_map[item_id] = {
                        "题目": item.get("题目", ""),
                        "一级大类": item.get("一级大类", ""),
                        "二级子类": item.get("二级子类", ""),
                        "考点标签": item.get("考点标签", ""),
                        "难度标签": item.get("难度标签", "")
                    }
                except (ValueError, TypeError):
                    pass
    except Exception:
        raw_items = []
        result_map = {}

    standardized = []
    for idx, q in enumerate(questions):
        if idx in result_map:
            it = result_map[idx]
            standardized.append([url, company, round_, q, normalize_category(it["一级大类"]), normalize_category(it["二级子类"]), it["考点标签"], it["难度标签"]])
        else:
            standardized.append([url, company, round_, q, "未分类(API漏标)", "未分类", "", "未知"])
    return standardized


async def incremental_update_master_bank(new_tagged_rows: list, bg_tasks: BackgroundTasks, submitter_is_admin: bool = True, user_id: int = None, is_personal: bool = False):
    from app.services.clustering import match_new_questions

    if not new_tagged_rows:
        return

    # 过滤掉空文本的行
    valid_rows = [row for row in new_tagged_rows if row[3].strip()]
    if not valid_rows:
        return

    current_pos = get_current_job_position()

    async def background_generate_answer(question_id: int, question_text: str):
        from app.core.prompts import ANSWER_PROMPT
        from app.services.llm import _call_llm_with_retry
        try:
            prompt = ANSWER_PROMPT.replace("{question}", question_text)
            answer = await _call_llm_with_retry(prompt)

            def _update():
                with get_db_connection() as conn:
                    conn.execute("UPDATE question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (answer, question_id))
                    conn.commit()

            await run_db(_update)
            logger.info(f"自动解答生成完毕: [ID:{question_id}] {question_text[:30]}...")
        except Exception as e:
            logger.error(f"自动解答生成失败（已重试3次）[ID:{question_id}]: {e}")
            def _mark_failed():
                with get_db_connection() as conn:
                    conn.execute("UPDATE question_bank SET ai_answer = '[生成失败，请手动重试]', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (question_id,))
                    conn.commit()
            try:
                await run_db(_mark_failed)
            except Exception:
                pass

    # 个人题库：直接插入，不做公共聚类
    if is_personal:
        def _insert_personal():
            with get_db_connection() as conn:
                cursor = conn.cursor()
                for row in valid_rows:
                    url, company, round_, q_text = row[0], row[1], row[2], row[3]
                    cat1 = normalize_category(row[4])
                    cat2 = normalize_category(row[5]) if len(row) > 5 else ''
                    tags = row[6] if len(row) > 6 else ''
                    diff_tag = row[7] if len(row) > 7 else '未知'
                    sources_json = json.dumps([{"url": url, "company": company, "round": round_}], ensure_ascii=False)
                    cursor.execute(
                        "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, sources, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 'approved', ?)",
                        (q_text, cat1, cat2, tags, diff_tag, sources_json, user_id, user_id, current_pos)
                    )
                    new_id = cursor.lastrowid
                    bg_tasks.add_task(background_generate_answer, new_id, q_text)
                conn.commit()

        await run_db(_insert_personal)
        logger.info(f"个人题库新增 {len(valid_rows)} 题")
        return

    # 公共题库：走聚类匹配流程
    def _load_existing():
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, question, cat2, sources FROM question_bank WHERE owner_id IS NULL AND status = 'approved' AND job_position = ?",
                (current_pos,)
            ).fetchall()
            return [dict(r) for r in rows]

    existing_bank = await run_db(_load_existing)

    # 按 cat2 分组已有题库，构建聚类上下文
    existing_by_cat2 = {}
    for r in existing_bank:
        cat2 = r.get('cat2') or ''
        if cat2 not in existing_by_cat2:
            existing_by_cat2[cat2] = []
        existing_by_cat2[cat2].append({
            "question_bank_id": r['id'],
            "question": r['question'],
            "all_questions": [r['question']],  # 每个聚类目前只有1个代表题
        })

    # 构建新题目列表（带 id 用于匹配结果映射）
    new_rows_for_match = []
    for idx, row in enumerate(valid_rows):
        new_rows_for_match.append({
            "id": idx,  # 临时 id，用于匹配结果
            "question": row[3],
            "cat2": row[5] if len(row) > 5 else '',  # cat2 在 row[5]
            "_orig_row": row,  # 保留原始行数据，用于未匹配时写入题库
        })

    # LLM 增量匹配
    match_result = await match_new_questions(new_rows_for_match, existing_by_cat2)
    matched = match_result["matched"]
    unmatched_rows = match_result["unmatched"]

    # 构建 idx → row 映射
    idx_to_row = {idx: row for idx, row in enumerate(valid_rows)}

    def _update_db():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            submitter_id = user_id
            if not submitter_id:
                import os
                admin_username = os.getenv("ADMIN_USERNAME", "sj")
                admin_row = conn.execute("SELECT id FROM users WHERE username = ?", (admin_username,)).fetchone()
                submitter_id = admin_row[0] if admin_row else None
            status = 'approved' if submitter_is_admin else 'pending'

            # 处理匹配到的题目：更新 frequency 和 sources
            for m in matched:
                new_idx = m["new_id"]
                qb_id = m["question_bank_id"]
                row = idx_to_row.get(new_idx)
                if not row:
                    continue

                url, company, round_ = row[0], row[1], row[2]
                new_source = {"url": url, "company": company, "round": round_}

                existing = cursor.execute("SELECT sources FROM question_bank WHERE id = ?", (qb_id,)).fetchone()
                if existing:
                    try:
                        sources = json.loads(existing['sources']) if existing['sources'] else []
                    except Exception:
                        sources = []
                    if new_source not in sources:
                        sources.append(new_source)
                    cursor.execute(
                        "UPDATE question_bank SET frequency = frequency + 1, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (json.dumps(sources, ensure_ascii=False), qb_id)
                    )

            # 处理未匹配的题目：新增到题库
            for item in unmatched_rows:
                row = item.get("_orig_row") if isinstance(item, dict) else item
                url, company, round_, q_text = row[0], row[1], row[2], row[3]
                cat1 = normalize_category(row[4])
                cat2 = normalize_category(row[5]) if len(row) > 5 else ''
                tags = row[6] if len(row) > 6 else ''
                diff_tag = row[7] if len(row) > 7 else '未知'

                sources_json = json.dumps([{"url": url, "company": company, "round": round_}], ensure_ascii=False)
                cursor.execute(
                    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, sources, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, 1, ?, NULL, ?, ?, ?)",
                    (q_text, cat1, cat2, tags, diff_tag, sources_json, submitter_id, status, current_pos)
                )
                new_id = cursor.lastrowid
                if status == 'approved':
                    bg_tasks.add_task(background_generate_answer, new_id, q_text)

            conn.commit()

    await run_db(_update_db)
    logger.info(f"增量更新完成: 匹配 {len(matched)} 题, 新增 {len(unmatched_rows)} 题")


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
    if url and await run_db(lambda: _check_duplicate_url_sync(url)):
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

        llm_kwargs = dict(
            model=LLM_MODEL,
            temperature=0.1,
        )
        if _should_use_response_format():
            llm_kwargs["response_format"] = {"type": "json_object"}
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]
        response_text = await _call_llm_with_retry_messages(messages, **llm_kwargs)
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

        # 计算 owner_id 和 status
        is_admin = user.get('is_admin', 0)
        if submit_target == 'personal':
            record_owner_id = user['id']
            record_status = 'approved'
        else:
            record_owner_id = None
            record_status = 'approved' if is_admin else 'pending'

        if doc_type == "jd":
            _ts = data.get("核心技术要求", [])
            tech_stack = "\n".join(f"{i+1}. {item}" for i, item in enumerate(_ts)) if _ts else "未提供"
            await run_db(lambda: _insert_jd(saved_url, data, tech_stack, season.strip(), owner_id=record_owner_id, status=record_status))
            return {"status": "success", "type": "JD", "target": submit_target, "saved_data": data}

        elif doc_type == "interview":
            _ql = data.get("具体题目清单", [])
            questions = "\n".join(f"{i+1}. {item}" for i, item in enumerate(_ql)) if _ql else "未提供"
            await run_db(lambda: _insert_interview(saved_url, data, questions, season.strip(), owner_id=record_owner_id, status=record_status))

            q_list = data.get("具体题目清单", [])
            if q_list:
                try:
                    # 重试补全和题目标签化并行执行
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
                            retry_kwargs = dict(
                                model=LLM_MODEL,
                                messages=[
                                    {"role": "system", "content": "你是一个信息补全助手。根据已有信息推断缺失字段，返回JSON。"},
                                    {"role": "user", "content": retry_prompt}
                                ],
                                temperature=0.2,
                            )
                            if _should_use_response_format():
                                retry_kwargs["response_format"] = {"type": "json_object"}
                            retry_response = await client.chat.completions.create(**retry_kwargs)
                            retry_data = _extract_json(retry_response.choices[0].message.content)
                            for field in missing_fields:
                                val = retry_data.get(field, "未提供")
                                if val and val != "未提供":
                                    data[field] = val
                                    logger.info(f"字段补全成功: {field} = {val}")
                        except Exception as e:
                            logger.warning(f"字段补全重试失败: {e}")

                    # 读取当前岗位的分类体系
                    taxonomy_config = await run_db(get_taxonomy_for_position)

                    # 并行执行：重试补全 + 题目标签化
                    _, tagged_rows = await asyncio.gather(
                        retry_fill_fields(),
                        tag_questions_batch(saved_url, data.get("公司", "未提供"), data.get("面试轮次", "未提供"), q_list, taxonomy_config)
                    )

                    # 重试可能更新了公司/轮次，同步到已标签化的行
                    if missing_fields:
                        updated_company = data.get("公司", "未提供")
                        updated_round = data.get("面试轮次", "未提供")
                        for row in tagged_rows:
                            row[1] = updated_company
                            row[2] = updated_round

                    await run_db(lambda: _insert_details(tagged_rows))
                    await incremental_update_master_bank(
                        tagged_rows, bg_tasks,
                        submitter_is_admin=bool(is_admin),
                        user_id=user['id'],
                        is_personal=(submit_target == 'personal')
                    )

                except Exception as e:
                    logger.error(f"题目标签化及更新题库失败: {e}")

            return {"status": "success", "type": "Interview", "target": submit_target, "saved_data": data}
        else:
            raise HTTPException(status_code=500, detail="模型返回了未知的分类类型: " + str(doc_type))
    except HTTPException:
        raise
    except openai.AuthenticationError:
        logger.error("LLM API Key 无效")
        raise HTTPException(status_code=500, detail="API Key 无效或已过期，请在系统配置中检查并更新 API Key。")
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
