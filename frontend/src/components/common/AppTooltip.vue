<template>
  <Tooltip v-if="supportsHover" v-model:open="isOpen" :delay-duration="delayDuration">
    <TooltipTrigger as-child>
      <slot />
    </TooltipTrigger>
    <TooltipContent :side="side" :align="align" :class="contentClass">
      <slot name="content">{{ text }}</slot>
    </TooltipContent>
  </Tooltip>
  <slot v-else />
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

defineProps({
  text: { type: String, default: '' },
  side: { type: String, default: 'top' },
  align: { type: String, default: 'center' },
  delayDuration: { type: Number, default: 120 },
  contentClass: { type: [String, Object, Array], default: '' },
})

const supportsHover = ref(true)
const isOpen = ref(false)
const route = useRoute()
let hoverQuery

const syncHoverCapability = () => {
  supportsHover.value = hoverQuery?.matches ?? true
}

watch(() => route.fullPath, () => {
  isOpen.value = false
})

onMounted(() => {
  hoverQuery = window.matchMedia('(hover: hover) and (pointer: fine)')
  syncHoverCapability()
  hoverQuery.addEventListener?.('change', syncHoverCapability)
})

onBeforeUnmount(() => hoverQuery?.removeEventListener?.('change', syncHoverCapability))
</script>
