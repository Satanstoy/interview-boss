<template>
  <div class="relative">
    <!-- User button -->
    <button
      ref="buttonRef"
      @click="showMenu = !showMenu"
      class="flex items-center transition-all duration-200 text-ink-700 dark:text-white group"
      :class="buttonClass || 'gap-2.5 px-3 py-1.5 rounded-lg hover:bg-surface-100 dark:hover:bg-white/5'"
    >
      <div v-if="compact" class="w-10 h-10 rounded-md bg-primary flex items-center justify-center text-sm font-bold text-primary-foreground shrink-0">
        {{ user?.username?.[0]?.toUpperCase() || '?' }}
      </div>
      <template v-else>
        <div class="w-[18px] h-[18px] rounded bg-primary flex items-center justify-center text-[9px] font-bold text-primary-foreground leading-none shrink-0">
          {{ user?.username?.[0]?.toUpperCase() || '?' }}
        </div>
        <span class="text-sm font-medium truncate">{{ user?.username }}</span>
        <svg class="w-4 h-4 text-ink-400 dark:text-white transition-transform duration-200 ml-auto" :class="{ 'rotate-180': showMenu }" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
        </svg>
      </template>
    </button>

    <!-- Teleport dropdown + overlay to body to escape overflow-hidden -->
    <Teleport to="body">
      <!-- Click outside -->
      <div v-if="showMenu" class="fixed inset-0 z-40" @click="showMenu = false"></div>

      <!-- Dropdown -->
      <Transition name="menu">
        <div
          v-if="showMenu"
          ref="dropdownRef"
          class="fixed w-60 bg-white dark:bg-surface-800 rounded-xl shadow-lg border border-border py-1.5 z-50 overflow-hidden"
          :style="dropdownStyle"
        >
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
    </Teleport>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, onUnmounted } from 'vue'
import { authUpdateBankMode, authLogout } from '@/api/index.js'
import { setAuthToken } from '@/services/http.js'

const props = defineProps({
  user: Object,
  pendingCount: { type: Number, default: 0 },
  placement: { type: String, default: 'bottom' },
  buttonClass: { type: String, default: '' },
  compact: { type: Boolean, default: false },
})

const emit = defineEmits(['logout', 'show-review', 'bank-mode-changed', 'show-profile'])

const showMenu = ref(false)
const buttonRef = ref(null)
const dropdownRef = ref(null)
const dropdownStyle = ref({})

const bankModes = [
  { value: 'public', label: '公共' },
  { value: 'personal', label: '个人' },
  { value: 'mixed', label: '混用' }
]

// Calculate dropdown position when menu opens
watch(showMenu, async (open) => {
  if (open) {
    await nextTick()
    updateDropdownPosition()
  }
})

function updateDropdownPosition() {
  const btn = buttonRef.value
  if (!btn) return
  const rect = btn.getBoundingClientRect()
  const right = Math.max(12, window.innerWidth - rect.right)
  if (props.placement === 'top') {
    dropdownStyle.value = {
      bottom: `${window.innerHeight - rect.top + 8}px`,
      left: `${rect.left}px`,
    }
    return
  }
  dropdownStyle.value = {
    top: `${rect.bottom + 8}px`,
    right: `${right}px`,
  }
}

// Update position on scroll/resize while menu is open
function onScrollOrResize() {
  if (showMenu.value) updateDropdownPosition()
}
window.addEventListener('scroll', onScrollOrResize, true)
window.addEventListener('resize', onScrollOrResize)
onUnmounted(() => {
  window.removeEventListener('scroll', onScrollOrResize, true)
  window.removeEventListener('resize', onScrollOrResize)
})

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

<style>
/* Transition styles must be global since dropdown is teleported to body */
.menu-enter-active, .menu-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.menu-enter-from, .menu-leave-to { opacity: 0; transform: scale(0.95); }
</style>
