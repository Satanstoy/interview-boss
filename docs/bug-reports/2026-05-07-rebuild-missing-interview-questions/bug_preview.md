# Bug 预览报告

**日期:** 2026-05-07
**问题:** 重建题库时无法正确处理面经库中的题目——`questions_detail` 表缺少 `job_position` 列，导致重建时所有岗位的面经题目被混入当前岗位题库
**严重程度:** Critical

## 初步诊断

### 问题现象
用户在前端点击"重建题库"按钮后，面经库中的题目无法被正确分析和归类到对应岗位。具体表现为：
1. 所有面经库的题目（不论属于哪个岗位）都被加载并重建到当前选中的岗位题库中
2. 属于其他岗位的面经题目被错误地混入当前岗位
3. 已有的 AI 答案可能因为聚类后题目文本变化而丢失

### 根本原因
数据库设计缺陷：`questions_detail` 表（存储从面经提取的单道题目）没有 `job_position` 列，也没有任何方式关联到岗位信息。

`_load()` 函数（`master_bank.py:167-172`）从 `questions_detail` 加载数据时无法按岗位过滤：
```python
raw = conn.execute(
    "SELECT qd.id, qd.question, qd.cat1, qd.cat2, qd.tags, qd.diff_tag, qd.url, qd.company, qd.round "
    "FROM questions_detail qd WHERE qd.question IS NOT NULL AND qd.question != ''"
).fetchall()  # 没有 job_position 过滤！
```

而 `_save()` 写入时统一使用 `current_pos`（第 339-341 行），将所有题目都归入当前岗位。

### 影响范围
- **功能:** 重建题库功能完全失效，无法按岗位隔离面经题目
- **用户:** 所有使用多岗位功能的管理员用户
- **数据:** 导致跨岗位数据污染，可能丢失已有 AI 答案

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Critical | 重建题库功能无法正确工作 |
| 数据完整性 | High | 跨岗位题目污染，答案丢失 |
| 安全风险 | Low | 无直接安全风险 |
