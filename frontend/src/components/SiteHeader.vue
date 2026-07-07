<script setup>
import { ref, computed } from 'vue'
import { Button } from '@/components/ui/button'
import { AlertCircle, Clock3, Loader2, Menu, Settings, X } from '@lucide/vue'
import { useSubmitJobs, removeJob } from '@/composables/useSubmitJobs.js'
import AppTooltip from '@/components/common/AppTooltip.vue'

const props = defineProps({
  activeTabLabel: {
    type: String,
    required: true
  },
  activeSeason: {
    type: String,
    default: null
  },
  noBorder: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['show-settings', 'toggle-mobile-nav'])

// ── 全局上传任务进度 ──
const { activeJobs } = useSubmitJobs()
const showJobPanel = ref(false)

const primaryJob = computed(() => {
  if (activeJobs.value.length === 0) return null
  // 优先显示 running 状态的任务
  return activeJobs.value.find(j => j.status === 'running') || activeJobs.value[0]
})

const onCloseJob = (jobId) => {
  removeJob(jobId)
}
</script>

<template>
  <header
    class="flex h-11 shrink-0 items-center gap-3 bg-background/80 px-3 lg:px-5"
  >
    <AppTooltip text="打开导航">
      <Button
        variant="ghost"
        size="icon"
        class="inline-flex h-8 w-8 shrink-0 items-center justify-center text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground md:hidden"
        aria-label="打开导航"
        @click="emit('toggle-mobile-nav')"
      >
        <Menu class="h-4 w-4" />
      </Button>
    </AppTooltip>

    <div class="flex h-8 min-w-0 items-center">
      <h1 class="truncate text-[13px] font-medium leading-5 text-foreground">
        {{ activeTabLabel }}
      </h1>
    </div>

    <div class="flex h-8 flex-1 items-center justify-end gap-1.5">
      <!-- 全局上传任务进度胶囊 -->
      <div v-if="activeJobs.length > 0" class="relative">
        <button
          @click="showJobPanel = !showJobPanel"
          class="flex items-center gap-1.5 h-8 px-2.5 rounded-md border border-border bg-muted/50 hover:bg-muted transition text-xs"
        >
          <Loader2 v-if="primaryJob?.status === 'running'" class="size-3.5 animate-spin text-blue-500" />
          <AlertCircle v-else-if="primaryJob?.status === 'failed'" class="size-3.5 text-red-500" />
          <Clock3 v-else class="size-3.5 text-amber-500" />
          <span class="font-medium text-foreground">{{ activeJobs.length }}</span>
          <span v-if="primaryJob?.percent > 0" class="text-muted-foreground">{{ primaryJob.percent }}%</span>
        </button>

        <!-- 展开的任务列表面板 -->
        <Transition name="fade-slide">
          <div
            v-if="showJobPanel"
            class="absolute right-0 top-full mt-1 z-50 w-80 bg-card rounded-xl shadow-lg border border-border p-3"
          >
            <div class="text-xs font-semibold text-foreground mb-2 px-1">后台任务</div>
            <div v-for="job in activeJobs" :key="job.id" class="flex flex-col gap-1.5 p-2 rounded-lg bg-muted/50 mb-1.5 last:mb-0">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-1.5">
                  <span
                    class="size-2 rounded-full flex-shrink-0"
                    :class="{
                      'bg-blue-500 animate-pulse': job.status === 'running',
                      'bg-amber-500': job.status === 'pending',
                      'bg-green-500': job.status === 'completed',
                      'bg-red-500': job.status === 'failed',
                    }"
                  />
                  <span class="text-xs font-medium text-foreground truncate max-w-[180px]">
                    {{ job.status === 'completed' ? '处理完成' : job.status === 'failed' ? '处理失败' : job.message || '处理中...' }}
                  </span>
                </div>
                <button
                  v-if="job.status === 'completed' || job.status === 'failed'"
                  @click="onCloseJob(job.id)"
                  aria-label="移除任务"
                  class="text-muted-foreground hover:text-foreground transition p-0.5"
                >
                  <X class="size-3.5" />
                </button>
              </div>
              <!-- 进度条 -->
              <div v-if="job.status === 'running' || job.status === 'pending'" class="w-full bg-muted rounded-full h-1 overflow-hidden">
                <div
                  class="h-full rounded-full bg-gradient-to-r from-blue-500 to-indigo-500 transition-all duration-500 ease-out"
                  :style="{ width: `${job.percent}%` }"
                />
              </div>
              <!-- 错误信息 -->
              <p v-if="job.error" class="text-[11px] text-red-500 truncate">{{ job.error }}</p>
            </div>
          </div>
        </Transition>
      </div>

      <!-- Season badge — h-8 matches settings button for visual center alignment -->
      <span
        v-if="activeSeason"
        class="hidden h-8 items-center rounded-md border border-border bg-muted/50 px-2 text-xs font-medium leading-none text-muted-foreground md:inline-flex"
      >
        {{ activeSeason }}
      </span>

      <!-- Settings button -->
      <AppTooltip text="设置">
        <Button
          variant="ghost"
          size="icon"
          class="inline-flex h-8 w-8 items-center justify-center text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
          @click="emit('show-settings')"
        >
          <Settings class="h-4 w-4" />
          <span class="sr-only">设置</span>
        </Button>
      </AppTooltip>
    </div>
  </header>
</template>

<style scoped>
.fade-slide-enter-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.fade-slide-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.fade-slide-enter-from { opacity: 0; transform: translateY(-4px); }
.fade-slide-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
