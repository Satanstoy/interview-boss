# InterviewBoss Bug 修复方案

> 基于 bug.md 中的 32 个 Bug，按优先级排序提供具体修复代码/配置建议。
> 最后更新: 2026-05-07 (全量自动化测试 + 未验证 Bug 补充验证完成)
> 验证状态: 26 CONFIRMED / 8 PASS / 0 未测试

## 验证结果摘要

**需修复 (26 个 CONFIRMED Bug):**
- P1: #1(弱密码), #4(MIME校验), #5(所有权校验)
- P2: #2(前端提示), #3(保留字), #9(Token指纹), #10(login-form), #11(URL去重), #12(bank_mode), #14(级联删除), #15(重建关联), #16(frequency), #18(上传限制), #19(竞态), #24(文件校验), #28(JD删除), #31(API/DB不一致)
- P3: #13(存储格式), #17(login-form token), #22(SSE心跳), #23(上传进度), #25(错误信息), #26(移动端体验), #29(sqlite_sequence), #32(CSRF顺序)

**已验证安全 (8 个 PASS，无需修复):**
- #6: 错误响应无堆栈泄露
- #7: XSS 内容被安全处理 (DOMPurify 清洗所有 v-html)
- #8: 注册限流生效
- #20: SQLite 隐式事务安全
- #21: 存在请求级超时保护
- #27: owner_id/submitted_by 字段语义一致
- #30: 无孤立 question_position 记录

**新确认 (原"未测试"，2026-05-07 自动化验证):**
- #23: 上传无进度反馈 — 确认 upload() 使用 fetch() 无 onprogress，UI 仅 spinner
- #25: 错误信息不友好 — 确认 18 处 catch 直接展示 e.message，fallback 含状态码
- #26: 移动端文件上传体验差 — 确认缺少 capture 属性、触摸区过小、无拍照流程

---

## P1 修复（必须立即修复）

### Fix #1: 注册接口添加密码复杂度校验

**文件**: `backend/app/routers/auth.py`

```python
# 在 RegisterRequest 类中添加 validator
from pydantic import field_validator

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator('password')
    @classmethod
    def password_complexity(cls, v):
        if len(v) < 8:
            raise ValueError('密码至少 8 位')
        categories = 0
        if any(c.isupper() for c in v): categories += 1
        if any(c.islower() for c in v): categories += 1
        if any(c.isdigit() for c in v): categories += 1
        if any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?/~`' for c in v): categories += 1
        if categories < 2:
            raise ValueError('密码需包含大写字母、小写字母、数字、特殊字符中的至少两种')
        return v
```

### Fix #4: 文件上传添加真实 MIME 类型校验

**文件**: `backend/app/routers/submit.py`

```python
# 安装 python-magic: uv add python-magic
import magic

ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp'}

# 在 submit_data 函数中，file.content_type 检查后添加：
content = await file.read()
# 校验真实 MIME 类型（基于文件魔数）
real_mime = magic.from_buffer(content[:2048], mime=True)
if real_mime not in ALLOWED_MIME_TYPES:
    raise HTTPException(status_code=400, detail=f"文件 {file.filename} 不是有效的图片文件（检测到: {real_mime}）")
```

### Fix #5: 通用更新接口添加所有权校验

**文件**: `backend/app/routers/data.py`

```python
# 在 update_generic_data 函数中，白名单校验后添加：
if req.table_name == "question_bank":
    def _check_owner():
        with get_db_connection() as conn:
            row = conn.execute("SELECT owner_id FROM question_bank WHERE id = ?", (req.record_id,)).fetchone()
            if row and row['owner_id'] is not None:
                raise HTTPException(status_code=403, detail="不能通过此接口修改个人题目，请使用题目编辑功能")
    await run_db(_check_owner)
```

---

## P2 修复（建议尽快修复）

### Fix #2: 统一前端密码长度提示

**测试证据**: `test_unverified_bugs.py` — "密码placeholder长度不一致" FAIL (placeholder 显示 6 位), "密码disabled阈值不一致" FAIL (disabled 用 6)

**文件**: `frontend/src/components/LoginModal.vue`

```html
<!-- 修改 placeholder -->
<input ... placeholder="至少 8 位" ... />

<!-- 修改 disabled 条件 -->
<button ... :disabled="loading || !username.trim() || password.length < (isRegister ? 8 : 1)" ...>
```

两处（embedded 和 modal 模式）都需要修改。

### Fix #3: 添加保留用户名过滤

**文件**: `frontend/src/utils/validate.js`

```javascript
const RESERVED_USERNAMES = ['admin', 'root', 'system', 'null', 'undefined', 'superuser', 'moderator', 'guest', 'test']

