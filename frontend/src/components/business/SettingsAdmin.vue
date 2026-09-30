<script setup>
import { ref, reactive, watch, onMounted } from 'vue'
import { useToast } from '@/composables/useNotification.js'
import { FolderTree, AlertTriangle, ChevronRight, Plus, Trash2, Save, ClipboardCheck } from '@lucide/vue'
import { fetchProfile, fetchPositions, fetchSystemTaxonomy, updateSystemTaxonomy } from '@/services/profileApi.js'
import SettingsQuality from './SettingsQuality.vue'
import SettingsQualityAssistant from './SettingsQualityAssistant.vue'
import SettingsSourceHealth from './SettingsSourceHealth.vue'
import SettingsGlobalModel from './SettingsGlobalModel.vue'
import SettingsPublicSearch from './SettingsPublicSearch.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import AppTooltip from '@/components/common/AppTooltip.vue'

const adminTabs = [
  { id: 'taxonomy', label: '分类管理' },
  { id: 'quality', label: '聚合质量' },
  { id: 'model', label: '模型配置' },
  { id: 'search', label: '联网搜索' },
]
const qualitySubTab = ref('list')

const props = defineProps({
  taxonomy: { type: Object, default: () => ({ categories: [] }) },
  isBuilding: { type: Boolean, default: false },
  isAdmin: { type: Boolean, default: false },
  initialTab: { type: String, default: 'taxonomy' },
})

const validAdminTabs = new Set(adminTabs.map((tab) => tab.id))
const normalizeAdminTab = (tab) => validAdminTabs.has(tab) ? tab : 'taxonomy'
const adminTab = ref(normalizeAdminTab(props.initialTab))
watch(() => props.initialTab, (tab) => {
  adminTab.value = normalizeAdminTab(tab)
})

const emit = defineEmits(['build-master-bank', 'taxonomy-updated'])
const { success: toastSuccess, error: toastError, warning: toastWarning } = useToast()

// Deep-copy taxonomy to avoid prop mutation
const localTaxonomy = reactive({
  job_position: props.taxonomy.job_position || '',
  categories: JSON.parse(JSON.stringify(props.taxonomy.categories || [])),
  tags: JSON.parse(JSON.stringify(props.taxonomy.tags || [])),
})
const positions = ref([])
const selectedPosition = ref('')

const syncTaxonomy = (taxonomy) => {
  localTaxonomy.job_position = taxonomy?.job_position || ''
  localTaxonomy.categories = JSON.parse(JSON.stringify(taxonomy?.categories || []))
  localTaxonomy.tags = JSON.parse(JSON.stringify(taxonomy?.tags || []))
}

const loadSystemTaxonomy = async (position) => {
  if (!position) return
  try {
    syncTaxonomy(await fetchSystemTaxonomy(position))
  } catch (e) {
    toastError(`读取岗位分类失败: ${e.message}`)
  }
}

watch(() => props.taxonomy, syncTaxonomy, { deep: true })
watch(selectedPosition, (position) => {
  loadSystemTaxonomy(position)
})

onMounted(async () => {
  try {
    const profile = await fetchProfile()
    const rawTaxonomy = profile?.settings?.taxonomy_config ?? profile?.taxonomy_config
    if (rawTaxonomy) {
      const taxonomy = typeof rawTaxonomy === 'string' ? JSON.parse(rawTaxonomy) : rawTaxonomy
      syncTaxonomy(taxonomy)
    }
    const positionData = await fetchPositions()
    positions.value = positionData.positions || []
    selectedPosition.value = profile?.settings?.current_job_position || localTaxonomy.job_position || positions.value[0]?.name || ''
    if (selectedPosition.value) await loadSystemTaxonomy(selectedPosition.value)
  } catch (e) {
    console.error('Failed to load taxonomy', e)
  }
})

// ── Card 1: 系统分类体系管理 ──

const addCat1 = () => {
  localTaxonomy.categories.push({ cat1: '', children: [''], _open: true })
}

const removeCat1 = (index) => {
  localTaxonomy.categories.splice(index, 1)
}

const addChild = (cat) => {
  cat.children.push('')
}

const removeChild = (cat, childIndex) => {
  cat.children.splice(childIndex, 1)
}

const addTag = () => {
  localTaxonomy.tags.push('')
}

const removeTag = (index) => {
  localTaxonomy.tags.splice(index, 1)
}

