# InterviewBoss 面试官质量优化 Spec

基于 2026-07-03 E2E 深度评估报告发现的 6 个问题，制定统一优化方案。

评估报告：`docs/evaluations/2026-07-03-interview-agent-e2e-evaluation.md`

---

## 背景

E2E 测试（31 轮对话，45000 字）暴露了面试官的系统性缺陷：

| 编号 | 问题 | 严重度 | 当前状态 |
|------|------|--------|----------|
| #1 | 推理-输出脱节：推理层识别错误但输出不纠正 | 🔴 P0 | Faiss 已修复，BERT/LRU 仍遗漏 |
| #2 | 发送消息偶发错误：内部 LLM 调用无 try-catch | 🟡 P1 | MiMo 500 时冒泡到前端 |
| #3 | 题库检索相关度低：混入不相关题目 | 🟡 P1 | 只有 heuristic rerank，无 neural rerank |
| #4 | 跨轮次去重缺失：同一候选人在不同轮次遇到相同题 | 🟠 P2 | OutputDeduplicator 仅单对话内 |
| #5 | 结尾评估报告缺失：面试结束无结构化反馈 | 🔴 P0 | 三轮一致缺失 |
| #6 | 推理 trace 模板化：summary 是通用模板 | 🟠 P2 | thinking 有真实内容但未展示 |

---

## #1 推理-输出脱节

### 问题

模型在 thinking 中识别了候选人的技术错误（如"Faiss 支持 ACID"），但最终输出跳过纠正，直接问下一个问题。

根因：system prompt 没有明确要求"发现错误必须纠正"。

### 方案：Prompt 强化 + 正反例

在 `build_react_system_prompt` 中新增一段指令。

**改动文件**：`backend/app/agents/chat/nodes.py`

**改动位置**：`build_react_system_prompt` 函数，在 Layer 1 base prompt 之后插入。

**新增 prompt 内容**：

```
## 技术错误识别与纠正

当候选人回答中包含技术概念错误时，你必须在回复中指出。这是面试官的核心职责——
帮助候选人发现认知盲点。

### 行为规则
1. 如果你识别到技术错误，必须在下一个回复中追问或纠正
2. 纠正方式：用追问引导候选人自己发现错误，而非直接告知答案
3. 可以一次追问一个最严重的错误，不必全部点出
4. 候选人主动纠正后，给予简短认可再继续

### 正例
候选人："Faiss原生支持ACID事务"
面试官："你提到Faiss支持ACID事务，这个说法的依据是什么？Faiss是向量相似性搜索库，
你能具体说说它在你项目中是如何保证数据一致性的吗？"
→ 用追问引导候选人思考，而非直接说"你错了"

### 反例  
候选人："Faiss原生支持ACID事务"
面试官："好的。接下来说说RAG和传统检索的区别。"
→ 跳过错误 = 失职。候选人会带着错误认知离开。
```

### 测试

**TDD 红测**（先写测试，确认失败）：

```python
# backend/tests/chat/test_error_correction.py

async def test_interviewer_corrects_technical_error(client, test_db, mock_llm):
    """面试官必须在回复中纠正候选人的技术错误"""
    # 注入包含已知错误的自我介绍
    intro = (
        "我做过RAG项目，用Faiss做向量存储，"
        "Faiss原生支持ACID事务。"
        "用BERT做文本生成任务。"
    )
    
    # 发送消息
    response = await send_message(client, conversation_id, intro)
    
    # 验证面试官回复中包含对错误的追问
    assistant_msg = get_last_assistant_message(response)
    assert "ACID" in assistant_msg or "Faiss" in assistant_msg, \
        "面试官应追问Faiss ACID错误"
    assert "BERT" in assistant_msg or "生成" in assistant_msg, \
        "面试官应追问BERT生成式错误"
```

**E2E 验证**：
- 注入 3 个已知错误（Faiss ACID、BERT 生成式、LRU 最近最常使用）
- 验证输出中至少纠正 2 个
- 对比修复前后各 3 轮的错误识别率

