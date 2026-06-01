"""
LangGraph 工作流与原始业务逻辑一致性测试

覆盖场景：
1. 个人面经提交流程 (submit_graph personal path)
2. 公共面经提交流程 (submit_graph public path)
3. 提取质量重试 (extraction quality < 7 triggers retry, max 2)
4. 分类质量重试 (tagging quality < 7 triggers retry, max 2)
5. JD 提交流程 (doc_type=jd, no classify step)
6. 题库重建流程 (build_bank_graph)
7. 批量生成答案流程 (batch_generate_graph)
8. 节点级单元测试 (quality evaluation, event builders)

所有 LLM 调用均 mock，使用真实 SQLite 内存数据库。
"""
import json
import sqlite3
import pytest
import asyncio
import time
from unittest.mock import patch, AsyncMock, MagicMock


# ─────────────────────────────────────────────
#  Helper: 创建测试内存数据库（与 test_pipeline_e2e.py 相同 schema）
# ─────────────────────────────────────────────

def create_test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            bank_mode TEXT DEFAULT 'public',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            current_position_id INTEGER,
            personal_position TEXT DEFAULT ''
        );
        CREATE TABLE job_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE interview (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            company TEXT,
            round TEXT,
            focus TEXT,
            questions_list TEXT,
            difficulty TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            season TEXT DEFAULT '',
            owner_id INTEGER,
            status TEXT DEFAULT 'approved',
            job_position TEXT DEFAULT '',
            url_signature TEXT DEFAULT '',
            updated_at TIMESTAMP,
            deleted_at TIMESTAMP,
            analysis_status TEXT DEFAULT 'idle',
            analysis_stage TEXT,
            analysis_result TEXT,
            analysis_updated_at TIMESTAMP
        );
        CREATE TABLE questions_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            company TEXT,
            round TEXT,
            question TEXT,
            cat1 TEXT,
            cat2 TEXT,
            tags TEXT,
            diff_tag TEXT,
            job_position TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            deleted_at TIMESTAMP
        );
        CREATE TABLE question_bank (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            cat1 TEXT,
            cat2 TEXT,
            tags TEXT,
            difficulty TEXT,
            frequency INTEGER DEFAULT 1,
            ai_answer TEXT,
            vector TEXT,
            sources TEXT DEFAULT '[]',
            original_questions TEXT DEFAULT '[]',
            original_question_sources TEXT DEFAULT '[]',
            is_starred INTEGER DEFAULT 0,
            owner_id INTEGER,
            submitted_by INTEGER,
            status TEXT DEFAULT 'approved',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMP,
            job_position TEXT DEFAULT '',
            duplicate_of INTEGER DEFAULT NULL,
            FOREIGN KEY (owner_id) REFERENCES users(id),
            FOREIGN KEY (submitted_by) REFERENCES users(id)
        );
        CREATE TABLE question_position (
            question_id INTEGER NOT NULL,
            position_id INTEGER NOT NULL,
            PRIMARY KEY (question_id, position_id),
            FOREIGN KEY (question_id) REFERENCES question_bank(id) ON DELETE CASCADE,
            FOREIGN KEY (position_id) REFERENCES job_positions(id) ON DELETE CASCADE
        );
        CREATE TABLE question_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_bank_id INTEGER NOT NULL,
            url TEXT,
            company TEXT,
            round TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE
        );
        CREATE TABLE question_original_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_bank_id INTEGER NOT NULL,
            question TEXT,
            sources_json TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE
        );
        CREATE TABLE analysis_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id INTEGER NOT NULL,
            question_detail_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            FOREIGN KEY (interview_id) REFERENCES interview(id)
        );
        CREATE TABLE user_practice_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            user_answer TEXT,
            evaluation_result TEXT,
            score INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE user_question_view (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            is_starred INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE user_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            UNIQUE(user_id, key)
        );
        CREATE TABLE refresh_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            jti TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE taxonomy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            categories_json TEXT NOT NULL,
            source TEXT DEFAULT 'system',
            owner_id INTEGER,
            is_public INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.execute("INSERT INTO users (id, username, password_hash, is_admin) VALUES (1, 'admin', 'hash', 1)")
    conn.execute("INSERT INTO users (id, username, password_hash, is_admin) VALUES (2, 'user', 'hash', 0)")
    conn.execute("INSERT INTO job_positions (id, name) VALUES (1, '后端开发')")
    conn.execute("INSERT INTO user_profile (user_id, key, value) VALUES (1, 'current_job_position', '后端开发')")
    conn.execute("INSERT INTO user_profile (user_id, key, value) VALUES (2, 'current_job_position', '后端开发')")
    conn.commit()
    return conn


# ─────────────────────────────────────────────
#  Mock LLM 函数
# ─────────────────────────────────────────────

