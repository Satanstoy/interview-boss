<template>
  <div class="relative">
    <!-- User button -->
    <button @click="showMenu = !showMenu" class="flex items-center gap-2.5 px-3 py-1.5 rounded-xl hover:bg-surface-100 dark:hover:bg-white/5 transition-all duration-200 text-ink-700 dark:text-white group">
      <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-primary-500 to-primary-700 dark:from-white/30 dark:to-white/10 flex items-center justify-center text-sm font-bold text-white backdrop-blur-sm border border-primary-400/30 dark:border-white/20 group-hover:from-primary-600 group-hover:to-primary-800 dark:group-hover:from-white/40 dark:group-hover:to-white/20 transition">
        {{ user?.username?.[0]?.toUpperCase() || '?' }}
      </div>
      <span class="text-sm font-medium hidden sm:inline">{{ user?.username }}</span>
      <svg class="w-4 h-4 text-ink-400 dark:text-white transition-transform duration-200" :class="{ 'rotate-180': showMenu }" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
      </svg>
    </button>

    <!-- Dropdown -->
    <Transition name="menu">
      <div v-if="showMenu" class="absolute right-0 top-full mt-2 w-60 bg-white dark:bg-surface-800 rounded-2xl shadow-xl border border-surface-100 dark:border-ink-700 py-1.5 z-50 overflow-hidden">
        <!-- User info -->
        <div class="px-4 py-3 border-b border-surface-100 dark:border-ink-700">
          <p class="text-sm font-bold text-ink-800 dark:text-ink-100">{{ user?.username }}</p>
          <p class="text-xs text-ink-400 dark:text-ink-500 mt-0.5 flex items-center gap-1">
            <span class="w-1.5 h-1.5 rounded-full" :class="user?.is_admin ? 'bg-amber-400' : 'bg-emerald-400'"></span>
            {{ user?.is_admin ? '管理员' : '普通用户' }}
          </p>
        </div>

        <!-- Bank mode -->
        <div class="px-4 py-3 border-b border-surface-100 dark:border-ink-700">
          <p class="text-xs text-ink-400 dark:text-ink-500 mb-2 font-medium uppercase tracking-wider">题库模式</p>
          <div class="flex gap-1 bg-surface-100 dark:bg-ink-800 rounded-lg p-0.5">
            <button
              v-for="mode in bankModes"
              :key="mode.value"
              @click="switchBankMode(mode.value)"
              :class="[
                'flex-1 px-2 py-1.5 text-xs rounded-md transition-all duration-200 font-medium',
                user?.bank_mode === mode.value
                  ? 'bg-white dark:bg-surface-700 text-primary-700 dark:text-primary-400 shadow-sm'
                  : 'text-ink-500 dark:text-ink-400 hover:text-ink-700 dark:hover:text-ink-300'
              ]"
            >{{ mode.label }}</button>
          </div>
        </div>

        <!-- Admin review -->
        <button
          v-if="user?.is_admin"
          @click="$emit('show-review'); showMenu = false"
          class="w-full text-left px-4 py-2.5 text-sm text-ink-700 dark:text-ink-300 hover:bg-surface-50 dark:hover:bg-ink-800 flex items-center gap-2.5 transition-colors"
        >
          <div class="w-7 h-7 rounded-lg bg-orange-100 dark:bg-orange-900/30 flex items-center justify-center">
            <svg class="w-4 h-4 text-orange-600 dark:text-orange-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
            </svg>
          </div>
          审核题库
          <span v-if="pendingCount > 0" class="ml-auto bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400 text-xs px-2 py-0.5 rounded-full font-bold">{{ pendingCount }}</span>
        </button>

        <!-- Profile -->
        <button
          @click="$emit('show-profile'); showMenu = false"
          class="w-full text-left px-4 py-2.5 text-sm text-ink-700 dark:text-ink-300 hover:bg-surface-50 dark:hover:bg-ink-800 flex items-center gap-2.5 transition-colors"
        >
          <div class="w-7 h-7 rounded-lg bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center">
            <svg class="w-4 h-4 text-primary-600 dark:text-primary-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
            </svg>
          </div>
          个人信息
        </button>

        <!-- Logout -->
        <button
          @click="handleLogout"
          class="w-full text-left px-4 py-2.5 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-2.5 transition-colors"
        >
          <div class="w-7 h-7 rounded-lg bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
            <svg class="w-4 h-4 text-red-500 dark:text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
            </svg>
          </div>
          退出登录
        </button>
      </div>
    </Transition>

    <!-- Click outside -->
    <div v-if="showMenu" class="fixed inset-0 z-40" @click="showMenu = false"></div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { authUpdateBankMode, authLogout } from '../api/index.js'
import { setAuthToken } from '../utils/http.js'

const props = defineProps({
  user: Object,
  pendingCount: { type: Number, default: 0 }
})

const emit = defineEmits(['logout', 'show-review', 'bank-mode-changed', 'show-profile'])

const showMenu = ref(false)

const bankModes = [
  { value: 'public', label: '公共' },
  { value: 'personal', label: '个人' },
  { value: 'mixed', label: '混用' }
]

async function switchBankMode(mode) {
  if (mode === props.user?.bank_mode) return
  try {
    await authUpdateBankMode(mode)
    const updated = { ...props.user, bank_mode: mode }
    emit('bank-mode-changed', updated)
  } catch (e) {
    console.error('切换题库模式失败:', e)
  }
}

async function handleLogout() {
  showMenu.value = false
  await authLogout()
  setAuthToken('')
  emit('logout')
}
</script>

<style scoped>
.menu-enter-active, .menu-leave-active { transition: all 0.2s cubic-bezier(0.21, 1.02, 0.73, 1); }
.menu-enter-from, .menu-leave-to { opacity: 0; transform: translateY(-8px) scale(0.95); }
</style>
