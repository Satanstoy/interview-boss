<template>
  <Tooltip :delay-duration="delayDuration">
    <TooltipTrigger as-child>
      <slot />
    </TooltipTrigger>
    <TooltipContent :side="side" :align="align" :class="contentClass">
      <slot name="content">{{ text }}</slot>
    </TooltipContent>
  </Tooltip>
</template>

<script setup>
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

defineProps({
  text: { type: String, default: '' },
  side: { type: String, default: 'top' },
  align: { type: String, default: 'center' },
  delayDuration: { type: Number, default: 120 },
  contentClass: { type: [String, Object, Array], default: '' },
})
</script>
