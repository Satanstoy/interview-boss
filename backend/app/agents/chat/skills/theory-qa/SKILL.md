---
name: theory-qa
description: "考察计算机基础八股文知识，追问底层原理和边界情况。Use when asking about CS fundamentals: OS, networking, databases, data structures, algorithms theory."
triggers: ["进程", "线程", "TCP", "HTTP", "MySQL", "Redis", "索引", "缓存", "锁", "内存", "IO"]
priority: 60
---

## When to use

候选人回答涉及计算机基础知识（操作系统、网络、数据库、数据结构、算法理论）时激活。

## Instructions

八股问题至少追问 2 层：
- 第 1 层：问概念/原理（"进程和线程的区别？"）
- 第 2 层：问应用场景或边界情况（"什么情况下会出问题？""实际项目中你怎么选？"）

## Rules

八股来源：
- 从项目回答中自然引出（"你用了 Redis，那缓存穿透怎么解决？"）
- 直接考察高频八股（MySQL 索引原理、TCP 三次握手、进程线程区别等）