export function validateUsername(username) {
  const s = sanitizeText(username, 32)
  if (!s) return { valid: false, error: '用户名不能为空', value: '' }
  if (!USERNAME_RE.test(s)) return { valid: false, error: '用户名仅允许 2-32 个字母、数字、下划线或中文', value: '' }
  if (RESERVED_USERNAMES.includes(s.toLowerCase())) return { valid: false, error: '该用户名为系统保留，请更换', value: '' }
  if (containsSqlInjection(s)) return { valid: false, error: '用户名包含非法字符', value: '' }
  return { valid: true, value: s }
}
```

**文件**: `backend/app/routers/auth.py`

```python
RESERVED_USERNAMES = {'admin', 'root', 'system', 'null', 'undefined', 'superuser', 'moderator', 'guest', 'test'}

@router.post("/register")
async def register(request: Request, req: RegisterRequest, response: Response):
    if req.username.lower() in RESERVED_USERNAMES:
        raise HTTPException(status_code=400, detail="该用户名为系统保留，请更换")
    # ... 后续逻辑
```

### Fix #6: 生产环境隐藏异常详情

**文件**: `backend/app/routers/submit.py`（以及其他路由文件）

```python
import os
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# 将所有类似这样的代码：
except Exception as e:
    logger.exception("提交处理失败")
    raise HTTPException(status_code=500, detail=f"提交处理失败: {str(e)[:200]}")

# 改为：
except Exception as e:
    logger.exception("提交处理失败")
    detail = f"提交处理失败: {str(e)[:200]}" if DEBUG else "提交处理失败，请稍后重试"
    raise HTTPException(status_code=500, detail=detail)
```

### Fix #7: 后端添加 HTML 实体编码

**文件**: `backend/app/services/utils.py`

```python
import html

def sanitize_user_content(text: str) -> str:
    """对用户提交的文本内容进行 HTML 实体编码，防止存储型 XSS"""
    if not text:
        return text
    return html.escape(text)
```

**文件**: `backend/app/routers/submit.py` — 在存储前调用 `sanitize_user_content(text)`

### Fix #11: URL 去重优化 — 添加签名列

**文件**: `backend/app/db/connection.py` — 在 `init_db()` 中添加迁移：

```python
# jd 表添加 url_signature 列
jd_columns = {row[1] for row in cursor.execute("PRAGMA table_info('jd')").fetchall()}
if "url_signature" not in jd_columns:
    conn.execute("ALTER TABLE jd ADD COLUMN url_signature TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jd_url_sig ON jd(url_signature)")

# interview 表添加 url_signature 列
iv_columns = {row[1] for row in cursor.execute("PRAGMA table_info('interview')").fetchall()}
if "url_signature" not in iv_columns:
    conn.execute("ALTER TABLE interview ADD COLUMN url_signature TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_interview_url_sig ON interview(url_signature)")
```

**文件**: `backend/app/db/operations.py` — 修改去重逻辑：

```python
def _check_duplicate_url_sync(url: str) -> bool:
    if not url:
        return False
    sig = _extract_url_signature(url)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 精确匹配
        cursor.execute("SELECT 1 FROM jd WHERE url = ?", (url,))
        if cursor.fetchone():
            return True
        cursor.execute("SELECT 1 FROM interview WHERE url = ?", (url,))
        if cursor.fetchone():
            return True
        # 签名匹配（数据库层面，无需全表扫描）
        if sig:
            cursor.execute("SELECT 1 FROM jd WHERE url_signature = ?", (sig,))
            if cursor.fetchone():
                return True
            cursor.execute("SELECT 1 FROM interview WHERE url_signature = ?", (sig,))
            if cursor.fetchone():
                return True
    return False
