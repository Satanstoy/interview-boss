import os
import json
import base64
import traceback
import sqlite3
import csv
import math
import re
from typing import List, Optional
from collections import Counter
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

app = FastAPI(title="Multimodal CV & JD Parser")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = AsyncOpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL")
)

client_of_embedding = AsyncOpenAI(
    api_key=os.environ.get("OPENAI_API_KEY_EMBEDDING"),
    base_url=os.environ.get("OPENAI_BASE_URL_EMBEDDING")
)

LLM_MODEL = os.environ.get("LLM_MODEL_NAME", "gpt-4o")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL_NAME", "text-embedding-3-small")

DATA_DIR = "/root/sj/multimodal-parser/backend/data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "multimodal.db")

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS master_question_bank (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT UNIQUE,
                cat1 TEXT,
                cat2 TEXT,
                tags TEXT,
                difficulty TEXT,
                frequency INTEGER DEFAULT 1,
                ai_answer TEXT,
                vector TEXT,
                sources TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(master_question_bank)")
        columns = [info[1] for info in cursor.fetchall()]
        if "vector" not in columns:
            conn.execute("ALTER TABLE master_question_bank ADD COLUMN vector TEXT")
        # 🔥 新增 sources 字段（以 JSON 数组存储这道题目的面经来源）
        if "sources" not in columns:
            conn.execute("ALTER TABLE master_question_bank ADD COLUMN sources TEXT DEFAULT '[]'")
init_db()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot_product = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot_product / (mag1 * mag2)

def check_duplicate_url(url: str) -> bool:
    if not url: return False
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM jd WHERE url = ?", (url,))
        if cursor.fetchone(): return True
        cursor.execute("SELECT 1 FROM interview WHERE url = ?", (url,))
        if cursor.fetchone(): return True
    return False

def encode_image(file_bytes: bytes) -> str:
    return base64.b64encode(file_bytes).decode('utf-8')

def format_array_for_csv(data_array: list) -> str:
    if not isinstance(data_array, list) or not data_array:
        return str(data_array) if data_array else "未提供"
    return "\n".join([f"{i+1}. {item}" for i, item in enumerate(data_array)])

SYSTEM_PROMPT = """你是一名顶级的信息提取专家。请从用户提供的文本/图片中提取以下结构化的JSON。

## 输出格式要求
返回一个JSON对象，包含两个顶层字段：
{
  "type": "JD 或 Interview 之一",
  "data": { ... }
}

## 判定 type 的规则
- 如果内容包含明确的岗位名称、技术栈要求、薪资、加分项等，判定为 JD。
- 如果内容包含面试轮次、面试题目、考察点等，判定为 Interview。
- 若无法判断，请根据主要特征选择最接近的一种。

## 当 type 为 "JD" 时，data 必须包含以下字段：
{
  "公司": "从内容中提取的公司名称，若缺失填'未提供'",
  "岗位名称": "职位名称，缺失填'未提供'",
  "薪资范围": "如 25k-40k，缺失填'未提供'",
  "核心技术要求": ["列出具体技术栈，如 Java, Spring, MySQL, Redis等，每项一条"],
  "加分项": "加分项原文描述，若无则'未提供'"
}

## 当 type 为 "Interview" 时，data 必须包含以下字段：
{
  "公司": "公司名，缺失填'未提供'",
  "面试轮次": "如 一面、二面、终面，缺失填'未提供'",
  "考察重点": "概括面试侧重点，如项目经验、算法、系统设计等",
  "具体题目清单": ["题目1", "题目2", "题目3", ...],
  "难易程度": "候选人对难度的描述，如 中等、较难，缺失填'未提供'"
}

## 抽取原则
- 严格按上述字段输出，不要遗漏任何一个字段。
- 所有字段值都用中文，除非原文是英文专业术语。
- 如果多张图片/多段文本属于同一份 JD 或面经，请合并分析，不要重复输出。
- 具体题目清单中的每道题应保持原样，不进行缩写或改写。
"""

TAGGING_PROMPT = """你是一名面试题结构化分类专家。请将下列每道面试题精确分配到分类体系中，并按要求输出JSON。

## 分类体系（严格遵循层级）
- **A. 项目经验与设计**
   A1. 项目介绍与背景
   A2. 系统架构设计
   A3. 难点攻关与优化
   A4. 反思与改进
- **B. Agent与LLM应用**
   B1. Agent架构设计
   B2. 记忆管理
   B3. 检索增强生成/RAG
   B4. 工具调用与集成
   B5. Prompt工程
   B6. 推理与规划范式
   B7. 上下文管理
   B8. 监控与评估
- **C. 基础工程能力**
   C1. 编程语言基础
   C2. 框架与中间件
   C3. 数据库基础
   C4. 操作系统与网络
- **D. 分布式系统与高并发**
   D1. 分布式一致性
   D2. 高并发策略
   D3. 链路与排障
- **E. 算法与数据结构**
   E1. 算法手撕与数据结构
- **F. 模型训练与评估**
   F1. 微调与评估
- **其他** (仅当确实无法归入以上任何一类时使用)

## 考点标签（可多选，从下方选择，用逗号分隔）
Agent架构设计, 记忆管理, RAG设计, 工具调用, Prompt工程, ReAct/推理范式, 上下文管理, 微调/SFT, 模型评估, Java并发, Redis, Spring/AOP, 分布式事务, 高并发限流, MySQL, Linux/网络, 算法手撕, 系统设计, AI Coding, 模型选型

## 难度标签（单选）
- L1-基础：考察基础知识、八股文，无需复杂推理
- L2-中等：需要结合项目场景、融会贯通
- L3-困难：需要深度系统设计或复杂算法手撕

## 规则
1. 一级大类与二级子类必须匹配，例如选了一级大类 A，则二级子类必须是 A1-A4 之一。
2. 考点标签应选择与题目直接相关的技术领域，不要与二级子类简单重复。
3. 如果题目包含多个子问题，请拆分后作为独立题目分别标注。
4. 返回的结果中必须包含输入的 `id` 字段。

## Few-Shot 示例
输入题目列表：[{"id": 0, "题目": "请介绍你做过的一个项目，并说明其中遇到的难点"}]
输出：
{"questions": [{"id": 0, "题目": "请介绍你做过的一个项目，并说明其中遇到的难点", "一级大类": "A.项目经验与设计", "二级子类": "A3.难点攻关与优化", "考点标签": "系统设计", "难度标签": "L2-中等"}]}

输入题目列表：[{"id": 0, "题目": "Redis持久化机制有哪些？"}, {"id": 1, "题目": "如何设计一个分布式锁？"}]
输出：
{"questions": [
  {"id": 0, "题目": "Redis持久化机制有哪些？", "一级大类": "C.基础工程能力", "二级子类": "C2.框架与中间件", "考点标签": "Redis", "难度标签": "L1-基础"},
  {"id": 1, "题目": "如何设计一个分布式锁？", "一级大类": "D.分布式系统与高并发", "二级子类": "D2.高并发策略", "考点标签": "分布式事务, Redis", "难度标签": "L2-中等"}]}

## 任务
现在请为以下题目列表标记：
{questions}
"""

ANSWER_PROMPT = """你是一名资深后端与算法面试官。请根据【面试题】，给出一份**极易口述背诵**的高质量面试回答。

## 输出总则
- 自动判断题目类型，采用**最匹配的结构与风格**。
- 始终保持**短句、大白话、可背诵**，凸显真正理解，而非机械背诵。
- 用 Markdown 提升可读性，**加粗**关键骨架词。
- 总字数：非代码题 300–500 字，代码题可适当增加，但**代码本身必须最好背、最好理解**。
- 所有代码一律使用 **Python**，逻辑直白，注释清晰，**绝不炫技或过度优化**。

## 场景 A：算法/手撕代码题（如写题、实现数据结构、算法复杂度等）
👉 必须提供**可运行的 Python 代码块**，代码力求**最好背、最好理解**。
结构：
1. **破题思路**（一句话，直击核心考点）
2. **复杂度**（用口语带出，例如：“时间复杂度 O(n)，因为只遍历一遍”）
3. **Python 代码实现**（带关键注释，逻辑直白，不赘述）
4. **易错点/边界提示**（1-2 句，如“注意空数组、int 越界”）

## 场景 B：系统设计/架构/项目经验题（包括分布式、高并发、LLM应用等）
👉 采用务实风格，结合真实落地方案与权衡（Trade-off）。
结构：
1. **直接破题**（一句话亮出你的核心解法）
2. **落地要点**（2-3 个核心执行点，包含技术选型、踩坑、妥协原因）
3. **务实收尾**（1-2 句说明当前方案的局限性或未来优化方向）
风格：必须使用口语化词汇，如“其实我们当时…”、“踩过一个坑…”、“评估下来…”，**严禁**说教或背诵教科书。

## 场景 C：基础原理/理论题（如八股文、协议、数据库原理等）
👉 追求**准、简、直**，但依然口语化。
结构：
1. **核心解释**（一句话大白话讲透概念）
2. **关键细节**（1-2 个记忆锚点，如“三种角色：Proposer, Acceptor, Learner”）
3. **实用场景**（什么时候用、为什么不用别的，带上你的个人经验）
禁止堆砌概念，必须体现出“跟你说人话就能讲明白”的感觉。

## 面试题：
{question}

## 请直接用上述规则生成回答：
"""

async def background_generate_answer(question_id: int, question_text: str):
    try:
        prompt = ANSWER_PROMPT.replace("{question}", question_text)
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一个后端和算法面试指导专家。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        answer = response.choices[0].message.content.strip()
        with get_db_connection() as conn:
            conn.execute("UPDATE master_question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (answer, question_id))
            conn.commit()
        print(f"✅ 自动解答生成完毕: [ID:{question_id}] {question_text[:15]}...")
    except Exception as e:
        print(f"❌ 自动解答生成失败 [ID:{question_id}]: {e}")

async def incremental_update_master_bank(new_tagged_rows: list, bg_tasks: BackgroundTasks):
    if not new_tagged_rows: return
    
    texts = [row[3] for row in new_tagged_rows if row[3].strip()]
    if not texts: return

    embeddings = []
    batch_texts = [t.replace("\n", " ") for t in texts]
    try:
        resp = await client_of_embeding.embeddings.create(input=batch_texts, model=EMBEDDING_MODEL)
        embeddings = [d.embedding for d in resp.data]
    except Exception as e:
        print(f"向量提取失败，跳过增量更新: {e}")
        return

    # 🔥 获取现有数据，并解析 sources 字段
    with get_db_connection() as conn:
        existing_masters = conn.execute("SELECT id, question, vector, sources FROM master_question_bank").fetchall()
        
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
            except:
                pass

    with get_db_connection() as conn:
        cursor = conn.cursor()
        for idx, row in enumerate(new_tagged_rows):
            new_vec = embeddings[idx]
            # row 的格式是 [url, company, round_, q_text, cat1, cat2, tags, diff_tag]
            url, company, round_, q_text = row[0], row[1], row[2], row[3]
            cat1 = row[4]
            tags = row[6]
            diff_tag = row[7]
            
            # 🔥 提取面经来源
            new_source = {"url": url, "company": company, "round": round_}

            found_match = False
            for m in master_vecs:
                if cosine_similarity(new_vec, m['vector']) >= 0.85:
                    # 追加新的源头如果不重复的话
                    if new_source not in m['sources']:
                        m['sources'].append(new_source)
                    
                    cursor.execute(
                        "UPDATE master_question_bank SET frequency = frequency + 1, sources = ? WHERE id = ?", 
                        (json.dumps(m['sources']), m['id'])
                    )
                    found_match = True
                    m['frequency'] = m.get('frequency', 1) + 1
                    break

            if not found_match:
                sources_json = json.dumps([new_source])
                cursor.execute(
                    "INSERT INTO master_question_bank (question, cat1, tags, difficulty, vector, sources) VALUES (?, ?, ?, ?, ?, ?)",
                    (q_text, cat1, tags, diff_tag, json.dumps(new_vec), sources_json)
                )
                new_id = cursor.lastrowid
                master_vecs.append({"id": new_id, "question": q_text, "vector": new_vec, "sources": [new_source]})
                
                bg_tasks.add_task(background_generate_answer, new_id, q_text)
                
        conn.commit()


@app.post("/api/submit")
async def submit_data(
    bg_tasks: BackgroundTasks, 
    url: Optional[str] = Form(""),
    text: Optional[str] = Form(""),
    files: List[UploadFile] = File(default=[])
):
    url = url.strip() if url else ""
    if url and check_duplicate_url(url):
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

        if doc_type == "JD":
            tech_stack = format_array_for_csv(data.get("核心技术要求", []))
            with get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO jd (url, company, job_title, salary, tech_stack, bonus) VALUES (?, ?, ?, ?, ?, ?)",
                    (saved_url, data.get("公司", "未提供"), data.get("岗位名称", "未提供"), data.get("薪资范围", "未提供"), tech_stack, data.get("加分项", "未提供"))
                )
                conn.commit()
            return {"status": "success", "type": "JD", "saved_data": data}

        elif doc_type == "Interview":
            questions = format_array_for_csv(data.get("具体题目清单", []))
            with get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO interview (url, company, round, focus, questions_list, difficulty) VALUES (?, ?, ?, ?, ?, ?)",
                    (saved_url, data.get("公司", "未提供"), data.get("面试轮次", "未提供"), data.get("考察重点", "未提供"), questions, data.get("难易程度", "未提供"))
                )
                conn.commit()

            q_list = data.get("具体题目清单", [])
            if q_list:
                try:
                    tagged_rows = await tag_questions_batch(saved_url, data.get("公司", "未提供"), data.get("面试轮次", "未提供"), q_list)
                    with get_db_connection() as conn:
                        for tr in tagged_rows:
                            conn.execute(
                                "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                tuple(tr)
                            )
                        conn.commit()
                    
                    await incremental_update_master_bank(tagged_rows, bg_tasks)

                except Exception as e:
                    print(f"题目标签化及更新题库失败: {e}")

            return {"status": "success", "type": "Interview", "saved_data": data}
        else:
            raise HTTPException(status_code=500, detail="模型返回了未知的分类类型: " + str(doc_type))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

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
            standardized.append([url, company, round_, q, it["一级大类"], it["二级子类"], it["考点标签"], it["难度标签"]])
        else:
            standardized.append([url, company, round_, q, "未分类(API漏标)", "未分类", "", "未知"])
    return standardized