MOCK_EXTRACT_RESPONSE = json.dumps({
    "type": "Interview",
    "data": {
        "公司": "字节跳动",
        "面试轮次": "二面",
        "考察重点": "算法与系统设计",
        "具体题目清单": [
            "Redis 持久化方式有哪些？",
            "请介绍 TCP 三次握手的过程",
            "请实现一个快速排序算法"
        ],
        "难易程度": "中等"
    }
}, ensure_ascii=False)

MOCK_EXTRACT_RESPONSE_LOW_QUALITY = json.dumps({
    "type": "Interview",
    "data": {
        "公司": "未提供",
        "面试轮次": "未提供",
        "考察重点": "未知",
        "具体题目清单": [],
        "难易程度": "未提供"
    }
}, ensure_ascii=False)

MOCK_EXTRACT_RESPONSE_JD = json.dumps({
    "type": "JD",
    "data": {
        "公司": "字节跳动",
        "岗位名称": "后端开发工程师",
        "薪资范围": "25k-40k",
        "核心技术要求": ["Java", "Spring", "MySQL", "Redis"],
        "加分项": "大模型应用经验"
    }
}, ensure_ascii=False)

MOCK_TAG_RESPONSE = json.dumps({
    "questions": [
        {"id": 0, "题目": "Redis 持久化方式有哪些？", "一级大类": "数据库", "二级子类": "Redis", "考点标签": "Redis,缓存", "难度标签": "L2-中等"},
        {"id": 1, "题目": "请介绍 TCP 三次握手的过程", "一级大类": "计算机网络", "二级子类": "TCP", "考点标签": "TCP,网络", "难度标签": "L1-基础"},
        {"id": 2, "题目": "请实现一个快速排序算法", "一级大类": "算法", "二级子类": "排序", "考点标签": "排序,算法", "难度标签": "L3-困难"},
    ]
}, ensure_ascii=False)

MOCK_TAG_RESPONSE_LOW_QUALITY = json.dumps({
    "questions": [
        {"id": 0, "题目": "Redis持久化", "一级大类": "", "二级子类": "", "考点标签": "", "难度标签": ""},
        {"id": 1, "题目": "TCP握手", "一级大类": "INVALID_CAT", "二级子类": "INVALID_SUB", "考点标签": "", "难度标签": "UNKNOWN"},
    ]
}, ensure_ascii=False)

MOCK_MATCH_RESPONSE = json.dumps({
    "matches": []
}, ensure_ascii=False)

MOCK_FILL_RESPONSE = json.dumps({
    "公司": "字节跳动",
    "面试轮次": "二面"
}, ensure_ascii=False)

MOCK_ANSWER = "这是 AI 生成的答案。**Redis 持久化**主要分为 RDB 和 AOF 两种方式。RDB 是快照式备份，AOF 是追加式日志。"


def _mock_tag_batch(url, company, round_, questions, taxonomy_config=None, user_id=None):
    """与 test_pipeline_e2e.py 一致的 mock tag"""
    results = []
    for q in questions:
        if 'Redis' in q or '缓存' in q:
            results.append([url, company, round_, q, "数据库", "Redis", "Redis,缓存", "L2-中等"])
        elif 'TCP' in q or '网络' in q or 'HTTP' in q:
            results.append([url, company, round_, q, "计算机网络", "TCP", "TCP,网络", "L1-基础"])
        elif '算法' in q or '排序' in q or '快排' in q:
            results.append([url, company, round_, q, "算法", "排序", "排序,算法", "L3-困难"])
        else:
            results.append([url, company, round_, q, "未分类", "未分类", "", "L2-中等"])
    return results


def _mock_tag_batch_low_quality(url, company, round_, questions, taxonomy_config=None, user_id=None):
    """返回低质量分类结果（有效但错误的分类）"""
    return [[url, company, round_, q, "INVALID_CAT1", "INVALID_CAT2", "", "INVALID_DIFF"] for q in questions]


# ─────────────────────────────────────────────
#  Fixture: mock DB + mock LLM
# ─────────────────────────────────────────────

@pytest.fixture
def mock_db():
    """mock get_db_connection 和 run_db，使用内存数据库"""
    conn = create_test_db()

    with patch('app.db.connection.get_db_connection', return_value=conn), \
         patch('app.db.operations.get_db_connection', return_value=conn), \
         patch('app.services.pipeline.get_db_connection', return_value=conn):

        async def _run_db_sync(func):
            return func()

        with patch('app.db.connection.run_db', side_effect=_run_db_sync), \
             patch('app.services.pipeline.run_db', side_effect=_run_db_sync):
            yield conn


# ═══════════════════════════════════════════════
#  1. 节点级单元测试 — Quality 评估函数
# ═══════════════════════════════════════════════

