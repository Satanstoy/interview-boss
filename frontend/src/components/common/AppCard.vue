<template>
  <Card
    :class="cn(
      'transition-colors duration-200',
      hover && 'hover:border-border hover:shadow-md',
      noPadding ? 'p-0 gap-0' : '',
      props.class
    )"
  >
    <!-- Header with title/description -->
    <CardHeader
      v-if="title || $slots.header || $slots['card-title']"
      :class="cn(
        noPadding ? '' : 'border-b border-border/50 pb-4'
      )"
    >
      <slot name="header">
        <CardTitle v-if="title" class="text-foreground">
          <slot name="card-title">{{ title }}</slot>
        </CardTitle>
        <CardDescription v-if="description" class="text-muted-foreground">
          {{ description }}
        </CardDescription>
      </slot>
      <CardAction v-if="$slots['card-action']">
        <slot name="card-action" />
      </CardAction>
    </CardHeader>

    <!-- Content -->
    <CardContent :class="cn(noPadding ? 'px-0' : 'py-5')">
      <slot />
    </CardContent>

    <!-- Footer -->
    <CardFooter
      v-if="$slots.footer"
      :class="cn(
        'gap-2',
        noPadding ? 'py-0 pb-6' : 'py-4 border-t border-border/50'
      )"
    >
      <slot name="footer" />
    </CardFooter>
  </Card>
</template>

<script setup>
import { cn } from '@/lib/utils'
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

const props = defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  noPadding: { type: Boolean, default: false },
  hover: { type: Boolean, default: false },
  class: { type: [String, Object, Array], default: '' },
})
</script>