---

## #2 发送消息偶发错误

### 问题

`_enforce_question_plan_on_text` 内部调用 `_repair_response_to_question_plan` 和 `_rewrite_transition_with_llm`，这两个函数的 LLM 调用没有 try-catch。MiMo 500 时异常冒泡到前端，用户看到"发送消息时出现错误"。

### 方案：防御性 try-catch

**改动文件**：`backend/app/agents/chat/answer.py`

**改动 1**：`_repair_response_to_question_plan`（约 172-199 行）

```python
# 在 LLM 调用处加 try-catch
try:
    result = await raw_llm_call(
        user_id=state["user_id"],
        model=state.get("model"),
        messages=[...],
        temperature=0.3,
        max_tokens=512,
    )
except Exception as e:
    logger.warning("repair_response LLM failed, using original: %s", e)
    return text  # 降级：用原文
```

**改动 2**：`_rewrite_transition_with_llm`（约 281-320 行）

```python
# 同样加 try-catch
try:
    result = await raw_llm_call(...)
except Exception as e:
    logger.warning("rewrite_transition LLM failed: %s", e)
    return None  # 降级：返回 None，调用方走 fallback
```

**改动 3**：`_enforce_question_plan_on_text`（约 151-223 行）

确保所有 LLM 调用路径都有降级，不向上冒泡异常。

### 测试

```python
async def test_plan_enforcement_graceful_on_llm_failure(mock_llm):
    """LLM 修复失败时应降级到原文，不应抛异常"""
    mock_llm.side_effect = Exception("MiMo 500")
    
    text = "你觉得Redis和Memcached有什么区别？"
    result = await _enforce_question_plan_on_text(text, state)
    
    # 不应抛异常，应返回原文或 fallback
    assert result is not None
    assert len(result) > 0
```

**回归**：现有 `test_error_recovery.py` 全量通过。

---

## #3 题库检索 — LLM Rerank in search_questions

### 问题

当前 rerank 是纯规则的（keyword overlap + RRF score），没有 neural rerank。不相关题目（如"C++ coredump"出现在 RAG 讨论中）无法被过滤。

已有的 LLM rerank 实现（`nodes.py:885`）被关掉（`CHAT_LLM_RERANK_MODE=off`），因为它是独立调用，增加延迟。

### 方案：Rerank 嵌入 search_questions 工具内部

在 `_execute_search_questions` 中，检索后立即用 LLM 做一次精排，不增加 ReAct 循环的额外调用。

**改动文件**：`backend/app/agents/chat/tools.py`

**改动位置**：`_execute_search_questions` 函数（约 283 行）

**新流程**：

```
1. 现有检索：hybrid_search → 返回 15 个候选（当前是 5 个）
2. LLM rerank：用 MiMo 对 15 个候选做相关性评分
3. Relevance threshold：分数 < 0.3 的丢弃
4. 返回 top 3-5 个精排结果
```

**新增函数** `_llm_rerank_in_tool`：

```python
async def _llm_rerank_in_tool(
    candidates: list[dict],
    conversation_context: str,
    user_id: int,
    model: str = None,
) -> list[dict]:
    """在 search_questions 工具内部做 LLM rerank。
    
    用 MiMo 对候选题做零样本相关性评分，过滤不相关结果。
    失败时降级返回原始排序。
    """
    if len(candidates) < 3:
        return candidates
    
    # 构造简化 prompt
    candidate_text = "\n".join(
        f"{i+1}. [{q.get('cat1','')}/{q.get('cat2','')}] {q.get('question','')}"
        for i, q in enumerate(candidates[:15])
    )
    
    prompt = f"""根据以下面试对话上下文，对候选题目的相关性评分（0-1）。
只输出JSON，不要解释。

对话上下文：
{conversation_context[:500]}

候选题目：
{candidate_text}

输出格式：{{"scores": [0.9, 0.3, 0.8, ...]}}  # 与候选顺序一一对应"""
    
    try:
        from app.services.llm import raw_llm_call
        result = await raw_llm_call(
            user_id=user_id,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
        )
        import json
        parsed = json.loads(result)
        scores = parsed.get("scores", [])
        
        # 合并分数
        for i, q in enumerate(candidates[:len(scores)]):
            q["_relevance_score"] = float(scores[i])
        
        # Relevance threshold 过滤
        filtered = [q for q in candidates if q.get("_relevance_score", 0) >= 0.3]
        
        # 按分数排序
        filtered.sort(key=lambda q: q.get("_relevance_score", 0), reverse=True)
        
        return filtered[:5] if filtered else candidates[:3]
        
    except Exception as e:
        logger.warning("LLM rerank in search_questions failed: %s", e)
        return candidates[:5]  # 降级：返回原始 top 5
```

