<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { getDistributionDefault, getDistributionPreference, saveDistributionPreference } from '@/services/interviewDistributionApi.js'

const props = defineProps({ jobPosition: { type: String, default: '' } })
const emit = defineEmits(['saved'])

const labels = {
  project_followup: '项目深挖', knowledge_probe: '知识探测', algorithm_coding: '算法与编程',
  system_design: '系统设计', behavioral: '行为与协作',
}
const keys = Object.keys(labels)
const loading = ref(false)
const saving = ref(false)
const mode = ref('system_default')
const targetQuestionCount = ref(10)
const distribution = ref(Object.fromEntries(keys.map(key => [key, 20])))
const stats = ref(null)
const error = ref('')
const total = computed(() => keys.reduce((sum, key) => sum + Number(distribution.value[key] || 0), 0))

function unwrapData(response) {
  return response?.data ?? response
}

function applyStats(value) {
  stats.value = value
  targetQuestionCount.value = value.recommended_total_count
  distribution.value = Object.fromEntries(keys.map(key => [key, Math.round(value.distribution[key] * 100)]))
  normalizeLastKey()
}
function normalizeLastKey(changedKey = null) {
  const pivot = changedKey || keys.at(-1)
  const others = keys.filter(key => key !== pivot).reduce((sum, key) => sum + Number(distribution.value[key] || 0), 0)
  distribution.value[pivot] = Math.max(0, Math.min(100, 100 - others))
}
function updateValue(key, event) {
  distribution.value[key] = Math.max(0, Math.min(100, Number(event.target.value || 0)))
  normalizeLastKey(key === keys.at(-1) ? keys.at(-2) : keys.at(-1))
}
async function load() {
  if (!props.jobPosition) return
  loading.value = true
  error.value = ''
  try {
    const [defaultResponse, preferenceResponse] = await Promise.all([
      getDistributionDefault(props.jobPosition), getDistributionPreference(props.jobPosition),
    ])
    const defaultStats = unwrapData(defaultResponse)
    const preference = unwrapData(preferenceResponse)
    applyStats(defaultStats)
    mode.value = preference.mode || 'system_default'
    if (preference.target_question_count) targetQuestionCount.value = preference.target_question_count
    if (preference.custom_distribution) {
      distribution.value = Object.fromEntries(keys.map(key => [key, Math.round(preference.custom_distribution[key] * 100)]))
      normalizeLastKey()
    }
  } catch (cause) {
    error.value = cause.message || '无法加载面试分布'
  } finally { loading.value = false }
}
async function save() {
  if (mode.value === 'custom' && total.value !== 100) return
  saving.value = true
  try {
    const payload = {
      mode: mode.value,
      target_question_count: Number(targetQuestionCount.value),
      custom_distribution: mode.value === 'custom'
        ? Object.fromEntries(keys.map(key => [key, Number(distribution.value[key]) / 100])) : null,
      style_strength: 'normal',
    }
    const saved = await saveDistributionPreference(props.jobPosition, payload)
    emit('saved', saved)
  } catch (cause) { error.value = cause.message || '保存失败' }
  finally { saving.value = false }
}
watch(() => props.jobPosition, load)
onMounted(load)
</script>

<template>
  <section class="rounded-xl border bg-card p-6 space-y-5" data-testid="interview-distribution-settings">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h4 class="text-sm font-semibold text-foreground">模拟面试题型分布</h4>
        <p class="mt-1 text-xs text-muted-foreground">默认值来自已审核真实面经；可按岗位保存自己的比例。</p>
      </div>
      <span v-if="stats" class="text-xs text-muted-foreground">样本 {{ stats.sample_interview_count }} 场 · 版本 {{ stats.stats_version }}</span>
    </div>
    <p v-if="error" class="text-xs text-destructive">{{ error }}</p>
    <div class="flex gap-2">
      <Button size="sm" :variant="mode === 'system_default' ? 'default' : 'outline'" @click="mode = 'system_default'">系统默认</Button>
      <Button size="sm" :variant="mode === 'custom' ? 'default' : 'outline'" @click="mode = 'custom'">自定义分布</Button>
    </div>
    <label class="block text-xs font-medium text-foreground">本场主问题数
      <Input v-model.number="targetQuestionCount" type="number" min="1" max="50" class="mt-1 h-8 w-28" />
    </label>
    <div class="space-y-3">
      <label v-for="key in keys" :key="key" class="grid grid-cols-[7rem_1fr_3rem] items-center gap-3 text-xs">
        <span>{{ labels[key] }}</span>
        <input :value="distribution[key]" type="range" min="0" max="100" step="1" :disabled="mode !== 'custom' || loading" @input="updateValue(key, $event)" />
        <Input :model-value="distribution[key]" type="number" min="0" max="100" :disabled="mode !== 'custom'" class="h-8 text-right" @update:model-value="value => { distribution[key] = Number(value); normalizeLastKey(key) }" />
      </label>
    </div>
    <div class="flex items-center justify-between text-xs" :class="total === 100 ? 'text-muted-foreground' : 'text-destructive'">
      <span>自定义比例合计 {{ total }}%</span><span v-if="stats">默认题数中位数 {{ stats.recommended_total_count }}</span>
    </div>
    <Button size="sm" :disabled="saving || loading || (mode === 'custom' && total !== 100)" @click="save">{{ saving ? '保存中...' : '保存面试分布' }}</Button>
  </section>
</template>
