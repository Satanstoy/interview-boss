# 修复计划

**Bug ID:** BUG-001, BUG-002, BUG-003, BUG-004
**日期:** 2026-05-10
**优先级:** BUG-004(P0) > BUG-003(P1) > BUG-002(P2) > BUG-001(P3)

---

## 步骤 1: [BUG-004] 修复软删除记录污染聚类

**文件:** `backend/app/routers/interview.py`
**行号:** 53-56
**修改类型:** 修正

**修改前:**
```python
rows = conn.execute(
    "SELECT id, question, cat2, sources, original_questions, original_question_sources FROM question_bank "
    "WHERE owner_id IS NULL AND status = 'approved' AND job_position = ?",
    (current_pos,)
).fetchall()
```

**修改后:**
```python
rows = conn.execute(
    "SELECT id, question, cat2, sources, original_questions, original_question_sources FROM question_bank "
    "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL AND job_position = ?",
    (current_pos,)
).fetchall()
```

**说明:** 此处有两处相同查询（非 SSE 版 line:51-56 和 SSE 版 line:148-153），都需要修改。

**验证方法:**
1. 软删除一条面经，确认关联 question_bank 记录有 deleted_at
2. 重新分析另一条包含类似题目的面经
3. 检查后端日志，确认匹配结果不包含已删除的聚类

**回滚方案:** 删除 `AND deleted_at IS NULL` 条件即可回滚

---

## 步骤 2: [BUG-003] 丰富 SSE 事件内容，添加分析详情

### 2a. 后端：在 SSE 事件中添加题目级详情

**文件:** `backend/app/routers/interview.py`
**行号:** 139-200（SSE 版 event_stream）
**修改类型:** 新增

**修改思路：**

在每个阶段的 SSE 事件中添加更多详情：

**Stage 1 - 标注阶段：**
```python
# 在 tag_questions_batch 调用后，发送每道题的标注结果
tagged_rows = await tag_questions_batch(url, company, round_, q_list, user_id=user['id'])

# 新增：发送标注详情
tag_details = [
    {"question": r[3], "cat1": r[4], "cat2": r[5], "tags": r[6], "difficulty": r[7]}
    for r in tagged_rows
]
yield f"data: {json.dumps({'step': 'tag', 'message': f'标注完成，共 {len(tagged_rows)} 道题', 'type': 'progress', 'details': tag_details}, ensure_ascii=False)}\n\n"
```

**Stage 2 - 匹配阶段：**
```python
# 匹配完成后发送详情
yield f"data: {json.dumps({
    'step': 'match',
    'message': f'匹配完成：{matched_count} 道已有题目，{unmatched_count} 道新题',
    'type': 'progress',
    'matched': matched_count,
    'unmatched': unmatched_count,
    'matched_questions': [idx_to_row[m['new_id']][3] for m in match_result['matched'] if m['new_id'] in idx_to_row][:10],
    'new_questions': [r[3] for r in match_result['unmatched'][:10]]
}, ensure_ascii=False)}\n\n"
```

### 2b. 前端：添加分析详情面板

**文件:** `frontend/src/App.vue`
**修改类型:** 新增

在面经表格的分析列，当 `reprocessingIds[row.id]` 为 true 时，展开一个小型详情面板（替代简单的文字标签），显示：
- 当前步骤标签
- message 文字
- 标注阶段：每道题的 cat1/cat2（展开列表）
- 匹配阶段：新增 vs 已有题目数量

**前端 `reprocessProgress` 数据结构调整：**
```javascript
// 当前结构
{ step: 'tag', message: '标注中...' }

// 新增结构
{
  step: 'tag',
  message: '标注完成，共 5 道题',
  details: [
    { question: 'Redis 和 Memcached 区别？', cat1: '数据库', cat2: 'Redis' },
    // ...
  ],
  matched: 3,
  unmatched: 2,
  matched_questions: ['...'],
  new_questions: ['...']
}
```

---

## 步骤 3: [BUG-002] 添加全局分析进度通知

**文件:** `frontend/src/App.vue`
**修改类型:** 新增

### 方案：全局浮动进度提示

在 App.vue 顶层添加一个全局浮动通知区域，当有任何分析进行中时，显示在页面右下角：

```html
<!-- 在 App.vue template 顶层添加 -->
<div v-if="Object.keys(activeReprocessing).length > 0"
     class="fixed bottom-4 right-4 z-50 bg-white dark:bg-surface-800 rounded-xl shadow-lg
            border border-surface-200 dark:border-ink-700 p-4 max-w-sm">
  <div class="flex items-center gap-3">
    <div class="animate-spin w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full"></div>
    <div>
      <p class="text-sm font-medium text-ink-900 dark:text-ink-100">
        正在分析面经...
      </p>
      <p v-for="(info, id) in activeReprocessing" :key="id"
         class="text-xs text-ink-500 dark:text-ink-400">
        {{ info.message }}
      </p>
    </div>
  </div>
</div>
```

