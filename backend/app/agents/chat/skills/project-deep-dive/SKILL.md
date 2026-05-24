---
name: project-deep-dive
description: "对候选人的项目经历进行 3-5 层深度追问，考察架构决策、技术选型、困难解决。Use when the candidate mentions a project, internship, or technical implementation."
triggers: ["项目", "实习", "做了", "开发", "设计", "系统", "框架", "GLEAR", "Agent", "RAG"]
priority: 80
---

## When to use

候选人提到项目、实习、技术实现等内容时激活。

## Instructions

每个项目问题至少追问 3 层：
- 第 1 层：问架构/方案（"你这个系统怎么设计的？"）
- 第 2 层：问决策原因（"为什么选这个方案？考虑过其他方案吗？"）
- 第 3 层：问困难和解决（"遇到什么问题？怎么解决的？效果如何？"）
- 第 4 层（可选）：压力追问（"如果规模扩大 10 倍呢？你这个方案还行吗？"）

## Rules

追问要点：
- 要求具体数字（准确率、延迟、QPS）
- 追问 trade-off（为什么不用 X？）
- 追问个人贡献（你具体负责哪部分？）
