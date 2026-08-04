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
    await expect(page.getByText('RAG系统设计')).toBeVisible()
    await expect(page.getByText('尚未形成个人能力分数')).toBeVisible()

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
