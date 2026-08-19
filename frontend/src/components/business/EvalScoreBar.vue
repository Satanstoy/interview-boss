<script setup>
const props = defineProps({
  deterministic: { type: Number, default: null },
  judge: { type: Number, default: null },
  final: { type: Number, default: null },
  height: { type: String, default: 'h-2' },
})

function pct(value) {
  if (value == null || isNaN(value)) return '0%'
  return Math.round(value * 100) + '%'
}
</script>

<template>
  <div class="flex items-center gap-2">
    <div :class="['relative w-full overflow-hidden rounded-full bg-muted', height]">
      <!-- Deterministic (blue) segment -->
      <div
        v-if="deterministic != null"
        class="absolute inset-y-0 left-0 bg-blue-500/80 transition-all duration-500"
        :style="{ width: pct(deterministic) }"
      />
      <!-- Judge (green) segment -->
      <div
        v-if="judge != null"
        class="absolute inset-y-0 left-0 bg-emerald-500/80 transition-all duration-500"
        :style="{ width: pct(judge) }"
      />
      <!-- Final overlay line -->
      <div
        v-if="final != null"
        class="absolute inset-y-0 w-0.5 bg-foreground/80"
        :style="{ left: pct(final) }"
      />
    </div>
    <span v-if="final != null" class="shrink-0 font-mono text-xs text-muted-foreground">{{ final.toFixed(3) }}</span>
    <span v-else class="shrink-0 text-xs text-muted-foreground">—</span>
  </div>
</template>