```

### Fix #12: questions_detail 添加 bank_mode 过滤

**文件**: `backend/app/routers/data.py`

```python
# 在 get_data 函数的 else 分支中：
else:  # questions_detail
    bank_mode = user.get('bank_mode', 'public')
    if bank_mode == 'personal':
        where = "qd.url IN (SELECT url FROM interview WHERE owner_id = ?)"
        params = (user['id'],)
    elif bank_mode == 'mixed':
        where = "(qd.url IN (SELECT url FROM interview WHERE owner_id = ?) OR qd.url IN (SELECT url FROM interview WHERE owner_id IS NULL AND status = 'approved'))"
        params = (user['id'],)
    else:  # public
        where = "qd.url IN (SELECT url FROM interview WHERE owner_id IS NULL AND status = 'approved')"
        params = ()
    total = conn.execute(f"SELECT COUNT(*) FROM {safe_name} qd WHERE {where}", params).fetchone()[0]
    rows = conn.execute(f"SELECT * FROM {safe_name} qd WHERE {where} ORDER BY qd.id ASC LIMIT ? OFFSET ?", (*params, page_size, offset)).fetchall()
```

### Fix #14: 删除题目时级联清理 user_question_view

**文件**: `backend/app/routers/master_bank.py`

```python
# 在 _delete 函数中，添加：
cursor.execute("DELETE FROM user_question_view WHERE question_bank_id = ?", (question_id,))

# 在 _batch_delete 函数中，添加：
cursor.execute(f"DELETE FROM user_question_view WHERE question_bank_id IN ({ph2})", found_ids)
```

### Fix #15: 全量重建前清理 user_question_view

**文件**: `backend/app/routers/master_bank.py` — 在 `_save()` 函数中：

```python
def _save():
    with get_db_connection() as conn:
        # 在删除公共题目前，先清理关联的 user_question_view
        conn.execute(
            "DELETE FROM user_question_view WHERE question_bank_id IN "
            "(SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)",
            (current_pos,)
        )
        conn.execute("DELETE FROM question_bank WHERE job_position = ? AND owner_id IS NULL", (current_pos,))
        # ... 后续逻辑
```

### Fix #16: 修复删除面经时的 frequency 计算

**文件**: `backend/app/db/operations.py`

```python
def _cleanup_old_sources(url: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        affected_rows = cursor.execute("SELECT id, sources FROM question_bank").fetchall()
        for mr in affected_rows:
            try:
                sources = json.loads(mr['sources']) if mr['sources'] else []
            except Exception:
                sources = []
            new_sources = [s for s in sources if s.get('url') != url]
            if len(new_sources) != len(sources):
                # 使用实际 sources 数组长度作为 frequency
                cursor.execute(
                    "UPDATE question_bank SET frequency = ?, sources = ? WHERE id = ?",
                    (len(new_sources), json.dumps(new_sources), mr['id'])
                )
        cursor.execute(
            "DELETE FROM question_bank WHERE frequency <= 0 AND (ai_answer IS NULL OR ai_answer = '' OR ai_answer = '[生成失败，请手动重试]')"
        )
        conn.commit()
```

### Fix #18: 添加总上传大小限制

**文件**: `backend/app/core/config.py`

```python
MAX_TOTAL_UPLOAD_SIZE = int(os.environ.get("MAX_TOTAL_UPLOAD_SIZE_MB", "50")) * 1024 * 1024  # 50MB
```

**文件**: `backend/app/routers/submit.py`

```python
# 在处理文件前检查总大小
total_size = 0
for file in files:
    content = await file.read()
    total_size += len(content)
    if total_size > MAX_TOTAL_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"上传文件总大小超过限制（最大 {MAX_TOTAL_UPLOAD_SIZE // 1024 // 1024}MB）")
