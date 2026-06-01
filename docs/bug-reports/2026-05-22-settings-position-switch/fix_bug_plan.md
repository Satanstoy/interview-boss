# 修复计划

**Bug ID:** BUG-001, BUG-002, BUG-003
**日期:** 2026-05-22
**优先级:** P1 (BUG-001, BUG-003), P2 (BUG-002)

---

## BUG-001 修复：onSwitchPosition 不再立即调用后端 API

**文件:** `frontend/src/components/business/SettingsPanel.vue`

### 步骤 1: 修改 `onSwitchPosition` (行 532-571)

**修改前:**
```javascript
const onSwitchPosition = async (pos) => {
  if (pos === taxonomy.job_position) return
  try {
    if (props.isAdmin) {
      await switchPosition(pos)
    } else {
      await switchMyPosition(pos)
    }
    taxonomy.job_position = pos
    originalPosition.value = pos
    positionOnlyChanged.value = true
    if (!availablePositions.value.includes(pos)) {
      availablePositions.value.push(pos)
    }
    // 重新加载分类配置
    if (props.isAdmin) {
      const data = await fetchProfile()
      const s = data.settings
      if (s.taxonomy_config) {
        try {
          const tc = typeof s.taxonomy_config === 'string' ? JSON.parse(s.taxonomy_config) : s.taxonomy_config
          taxonomy.categories = (tc.categories || []).map(c => ({ ...c, _open: false }))
        } catch { taxonomy.categories = [] }
      } else {
        taxonomy.categories = []
      }
      availablePositions.value = data.settings.available_positions || availablePositions.value
    } else {
      const data = await fetchPublicProfile()
      if (data.settings?.taxonomy_config) {
        try {
          const tc = typeof data.settings.taxonomy_config === 'string' ? JSON.parse(data.settings.taxonomy_config) : data.settings.taxonomy_config
          taxonomy.categories = (tc.categories || []).map(c => ({ ...c, _open: false }))
        } catch { taxonomy.categories = [] }
      }
    }
    toast.success(`已切换到岗位：${pos}`)
  } catch (e) {
    toast.error(`切换失败: ${e.message}`)
  }
}
```

**修改后:**
```javascript
const onSwitchPosition = async (pos) => {
  if (pos === taxonomy.job_position) return
  try {
    // 不再立即调用后端 API，仅本地更新 + 加载新岗位分类
    taxonomy.job_position = pos
    positionOnlyChanged.value = true
    if (!availablePositions.value.includes(pos)) {
      availablePositions.value.push(pos)
    }
    // 重新加载分类配置（绕过缓存）
    if (props.isAdmin) {
      const data = await fetchProfile({ noCache: true })
      const s = data.settings
      if (s.taxonomy_config) {
        try {
          const tc = typeof s.taxonomy_config === 'string' ? JSON.parse(s.taxonomy_config) : s.taxonomy_config
          taxonomy.categories = (tc.categories || []).map(c => ({ ...c, _open: false }))
        } catch { taxonomy.categories = [] }
      } else {
        taxonomy.categories = []
      }
      availablePositions.value = data.settings.available_positions || availablePositions.value
    } else {
      const data = await fetchPublicProfile({ noCache: true })
      if (data.settings?.taxonomy_config) {
        try {
          const tc = typeof data.settings.taxonomy_config === 'string' ? JSON.parse(data.settings.taxonomy_config) : data.settings.taxonomy_config
          taxonomy.categories = (tc.categories || []).map(c => ({ ...c, _open: false }))
        } catch { taxonomy.categories = [] }
      }
    }
  } catch (e) {
    toast.error(`加载分类失败: ${e.message}`)
  }
}
```

**关键改动：**
- 移除 `switchPosition(pos)` / `switchMyPosition(pos)` 调用
- 移除 `originalPosition.value = pos`（只在 saveProfile 成功后更新）
- 移除 `toast.success(...)` （保存时再提示）
- fetchProfile/fetchPublicProfile 加 `{ noCache: true }` 绕过缓存

### 步骤 2: 在 `saveProfile` 中添加岗位切换 API 调用 (行 761-796)

