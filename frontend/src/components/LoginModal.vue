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
          <form @submit.prevent="handleSubmit" class="px-6 pb-2">
            <div class="space-y-4">
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">用户名</label>
                <input
                  ref="usernameInput"
                  v-model="username"
                  type="text"
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
                  placeholder="至少 6 位"
                  class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition"
                  :disabled="loading"
                  autocomplete="current-password"
                />
              </div>
            </div>

            <!-- Error -->
            <p v-if="error" class="text-red-500 text-sm mt-3">{{ error }}</p>

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

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['close', 'login-success'])

const usernameInput = ref(null)
const isRegister = ref(false)
const username = ref('')
const password = ref('')
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
    const data = await fn(username.value.trim(), password.value)
    localStorage.setItem('auth_token', data.token)
    localStorage.setItem('auth_user', JSON.stringify(data.user))
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
</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
