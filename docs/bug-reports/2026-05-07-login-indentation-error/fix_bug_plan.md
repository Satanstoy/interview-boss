# 修复计划

**Bug ID:** INDENT-001
**日期:** 2026-05-07
**优先级:** P0 (Critical)

## 问题概述

`backend/app/routers/master_bank.py` 文件第 922-954 行存在缩进错误，导致后端服务无法启动。

## 修复步骤

### 步骤 1: 修正 `_gen_one` 函数缩进

**文件:** `backend/app/routers/master_bank.py`
**行号:** 922-954
**修改类型:** 修正缩进

**修改前:**
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

**修改后:**
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

### 步骤 2: 验证 Python 语法

```bash
cd /root/sj/interview-boss/backend
python3 -m py_compile app/routers/master_bank.py
```

### 步骤 3: 重启后端服务

```bash
# 杀死现有进程（如果有）
pkill -f "uvicorn app.asgi:app"

# 启动服务
cd /root/sj/interview-boss/backend
/root/.local/bin/uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000
```

### 步骤 4: 验证修复

1. 检查后端服务启动日志无错误
2. 测试登录 API：
   ```bash
   curl -X POST http://localhost:8000/api/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username":"sj","password":"qnmlgb233.."}'
   ```
3. 在前端测试登录功能

## 架构考虑

此修复仅为语法修正，不涉及逻辑变更：
- 保持原有业务逻辑不变
- 不引入新的依赖
- 不影响其他功能模块

## 回滚方案

如果修复后出现问题，可以回退到修复前的代码状态：
```bash
cd /root/sj/interview-boss
git checkout backend/app/routers/master_bank.py
```

## 相关文件

- `backend/app/routers/master_bank.py` - 主要修复文件
- `backend/app/asgi.py` - 导入 master_bank 模块
- `frontend/src/api/index.js` - 前端 API 调用
