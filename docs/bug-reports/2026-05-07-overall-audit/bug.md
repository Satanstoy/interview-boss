# Bug 深度分析报告

**审计日期:** 2026-05-07
**审计范围:** 后端全部路由 + 核心服务 + 数据库层 + 前端 HTTP 层

---

## BUG-001: `submit.py:48` — 未定义变量 `response` 导致静默数据损坏

### 分类
Correctness & Logic — 静默数据损坏

### 位置
`backend/app/routers/submit.py:48`

### 代码片段
```python
# line 41-48
raw_content = await _call_llm_with_retry(
    prompt=user_msg,
    system_msg="...",
    response_format=kwargs.get("response_format"),
)
try:
    raw_items = _extract_json(raw_content).get("questions", [])
    raw_items = _extract_json(response.choices[0].message.content).get("questions", [])  # BUG
```

### 根因分析
- 第41行调用 `_call_llm_with_retry` 返回字符串 `raw_content`
- 第47行正确地从 `raw_content` 提取 JSON
- 第48行引用了 `response` 变量，但该变量在 `tag_questions_batch` 函数作用域中从未定义
- `response` 只在 `submit_data` 函数的第311行定义（`response = await client.chat.completions.create(...)`），属于不同作用域
- 这是复制粘贴错误：开发者在重构时从直接 API 调用改为使用 `_call_llm_with_retry` 封装，但遗留了旧的 `response` 引用
- **关键发现:** `NameError` 被第63行的 `except Exception` 静默捕获，导致 `result_map = {}`，所有题目被错误分类为"未分类(API漏标)"

### 影响
- `tag_questions_batch` 每次调用都会抛出 `NameError`，但被 `except Exception` 静默捕获
- `result_map` 被设为空字典，所有题目被标记为 `"未分类(API漏标)"`
- 函数返回成功但数据完全错误 — **静默数据损坏**
- 实测验证：LLM 返回 `{"一级大类": "算法"}`，但函数返回 `"未分类(API漏标)"`

### 调用链
```
POST /api/submit → submit_data() → tag_questions_batch() → NameError (line 48)
```

---

## ~~BUG-002: `master_bank.py:922-923` — `_gen_one` 函数缩进错误~~

### 状态: ❌ 经验证不存在

初始分析有误。Read 工具的 `cat -n` 显示格式导致误判，实际文件第 923 行有正确的 16 空格缩进。

```bash
$ sed -n '922,923p' backend/app/routers/master_bank.py | cat -A
            async def _gen_one(idx, qid, question_text):$
                nonlocal generated, failed, done_count$
```

`py_compile` 和 `importlib` 均验证通过。

---

## BUG-003: `master_bank.py:420` — `build-personal` 返回值解包错误

### 分类
Correctness & Logic — 类型错误

### 位置
`backend/app/routers/master_bank.py:420`

### 代码片段
```python
420:            matched, unmatched = await match_new_questions(new_rows_for_match, existing_by_cat2)
...
428:                for new_id, qb_id in matched.items():
```

### 根因分析
- `match_new_questions` 函数（`clustering.py:363-425`）返回 `dict`:
  ```python
  return {"matched": matched, "unmatched": unmatched}
  ```
  其中 `matched` 是 `list[dict]`，每个 dict 含 `new_id` 和 `question_bank_id`
- 第420行用元组解包 `matched, unmatched = await ...`，试图从 dict 中解包出两个变量，会抛出 `ValueError: too many values to unpack`（dict 有2个键，解包OK）— 实际上 dict 解包是按 key 迭代的，所以 `matched` 会是字符串 `"matched"`，`unmatched` 会是字符串 `"unmatched"`
- 第428行 `matched.items()` 在字符串上调用 `.items()` 会抛出 `AttributeError`

### 正确用法
```python
result = await match_new_questions(new_rows_for_match, existing_by_cat2)
matched = result["matched"]
unmatched = result["unmatched"]
```

### 影响
- 个人题库合并功能（`POST /api/master-bank/build-personal`）调用时必定崩溃
- 用户无法将个人题目合并到公共题库

---

## BUG-004: `analytics.py:34-35` — SQL 运算符优先级错误

### 分类
Correctness & Logic — 逻辑错误

### 位置
`backend/app/routers/analytics.py:34-35`

### 代码片段
```python
34:            return "", "WHERE (qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ? AND qb.job_position = ?", [uid, pos_name]
35:        else:
36:            return "", "WHERE qb.owner_id IS NULL AND qb.status = 'approved' AND qb.job_position = ?", [pos_name]
```

### 根因分析
SQL 中 `AND` 优先级高于 `OR`，所以第34行实际解析为：
```sql
WHERE (qb.owner_id IS NULL AND qb.status = 'approved')
   OR (qb.owner_id = ? AND qb.job_position = ?)
```
这意味着第一个条件（公共题目）没有 `job_position` 过滤，会返回所有岗位的公共题目。

### 正确写法
```python
return "", "WHERE ((qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ?) AND qb.job_position = ?", [uid, pos_name]
```

### 影响
- `mixed` 模式下的 analytics/practice-stats/knowledge-graph 查询会返回跨岗位数据
- 用户可能看到不属于当前岗位的统计数据

---

## BUG-005: `llm.py:61-64` — `_extract_json` 大括号匹配不可靠

### 分类
Edge Cases — 解析脆弱性

### 位置
`backend/app/services/llm.py:61-64`

### 代码片段
```python
61:    start = text.find('{')
62:    end = text.rfind('}')
63:    if start != -1 and end != -1 and end > start:
64:        return json.loads(text[start:end + 1])
```