@app.get("/api/data/{file_type}")
async def get_data(file_type: str):
    table_map = {"jd": "jd", "interview": "interview", "tagged": "questions_detail"}
    table_name = table_map.get(file_type.lower())
    if not table_name: return []
    with get_db_connection() as conn:
        rows = conn.execute(f"SELECT * FROM {table_name} ORDER BY id ASC").fetchall()
        
    result = []
    for r in rows:
        d = dict(r)
        if table_name == 'jd':
            result.append({"id": d['id'], "来源链接": d['url'], "公司": d['company'], "岗位名称": d['job_title'], "薪资范围": d['salary'], "核心技术要求": d['tech_stack'], "加分项": d['bonus']})
        elif table_name == 'interview':
            result.append({"id": d['id'], "来源链接": d['url'], "公司": d['company'], "面试轮次": d['round'], "考察重点": d['focus'], "具体题目清单": d['questions_list'], "难易程度": d['difficulty']})
        elif table_name == 'questions_detail':
             result.append({"id": d['id'], "来源链接": d['url'], "公司": d['company'], "面试轮次": d['round'], "题目": d['question'], "一级大类": d['cat1'], "二级子类": d['cat2'], "考点标签": d['tags'], "难度标签": d['diff_tag']})
    return result

@app.get("/api/download/{file_type}")
async def download_csv(file_type: str):
    table_map = {
        "jd": ("jd", ["来源链接", "公司", "岗位名称", "薪资范围", "核心技术要求", "加分项"]),
        "interview": ("interview", ["来源链接", "公司", "面试轮次", "考察重点", "具体题目清单", "难易程度"]),
        "tagged": ("questions_detail", ["来源链接", "公司", "面试轮次", "题目", "一级大类", "二级子类", "考点标签", "难度标签"])
    }
    if file_type not in table_map: raise HTTPException(status_code=404, detail="未知文件类型")
    table_name, headers = table_map[file_type]
    temp_file_path = os.path.join(DATA_DIR, f"temp_{file_type}.csv")
    
    with get_db_connection() as conn:
        rows = conn.execute(f"SELECT * FROM {table_name} ORDER BY id ASC").fetchall()
    with open(temp_file_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for r in rows:
            d = dict(r)
            if table_name == 'jd': writer.writerow([d['url'], d['company'], d['job_title'], d['salary'], d['tech_stack'], d['bonus']])
            elif table_name == 'interview': writer.writerow([d['url'], d['company'], d['round'], d['focus'], d['questions_list'], d['difficulty']])
            elif table_name == 'questions_detail': writer.writerow([d['url'], d['company'], d['round'], d['question'], d['cat1'], d['cat2'], d['tags'], d['diff_tag']])
    return FileResponse(path=temp_file_path, filename=f"{file_type}_data.csv", media_type='text/csv')

@app.delete("/api/data/{file_type}/{row_index}")
async def delete_data(file_type: str, row_index: int):
    table_map = {"jd": "jd", "interview": "interview", "tagged": "questions_detail"}
    table_name = table_map.get(file_type.lower())
    if not table_name: raise HTTPException(status_code=400, detail="不支持")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute(f"SELECT id, url, questions_list FROM {table_name} ORDER BY id ASC").fetchall()
            if row_index < 0 or row_index >= len(rows): raise HTTPException(status_code=400, detail="越界")
            
            target_row = rows[row_index]
            target_id = target_row['id']
            
            if table_name == 'interview':
                url = target_row['url']
                cursor.execute("DELETE FROM questions_detail WHERE url = ?", (url,))
                
                q_list_str = target_row['questions_list'] or ""
                for qi in q_list_str.split('\n'):
                    q_text = re.sub(r'^\d+[\.\)\]、-]\s*', '', qi).strip()
                    if q_text:
                        cursor.execute("UPDATE master_question_bank SET frequency = frequency - 1 WHERE question = ?", (q_text,))
                
                cursor.execute("DELETE FROM master_question_bank WHERE frequency <= 0")
                
            cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (target_id,))
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics")
async def get_analytics():
    tech_counter, tag_counter, level_counter = Counter(), Counter(), Counter()
    with get_db_connection() as conn:
        for r in conn.execute("SELECT tech_stack FROM jd").fetchall():
            if r['tech_stack']: tech_counter.update([t.strip().lstrip('0123456789. ') for t in r['tech_stack'].split('\n') if t.strip()])
        for r in conn.execute("SELECT tags, diff_tag FROM questions_detail").fetchall():
            if r['tags']: tag_counter.update([t.strip() for t in r['tags'].split(",") if t.strip()])
            if r['diff_tag']: level_counter[r['diff_tag']] += 1
    return {"tech_trends": dict(tech_counter.most_common(10)), "interview_topics": dict(tag_counter.most_common(10)), "popular_tags": dict(tag_counter.most_common(20)), "difficulty_distribution": dict(level_counter)}

