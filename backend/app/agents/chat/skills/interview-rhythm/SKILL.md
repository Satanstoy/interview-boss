---
name: interview-rhythm
description: "控制面试的穿插式节奏，确保项目深挖、八股问答、算法手撕交替进行。Always active during interviews — controls overall flow and topic transitions."
triggers: ["面试", "开始", "继续", "下一个"]
priority: 100
always_active: true
---

## When to use

面试进行中时始终激活，控制整体节奏和话题切换。

## Instructions

不要按固定模板走，采用穿插式节奏：

1. **项目深挖**（核心，占 50%+ 时间）：从候选人自我介绍或简历中的项目开始，连续追问 3-5 层
2. **八股穿插**（占 25% 时间）：从项目中自然引出基础问题（如"你用了 Redis，那缓存穿透怎么解决？"），或直接考察
3. **算法/手撕代码**（占 15% 时间）：要求候选人写代码或描述算法思路
4. **系统设计**（占 10% 时间，可选）

## Rules

穿插规则：项目深挖 2 题后，切一道八股；八股之后可以继续项目或出算法题。不要连续问同一类型超过 3 题。
