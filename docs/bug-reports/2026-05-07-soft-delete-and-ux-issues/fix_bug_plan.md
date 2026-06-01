# 修复计划

**Bug ID:** BUG-001 ~ BUG-005
**日期:** 2026-05-07
**优先级:** P0 (BUG-001), P1 (BUG-002, BUG-005), P2 (BUG-003, BUG-004)

---

## BUG-001: question_bank 软删除改造

### 步骤 1: 为 question_bank 表添加 deleted_at 字段

**文件:** `backend/app/db/connection.py`
**行号:** 299-353 (question_bank 表相关迁移)
**修改类型:** 新增

**修改前:**
```python
cursor.execute("PRAGMA index_list('question_bank')")
qb_indexes = [row[1] for row in cursor.fetchall()]
if "idx_qb_owner_status" not in qb_indexes:
    conn.execute("CREATE INDEX idx_qb_owner_status ON question_bank(owner_id, status)")
```

**修改后:**
```python
cursor.execute("PRAGMA index_list('question_bank')")
qb_indexes = [row[1] for row in cursor.fetchall()]
if "idx_qb_owner_status" not in qb_indexes:
    conn.execute("CREATE INDEX idx_qb_owner_status ON question_bank(owner_id, status)")

# 添加 deleted_at 字段支持软删除
qb_columns = {row[1] for row in cursor.execute("PRAGMA table_info('question_bank')").fetchall()}
if "deleted_at" not in qb_columns:
    conn.execute("ALTER TABLE question_bank ADD COLUMN deleted_at TIMESTAMP")
```

### 步骤 2: 修改单条删除为软删除

**文件:** `backend/app/routers/master_bank.py`
**行号:** 805-839
**修改类型:** 修正

**修改前:**
```python
@router.delete("/api/master-bank/{question_id}")
async def delete_master_question(question_id: int, user: dict = Depends(get_current_user)):
    def _delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT id, question, sources, owner_id FROM question_bank WHERE id = ?", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目，可能已被删除")

            # 权限检查：公共题目仅管理员可删，个人题目仅本人可删
            is_admin = user.get('is_admin', 0)
            if row['owner_id'] is None and not is_admin:
                raise HTTPException(status_code=403, detail="无权删除公共题目")
            if row['owner_id'] is not None and row['owner_id'] != user['id'] and not is_admin:
                raise HTTPException(status_code=403, detail="无权删除他人的个人题目")

            # 联动清理 questions_detail 中对应的记录
            question_text = row['question']
            if question_text:
                cursor.execute("DELETE FROM questions_detail WHERE question = ?", (question_text,))

            # Bug #14: 级联清理 user_question_view 和 question_position
            cursor.execute("DELETE FROM user_question_view WHERE question_bank_id = ?", (question_id,))
            cursor.execute("DELETE FROM question_position WHERE question_id = ?", (question_id,))
            cursor.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
            cursor.execute("DELETE FROM user_practice_history WHERE question_bank_id = ?", (question_id,))
            conn.commit()

    try:
        await run_db(_delete)
        return {"status": "success", "message": "题目删除成功（已联动清理 questions_detail 和练习历史）"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="删除失败，请查看服务端日志")
```

**修改后:**
```python
@router.delete("/api/master-bank/{question_id}")
async def delete_master_question(question_id: int, user: dict = Depends(get_current_user)):
    def _delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT id, question, sources, owner_id, deleted_at FROM question_bank WHERE id = ?", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目，可能已被删除")
            if row['deleted_at']:
                raise HTTPException(status_code=404, detail="该题目已被删除")

            # 权限检查：公共题目仅管理员可删，个人题目仅本人可删
            is_admin = user.get('is_admin', 0)
            if row['owner_id'] is None and not is_admin:
                raise HTTPException(status_code=403, detail="无权删除公共题目")
            if row['owner_id'] is not None and row['owner_id'] != user['id'] and not is_admin:
                raise HTTPException(status_code=403, detail="无权删除他人的个人题目")

            # 软删除：设置 deleted_at
            cursor.execute("UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?", (question_id,))

            # 联动软删除 questions_detail 中对应的记录
            question_text = row['question']
            if question_text:
                cursor.execute("UPDATE questions_detail SET deleted_at = CURRENT_TIMESTAMP WHERE question = ? AND deleted_at IS NULL", (question_text,))

            conn.commit()

    try:
        await run_db(_delete)
        return {"status": "success", "message": "题目已移至回收站"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="删除失败，请查看服务端日志")
```

