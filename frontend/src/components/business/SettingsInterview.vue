<script setup>
import { ref, computed, onMounted, inject } from 'vue'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import { switchMyPosition, deletePosition, createPosition, generateTaxonomy, confirmTaxonomy, fetchPositions } from '@/services/profileApi.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import AppTooltip from '@/components/common/AppTooltip.vue'
import InterviewDistributionSettings from '@/components/business/InterviewDistributionSettings.vue'

const props = defineProps({
  masterBank: { type: Array, default: () => [] },
})

const emit = defineEmits(['go-to-question', 'profile-updated'])
const { success: toastSuccess, error: toastError, warning: toastWarning } = useToast()
const { confirm: showConfirm } = useConfirm()

const { displayUser, currentUser } = inject('appData')

onMounted(async () => {
  try {
    const data = await fetchPositions()
    positions.value = data.positions || []
    // 从用户数据初始化当前岗位
    if (displayUser.value?.current_position) {
      currentPosition.value = displayUser.value.current_position
    }
  } catch (e) {
    console.error('Failed to fetch positions', e)
  }
})

// ── Position management ──
const positions = ref([])
const currentPosition = ref('')
const newPositionInput = ref('')
const switching = ref(false)

const setCurrentPosition = (pos) => {
  currentPosition.value = pos
}

const handleSwitchPosition = async (pos) => {
  if (pos === currentPosition.value) return
  switching.value = true
  try {
    const data = await switchMyPosition(pos)
    currentPosition.value = pos
    if (currentUser?.value) {
      currentUser.value = {
        ...currentUser.value,
        current_position: data.current_position || data.current_job_position || pos,
        current_position_id: data.current_position_id ?? null,
      }
    }
    toastSuccess(`已切换到岗位：${pos}`)
    emit('profile-updated')
  } catch (e) {
    toastError(`切换失败: ${e.message}`)
  } finally {
    switching.value = false
  }
}

const handleAddPosition = async () => {
  const name = newPositionInput.value.trim()
  if (!name) return
  if (name.length > 30) {
    toastWarning('岗位名称不能超过 30 个字符')
    return
  }
  if (positions.value.some(p => p.name === name)) {
    toastWarning('该岗位已存在')
    return
  }
  try {
    await createPosition(name)
    // 添加到本地列表
    positions.value.push({ name })
    newPositionInput.value = ''
    toastSuccess(`岗位「${name}」已添加`)
    emit('profile-updated')
  } catch (e) {
    toastError(`添加失败: ${e.message}`)
  }
}

const handleDeletePosition = async (pos) => {
  if (!await showConfirm(`确定要删除岗位"${pos}"吗？`)) return
  try {
    await deletePosition(pos)
    // 从本地列表中移除（positions 是对象数组，按 name 匹配）
    positions.value = positions.value.filter(p => p.name !== pos)
    if (currentPosition.value === pos) {
      currentPosition.value = ''
    }
    toastSuccess(`岗位"${pos}"已删除`)
    emit('profile-updated')
  } catch (e) {
    toastError(`删除失败: ${e.message}`)
  }
}

// ── AI Taxonomy suggestion ──
const taxonomyLoading = ref(false)
const taxonomyPreview = ref(null) // { position, categories }
const taxonomyOpen = ref(false)

const handleGenerateTaxonomy = async () => {
  if (!currentPosition.value) {
    toastWarning('请先选择目标岗位')
    return
  }
  taxonomyLoading.value = true
  try {
    const data = await generateTaxonomy()
    taxonomyPreview.value = data
    taxonomyOpen.value = true
  } catch (e) {
    toastError(`AI生成失败: ${e.message}`)
  } finally {
    taxonomyLoading.value = false
  }
}

const handleConfirmTaxonomy = async () => {
  if (!taxonomyPreview.value) return
  try {
    await confirmTaxonomy(taxonomyPreview.value.categories)
    taxonomyOpen.value = false
    taxonomyPreview.value = null
    toastSuccess('分类体系已更新')
    emit('profile-updated')
  } catch (e) {
    toastError(`保存失败: ${e.message}`)
  }
}

const handleCancelTaxonomy = () => {
  taxonomyOpen.value = false
  taxonomyPreview.value = null
}

// ── Favorites ──
const starredQuestions = computed(() => {
  return props.masterBank
    .filter(q => q.is_starred)
    .slice(0, 20)
})

const handleGoToQuestion = (question) => {
  emit('go-to-question', question)
}
</script>

