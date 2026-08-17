import { expect, test } from '@playwright/test'

const overviewPayload = {
  counts: { completed: 2, running: 1, queued: 0, created: 0, failed: 0, cancelled: 0 },
  human_reviews: {
    total: 3,
    comparison_groups: [
      {
        comparison_group: 'release-ab-2026-08',
        run_a_id: 11,
        run_b_id: 12,
        run_a_target_release_key: 'interview-agent@1.0',
        run_b_target_release_key: 'interview-agent@1.1',
        review_count: 3,
        a_wins: 2,
        b_wins: 1,
        ties: 0,
        both_fail: 0,
      },
    ],
  },
}

const releasesPayload = {
  releases: [
    { id: 1, release_key: 'interview-agent@1.0', release_type: 'target', target_type: 'interview', status: 'published', version: '1.0', manifest: { workflow: 'chat-interview', model: 'target-model' } },
    { id: 2, release_key: 'interview-eval@1.0', release_type: 'evaluation', target_type: 'interview', status: 'published', version: '1.0', judge_model: 'fixed-judge', manifest: { benchmark: { suite_key: 'interview-e2e-suite' }, judge: { model: 'fixed-judge' }, simulator_harness: { version: '1.0' }, candidate_simulator: { model: 'candidate-model' }, tool_evaluation: { enabled: true }, intent_evaluation: { enabled: true } } },
  ],
}

const runsPayload = {
  runs: [
    {
      id: 12,
      status: 'completed',
      target_release_key: 'interview-agent@1.0',
      evaluation_release_key: 'interview-eval@1.0',
      completed_items: 60,
      total_items: 60,
      created_at: '2026-08-17T10:00:00Z',
    },
  ],
}

const benchmarksPayload = {
  suites: [
    {
      id: 1,
      release_key: 'interview-eval@1.0',
      evaluation_release_key: 'interview-eval@1.0',
      release_status: 'published',
      description: '模拟面试的固定 E2E 场景。',
      target_type: 'interview',
      judge_model: 'fixed-judge',
      manifest: { tool_evaluation: { enabled: true }, intent_evaluation: { enabled: true } },
      cases: [],
    },
  ],
}

async function mockEvaluationApis(page) {
  await page.route('**/api/admin/evals/overview', route => route.fulfill({ json: overviewPayload }))
  await page.route('**/api/admin/evals/releases**', route => route.fulfill({ json: releasesPayload }))
  await page.route('**/api/admin/evals/runs**', route => route.fulfill({ json: runsPayload }))
  await page.route('**/api/admin/evals/benchmarks', route => route.fulfill({ json: benchmarksPayload }))
  await page.route('**/api/admin/evals/reviews**', route => route.fulfill({ json: { reviews: [] } }))
  await page.route('**/api/auth/**', route => {
    if (route.request().url().includes('/api/auth/refresh')) {
      return route.fulfill({ json: { token: 'mock-token', user: { id: 1, username: 'admin', is_admin: true } } })
    }
    return route.fulfill({ json: { id: 1, username: 'admin', is_admin: true } })
  })
  await page.route('**/api/data/**', route => route.fulfill({ json: [] }))
  await page.route('**/api/analytics**', route => route.fulfill({ json: {} }))
  await page.route('**/api/practice/**', route => route.fulfill({ json: [] }))
  await page.route('**/api/profile**', route => route.fulfill({ json: { positions: [] } }))
  await page.route('**/api/interview**', route => route.fulfill({ json: [] }))
  await page.route('**/api/coding/**', route => route.fulfill({ json: [] }))
  await page.route('**/api/knowledge**', route => route.fulfill({ json: { nodes: [], edges: [] } }))
  await page.route('**/api/admin/**', route => {
    if (route.request().url().includes('/api/admin/evals/')) return route.fallback()
    return route.fulfill({ json: [] })
  })
}

