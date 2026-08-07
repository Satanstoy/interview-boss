import { expect, test } from '@playwright/test'

// 洞察 · 岗位准备度双线雷达 smoke 测试
// mock /api/insights，断言：双线雷达 canvas 渲染 + 其余主题列表 + 能力矩阵折叠
// 文本断言为主（禁截图）。

const MOCK_SNAPSHOT = {
  version: 1,
  target_position: { name: '测试岗位', source: 'position_id' },
  summary: {
    question_count: 10,
    jd_count: 1,
    interview_count: 1,
    practiced_question_count: 2,
    evaluated_answer_count: 2,
    evidence_state: 'available',
  },
  actions: [],
  readiness: {
    items: [
      { id: 't1', name: 'Agent架构与范式', question_count: 4, question_frequency: 62, practice_count: 3, average_score: 82, proficiency: 78, status: 'stable', reason: '练习平均分达到 80 以上' },
      { id: 't2', name: 'RAG系统设计', question_count: 3, question_frequency: 53, practice_count: 2, average_score: 68, proficiency: 62, status: 'developing', reason: '已开始练习' },
      { id: 't3', name: '数据库基础', question_count: 3, question_frequency: 29, practice_count: 0, average_score: null, proficiency: null, status: 'not_started', reason: '尚未练习' },
      { id: 't4', name: '评估安全与优化', question_count: 2, question_frequency: 41, practice_count: 0, average_score: null, proficiency: null, status: 'not_started', reason: '尚未练习' },
      { id: 't5', name: '记忆与上下文管理', question_count: 2, question_frequency: 31, practice_count: 0, average_score: null, proficiency: null, status: 'not_started', reason: '尚未练习' },
      { id: 't6', name: '框架与中间件', question_count: 2, question_frequency: 21, practice_count: 0, average_score: null, proficiency: null, status: 'not_started', reason: '尚未练习' },
      { id: 't7', name: '缓存设计与优化', question_count: 2, question_frequency: 17, practice_count: 0, average_score: null, proficiency: null, status: 'not_started', reason: '尚未练习' },
      { id: 't8', name: '工具调用与协议集成', question_count: 2, question_frequency: 16, practice_count: 0, average_score: null, proficiency: null, status: 'not_started', reason: '尚未练习' },
      { id: 't9', name: '模型与框架选型', question_count: 2, question_frequency: 15, practice_count: 0, average_score: null, proficiency: null, status: 'not_started', reason: '尚未练习' },
      { id: 't10', name: 'Prompt工程', question_count: 2, question_frequency: 10, practice_count: 0, average_score: null, proficiency: null, status: 'not_started', reason: '尚未练习' },
    ],
  },
  high_frequency: [],
  reviews: { total: 0, items: [] },
  data_quality: { unassigned_question_count: 0, has_practice_evidence: true, message: '' },
}

test('insights readiness renders dual-line radar and matrix', async ({ page }) => {
  await page.route('**/api/auth/**', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
  })
  await page.route('**/api/insights**', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SNAPSHOT) })
  })

  await page.goto('/insights/readiness?preview=1')

  // 页面加载出岗位准备度
  await expect(page.getByRole('heading', { name: '岗位准备度' })).toBeVisible()

  // 双线雷达图（ECharts canvas）
  const radar = page.locator('.dual-radar-canvas')
  await expect(radar).toHaveCount(1)
  await expect(radar.locator('canvas').first()).toBeVisible()

  // 其余主题列表（Top8 之外的主题）
  await expect(page.getByRole('heading', { name: /^其余主题$/ })).toBeVisible()
  await expect(page.getByText(/模型与框架选型/)).toBeVisible()
  await expect(page.getByText(/Prompt工程/)).toBeVisible()

  // 能力矩阵折叠区（默认折叠，点击展开）
  await expect(page.getByRole('heading', { name: /能力矩阵/ })).toBeVisible()
  const matrixBtn = page.getByRole('button', { name: /能力矩阵/ })
  await matrixBtn.click()
  await expect(page.getByText(/Agent架构与范式/)).toBeVisible()
})
