# 修复计划

**日期:** 2026-05-07
**优先级:** P0 ~ P2

## 步骤 1: 修复 BUG-002 — analytics 数据泄露（P0）

**文件:** `backend/app/routers/analytics.py`
**行号:** 46-62
**修改类型:** 修正

**修改前:**
```python
@router.get("/api/analytics")
async def get_analytics(user: dict = Depends(get_current_user)):
    def _query():
        tech_counter, tag_counter, level_counter = Counter(), Counter(), Counter()
        with get_db_connection() as conn:
            for r in conn.execute("SELECT tech_stack FROM jd").fetchall():
                if r['tech_stack']:
                    tech_counter.update([t.strip().lstrip('0123456789. ') for t in r['tech_stack'].split('\n') if t.strip()])
            for r in conn.execute("SELECT tags, diff_tag FROM questions_detail").fetchall():
                if r['tags']:
                    tag_counter.update([t.strip() for t in r['tags'].split(",") if t.strip()])
                if r['diff_tag']:
                    level_counter[r['diff_tag']] += 1
        return dict(tech_counter.most_common(10)), dict(tag_counter.most_common(10)), dict(tag_counter.most_common(20)), dict(level_counter)
```

**修改后:**
```python
@router.get("/api/analytics")
async def get_analytics(user: dict = Depends(get_current_user)):
    def _query():
        tech_counter, tag_counter, level_counter = Counter(), Counter(), Counter()
        with get_db_connection() as conn:
            # 按用户可见范围过滤 JD 数据
            join_clause, bank_where, bank_params = _build_analytics_bank_filter(user)
            # JD 数据直接全量返回（jd 表无 owner_id，属于共享数据）
            for r in conn.execute("SELECT tech_stack FROM jd").fetchall():
                if r['tech_stack']:
                    tech_counter.update([t.strip().lstrip('0123456789. ') for t in r['tech_stack'].split('\n') if t.strip()])
            # 题目标签需按 bank_mode 过滤
            for r in conn.execute(
                f"SELECT qb.tags, qb.diff_tag FROM question_bank qb {join_clause} {bank_where}",
                bank_params
            ).fetchall():
                if r['tags']:
                    tag_counter.update([t.strip() for t in r['tags'].split(",") if t.strip()])
                if r['diff_tag']:
                    level_counter[r['diff_tag']] += 1
        return dict(tech_counter.most_common(10)), dict(tag_counter.most_common(10)), dict(tag_counter.most_common(20)), dict(level_counter)
```

**关键变更:**
- `questions_detail` 查询改为 `question_bank` 并使用 `_build_analytics_bank_filter` 过滤
- JD 数据保持全量（`jd` 表无 `owner_id`，属于共享数据源）

## 步骤 2: 修复 BUG-001 — 空消毒函数（P1）

**文件:** `frontend/src/utils/validate.js`
**行号:** 13-17
**修改类型:** 修正

**修改前:**
```javascript
/**
 * 输入消毒占位函数（SQL 注入检测已移除，后端使用参数化查询）
 */
export function sanitizeAgainstInjection(str, _fieldName = '输入') {
  return str
}
```

**修改后:**
```javascript
/**
 * 输入消毒（XSS 防护）
 * 移除了 SQL 注入检测（后端使用参数化查询），保留 XSS 消毒
 */
export function sanitizeAgainstInjection(str, _fieldName = '输入') {
  if (typeof str !== 'string') return ''
  // 移除潜在的 XSS 向量：HTML 标签和事件处理器
  return str
    .replace(/<[^>]*>/g, '')           // 移除 HTML 标签
    .replace(/javascript:/gi, '')       // 移除 javascript: 协议
    .replace(/on\w+\s*=/gi, '')         // 移除事件处理器 (onclick=, onerror= 等)
    .replace(/data:/gi, '')             // 移除 data: 协议
}
```

## 步骤 3: 修复 BUG-003 — URL href 无协议验证（P1）

**文件:** `frontend/src/utils/validate.js`
**修改类型:** 新增

**新增函数:**
```javascript
/**
 * 安全化 URL：仅允许 http/https 协议，阻止 javascript: / data: 等
 */
export function safeUrl(url) {
  if (!url || typeof url !== 'string') return ''
  const trimmed = url.trim()
  if (/^https?:\/\//i.test(trimmed)) return trimmed
  return ''  // 非 http(s) 协议返回空字符串
}
```

**文件:** `frontend/src/components/QuestionCard.vue` 和 `frontend/src/App.vue`
**修改类型:** 替换

所有 `:href="item.url"` 改为 `:href="safeUrl(item.url)"`

## 步骤 4: 修复 BUG-005 — API Key 掩码（P2）

**文件:** `backend/app/routers/profile.py`
**行号:** 46-49
**修改类型:** 修正

**修改前:**
```python
def _mask_key(value: str) -> str:
    if not value or len(value) <= 4:
        return "****"
    return value[:4] + "****"
```

**修改后:**
```python
def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:4] + "*" * (len(value) - 8) + value[-4:]
```

## 步骤 5: 修复 BUG-006 — 账户锁定 DoS（P2）

**文件:** `backend/app/routers/auth.py`
**修改类型:** 新增

添加基于 IP 的速率限制，与现有的用户名锁定并行运行。

## 验证方法

1. 运行 `pytest tests/test_security_audit.py -v` 确认所有安全测试通过
2. 手动测试 analytics 端点，确认不同 bank_mode 用户看到不同数据
3. 在前端尝试输入 `javascript:alert(1)` 作为 URL，确认被过滤

## 回滚方案

所有修改均为增量式，可通过 `git revert` 回滚。
