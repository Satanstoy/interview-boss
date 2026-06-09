<template>
  <teleport to="body">
    <transition name="fade">
      <div v-if="visible" class="fixed inset-0 z-[100] flex items-start justify-center pt-[8vh] px-4">
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="emit('close')"></div>
        <div class="relative bg-white dark:bg-surface-800 rounded-3xl shadow-2xl w-full max-w-md max-h-[84vh] flex flex-col overflow-hidden animate-slide-up">
          <!-- Header -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-surface-100 dark:border-ink-700 shrink-0 bg-gradient-to-r from-primary-50/50 to-accent-50/30 dark:from-primary-900/20 dark:to-accent-900/10">
            <div class="flex items-center gap-3">
              <div class="w-9 h-9 rounded-xl bg-gradient-brand flex items-center justify-center">
                <svg class="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>
              </div>
              <h2 class="text-lg font-bold text-ink-800 dark:text-ink-100">个人信息</h2>
            </div>
            <button @click="emit('close')" class="p-2 rounded-xl text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-100 dark:hover:bg-ink-700 transition">
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <!-- Body -->
          <div class="flex-1 overflow-y-auto custom-scrollbar px-6 py-5 space-y-5">

            <!-- 基本信息 -->
            <div class="space-y-3 p-4 rounded-2xl border border-surface-200 dark:border-ink-700 bg-surface-50 dark:bg-surface-900">
              <div class="flex items-center gap-3">
                <div class="w-12 h-12 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center text-lg font-bold text-white">
                  {{ user?.username?.[0]?.toUpperCase() || '?' }}
                </div>
                <div>
                  <p class="text-sm font-bold text-ink-800 dark:text-ink-100">{{ user?.username }}</p>
                  <p class="text-xs text-ink-400 dark:text-ink-500 flex items-center gap-1">
                    <span class="w-1.5 h-1.5 rounded-full" :class="user?.is_admin ? 'bg-amber-400' : 'bg-emerald-400'"></span>
                    {{ user?.is_admin ? '管理员' : '普通用户' }}
                  </p>
                </div>
              </div>
            </div>

            <!-- 邮箱绑定 -->
            <div class="space-y-3.5 p-4 rounded-2xl border border-primary-100 dark:border-primary-800 bg-gradient-to-b from-primary-50/50 to-white dark:from-primary-900/20 dark:to-surface-800">
              <h3 class="text-xs font-bold text-primary-600 dark:text-primary-400 uppercase tracking-wider flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
                邮箱绑定
              </h3>

              <!-- 已绑定 -->
              <div v-if="myEmail && !emailBinding.editing" class="flex items-center gap-3">
                <span class="text-sm text-ink-700 dark:text-ink-200 font-mono">{{ myEmail }}</span>
                <span class="text-xs text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 px-2 py-0.5 rounded-lg">已绑定</span>
                <button @click="startEmailBinding" class="ml-auto text-xs text-primary-600 dark:text-primary-400 hover:text-primary-800 dark:hover:text-primary-300 font-medium">更换</button>
              </div>

              <!-- 未绑定 -->
              <div v-if="!myEmail && !emailBinding.editing" class="flex items-center gap-3">
                <span class="text-sm text-ink-400 dark:text-ink-500">未绑定邮箱</span>
                <button @click="startEmailBinding" class="ml-auto text-xs bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 px-3 py-1.5 rounded-lg hover:bg-primary-100 dark:hover:bg-primary-900/50 transition font-medium border border-primary-200 dark:border-primary-800">立即绑定</button>
              </div>

              <!-- 绑定表单 -->
              <div v-if="emailBinding.editing" class="space-y-3">
                <div>
                  <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">邮箱地址</label>
                  <div class="flex gap-2">
                    <input v-model="emailBinding.email" type="email" placeholder="your@email.com" class="flex-1 border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm bg-surface-50 dark:bg-surface-900 text-ink-800 dark:text-ink-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200" />
                    <button @click="onSendBindCode" :disabled="emailBinding.cooldown > 0 || !emailBinding.email.trim()" class="px-3 py-2.5 text-xs font-medium rounded-xl border border-primary-200 dark:border-primary-800 text-primary-600 dark:text-primary-400 hover:bg-primary-50 dark:hover:bg-primary-900/30 transition disabled:opacity-50 whitespace-nowrap">
                      {{ emailBinding.cooldown > 0 ? `${emailBinding.cooldown}s` : '发送验证码' }}
                    </button>
                  </div>
                </div>
                <div>
                  <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">验证码</label>
                  <input v-model="emailBinding.code" type="text" placeholder="6位数字" maxlength="6" class="w-full border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm bg-surface-50 dark:bg-surface-900 text-ink-800 dark:text-ink-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200" />
                </div>
                <div class="flex gap-2 pt-1">
                  <button @click="onConfirmBindEmail" :disabled="emailBinding.saving || !emailBinding.code.trim()" class="btn-primary px-4 text-sm">
                    {{ emailBinding.saving ? '绑定中...' : '确认绑定' }}
                  </button>
                  <button @click="emailBinding.editing = false" class="btn-secondary px-4 text-sm">取消</button>
                </div>
                <p v-if="emailBinding.error" class="text-xs text-red-500 dark:text-red-400">{{ emailBinding.error }}</p>
              </div>

              <p class="text-xs text-ink-400 dark:text-ink-500">绑定邮箱后可使用邮箱验证码登录</p>
            </div>

            <!-- 简历管理 -->
            <div class="space-y-3.5 p-4 rounded-2xl border border-emerald-100 dark:border-emerald-800 bg-gradient-to-b from-emerald-50/50 to-white dark:from-emerald-900/20 dark:to-surface-800">
              <h3 class="text-xs font-bold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                简历管理
              </h3>

              <!-- 已有简历 -->
              <div v-if="resumeInfo" class="flex items-center gap-3">
                <div class="flex-1 min-w-0">
                  <p class="text-sm font-medium text-ink-700 dark:text-ink-200 truncate">{{ resumeInfo.filename }}</p>
                  <p class="text-xs text-ink-400 dark:text-ink-500">上传于 {{ formatDate(resumeInfo.created_at) }}</p>
                </div>
                <label class="text-xs text-primary-600 dark:text-primary-400 hover:text-primary-800 dark:hover:text-primary-300 font-medium cursor-pointer whitespace-nowrap">
                  重新上传
                  <input type="file" accept=".pdf" class="hidden" @change="onResumeFileSelect" />
                </label>
                <button @click="onDeleteResume" class="text-xs text-red-500 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 font-medium">删除</button>
              </div>

              <!-- 无简历 - 上传区域 -->
              <div v-else>
                <div
                  class="border-2 border-dashed border-surface-300 dark:border-ink-600 rounded-xl p-4 text-center hover:border-emerald-400 dark:hover:border-emerald-500 transition cursor-pointer"
                  @dragover.prevent="resumeDragover = true"
                  @dragleave="resumeDragover = false"
                  @drop.prevent="onResumeDrop"
                  :class="resumeDragover ? 'border-emerald-400 dark:border-emerald-500 bg-emerald-50/30 dark:bg-emerald-900/10' : ''"
                  @click="$refs.resumeInput.click()"
                >
                  <input ref="resumeInput" type="file" accept=".pdf" class="hidden" @change="onResumeFileSelect" />
                  <svg class="w-8 h-8 mx-auto text-ink-300 dark:text-ink-600 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/></svg>
                  <div class="text-xs text-ink-400 dark:text-ink-500">点击上传或拖拽 PDF 简历</div>
                  <div class="text-[10px] text-ink-300 dark:text-ink-600 mt-1">上传后，模拟面试时可自动使用</div>
                </div>
              </div>

              <!-- 上传进度 -->
              <div v-if="resumeUploading" class="flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400">
                <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                上传解析中...
              </div>
              <p v-if="resumeError" class="text-xs text-red-500 dark:text-red-400">{{ resumeError }}</p>
            </div>

            <!-- Learning Progress -->
            <div class="space-y-3.5 p-4 rounded-2xl border border-primary-100 dark:border-primary-800 bg-gradient-to-b from-primary-50/50 to-white dark:from-primary-900/20 dark:to-surface-800">
              <h3 class="text-xs font-bold text-primary-600 dark:text-primary-400 uppercase tracking-wider flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
                学习进度
              </h3>

              <div class="flex items-center justify-between mb-2">
                <span class="text-xs text-ink-400 dark:text-ink-500 tabular-nums">
                  <span class="text-base font-bold text-ink-900 dark:text-ink-100">{{ practiceStats.practiced_questions || 0 }}</span>
                  <span>/{{ practiceStats.total_questions || 0 }} 题</span>
                </span>
              </div>

              <!-- Overall progress bar -->
              <div class="w-full bg-surface-200 dark:bg-ink-700 rounded-full h-2 mb-3 overflow-hidden">
                <div
                  class="h-2 rounded-full transition-all duration-700 ease-out"
                  :class="progressPercent >= 80 ? 'bg-gradient-to-r from-emerald-400 to-emerald-500' : progressPercent >= 40 ? 'bg-gradient-to-r from-amber-400 to-amber-500' : 'bg-gradient-to-r from-primary-400 to-primary-500'"
                  :style="{ width: progressPercent + '%' }"
                ></div>
              </div>

              <!-- Per-difficulty breakdown -->
              <div class="space-y-3">
                <div v-for="diff in diffOrder" :key="diff" class="group">
                  <div class="flex items-center justify-between text-xs mb-1.5">
                    <span class="font-semibold" :class="diffColor(diff)">{{ diff }}</span>
                    <span class="text-ink-400 dark:text-ink-500 tabular-nums">
                      {{ (practiceStats.by_difficulty?.[diff]?.practiced || 0) }}/{{ (practiceStats.by_difficulty?.[diff]?.total || 0) }}
                      <span v-if="practiceStats.by_difficulty?.[diff]?.avg_score" class="ml-1 font-bold" :class="scoreColor(practiceStats.by_difficulty[diff].avg_score)">
                        {{ practiceStats.by_difficulty[diff].avg_score }}分
                      </span>
                    </span>
                  </div>
                  <div class="w-full bg-surface-200 dark:bg-ink-700 rounded-full h-1.5 overflow-hidden">
                    <div
                      class="h-1.5 rounded-full transition-all duration-700 ease-out"
                      :class="diffBarColor(diff)"
                      :style="{ width: diffProgress(diff) + '%' }"
                    ></div>
                  </div>
                </div>
              </div>

              <!-- Average score badge -->
              <div v-if="practiceStats.avg_score" class="mt-4 flex items-center gap-2 text-xs">
                <span class="text-ink-400 dark:text-ink-500">平均最高分</span>
                <span class="font-bold px-2.5 py-0.5 rounded-lg" :class="scoreBadgeClass(practiceStats.avg_score)">
                  {{ practiceStats.avg_score }}
                </span>
              </div>
            </div>

            <!-- Daily Recommendation -->
            <div class="space-y-3.5 p-4 rounded-2xl border border-amber-100 dark:border-amber-800 bg-gradient-to-b from-amber-50/50 to-white dark:from-amber-900/20 dark:to-surface-800">
              <div class="flex items-center justify-between">
                <h3 class="text-xs font-bold text-amber-600 dark:text-amber-400 uppercase tracking-wider flex items-center gap-2">
                  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                  每日推荐
                </h3>
                <button @click="emit('refresh-recommend')" class="text-xs text-ink-400 hover:text-amber-500 dark:hover:text-amber-400 transition p-1 rounded-lg hover:bg-amber-50 dark:hover:bg-amber-900/30" title="换一批">
                  <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
                </button>
              </div>
              <div v-if="recommendations.length === 0" class="text-xs text-ink-400 dark:text-ink-500 text-center py-6">
                暂无推荐，继续加油
              </div>
              <ul class="space-y-1.5">
                <li
                  v-for="q in recommendations"
                  :key="q.id"
                  @click="emit('go-to-question', q)"
                  class="group flex items-start gap-2.5 p-2.5 rounded-xl cursor-pointer hover:bg-amber-50/60 dark:hover:bg-amber-900/20 transition-all duration-200"
                >
                  <span class="flex-shrink-0 mt-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded-md" :class="freqBadgeClass(q.frequency)">
                    {{ q.frequency > 1 ? '高频' : '新题' }}
                  </span>
                  <div class="min-w-0 flex-1">
                    <p class="text-xs text-ink-600 dark:text-ink-400 leading-relaxed line-clamp-2 group-hover:text-amber-700 dark:group-hover:text-amber-400 transition-colors">{{ q.question }}</p>
                    <div class="flex items-center gap-1.5 mt-1.5">
                      <span class="text-[10px] px-1.5 py-0.5 rounded-md bg-surface-100 dark:bg-ink-800 text-ink-500 dark:text-ink-400">{{ shortCat(q.cat1) }}</span>
                      <span class="text-[10px] px-1.5 py-0.5 rounded-md" :class="diffChipClass(q.difficulty)">{{ shortDiff(q.difficulty) }}</span>
                    </div>
                  </div>
                </li>
              </ul>
            </div>

            <!-- Starred Quick Access -->
            <div class="space-y-3.5 p-4 rounded-2xl border border-amber-100 dark:border-amber-800 bg-gradient-to-b from-amber-50/50 to-white dark:from-amber-900/20 dark:to-surface-800">
              <div class="flex items-center justify-between">
                <h3 class="text-xs font-bold text-amber-600 dark:text-amber-400 uppercase tracking-wider flex items-center gap-2">
                  <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg>
                  收藏夹
                </h3>
                <span class="text-xs text-ink-400 dark:text-ink-500 tabular-nums">{{ starredItems.length }} 题</span>
              </div>
              <div v-if="starredItems.length === 0" class="text-xs text-ink-400 dark:text-ink-500 text-center py-6">
                点击题目卡片的 <svg class="inline w-3 h-3 text-ink-300 dark:text-ink-600" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg> 收藏
              </div>
              <ul v-else class="space-y-0.5 max-h-40 overflow-y-auto custom-scrollbar">
                <li
                  v-for="q in starredItems"
                  :key="q.id"
                  @click="emit('go-to-question', q)"
                  class="flex items-center gap-2 p-2 rounded-lg cursor-pointer hover:bg-amber-50 dark:hover:bg-amber-900/20 transition-all duration-200 text-xs text-ink-600 dark:text-ink-400 hover:text-amber-700 dark:hover:text-amber-400"
                >
                  <svg class="w-3 h-3 text-amber-400 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg>
                  <span class="truncate">{{ q.question }}</span>
                </li>
              </ul>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-end px-6 py-4 border-t border-surface-100 dark:border-ink-700 bg-surface-50/80 dark:bg-surface-900/80 shrink-0">
            <button @click="emit('close')" class="btn-secondary px-5">关闭</button>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { getMyEmail, sendBindCode, bindEmail, uploadResume, getResume, deleteResume } from '@/api/index.js'
