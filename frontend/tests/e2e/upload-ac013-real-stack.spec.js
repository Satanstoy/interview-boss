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

async function waitForStatus(page, importId, token, status, timeout = 120000) {
  let latest
  await expect.poll(async () => {
    latest = await readSnapshot(page, importId, token)
    return latest.status
  }, { timeout, intervals: [1000, 2000, 5000] }).toBe(status)
  return latest
}

async function readFirstSnapshot(page, url, { token, method = 'GET', form } = {}) {
  const result = await page.evaluate(async ({ requestUrl, bearerToken, requestMethod, formValues }) => {
    const headers = {
      Authorization: `Bearer ${bearerToken}`,
      'X-Requested-With': 'XMLHttpRequest',
    }
    let body
    if (formValues) {
      body = new FormData()
      Object.entries(formValues).forEach(([key, value]) => body.append(key, value))
      headers['Idempotency-Key'] = formValues.idempotency_key
      body.delete('idempotency_key')
    }
    const response = await fetch(requestUrl, { method: requestMethod, headers, body })
    if (!response.ok) return { status: response.status, text: await response.text() }
    const reader = response.body.getReader()
    let text = ''
    try {
      while (!text.includes('\n\n')) {
        const chunk = await reader.read()
        if (chunk.done) break
        text += new TextDecoder().decode(chunk.value, { stream: true })
      }
    } finally {
      await reader.cancel()
    }
    const dataLine = text.split(/\r?\n/).find((line) => line.startsWith('data: '))
    return { status: response.status, text, data: dataLine ? JSON.parse(dataLine.slice(6)) : null }
  }, {
    requestUrl: url,
    bearerToken: token,
    requestMethod: method,
    formValues: form,
  })
  expect(result.status, result.text).toBe(200)
  expect(result.data, result.text).toBeTruthy()
  return result.data
}

function sourceText(marker) {
  return `${marker}\nAC013_PRIVATE_RAW_SENTINEL\n真实用户私有题干AC013_PRIVATE_QUESTION_SENTINEL`
}