@app.post("/api/master-bank/build")
async def build_master_bank():
    with get_db_connection() as conn:
        raw_questions = conn.execute("SELECT * FROM questions_detail").fetchall()
    
    if not raw_questions: return {"status": "error", "detail": "没有数据"}
    texts = [q['question'] for q in raw_questions if q['question'].strip()]
    
    print(f"全量重建: 正在提取 {len(texts)} 道题目特征...")
    embeddings = []
    for i in range(0, len(texts), 100):
        batch_texts = [t.replace("\n", " ") for t in texts[i:i+100]]
        resp = await client.embeddings.create(input=batch_texts, model=EMBEDDING_MODEL)
        embeddings.extend([d.embedding for d in resp.data])

    clusters = []
    for idx, text in enumerate(texts):
        vec = embeddings[idx]
        row = raw_questions[idx]
        
        # 🔥 获取这道题的面经来源信息
        new_source = {"url": row['url'], "company": row['company'], "round": row['round']}
        
        found = False
        for c in clusters:
            if cosine_similarity(vec, c['vector']) >= 0.85:
                c['frequency'] += 1
                if row['cat1']: c['cat1'].add(row['cat1'])
                if row['tags']: 
                    for t in str(row['tags']).split(','):
                        if t.strip(): c['tags'].add(t.strip())
                if row['diff_tag']: c['diffs'].append(row['diff_tag'])
                if len(text) > len(c['question']):
                    c['question'] = text
                    c['vector'] = vec 
                
                # 🔥 追加不重复的来源
                if new_source not in c['sources']:
                    c['sources'].append(new_source)
                    
                found = True
                break
        if not found:
            clusters.append({
                'question': text, 'cat1': {row['cat1']} if row['cat1'] else set(),
                'tags': {t.strip() for t in str(row['tags']).split(',') if t.strip()},
                'diffs': [row['diff_tag']] if row['diff_tag'] else [],
                'frequency': 1, 'vector': vec,
                'sources': [new_source] # 🔥 初始化第一个来源
            })

    with get_db_connection() as conn:
        conn.execute("DELETE FROM master_question_bank")
        for c in clusters:
            diff_str = Counter(c['diffs']).most_common(1)[0][0] if c['diffs'] else "未知"
            conn.execute(
                "INSERT INTO master_question_bank (question, cat1, tags, difficulty, frequency, vector, sources) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (c['question'], ",".join(c['cat1']), ",".join(c['tags']), diff_str, c['frequency'], json.dumps(c['vector']), json.dumps(c['sources']))
            )
        conn.commit()

    return {"status": "success", "total_unique": len(clusters)}

