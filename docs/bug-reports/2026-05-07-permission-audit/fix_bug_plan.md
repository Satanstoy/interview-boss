# 修复计划

**日期:** 2026-05-07
**优先级:** P0 (BUG-001) / P1-P2 (BUG-002~008)

## 修复步骤

### 步骤 1: 修复 BUG-001 — `build-personal` 变量名错误
**文件:** `backend/app/routers/master_bank.py`
**行号:** 420
**修改类型:** 修正

**修改前:**
```python
match_result = await match_new_questions(new_rows_for_match, existing_by_cat2, user_id=admin['id'])
```

**修改后:**
```python
match_result = await match_new_questions(new_rows_for_match, existing_by_cat2, user_id=user['id'])
```

---

### 步骤 2: 修复 BUG-002 — "重建题库"按钮权限拆分
**文件:** `frontend/src/App.vue`
**行号:** 157-172
**修改类型:** 修正

管理员看到"重建题库"（全量重建公共题库），普通用户看到"重建个人题库"（增量合并到公共题库）。

**修改前:**
```html
<div v-if="activeTab === 'MasterBank'" class="flex items-center gap-2">
  <button @click="triggerBuildMasterBank" :disabled="isBuilding" class="btn-primary text-sm">
    {{ isBuilding ? '重建中...' : '重建题库' }}
  </button>
  ...
</div>
```

**修改后:**
```html
<div v-if="activeTab === 'MasterBank'" class="flex items-center gap-2">
  <button v-if="currentUser?.is_admin" @click="triggerBuildMasterBank" :disabled="isBuilding" class="btn-primary text-sm">
    {{ isBuilding ? '重建中...' : '重建题库' }}
  </button>
  <button v-else @click="triggerBuildPersonalBank" :disabled="isBuilding" class="btn-primary text-sm">
    {{ isBuilding ? '重建中...' : '重建个人题库' }}
  </button>
  ...（进度条保持不变）
</div>
```

新增 `triggerBuildPersonalBank` 函数，调用 `api.buildPersonalBankSSE`。

---

### 步骤 3: 修复 BUG-003 — "重新分类"按钮权限守卫
**文件:** `frontend/src/components/QuestionCard.vue`
**行号:** 57
**修改类型:** 修正

添加 `isAdmin` prop，在模板中用 `v-if` 控制显示。

---

### 步骤 4: 修复 BUG-004 — "独立"/"合并到"按钮权限守卫
**文件:** `frontend/src/components/QuestionCard.vue`
**行号:** 151-158
**修改类型:** 修正

添加 `v-if="isAdmin"` 到两个按钮。

---

### 步骤 5: 修复 BUG-005~007 — 数据表操作按钮权限守卫
**文件:** `frontend/src/App.vue`
**行号:** 234-244（JD）、286-310（面经）
**修改类型:** 修正

为删除按钮、分析按钮、InlineEdit 添加 `v-if="currentUser?.is_admin"` 守卫。

---

### 步骤 6: 修复 BUG-008 — 批量操作面板权限守卫
**文件:** `frontend/src/App.vue`
**行号:** 606-665
**修改类型:** 修正

将 JD 和面经的 batch actions 仅在管理员时显示。

---

## 验证方法
1. 以普通用户登录，验证：
   - 高频题库只看到"重建个人题库"按钮
   - 题目卡片无"重新分类"、"独立"、"合并到"按钮
   - JD/面经表无删除、分析、内联编辑按钮
   - JD/面经无批量操作面板
2. 以管理员登录，验证所有按钮正常显示
3. 普通用户点击"重建个人题库"，验证 SSE 进度正常

## 回滚方案
撤销所有 `App.vue` 和 `QuestionCard.vue` 的修改。后端修改为单行变量名修正，回滚即可。
