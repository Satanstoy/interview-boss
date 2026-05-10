<template>
  <!-- Embedded mode: inline form without overlay -->
  <div v-if="embedded">
    <div class="mb-8">
      <h3 class="text-xl font-serif text-ink-800 dark:text-ink-100">{{ isRegister ? '创建账号' : '欢迎回来' }}</h3>
      <p class="text-sm text-ink-400 dark:text-ink-400 mt-1">{{ isRegister ? '注册后即可使用全部功能' : '登录以访问你的面试题库' }}</p>
    </div>
    <form ref="formEl" @submit.prevent="handleSubmit" action="/api/auth/login-form" method="post">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-semibold text-ink-700 dark:text-ink-300 mb-1.5">用户名</label>
          <input
            ref="usernameInput"
            v-model="username"
            type="text"
            name="username"
            placeholder="2-32 个字符"
            maxlength="32"
            class="w-full px-4 py-2.5 border border-surface-200 dark:border-ink-600 rounded-xl text-sm focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 outline-none transition-all duration-200 bg-surface-50 dark:bg-surface-900 focus:bg-white dark:focus:bg-surface-800 text-ink-800 dark:text-ink-200 placeholder-ink-400 dark:placeholder-ink-500"
            :disabled="loading"
            autocomplete="username"
          />
        </div>
        <div>
          <label class="block text-sm font-semibold text-ink-700 dark:text-ink-300 mb-1.5">密码</label>
          <input
            v-model="password"
            type="password"
            name="password"
            placeholder="至少 8 位"
            class="w-full px-4 py-2.5 border border-surface-200 dark:border-ink-600 rounded-xl text-sm focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 outline-none transition-all duration-200 bg-surface-50 dark:bg-surface-900 focus:bg-white dark:focus:bg-surface-800 text-ink-800 dark:text-ink-200 placeholder-ink-400 dark:placeholder-ink-500"
            :disabled="loading"
            autocomplete="current-password"
          />
        </div>
      </div>

      <label v-if="!isRegister" class="flex items-center gap-2 mt-3 cursor-pointer group">
        <input v-model="rememberMe" type="checkbox" class="w-4 h-4 rounded-md border-surface-300 dark:border-ink-600 text-primary-600 focus:ring-primary-500 transition" />
        <span class="text-sm text-ink-500 dark:text-ink-400 group-hover:text-ink-700 dark:group-hover:text-ink-300 transition">记住我（30 天免登录）</span>
      </label>
      <Transition name="fade">
        <p v-if="error" class="text-red-500 dark:text-red-400 text-sm mt-2 flex items-center gap-1.5">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          {{ error }}
        </p>
      </Transition>

      <button
        type="submit"
        :disabled="loading || !username.trim() || password.length < (isRegister ? 8 : 1)"
        class="w-full mt-5 py-2.5 btn-primary text-base relative overflow-hidden"
      >
        <span :class="{ 'opacity-0': loading }">{{ loading ? '处理中...' : (isRegister ? '注册' : '登录') }}</span>
        <span v-if="loading" class="absolute inset-0 flex items-center justify-center">
          <svg class="animate-spin h-5 w-5" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
        </span>
      </button>
    </form>

    <div class="mt-4 text-center">
      <span class="text-sm text-ink-500 dark:text-ink-400">{{ isRegister ? '已有账号？' : '没有账号？' }}</span>
      <button @click="isRegister = !isRegister; error = ''" class="text-sm text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300 font-semibold ml-1 transition">
        {{ isRegister ? '去登录' : '注册一个' }}
      </button>
    </div>
  </div>

  <!-- Modal mode: overlay dialog (for 401 re-login etc.) -->
  <Teleport v-else to="body">
    <Transition name="fade">
      <div v-if="visible" class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm" @click.self="$emit('close')">
        <div class="bg-white dark:bg-surface-800 rounded-3xl shadow-2xl w-full max-w-sm mx-4 overflow-hidden animate-slide-up">
          <!-- Gradient header -->
          <div class="relative px-6 pt-8 pb-5 bg-gradient-to-br from-primary-50/80 via-white to-accent-50/80 dark:from-primary-900/20 dark:via-surface-800 dark:to-accent-900/20 overflow-hidden">
            <div class="absolute -top-6 -right-6 w-24 h-24 bg-primary-200/15 dark:bg-primary-700/15 rounded-full blur-xl"></div>
            <div class="absolute -bottom-4 -left-4 w-16 h-16 bg-accent-200/15 dark:bg-accent-700/15 rounded-full blur-xl"></div>
            <div class="absolute top-3 right-3 z-10">
              <button @click="$emit('close')" class="p-1.5 rounded-lg text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-white/60 dark:hover:bg-ink-700/60 transition">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
              </button>
            </div>
            <div class="relative z-10">
              <div class="w-12 h-12 mx-auto mb-3 rounded-2xl bg-gradient-brand flex items-center justify-center shadow-glow">
                <svg class="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
                </svg>
              </div>
              <h2 class="text-xl font-serif text-ink-800 dark:text-ink-100 text-center">{{ isRegister ? '创建账号' : '欢迎回来' }}</h2>
              <p class="text-sm text-ink-400 dark:text-ink-400 text-center mt-1">{{ isRegister ? '注册后即可使用全部功能' : '登录以访问你的面试题库' }}</p>
            </div>
          </div>

          <!-- Form -->
          <form ref="formEl" @submit.prevent="handleSubmit" action="/api/auth/login-form" method="post" class="px-6 pb-2 pt-4">
            <div class="space-y-4">
              <div>
                <label class="block text-sm font-semibold text-ink-700 dark:text-ink-300 mb-1.5">用户名</label>
                <input
                  ref="usernameInput"
                  v-model="username"
                  type="text"
                  name="username"
                  placeholder="2-32 个字符"
                  maxlength="32"
                  class="w-full px-4 py-2.5 border border-surface-200 dark:border-ink-600 rounded-xl text-sm focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 outline-none transition-all duration-200 bg-surface-50 dark:bg-surface-900 focus:bg-white dark:focus:bg-surface-800 text-ink-800 dark:text-ink-200 placeholder-ink-400 dark:placeholder-ink-500"
                  :disabled="loading"
                  autocomplete="username"
                />
              </div>
              <div>
                <label class="block text-sm font-semibold text-ink-700 dark:text-ink-300 mb-1.5">密码</label>
                <input
                  v-model="password"
                  type="password"
                  name="password"
                  placeholder="至少 8 位"
                  class="w-full px-4 py-2.5 border border-surface-200 dark:border-ink-600 rounded-xl text-sm focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 outline-none transition-all duration-200 bg-surface-50 dark:bg-surface-900 focus:bg-white dark:focus:bg-surface-800 text-ink-800 dark:text-ink-200 placeholder-ink-400 dark:placeholder-ink-500"
                  :disabled="loading"
                  autocomplete="current-password"
                />
              </div>
            </div>

            <!-- Remember me + Error -->
            <label v-if="!isRegister" class="flex items-center gap-2 mt-3 cursor-pointer group">
              <input v-model="rememberMe" type="checkbox" class="w-4 h-4 rounded-md border-surface-300 dark:border-ink-600 text-primary-600 focus:ring-primary-500 transition" />
              <span class="text-sm text-ink-500 dark:text-ink-400 group-hover:text-ink-700 dark:group-hover:text-ink-300 transition">记住我（30 天免登录）</span>
            </label>
            <Transition name="fade">
              <p v-if="error" class="text-red-500 dark:text-red-400 text-sm mt-2 flex items-center gap-1.5">
                <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                {{ error }}
              </p>
            </Transition>

            <!-- Submit -->
            <button
              type="submit"
              :disabled="loading || !username.trim() || password.length < (isRegister ? 8 : 1)"
              class="w-full mt-5 py-2.5 btn-primary text-base relative overflow-hidden"
            >
              <span :class="{ 'opacity-0': loading }">{{ loading ? '处理中...' : (isRegister ? '注册' : '登录') }}</span>
              <span v-if="loading" class="absolute inset-0 flex items-center justify-center">
                <svg class="animate-spin h-5 w-5" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              </span>
            </button>
          </form>

          <!-- Toggle -->
          <div class="px-6 py-4 bg-surface-50/80 dark:bg-surface-900/80 text-center border-t border-surface-200/80 dark:border-ink-700">
            <span class="text-sm text-ink-500 dark:text-ink-400">{{ isRegister ? '已有账号？' : '没有账号？' }}</span>
            <button @click="isRegister = !isRegister; error = ''" class="text-sm text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300 font-semibold ml-1 transition">
              {{ isRegister ? '去登录' : '注册一个' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, nextTick, onMounted } from 'vue'
import { authLogin, authRegister } from '../api/index.js'
import { setAuthToken } from '../utils/http.js'
import { validateUsername, validatePassword } from '../utils/validate.js'

const props = defineProps({
  visible: Boolean,
  embedded: { type: Boolean, default: false }
})
const emit = defineEmits(['close', 'login-success'])

const usernameInput = ref(null)
const formEl = ref(null)
const isRegister = ref(false)
const username = ref('')
const password = ref('')
const rememberMe = ref(true)
const loading = ref(false)
const error = ref('')

watch(() => props.visible, (v) => {
  if (v) {
    error.value = ''
    isRegister.value = false
    nextTick(() => usernameInput.value?.focus())
  }
})

onMounted(() => {
  if (props.embedded) {
    nextTick(() => usernameInput.value?.focus())
  }
})

async function handleSubmit() {
  if (loading.value) return
  error.value = ''

  const userResult = validateUsername(username.value)
  if (!userResult.valid) { error.value = userResult.error; return }
  const passResult = validatePassword(password.value)
  if (!passResult.valid) { error.value = passResult.error; return }

  loading.value = true
  try {
    const fn = isRegister.value ? authRegister : authLogin
    const args = isRegister.value
      ? [userResult.value, passResult.value]
      : [userResult.value, passResult.value, rememberMe.value]
    const data = await fn(...args)
    setAuthToken(data.token)
    triggerBrowserSavePassword()
    emit('login-success', data.user)
    emit('close')
    username.value = ''
    password.value = ''
  } catch (e) {
    error.value = e.message || '操作失败'
  } finally {
    loading.value = false
  }
}

function triggerBrowserSavePassword() {
  // Use Credential Management API with the actual form element
  if (window.PasswordCredential && formEl.value) {
    try {
      const cred = new PasswordCredential(formEl.value)
      navigator.credentials.store(cred)
      return
    } catch { /* fallback below */ }
  }
  // Fallback: history.pushState simulates navigation to trigger browser save prompt
  try { history.pushState(null, '', location.href) } catch {}
}
</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
