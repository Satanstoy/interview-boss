import os
import json
import base64
import traceback
import sqlite3
import csv
import math
import re
import logging
import tempfile
import asyncio
import time
from typing import List, Optional, Dict, Any
from collections import Counter
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# ─── 日志配置 ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("multimodal-parser")

load_dotenv()

app = FastAPI(title="Multimodal CV & JD Parser")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 请求日志中间件 ───

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录每个请求的方法、路径、状态码、耗时"""
    start = time.time()
    response = await call_next(request)
    elapsed = round((time.time() - start) * 1000, 1)
    level = logging.WARNING if response.status_code >= 400 else logging.INFO
    logger.log(level, "%s %s → %d (%.1fms)", request.method, request.url.path, response.status_code, elapsed)
    return response

# ─── 全局异常处理器 ───

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理的异常，返回统一 JSON 格式"""
    logger.error("未捕获异常: %s %s → %s\n%s", request.method, request.url.path, str(exc), traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": "服务器内部错误，请稍后重试"},
    )

# ─── 健康检查 ───

@app.get("/api/health")
async def health_check():
    """健康检查端点，供 Nginx/负载均衡器探活"""
    try:
        def _ping():
            with get_db_connection() as conn:
                conn.execute("SELECT 1").fetchone()
        await run_db(_ping)
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        raise HTTPException(status_code=503, detail="数据库连接异常")

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
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "0.85"))

DATA_DIR = "/root/sj/multimodal-parser/backend/data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "multimodal.db")

# ─── 数据库初始化 ───

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
        if "sources" not in columns:
            conn.execute("ALTER TABLE master_question_bank ADD COLUMN sources TEXT DEFAULT '[]'")
        if "is_starred" not in columns:
            conn.execute("ALTER TABLE master_question_bank ADD COLUMN is_starred INTEGER DEFAULT 0")
init_db()

def get_db_connection():
    """获取数据库连接，启用 WAL 模式和外键约束，提升并发安全性"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

async def run_db(func):
    """在线程池中执行同步数据库操作，避免阻塞事件循环"""
    return await asyncio.to_thread(func)

# ─── 工具函数 ───

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot_product = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot_product / (mag1 * mag2)

def find_best_match(new_vec: List[float], master_vecs: list) -> tuple:
    """在 master_vecs 中找到与 new_vec 相似度最高的记录，返回 (record, score) 或 (None, 0.0)"""
    best_match = None
    best_score = 0.0
    for m in master_vecs:
        score = cosine_similarity(new_vec, m['vector'])
        if score > best_score:
            best_score = score
            best_match = m
    if best_match and best_score >= SIMILARITY_THRESHOLD:
        return best_match, best_score
    return None, 0.0

def _extract_url_signature(url: str) -> str:
    """从 URL 中提取帖子唯一标识，用于增强去重"""
    if not url:
        return ""
    # 小红书：提取 /explore/ 后面的帖子 ID
    m = re.search(r'/explore/([a-f0-9]+)', url)
    if m:
        return f"xhs:{m.group(1)}"
    # 牛客：提取 discuss/ 后面的数字 ID
    m = re.search(r'/discuss/(\d+)', url)
    if m:
        return f"nc:{m.group(1)}"
    # Boss直聘：提取 job/ 后面的 ID
    m = re.search(r'/job_detail/([^?]+)', url)
    if m:
        return f"boss:{m.group(1)}"
    # 通用：去掉查询参数后的 URL 路径
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return f"generic:{parsed.netloc}{parsed.path}"

def _check_duplicate_url_sync(url: str) -> bool:
    if not url:
        return False
    sig = _extract_url_signature(url)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 先按精确 URL 匹配
        cursor.execute("SELECT 1 FROM jd WHERE url = ?", (url,))
        if cursor.fetchone():
            return True
        cursor.execute("SELECT 1 FROM interview WHERE url = ?", (url,))
        if cursor.fetchone():
            return True
        # 再按 URL 签名匹配（增强去重）
        if sig:
            cursor.execute("SELECT id, url FROM jd")
            for row in cursor.fetchall():
                if _extract_url_signature(row['url']) == sig:
                    return True
            cursor.execute("SELECT id, url FROM interview")
            for row in cursor.fetchall():
                if _extract_url_signature(row['url']) == sig:
                    return True
    return False

def encode_image(file_bytes: bytes) -> str:
    return base64.b64encode(file_bytes).decode('utf-8')

def normalize_category(text: str) -> str:
    """规范化分类名称，去除多余空格，统一格式（如 'A. 项目' → 'A.项目'）"""
    if not text:
        return text
    text = text.strip()
    text = re.sub(r'^([A-Fa-f]\d?)\.\s+', r'\1.', text)
    return text

def format_array_for_csv(data_array: list) -> str:
    if not isinstance(data_array, list) or not data_array:
        return str(data_array) if data_array else "未提供"
    return "\n".join([f"{i+1}. {item}" for i, item in enumerate(data_array)])

# ─── 字段白名单（用于 GenericUpdateRequest 安全校验）───

ALLOWED_UPDATE_COLUMNS = {
    "master_question_bank": {"question", "cat1", "cat2", "tags", "difficulty", "ai_answer", "is_starred"},
    "jd": {"url", "company", "job_title", "salary", "tech_stack", "bonus"},
    "interview": {"url", "company", "round", "focus", "questions_list", "difficulty"},
    "questions_detail": {"url", "company", "round", "question", "cat1", "cat2", "tags", "diff_tag"},
}

# ─── Prompt 模板 ───

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
2. **复杂度**（用口语带出，例如："时间复杂度 O(n)，因为只遍历一遍"）
3. **Python 代码实现**（带关键注释，逻辑直白，不赘述）
4. **易错点/边界提示**（1-2 句，如"注意空数组、int 越界"）

## 场景 B：系统设计/架构/项目经验题（包括分布式、高并发、LLM应用等）
👉 采用务实风格，结合真实落地方案与权衡（Trade-off）。
结构：
1. **直接破题**（一句话亮出你的核心解法）
2. **落地要点**（2-3 个核心执行点，包含技术选型、踩坑、妥协原因）
3. **务实收尾**（1-2 句说明当前方案的局限性或未来优化方向）
风格：必须使用口语化词汇，如"其实我们当时…"、"踩过一个坑…"、"评估下来…"，**严禁**说教或背诵教科书。

## 场景 C：基础原理/理论题（如八股文、协议、数据库原理等）
👉 追求**准、简、直**，但依然口语化。
结构：
1. **核心解释**（一句话大白话讲透概念）
2. **关键细节**（1-2 个记忆锚点，如"三种角色：Proposer, Acceptor, Learner"）
3. **实用场景**（什么时候用、为什么不用别的，带上你的个人经验）
禁止堆砌概念，必须体现出"跟你说人话就能讲明白"的感觉。

## 面试题：
{question}

## 请直接用上述规则生成回答：
"""

