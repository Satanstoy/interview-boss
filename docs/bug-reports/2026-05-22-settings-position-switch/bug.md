# Bug 详细分析报告

**Bug ID:** BUG-001, BUG-002, BUG-003
**发现日期:** 2026-05-22
**状态:** 已确认

## 问题概述

设置面板（SettingsPanel.vue）中的岗位切换功能存在三个关联 bug。核心设计问题：`onSwitchPosition` 将"即时后端持久化"和"本地状态预览"混为一体，导致用户每点一次岗位按钮就立即修改数据库，而非等用户点"保存全局配置"后统一提交。

---

## 根本原因分析

### BUG-001: 点击岗位按钮立即生效（应延迟到保存）

- **位置:** `frontend/src/components/business/SettingsPanel.vue:532-571`
- **症状:** 点击岗位按钮后，后端数据库立即被修改，toast 显示 "已切换到岗位：XXX"，用户无需点"保存全局配置"就已经完成了岗位切换
- **根因:** `onSwitchPosition` 函数在本地状态更新之前先调用了后端 API：

```javascript
// SettingsPanel.vue:532-571
const onSwitchPosition = async (pos) => {
  if (pos === taxonomy.job_position) return
  try {
    // BUG: 立即调用后端 API 持久化
    if (props.isAdmin) {
      await switchPosition(pos)       // PUT /api/profile/position
    } else {
      await switchMyPosition(pos)     // PUT /api/profile/my-position
    }
    taxonomy.job_position = pos
    originalPosition.value = pos
    positionOnlyChanged.value = true
    // ... 加载分类 ...
    toast.success(`已切换到岗位：${pos}`)  // BUG: 立即提示成功
  }
}
```

- **影响:** 后端 `users` 表的 `current_position_id` 或 `personal_position` 字段被即时修改，导致：
  - 其他页面/组件读到的岗位已经是新值
  - 如果用户取消修改，数据库已经脏了
  - 每次点击都发一次 PUT 请求

- **严重程度:** P1

---

### BUG-002: 保存配置后双重刷新

- **位置:**
  - `frontend/src/components/business/SettingsPanel.vue:783-787`
  - `frontend/src/App.vue:889-891`
- **症状:** 点击"保存全局配置"后，页面数据闪烁/跳动两次
- **根因:** `saveProfile()` 完成后 emit `position-changed` 事件，而 modal 关闭时又触发 `@close` 事件，两者都调用 `loadAllData()`：

```javascript
// SettingsPanel.vue:783-787
if (positionOnlyChanged.value) {
  emit('position-changed')   // 触发 App.vue 的 onPositionChanged → loadAllData()
} else {
  emit('settings-saved')     // 触发 App.vue 的 onSettingsSaved → loadAllData()
}
```

```javascript
// App.vue:889-891
const onSettingsClose = () => { showSettings.value = false; loadAllData() }  // 总是调用
const onSettingsSaved = () => { loadAllData() }                               // 也会调用
const onPositionChanged = () => { loadAllData() }                             // 也会调用
```

当 position 改变时，执行序列：
1. `emit('position-changed')` → `onPositionChanged` → `loadAllData()` ← **第1次**
2. modal 关闭 → `emit('close')` → `onSettingsClose` → `loadAllData()` ← **第2次**

- **影响:** `loadAllData()` 内包含 `fetchTableData()`（3个并发 API）、`fetchAnalytics()`、`fetchPracticeStats()`、`loadActiveSeason()`。双重触发 = 8个冗余请求。

- **严重程度:** P2

---

### BUG-003: A→B→A 切换后保存，实际生效为 B

- **位置:**
  - `frontend/src/components/business/SettingsPanel.vue:560-566`（onSwitchPosition 中的 fetchPublicProfile）
  - `frontend/src/services/http.js:23-36`（GET 缓存机制）
- **症状:** 从岗位 A 切到 B，再切回 A，点保存后页面显示的岗位是 B 而非 A
- **根因:** HTTP GET 缓存 + BUG-001 的组合效应

**详细时序分析：**

1. **设置面板打开**：`loadProfile()` → `fetchPublicProfile()` → 缓存 key=`/api/profile/public`（TTL=30s），服务器返回岗位 A

2. **用户点击岗位 B**：`onSwitchPosition(B)` →
   - `await switchMyPosition(B)` — 立即更新数据库为 B
   - `taxonomy.job_position = B` — 本地状态设为 B
   - `await fetchPublicProfile()` — **命中缓存**，返回的是步骤 1 的数据（岗位 A）
   - `taxonomy.categories = tc.categories` — 分类被覆盖为 A 的分类（但 job_position 仍为 B，因为步骤中先设了 job_position）

3. **用户点击岗位 A**：`onSwitchPosition(A)` →
   - `await switchMyPosition(A)` — 数据库改为 A
   - `taxonomy.job_position = A`
   - `await fetchPublicProfile()` — **可能仍命中缓存**（距步骤 1 不到 30s）
   - 分类被覆盖为缓存中的 A 分类

4. **用户点"保存全局配置"**：`saveProfile()` →
   - `payload.taxonomy_config = JSON.stringify({ job_position: taxonomy.job_position, ... })` — job_position 是 A ✅
   - `await updateProfile(payload)` — PUT 保存成功
   - `await loadProfile()` → `fetchPublicProfile()` — **可能命中旧缓存**，返回岗位 A 的数据
   - `emit('position-changed')` → App.vue `loadAllData()` → `loadActiveSeason()` → `fetchPublicProfile()` — **再次命中缓存**

**关键问题**：`switchMyPosition()` API 响应中不包含 `taxonomy_config`，所以前端在 `onSwitchPosition` 中要额外调 `fetchPublicProfile()` 来获取分类。但 `fetchPublicProfile()` 的 GET 请求被 http.js 缓存了 30 秒，导致拿到的是切换前的旧分类数据。

- **影响:** 用户操作结果与预期不符，且难以复现（取决于操作速度是否在 30s 缓存窗口内）

- **严重程度:** P1

---

## 复现步骤

### BUG-001 复现

1. 打开设置面板
2. 当前岗位为 A，点击岗位 B
3. **观察**：立即看到 toast "已切换到岗位：B"，数据库已更新
4. **预期**：应该只是本地预览，不发 API 请求，不显示成功提示

### BUG-002 复现

1. 以管理员身份打开设置面板
2. 切换一个岗位
3. 点击"保存全局配置"
4. **观察**：页面数据刷新两次（表格闪烁两次）
5. **预期**：只刷新一次

### BUG-003 复现

1. 当前岗位为 A，打开设置面板
2. 点击岗位 B（立即生效）
3. 快速（30s 内）点击岗位 A
4. 点击"保存全局配置"
5. **观察**：页面显示的当前岗位可能是 B
6. **预期**：应该是 A

## 修复建议

详见 `fix_bug_plan.md`
