<script setup>
import { ref, onMounted } from 'vue'
import { AlertTriangle, Check, Copy, KeyRound, RefreshCw, Server, Trash2 } from '@lucide/vue'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import { fetchMyMCPConfig, rotateMyMCPToken, revokeMyMCPToken } from '@/services/profileApi.js'
import { Button } from '@/components/ui/button'

const { success: toastSuccess, error: toastError } = useToast()
const { confirm: showConfirm } = useConfirm()

const loading = ref(true)
const working = ref(false)
const settings = ref(null)
const issuedToken = ref('')
const issuedConfig = ref('')
const issuedStdioConfig = ref('')
const copied = ref('')

const loadConfig = async () => {
  loading.value = true
  try {
    settings.value = await fetchMyMCPConfig()
  } catch (error) {
    toastError(`加载 MCP 配置失败：${error.message}`)
  } finally {
    loading.value = false
  }
}

const issueToken = async () => {
  const hadToken = Boolean(settings.value?.configured)
  if (hadToken) {
    const confirmed = await showConfirm(
      '重置后，之前复制给外部 agent 的 Token 会立即失效，需要重新配置。确定继续吗？',
      { title: '重置 MCP Token', confirmLabel: '重置 Token' },
    )
    if (!confirmed) return
  }

  working.value = true
  try {
    const result = await rotateMyMCPToken()
    settings.value = result
    issuedToken.value = result.token || ''
    issuedConfig.value = result.config_json || ''
    issuedStdioConfig.value = result.stdio_config_json || ''
    toastSuccess(hadToken ? 'MCP Token 已重置，请立即复制保存' : 'MCP Token 已生成，请立即复制保存')
  } catch (error) {
    toastError(`生成 MCP Token 失败：${error.message}`)
  } finally {
    working.value = false
  }
}

const revokeToken = async () => {
  const confirmed = await showConfirm(
    '撤销后外部 agent 将无法访问题库，直到你重新生成 Token。确定撤销吗？',
    { title: '撤销 MCP 访问', confirmLabel: '撤销 Token', variant: 'destructive' },
  )
  if (!confirmed) return

  working.value = true
  try {
    await revokeMyMCPToken()
    issuedToken.value = ''
    issuedConfig.value = ''
    issuedStdioConfig.value = ''
    await loadConfig()
    toastSuccess('MCP Token 已撤销')
  } catch (error) {
    toastError(`撤销 MCP Token 失败：${error.message}`)
  } finally {
    working.value = false
  }
}

const copyText = async (value, name) => {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
    copied.value = name
    window.setTimeout(() => { if (copied.value === name) copied.value = '' }, 1800)
  } catch {
    toastError('复制失败，请手动选择文本复制')
  }
}

const formatDate = (value) => value ? value.replace('T', ' ').slice(0, 16) : '—'

onMounted(loadConfig)
</script>

