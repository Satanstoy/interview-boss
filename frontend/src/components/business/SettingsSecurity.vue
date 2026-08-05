<script setup>
import { ref, onUnmounted } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { changePassword, resetPassword, sendVerifyCode } from '@/api/index.js'
import { validatePassword } from '@/utils/validate.js'
import { toast } from 'vue-sonner'
import { useConfirm } from '@/composables/useNotification.js'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

const emit = defineEmits(['logout'])

const changeMethod = ref('current')

// ── Password change: current password ──
const passwordForm = ref({
  currentPassword: '',
  newPassword: '',
  confirmPassword: '',
})

const passwordError = ref('')
const passwordSuccess = ref('')
const passwordSaving = ref(false)

// ── Password change: email code ──
const emailForm = ref({
  email: '',
  code: '',
  newPassword: '',
  confirmPassword: '',
})
const emailError = ref('')
const emailSuccess = ref('')
const emailSaving = ref(false)
const codeSending = ref(false)
const codeCooldown = ref(0)
let codeTimer = null

const isEmailValid = (email) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())

function clearCodeTimer() {
  if (codeTimer) {
    clearInterval(codeTimer)
    codeTimer = null
  }
  codeCooldown.value = 0
}

function startCodeCooldown() {
  clearCodeTimer()
  codeCooldown.value = 60
  codeTimer = setInterval(() => {
    codeCooldown.value--
    if (codeCooldown.value <= 0) clearCodeTimer()
  }, 1000)
}

const handlePasswordChange = async () => {
  if (passwordSaving.value) return
  passwordError.value = ''
  passwordSuccess.value = ''

  if (!passwordForm.value.currentPassword) {
    passwordError.value = '请输入当前密码'
    return
  }
  const passResult = validatePassword(passwordForm.value.newPassword)
  if (!passResult.valid) { passwordError.value = passResult.error; return }
  if (passwordForm.value.newPassword !== passwordForm.value.confirmPassword) {
    passwordError.value = '两次输入的新密码不一致'
    return
  }
  if (passwordForm.value.currentPassword === passwordForm.value.newPassword) {
    passwordError.value = '新密码不能与当前密码相同'
    return
  }

  passwordSaving.value = true
  try {
    await changePassword(passwordForm.value.currentPassword, passResult.value)
    passwordForm.value = { currentPassword: '', newPassword: '', confirmPassword: '' }
    passwordSuccess.value = '密码修改成功'
    toast.success('密码修改成功')
  } catch (e) {
    passwordError.value = e.message || '修改失败'
  } finally {
    passwordSaving.value = false
  }
}

const handleSendEmailCode = async () => {
  if (codeSending.value || codeCooldown.value > 0) return
  emailError.value = ''
  emailSuccess.value = ''
  if (!isEmailValid(emailForm.value.email)) {
    emailError.value = '请输入有效的邮箱地址'
    return
  }

  codeSending.value = true
  try {
    await sendVerifyCode(emailForm.value.email.trim(), 'reset_password')
    startCodeCooldown()
    toast.success('验证码已发送')
  } catch (e) {
    emailError.value = e.message || '发送失败'
  } finally {
    codeSending.value = false
  }
}

const handleEmailPasswordChange = async () => {
  if (emailSaving.value) return
  emailError.value = ''
  emailSuccess.value = ''

  if (!isEmailValid(emailForm.value.email)) {
    emailError.value = '请输入有效的邮箱地址'
    return
  }
  if (emailForm.value.code.length < 6) {
    emailError.value = '请输入 6 位验证码'
    return
  }
  const passResult = validatePassword(emailForm.value.newPassword)
  if (!passResult.valid) { emailError.value = passResult.error; return }
  if (emailForm.value.newPassword !== emailForm.value.confirmPassword) {
    emailError.value = '两次输入的新密码不一致'
    return
  }

  emailSaving.value = true
  try {
    await resetPassword(emailForm.value.email.trim(), emailForm.value.code, passResult.value)
    emailForm.value = { email: emailForm.value.email.trim(), code: '', newPassword: '', confirmPassword: '' }
    emailSuccess.value = '密码修改成功'
    clearCodeTimer()
    toast.success('密码修改成功')
  } catch (e) {
    emailError.value = e.message || '修改失败'
  } finally {
    emailSaving.value = false
  }
}

// ── Logout ──
const { confirm: showConfirm } = useConfirm()
const handleLogout = async () => {
  if (!await showConfirm('确定要退出登录吗？')) return
  emit('logout')
}

onUnmounted(() => {
  clearCodeTimer()
})
</script>