test.describe('评测中心可读性', () => {
  test.beforeEach(async ({ page }) => {
    await mockEvaluationApis(page)
  })

  test('可视化展示运行状态和人工 A/B 汇总', async ({ page }) => {
    await page.goto('/admin/evals/overview?preview=1')

    await expect(page.getByRole('heading', { name: '测评可视化' })).toBeVisible({ timeout: 15000 })
    await expect(page.getByText('人工 A/B 汇总')).toBeVisible()
    await expect(page.getByText('release-ab-2026-08')).toBeVisible()
    await expect(page.getByText('A 胜 2')).toBeVisible()
    await expect(page.getByRole('button', { name: '开始一次完整评测' }).first()).toBeVisible()
  })

  test('评测结果独立承载 Run 进度', async ({ page }) => {
    await page.goto('/admin/evals/results?preview=1')

    await expect(page.getByRole('heading', { name: '评测结果' })).toBeVisible()
    await expect(page.getByText('最近评测运行')).toBeVisible()
    await expect(page.getByText('评测 #12')).toBeVisible()
  })

  test('流程导航按五步顺序排列', async ({ page }) => {
    await page.goto('/admin/evals/releases?preview=1')

    const flowSteps = page.locator('[aria-label="评测中心流程位置"] > div')
    await expect(flowSteps.first()).toBeVisible({ timeout: 15000 })
    const labels = await flowSteps.allTextContents()
    const evaluationLabels = ['版本与发布', 'Benchmark', '测评实验', '评测结果', '人工 A/B']
    const positions = evaluationLabels.map(label => labels.findIndex(text => text.includes(label)))

    expect(positions.every(position => position >= 0)).toBeTruthy()
    expect(positions).toEqual([...positions].sort((a, b) => a - b))
  })

  test('实验页按步骤解释配置项', async ({ page }) => {
    await page.goto('/admin/evals/experiments?preview=1')

    await expect(page.getByRole('heading', { name: '发起一次评测' })).toBeVisible()
    await expect(page.getByText('第 1 步：选择被测版本')).toBeVisible()
    await expect(page.getByText('第 2 步：选择完整评测版本')).toBeVisible()
    await expect(page.getByText('第 3 步：固定运行参数')).toBeVisible()
    await expect(page.getByText('每个 Case 重跑次数')).toBeVisible()
    await expect(page.getByRole('button', { name: '创建并开始评测' })).toBeVisible()
    await expect(page.locator('#eval-release')).toHaveValue('2')
    await expect(page.getByText('工具调用效果')).toBeVisible()
    await expect(page.getByText('意图识别效果')).toBeVisible()
  })

  test('评测对象明确展示已接入的目标类型', async ({ page }) => {
    await page.goto('/admin/evals/experiments?preview=1')

    await expect(page.getByText('评测对象')).toBeVisible()
    await expect(page.getByRole('button', { name: /模拟面试 Agent/ })).toBeVisible()
    await expect(page.getByText('可运行完整 E2E')).toBeVisible()
    await expect(page.getByText('面经提取 Agent')).toBeVisible()
    await expect(page.getByText('JD 提取 Agent')).toBeVisible()
    await expect(page.getByText(/简历分析 \/ 优化 Agent/)).toBeVisible()
    await expect(page.getByText('面试题分类 Agent')).toBeVisible()
    await expect(page.getByText('可运行结构化 Eval').first()).toBeVisible()
  })

  test('版本列表使用固定列宽并保持关键固定项可读', async ({ page }) => {
    await page.goto('/admin/evals/releases?preview=1')

    await expect(page.getByText('完整评测版本会固定适合该目标的题集、规则、模型、执行器和确定性指标；模拟面试额外固定模拟器、工具调用与意图识别。')).toBeVisible()
    const tableLayout = await page.locator('table').first().evaluate(element => getComputedStyle(element).tableLayout)
    expect(tableLayout).toBe('fixed')

    await page.setViewportSize({ width: 390, height: 844 })
    const tableWidth = await page.locator('table').first().evaluate(element => ({ scrollWidth: element.scrollWidth, clientWidth: element.clientWidth }))
    expect(tableWidth.scrollWidth).toBeGreaterThanOrEqual(tableWidth.clientWidth)
  })

  test('其余页面也先展示管理员任务，而不是底层字段', async ({ page }) => {
    await page.goto('/admin/evals/benchmarks?preview=1')
    await expect(page.getByRole('heading', { name: 'Benchmark：这套题集测什么' })).toBeVisible()
    await expect(page.getByText('这里定义完整评测版本要测什么')).toBeVisible()

    await page.goto('/admin/evals/releases?preview=1')
    await expect(page.getByRole('heading', { name: '版本与发布：决定测谁' })).toBeVisible()
    await expect(page.getByText('先选择被测对象版本，再绑定一个完整评测版本')).toBeVisible()

    await page.goto('/admin/evals/reviews?preview=1')
    await expect(page.getByRole('heading', { name: '人工 A/B：核对版本差异' })).toBeVisible()
    await expect(page.getByText('先定位同一个完整评测版本下的两条 Run')).toBeVisible()
  })
})
