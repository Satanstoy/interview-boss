# 修复计划

**Bug ID:** BUG-001
**日期:** 2026-05-10
**优先级:** P1

## 修复步骤

### 步骤 1: 修复 split_question 函数的来源查找逻辑

**文件:** `backend/app/routers/master_bank.py`
**行号:** 626-638
**修改类型:** 修正

**修改前:**
```python
# 找到该题的来源
split_sources = []
for item in orig_qs_src:
    if item.get('question') == original_q:
        split_sources = item.get('sources', [])
        break

# 创建新的独立题目（继承原题的 job_position）
admin_id = admin['id'] if isinstance(admin, dict) else admin.id
orig_job_position = row['job_position'] if 'job_position' in row.keys() else get_current_job_position()
cursor.execute(
    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, sources, original_questions, original_question_sources, ai_answer, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, 1, ?, '[]', '[]', NULL, ?, ?, 'approved', ?)",
    (original_q, row['cat1'], row['cat2'], row['tags'], row['difficulty'],
     json.dumps(split_sources, ensure_ascii=False), admin_id, admin_id, orig_job_position)
)
```

**修改后:**
```python
# 找到该题的来源
split_sources = []
for item in orig_qs_src:
    if item.get('question') == original_q:
        split_sources = item.get('sources', [])
        break

# 如果来源为空，从 questions_detail 查询原始来源
if not split_sources:
    qd_row = cursor.execute(
        "SELECT url, company, round, cat1, cat2, tags, diff_tag FROM questions_detail WHERE question = ? AND deleted_at IS NULL LIMIT 1",
        (original_q,)
    ).fetchone()
    if qd_row:
        split_sources = [{"url": qd_row['url'], "company": qd_row['company'], "round": qd_row['round']}]
        # 如果分类也为空，使用 questions_detail 的分类
        if not row['cat1'] and qd_row['cat1']:
            row = dict(row)
            row['cat1'] = qd_row['cat1']
            row['cat2'] = qd_row['cat2']
            row['tags'] = qd_row['tags'] or row['tags']

# 创建新的独立题目（继承原题的 job_position）
admin_id = admin['id'] if isinstance(admin, dict) else admin.id
orig_job_position = row['job_position'] if 'job_position' in row.keys() else get_current_job_position()
cursor.execute(
    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, sources, original_questions, original_question_sources, ai_answer, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, 1, ?, '[]', '[]', NULL, ?, ?, 'approved', ?)",
    (original_q, row['cat1'], row['cat2'], row['tags'], row['difficulty'],
     json.dumps(split_sources, ensure_ascii=False), admin_id, admin_id, orig_job_position)
)
```

### 步骤 2: 清理现有的孤立数据

**文件:** 数据库直接操作
**修改类型:** 删除

```sql
-- 删除孤立的空数据题目
DELETE FROM question_bank
WHERE id = 5877
  AND (sources = '[]' OR sources IS NULL)
  AND (cat1 = '' OR cat1 IS NULL)
  AND (original_questions = '[]' OR original_questions IS NULL);
```

## 验证方法

1. 运行 pytest 测试用例验证修复
2. 手动测试：点击"独立"按钮，检查新题目的来源和分类是否正确
3. 查询数据库验证：

```sql
SELECT id, question, cat1, cat2, sources
FROM question_bank
WHERE owner_id IS NULL AND deleted_at IS NULL
  AND (sources = '[]' OR cat1 = '' OR cat1 IS NULL);
```

预期结果：无返回行（所有题目都有完整的来源和分类）

## 回滚方案

如果修复失败，从备份恢复数据库：
```bash
cp /root/sj/interview-boss/backend/data/interview-boss.db.bak.build.* /root/sj/interview-boss/backend/data/interview-boss.db
```
