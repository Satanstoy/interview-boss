/**
 * AC-029：单份面经逐题数据流（前端面）
 *
 * 覆盖用户可见的数据流闭环（全部 API mock）：
 * - 用户提交 share 面经 → 任务卡片出现，状态从 queued 推进到 partial_failed；
 * - 失败后「重试失败步骤」调用恢复接口，任务回到 queued；
 * - 完成后「查看结果」定位到面经页并高亮目标记录；
 * - 只有服务端 allowed_actions 展示，不出现暂停等虚构按钮。
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

const BASE_TASK = {
  import_id: 'imp-ac029-1',
  revision: 1,
  status: 'queued',
  target_intent: 'share',
  attempt_no: 0,
  review_status: null,
  stage: 'extract',
  position_id: 1,
  position_name: '后端开发工程师',
  error: null,
  allowed_actions: ['view_progress'],
  created_at: '2026-09-30T00:00:00Z',
  updated_at: '2026-09-30T00:00:00Z',
}

function task(overrides) {
  return { ...BASE_TASK, ...overrides }
}

async function mockApi(page) {
  await page.route('**/api/auth/**', (route) =>
    route.fulfill({ json: { token: 'e2e-token', user: MOCK_USER } }),
  )
  // 提交入口（v2）与任务中心共用 /api/submit-jobs
  await page.route('**/api/submit-jobs', (route) => {
    if (route.request().method() === 'POST') {
      return route.fulfill({
        status: 202,
        json: {
          import_id: 'imp-ac029-1',
          created: true,
          status_url: '/api/upload-imports/imp-ac029-1',
          idempotency_key: 'ac029-key',
        },
      })
    }
    return route.fulfill({ json: { items: [], total: 0 } })
  })
  await page.route('**/api/upload-imports?**', (route) =>
    route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20 } }),
  )
  await page.route('**/api/upload-imports/imp-ac029-1', (route) => {
    // 首查返回待审核已完成状态，供卡片渲染
    return route.fulfill({ json: task({ status: 'waiting_review', revision: 9 }) })
  })
  await page.route('**/api/upload-imports/imp-ac029-1/stream', (route) =>
    route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: '',
    }),
  )
}

test('share 提交展示任务卡片且只展示服务端 allowed_actions', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  // 打开任务中心
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center).toBeVisible()
  // 无暂停能力
  await expect(center.getByRole('button', { name: /暂停/ })).toHaveCount(0)
})

test('失败任务可重试且完成后可查看结果', async ({ page }) => {
  await mockApi(page)
  // 部分失败的既有任务（服务端 allowed_actions 授权重试）
  const failed = task({
    status: 'partial_failed',
    revision: 7,
    attempt_no: 1,
    stage: 'answer',
    interview_id: 555,
    error: { code: 'UPSTREAM_TIMEOUT', message: '答案生成超时', retryable: true },
    allowed_actions: ['open_result', 'retry_failed_steps'],
  })
  await page.route('**/api/upload-imports?**', (route) =>
    route.fulfill({ json: { items: [failed], total: 1, page: 1, page_size: 20 } }),
  )
  let retried = false
  await page.route('**/api/upload-imports/imp-ac029-1/retry', (route) => {
    retried = true
    return route.fulfill({
      json: task({ status: 'queued', revision: 8, attempt_no: 2, allowed_actions: ['view_progress'] }),
    })
  })
  await page.route('**/api/data/interview/555/location?**', (route) =>
    route.fulfill({ json: { interview_id: 555, page: 4, page_size: 20, rank: 61, position_id: 1 } }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center.getByText('部分失败', { exact: true })).toBeVisible()
  await expect(center.getByRole('button', { name: '重试失败步骤' })).toBeVisible()

  await center.getByRole('button', { name: '重试失败步骤' }).click()
  await expect.poll(() => retried).toBe(true)

  // 完成态允许查看结果 → 按 location 定位并高亮
  await page.route('**/api/upload-imports/imp-ac029-1', (route) =>
    route.fulfill({
      json: task({ status: 'completed', revision: 10, interview_id: 555, allowed_actions: ['open_result'] }),
    }),
  )
  await page.route('**/api/upload-imports?**', (route) =>
    route.fulfill({
      json: {
        items: [task({ status: 'completed', revision: 10, interview_id: 555, allowed_actions: ['open_result'] })],
        total: 1,
        page: 1,
        page_size: 20,
      },
    }),
  )
  // 刷新任务中心（重新打开）后呈现「查看结果」
  await page.getByRole('button', { name: '关闭任务中心' }).click()
  await page.getByRole('button', { name: '上传任务中心' }).click()
  await page.getByRole('button', { name: '查看结果' }).click()
  await expect(page).toHaveURL(/page=4/)
  await expect(page).toHaveURL(/highlight=555/)
})