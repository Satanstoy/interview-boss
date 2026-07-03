# Interview Agent 评测框架设计

日期：2026-07-03
状态：设计完成，待实现

## 背景

今天的 E2E 评测（3 轮完整面试 + 4 项深度测试 + 1 轮修复验证，共 31 轮对话）发现了 P0 bug（推理-输出脱节）并验证了修复。但评测脚本是临时生成的（`python3 -c`），没有持久化。需要将评测能力固化为可复用的独立脚本。

## 目标

1. 将今天的 3 个临时评测脚本（codex_agent_eval、HTTP/SSE E2E、end-policy E2E）合并为一个统一框架
2. 用 LLM 扮演候选人，支持 16-20 轮长程面试
3. 复用现有 Skill 基建（`app/agents/shared/skills/`）构建智能候选人
4. 自动评分 + JSON/MD 报告输出
5. 独立脚本，手动触发，不进 CI

## 架构

### 文件结构

```
backend/scripts/
├── verify_interview_agent_real_e2e.py   ← 保留不动
├── verify_chat_tools_real_e2e.py        ← 保留不动
└── eval_interview_agent.py              ← 新增，统一入口

backend/app/agents/candidate/
└── skills/
    ├── candidate-rhythm/SKILL.md        ← 候选人节奏控制（always_active）
    ├── project-storytelling/SKILL.md     ← 项目叙述策略
    ├── coding-answer/SKILL.md            ← 算法题回答策略
    ├── knowledge-answer/SKILL.md         ← 八股/理论回答策略
    ├── error-injection/SKILL.md          ← 故意注入错误（场景专用）
    └── stall-and-clarify/SKILL.md        ← 回避/追问策略（场景专用）
```

### 入口

```bash
python backend/scripts/eval_interview_agent.py --scenario all
python backend/scripts/eval_interview_agent.py --scenario long_session_mid
python backend/scripts/eval_interview_agent.py --scenario error_correction --verbose
```

### 输出

- JSON: `backend/data/evaluations/eval_<scenario>_<timestamp>.json`
- MD: `backend/data/evaluations/eval_<scenario>_<timestamp>.md`

## 场景矩阵

| 场景 ID | 类型 | 轮数 | 消息数 | 测什么 |
|---------|------|------|--------|--------|
| `long_session_mid` | 长程回归 | 16 | ~32 | 中级自由练习，完整覆盖度 → 触发 soft_close |
| `long_session_senior` | 长程回归 | 20 | ~40 | 高级自由练习，更深追问 → 接近 strong_close |
| `long_session_jd` | 长程回归 | 16 | ~32 | JD+简历定制，验证简历引用和 JD 贴合 |
| `error_correction` | 错误识别 | 8 | ~16 | 注入错误 + 后续追问，验证纠正是否贯穿 |
| `early_close_guard` | 结束策略 | 5 | ~10 | 过早要求结束 |
| `proper_end` | 结束策略 | 10 | ~20 | 覆盖充分后结构化结束 |
| `insufficient_evidence` | 结束策略 | 5 | ~10 | 拒绝回答 |
| `counter_question` | 结束策略 | 6 | ~12 | 反问后收尾 |

轮数依据：
- 面经库平均 12.7 个问题，中位数 ~14，高级可达 21 个
- 生产数据最长 15 轮（30 条消息），实质性面试 9-15 轮
- 代码阈值：soft_close = 32 条消息（16 轮），strong_close = 44 条（22 轮）
- 覆盖度要求：中级至少 11 个问题，高级 12 个

## 智能候选人设计

### 复用 Skill 基建

复用 `app/agents/shared/skills/` 的 Skill、SkillRegistry、loader、resolver、builder：