@app.get("/api/master-bank")
async def get_master_bank(sort: str = "frequency_desc"):
    order_clause = "ORDER BY frequency DESC" if sort != "recent" else "ORDER BY id DESC"
    with get_db_connection() as conn:
        # 🔥 取出 sources 字段发给前端
        rows = conn.execute(f"SELECT id, question, cat1, cat2, tags, difficulty, frequency, ai_answer, sources FROM master_question_bank {order_clause}").fetchall()
    
    result = []
    for r in rows:
        d = dict(r)
        # 将 JSON 字符串解板为数组给前端
        try:
            d['sources'] = json.loads(d['sources']) if d['sources'] else []
        except:
            d['sources'] = []
        result.append(d)
        
    return result

@app.post("/api/master-bank/generate-answer/{question_id}")
async def generate_master_answer(question_id: int):
    with get_db_connection() as conn:
        row = conn.execute("SELECT question, ai_answer FROM master_question_bank WHERE id = ?", (question_id,)).fetchone()
    if not row: raise HTTPException(status_code=404)
    if row['ai_answer']: return {"status": "success", "answer": row['ai_answer']}

    response = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "system", "content": "你是一个后端和算法面试指导专家。"}, {"role": "user", "content": ANSWER_PROMPT.replace("{question}", row['question'])}],
        temperature=0.3
    )
    answer = response.choices[0].message.content.strip()
    with get_db_connection() as conn:
        conn.execute("UPDATE master_question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (answer, question_id))
        conn.commit()
    return {"status": "success", "answer": answer}

@app.delete("/api/master-bank/{question_id}")
async def delete_master_question(question_id: int):
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT id FROM master_question_bank WHERE id = ?", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目，可能已被删除")
            conn.execute("DELETE FROM master_question_bank WHERE id = ?", (question_id,))
            conn.commit()
        return {"status": "success", "message": "题目删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")

