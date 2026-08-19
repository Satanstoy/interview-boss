# Spec: 简历分析模块修复 — 记忆同步 / 事件循环 / 缺少 max_tokens / 架构 / 测试 / UX

> 位置: `backend/app/services/resume_service.py` + `backend/app/routers/profile_pkg/resume.py` + `backend/app/routers/chat.py` + `backend/app/services/chat_memory_service.py` + `backend/app/agents/chat/nodes.py` + `backend/app/db/migrations/resume.py` + `frontend/src/views/ResumeView.vue`
> 类型: 技术质量 spec（tech-audit 深度审计）
> 日期: 2026-08-18
> 状态: 待实施
> 审计依据: `.tech-audit/work/2026-08-18/findings.tsv`（16 条 findings，8 维度；0 🔴 / 6 🟡 / 10 🟢）
> Repo HEAD: ef62c310
> 方法: TDD（先写失败测试）→ 最小实现 → 验证 → 提交

## 背景

tech-audit 对简历分析模块（上传/CRUD、SSE 优化、chat 简历集成、评测适配器）做了完整审查：实测 27 passed / 2 skipped。发现 6 个 🟡 与 10 个 🟢，无 🔴。最重要的三个：

1. **双份简历不同步（D9）**：`user_resumes.raw_text` 与 `chat_memories`（`memory_type='resume'`）是两份拷贝；删除/替换简历后 chat 记忆中的旧简历仍被面试 agent 召回（含已删除简历的 PII）。
2. **事件循环被阻塞（D14）**：两个 async 路由直接同步跑 pdfplumber 解析，10MB 恶意/扫描件 PDF 可卡住全站。
3. **缺少 max_tokens（D14）**：优化全文阶段 `stream_llm_messages` 不传 `max_tokens`，OpenAI 兼容流式路径无默认值注入，服务端默认值可能静默截断优化版简历。

**最佳实践参考**：

| 问题 | 参考方案 | 核心原则 |
|------|---------|---------|
| 简历双份不同步 | AWS Bedrock agent memory / LangChain memory | Single source of truth：agent 统一读 `user_resumes`；save/delete 时停用 `chat_memories` 简历记忆 |
| 事件循环阻塞 | FastAPI 文档 async def CPU 工作 | 把同步 CPU 工作丢到线程池（`asyncio.to_thread`） |
| max_tokens 缺失 | 项目既有约定（services/CLAUDE.md） | 所有 LLM 调用显式下发 max_tokens（默认 4096） |
| 路由含业务逻辑 | 项目路由铁律（routers/CLAUDE.md） | 路由只做 HTTP 感知，业务逻辑在 services |
| 删除无确认 | 项目 ConfirmDialog 惯例 | Destructive action 必须单次 styled confirm |

---

## 实施顺序

数据一致性（D9）→ 运行时安全（D14 事件循环/max_tokens）→ 架构（D1）→ 测试（D3）→ UX（D15）→ 加固批次（🟢）。

---

## Task A: 简历记忆单一事实源 + 删除同步停用 🟡（M39）

**Files:**

- Edit: `backend/app/services/chat_memory_service.py`
- Edit: `backend/app/services/resume_service.py`
- Edit: `backend/app/agents/chat/nodes.py`
- Create: `backend/tests/services/test_resume_chat_memory_sync.py`

**现状**（已核实源码）：
- `resume_service.save_resume()`（:56-66）写 `user_resumes`，**不触碰 `chat_memories`**
- `resume_service.delete_resume()`（:117-125）只删 `user_resumes`，**旧简历仍在 chat_memories 被 `get_resume_memory`（chat_memory_service.py:187-197）召回**
- `agents/chat/nodes.py:186-193 recall_memories` 用 `chat_service.get_resume_memory(user_id)` 填充 `resume_summary` → free_practice 面试提示词缝合旧简历（nodes.py:730-732）
- `chat.py:86-89`：仅当 resume_text != "__saved__" 时写 chat_memories；profile 上传路径完全不写 chat 记忆

**方案**：agent 的简历上下文统一从 `user_resumes` 读取（单一事实源）；profile save/delete 时把 `chat_memories` 的简历记忆一并停用，防止已删简历 PII 残留 recall。

**Step 1（RED）**：写 `test_resume_chat_memory_sync.py`：

