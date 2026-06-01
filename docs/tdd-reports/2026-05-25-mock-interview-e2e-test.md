# 模拟面试 E2E 测试报告

**测试时间**: 2026-05-25 13:35 ~ 13:55 (约 20 分钟)
**测试账号**: sj (admin, 岗位: agent开发/大模型应用开发/大模型开发)
**对话模式**: free_practice (自由练习)
**对话 ID**: `253783e1-5bc3-4b08-8a9f-de4d463618d2`

---

## 一、测试概览

以施杰身份完成了一次完整的模拟面试，共 **12 轮有效对话**（13 轮中 1 轮因 JWT 过期失败），覆盖了：

| 轮次 | 候选人回答主题 | 面试官追问方向 |
|------|--------------|--------------|
| R1 | 自我介绍 | 项目架构深挖 |
| R2 | 多 Agent 系统架构 | LangGraph 手动编排原因 |
| R3 | 流式输出 + 手动编排 | LangGraph vs LangChain |
| R4 | LangGraph 区别 | 记忆管理机制设计 |
| R5 | 5 级渐进式压缩 | 压缩细节追问（2 个子问题） |
| R6 | 压缩实现 + session notes | GLEAR 项目（从记忆中提取） |
| R7 | GLEAR 项目 + 图算法 | LRU Cache 算法题 |
| R8 | OrderedDict 实现 | 要求手写双向链表 |
| R9 | 手写 LRU Cache | 边界情况 + 线程安全 |
| R10 | capacity=0 + 分片锁 | 向量索引算法 |
| R11 | HNSW/IVF/PQ | MySQL B+ 树索引 |
| R12 | B+ 树双向链表 + HR 话题 | 拒绝 HR，追问千万级检索系统设计 |

---

## 二、Skill 调用分析

### 2.1 Skill 激活记录（来自后端日志）

| 轮次 | 时间 | 激活的 Skills | 触发说明 |
|------|------|--------------|---------|
| R1 | 13:37:35 | `interview-rhythm`, `adaptive-difficulty`, `project-deep-dive`, `theory-qa` | 自我介绍中含"LangGraph"、"RAG"等关键词触发 project-deep-dive |
| R2 | 13:38:29 | `interview-rhythm`, `adaptive-difficulty`, `project-deep-dive` | 项目架构讨论，project-deep-dive 持续活跃 |
| R3 | 13:39:16 | `interview-rhythm`, `adaptive-difficulty`, `project-deep-dive` | 继续项目讨论 |
| R4 | 13:40:13 | `interview-rhythm`, `adaptive-difficulty`, `project-deep-dive`, `hr-soft-skills` | hr-soft-skills 被意外触发（可能因消息中含"适合"等词） |
| R5 | 13:41:25 | `interview-rhythm`, `adaptive-difficulty`, `project-deep-dive` | 记忆管理讨论 |
| R6 | 13:43:49 | `interview-rhythm`, `adaptive-difficulty`, `project-deep-dive` | GLEAR 项目讨论 |
| R7 | 13:45:46 | `interview-rhythm`, `adaptive-difficulty`, `project-deep-dive`, `algorithm-coding` | LRU Cache 题触发 algorithm-coding |
| R8 | 13:47:06 | `interview-rhythm`, `adaptive-difficulty`, `algorithm-coding` | 手写代码要求，project-deep-dive 消退 |
| R9 | 13:48:20 | `interview-rhythm`, `adaptive-difficulty`, `algorithm-coding` | 边界情况追问 |
| R10 | 13:49:30 | `interview-rhythm`, `adaptive-difficulty`, `theory-qa`, `algorithm-coding` | 向量索引理论触发 theory-qa |
| R11 | 13:50:44 | `interview-rhythm`, `adaptive-difficulty`, `project-deep-dive`, `theory-qa`, `algorithm-coding` | B+ 树理论，5 个 skill 同时活跃 |
| R12 | 13:55:11 | `interview-rhythm`, `adaptive-difficulty`, `algorithm-coding`, `hr-soft-skills` | HR 话题触发 hr-soft-skills |

### 2.2 Skill 评估

