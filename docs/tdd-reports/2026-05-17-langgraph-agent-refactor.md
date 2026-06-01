# LangGraph Agent 架构改造设计文档

> **日期**: 2026-05-17
> **状态**: 设计阶段 — 待讨论确认后实施
> **目标**: 将 InterviewBoss 核心 LLM 处理流程从硬编码 pipeline 重构为 LangGraph 状态机，引入质量自评重试、增强 SSE 可观测性、统一 Agent 编排架构。

---

## 一、现状分析

### 1.1 当前架构问题

```
现有流程（硬编码 pipeline）：

submit_data()
  ├── _call_llm_with_retry_messages()  → 提取内容（3-10s）
  ├── raw_llm_call()                   → 补全字段（2-5s，可选）
  ├── tag_questions_batch()            → 分类标注（3-8s）
  ├── [personal] match_new_questions() + submit_interview_txn()
  │   └── background_generate_answer() → 生成答案（5-15s，异步）
  └── [public] submit_interview_txn_tag_only() + enqueue_questions()
      └── cluster_batch()              → 聚类去重（5-30s，异步）
```

**核心问题：**

| # | 问题 | 影响 |
|---|------|------|
| 1 | **无质量检查** | LLM 提取了 0 个题目也直接存入数据库 |
| 2 | **无自动重试** | 分类结果格式错误只能整体失败 |
| 3 | **SSE 事件信息贫乏** | 前端只知道到了哪一步，不知道结果详情（提取了几个题、分到哪些类） |
| 4 | **无断点续跑** | 进程在 tag 完成后崩溃，需要从头重跑提取 |
| 5 | **错误粒度粗** | 任何步骤失败都是整体 error，无法定位具体哪个节点出问题 |
| 6 | **三个核心流程各自为政** | submit、build-master-bank、batch-generate 的进度/错误处理逻辑大量重复 |

### 1.2 现有前端进度机制

前端 `StagingPanel.vue` 已有 5 步进度条：

```js
const submitStepsDef = [
  { key: 'extract', label: '提取内容' },
  { key: 'fill',    label: '补全信息' },
  { key: 'tag',     label: '标注题目' },
  { key: 'match',   label: '匹配聚类' },
  { key: 'save',    label: '保存入库' },
]
```

后端通过 `POST /api/submit-stream` (SSE) 发送事件驱动，格式：
```json
{ "type": "progress", "step": "extract", "message": "正在识别内容..." }
{ "type": "done", "doc_type": "Interview", "saved_data": {...} }
```

**改造空间**：当前 SSE 事件只有 step key 和简单 message，可以扩展为携带结构化数据（提取的题目列表、分类分布、质量分数、耗时统计）。

---

## 二、LangGraph 架构设计

### 2.1 设计原则

1. **渐进式引入**：节点内部调用现有 service 函数，不重写业务逻辑
2. **统一编排**：submit / build / batch-generate 共享同一个 StateGraph 基础设施
3. **SSE 兼容**：LangGraph 的 `astream_events` 映射到现有前端 SSE 协议
4. **质量闭环**：每个 LLM 节点后都有质量检查 + 自动重试（最多 2 次）

### 2.2 依赖引入

```toml
# pyproject.toml 新增
langgraph >= 1.1.0
langchain-core >= 1.0.0
```

**不需要引入的**：
- 不需要 langchain（LLM 调用继续用 AsyncOpenAI/AsyncAnthropic）
- 不需要 LangSmith（用 Langfuse 或自建 trace）
- 不需要 LangGraph Platform Server（用 FastAPI 直接集成）

### 2.3 核心 State 定义