import { useToast } from '@/composables/useNotification.js'

const toast = useToast()

const props = defineProps({
  visible: { type: Boolean, default: false },
  user: { type: Object, default: null },
  practiceStats: { type: Object, default: () => ({}) },
  masterBank: { type: Array, default: () => [] },
  recommendSeed: { type: Number, default: 0 }
})

const emit = defineEmits(['close', 'go-to-question', 'refresh-recommend'])

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

// ── 简历状态 ──
const resumeInfo = ref(null)
const resumeUploading = ref(false)
const resumeError = ref('')
const resumeDragover = ref(false)

// ── 学习进度相关 ──
const diffOrder = ['L1-基础', 'L2-中等', 'L3-困难']

const progressPercent = computed(() => {
  const s = props.practiceStats
  if (!s.total_questions) return 0
  return Math.round((s.practiced_questions / s.total_questions) * 100)
})

const diffProgress = (diff) => {
  const d = props.practiceStats.by_difficulty?.[diff]
  if (!d || !d.total) return 0
  return Math.round((d.practiced / d.total) * 100)
}

const diffColor = (diff) => {
  if (diff.includes('L1')) return 'text-emerald-600 dark:text-emerald-400'
  if (diff.includes('L2')) return 'text-amber-600 dark:text-amber-400'
  if (diff.includes('L3')) return 'text-red-600 dark:text-red-400'
  return 'text-ink-600 dark:text-ink-400'
}

