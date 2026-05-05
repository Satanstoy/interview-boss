import json
import logging

from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from app.core.config import LLM_MODEL, MAX_FILE_SIZE
from app.core.prompts import SYSTEM_PROMPT, TAGGING_PROMPT
from app.db.connection import get_db_connection, run_db
from app.db.operations import _check_duplicate_url_sync, _insert_jd, _insert_interview, _insert_details
from app.services.llm import client
from app.services.embedding import find_best_match
from app.services.utils import encode_image, normalize_category, format_array_for_csv

logger = logging.getLogger("interview-boss")

router = APIRouter()


async def tag_questions_batch(url: str, company: str, round_: str, questions: List[str]) -> List[List[str]]:
    input_data = [{"id": idx, "题目": q} for idx, q in enumerate(questions)]
    q_json = json.dumps(input_data, ensure_ascii=False)
    user_msg = TAGGING_PROMPT.replace("{questions}", q_json)

    response = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": "你是一个严格输出 JSON 对象的助手，格式必须为 {\"questions\": [...]}。必须输出输入数据中每一项对应的 \"id\" 字段，以便于与原输入一一对应。"},
            {"role": "user", "content": user_msg}
        ],
        temperature=0.0,
        response_format={"type": "json_object"}
    )
    try:
        raw_items = json.loads(response.choices[0].message.content.strip()).get("questions", [])
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