```python
from app.agents.shared.skills.resolver import get_agent_skill_registry
from app.agents.shared.skills.builder import build_skill_prompt

class SmartCandidateAgent:
    def __init__(self, persona: dict, active_skills: list[str]):
        self.persona = persona
        self.registry = get_agent_skill_registry("candidate")
        self.active_skills = active_skills
        self.messages = []
        self._build_system_prompt()

    def _build_system_prompt(self):
        skill_prompt = build_skill_prompt(self.registry, self.active_skills)
        system = f"""你是一个正在参加技术面试的候选人。
        
## 你的背景
{self.persona['resume_text']}

## 你的能力画像
{self.persona['ability_profile']}

{skill_prompt}"""
        self.messages = [{"role": "system", "content": system}]

    async def respond(self, interviewer_message: str) -> str:
        self.messages.append({"role": "user", "content": interviewer_message})
        from app.services.llm import llm_with_tools
        response = await llm_with_tools(
            messages=self.messages,
            model=self.persona.get("model", "mimo-v2.5"),
            temperature=0.7,
        )
        reply = response["content"]
        self.messages.append({"role": "assistant", "content": reply})
        return reply
```

### 候选人 Skill 定义

| Skill | always_active | 用途 |
|-------|--------------|------|
| `candidate-rhythm` | true | 回答长度、节奏、禁止行为 |
| `project-storytelling` | false | 项目叙述策略，被追问时保持一致 |
| `coding-answer` | false | 算法题回答策略，给出完整代码 |
| `knowledge-answer` | false | 八股/理论回答策略 |
| `error-injection` | false | 故意注入技术错误（场景专用） |
| `stall-and-clarify` | false | 回避/追问策略（场景专用） |

### 场景 Skill 配置

```python
SCENARIOS = {
    # 长程回归
    "long_session_mid": {
        "mode": "free_practice", "difficulty": "mid", "max_turns": 16,
        "persona": MID_LEVEL_PERSONA,
        "active_skills": ["candidate-rhythm", "project-storytelling",
                          "knowledge-answer", "coding-answer"],
        "scoring": LONG_SESSION_SCORING,
    },
    "long_session_senior": {
        "mode": "free_practice", "difficulty": "senior", "max_turns": 20,
        "persona": SENIOR_PERSONA,
        "active_skills": ["candidate-rhythm", "project-storytelling",
                          "knowledge-answer", "coding-answer"],
        "scoring": LONG_SESSION_SCORING,
    },
    "long_session_jd": {
        "mode": "jd_resume", "difficulty": "mid", "max_turns": 16,
        "persona": MID_LEVEL_PERSONA,
        "active_skills": ["candidate-rhythm", "project-storytelling",
                          "knowledge-answer", "coding-answer"],
        "scoring": LONG_SESSION_SCORING,
        "extra_args": {"jd_id": None},  # 运行时从 DB 选一个 JD
    },
    # 错误识别
    "error_correction": {
        "mode": "free_practice", "difficulty": "mid", "max_turns": 8,
        "persona": MID_LEVEL_PERSONA,
        "active_skills": ["candidate-rhythm", "error-injection",
                          "project-storytelling", "knowledge-answer"],
        "scoring": ERROR_CORRECTION_SCORING,
    },
    # 结束策略
    "early_close_guard": {
        "mode": "free_practice", "difficulty": "mid", "max_turns": 5,
        "persona": MID_LEVEL_PERSONA,
        "active_skills": ["candidate-rhythm", "stall-and-clarify"],
        "scoring": END_POLICY_SCORING,
        "early_exit_check": lambda turns: _candidate_asks_to_end(turns),
    },
    "proper_end": {
        "mode": "free_practice", "difficulty": "senior", "max_turns": 10,
        "persona": SENIOR_PERSONA,
        "active_skills": ["candidate-rhythm", "project-storytelling",
                          "knowledge-answer", "coding-answer"],
        "scoring": END_POLICY_SCORING,
    },
    "insufficient_evidence": {
        "mode": "free_practice", "difficulty": "mid", "max_turns": 5,
        "persona": MID_LEVEL_PERSONA,
        "active_skills": ["candidate-rhythm", "stall-and-clarify"],
        "scoring": END_POLICY_SCORING,
        "early_exit_check": lambda turns: _interviewer_forces_close(turns),
    },
    "counter_question": {
        "mode": "free_practice", "difficulty": "senior", "max_turns": 6,
        "persona": SENIOR_PERSONA,
        "active_skills": ["candidate-rhythm", "project-storytelling",
                          "knowledge-answer"],
        "scoring": END_POLICY_SCORING,
    },
}
```