| Skill | 表现 | 评分 |
|-------|------|------|
| **interview-rhythm** (always_active) | 全程活跃，确保了项目/算法/理论的交替节奏 | A |
| **adaptive-difficulty** (always_active) | 全程活跃，LRU Cache 从 OrderedDict → 手写 → 边界+线程安全体现了递进式难度 | A |
| **project-deep-dive** | R1-R7 持续活跃，成功驱动了 3-5 层深挖（架构 → 手动编排原因 → 流式实现 → LangGraph 区别 → 记忆管理 → 压缩细节） | A |
| **algorithm-coding** | R7-R12 活跃，成功要求候选人口述 + 手写代码 + 边界处理 + 线程安全 | A |
| **theory-qa** | R10-R11 活跃，覆盖了向量索引和数据库索引两个理论主题 | B+ |
| **hr-soft-skills** | R4 意外触发（误判），R12 正确触发但 AI 面试官拒绝了 HR 话题继续追问技术 | C |

**问题**: hr-soft-skills 在 R12 激活后，AI 面试官仍拒绝讨论 HR 话题（"公司情况先不聊。回到技术"），说明 skill 的 behavioral instruction 未能有效影响 LLM 的回复策略。

---

## 三、RAG 检索分析

### 3.1 检索统计

- **总 AI 回复数**: 13 条
- **触发 RAG 检索的回复**: 8 条 (61.5%)
- **直接回复（无 RAG）**: 5 条 (38.5%)

### 3.2 RAG 检索详情

| 轮次 | 检索数量 | 检索到的题目 | 相关度 |
|------|---------|------------|--------|
| R1→AI | 3 | multi agent 优劣、Agent 核心模块、Agent 检索机制 | **高** - 完美匹配 Agent 话题 |
| R2→AI | 3 | 同上 3 题 | 中 - 重复了上轮的检索结果 |
| R3→AI | 1 | LangGraph 和 LangChain 区别 | **高** - 精确匹配 |
| R4→AI | 3 | LangGraph 区别、Agent 评估、Agent 记忆管理 | **高** - 记忆管理题完美匹配 |
| R5→AI | 2 | Agent 记忆管理、OpenClaw vs Hermes | 中 - 第 2 题不太相关 |
| R6→AI | 3 | Agent 评估、LangGraph 区别、Agent 记忆管理 | 中 - 偏 Agent 话题，与算法题不太匹配 |
| R7→AI | 2 | Python 依赖管理、排行榜查询 | **低** - 与 LRU Cache 算法题不匹配 |
| R8→AI | 2 | 同上 | **低** - 算法题场景下检索结果不相关 |

### 3.3 RAG 评估

**优点**:
- 项目讨论阶段（R1-R5）检索质量高，"Agent"、"LangGraph"、"记忆管理"等关键词精准命中
- 参考题目按钮在前端正确展示，用户可点击查看相关题目

**问题**:
1. **算法题场景 RAG 检索质量差**: R7-R8 检索到 "Python 依赖包管理" 和 "排行榜查询"，与 LRU Cache 完全无关。原因可能是 FTS5 的 search_query 生成逻辑对算法题场景不够精准
2. **检索结果重复**: R1 和 R2 检索到了完全相同的 3 道题，缺少去重机制
3. **R6 检索与题型不匹配**: GLEAR 项目讨论后紧接着出 LRU Cache 算法题，但 RAG 检索仍返回 Agent 相关题

---

## 四、记忆提取分析

从 `chat_memories` 表中检测到本次面试提取的记忆：

| 类型 | 内容 | 评价 |
|------|------|------|
| **strength** | "对 HNSW 向量索引的核心参数（M 和 ef）及其 trade-off 有清晰的理解" | **准确** - R11 回答确实展示了对 HNSW 的深入理解 |
| **weakness** | "面试中未展示手写代码实现 LRU Cache 的能力" | **不准确** - R9 候选人实际手写了完整的 LRU Cache 代码，但记忆提取可能因为代码在 markdown code block 中而未正确识别 |

**问题**: 记忆提取对代码块内容的理解有缺陷，误判了候选人的编码能力。

---

## 五、对话质量评估

### 5.1 面试官表现

| 维度 | 评分 | 说明 |
|------|------|------|
| 追问深度 | **A** | 每个话题都能追问 2-3 层，如 LRU: OrderedDict → 手写 → 边界+线程安全 |
| 话题切换 | **A** | 自然地在项目、算法、理论之间切换，体现了 interview-rhythm skill 的效果 |
| 问题质量 | **A** | 问题专业且有针对性，如 "100 条消息截断与压缩的矛盾" |
| 用户体验 | **B** | 流式输出正常工作，SSE 推送流畅 |
| HR 转换 | **C** | 拒绝了候选人的 HR 话题请求，继续追问技术 |