const diffBarColor = (diff) => {
  if (diff.includes('L1')) return 'bg-gradient-to-r from-emerald-400 to-emerald-500'
  if (diff.includes('L2')) return 'bg-gradient-to-r from-amber-400 to-amber-500'
  if (diff.includes('L3')) return 'bg-gradient-to-r from-red-400 to-red-500'
  return 'bg-ink-400'
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

// ── 每日推荐相关 ──
const recommendations = computed(() => {
  void props.recommendSeed
  const pool = [...props.masterBank]
  pool.sort((a, b) => (b.frequency || 1) - (a.frequency || 1))

  const picks = []
  const byDiff = { 'L1': [], 'L2': [], 'L3': [] }
  pool.forEach(q => {
    const d = (q.difficulty || '').substring(0, 2)
    if (byDiff[d]) byDiff[d].push(q)
    else byDiff['L2'].push(q)
  })

  const seed = props.recommendSeed || Date.now()
  const pickFrom = (arr, count) => {
    if (arr.length === 0) return []
    const result = []
    const used = new Set()
    for (let i = 0; i < count && i < arr.length; i++) {
      let idx = (seed * (i + 1) * 7 + i * 13) % arr.length
      let tries = 0
      while (used.has(idx) && tries < arr.length) { idx = (idx + 1) % arr.length; tries++ }
      if (!used.has(idx)) { used.add(idx); result.push(arr[idx]) }
    }
    return result
  }

  picks.push(...pickFrom(byDiff['L1'], 1))
  picks.push(...pickFrom(byDiff['L2'], 2))
  picks.push(...pickFrom(byDiff['L3'], 1))
  if (picks.length < 4) {
    const remaining = pool.filter(q => !picks.includes(q))
    picks.push(...pickFrom(remaining, 4 - picks.length))
  }
  return picks.slice(0, 5)
})

// ── 收藏夹相关 ──
const starredItems = computed(() => props.masterBank.filter(q => q.is_starred).slice(0, 20))

const shortCat = (cat) => {
  if (!cat) return '未分类'
  const match = cat.match(/^[A-F]\.(.+)/)
  if (match) { const parts = match[1].split(/[与和、]/); return parts[0].substring(0, 4) }
  return cat.substring(0, 4)
}

const shortDiff = (diff) => {
  if (!diff) return '?'
  if (diff.includes('L1')) return '基础'
  if (diff.includes('L2')) return '中等'
  if (diff.includes('L3')) return '困难'
  return diff
}

const diffChipClass = (diff) => {
  if (!diff) return 'bg-surface-100 dark:bg-ink-800 text-ink-500 dark:text-ink-400'
  if (diff.includes('L1')) return 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400'
  if (diff.includes('L2')) return 'bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400'
  if (diff.includes('L3')) return 'bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400'
  return 'bg-surface-100 dark:bg-ink-800 text-ink-500 dark:text-ink-400'
}

const freqBadgeClass = (freq) => {
  if (freq >= 3) return 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400'
  if (freq >= 2) return 'bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400'
  return 'bg-surface-100 dark:bg-ink-800 text-ink-500 dark:text-ink-400'
}

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
  } catch (e) {
    resumeError.value = e.message || '删除失败'
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return dateStr.replace('T', ' ').slice(0, 16)
}

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
  } catch (e) {
    emailBinding.error = e.message || '绑定失败'
  } finally {
    emailBinding.saving = false
  }
}

watch(() => props.visible, (val) => {
  if (val) {
    loadMyEmail()
    loadResume()
    emailBinding.editing = false
    emailBinding.error = ''
    resumeError.value = ''
  }
})
</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