# ─── 后台任务 ───

LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE_MB", "10")) * 1024 * 1024  # 默认 10MB

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((Exception,)),
    before_sleep=lambda retry_state: logger.warning(f"LLM 调用失败，第 {retry_state.attempt_number} 次重试: {retry_state.outcome.exception()}")
)
async def _call_llm_with_retry(prompt: str, system_msg: str = "你是一个后端和算法面试指导专家。") -> str:
    """带指数退避重试 + 超时保护的 LLM 调用封装"""
    response = await asyncio.wait_for(
        client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        ),
        timeout=LLM_TIMEOUT
    )
    return response.choices[0].message.content.strip()

async def background_generate_answer(question_id: int, question_text: str):
    try:
        prompt = ANSWER_PROMPT.replace("{question}", question_text)
        answer = await _call_llm_with_retry(prompt)

        def _update():
            with get_db_connection() as conn:
                conn.execute("UPDATE master_question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (answer, question_id))
                conn.commit()

        await run_db(_update)
        logger.info(f"自动解答生成完毕: [ID:{question_id}] {question_text[:30]}...")
    except Exception as e:
        logger.error(f"自动解答生成失败（已重试3次）[ID:{question_id}]: {e}")
        # 标记失败状态，前端可识别并支持手动重试
        def _mark_failed():
            with get_db_connection() as conn:
                conn.execute("UPDATE master_question_bank SET ai_answer = '[生成失败，请手动重试]', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (question_id,))
                conn.commit()
        try:
            await run_db(_mark_failed)
        except Exception:
            pass

async def incremental_update_master_bank(new_tagged_rows: list, bg_tasks: BackgroundTasks):
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
            return conn.execute("SELECT id, question, vector, sources FROM master_question_bank").fetchall()

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

    def _update_db():
        with get_db_connection() as conn:
            cursor = conn.cursor()
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
                        "UPDATE master_question_bank SET frequency = frequency + 1, sources = ? WHERE id = ?",
                        (json.dumps(best_match['sources']), best_match['id'])
                    )
                    best_match['frequency'] = best_match.get('frequency', 1) + 1
                else:
                    sources_json = json.dumps([new_source])
                    cursor.execute(
                        "INSERT INTO master_question_bank (question, cat1, tags, difficulty, vector, sources) VALUES (?, ?, ?, ?, ?, ?)",
                        (q_text, cat1, tags, diff_tag, json.dumps(new_vec), sources_json)
                    )
                    new_id = cursor.lastrowid
                    master_vecs.append({"id": new_id, "question": q_text, "vector": new_vec, "sources": [new_source]})

                    bg_tasks.add_task(background_generate_answer, new_id, q_text)

            conn.commit()

    await run_db(_update_db)


@app.post("/api/submit")
async def submit_data(
    bg_tasks: BackgroundTasks,
    url: Optional[str] = Form(""),
    text: Optional[str] = Form(""),
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

            def _insert_jd():
                with get_db_connection() as conn:
                    conn.execute(
                        "INSERT INTO jd (url, company, job_title, salary, tech_stack, bonus) VALUES (?, ?, ?, ?, ?, ?)",
                        (saved_url, data.get("公司", "未提供"), data.get("岗位名称", "未提供"), data.get("薪资范围", "未提供"), tech_stack, data.get("加分项", "未提供"))
                    )
                    conn.commit()

            await run_db(_insert_jd)
            return {"status": "success", "type": "JD", "saved_data": data}

        elif doc_type == "Interview":
            questions = format_array_for_csv(data.get("具体题目清单", []))

            def _insert_interview():
                with get_db_connection() as conn:
                    conn.execute(
                        "INSERT INTO interview (url, company, round, focus, questions_list, difficulty) VALUES (?, ?, ?, ?, ?, ?)",
                        (saved_url, data.get("公司", "未提供"), data.get("面试轮次", "未提供"), data.get("考察重点", "未提供"), questions, data.get("难易程度", "未提供"))
                    )
                    conn.commit()

            await run_db(_insert_interview)

            q_list = data.get("具体题目清单", [])
            if q_list:
                try:
                    tagged_rows = await tag_questions_batch(saved_url, data.get("公司", "未提供"), data.get("面试轮次", "未提供"), q_list)

                    def _insert_details():
                        with get_db_connection() as conn:
                            for tr in tagged_rows:
                                conn.execute(
                                    "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                    tuple(tr)
                                )
                            conn.commit()

                    await run_db(_insert_details)
                    await incremental_update_master_bank(tagged_rows, bg_tasks)

                except Exception as e:
                    logger.error(f"题目标签化及更新题库失败: {e}")

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
            standardized.append([url, company, round_, q, normalize_category(it["一级大类"]), normalize_category(it["二级子类"]), it["考点标签"], it["难度标签"]])
        else:
            standardized.append([url, company, round_, q, "未分类(API漏标)", "未分类", "", "未知"])
    return standardized

@app.get("/api/data/{file_type}")
async def get_data(file_type: str, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500)):
    table_map = {"jd": "jd", "interview": "interview", "tagged": "questions_detail"}
    table_name = table_map.get(file_type.lower())
    if not table_name:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    offset = (page - 1) * page_size

    def _query():
        with get_db_connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            rows = conn.execute(f"SELECT * FROM {table_name} ORDER BY id ASC LIMIT ? OFFSET ?", (page_size, offset)).fetchall()
            return total, rows

    total, rows = await run_db(_query)

    result = []
    for r in rows:
        d = dict(r)
        if table_name == 'jd':
            result.append({"id": d['id'], "来源链接": d['url'], "公司": d['company'], "岗位名称": d['job_title'], "薪资范围": d['salary'], "核心技术要求": d['tech_stack'], "加分项": d['bonus']})
        elif table_name == 'interview':
            result.append({"id": d['id'], "来源链接": d['url'], "公司": d['company'], "面试轮次": d['round'], "考察重点": d['focus'], "具体题目清单": d['questions_list'], "难易程度": d['difficulty']})
        elif table_name == 'questions_detail':
            result.append({"id": d['id'], "来源链接": d['url'], "公司": d['company'], "面试轮次": d['round'], "题目": d['question'], "一级大类": d['cat1'], "二级子类": d['cat2'], "考点标签": d['tags'], "难度标签": d['diff_tag']})
    return {"items": result, "total": total, "page": page, "page_size": page_size}

@app.get("/api/download/{file_type}")
async def download_csv(file_type: str):
    table_map = {
        "jd": ("jd", ["来源链接", "公司", "岗位名称", "薪资范围", "核心技术要求", "加分项"]),
        "interview": ("interview", ["来源链接", "公司", "面试轮次", "考察重点", "具体题目清单", "难易程度"]),
        "tagged": ("questions_detail", ["来源链接", "公司", "面试轮次", "题目", "一级大类", "二级子类", "考点标签", "难度标签"])
    }
    if file_type not in table_map:
        raise HTTPException(status_code=404, detail="未知文件类型")
    table_name, headers = table_map[file_type]

    # 使用唯一临时文件避免并发冲突
    fd, temp_file_path = tempfile.mkstemp(suffix=".csv", dir=DATA_DIR)
    os.close(fd)

    def _export():
        with get_db_connection() as conn:
            rows = conn.execute(f"SELECT * FROM {table_name} ORDER BY id ASC").fetchall()
        with open(temp_file_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for r in rows:
                d = dict(r)
                if table_name == 'jd':
                    writer.writerow([d['url'], d['company'], d['job_title'], d['salary'], d['tech_stack'], d['bonus']])
                elif table_name == 'interview':
                    writer.writerow([d['url'], d['company'], d['round'], d['focus'], d['questions_list'], d['difficulty']])
                elif table_name == 'questions_detail':
                    writer.writerow([d['url'], d['company'], d['round'], d['question'], d['cat1'], d['cat2'], d['tags'], d['diff_tag']])

    await run_db(_export)
    # 使用 BackgroundTasks 在响应发送后清理临时文件
    bg_cleanup = BackgroundTasks()
    bg_cleanup.add_task(_cleanup_temp_file, temp_file_path)
    return FileResponse(path=temp_file_path, filename=f"{file_type}_data.csv", media_type='text/csv', background=bg_cleanup)

def _cleanup_temp_file(path: str):
    """清理临时文件"""
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        logger.warning(f"清理临时文件失败: {path} → {e}")

@app.delete("/api/data/{file_type}/{record_id}")
async def delete_data(file_type: str, record_id: int):
    """通过 record_id 直接删除记录，避免行号偏移导致删错"""
    table_map = {"jd": "jd", "interview": "interview", "tagged": "questions_detail"}
    table_name = table_map.get(file_type.lower())
    if not table_name:
        raise HTTPException(status_code=400, detail="不支持的表类型")

    def _delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            target_row = cursor.execute(f"SELECT id, url, questions_list FROM {table_name} WHERE id = ?", (record_id,)).fetchone()
            if not target_row:
                raise HTTPException(status_code=404, detail="未找到该记录，可能已被删除")

            if table_name == 'interview':
                url = target_row['url']
                # 通过 sources 字段中的 URL 追溯受影响的 master_bank 记录
                affected_rows = cursor.execute("SELECT id, sources FROM master_question_bank").fetchall()
                for mr in affected_rows:
                    try:
                        sources = json.loads(mr['sources']) if mr['sources'] else []
                    except Exception:
                        sources = []
                    match_count = sum(1 for s in sources if s.get('url') == url)
                    if match_count > 0:
                        new_sources = [s for s in sources if s.get('url') != url]
                        cursor.execute(
                            "UPDATE master_question_bank SET frequency = ?, sources = ? WHERE id = ?",
                            (len(new_sources), json.dumps(new_sources), mr['id'])
                        )

                # 保留有 AI 答案的记录，即使 frequency 降为 0（避免答案丢失）
                cursor.execute(
                    "DELETE FROM master_question_bank WHERE frequency <= 0 AND (ai_answer IS NULL OR ai_answer = '' OR ai_answer = '[生成失败，请手动重试]')"
                )
                cursor.execute("DELETE FROM questions_detail WHERE url = ?", (url,))

            cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (record_id,))
            conn.commit()

    try:
        await run_db(_delete)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics")
async def get_analytics():
    def _query():
        tech_counter, tag_counter, level_counter = Counter(), Counter(), Counter()
        with get_db_connection() as conn:
            for r in conn.execute("SELECT tech_stack FROM jd").fetchall():
                if r['tech_stack']:
                    tech_counter.update([t.strip().lstrip('0123456789. ') for t in r['tech_stack'].split('\n') if t.strip()])
            for r in conn.execute("SELECT tags, diff_tag FROM questions_detail").fetchall():
                if r['tags']:
                    tag_counter.update([t.strip() for t in r['tags'].split(",") if t.strip()])
                if r['diff_tag']:
                    level_counter[r['diff_tag']] += 1
        return dict(tech_counter.most_common(10)), dict(tag_counter.most_common(10)), dict(tag_counter.most_common(20)), dict(level_counter)

    tech, topics, popular, difficulty = await run_db(_query)
    return {"tech_trends": tech, "interview_topics": topics, "popular_tags": popular, "difficulty_distribution": difficulty}

@app.post("/api/master-bank/build")
async def build_master_bank():
    """全量重建题库：保留已有的 AI 答案，使用 Embedding 语义聚类"""
    # 重建前自动备份数据库
    import shutil
    backup_path = f"{DB_PATH}.bak.build.{int(time.time())}"
    try:
        shutil.copy2(DB_PATH, backup_path)
        logger.info(f"全量重建前已创建数据库备份: {backup_path}")
    except Exception as e:
        logger.warning(f"创建备份失败（不影响重建流程）: {e}")

    def _load():
        with get_db_connection() as conn:
            raw = conn.execute("SELECT * FROM questions_detail").fetchall()
            # 保留已有的 ai_answer 及其向量，用于重建后按语义匹配恢复
            existing = conn.execute(
                "SELECT question, ai_answer, vector FROM master_question_bank WHERE ai_answer IS NOT NULL AND ai_answer != ''"
            ).fetchall()
            existing_answers_map = {}
            for r in existing:
                vec = None
                if r['vector']:
                    try:
                        vec = json.loads(r['vector'])
                    except Exception:
                        pass
                existing_answers_map[r['question']] = {
                    "ai_answer": r['ai_answer'],
                    "vector": vec
                }
            return raw, existing_answers_map

    raw_questions, existing_answers_map = await run_db(_load)

    if not raw_questions:
        return {"status": "error", "detail": "没有数据"}
    texts = [q['question'] for q in raw_questions if q['question'].strip()]

    logger.info(f"全量重建: 正在提取 {len(texts)} 道题目特征...")
    embeddings = []
    for i in range(0, len(texts), 100):
        batch_texts = [t.replace("\n", " ") for t in texts[i:i+100]]
        resp = await client_of_embedding.embeddings.create(input=batch_texts, model=EMBEDDING_MODEL)
        embeddings.extend([d.embedding for d in resp.data])

    clusters = []
    for idx, text in enumerate(texts):
        vec = embeddings[idx]
        row = raw_questions[idx]

        new_source = {"url": row['url'], "company": row['company'], "round": row['round']}

        best_cluster = None
        best_score = 0.0
        for c in clusters:
            score = cosine_similarity(vec, c['vector'])
            if score > best_score:
                best_score = score
                best_cluster = c

        if best_cluster and best_score >= SIMILARITY_THRESHOLD:
            best_cluster['frequency'] += 1
            if row['cat1']:
                best_cluster['cat1'].add(normalize_category(row['cat1']))
            if row['tags']:
                for t in str(row['tags']).split(','):
                    if t.strip():
                        best_cluster['tags'].add(t.strip())
            if row['diff_tag']:
                best_cluster['diffs'].append(row['diff_tag'])
            if len(text) > len(best_cluster['question']):
                best_cluster['question'] = text
                best_cluster['vector'] = vec

            if new_source not in best_cluster['sources']:
                best_cluster['sources'].append(new_source)
        else:
            clusters.append({
                'question': text, 'cat1': {normalize_category(row['cat1'])} if row['cat1'] else set(),
                'tags': {t.strip() for t in str(row['tags']).split(',') if t.strip()},
                'diffs': [row['diff_tag']] if row['diff_tag'] else [],
                'frequency': 1, 'vector': vec,
                'sources': [new_source]
            })

    def _save():
        with get_db_connection() as conn:
            conn.execute("DELETE FROM master_question_bank")
            restored_count = 0
            for c in clusters:
                diff_str = Counter(c['diffs']).most_common(1)[0][0] if c['diffs'] else "未知"
                # 多策略匹配保留已有 AI 答案：
                # 1. 精确文本匹配（question 完全一致）
                # 2. 向量语义匹配（余弦相似度 >= 0.95，比聚类阈值更严格，确保是同一道题）
                ai_answer = None
                if c['question'] in existing_answers_map:
                    ai_answer = existing_answers_map[c['question']]['ai_answer']
                else:
                    best_sim = 0.0
                    best_answer = None
                    for old_q, info in existing_answers_map.items():
                        if info['vector'] and c['vector']:
                            sim = cosine_similarity(c['vector'], info['vector'])
                            if sim > best_sim:
                                best_sim = sim
                                best_answer = info['ai_answer']
                    # 使用 0.95 高阈值，确保只恢复真正同一道题的答案
                    if best_sim >= 0.95 and best_answer:
                        ai_answer = best_answer
                        restored_count += 1
                        logger.info(f"通过向量匹配恢复答案 (sim={best_sim:.4f}): {c['question'][:40]}...")

                conn.execute(
                    "INSERT INTO master_question_bank (question, cat1, tags, difficulty, frequency, vector, sources, ai_answer) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (c['question'], ",".join(c['cat1']), ",".join(c['tags']), diff_str, c['frequency'], json.dumps(c['vector']), json.dumps(c['sources']), ai_answer)
                )
            conn.commit()
            logger.info(f"答案恢复统计: 精确匹配 {len(clusters) - restored_count} 条, 向量匹配恢复 {restored_count} 条")

    await run_db(_save)
    logger.info(f"全量重建完成: {len(clusters)} 道核心真题")
    return {"status": "success", "total_unique": len(clusters)}

@app.get("/api/master-bank")
async def get_master_bank(sort: str = "frequency_desc", page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=1000)):
    order_clause = "ORDER BY frequency DESC" if sort != "recent" else "ORDER BY id DESC"
    offset = (page - 1) * page_size

    def _query():
        with get_db_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM master_question_bank").fetchone()[0]
            rows = conn.execute(f"SELECT id, question, cat1, cat2, tags, difficulty, frequency, ai_answer, sources, is_starred FROM master_question_bank {order_clause} LIMIT ? OFFSET ?", (page_size, offset)).fetchall()
            return total, rows

    total, rows = await run_db(_query)

    result = []
    for r in rows:
        d = dict(r)
        try:
            d['sources'] = json.loads(d['sources']) if d['sources'] else []
        except Exception:
            d['sources'] = []
        result.append(d)

    return {"items": result, "total": total, "page": page, "page_size": page_size}