**修改 `_execute_search_questions`**：

```python
async def _execute_search_questions(args, state):
    # ... 现有检索逻辑 ...
    envelope = await search_questions_tool(args, state)
    
    # 新增：LLM rerank
    candidates = envelope.get("questions", [])
    if len(candidates) >= 3:
        recent = state.get("recent_messages", [])
        context = "\n".join(
            f"{'面试官' if m.get('role')=='assistant' else '候选人'}: {m.get('content','')[:100]}"
            for m in recent[-4:]
        )
        reranked = await _llm_rerank_in_tool(
            candidates, context, state["user_id"], state.get("model")
        )
        envelope["questions"] = reranked
        envelope["result_count"] = len(reranked)
    
    return envelope
```

**改动检索候选数**：`search_questions_tool` 返回 15 个（当前 5 个），给 rerank 更多选择。

### 测试

```python
async def test_llm_rerank_filters_irrelevant(mock_llm):
    """LLM rerank 应过滤不相关题目"""
    candidates = [
        {"id": 1, "question": "RAG的具体流程", "cat1": "B", "cat2": "RAG"},
        {"id": 2, "question": "C++ coredump分析", "cat1": "C", "cat2": "C++"},
        {"id": 3, "question": "向量数据库选型", "cat1": "B", "cat2": "向量"},
    ]
    
    # Mock LLM 返回：第1、3题相关，第2题不相关
    mock_llm.return_value = '{"scores": [0.9, 0.1, 0.8]}'
    
    result = await _llm_rerank_in_tool(candidates, "RAG项目讨论", user_id=1)
    
    # 第2题应被过滤
    ids = [q["id"] for q in result]
    assert 2 not in ids, "不相关的C++题应被过滤"
    assert 1 in ids
    assert 3 in ids


async def test_llm_rerank_fallback_on_failure(mock_llm):
    """LLM rerank 失败时应降级返回原始排序"""
    mock_llm.side_effect = Exception("MiMo 500")
    
    candidates = [{"id": i, "question": f"Q{i}"} for i in range(5)]
    result = await _llm_rerank_in_tool(candidates, "test", user_id=1)
    
    # 应返回原始 top 5
    assert len(result) == 5
    assert result[0]["id"] == 0
```

**延迟测试**：rerank 增加的延迟 < 2 秒。

---

## #4 跨轮次去重

### 问题

`OutputDeduplicator` 是 per-state 的（`answer.py:48-83`），窗口=8，仅单对话内去重。同一候选人在不同面试轮次可能遇到相同题目（如 LRU Cache 在第 1、2 轮重复出现）。

### 方案：interview_asked_questions 表

**数据库变更**：

```sql
-- 新增表
CREATE TABLE interview_asked_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    conversation_id TEXT NOT NULL,
    question_id INTEGER NOT NULL,
    asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_iaq_user_question 
    ON interview_asked_questions(user_id, question_id);
CREATE INDEX idx_iaq_conversation 
    ON interview_asked_questions(conversation_id);
```

**改动文件**：

1. `backend/app/db/operations.py` — 新增 `record_asked_question` 和 `get_asked_question_ids`
2. `backend/app/agents/chat/tools.py` — `_execute_search_questions` 中排除已出题
3. `backend/app/agents/chat/metadata.py` — 出题后记录到表

