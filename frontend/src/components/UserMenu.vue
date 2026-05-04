<template>
  <div class="relative">
    <!-- User button -->
    <button @click="showMenu = !showMenu" class="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-white/10 transition text-white">
      <div class="w-7 h-7 rounded-full bg-blue-400/30 flex items-center justify-center text-sm font-bold">
        {{ user?.username?.[0]?.toUpperCase() || '?' }}
      </div>
      <span class="text-sm font-medium hidden sm:inline">{{ user?.username }}</span>
      <svg class="w-4 h-4 transition-transform" :class="{ 'rotate-180': showMenu }" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
      </svg>
    </button>

    <!-- Dropdown -->
    <Transition name="menu">
      <div v-if="showMenu" class="absolute right-0 top-full mt-1 w-56 bg-white rounded-xl shadow-xl border border-gray-100 py-1 z-50">
        <!-- User info -->
        <div class="px-4 py-3 border-b border-gray-100">
          <p class="text-sm font-semibold text-gray-800">{{ user?.username }}</p>
          <p class="text-xs text-gray-500">{{ user?.is_admin ? '管理员' : '普通用户' }}</p>
        </div>

        <!-- Bank mode -->
        <div class="px-4 py-3 border-b border-gray-100">
          <p class="text-xs text-gray-500 mb-2">题库模式</p>
          <div class="flex gap-1">
            <button
              v-for="mode in bankModes"
              :key="mode.value"
              @click="switchBankMode(mode.value)"
              :class="[
                'px-2.5 py-1 text-xs rounded-md transition font-medium',
                user?.bank_mode === mode.value
                  ? 'bg-blue-100 text-blue-700'
                  : 'text-gray-600 hover:bg-gray-100'
              ]"
            >{{ mode.label }}</button>
          </div>
        </div>

        <!-- Admin review -->
        <button
          v-if="user?.is_admin"
          @click="$emit('show-review'); showMenu = false"
          class="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
        >
          <svg class="w-4 h-4 text-orange-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          审核题库
          <span v-if="pendingCount > 0" class="ml-auto bg-orange-100 text-orange-700 text-xs px-1.5 py-0.5 rounded-full font-bold">{{ pendingCount }}</span>
        </button>

        <!-- Logout -->
        <button
          @click="handleLogout"
          class="w-full text-left px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 flex items-center gap-2"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
          </svg>
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
import { authUpdateBankMode } from '../api/index.js'

const props = defineProps({
  user: Object,
  pendingCount: { type: Number, default: 0 }
})

const emit = defineEmits(['logout', 'show-review', 'bank-mode-changed'])

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
    localStorage.setItem('auth_user', JSON.stringify(updated))
    emit('bank-mode-changed', updated)
  } catch (e) {
    console.error('切换题库模式失败:', e)
  }
}

function handleLogout() {
  localStorage.removeItem('auth_token')
  localStorage.removeItem('auth_user')
  showMenu.value = false
  emit('logout')
}
</script>

<style scoped>
.menu-enter-active, .menu-leave-active { transition: all 0.15s ease; }
.menu-enter-from, .menu-leave-to { opacity: 0; transform: translateY(-4px) scale(0.95); }
</style>