@app.post("/api/master-bank/toggle-star/{question_id}")
async def toggle_star(question_id: int):
    """切换题目收藏状态"""
    def _toggle():
        with get_db_connection() as conn:
            row = conn.execute("SELECT is_starred FROM master_question_bank WHERE id = ?", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目")
            new_val = 0 if row['is_starred'] else 1
            conn.execute("UPDATE master_question_bank SET is_starred = ? WHERE id = ?", (new_val, question_id))
            conn.commit()
            return new_val

    try:
        new_val = await run_db(_toggle)
        return {"status": "success", "is_starred": bool(new_val)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/master-bank/generate-answer/{question_id}")
async def generate_master_answer(question_id: int):
    def _get():
        with get_db_connection() as conn:
            return conn.execute("SELECT question, ai_answer FROM master_question_bank WHERE id = ?", (question_id,)).fetchone()

    row = await run_db(_get)
    if not row:
        raise HTTPException(status_code=404)
    # 如果已有有效答案（非失败标记），直接返回
    if row['ai_answer'] and '生成失败' not in row['ai_answer']:
        return {"status": "success", "answer": row['ai_answer']}

    try:
        prompt = ANSWER_PROMPT.replace("{question}", row['question'])
        answer = await _call_llm_with_retry(prompt)

        def _update():
            with get_db_connection() as conn:
                conn.execute("UPDATE master_question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (answer, question_id))
                conn.commit()

        await run_db(_update)
        return {"status": "success", "answer": answer}
    except Exception as e:
        logger.error(f"手动生成答案失败（已重试3次）[ID:{question_id}]: {e}")
        raise HTTPException(status_code=500, detail="生成答案失败，请稍后重试")

@app.delete("/api/master-bank/{question_id}")
async def delete_master_question(question_id: int):
    def _delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT id, question, sources FROM master_question_bank WHERE id = ?", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目，可能已被删除")

            # 联动清理 questions_detail 中对应的记录
            question_text = row['question']
            if question_text:
                cursor.execute("DELETE FROM questions_detail WHERE question = ?", (question_text,))

            cursor.execute("DELETE FROM master_question_bank WHERE id = ?", (question_id,))
            conn.commit()

    try:
        await run_db(_delete)
        return {"status": "success", "message": "题目删除成功（已联动清理 questions_detail）"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")

@app.post("/api/clear-db")
async def clear_db():
    """清空所有数据库表（执行前自动创建备份）"""
    import shutil
    backup_path = f"{DB_PATH}.bak.{int(time.time())}"
    try:
        shutil.copy2(DB_PATH, backup_path)
        logger.info(f"清空前已创建数据库备份: {backup_path}")
    except Exception as e:
        logger.error(f"创建备份失败，拒绝清空操作: {e}")
        raise HTTPException(status_code=500, detail=f"备份创建失败，清空操作已中止: {str(e)}")

    def _clear():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jd")
            cursor.execute("DELETE FROM interview")
            cursor.execute("DELETE FROM questions_detail")
            cursor.execute("DELETE FROM master_question_bank")
            cursor.execute("DELETE FROM sqlite_sequence")
            conn.commit()

    try:
        await run_db(_clear)
        return {"status": "success", "message": f"已清空所有数据库表（备份已保存至 {os.path.basename(backup_path)}）"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清空失败: {str(e)}")

@app.post("/api/sync-db")
async def sync_db():
    """使用 Embedding 语义聚类重建题库（与 build_master_bank 逻辑一致）"""
    try:
        # 复用 build_master_bank 的逻辑
        result = await build_master_bank()
        return {"status": "success", "message": f"数据库同步完成，共 {result.get('total_unique', 0)} 道核心真题"}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"数据库同步失败: {str(e)}")

@app.post("/api/interview/{interview_id}/re-process")
async def reprocess_interview(interview_id: int, bg_tasks: BackgroundTasks):
    def _load():
        with get_db_connection() as conn:
            return conn.execute("SELECT * FROM interview WHERE id = ?", (interview_id,)).fetchone()

    row = await run_db(_load)

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

        # 先清理 master_bank 中该面经的旧来源（与 delete_data 逻辑一致）
        def _cleanup_old_sources():
            with get_db_connection() as conn:
                cursor = conn.cursor()
                affected_rows = cursor.execute("SELECT id, sources FROM master_question_bank").fetchall()
                for mr in affected_rows:
                    try:
                        sources = json.loads(mr['sources']) if mr['sources'] else []
                    except Exception:
                        sources = []
                    match_count = sum(1 for s in sources if s.get('url') == url)
                    if match_count > 0:
                        new_sources = [s for s in sources if s.get('url') != url]
                        cursor.execute(
                            "UPDATE master_question_bank SET frequency = ?, sources = ? WHERE id = ?",
                            (len(new_sources), json.dumps(new_sources), mr['id'])
                        )
                # 保留有 AI 答案的记录，即使 frequency 降为 0（避免答案丢失）
                cursor.execute(
                    "DELETE FROM master_question_bank WHERE frequency <= 0 AND (ai_answer IS NULL OR ai_answer = '' OR ai_answer = '[生成失败，请手动重试]')"
                )
                conn.commit()

        await run_db(_cleanup_old_sources)

        tagged_rows = await tag_questions_batch(url, company, round_, q_list)

        def _replace_details():
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # 先删除该面经对应的旧 questions_detail 记录，避免重复
                cursor.execute("DELETE FROM questions_detail WHERE url = ?", (url,))
                for tr in tagged_rows:
                    cursor.execute(
                        "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        tuple(tr)
                    )
                conn.commit()

        await run_db(_replace_details)
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
    def _get():
        with get_db_connection() as conn:
            return conn.execute("SELECT question, cat1, cat2, tags, difficulty FROM master_question_bank WHERE id = ?", (question_id,)).fetchone()

    row = await run_db(_get)

    if not row or not row['question']:
        raise HTTPException(status_code=404, detail="未找到该题目")

    question_text = row['question']
    current_cat1 = row['cat1'] or '未分类'
    current_cat2 = row['cat2'] or '未分类'
    current_tags = row['tags'] or ''
    current_diff = row['difficulty'] or '未知'

    # 在 prompt 中告知当前分类，要求 LLM 重新审视并给出更准确的分类
    input_data = [{"id": question_id, "题目": question_text}]
    q_json = json.dumps(input_data, ensure_ascii=False)
    user_msg = TAGGING_PROMPT.replace("{questions}", q_json)
    user_msg += f"""

## ⚠️ 重要：重新审视请求
该题目当前的分类结果如下，请仔细重新审视是否准确：
- 当前一级大类：{current_cat1}
- 当前二级子类：{current_cat2}
- 当前考点标签：{current_tags}
- 当前难度：{current_diff}

如果当前分类不准确，请给出更合适的分类。如果当前分类已经准确，请保持不变。
请特别注意：
1. 一级大类和二级子类必须严格匹配（如选了A则二级必须是A1-A4）
2. 考点标签应选择与题目内容最直接相关的技术领域
3. 难度应根据题目实际考察深度判断
"""
    
    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一个严格输出 JSON 对象的助手，格式必须为 {\"questions\": [...]}。必须输出输入数据中每一项对应的 \"id\" 字段，以便于与原输入一一对应。请仔细分析题目内容，给出最准确的分类。"},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )

        parsed_result = json.loads(response.choices[0].message.content.strip())
        items = parsed_result.get("questions", [])

        if not items:
            raise ValueError("大模型未返回有效的分类数据")

        item = items[0]
        cat1 = normalize_category(item.get("一级大类", "未分类"))
        cat2 = normalize_category(item.get("二级子类", "未分类"))
        tags = item.get("考点标签", "")
        diff = item.get("难度标签", "未知")

        def _update():
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

        await run_db(_update)

        return {
            "status": "success",
            "message": "题目重新打标成功",
            "data": {"cat1": cat1, "cat2": cat2, "tags": tags, "difficulty": diff}
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"重新打标失败: {str(e)}")

@app.get("/api/master-bank/random")
async def get_random_questions(
    count: int = Query(5, ge=1, le=20),
    cat1: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None)
):
    """随机抽题接口，支持按分类和难度筛选"""
    def _query():
        with get_db_connection() as conn:
            conditions = []
            params = []
            if cat1:
                conditions.append("cat1 LIKE ?")
                params.append(f"%{cat1}%")
            if difficulty:
                conditions.append("difficulty LIKE ?")
                params.append(f"%{difficulty}%")

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = conn.execute(
                f"SELECT id, question, cat1, cat2, tags, difficulty, frequency, ai_answer, sources FROM master_question_bank {where_clause} ORDER BY RANDOM() LIMIT ?",
                params + [count]
            ).fetchall()
            return rows

    rows = await run_db(_query)
    result = []
    for r in rows:
        d = dict(r)
        try:
            d['sources'] = json.loads(d['sources']) if d['sources'] else []
        except Exception:
            d['sources'] = []
        result.append(d)
    return result

@app.post("/api/normalize-categories")
async def normalize_categories():
    """批量规范化现有数据库中 cat1/cat2 字段的格式（去除多余空格）"""
    def _normalize():
        updated_detail = 0
        updated_master = 0
        with get_db_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT id, cat1, cat2 FROM questions_detail").fetchall()
            for r in rows:
                new_cat1 = normalize_category(r['cat1'])
                new_cat2 = normalize_category(r['cat2'])
                if new_cat1 != r['cat1'] or new_cat2 != r['cat2']:
                    cursor.execute("UPDATE questions_detail SET cat1 = ?, cat2 = ? WHERE id = ?", (new_cat1, new_cat2, r['id']))
                    updated_detail += 1
            rows = cursor.execute("SELECT id, cat1, cat2 FROM master_question_bank").fetchall()
            for r in rows:
                new_cat1 = normalize_category(r['cat1'])
                new_cat2 = normalize_category(r['cat2'])
                if new_cat1 != r['cat1'] or new_cat2 != r['cat2']:
                    cursor.execute("UPDATE master_question_bank SET cat1 = ?, cat2 = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_cat1, new_cat2, r['id']))
                    updated_master += 1
            conn.commit()
        return updated_detail, updated_master

    try:
        detail_count, master_count = await run_db(_normalize)
        return {"status": "success", "message": f"规范化完成：questions_detail 更新 {detail_count} 条，master_question_bank 更新 {master_count} 条"}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"规范化失败: {str(e)}")

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

    # 白名单校验：只允许更新指定字段
    allowed_cols = ALLOWED_UPDATE_COLUMNS.get(req.table_name, set())
    for col in req.update_data.keys():
        if col not in allowed_cols:
            raise HTTPException(status_code=400, detail=f"安全拦截：不允许更新字段 '{col}'，允许的字段: {allowed_cols}")

    # 防止通过通用更新接口意外清空 ai_answer
    if req.table_name == "master_question_bank" and "ai_answer" in req.update_data:
        new_val = req.update_data["ai_answer"]
        if not new_val or (isinstance(new_val, str) and not new_val.strip()):
            raise HTTPException(status_code=400, detail="不允许将 ai_answer 设置为空值，请使用 /api/master-bank/generate-answer 接口重新生成答案")

    set_clauses = [f"{col} = ?" for col in req.update_data.keys()]
    values = list(req.update_data.values())

    if req.table_name == "master_question_bank" and "updated_at" not in req.update_data:
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")

    values.append(req.record_id)

    sql = f"UPDATE {req.table_name} SET {', '.join(set_clauses)} WHERE id = ?"

    def _update():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(values))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="未找到对应的记录，可能已被删除")
            conn.commit()

    try:
        await run_db(_update)
        return {"status": "success", "message": f"{req.table_name} 表数据更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"数据库更新失败: {str(e)}")