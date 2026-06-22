<template>
  <div class="w-full space-y-8">
    <div>
      <h3 class="text-lg font-semibold text-foreground">个人信息</h3>
      <p class="text-sm text-muted-foreground mt-1">管理你的账户信息和偏好设置</p>
    </div>

    <!-- ═══ Card 1: 邮箱绑定 ═══ -->
    <Card>
      <CardHeader>
        <CardTitle class="text-base flex items-center gap-2">
          <Mail class="size-4 text-muted-foreground" />
          邮箱绑定
        </CardTitle>
        <CardDescription>绑定邮箱后可使用邮箱验证码登录</CardDescription>
      </CardHeader>
      <CardContent>
        <!-- 已绑定 -->
        <div v-if="myEmail && !emailBinding.editing" class="flex items-center gap-3">
          <span class="text-sm font-mono text-foreground">{{ myEmail }}</span>
          <Badge variant="outline" class="border-emerald-300 dark:border-emerald-700 text-emerald-600 dark:text-emerald-400">
            已绑定
          </Badge>
          <Button variant="ghost" size="sm" @click="startEmailBinding" class="ml-auto">
            更换
          </Button>
        </div>

        <!-- 未绑定 -->
        <div v-else-if="!emailBinding.editing" class="flex items-center gap-3">
          <span class="text-sm text-muted-foreground">未绑定邮箱</span>
          <Button variant="outline" size="sm" @click="startEmailBinding" class="ml-auto">
            立即绑定
          </Button>
        </div>

        <!-- 绑定表单 -->
        <div v-if="emailBinding.editing" class="flex flex-col gap-3">
          <div>
            <Label class="text-xs font-semibold text-muted-foreground mb-1.5">邮箱地址</Label>
            <div class="flex gap-2">
              <Input
                v-model="emailBinding.email"
                type="email"
                placeholder="your@email.com"
                class="flex-1"
              />
              <Button
                variant="outline"
                size="sm"
                @click="onSendBindCode"
                :disabled="emailBinding.cooldown > 0 || !emailBinding.email.trim()"
                class="whitespace-nowrap"
              >
                {{ emailBinding.cooldown > 0 ? `${emailBinding.cooldown}s` : '发送验证码' }}
              </Button>
            </div>
          </div>
          <div>
            <Label class="text-xs font-semibold text-muted-foreground mb-1.5">验证码</Label>
            <Input
              v-model="emailBinding.code"
              type="text"
              placeholder="6位数字"
              maxlength="6"
            />
          </div>
          <div class="flex gap-2 pt-1">
            <Button
              size="sm"
              @click="onConfirmBindEmail"
              :disabled="emailBinding.saving || !emailBinding.code.trim()"
            >
              {{ emailBinding.saving ? '绑定中...' : '确认绑定' }}
            </Button>
            <Button variant="outline" size="sm" @click="emailBinding.editing = false">
              取消
            </Button>
          </div>
          <p v-if="emailBinding.error" class="text-xs text-destructive">{{ emailBinding.error }}</p>
        </div>
      </CardContent>
    </Card>

    <!-- ═══ Card 2: 简历管理 ═══ -->
    <Card>
      <CardHeader>
        <CardTitle class="text-base flex items-center gap-2">
          <FileText class="size-4 text-muted-foreground" />
          简历管理
        </CardTitle>
        <CardDescription>上传简历后，模拟面试时可自动使用</CardDescription>
      </CardHeader>
      <CardContent>
        <!-- 已上传 -->
        <div v-if="resumeInfo" class="flex items-center gap-3">
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-foreground truncate">{{ resumeInfo.filename }}</p>
            <p class="text-xs text-muted-foreground">上传于 {{ formatDate(resumeInfo.created_at) }}</p>
          </div>
          <label class="cursor-pointer">
            <Button variant="ghost" size="sm" as="span">
              重新上传
            </Button>
            <input type="file" accept=".pdf" class="hidden" @change="onResumeFileSelect" />
          </label>
          <Button variant="ghost" size="sm" @click="onDeleteResume" class="text-destructive hover:text-destructive">
            删除
          </Button>
        </div>

        <!-- 未上传 -->
        <div v-else>
          <div
            class="border-2 border-dashed border-border rounded-lg p-6 text-center hover:border-muted-foreground/50 transition cursor-pointer"
            :class="resumeDragover ? 'border-primary bg-primary/5' : ''"
            @dragover.prevent="resumeDragover = true"
            @dragleave="resumeDragover = false"
            @drop.prevent="onResumeDrop"
            @click="$refs.resumeInput.click()"
          >
            <input ref="resumeInput" type="file" accept=".pdf" class="hidden" @change="onResumeFileSelect" />
            <Upload class="size-8 mx-auto text-muted-foreground/50 mb-2" />
            <p class="text-sm text-muted-foreground">点击上传或拖拽 PDF 简历</p>
            <p class="text-xs text-muted-foreground/60 mt-1">仅支持 PDF 格式</p>
          </div>
        </div>

        <!-- 上传进度 -->
        <div v-if="resumeUploading" class="flex items-center gap-2 text-xs text-primary mt-3">
          <Loader2 class="size-4 animate-spin" />
          上传解析中...
        </div>
        <p v-if="resumeError" class="text-xs text-destructive mt-2">{{ resumeError }}</p>
      </CardContent>
    </Card>

    <!-- ═══ Card 3: 学习进度 ═══ -->
    <Card>
      <CardHeader>
        <CardTitle class="text-base flex items-center gap-2">
          <BarChart3 class="size-4 text-muted-foreground" />
          学习进度
        </CardTitle>
        <CardDescription>你的练习完成情况和各难度得分</CardDescription>
      </CardHeader>
      <CardContent>
        <!-- 总进度 -->
        <div class="mb-4">
          <div class="flex items-center justify-between mb-2">
            <span class="text-sm text-foreground">
              <span class="font-semibold">{{ practiceStats.practiced_questions || 0 }}</span>
              <span class="text-muted-foreground">/{{ practiceStats.total_questions || 0 }} 题</span>
            </span>
            <span class="text-sm font-medium text-muted-foreground">{{ progressPercent }}%</span>
          </div>
          <div class="w-full bg-secondary rounded-full h-2 overflow-hidden">
            <div
              class="h-full rounded-full bg-primary transition-all duration-700 ease-out"
              :style="{ width: progressPercent + '%' }"
            ></div>
          </div>
        </div>

        <Separator class="mb-4" />

        <!-- 分难度进度 -->
        <div class="flex flex-col gap-3">
          <div v-for="diff in diffOrder" :key="diff">
            <div class="flex items-center justify-between text-xs mb-1.5">
              <span class="font-semibold" :class="diffColor(diff)">{{ diffLabel(diff) }}</span>
              <span class="text-muted-foreground tabular-nums">
                {{ (practiceStats.by_difficulty?.[diff]?.practiced || 0) }}/{{ (practiceStats.by_difficulty?.[diff]?.total || 0) }}
                <span v-if="practiceStats.by_difficulty?.[diff]?.avg_score" class="ml-1 font-bold" :class="scoreColor(practiceStats.by_difficulty[diff].avg_score)">
                  {{ practiceStats.by_difficulty[diff].avg_score }}分
                </span>
              </span>
            </div>
            <div class="w-full bg-secondary rounded-full h-1.5 overflow-hidden">
              <div
                class="h-full rounded-full transition-all duration-700 ease-out"
                :class="diffBarColor(diff)"
                :style="{ width: diffProgress(diff) + '%' }"
              ></div>
            </div>
          </div>
        </div>

        <!-- 平均分 -->
        <div v-if="practiceStats.avg_score" class="mt-4 flex items-center gap-2 text-xs">
          <span class="text-muted-foreground">平均最高分</span>
          <span class="font-bold px-2.5 py-0.5 rounded-md" :class="scoreBadgeClass(practiceStats.avg_score)">
            {{ practiceStats.avg_score }}
          </span>
        </div>
      </CardContent>
    </Card>

    <!-- ═══ Card 4: 题库模式 ═══ -->
    <Card>
      <CardHeader>
        <CardTitle class="text-base flex items-center gap-2">
          <Database class="size-4 text-muted-foreground" />
          题库模式
        </CardTitle>
        <CardDescription>选择题目来源方式</CardDescription>
      </CardHeader>
      <CardContent>
        <div class="flex flex-col gap-2">
          <button
            v-for="opt in bankModeOptions"
            :key="opt.value"
            @click="onBankModeChange(opt.value)"
            class="flex items-start gap-3 p-3 rounded-lg border text-left transition-all duration-200"
            :class="bankMode === opt.value
              ? 'border-primary bg-primary/5 ring-1 ring-primary/20'
              : 'border-border hover:border-muted-foreground/50 hover:bg-muted/50'"
          >
            <span
              class="mt-0.5 size-4 rounded-full border-2 flex items-center justify-center shrink-0 transition-colors"
              :class="bankMode === opt.value ? 'border-primary' : 'border-muted-foreground/40'"
            >
              <span v-if="bankMode === opt.value" class="size-2 rounded-full bg-primary"></span>
            </span>
            <div>
              <p class="text-sm font-medium text-foreground">{{ opt.label }}</p>
              <p class="text-xs text-muted-foreground mt-0.5">{{ opt.desc }}</p>
            </div>
          </button>
        </div>
      </CardContent>
    </Card>

    <!-- ═══ Card 5: 招聘季 ═══ -->
    <div class="rounded-xl border bg-card p-6 space-y-4">
      <div class="flex items-center gap-2">
        <Calendar class="size-4 text-muted-foreground" />
        <h4 class="text-sm font-semibold text-foreground">招聘季</h4>
      </div>
      <p class="text-xs text-muted-foreground">选择当前活跃的招聘季节</p>
      <Select :model-value="activeSeason" @update:model-value="$emit('update:activeSeason', $event)">
        <SelectTrigger class="w-full text-sm">
          <SelectValue placeholder="选择招聘季" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="s in availableSeasons" :key="s" :value="s">{{ s }}</SelectItem>
        </SelectContent>
      </Select>
      <div class="flex gap-2">
        <Input v-model="newSeasonInput" placeholder="新增招聘季" class="flex-1 text-sm" @keyup.enter="addSeason" />
        <Button variant="outline" size="sm" @click="addSeason">添加</Button>
      </div>
    </div>

    <!-- ═══ Card 6: 外观偏好 ═══ -->
    <Card>
      <CardHeader>
        <CardTitle class="text-base flex items-center gap-2">
          <Palette class="size-4 text-muted-foreground" />
          外观偏好
        </CardTitle>
        <CardDescription>自定义界面显示效果</CardDescription>
      </CardHeader>
      <CardContent class="flex flex-col gap-6">
        <!-- 主题切换 -->
        <div>
          <Label class="text-sm font-medium text-foreground mb-3 block">主题</Label>
          <div class="flex gap-2">
            <button
              v-for="opt in themeOptions"
              :key="opt.value"
              @click="setTheme(opt.value)"
              class="flex items-center gap-2 px-4 py-2.5 rounded-lg border text-sm font-medium transition-all duration-200"
              :class="currentTheme === opt.value
                ? 'border-primary bg-primary/5 text-primary ring-1 ring-primary/20'
                : 'border-border text-muted-foreground hover:border-muted-foreground/50 hover:text-foreground'"
            >
              <component :is="opt.icon" class="size-4" />
              {{ opt.label }}
            </button>
          </div>
        </div>

        <Separator />

        <!-- 侧栏默认状态 -->
        <div class="flex items-center justify-between">
          <div>
            <Label class="text-sm font-medium text-foreground">默认收起侧栏</Label>
            <p class="text-xs text-muted-foreground mt-0.5">页面加载时侧边栏的状态</p>
          </div>
          <button
            @click="toggleSidebarDefault"
            class="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            :class="sidebarCollapsed ? 'bg-primary' : 'bg-input'"
            role="switch"
            :aria-checked="sidebarCollapsed"
          >
            <span
              class="pointer-events-none block size-5 rounded-full bg-background shadow-lg ring-0 transition-transform duration-200"
              :class="sidebarCollapsed ? 'translate-x-5' : 'translate-x-0'"
            ></span>
          </button>
        </div>
      </CardContent>
    </Card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onBeforeUnmount, markRaw } from 'vue'
