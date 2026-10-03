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
  // contracts §4.2：interview_id 在 result 内，快照顶层没有该字段
  result: { interview_id: 555, position_id: 1 },
  error: { code: 'UPSTREAM_TIMEOUT', message: '答案生成超时', retryable: true },
  allowed_actions: ['open_result', 'retry_failed_steps'],
  created_at: '2026-09-29T10:00:00Z',
  updated_at: '2026-09-29T10:05:00Z',
}

const MOCK_TASKS = { items: [TASK], total: 1, page: 1, page_size: 20 }

async function mockApi(page, { user = MOCK_USER, task = TASK } = {}) {
  await page.route('**/api/auth/**', (route) =>
    route.fulfill({ json: { token: 'e2e-token', user } }),
  )
  await page.route('**/api/upload-imports?**', (route) =>
    route.fulfill({ json: { ...MOCK_TASKS, items: [task] } }),
  )
  await page.route('**/api/upload-imports/imp-e2e-0001', (route) => route.fulfill({ json: task }))
  await page.route('**/api/data/interview/555/location?**', (route) =>
    route.fulfill({ json: { interview_id: 555, page: 4, page_size: 20, rank: 61, position_id: 1 } }),
  )
  await page.route('**/api/positions**', (route) =>
    route.fulfill({ json: { positions: [{ id: 1, name: '后端开发工程师' }] } }),
  )
  await page.route('**/api/profile**', (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith('/embedding')) {
      return route.fulfill({ json: { settings: { backend: 'auto', dimension: 512 } } })
    }
    if (pathname.endsWith('/taxonomy/system')) {
      return route.fulfill({ json: { job_position: '后端开发工程师', categories: [], tags: [] } })
    }
    return route.fulfill({
      json: {
        settings: {
          current_job_position: '后端开发工程师',
          llm_model: 'system-model',
          llm_timeout: '120',
        },
      },
    })
  })
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

