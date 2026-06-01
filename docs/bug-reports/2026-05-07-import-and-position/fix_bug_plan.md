# 修复计划

**日期:** 2026-05-07

## 修复步骤

### 步骤 1: 修复 BUG-001 — 前端字段名 `type` → `content_type`
**文件:** `frontend/src/components/StagingPanel.vue:235`

```js
// 修改前
formData.append('type', importType.value)
// 修改后
formData.append('content_type', importType.value)
```

### 步骤 2: 修复 BUG-002 — 加载并传递 availableSeasons
**文件:** `frontend/src/App.vue`

- `loadActiveSeason()` 中同时加载 `available_seasons`
- 新增 `availableSeasons` ref
- StagingPanel 传递 `:available-seasons="availableSeasons"`

### 步骤 3: 修复 BUG-003 — JD 表添加 job_position 字段
**文件:** `backend/app/db/connection.py` (init_db 迁移) + `backend/app/db/operations.py`

- init_db 中 ALTER TABLE jd ADD COLUMN job_position TEXT DEFAULT ''
- `_insert_jd()` 增加 `job_position` 参数
- `data.py` 中 JD 查询添加 job_position 过滤

### 步骤 4: 修复 BUG-004 — 清理历史空 job_position 数据
**文件:** `backend/app/db/connection.py` (init_db 迁移)

- 将 interview 表中 job_position='' 的记录更新为当前全局岗位

### 步骤 5: 修复 BUG-005 — 前端发送 target 字段
**文件:** `frontend/src/components/StagingPanel.vue`

- 新增 target 选择 UI（管理员可见：公共/个人；普通用户：仅个人）
- `submitAll()` 中 `formData.append('target', ...)`

### 步骤 6: submit.py 中 JD 也写入 job_position
**文件:** `backend/app/routers/submit.py:346`

- `_insert_jd()` 调用时传入 `job_position=current_pos`

## 验证方法
1. 导入界面选择"JD"，验证后端使用 JD_PROMPT
2. 招聘季下拉框显示已有赛季选项
3. 导入 JD 后切换岗位，验证 JD 列表按岗位过滤
4. 管理员可选择提交到公共题库

## 回滚方案
所有修改均为增量添加，回滚只需撤销代码变更。数据库迁移使用 IF NOT EXISTS，安全可重复执行。
