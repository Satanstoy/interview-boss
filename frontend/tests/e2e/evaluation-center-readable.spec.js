import { expect, test } from '@playwright/test'

const overviewPayload = {
  counts: { completed: 2, running: 1, queued: 0, created: 0, failed: 0, cancelled: 0 },
}

const releasesPayload = {
  releases: [
    { id: 1, release_key: 'interview-agent@1.0', release_type: 'target', status: 'published', version: '1.0' },
    { id: 2, release_key: 'interview-e2e-suite@1.0', release_type: 'benchmark_suite', status: 'published', version: '1.0' },
    { id: 3, release_key: 'eval-protocol@1.0', release_type: 'eval_protocol', status: 'published', version: '1.0' },
    { id: 4, release_key: 'judge@1.0', release_type: 'judge', status: 'published', version: '1.0', judge_model: 'fixed-judge' },
    { id: 5, release_key: 'interview-harness@1.0', release_type: 'simulator_harness', status: 'published', version: '1.0' },
    { id: 6, release_key: 'candidate-simulator@1.0', release_type: 'candidate_simulator', status: 'published', version: '1.0' },
  ],
}

const runsPayload = {
  runs: [
    {
      id: 12,
      status: 'completed',
      target_release_key: 'interview-agent@1.0',
      benchmark_suite_release_key: 'interview-e2e-suite@1.0',
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
      release_key: 'interview-e2e-suite@1.0',
      release_status: 'published',
      description: '模拟面试的固定 E2E 场景。',
      judge_model: 'fixed-judge',
      cases: [],
    },
  ],
}

async function mockEvaluationApis(page) {
  await page.route('**/api/admin/evals/overview', route => route.fulfill({ json: overviewPayload }))
  await page.route('**/api/admin/evals/releases**', route => route.fulfill({ json: releasesPayload }))
  await page.route('**/api/admin/evals/runs**', route => route.fulfill({ json: runsPayload }))
  await page.route('**/api/admin/evals/benchmarks', route => route.fulfill({ json: benchmarksPayload }))
  await page.route('**/api/auth/**', route => route.fulfill({ json: { id: 1, username: 'admin', is_admin: true } }))
  await page.route('**/api/data/**', route => route.fulfill({ json: [] }))
  await page.route('**/api/analytics**', route => route.fulfill({ json: {} }))
  await page.route('**/api/practice/**', route => route.fulfill({ json: [] }))
  await page.route('**/api/profile**', route => route.fulfill({ json: { positions: [] } }))
  await page.route('**/api/interview**', route => route.fulfill({ json: [] }))
  await page.route('**/api/coding/**', route => route.fulfill({ json: [] }))
  await page.route('**/api/knowledge**', route => route.fulfill({ json: { nodes: [], edges: [] } }))
  await page.route('**/api/admin/**', route => route.fulfill({ json: [] }))
}

test.describe('评测中心可读性', () => {
  test.beforeEach(async ({ page }) => {
    await mockEvaluationApis(page)
  })

  test('总览告诉管理员评测流程和下一步动作', async ({ page }) => {
    await page.goto('/admin/evals/overview?preview=1')

    await expect(page.getByRole('heading', { name: '评测总览' })).toBeVisible()
    await expect(page.getByText('版本与发布 → Benchmark → 测评实验 → 评测结果 → 人工 A/B')).toBeVisible()
    await expect(page.getByText('这里查看所有评测运行的整体状态')).toBeVisible()
    await expect(page.getByRole('button', { name: '开始一次完整评测' }).first()).toBeVisible()
  })

  test('实验页按步骤解释配置项', async ({ page }) => {
    await page.goto('/admin/evals/experiments?preview=1')

    await expect(page.getByRole('heading', { name: '发起一次评测' })).toBeVisible()
    await expect(page.getByText('第 1 步：选择被测版本')).toBeVisible()
    await expect(page.getByText('第 2 步：选择评测基线')).toBeVisible()
    await expect(page.getByText('第 3 步：固定运行参数')).toBeVisible()
    await expect(page.getByText('每个 Case 重跑次数')).toBeVisible()
    await expect(page.getByRole('button', { name: '创建并开始评测' })).toBeVisible()
  })

  test('其余页面也先展示管理员任务，而不是底层字段', async ({ page }) => {
    await page.goto('/admin/evals/benchmarks?preview=1')
    await expect(page.getByRole('heading', { name: 'Benchmark：这套题集测什么' })).toBeVisible()
    await expect(page.getByText('先看每套题集覆盖的场景和质量要求')).toBeVisible()

    await page.goto('/admin/evals/releases?preview=1')
    await expect(page.getByRole('heading', { name: '版本与发布：决定测谁' })).toBeVisible()
    await expect(page.getByText('只有已发布版本可以进入正式 Benchmark')).toBeVisible()

    await page.goto('/admin/evals/reviews?preview=1')
    await expect(page.getByRole('heading', { name: '人工 A/B：核对版本差异' })).toBeVisible()
    await expect(page.getByText('先定位同一 Case，再阅读两边的完整 E2E 回答')).toBeVisible()
  })
})