```python
from typing import TypedDict, Annotated, Optional
from operator import add

class SubmitState(TypedDict):
    """提交流程的完整状态"""
    # === 输入 ===
    raw_text: str                           # 用户输入的文本
    image_data: list[str]                   # base64 图片列表
    url: str                                # 来源 URL
    season: str                             # 届次
    content_type_hint: str                  # "auto" | "jd" | "interview"
    target: str                             # "personal" | "public"
    user_id: int                            # 当前用户 ID
    is_admin: bool                          # 是否管理员
    job_position: str                       # 当前岗位

    # === 节点输出 ===
    doc_type: str                           # "JD" | "Interview" 由识别节点填入
    extracted_data: dict                    # LLM 提取的原始数据
    completion_attempted: bool              # 是否尝试了字段补全
    tagged_rows: list[list[str]]            # 分类结果 [url, company, round, q, cat1, cat2, tags, diff_tag]
    match_result: dict                      # 聚类匹配结果 {matched: [...], unmatched: [...]}
    saved_interview_id: int                 # 写入 DB 后的 interview ID
    answer_tasks: list[tuple[int, str]]     # 需要生成答案的 (question_id, question_text) 列表
    cluster_result: dict                    # 聚类结果

    # === 质量控制 ===
    extraction_quality: float               # 提取质量分数 (0-10)
    extraction_retries: int                 # 提取重试次数
    tagging_quality: float                  # 分类质量分数 (0-10)
    tagging_retries: int                    # 分类重试次数

    # === 可观测性 ===
    events: Annotated[list[dict], add]      # 累积的进度事件（reducer: append）
    node_timings: dict                      # 每个节点的执行耗时
    error: str                              # 错误信息（如果有）
    llm_call_count: int                     # LLM 调用总次数
    total_tokens: int                       # Token 消耗估算
```

### 2.4 Submit 流程 StateGraph

```
                    ┌──────────────┐
                    │   START      │
                    └──────┬───────┘
                           ▼
                   ┌───────────────┐
                   │   recognize   │  识别内容类型 (JD/Interview)
                   │   + quality   │  检查: doc_type 是否有效
                   └───────┬───────┘
                           ▼
                   ┌───────────────┐
                   │   extract     │  LLM 提取结构化数据
                   │   + quality   │  检查: 题目数 > 0, 必填字段完整
                   └───────┬───────┘
                      质量<7?──────→ 重试 (max 2)
                           ▼
                   ┌───────────────┐
                   │   complete    │  补全缺失字段 (可选)
                   └───────┬───────┘
                           ▼
                   ┌───────────────┐
                   │   classify    │  LLM 分类标注
                   │   + quality   │  检查: cat1/cat2 合法, diff_tag 有效
                   └───────┬───────┘
                      质量<7?──────→ 重试 (max 2)
                           ▼
                    ┌──────┴──────┐
                    │  target?    │
                    └──┬──────┬───┘
                 personal   public
                    ▼         ▼
           ┌────────────┐  ┌─────────────┐
           │  match     │  │  persist    │  仅写 interview + questions_detail
           │  + persist │  │  (public)   │
           │ (personal) │  └──────┬──────┘
           └─────┬──────┘         ▼
                 ▼          ┌─────────────┐
           ┌──────────┐    │  enqueue    │  加入聚类队列
           │ generate │    └──────┬──────┘
           │ answers  │         ▼
           │ (bg)     │    ┌─────────────┐
           └────┬─────┘    │  cluster    │  聚类去重 (如触发)
                ▼          └──────┬──────┘
                ▼                 ▼
           ┌─────────────────────────┐
           │          END            │
           └─────────────────────────┘
```

### 2.5 节点实现策略

每个节点函数：**调用现有 service + 质量检查 + 写 events**

```python
async def classify_node(state: SubmitState) -> dict:
    """分类标注节点 — 调用现有 tag_questions_batch + 质量检查"""
    import time
    start = time.monotonic()

    # 1. 调用现有 service
    tagged_rows = await tag_questions_batch(
        url=state["url"],
        company=state["extracted_data"]["公司"],
        round_=state["extracted_data"]["面试轮次"],
        questions=state["extracted_data"]["具体题目清单"],
        taxonomy_config=get_taxonomy_config(state["user_id"]),
        user_id=state["user_id"],
    )

    # 2. 质量检查
    quality_score = _evaluate_tagging_quality(tagged_rows, state)

    elapsed = time.monotonic() - start

    # 3. 返回状态更新 + 事件
    return {
        "tagged_rows": tagged_rows,
        "tagging_quality": quality_score,
        "tagging_retries": state.get("tagging_retries", 0),
        "node_timings": {**state.get("node_timings", {}), "classify": elapsed},
        "events": [{
            "type": "progress",
            "step": "tag",
            "message": f"标注完成: {len(tagged_rows)} 个题目",
            "data": {
                "question_count": len(tagged_rows),
                "categories": _count_categories(tagged_rows),
                "quality_score": quality_score,
                "elapsed_seconds": round(elapsed, 1),
            }
        }],
    }
```