## 评分引擎

### 长程场景评分

```python
LONG_SESSION_SCORING = {
    "tool_call_rate": {
        "description": "至少 60% 的轮次有工具调用信号",
        "check": lambda m: m["tool_count"] / m["turn_count"] >= 0.6,
        "weight": 1.0,
    },
    "selected_question_present": {
        "description": "至少出现 1 次 selected_question 事件",
        "check": lambda m: len(m["selected_ids"]) >= 1,
        "weight": 1.0,
    },
    "asked_questions_recorded": {
        "description": "DB 中有 asked_questions 记录",
        "check": lambda m: len(m["asked_questions"]) >= 1,
        "weight": 1.0,
    },
    "no_cross_turn_duplicate_candidates": {
        "description": "跨轮候选题无重复",
        "check": lambda m: len(m["cross_turn_duplicate_candidates"]) == 0,
        "weight": 0.5,
    },
    "has_summary": {
        "description": "最后一轮包含结构化总结",
        "check": lambda m: m["has_summary"],
        "weight": 1.0,
    },
    "no_sse_errors": {
        "description": "零 SSE 错误事件",
        "check": lambda m: len(m["errors"]) == 0,
        "weight": 1.0,
    },
    "thinking_transparency": {
        "description": "至少 50% 的轮次有 thinking 事件",
        "check": lambda m: m["thinking_turns"] / m["turn_count"] >= 0.5,
        "weight": 0.5,
    },
}
```

### 错误纠正场景评分

```python
ERROR_CORRECTION_SCORING = {
    "bert_error_corrected": {
        "description": "BERT 生成式错误在输出层被纠正",
        "check": lambda m: _check_error_corrected(m, "bert"),
    },
    "faiss_error_corrected": {
        "description": "Faiss ACID 错误在输出层被纠正",
        "check": lambda m: _check_error_corrected(m, "faiss"),
    },
    "correction_in_output": {
        "description": "纠正出现在 assistant 回复中，而非仅在 thinking 中",
        "check": lambda m: m["correction_in_output_count"] > 0,
    },
}
```

### 结束策略场景评分

```python
END_POLICY_SCORING = {
    "early_close_refused": {
        "description": "过早收尾被拒绝",
        "check": lambda m: m.get("early_close_refused", False),
    },
    "proper_close_with_summary": {
        "description": "覆盖充分后给出结构化总结",
        "check": lambda m: m.get("has_summary", False),
    },
    "insufficient_evidence_noted": {
        "description": "证据不足被诚实标注",
        "check": lambda m: m.get("has_insufficient_evidence_marker", False),
    },
    "counter_question_answered": {
        "description": "候选人反问被回答",
        "check": lambda m: m.get("counter_question_answered", False),
    },
}
```

## 指标提取

```python
def extract_metrics(turns: list, conv_id: str) -> dict:
    all_events = [e for t in turns for e in t["events"]]
    return {
        "turn_count": len(turns),
        "event_counts": Counter(e["type"] for e in all_events),
        "tool_names": [e["data"]["tool"] for e in all_events if e["type"] == "tool_step"],
        "tool_count": sum(1 for e in all_events if e["type"] == "tool_step"),
        "selected_ids": [e["data"]["question_id"] for e in all_events 
                        if e["type"] == "selected_question"],
        "candidate_ids": extract_all_candidate_ids(all_events),
        "cross_turn_duplicate_candidates": find_cross_turn_duplicates(turns),
        "asked_questions": query_asked_questions_db(conv_id),
        "has_summary": any("面试总结" in t["assistant"] or "整体表现" in t["assistant"] 
                          for t in turns[-2:]),
        "thinking_turns": sum(1 for t in turns 
                             if any(e["type"] == "thinking" for e in t["events"])),
        "errors": [e for e in all_events if e["type"] == "error"],
        "thinking_chars": sum(len(e["data"].get("text", "")) 
                             for e in all_events if e["type"] == "thinking"),
    }
```

