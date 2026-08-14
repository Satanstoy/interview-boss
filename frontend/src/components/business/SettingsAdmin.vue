<script setup>
import { ref, reactive, watch, onMounted } from 'vue'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import { FolderTree, AlertTriangle, ChevronRight, Plus, Trash2, Save, Share2, Globe, ClipboardCheck } from '@lucide/vue'
import { savePersonalTaxonomy, shareTaxonomy, fetchPublicTaxonomies, deletePublicTaxonomy, fetchProfile } from '@/services/profileApi.js'
import SettingsQuality from './SettingsQuality.vue'
import SettingsQualityAssistant from './SettingsQualityAssistant.vue'
import SettingsSourceHealth from './SettingsSourceHealth.vue'
import SettingsGlobalModel from './SettingsGlobalModel.vue'
import SettingsPublicSearch from './SettingsPublicSearch.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import AppTooltip from '@/components/common/AppTooltip.vue'

const adminTabs = [
  { id: 'taxonomy', label: '分类管理' },
  { id: 'quality', label: '聚合质量' },
  { id: 'model', label: '模型配置' },
  { id: 'search', label: '联网搜索' },
]
const adminTab = ref('taxonomy')
const qualitySubTab = ref('list')

const props = defineProps({
  taxonomy: { type: Object, default: () => ({ categories: [] }) },
  isBuilding: { type: Boolean, default: false },
  isAdmin: { type: Boolean, default: false },
})

const emit = defineEmits(['build-master-bank', 'taxonomy-updated'])
const { success: toastSuccess, error: toastError, warning: toastWarning } = useToast()
const { confirm: showConfirm } = useConfirm()

// Deep-copy taxonomy to avoid prop mutation
const localTaxonomy = reactive({
  categories: JSON.parse(JSON.stringify(props.taxonomy.categories || []))
})

onMounted(async () => {
  try {
    const profile = await fetchProfile()
    if (profile?.taxonomy_config?.categories) {
      localTaxonomy.categories = JSON.parse(JSON.stringify(profile.taxonomy_config.categories))
    }
  } catch (e) {
    console.error('Failed to load taxonomy', e)
  }
})

// ── Card 1: 分类体系管理 ──
const publicTaxonomies = ref([])
const publicTaxonomiesLoading = ref(false)
const showPublicTaxonomies = ref(false)

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

const onSavePersonal = async () => {
  const valid = getValidCategories()
  if (!valid.length) {
    toastWarning('没有可保存的分类')
    return
  }
  try {
    await savePersonalTaxonomy(valid)
    toastSuccess('已保存为个人分类')
  } catch (e) {
    toastError(`保存失败: ${e.message}`)
  }
}

const onShare = async () => {
  const valid = getValidCategories()
  if (!valid.length) {
    toastWarning('没有可分享的分类')
    return
  }
  try {
    const result = await savePersonalTaxonomy(valid)
    if (result.taxonomy?.id) {
      await shareTaxonomy(result.taxonomy.id)
      toastSuccess('分类已分享')
    }
  } catch (e) {
    toastError(`分享失败: ${e.message}`)
  }
}

const onShowPublic = async () => {
  showPublicTaxonomies.value = true
  publicTaxonomiesLoading.value = true
  try {
    const data = await fetchPublicTaxonomies()
    publicTaxonomies.value = data.taxonomies || []
  } catch (e) {
    toastError(`获取公开分类失败: ${e.message}`)
  } finally {
    publicTaxonomiesLoading.value = false
  }
}

const onUsePublic = async (tax) => {
  const categories = tax.categories.map(c => ({ ...c, _open: false }))
  localTaxonomy.categories = categories
  const valid = categories
    .filter(c => c.cat1?.trim())
    .map(c => ({
      cat1: c.cat1.trim(),
      children: (c.children || []).filter(Boolean),
    }))
  showPublicTaxonomies.value = false
  if (!valid.length) {
    toastWarning('该公开分类没有有效分类，无法使用')
    return
  }
  try {
    await savePersonalTaxonomy(valid)
    emit('taxonomy-updated')
    toastSuccess(`已加载并保存"${tax.position_name}"的分类`)
  } catch (e) {
    toastError(`加载分类失败: ${e.message}`)
  }
}