### 步骤 3: 修改批量删除为软删除

**文件:** `backend/app/routers/master_bank.py`
**行号:** 842-888
**修改类型:** 修正

**修改前:**
```python
@router.post("/api/master-bank/batch-delete")
async def batch_delete_master_bank(req: BatchDeleteRequest, user: dict = Depends(get_current_user)):
    """批量删除题库题目，单事务完成"""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    def _batch_delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(req.ids))
            rows = cursor.execute(
                f"SELECT id, question, owner_id FROM question_bank WHERE id IN ({placeholders})", req.ids
            ).fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail="未找到任何匹配记录")

            # 权限检查
            is_admin = user.get('is_admin', 0)
            for r in rows:
                if r['owner_id'] is None and not is_admin:
                    raise HTTPException(status_code=403, detail=f"无权删除公共题目 (id={r['id']})")
                if r['owner_id'] is not None and r['owner_id'] != user['id'] and not is_admin:
                    raise HTTPException(status_code=403, detail=f"无权删除他人的个人题目 (id={r['id']})")

            question_texts = [r["question"] for r in rows if r["question"]]
            if question_texts:
                qph = ",".join("?" * len(question_texts))
                cursor.execute(f"DELETE FROM questions_detail WHERE question IN ({qph})", question_texts)

            found_ids = [r["id"] for r in rows]
            ph2 = ",".join("?" * len(found_ids))
            # Bug #14: 级联清理 user_question_view 和 question_position
            cursor.execute(f"DELETE FROM user_question_view WHERE question_bank_id IN ({ph2})", found_ids)
            cursor.execute(f"DELETE FROM question_position WHERE question_id IN ({ph2})", found_ids)
            cursor.execute(f"DELETE FROM question_bank WHERE id IN ({ph2})", found_ids)
            cursor.execute(f"DELETE FROM user_practice_history WHERE question_bank_id IN ({ph2})", found_ids)
            conn.commit()
            return len(found_ids)

    try:
        deleted = await run_db(_batch_delete)
        return {"status": "success", "deleted": deleted}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("批量删除失败")
        raise HTTPException(status_code=500, detail="批量删除失败，请查看服务端日志")
```

**修改后:**
```python
@router.post("/api/master-bank/batch-delete")
async def batch_delete_master_bank(req: BatchDeleteRequest, user: dict = Depends(get_current_user)):
    """批量软删除题库题目，单事务完成"""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    def _batch_delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(req.ids))
            rows = cursor.execute(
                f"SELECT id, question, owner_id, deleted_at FROM question_bank WHERE id IN ({placeholders})", req.ids
            ).fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail="未找到任何匹配记录")

            # 权限检查
            is_admin = user.get('is_admin', 0)
            for r in rows:
                if r['deleted_at']:
                    continue  # 跳过已删除的记录
                if r['owner_id'] is None and not is_admin:
                    raise HTTPException(status_code=403, detail=f"无权删除公共题目 (id={r['id']})")
                if r['owner_id'] is not None and r['owner_id'] != user['id'] and not is_admin:
                    raise HTTPException(status_code=403, detail=f"无权删除他人的个人题目 (id={r['id']})")

            # 过滤出未删除的记录
            active_rows = [r for r in rows if not r['deleted_at']]
            if not active_rows:
                return 0

            question_texts = [r["question"] for r in active_rows if r["question"]]
            if question_texts:
                qph = ",".join("?" * len(question_texts))
                cursor.execute(f"UPDATE questions_detail SET deleted_at = CURRENT_TIMESTAMP WHERE question IN ({qph}) AND deleted_at IS NULL", question_texts)

            found_ids = [r["id"] for r in active_rows]
            ph2 = ",".join("?" * len(found_ids))
            # 软删除 question_bank 记录
            cursor.execute(f"UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP WHERE id IN ({ph2})", found_ids)
            conn.commit()
            return len(found_ids)

    try:
        deleted = await run_db(_batch_delete)
        return {"status": "success", "deleted": deleted}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("批量删除失败")
        raise HTTPException(status_code=500, detail="批量删除失败，请查看服务端日志")
```

