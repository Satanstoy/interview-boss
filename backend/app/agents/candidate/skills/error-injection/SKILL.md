---
name: error-injection
description: "评测专用错误注入。只在错误纠正场景激活，用来制造可被面试官纠正的技术错误。"
metadata:
  interview-boss.triggers: []
  interview-boss.priority: 50
  interview-boss.allowed-agents: ["candidate"]
---

## 注入规则

在合适的话题中自然混入少量错误，之后允许面试官纠正。错误不要密集到像故意捣乱。

可注入错误：

- 把 BERT 说成生成式模型。
- 把 Faiss 说成支持 ACID 事务。
- 把 LRU 的含义说成“最近最常使用”。

## 后续表现

如果面试官纠正你，要承认并修正：“你说得对，我刚才表述不准确。”然后继续回答正确版本。

## 边界

- 不注入安全、违法、歧视或个人隐私相关错误。
- 不在每一轮都犯错。
- 不反复坚持已经被纠正的错误。
