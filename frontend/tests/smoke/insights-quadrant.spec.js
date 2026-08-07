import { expect, test } from '@playwright/test'

// 洞察总览 · 岗位高频待练 smoke 测试
// mock /api/insights + /api/insights/practice-activity + /api/practice/decks
// 断言「岗位高频待练」横向条形图渲染 + 今日该刷入口
// 文本断言为主（禁截图）。

const MOCK_SNAPSHOT = {
  version: 1,
  target_position: { name: '测试岗位', source: 'position_id' },
  summary: {
    question_count: 10,
    jd_count: 1,
    interview_count: 1,
    practiced_question_count: 0,
    evaluated_answer_count: 0,
    evidence_state: 'insufficient',
  },
  actions: [],
  readiness: { items: [] },
  high_frequency: [
    { topic: 'Agent架构与范式', frequency: 62 },
    { topic: 'RAG系统设计', frequency: 53 },
    { topic: '评估安全与优化', frequency: 41 },
    { topic: '记忆与上下文管理', frequency: 31 },
  ],
  reviews: { total: 0, items: [] },
  data_quality: { unassigned_question_count: 0, has_practice_evidence: false, message: '' },
}

const MOCK_ACTIVITY = {
  version: 1,
  heatmap: [],
  streak: { current: 0, longest: 0 },
  trend: [],
  radar: [],
  difficulty: [],
  recent: [],
}

test('insights overview renders high-frequency topics and today queue', async ({ page }) => {
  // 认证接口统一 mock（避免真实网络请求）
  await page.route('**/api/auth/**', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
  })
  await page.route('**/api/insights**', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SNAPSHOT) })
  })
  await page.route('**/api/insights/practice-activity**', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_ACTIVITY) })
  })

  // ?preview=1 绕过路由 requiresAuth 守卫（项目预留预览旁路）
  await page.goto('/insights/overview?preview=1')

  // 页面加载出洞察总览
  await expect(page.getByRole('heading', { name: '洞察总览' })).toBeVisible()

  // 岗位高频待练区块
  await expect(page.getByRole('heading', { name: /岗位高频待练/ })).toBeVisible()

  // 一句话洞察（未练提示 + 高频主题，真实 DOM 文本）
  const hfCard = page.getByTestId('high-freq-card')
  await expect(hfCard.getByText(/还没有练习记录/)).toBeVisible()
  await expect(hfCard.getByText(/Agent架构/)).toBeVisible()
  await expect(hfCard.getByText(/RAG系统设计/)).toBeVisible()

  // 高频图组件渲染出 ECharts canvas（横向条形图主体）
  const canvas = page.locator('.high-freq-canvas')
  await expect(canvas).toHaveCount(1)
  await expect(canvas.locator('canvas').first()).toBeVisible()
})
