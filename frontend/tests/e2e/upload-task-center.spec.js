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

test.beforeEach(async ({ page }) => {
  // Task center now reads both upload roots and personal rootless failures.
  // Keep the additional API boundary isolated in this mock-only suite.
  await page.route('**/api/personal-analysis-queue/failed?**', (route) =>
    route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20 } }),
  )
  await page.route('**/api/personal-analysis-queue/failed/refresh', (route) =>
    route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20 } }),
  )
})

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
  result_target: { entity_type: 'interview', entity_id: 555, scope: 'private' },
  error: { code: 'UPSTREAM_TIMEOUT', message: '答案生成超时', retryable: true },
  allowed_actions: ['open_result', 'retry_failed_steps'],
  created_at: '2026-09-29T10:00:00Z',
  updated_at: '2026-09-29T10:05:00Z',
}

const PUBLISHED_PUBLIC_TASK = {
  ...TASK,
  target_intent: 'share',
  result_target: { entity_type: 'interview', entity_id: 777, scope: 'public' },
}

const MOCK_TASKS = { items: [TASK], total: 1, page: 1, page_size: 20 }
const ROOTLESS_FAILURE = {
  queue_id: 2700,
  interview_id: 700,
  company: 'U1 私人公司',
  job_position: '后端',
  question: 'U1 私人失败题',
  status: 'failed',
  allowed_actions: ['retry'],
}

async function mockApi(page, { user = MOCK_USER, task = TASK } = {}) {
  await page.route('**/api/auth/**', (route) =>
    route.fulfill({ json: { token: 'e2e-token', user } }),
  )
  await page.route('**/api/upload-imports?**', (route) =>
    route.fulfill({ json: { ...MOCK_TASKS, items: [task] } }),
  )
  await page.route('**/api/personal-analysis-queue/failed?**', (route) =>
    route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20 } }),
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