### 步骤 4: 修改题库重建为软删除

**文件:** `backend/app/routers/master_bank.py`
**行号:** 314-328
**修改类型:** 修正

**修改前:**
```python
# 清除该岗位下的旧题目（仅公共题库）
cursor.execute("DELETE FROM question_bank WHERE job_position = ? AND owner_id IS NULL", (position,))
```

**修改后:**
```python
# 软删除该岗位下的旧题目（仅公共题库）
cursor.execute("UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP WHERE job_position = ? AND owner_id IS NULL AND deleted_at IS NULL", (position,))
```

### 步骤 5: 添加回收站查询和恢复接口

**文件:** `backend/app/routers/master_bank.py`
**行号:** 在删除接口之后添加
**修改类型:** 新增

**新增代码:**
```python
@router.get("/api/master-bank/trash")
async def get_trash(page: int = 1, page_size: int = 50, user: dict = Depends(get_current_user)):
    """获取题库回收站"""
    is_admin = user.get('is_admin', 0)

    def _query():
        with get_db_connection() as conn:
            if is_admin:
                # 管理员可以看到所有已删除的题目
                total = conn.execute(
                    "SELECT COUNT(*) FROM question_bank WHERE deleted_at IS NOT NULL"
                ).fetchone()[0]
                rows = conn.execute(
                    "SELECT id, question, cat1, cat2, tags, difficulty, owner_id, deleted_at "
                    "FROM question_bank WHERE deleted_at IS NOT NULL "
                    "ORDER BY deleted_at DESC LIMIT ? OFFSET ?",
                    (page_size, (page - 1) * page_size)
                ).fetchall()
            else:
                # 普通用户只能看到自己删除的个人题目
                total = conn.execute(
                    "SELECT COUNT(*) FROM question_bank WHERE deleted_at IS NOT NULL AND owner_id = ?",
                    (user['id'],)
                ).fetchone()[0]
                rows = conn.execute(
                    "SELECT id, question, cat1, cat2, tags, difficulty, owner_id, deleted_at "
                    "FROM question_bank WHERE deleted_at IS NOT NULL AND owner_id = ? "
                    "ORDER BY deleted_at DESC LIMIT ? OFFSET ?",
                    (user['id'], page_size, (page - 1) * page_size)
                ).fetchall()
            return total, [dict(r) for r in rows]

    total, items = await run_db(_query)
    return {"total": total, "items": items, "page": page, "page_size": page_size}


@router.post("/api/master-bank/restore/{question_id}")
async def restore_question(question_id: int, user: dict = Depends(get_current_user)):
    """恢复已删除的题目"""
    def _restore():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT id, question, owner_id, deleted_at FROM question_bank WHERE id = ?",
                (question_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目")
            if not row['deleted_at']:
                raise HTTPException(status_code=400, detail="该题目未被删除")

            # 权限检查
            is_admin = user.get('is_admin', 0)
            if row['owner_id'] is None and not is_admin:
                raise HTTPException(status_code=403, detail="无权恢复公共题目")
            if row['owner_id'] is not None and row['owner_id'] != user['id'] and not is_admin:
                raise HTTPException(status_code=403, detail="无权恢复他人的个人题目")

            # 恢复题目
            cursor.execute("UPDATE question_bank SET deleted_at = NULL WHERE id = ?", (question_id,))

            # 联动恢复 questions_detail
            question_text = row['question']
            if question_text:
                cursor.execute("UPDATE questions_detail SET deleted_at = NULL WHERE question = ? AND deleted_at IS NOT NULL", (question_text,))

            conn.commit()

    try:
        await run_db(_restore)
        return {"status": "success", "message": "题目已恢复"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="恢复失败，请查看服务端日志")


@router.post("/api/master-bank/batch-restore")
async def batch_restore_questions(req: BatchDeleteRequest, user: dict = Depends(get_current_user)):
    """批量恢复已删除的题目"""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    def _batch_restore():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(req.ids))
            rows = cursor.execute(
                f"SELECT id, question, owner_id, deleted_at FROM question_bank WHERE id IN ({placeholders}) AND deleted_at IS NOT NULL",
                req.ids
            ).fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail="未找到任何已删除的记录")

            # 权限检查
            is_admin = user.get('is_admin', 0)
            for r in rows:
                if r['owner_id'] is None and not is_admin:
                    raise HTTPException(status_code=403, detail=f"无权恢复公共题目 (id={r['id']})")
                if r['owner_id'] is not None and r['owner_id'] != user['id'] and not is_admin:
                    raise HTTPException(status_code=403, detail=f"无权恢复他人的个人题目 (id={r['id']})")

            found_ids = [r["id"] for r in rows]
            ph = ",".join("?" * len(found_ids))
            cursor.execute(f"UPDATE question_bank SET deleted_at = NULL WHERE id IN ({ph})", found_ids)

            # 联动恢复 questions_detail
            question_texts = [r["question"] for r in rows if r["question"]]
            if question_texts:
                qph = ",".join("?" * len(question_texts))
                cursor.execute(f"UPDATE questions_detail SET deleted_at = NULL WHERE question IN ({qph}) AND deleted_at IS NOT NULL", question_texts)

            conn.commit()
            return len(found_ids)

    try:
        restored = await run_db(_batch_restore)
        return {"status": "success", "restored": restored}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("批量恢复失败")
        raise HTTPException(status_code=500, detail="批量恢复失败，请查看服务端日志")
```

