# 修复计划

**Bug ID:** BUG-001
**日期:** 2026-05-10
**优先级:** P2

## 修复步骤

### 步骤 1: 重写 Single-question sources 分支
**文件:** `frontend/src/components/QuestionCard.vue`
**行号:** 170-185
**修改类型:** 重写

**修改前:**
```html
<!-- Single-question sources (no original_questions) -->
<div v-else-if="question.sources && question.sources.length > 0" class="flex flex-wrap items-center gap-1.5">
  <span v-for="(src, idx) in question.sources" :key="idx"
    @click="$emit('navigate-to-interview', src)"
    class="text-xs bg-primary-50 ... px-2 py-1 rounded-md inline-flex items-center cursor-pointer ...">
    {{ src.company }} | {{ src.round }}
    <a ...>[原文]</a>
  </span>
  <button v-if="isAdmin" @click.stop="$emit('start-merge', ...)" ...>合并到</button>
</div>
```

**修改后:**
```html
<!-- Single-question sources (no original_questions) -->
<template v-else-if="question.sources && question.sources.length > 0">
  <div v-for="(src, idx) in question.sources" :key="idx"
    class="bg-surface-50 dark:bg-surface-700 border border-surface-200 dark:border-ink-600 rounded-xl p-3 flex items-start gap-3">
    <span class="text-ink-400 dark:text-ink-500 font-mono text-xs shrink-0 mt-0.5">{{ idx + 1 }}.</span>
    <div class="flex-1 min-w-0">
      <div class="flex flex-wrap items-center gap-1.5">
        <span @click="$emit('navigate-to-interview', src)"
          class="text-[11px] bg-primary-50 ... cursor-pointer ...">
          {{ src.company }} | {{ src.round }}
          <a ...>[原文]</a>
        </span>
        <button v-if="isAdmin" @click.stop="$emit('split-question', { question, originalQuestion: question.question })"
          ...>独立</button>
        <button v-if="isAdmin" @click.stop="$emit('start-merge', { question, originalQuestion: question.question })"
          ...>合并到</button>
      </div>
    </div>
  </div>
</template>
```

## 验证方法
1. 高频题库中找到无 `original_questions` 但 frequency > 1 的题目
2. 展开来源详情，确认每条来源独立一行、有序号、有"独立"和"合并到"按钮
3. 测试"独立"和"合并到"按钮功能正常（后端已有校验）

## 回滚方案
恢复 QuestionCard.vue 原始的 Single-question sources 分支代码