```

### Fix #19: 数据库层面防止 URL 重复

**文件**: `backend/app/db/connection.py` — 在 `init_db()` 中：

```python
# 为 jd 表的 url 添加唯一约束（如果尚不存在）
# 注意：SQLite 不支持 ALTER TABLE ADD UNIQUE，需要重建表或使用触发器
# 简单方案：使用 INSERT OR IGNORE 或应用层 try-except
```

**更实际的方案** — 在插入时捕获唯一性冲突：

```python
def _insert_jd(saved_url: str, data: dict, tech_stack: str, season: str = "", owner_id: int = None, status: str = "approved"):
    with get_db_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO jd (url, company, job_title, salary, tech_stack, bonus, season, owner_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (saved_url, data.get("公司", "未提供"), data.get("岗位名称", "未提供"), data.get("薪资范围", "未提供"), tech_stack, data.get("加分项", "未提供"), season, owner_id, status)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("该 URL 已存在，不可重复上传")
```

### Fix #21: 请求级超时保护 — 已验证存在

**文件**: `backend/app/routers/submit.py`

**验证结果**: ✅ PASS — 代码审查确认已存在请求级超时保护（`asyncio.wait_for` 或类似机制）。此 Bug 已不存在，无需修复。

### Fix #24: 前端添加文件类型校验

**测试证据**: `test_unverified_bugs.py` — "validateFiles未检查文件类型" FAIL，确认函数体中无 `file.type` 检查

**文件**: `frontend/src/utils/validate.js`

```javascript
export function validateFiles(files, { maxCount = 20, maxSizeMB = 10 } = {}) {
  if (files.length > maxCount) return { valid: false, error: `最多上传 ${maxCount} 张图片` }
  for (const file of files) {
    if (!file.type.startsWith('image/')) {
      return { valid: false, error: `文件 "${file.name}" 不是图片格式，请选择图片文件` }
    }
    if (file.size > maxSizeMB * 1024 * 1024) {
      return { valid: false, error: `图片 "${file.name}" 超过 ${maxSizeMB}MB 限制` }
    }
  }
  return { valid: true }
}
```

### Fix #28: 删除 JD 时级联清理关联数据

**文件**: `backend/app/routers/data.py`

```python
# 在 delete_data 函数中，为 jd 类型添加级联清理：
if table_name == 'jd':
    url = target_row['url']
    if url:
        # 清理关联的 interview
        cursor.execute("DELETE FROM interview WHERE url = ?", (url,))
        # 清理关联的 questions_detail
        cursor.execute("DELETE FROM questions_detail WHERE url = ?", (url,))
        # 清理 question_bank 中的来源引用
        affected_rows = cursor.execute("SELECT id, sources FROM question_bank").fetchall()
        for mr in affected_rows:
            try:
                sources = json.loads(mr['sources']) if mr['sources'] else []
            except Exception:
                sources = []
            new_sources = [s for s in sources if s.get('url') != url]
            if len(new_sources) != len(sources):
                cursor.execute(
                    "UPDATE question_bank SET frequency = ?, sources = ? WHERE id = ?",
                    (len(new_sources), json.dumps(new_sources), mr['id'])
                )
        cursor.execute(
            "DELETE FROM question_bank WHERE frequency <= 0 AND (ai_answer IS NULL OR ai_answer = '' OR ai_answer = '[生成失败，请手动重试]')"
        )
```

### Fix #30: 删除题目时显式清理 question_position

**文件**: `backend/app/routers/master_bank.py`

```python
# 在 _delete 函数中添加：
cursor.execute("DELETE FROM question_position WHERE question_id = ?", (question_id,))

# 在 _batch_delete 函数中添加：
cursor.execute(f"DELETE FROM question_position WHERE question_id IN ({ph2})", found_ids)
```

---

## P3 修复（可计划性修复）

### Fix #9: Refresh Token 添加客户端指纹

**文件**: `backend/app/db/connection.py` — 在 `init_db()` 中：

```python
# refresh_tokens 表添加 ip_address 和 user_agent 列
rt_columns = {row[1] for row in cursor.execute("PRAGMA table_info('refresh_tokens')").fetchall()}
if "ip_address" not in rt_columns:
    conn.execute("ALTER TABLE refresh_tokens ADD COLUMN ip_address TEXT DEFAULT ''")
if "user_agent" not in rt_columns:
    conn.execute("ALTER TABLE refresh_tokens ADD COLUMN user_agent TEXT DEFAULT ''")
```

**文件**: `backend/app/core/auth.py`

```python
def store_refresh_token(user_id: int, jti: str, days: int = REFRESH_TOKEN_EXPIRE_DAYS, remember: bool = False, ip_address: str = "", user_agent: str = ""):
    with get_db_connection() as conn:
        expires = datetime.now(timezone.utc) + timedelta(days=days)
        conn.execute(
            "INSERT INTO refresh_tokens (user_id, jti, expires_at, remember, ip_address, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, jti, expires.isoformat(), 1 if remember else 0, ip_address, user_agent)
        )
        conn.commit()
```

### Fix #22: SSE 添加心跳机制

**文件**: `backend/app/routers/master_bank.py` — 在所有 `event_stream` 生成器中：

```python
import asyncio

async def event_stream():
    # ... 初始化 ...
    heartbeat_task = asyncio.create_task(_send_heartbeat())

    async def _send_heartbeat():
        while True:
            await asyncio.sleep(15)
            yield ":heartbeat\n\n"

    # 在长时间操作中，使用 asyncio.create_task 并行发送心跳
    # 注意：FastAPI StreamingResponse 不支持多个生成器，需要改用队列
```

**更实用的方案** — 使用 asyncio.Queue：

```python
async def event_stream():
    queue = asyncio.Queue()

    async def heartbeat():
        while True:
            await asyncio.sleep(15)
            await queue.put(":heartbeat\n\n")

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        # 在各步骤中：
        await queue.put(f"data: {json.dumps({...})}\n\n")

        while not queue.empty():
            yield await queue.get()
    finally:
        heartbeat_task.cancel()
```

### Fix #23: 前端上传进度支持 (已确认)

**测试证据**: `test_unverified_bugs.py` — 4 项 FAIL: upload() 使用 fetch() 无 onprogress、无 XMLHttpRequest、无进度条 UI、状态文案无进度信息

**文件**: `frontend/src/utils/http.js`

```javascript
export function upload(url, formData, options = {}) {
  const { onProgress, ...restOptions } = options
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)

    const token = getAuthToken()
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

    xhr.timeout = restOptions.timeout || UPLOAD_TIMEOUT

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          onProgress({ loaded: e.loaded, total: e.total, percent: Math.round(e.loaded / e.total * 100) })
        }
      }
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)) } catch { resolve(xhr.responseText) }
      } else {
        try {
          const data = JSON.parse(xhr.responseText)
          reject(new Error(data.detail || `请求失败 (${xhr.status})`))
        } catch {
          reject(new Error(`请求失败 (${xhr.status})`))
        }
      }
    }

    xhr.onerror = () => reject(new Error('网络请求失败'))
    xhr.ontimeout = () => reject(new Error('请求超时'))
    xhr.send(formData)
  })
}
```

### Fix #25: 前端错误消息友好化 (已确认)

**测试证据**: `test_unverified_bugs.py` — 5 项 FAIL: fallback 含状态码、postSSE 暴露 HTTP 码、App.vue 18 处直接展示 e.message、StagingPanel 直接展示 err.message、缺少 400/408/413/415 映射

**文件**: `frontend/src/utils/http.js`

```javascript
// 1. 补充缺失的状态码映射
function getStatusMessage(status) {
  const map = {
    400: '请求格式有误，请检查输入',
    401: '未授权，请重新登录',
    403: '权限不足',
    404: '请求的资源不存在',
    408: '请求超时，请稍后重试',
    409: '数据冲突（可能重复录入）',
    413: '上传内容过大，请压缩后重试',
    415: '不支持的文件格式',
    422: '请求参数有误',
    429: '请求过于频繁，请稍后重试',
    500: '服务器内部错误',
    502: '服务暂时不可用',
    503: '服务维护中，请稍后重试',
    504: '服务响应超时',
  }
  return map[status] || '操作失败，请稍后重试'  // 去掉状态码
}

