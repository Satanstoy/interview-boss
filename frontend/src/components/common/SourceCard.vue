<template>
  <a
    v-if="href"
    :href="href"
    target="_blank"
    rel="noopener noreferrer"
    class="group/source flex min-w-0 items-start gap-2.5 rounded-lg border border-border/80 bg-card px-3 py-2.5 text-left transition-colors hover:border-primary/40 hover:bg-primary/5"
    :aria-label="`打开来源：${title}`"
  >
    <span class="mt-0.5 flex size-7 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border/70 bg-muted">
      <img
        v-if="showFavicon"
        :src="favicon"
        :alt="`${host} 网站图标`"
        class="size-5 object-contain"
        loading="lazy"
        referrerpolicy="no-referrer"
        @error="showFavicon = false"
      >
      <svg v-else class="size-4 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
      </svg>
    </span>
    <span class="min-w-0 flex-1">
      <span class="flex items-center gap-1.5">
        <span class="min-w-0 truncate text-xs font-semibold text-foreground group-hover/source:text-primary">{{ title }}</span>
        <svg class="size-3 shrink-0 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M14 3h7v7M10 14 21 3M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" />
        </svg>
      </span>
      <span class="mt-0.5 block truncate text-[11px] text-muted-foreground">{{ host }}<span v-if="path" class="text-muted-foreground/70">{{ path }}</span></span>
      <span v-if="source.snippet" class="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">{{ source.snippet }}</span>
    </span>
  </a>
  <div v-else class="flex min-w-0 items-start gap-2.5 rounded-lg border border-border/80 bg-card px-3 py-2.5">
    <span class="flex size-7 shrink-0 items-center justify-center rounded-md border border-border/70 bg-muted">
      <svg class="size-4 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
      </svg>
    </span>
    <span class="min-w-0 flex-1 text-xs text-muted-foreground">{{ title }}</span>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { sourceFavicon, sourceHost, sourcePath, sourceTitle, sourceUrl } from '@/utils/source.js'

const props = defineProps({
  source: { type: Object, default: () => ({}) },
})

const href = computed(() => sourceUrl(props.source))
const host = computed(() => sourceHost(props.source))
const path = computed(() => sourcePath(props.source))
const title = computed(() => sourceTitle(props.source))
const favicon = computed(() => sourceFavicon(props.source))
const showFavicon = ref(Boolean(favicon.value))

watch(favicon, (value) => {
  showFavicon.value = Boolean(value)
})
</script>
