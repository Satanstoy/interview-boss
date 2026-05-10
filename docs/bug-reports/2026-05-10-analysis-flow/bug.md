# Bug 详细分析报告

**Bug ID:** BUG-001, BUG-002, BUG-003, BUG-004
**发现日期:** 2026-05-10
**状态:** 已确认

---

## 问题概述

题目分析（面经重新解析）功能存在四个相互关联的问题，影响分析可靠性、用户体验和聚类质量。

---

## 根本原因分析

### BUG-001: 不支持断点续传

- **位置:** `backend/app/routers/interview.py:132-200`（SSE event_stream 函数）
- **症状:** 网络断开或页面刷新后，分析进度完全丢失，需要从头重新开始
- **根因:** 整个分析流程分为三个阶段（标注 → 匹配 → 写入），但没有在任何阶段保存中间状态。`tagged_rows` 和 `match_result` 仅存在于协程内存中，无持久化机制。
- **影响:** 每次中断都会浪费已完成的 LLM API 调用和等待时间
- **严重程度:** P3（架构缺陷，需较大重构）

**关键代码路径：**

```
[interview.py:132] event_stream()
  ├── [interview.py:141] tag_questions_batch()  ← LLM调用，结果仅存内存
  ├── [interview.py:179] match_new_questions()  ← LLM调用，结果仅存内存
  └── [interview.py:188] sync_interview_details()  ← 原子写入
```

**断点续传需要解决的问题：**
1. 标注结果 `tagged_rows` 需要持久化（以便中断后跳过 Stage 1）
2. 匹配结果 `match_result` 需要持久化（以便中断后跳过 Stage 2）
3. 需要引入分析状态追踪（pending / tagging / matching / saving / done / failed）
4. 前端需要支持"恢复分析"而非"重新分析"

---

### BUG-002: 切换界面不支持后台继续分析

- **位置:** `frontend/src/App.vue:308`（`v-if="activeTab === 'Interview'"`）, `frontend/src/App.vue:960-979`（`reprocessInterview`）
- **症状:** 分析进行中切换到其他 Tab（如题库、JD），后台 SSE 仍在运行，但用户完全没有视觉反馈，不知道分析是否还在进行
- **根因:**
  1. `DataTable` 组件通过 `v-if="activeTab === 'Interview'"` 条件渲染，切走时组件销毁
  2. `reprocessingIds` 和 `reprocessProgress` 是顶级 `ref`，状态确实保留
  3. 但唯一的进度指示器（spinner + 步骤文字）绑定在 DataTable 的 `#actions` slot 内，组件销毁后不可见
  4. 没有全局进度指示器（如顶栏 toast、侧边通知、全局 loading 条）

- **影响:** 用户体验差，用户可能误以为分析失败而重复触发
- **严重程度:** P2（UX 问题）

**前端状态生命周期：**

```javascript
// App.vue:553-554 — 顶级 ref，跨 Tab 存活
const reprocessingIds = ref({})
const reprocessProgress = ref({})

// App.vue:960-979 — 发起分析
const reprocessInterview = async (id) => {
  reprocessingIds.value[id] = true  // ← 状态确实被设置
  reprocessProgress.value[id] = { step: '', message: '准备中...' }
  await api.reprocessInterviewSSE(id, callback)  // ← SSE 连接保持活跃
  // ...
}

// App.vue:323-331 — 唯一的进度展示位置（在 DataTable 内部）
// activeTab !== 'Interview' 时整个 <DataTable> 被销毁
```

**结论：** 后台分析确实在继续运行，但用户完全没有反馈。需要添加全局进度通知。

---

### BUG-003: 分析中不显示详细内容

- **位置:** `backend/app/routers/interview.py:140-200`, `frontend/src/App.vue:329`
- **症状:** 分析过程中只显示"标注中"/"聚类中"/"保存中"三个字，无法看到正在处理的具体内容
- **根因:**

