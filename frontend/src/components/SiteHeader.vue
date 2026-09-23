<script setup>
import { computed, inject, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { AlertCircle, ArrowDown, ArrowUp, CheckCircle2, ChevronDown, ChevronRight, Clock3, Ellipsis, FileText, Layers, Loader2, Menu, Plus, Settings, Tag, Trash2, X } from '@lucide/vue'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Textarea } from '@/components/ui/textarea'
import { useSubmitJobs, removeJob } from '@/composables/useSubmitJobs.js'
import { useToast } from '@/composables/useNotification.js'
import { createCodingPlaylist, deleteCodingPlaylist, moveCodingPlaylist } from '@/services/codingApi.js'
import AppTooltip from '@/components/common/AppTooltip.vue'

const props = defineProps({
  activeTabLabel: {
    type: String,
    required: true
  },
  showCurrentPageLabel: {
    type: Boolean,
    default: true
  },
  activeSeason: {
    type: String,
    default: null
  },
  noBorder: {
    type: Boolean,
    default: false
  },
  showCodingControls: {
    type: Boolean,
    default: false
  },
  showPracticeControls: {
    type: Boolean,
    default: false
  },
  practiceDecks: {
    type: Array,
    default: () => []
  },
  practiceSelectedDeckKey: {
    type: String,
    default: 'all'
  },
  practiceDeckLoading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['show-settings', 'toggle-mobile-nav', 'practice-select-deck', 'practice-manage-decks'])

// ── 全局上传任务进度 ──
const { activeJobs } = useSubmitJobs()
const showJobPanel = ref(false)
const expandedJobs = ref(new Set())
const { success, error } = useToast()
const codingNavigation = inject('codingNavigation', null)
const codingPlaylists = computed(() => codingNavigation?.playlists?.value || [])
const codingSelectedListKey = computed(() => codingNavigation?.selectedListKey?.value || 'all')
const playlistDialogOpen = ref(false)
const playlistName = ref('')
const playlistDescription = ref('')
const isCreatingPlaylist = ref(false)
const practiceSelectOpen = ref(false)

// 阶段配置
const PHASE_CONFIG = {
  extract: { label: '提取题目', icon: FileText, color: 'text-blue-500' },
  fill: { label: '补全信息', icon: FileText, color: 'text-cyan-500' },
  tag: { label: '分类标注', icon: Tag, color: 'text-violet-500' },
  match: { label: '匹配聚类', icon: Layers, color: 'text-amber-500' },
  save: { label: '写入题库', icon: CheckCircle2, color: 'text-green-500' },
  cluster: { label: '聚类完成', icon: CheckCircle2, color: 'text-emerald-500' },
}

const PHASE_ORDER = ['extract', 'fill', 'tag', 'match', 'save', 'cluster']

const primaryJob = computed(() => {
  if (activeJobs.value.length === 0) return null
  return activeJobs.value.find(j => j.status === 'running') || activeJobs.value[0]
})

const toggleJobExpand = (jobId) => {
  if (expandedJobs.value.has(jobId)) {
    expandedJobs.value.delete(jobId)
  } else {
    expandedJobs.value.add(jobId)
  }
}

const getPhaseIndex = (step) => PHASE_ORDER.indexOf(step)

const onCloseJob = (jobId) => {
  removeJob(jobId)
  expandedJobs.value.delete(jobId)
}

const openCreatePlaylist = () => {
  playlistName.value = ''
  playlistDescription.value = ''
  playlistDialogOpen.value = true
}

const selectCodingList = (value) => {
  codingNavigation?.selectList(value)
}

const refreshCodingPlaylists = async () => {
  await codingNavigation?.loadPlaylists()
}

const movePlaylist = async (playlist, direction) => {
  try {
    await moveCodingPlaylist(playlist.id, direction)
    await refreshCodingPlaylists()
  } catch (err) {
    error(err.message || '调整题单顺序失败')
  }
}

const removePlaylist = async (playlist) => {
  try {
    await deleteCodingPlaylist(playlist.id)
    if (codingSelectedListKey.value === String(playlist.id)) codingNavigation?.selectList('all')
    await refreshCodingPlaylists()
    success('题单已删除')
  } catch (err) {
    error(err.message || '删除题单失败')
  }
}

const selectPracticeList = (value) => {
  emit('practice-select-deck', value)
}

const openPracticeManager = () => {
  practiceSelectOpen.value = false
  emit('practice-manage-decks')
}

const createPlaylist = async () => {
  if (!playlistName.value.trim() || !codingNavigation) return
  isCreatingPlaylist.value = true
  try {
    if (!codingPlaylists.value.length) await codingNavigation.loadPlaylists()
    const playlist = await createCodingPlaylist({
      name: playlistName.value.trim(),
      description: playlistDescription.value.trim(),
    })
    await codingNavigation.loadPlaylists()
    codingNavigation.selectList(String(playlist.id))
    playlistDialogOpen.value = false
    success('题单已创建')
  } catch (err) {
    error(err.message || '创建题单失败')
  } finally {
    isCreatingPlaylist.value = false
  }
}
</script>

<template>
  <header
    :data-testid="showPracticeControls ? 'practice-header' : undefined"
    class="flex min-h-12 shrink-0 items-center gap-2 bg-background/80 px-2 py-1.5 sm:gap-3 sm:px-3 md:h-11 md:min-h-11 md:py-0 lg:px-5"
  >
    <AppTooltip text="打开导航">
      <Button
        variant="ghost"
        size="sm"
        class="inline-flex h-10 shrink-0 items-center justify-center gap-1.5 px-2.5 text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground md:hidden"
        aria-label="打开导航"
        @click="emit('toggle-mobile-nav')"
      >
        <Menu class="h-4 w-4" />
        <span class="text-xs">菜单</span>
      </Button>
    </AppTooltip>

    <div class="flex h-8 min-w-0 shrink-0 items-center gap-2">
      <span v-if="showCurrentPageLabel" class="hidden h-8 items-center truncate text-[13px] font-semibold leading-none text-foreground sm:flex">
        {{ activeTabLabel }}
      </span>

      <template v-if="showCodingControls">
        <Select :model-value="codingSelectedListKey" @update:model-value="selectCodingList">
          <SelectTrigger class="h-10 w-[min(42vw,150px)] rounded-lg text-xs sm:h-8 sm:w-[150px]">
            <SelectValue placeholder="选择题单" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部题目</SelectItem>
            <SelectItem value="favorites">我的收藏</SelectItem>
            <div v-for="playlist in codingPlaylists" :key="playlist.id" class="relative">
              <SelectItem :value="String(playlist.id)" class="pr-16">
                {{ playlist.name }}（{{ playlist.problem_count }}）
              </SelectItem>
              <DropdownMenu>
                <DropdownMenuTrigger as-child>
                  <button
                    type="button"
                    class="absolute right-8 top-1/2 z-10 inline-flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                    :aria-label="`管理题单 ${playlist.name}`"
                    @pointerdown.stop
                    @click.stop
                  >
                    <Ellipsis class="size-4" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" class="z-[100] min-w-36">
                  <DropdownMenuItem @select="movePlaylist(playlist, 'up')"><ArrowUp class="size-3.5" />上移</DropdownMenuItem>
                  <DropdownMenuItem @select="movePlaylist(playlist, 'down')"><ArrowDown class="size-3.5" />下移</DropdownMenuItem>
                  <DropdownMenuItem variant="destructive" @select="removePlaylist(playlist)"><Trash2 class="size-3.5" />删除题单</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <SelectSeparator />
            <button
              type="button"
              class="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-muted-foreground outline-none transition hover:bg-accent hover:text-accent-foreground"
              @pointerdown.prevent
              @click="openCreatePlaylist"
            >
              <Plus class="size-4" />新建题单
            </button>
          </SelectContent>
        </Select>
      </template>

      <template v-else-if="showPracticeControls">
        <Select v-model:open="practiceSelectOpen" :model-value="practiceSelectedDeckKey" :disabled="practiceDeckLoading || !practiceDecks.length" @update:model-value="selectPracticeList">
          <SelectTrigger data-testid="practice-deck-select" class="h-10 w-[min(42vw,150px)] rounded-lg text-xs sm:h-8 sm:w-[180px]">
            <SelectValue placeholder="选择题单" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="deck in practiceDecks" :key="deck.key" :value="deck.key">
              {{ deck.name }} · {{ deck.total || 0 }} 题
            </SelectItem>
            <SelectSeparator />
            <button
              type="button"
              data-testid="practice-manage-decks"
              class="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-muted-foreground outline-none transition hover:bg-accent hover:text-accent-foreground"
              @pointerdown.prevent
              @click="openPracticeManager"
            >
              <Layers class="size-4" />管理题单
            </button>
          </SelectContent>
        </Select>
      </template>
    </div>

    <div class="flex h-8 flex-1 items-center justify-end gap-1.5">
      <!-- 全局上传任务进度胶囊 -->
      <div v-if="activeJobs.length > 0" class="relative">
        <button
          data-testid="job-progress-toggle"
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
            data-testid="job-progress-panel"
            class="absolute right-0 top-full z-50 mt-1 w-[min(24rem,calc(100vw-1rem))] rounded-xl border border-border bg-card shadow-lg overflow-hidden"
          >
            <div class="text-xs font-semibold text-foreground p-3 pb-2">处理进度</div>
            <div class="max-h-[60vh] overflow-y-auto px-3 pb-3">
              <div v-for="job in activeJobs" :key="job.id" class="rounded-lg border border-border/50 bg-muted/30 mb-2 last:mb-0">
                <!-- 任务头部 -->
                <div
                  class="flex items-center gap-2 p-2.5 cursor-pointer hover:bg-muted/50 transition"
                  @click="toggleJobExpand(job.id)"
                >
                  <ChevronDown v-if="expandedJobs.has(job.id)" class="size-3.5 text-muted-foreground flex-shrink-0" />
                  <ChevronRight v-else class="size-3.5 text-muted-foreground flex-shrink-0" />
                  <span
                    class="size-2 rounded-full flex-shrink-0"
                    :class="{
                      'bg-blue-500 animate-pulse': job.status === 'running',
                      'bg-amber-500': job.status === 'pending',
                      'bg-green-500': job.status === 'completed',
                      'bg-red-500': job.status === 'failed',
                    }"
                  />
                  <span class="text-xs font-medium text-foreground truncate flex-1">
                    {{ job.status === 'completed' ? '处理完成' : job.status === 'failed' ? '处理失败' : job.message || '处理中...' }}
                  </span>
                  <span v-if="job.status === 'running' && job.current > 0" class="text-[10px] text-muted-foreground tabular-nums">
                    {{ job.current }}/{{ job.total }}
                  </span>
                  <AppTooltip v-if="job.status === 'completed' || job.status === 'failed'" text="移除">
                    <button
                      @click.stop="onCloseJob(job.id)"
                      aria-label="移除任务"
                      class="text-muted-foreground hover:text-foreground transition p-0.5"
                    >
                      <X class="size-3" />
                    </button>
                  </AppTooltip>
                </div>

                <!-- 阶段进度条（紧凑模式） -->
                <div v-if="job.status === 'running' || job.status === 'pending'" class="px-2.5 pb-2">
                  <div class="flex gap-0.5">
                    <div
                      v-for="phase in PHASE_ORDER"
                      :key="phase"
                      class="h-1 flex-1 rounded-full transition-colors duration-300"
                      :class="{
                        'bg-blue-500': getPhaseIndex(job.step) > PHASE_ORDER.indexOf(phase),
                        'bg-blue-500 animate-pulse': job.step === phase,
                        'bg-muted': getPhaseIndex(job.step) < PHASE_ORDER.indexOf(phase),
                      }"
                    />
                  </div>
                </div>

                <!-- 展开的详情 -->
                <Transition name="expand">
                  <div v-if="expandedJobs.has(job.id)" class="px-2.5 pb-2.5">
                    <!-- 阶段列表 -->
                    <div class="space-y-1">
                      <div
                        v-for="phase in PHASE_ORDER"
                        :key="phase"
                        class="flex items-center gap-2 py-1 text-[11px]"
                      >
                        <component
                          :is="PHASE_CONFIG[phase].icon"
                          class="size-3 flex-shrink-0"
                          :class="{
                            'text-blue-500': getPhaseIndex(job.step) > PHASE_ORDER.indexOf(phase),
                            'text-blue-500': job.step === phase,
                            'text-muted-foreground/40': getPhaseIndex(job.step) < PHASE_ORDER.indexOf(phase),
                          }"
                        />
                        <span
                          :class="{
                            'text-foreground font-medium': job.step === phase,
                            'text-foreground/70': getPhaseIndex(job.step) > PHASE_ORDER.indexOf(phase),
                            'text-muted-foreground/50': getPhaseIndex(job.step) < PHASE_ORDER.indexOf(phase),
                          }"
                        >
                          {{ PHASE_CONFIG[phase].label }}
                        </span>
                        <CheckCircle2
                          v-if="getPhaseIndex(job.step) > PHASE_ORDER.indexOf(phase)"
                          class="size-3 text-green-500 ml-auto"
                        />
                        <Loader2
                          v-else-if="job.step === phase"
                          class="size-3 text-blue-500 animate-spin ml-auto"
                        />
                      </div>
                    </div>

                    <!-- 当前阶段消息 -->
                    <div v-if="job.message && job.status === 'running'" class="mt-2 pt-2 border-t border-border/50">
                      <p class="text-[11px] text-muted-foreground">{{ job.message }}</p>
                    </div>

                    <!-- 错误信息 -->
                    <div v-if="job.error" class="mt-2 pt-2 border-t border-border/50">
                      <p class="text-[11px] text-red-500">{{ job.error }}</p>
                    </div>

                    <!-- 完成结果 -->
                    <div v-if="job.status === 'completed' && job.result" class="mt-2 pt-2 border-t border-border/50">
                      <p class="text-[11px] text-green-600">
                        提取完成
                        <template v-if="job.result.question_count">，{{ job.result.question_count }} 道题</template>
                        <template v-if="job.result.match_result">
                          （{{ job.result.match_result.matched_count }} 道已有、{{ job.result.match_result.unmatched_count }} 道新题）
                        </template>
                      </p>
                    </div>
                  </div>
                </Transition>
              </div>
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
          size="sm"
          class="inline-flex h-10 items-center justify-center gap-1.5 px-2.5 text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground md:h-8 md:w-8 md:px-0"
          @click="emit('show-settings')"
        >
          <Settings class="h-4 w-4" />
          <span class="text-xs md:sr-only">设置</span>
        </Button>
      </AppTooltip>
    </div>
  </header>

  <Dialog v-model:open="playlistDialogOpen">
    <DialogContent class="max-w-md">
      <DialogHeader>
        <DialogTitle>新建题单</DialogTitle>
        <DialogDescription>创建后会出现在“手撕代码”全局顶栏的题单选择器中。</DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-3">
        <div class="flex flex-col gap-1.5">
          <label class="text-xs font-semibold">题单名称</label>
          <Input v-model="playlistName" placeholder="例如：字节后端高频题" @keyup.enter="createPlaylist" />
        </div>
        <div class="flex flex-col gap-1.5">
          <label class="text-xs font-semibold">描述（可选）</label>
          <Textarea v-model="playlistDescription" :rows="2" placeholder="这个题单用于什么场景？" />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="playlistDialogOpen = false">取消</Button>
        <Button :disabled="isCreatingPlaylist || !playlistName.trim()" @click="createPlaylist">
          {{ isCreatingPlaylist ? '创建中...' : '创建题单' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
.fade-slide-enter-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.fade-slide-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.fade-slide-enter-from { opacity: 0; transform: translateY(-4px); }
.fade-slide-leave-to { opacity: 0; transform: translateY(-4px); }
.expand-enter-active { transition: all 0.2s ease-out; }
.expand-leave-active { transition: all 0.15s ease-in; }
.expand-enter-from, .expand-leave-to { opacity: 0; max-height: 0; }
.expand-enter-to, .expand-leave-from { opacity: 1; max-height: 300px; }
</style>