**检索排除逻辑**（在 `_execute_search_questions` 中）：

```python
# 获取该用户已出过的题
from app.db.operations import get_asked_question_ids
asked_ids = await run_db(lambda: get_asked_question_ids(state["user_id"]))

# 过滤
if asked_ids:
    envelope["questions"] = [
        q for q in envelope.get("questions", [])
        if q.get("id") not in asked_ids
    ]
```

**出题记录**（在 metadata 提取阶段）：

```python
# 当面试官选了一道题提问后
if selected_question_id:
    from app.db.operations import record_asked_question
    await run_db(lambda: record_asked_question(
        user_id=state["user_id"],
        conversation_id=state["conversation_id"],
        question_id=selected_question_id,
    ))
```

### 测试

```python
async def test_cross_conversation_dedup(test_db):
    """不同对话中不应重复出同一道题"""
    # 对话 1 出了题 101
    record_asked_question(user_id=1, conversation_id="conv1", question_id=101)
    
    # 对话 2 检索时应排除题 101
    asked = get_asked_question_ids(user_id=1)
    assert 101 in asked
    
    # 检索结果中不应包含题 101
    results = search_with_dedup(user_id=1, keywords=["Redis"])
    ids = [q["id"] for q in results]
    assert 101 not in ids


async def test_cross_user_isolation(test_db):
    """用户 1 出过的题不影响用户 2"""
    record_asked_question(user_id=1, conversation_id="conv1", question_id=101)
    
    asked_user2 = get_asked_question_ids(user_id=2)
    assert 101 not in asked_user2
```

---

## #5 结尾评估报告

### 问题

面试结束时没有结构化评估。候选人无法获得面试表现的反馈。

### 方案：面试结束时生成结构化评估

**触发条件**：
- 候选人消息包含"收尾"/"结束"/"没了吧"/"请教几个问题"等意图
- 或面试已覆盖主要维度（coverage 满足阈值）
- 或面试时长超过 15 分钟

**改动文件**：

1. `backend/app/agents/chat/nodes.py` — 新增 `EVALUATION_PROMPT`
2. `backend/app/agents/chat/react_loop.py` — 在 done 事件前插入评估生成
3. `backend/app/agents/chat/pipeline.py` — 评估事件通过 SSE 推送

**评估 Prompt**（参考 SIIS 框架，强制 observe → reason → verdict）：

```python
EVALUATION_PROMPT = """你是一位面试评估专家。根据以下面试对话，生成结构化评估报告。

## 评估规则
1. 每个维度必须按"观察→推理→评分"顺序
2. 评分必须引用具体对话证据（逐字引用，不能转述）
3. 如果某维度证据不足，写"证据不足，建议补充考察"
4. 不要给出"通过/不通过"建议，只给维度评分和改进建议

## 评估维度
1. 技术深度：对技术原理的理解程度（1-5）
2. 项目实战：对项目细节的掌握程度（1-5）
3. 表达清晰度：回答的结构化和逻辑性（1-5）
4. 错误认知：是否存在技术概念错误（1-5，5=无错误）
5. 应变能力：面对追问的反应速度和深度（1-5）

## 面试对话
{conversation}

## 输出格式
### 面试评估报告

**综合评分**: X.X/5

#### 1. 技术深度 ⭐⭐⭐⭐ (4/5)
**观察**: 候选人能清晰解释IVF的聚类原理和nprobe参数...
**依据**: "IVF是基于聚类的近似最近邻索引，核心思路是先粗量化再精排..."
**改进建议**: 对HNSW的失效场景理解不够深入，建议补充学习

#### 2. 项目实战 ⭐⭐⭐ (3/5)
...

### 关键发现
- 候选人存在X概念错误，建议复习Y
- 项目经验扎实，但缺乏Z方面的深度

### 改进建议
1. ...
2. ...
"""
```

**实现位置**：在 `_react_loop` 中，当检测到面试结束意图时：

