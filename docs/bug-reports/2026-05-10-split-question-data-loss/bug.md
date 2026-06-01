# Bug 详细分析报告

**Bug ID:** BUG-001
**发现日期:** 2026-05-10
**状态:** 已确认

## 问题概述
当管理员点击"独立"按钮将题目从聚类中拆出时，新创建的独立题目会丢失来源(sources)和分类(cat1/cat2)信息。

## 根本原因分析

### BUG-001: 独立题目时来源和分类丢失

- **位置:** `backend/app/routers/master_bank.py:626-638`
- **症状:** 新创建的独立题目 `sources` 为空 `[]`，`cat1`/`cat2` 为空字符串
- **根因:** `split_question` 函数在查找题目来源时存在两个问题：

  **问题 1: 来源查找失败时未提供默认值**
  ```python
  # 第 626-630 行
  split_sources = []
  for item in orig_qs_src:
      if item.get('question') == original_q:
          split_sources = item.get('sources', [])
          break
  ```
  如果 `orig_qs_src` 为空或不包含匹配项，`split_sources` 将为空数组。

  **问题 2: 分类直接继承父聚类，未从 questions_detail 查询原始分类**
  ```python
  # 第 636-638 行
  cursor.execute(
      "INSERT INTO question_bank (...) VALUES (?, ?, ?, ?, ?, 1, ?, '[]', '[]', NULL, ?, ?, 'approved', ?)",
      (original_q, row['cat1'], row['cat2'], row['tags'], row['difficulty'],
       json.dumps(split_sources, ensure_ascii=False), admin_id, admin_id, orig_job_position)
  )
  ```
  如果父聚类的 `cat1`/`cat2` 为空（例如重建时 LLM 未分配分类），独立题目也会继承空分类。

- **影响:** 独立后的题目丢失来源和分类信息，导致：
  1. 前端无法显示题目来源（公司、轮次）
  2. 题目无法正确分类，影响筛选和检索
  3. 数据完整性受损

- **严重程度:** P1

## 复现步骤

1. 打开题库页面，找到一个包含多道原始题目的聚类
2. 点击某道原始题目旁边的"独立"按钮
3. 检查新创建的独立题目
4. **预期:** 新题目应有完整的来源和分类信息
5. **实际:** 新题目的来源为空，分类可能为空（取决于父聚类）

**数据库验证:**
```sql
-- 存在孤立的空数据题目
SELECT id, question, cat1, cat2, sources
FROM question_bank
WHERE owner_id IS NULL AND deleted_at IS NULL
  AND (sources = '[]' OR cat1 = '' OR cat1 IS NULL);
```

结果：
```
5877|React模式和Plan and Solve模型有什么区别？|||[]|[]|[]
```

## 修复建议

1. **来源查找失败时，从 questions_detail 查询原始来源**
2. **分类为空时，从 questions_detail 查询原始分类**
3. **清理现有的孤立数据**（ID 5877）