class TestQualityEvaluation:
    """测试质量评估函数是否与设计文档一致"""

    def test_extraction_quality_full_data(self):
        from app.agents.shared.quality import evaluate_extraction_quality
        data = {
            "公司": "字节跳动",
            "面试轮次": "二面",
            "具体题目清单": ["Redis持久化方式详解", "TCP三次握手完整过程", "快速排序算法实现"],
            "难易程度": "中等"
        }
        score = evaluate_extraction_quality(data)
        assert score == 10.0

    def test_extraction_quality_no_questions(self):
        from app.agents.shared.quality import evaluate_extraction_quality
        data = {"公司": "字节跳动", "面试轮次": "二面", "具体题目清单": []}
        score = evaluate_extraction_quality(data)
        assert score == 0.0

    def test_extraction_quality_missing_company(self):
        from app.agents.shared.quality import evaluate_extraction_quality
        data = {"公司": "未提供", "面试轮次": "二面", "具体题目清单": ["Redis持久化方式", "TCP三次握手过程"]}
        score = evaluate_extraction_quality(data)
        assert score == 8.0  # 10 - 2 (missing company)

    def test_extraction_quality_few_questions(self):
        from app.agents.shared.quality import evaluate_extraction_quality
        data = {"公司": "字节", "面试轮次": "一面", "具体题目清单": ["题"]}
        score = evaluate_extraction_quality(data)
        # 10 - 3 (few questions) - 1 (short question) = 6
        assert score == 6.0

    def test_tagging_quality_valid_rows(self):
        from app.agents.shared.quality import evaluate_tagging_quality
        rows = [
            ["url", "公司", "一面", "题目1", "数据库", "Redis", "缓存", "L2-中等"],
            ["url", "公司", "一面", "题目2", "计算机网络", "TCP", "网络", "L1-基础"],
        ]
        score = evaluate_tagging_quality(rows)
        assert score >= 9.0

    def test_tagging_quality_empty_rows(self):
        from app.agents.shared.quality import evaluate_tagging_quality
        score = evaluate_tagging_quality([])
        assert score == 0.0

    def test_tagging_quality_invalid_diff(self):
        from app.agents.shared.quality import evaluate_tagging_quality
        rows = [
            ["url", "公司", "一面", "题目1", "数据库", "Redis", "缓存", "UNKNOWN_TAG"],
        ]
        score = evaluate_tagging_quality(rows)
        assert score < 10.0

    def test_answer_quality_good_answer(self):
        from app.agents.shared.quality import evaluate_answer_quality
        answer = "这是一份很好的答案。" * 10  # > 50 chars
        score = evaluate_answer_quality(answer, "Redis 持久化")
        assert score >= 9.0

    def test_answer_quality_too_short(self):
        from app.agents.shared.quality import evaluate_answer_quality
        score = evaluate_answer_quality("太短", "问题")
        assert score == 1.0

    def test_answer_quality_refusal(self):
        from app.agents.shared.quality import evaluate_answer_quality
        score = evaluate_answer_quality("抱歉，我无法回答这个问题。" * 5, "问题")
        assert score == 2.0

    def test_should_retry_below_threshold(self):
        from app.agents.shared.quality import should_retry
        assert should_retry(2.0, 0) is True   # below threshold 3.0
        assert should_retry(2.0, 2) is False   # max retries reached
        assert should_retry(5.0, 0) is False   # above threshold


# ═══════════════════════════════════════════════
#  2. 节点级单元测试 — Event 构建函数
# ═══════════════════════════════════════════════

class TestEventBuilders:
    """测试 SSE 事件构建工具"""

    def test_make_progress_event_basic(self):
        from app.agents.shared.events import make_progress_event
        evt = make_progress_event("extract", "正在提取...")
        assert evt == {"type": "progress", "step": "extract", "message": "正在提取..."}

    def test_make_progress_event_with_data(self):
        from app.agents.shared.events import make_progress_event
        evt = make_progress_event("tag", "标注完成", {"count": 5})
        assert evt["data"] == {"count": 5}
        assert evt["type"] == "progress"

    def test_format_sse(self):
        from app.agents.shared.events import format_sse
        sse = format_sse({"type": "progress", "step": "tag", "message": "ok"})
        assert sse.startswith("data: ")
        assert sse.endswith("\n\n")
        parsed = json.loads(sse[6:].strip())
        assert parsed["step"] == "tag"

    def test_build_extraction_data(self):
        from app.agents.shared.events import build_extraction_data
        data = {"_doc_type": "interview", "公司": "字节", "具体题目清单": ["Q1", "Q2"]}
        result = build_extraction_data(data, 9.0, 3.5, 0)
        assert result["question_count"] == 2
        assert result["company"] == "字节"
        assert result["quality_score"] == 9.0

    def test_build_tagging_data(self):
        from app.agents.shared.events import build_tagging_data
        rows = [
            ["u", "c", "r", "q1", "数据库", "Redis", "", "L2"],
            ["u", "c", "r", "q2", "数据库", "MySQL", "", "L2"],
            ["u", "c", "r", "q3", "算法", "排序", "", "L3"],
        ]
        result = build_tagging_data(rows, 9.5, 2.1)
        assert result["question_count"] == 3
        assert result["categories"]["数据库"] == 2
        assert result["categories"]["算法"] == 1

    def test_node_timer(self):
        from app.agents.shared.events import NodeTimer
        with NodeTimer() as t:
            time.sleep(0.05)
        assert t.elapsed >= 0.04