async def incremental_update_master_bank(new_tagged_rows: list, bg_tasks: BackgroundTasks):
    from app.services.llm import client_of_embedding
    from app.core.config import EMBEDDING_MODEL

    if not new_tagged_rows:
        return

    # 过滤掉空文本的行，同时保留原始索引映射
    valid_rows = [(idx, row) for idx, row in enumerate(new_tagged_rows) if row[3].strip()]
    if not valid_rows:
        return

    texts = [row[3] for _, row in valid_rows]
    batch_texts = [t.replace("\n", " ") for t in texts]
    try:
        resp = await client_of_embedding.embeddings.create(input=batch_texts, model=EMBEDDING_MODEL)
        embeddings = [d.embedding for d in resp.data]
    except Exception as e:
        logger.error(f"向量提取失败，跳过增量更新: {e}")
        return

    def _load_existing():
        with get_db_connection() as conn:
            return conn.execute("SELECT id, question, vector, sources FROM question_bank WHERE owner_id IS NULL AND status = 'approved'").fetchall()

    existing_masters = await run_db(_load_existing)

    master_vecs = []
    for m in existing_masters:
        if m['vector']:
            try:
                parsed_sources = json.loads(m['sources']) if m['sources'] else []
                master_vecs.append({
                    "id": m['id'],
                    "question": m['question'],
                    "vector": json.loads(m['vector']),
                    "sources": parsed_sources
                })
            except Exception:
                pass

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
            # 标记失败状态，前端可识别并支持手动重试
            def _mark_failed():
                with get_db_connection() as conn:
                    conn.execute("UPDATE question_bank SET ai_answer = '[生成失败，请手动重试]', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (question_id,))
                    conn.commit()
            try:
                await run_db(_mark_failed)
            except Exception:
                pass

    def _update_db():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # 获取管理员 ID 作为默认 submitted_by
            admin_row = conn.execute("SELECT id FROM users WHERE username = 'sj'").fetchone()
            admin_id = admin_row[0] if admin_row else None

            for emb_idx, (orig_idx, row) in enumerate(valid_rows):
                new_vec = embeddings[emb_idx]
                url, company, round_, q_text = row[0], row[1], row[2], row[3]
                cat1 = normalize_category(row[4])
                tags = row[6]
                diff_tag = row[7]

                new_source = {"url": url, "company": company, "round": round_}

                best_match, best_score = find_best_match(new_vec, master_vecs)

                if best_match:
                    if new_source not in best_match['sources']:
                        best_match['sources'].append(new_source)

                    cursor.execute(
                        "UPDATE question_bank SET frequency = frequency + 1, sources = ? WHERE id = ?",
                        (json.dumps(best_match['sources']), best_match['id'])
                    )
                    best_match['frequency'] = best_match.get('frequency', 1) + 1
                else:
                    sources_json = json.dumps([new_source])
                    cursor.execute(
                        "INSERT INTO question_bank (question, cat1, tags, difficulty, vector, sources, owner_id, submitted_by, status) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 'approved')",
                        (q_text, cat1, tags, diff_tag, json.dumps(new_vec), sources_json, admin_id)
                    )
                    new_id = cursor.lastrowid
                    master_vecs.append({"id": new_id, "question": q_text, "vector": new_vec, "sources": [new_source]})

                    bg_tasks.add_task(background_generate_answer, new_id, q_text)

            conn.commit()

    await run_db(_update_db)


@router.post("/api/submit")
async def submit_data(
    bg_tasks: BackgroundTasks,
    url: Optional[str] = Form(""),
    text: Optional[str] = Form(""),
    season: Optional[str] = Form(""),
    files: List[UploadFile] = File(default=[])
):
    url = url.strip() if url else ""
    if url and await run_db(lambda: _check_duplicate_url_sync(url)):
        raise HTTPException(status_code=409, detail="该链接的内容已存在于数据库中，请勿重复上传！")
    if not text.strip() and (not files or len(files) == 0 or not files[0].filename):
        raise HTTPException(status_code=400, detail="提交内容不能为空，必须提供纯文本或至少一张图片。")

    try:
        user_content = [{"type": "text", "text": "请分析以下联合内容，保持信息连贯性，并综合整理后严格按照 JSON Schema 返回："}]
        if text.strip():
            user_content.append({"type": "text", "text": f"\n【文本内容】:\n{text}\n"})
        if files and files[0].filename:
            for file in files:
                if file.content_type.startswith("image/"):
                    content = await file.read()
                    # 文件大小限制
                    if len(content) > MAX_FILE_SIZE:
                        raise HTTPException(status_code=413, detail=f"图片 {file.filename} 超过大小限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）")
                    base64_img = encode_image(content)
                    user_content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{file.content_type};base64,{base64_img}"}
                    })

        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_content}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        parsed_data = json.loads(response.choices[0].message.content.strip())
        doc_type = parsed_data.get("type")
        data = parsed_data.get("data", {})
        saved_url = url if url else "未提供链接"

        # 校验 LLM 返回的数据是否有效
        if not doc_type or not data:
            raise HTTPException(status_code=422, detail="大模型未能从内容中提取有效信息，请检查提交的内容是否包含足够的文本或图片。")

        if doc_type == "Interview":
            q_list = data.get("具体题目清单", [])
            if not q_list or all(not q.strip() for q in q_list):
                raise HTTPException(status_code=422, detail="大模型未能从内容中提取到面试题目，请确认提交的是面经内容而非其他类型。")

            # 对"未提供"的关键字段进行重试补全
            missing_fields = []
            if data.get("公司") == "未提供":
                missing_fields.append("公司")
            if data.get("面试轮次") == "未提供":
                missing_fields.append("面试轮次")
            if data.get("难易程度") == "未提供":
                missing_fields.append("难易程度")

            if missing_fields and len(missing_fields) <= 2:
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
                    retry_response = await client.chat.completions.create(
                        model=LLM_MODEL,
                        messages=[
                            {"role": "system", "content": "你是一个信息补全助手。根据已有信息推断缺失字段，返回JSON。"},
                            {"role": "user", "content": retry_prompt}
                        ],
                        temperature=0.2,
                        response_format={"type": "json_object"}
                    )
                    retry_data = json.loads(retry_response.choices[0].message.content.strip())
                    for field in missing_fields:
                        val = retry_data.get(field, "未提供")
                        if val and val != "未提供":
                            data[field] = val
                            logger.info(f"字段补全成功: {field} = {val}")
                except Exception as e:
                    logger.warning(f"字段补全重试失败: {e}")

        if doc_type == "JD":
            tech_stack = format_array_for_csv(data.get("核心技术要求", []))
            await run_db(lambda: _insert_jd(saved_url, data, tech_stack))
            return {"status": "success", "type": "JD", "saved_data": data}

        elif doc_type == "Interview":
            questions = format_array_for_csv(data.get("具体题目清单", []))
            await run_db(lambda: _insert_interview(saved_url, data, questions, season.strip()))

            q_list = data.get("具体题目清单", [])
            if q_list:
                try:
                    tagged_rows = await tag_questions_batch(saved_url, data.get("公司", "未提供"), data.get("面试轮次", "未提供"), q_list)
                    await run_db(lambda: _insert_details(tagged_rows))
                    await incremental_update_master_bank(tagged_rows, bg_tasks)

                except Exception as e:
                    logger.error(f"题目标签化及更新题库失败: {e}")

            return {"status": "success", "type": "Interview", "saved_data": data}
        else:
            raise HTTPException(status_code=500, detail="模型返回了未知的分类类型: " + str(doc_type))
    except Exception as e:
        logger.exception("提交处理失败")
        raise HTTPException(status_code=500, detail=str(e))
