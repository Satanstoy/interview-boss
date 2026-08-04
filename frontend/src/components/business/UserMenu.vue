<template>
  <div class="relative">
    <!-- User button -->
    <button
      ref="buttonRef"
      @click="showMenu = !showMenu"
      class="flex items-center transition-all duration-200 text-foreground dark:text-white group"
      :class="buttonClass || 'gap-2.5 px-3 py-1.5 rounded-lg hover:bg-muted dark:hover:bg-white/5'"
    >
      <div v-if="compact" class="size-10 rounded-md bg-primary flex items-center justify-center text-sm font-bold text-primary-foreground shrink-0">
        {{ user?.username?.[0]?.toUpperCase() || '?' }}
      </div>
      <template v-else>
        <div class="size-[18px] rounded bg-primary flex items-center justify-center text-[9px] font-bold text-primary-foreground leading-none shrink-0">
          {{ user?.username?.[0]?.toUpperCase() || '?' }}
        </div>
        <span class="text-sm font-medium truncate">{{ user?.username }}</span>
        <svg class="size-4 text-muted-foreground dark:text-white transition-transform duration-200 ml-auto" :class="{ 'rotate-180': showMenu }" viewBox="0 0 20 20" fill="currentColor">
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
          data-material="glass"
          class="fixed w-60 rounded-xl shadow-lg border border-border py-1.5 z-50 overflow-hidden"
          :style="dropdownStyle"
        >
        <!-- User info -->
        <div class="px-4 py-3 border-b border-border">
          <p class="text-sm font-bold text-foreground">{{ user?.username }}</p>
          <p class="text-xs text-muted-foreground mt-0.5 flex items-center gap-1">
            <span class="size-1.5 rounded-full" :class="user?.is_admin ? 'bg-amber-400' : 'bg-emerald-400'"></span>
            {{ user?.is_admin ? '管理员' : '普通用户' }}
          </p>
        </div>

        <!-- Admin review -->
        <button
          v-if="user?.is_admin"
          @click="$emit('show-review'); showMenu = false"
          class="group w-full text-left px-4 py-2.5 text-sm text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground flex items-center gap-3 transition-colors"
        >
          <svg class="size-4 shrink-0 text-sidebar-foreground/40 group-hover:text-sidebar-foreground/70" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          审核题库
          <span v-if="pendingCount > 0" class="ml-auto text-[11px] font-medium text-sidebar-foreground/50">{{ pendingCount }}</span>
        </button>

        <!-- Settings -->
        <button
          @click="$emit('show-settings'); showMenu = false"
          class="group w-full text-left px-4 py-2.5 text-sm text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground flex items-center gap-3 transition-colors"
        >
          <svg class="size-4 shrink-0 text-sidebar-foreground/40 group-hover:text-sidebar-foreground/70" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          设置
        </button>

        <!-- Logout -->
        <button
          @click="handleLogout"
          class="w-full text-left px-4 py-2.5 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-3 transition-colors"
        >
          <svg class="size-4 shrink-0 text-red-500 dark:text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
          </svg>
          退出登录
        </button>
      </div>
    </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, onUnmounted } from 'vue'

const props = defineProps({
  user: Object,
  pendingCount: { type: Number, default: 0 },
  placement: { type: String, default: 'bottom' },
  buttonClass: { type: String, default: '' },
  compact: { type: Boolean, default: false },
})

const emit = defineEmits(['logout', 'show-review', 'show-settings'])

const showMenu = ref(false)
const buttonRef = ref(null)
const dropdownRef = ref(null)
const dropdownStyle = ref({})

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

async function handleLogout() {
  showMenu.value = false
  emit('logout')
}
</script>

<style>
/* Transition styles must be global since dropdown is teleported to body */
.menu-enter-active, .menu-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.menu-enter-from, .menu-leave-to { opacity: 0; transform: scale(0.95); }
</style>