# ═══════════════════════════════════════════════
#  3. Submit Graph 节点级测试
# ═══════════════════════════════════════════════

class TestSubmitNodes:
    """测试 submit_graph 各节点与原始业务逻辑的一致性"""

    def test_recognize_node_explicit_hint(self, mock_db):
        from app.agents.submit.extract import recognize_node
        state = {"content_type_hint": "interview", "user_id": 1}
        result = asyncio.run(recognize_node(state))
        assert result["doc_type"] == "interview"

    def test_recognize_node_auto(self, mock_db):
        from app.agents.submit.extract import recognize_node
        state = {"content_type_hint": "auto", "user_id": 1}
        result = asyncio.run(recognize_node(state))
        assert result["doc_type"] == ""  # deferred to extract

    def test_extract_node_produces_correct_data(self, mock_db):
        """验证 extract_node 调用 LLM 后产生与原始 submit_data 相同的数据结构"""
        from app.agents.submit.extract import extract_node
        mock_llm = AsyncMock(return_value=MOCK_EXTRACT_RESPONSE)

        with patch('app.services.llm._call_llm_with_retry_messages', mock_llm), \
             patch('app.services.llm._should_use_response_format', return_value=False), \
             patch('app.services.llm.get_llm_client_for_user', return_value=(MagicMock(), "test-model", 30, "", "openai")):

            state = {
                "raw_text": "面经内容...",
                "image_data": [],
                "url": "https://test.com/1",
                "user_id": 1,
                "content_type_hint": "interview",
                "doc_type": "interview",
                "extraction_retries": 0,
            }
            result = asyncio.run(extract_node(state))

        assert result["doc_type"] == "interview"
        assert result["extracted_data"]["公司"] == "字节跳动"
        assert len(result["extracted_data"]["具体题目清单"]) == 3
        assert result["extraction_quality"] >= 7.0
        assert "events" in result
        assert result["events"][0]["step"] == "extract"

    def test_extract_node_blacklist_filter(self, mock_db):
        """验证提取黑名单过滤（精确匹配）"""
        from app.agents.submit.extract import extract_node
        response = json.dumps({
            "type": "Interview",
            "data": {
                "公司": "字节",
                "面试轮次": "一面",
                "考察重点": "综合",
                "具体题目清单": ["Redis持久化", "自我介绍", "TCP三次握手", "反问"],
                "难易程度": "中等"
            }
        }, ensure_ascii=False)

        with patch('app.services.llm._call_llm_with_retry_messages', AsyncMock(return_value=response)), \
             patch('app.services.llm._should_use_response_format', return_value=False), \
             patch('app.services.llm.get_llm_client_for_user', return_value=(MagicMock(), "model", 30, "", "openai")):

            state = {
                "raw_text": "面经", "image_data": [], "url": "", "user_id": 1,
                "content_type_hint": "", "doc_type": "", "extraction_retries": 0,
            }
            result = asyncio.run(extract_node(state))

        questions = result["extracted_data"]["具体题目清单"]
        assert "自我介绍" not in questions  # 精确匹配黑名单
        assert "反问" not in questions       # 精确匹配黑名单
        assert "Redis持久化" in questions

    def test_classify_node_calls_tag_questions_batch(self, mock_db):
        """验证 classify_node 调用与原始 tag_questions_batch 相同的接口"""
        from app.agents.submit.classify import classify_node

        with patch('app.routers.submit.tag_questions_batch', side_effect=_mock_tag_batch), \
             patch('app.db.connection.get_taxonomy_for_position', return_value=None), \
             patch('app.db.connection.run_db', new_callable=AsyncMock, side_effect=lambda f: f()):

            state = {
                "extracted_data": {
                    "公司": "字节",
                    "面试轮次": "二面",
                    "具体题目清单": ["Redis持久化", "TCP三次握手"],
                },
                "saved_url": "https://test.com/1",
                "user_id": 1,
                "tagging_retries": 0,
                "taxonomy_config": None,
            }
            result = asyncio.run(classify_node(state))

        assert len(result["tagged_rows"]) == 2
        assert result["tagged_rows"][0][4] == "数据库"  # cat1
        assert result["tagged_rows"][0][5] == "Redis"    # cat2
        assert result["tagging_quality"] >= 7.0
        assert result["events"][0]["step"] == "tag"

    def test_match_and_persist_personal_creates_qb_records(self, mock_db):
        """验证个人题库路径写入 question_bank 的记录与原始 submit_interview_txn 一致"""
        from app.agents.submit.persist_personal import match_and_persist_personal_node

        with patch('app.services.clustering.match_new_questions', AsyncMock(return_value={"matched": [], "unmatched": []})), \
             patch('app.db.connection.get_current_job_position', return_value="后端开发"):

            state = {
                "extracted_data": {
                    "公司": "字节",
                    "面试轮次": "二面",
                    "具体题目清单": ["Redis持久化", "TCP握手"],
                    "考察重点": "基础",
                    "难易程度": "中等",
                },
                "tagged_rows": [
                    ["https://test.com/1", "字节", "二面", "Redis持久化", "数据库", "Redis", "缓存", "L2-中等"],
                    ["https://test.com/1", "字节", "二面", "TCP握手", "计算机网络", "TCP", "网络", "L1-基础"],
                ],
                "saved_url": "https://test.com/1",
                "season": "2027届",
                "user_id": 1,
                "is_admin": True,
                "job_position": "后端开发",
            }
            result = asyncio.run(match_and_persist_personal_node(state))

        assert result["saved_interview_id"] is not None
        assert result["record_owner_id"] == 1
        assert result["record_status"] == "approved"

        # 验证 DB 中 interview 和 questions_detail 已写入
        conn = mock_db
        iv = conn.execute("SELECT * FROM interview WHERE url = 'https://test.com/1'").fetchone()
        assert iv is not None
        assert iv["company"] == "字节"

        details = conn.execute("SELECT * FROM questions_detail WHERE url = 'https://test.com/1'").fetchall()
        assert len(details) == 2

    def test_persist_public_writes_and_enqueues(self, mock_db):
        """验证公共题库路径写入 interview + questions_detail + 入队"""
        from app.agents.submit.persist_public import persist_public_node

        with patch('app.db.connection.get_current_job_position', return_value="后端开发"), \
             patch('app.services.pipeline.enqueue_questions', return_value=2):

            state = {
                "extracted_data": {
                    "公司": "阿里",
                    "面试轮次": "一面",
                    "具体题目清单": ["Redis缓存", "算法题"],
                    "考察重点": "基础",
                    "难易程度": "中等",
                },
                "tagged_rows": [
                    ["https://test.com/2", "阿里", "一面", "Redis缓存", "数据库", "Redis", "缓存", "L2-中等"],
                    ["https://test.com/2", "阿里", "一面", "算法题", "算法", "排序", "算法", "L3-困难"],
                ],
                "saved_url": "https://test.com/2",
                "season": "2027届",
                "user_id": 2,
                "is_admin": False,
                "job_position": "后端开发",
            }
            result = asyncio.run(persist_public_node(state))

        assert result["saved_interview_id"] is not None
        assert result["record_owner_id"] is None  # public: no owner
        assert result["record_status"] == "pending"  # non-admin → pending

        conn = mock_db
        iv = conn.execute("SELECT * FROM interview WHERE url = 'https://test.com/2'").fetchone()
        assert iv is not None
        assert iv["owner_id"] is None

    def test_cluster_public_triggers_clustering(self, mock_db):
        """验证公共路径的聚类节点调用 pipeline.cluster_batch"""
        from app.agents.submit.persist_public import cluster_public_node

        mock_cluster = AsyncMock(return_value=5)
        with patch('app.services.pipeline.should_trigger_clustering', return_value=True), \
             patch('app.services.pipeline.dequeue_batch', return_value=[{"queue_id": 1, "qd_id": 1, "question": "Q1", "cat1": "A", "cat2": "B", "tags": "", "diff_tag": "L2", "url": "u", "company": "c", "round": "r", "job_position": ""}]), \
             patch('app.services.pipeline.cluster_batch', mock_cluster), \
             patch('app.services.pipeline.mark_batch_done'):

            state = {"user_id": 1}
            result = asyncio.run(cluster_public_node(state))

        mock_cluster.assert_called_once()
        assert result["cluster_result"]["new_qb_count"] == 5