async function submit(page, token, marker) {
  const idempotencyKey = `ac013-${marker.toLowerCase()}`
  const result = await page.evaluate(async ({ bearerToken, key, text }) => {
    const body = new FormData()
    body.append('text', text)
    body.append('season', '2026秋招')
    body.append('content_type', 'interview')
    body.append('target', 'private')
    const response = await fetch('/api/submit-jobs', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${bearerToken}`,
        'Idempotency-Key': key,
        'X-Requested-With': 'XMLHttpRequest',
      },
      body,
    })
    return { status: response.status, text: await response.text() }
  }, {
    bearerToken: token,
    key: idempotencyKey,
    text: sourceText(marker),
  })
  expect(result.status, result.text).toBe(202)
  return { ...JSON.parse(result.text), idempotency_key: idempotencyKey }
}

test('AC-013 uses real provider HTTP, shared budgets and read-only legacy SSE', async ({ page }) => {
  test.setTimeout(12 * 60 * 1000)
  test.skip(process.env.REAL_STACK_E2E !== '1', 'run through scripts/real_stack_smoke.sh')

  const seedPath = process.env.AC013_SEED_PATH
  const tracePath = process.env.AC013_BROWSER_TRACE
  const stubUrl = process.env.AC013_STUB_URL
  expect(seedPath).toBeTruthy()
  expect(tracePath).toBeTruthy()
  expect(stubUrl).toBeTruthy()
  const seed = JSON.parse(readFileSync(seedPath, 'utf8'))

  const loginPromise = page.waitForResponse((response) =>
    pathOf(response.url()) === '/api/auth/login' && response.request().method() === 'POST',
  )
  await page.goto('/login')
  await page.getByLabel('用户名').fill(seed.username)
  await page.getByLabel('密码').fill(seed.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  const login = await loginPromise
  const loginBody = await login.json()
  expect(login.status(), JSON.stringify(loginBody)).toBe(200)
  expect(loginBody.token).toBeTruthy()
  await expect(page).toHaveURL(/\/master-bank/, { timeout: 30000 })
  const token = loginBody.token

  const authAccepted = await submit(page, token, 'AC013_AUTH_401')
  const authSnapshot = await waitForStatus(page, authAccepted.import_id, token, 'needs_action')
  expect(authSnapshot.error).toMatchObject({
    code: 'MODEL_AUTH_INVALID', retryable: false, action: 'configure_user_model',
  })
  expect(authSnapshot.allowed_actions).toContain(authSnapshot.error.action)
  expect(authSnapshot.error.message).not.toContain('AC013_PRIVATE')
  const authSse = await readFirstSnapshot(
    page,
    `/api/upload-imports/${encodeURIComponent(authAccepted.import_id)}/stream`,
    { token },
  )
  expect(authSse.status).toBe('needs_action')
  expect(authSse.error.code).toBe('MODEL_AUTH_INVALID')

  const permissionAccepted = await submit(page, token, 'AC013_PERMISSION_403')
  const permissionSnapshot = await waitForStatus(
    page, permissionAccepted.import_id, token, 'needs_action',
  )
  expect(permissionSnapshot.error).toMatchObject({
    code: 'PERMISSION_REVOKED', retryable: false, action: 'check_permission',
  })
  expect(permissionSnapshot.allowed_actions).toContain(permissionSnapshot.error.action)
  expect(permissionSnapshot.error.message).not.toContain('AC013_PRIVATE')

  await page.reload()
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const taskCenter = page.getByRole('region', { name: '上传任务中心' })
  const authTask = taskCenter.locator('li').filter({ hasText: authAccepted.import_id })
  await expect(authTask).toContainText('需要配置')
  await expect(authTask.getByRole('button', { name: '去配置模型' })).toBeVisible()
  const permissionTask = taskCenter.locator('li').filter({ hasText: permissionAccepted.import_id })
  await expect(permissionTask).toContainText('需要配置')
  await expect(permissionTask.getByRole('button', { name: '检查模型权限' })).toBeVisible()
  await expect(authTask).not.toContainText('AC013_PRIVATE')
  await expect(permissionTask).not.toContainText('AC013_PRIVATE')

  const rateAccepted = await submit(page, token, 'AC013_RATE_429')
  const legacySse = await readFirstSnapshot(page, '/api/submit-stream-v2', {
    token,
    method: 'POST',
    form: {
      idempotency_key: rateAccepted.idempotency_key,
      text: sourceText('AC013_RATE_429'),
      season: '2026秋招',
      content_type: 'interview',
      target: 'private',
    },
  })
  expect(legacySse.import_id).toBe(rateAccepted.import_id)
  expect(['queued', 'running', 'failed', 'partial_failed']).toContain(legacySse.status)

  const rateFailed = await waitForStatus(
    page, rateAccepted.import_id, token, 'partial_failed', 240000,
  )
  expect(rateFailed.error).toMatchObject({
    code: 'UPSTREAM_RATE_LIMIT', retryable: true, action: 'retry_failed_steps',
  })
  expect(rateFailed.allowed_actions).toContain(rateFailed.error.action)
  const activeResponse = await page.request.get('/api/submit-jobs/active', {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(activeResponse.status()).toBe(200)
  const activeJobs = await activeResponse.json()
  const failedSubmitJob = activeJobs.find((job) => job.status === 'failed')
  expect(failedSubmitJob).toBeTruthy()

  const release = await page.request.post(`${stubUrl}/__e2e/release`, {
    data: { marker: 'AC013_RATE_429' },
    timeout: 5000,
  })
  expect(release.status()).toBe(200)
  const legacyRetryResponse = await page.request.post(
    `/api/submit-jobs/${failedSubmitJob.id}/retry`,
    { headers: {
      Authorization: `Bearer ${token}`,
      'X-Requested-With': 'XMLHttpRequest',
    } },
  )
  expect(legacyRetryResponse.status(), await legacyRetryResponse.text()).toBe(200)
  const legacyRetry = await legacyRetryResponse.json()
  expect(legacyRetry.created).toBe(true)
  const rateCompleted = await waitForStatus(
    page, rateAccepted.import_id, token, 'completed', 60000,
  )
  expect(rateCompleted.attempt_no).toBe(2)

  const formatAccepted = await submit(page, token, 'AC013_FORMAT_INVALID')
  const formatFailed = await waitForStatus(
    page, formatAccepted.import_id, token, 'partial_failed', 180000,
  )
  expect(formatFailed.error).toMatchObject({
    code: 'MODEL_OUTPUT_INVALID', retryable: true, action: 'retry_failed_steps',
  })
  expect(formatFailed.allowed_actions).toContain(formatFailed.error.action)

  const timeoutAccepted = await submit(page, token, 'AC013_TIMEOUT_ONCE')
  const timeoutCompleted = await waitForStatus(
    page, timeoutAccepted.import_id, token, 'completed', 180000,
  )
  expect(timeoutCompleted.error).toBeNull()

  const callResponse = await page.request.get(`${stubUrl}/__e2e/calls`)
  const physicalCalls = (await callResponse.json()).counts
  expect(physicalCalls).toMatchObject({
    AC013_AUTH_401: 1,
    AC013_PERMISSION_403: 1,
    AC013_RATE_429: 4,
    AC013_FORMAT_INVALID: 3,
    AC013_TIMEOUT_ONCE: 2,
  })
  const accessResponse = await page.request.get(`${stubUrl}/__e2e/access`)
  const providerAccess = await accessResponse.json()
  expect(providerAccess.marker_statuses).toMatchObject({
    AC013_AUTH_401: { '401': 1 },
    AC013_PERMISSION_403: { '403': 1 },
    AC013_RATE_429: { '429': 3, '200': 1 },
    AC013_FORMAT_INVALID: { '200': 3 },
    AC013_TIMEOUT_ONCE: { '200': 2 },
  })

  writeFileSync(tracePath, `${JSON.stringify({
    import_ids: {
      auth_401: authAccepted.import_id,
      permission_403: permissionAccepted.import_id,
      rate_429: rateAccepted.import_id,
      format_invalid: formatAccepted.import_id,
      timeout_once: timeoutAccepted.import_id,
    },
    api: {
      auth: authSnapshot,
      auth_sse: authSse,
      permission: permissionSnapshot,
      legacy_sse: legacySse,
      rate_failed: rateFailed,
      legacy_retry: legacyRetry,
      rate_completed: rateCompleted,
      format_failed: formatFailed,
      timeout_completed: timeoutCompleted,
    },
    provider_physical_calls: physicalCalls,
    provider_http_access: providerAccess,
  }, null, 2)}\n`, { flag: 'wx' })
})