```python
# 在 _react_loop 的 final_answer_text 处理之后
if _is_interview_ending(state):
    evaluation = await _generate_evaluation(state)
    if evaluation:
        yield {"type": "chunk", "content": "\n\n---\n\n" + evaluation}
```

**`_is_interview_ending` 判断逻辑**：

```python
def _is_interview_ending(state: ChatState) -> bool:
    user_msg = state.get("user_message", "").lower()
    ending_keywords = ["收尾", "结束", "没了吧", "请教几个问题", "最后", "差不多了"]
    return any(kw in user_msg for kw in ending_keywords)
```

### 测试

```python
async def test_evaluation_report_generated(mock_llm):
    """面试结束时应生成评估报告"""
    # Mock LLM 返回评估内容
    mock_llm.return_value = "### 面试评估报告\n**综合评分**: 3.8/5\n..."
    
    state = {
        "user_message": "我想请教几个问题就收尾",
        "message_history": [...],  # 包含多轮对话
    }
    
    events = []
    async for event in _react_loop(state):
        events.append(event)
    
    # 应包含评估内容
    chunks = [e for e in events if e.get("type") == "chunk"]
    full_text = "".join(e.get("content", "") for e in chunks)
    assert "评估报告" in full_text or "综合评分" in full_text


async def test_evaluation_cites_evidence(evaluation_text):
    """评估应引用具体对话证据"""
    # 评估中应包含引号格式的对话引用
    assert '"' in evaluation_text or "'" in evaluation_text, \
        "评估应引用具体对话证据"
```

---

## #6 推理 trace 模板化

### 问题

`reasoning_trace.summary` 是通用模板（"分析候选人回答，判断下一步追问方向"），缺乏具体信息。但 `thinking` 字段有真实的模型推理内容（"候选人纠正了自己的错误表述，这是一个好的信号"）。

### 方案：改前端展示逻辑

**改动文件**：`frontend/src/components/business/ReasoningTimeline.vue`

**改动**：从 metadata 中读取 `thinking` 字段，截取前 200 字作为展示内容。

```javascript
// 现有逻辑：展示 reasoning_trace.summary
const summary = metadata.reasoning_trace?.summary || []

// 新逻辑：优先展示 thinking 内容
const thinkingChunks = metadata.thinking?.[0]?.chunks || []
const thinkingText = thinkingChunks.join('').slice(0, 200)

const displayText = thinkingText 
  ? thinkingText + (thinkingChunks.join('').length > 200 ? '...' : '')
  : summary.join(' → ')
```

### 测试

前端手动验证：发送一条包含技术错误的回答，检查推理展示区是否显示具体的 thinking 内容而非模板。

---

## 实施顺序

| 顺序 | 问题 | 预计工作量 | 依赖 |
|------|------|-----------|------|
| 1 | #1 推理-输出脱节（prompt 强化） | 30 分钟 | 无 |
| 2 | #2 发送消息偶发错误（try-catch） | 20 分钟 | 无 |
| 3 | #3 LLM rerank in search_questions | 1 小时 | 无 |
| 4 | #4 跨轮次去重 | 40 分钟 | 无 |
| 5 | #5 结尾评估报告 | 1 小时 | #1（依赖错误识别能力） |
| 6 | #6 推理 trace 展示 | 15 分钟 | 无 |

**总预计工作量**：约 3.5 小时

## 测试总策略

### 单元测试

每个改动对应 2-3 个测试用例：
- 正常路径
- 异常降级路径
- 边界条件

### 集成测试

每改一个，跑 `backend/tests/chat/` 全量回归：
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q
```

### E2E 验证测试

全部改完后，用评估报告中的测试矩阵做完整验证：
- 3 轮完整面试（自由练习中级、高级、JD定制）
- 错误注入测试（3 个已知技术错误）
- 跨轮次去重验证（两轮面试检查题目不重复）
- 结尾评估报告验证（触发收尾后检查评估输出）

### 性能基准

- 单轮面试延迟 < 20 秒（当前约 16 秒）
- LLM rerank 增加 < 2 秒
- 评估报告生成 < 5 秒