## 认证与 LLM 配置

```python
# 候选人 LLM（环境变量）
CANDIDATE_OPENAI_API_KEY = os.getenv("CANDIDATE_OPENAI_API_KEY")
CANDIDATE_LLM_BASE_URL = os.getenv("CANDIDATE_LLM_BASE_URL", "https://api.openai.com/v1")
CANDIDATE_LLM_MODEL = os.getenv("CANDIDATE_LLM_MODEL", "mimo-v2.5")

# 面试官认证
EVAL_USER_NAME = os.getenv("EVAL_USER_NAME", "sj")
EVAL_USER_PASSWORD = os.getenv("EVAL_USER_PASSWORD")
```

## 评测主循环

```python
async def run_evaluation(scenario: dict, auth_token: str):
    # 1. 创建对话
    conv_id = await create_conversation(scenario["mode"], scenario["difficulty"], auth_token)
    
    # 2. 初始化智能候选人
    candidate = SmartCandidateAgent(scenario["persona"], scenario["active_skills"])
    
    # 3. 评测循环
    turns = []
    for turn_idx in range(scenario["max_turns"]):
        # 候选人回复
        if turn_idx == 0:
            user_msg = scenario["persona"]["opening"]
        else:
            user_msg = await candidate.respond(interviewer_response)
        
        # 发送给面试官，收集 SSE 事件
        result = await send_message_and_collect(conv_id, user_msg, auth_token)
        interviewer_response = result["assistant"]
        
        turns.append({
            "turn": turn_idx,
            "user": user_msg,
            "assistant": interviewer_response,
            "events": result["events"],
            "latency_sec": result["latency_sec"],
        })
        
        # 提前退出检查
        if scenario.get("early_exit_check") and scenario["early_exit_check"](turns):
            break
    
    # 4. 计算指标和评分
    metrics = extract_metrics(turns, conv_id)
    scores = score_scenario(scenario, metrics)
    
    return {"turns": turns, "metrics": metrics, "scores": scores}
```

## Persona 配置

```python
MID_LEVEL_PERSONA = {
    "model": "mimo-v2.5",
    "resume_text": "211 硕士，2 年 RAG + Agent 开发经验。做过双路召回 + rerank 的 RAG 系统，用 LangChain/LangGraph 搭建过 Agent，Faiss 做向量检索，Redis 做缓存。",
    "ability_profile": """
- RAG 系统：熟练，做过双路召回 + rerank，了解 embedding 模型选型
- Agent 框架：熟悉 LangChain/LangGraph，了解 MCP 协议
- 向量数据库：用过 Faiss，了解 HNSW 原理，知道 IVF
- 数据库：MySQL 基础扎实（B+树、索引），Redis 常用（缓存、分布式锁）
- 算法：中等水平，常见题型（LRU、排序、二叉树）能做
- 系统设计：能做中等复杂度的设计
""",
    "opening": "大家好，我叫张明，211硕士毕业，2年RAG和Agent开发经验。最近一份工作做了一个企业级RAG系统，用双路召回加rerank提升检索质量，用LangGraph搭建了多Agent协作框架。",
}

SENIOR_PERSONA = {
    "model": "mimo-v2.5",
    "resume_text": "985 硕士，4 年后端 + 2 年 Agent 开发经验。从零搭建过 MCP 工具平台，对分布式系统（限流、熔断、幂等）有深入理解，发表过 CCF-B 论文。",
    "ability_profile": """
- Agent 平台：深入，从零搭建过 MCP Server + 工具市场
- 分布式系统：深入，限流（令牌桶/滑动窗口）、熔断、幂等重试
- 向量检索：深入，HNSW 构建原理、pgvector vs Faiss trade-off
- 数据库：深入，B+树叶分裂、聚簇索引、主键设计
- 算法：较强，能写 LRU Cache、滑动窗口、图搜索
- 系统设计：能做高并发场景设计（SSE 架构、Agent 编排）
""",
    "opening": "大家好，我叫李强，985硕士，4年后端加2年Agent开发。最近在做MCP工具平台，从协议设计到Server实现到工具市场，全链路都参与过。之前还做过分布式限流和熔断的基础设施。",
}
```

