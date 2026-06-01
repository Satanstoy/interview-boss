# 修复计划

**Bug ID:** BUG-001
**日期:** 2026-05-07
**优先级:** P2

## 修复步骤

### 步骤 1: 新增进度状态变量
**文件:** `frontend/src/App.vue`
**行号:** 450 附近
**修改类型:** 新增

**修改前:**
```javascript
const isBuilding = ref(false)
```

**修改后:**
```javascript
const isBuilding = ref(false)
const buildProgress = ref({ step: '', current: 0, total: 0, message: '' })
```

### 步骤 2: 修改 triggerBuildMasterBank 消费 SSE 事件
**文件:** `frontend/src/App.vue`
**行号:** 907-917
**修改类型:** 修正

**修改前:**
```javascript
const triggerBuildMasterBank = async () => {
  if (!await showConfirm('将重新整理全部题目并调用 LLM 重新分类聚类，会消耗大量 API Token，确定继续？', { title: '重建题库', variant: 'danger' })) return
  isBuilding.value = true
  try {
    const result = await api.buildMasterBankSSE(() => {})
    toast.success(`重建完成，共 ${result?.total_unique || 0} 道题目`)
    fetchTableData()
    fetchAnalytics()
  } catch (e) { toast.error('重建失败：' + getFriendlyError(e)) }
  finally { isBuilding.value = false }
}
```

**修改后:**
```javascript
const STEP_LABELS = { tag: 'LLM 标注', cluster: '聚类去重', merge: '生成统一问题', save: '写入题库' }

const triggerBuildMasterBank = async () => {
  if (!await showConfirm('将重新整理全部题目并调用 LLM 重新分类聚类，会消耗大量 API Token，确定继续？', { title: '重建题库', variant: 'danger' })) return
  isBuilding.value = true
  buildProgress.value = { step: '', current: 0, total: 0, message: '' }
  try {
    const result = await api.buildMasterBankSSE((event) => {
      if (event.type === 'init') {
        buildProgress.value = { step: event.step, current: 0, total: event.total, message: event.message }
      } else if (event.type === 'progress') {
        buildProgress.value = { step: event.step, current: event.current, total: event.total, message: event.message }
      } else if (event.type === 'error') {
        throw new Error(event.message)
      }
    })
    toast.success(`重建完成，共 ${result?.total_unique || 0} 道题目`)
    fetchTableData()
    fetchAnalytics()
  } catch (e) { toast.error('重建失败：' + getFriendlyError(e)) }
  finally { isBuilding.value = false; buildProgress.value = { step: '', current: 0, total: 0, message: '' } }
}
```

### 步骤 3: 修改按钮 UI 展示进度
**文件:** `frontend/src/App.vue`
**行号:** 157-159
**修改类型:** 修正

**修改前:**
```html
<button v-if="activeTab === 'MasterBank'" @click="triggerBuildMasterBank" class="btn-primary text-sm">
  {{ isBuilding ? '重建中...' : '重建题库' }}
</button>
```

**修改后:**
```html
<div v-if="activeTab === 'MasterBank'" class="flex items-center gap-2">
  <button @click="triggerBuildMasterBank" :disabled="isBuilding" class="btn-primary text-sm">
    {{ isBuilding ? '重建中...' : '重建题库' }}
  </button>
  <div v-if="isBuilding" class="flex items-center gap-2 max-w-xs">
    <div class="flex-1 h-1.5 bg-surface-200 dark:bg-ink-700 rounded-full overflow-hidden">
      <div
        class="h-full bg-gradient-brand rounded-full transition-all duration-300"
        :style="{ width: buildProgress.total > 0 ? Math.round((buildProgress.current / buildProgress.total) * 100) + '%' : '100%' }"
      ></div>
    </div>
    <span class="text-xs text-ink-500 dark:text-ink-400 whitespace-nowrap tabular-nums">
      {{ buildProgress.message || '准备中...' }}
    </span>
  </div>
</div>
```

## 验证方法
1. 以管理员登录，切换到高频题库标签
2. 点击"重建题库"，确认对话框
3. 观察按钮右侧是否出现进度条和阶段文字
4. 验证进度条在标注阶段正确递增（如 "LLM 标注 2/4 批"）
5. 验证聚类、统一问题、写入阶段文字正确切换
6. 重建完成后进度条消失，toast 正常弹出

## 回滚方案
撤销 `App.vue` 的三处修改即可恢复原状。无数据库变更，无后端变更。