### 步骤 6: 修改查询接口过滤已删除记录

**文件:** `backend/app/routers/master_bank.py`
**行号:** 查询相关的接口
**修改类型:** 修正

需要修改以下查询，添加 `AND deleted_at IS NULL` 条件：
- `GET /api/master-bank` (列表查询)
- `GET /api/master-bank/random` (随机抽题)
- `GET /api/master-bank/search` (搜索)
- 其他查询 question_bank 的接口

---

## BUG-002: 前端导入添加类型和季节选择

### 步骤 1: 修改 StagingPanel.vue 添加类型选择

**文件:** `frontend/src/components/StagingPanel.vue`
**行号:** 60-73 (提交按钮区域)
**修改类型:** 新增

**修改前:**
```vue
<div class="bg-surface-50 dark:bg-surface-900 border-t border-surface-200 dark:border-ink-600 p-4 flex flex-col items-center">
  <div class="flex gap-4 w-full justify-end mb-4">
    <button @click="clearStaging" :disabled="isUploading" class="px-5 py-2 rounded-lg text-ink-600 dark:text-ink-400 hover:bg-surface-200 dark:hover:bg-ink-700 transition">
      清空
    </button>
    <button
      @click="submitAll"
      :disabled="isUploading || (!stagedText.trim() && stagedFiles.length === 0)"
      class="bg-blue-600 text-white font-bold px-8 py-2 rounded-lg hover:bg-blue-700 transition shadow-md disabled:bg-blue-300 dark:disabled:bg-blue-800 disabled:cursor-not-allowed flex items-center gap-2"
    >
      <svg v-if="isUploading" class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
      {{ isUploading ? 'AI 正在解析中...' : '提交解析' }}
    </button>
  </div>
```