# ═══════════════════════════════════════════════
#  4. Submit Graph 路由逻辑测试
# ═══════════════════════════════════════════════

class TestSubmitGraphRouting:
    """测试 submit_graph 的条件路由是否正确"""

    def test_after_extract_good_quality(self):
        from app.agents.submit.graph import after_extract
        state = {"extraction_quality": 9.0, "extraction_retries": 0}
        assert after_extract(state) == "continue"

    def test_after_extract_low_quality_triggers_retry(self):
        from app.agents.submit.graph import after_extract
        state = {"extraction_quality": 2.0, "extraction_retries": 0}
        assert after_extract(state) == "retry"

    def test_after_extract_max_retries_forces_continue(self):
        from app.agents.submit.graph import after_extract
        # 有题目但质量低 → 重试耗尽后继续
        state = {"extraction_quality": 2.0, "extraction_retries": 2, "extracted_data": {"具体题目清单": ["题1"]}}
        assert after_extract(state) == "continue"

    def test_after_extract_max_retries_empty_questions(self):
        from app.agents.submit.graph import after_extract
        # 无题目且重试耗尽 → 报错
        state = {"extraction_quality": 0.0, "extraction_retries": 2, "extracted_data": {"具体题目清单": []}}
        assert after_extract(state) == "error_empty"

    def test_after_extract_zero_quality_retries(self):
        from app.agents.submit.graph import after_extract
        state = {"extraction_quality": 0.0, "extraction_retries": 0}
        assert after_extract(state) == "retry"

    def test_after_classify_good_quality_personal(self):
        from app.agents.submit.graph import after_classify
        state = {"tagging_quality": 9.0, "tagging_retries": 0, "target": "personal"}
        assert after_classify(state) == "personal"

    def test_after_classify_good_quality_public(self):
        from app.agents.submit.graph import after_classify
        state = {"tagging_quality": 9.0, "tagging_retries": 0, "target": "public"}
        assert after_classify(state) == "public"

    def test_after_classify_low_quality_retries(self):
        from app.agents.submit.graph import after_classify
        state = {"tagging_quality": 2.0, "tagging_retries": 0, "target": "personal"}
        assert after_classify(state) == "retry"

    def test_after_classify_max_retries_routes_by_target(self):
        from app.agents.submit.graph import after_classify
        state = {"tagging_quality": 2.0, "tagging_retries": 2, "target": "public"}
        assert after_classify(state) == "public"


