import { writeFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { configureDisposableUserModel } from '../_helpers/real-stack-model.js'

const IMPORT_ID = 'imp-ac007-owner-retry-real-stack'
const OWNER = 'ac007_owner'
const OTHER = 'ac007_other'
const PASSWORD = 'Ac007-owner-retry-real-stack-123!'

function pathOf(value) {
  return new URL(value).pathname
}

async function login(page, username, password) {
  await page.goto('/login')
  await page.locator('input[name="username"]').fill(username)
  await page.locator('input[name="password"]').fill(password)
  const responsePromise = page.waitForResponse((response) =>
    pathOf(response.url()) === '/api/auth/login' && response.request().method() === 'POST',
  )
  await page.locator('button[type="submit"]').first().click()
  const response = await responsePromise
  expect(response.status(), await response.text()).toBe(200)
  await expect(page).toHaveURL(/\/master-bank/, { timeout: 30000 })
}

async function snapshotFor(page, importId) {
  return page.evaluate(async (id) => {
    const refreshed = await fetch('/api/auth/refresh', {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
    if (!refreshed.ok) return { status: refreshed.status, body: null }
    const { token } = await refreshed.json()
    const response = await fetch(`/api/upload-imports/${encodeURIComponent(id)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    return { status: response.status, body: await response.json() }
  }, importId)
}

async function retryAs(page, importId) {
  return page.evaluate(async (id) => {
    const refreshed = await fetch('/api/auth/refresh', {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
    if (!refreshed.ok) return { status: refreshed.status, body: await refreshed.json() }
    const { token } = await refreshed.json()
    const response = await fetch(`/api/upload-imports/${encodeURIComponent(id)}/retry`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'X-Requested-With': 'XMLHttpRequest',
      },
    })
    return { status: response.status, body: await response.json() }
  }, importId)
}

test('owner retry is authorized, concurrent requests share one attempt, and worker resumes after restart', async ({ browser, page }) => {
  test.setTimeout(300000)
  test.skip(process.env.REAL_STACK_E2E !== '1', 'run through scripts/real_stack_smoke.sh')
  const tracePath = process.env.AC007_BROWSER_TRACE
  const restartSignal = process.env.AC007_WORKER_RESTART_SIGNAL
  const finishSignal = restartSignal && `${restartSignal}.finished`
  expect(tracePath, 'the runner must retain browser/API evidence').toBeTruthy()
  expect(restartSignal, 'the runner must restart the worker after owner requests').toBeTruthy()
  const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:18081'
  const otherContext = await browser.newContext({ baseURL })
  const adminContext = await browser.newContext({ baseURL })
  const owner2Context = await browser.newContext({ baseURL })

  try {
    await login(page, OWNER, PASSWORD)
    await configureDisposableUserModel(page)
    const owner2 = await owner2Context.newPage()
    await login(owner2, OWNER, PASSWORD)
    await configureDisposableUserModel(owner2)

    await page.goto('/')
    await page.getByRole('button', { name: '上传任务中心' }).click()
    const ownerTask = page.locator('li').filter({ hasText: IMPORT_ID })
    await expect(ownerTask).toContainText('部分失败')
    await expect(ownerTask.getByRole('button', { name: '重试失败步骤' })).toBeVisible()
    const initial = await snapshotFor(page, IMPORT_ID)
    expect(initial.status).toBe(200)
    expect(initial.body.allowed_actions).toContain('retry_failed_steps')
    expect(initial.body.recovery_available).toBe(true)

    await owner2.goto('/')
    await owner2.getByRole('button', { name: '上传任务中心' }).click()
    const owner2Task = owner2.locator('li').filter({ hasText: IMPORT_ID })
    await expect(owner2Task).toContainText('部分失败')
    await expect(owner2Task.getByRole('button', { name: '重试失败步骤' })).toBeVisible()

    const other = await otherContext.newPage()
    await login(other, OTHER, PASSWORD)
    const otherRetry = await retryAs(other, IMPORT_ID)
    expect(otherRetry.status).toBe(404)

    const admin = await adminContext.newPage()
    const adminUsername = process.env.REAL_STACK_ADMIN_USERNAME || 'real_stack_admin'
    const adminPassword = process.env.REAL_STACK_ADMIN_PASSWORD || 'real-stack-admin-password-123'
    await login(admin, adminUsername, adminPassword)
    const adminRetry = await retryAs(admin, IMPORT_ID)
    expect(adminRetry.status).toBe(404)

    const retryPath = `/api/upload-imports/${encodeURIComponent(IMPORT_ID)}/retry`
    const firstResponsePromise = page.waitForResponse((response) =>
      pathOf(response.url()) === retryPath && response.request().method() === 'POST',
    )
    const secondResponsePromise = owner2.waitForResponse((response) =>
      pathOf(response.url()) === retryPath && response.request().method() === 'POST',
    )
    await Promise.all([
      ownerTask.getByRole('button', { name: '重试失败步骤' }).click(),
      owner2Task.getByRole('button', { name: '重试失败步骤' }).click(),
    ])
    const [firstResponse, secondResponse] = await Promise.all([
      firstResponsePromise,
      secondResponsePromise,
    ])
    const first = await firstResponse.json()
    const second = await secondResponse.json()
    expect(firstResponse.status(), JSON.stringify(first)).toBe(200)
    expect(secondResponse.status(), JSON.stringify(second)).toBe(200)
    expect(first.attempt_no).toBe(2)
    expect(second.attempt_no).toBe(2)
    expect(first.import_id).toBe(IMPORT_ID)
    expect(second.import_id).toBe(IMPORT_ID)
    expect([first.created_attempt, second.created_attempt].sort()).toEqual([false, true])

    writeFileSync(restartSignal, 'owner retry accepted\n', { flag: 'wx' })
    await expect.poll(async () => {
      const snapshot = await snapshotFor(page, IMPORT_ID)
      if (snapshot.status !== 200) return `HTTP ${snapshot.status}`
      if (snapshot.body.status !== 'completed') return snapshot.body.status
      const answered = Number(snapshot.body.counts?.answered || 0)
      return answered > 0
        ? 'completed-with-all-answers'
        : `completed-without-answers-${answered}`
    }, {
      timeout: Number(process.env.AC007_COMPLETION_TIMEOUT_MS || 150000),
      intervals: [1000, 2000, 3000],
    }).toBe('completed-with-all-answers')

    const finished = await snapshotFor(page, IMPORT_ID)
    expect(finished.status).toBe(200)
    expect(finished.body.result?.interview_id).toBeTruthy()
    await expect(ownerTask.getByRole('button', { name: '查看结果' })).toBeVisible()
    await ownerTask.getByRole('button', { name: '查看结果' }).click()
    await expect(page).toHaveURL(/\/interview(?:\?|$)/)
    await expect(page.getByText('AC007 checkpoint question', { exact: false })).toBeVisible({ timeout: 30000 })
    writeFileSync(tracePath, `${JSON.stringify({
      import_id: IMPORT_ID,
      owner_id: Number(process.env.AC007_EXPECTED_OWNER_ID),
      initially_allowed_actions: initial.body.allowed_actions,
      owner_retries: [
        { status: firstResponse.status(), attempt_no: first.attempt_no, created_attempt: first.created_attempt },
        { status: secondResponse.status(), attempt_no: second.attempt_no, created_attempt: second.created_attempt },
      ],
      other_owner_retry_status: otherRetry.status,
      admin_retry_status: adminRetry.status,
      final_status: finished.body.status,
      result_interview_id: finished.body.result.interview_id,
      recovered_private_result_opened: true,
      worker_restarted_after_retry: true,
    }, null, 2)}\n`, { flag: 'wx' })
    writeFileSync(finishSignal, 'owner retry completed\n', { flag: 'wx' })
  } finally {
    await owner2Context.close()
    await otherContext.close()
    await adminContext.close()
  }
})
