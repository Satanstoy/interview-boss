// 纯格式化工具函数（从 ChatView.vue 抽出，零 Vue/业务依赖）
// 遵循 utils 规范：纯函数、无副作用、不 import services/composables。

const STEP_TEXT_MAP = {
  retrieve: '检索相关题目...',
  evaluate: '评估答案...',
  generate: '生成回答...',
  generating: '正在组织面试官回复...',
  search: '搜索知识库...',
  analyze: '分析问题...',
  think: '深度思考...',
  load_skill: '正在加载面试策略...',
  search_questions: '正在检索相关面试题...',
  draw_questions: '正在从题库抽题...',
  'project-deep-dive': '正在切换到项目深挖...',
  'algorithm-coding': '正在切换到算法面试...',
  'interview-rhythm': '正在调整面试节奏...',
  'theory-qa': '正在准备理论追问...',
  'hr-soft-skills': '正在准备软技能追问...',
  'adaptive-difficulty': '正在调整题目难度...',
}

export function createClientRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function formatGroupTime(date) {
  const now = new Date()
  const diff = now - date
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  if (hours < 24) return `${hours} 小时前`
  if (days < 7) return `${days} 天前`
  return date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })
}

export function formatRelativeTime(ts) {
  if (!ts) return ''
  const d = new Date(ts + (ts.includes('Z') || ts.includes('+') ? '' : 'Z'))
  const now = new Date()
  const diff = now - d
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

export function waitingStepText(step) {
  return STEP_TEXT_MAP[step] || ''
}