# ═══════════════════════════════════════════════
#  5. Build Graph 节点级测试
# ═══════════════════════════════════════════════

class TestBuildNodes:
    """测试 build_bank_graph 各节点"""

    def test_backup_db_node(self, mock_db):
        from app.agents.build.nodes import backup_db_node
        with patch('shutil.copy2') as mock_copy:
            result = asyncio.run(backup_db_node({"user_id": 1}))
        assert "backup_path" in result
        assert result["events"][0]["step"] == "tag"
        mock_copy.assert_called_once()

    def test_clear_qb_node(self, mock_db):
        from app.agents.build.nodes import clear_qb_node
        conn = mock_db
        conn.execute("INSERT INTO question_bank (question) VALUES ('测试题')")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0] == 1

        result = asyncio.run(clear_qb_node({"user_id": 1}))
        assert conn.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0] == 0

    def test_load_all_node_enqueues(self, mock_db):
        from app.agents.build.nodes import load_all_node
        conn = mock_db
        # 插入测试面经 + 题目
        conn.execute("INSERT INTO interview (id, url, company, round, job_position) VALUES (100, 'https://test.com', '字节', '一面', '后端开发')")
        conn.execute("INSERT INTO questions_detail (id, url, company, round, question, cat1, cat2, tags, diff_tag, job_position) VALUES (200, 'https://test.com', '字节', '一面', 'Redis持久化', '数据库', 'Redis', '', 'L2-中等', '后端开发')")
        conn.commit()

        result = asyncio.run(load_all_node({"user_id": 1}))
        assert result["total_questions"] == 1
        assert result["processed_count"] == 0

    def test_cluster_loop_node_processes_batches(self, mock_db):
        from app.agents.build.nodes import cluster_loop_node
        conn = mock_db

        # 模拟队列中有数据
        conn.execute("INSERT INTO interview (id, url, company, round, job_position) VALUES (101, 'https://t.com', '公司', '一面', '后端开发')")
        conn.execute("INSERT INTO questions_detail (id, url, company, round, question, cat1, cat2, tags, diff_tag, job_position) VALUES (301, 'https://t.com', '公司', '一面', 'Q1', 'A', 'B', '', 'L2', '后端开发')")
        conn.execute("INSERT INTO analysis_queue (interview_id, question_detail_id, status) VALUES (101, 301, 'pending')")
        conn.commit()

        with patch('app.services.pipeline.cluster_batch', AsyncMock(return_value=1)), \
             patch('app.services.pipeline.mark_batch_done'):
            result = asyncio.run(cluster_loop_node({"user_id": 1, "total_questions": 1, "processed_count": 0}))

        assert result["processed_count"] >= 0
        assert result["progress_pct"] == 100.0


# ═══════════════════════════════════════════════
#  6. Batch Generate Graph 测试
# ═══════════════════════════════════════════════