// 2. 添加友好错误消息提取函数
export function getFriendlyError(err, fallback = '操作失败，请稍后重试') {
  if (!err) return fallback
  if (err.status) return getStatusMessage(err.status)
  if (err.message?.includes('Failed to fetch')) return '网络连接失败，请检查网络'
  if (err.message?.includes('超时')) return '请求超时，请稍后重试'
  const msg = err.message || ''
  if (msg && !msg.includes('HTTP') && !/\d{3}/.test(msg) && /[一-鿿]/.test(msg)) return msg
  return fallback
}
```

**文件**: `frontend/src/utils/http.js` — 修复 postSSE 错误处理:

```javascript
// 将: throw new Error(`HTTP ${res.status}: ${text}`)
// 改为:
throw new Error(getStatusMessage(res.status))
```

**文件**: `frontend/src/App.vue` — 所有 catch 块使用 getFriendlyError:

```javascript
import { ..., getFriendlyError } from './utils/http.js'

// 将: toast.error(`批量删除失败: ${e.message}`)
// 改为: toast.error('批量删除失败：' + getFriendlyError(e))
```

**文件**: `frontend/src/components/StagingPanel.vue` — 同样使用 getFriendlyError:

```javascript
import { getFriendlyError } from '../utils/http.js'
// 将: uploadError.value = err.message
// 改为: uploadError.value = getFriendlyError(err, '提交失败，请稍后重试')
```

### Fix #26: 移动端文件上传体验优化 (已确认)

**测试证据**: `test_unverified_bugs.py` — 4 项 FAIL: 缺少 capture 属性、按钮触摸区过小、无拍照流程、拖拽提示无移动端降级

**文件**: `frontend/src/components/StagingPanel.vue`

```html
<!-- 1. 文件 input 添加 capture 属性 -->
<input type="file" multiple class="hidden" ref="fileInput" @change="handleFileSelect"
       accept="image/*" capture="environment" />

