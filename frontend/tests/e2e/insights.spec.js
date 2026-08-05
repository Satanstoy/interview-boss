import { expect, test } from '@playwright/test'

const insightsSnapshot = {
  version: 1,
  target_position: { name: '大模型应用开发', source: 'user_position' },
  summary: {
    question_count: 268,
    jd_count: 9,
    interview_count: 46,
    practiced_question_count: 0,
    evaluated_answer_count: 0,
    evidence_state: 'insufficient',
  },
  actions: [
    {
      id: 'topic:RAG系统设计',
      title: 'RAG系统设计',
      description: '题库覆盖充分，但还没有个人练习证据。',
      question_count: 25,
      priority: 'high',
      action: '开始练习',
    },
  ],
  readiness: {
    items: [
      {
        id: 'RAG系统设计',
        name: 'RAG系统设计',
        question_count: 25,
        question_frequency: 35,
        practice_count: 0,
        average_score: null,
        status: 'not_started',
        reason: '尚无个人练习记录',
      },
    ],
  },
  reviews: { total: 0, items: [] },
  data_quality: {
    unassigned_question_count: 0,
    has_practice_evidence: false,
    message: '当前没有结构化练习评分，准备度仅基于岗位和题库事实。',
  },
}

const practiceActivity = {
  version: 1,
  heatmap: Array.from({ length: 90 }, (_, i) => ({
    date: `2026-05-${String((i % 28) + 1).padStart(2, '0')}`,
    count: i % 7 === 0 ? 3 : 0,
    avg_score: i % 7 === 0 ? 78 : 0,
  })),
  streak: { current: 3, longest: 5 },
  trend: Array.from({ length: 30 }, (_, i) => ({
    date: `2026-07-${String((i % 28) + 1).padStart(2, '0')}`,
    count: i % 3 === 0 ? 2 : 0,
    avg_score: i % 3 === 0 ? 80 : 0,
  })),
  radar: [{ topic: 'RAG系统设计', proficiency: 80 }],
  difficulty: [
    { difficulty: '简单', count: 6, correct_rate: 83 },
    { difficulty: '中等', count: 3, correct_rate: 67 },
  ],
  recent: [
    {
      id: 1,
      type: 'answer',
      question: 'RAG 的检索阶段如何减少幻觉？',
      difficulty: '中等',
      topic: 'RAG系统设计',
      score: 85,
      rating: null,
      created_at: '2026-08-05 09:30:00',
    },
  ],
}

async function mockInsightsApis(page) {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url()
    const pathname = new URL(url).pathname
    if (!pathname.startsWith('/api/')) {
      await route.continue()
      return
    }
    if (pathname === '/api/insights') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(insightsSnapshot) })
      return
    }
    if (pathname === '/api/insights/practice-activity') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(practiceActivity) })
      return
    }
    if (pathname === '/api/auth/me') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 1, username: '测试用户' }) })
      return
    }
    if (pathname === '/api/auth/refresh') {
      await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: '未登录' }) })
      return
    }
    if (pathname === '/api/knowledge-graph') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ nodes: [], links: [], categories: [] }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: [], items: [], total: 0 }) })
  })
}

test.describe('洞察工作台', () => {
  test.beforeEach(async ({ page }) => {
    await mockInsightsApis(page)
  })

  test('总览展示行动建议并可切换三个洞察 Tab', async ({ page }) => {
    await page.goto('/insights/overview?preview=1')

    await expect(page.getByRole('heading', { name: '洞察总览' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'RAG系统设计' })).toBeVisible()
    await expect(page.getByText('尚未形成个人能力分数')).toBeVisible()

    await expect(page.getByRole('heading', { name: '我的练习足迹' })).toBeVisible()
    await expect(page.getByText('打卡热力图')).toBeVisible()
    await expect(page.getByText('历史最长 5 天')).toBeVisible()
    await expect(page.getByText('今天还没打卡，再刷一题连击 +1')).toBeVisible()
    await expect(page.getByText('最近刷题')).toBeVisible()
    await expect(page.getByText('RAG 的检索阶段如何减少幻觉？')).toBeVisible()

    await page.getByRole('button', { name: '岗位准备度' }).click()
    await expect(page).toHaveURL(/\/insights\/readiness\?preview=1$/)
    await expect(page.locator('section').getByRole('heading', { name: '岗位准备度' })).toBeVisible()

    await page.getByRole('button', { name: '面试复盘' }).click()
    await expect(page).toHaveURL(/\/insights\/reviews\?preview=1$/)
    await expect(page.locator('section').getByRole('heading', { name: '面试复盘' })).toBeVisible()
    await expect(page.getByText('还没有模拟面试记录')).toBeVisible()
  })

  test('旧知识图谱入口保留并落到岗位准备度的图谱视图', async ({ page }) => {
    await page.goto('/knowledge-graph?preview=1')

    await expect(page).toHaveURL(/\/insights\/readiness\?preview=1&view=graph$/)
    await expect(page.locator('section').getByRole('heading', { name: '知识图谱' })).toBeVisible()
    await expect(page.getByText('暂无数据')).toBeVisible()
  })
})
