<template>
  <div class="relative">
    <button
      ref="buttonRef"
      type="button"
      aria-label="账户菜单"
      aria-haspopup="menu"
      :aria-expanded="showMenu"
      class="flex items-center text-foreground transition-all duration-200 dark:text-white group"
      :class="buttonClass || 'gap-2.5 rounded-lg px-3 py-1.5 hover:bg-muted dark:hover:bg-white/5'"
      @click="toggleMenu"
      @keydown.esc.prevent="closeMenu"
    >
      <div v-if="compact" class="flex size-10 shrink-0 items-center justify-center rounded-md bg-primary text-sm font-bold text-primary-foreground">
        {{ user?.username?.[0]?.toUpperCase() || '?' }}
      </div>
      <template v-else>
        <div class="flex size-[18px] shrink-0 items-center justify-center rounded bg-primary text-[9px] font-bold leading-none text-primary-foreground">
          {{ user?.username?.[0]?.toUpperCase() || '?' }}
        </div>
        <span class="truncate text-sm font-medium">{{ user?.username }}</span>
        <ChevronDown class="ml-auto size-4 text-muted-foreground transition-transform duration-200 dark:text-white" :class="{ 'rotate-180': showMenu }" aria-hidden="true" />
      </template>
    </button>

    <Teleport to="body">
      <div v-if="showMenu" class="fixed inset-0 z-40" @click="closeMenu" />
      <Transition name="menu">
        <div
          v-if="showMenu"
          ref="dropdownRef"
          role="menu"
          aria-label="账户菜单"
          tabindex="-1"
          data-material="glass"
          class="fixed z-50 w-60 overflow-hidden rounded-xl border border-border py-1.5 shadow-lg"
          :style="dropdownStyle"
          @keydown.esc.prevent="closeMenu"
        >
          <div class="border-b border-border px-4 py-3">
            <p class="text-sm font-bold text-foreground">{{ user?.username }}</p>
            <p class="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
              <span class="size-1.5 rounded-full" :class="user?.is_admin ? 'bg-amber-400' : 'bg-emerald-400'" />
              {{ user?.is_admin ? '管理员' : '普通用户' }}
            </p>
          </div>

          <button
            v-if="user?.is_admin"
            type="button"
            role="menuitem"
            class="group flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
            @click="emitAndClose('show-review')"
          >
            <CircleCheck class="size-4 shrink-0 text-sidebar-foreground/40 group-hover:text-sidebar-foreground/70" aria-hidden="true" />
            审核题库
            <span v-if="pendingCount > 0" class="ml-auto text-[11px] font-medium text-sidebar-foreground/50">{{ pendingCount }}</span>
          </button>

          <button
            type="button"
            role="menuitem"
            class="group flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
            @click="emitAndClose('show-settings')"
          >
            <Settings class="size-4 shrink-0 text-sidebar-foreground/40 group-hover:text-sidebar-foreground/70" aria-hidden="true" />
            设置
          </button>

          <button
            type="button"
            role="menuitem"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm text-red-600 transition-colors hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-900/20"
            @click="emitAndClose('logout')"
          >
            <LogOut class="size-4 shrink-0 text-red-500 dark:text-red-400" aria-hidden="true" />
            退出登录
          </button>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { nextTick, onUnmounted, ref, watch } from 'vue'
import { ChevronDown, CircleCheck, LogOut, Settings } from '@lucide/vue'

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

function toggleMenu() {
  showMenu.value = !showMenu.value
}

function closeMenu() {
  showMenu.value = false
  nextTick(() => buttonRef.value?.focus())
}

function emitAndClose(event) {
  emit(event)
  closeMenu()
}

function updateDropdownPosition() {
  const button = buttonRef.value
  if (!button) return
  const rect = button.getBoundingClientRect()
  if (props.placement === 'top') {
    dropdownStyle.value = { bottom: `${window.innerHeight - rect.top + 8}px`, left: `${rect.left}px` }
  } else {
    dropdownStyle.value = { top: `${rect.bottom + 8}px`, right: `${Math.max(12, window.innerWidth - rect.right)}px` }
  }
}

function onScrollOrResize() {
  if (showMenu.value) updateDropdownPosition()
}

watch(showMenu, async open => {
  if (open) {
    await nextTick()
    updateDropdownPosition()
    dropdownRef.value?.focus()
  }
})

window.addEventListener('scroll', onScrollOrResize, true)
window.addEventListener('resize', onScrollOrResize)
onUnmounted(() => {
  window.removeEventListener('scroll', onScrollOrResize, true)
  window.removeEventListener('resize', onScrollOrResize)
})
</script>

<style>
.menu-enter-active, .menu-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.menu-enter-from, .menu-leave-to { opacity: 0; transform: scale(0.95); }
</style>