import { getMyEmail, sendBindCode, bindEmail, authUpdateBankMode } from '@/services/authApi.js'
import { uploadResume, getResume, deleteResume } from '@/services/resumeApi.js'
import { useTheme } from '@/composables/useTheme.js'
import { useToast } from '@/composables/useNotification.js'

// shadcn components
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

// Lucide icons
import {
  Mail, FileText, Upload, Loader2, BarChart3, Database, Palette,
  Sun, Moon, Monitor, Calendar
} from '@lucide/vue'

const toast = useToast()
const { isDark, toggleDark } = useTheme()

const props = defineProps({
  practiceStats: { type: Object, default: () => ({}) },
  bankMode: { type: String, default: 'public' },
  displayUser: { type: Object, default: null },
  activeSeason: { type: String, default: '' },
  availableSeasons: { type: Array, default: () => [] },
})

const emit = defineEmits(['bank-mode-changed', 'profile-updated', 'sidebar-collapsed-changed', 'update:activeSeason'])

// ── 邮箱绑定 ──
const myEmail = ref('')
const emailBinding = reactive({
  editing: false,
  email: '',
  code: '',
  cooldown: 0,
  saving: false,
  error: ''
})
let emailCooldownTimer = null

const loadMyEmail = async () => {
  try {
    const data = await getMyEmail()
    myEmail.value = data.email || ''
  } catch { /* ignore */ }
}