test('个人 rootless 失败项在任务中心由所有者重试原队列项', async ({ page }) => {
  await mockApi(page)
  let refreshCalls = 0
  let retryRequest = null
  await page.unroute('**/api/personal-analysis-queue/failed/refresh')
  await page.route('**/api/personal-analysis-queue/failed/refresh', (route) => {
    refreshCalls += 1
    return route.fulfill({
      json: {
        items: retryRequest ? [] : [ROOTLESS_FAILURE],
        total: retryRequest ? 0 : 1,
        page: 1,
        page_size: 20,
      },
    })
  })
  await page.route('**/api/personal-analysis-queue/2700/retry', async (route) => {
    retryRequest = route.request()
    await route.fulfill({
      status: 202,
      json: { queue_id: 2700, status: 'pending', created: true },
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  const failureCard = center.locator('li', { hasText: 'U1 私人失败题' })
  await expect(failureCard).toBeVisible()
  await expect(failureCard.getByRole('button', { name: '重试' })).toBeVisible()
  await failureCard.getByRole('button', { name: '重试' }).click()

  await expect.poll(() => retryRequest?.method()).toBe('POST')
  await expect(failureCard).toHaveCount(0)
  await expect(center.getByText('失败题目已重新排队处理')).toBeAttached()
})

test('任务中心可翻到超过首屏的个人 rootless 失败项', async ({ page }) => {
  await mockApi(page)
  await page.unroute('**/api/personal-analysis-queue/failed?**')
  const firstPage = Array.from({ length: 20 }, (_, index) => ({
    ...ROOTLESS_FAILURE,
    queue_id: 2800 + index,
    question: `个人失败题 ${index + 1}`,
  }))
  await page.route('**/api/personal-analysis-queue/failed?**', (route) => {
    const requestUrl = new URL(route.request().url())
    if (requestUrl.searchParams.get('page') === '2') {
      return route.fulfill({
        json: {
          items: [{ ...ROOTLESS_FAILURE, queue_id: 2820, question: '第二页个人失败题' }],
          total: 21,
          page: 2,
          page_size: 20,
        },
      })
    }
    return route.fulfill({
      json: { items: firstPage, total: 21, page: 1, page_size: 20 },
    })
  })
  await page.unroute('**/api/personal-analysis-queue/failed/refresh')
  await page.route('**/api/personal-analysis-queue/failed/refresh', (route) => {
    return route.fulfill({
      json: { items: firstPage, total: 21, page: 1, page_size: 20 },
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center.getByText('个人失败题 20', { exact: true })).toBeVisible()
  await expect(center.getByText('第二页个人失败题', { exact: true })).toHaveCount(0)
  await center.getByRole('button', { name: /加载更多个人失败项/ }).click()
  await expect(center.getByText('第二页个人失败题', { exact: true })).toBeVisible()
  await expect(center.getByRole('button', { name: /加载更多个人失败项/ })).toHaveCount(0)
})

test('任务中心刷新已展开的个人失败页时请求数保持固定', async ({ page }) => {
  await mockApi(page)
  const requests = []
  const loadedItems = new Map()
  for (let index = 0; index < 20; index += 1) {
    const item = {
      ...ROOTLESS_FAILURE,
      queue_id: 3000 + index,
      question: `个人失败题-1-${index}`,
    }
    loadedItems.set(item.queue_id, item)
  }
  await page.unroute('**/api/personal-analysis-queue/failed?**')
  await page.route('**/api/personal-analysis-queue/failed?**', async (route) => {
    const requestUrl = new URL(route.request().url())
    const pageNumber = Number(requestUrl.searchParams.get('page') || 1)
    requests.push({ method: 'GET', page: pageNumber })
    const itemCount = pageNumber === 4 ? 1 : 20
    const items = Array.from({ length: itemCount }, (_, index) => ({
      ...ROOTLESS_FAILURE,
      queue_id: 3000 + (pageNumber - 1) * 20 + index,
      question: `个人失败题-${pageNumber}-${index}`,
    }))
    for (const item of items) loadedItems.set(item.queue_id, item)
    return route.fulfill({
      json: { items, total: 61, page: pageNumber, page_size: 20 },
    })
  })
  await page.route('**/api/personal-analysis-queue/failed/refresh', async (route) => {
    const { loaded_count: loadedCount } = route.request().postDataJSON()
    requests.push({ method: 'POST', loadedCount })
    return route.fulfill({
      json: {
        items: [...loadedItems.values()].slice(0, loadedCount),
        total: 61,
        page: 1,
        page_size: loadedCount,
      },
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  for (let pageNumber = 2; pageNumber <= 4; pageNumber += 1) {
    await center.getByRole('button', { name: /加载更多个人失败项/ }).click()
    await expect(center.getByText(`个人失败题-${pageNumber}-0`, { exact: true })).toBeVisible()
  }

  requests.length = 0
  await center.getByRole('button', { name: '刷新' }).click()
  await page.waitForTimeout(100)

  expect(requests.filter((request) => request.method === 'GET')).toHaveLength(0)
  expect(requests.filter((request) => request.method === 'POST')).toEqual([
    { method: 'POST', loadedCount: 80 },
  ])
  await expect(center.getByText('个人失败题-4-0', { exact: true })).toBeVisible()
})

test('刷新缩短个人失败范围后，加载更多继续请求紧邻页', async ({ page }) => {
  await mockApi(page)
  const requests = []
  const loadedItems = new Map()
  for (let index = 0; index < 20; index += 1) {
    const item = {
      ...ROOTLESS_FAILURE,
      queue_id: 3000 + index,
      question: `个人失败题-1-${index}`,
    }
    loadedItems.set(item.queue_id, item)
  }
  let listTotal = 61
  await page.unroute('**/api/personal-analysis-queue/failed?**')
  await page.route('**/api/personal-analysis-queue/failed?**', async (route) => {
    const requestUrl = new URL(route.request().url())
    const pageNumber = Number(requestUrl.searchParams.get('page') || 1)
    requests.push(pageNumber)
    const itemCount = pageNumber === 4 ? 1 : 20
    const items = Array.from({ length: itemCount }, (_, index) => ({
      ...ROOTLESS_FAILURE,
      queue_id: 3000 + (pageNumber - 1) * 20 + index,
      question: `个人失败题-${pageNumber}-${index}`,
    }))
    for (const item of items) loadedItems.set(item.queue_id, item)
    return route.fulfill({
      json: { items, total: listTotal, page: pageNumber, page_size: 20 },
    })
  })
  await page.route('**/api/personal-analysis-queue/failed/refresh', async (route) => {
    loadedItems.delete(3060)
    return route.fulfill({
      json: {
        items: [...loadedItems.values()].slice(0, 80),
        total: 61,
        page: 1,
        page_size: 80,
      },
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  for (let pageNumber = 2; pageNumber <= 4; pageNumber += 1) {
    await center.getByRole('button', { name: /加载更多个人失败项/ }).click()
    await expect(center.getByText(`个人失败题-${pageNumber}-0`, { exact: true })).toBeVisible()
  }

  await center.getByRole('button', { name: '刷新' }).click()
  await expect(center.getByText('个人失败题-4-0', { exact: true })).toHaveCount(0)
  const loadMore = center.getByRole('button', { name: /加载更多个人失败项/ })
  await expect(loadMore).toContainText('60/61')
  await loadMore.click()
  await expect.poll(() => requests.filter((requestedPage) => requestedPage === 4).length).toBe(2)
  await expect(center.getByText('个人失败题-4-0', { exact: true })).toBeVisible()
})

test('较新的刷新结果优先，旧响应不能恢复已消失的失败项', async ({ page }) => {
  await mockApi(page)
  await page.unroute('**/api/personal-analysis-queue/failed/refresh')
  const staleFailure = { ...ROOTLESS_FAILURE, queue_id: 3900, question: '过期的个人失败题' }
  let refreshCalls = 0
  let releaseStale
  let staleCompleted = false
  const staleResponse = new Promise((resolve) => { releaseStale = resolve })
  await page.route('**/api/personal-analysis-queue/failed/refresh', async (route) => {
    refreshCalls += 1
    if (refreshCalls === 1) {
      await staleResponse
      staleCompleted = true
      return route.fulfill({ json: { items: [staleFailure], total: 1, page: 1, page_size: 20 } })
    }
    return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20 } })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect.poll(() => refreshCalls).toBe(2)
  await center.getByRole('button', { name: '刷新' }).click()
  await expect.poll(() => refreshCalls).toBe(3)
  releaseStale()
  await expect.poll(() => staleCompleted).toBe(true)
  await page.waitForTimeout(100)
  await expect(center.getByText('过期的个人失败题', { exact: true })).toHaveCount(0)
})

test('较新的范围刷新完成后，迟到的分页响应不能恢复旧失败项', async ({ page }) => {
  await mockApi(page)
  const firstPage = Array.from({ length: 20 }, (_, index) => ({
    ...ROOTLESS_FAILURE,
    queue_id: 4000 + index,
    question: `个人失败范围项-${index + 1}`,
  }))
  const staleFailure = { ...ROOTLESS_FAILURE, queue_id: 4021, question: '过期的第二页失败项' }
  let releasePageTwo
  let pageTwoRequested = false
  let pageTwoCompleted = false
  const delayedPageTwo = new Promise((resolve) => { releasePageTwo = resolve })
  let refreshCalls = 0
  await page.unroute('**/api/personal-analysis-queue/failed?**')
  await page.route('**/api/personal-analysis-queue/failed?**', async (route) => {
    const requestUrl = new URL(route.request().url())
    if (requestUrl.searchParams.get('page') === '2') {
      pageTwoRequested = true
      await delayedPageTwo
      pageTwoCompleted = true
      return route.fulfill({ json: { items: [staleFailure], total: 21, page: 2, page_size: 20 } })
    }
    return route.fulfill({ json: { items: firstPage, total: 21, page: 1, page_size: 20 } })
  })
  await page.unroute('**/api/personal-analysis-queue/failed/refresh')
  await page.route('**/api/personal-analysis-queue/failed/refresh', async (route) => {
    refreshCalls += 1
    return route.fulfill({
      json: {
        items: firstPage,
        total: refreshCalls <= 2 ? 21 : 20,
        page: 1,
        page_size: 20,
      },
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center.getByText('个人失败范围项-20', { exact: true })).toBeVisible()
  await center.getByRole('button', { name: /加载更多个人失败项/ }).click()
  await expect.poll(() => pageTwoRequested).toBe(true)
  await center.getByRole('button', { name: '刷新' }).click()
  await expect(center.getByRole('button', { name: /加载更多个人失败项/ })).toHaveCount(0)
  releasePageTwo()
  await expect.poll(() => pageTwoCompleted).toBe(true)
  await page.waitForTimeout(100)
  await expect(center.getByText('过期的第二页失败项', { exact: true })).toHaveCount(0)
})

test('切换账号后旧分页失败不能回滚新账号页码或清除加载状态', async ({ page }) => {
  await mockApi(page)
  const firstPage = (userId) => Array.from({ length: 20 }, (_, index) => ({
    ...ROOTLESS_FAILURE,
    queue_id: (userId === 101 ? 5000 : 6000) + index,
    question: `用户${userId}个人失败项-${index + 1}`,
  }))
  let pageTwoRequests = 0
  let firstPageTwoFinished = false
  let releaseFirstPageTwo
  let releaseSecondPageTwo
  const firstPageTwoResponse = new Promise((resolve) => { releaseFirstPageTwo = resolve })
  const secondPageTwoResponse = new Promise((resolve) => { releaseSecondPageTwo = resolve })
  await page.unroute('**/api/personal-analysis-queue/failed?**')
  await page.route('**/api/personal-analysis-queue/failed?**', async (route) => {
    const requestUrl = new URL(route.request().url())
    const requestedPage = Number(requestUrl.searchParams.get('page') || 1)
    if (requestedPage === 1) {
      const userId = Number((await page.evaluate(async () => {
        const { currentUser } = await import('/src/composables/useAuth.js')
        return currentUser.value?.id
      })))
      return route.fulfill({
        json: { items: firstPage(userId), total: 21, page: 1, page_size: 20 },
      })
    }
    pageTwoRequests += 1
    if (pageTwoRequests === 1) {
      await firstPageTwoResponse
      await route.fulfill({ status: 400, json: { detail: '旧账号分页失败' } })
      firstPageTwoFinished = true
      return
    }
    await secondPageTwoResponse
    return route.fulfill({
      json: {
        items: [{ ...ROOTLESS_FAILURE, queue_id: 6020, question: '用户102个人失败项-21' }],
        total: 21,
        page: 2,
        page_size: 20,
      },
    })
  })
  await page.unroute('**/api/personal-analysis-queue/failed/refresh')
  await page.route('**/api/personal-analysis-queue/failed/refresh', async (route) => {
    const userId = Number((await page.evaluate(async () => {
      const { currentUser } = await import('/src/composables/useAuth.js')
      return currentUser.value?.id
    })))
    return route.fulfill({
      json: { items: firstPage(userId), total: 21, page: 1, page_size: 20 },
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center.getByText('用户101个人失败项-20', { exact: true })).toBeVisible()
  await center.getByRole('button', { name: /加载更多个人失败项/ }).click()
  await expect.poll(() => pageTwoRequests).toBe(1)

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
  await expect(center.getByText('用户102个人失败项-20', { exact: true })).toBeVisible()
  await center.getByRole('button', { name: /加载更多个人失败项/ }).click()
  await expect.poll(() => pageTwoRequests).toBe(2)

  releaseFirstPageTwo()
  await expect.poll(() => firstPageTwoFinished).toBe(true)
  await page.waitForTimeout(100)
  await expect(center.getByText('旧账号分页失败')).toHaveCount(0)
  await expect(center.getByText('用户102个人失败项-21', { exact: true })).toHaveCount(0)
  await expect(center.getByRole('button', { name: /加载中/ })).toBeVisible()
  releaseSecondPageTwo()
  await expect(center.getByText('用户102个人失败项-21', { exact: true })).toBeVisible()
})

test('范围刷新失败后下一次加载更多仍请求未加载的紧邻页', async ({ page }) => {
  await mockApi(page)
  const firstPage = Array.from({ length: 20 }, (_, index) => ({
    ...ROOTLESS_FAILURE,
    queue_id: 7000 + index,
    question: `个人失败项-${index + 1}`,
  }))
  let pageTwoRequests = 0
  let releaseStalePageTwo
  const stalePageTwoResponse = new Promise((resolve) => { releaseStalePageTwo = resolve })
  const requestedPages = []
  let refreshCalls = 0
  let failNextRefresh = false
  await page.unroute('**/api/personal-analysis-queue/failed?**')
  await page.route('**/api/personal-analysis-queue/failed?**', async (route) => {
    const requestUrl = new URL(route.request().url())
    const requestedPage = Number(requestUrl.searchParams.get('page') || 1)
    requestedPages.push(requestedPage)
    if (requestedPage === 2) {
      pageTwoRequests += 1
      if (pageTwoRequests === 1) {
        await stalePageTwoResponse
        return route.fulfill({
          json: {
            items: [{ ...ROOTLESS_FAILURE, queue_id: 7099, question: '刷新前迟到的失败项' }],
            total: 21,
            page: 2,
            page_size: 20,
          },
        })
      }
      return route.fulfill({
        json: {
          items: [{ ...ROOTLESS_FAILURE, queue_id: 7020, question: '紧邻页的失败项' }],
          total: 21,
          page: 2,
          page_size: 20,
        },
      })
    }
    return route.fulfill({
      json: {
        items: [{ ...ROOTLESS_FAILURE, queue_id: 7120, question: '跳过一页返回的失败项' }],
        total: 21,
        page: requestedPage,
        page_size: 20,
      },
    })
  })
  await page.unroute('**/api/personal-analysis-queue/failed/refresh')
  await page.route('**/api/personal-analysis-queue/failed/refresh', async (route) => {
    refreshCalls += 1
    if (failNextRefresh) {
      failNextRefresh = false
      return route.fulfill({ status: 400, json: { detail: '范围刷新失败' } })
    }
    return route.fulfill({
      json: { items: firstPage, total: 21, page: 1, page_size: 20 },
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center.getByText('个人失败项-20', { exact: true })).toBeVisible()
  await center.getByRole('button', { name: /加载更多个人失败项/ }).click()
  await expect.poll(() => pageTwoRequests).toBe(1)

  const refreshCallsBeforeClick = refreshCalls
  failNextRefresh = true
  await center.getByRole('button', { name: '刷新' }).click()
  await expect.poll(() => refreshCalls).toBe(refreshCallsBeforeClick + 1)
  await expect(center.getByText(/范围刷新失败/)).toBeVisible()
  await center.getByRole('button', { name: /加载更多个人失败项/ }).click()
  await expect.poll(() => pageTwoRequests).toBe(2)
  expect(requestedPages.slice(-1)).toEqual([2])

  releaseStalePageTwo()
  await expect(center.getByText('紧邻页的失败项', { exact: true })).toBeVisible()
  await expect(center.getByText('刷新前迟到的失败项', { exact: true })).toHaveCount(0)
})

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

test('已发布分享任务定位公共结果并沿用当前每页数量', async ({ page }) => {
  await mockApi(page, { task: PUBLISHED_PUBLIC_TASK })
  let locationQuery
  await page.route('**/api/data/interview/777/location?**', async (route) => {
    locationQuery = new URL(route.request().url()).searchParams
    await route.fulfill({
      json: { interview_id: 777, page: 3, page_size: 50, rank: 120, position_id: 1 },
    })
  })

  await page.goto('/interview?page_size=50')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  await page.getByRole('button', { name: '查看结果' }).click()

  await expect.poll(() => locationQuery?.get('page_size')).toBe('50')
  await expect(page).toHaveURL(/page=3/)
  await expect(page).toHaveURL(/page_size=50/)
  await expect(page).toHaveURL(/highlight=777/)
})

test('私人结果没有岗位 ID 时不发送字面量 undefined 过滤条件', async ({ page }) => {
  const taskWithoutPosition = {
    ...TASK,
    position_id: null,
    result: { interview_id: 555, position_id: null },
  }
  await mockApi(page, { task: taskWithoutPosition })
  let locationQuery
  await page.route('**/api/data/interview/555/location?**', async (route) => {
    locationQuery = new URL(route.request().url()).searchParams
    await route.fulfill({
      json: { interview_id: 555, page: 1, page_size: 20, rank: 0, position_id: null },
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  await page.getByRole('button', { name: '查看结果' }).click()

  await expect.poll(() => locationQuery?.has('position_id')).toBe(false)
  await expect.poll(() => locationQuery?.get('scope')).toBe('all')
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
  await expect(center.locator('.sr-only[aria-live="polite"]')).toHaveText(
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
  await expect(center.locator('.sr-only[aria-live="polite"]')).toHaveCount(1)
  await expect(center.getByText('部分失败', { exact: true })).toHaveAttribute('role', 'status')
  await expect(center.getByText('部分失败', { exact: true })).toHaveAttribute('aria-live', 'polite')
})

test('键盘可完整打开任务中心、执行操作并关闭后回到触发按钮', async ({ page }) => {
  await mockApi(page)
  let retryCalled = false
  await page.route('**/api/upload-imports/imp-e2e-0001/retry', (route) => {
    retryCalled = true
    return route.fulfill({ json: { ...TASK, created_attempt: false } })
  })

  await page.goto('/')
  const trigger = page.getByRole('button', { name: '上传任务中心' })
  await trigger.focus()
  await page.keyboard.press('Enter')

  const center = page.getByRole('region', { name: '上传任务中心' })
  const closeButton = center.getByRole('button', { name: '关闭任务中心' })
  await expect(closeButton).toBeFocused()

  const retryButton = center.getByRole('button', { name: '重试失败步骤' })
  await retryButton.focus()
  await page.keyboard.press('Enter')
  await expect.poll(() => retryCalled).toBe(true)

  await closeButton.focus()
  await page.keyboard.press('Enter')
  await expect(center).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

test('375px 与 1440px 下任务状态和操作都可见且不横向溢出', async ({ page }) => {
  await mockApi(page)
  for (const width of [375, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')
    await page.getByRole('button', { name: '上传任务中心' }).click()

    const center = page.getByRole('region', { name: '上传任务中心' })
    const card = center.locator('li', { hasText: TASK.import_id })
    await expect(card.getByText('部分失败', { exact: true })).toBeVisible()
    await expect(card.getByRole('button', { name: '重试失败步骤' })).toBeVisible()
    const dimensions = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }))
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)

    const cardBox = await card.boundingBox()
    expect(cardBox.x).toBeGreaterThanOrEqual(0)
    expect(cardBox.x + cardBox.width).toBeLessThanOrEqual(width)
  }
})

test('375px 与 1440px 下排队、审核、配置和失败状态都能读取并触达合法动作', async ({ page }) => {
  const scenarios = [
    {
      status: 'queued',
      label: '排队中',
      action: 'view_progress',
      actionLabel: '查看进度',
      allowed_actions: ['view_progress'],
    },
    {
      status: 'waiting_review',
      label: '待审核',
      action: 'view_review_status',
      actionLabel: '查看审核状态',
      allowed_actions: ['view_review_status'],
    },
    {
      status: 'needs_action',
      label: '需要配置',
      action: 'configure_user_model',
      actionLabel: '去配置模型',
      allowed_actions: ['configure_user_model', 'retry_after_configuration'],
      error: { code: 'MODEL_CONFIG_MISSING', message: '请配置个人模型' },
    },
    {
      status: 'partial_failed',
      label: '部分失败',
      action: 'retry_failed_steps',
      actionLabel: '重试失败步骤',
      allowed_actions: ['open_result', 'retry_failed_steps'],
      error: { code: 'UPSTREAM_TIMEOUT', message: '答案生成超时', retryable: true },
    },
  ]
  let currentTask = { ...TASK }
  await mockApi(page)
  await page.unroute('**/api/upload-imports?**')
  await page.route('**/api/upload-imports?**', (route) =>
    route.fulfill({ json: { items: [currentTask], total: 1, page: 1, page_size: 20 } }),
  )

  for (const width of [375, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    for (const scenario of scenarios) {
      currentTask = { ...TASK, ...scenario }
      await page.goto(`/?ac027=${scenario.status}-${width}`)
      await page.getByRole('button', { name: '上传任务中心' }).click()

      const center = page.getByRole('region', { name: '上传任务中心' })
      const card = center.locator('li', { hasText: TASK.import_id })
      const status = card.getByText(scenario.label, { exact: true })
      await expect(status).toHaveAttribute('role', 'status')
      await expect(status).toHaveAttribute('aria-live', 'polite')
      const action = card.getByRole('button', { name: scenario.actionLabel })
      await expect(action).toBeVisible()
      await action.focus()
      await expect(action).toBeFocused()

      const dimensions = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      }))
      expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
      const cardBox = await card.boundingBox()
      expect(cardBox.x).toBeGreaterThanOrEqual(0)
      expect(cardBox.x + cardBox.width).toBeLessThanOrEqual(width)
    }
  }
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

test('已完成历史任务原稿过期时明确提示且不显示恢复动作', async ({ page }) => {
  const expiredTask = {
    ...TASK,
    status: 'completed',
    error: null,
    allowed_actions: ['open_result', 'resubmit_source'],
    recovery_available: false,
    recovery_message: '原稿已过期，无法从原稿重新处理；请重新提交材料。',
  }
  await mockApi(page, { task: expiredTask })

  await page.goto('/')
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  const taskCard = center.locator('li', { hasText: expiredTask.import_id })
  await expect(taskCard.getByText(expiredTask.recovery_message)).toBeVisible()
  await expect(taskCard.getByRole('button', { name: '查看结果' })).toBeVisible()
  await expect(taskCard.getByRole('button', { name: '重新提交原文' })).toBeVisible()
  await expect(taskCard.getByRole('button', { name: /重试|重新处理|配置后继续/ })).toHaveCount(0)
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

test('切换账号后清除通用 GET 缓存中的旧用户私有数据', async ({ page }) => {
  let serverUserId = 101
  await mockApi(page)
  await page.route('**/api/auth/me', (route) => route.fulfill({
    json: { id: serverUserId, username: `u${serverUserId}` },
  }))

  await page.goto('/')
  const firstRead = await page.evaluate(async () => {
    const { get } = await import('/src/services/http.js')
    return get('/api/auth/me')
  })
  expect(firstRead.id).toBe(101)

  serverUserId = 102
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
  const secondRead = await page.evaluate(async () => {
    const { get } = await import('/src/services/http.js')
    return get('/api/auth/me')
  })
  expect(secondRead.id).toBe(102)
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

async function mountAlignmentCenter(page, listHandler, streamEvents = []) {
  let streamDeliveries = 0
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (url.pathname === '/api/upload-imports') return listHandler(route, url)
    if (url.pathname.endsWith('/stream')) return route.fulfill({ contentType: 'text/event-stream', body: (streamDeliveries++ === 0 ? streamEvents : []).map(snapshot => `event: snapshot\nid: ${snapshot.revision}\ndata: ${JSON.stringify(snapshot)}\n\n`).join('') })
    if (url.pathname === '/api/submit-jobs') return route.fulfill({ json: { import_id: 'accepted-root', job_id: 77 } })
    if (url.pathname.includes('/by-key/')) return route.fulfill({ status:404,json:{detail:'任务不存在'} })
    if (url.pathname.endsWith('/budget')) return route.fulfill({ json: { calls: 1, total_tokens: 123, unknown_calls: 0 } })
    return route.fulfill({ json: { items: [], total: 0 } })
  })
  await page.route('**/__task_alignment', route => route.fulfill({ contentType: 'text/html', body: `
  <html><body><div id="app"></div><script type="module">
  import {createApp,h} from '/node_modules/.vite/deps/vue.js';
  import {createRouter,createWebHistory} from '/node_modules/.vite/deps/vue-router.js';
  import Center from '/src/components/business/UploadTaskCenter.vue';
  import {currentUser} from '/src/composables/useAuth.js';
  currentUser.value=${JSON.stringify(MOCK_USER)};
  const router=createRouter({history:createWebHistory(),routes:[{path:'/:pathMatch(.*)*',component:{render:()=>null}}]});
  createApp({render:()=>h(Center)}).use(router).mount('#app');
  </script></body></html>` }))
  await page.goto('/__task_alignment')
  await page.getByRole('button', { name: /上传任务中心/ }).click()
}

test('spec对齐：任务历史第二页可达', async ({ page }) => {
  await mountAlignmentCenter(page, (route, url) => {
    const number = Number(url.searchParams.get('page') || 1)
    const start = (number - 1) * 20
    return route.fulfill({ json: { items: Array.from({length: number === 1 ? 20 : 5}, (_,i)=>({...TASK, import_id:`history-${start+i+1}`, status:'completed', allowed_actions:[]})), total:25 } })
  })
  await expect(page.getByText(/history-20$/)).toBeVisible()
  await page.getByRole('button', { name:'下一页上传任务' }).click()
  await expect(page.getByText(/history-25$/)).toBeVisible()
  await expect(page.getByText(/history-1$/)).toHaveCount(0)
})

for (const [action, label, detail] of [
  ['view_summary','查看摘要','已识别题目'],
  ['view_progress','查看进度','处理进度'],
  ['view_review_status','查看审核状态','审核状态'],
  ['view_budget','查看额度','累计用量'],
]) {
  test(`spec对齐：${label}可打开可读详情`, async ({ page }) => {
    await mountAlignmentCenter(page, route => route.fulfill({json:{items:[{...TASK,status:'completed',allowed_actions:[action],counts:{extracted:3,answered:2,failed:1},review_status:'pending',budget:{total_tokens:123}}],total:1}}))
    await page.getByRole('button',{name:label,exact:true}).click()
    await expect(page.getByRole('region',{name:label})).toBeVisible()
    await expect(page.getByRole('region',{name:label})).toContainText(detail)
    if (action === 'view_budget') await expect(page.getByRole('region',{name:label})).toContainText('123 tokens')
  })
}

test('spec对齐：打开及回焦立即刷新任务', async ({ page }) => {
  let calls = 0
  await mountAlignmentCenter(page, route => { calls++;return route.fulfill({json:{items:[{...TASK,status:'completed',allowed_actions:[]}],total:1}}) })
  await expect.poll(()=>calls).toBeGreaterThanOrEqual(2)
  const before = calls
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')))
  await expect.poll(()=>calls).toBeGreaterThan(before)
})


test('spec对齐：列表旧revision不能覆盖较新SSE', async ({ page }) => {
  const old = {...TASK,status:'running',revision:3,stage:'OLD_STAGE',allowed_actions:[]}
  const newer = {...old,status:'completed',revision:5,stage:'LATEST_STAGE'}
  await mountAlignmentCenter(page, route=>route.fulfill({json:{items:[old],total:1}}),[newer])
  await expect(page.getByText('当前阶段：LATEST_STAGE')).toBeVisible()
  await page.getByRole('button',{name:'刷新',exact:true}).click()
  await expect(page.getByText('当前阶段：LATEST_STAGE')).toBeVisible()
})

test('spec对齐：相同revision的SSE不能改写已有快照', async ({ page }) => {
  const old = {...TASK,status:'running',revision:3,stage:'OLD_STAGE',allowed_actions:[]}
  await mountAlignmentCenter(page, route=>route.fulfill({json:{items:[old],total:1}}),[
    {...old,revision:5,stage:'LATEST_STAGE'}, {...old,revision:5,stage:'STALE_EQUAL'},
  ])
  await expect(page.getByText('当前阶段：LATEST_STAGE')).toBeVisible()
  await expect(page.getByText('当前阶段：STALE_EQUAL')).toHaveCount(0)
})

test('spec对齐：真实提交composable接受任务后立即刷新中心', async ({ page }) => {
  let calls=0
  await mountAlignmentCenter(page, route=>{calls++;return route.fulfill({json:{items:[{...TASK,status:'completed',allowed_actions:[]}],total:1}})})
  await expect.poll(()=>calls).toBeGreaterThanOrEqual(2)
  const before=calls
  await page.evaluate(async()=>{
    const {submitUploadWithIdempotency}=await import('/src/composables/useSubmitJobs.js')
    const data=new FormData();data.set('text','TEST_SOURCE');
    await submitUploadWithIdempotency(data,{draftId:'alignment-accepted'})
  })
  await expect.poll(()=>calls).toBeGreaterThan(before)
})
