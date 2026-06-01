# Skills 优化后 Playwright 模拟面试测试报告

**日期:** 2026-05-25
**测试方式:** Playwright 模拟施杰身份，14 轮自由练习面试
**优化内容:** 基于 Exa 搜索的 SKILL.md 最佳实践优化 6 个 skill

## 优化前后对比

| 优化项 | 优化前 | 优化后 |
|--------|--------|--------|
| Description | 简短描述 | Pushy 风格，含 MUST 指令 |
| "When to use" | 在 body 中 | 移至 frontmatter description |
| WHY 解释 | 无 | 每个 skill 加了 WHY 理由 |
| Examples | 无 | 加了具体示例序列 |
| Boundaries | 无 | 加了"不要做"清单 |
| Triggers | 过于宽泛 | 收窄精准 |

## 14 轮对话 Skill 行为记录

| 轮次 | AI 问题摘要 | 涉及 Skill | 评价 |
|------|-----------|-----------|------|
| R1 | 自我介绍 | interview-rhythm | ✅ 正确开场 |
| R2 | RAG 整体架构（Layer 1） | project-deep-dive | ✅ 项目深挖启动 |
| R3 | chunk size 参数实验（Layer 2） | project-deep-dive, adaptive-difficulty | ✅ 难度递增 |
| R4 | PDF 解析问题（Layer 3） | project-deep-dive, adaptive-difficulty | ✅ 继续递增 |
| R5 | RRF vs 加权融合（Layer 2） | project-deep-dive, adaptive-difficulty | ✅ 从用户回答中抓取新锚点 |
| R6 | k=60 调优（Layer 3） | project-deep-dive, adaptive-difficulty | ✅ 深入追问 |
| R7 | HNSW M/ef trade-off（Layer 4） | project-deep-dive, adaptive-difficulty | ✅ 压力测试层 |
| R8 | HNSW 内存/延迟（Layer 4 续） | project-deep-dive, adaptive-difficulty | ✅ 继续压力测试 |
| R9 | **MySQL B+树 vs B树** | **interview-rhythm, theory-qa** | ✅ **话题切换成功！** |
| R10 | InnoDB 聚簇索引 vs 二级索引 | theory-qa, adaptive-difficulty | ✅ 理论深挖 Layer 2 |
| R11 | **手写 LRU Cache** | **algorithm-coding** | ✅ **算法题触发** |
| R12 | LRU capacity=0 + 线程安全 | algorithm-coding, project-deep-dive | ⚠️ 两个问题合一 |
| R13 | 知识图谱证据链路径挖掘 | project-deep-dive | ✅ 第二个项目深挖 |
| R14 | 路径定义 + 剪枝规则 | project-deep-dive | ✅ 继续追问 |

## 关键发现

### 1. interview-rhythm 话题切换 ✅ 部分成功

**成功案例（R9）：**
- AI 主动说："好，项目部分先到这里。换个话题，考察下基础。"
- 从项目深挖（R2-R8，连续 7 轮）切换到理论问答
- 优化后的 SKILL.md 中"50% 项目深挖"比例指令生效

**失败案例（R12-R14）：**
- R12 中 AI 把算法边界问题和新项目问题合并到一条消息
- R13-R14 继续深挖第二个项目（知识图谱），没有切换到其他话题
- 候选人在 R14 主动问"职业发展路径"，AI 回复"先聊技术，职业发展的问题最后再说"
- **hr-soft-skills 没有被触发**

### 2. adaptive-difficulty 难度递增 ✅ 工作良好

项目深挖阶段的难度递增非常清晰：

```
R2: Layer 1（架构）→ R3: Layer 2（决策原因）→ R4: Layer 3（困难与解决）→ R7-R8: Layer 4（压力测试）
```

AI 的追问模式完全符合 SKILL.md 中定义的漏斗模型：
- 好的回答 → 升级到下一层
- 追问具体数字（"百万级向量，内存占了多少？"）
- 追问 trade-off（"M 和 ef 怎么理解它们的 trade-off？"）

### 3. project-deep-dive 深挖质量 ✅ 优秀

- 对 RAG 项目深挖了 7 层（R2-R8），覆盖架构→参数→实现→优化
- 对知识图谱项目深挖了 2 层（R13-R14）
- AI 正确使用候选人的回答作为追问锚点（"你提到 chunk size 512..."）
- 要求具体数字（"Recall@5"、"P99 延迟"）

