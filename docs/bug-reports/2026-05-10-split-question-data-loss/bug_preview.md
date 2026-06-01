# Bug 预览报告

**日期:** 2026-05-10
**问题:** 题目从聚类中独立出来时，来源(sources)和分类(cat1/cat2)会丢失
**严重程度:** High

## 初步诊断

### 问题现象
当管理员点击"独立"按钮将题目从聚类中拆出时，新创建的独立题目会出现以下问题：
1. **来源丢失**: `sources` 字段为空 `[]`，导致题目没有任何来源信息
2. **分类丢失**: `cat1` 和 `cat2` 字段为空字符串，导致题目没有分类
3. **原始题目丢失**: `original_questions` 和 `original_question_sources` 为空 `[]`

**数据库证据** (ID 5877):
```
5877|React模式和Plan and Solve模型有什么区别？|||[]|[]|[]
```
该题目与 ID 5880 是同一道题，但 ID 5880 有完整的数据：
```
5880|React模式和Plan and Solve模型有什么区别？|B.Agent与LLM应用|B1.Agent架构与范式|[3个来源]|[4个原始题目]|[完整来源映射]
```

### 根本原因
在 `split_question` 函数中（`master_bank.py:626-630`），从 `original_question_sources` 查找题目来源时，使用精确匹配：

```python
split_sources = []
for item in orig_qs_src:
    if item.get('question') == original_q:
        split_sources = item.get('sources', [])
        break
```

如果 `original_question_sources` 为空或不包含匹配项，`split_sources` 将为空数组。

### 影响范围
- **功能:** 题目独立功能（split-question API）
- **用户:** 管理员用户
- **数据:** 影响数据完整性，独立后的题目丢失来源和分类信息

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Medium | 独立功能可用但结果不正确 |
| 数据完整性 | High | 独立后的题目丢失关键元数据 |
| 安全风险 | Low | 无安全风险 |
