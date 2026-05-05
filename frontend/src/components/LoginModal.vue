<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="visible" class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm" @click.self="$emit('close')">
        <div class="bg-white rounded-3xl shadow-2xl w-full max-w-sm mx-4 overflow-hidden animate-slide-up">
          <!-- Gradient header -->
          <div class="relative px-6 pt-8 pb-5 bg-gradient-to-br from-primary-50 via-white to-accent-50">
            <div class="absolute top-3 right-3">
              <button @click="$emit('close')" class="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-white/60 transition">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
              </button>
            </div>
            <div class="w-12 h-12 mx-auto mb-3 rounded-2xl bg-gradient-brand flex items-center justify-center shadow-glow">
              <svg class="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
              </svg>
            </div>
            <h2 class="text-xl font-bold text-gray-800 text-center">{{ isRegister ? '创建账号' : '欢迎回来' }}</h2>
            <p class="text-sm text-gray-500 text-center mt-1">{{ isRegister ? '注册后即可使用全部功能' : '登录以访问你的面试题库' }}</p>
          </div>

          <!-- Form -->
          <form @submit.prevent="handleSubmit" action="/api/auth/login-form" method="post" class="px-6 pb-2 pt-4">
            <div class="space-y-4">
              <div>
                <label class="block text-sm font-semibold text-gray-700 mb-1.5">用户名</label>
                <input
                  ref="usernameInput"
                  v-model="username"
                  type="text"
                  name="username"
                  placeholder="2-32 个字符"
                  maxlength="32"
                  class="w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-primary-200 focus:border-primary-400 outline-none transition-all duration-200 bg-gray-50 focus:bg-white"
                  :disabled="loading"
                  autocomplete="username"
                />
              </div>
              <div>
                <label class="block text-sm font-semibold text-gray-700 mb-1.5">密码</label>
                <input
                  v-model="password"
                  type="password"
                  name="password"
                  placeholder="至少 6 位"
                  class="w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-primary-200 focus:border-primary-400 outline-none transition-all duration-200 bg-gray-50 focus:bg-white"
                  :disabled="loading"
                  autocomplete="current-password"
                />
              </div>
            </div>

            <!-- Remember me + Error -->
            <label v-if="!isRegister" class="flex items-center gap-2 mt-3 cursor-pointer group">
              <input v-model="rememberMe" type="checkbox" class="w-4 h-4 rounded-md border-gray-300 text-primary-600 focus:ring-primary-500 transition" />
              <span class="text-sm text-gray-500 group-hover:text-gray-700 transition">记住我（30 天免登录）</span>
            </label>
            <Transition name="fade">
              <p v-if="error" class="text-red-500 text-sm mt-2 flex items-center gap-1.5">
                <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                {{ error }}
              </p>
            </Transition>

            <!-- Submit -->
            <button
              type="submit"
              :disabled="loading || !username.trim() || password.length < (isRegister ? 6 : 1)"
              class="w-full mt-5 py-2.5 btn-primary text-base"
            >
              <svg v-if="loading" class="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              {{ loading ? '处理中...' : (isRegister ? '注册' : '登录') }}
            </button>
          </form>

          <!-- Toggle -->
          <div class="px-6 py-4 bg-gray-50/80 text-center border-t border-gray-100">
            <span class="text-sm text-gray-500">{{ isRegister ? '已有账号？' : '没有账号？' }}</span>
            <button @click="isRegister = !isRegister; error = ''" class="text-sm text-primary-600 hover:text-primary-700 font-semibold ml-1 transition">
              {{ isRegister ? '去登录' : '注册一个' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { authLogin, authRegister } from '../api/index.js'
import { setAuthToken } from '../utils/http.js'
import { validateUsername, validatePassword } from '../utils/validate.js'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['close', 'login-success'])

const usernameInput = ref(null)
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
    triggerBrowserSavePassword(userResult.value, passResult.value)
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

function triggerBrowserSavePassword(user, pass) {
  try {
    if (window.PasswordCredential) {
      const cred = new PasswordCredential({ id: user, password: pass, name: user })
      navigator.credentials.store(cred)
      return
    }
  } catch { /* fallback below */ }

  const iframe = document.createElement('iframe')
  iframe.name = 'pw-save-frame'
  iframe.style.display = 'none'
  document.body.appendChild(iframe)

  const form = document.createElement('form')
  form.action = '/api/auth/login-form'
  form.method = 'POST'
  form.target = 'pw-save-frame'
  form.style.display = 'none'

  const uInput = document.createElement('input')
  uInput.name = 'username'
  uInput.value = user
  const pInput = document.createElement('input')
  pInput.name = 'password'
  pInput.type = 'password'
  pInput.value = pass

  form.appendChild(uInput)
  form.appendChild(pInput)
  document.body.appendChild(form)
  form.submit()

  setTimeout(() => { form.remove(); iframe.remove() }, 2000)
}
</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