- `test_save_resume_deactivates_stale_resume_memory`：先 `save_resume_memory(u, "旧简历")` 再 `save_resume(u, ...)` → `get_resume_memory(u)` 不再返回旧简历内容
- `test_delete_resume_deactivates_resume_memory`：`save_resume_memory(u, "内容")` → `delete_resume(u)` → `get_resume_memory(u)` 为 `None`
- `test_recall_nodes_prefers_user_resumes`：mock `resume_service.get_resume_text` 返回新简历、`chat_service.get_resume_memory` 返回旧简历 → `recall_memories` 产出的 `resume_summary` 等于新简历

**Step 2**：跑测试确认失败（Docker test-runtime）

**Step 3（GREEN）**：

```python
# chat_memory_service.py — 新增：停用用户全部简历记忆
def deactivate_resume_memories(user_id: int) -> int:
    """停用用户所有 active 简历记忆（profile save/delete 时同步清理）。"""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "UPDATE chat_memories SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
            "WHERE user_id = ? AND memory_type = 'resume' AND is_active = 1",
            (user_id,),
        )
        conn.commit()
        return cursor.rowcount
```

```python
# resume_service.py — save_resume 末尾追加（在 conn.commit() 之后）：
from app.services.chat_memory_service import deactivate_resume_memories  # 顶部 import（延迟 import 亦可）

def save_resume(user_id: int, filename: str, raw_text: str) -> int:
    with get_db_connection() as conn:
        conn.execute("DELETE FROM user_resumes WHERE user_id = ?", (user_id,))
        cursor = conn.execute(
            "INSERT INTO user_resumes (user_id, filename, raw_text) VALUES (?, ?, ?)",
            (user_id, filename, raw_text),
        )
        conn.commit()
        resume_id = cursor.lastrowid
    # 同步停用 chat 旧简历记忆；失败不阻断上传（记录日志）
    try:
        deactivate_resume_memories(user_id)
    except Exception:
        logger.exception("停用旧简历记忆失败")
    return resume_id
```

测试使用 `test_db` 内存库时 `deactivate_resume_memories` 会拿到同一连接，行为一致；`save_resume` 需在 `conn.commit()` 后再调用（否则与后续 ROLLBACK 冲突）。

```python
# resume_service.py — delete_resume 同理：
def delete_resume(user_id: int) -> bool:
    with get_db_connection() as conn:
        cursor = conn.execute("DELETE FROM user_resumes WHERE user_id = ?", (user_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
    try:
        deactivate_resume_memories(user_id)
    except Exception:
        logger.exception("删除简历时停用记忆失败")
    return deleted
```

```python
# nodes.py — recall_memories 改为统一读 user_resumes（单一事实源），经 run_db 包装：
async def recall_memories(state: ChatState) -> dict:
    """加载简历（优先 user_resumes 事实源 + chat 记忆兜底）。"""
    user_id = state["user_id"]
    resume_summary = chat_service.get_resume_memory(user_id)
    try:
        from app.services import resume_service
        from app.db.connection import run_db
        resume_text = await run_db(lambda: resume_service.get_resume_text(user_id))
        if resume_text:
            resume_summary = resume_text
    except Exception:
        pass
    return {"memory_summaries": [], "resume_summary": resume_summary}
```

（节点内 DB 操作必须经 `run_db` 包装，符合 agents/CLAUDE.md。实施时删除占位的 maps。）

**Step 4**：跑全量简历 + chat 测试确认通过

**Step 5**：提交 `fix(resume): single source of truth for resume memory + deactivate stale chat memories`

**Done when**：profile 上传/删除简历后 `get_resume_memory` 不再返回旧简历；free_practice 面试使用 `user_resumes` 当前文本。

---

## Task B: PDF 解析 offload 到线程池 🟡（M40）

**Files:**

- Edit: `backend/app/routers/profile_pkg/resume.py`
- Edit: `backend/app/routers/chat.py`
- Edit: `backend/tests/services/test_resume_optimize_endpoint.py`

**现状**（已核实源码）：
- `profile_pkg/resume.py:42` `raw_text = resume_service.extract_pdf_text(content)` 在 async 路由内同步执行
- `chat.py:706` 同样同步执行
- pdfplumber 是 CPU 密集解析；10MB 恶意/扫描件可阻塞事件循环数秒，拖垮全站

**Step 1（RED）**：在 `test_resume_optimize_endpoint.py` 增加测试：mock `asyncio.to_thread`，断言它被用于包裹 `extract_pdf_text`（变异验证：去掉 to_thread 则测试变红）。

**Step 2（GREEN）**：