**质量检查函数示例：**

```python
def _evaluate_extraction_quality(data: dict, state: SubmitState) -> float:
    """评估提取质量 (0-10)"""
    score = 10.0
    questions = data.get("具体题目清单", [])

    if len(questions) == 0:
        return 0.0                           # 致命: 没提取到题目
    if not data.get("公司") or data["公司"] == "未提供":
        score -= 2.0                         # 公司缺失
    if not data.get("面试轮次") or data["面试轮次"] == "未提供":
        score -= 1.0                         # 轮次缺失
    if len(questions) < 2:
        score -= 3.0                         # 题目太少，可疑
    if any(len(q) < 4 for q in questions):
        score -= 1.0                         # 有极短题目，可能是噪声

    return max(0.0, score)

def _evaluate_tagging_quality(rows: list[list[str]], state: SubmitState) -> float:
    """评估分类质量 (0-10)"""
    score = 10.0
    valid_cats = _load_valid_categories(state["user_id"])

    for row in rows:
        cat1, cat2, diff_tag = row[4], row[5], row[7]
        if cat1 not in valid_cats["cat1"]:
            score -= 1.5                     # 无效的 cat1
        if cat2 not in valid_cats.get(cat1, {}).get("cat2", []):
            score -= 1.0                     # 无效的 cat2
        if diff_tag not in ("L1-基础", "L2-中级", "L3-高级"):
            score -= 0.5                     # 无效的难度标签

    return max(0.0, score / max(len(rows), 1) * 10)
```

**条件路由 + 重试：**

```python
def after_classify(state: SubmitState) -> str:
    """分类后路由: 质量达标则继续，否则重试"""
    if state["tagging_quality"] >= 7.0:
        return "continue"
    if state.get("tagging_retries", 0) >= 2:
        return "continue"                    # 重试上限，强制继续
    return "retry"

# 在 StateGraph 中注册
workflow.add_conditional_edges(
    "classify",
    after_classify,
    {"continue": "route_target", "retry": "classify"},
)
```

### 2.6 SSE 事件协议增强

**现有协议（保持兼容）：**
```json
{ "type": "progress", "step": "tag", "message": "正在标注题目..." }
```

**增强后协议（新增 data 字段）：**
```json
{
  "type": "progress",
  "step": "tag",
  "message": "标注完成: 5 个题目",
  "data": {
    "question_count": 5,
    "categories": {"算法与数据结构": 2, "系统设计": 1, "基础工程能力": 2},
    "quality_score": 9.2,
    "elapsed_seconds": 3.4,
    "retry_count": 0,
    "llm_calls_so_far": 3,
    "tokens_so_far": 4200
  }
}
```

**前端渲染（在 StagingPanel.vue 进度条下方）：**
```
✅ 提取内容 — 识别为「面经」, 公司: 字节跳动
✅ 标注题目 — 5 题 | 算法×2, 系统设计×1, 基础×2 | 质量 9.2/10 | 3.4s
⏳ 匹配聚类 — 质量不足，正在重试... (1/2)
⬜ 保存入库
```

**从 LangGraph astream_events 到 SSE 的映射：**

```python
async def stream_submit_graph(graph, input_state, config):
    """LangGraph astream_events → 前端 SSE 格式"""
    async for event in graph.astream_events(input_state, config, version="v2"):
        if event["event"] == "on_chain_end" and event["name"] != "__start__":
            node_name = event["name"]
            output = event["data"]["output"]
            # 提取 output 中的 events 字段，转换为 SSE
            for evt in output.get("events", []):
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
```

### 2.7 断点续跑（Checkpoint）

```python
from langgraph.checkpoint.memory import MemorySaver

# 生产环境可切换为 SqliteSaver 或 PostgresSaver
checkpointer = MemorySaver()

workflow = StateGraph(SubmitState)
# ... 添加节点和边 ...
app = workflow.compile(checkpointer=checkpointer)

# 调用时通过 thread_id 标识一次提交
config = {"configurable": {"thread_id": f"submit-{user_id}-{int(time.time())}"}}

# 如果进程崩溃，可以用同一个 thread_id 恢复
# app.get_state(config) → 获取最后的检查点状态
```

**注意**：MemorySaver 是进程内存级的，进程重启后丢失。生产环境如果需要跨进程续跑，需要切换到 SqliteSaver（已有的 SQLite 数据库可以复用）。当前阶段建议用 MemorySaver 起步，满足 "同一次请求内的节点级重试" 需求即可。

