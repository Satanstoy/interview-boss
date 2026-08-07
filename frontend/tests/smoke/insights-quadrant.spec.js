import { expect, test } from '@playwright/test'

// 洞察总览 · 四象限决策图 smoke 测试
// mock /api/insights + /api/insights/practice-activity，断言四象限图渲染与象限文案
// 文本断言为主（禁截图），验证「岗位重点知识」四象限决策图正常挂载。

const MOCK_SNAPSHOT = {
  version: 1,
  target_position: { name: '测试岗位', source: 'position_id' },
  summary: {
    question_count: 10,
    jd_count: 1,
    interview_count: 1,
    practiced_question_count: 3,
    evaluated_answer_count: 2,
    evidence_state: 'available',
  },
  actions: [],
  readiness: {
    items: [
      // 重点突破：高热度 + 未练
      { id: 't1', name: 'RAG系统设计', question_count: 3, question_frequency: 9, practice_count: 0, average_score: null, status: 'not_started', reason: '题库覆盖充分，但还没有个人练习证据。' },
      // 优势：高热度 + 熟练
      { id: 't2', name: 'Agent架构', question_count: 2, question_frequency: 8, practice_count: 3, average_score: 88, status: 'stable', reason: '练习平均分达到 80 以上' },
      // 可保持：低热度 + 熟练
      { id: 't3', name: '算法手撕', question_count: 2, question_frequency: 2, practice_count: 2, average_score: 82, status: 'stable', reason: '练习平均分达到 80 以上' },
      // 不急：低热度 + 未练
      { id: 't4', name: '操作系统', question_count: 3, question_frequency: 1, practice_count: 0, average_score: null, status: 'not_started', reason: '题库覆盖充分，但还没有个人练习证据。' },
    ],
  },
  reviews: { total: 0, items: [] },
  data_quality: { unassigned_question_count: 0, has_practice_evidence: true, message: '' },
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

test('insights overview renders quadrant decision chart', async ({ page }) => {
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

  // 四象限决策图区块（岗位重点知识）出现在最前
  await expect(page.getByRole('heading', { name: /岗位重点知识/ })).toBeVisible()

  // 图例渲染 4 个象限（在四象限卡片内，完整文本避免与描述文案撞词）
  const quadCard = page.getByTestId('quadrant-card')
  await expect(quadCard.getByText(/重点突破 · 高热度但没练好/)).toBeVisible()
  await expect(quadCard.getByText(/优势 · 高热度又熟练/)).toBeVisible()
  await expect(quadCard.getByText(/可保持 · 熟练但岗位热度低/)).toBeVisible()
  await expect(quadCard.getByText(/不急 · 热度低也没练/)).toBeVisible()

  // 组件容器渲染出 ECharts canvas（四象限图主体）
  const canvas = page.locator('.quad-chart-canvas')
  await expect(canvas).toHaveCount(1)
  await expect(canvas.locator('canvas').first()).toBeVisible()
})
