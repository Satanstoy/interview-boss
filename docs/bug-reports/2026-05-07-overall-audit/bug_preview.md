# Bug Preview - InterviewBoss 整体代码审计

**审计日期:** 2026-05-07
**审计范围:** 后端全部路由 + 核心服务 + 前端 HTTP 层
**严重程度评估:** 🔴 高危 (存在导致静默数据损坏和功能失效的运行时错误)

---

## 1. Correctness & Logic

### 🔴 BUG-001: `submit.py:48` — 未定义变量 `response` 导致静默数据损坏
- **位置:** `backend/app/routers/submit.py:48`
- **症状:** `tag_questions_batch` 函数中，第47行正确从 `raw_content` 提取 JSON，但第48行引用了从未定义的 `response` 变量。`NameError` 被第63行的 `except Exception` 静默捕获，导致 `result_map` 为空字典，所有题目被错误分类为"未分类(API漏标)"
- **影响:** 所有面试题的 LLM 分类结果被静默丢弃，题目永远无法得到正确分类
- **严重程度:** 🔴 Critical — 静默数据损坏，核心功能产出错误结果

### 🔴 BUG-003: `master_bank.py:420` — `build-personal` 返回值解包错误
- **位置:** `backend/app/routers/master_bank.py:420`
- **症状:** `match_new_questions()` 返回 `{"matched": [...], "unmatched": [...]}` 字典，但代码用 `matched, unmatched = await match_new_questions(...)` 解包，且后续 `matched.items()` 将列表当字典使用
- **影响:** 个人题库合并功能调用时抛出 `ValueError`/`AttributeError`
- **严重程度:** 🔴 Critical — 功能完全失效

### 🟡 BUG-004: `analytics.py:34-35` — SQL 运算符优先级错误
- **位置:** `backend/app/routers/analytics.py:34-35`
- **症状:** `mixed` 模式下 WHERE 子句: `(qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ? AND qb.job_position = ?`，`AND` 优先于 `OR`，导致 job_position 过滤仅作用于第二个条件
- **影响:** mixed 模式下的 analytics 查询可能返回不属于当前岗位的题目
- **严重程度:** 🟡 Medium — 数据查询结果不准确

---

## 2. Edge Cases

### 🟡 BUG-005: `_extract_json` — 大括号匹配在含字符串大括号时可能失败
- **位置:** `backend/app/services/llm.py:61-64`
- **症状:** 当 LLM 返回的 JSON 中包含 `{` 或 `}` 字符串值时，`text.find('{')` 和 `text.rfind('}')` 可能匹配到字符串内的大括号
- **影响:** 特定 LLM 响应解析失败（实际测试中未触发，风险较低）
- **严重程度:** 🟡 Low — 仅在极端 LLM 输出下可能触发

### 🟡 BUG-006: `normalize_category` — 逗号分隔多分类仅取第一个
- **位置:** `backend/app/services/utils.py:15-16`
- **症状:** 当 LLM 返回 `"算法,数据结构"` 时，只保留 `"算法"`
- **影响:** 分类信息丢失
- **严重程度:** 🟡 Low — 设计选择，但可能导致数据不完整

---

## 3. State & Concurrency

### 🟡 BUG-007: 线程本地数据库连接永不关闭
- **位置:** `backend/app/db/connection.py:506-525`
- **症状:** `get_db_connection()` 将连接存储在线程本地变量中，但只有主线程的连接在 `shutdown` 事件中关闭
- **影响:** 线程池中的工作线程连接泄漏
- **严重程度:** 🟡 Medium — 长期运行后资源泄漏

### 🟡 BUG-008: `_record_failure` — 并发请求下的竞态条件
- **位置:** `backend/app/routers/auth.py:51-70`
- **症状:** 读取 `failure_count` 和写入新值之间没有原子性保证
- **影响:** 并发登录尝试可能导致锁定计数不准确
- **严重程度:** 🟡 Low — 实际触发概率低

---

## 4. Safety & Anti-Patterns

### 🟡 BUG-009: CSRF 中间件检查逻辑可增强
- **位置:** `backend/app/asgi.py:73-84`
- **症状:** CSRF 中间件只检查 `X-Requested-With` 头是否存在，可同时验证 `Content-Type: application/json` 以增强防护
- **影响:** CSRF 防护可进一步增强
- **严重程度:** 🟡 Medium — 当前防护基本有效，但可更严格

### 🟡 BUG-010: `postSSE` 未设置 `X-Requested-With` 头
- **位置:** `frontend/src/utils/http.js:366-370`
- **症状:** SSE 请求的 headers 只包含 `Content-Type` 和 `Authorization`，缺少 `X-Requested-With`
- **影响:** SSE 请求可能被 CSRF 中间件 403 拒绝（取决于中间件是否同时检查 Content-Type）
- **严重程度:** 🟡 Medium — 需确认生产环境 CSRF 中间件行为

---

## 总结

| 严重程度 | 数量 | 编号 |
|---------|------|------|
| 🔴 Critical | 2 | BUG-001, BUG-003 |
| 🟡 Medium | 4 | BUG-004, BUG-007, BUG-009, BUG-010 |
| 🟡 Low | 3 | BUG-005, BUG-006, BUG-008 |

**最高优先级修复:** BUG-001 (静默数据损坏), BUG-003 (功能失效)

**已排除:** 初始分析中的 BUG-002 (master_bank.py 缩进错误) 经验证不存在，文件缩进正确。