@app.post("/api/clear-db")
async def clear_db():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jd")
            cursor.execute("DELETE FROM interview")
            cursor.execute("DELETE FROM questions_detail")
            cursor.execute("DELETE FROM master_question_bank")
            cursor.execute("DELETE FROM sqlite_sequence")
            conn.commit()
        return {"status": "success", "message": "已清空所有数据库表"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清空失败: {str(e)}")


@app.post("/api/sync-db")
async def sync_db():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM master_question_bank")
            
            # 🔥 把 url, company, round 一并查出来
            all_details = cursor.execute("SELECT url, company, round, question, cat1, cat2, tags, diff_tag FROM questions_detail").fetchall()
            
            question_map = {}
            for row in all_details:
                q = row['question']
                if not q:
                    continue
                if q not in question_map:
                    question_map[q] = {
                        'cat1': set(),
                        'cat2': set(),
                        'tags': set(),
                        'diffs': [],
                        'frequency': 0,
                        'sources': [] # 🔥 初始化源头集合
                    }
                
                if row['cat1']:
                    question_map[q]['cat1'].add(row['cat1'])
                if row['cat2']:
                    question_map[q]['cat2'].add(row['cat2'])
                if row['tags']:
                    for tag in row['tags'].split(','):
                        if tag.strip():
                            question_map[q]['tags'].add(tag.strip())
                if row['diff_tag']:
                    question_map[q]['diffs'].append(row['diff_tag'])
                
                question_map[q]['frequency'] += 1
                
                # 🔥 收集并去重题目的源头信息
                new_source = {"url": row['url'], "company": row['company'], "round": row['round']}
                if new_source not in question_map[q]['sources']:
                    question_map[q]['sources'].append(new_source)
            
            for q, data in question_map.items():
                diff_str = Counter(data['diffs']).most_common(1)[0][0] if data['diffs'] else "未知"
                cat1_str = ",".join(data['cat1'])
                cat2_str = ",".join(data['cat2'])
                tags_str = ",".join(data['tags'])
                
                cursor.execute(
                    "INSERT INTO master_question_bank (question, cat1, cat2, tags, difficulty, frequency, sources) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (q, cat1_str, cat2_str, tags_str, diff_str, data['frequency'], json.dumps(data['sources']))
                )
            conn.commit()
        return {"status": "success", "message": "数据库同步完成"}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"数据库同步失败: {str(e)}")

