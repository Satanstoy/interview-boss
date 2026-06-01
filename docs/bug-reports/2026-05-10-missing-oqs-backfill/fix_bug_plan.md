# 修复计划

**Bug ID:** BUG-004
**日期:** 2026-05-10
**优先级:** P2

## 修复步骤

### 步骤 1: 保留独立题目的 oqs
**文件:** `backend/app/routers/master_bank.py:325-326`
**修改类型:** 删除一行

**修改前:**
```python
detail['original_questions'] = []
detail['original_question_sources'] = []
```

**修改后:**
```python
detail['original_questions'] = []
# 保留 original_question_sources 以便前端显示来源对应的原始题目文本
```

### 步骤 2: 新建题目包含 oqs
**文件:** `backend/app/db/operations.py:212-216`
**修改类型:** 修正

**修改前:**
```python
sources_json = json.dumps([...])
cursor.execute("INSERT INTO question_bank (..., sources, owner_id, ...) VALUES ...")
```

**修改后:**
```python
sources_json = json.dumps([...])
oqs_json = json.dumps([{"question": q_text, "sources": [...]}])
cursor.execute("INSERT INTO question_bank (..., sources, original_question_sources, owner_id, ...) VALUES ...")
```

### 步骤 3: 启动自动回填
**文件:** `backend/app/db/connection.py` init_db()
**修改类型:** 新增

新增两个修复逻辑：
1. 回填 oqs 为空但 sources 非空的题目（从 questions_detail 查找原始题目文本）
2. 修复 oqs 中 sources 为空数组的条目

## 验证方法
数据库检查：无 oqs 为空但 sources 非空的题目

## 回滚方案
从数据库备份恢复。