### 4. theory-qa 理论问答 ✅ 工作良好

- R9: B+树 vs B树 vs 跳表（Layer 1 概念）
- R10: 聚簇索引 vs 二级索引 + 回表 + 覆盖索引（Layer 2 应用）
- 完美执行了 drill-down 模式：从概念到应用，2 层深度

### 5. algorithm-coding 算法题 ✅ 工作良好

- R11: 要求手写 LRU Cache（"用你熟悉的语言，写出关键代码就行"）
- R12: 代码审查后追问边界情况（capacity=0）和线程安全
- 完全符合 SKILL.md 的流程：要求代码 → 边界追问 → 复杂度分析

### 6. hr-soft-skills ❌ 未触发

**问题：** 候选人在 R14 主动问"职业发展路径"和"团队技术氛围"，AI 回复"先聊技术，职业发展的问题最后再说"，拒绝进入 HR 阶段。

**根因分析：**
- hr-soft-skills 的 triggers 包含"职业规划"、"团队"，候选人的消息应该触发
- 但 AI 面试官的 system prompt 中可能有更强的"技术优先"指令
- hr-soft-skills 优先级只有 30，可能被其他高优先级 skill 压制
- 面试阶段判定逻辑（`_determine_interview_phase()`）可能还没有进入 wrap-up 阶段

## AI 面试官行为分析

| 维度 | 评分 | 说明 |
|------|------|------|
| 话题覆盖 | ⭐⭐⭐⭐ | 项目→理论→算法 覆盖良好，缺 HR |
| 追问深度 | ⭐⭐⭐⭐⭐ | 项目 7 层追问，理论 2 层，算法边界 |
| 话题切换 | ⭐⭐⭐ | R9 成功切换，但 R12 后又回到项目 |
| 一次一题 | ⭐⭐ | R12 把两个问题合一，违反规则 |
| HR 过渡 | ⭐ | 明确拒绝进入 HR 阶段 |
| 参考题目 | ⭐⭐⭐⭐ | 正确引用题库中的相关题目 |

## 待修复问题

### P0: hr-soft-skills 无法触发

**问题：** 候选人主动提及"职业发展"、"团队氛围"，AI 仍拒绝进入 HR 阶段。

**修复方案：**
1. 检查 `_determine_interview_phase()` 的阶段判定逻辑，确保 10+ 轮后进入 wrap-up
2. 在 system prompt 中增加 HR 阶段的强制过渡指令
3. 提高 hr-soft-skills 的优先级（30→50），或在 wrap-up 阶段设为 always_active

### P1: 一次一题规则违反

**问题：** R12 中 AI 把算法边界问题和新项目问题合并到一条消息。

**修复方案：**
- 在 interview-rhythm 的 body 中强化"一次只问一个问题"的指令
- 增加示例：展示正确的一次一题行为

### P2: 第二个项目过度深挖

**问题：** R13-R14 继续深挖知识图谱项目，没有切换到理论或算法。

**修复方案：**
- 在 interview-rhythm 中明确"每个项目最多 3-4 轮"的限制
- 增加"第二个项目最多 2 轮"的规则

## 与优化前对比

| 指标 | 优化前 | 优化后 | 变化 |
|------|--------|--------|------|
| interview-rhythm 覆盖率 | 100% | 100% | 持平 |
| 话题切换 | R7 切换到算法 | R9 切换到理论 | ✅ 更自然 |
| algorithm-coding 误触发 | 9/10 轮 | 1/14 轮 | ✅ 大幅改善 |
| project-deep-dive 稳定性 | R3 缺失 | 全程稳定 | ✅ 改善 |
| 难度递增 | 无明显梯度 | Layer 1→4 清晰 | ✅ 明显改善 |
| HR 阶段触发 | R10 触发 | R14 未触发 | ❌ 退化 |

## 结论

优化后的 Skills 系统在项目深挖、理论问答、算法编码三个核心场景表现优秀：
- **adaptive-difficulty** 的漏斗模型效果显著，难度递增清晰
- **project-deep-dive** 的深挖质量很高，能从候选人回答中抓取追问锚点
- **theory-qa** 的 drill-down 模式工作正常
- **algorithm-coding** 的代码→边界→复杂度流程完整
- **interview-rhythm** 的话题切换在 R9 成功触发

主要问题是 **hr-soft-skills 无法触发**，需要检查面试阶段判定逻辑和 skill 优先级配置。这是下一轮优化的重点。