---

## 三、三个核心流程的 LangGraph 设计

### 3.1 Submit 流程（2.4 已详述）

### 3.2 Build-Master-Bank 流程（题库重建）

**现有流程** (`worker.py` → `build_master_bank_task`)：
```
备份 DB → 清空 QB → 加载所有 questions_detail → 入队 → 循环 cluster_batch → 恢复 AI 答案
```

**LangGraph 改造：**

```
START → backup_db → clear_qb → load_all → loop_cluster → restore_answers → END
                                         ↑        │
                                         └── retry ┘ (质量 < 7)
```

```python
class BuildBankState(TypedDict):
    # 输入
    user_id: int
    job_position: str
    # 流程状态
    backup_path: str
    total_questions: int
    processed_count: int
    current_batch: list[dict]
    cluster_results: list[dict]
    # 质量
    batch_quality_scores: list[float]
    # 可观测性
    events: Annotated[list[dict], add]
    progress_pct: float
```

**SSE 事件增强：**
```json
{
  "type": "progress",
  "step": "cluster",
  "current": 120,
  "total": 350,
  "message": "正在聚类第 120/350 题",
  "data": {
    "batch_matched": 8,
    "batch_new_clusters": 3,
    "batch_quality": 8.5,
    "cumulative_new_qb": 45,
    "cumulative_merged": 75,
    "elapsed_seconds": 12.3,
    "estimated_remaining": "45s"
  }
}
```

### 3.3 Batch-Generate-Answers 流程（批量生成答案）

**现有流程** (`routers/master_bank.py` → `batch_generate_answers_stream`)：
```
加载题目 → 逐题调用 LLM 生成答案 → UPDATE question_bank.ai_answer
```

**LangGraph 改造：**

```
START → load_questions → for_each_question → generate → quality_check → save_or_retry → END
                                                  ↑            │
                                                  └── retry ───┘ (答案质量 < 7)
```

```python
class BatchGenerateState(TypedDict):
    question_ids: list[int]
    current_index: int
    current_question: str
    current_answer: str
    answer_quality: float
    retry_count: int
    results: Annotated[list[dict], add]     # {id, quality, elapsed, success}
    events: Annotated[list[dict], add]
    success_count: int
    fail_count: int
```

**答案质量检查（用 LLM-as-Judge）：**
```python
def _evaluate_answer_quality(answer: str, question: str) -> float:
    """快速质量检查（规则 + 简单 LLM）"""
    score = 10.0
    if len(answer) < 50:
        return 1.0                           # 太短，几乎无效
    if "抱歉" in answer[:20] or "无法" in answer[:20]:
        return 2.0                           # LLM 拒绝回答
    if "```" in answer and question not in ("算法", "代码"):
        score -= 1.0                         # 非算法题包含代码块
    return score
```

---

## 四、文件结构设计

```
backend/app/
├── agents/                          # 新增: LangGraph Agent 定义
│   ├── __init__.py
│   ├── state.py                     # TypedDict State 定义
│   ├── submit_graph.py              # Submit 流程的 StateGraph
│   ├── build_graph.py               # Build-Master-Bank 的 StateGraph
│   ├── batch_generate_graph.py      # Batch-Generate 的 StateGraph
│   ├── nodes/                       # 节点函数（按流程分文件）
│   │   ├── __init__.py
│   │   ├── common.py                # 共享节点: recognize, quality_check
│   │   ├── submit_nodes.py          # Submit 专用: extract, classify, match, persist
│   │   ├── build_nodes.py           # Build 专用: backup, clear, load, cluster_loop
│   │   └── generate_nodes.py        # Generate 专用: generate_answer, evaluate_answer
│   ├── quality.py                   # 质量评估函数
│   └── events.py                    # SSE 事件构建工具
├── routers/
│   └── submit.py                    # 修改: submit-stream 端点使用 LangGraph
├── services/
│   ├── llm.py                       # 不变
│   ├── clustering.py                # 不变
│   └── pipeline.py                  # 不变（被 nodes/ 调用）
├── db/
│   └── operations.py                # 不变（被 nodes/ 调用）
└── core/
    └── prompts.py                   # 不变