**修改前:**
```javascript
const saveProfile = async () => {
  isSaving.value = true
  saveMessage.value = ''
  try {
    const payload = {
      active_season: form.active_season,
    }

    const validCategories = taxonomy.categories
      .filter(c => c.cat1.trim())
      .map(c => ({ cat1: c.cat1.trim(), children: c.children.filter(x => x.trim()) }))
    if (validCategories.length > 0) {
      payload.taxonomy_config = JSON.stringify({ job_position: taxonomy.job_position, categories: validCategories })
    }

    await updateProfile(payload)
    emit('update:activeSeason', form.active_season)
    await loadProfile()

    saveMessage.value = '全局配置已保存'
    saveSuccess.value = true
    originalPosition.value = taxonomy.job_position
    if (positionOnlyChanged.value) {
      emit('position-changed')
    } else {
      emit('settings-saved')
    }
    positionOnlyChanged.value = false
    setTimeout(() => { saveMessage.value = '' }, 3000)
  } catch (e) {
    saveMessage.value = `保存失败: ${e.message}`
    saveSuccess.value = false
  } finally {
    isSaving.value = false
  }
}
```

**修改后:**
```javascript
const saveProfile = async () => {
  isSaving.value = true
  saveMessage.value = ''
  try {
    // 如果岗位有变更，先调用切换 API
    if (positionOnlyChanged.value) {
      if (props.isAdmin) {
        await switchPosition(taxonomy.job_position)
      } else {
        await switchMyPosition(taxonomy.job_position)
      }
    }

    const payload = {
      active_season: form.active_season,
    }

    const validCategories = taxonomy.categories
      .filter(c => c.cat1.trim())
      .map(c => ({ cat1: c.cat1.trim(), children: c.children.filter(x => x.trim()) }))
    if (validCategories.length > 0) {
      payload.taxonomy_config = JSON.stringify({ job_position: taxonomy.job_position, categories: validCategories })
    }

    await updateProfile(payload)
    emit('update:activeSeason', form.active_season)
    await loadProfile()

    saveMessage.value = '全局配置已保存'
    saveSuccess.value = true
    originalPosition.value = taxonomy.job_position
    if (positionOnlyChanged.value) {
      emit('position-changed')
    } else {
      emit('settings-saved')
    }
    positionOnlyChanged.value = false
    setTimeout(() => { saveMessage.value = '' }, 3000)
  } catch (e) {
    saveMessage.value = `保存失败: ${e.message}`
    saveSuccess.value = false
  } finally {
    isSaving.value = false
  }
}
```

---

## BUG-002 修复：移除 onSettingsClose 中的 loadAllData()

**文件:** `frontend/src/App.vue`

### 步骤 3: 修改 `onSettingsClose` (行 889)

**修改前:**
```javascript
const onSettingsClose = () => { showSettings.value = false; loadAllData() }
```

**修改后:**
```javascript
const onSettingsClose = () => { showSettings.value = false }
```

**说明：**
- `onSettingsClose` 仅负责关闭 modal，不触发数据刷新
- `onSettingsSaved` 和 `onPositionChanged` 各自负责 `loadAllData()`
- 如果用户取消修改（点关闭/点背景），不会触发无意义的数据刷新

---

## BUG-003 修复：GET 缓存绕过 + 清除

**文件:** `frontend/src/services/profileApi.js` + `frontend/src/components/business/SettingsPanel.vue`

### 步骤 4: 修改 profileApi.js 的 fetchProfile 和 fetchPublicProfile

**修改前:**
```javascript
export const fetchProfile = () => get(`${API}/profile`)
export const fetchPublicProfile = () => get(`${API}/profile/public`)
```

**修改后:**
```javascript
export const fetchProfile = (options) => get(`${API}/profile`, options)
export const fetchPublicProfile = (options) => get(`${API}/profile/public`, options)
```

**说明：** 透传 `options` 参数（包含 `noCache: true`），让调用方可以选择绕过缓存。

### 步骤 5: 在 saveProfile 的 updateProfile 之后清除缓存

在 `saveProfile` 中 `await updateProfile(payload)` 之后添加缓存清除：

```javascript
await updateProfile(payload)
invalidateCache('/api/profile')   // 新增：清除 profile 相关的 GET 缓存
```

需要在 SettingsPanel.vue 的 import 中增加 `invalidateCache`：

```javascript
import { invalidateCache } from '@/services/http.js'
```

---

## 验证方法

1. 打开设置面板，点击不同岗位按钮 → 不应出现 toast，不应有 PUT 请求（DevTools Network 验证）
2. 切换岗位后点"保存全局配置" → 只刷新一次数据（Network 面板中只出现一组 loadAllData 请求）
3. A→B→A 快速切换后保存 → 页面显示 A，与保存时的选择一致
4. Network 面板验证：onSwitchPosition 期间无 PUT 请求，saveProfile 时出现 PUT + 保存成功

## 回滚方案

所有修改均在前端代码（SettingsPanel.vue、App.vue、profileApi.js），后端无变更。回滚只需 `git checkout` 这三个文件。
