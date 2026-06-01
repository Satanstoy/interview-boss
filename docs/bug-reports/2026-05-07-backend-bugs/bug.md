# Bug 详细分析报告

**Bug ID:** BUG-001 ~ BUG-004
**发现日期:** 2026-05-07
**状态:** 已确认

## 问题概述

后端代码存在 4 个 Bug，涉及异步事件循环阻塞、数据库查询效率、LLM 响应解析容错和调用可靠性。

## 根本原因分析

### BUG-001: 异步端点中同步阻塞数据库调用

- **位置:** `backend/app/routers/profile.py:71-76`
- **症状:** `get_public_profile` 异步端点中，`_get_available_positions()` (line 71) 和 line 72-76 的 `get_db_connection()` 直接使用同步 SQLite 调用，阻塞事件循环
- **根因:** 辅助函数 `_get_available_positions()` 是普通同步函数，直接使用 `with get_db_connection() as conn`；line 72-76 在 async 函数体中也直接调用
- **影响:** 当数据库查询较慢或并发请求多时，整个 FastAPI 进程被阻塞，其他请求无法处理
- **严重程度:** P1 (High)

**问题代码:**
```python
# line 71 — 同步调用，阻塞事件循环
available_positions = _get_available_positions()
# line 72-76 — 同步调用，阻塞事件循环
with get_db_connection() as conn:
    user_row = conn.execute(...)
```

### BUG-002: 删除操作全表扫描 question_bank

- **位置:** `backend/app/routers/data.py:103, 122, 190`
- **症状:** 删除 JD 或 interview 时，执行 `SELECT id, sources FROM question_bank` 遍历整个题库表来清理来源引用
- **根因:** 未利用 sources JSON 中的 url 字段做预筛选，而是全表遍历后在 Python 中过滤
- **影响:** 当 question_bank 数据量增长到数千条时，每次删除操作都会变慢
- **严重程度:** P2 (Medium)

**问题代码:**
```python
# data.py:103 — 全表扫描
affected_rows = cursor.execute("SELECT id, sources FROM question_bank").fetchall()
for mr in affected_rows:
    sources = json.loads(mr['sources']) if mr['sources'] else []
    new_sources = [s for s in sources if s.get('url') != url]
```

### BUG-003: master_bank _tag_batch 使用原始 json.loads

- **位置:** `backend/app/routers/master_bank.py:204`
- **症状:** `_tag_batch` 函数直接用 `json.loads()` 解析 LLM 响应，如果 LLM 返回 markdown 代码块包裹的 JSON（如 `` ```json ... ``` ``），解析会失败
- **根因:** 未使用 `_extract_json()` 容错函数（`services/llm.py:48`），该函数能处理直接 JSON、markdown 代码块和部分 JSON 三种情况
- **影响:** 题库重建时某些批次可能因 LLM 响应格式问题而失败，导致部分题目标签丢失
- **严重程度:** P2 (Medium)

**问题代码:**
```python
# master_bank.py:204 — 脆弱的 JSON 解析
response = await client.chat.completions.create(**kwargs)
result = json.loads(response.choices[0].message.content.strip())  # 可能失败
```

### BUG-004: submit LLM 调用缺少重试机制

- **位置:** `backend/app/routers/submit.py:310`
- **症状:** `submit_data` 中的 LLM 调用直接使用 `client.chat.completions.create()`，不带重试
- **根因:** 未使用 `services/llm.py` 中的 `_call_llm_with_retry()` 封装（该函数有 3 次重试 + 指数退避）
- **影响:** 网络波动或 API 限流时，用户提交内容直接失败，需手动重试
- **严重程度:** P1 (High)

**问题代码:**
```python
# submit.py:310 — 无重试
response = await client.chat.completions.create(**llm_kwargs)
```

## 复现步骤

### BUG-001
1. 启动 FastAPI 服务
2. 并发发送多个 `/api/profile/public` 请求
3. 观察请求延迟明显增加（串行执行而非并行）

### BUG-002
1. 导入大量数据（question_bank > 1000 条）
2. 删除一条 JD 记录
3. 观察删除响应时间随数据量线性增长

### BUG-003
1. 触发题库重建（build_master_bank）
2. 当 LLM 返回 `` ```json {...} ``` `` 格式时
3. 该批次 JSON 解析失败，题目标签丢失

### BUG-004
1. 提交一段面经内容
2. 模拟网络波动（LLM API 短暂不可用）
3. 提交直接报错，无自动重试

## 修复建议

| Bug ID | 修复方向 |
|--------|---------|
| BUG-001 | 将同步 DB 调用包装到 `await run_db()` 中 |
| BUG-002 | 使用 JSON 函数预筛选或建立索引减少扫描范围 |
| BUG-003 | 将 `json.loads()` 替换为 `_extract_json()` |
| BUG-004 | 使用 `_call_llm_with_retry()` 或添加重试装饰器 |