@app.post("/api/interview/{interview_id}/re-process")
async def reprocess_interview(interview_id: int, bg_tasks: BackgroundTasks):
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM interview WHERE id = ?", (interview_id,)).fetchone()
        
    if not row:
        raise HTTPException(status_code=404, detail="未找到该面经记录")
        
    questions_str = row['questions_list']
    if not questions_str or not questions_str.strip():
        raise HTTPException(status_code=400, detail="该面经没有具体的题目清单可以分析")
        
    raw_lines = [line.strip() for line in questions_str.split('\n') if line.strip()]
    q_list = []
    for line in raw_lines:
        clean_q = re.sub(r'^\d+[\.\)\]、-]\s*', '', line).strip()
        if clean_q:
            q_list.append(clean_q)
            
    if not q_list:
        raise HTTPException(status_code=400, detail="解析题目清单失败，未能提取到有效题目")

    try:
        url = row['url'] or "未提供链接"
        company = row['company'] or "未提供"
        round_ = row['round'] or "未提供"
        
        tagged_rows = await tag_questions_batch(url, company, round_, q_list)
        
        with get_db_connection() as conn:
            for tr in tagged_rows:
                conn.execute(
                    "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    tuple(tr)
                )
            conn.commit()
        
        await incremental_update_master_bank(tagged_rows, bg_tasks)
        
        return {
            "status": "success", 
            "message": f"成功重新分析了 {len(q_list)} 道题目，并已加入精炼题库！",
            "extracted_count": len(q_list)
        }
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"重新分析失败: {str(e)}")

