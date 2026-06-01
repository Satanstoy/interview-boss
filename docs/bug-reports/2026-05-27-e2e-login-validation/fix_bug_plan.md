# 修复计划

**Bug ID:** BUG-001, BUG-002, BUG-003
**日期:** 2026-05-27
**优先级:** P1 (BUG-002), P2 (BUG-001), P3 (BUG-003)

## 修复步骤

### 步骤 1: 修复 BUG-001 — 正则字符范围

**文件:** `frontend/src/utils/validate.js`
**行号:** 58, 61
**修改类型:** 修正

**修改前:**
```javascript
const USERNAME_RE = /^[a-zA-Z0-9_一-龥]{2,32}$/
const SEASON_RE = /^[一-龥a-zA-Z0-9\s\-_()（）]{1,50}$/
```

**修改后:**
```javascript
const USERNAME_RE = /^[a-zA-Z0-9_一-鿿]{2,32}$/
const SEASON_RE = /^[一-鿿a-zA-Z0-9\s\-_()（）]{1,50}$/
```

### 步骤 2: 修复 BUG-002 — 消毒函数返回值

**文件:** `frontend/src/components/business/PracticePanel.vue`
**行号:** 327-334, 358-363
**修改类型:** 修正

**修改前:**
```javascript
try {
  sanitizeAgainstInjection(qState._editAnswer, '参考答案')
} catch (e) {
  toast.warning(e.message)
  return
}
```

**修改后:**
```javascript
qState._editAnswer = sanitizeAgainstInjection(qState._editAnswer, '参考答案')
```

### 步骤 3: 修复 BUG-003 — 缓存失效

**文件:** `frontend/src/App.vue`
**行号:** 635
**修改类型:** 新增

**修改前:**
```javascript
const fetchTableData = async () => {
  isDataLoading.value = true
  dataLoadError.value = null
```

**修改后:**
```javascript
const fetchTableData = async () => {
  isDataLoading.value = true
  dataLoadError.value = null
  invalidateCache()  // 确保刷新时获取最新数据
```

## 验证方法
1. `cd frontend && npm run build` — 构建通过
2. `npx playwright test tests/e2e/full-flow.spec.js` — E2E 测试通过
3. 手动验证正则匹配扩展汉字

## 回滚方案
每个修改都是独立的单行/多行修改，可逐个 revert。