### 根因分析
当 LLM 返回类似以下内容时：
```
这是分析结果：{"key": "值包含{括号}"}
```
`text.rfind('}')` 会匹配到字符串内部的 `}`，导致截取的 JSON 不完整。

### 影响
- 仅在 LLM 返回包含大括号的字符串值时触发
- 概率较低，但一旦触发会导致 JSON 解析失败

---

## BUG-006: `utils.py:15-16` — `normalize_category` 丢失多分类信息

### 分类
Edge Cases — 数据丢失

### 位置
`backend/app/services/utils.py:15-16`

### 代码片段
```python
15:    if ',' in text:
16:        text = text.split(',')[0].strip()
```

### 根因分析
当 LLM 返回 `"算法,数据结构"` 时，只保留 `"算法"`，第二个分类被丢弃。这可能是设计选择，但会导致分类信息不完整。

### 影响
- 题目分类信息可能不完整
- 知识图谱中的标签关联可能缺失

---

## BUG-007: 线程本地数据库连接泄漏

### 分类
State & Concurrency — 资源泄漏

### 位置
`backend/app/db/connection.py:506-525`

### 代码片段
```python
506:def get_db_connection():
507:    conn = getattr(_local, 'conn', None)
508:    if conn is not None:
509:        try:
510:            conn.execute("SELECT 1")
511:            return conn
512:        except Exception:
...
519:    conn = sqlite3.connect(DB_PATH, timeout=30)
...
524:    _local.conn = conn
525:    return conn
```

### 根因分析
- `get_db_connection()` 将连接存储在 `threading.local()` 中
- `asgi.py` 的 `shutdown` 事件只关闭了主线程的连接
- FastAPI 使用 `asyncio.to_thread()` 执行同步数据库操作，线程池中的工作线程连接永远不会被关闭
- SQLite WAL 模式下，未关闭的连接会持有 WAL 文件锁

### 影响
- 长期运行后可能出现文件描述符泄漏
- 极端情况下可能导致数据库锁争用

---

## BUG-008: `_record_failure` 竞态条件

### 分类
State & Concurrency — 竞态条件

### 位置
`backend/app/routers/auth.py:51-70`

### 根因分析
- `_record_failure` 先读取 `failure_count`，再写入新值
- 两个并发请求可能同时读取相同的 `failure_count`，导致计数不准确
- 实际触发概率低（需要完全同时的登录尝试），但理论上存在

### 影响
- 账号锁定计数可能不准确
- 不会导致安全漏洞（最多是少计一次失败）

---

## BUG-009: CSRF 中间件防护不完整

### 分类
Safety & Anti-Patterns — 安全防护不足

### 位置
`backend/app/asgi.py:73-84`

### 根因分析
- CSRF 中间件只检查 `X-Requested-With` 头是否存在
- 前端使用 `Content-Type: application/json` 发送所有 API 请求
- 但中间件没有验证 Content-Type — 任何带 `X-Requested-With` 头的跨域请求都能通过
- 正确做法应该是同时检查两者：要么有 `X-Requested-With`，要么 Content-Type 是 `application/json`

### 影响
- CSRF 防护不完整，可能被绕过
- 需要结合其他漏洞才能利用

---

## BUG-010: `postSSE` 缺少 `X-Requested-With` 头

### 分类
Safety & Anti-Patterns — 功能失效

### 位置
`frontend/src/utils/http.js:366-370`

### 代码片段
```javascript
366:    const res = await fetch(url, {
367:      method: 'POST',
368:      headers: { 'Content-Type': 'application/json', ...authHeaders },
369:      body: JSON.stringify(body),
370:      signal: controller.signal,
371:      credentials: 'same-origin',
372:    })
```

### 根因分析
- `postSSE` 的 headers 只包含 `Content-Type` 和 `Authorization`
- 缺少 `X-Requested-With: XMLHttpRequest` 头
- 全局 CSRF 中间件（`asgi.py:73-84`）会检查此头，缺少时返回 403

### 影响
- 所有 SSE 端点（`/api/master-bank/build`、`/api/master-bank/batch-generate-answers`）会返回 403
- 题库重建和批量生成功能完全不可用
- **注意:** 如果后端实际上未部署或 CSRF 中间件被禁用，则此 bug 不会触发

---

## BUG 汇总表

| ID | 严重程度 | 文件 | 行号 | 类型 | 影响范围 |
|----|---------|------|------|------|---------|
| BUG-001 | Critical | submit.py | 48 | 静默数据损坏 | 所有题目分类错误 |
| BUG-002 | N/A | — | — | 不存在 | 初始分析有误 |
| BUG-003 | Critical | master_bank.py | 420 | ValueError | 个人题库合并功能 |
| BUG-004 | Medium | analytics.py | 34 | 逻辑错误 | mixed 模式数据查询 |
| BUG-005 | Low | llm.py | 61 | 解析脆弱性 | 极端 LLM 输出 |
| BUG-006 | Low | utils.py | 15 | 数据丢失 | 分类信息完整性 |
| BUG-007 | Medium | connection.py | 506 | 资源泄漏 | 长期运行稳定性 |
| BUG-008 | Low | auth.py | 51 | 竞态条件 | 登录锁定计数 |
| BUG-009 | Medium | asgi.py | 73 | 安全防护可增强 | CSRF 防护 |
| BUG-010 | Medium | http.js | 366 | 缺少请求头 | SSE 端点 |
