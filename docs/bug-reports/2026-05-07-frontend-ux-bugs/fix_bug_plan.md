# 修复计划

**日期:** 2026-05-07
**优先级:** P2 (用户体验优化)

---

## 修复步骤

### 步骤 1: 搜索框添加清除按钮 (BUG-001)
**文件:** `frontend/src/components/SearchFilterBar.vue`
**修改类型:** 新增

**修改前:**
```html
<input v-model="localQuery" type="text" ... />
```

**修改后:**
```html
<div class="relative flex-1 min-w-[200px]">
  <svg class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 ...">...</svg>
  <input v-model="localQuery" type="text" class="w-full ... pr-10" />
  <button v-if="localQuery" @click="localQuery = ''" class="absolute right-3 top-1/2 -translate-y-1/2 ...">
    <svg class="w-4 h-4" ...>...</svg>
  </button>
</div>
```

### 步骤 2: 答案操作按钮始终可见 (BUG-004)
**文件:** `frontend/src/components/QuestionCard.vue`
**修改类型:** 修改

**修改前:**
```html
<button class="... opacity-0 group-hover:opacity-100 ...">编辑</button>
<button class="... opacity-0 group-hover:opacity-100 ...">重新生成</button>
```

**修改后:**
```html
<button class="... opacity-60 hover:opacity-100 ...">编辑</button>
<button class="... opacity-60 hover:opacity-100 ...">重新生成</button>
```

### 步骤 3: 收藏按钮扩大点击区域 (BUG-005)
**文件:** `frontend/src/components/QuestionCard.vue`
**修改类型:** 修改

**修改后:**
```html
<button @click.stop="$emit('toggle-star', question)" class="ml-1 p-1.5 -m-1.5 transition-all duration-200 hover:scale-125 star-btn" ...>
```

### 步骤 4: "换一批"添加确认提示 (BUG-010)
**文件:** `frontend/src/components/MockInterview.vue`
**修改类型:** 修改

**修改后:**
```javascript
const loadQuestions = async () => {
  // 检查是否有未保存的输入
  const hasInput = mockQuestions.value.some(q => q._userAnswer.trim())
  if (hasInput) {
    const confirmed = await confirm('当前有未提交的答案，确定要换一批吗？')
    if (!confirmed) return
  }
  // ... 原有逻辑
}
```

### 步骤 5: 移除 capture 属性 (BUG-018)
**文件:** `frontend/src/components/StagingPanel.vue`
**修改类型:** 删除

**修改前:**
```html
<input type="file" multiple class="hidden" ref="fileInput" @change="handleFileSelect" accept="image/*" capture="environment" />
```

**修改后:**
```html
<input type="file" multiple class="hidden" ref="fileInput" @change="handleFileSelect" accept="image/*" />
```

### 步骤 6: 练习面板响应式布局 (BUG-007)
**文件:** `frontend/src/components/PracticePanel.vue`
**修改类型:** 修改

**修改后:**
```html
<div class="flex-1 flex flex-col lg:flex-row overflow-hidden">
  <div class="w-full lg:w-1/2 flex flex-col border-r border-gray-200 ...">
```

### 步骤 7: 页面切换滚动到顶部 (BUG-013)
**文件:** `frontend/src/App.vue`
**修改类型:** 新增

**修改后:**
```javascript
const onTabChange = (tab) => {
  activeTab.value = tab
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
```

### 步骤 8: 缩短错误 toast 时间 (BUG-014)
**文件:** `frontend/src/composables/useNotification.js`
**修改类型:** 修改

**修改后:**
```javascript
const error = (msg, options) => toast.error(msg, { duration: 5000, ...options })
```

### 步骤 9: 添加 aria-label (BUG-015)
**文件:** 多个组件
**修改类型:** 新增

为所有图标按钮添加 `aria-label` 属性。

### 步骤 10: 虚拟滚动高度响应式 (BUG-016)
**文件:** `frontend/src/components/MasterBankList.vue`
**修改类型:** 修改

**修改后:**
```css
.virtual-scroller {
  height: calc(100vh - 280px);
}
@media (max-width: 1024px) {
  .virtual-scroller {
    height: calc(100vh - 400px);
  }
}
```

---

## 验证方法
1. 在桌面和移动浏览器上测试所有修改
2. 使用屏幕阅读器验证 aria-label
3. 检查键盘导航是否正常

## 回滚方案
每个修改都是独立的，可以通过 git revert 单独回滚。
