<template>
  <div ref="containerRef" class="w-full h-full min-h-[300px]"></div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount, shallowRef } from 'vue'
import { useTheme } from '@/composables/useTheme'
import loader from '@monaco-editor/loader'

const props = defineProps({
  modelValue: { type: String, default: '' },
  language: { type: String, default: 'python' },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const containerRef = ref(null)
const { isDark } = useTheme()

const editor = shallowRef(null)
const model = shallowRef(null)
let monacoInstance = null

const LANGUAGE_MAP = {
  python: 'python',
  c: 'c',
  java: 'java',
}

onMounted(async () => {
  monacoInstance = await loader.init()

  model.value = monacoInstance.editor.createModel(
    props.modelValue,
    LANGUAGE_MAP[props.language] || 'python'
  )

  editor.value = monacoInstance.editor.create(containerRef.value, {
    model: model.value,
    theme: isDark.value ? 'vs-dark' : 'vs',
    fontSize: 14,
    tabSize: 4,
    minimap: { enabled: false },
    lineNumbers: 'on',
    bracketPairColorization: { enabled: true },
    autoClosingBrackets: 'always',
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    automaticLayout: true,
    readOnly: props.readOnly,
    padding: { top: 8, bottom: 8 },
  })

  model.value.onDidChangeContent(() => {
    emit('update:modelValue', model.value.getValue())
  })
})

onBeforeUnmount(() => {
  if (editor.value) {
    editor.value.dispose()
  }
  if (model.value) {
    model.value.dispose()
  }
})

watch(() => props.modelValue, (val) => {
  if (model.value && val !== model.value.getValue()) {
    model.value.setValue(val)
  }
})

watch(() => props.language, (lang) => {
  if (model.value && monacoInstance) {
    monacoInstance.editor.setModelLanguage(model.value, LANGUAGE_MAP[lang] || 'python')
  }
})

watch(isDark, (dark) => {
  if (monacoInstance) {
    monacoInstance.editor.setTheme(dark ? 'vs-dark' : 'vs')
  }
})

watch(() => props.readOnly, (ro) => {
  if (editor.value) {
    editor.value.updateOptions({ readOnly: ro })
  }
})
</script>
