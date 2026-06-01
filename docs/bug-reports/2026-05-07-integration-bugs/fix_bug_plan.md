# 修复计划

**Bug ID:** BUG-001 ~ BUG-003
**日期:** 2026-05-07
**优先级:** P1 (BUG-001) / P2 (BUG-002, BUG-003)

## 修复步骤

### 步骤 1: 修复 BUG-003 — 添加 fetchPublicProfile API 函数

**文件:** `frontend/src/api/index.js`
**行号:** 72-73
**修改类型:** 新增

**修改前:**
```javascript
// ── Profile ──
export const fetchProfile = () => get(`${API}/profile`)
```

**修改后:**
```javascript
// ── Profile ──
export const fetchProfile = () => get(`${API}/profile`)
export const fetchPublicProfile = () => get(`${API}/profile/public`)
```

**验证方法:** 检查 api/index.js 中存在 `fetchPublicProfile` 函数

---

### 步骤 2: 修复 BUG-001 — loadActiveSeason 改用公开端点

**文件:** `frontend/src/App.vue`
**行号:** 964-968
**修改类型:** 替换

**修改前:**
```javascript
const loadActiveSeason = async () => {
  try {
    const data = await api.fetchProfile()
    activeSeason.value = data.settings?.active_season || ''
  } catch { /* ignore */ }
}
```

**修改后:**
```javascript
const loadActiveSeason = async () => {
  try {
    const data = await api.fetchPublicProfile()
    activeSeason.value = data.settings?.active_season || ''
  } catch { /* ignore */ }
}
```

**验证方法:** 以非管理员用户登录，确认招聘季筛选器有值

---

### 步骤 3: 修复 BUG-002 — buildMasterBank 改用 SSE 版本

**文件:** `frontend/src/App.vue`
**行号:** 902-911
**修改类型:** 替换

**修改前:**
```javascript
const triggerBuildMasterBank = async () => {
  if (!await showConfirm('将重新整理全部题目，确定继续？', { title: '重建题库', variant: 'danger' })) return
  isBuilding.value = true
  try {
    const data = await api.buildMasterBank()
    toast.success(`重建完成，共 ${data.total_unique} 道题目`)
    fetchTableData()
    fetchAnalytics()
  } catch (e) { toast.error('重建失败：' + getFriendlyError(e)) }
  finally { isBuilding.value = false }
}
```

**修改后:**
```javascript
const triggerBuildMasterBank = async () => {
  if (!await showConfirm('将重新整理全部题目，确定继续？', { title: '重建题库', variant: 'danger' })) return
  isBuilding.value = true
  try {
    const result = await api.buildMasterBankSSE((event) => {
      if (event.type === 'progress') {
        // 可选：显示进度
      }
    })
    toast.success(`重建完成，共 ${result?.total_unique || 0} 道题目`)
    fetchTableData()
    fetchAnalytics()
  } catch (e) { toast.error('重建失败：' + getFriendlyError(e)) }
  finally { isBuilding.value = false }
}
```

**验证方法:** 以管理员用户登录，点击"重建题库"，确认提示正确的题目数量

## 验证方法

1. 以非管理员用户登录，确认招聘季筛选器有值
2. 以管理员用户登录，点击"重建题库"，确认提示正确
3. 检查网络请求，确认调用了正确的端点

## 回滚方案

每个 Bug 修复独立修改，如需回滚可单独还原对应文件。
