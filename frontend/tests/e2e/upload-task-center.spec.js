/**
 * 上传任务中心 E2E（AC-010 / AC-027 / AC-001 前端面）
 *
 * 所有 API 通过 page.route() mock：
 * - 任务中心常驻、只显示服务端 allowed_actions（无暂停）；
 * - 点击“查看结果”调用 location 接口并带上 page/highlight；
 * - 恢复失败（500）不清空已有任务；
 * - 键盘可达、aria-live 状态可读。
 */
import { test, expect } from '@playwright/test'

const MOCK_USER = {
  id: 101,
  username: 'u101',
  is_admin: 0,
  bank_mode: 'public',
  current_position_id: 1,
  current_position: '后端开发工程师',
}

const TASK = {
  import_id: 'imp-e2e-0001',
  revision: 3,
  status: 'partial_failed',
  target_intent: 'private',
  attempt_no: 1,
  review_status: null,
  stage: 'answer',
  position_id: 1,
  position_name: '后端开发工程师',
  interview_id: 555,
  error: { code: 'UPSTREAM_TIMEOUT', message: '答案生成超时', retryable: true },
  allowed_actions: ['open_result', 'retry_failed_steps'],
  created_at: '2026-09-29T10:00:00Z',
  updated_at: '2026-09-29T10:05:00Z',
}

const MOCK_TASKS = { items: [TASK], total: 1, page: 1, page_size: 20 }

async function mockApi(page) {
  await page.route('**/api/auth/**', (route) =>
    route.fulfill({ json: { token: 'e2e-token', user: MOCK_USER } }),
  )
  await page.route('**/api/upload-imports?**', (route) => route.fulfill({ json: MOCK_TASKS }))
  await page.route('**/api/upload-imports/imp-e2e-0001', (route) => route.fulfill({ json: TASK }))
  await page.route('**/api/data/interview/555/location?**', (route) =>
    route.fulfill({ json: { interview_id: 555, page: 4, page_size: 20, rank: 61, position_id: 1 } }),
  )
}

test('任务中心展示 allowed_actions 且不出现暂停按钮', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()

  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center).toBeVisible()
  await expect(center.getByText('部分失败', { exact: true })).toBeVisible()
  await expect(center.getByRole('button', { name: '查看结果' })).toBeVisible()
  await expect(center.getByRole('button', { name: '重试失败步骤' })).toBeVisible()
  // 没有暂停能力就禁止显示暂停
  await expect(center.getByRole('button', { name: /暂停/ })).toHaveCount(0)
})

test('查看结果按 location 定位页码并高亮目标', async ({ page }) => {
  await mockApi(page)
  let locationCalled = false
  await page.route('**/api/data/interview/555/location?**', (route) => {
    locationCalled = true
    return route.fulfill({
      json: { interview_id: 555, page: 4, page_size: 20, rank: 61, position_id: 1 },
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  await page.getByRole('button', { name: '查看结果' }).click()

  await expect.poll(() => locationCalled).toBe(true)
  await expect(page).toHaveURL(/page=4/)
  await expect(page).toHaveURL(/highlight=555/)
})

test('恢复接口 500 时保留已有任务', async ({ page }) => {
  await mockApi(page)
  await page.route('**/api/upload-imports/imp-e2e-0001/retry', (route) =>
    route.fulfill({ status: 500, json: { detail: '内部错误' } }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  await page.getByRole('button', { name: '重试失败步骤' }).click()

  // 失败后任务仍可见（不被当作空列表）
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center.locator('li', { hasText: 'imp-e2e-0001' })).toBeVisible()
  await expect(center.getByText(/恢复失败|内部错误/)).toBeVisible()
})

test('任务卡片可用键盘操作且状态对读屏可见', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()

  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center).toBeVisible()
  const actionButton = center.getByRole('button', { name: '查看结果' })
  await actionButton.focus()
  await expect(actionButton).toBeFocused()
  await expect(center.locator('[aria-live="polite"]')).toHaveCount(1)
})

test('SSE 非终态 EOF 后客户端会重连', async ({ page }) => {
  const runningTask = {
    ...TASK,
    status: 'running',
    stage: 'cluster',
    allowed_actions: ['view_progress'],
    error: null,
  }
  await page.route('**/api/auth/**', (route) =>
    route.fulfill({ json: { token: 'e2e-token', user: MOCK_USER } }),
  )
  await page.route('**/api/upload-imports?**', (route) =>
    route.fulfill({ json: { items: [runningTask], total: 1, page: 1, page_size: 20 } }),
  )

  let streamCalls = 0
  await page.route('**/api/upload-imports/imp-e2e-0001/stream', (route) => {
    streamCalls += 1
    // 发一个非终态快照后正常 EOF（不发 error）
    return route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: `event: snapshot\nid: 4\ndata: ${JSON.stringify({ ...runningTask, revision: 4 })}\n\n`,
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  await expect.poll(() => streamCalls, { timeout: 15_000 }).toBeGreaterThan(1)
})

test('375px 与 1440px 均可查看任务与恢复按钮', async ({ page }) => {
  await mockApi(page)
  for (const width of [375, 1440]) {
    await page.setViewportSize({ width, height: 800 })
    await page.goto('/')
    await page.getByRole('button', { name: '上传任务中心' }).click()
    const center = page.getByRole('region', { name: '上传任务中心' })
    await expect(center).toBeVisible()
    await expect(center.getByRole('button', { name: '重试失败步骤' })).toBeVisible()
    await expect(center.getByRole('button', { name: '查看结果' })).toBeVisible()
  }
})