const startEmailBinding = () => {
  emailBinding.editing = true
  emailBinding.email = ''
  emailBinding.code = ''
  emailBinding.error = ''
}

const onSendBindCode = async () => {
  if (emailBinding.cooldown > 0 || !emailBinding.email.trim()) return
  emailBinding.error = ''
  try {
    await sendBindCode(emailBinding.email.trim())
    emailBinding.cooldown = 60
    emailCooldownTimer = setInterval(() => {
      emailBinding.cooldown--
      if (emailBinding.cooldown <= 0) {
        clearInterval(emailCooldownTimer)
        emailCooldownTimer = null
      }
    }, 1000)
  } catch (e) {
    emailBinding.error = e.message || '发送失败'
  }
}

const onConfirmBindEmail = async () => {
  if (emailBinding.saving || !emailBinding.code.trim()) return
  emailBinding.error = ''
  emailBinding.saving = true
  try {
    const result = await bindEmail(emailBinding.email.trim(), emailBinding.code)
    myEmail.value = result.email
    emailBinding.editing = false
    toast.success('邮箱绑定成功')
    emit('profile-updated')
  } catch (e) {
    emailBinding.error = e.message || '绑定失败'
  } finally {
    emailBinding.saving = false
  }
}

onBeforeUnmount(() => {
  if (emailCooldownTimer) clearInterval(emailCooldownTimer)
})

