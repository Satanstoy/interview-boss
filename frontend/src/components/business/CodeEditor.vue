<template>
  <div class="light-code-editor" :class="{ 'is-readonly': readOnly }">
    <div ref="gutterRef" class="editor-gutter" aria-hidden="true">
      <div class="editor-gutter-lines" :style="{ transform: `translateY(-${scrollTop}px)` }">
        <span v-for="line in lineCount" :key="line">{{ line }}</span>
      </div>
    </div>

    <textarea
      v-if="!readOnly"
      ref="textareaRef"
      :value="modelValue"
      class="editor-input"
      :aria-label="`${language} 代码编辑器`"
      spellcheck="false"
      autocapitalize="off"
      autocomplete="off"
      autocorrect="off"
      @input="handleInput"
      @keydown="handleKeydown"
      @scroll="handleScroll"
    />
    <pre v-else class="editor-input editor-output" :aria-label="`${language} 参考代码`">{{ modelValue }}</pre>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  language: { type: String, default: 'python' },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const textareaRef = ref(null)
const gutterRef = ref(null)
const scrollTop = ref(0)
const lineCount = computed(() => Math.max(1, (props.modelValue || '').split('\n').length))

function handleInput(event) {
  emit('update:modelValue', event.target.value)
}

function handleScroll(event) {
  scrollTop.value = event.target.scrollTop
  if (gutterRef.value) gutterRef.value.scrollTop = event.target.scrollTop
}

function handleKeydown(event) {
  if (event.key !== 'Tab') return

  event.preventDefault()
  const target = event.currentTarget
  const start = target.selectionStart
  const end = target.selectionEnd
  const nextValue = `${props.modelValue.slice(0, start)}    ${props.modelValue.slice(end)}`
  emit('update:modelValue', nextValue)

  requestAnimationFrame(() => {
    if (textareaRef.value) {
      textareaRef.value.selectionStart = start + 4
      textareaRef.value.selectionEnd = start + 4
    }
  })
}
</script>

<style scoped>
.light-code-editor {
  --editor-background: #1e1e1e;
  --editor-foreground: #d4d4d4;
  display: flex;
  height: 100%;
  min-height: 300px;
  overflow: hidden;
  background: var(--editor-background);
  color: var(--editor-foreground);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 14px;
  line-height: 1.5;
}

.editor-gutter {
  width: 52px;
  flex: 0 0 52px;
  overflow: hidden;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  color: #858585;
  text-align: right;
  user-select: none;
}

.editor-gutter-lines {
  display: flex;
  min-height: 100%;
  flex-direction: column;
  padding: 12px 12px 12px 0;
  will-change: transform;
}

.editor-gutter-lines span {
  height: 21px;
  flex: 0 0 21px;
}

.editor-input {
  min-width: 0;
  width: 0;
  flex: 1;
  height: 100%;
  margin: 0;
  border: 0;
  outline: 0;
  padding: 12px 16px;
  resize: none;
  overflow: auto;
  background: transparent;
  color: inherit;
  font: inherit;
  line-height: inherit;
  tab-size: 4;
  white-space: pre;
  word-wrap: normal;
}

.editor-input::selection {
  background: rgba(38, 130, 210, 0.45);
}

.editor-output {
  display: block;
}

.is-readonly .editor-input {
  cursor: default;
}
</style>