@app.post("/api/master-bank/re-tag/{question_id}")
async def retag_master_question(question_id: int):
    with get_db_connection() as conn:
        row = conn.execute("SELECT question FROM master_question_bank WHERE id = ?", (question_id,)).fetchone()
        
    if not row or not row['question']:
        raise HTTPException(status_code=404, detail="未找到该题目")
        
    question_text = row['question']
    input_data = [{"id": question_id, "题目": question_text}]
    q_json = json.dumps(input_data, ensure_ascii=False)
    user_msg = TAGGING_PROMPT.replace("{questions}", q_json)
    
    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一个严格输出 JSON 对象的助手，格式必须为 {\"questions\": [...]}。必须输出输入数据中每一项对应的 \"id\" 字段，以便于与原输入一一对应。"},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        
        parsed_result = json.loads(response.choices[0].message.content.strip())
        items = parsed_result.get("questions", [])
        
        if not items:
            raise ValueError("大模型未返回有效的分类数据")
            
        item = items[0]
        cat1 = item.get("一级大类", "未分类")
        cat2 = item.get("二级子类", "未分类")
        tags = item.get("考点标签", "")
        diff = item.get("难度标签", "未知")
        
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE master_question_bank SET cat1 = ?, cat2 = ?, tags = ?, difficulty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (cat1, cat2, tags, diff, question_id)
            )
            
            conn.execute(
                "UPDATE questions_detail SET cat1 = ?, cat2 = ?, tags = ?, diff_tag = ? WHERE question = ?",
                (cat1, cat2, tags, diff, question_text)
            )
            conn.commit()
            
        return {
            "status": "success", 
            "message": "题目重新打标成功", 
            "data": {"cat1": cat1, "cat2": cat2, "tags": tags, "difficulty": diff}
        }
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"重新打标失败: {str(e)}")