**修改后:**
```vue
<div class="bg-surface-50 dark:bg-surface-900 border-t border-surface-200 dark:border-ink-600 p-4 flex flex-col items-center">
  <!-- 类型和季节选择 -->
  <div class="flex gap-4 w-full mb-4">
    <div class="flex-1">
      <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">导入类型</label>
      <select v-model="importType" class="w-full border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm bg-white dark:bg-surface-800 text-ink-800 dark:text-ink-100 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200">
        <option value="auto">自动识别</option>
        <option value="jd">JD (职位描述)</option>
        <option value="interview">面经</option>
      </select>
    </div>
    <div class="flex-1">
      <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">招聘季节</label>
      <select v-model="selectedSeason" class="w-full border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm bg-white dark:bg-surface-800 text-ink-800 dark:text-ink-100 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200">
        <option v-for="s in availableSeasons" :key="s" :value="s">{{ s }}</option>
        <option value="custom">自定义...</option>
      </select>
      <input v-if="selectedSeason === 'custom'" v-model="customSeason" placeholder="输入招聘季名称" class="mt-2 w-full border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm bg-white dark:bg-surface-800 text-ink-800 dark:text-ink-100 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200" />
    </div>
  </div>

  <div class="flex gap-4 w-full justify-end mb-4">
    <button @click="clearStaging" :disabled="isUploading" class="px-5 py-2 rounded-lg text-ink-600 dark:text-ink-400 hover:bg-surface-200 dark:hover:bg-ink-700 transition">
      清空
    </button>
    <button
      @click="submitAll"
      :disabled="isUploading || (!stagedText.trim() && stagedFiles.length === 0)"
      class="bg-blue-600 text-white font-bold px-8 py-2 rounded-lg hover:bg-blue-700 transition shadow-md disabled:bg-blue-300 dark:disabled:bg-blue-800 disabled:cursor-not-allowed flex items-center gap-2"
    >
      <svg v-if="isUploading" class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
      {{ isUploading ? 'AI 正在解析中...' : '提交解析' }}
    </button>
  </div>
```

### 步骤 2: 添加类型和季节的状态变量

**文件:** `frontend/src/components/StagingPanel.vue`
**行号:** 93-103
**修改类型:** 新增

**修改前:**
```javascript
const props = defineProps({
  activeSeason: { type: String, default: '' }
})

const sourceUrl = ref('')
const stagedText = ref('')
const stagedFiles = ref([])
const isDragging = ref(false)
const isUploading = ref(false)
const uploadResult = ref(null)
const uploadError = ref(null)
```

**修改后:**
```javascript
const props = defineProps({
  activeSeason: { type: String, default: '' },
  availableSeasons: { type: Array, default: () => [] }
})

const sourceUrl = ref('')
const stagedText = ref('')
const stagedFiles = ref([])
const isDragging = ref(false)
const isUploading = ref(false)
const uploadResult = ref(null)
const uploadError = ref(null)

// 类型和季节选择
const importType = ref('auto')
const selectedSeason = ref(props.activeSeason || '')
const customSeason = ref('')

// 监听 activeSeason 变化
watch(() => props.activeSeason, (val) => {
  if (val && !selectedSeason.value) {
    selectedSeason.value = val
  }
})
```

### 步骤 3: 修改 submitAll 函数传递类型和季节

**文件:** `frontend/src/components/StagingPanel.vue`
**行号:** 189-193
**修改类型:** 修正

**修改前:**
```javascript
const formData = new FormData()
formData.append('url', sanitizeText(sourceUrl.value, 2048))
formData.append('text', stagedText.value.slice(0, 100000)) // 100KB text limit
formData.append('season', props.activeSeason || '2027届暑期实习')
stagedFiles.value.forEach(item => formData.append('files', item.file))
```

**修改后:**
```javascript
const formData = new FormData()
formData.append('url', sanitizeText(sourceUrl.value, 2048))
formData.append('text', stagedText.value.slice(0, 100000)) // 100KB text limit

// 处理季节选择
let season = selectedSeason.value
if (season === 'custom') {
  season = customSeason.value.trim()
}
formData.append('season', season || props.activeSeason || '2027届暑期实习')

// 处理类型选择
if (importType.value !== 'auto') {
  formData.append('type', importType.value)
}

stagedFiles.value.forEach(item => formData.append('files', item.file))
```