### 5.2 回复质量

- 所有 AI 回复均结构清晰、长度适中
- 代码问题能要求手写实现而非仅口述
- 对候选人回答的评价及时（"代码正确，实现清晰"、"这个设计考虑得挺系统化的"）

---

## 六、发现的问题

### P0 - 严重

| # | 问题 | 复现路径 | 影响 |
|---|------|---------|------|
| 1 | **JWT Token 15 分钟过期导致对话中断** | 进行超过 15 分钟的面试 | 面试中断，用户需刷新页面重新登录，最后一条消息丢失 |

### P1 - 重要

| # | 问题 | 说明 |
|---|------|------|
| 2 | **前端代码块未渲染** | 候选人发送的 markdown 代码块在前端显示为纯文本（含 ``` 标记），而非格式化代码 |
| 3 | **算法题场景 RAG 检索不相关** | 算法题（LRU Cache）的检索结果为 "Python 依赖包管理"、"排行榜查询" 等无关题目 |
| 4 | **记忆提取误判编码能力** | 候选人成功手写了 LRU Cache，但系统提取的记忆是 "未展示手写代码能力" |
| 5 | **hr-soft-skills 效果不佳** | skill 激活后 AI 仍拒绝 HR 话题，instruction 未有效约束 LLM 行为 |

### P2 - 一般

| # | 问题 | 说明 |
|---|------|------|
| 6 | **RAG 检索结果重复** | R1 和 R2 检索到完全相同的 3 道题，缺少去重 |
| 7 | **hr-soft-skills 误触发** | R4 在纯技术讨论中被触发（可能因 "适合" 等词触发了关键词匹配） |
| 8 | **Session notes JSON 解析错误** | 后端日志中 `session_notes` 字段存在 JSON 解析异常 |
| 9 | **简历记忆重复写入** | `chat_memories` 中存在 9 条相同的 resume 类型记忆（仅最新 1 条 active） |

---

## 七、LLM 调用统计

- **LLM 提供商**: `token-plan-cn.xiaomimimo.com` (OpenAI 兼容接口)
- **每次用户消息的 LLM 调用数**: 约 3 次
  - 1 次：意图分类 + 记忆选择 + 搜索查询生成（merged call）
  - 1 次：回复生成（streaming）
  - 1 次：记忆提取（async, fire-and-forget）
- **总 LLM 调用次数**: 约 36 次（12 轮 x 3 次/轮）
- **所有调用均成功**: 全部返回 HTTP 200

---

## 八、改进建议

### 高优先级

1. **JWT 过期问题**: 前端应实现 token 自动刷新机制（15 分钟过期前自动调用 `/api/auth/refresh`），或在 SSE 流中检测 401 响应后自动刷新重试
2. **代码块渲染**: 前端 markdown 渲染器需正确处理候选人消息中的代码块
3. **记忆提取优化**: 提取 prompt 需能理解 markdown 代码块中的实际代码内容

### 中优先级

4. **算法题 RAG 优化**: 当 intent 为 `practice_request` 且涉及算法题时，应跳过 RAG 检索或使用专门的算法题 search_query
5. **hr-soft-skills 强化**: 增加更强制的 instruction，如 "当候选人主动询问团队/职业发展时，必须回应"
6. **RAG 去重**: 在检索结果中加入已展示题目的去重逻辑

### 低优先级

7. **简历记忆去重**: 添加 upsert 逻辑避免重复写入相同的简历摘要
8. **Session notes 异常处理**: 增加 JSON 解析的容错逻辑

---

## 九、总体评价

| 维度 | 评分 | 说明 |
|------|------|------|
| 面试流程完整性 | **B+** | 12 轮对话覆盖了项目、算法、理论三大类，但缺少独立的 HR 环节 |
| Skill 系统 | **A-** | 6 个 skill 中 5 个表现优秀，hr-soft-skills 需要改进 |
| RAG 检索 | **B** | 项目讨论场景优秀，算法题场景较差 |
| 记忆系统 | **B** | 长期记忆召回（GLEAR 项目）准确，但编码能力提取有误 |
| 用户体验 | **B+** | 流式输出正常，但代码块渲染和 Token 过期影响体验 |
| **综合** | **B+** | 核心功能运作良好，有几个需修复的 P0/P1 问题 |