```python
# profile_pkg/resume.py — 顶部补 import asyncio；upload_resume 内：
raw_text = await asyncio.to_thread(resume_service.extract_pdf_text, content)
```

```python
# chat.py — 顶部补 import asyncio；extract_pdf 内：
full_text = await asyncio.to_thread(resume_service.extract_pdf_text, content)
```

**Step 3**：跑 `backend/tests/security/test_upload_size_guard.py` 与简历端点测试确认通过

**Step 4**：提交 `perf(resume): offload pdfplumber parsing to threadpool in async routes`

**Done when**：`extract_pdf_text` 不再直接在事件循环内执行；两处路由均经 `asyncio.to_thread`。

---

## Task C: 优化全文阶段显式 max_tokens 🟡（M41）

**Files:**

- Edit: `backend/app/routers/profile_pkg/resume.py`（或移入 service 后在 service 改）
- Edit: `backend/tests/services/test_resume_optimize_endpoint.py`

**现状**（已核实源码）：
- `optimize_resume_event_stream` 第一阶段要点 `raw_llm_call` 已传 `max_tokens=1024`
- **第二阶段全文 `stream_llm_messages`（:120-129）只传 `temperature=0.4`，无 max_tokens**；OpenAI 兼容流式路径（llm.py:1929-1933）直接把 kwargs 传给 `chat.completions.create`，服务端默认值（部分网关 100-500 token）会静默截断优化版

**Step 1（RED）**：`test_optimize_streams_points_delta_done` 的 `fake_stream` 捕获 `kwargs`，断言第二次（全文）调用带 `max_tokens`（≥4096）。

**Step 2**：跑测试确认失败

**Step 3（GREEN）**：在全文 `stream_llm_messages` 调用追加 `max_tokens=4096`。

**Step 4**：跑测试确认通过

**Step 5**：提交 `fix(resume): pass explicit max_tokens to optimized-text streaming call`

**Done when**：优化全文流式调用显式下发 max_tokens，不再依赖服务端默认值。

---

## Task D: 优化 SSE 生成器移入 services（架构铁律）🟡（M42）

**Files:**

- Edit: `backend/app/services/resume_service.py`
- Edit: `backend/app/routers/profile_pkg/resume.py`
- Edit: `backend/tests/services/test_resume_optimize_endpoint.py`

**现状**（已核实源码）：
- `optimize_resume_event_stream`（resume.py:106-168）在 router 内持有 LLM 编排、JSON 解析、持久化，违反 routers「禁止业务逻辑」
- 端点 `optimize_resume`（:176-194）只调 has_resume + StreamingResponse——搬走后路由更薄

**Step 1（RED）**：`test_resume_optimize_endpoint.py` 内的 import 从 `app.routers.profile_pkg.resume.optimize_resume_event_stream` 改为 `app.services.resume_service.optimize_resume_event_stream`（测试先改 import → fail）。

**Step 2**：确认失败（ImportError）

**Step 3（GREEN）**：把 generator 移到 `resume_service.py`（签名改为 `user_id: int`，内部 `user["id"]` → `user_id`），router 保留薄包装：

```python
# resume.py — 端点改为：
return StreamingResponse(
    resume_service.optimize_resume_event_stream(user["id"], position),
    media_type="text/event-stream",
    headers={"X-Accel-Buffering": "no"},
)
```

router 内删除 `raw_llm_call`/`stream_llm_messages`/`_extract_json` 依赖与 build_*_prompt import（若不再使用）。

**Step 4**：跑简历端点测试确认通过

**Step 5**：提交 `refactor(resume): move optimize SSE generator from router into resume_service`

**Done when**：router 不再持有 LLM 编排逻辑；service 可独立测试。

---

## Task E: 补齐对抗性测试缺口 🟡（M43）

**Files:**

- Create: `backend/tests/services/test_resume_adversarial.py`

**现状**：审查确认以下路径无测试：HTTP 级 upload/delete/get-metadata happy path、错误类型 position、dict-envelope points、50k 截断、重复上传单行不变量、跨用户隔离、陈旧 chat 记忆回归。

**Step 1（RED→GREEN 逐条）**：