---

## BUG-003/004: 脏数据清理

### 步骤 1: 清理 job_positions 表脏数据

**文件:** `backend/app/db/connection.py`
**行号:** 在迁移代码之后添加
**修改类型:** 新增

**新增代码:**
```python
# ── 清理脏数据：job_positions 表中的无效岗位 ──
invalid_positions = conn.execute(
    "SELECT id, name FROM job_positions WHERE name LIKE '%test%' OR name LIKE '%测试%' OR LENGTH(name) > 50 OR name LIKE '%!@#$%'"
).fetchall()
if invalid_positions:
    for pos in invalid_positions:
        # 删除关联的 question_position 记录
        conn.execute("DELETE FROM question_position WHERE position_id = ?", (pos['id'],))
        # 删除关联的 taxonomy 记录
        conn.execute("DELETE FROM taxonomy WHERE position_name = ?", (pos['name'],))
        # 删除岗位记录
        conn.execute("DELETE FROM job_positions WHERE id = ?", (pos['id'],))
    logger.info(f"已清理 {len(invalid_positions)} 个无效岗位数据")
```

### 步骤 2: 清理 question_bank 表 cat1 脏数据

**文件:** `backend/app/db/connection.py`
**行号:** 在迁移代码之后添加
**修改类型:** 新增

**新增代码:**
```python
# ── 清理脏数据：question_bank 表中的无效分类 ──
conn.execute("UPDATE question_bank SET cat1 = '' WHERE cat1 = 'test' AND deleted_at IS NULL")
logger.info("已清理 question_bank 表中的无效分类数据")
```

---

## BUG-005: 用户个人 LLM 配置修改优化

### 步骤 1: 优化前端用户体验

**文件:** `frontend/src/components/SettingsPanel.vue`
**行号:** 40-61
**修改类型:** 修正

**修改前:**
```vue
<!-- 已配置：显示摘要 -->
<div v-if="myLLM.configured && !myLLM.editing" class="space-y-2">
  <div class="grid grid-cols-2 gap-3 text-sm">
    <div>
      <span class="text-xs text-ink-500 dark:text-ink-400">API Key</span>
      <div class="font-mono text-ink-700 dark:text-ink-200">{{ myLLM.settings.llm_api_key || '未设置' }}</div>
    </div>
    <div>
      <span class="text-xs text-ink-500 dark:text-ink-400">模型</span>
      <div class="font-mono text-ink-700 dark:text-ink-200">{{ myLLM.settings.llm_model || '未设置' }}</div>
    </div>
    <div>
      <span class="text-xs text-ink-500 dark:text-ink-400">Base URL</span>
      <div class="font-mono text-ink-700 dark:text-ink-200 truncate">{{ myLLM.settings.llm_base_url || '未设置' }}</div>
    </div>
    <div>
      <span class="text-xs text-ink-500 dark:text-ink-400">超时</span>
      <div class="font-mono text-ink-700 dark:text-ink-200">{{ myLLM.settings.llm_timeout || 120 }}s</div>
    </div>
  </div>
  <button @click="startEditMyLLM" class="text-xs text-primary-600 hover:text-primary-800 dark:text-primary-400 dark:hover:text-primary-300 font-medium">修改配置</button>
</div>
```