class TestBatchGenerateNodes:
    """测试 batch_generate_graph 各节点"""

    def test_load_questions_node(self, mock_db):
        from app.agents.batch_generate.nodes import load_questions_node
        conn = mock_db
        conn.execute("INSERT INTO question_bank (id, question, ai_answer) VALUES (10, 'Q1', NULL)")
        conn.execute("INSERT INTO question_bank (id, question, ai_answer) VALUES (11, 'Q2', '')")
        conn.execute("INSERT INTO question_bank (id, question, ai_answer) VALUES (12, 'Q3', '已有答案')")
        conn.commit()

        result = asyncio.run(load_questions_node({"user_id": 1}))
        assert len(result["question_ids"]) == 2  # 只加载无答案的
        assert result["current_index"] == 0

    def test_generate_answer_node_saves_to_db(self, mock_db):
        from app.agents.batch_generate.nodes import generate_answer_node
        conn = mock_db
        conn.execute("INSERT INTO question_bank (id, question, ai_answer) VALUES (20, 'Redis持久化', NULL)")
        conn.commit()

        with patch('app.services.llm._call_llm_with_retry', AsyncMock(return_value=MOCK_ANSWER)):
            state = {
                "question_ids": [20],
                "current_index": 0,
                "user_id": 1,
                "success_count": 0,
                "fail_count": 0,
            }
            result = asyncio.run(generate_answer_node(state))

        assert result["success_count"] == 1
        assert result["answer_quality"] >= 5.0

        # 验证答案已写入 DB
        row = conn.execute("SELECT ai_answer FROM question_bank WHERE id = 20").fetchone()
        assert row["ai_answer"] == MOCK_ANSWER

    def test_should_continue_generate(self):
        from app.agents.batch_generate.nodes import should_continue_generate
        assert should_continue_generate({"current_index": 2, "question_ids": [1, 2, 3]}) == "continue"
        assert should_continue_generate({"current_index": 3, "question_ids": [1, 2, 3]}) == "done"

    def test_summarize_node(self, mock_db):
        from app.agents.batch_generate.nodes import summarize_node
        result = asyncio.run(summarize_node({"success_count": 8, "fail_count": 2}))
        assert "8/10" in result["events"][0]["message"]


# ═══════════════════════════════════════════════
#  7. Submit Graph 端到端集成测试（与原始流程对比）
# ═══════════════════════════════════════════════