const onDeletePublic = async (tax) => {
  if (!await showConfirm(`确定要删除"${tax.position_name}"的公开分类吗？`)) return
  try {
    await deletePublicTaxonomy(tax.id)
    publicTaxonomies.value = publicTaxonomies.value.filter(t => t.id !== tax.id)
    toastSuccess('已删除公开分类')
  } catch (e) {
    toastError(`删除失败: ${e.message}`)
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
      <p class="text-sm text-muted-foreground mt-1">管理系统级配置（仅管理员可见）</p>
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
          分类体系管理
        </h3>
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

      <!-- Action buttons -->
      <div class="flex gap-2 pt-2">
        <Button variant="outline" size="sm" @click="onSavePersonal"
          class="flex-1 border-primary-200 dark:border-primary-800 text-primary-700 dark:text-primary-400">
          <Save class="size-3.5 mr-1.5" />
          保存为个人分类
        </Button>
        <Button variant="outline" size="sm" @click="onShare"
          class="flex-1 border-primary-200 dark:border-primary-800 text-primary-700 dark:text-primary-400">
          <Share2 class="size-3.5 mr-1.5" />
          分享分类
        </Button>
        <Button variant="outline" size="sm" @click="onShowPublic" class="flex-1">
          <Globe class="size-3.5 mr-1.5" />
          使用公开分类
        </Button>
      </div>
    </div>

    <!-- Public taxonomy dialog -->
    <Teleport to="body">
      <div v-if="showPublicTaxonomies" class="fixed inset-0 z-50 flex items-center justify-center">
        <!-- Backdrop -->
        <div class="fixed inset-0 bg-black/50" @click="showPublicTaxonomies = false" />
        <!-- Content -->
        <div class="relative z-50 w-full max-w-2xl max-h-[80vh] bg-card rounded-xl border shadow-lg flex flex-col mx-4">
          <div class="px-6 py-4 border-b">
            <h3 class="text-lg font-semibold text-foreground">公开分类体系</h3>
            <p class="text-sm text-muted-foreground mt-1">选择一个分类体系应用到当前岗位</p>
          </div>
          <div class="flex-1 overflow-y-auto p-6">
            <div v-if="publicTaxonomiesLoading" class="flex items-center justify-center py-8">
              <div class="size-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            </div>
            <div v-else-if="!publicTaxonomies.length" class="text-center py-8 text-muted-foreground text-sm">
              暂无公开分类
            </div>
            <div v-else class="flex flex-col gap-3">
              <div v-for="tax in publicTaxonomies" :key="tax.id"
                class="rounded-xl border border-border p-4 hover:border-primary/40 dark:hover:border-primary/50 transition cursor-pointer"
                @click="onUsePublic(tax)">
                <div class="flex items-center justify-between mb-2">
                  <h4 class="text-sm font-semibold text-foreground">{{ tax.position_name }}</h4>
                  <div class="flex items-center gap-2">
                    <span class="text-xs text-muted-foreground">分享者: {{ tax.owner_name || '匿名' }}</span>
                    <AppTooltip v-if="isAdmin" text="删除此公开分类">
                      <Button variant="ghost" size="icon-sm" aria-label="删除此公开分类"
                        @click.stop="onDeletePublic(tax)"
                        class="text-red-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors duration-200">
                        <Trash2 class="size-4" />
                      </Button>
                    </AppTooltip>
                  </div>
                </div>
                <div class="flex flex-wrap gap-1.5">
                  <span v-for="(c, i) in (tax.categories || [])" :key="i"
                    class="text-xs bg-muted px-2 py-0.5 rounded text-muted-foreground">
                    {{ c.cat1 }}
                  </span>
                </div>
              </div>
            </div>
          </div>
          <div class="px-6 py-4 border-t flex justify-end">
            <Button variant="outline" size="sm" @click="showPublicTaxonomies = false">关闭</Button>
          </div>
        </div>
      </div>
    </Teleport>

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