// ── 简历管理 ──
const resumeInfo = ref(null)
const resumeUploading = ref(false)
const resumeError = ref('')
const resumeDragover = ref(false)

const loadResume = async () => {
  try {
    const data = await getResume()
    resumeInfo.value = data.has_resume ? data.resume : null
  } catch { /* ignore */ }
}

const onResumeFileSelect = async (e) => {
  const file = e.target.files?.[0]
  if (!file) return
  await doUploadResume(file)
}

const onResumeDrop = async (e) => {
  resumeDragover.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file && file.type === 'application/pdf') {
    await doUploadResume(file)
  }
}

const doUploadResume = async (file) => {
  resumeError.value = ''
  resumeUploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)
    await uploadResume(formData)
    await loadResume()
    toast.success('简历上传成功')
    emit('profile-updated')
  } catch (e) {
    resumeError.value = e.message || '上传失败'
  } finally {
    resumeUploading.value = false
  }
}

const onDeleteResume = async () => {
  try {
    await deleteResume()
    resumeInfo.value = null
    toast.success('简历已删除')
    emit('profile-updated')
  } catch (e) {
    resumeError.value = e.message || '删除失败'
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return dateStr.replace('T', ' ').slice(0, 16)
}

// ── 学习进度 ──
const diffOrder = ['L1-基础', 'L2-中等', 'L3-困难']

const progressPercent = computed(() => {
  const s = props.practiceStats
  if (!s.total_questions) return 0
  return Math.round((s.practiced_questions / s.total_questions) * 100)
})

const diffLabel = (diff) => {
  if (diff.includes('L1')) return 'L1 基础'
  if (diff.includes('L2')) return 'L2 中等'
  if (diff.includes('L3')) return 'L3 困难'
  return diff
}

const diffProgress = (diff) => {
  const d = props.practiceStats.by_difficulty?.[diff]
  if (!d || !d.total) return 0
  return Math.round((d.practiced / d.total) * 100)
}

const diffColor = (diff) => {
  if (diff.includes('L1')) return 'text-emerald-600 dark:text-emerald-400'
  if (diff.includes('L2')) return 'text-amber-600 dark:text-amber-400'
  if (diff.includes('L3')) return 'text-red-600 dark:text-red-400'
  return 'text-muted-foreground'
}

const diffBarColor = (diff) => {
  if (diff.includes('L1')) return 'bg-emerald-500'
  if (diff.includes('L2')) return 'bg-amber-500'
  if (diff.includes('L3')) return 'bg-red-500'
  return 'bg-muted-foreground'
}

const scoreColor = (score) => {
  if (score >= 80) return 'text-emerald-600 dark:text-emerald-400'
  if (score >= 60) return 'text-amber-600 dark:text-amber-400'
  return 'text-red-600 dark:text-red-400'
}

const scoreBadgeClass = (score) => {
  if (score >= 80) return 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
  if (score >= 60) return 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'
  return 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400'
}

// ── 题库模式 ──
const bankModeOptions = [
  { value: 'public', label: '公共题库', desc: '使用系统内置的公共面试题库' },
  { value: 'personal', label: '个人题库', desc: '使用你自己创建和导入的面试题' },
  { value: 'mixed', label: '混用', desc: '同时展示公共题库和个人题库的题目' }
]

// ── 招聘季 ──
const newSeasonInput = ref('')
const addSeason = () => {
  if (!newSeasonInput.value.trim()) return
  emit('update:activeSeason', newSeasonInput.value.trim())
  newSeasonInput.value = ''
}

const onBankModeChange = async (mode) => {
  if (mode === props.bankMode) return
  try {
    await authUpdateBankMode(mode)
    emit('bank-mode-changed', mode)
    toast.success('题库模式已切换')
  } catch (e) {
    toast.error(`切换失败: ${e.message}`)
  }
}

// ── 外观偏好 ──
const themeOptions = [
  { value: 'light', label: '亮色', icon: markRaw(Sun) },
  { value: 'dark', label: '暗色', icon: markRaw(Moon) },
  { value: 'system', label: '跟随系统', icon: markRaw(Monitor) }
]

const currentTheme = ref('light')

// 初始化主题状态
const initTheme = () => {
  const stored = localStorage.getItem('interviewboss-theme')
  if (!stored) {
    // 无存储值 = 跟随系统
    currentTheme.value = 'system'
  } else if (stored === 'dark') {
    currentTheme.value = 'dark'
  } else {
    currentTheme.value = 'light'
  }
}

const setTheme = (value) => {
  currentTheme.value = value
  if (value === 'system') {
    // 跟随系统：移除手动设置的 class，让 @media 生效
    localStorage.removeItem('interviewboss-theme')
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    toggleDark(prefersDark)
  } else {
    toggleDark(value === 'dark')
  }
}

// ── 侧栏默认状态 ──
const sidebarCollapsed = ref(localStorage.getItem('sidebar-collapsed') === 'true')

const toggleSidebarDefault = () => {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('sidebar-collapsed', String(sidebarCollapsed.value))
  emit('sidebar-collapsed-changed', sidebarCollapsed.value)
}

// ── 初始化 ──
watch(() => props.displayUser, () => {
  loadMyEmail()
  loadResume()
}, { immediate: true })

initTheme()
</script>