const onSaveSystem = async () => {
  const valid = getValidCategories()
  const tags = (localTaxonomy.tags || []).map(tag => tag.trim()).filter(Boolean)
  if (!localTaxonomy.job_position || !valid.length || !tags.length) {
    toastWarning('岗位、分类和标签均不能为空')
    return
  }
  try {
    await updateSystemTaxonomy({
      position: localTaxonomy.job_position,
      categories: valid,
      tags,
    })
    localTaxonomy.tags = tags
    toastSuccess('系统分类已保存')
    emit('taxonomy-updated')
  } catch (e) {
    toastError(`保存失败: ${e.message}`)
  }
}

const getValidCategories = () => {
  return (localTaxonomy.categories || [])
    .filter(c => c.cat1?.trim())
    .map(c => ({
      cat1: c.cat1.trim(),
      children: (c.children || []).filter(x => x.trim()),
    }))
}

// ── Card 3: 题库操作 ──
const onRebuild = () => {
  emit('build-master-bank')
}
</script>

<template>
  <div class="w-full space-y-8">
    <!-- Header -->
    <div>
      <h3 class="text-lg font-semibold text-foreground">管理员设置</h3>
    </div>

    <!-- Tab 切换：分类管理 / 聚合质量 -->
    <div class="flex items-center gap-1.5 rounded-lg border border-border p-1 w-fit">
      <button
        v-for="tab in adminTabs"
        :key="tab.id"
        class="rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
        :class="adminTab === tab.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'"
        @click="adminTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Card 1: 分类体系管理 -->
    <div v-if="adminTab === 'taxonomy'" class="rounded-xl border bg-card p-6 space-y-4">
      <div class="flex items-center justify-between">
        <h3 class="text-xs font-bold text-primary uppercase tracking-wider flex items-center gap-2">
          <FolderTree class="size-4" />
          系统分类体系管理
        </h3>
        <label class="flex items-center gap-2 text-xs text-muted-foreground">
          <span>岗位</span>
          <select v-model="selectedPosition" class="rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground">
            <option v-for="position in positions" :key="position.id" :value="position.name">{{ position.name }}</option>
          </select>
        </label>
        <Button variant="link" size="sm" @click="addCat1" class="text-xs text-primary h-auto p-0 no-underline hover:no-underline">
          <Plus class="size-3.5 mr-1" />
          添加大类
        </Button>
      </div>

      <!-- Category tree -->
      <div v-if="localTaxonomy.categories?.length" class="flex flex-col gap-2">
        <div v-for="(cat, ci) in localTaxonomy.categories" :key="ci"
          class="rounded-xl border border-border bg-background overflow-hidden">
          <!-- Cat1 header -->
          <div class="flex items-center gap-2 px-3 py-2.5 bg-muted dark:bg-card border-b border-border">
            <AppTooltip :text="cat._open ? '收起分类' : '展开分类'">
              <Button variant="ghost" size="icon-sm" :aria-label="cat._open ? '收起分类' : '展开分类'" @click="cat._open = !cat._open"
                class="text-muted-foreground hover:text-foreground h-6 w-6 transition-colors duration-200">
                <ChevronRight :class="['size-4 transition-transform', { 'rotate-90': cat._open }]" />
              </Button>
            </AppTooltip>
            <input v-model="cat.cat1"
              class="flex-1 text-sm font-semibold bg-transparent border-none outline-none text-foreground placeholder-muted-foreground"
              placeholder="如 A.项目经验与设计" />
            <span class="text-xs text-muted-foreground">{{ (cat.children || []).length }} 个子类</span>
            <AppTooltip text="删除大类">
              <Button variant="ghost" size="icon-sm" aria-label="删除大类" @click="removeCat1(ci)"
                class="text-muted-foreground/50 hover:text-red-500 dark:hover:text-red-400 h-6 w-6 transition-colors duration-200">
                <Trash2 class="size-4" />
              </Button>
            </AppTooltip>
          </div>

          <!-- Children -->
          <div v-if="cat._open" class="p-3 flex flex-col gap-1.5">
            <div v-for="(child, ci2) in cat.children" :key="ci2" class="flex items-center gap-2">
              <span class="text-muted-foreground/50 text-xs">-</span>
              <input v-model="cat.children[ci2]"
                class="flex-1 text-sm bg-transparent border-none outline-none text-foreground placeholder-muted-foreground"
                placeholder="如 A1.系统设计" />
              <AppTooltip text="删除子类">
                <Button variant="ghost" size="icon-sm" aria-label="删除子类" @click="removeChild(cat, ci2)"
                  class="text-muted-foreground/50 hover:text-red-500 dark:hover:text-red-400 h-5 w-5 transition-colors duration-200">
                  <Trash2 class="size-3.5" />
                </Button>
              </AppTooltip>
            </div>
            <Button variant="link" size="sm" @click="addChild(cat)"
              class="text-xs text-primary h-auto p-0 mt-1 no-underline hover:no-underline">
              <Plus class="size-3 mr-1" />
              添加子类
            </Button>
          </div>
        </div>
      </div>

      <p v-else class="text-sm text-muted-foreground text-center py-4">
        暂无分类，点击「添加大类」开始构建
      </p>

      <div class="space-y-2">
        <Label class="text-xs font-semibold text-foreground">考点标签</Label>
        <div v-for="(_, ti) in localTaxonomy.tags" :key="ti" class="flex items-center gap-2">
          <Input v-model="localTaxonomy.tags[ti]" class="text-sm" placeholder="如 接口测试、Redis、系统设计" />
          <Button variant="ghost" size="icon-sm" aria-label="删除标签" @click="removeTag(ti)" class="text-muted-foreground/50 hover:text-red-500">
            <Trash2 class="size-3.5" />
          </Button>
        </div>
        <Button variant="link" size="sm" @click="addTag" class="text-xs text-primary h-auto p-0 no-underline hover:no-underline">
          <Plus class="size-3 mr-1" />
          添加标签
        </Button>
      </div>

      <!-- Action buttons -->
      <div class="flex gap-2 pt-2">
        <Button variant="outline" size="sm" @click="onSaveSystem"
          class="flex-1 border-primary-200 dark:border-primary-800 text-primary-700 dark:text-primary-400">
          <Save class="size-3.5 mr-1.5" />
          保存系统分类
        </Button>
      </div>
    </div>

    <!-- Card 3: 题库操作 (Danger Zone) -->
    <div v-if="adminTab === 'taxonomy'" class="rounded-xl border border-red-200 dark:border-red-800/50 bg-red-50/50 dark:bg-red-900/10 p-6 space-y-4">
      <h3 class="text-xs font-bold text-red-600 dark:text-red-400 uppercase tracking-wider flex items-center gap-2">
        <AlertTriangle class="size-4" />
        题库操作
      </h3>
      <p class="text-xs text-muted-foreground leading-relaxed">
        基于现有分类重新聚类，不会重新打标。仅在题库聚类结果需要修复时使用。
      </p>
      <Button variant="destructive" size="sm" @click="onRebuild" :disabled="isBuilding">
        {{ isBuilding ? '聚类中...' : '重新聚类题库' }}
      </Button>
    </div>

    <!-- 聚合质量：审查清单 / AI 助手（子分段切换） -->
    <div v-else-if="adminTab === 'quality'" class="rounded-xl border bg-card p-6">
      <div class="mb-4">
        <h3 class="text-xs font-bold text-primary uppercase tracking-wider flex items-center gap-2">
          <ClipboardCheck class="size-4" />
          聚合质量审查
        </h3>
        <p class="text-xs text-muted-foreground mt-1">
          每周自动审查公共题库聚类质量（误合并 / 重复问法 / 代表题不规范），
          由 LLM 给出修改建议，管理员审批后执行。记录永久保留可审计。
        </p>
      </div>
      <div class="mb-3 flex items-center gap-1.5 rounded-lg border border-border p-1 w-fit">
        <button
          class="rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
          :class="qualitySubTab === 'list' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'"
          @click="qualitySubTab = 'list'"
        >
          审查清单
        </button>
        <button
          class="rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
          :class="qualitySubTab === 'assistant' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'"
          @click="qualitySubTab = 'assistant'"
        >
          AI 助手
        </button>
        <button
          class="rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
          :class="qualitySubTab === 'health' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'"
          @click="qualitySubTab = 'health'"
        >
          来源健康
        </button>
      </div>
      <SettingsQuality v-if="qualitySubTab === 'list'" />
      <SettingsQualityAssistant v-else-if="qualitySubTab === 'assistant'" />
      <SettingsSourceHealth v-else />
    </div>

    <!-- 模型配置 -->
    <div v-else-if="adminTab === 'model'" class="rounded-xl border bg-card p-6">
      <SettingsGlobalModel />
    </div>

    <!-- 公共联网搜索配置 -->
    <SettingsPublicSearch v-else-if="adminTab === 'search'" />
  </div>
</template>
