<script setup>
import { computed, ref, onMounted } from 'vue'
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

const agentConfigPrompt = computed(() => {
  const endpoint = settings.value?.endpoint
  const token = issuedToken.value
  if (!endpoint || !token) return ''

  return [
    '请帮我配置 InterviewBoss MCP，并完成一次连接测试。',
    '服务名称：interview-boss',
    '传输协议：Streamable HTTP',
    `MCP 地址：${endpoint}`,
    `Authorization：Bearer ${token}`,
    '连接后请加载 InterviewBoss 的 interview-tool-use skill，按岗位使用题库搜索、抽题和选题工具。',
  ].join('\n')
})

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
            <span class="text-xs font-semibold text-muted-foreground">MCP 地址</span>
            <Button variant="ghost" size="sm" class="h-7 gap-1.5" @click="copyText(settings?.endpoint, 'endpoint')">
              <Check v-if="copied === 'endpoint'" class="size-3.5 text-emerald-500" />
              <Copy v-else class="size-3.5" />
              {{ copied === 'endpoint' ? '已复制地址' : '复制 MCP 地址' }}
            </Button>
          </div>
          <code class="block break-all rounded-md bg-muted px-3 py-2 text-xs text-foreground">{{ settings?.endpoint }}</code>
        </div>

        <div class="space-y-1.5">
          <div class="flex items-center justify-between gap-3">
            <span class="text-xs font-semibold text-muted-foreground">访问 Token</span>
            <div class="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                class="h-7 gap-1.5"
                :disabled="!issuedToken || working"
                title="完整 Token 只在生成或重置后可复制"
                @click="copyText(issuedToken, 'token')"
              >
                <Check v-if="copied === 'token'" class="size-3.5 text-emerald-500" />
                <Copy v-else class="size-3.5" />
                {{ copied === 'token' ? '已复制 Token' : '复制 Token' }}
              </Button>
              <Button variant="outline" size="sm" class="h-7 gap-1.5" :disabled="working" @click="issueToken">
                <RefreshCw class="size-3.5" :class="working ? 'animate-spin' : ''" />
                {{ settings?.configured ? '重置 Token' : '生成 Token' }}
              </Button>
            </div>
          </div>
          <code class="block min-h-10 break-all rounded-md bg-muted px-3 py-2 text-xs leading-5 text-foreground">
            {{ settings?.configured ? settings.token_hint : '尚未生成 Token' }}
          </code>
          <p class="text-xs leading-5 text-muted-foreground">
            完整 Token 不会直接显示；生成或重置后，点击右侧“复制 Token”即可复制。刷新页面后如需再次获取，请重置 Token。
          </p>
        </div>

        <div v-if="settings?.configured" class="grid gap-3 text-xs text-muted-foreground sm:grid-cols-2">
          <div>最近轮换：<code class="text-foreground">{{ formatDate(settings.rotated_at) }}</code></div>
          <div>服务状态：<code class="text-foreground">已启用</code></div>
        </div>

        <div v-if="settings?.warning" class="flex items-start gap-2 rounded-lg border border-amber-300/70 bg-amber-50 p-3 text-xs leading-5 text-amber-800 dark:border-amber-800/60 dark:bg-amber-950/20 dark:text-amber-300">
          <AlertTriangle class="mt-0.5 size-4 shrink-0" />
          <span>{{ settings.warning }}</span>
        </div>

        <div v-if="settings?.configured" class="flex flex-wrap gap-2">
          <Button variant="outline" class="gap-2 text-destructive hover:text-destructive" :disabled="working" @click="revokeToken">
            <Trash2 class="size-4" />
            撤销访问
          </Button>
        </div>
      </div>

      <div v-if="issuedToken" class="rounded-xl border border-primary/30 bg-primary/5 p-6 space-y-5">
        <div class="flex items-start gap-3">
          <KeyRound class="mt-0.5 size-5 shrink-0 text-primary" />
          <div>
            <h4 class="text-sm font-semibold text-foreground">可选配置格式</h4>
            <p class="mt-1 text-xs leading-5 text-muted-foreground">需要 JSON 的 agent 可以直接复制配置；配置内容包含 Token，请只粘贴到可信的 agent 设置中。</p>
          </div>
        </div>

        <div class="space-y-1.5">
          <div class="flex items-center justify-between gap-3">
            <span class="text-xs font-semibold text-muted-foreground">远程 HTTP 配置 JSON（优先）</span>
            <Button variant="outline" size="sm" class="h-7 gap-1.5" @click="copyText(issuedConfig, 'config')">
              <Check v-if="copied === 'config'" class="size-3.5 text-emerald-500" />
              <Copy v-else class="size-3.5" />
              {{ copied === 'config' ? '已复制配置' : '复制配置' }}
            </Button>
          </div>
        </div>

        <div v-if="issuedStdioConfig" class="space-y-1.5">
          <div class="flex items-center justify-between gap-3">
            <span class="text-xs font-semibold text-muted-foreground">npx 兼容配置 JSON（仅支持 stdio 的 agent）</span>
            <Button variant="outline" size="sm" class="h-7 gap-1.5" @click="copyText(issuedStdioConfig, 'stdio-config')">
              <Check v-if="copied === 'stdio-config'" class="size-3.5 text-emerald-500" />
              <Copy v-else class="size-3.5" />
              {{ copied === 'stdio-config' ? '已复制配置' : '复制配置' }}
            </Button>
          </div>
          <p class="text-xs leading-5 text-muted-foreground">需要本机安装 Node.js 18+。npx 本身不需要申请证书；HTTP 仅建议用于内网、VPN 或安全隧道。</p>
        </div>
      </div>

      <div class="rounded-xl border bg-card p-6">
        <h4 class="text-sm font-semibold text-foreground">如何给 agent 配置 MCP</h4>
        <ol class="mt-3 list-decimal space-y-2 pl-5 text-xs leading-5 text-muted-foreground">
          <li>先生成 Token，然后复制上方的 <strong class="font-semibold text-foreground">MCP 地址</strong> 和 <strong class="font-semibold text-foreground">访问 Token</strong>。</li>
          <li>在 agent 的 MCP 设置中新增一个 <strong class="font-semibold text-foreground">Streamable HTTP</strong> 服务：URL 填 MCP 地址，认证 Header 填 <code class="text-foreground">Authorization: Bearer 你的 Token</code>。</li>
          <li>如果 agent 支持直接粘贴 MCP JSON，可复制上面的远程 HTTP 配置；只支持 stdio 的 agent 才使用 npx 配置 JSON。</li>
          <li>连接初始化时会自动加载 InterviewBoss 的 MCP 工具使用 skill，无需另行安装；领域技能会按需加载。</li>
          <li>连接后，agent 可以按岗位传入 <code class="text-foreground">job_position</code>，再调用搜索、抽题和选题工具。</li>
        </ol>
        <div class="mt-4 flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            class="gap-2"
            :disabled="!agentConfigPrompt || working"
            title="生成或重置 Token 后可复制完整配置 Prompt"
            @click="copyText(agentConfigPrompt, 'prompt')"
          >
            <Check v-if="copied === 'prompt'" class="size-4 text-emerald-500" />
            <Copy v-else class="size-4" />
            {{ copied === 'prompt' ? '已复制配置 Prompt' : '复制给 Agent 的配置 Prompt' }}
          </Button>
          <span v-if="!issuedToken" class="text-xs text-muted-foreground">请先生成或重置 Token，才能复制包含认证信息的 Prompt。</span>
        </div>
      </div>
    </template>
  </div>
</template>