## 辅助函数定义

### `_check_error_corrected(metrics, error_type)`

判断特定技术错误是否在输出层被纠正：

```python
def _check_error_corrected(metrics: dict, error_type: str) -> bool:
    """检查面试官输出中是否包含对特定错误的纠正。
    
    实现方式：在最后 4 轮的 assistant 回复中搜索纠正关键词：
    - bert: "encoder" / "判别式" / "不是生成式" / "生成模型...不"
    - faiss: "不支持事务" / "不支持ACID" / "向量索引库"
    - lru: "Least Recently Used" / "最近最少使用"
    """
    correction_keywords = {
        "bert": ["encoder", "判别式", "不是生成式", "生成模型...不"],
        "faiss": ["不支持事务", "不支持ACID", "向量索引库"],
        "lru": ["Least Recently Used", "最近最少使用"],
    }
    keywords = correction_keywords.get(error_type, [])
    recent_assistant_texts = [t["assistant"] for t in metrics.get("recent_turns", [])]
    return any(kw in text for text in recent_assistant_texts for kw in keywords)
```

### `query_asked_questions_db(conv_id)`

直接读 SQLite DB 查询 `interview_asked_questions` 表：

```python
def query_asked_questions_db(conv_id: str) -> list[int]:
    """从 DB 查询该对话的 asked_questions 记录。"""
    import sqlite3
    db_path = os.getenv("DB_PATH", "backend/data/interview-boss.db")
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT question_id FROM interview_asked_questions WHERE conversation_id = ?",
        (conv_id,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]
```

### `_candidate_asks_to_end(turns)` / `_interviewer_forces_close(turns)`

结束策略场景的提前退出检查：

```python
def _candidate_asks_to_end(turns: list) -> bool:
    """检查候选人是否在最近一轮提出了结束请求。"""
    if not turns:
        return False
    last_user = turns[-1]["user"]
    end_signals = ["收尾", "结束", "不聊了", "就到这里", "想请教几个问题就收尾"]
    return any(sig in last_user for sig in end_signals)

def _interviewer_forces_close(turns: list) -> bool:
    """检查面试官是否已经给出了结构化总结（面试自然结束）。"""
    if not turns:
        return False
    last_assistant = turns[-1]["assistant"]
    close_signals = ["面试总结", "整体表现", "面试到这里结束"]
    return any(sig in last_assistant for sig in close_signals)
```

## 错误处理

- 每轮 SSE 事件中捕获 error 事件
- 超时保护：单轮 120s，整个场景 30min
- 失败轮次记录但不中断（继续下一轮）
- 最终报告中标注失败轮次和原因

## 报告格式

```markdown
# 评测报告：{scenario_id}
时间：{timestamp}
场景：{mode} · {difficulty} · {max_turns} 轮

## 评分
| 维度 | 得分 | 说明 |
|------|------|------|

## 面试流程
| 轮次 | 候选人摘要 | 面试官摘要 | 工具 | 耗时 |
|------|-----------|-----------|------|------|

## 关键事件
- T{n}: load_skill → {skill_name}

## 代表性输出
> T{n}: {interviewer_response[:200]}...
```

## 实现计划

1. 创建 `backend/app/agents/candidate/skills/` 下的 6 个 SKILL.md
2. 实现 `eval_interview_agent.py`（单文件，~600-700 行）
3. 验证：先跑 `error_correction` 场景（最短，8 轮），确认评分和报告正确
4. 扩展：跑 `long_session_mid`（16 轮），验证长程稳定性
5. 全量：`--scenario all` 跑全部 8 个场景

## 依赖

- 真实后端运行中（Docker 容器）
- 候选人 LLM API 可用（环境变量配置）
- 题库中有足够数据（现有 6000+ 题）
