# Bug 修复计划

**审计日期:** 2026-05-07

---

## 修复优先级

### P0 — 阻断性 (必须立即修复)

#### FIX-001: `submit.py:48` — 删除遗留的 `response` 引用

**文件:** `backend/app/routers/submit.py`
**行号:** 48
**操作:** 删除第48行

```python
# 删除这一行:
raw_items = _extract_json(response.choices[0].message.content).get("questions", [])
```

第47行已经正确地从 `raw_content` 提取了 JSON，第48行是重构时遗留的旧代码。当前 `NameError` 被 `except Exception` 静默捕获，导致所有题目被错误分类为"未分类(API漏标)"。

**风险评估:** 无风险，纯删除冗余代码。

---

#### FIX-003: `master_bank.py:420` — 修复 `build-personal` 返回值处理

**文件:** `backend/app/routers/master_bank.py`
**行号:** 420
**操作:** 修改为正确的字典访问方式

```python
# 修改前:
matched, unmatched = await match_new_questions(new_rows_for_match, existing_by_cat2)

# 修改后:
match_result = await match_new_questions(new_rows_for_match, existing_by_cat2)
matched = match_result["matched"]
unmatched = match_result["unmatched"]
```

同时需要修复第428行的 `matched.items()` 调用：
```python
# 修改前:
for new_id, qb_id in matched.items():

# 修改后:
for m in matched:
    new_id = m["new_id"]
    qb_id = m["question_bank_id"]
    personal_row = personal_rows[new_id]
    ...
```

**风险评估:** 低风险，修复类型错误。

---

### P1 — 高优先级

#### FIX-004: `analytics.py:34` — 修复 SQL 运算符优先级

**文件:** `backend/app/routers/analytics.py`
**行号:** 34
**操作:** 添加括号确保正确的运算顺序

```python
# 修改前:
return "", "WHERE (qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ? AND qb.job_position = ?", [uid, pos_name]

# 修改后:
return "", "WHERE ((qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ?) AND qb.job_position = ?", [uid, pos_name]
```

**风险评估:** 低风险，修复查询逻辑。

---

#### FIX-010: `http.js:368` — 为 `postSSE` 添加 `X-Requested-With` 头

**文件:** `frontend/src/utils/http.js`
**行号:** 368
**操作:** 在 headers 中添加 `X-Requested-With`

```javascript
// 修改前:
headers: { 'Content-Type': 'application/json', ...authHeaders },

// 修改后:
headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', ...authHeaders },
```

**风险评估:** 无风险，添加缺失的请求头。

---

### P2 — 中优先级

#### FIX-009: `asgi.py:73-84` — 增强 CSRF 中间件检查

**文件:** `backend/app/asgi.py`
**操作:** 同时检查 `X-Requested-With` 和 `Content-Type`

```python
class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in ('POST', 'PUT', 'DELETE'):
            if request.url.path not in _CSRF_EXEMPT_PATHS:
                has_custom_header = bool(request.headers.get("X-Requested-With"))
                ct = request.headers.get("content-type", "")
                has_json_content_type = "application/json" in ct
                if not has_custom_header and not has_json_content_type:
                    return JSONResponse(status_code=403, content={"detail": "缺少必要的请求头，请通过前端发起请求"})
        return await call_next(request)
```

**风险评估:** 低风险，增强安全检查逻辑。

---

#### FIX-007: `connection.py` — 线程连接生命周期管理

**文件:** `backend/app/db/connection.py`
**操作:** 使用 context manager 确保连接关闭

这是一个架构级改进，建议作为后续优化：
1. 使用 `contextvars` 替代 `threading.local()` 以更好地配合 asyncio
2. 或者在 `run_db` 中使用短生命周期连接

**风险评估:** 中风险，需要全面测试。

---

### P3 — 低优先级 (建议后续处理)

- **FIX-005:** `_extract_json` 大括号匹配 — 可以改用正则匹配最外层 `{...}` 或增加 JSON 解析库
- **FIX-006:** `normalize_category` 多分类 — 需求决策，是否保留全部分类
- **FIX-008:** `_record_failure` 竞态 — 可用 `UPDATE ... SET failure_count = failure_count + 1` 原子操作

---

## 修复顺序建议

1. **FIX-001** (submit.py 未定义变量) — 静默数据损坏，所有题目分类错误
2. **FIX-003** (build-personal 返回值) — 功能失效
3. **FIX-010** (postSSE 缺少头) — SSE 功能可能失效
4. **FIX-004** (analytics SQL) — 查询结果不准确
5. **FIX-009** (CSRF 增强) — 安全加固

**已排除:** FIX-002 (master_bank.py 缩进) 经验证不存在

## 架构考虑

- 所有修复都是局部修改，不影响整体架构
- FIX-002 是纯缩进修复，不改变任何逻辑
- FIX-003 需要同时修改解包方式和后续的字典访问
- FIX-009 增强 CSRF 检查后，需确保前端所有请求都携带正确的头
