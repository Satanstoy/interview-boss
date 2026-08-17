<script setup>
defineProps({
  number: { type: Number, required: true },
  title: { type: String, required: true },
  description: { type: String, required: true },
})
</script>

<template>
  <section class="rounded-xl border border-border/70 bg-background p-4 sm:p-5">
    <div class="flex items-start gap-3">
      <div class="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary">
        {{ number }}
      </div>
      <div class="min-w-0 flex-1">
        <h2 class="text-sm font-semibold text-foreground">第 {{ number }} 步：{{ title }}</h2>
        <p class="mt-1 text-xs leading-5 text-muted-foreground">{{ description }}</p>
        <div class="mt-4">
          <slot />
        </div>
      </div>
    </div>
  </section>
</template>
