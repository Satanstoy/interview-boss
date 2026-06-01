# Bug 详细分析报告

**Bug ID:** INDENT-001
**发现日期:** 2026-05-07
**状态:** 已确认

## 问题概述

用户在前端输入用户名和密码后，系统显示"服务暂时不可用"错误。经排查，根本原因是后端 Python 服务无法启动。

## 根本原因分析

### 直接原因
`backend/app/routers/master_bank.py` 文件第 922-954 行存在 Python 缩进错误（IndentationError），导致 uvicorn 无法加载 FastAPI 应用。

### 错误代码
```python
# 第 922 行
async def _gen_one(idx, qid, question_text):
nonlocal generated, failed, done_count  # ❌ 错误：缺少缩进
async with semaphore:
try:
# ... 更多错误缩进的代码
```

### 正确代码应该是
```python
async def _gen_one(idx, qid, question_text):
    nonlocal generated, failed, done_count  # ✅ 正确：4空格缩进
    async with semaphore:
        try:
            # ... 正确缩进的代码
```

## 详细分析

### 1. 代码结构分析

**文件:** `backend/app/routers/master_bank.py`
**函数:** `_gen_one` (位于 `batch_generate_answers` 端点内的 SSE 事件生成器中)

**问题代码段 (第 922-954 行):**
```python
async def _gen_one(idx, qid, question_text):
nonlocal generated, failed, done_count
async with semaphore:
try:
prompt = ANSWER_PROMPT.replace("{question}", question_text)
answer = await _call_llm_with_retry(prompt)
def _update():
with get_db_connection() as conn:
conn.execute(
"UPDATE question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
(answer, qid)
)
conn.commit()
await run_db(_update)
async with results_lock:
generated += 1
done_count += 1
yield_event = json.dumps({'type': 'progress', 'current': done_count, 'total': total, 'id': qid, 'success': True})
except Exception as e:
logger.error(f"批量生成答案失败 [ID:{qid}]: {e}")
def _mark_failed():
with get_db_connection() as conn:
conn.execute(
"UPDATE question_bank SET ai_answer = '[生成失败，请手动重试]', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
(qid,)
)
conn.commit()
await run_db(_mark_failed)
async with results_lock:
failed += 1
done_count += 1
yield_event = json.dumps({'type': 'progress', 'current': done_count, 'total': total, 'id': qid, 'success': False})
return yield_event
```

**正确缩进版本:**
```python
async def _gen_one(idx, qid, question_text):
    nonlocal generated, failed, done_count
    async with semaphore:
        try:
            prompt = ANSWER_PROMPT.replace("{question}", question_text)
            answer = await _call_llm_with_retry(prompt)
            def _update():
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (answer, qid)
                    )
                    conn.commit()
            await run_db(_update)
            async with results_lock:
                generated += 1
                done_count += 1
                yield_event = json.dumps({'type': 'progress', 'current': done_count, 'total': total, 'id': qid, 'success': True})
        except Exception as e:
            logger.error(f"批量生成答案失败 [ID:{qid}]: {e}")
            def _mark_failed():
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE question_bank SET ai_answer = '[生成失败，请手动重试]', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (qid,)
                    )
                    conn.commit()
            await run_db(_mark_failed)
            async with results_lock:
                failed += 1
                done_count += 1
                yield_event = json.dumps({'type': 'progress', 'current': done_count, 'total': total, 'id': qid, 'success': False})
    return yield_event
```

### 2. 错误传播路径

1. uvicorn 尝试导入 `app.asgi` 模块
2. `asgi.py` 第 15 行导入 `app.routers.master_bank`
3. Python 解析器在解析 `master_bank.py` 时遇到 `IndentationError`
4. 模块导入失败，uvicorn 退出
5. 后端服务完全不可用
6. 前端请求 API 时收到连接拒绝或 502 错误
7. 前端显示"服务暂时不可用"

### 3. 影响分析

| 影响项 | 严重程度 | 说明 |
|-------|---------|------|
| 后端服务 | Critical | 无法启动 |
| 所有 API | Critical | 全部不可用 |
| 登录功能 | Critical | 用户无法登录 |
| 题库功能 | Critical | 无法使用 |
| 数据库 | None | 数据未受影响 |

## 复现步骤

1. 尝试启动后端服务：`uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000`
2. 观察控制台输出的 `IndentationError`
3. 在前端尝试登录，看到"服务暂时不可用"错误

## 修复建议

1. 修正 `master_bank.py` 第 923-954 行的缩进
2. 确保所有函数体相对于函数定义有正确的缩进级别（通常是 4 个空格）
3. 重启后端服务验证修复

## 测试验证

修复后需要验证：
- [ ] 后端服务能正常启动
- [ ] `/api/auth/login` 端点响应正常
- [ ] 用户能成功登录
- [ ] 批量生成功能不受影响