**修改后:**
```vue
<!-- 已配置：显示摘要 -->
<div v-if="myLLM.configured && !myLLM.editing" class="space-y-2">
  <div class="grid grid-cols-2 gap-3 text-sm">
    <div>
      <span class="text-xs text-ink-500 dark:text-ink-400">API Key</span>
      <div class="font-mono text-ink-700 dark:text-ink-200">{{ myLLM.settings.llm_api_key || '未设置' }}</div>
    </div>
    <div>
      <span class="text-xs text-ink-500 dark:text-ink-400">模型</span>
      <div class="font-mono text-ink-700 dark:text-ink-200">{{ myLLM.settings.llm_model || '未设置' }}</div>
    </div>
    <div>
      <span class="text-xs text-ink-500 dark:text-ink-400">Base URL</span>
      <div class="font-mono text-ink-700 dark:text-ink-200 truncate">{{ myLLM.settings.llm_base_url || '未设置' }}</div>
    </div>
    <div>
      <span class="text-xs text-ink-500 dark:text-ink-400">超时</span>
      <div class="font-mono text-ink-700 dark:text-ink-200">{{ myLLM.settings.llm_timeout || 120 }}s</div>
    </div>
  </div>
  <div class="flex gap-2">
    <button @click="startEditMyLLM" class="text-xs bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 px-3 py-1.5 rounded-lg hover:bg-primary-100 dark:hover:bg-primary-900/50 transition font-medium border border-primary-200 dark:border-primary-800">
      修改配置
    </button>
    <button @click="deleteMyLLM" class="text-xs bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400 px-3 py-1.5 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/50 transition font-medium border border-red-200 dark:border-red-800">
      清除配置
    </button>
  </div>
</div>
```

### 步骤 2: 添加删除 LLM 配置的功能

**文件:** `frontend/src/components/SettingsPanel.vue`
**行号:** 在 saveMyLLM 函数之后添加
**修改类型:** 新增

**新增代码:**
```javascript
const deleteMyLLM = async () => {
  if (!confirm('确定要清除 LLM 配置吗？清除后需要重新配置才能使用 AI 功能。')) return

  myLLM.saving = true
  try {
    await updateMyLLMConfig({
      llm_api_key: '',
      llm_base_url: '',
      llm_model: '',
      llm_timeout: 120
    })
    toast.success('LLM 配置已清除')
    await loadMyLLM()
  } catch (e) {
    myLLM.error = `清除失败: ${e.message}`
  } finally {
    myLLM.saving = false
  }
}
```

### 步骤 3: 添加后端删除 LLM 配置接口

**文件:** `backend/app/routers/profile.py`
**行号:** 在 update_my_llm_config 接口之后添加
**修改类型:** 新增

**新增代码:**
```python
@router.delete("/api/profile/llm")
async def delete_my_llm_config(user: dict = Depends(get_current_user)):
    """删除当前用户的 LLM 配置"""

    def _delete():
        with get_db_connection() as conn:
            conn.execute("DELETE FROM user_llm_config WHERE user_id = ?", (user['id'],))
            conn.commit()

    await run_db(_delete)

    # 清除该用户的 client 缓存
    from app.services.llm import clear_user_client_cache
    clear_user_client_cache(user['id'])

    return {"status": "success", "message": "LLM 配置已清除"}
```

---

## 验证方法

### BUG-001 验证:
1. 删除题目后，检查 `question_bank` 表中 `deleted_at` 字段是否被设置
2. 查询回收站接口，确认已删除题目可见
3. 恢复题目后，确认 `deleted_at` 被清空
4. 确认普通列表查询不包含已删除题目

### BUG-002 验证:
1. 进入导入页面，确认类型选择和季节选择控件存在
2. 选择不同类型和季节，提交后检查数据是否正确保存
3. 选择"自动识别"，确认后端 AI 正常解析

### BUG-003/004 验证:
1. 检查用户设置中的岗位下拉列表，确认无脏数据
2. 检查题库分类筛选，确认无 test 分类

### BUG-005 验证:
1. 配置 LLM 后，确认可以点击"修改配置"按钮
2. 修改配置后，确认保存成功
3. 点击"清除配置"，确认配置被清除

---

## 回滚方案

### BUG-001 回滚:
1. 将软删除的记录恢复：`UPDATE question_bank SET deleted_at = NULL WHERE deleted_at IS NOT NULL`
2. 恢复硬删除代码

### BUG-002 回滚:
1. 恢复 StagingPanel.vue 原始代码

### BUG-003/004 回滚:
1. 从数据库备份恢复脏数据（如果有备份）

### BUG-005 回滚:
1. 恢复 SettingsPanel.vue 原始代码
2. 删除新增的 API 接口
