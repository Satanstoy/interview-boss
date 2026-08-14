<template>
  <Tooltip v-if="supportsHover" v-model:open="isOpen" :delay-duration="delayDuration">
    <TooltipTrigger as-child :aria-label="effectiveLabel || undefined">
      <slot />
    </TooltipTrigger>
    <TooltipContent :side="side" :align="align" :class="contentClass">
      <slot name="content">{{ text }}</slot>
    </TooltipContent>
  </Tooltip>
  <template v-else>
    <AccessibleSlot />
    <span class="sr-only">{{ effectiveLabel }}</span>
  </template>
</template>

<script setup>
import { cloneVNode, computed, defineComponent, h, onBeforeUnmount, onMounted, ref, useSlots, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const props = defineProps({
  text: { type: String, default: '' },
  ariaLabel: { type: String, default: '' },
  side: { type: String, default: 'top' },
  align: { type: String, default: 'center' },
  delayDuration: { type: Number, default: 120 },
  contentClass: { type: [String, Object, Array], default: '' },
})

const slots = useSlots()

// Accessible label is shared by the hover trigger and the touch fallback so
// icon-only buttons always expose a name (WCAG 4.1.2).
const effectiveLabel = computed(() => props.ariaLabel || props.text || '')

// Touch fallback: re-render the single default-slot root with aria-label
// injected onto it, so a bare icon-only <button> still carries a name on
// devices without hover. Caller-provided aria-labels are never overwritten.
const AccessibleSlot = defineComponent({
  name: 'AppTooltipAccessibleSlot',
  render() {
    const vnodes = slots.default?.() ?? []
    const root = vnodes.length === 1 ? vnodes[0] : null
    if (!root) return h('span', { style: 'display:contents;' }, vnodes)
    const label = effectiveLabel.value
    if (!label) return root
    const type = root.type
    if (typeof type !== 'string' && typeof type !== 'object') return root
    const existing = root.props?.['aria-label']
    if (existing && String(existing).trim()) return root
    return cloneVNode(root, { 'aria-label': label })
  },
})

const supportsHover = ref(true)
const isOpen = ref(false)
// Gracefully handle being mounted outside a vue-router context (e.g. isolated
// component tests): only auto-close on route change when a router is present.
const route = (() => { try { return useRoute() } catch { return null } })()
let hoverQuery

const syncHoverCapability = () => {
  supportsHover.value = hoverQuery?.matches ?? true
}

watch(() => route?.fullPath, () => {
  isOpen.value = false
})

onMounted(() => {
  hoverQuery = window.matchMedia('(hover: hover) and (pointer: fine)')
  syncHoverCapability()
  hoverQuery.addEventListener?.('change', syncHoverCapability)
})

onBeforeUnmount(() => hoverQuery?.removeEventListener?.('change', syncHoverCapability))
</script>
