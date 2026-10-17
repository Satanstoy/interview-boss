import { existsSync, writeFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

const PASSWORD = 'Ac010-real-stack-account-switch-123!'
const CONTROL_TOKEN = 'real-stack-ac010-control-token'

async function login(page, username) {
  await page.goto('/login')
  await page.locator('input[name="username"]').first().fill(username)
  await page.locator('input[name="password"]').first().fill(PASSWORD)
  await page.locator('button[type="submit"]').first().click()
  await expect(page).toHaveURL(/\/master-bank/, { timeout: 30000 })
}

async function proxyEvidence(page) {
  const response = await page.evaluate(async (token) => {
    const result = await fetch('/__ac010/events', {
      headers: { 'X-AC010-Control': token },
      cache: 'no-store',
    })
    return { status: result.status, body: await result.json() }
  }, CONTROL_TOKEN)
  expect(response.status, JSON.stringify(response.body)).toBe(200)
  return response.body
}

test('real task API/SSE retains last good state through faults and isolates account switch', async ({
  browser,
  page,
}) => {
  test.setTimeout(180000)
  test.skip(process.env.REAL_STACK_E2E !== '1', 'run through scripts/real_stack_smoke.sh')

  const seedPath = process.env.AC010_SEED_PATH
  const revisionSignal = process.env.AC010_REVISION7_SIGNAL
  const revisionReady = process.env.AC010_REVISION7_SIGNAL_READY
  const tracePath = process.env.AC010_BROWSER_TRACE
  expect(seedPath).toBeTruthy()
  expect(revisionSignal).toBeTruthy()
  expect(revisionReady).toBeTruthy()
  expect(tracePath).toBeTruthy()
  expect(existsSync(seedPath), 'the candidate runner must seed the disposable DB').toBe(true)

  const seed = JSON.parse(await import('node:fs/promises').then(({ readFile }) => readFile(seedPath, 'utf8')))
  const [user1, user2] = seed.roots
  const user2Failed = seed.roots[2]
  const network = []
  let truncateNextStream = true
  let failTaskList = false
  let failTaskSnapshot = false
  let failRecovery = false
  let delayTaskListUnauthorized = false
  let taskAuthorization = ''

  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname.startsWith('/api/upload-imports')) {
      if (url.pathname === '/api/upload-imports' && request.headers().authorization) {
        taskAuthorization = request.headers().authorization
      }
      network.push({
        type: 'request',
        method: request.method(),
        path: url.pathname,
        fault: request.headers()['x-ac010-fault'] || '',
      })
    }
  })
  page.on('response', (response) => {
    const url = new URL(response.url())
    if (url.pathname.startsWith('/api/upload-imports')) {
      network.push({ type: 'response', method: response.request().method(), path: url.pathname, status: response.status() })
    }
  })
  page.on('requestfailed', (request) => {
    const url = new URL(request.url())
    if (url.pathname.endsWith('/stream')) {
      network.push({ type: 'requestfailed', path: url.pathname, failure: request.failure()?.errorText || '' })
    }
  })
  await page.route('**/api/upload-imports**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const headers = { ...request.headers() }
    if (url.pathname.endsWith('/stream') && truncateNextStream) {
      headers['x-ac010-fault'] = 'truncate-after-snapshot'
      truncateNextStream = false
    } else if (url.pathname === '/api/upload-imports' && request.method() === 'GET' && delayTaskListUnauthorized) {
      headers['x-ac010-fault'] = 'delay-401'
    } else if (url.pathname === '/api/upload-imports' && request.method() === 'GET' && failTaskList) {
      headers['x-ac010-fault'] = 'http-500'
    } else if (url.pathname === `/api/upload-imports/${encodeURIComponent(user1.import_id)}` && failTaskSnapshot) {
      headers['x-ac010-fault'] = 'http-500'
    } else if (
      request.method() === 'POST' &&
      url.pathname === `/api/upload-imports/${encodeURIComponent(user2Failed.import_id)}/retry` &&
      failRecovery
    ) {
      headers['x-ac010-fault'] = 'http-500'
    }
    await route.continue({ headers })
  })

  const otherContext = await browser.newContext({
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:18081',
  })
  const otherPage = await otherContext.newPage()

  try {
    await Promise.all([login(page, user1.username), login(otherPage, user2.username)])

    const centerButton = page.getByRole('button', { name: '上传任务中心' })
    await centerButton.click()
    const center = page.getByRole('region', { name: '上传任务中心' })
    const ownTask = center.locator('li').filter({ hasText: user1.import_id })
    await expect(ownTask).toBeVisible()
    await expect(ownTask.getByRole('status')).toHaveText('处理中')
    await expect(ownTask.getByText('0/1 题已处理')).toBeVisible()
    const crossOwnerSnapshot = await page.evaluate(async ({ importId, authorization }) => {
      const response = await fetch(`/api/upload-imports/${encodeURIComponent(importId)}`, {
        headers: { Authorization: authorization },
      })
      return { status: response.status }
    }, { importId: user2.import_id, authorization: taskAuthorization })
    expect(crossOwnerSnapshot.status).toBe(404)

    await expect.poll(async () => {
      const state = await proxyEvidence(page)
      return state.events.some((event) =>
        event.path === `/api/upload-imports/${user1.import_id}/stream` &&
        event.event === 'snapshot' && event.snapshot?.revision === 8 &&
        event.snapshot?.status === 'running',
      )
    }, { timeout: 15000 }).toBe(true)

    writeFileSync(revisionSignal, JSON.stringify({ import_id: user1.import_id, observed_revision: 8 }), { flag: 'wx' })
    await expect.poll(() => existsSync(revisionReady), { timeout: 15000 }).toBe(true)
    await expect.poll(async () => {
      const state = await proxyEvidence(page)
      return state.events.some((event) =>
        event.path === `/api/upload-imports/${user1.import_id}/stream` &&
        event.event === 'snapshot' && event.snapshot?.revision === 7 &&
        event.snapshot?.status === 'running',
      )
    }, { timeout: 20000 }).toBe(true)
    await expect(ownTask.getByRole('status')).toHaveText('处理中')
    await expect(ownTask.getByText('0/1 题已处理')).toBeVisible()

    failTaskList = true
    await center.getByRole('button', { name: '刷新' }).click()
    await expect(center.getByText('AC010 injected task GET failure')).toBeVisible({ timeout: 15000 })
    await expect(ownTask).toBeVisible()
    await expect(ownTask.getByRole('status')).toHaveText('处理中')
    await expect(ownTask.getByText('0/1 题已处理')).toBeVisible()

    failTaskSnapshot = true
    const snapshotFailure = await page.evaluate(async ({ importId, authorization }) => {
      const response = await fetch(`/api/upload-imports/${encodeURIComponent(importId)}`, {
        headers: { Authorization: authorization },
      })
      return { status: response.status }
    }, { importId: user1.import_id, authorization: taskAuthorization })
    expect(snapshotFailure.status).toBe(500)
    failTaskSnapshot = false

    const beforeHeartbeat = {
      status: await ownTask.getByRole('status').innerText(),
      progress: await ownTask.getByRole('progressbar').getAttribute('aria-valuenow'),
      progressText: await ownTask.getByText('0/1 题已处理').innerText(),
      counts: await ownTask.getByText(/答案已生成/).innerText(),
    }
    await expect.poll(async () => {
      const state = await proxyEvidence(page)
      return state.events.some((event) =>
        event.path === `/api/upload-imports/${user1.import_id}/stream` && event.event === 'heartbeat',
      )
    }, { timeout: 25000 }).toBe(true)
    await expect(ownTask).toBeVisible()
    await expect(ownTask.getByRole('status')).toHaveText(beforeHeartbeat.status)
    await expect(ownTask.getByRole('progressbar')).toHaveAttribute('aria-valuenow', beforeHeartbeat.progress)
    await expect(ownTask.getByText('0/1 题已处理')).toHaveText(beforeHeartbeat.progressText)
    await expect(ownTask.getByText(/答案已生成/)).toHaveText(beforeHeartbeat.counts)
    await expect(ownTask.getByRole('status')).toHaveText('处理中')
    await expect(ownTask.getByText('0/1 题已处理')).toBeVisible()

    const cachedUser = await page.evaluate(async (authorization) => {
      const response = await fetch('/api/auth/me', { headers: { Authorization: authorization } })
      return response.json()
    }, taskAuthorization)
    expect(cachedUser.id).toBe(user1.user_id)
    await page.evaluate((userId) => {
      localStorage.setItem(`interviewboss-submit-draft:${userId}:ac010-private`, 'private-u1-draft')
    }, user1.user_id)

    delayTaskListUnauthorized = true
    const delayedListResponse = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return url.pathname === '/api/upload-imports' && response.status() === 401
    })
    const refreshAfterUnauthorized = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return url.pathname === '/api/auth/refresh' && response.status() === 401
    })
    await center.getByRole('button', { name: '刷新' }).click()
    await expect.poll(async () => {
      const state = await proxyEvidence(page)
      return state.requests.some((request) => request.path === '/api/upload-imports' && request.mode === 'delay-401')
    }, { timeout: 10000 }).toBe(true)

    const userMenu = page.getByRole('button').filter({ hasText: user1.username }).first()
    await userMenu.click()
    await page.getByRole('button', { name: '退出登录' }).click()
    await expect(page.locator('input[name="username"]').first()).toBeVisible({ timeout: 15000 })
    expect((await delayedListResponse).status()).toBe(401)
    expect((await refreshAfterUnauthorized).status()).toBe(401)
    await expect(page.getByRole('button', { name: '关闭', exact: true })).toHaveCount(0)
    await expect.poll(() => page.evaluate((userId) =>
      localStorage.getItem(`interviewboss-submit-draft:${userId}:ac010-private`), user1.user_id,
    )).toBeNull()
    delayTaskListUnauthorized = false
    failTaskList = false

    await page.locator('input[name="username"]').first().fill(user2.username)
    await page.locator('input[name="password"]').first().fill(PASSWORD)
    await page.locator('button[type="submit"]').first().click()
    await expect(page).toHaveURL(/\/master-bank/, { timeout: 30000 })
    const switchedCenter = page.getByRole('region', { name: '上传任务中心' })
    const otherTask = switchedCenter.locator('li').filter({
      hasText: new RegExp(`${user2.import_id}(?!-recoverable)`),
    })
    await expect(otherTask).toBeVisible({ timeout: 15000 })
    const recoverableTask = switchedCenter.locator('li').filter({ hasText: user2Failed.import_id })
    await expect(recoverableTask).toBeVisible()
    await expect(switchedCenter.locator('li').filter({ hasText: user1.import_id })).toHaveCount(0)

    const switchedUserCache = await page.evaluate(async (authorization) => {
      const response = await fetch('/api/auth/me', { headers: { Authorization: authorization } })
      return response.json()
    }, taskAuthorization)
    expect(switchedUserCache.id).toBe(user2.user_id)

    await page.evaluate((userId) => {
      localStorage.setItem(`interviewboss-submit-draft:${userId}:ac010-recovery`, 'private-u2-draft')
    }, user2.user_id)
    failRecovery = true
    await recoverableTask.getByRole('button', { name: '重试失败步骤' }).click()
    await expect(switchedCenter.getByText('AC010 injected task recovery failure')).toBeVisible()
    await expect(recoverableTask).toBeVisible()
    await expect(recoverableTask.getByRole('status')).toHaveText('部分失败')
    await expect.poll(() => page.evaluate((userId) =>
      localStorage.getItem(`interviewboss-submit-draft:${userId}:ac010-recovery`), user2.user_id,
    )).toBe('private-u2-draft')
    failRecovery = false

    const evidence = await proxyEvidence(page)
    const user1Streams = evidence.requests.filter((request) =>
      request.path === `/api/upload-imports/${user1.import_id}/stream`,
    )
    const user2Streams = evidence.requests.filter((request) =>
      request.path === `/api/upload-imports/${user2.import_id}/stream`,
    )
    expect(user1Streams.length).toBeGreaterThanOrEqual(2)
    expect(user2Streams.length).toBeGreaterThan(0)
    expect(network.filter((event) =>
      event.type === 'request' && event.path === `/api/upload-imports/${user2.import_id}/stream`,
    ).length).toBeGreaterThan(0)
    const user1StreamCountAtSwitch = network.filter((event) =>
      event.type === 'request' && event.path === `/api/upload-imports/${user1.import_id}/stream`,
    ).length
    await page.waitForTimeout(1500)
    expect(network.filter((event) =>
      event.type === 'request' && event.path === `/api/upload-imports/${user1.import_id}/stream`,
    )).toHaveLength(user1StreamCountAtSwitch)

    writeFileSync(tracePath, `${JSON.stringify({
      users: seed.roots.map(({ username, user_id, import_id }) => ({ username, user_id, import_id })),
      initial_snapshot_revision: 8,
      stale_snapshot_revision: 7,
      stale_revision_kept_out_of_ui: true,
      list_get_failure_statuses: evidence.requests
        .filter((request) => request.path === '/api/upload-imports' && request.mode === 'http-500')
        .map((request) => request.status),
      detail_get_failure_statuses: evidence.requests
        .filter((request) => request.path === `/api/upload-imports/${user1.import_id}` && request.mode === 'http-500')
        .map((request) => request.status),
      recovery_failure_statuses: evidence.requests
        .filter((request) =>
          request.path === `/api/upload-imports/${user2Failed.import_id}/retry` &&
          request.mode === 'http-500',
        )
        .map((request) => request.status),
      heartbeat_seen: evidence.events.some((event) =>
        event.path === `/api/upload-imports/${user1.import_id}/stream` && event.event === 'heartbeat',
      ),
      user1_stream_count_at_switch: user1StreamCountAtSwitch,
      user2_stream_count_after_switch: user2Streams.length,
      old_draft_cleared: true,
      recovery_draft_preserved: true,
      generic_get_cache_user_after_switch: switchedUserCache.id,
      network,
      proxy: evidence,
    }, null, 2)}\n`, { flag: 'wx' })
  } finally {
    await otherContext.close()
  }
})