```javascript
// computed 属性
const activeReprocessing = computed(() => {
  const active = {}
  for (const [id, isProcessing] of Object.entries(reprocessingIds.value)) {
    if (isProcessing && reprocessProgress.value[id]) {
      active[id] = reprocessProgress.value[id]
    }
  }
  return active
})
```

---

## 步骤 4: [BUG-001] 断点续传架构设计

**修改类型:** 新增（架构性改动）

### 4a. 数据库：添加分析状态追踪

**文件:** `backend/app/db/connection.py`（在 `init_db` 中添加迁移）

```sql
ALTER TABLE interview ADD COLUMN analysis_status TEXT DEFAULT 'idle';
ALTER TABLE interview ADD COLUMN analysis_stage TEXT DEFAULT NULL;
ALTER TABLE interview ADD COLUMN analysis_result TEXT DEFAULT NULL;
ALTER TABLE interview ADD COLUMN analysis_updated_at TIMESTAMP DEFAULT NULL;
```

**字段说明：**
- `analysis_status`: `idle` / `running` / `completed` / `failed`
- `analysis_stage`: `tagging` / `matching` / `saving` / `done`
- `analysis_result`: JSON 存储中间结果（tagged_rows 等）
- `analysis_updated_at`: 最后更新时间（用于超时判断）

### 4b. 后端：持久化中间状态

**文件:** `backend/app/routers/interview.py`（SSE 版 event_stream）

```python
async def event_stream():
    # 检查是否有未完成的分析
    current_state = await run_db(_load_analysis_state, interview_id)

    if current_state and current_state['analysis_status'] == 'running':
        # 从中断点恢复
        if current_state['analysis_stage'] == 'tagging':
            # 标注未完成，从头开始
            pass
        elif current_state['analysis_stage'] == 'matching':
            # 标注已完成，从匹配阶段恢复
            tagged_rows = json.loads(current_state['analysis_result'])
            # 跳过 Stage 1，直接进入 Stage 2
        elif current_state['analysis_stage'] == 'saving':
            # 匹配已完成，从写入阶段恢复
            tagged_rows, match_result = json.loads(current_state['analysis_result'])
            # 跳过 Stage 1 和 Stage 2，直接进入 Stage 3

    # Stage 1: 标注
    await run_db(_save_analysis_state, interview_id, 'running', 'tagging', None)
    tagged_rows = await tag_questions_batch(...)
    await run_db(_save_analysis_state, interview_id, 'running', 'matching', json.dumps(tagged_rows))

    # Stage 2: 匹配
    match_result = await match_new_questions(...)
    await run_db(_save_analysis_state, interview_id, 'running', 'saving', json.dumps({...}))

    # Stage 3: 写入
    sync_interview_details(...)
    await run_db(_save_analysis_state, interview_id, 'completed', 'done', None)
```

### 4c. 前端：支持恢复分析

**文件:** `frontend/src/App.vue`

```javascript
const reprocessInterview = async (id) => {
  // 检查是否是恢复操作
  const isResume = reprocessingIds.value[id] && reprocessProgress.value[id]?.step
  if (!isResume && !await showConfirm('确定要重新解析该面经？')) return

  // ...SSE 调用，后端自动判断是否需要从断点恢复
}
```

---

## 验证方法

### BUG-004 验证
```bash
# 1. 软删除一条面经
curl -X DELETE http://localhost:8000/api/data/interview/123 -H "Authorization: Bearer $TOKEN"

# 2. 检查 question_bank 中是否有 deleted_at 非空的记录
sqlite3 backend/data/interview-boss.db "SELECT id, question, deleted_at FROM question_bank WHERE deleted_at IS NOT NULL LIMIT 5"

# 3. 重新分析另一条面经，查看后端日志
# 确认日志中没有出现已删除聚类的匹配
```

### BUG-003 验证
```bash
# 触发分析，在浏览器 DevTools Network 面板查看 SSE 事件
# 确认每个事件包含 details / matched_questions / new_questions 字段
```

### BUG-002 验证
```bash
# 触发分析后切换 Tab，确认右下角出现浮动进度提示
# 分析完成后确认 toast 通知仍然显示
```

### BUG-001 验证
```bash
# 触发分析后刷新页面，再次点击分析
# 确认从断点恢复而非从头开始（查看后端日志）
```

---

## 回滚方案

| Bug | 回滚方式 |
|-----|---------|
| BUG-004 | 删除 `AND deleted_at IS NULL` 条件 |
| BUG-003 | 删除 SSE 事件中的 details 字段，移除前端详情面板 |
| BUG-002 | 移除全局浮动通知组件 |
| BUG-001 | 移除 analysis_status 相关列和恢复逻辑 |
