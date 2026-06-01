# Adaptive-Difficulty Skill Playwright 测试报告

**日期:** 2026-05-24
**测试方式:** Playwright 模拟施杰身份，6 轮自由练习面试
**测试目标:** 验证 adaptive-difficulty skill 的自适应追问效果

## 测试结果

### 6 轮对话记录

| 轮次 | 候选人回答质量 | AI 追问策略 | 自适应效果 |
|------|-------------|-------------|-----------|
| R1 | ⭐⭐⭐⭐ 好（提到 RAG/Agent 项目 + 数据） | 追问检索优化细节（漏斗第 2 层） | ✅ 自然升级 |
| R2 | ⭐⭐⭐⭐⭐ 很好（混合检索 + chunking + query rewriting） | 追问 RRF 实现 + trade-off（漏斗第 3 层） | ✅ 继续升级 |
| R3 | ⭐⭐⭐⭐⭐ 很好（RRF 公式 + 对比分析） | 切话题到 Redis 热 Key | ✅ 穿插切换 |
| R4 | ⭐⭐ 差（"记不太清"，承认没经验） | 抓住"本地缓存"缩小范围追问 | ✅ 降级引导 |
| R5 | ⭐⭐⭐ 中等（本地缓存说对了，一致性提到但不深） | 切话题到 Linux 运维 | ✅ 自然切话题 |
| R6 | ⭐⭐⭐ 中等（基础运维知道，承认经验不足） | 出 LRU 算法题 | ✅ 穿插切换 |

### Skill 激活记录

| 轮次 | Active Skills | 评价 |
|------|---------------|------|
| R1 | interview-rhythm, adaptive-difficulty, project-deep-dive, theory-qa | ✅ 正确 |
| R2 | interview-rhythm, adaptive-difficulty, project-deep-dive | ✅ 正确 |
| R3 | interview-rhythm, adaptive-difficulty | ⚠️ project-deep-dive 缺失（仍在 RAG 话题） |
| R4 | interview-rhythm, adaptive-difficulty, project-deep-dive, theory-qa | ✅ 正确 |
| R5 | interview-rhythm, adaptive-difficulty, theory-qa | ✅ 正确 |
| R6 | interview-rhythm, adaptive-difficulty, project-deep-dive | ✅ 正确 |

**adaptive-difficulty 覆盖率: 100%（6/6 轮）** ✅

### 自适应行为分析

#### 1. 升级追问（回答好时）✅
- R1→R2: 候选人提到混合检索 → AI 追问"具体怎么优化的？关键改动是什么？"
- R2→R3: 候选人详细回答了三点 → AI 追问"RRF 具体怎么实现的？为什么不用加权求和？"
- **评价**: 追问自然，从回答中找追问点，不是生硬跳转。符合漏斗模型。

#### 2. 降级引导（回答差时）✅
- R4: 候选人说"记不太清" → AI 没有继续追问热 Key 的高难度细节
- 而是抓住候选人提到的"本地缓存"，缩小范围问"本地缓存具体怎么做？"
- **评价**: 这是最关键的改进点。之前的面试官可能会继续追问"那缓存穿透呢？缓存雪崩呢？"，但现在的 AI 选择了给台阶。

#### 3. 话题切换（回答中等时）✅
- R5: 候选人回答了本地缓存（中等） → AI 切换到 Linux 运维
- R6: 候选人承认运维经验不足 → AI 出 LRU 算法题
- **评价**: 切换自然，不会在一个弱项上死磕。

#### 4. 穿插式节奏 ✅
- R1-R3: 项目深挖（RAG 项目）
- R4-R5: 八股穿插（Redis 热 Key + 本地缓存）
- R6: 算法手撕（LRU Cache）
- **评价**: 完美符合 interview-rhythm 的穿插式节奏。

### 与之前面试的对比

| 维度 | 之前（无 adaptive-difficulty） | 现在（有 adaptive-difficulty） |
|------|------------------------------|-------------------------------|
| 追问深度 | 固定深度，不管回答好坏 | 根据回答质量调整 |
| 卡壳处理 | 继续追问，候选人压力大 | 给台阶，缩小范围 |
| 话题切换 | 有时死磕一个问题 | 自然切换，不强求 |
| 整体节奏 | 线性推进 | 穿插式，有变化 |

### 结论

**adaptive-difficulty Phase 1（纯 instruction）效果良好。** 不需要改架构，LLM 足够聪明，能根据 instruction 自行判断难度调整。追问不生硬，降级自然。

**不需要进入 Phase 2（state 追踪）。** Phase 1 的 instruction-only 方案已经达到了预期效果。

### 改进建议

1. **R3 的 project-deep-dive 缺失** — 候选人回答 RRF 时没有提到"项目"等触发词，但仍在 RAG 话题中。可以考虑在 RAG 话题连续时保持 project-deep-dive 激活。
2. **可以加一个"压力追问"模式** — 当候选人连续 3 轮都回答得很好时，AI 可以故意抛出反对意见或刁钻问题，考察应变能力。