<template>
  <div class="w-full space-y-8">
    <div>
      <h3 class="text-lg font-semibold text-foreground">面试偏好</h3>
      <p class="text-sm text-muted-foreground mt-1">设置你的目标岗位和面试偏好</p>
    </div>

    <!-- Card 1: 目标岗位 -->
    <div class="rounded-xl border bg-card p-6 space-y-4">
      <h4 class="text-sm font-semibold text-foreground">目标岗位</h4>

      <!-- Position button group -->
      <div class="flex gap-2 flex-wrap">
        <div v-for="pos in positions" :key="pos.id || pos.name" class="flex items-center gap-1">
          <Button
            :variant="currentPosition === pos.name ? 'default' : 'outline'"
            size="sm"
            :disabled="switching"
            @click="handleSwitchPosition(pos.name)"
            :class="currentPosition === pos.name
              ? 'bg-primary/10 text-primary border-primary/30 hover:bg-primary/15'
              : ''"
          >
            {{ pos.name }}
          </Button>
          <AppTooltip text="删除岗位">
            <Button
              variant="ghost"
              size="icon-sm"
              @click="handleDeletePosition(pos.name)"
              class="text-muted-foreground/50 hover:text-destructive transition-colors"
            >
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </Button>
          </AppTooltip>
        </div>
      </div>

      <!-- Add new position -->
      <div class="flex gap-2">
        <Input
          v-model="newPositionInput"
          placeholder="新增岗位（最多30字）"
          class="flex-1 text-sm"
          @keyup.enter="handleAddPosition"
        />
        <Button variant="outline" size="sm" @click="handleAddPosition" class="whitespace-nowrap">
          添加
        </Button>
      </div>
      <div v-if="newPositionInput.length > 20" class="text-xs" :class="newPositionInput.length > 30 ? 'text-destructive' : 'text-muted-foreground'">
        {{ newPositionInput.length }} / 30
      </div>

      <!-- AI Taxonomy button -->
      <Button
        @click="handleGenerateTaxonomy"
        :disabled="taxonomyLoading || !currentPosition"
        variant="outline"
        size="sm"
        class="w-full"
      >
        <svg v-if="taxonomyLoading" class="size-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
        <svg v-else class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
        {{ taxonomyLoading ? 'AI 生成中...' : 'AI 推荐分类体系' }}
      </Button>
    </div>

    <InterviewDistributionSettings :job-position="currentPosition" @saved="() => toastSuccess('面试分布已保存')" />

    <!-- Card 2: 收藏夹 -->
    <div class="rounded-xl border bg-card p-6 space-y-4">
      <h4 class="text-sm font-semibold text-foreground">收藏夹</h4>

      <div v-if="starredQuestions.length === 0" class="text-sm text-muted-foreground py-4 text-center">
        暂无收藏题目
      </div>

      <div v-else class="flex flex-col gap-2">
        <div
          v-for="question in starredQuestions"
          :key="question.id"
          class="flex items-center gap-3 p-3 rounded-lg border border-border hover:bg-accent/50 cursor-pointer transition-colors"
          @click="handleGoToQuestion(question)"
        >
          <svg class="size-4 text-amber-500 shrink-0" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
          </svg>
          <span class="text-sm text-foreground truncate flex-1">{{ question.question }}</span>
          <svg class="size-4 text-muted-foreground shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>
      </div>
    </div>

    <!-- AI Taxonomy Preview Dialog -->
    <Dialog :open="taxonomyOpen" @update:open="handleCancelTaxonomy">
      <DialogContent class="sm:max-w-2xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>AI 推荐分类体系</DialogTitle>
          <DialogDescription>岗位：{{ taxonomyPreview?.position }}</DialogDescription>
        </DialogHeader>
        <div class="flex-1 overflow-y-auto flex flex-col gap-3">
          <div v-for="(cat, i) in (taxonomyPreview?.categories || [])" :key="i" class="rounded-xl border border-border overflow-hidden">
            <div class="px-4 py-2.5 bg-primary/10 dark:bg-primary/20 font-semibold text-sm text-primary">
              {{ cat.cat1 }}
            </div>
            <div class="px-4 py-2 flex flex-col gap-1">
              <div v-for="(child, j) in cat.children" :key="j" class="text-sm text-muted-foreground pl-4">
                {{ child }}
              </div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="handleCancelTaxonomy">取消</Button>
          <Button @click="handleConfirmTaxonomy">采纳此分类</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
