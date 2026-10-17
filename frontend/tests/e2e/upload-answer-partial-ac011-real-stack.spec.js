import { readFileSync, writeFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

function pathOf(value) {
  return new URL(value).pathname
}

async function readSnapshot(page, importId, token) {
  const response = await page.request.get(`/api/upload-imports/${encodeURIComponent(importId)}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(response.status(), await response.text()).toBe(200)
  return response.json()
}

async function readTerminalSseSnapshot(page, importId, token) {
  const result = await page.evaluate(async ({ id, bearerToken }) => {
    const response = await fetch(`/api/upload-imports/${encodeURIComponent(id)}/stream`, {
      headers: { Authorization: `Bearer ${bearerToken}` },
    })
    if (!response.ok) return { status: response.status, text: '' }
    const reader = response.body.getReader()
    const first = await reader.read()
    await reader.cancel()
    return { status: response.status, text: new TextDecoder().decode(first.value || new Uint8Array()) }
  }, { id: importId, bearerToken: token })
  expect(result.status).toBe(200)
  const dataLine = result.text.split(/\r?\n/).find((line) => line.startsWith('data: '))
  expect(dataLine, result.text).toBeTruthy()
  return JSON.parse(dataLine.slice('data: '.length))
}

test('AC-011 restores only two failed answers through the real browser, API, worker and provider', async ({ page }) => {
  test.setTimeout(12 * 60 * 1000)
  test.skip(process.env.REAL_STACK_E2E !== '1', 'run through scripts/real_stack_smoke.sh')

  const seedPath = process.env.AC011_SEED_PATH
  const releaseSignal = process.env.AC011_RELEASE_SIGNAL
  const releaseDone = process.env.AC011_RELEASE_DONE
  const browserDone = process.env.AC011_BROWSER_DONE
  const tracePath = process.env.AC011_BROWSER_TRACE
  expect(seedPath).toBeTruthy()
  expect(releaseSignal).toBeTruthy()
  expect(releaseDone).toBeTruthy()
  expect(browserDone).toBeTruthy()
  expect(tracePath).toBeTruthy()
  const seed = JSON.parse(readFileSync(seedPath, 'utf8'))
  const { import_id: importId, interview_id: interviewId, username, password } = seed

  const loginPromise = page.waitForResponse((response) =>
    pathOf(response.url()) === '/api/auth/login' && response.request().method() === 'POST',
  )
  await page.goto('/login')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  const login = await loginPromise
  const loginBody = await login.json()
  expect(login.status(), JSON.stringify(loginBody)).toBe(200)
  expect(loginBody.token).toBeTruthy()
  await expect(page).toHaveURL(/\/master-bank/, { timeout: 30000 })

  await page.getByRole('button', { name: '上传任务中心' }).click()
  const task = page.locator('li').filter({ hasText: importId })
  await expect(task).toContainText('部分失败', { timeout: 360000 })
  await expect(task).toContainText('答案成功 8 · 失败 2')
  await expect(task.getByRole('button', { name: '重试失败步骤' })).toBeVisible()
  await expect(task.getByRole('button', { name: '查看结果' })).toBeVisible()

  const firstSnapshot = await readSnapshot(page, importId, loginBody.token)
  expect(firstSnapshot.status).toBe('partial_failed')
  expect(firstSnapshot.progress).toMatchObject({ unit: 'questions', total: 10, completed: 10 })
  expect(firstSnapshot.counts).toMatchObject({ total: 10, answered: 8, failed: 2, resolved: 10 })
  expect(firstSnapshot.error).toMatchObject({ code: 'UPSTREAM_UNAVAILABLE', retryable: true })
  expect(firstSnapshot.allowed_actions).toContain('retry_failed_steps')
  expect(firstSnapshot.allowed_actions).toContain('open_result')
  const firstSseSnapshot = await readTerminalSseSnapshot(page, importId, loginBody.token)
  expect(firstSseSnapshot.status).toBe('partial_failed')
  expect(firstSseSnapshot.progress).toMatchObject({ unit: 'questions', total: 10, completed: 10 })
  expect(firstSseSnapshot.counts).toMatchObject({ total: 10, answered: 8, failed: 2, resolved: 10 })
  expect(firstSseSnapshot.error).toMatchObject({ code: 'UPSTREAM_UNAVAILABLE', retryable: true })

  // The shell snapshots SQLite and releases just the two failed provider keys.
  writeFileSync(releaseSignal, `${importId}\n`, { flag: 'wx' })
  await expect.poll(() => {
    try {
      return readFileSync(releaseDone, 'utf8').trim()
    } catch {
      return ''
    }
  }, { timeout: 60000 }).toBe(importId)

  await page.waitForTimeout(6000)
  await task.getByRole('button', { name: '查看结果' }).click()
  await expect(page).toHaveURL(/\/interview(?:\?|$)/)
  await expect(page.locator(`[data-row-id="${interviewId}"]`)).toBeVisible()
  await expect(page.locator(`[data-row-id="${interviewId}"]`)).toContainText('AC011_QUESTION_01')

  await page.getByRole('button', { name: '上传任务中心' }).click()
  const retryResponsePromise = page.waitForResponse((response) =>
    pathOf(response.url()) === `/api/upload-imports/${encodeURIComponent(importId)}/retry` &&
    response.request().method() === 'POST',
  )
  await task.getByRole('button', { name: '重试失败步骤' }).click()
  const retryResponse = await retryResponsePromise
  expect(retryResponse.status(), await retryResponse.text()).toBe(200)
  const retrySnapshot = await retryResponse.json()
  expect(retrySnapshot.created_attempt).toBe(true)
  expect(retrySnapshot.attempt_no).toBe(2)

  await expect.poll(async () => (await readSnapshot(page, importId, loginBody.token)).status, {
    timeout: 360000,
    intervals: [1000, 2000, 5000],
  }).toBe('completed')
  await page.reload()
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const completedTask = page.locator('li').filter({ hasText: importId })
  await expect(completedTask).toContainText('已完成')
  await expect(completedTask).toContainText('答案成功 10 · 失败 0')

  // Result history stays openable after the terminal status has aged past 5 seconds.
  await page.waitForTimeout(6000)
  await completedTask.getByRole('button', { name: '查看结果' }).click()
  await expect(page).toHaveURL(/\/interview(?:\?|$)/)
  await expect(page.locator(`[data-row-id="${interviewId}"]`)).toBeVisible()

  writeFileSync(
    tracePath,
    `${JSON.stringify({
      import_id: importId,
      interview_id: interviewId,
      login_status: login.status(),
      first_snapshot: firstSnapshot,
      first_sse_snapshot: firstSseSnapshot,
      retry_http_status: retryResponse.status(),
      retry_created_attempt: retrySnapshot.created_attempt,
      final_snapshot: await readSnapshot(page, importId, loginBody.token),
      result_opened_after_partial_failure: true,
      result_reopened_after_completed_wait_ms: 6000,
    }, null, 2)}\n`,
    { flag: 'wx' },
  )
  writeFileSync(browserDone, `${importId}\n`, { flag: 'wx' })
})