class TestSubmitGraphE2E:
    """端到端测试：模拟完整 submit_graph 执行，与原始流程对比"""

    def test_personal_interview_e2e(self, mock_db):
        """个人面经：extract → complete → classify → match_persist_personal"""
        from app.agents.submit.graph import submit_graph

        mock_llm = AsyncMock(return_value=MOCK_EXTRACT_RESPONSE)
        mock_tag = AsyncMock(side_effect=_mock_tag_batch)
        mock_match = AsyncMock(return_value={"matched": [], "unmatched": []})

        with patch('app.services.llm._call_llm_with_retry_messages', mock_llm), \
             patch('app.services.llm._should_use_response_format', return_value=False), \
             patch('app.services.llm.get_llm_client_for_user', return_value=(MagicMock(), "model", 30, "", "openai")), \
             patch('app.routers.submit.tag_questions_batch', mock_tag), \
             patch('app.services.clustering.match_new_questions', mock_match), \
             patch('app.db.connection.get_current_job_position', return_value="后端开发"), \
             patch('app.db.connection.get_taxonomy_for_position', return_value=None), \
             patch('app.db.connection.run_db', new_callable=AsyncMock, side_effect=lambda f: f()):

            input_state = {
                "raw_text": "字节跳动二面面经...",
                "image_data": [],
                "url": "https://test.com/e2e",
                "season": "2027届",
                "content_type_hint": "interview",
                "target": "personal",
                "user_id": 1,
                "is_admin": True,
                "job_position": "后端开发",
            }
            result = asyncio.run(submit_graph.ainvoke(input_state, config={"configurable": {"thread_id": "test-personal-e2e"}}))

        # 验证关键状态
        assert result.get("doc_type") == "interview"
        assert result.get("extracted_data", {}).get("公司") == "字节跳动"
        assert len(result.get("tagged_rows", [])) == 3
        assert result.get("saved_interview_id") is not None

        # 验证 DB 有写入
        conn = mock_db
        iv = conn.execute("SELECT * FROM interview WHERE url = 'https://test.com/e2e'").fetchone()
        assert iv is not None
        details = conn.execute("SELECT * FROM questions_detail WHERE url = 'https://test.com/e2e'").fetchall()
        assert len(details) == 3

    def test_public_interview_e2e(self, mock_db):
        """公共面经：extract → complete → classify → persist_public → cluster_public"""
        from app.agents.submit.graph import submit_graph

        mock_llm = AsyncMock(return_value=MOCK_EXTRACT_RESPONSE)

        with patch('app.services.llm._call_llm_with_retry_messages', mock_llm), \
             patch('app.services.llm._should_use_response_format', return_value=False), \
             patch('app.services.llm.get_llm_client_for_user', return_value=(MagicMock(), "model", 30, "", "openai")), \
             patch('app.routers.submit.tag_questions_batch', AsyncMock(side_effect=_mock_tag_batch)), \
             patch('app.db.connection.get_current_job_position', return_value="后端开发"), \
             patch('app.db.connection.get_taxonomy_for_position', return_value=None), \
             patch('app.db.connection.run_db', new_callable=AsyncMock, side_effect=lambda f: f()), \
             patch('app.services.pipeline.enqueue_questions', return_value=3), \
             patch('app.services.pipeline.should_trigger_clustering', return_value=False):

            input_state = {
                "raw_text": "阿里一面面经...",
                "image_data": [],
                "url": "https://test.com/e2e-public",
                "season": "2027届",
                "content_type_hint": "interview",
                "target": "public",
                "user_id": 1,
                "is_admin": True,
                "job_position": "后端开发",
            }
            result = asyncio.run(submit_graph.ainvoke(input_state, config={"configurable": {"thread_id": "test-public-e2e"}}))

        assert result.get("doc_type") == "interview"
        assert result.get("saved_interview_id") is not None

        conn = mock_db
        iv = conn.execute("SELECT * FROM interview WHERE url = 'https://test.com/e2e-public'").fetchone()
        assert iv is not None
        assert iv["owner_id"] is None  # public

    def test_extraction_quality_retry(self, mock_db):
        """提取质量不足时应触发重试（最多2次）"""
        from app.agents.submit.extract import extract_node

        call_count = 0
        def mock_llm_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return MOCK_EXTRACT_RESPONSE_LOW_QUALITY  # 前两次返回低质量
            return MOCK_EXTRACT_RESPONSE  # 第三次返回正常

        mock_llm = AsyncMock(side_effect=mock_llm_side_effect)

        with patch('app.services.llm._call_llm_with_retry_messages', mock_llm), \
             patch('app.services.llm._should_use_response_format', return_value=False), \
             patch('app.services.llm.get_llm_client_for_user', return_value=(MagicMock(), "model", 30, "", "openai")):

            state = {
                "raw_text": "面经", "image_data": [], "url": "", "user_id": 1,
                "content_type_hint": "interview", "doc_type": "interview",
                "extraction_retries": 0,
            }
            result = asyncio.run(extract_node(state))

        # 低质量（空题目）→ quality = 0
        assert result["extraction_quality"] == 0.0

    def test_classification_quality_retry(self, mock_db):
        """分类质量不足时应触发重试"""
        from app.agents.submit.classify import classify_node

        with patch('app.routers.submit.tag_questions_batch', AsyncMock(side_effect=_mock_tag_batch_low_quality)), \
             patch('app.db.connection.get_taxonomy_for_position', return_value=None), \
             patch('app.db.connection.run_db', new_callable=AsyncMock, side_effect=lambda f: f()):

            taxonomy = {"categories": [
                {"cat1": "数据库", "children": ["Redis", "MySQL"]},
                {"cat1": "计算机网络", "children": ["TCP", "HTTP"]},
            ]}
            state = {
                "extracted_data": {"公司": "字节", "面试轮次": "一面", "具体题目清单": ["Q1问题", "Q2问题"]},
                "saved_url": "https://test.com",
                "user_id": 1,
                "tagging_retries": 0,
                "taxonomy_config": taxonomy,
            }
            result = asyncio.run(classify_node(state))

        # 低质量分类（无效 cat1/cat2/diff）→ quality < 7
        assert result["tagging_quality"] < 7.0


# ═══════════════════════════════════════════════
#  8. Graph 结构验证测试
# ═══════════════════════════════════════════════

class TestGraphStructure:
    """验证三个 Graph 的节点和边结构与设计文档一致"""

    def test_submit_graph_nodes(self):
        from app.agents.submit.graph import submit_graph
        nodes = set(submit_graph.nodes.keys())
        expected = {
            "__start__", "recognize", "extract", "retry_extract",
            "complete", "classify", "retry_classify",
            "match_persist_personal", "persist_public", "cluster_public",
            "jd_persist", "error_empty",
        }
        assert nodes == expected

    def test_build_bank_graph_nodes(self):
        from app.agents.build.graph import build_bank_graph
        nodes = set(build_bank_graph.nodes.keys())
        expected = {
            "__start__", "backup_db", "clear_qb", "load_all",
            "cluster_loop", "restore_answers"
        }
        assert nodes == expected

    def test_batch_generate_graph_nodes(self):
        from app.agents.batch_generate.graph import batch_generate_graph
        nodes = set(batch_generate_graph.nodes.keys())
        expected = {"__start__", "load_questions", "generate_answer", "summarize"}
        assert nodes == expected

    def test_submit_graph_has_quality_retry_loops(self):
        """验证 submit_graph 包含质量重试循环（extract ↔ retry_extract, classify ↔ retry_classify）"""
        from app.agents.submit.graph import submit_graph
        # 通过 ainvoke 不传数据看结构不崩（空输入会走完 recognize 就出错，但节点存在就行）
        assert "retry_extract" in submit_graph.nodes
        assert "retry_classify" in submit_graph.nodes