```

**关键设计：nodes/ 中的函数调用现有 services/ 和 db/ 的函数，不重写业务逻辑。**

---

## 五、迁移策略

### 5.1 渐进式迁移路线

```
阶段 1: submit 流程 LangGraph 化（核心改造）
  ├── 1a: 定义 State、节点函数、质量检查
  ├── 1b: 构建 StateGraph，替换 submit-stream 端点
  ├── 1c: 前端适配增强 SSE 事件
  └── 1d: 测试验证 + 灰度切换

阶段 2: build-master-bank 流程 LangGraph 化
  ├── 2a: 构建 BuildBankState + BuildGraph
  └── 2b: 替换 worker.py 中的 build_master_bank_task

阶段 3: batch-generate 流程 LangGraph 化
  ├── 3a: 构建 BatchGenerateState + GenerateGraph
  └── 3b: 替换 batch-generate-answers 端点
```

### 5.2 向后兼容

- 现有的 `POST /api/submit`（非 SSE）端点保留不动，内部也走 LangGraph 但不推送事件
- 现有的 SSE 协议格式保持兼容（新增 `data` 字段，前端做可选解析）
- 现有 services/ 和 db/ 代码完全不动，只在 agents/nodes/ 中调用

### 5.3 测试策略

每个节点函数可以独立测试（纯函数，输入 state → 输出 state delta）：

```python
# tests/test_agents/test_submit_nodes.py

async def test_classify_node_happy_path():
    state = make_mock_state(extracted_data={"公司": "字节", "面试轮次": "一面", "具体题目清单": ["TCP三次握手"]})
    result = await classify_node(state)
    assert len(result["tagged_rows"]) == 1
    assert result["tagging_quality"] >= 7.0
    assert result["events"][0]["step"] == "tag"

async def test_classify_node_quality_retry():
    """模拟 LLM 返回无效分类，质量分数低，应触发重试路由"""
    state = make_mock_state(tagging_quality=3.0, tagging_retries=0)
    route = after_classify(state)
    assert route == "retry"
```

---

## 六、预期收益

| 指标 | 改造前 | 改造后 |
|------|--------|--------|
| 提取 0 题时 | 静默存入空数据 | 质量检查拦截，自动重试提取 |
| 分类无效时 | 静默存入错误分类 | 质量检查拦截，自动重试分类 |
| SSE 事件信息 | `step` + `message`（~20 字节） | 结构化 data（~200 字节），含题目数、分类分布、质量分数、耗时 |
| 错误定位 | "处理失败" | "classify 节点第 2 次重试后质量仍不达标 (4.2/10)" |
| 代码可测试性 | 整体端到端测试 | 每个节点独立单元测试 |
| 断点续跑 | 不支持 | 检查点机制，节点级重试 |
| 代码可维护性 | 400+ 行 submit_data() 函数 | 每个节点 30-50 行，职责清晰 |

---

## 七、风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| LangGraph 版本升级 breaking changes | 锁定 `langgraph>=1.1.0,<2.0`，核心业务逻辑在 services/ 中不受影响 |
| astream_events 性能开销 | 每个 super-step 的序列化开销 < 1ms（State 是 TypedDict，非 Pydantic） |
| 质量检查本身消耗 LLM token | 提取质量检查用规则（无 LLM 调用），分类质量检查用规则校验 taxonomy 合法性 |
| 重试导致总耗时增加 | 设置上限 2 次重试 + 重试时降低 temperature，最坏情况增加 ~10s |
| MemorySaver 进程重启丢失 | 当前阶段可接受（单次请求内重试足够）。后续可切换 SqliteSaver |

---

## 八、技术选型对比

| 选项 | 选择 | 理由 |
|------|------|------|
| LangGraph vs 手搓状态机 | LangGraph | 检查点、条件路由、astream_events 免费获得，手搓要 ~200 行胶水代码 |
| LangGraph vs Dify/Coze | LangGraph | 纯代码控制，不需要额外部署，与现有 FastAPI 无缝集成 |
| MemorySaver vs SqliteSaver | 先 MemorySaver | 满足单请求内节点重试，后续按需升级 |
| LangGraph Server vs FastAPI 集成 | FastAPI 集成 | 参考 DeerFlow 架构，FastAPI 做 Gateway，不引入额外进程 |
| TypedDict vs Pydantic State | TypedDict | LangGraph 官方推荐，性能最佳，序列化开销最小 |