1. **HTTP 级 upload**：patch `resume_service.extract_pdf_text` 返回文本 + patch `save_resume` 返回 id → `POST /api/profile/resume` 断言 200 + {"status","id","filename"}
2. **HTTP 级 delete**：seed 后 `DELETE /api/profile/resume` 断言 200；无简历断言 404
3. **HTTP 级 metadata**：GET /api/profile/resume 断言返回不含 raw_text 键
4. **错误类型 position**：`POST /api/profile/resume/optimize` body `{"position": ["x"]}` 断言 422/400 而非 500
5. **dict-envelope points**：`fake_raw_llm_call` 返回 `{"points": ["a","b"]}` → SSE points 事件 = ["a","b"]
6. **50k 截断**：mock `extract_pdf_text` 返回 60000 字符 → 断言落库 raw_text ≤ 50000 + 含 "(文本过长，已截断)"
7. **跨用户隔离**：user A seed 简历，dependency_overrides 切 user B → GET /api/profile/resume 断言 has_resume False
8. **重复上传单行**：upload 两次 → `SELECT COUNT(*) FROM user_resumes WHERE user_id` 断言 = 1

**Step 2**：全量跑测试（含 mutation 验证：去掉对应 guard 后应变红）

**Step 3**：提交 `test(resume): adversarial coverage for endpoints, truncation, isolation`

**Done when**：上述 8 个场景均有通过测试；无 500 灰洞路径。

---

## Task F: 删除确认 + a11y + SSE abort 🟡/🟢（M44）

**Files:**

- Edit: `frontend/src/views/ResumeView.vue`

**现状**：
- `handleDelete`（:102-114）直接删除，无确认——简历+优化历史不可逆丢失
- Trash2 图标按钮（:171）无 aria-label/AppTooltip
- `optimizeResume` 不传 AbortController，组件卸载后流式请求不中断

**Step 1（RED）**：Playwright smoke 断言「删除简历出现确认框」。

**Step 2（GREEN）**：

```javascript
// ResumeView.vue
import { useConfirm } from '@/composables/useNotification.js'
const { confirm: showConfirm } = useConfirm()

async function handleDelete() {
  const ok = await showConfirm('删除后简历原文与优化记录将不可恢复，确定删除？', {
    title: '删除简历',
    confirmLabel: '删除',
  })
  if (!ok) return
  try {
    await deleteResume()
    toast.success('简历已删除')
    resume.value = null
    rawText.value = ''
    savedOptimization.value = null
    points.value = []
    optimizedText.value = ''
  } catch (e) {
    toast.error(`删除失败：${e.message || '请稍后重试'}`)
  }
}
```

```html
<!-- ResumeView.vue — 删除按钮加 aria-label -->
<Button variant="ghost" size="sm" class="text-destructive" aria-label="删除简历" @click="handleDelete">
  <Trash2 :size="14" />
</Button>
```

```javascript
// ResumeView.vue — SSE 离开页面即中止
import { onUnmounted } from 'vue'

let abortOptimize = null

async function handleOptimize() {
  // ...
  try {
    await optimizeResume(position, (event) => { /* 现有事件处理 */ }, {
      onController: (c) => { abortOptimize = c },
    })
  } finally {
    optimizing.value = false
  }
}

onUnmounted(() => { abortOptimize?.abort() })
```

（http.js:459 `options.onController` 已存在，postSSE 支持传 AbortController。）

**Step 3**：`cd frontend && npm run build` + `npm run test`

**Step 4**：提交 `fix(frontend): confirm on resume delete, button a11y label, abort SSE on unmount`

**Done when**：删除有确认弹窗；删除按钮有可访问名；离开页面不再继续请求 optimize。

---

## Task G: 加固批次 🟢/🟡（M45）

**Files:**

- Edit: `backend/app/db/migrations/resume.py` + `backend/app/db/migrations/__init__.py`
- Edit: `backend/app/services/resume_service.py`
- Edit: `backend/app/routers/profile_pkg/resume.py`
- Edit: `frontend/src/views/ResumeView.vue`

### G1: UNIQUE(user_id) 迁移（D9 🟢）

```python
# migrations/resume.py — 新增 migration（编号按 migrations/__init__.py 当前最大 +1）
def _migration_094_resume_user_unique(conn):
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_resume_user_unique "
        "ON user_resumes(user_id)"
    )
```

在 `migrations/__init__.py` `_MIGRATIONS` 末尾登记 `(94, "resume_user_unique", ...)`（以实际编号为准）。

### G2: get_resume 轻量 meta 查询（D10 🟢）

```python
# resume_service.py — 新增
def get_resume_meta(user_id: int) -> Optional[dict]:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, filename, created_at FROM user_resumes WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    return {"id": row[0], "filename": row[1], "created_at": row[2]}
```