<template>
  <div class="w-full space-y-8">
    <div>
      <h3 class="text-lg font-semibold text-foreground">MCP 接入</h3>
      <p class="mt-1 text-sm text-muted-foreground">让外部 agent 调用你的题库搜索、抽题和选题能力</p>
    </div>

    <div v-if="loading" class="rounded-xl border bg-card p-8 text-center">
      <div class="mx-auto size-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
    </div>

    <template v-else>
      <div class="rounded-xl border bg-card p-6 space-y-5">
        <div class="flex items-start gap-3">
          <div class="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Server class="size-5" />
          </div>
          <div class="min-w-0 flex-1">
            <h4 class="text-sm font-semibold text-foreground">Streamable HTTP 服务</h4>
            <p class="mt-1 text-xs leading-5 text-muted-foreground">
              一个账户只保留一个 Token。重置后旧 Token 立即失效；服务端只保存 Token 哈希。
            </p>
          </div>
          <span
            class="shrink-0 rounded-full px-2.5 py-1 text-xs font-medium"
            :class="settings?.configured ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400' : 'bg-muted text-muted-foreground'"
          >
            {{ settings?.configured ? '已启用' : '未启用' }}
          </span>
        </div>

        <div class="space-y-1.5">
          <div class="flex items-center justify-between gap-3">
            <span class="text-xs font-semibold text-muted-foreground">MCP Endpoint</span>
            <Button variant="ghost" size="sm" class="h-7 gap-1.5" @click="copyText(settings?.endpoint, 'endpoint')">
              <Check v-if="copied === 'endpoint'" class="size-3.5 text-emerald-500" />
              <Copy v-else class="size-3.5" />
              {{ copied === 'endpoint' ? '已复制' : '复制' }}
            </Button>
          </div>
          <code class="block break-all rounded-md bg-muted px-3 py-2 text-xs text-foreground">{{ settings?.endpoint }}</code>
        </div>

        <div v-if="settings?.configured" class="grid gap-3 text-xs text-muted-foreground sm:grid-cols-2">
          <div>当前 Token：<code class="text-foreground">{{ settings.token_hint }}</code></div>
          <div>最近轮换：<code class="text-foreground">{{ formatDate(settings.rotated_at) }}</code></div>
        </div>

        <div v-if="settings?.warning" class="flex items-start gap-2 rounded-lg border border-amber-300/70 bg-amber-50 p-3 text-xs leading-5 text-amber-800 dark:border-amber-800/60 dark:bg-amber-950/20 dark:text-amber-300">
          <AlertTriangle class="mt-0.5 size-4 shrink-0" />
          <span>{{ settings.warning }}</span>
        </div>

        <div class="flex flex-wrap gap-2">
          <Button class="gap-2" :disabled="working" @click="issueToken">
            <RefreshCw class="size-4" :class="working ? 'animate-spin' : ''" />
            {{ settings?.configured ? '重置 Token' : '生成 Token' }}
          </Button>
          <Button v-if="settings?.configured" variant="outline" class="gap-2 text-destructive hover:text-destructive" :disabled="working" @click="revokeToken">
            <Trash2 class="size-4" />
            撤销访问
          </Button>
        </div>
      </div>

      <div v-if="issuedToken" class="rounded-xl border border-primary/30 bg-primary/5 p-6 space-y-5">
        <div class="flex items-start gap-3">
          <KeyRound class="mt-0.5 size-5 shrink-0 text-primary" />
          <div>
            <h4 class="text-sm font-semibold text-foreground">新 Token 只在这里返回</h4>
            <p class="mt-1 text-xs leading-5 text-muted-foreground">请复制到外部 agent 的 MCP 配置中。刷新页面后不会再次显示完整 Token。</p>
          </div>
        </div>

        <div class="space-y-1.5">
          <div class="flex items-center justify-between gap-3">
            <span class="text-xs font-semibold text-muted-foreground">Bearer Token</span>
            <Button variant="outline" size="sm" class="h-7 gap-1.5" @click="copyText(issuedToken, 'token')">
              <Check v-if="copied === 'token'" class="size-3.5 text-emerald-500" />
              <Copy v-else class="size-3.5" />
              {{ copied === 'token' ? '已复制' : '复制 Token' }}
            </Button>
          </div>
          <code class="block break-all rounded-md border bg-background px-3 py-2 text-xs text-foreground">{{ issuedToken }}</code>
        </div>

        <div class="space-y-1.5">
          <div class="flex items-center justify-between gap-3">
            <span class="text-xs font-semibold text-muted-foreground">远程 HTTP 配置 JSON（优先）</span>
            <Button variant="outline" size="sm" class="h-7 gap-1.5" @click="copyText(issuedConfig, 'config')">
              <Check v-if="copied === 'config'" class="size-3.5 text-emerald-500" />
              <Copy v-else class="size-3.5" />
              {{ copied === 'config' ? '已复制' : '复制配置' }}
            </Button>
          </div>
          <pre class="max-h-64 overflow-auto rounded-md border bg-background p-3 text-xs leading-5 text-foreground">{{ issuedConfig }}</pre>
        </div>

        <div v-if="issuedStdioConfig" class="space-y-1.5">
          <div class="flex items-center justify-between gap-3">
            <span class="text-xs font-semibold text-muted-foreground">npx 兼容配置 JSON（仅支持 stdio 的 agent）</span>
            <Button variant="outline" size="sm" class="h-7 gap-1.5" @click="copyText(issuedStdioConfig, 'stdio-config')">
              <Check v-if="copied === 'stdio-config'" class="size-3.5 text-emerald-500" />
              <Copy v-else class="size-3.5" />
              {{ copied === 'stdio-config' ? '已复制' : '复制配置' }}
            </Button>
          </div>
          <p class="text-xs leading-5 text-muted-foreground">需要本机安装 Node.js 18+。npx 本身不需要申请证书；HTTP 仅建议用于内网、VPN 或安全隧道。</p>
          <pre class="max-h-64 overflow-auto rounded-md border bg-background p-3 text-xs leading-5 text-foreground">{{ issuedStdioConfig }}</pre>
        </div>
      </div>

      <div class="rounded-xl border bg-card p-6">
        <h4 class="text-sm font-semibold text-foreground">接入步骤</h4>
        <ol class="mt-3 list-decimal space-y-2 pl-5 text-xs leading-5 text-muted-foreground">
          <li>生成 Token：支持远程 HTTP 的 agent 复制第一份 JSON；只支持 stdio 的 agent 复制 npx JSON。</li>
          <li>npx 配置会把 Token 放在本机环境变量中，保持 <code class="text-foreground">Authorization: Bearer ...</code> 认证。</li>
          <li>连接初始化时会自动加载 InterviewBoss 的 MCP 工具使用 skill，无需另行安装；领域技能会按需加载。</li>
          <li>连接后，agent 可以按岗位传入 <code class="text-foreground">job_position</code>，再调用搜索、抽题和选题工具。</li>
        </ol>
      </div>
    </template>
  </div>
</template>
