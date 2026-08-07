import { expect, test } from '@playwright/test'

// 洞察总览 · 岗位知识地图（技能星图）smoke 测试
// mock /api/insights + /api/insights/practice-activity
// 断言：星图 SVG 渲染（节点 = readiness.items 热度 Top8）+ 覆盖徽标 + 空态
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
  readiness: {
    items: [
      { id: 't1', name: 'Agent架构与范式', question_count: 4, question_frequency: 62, practice_count: 0, average_score: null, status: 'not_started', reason: '尚未练习' },
      { id: 't2', name: 'RAG系统设计', question_count: 3, question_frequency: 53, practice_count: 0, average_score: null, status: 'not_started', reason: '尚未练习' },
      { id: 't3', name: '数据库基础', question_count: 3, question_frequency: 29, practice_count: 0, average_score: null, status: 'not_started', reason: '尚未练习' },
    ],
  },
  high_frequency: [],
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

test('insights overview renders star map with topic nodes', async ({ page }) => {
  await page.route('**/api/auth/**', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
  })
  await page.route('**/api/insights**', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SNAPSHOT) })
  })
  await page.route('**/api/insights/practice-activity**', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_ACTIVITY) })
  })

  await page.goto('/insights/overview?preview=1')

  await expect(page.getByRole('heading', { name: '洞察总览' })).toBeVisible()

  // 岗位知识地图卡 + 星图 SVG（1 hub + 3 节点）
  await expect(page.getByRole('heading', { name: /岗位知识地图/ })).toBeVisible()
  const starCard = page.getByTestId('star-map-card')
  const svg = starCard.locator('svg')
  await expect(svg).toHaveCount(1)
  await expect(svg.locator('circle[data-index]')).toHaveCount(3)
  await expect(svg.locator('text')).toContainText(['Agent架构与范式', 'RAG系统设计', '数据库基础'])

  // 覆盖徽标：已练 0/3
  await expect(starCard.getByText(/已练 0\/3/)).toBeVisible()

  // 空态：无练习数据时热力图空态与引导仍出现
  await expect(page.getByText(/还没有练习记录/).first()).toBeVisible()
})