router GET /api/profile/resume 改用 `get_resume_meta`（不再 SELECT raw_text）。保留 `get_resume` 供测试/未来使用。

### G3: points 强制 str + dict-envelope 校验（D14 🟢）

```python
# resume.py（或 service）— 解析 points 后强制 str
if not isinstance(points, list):
    points = []
points = [str(p) for p in points]
```

### G4: optimize body 用 Pydantic 模型（D14 🟢）

```python
# resume.py — 新增请求模型
from pydantic import BaseModel, Field

class OptimizeResumeRequest(BaseModel):
    position: str = Field(..., min_length=1, max_length=100)

@router.post("/api/profile/resume/optimize")
async def optimize_resume(
    body: OptimizeResumeRequest,
    user: dict = Depends(get_current_user),
):
    position = body.position.strip()
    # ... 其余不变（校验非空已在模型层完成，保留 has_resume 检查）
```

### G5: save_optimization 返回值检查（D14 🟢）

```python
# service 生成器内，save 后检查：
saved = await run_db(lambda: resume_service.save_optimization(
    user["id"], position, points, optimized_text
))
if not saved:
    yield f"data: {json.dumps({'type': 'error', 'message': '未找到简历，可能已删除'}, ensure_ascii=False)}\n\n"
    return
yield f"data: {json.dumps({'type': 'done', 'position': position}, ensure_ascii=False)}\n\n"
```

### G6: extract_pdf_text 记录根因日志（D14 🟢）

```python
def extract_pdf_text(pdf_bytes: bytes) -> str:
    import pdfplumber
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            text_parts = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text.strip())
            return "\n\n".join(text_parts)
    except Exception as e:
        logger.warning("PDF 解析失败: %s", e)
        raise ValueError("无效的 PDF 文件，无法解析") from e
```

### G7: 前端 shadcn 组件替换（D16 🟢）

- `<select>` → shadcn Select（`ui/select`）
- 复选框 → shadcn Checkbox（`ui/checkbox`）
- 文件输入保留原生隐藏 input（file dialog 无 shadcn 等价，项目允许 hidden input 模式）

### G8: updated_at 死列（D9 🟢）

`save_resume` INSERT 时显式写 `updated_at = CURRENT_TIMESTAMP`；`save_optimization` UPDATE 时设置 `updated_at = CURRENT_TIMESTAMP`（消除死列歧义）。

**验证**：全量简历/安全测试 + `cd frontend && npm run build`。

**提交**（每项独立 commit，conventional commits 英文；每项按需带回归测试）。

---

## 验证方案

### 后端测试

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_resume_service.py backend/tests/services/test_resume_optimize_endpoint.py backend/tests/services/test_resume_adversarial.py backend/tests/services/test_resume_chat_memory_sync.py -q -v
docker compose --profile test run --rm test uv run pytest backend/tests/security/test_upload_size_guard.py -q
docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q
```

### 前端

```bash
cd frontend && npm run build
cd frontend && npm run test
```

### 手动验证

1. **上传→替换→删除**：上传 A 简历 → 新开自由面试确认用 A → 删除简历 → 再开面试确认不再出现简历内容
2. **优化**：选职位生成优化版，确认全文完整（无明显截断）
3. **删除弹窗**：点删除确认出现 styled confirm
4. **10MB 大 PDF**：上传约 8MB 真实 PDF，确认页面不卡（解析在线程池）

## 里程碑对照

| 条目 | 里程碑 | Effort |
|------|--------|--------|
| Task A D9 记忆同步 | M39 | 2-4h |
| Task B D14 事件循环 | M40 | 30min |
| Task C D14 max_tokens | M41 | 30min |
| Task D D1 架构 | M42 | 2-4h |
| Task E D3 测试 | M43 | 4h |
| Task F D15 UX | M44 | 30min |
| Task G 加固 | M45 | 4h |

## 修改后必做

1. 更新 `backend/app/services/CLAUDE.md`（resume_service 职责变化 + 记忆同步）
2. 更新 `backend/app/routers/profile_pkg/CLAUDE.md`（resume 端点薄化）
3. 更新 `frontend/src/views/CLAUDE.md`（ResumeView UX 变化）
4. 更新 `docs/compliance/privacy-policy.md`（明确简历删除会同步停用 chat 记忆中的简历副本；account-deletion 保持级联一致）
5. backend/app 改动后跑 `pytest backend/tests/services/ -q` 与 chat 全量；每条 fix 提交带对应回归测试（audit D3 ≥80% 红线）