<template>
  <div class="w-full space-y-6">
    <div>
      <h3 class="text-lg font-semibold text-foreground">账户安全</h3>
      <p class="text-sm text-muted-foreground mt-1">管理你的账户安全设置</p>
    </div>

    <!-- Card 1: 修改密码 -->
    <div class="rounded-xl border bg-card p-6 space-y-4">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h4 class="text-sm font-semibold text-foreground">修改密码</h4>
          <p class="text-xs text-muted-foreground mt-1">选择当前密码或邮箱验证码完成验证</p>
        </div>
        <Tabs v-model="changeMethod" class="shrink-0">
          <TabsList>
            <TabsTrigger value="current">当前密码</TabsTrigger>
            <TabsTrigger value="email">邮箱验证码</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <div v-if="changeMethod === 'current'" class="space-y-3">
        <div>
          <Label class="text-xs font-semibold text-muted-foreground mb-1.5">当前密码</Label>
          <Input v-model="passwordForm.currentPassword" type="password" placeholder="输入当前密码" autocomplete="current-password" :disabled="passwordSaving" />
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <div>
            <Label class="text-xs font-semibold text-muted-foreground mb-1.5">新密码</Label>
            <Input v-model="passwordForm.newPassword" type="password" placeholder="输入新密码" autocomplete="new-password" :disabled="passwordSaving" />
          </div>
          <div>
            <Label class="text-xs font-semibold text-muted-foreground mb-1.5">确认新密码</Label>
            <Input v-model="passwordForm.confirmPassword" type="password" placeholder="再次输入新密码" autocomplete="new-password" :disabled="passwordSaving" />
          </div>
        </div>

        <Button
          variant="outline"
          size="sm"
          @click="handlePasswordChange"
          :disabled="passwordSaving || !passwordForm.currentPassword || passwordForm.newPassword.length < 8 || passwordForm.confirmPassword.length < 8"
        >
          {{ passwordSaving ? '修改中...' : '修改密码' }}
        </Button>
        <p v-if="passwordSuccess" class="text-xs text-emerald-600 dark:text-emerald-400">{{ passwordSuccess }}</p>
        <p v-if="passwordError" class="text-xs text-destructive">{{ passwordError }}</p>
      </div>

      <div v-else class="space-y-3">
        <div>
          <Label class="text-xs font-semibold text-muted-foreground mb-1.5">绑定邮箱</Label>
          <div class="flex gap-2">
            <Input v-model="emailForm.email" type="email" placeholder="your@email.com" autocomplete="email" :disabled="emailSaving" />
            <Button variant="outline" size="sm" class="whitespace-nowrap" @click="handleSendEmailCode" :disabled="codeSending || codeCooldown > 0 || !emailForm.email.trim()">
              {{ codeCooldown > 0 ? `${codeCooldown}s` : (codeSending ? '发送中...' : '发送验证码') }}
            </Button>
          </div>
        </div>
        <div>
          <Label class="text-xs font-semibold text-muted-foreground mb-1.5">验证码</Label>
          <Input v-model="emailForm.code" type="text" maxlength="6" placeholder="6位数字" :disabled="emailSaving" />
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <div>
            <Label class="text-xs font-semibold text-muted-foreground mb-1.5">新密码</Label>
            <Input v-model="emailForm.newPassword" type="password" placeholder="输入新密码" autocomplete="new-password" :disabled="emailSaving" />
          </div>
          <div>
            <Label class="text-xs font-semibold text-muted-foreground mb-1.5">确认新密码</Label>
            <Input v-model="emailForm.confirmPassword" type="password" placeholder="再次输入新密码" autocomplete="new-password" :disabled="emailSaving" />
          </div>
        </div>

        <Button
          variant="outline"
          size="sm"
          @click="handleEmailPasswordChange"
          :disabled="emailSaving || !emailForm.email.trim() || emailForm.code.length < 6 || emailForm.newPassword.length < 8 || emailForm.confirmPassword.length < 8"
        >
          {{ emailSaving ? '修改中...' : '修改密码' }}
        </Button>
        <p v-if="emailSuccess" class="text-xs text-emerald-600 dark:text-emerald-400">{{ emailSuccess }}</p>
        <p v-if="emailError" class="text-xs text-destructive">{{ emailError }}</p>
      </div>
    </div>

    <!-- Card 2: 退出登录 -->
    <div class="rounded-xl border bg-card p-6">
      <Button
        variant="outline"
        @click="handleLogout"
        class="border-destructive/50 text-destructive hover:bg-destructive/5 hover:text-destructive"
      >
        退出登录
      </Button>
    </div>
  </div>
</template>