test('任务列表恢复 GET 返回 500 时保留已知任务和结果入口', async ({ page }) => {
  await mockApi(page)
  let listCalls = 0
  await page.route('**/api/upload-imports?**', (route) => {
    listCalls += 1
    if (listCalls === 1) return route.fulfill({ json: MOCK_TASKS })
    return route.fulfill({ status: 500, json: { detail: '恢复读取失败' } })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center.getByRole('button', { name: '查看结果' })).toBeVisible()
  await center.getByRole('button', { name: '刷新' }).click()

  await expect(center.getByText(/恢复读取失败|任务列表加载失败/)).toBeVisible()
  await expect(center.locator('li', { hasText: 'imp-e2e-0001' })).toBeVisible()
  await expect(center.getByRole('button', { name: '查看结果' })).toBeVisible()
})

test('恢复请求复用已有 attempt 时说明任务正在继续', async ({ page }) => {
  const runningTask = {
    ...TASK,
    status: 'running',
    allowed_actions: ['view_progress'],
    error: null,
  }
  await mockApi(page)
  let listCalls = 0
  await page.route('**/api/upload-imports?**', (route) => {
    listCalls += 1
    const task = listCalls === 1 ? TASK : runningTask
    return route.fulfill({ json: { items: [task], total: 1, page: 1, page_size: 20 } })
  })
  await page.route('**/api/upload-imports/imp-e2e-0001/retry', (route) =>
    route.fulfill({ json: { ...runningTask, created_attempt: false } }),
  )
  await page.route('**/api/upload-imports/imp-e2e-0001/stream', (route) =>
    route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: `event: snapshot\nid: 4\ndata: ${JSON.stringify({ ...runningTask, revision: 4 })}\n\n`,
    }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  await page.getByRole('button', { name: '重试失败步骤' }).click()

  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center.locator('[aria-live="polite"]')).toHaveText(
    '已有恢复任务正在继续处理未完成步骤',
  )
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

test('普通用户遇到公共模型阻塞时只看到等待提示', async ({ page }) => {
  const waitingTask = {
    ...TASK,
    status: 'needs_action',
    error: {
      code: 'MODEL_CONFIG_MISSING',
      message: '系统尚未配置模型，请管理员修复',
      retryable: false,
      action: 'wait_for_global_model',
      scope: 'global',
    },
    allowed_actions: ['wait_for_global_model', 'retry_after_configuration'],
  }
  await mockApi(page, { task: waitingTask })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center.getByText('等待管理员配置公共模型')).toBeVisible()
  await expect(center.getByRole('button', { name: '等待管理员配置公共模型' })).toHaveCount(0)
  await expect(center.getByRole('button', { name: '配置后继续' })).toBeVisible()
})

test('管理员可从公共模型阻塞任务直达全局模型配置', async ({ page }) => {
  const admin = { ...MOCK_USER, id: 201, username: 'admin', is_admin: 1 }
  const blockedTask = {
    ...TASK,
    status: 'needs_action',
    error: {
      code: 'MODEL_AUTH_INVALID',
      message: '系统模型鉴权失败',
      retryable: false,
      action: 'configure_system_model',
      scope: 'global',
    },
    allowed_actions: ['configure_system_model', 'retry_after_configuration'],
  }
  await mockApi(page, { user: admin, task: blockedTask })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  await page.getByRole('button', { name: '配置系统模型' }).click()

  await expect(page).toHaveURL(/section=admin/)
  await expect(page).toHaveURL(/adminTab=model/)
  await expect(page.getByText('全局 LLM 配置')).toBeVisible()
})

test('普通用户不能通过管理员设置深链打开全局模型配置', async ({ page }) => {
  await mockApi(page)
  await page.goto('/settings?section=admin&adminTab=model')

  await expect(page.getByText('全局 LLM 配置')).toHaveCount(0)
  await expect(page.getByText('管理员设置')).toHaveCount(0)
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

test('SSE 首次返回 503 后自动重连并继续接收快照', async ({ page }) => {
  const runningTask = {
    ...TASK,
    status: 'running',
    stage: 'extract',
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
    if (streamCalls === 1) {
      return route.fulfill({ status: 503, json: { detail: '暂时不可用' } })
    }
    return route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: `event: snapshot\nid: 5\ndata: ${JSON.stringify({ ...runningTask, revision: 5 })}\n\n`,
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  await expect.poll(() => streamCalls, { timeout: 10_000 }).toBeGreaterThan(1)
})

test('SSE 非终态 EOF 后重连并用新快照收敛', async ({ page }) => {
  const runningTask = {
    ...TASK,
    revision: 4,
    status: 'running',
    stage: 'answer',
    progress: { unit: 'questions', completed: 0, total: 10 },
    counts: { total: 10, answered: 0, failed: 0 },
    allowed_actions: ['view_progress'],
    error: null,
  }
  await mockApi(page, { task: runningTask })
  let streamCalls = 0
  await page.route('**/api/upload-imports/imp-e2e-0001/stream', (route) => {
    streamCalls += 1
    const snapshot = streamCalls === 1
      ? {
          ...runningTask,
          revision: 6,
          progress: { unit: 'questions', completed: 5, total: 10 },
          counts: { total: 10, answered: 4, failed: 1 },
        }
      : {
          ...runningTask,
          revision: 7,
          status: 'completed',
          progress: { unit: 'questions', completed: 10, total: 10 },
          counts: { total: 10, answered: 8, failed: 2 },
          allowed_actions: ['open_result'],
        }
    return route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: `event: snapshot\nid: ${snapshot.revision}\ndata: ${JSON.stringify(snapshot)}\n\n`,
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect.poll(() => streamCalls, { timeout: 10_000 }).toBe(2)
  await expect(center.getByText('已完成', { exact: true })).toBeVisible()
  await expect(center.getByText('10/10 题已处理')).toBeVisible()
  await expect(center.getByText('答案成功 8 · 失败 2')).toBeVisible()
})

test('SSE 先收到 revision 8 再收到 7 时不回退，心跳不改题目计数', async ({ page }) => {
  const runningTask = {
    ...TASK,
    status: 'running',
    allowed_actions: ['view_progress'],
    error: null,
  }
  const newer = {
    ...runningTask,
    revision: 8,
    progress: { unit: 'questions', completed: 8, total: 10 },
    counts: { total: 10, answered: 8, failed: 0 },
  }
  const older = {
    ...runningTask,
    revision: 7,
    progress: { unit: 'questions', completed: 7, total: 10 },
    counts: { total: 10, answered: 7, failed: 1 },
  }
  await mockApi(page, { task: runningTask })
  await page.route('**/api/upload-imports/imp-e2e-0001/stream', (route) =>
    route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: [newer, older]
        .map((snapshot) => `event: snapshot\nid: ${snapshot.revision}\ndata: ${JSON.stringify(snapshot)}\n\n`)
        .join('') + ': heartbeat\n\n',
    }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center.getByText('8/10 题已处理')).toBeVisible()
  await expect(center.getByText('答案成功 8 · 失败 0')).toBeVisible()
  await expect(center.getByText('7/10 题已处理')).toHaveCount(0)
})

test('SSE 401 鉴权失败后不重连第二次', async ({ page }) => {
  const runningTask = {
    ...TASK,
    status: 'running',
    allowed_actions: ['view_progress'],
    error: null,
  }
  await mockApi(page, { task: runningTask })
  let streamCalls = 0
  await page.route('**/api/upload-imports/imp-e2e-0001/stream', (route) => {
    streamCalls += 1
    return route.fulfill({ status: 401, json: { detail: 'unauthorized' } })
  })
  let refreshCalls = 0
  await page.route('**/api/auth/refresh', (route) => {
    refreshCalls += 1
    if (refreshCalls === 1) {
      return route.fulfill({ json: { token: 'e2e-token', user: MOCK_USER } })
    }
    return route.fulfill({ status: 401, json: { detail: 'unauthorized' } })
  })

  await page.goto('/')
  // The task center subscribes as soon as the authenticated task list loads;
  // the second 401 can open the login dialog before the panel is opened.
  await expect.poll(() => streamCalls).toBe(1)
  await page.waitForTimeout(1500)
  expect(streamCalls).toBe(1)
})

test('题目进度显示服务端真实分子分母和答案计数', async ({ page }) => {
  const task = {
    ...TASK,
    progress: { unit: 'questions', completed: 10, total: 10 },
    counts: { total: 10, answered: 8, failed: 2 },
  }
  await mockApi(page, { task })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center.getByText(/10\/10 题已处理/)).toBeVisible()
  await expect(center.getByText(/答案成功 8 · 失败 2/)).toBeVisible()
})

test('切换账号后清除旧账号任务和本地活跃任务缓存', async ({ page }) => {
  const runningTask = {
    ...TASK,
    status: 'running',
    allowed_actions: ['view_progress'],
    error: null,
  }
  let servedUserId = '101'
  await page.route('**/api/auth/**', (route) =>
    route.fulfill({ json: { token: 'e2e-token', user: MOCK_USER } }),
  )
  await page.route('**/api/upload-imports?**', (route) =>
    route.fulfill({
      json: {
        items: servedUserId === '101' ? [runningTask] : [],
        total: servedUserId === '101' ? 1 : 0,
        page: 1,
        page_size: 20,
      },
    }),
  )
  let streamCalls = 0
  await page.route('**/api/upload-imports/imp-e2e-0001/stream', (route) => {
    streamCalls += 1
    return route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: `event: snapshot\nid: 4\ndata: ${JSON.stringify({ ...runningTask, revision: 4 })}\n\n`,
    })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center.locator('li', { hasText: 'imp-e2e-0001' })).toBeVisible()
  await expect.poll(() => streamCalls).toBeGreaterThan(0)

  await page.evaluate(() => {
    localStorage.setItem('interviewboss-submit-jobs:101', '[77]')
    localStorage.setItem('interviewboss-submit-draft:101:panel-default', 'old-user-key')
  })
  servedUserId = '102'
  await page.evaluate(async () => {
    const { useAuth } = await import('/src/composables/useAuth.js')
    useAuth().handleLoginSuccess({
      id: 102,
      username: 'u102',
      is_admin: 0,
      bank_mode: 'public',
      current_position_id: 1,
      current_position: '后端开发工程师',
    })
  })

  await expect(center.getByText('暂无上传任务')).toBeVisible()
  await expect(center.locator('li', { hasText: 'imp-e2e-0001' })).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => localStorage.getItem('interviewboss-submit-jobs:101'))).toBeNull()
  await expect.poll(() => page.evaluate(() => localStorage.getItem('interviewboss-submit-draft:101:panel-default'))).toBeNull()
  await page.waitForTimeout(1500)
  expect(streamCalls).toBe(1)
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