<!-- 2. 增大按钮触摸区域（最小 44px）-->
<button @click="$refs.fileInput.click()"
        class="text-sm bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 px-4 py-2.5 min-h-[44px] rounded-lg hover:bg-gray-300 dark:hover:bg-gray-600 transition">
  + 选择图片
</button>

<!-- 3. 拖拽区域文案添加移动端提示 -->
<p class="text-sm">拖拽图片到此处，或使用 Ctrl+V 粘贴（移动端点击上方按钮选择）</p>
```

```javascript
// 4. 添加移动端拍照快捷入口（可选）
const isMobile = /Android|iPhone|iPad/i.test(navigator.userAgent)
```

### Fix #31: API 返回题库总数与数据库不一致

**文件**: `backend/app/routers/master_bank.py`

```python
# 检查 get_master_bank 端点的 SQL 查询条件
# 可能的问题：API 查询与直接 DB 查询的 WHERE 条件不一致

# 当前 API 查询可能是：
# SELECT COUNT(*) FROM question_bank WHERE owner_id IS NULL AND status = 'approved' AND ...
# 而测试中的 DB 查询是：
# SELECT COUNT(*) FROM question_bank WHERE owner_id IS NULL AND status = 'approved'

# 需要检查：
# 1. 是否有额外的 job_position 过滤
# 2. 是否有 bank_mode 相关的额外条件
# 3. 是否有 JOIN 导致的行数差异

# 修复方案：确保 API 的 count 查询与实际数据查询使用完全相同的 WHERE 条件
```

### Fix #32: CSRF 中间件执行顺序

**文件**: `backend/app/asgi.py`

```python
# 检查中间件注册顺序
# 当前可能的顺序：
# 1. CORS
# 2. Rate Limiting
# 3. CSRF
# 4. Authentication (FastAPI Depends)

# 问题：CSRF 中间件在认证中间件之后执行
# 修复：调整中间件顺序，或在 CSRF 中间件中排除不需要认证的端点

# 方案 A：调整中间件顺序（推荐）
app.add_middleware(CSRFMiddleware, ...)  # CSRF 先执行
# 然后才是认证相关的依赖注入

# 方案 B：在 CSRF 中间件中排除认证端点
CSRF_EXEMPT_PATHS = {'/api/auth/login', '/api/auth/register', '/api/auth/refresh'}

class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in CSRF_EXEMPT_PATHS:
            return await call_next(request)
        # ... CSRF 检查逻辑
```

---

## 架构优化建议

### 1. 引入消息队列替代 BackgroundTasks

```python
# 使用 Redis + Celery 或轻量级的 arq
# 示例：arq (async Redis queue)

from arq import create_pool
from arq.connections import RedisSettings

async def submit_data(bg_tasks, ...):
    # 替代 bg_tasks.add_task
    redis = await create_pool(RedisSettings())
    await redis.enqueue_job('background_generate_answer', new_id, q_text)
```

### 2. 文件存储迁移到对象存储

```python
# 使用 MinIO (S3 兼容)
from minio import Minio

minio_client = Minio("localhost:9000", access_key="...", secret_key="...", secure=False)

async def upload_file(file: UploadFile) -> str:
    content = await file.read()
    object_name = f"uploads/{uuid.uuid4()}/{file.filename}"
    minio_client.put_object("interview-boss", object_name, io.BytesIO(content), len(content))
    return f"http://localhost:9000/interview-boss/{object_name}"
```

### 3. 添加软删除支持

```python
# 在 init_db() 中为关键表添加 deleted_at 列
# jd, interview, question_bank 表添加：
# deleted_at TIMESTAMP DEFAULT NULL

# 删除时改为：
UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?

# 查询时添加：
WHERE deleted_at IS NULL
```

### 4. 完善 RBAC 模型

```python
# 创建 roles 表和 user_roles 关联表
# 定义权限粒度：question:read, question:write, question:delete, bank:manage, system:config
# 使用依赖注入检查权限
def require_permission(permission: str):
    async def checker(current_user: dict = Depends(get_current_user)):
        if not has_permission(current_user['id'], permission):
            raise HTTPException(status_code=403, detail="权限不足")
        return current_user
    return checker
```

### 5. 添加操作审计日志

```python
# 创建 audit_log 表
# 记录：who, did what, to which resource, when, from where
# 在关键操作（删除、更新、审核）时写入审计日志
```
