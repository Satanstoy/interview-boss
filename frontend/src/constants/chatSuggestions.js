// 聊天开场建议（从 ChatView.vue 抽出）
import { MessageSquare, Briefcase } from '@lucide/vue'

export const promptSuggestions = [
  {
    icon: MessageSquare,
    text: '自由练习',
    title: '自由练习',
    description: '从题库随机抽题，按你的节奏练习',
    mode: 'free_practice',
  },
  {
    icon: Briefcase,
    text: '定制面试',
    title: '定制面试',
    description: '结合目标 JD 和简历，模拟岗位面试',
    mode: 'jd_resume',
  },
]
