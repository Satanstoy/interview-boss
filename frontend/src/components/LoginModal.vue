<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="visible" class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm" @click.self="$emit('close')">
        <div class="bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 overflow-hidden">
          <!-- Header -->
          <div class="px-6 pt-6 pb-4">
            <h2 class="text-xl font-bold text-gray-800">{{ isRegister ? '注册账号' : '登录' }}</h2>
            <p class="text-sm text-gray-500 mt-1">{{ isRegister ? '创建新账号以使用完整功能' : '登录后可使用个人题库和刷题记录' }}</p>
          </div>

          <!-- Form -->
          <form @submit.prevent="handleSubmit" action="/api/auth/login-form" method="post" class="px-6 pb-2">
            <div class="space-y-4">
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">用户名</label>
                <input
                  ref="usernameInput"
                  v-model="username"
                  type="text"
                  name="username"
                  placeholder="2-32 个字符"
                  class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition"
                  :disabled="loading"
                  autocomplete="username"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">密码</label>
                <input
                  v-model="password"
                  type="password"
                  name="password"
                  placeholder="至少 6 位"
                  class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition"
                  :disabled="loading"
                  autocomplete="current-password"
                />
              </div>
            </div>

            <!-- Remember me + Error -->
            <label v-if="!isRegister" class="flex items-center gap-2 mt-3 cursor-pointer">
              <input v-model="rememberMe" type="checkbox" class="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
              <span class="text-sm text-gray-600">记住我（30 天免登录）</span>
            </label>
            <p v-if="error" class="text-red-500 text-sm mt-2">{{ error }}</p>

            <!-- Submit -->
            <button
              type="submit"
              :disabled="loading || !username.trim() || password.length < (isRegister ? 6 : 1)"
              class="w-full mt-4 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white font-medium rounded-lg transition flex items-center justify-center gap-2"
            >
              <svg v-if="loading" class="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              {{ loading ? '处理中...' : (isRegister ? '注册' : '登录') }}
            </button>
          </form>

          <!-- Toggle -->
          <div class="px-6 py-4 bg-gray-50 text-center">
            <span class="text-sm text-gray-500">{{ isRegister ? '已有账号？' : '没有账号？' }}</span>
            <button @click="isRegister = !isRegister; error = ''" class="text-sm text-blue-600 hover:text-blue-800 font-medium ml-1">
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
  loading.value = true
  try {
    const fn = isRegister.value ? authRegister : authLogin
    const args = isRegister.value
      ? [username.value.trim(), password.value]
      : [username.value.trim(), password.value, rememberMe.value]
    const data = await fn(...args)
    setAuthToken(data.token)
    // 触发浏览器「保存密码」：提交一个隐藏 form 到隐藏 iframe
    triggerBrowserSavePassword(username.value, password.value)
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
    // 尝试 Credential Management API（Chrome 最优路径）
    if (window.PasswordCredential) {
      const cred = new PasswordCredential({
        id: user,
        password: pass,
        name: user,
      })
      navigator.credentials.store(cred)
      return
    }
  } catch { /* fallback below */ }

  // 兜底：创建隐藏 form + iframe 让浏览器原生密码管理器捕获
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
