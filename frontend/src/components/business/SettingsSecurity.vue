<script setup>
import { ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const emit = defineEmits(['logout'])

// ── Password change (placeholder UI) ──
const passwordForm = ref({
  currentPassword: '',
  newPassword: '',
  confirmPassword: '',
})

const passwordError = ref('')

const handlePasswordChange = () => {
  passwordError.value = '该功能正在开发中，敬请期待'
}

// ── Logout ──
const handleLogout = () => {
  emit('logout')
}
</script>

<template>
  <div class="space-y-8 max-w-2xl">
    <div>
      <h3 class="text-lg font-semibold text-foreground">账户安全</h3>
      <p class="text-sm text-muted-foreground mt-1">管理你的账户安全设置</p>
    </div>

    <!-- Card 1: 修改密码 -->
    <div class="rounded-xl border bg-card p-6 space-y-4">
      <h4 class="text-sm font-semibold text-foreground">修改密码</h4>

      <div class="space-y-3">
        <div>
          <Label class="text-xs font-semibold text-muted-foreground mb-1.5">当前密码</Label>
          <Input
            v-model="passwordForm.currentPassword"
            type="password"
            placeholder="输入当前密码"
          />
        </div>
        <div>
          <Label class="text-xs font-semibold text-muted-foreground mb-1.5">新密码</Label>
          <Input
            v-model="passwordForm.newPassword"
            type="password"
            placeholder="输入新密码"
          />
        </div>
        <div>
          <Label class="text-xs font-semibold text-muted-foreground mb-1.5">确认新密码</Label>
          <Input
            v-model="passwordForm.confirmPassword"
            type="password"
            placeholder="再次输入新密码"
          />
        </div>
      </div>

      <Button variant="outline" size="sm" @click="handlePasswordChange" disabled>
        修改密码
      </Button>
      <p class="text-xs text-muted-foreground">功能开发中</p>
      <p v-if="passwordError" class="text-xs text-destructive">{{ passwordError }}</p>
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