**后端（SSE 事件粒度不足）：**
```python
# interview.py:140 — 只有笼统的阶段信息
yield f"data: {json.dumps({'step': 'tag', 'message': f'正在标注 {len(q_list)} 道题目...', 'type': 'progress'})}\n\n"

# interview.py:142 — 标注完成后也只告诉总数
yield f"data: {json.dumps({'step': 'tag', 'message': f'标注完成，共 {len(tagged_rows)} 道题', 'type': 'progress'})}\n\n"

# interview.py:184 — 匹配完成只告诉数字
yield f"data: {json.dumps({'step': 'match', 'message': f'匹配完成：{matched_count} 道已有题目，{unmatched_count} 道新题', 'type': 'progress'})}\n\n"
```

缺失的信息：
- 每道题的标签结果（cat1/cat2/tags/difficulty）
- 匹配到的具体聚类名称
- 哪些题是新增、哪些是已有
- 当前正在处理第几题

**前端（展示过于简化）：**
```javascript
// App.vue:329 — 仅展示步骤标签
{{ reprocessingIds[row.id]
  ? (reprocessProgress[row.id]?.step === 'tag' ? '标注中'
    : reprocessProgress[row.id]?.step === 'match' ? '聚类中'
    : reprocessProgress[row.id]?.step === 'save' ? '保存中'
    : '分析中')
  : '分析' }}
```

- **影响:** 用户无法判断分析是否正确进行，也无法提前发现标注错误
- **严重程度:** P1（体验问题，需中等工作量改进）

---

### BUG-004: 软删除记录污染聚类质量

- **位置:** `backend/app/routers/interview.py:53-56`
- **症状:** 重新分析面经时，已软删除的 `question_bank` 记录仍参与增量匹配，导致新题目可能匹配到已废弃的聚类
- **根因:** SQL 查询缺少 `deleted_at IS NULL` 过滤条件

**当前代码（有 bug）：**
```python
# interview.py:53-56
rows = conn.execute(
    "SELECT id, question, cat2, sources, original_questions, original_question_sources FROM question_bank "
    "WHERE owner_id IS NULL AND status = 'approved' AND job_position = ?",
    (current_pos,)
).fetchall()
```

**修复后代码：**
```python
rows = conn.execute(
    "SELECT id, question, cat2, sources, original_questions, original_question_sources FROM question_bank "
    "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL AND job_position = ?",
    (current_pos,)
).fetchall()
```

**影响链路：**

```
[BUG] 未过滤 deleted_at
  ↓
existing_by_cat2 包含已删除的聚类
  ↓
match_new_questions() 将新题与废弃聚类匹配
  ↓
_apply_incremental_txn() 对废弃聚类执行频率+1
  ↓
已删除的记录被"复活"（frequency 增加但仍保持 deleted_at 有值）
  ↓
聚类质量下降，出现错误的题目归类
```

- **影响:** 聚类准确性下降，题库中可能出现错误的题目关联
- **严重程度:** P0（数据质量问题，一行代码修复）

---

## 复现步骤

### BUG-001 复现
1. 管理员登录，进入面经库
2. 点击某条面经的"分析"按钮
3. 在标注阶段进行中时刷新页面或断开网络
4. 重新连接后再次点击"分析"
5. **预期：** 从断点处继续，已完成的标注不再重做
6. **实际：** 从头开始重新标注所有题目

### BUG-002 复现
1. 管理员登录，进入面经库
2. 点击某条面经的"分析"按钮，看到 spinner 和"标注中"
3. 切换到"高频题库" Tab
4. 观察是否有任何分析进度提示
5. **预期：** 顶栏或某处有全局进度提示
6. **实际：** 完全没有任何反馈

### BUG-003 复现
1. 管理员登录，进入面经库
2. 点击某条包含 10+ 道题的面经"分析"按钮
3. 观察分析进度展示
4. **预期：** 显示正在处理的具体题目、匹配结果等
5. **实际：** 只显示"标注中"/"聚类中"/"保存中"

### BUG-004 复现
1. 删除某条面经记录（软删除）
2. 该面经关联的 `question_bank` 记录保持 `deleted_at IS NOT NULL`
3. 重新分析另一条包含类似题目的面经
4. 查看匹配日志，新题可能匹配到了已删除的聚类
5. **预期：** 已删除聚类不参与匹配
6. **实际：** 已删除聚类被加载并参与匹配
