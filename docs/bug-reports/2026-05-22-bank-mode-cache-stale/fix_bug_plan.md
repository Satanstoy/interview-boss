# 修复计划

**Bug ID:** BUG-001
**日期:** 2026-05-22
**优先级:** P1

## 修复步骤

### 步骤 1: 在 App.vue 中导入 invalidateCache
**文件:** `frontend/src/App.vue`
**行号:** 516
**修改类型:** 修改

**修改前:**
```javascript
import { cancelAllRequests, setUnauthorizedHandler, setAuthToken, refreshAuthToken, getFriendlyError } from '@/services/http.js'
```

**修改后:**
```javascript
import { cancelAllRequests, setUnauthorizedHandler, setAuthToken, refreshAuthToken, getFriendlyError, invalidateCache } from '@/services/http.js'
```

### 步骤 2: 在 handleBankModeChanged 中清除缓存
**文件:** `frontend/src/App.vue`
**行号:** 957
**修改类型:** 修改

**修改前:**
```javascript
const handleBankModeChanged = (user) => { currentUser.value = user; fetchTableData(); fetchPracticeStats() }
```

**修改后:**
```javascript
const handleBankModeChanged = (user) => { currentUser.value = user; invalidateCache('master-bank'); fetchTableData(); fetchPracticeStats() }
```

## 验证方法
1. 以管理员身份登录
2. 在公共题库和个人题库之间来回切换
3. 确认每次切换后题库列表正确更新
4. 确认快速切换（30 秒内多次）也能正确显示

## 回滚方案
撤销上述两处修改即可恢复原状。