from pydantic import BaseModel
from typing import Dict, Any
import re

class GenericUpdateRequest(BaseModel):
    table_name: str
    record_id: int
    update_data: Dict[str, Any]

@app.put("/api/data/update")
async def update_generic_data(req: GenericUpdateRequest):
    allowed_tables = ["master_question_bank", "jd", "interview", "questions_detail"]
    if req.table_name not in allowed_tables:
        raise HTTPException(status_code=400, detail=f"安全拦截：不被允许操作的数据表 '{req.table_name}'")

    if not req.update_data:
        raise HTTPException(status_code=400, detail="更新数据不能为空")

    for col in req.update_data.keys():
        if not re.match(r'^[a-zA-Z0-9_]+$', col):
            raise HTTPException(status_code=400, detail=f"安全拦截：非法的字段名 '{col}'")

    set_clauses = [f"{col} = ?" for col in req.update_data.keys()]
    values = list(req.update_data.values())
    
    if req.table_name == "master_question_bank" and "updated_at" not in req.update_data:
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")

    values.append(req.record_id) 

    sql = f"UPDATE {req.table_name} SET {', '.join(set_clauses)} WHERE id = ?"

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(values))
            
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="未找到对应的记录，可能已被删除")
                
            conn.commit()
            
        return {"status": "success", "message": f"{req.table_name} 表数据更新成功"}
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"数据库更新失败: {str(e)}")