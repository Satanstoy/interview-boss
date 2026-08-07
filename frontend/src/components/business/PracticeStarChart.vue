<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div class="flex items-start justify-end gap-3">
      <span v-if="topItems.length" class="rounded-full border border-border bg-muted/40 px-2.5 py-0.5 text-xs font-semibold text-foreground">
        已练 {{ practicedCount }}/{{ topItems.length }}
      </span>
    </div>

    <div v-if="topItems.length" class="relative mt-2 min-h-[300px] w-full flex-1">
      <svg ref="svgRef" class="h-full w-full" viewBox="0 0 720 470" @click="onSvgClick" />
    </div>
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      题库还没有主题数据
    </div>
    <p v-if="topItems.length" class="mt-1 text-center text-xs text-muted-foreground">
      先刷高热度主题命中率最高 —— {{ topItems[0].name }} 被问 {{ topItems[0].question_frequency }} 次，是当前第一大考点
    </p>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useTheme } from '@/composables/useTheme.js'

const props = defineProps({
  items: { type: Array, default: () => [] },
  positionName: { type: String, default: '岗位' },
})

const emit = defineEmits(['select-topic'])

const { isDark } = useTheme()
const svgRef = ref(null)

const topItems = computed(() =>
  [...props.items]
    .filter((i) => i.question_frequency > 0)
    .sort((a, b) => (b.question_frequency || 0) - (a.question_frequency || 0))
    .slice(0, 8),
)

const practicedCount = computed(() => topItems.value.filter((i) => i.practice_count > 0).length)

const maxHeat = computed(() => Math.max(...topItems.value.map((i) => i.question_frequency || 0), 1))
const totalHeat = computed(() => topItems.value.reduce((s, i) => s + (i.question_frequency || 0), 0))

// 掌握状态三档 → porcelain 蓝阶明度（未练最浅 → 熟练最深）
function statusLevel(item, dark) {
  const st = item.status
  if (st === 'stable') return dark ? '#EDEFF1' : '#334EAC'
  if (st === 'developing') return dark ? '#9EB3CD' : '#7096D1'
  return dark ? '#6C93C7' : '#BAD6EB'
}

function statusBorder(item, dark) {
  if (item.status === 'stable') return dark ? '#EDEFF1' : '#081F5C'
  if (item.status === 'developing') return dark ? '#BCC7D7' : '#334EAC'
  return dark ? '#9EB3CD' : '#334EAC'
}

const STATUS_LABEL = {
  not_started: '未练',
  needs_work: '待加强',
  evidence_only: '待评分',
  developing: '发展中',
  stable: '熟练',
}

function buildSvg(dark) {
  const items = topItems.value
  if (!items.length) return ''
  const R = 250
  const cx = 360
  const cy = 235
  const nodeR = (i) => 8 + Math.sqrt(i.question_frequency) * 3.2
  const lineW = (i) => 0.8 + (i.question_frequency / maxHeat.value) * 1.8
  const hubFill = dark ? '#EDEFF1' : '#081F5C'
  const hubText = dark ? '#081F5C' : '#EDEFF1'
  const lineCol = dark ? 'rgba(237,239,241,.22)' : 'rgba(8,31,92,.15)'
  const labelCol = dark ? '#EDEFF1' : '#081F5C'
  const subCol = dark ? '#9EB3CD' : 'rgba(8,31,92,.60)'

  let s = ''
  s += `<circle cx="${cx}" cy="${cy}" r="74" fill="#334EAC" opacity="${dark ? 0.35 : 0.12}"></circle>`
  items.forEach((item, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / items.length
    const r = R * 0.82
    const x = cx + r * Math.cos(a)
    const y = cy + r * Math.sin(a)
    const rNode = nodeR(item)
    const fill = statusLevel(item, dark)
    const stroke = statusBorder(item, dark)
    s += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${lineCol}" stroke-width="${lineW(item)}"></line>`
    s += `<circle cx="${x}" cy="${y}" r="${rNode}" fill="${fill}" stroke="${stroke}" stroke-width="1.5" data-index="${i}" style="cursor:pointer"></circle>`
    const anchor = x > cx ? 'start' : x < cx ? 'end' : 'middle'
    const tx = x > cx ? x + rNode + 8 : x < cx ? x - rNode - 8 : x
    const ty = y + 3.5
    s += `<text x="${tx}" y="${ty}" text-anchor="${anchor}" font-size="11" font-weight="700" fill="${labelCol}">${item.name}</text>`
    s += `<text x="${tx}" y="${ty + 12}" text-anchor="${anchor}" font-size="9" fill="${subCol}">${item.question_frequency} 次 · ${STATUS_LABEL[item.status] || item.status}</text>`
  })
  s += `<circle cx="${cx}" cy="${cy}" r="56" fill="${hubFill}"></circle>`
  s += `<text x="${cx}" y="${cy - 3}" text-anchor="middle" font-size="14" font-weight="800" fill="${hubText}">${totalHeat.value} 次</text>`
  s += `<text x="${cx}" y="${cy + 16}" text-anchor="middle" font-size="9.5" fill="${dark ? '#081F5C' : 'rgba(237,239,241,.85)'}">岗位总热度</text>`
  return s
}

function render() {
  if (svgRef.value) {
    svgRef.value.innerHTML = buildSvg(isDark.value)
  }
}

function onSvgClick(ev) {
  const el = ev.target.closest('circle[data-index]')
  if (!el) return
  const item = topItems.value[Number(el.dataset.index)]
  if (item) emit('select-topic', item.name)
}

watch(isDark, render)
watch(() => props.items, () => { nextFrame() })
function nextFrame() {
  requestAnimationFrame(render)
}
onMounted(render)
</script>
