import { writeFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { configureDisposableUserModel } from '../_helpers/real-stack-model.js'

function pathOf(value) {
  return new URL(value).pathname
}

test('real multipart file rejection preserves draft and does not claim its idempotency key', async ({ page }) => {
  test.setTimeout(180000)
  test.skip(process.env.REAL_STACK_E2E !== '1', 'run through scripts/real_stack_smoke.sh')
  const tracePath = process.env.AC022_BROWSER_TRACE
  expect(tracePath, 'the runner must retain browser/API evidence').toBeTruthy()

  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
  const username = `ac022_${suffix}`
  const password = 'Ac022-real-stack-password-123'
  const text = `AC022_${suffix} rejected file must not create a task`
  const validPng = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ1sAAAAASUVORK5CYII=',
    'base64',
  )
  const fileLimitBytes = 10 * 1024 * 1024
  const oversizedFileBytes = 20 * 1024 * 1024 + 1
  const postResults = []
  const byKeyResponses = []

  await page.addInitScript(() => {
    window.__ac022SubmittedEntries = []
    window.__ac022CaptureFormData = true
    const originalAppend = FormData.prototype.append
    FormData.prototype.append = function (name, value, filename) {
      if (window.__ac022CaptureFormData && ['url', 'text', 'season', 'target', 'content_type', 'files'].includes(name)) {
        window.__ac022SubmittedEntries.push([name, value])
      }
      if (arguments.length === 2) return originalAppend.call(this, name, value)
      return originalAppend.call(this, name, value, filename)
    }
  })

  page.on('request', (request) => {
    if (pathOf(request.url()) !== '/api/submit-jobs' || request.method() !== 'POST') return
    postResults.push({
      key: request.headers()['idempotency-key'],
    })
  })
  page.on('response', (response) => {
    const url = new URL(response.url())
    if (url.pathname.startsWith('/api/upload-imports/by-key/')) {
      byKeyResponses.push({
        key: decodeURIComponent(url.pathname.split('/').pop()),
        status: response.status(),
      })
    }
  })

  await page.goto('/login')
  await page.getByRole('button', { name: '立即注册' }).click()
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByLabel('邮箱').fill(`${username}@example.test`)
  await page.getByRole('button', { name: '注册', exact: true }).click()
  await expect(page).toHaveURL(/\/master-bank/, { timeout: 30000 })
  await configureDisposableUserModel(page)
  await page.goto('/import')

  const textarea = page.getByPlaceholder('粘贴面经或 JD 内容...')
  const fileInput = page.locator('input[type="file"]')
  await textarea.fill(text)

  async function submitRejectedFile({ name, mimeType, buffer, status, detail }) {
    await fileInput.setInputFiles({ name, mimeType, buffer })
    await expect(page.getByText(name, { exact: true })).toBeVisible()
    const responsePromise = page.waitForResponse((response) =>
      pathOf(response.url()) === '/api/submit-jobs' && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '提交解析' }).click()
    const response = await responsePromise
    const body = response.status() === 413 ? null : await response.json()
    expect(response.status(), JSON.stringify(body)).toBe(status)
    if (body) expect(body.detail).toContain(detail)
    await expect(page.getByTestId('submit-error')).toContainText(detail)
    await expect(textarea).toHaveValue(text)
    await expect(page.getByText(name, { exact: true })).toBeVisible()
    return { response, body }
  }

  const unsupported = await submitRejectedFile({
    name: 'notes.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('not an image'),
    status: 400,
    detail: '不是有效的图片文件',
  })
  const idempotencyKey = postResults[0]?.key
  expect(idempotencyKey).toBeTruthy()

  async function assertKeyUnclaimed() {
    const lookup = await page.request.get(
      `/api/upload-imports/by-key/${encodeURIComponent(idempotencyKey)}`,
      { headers: { Authorization: unsupported.response.request().headers().authorization } },
    )
    expect(lookup.status(), await lookup.text()).toBe(404)
  }

  await assertKeyUnclaimed()
  await page.getByRole('button', { name: '移除图片 1' }).click()
  await submitRejectedFile({
    name: 'empty.png',
    mimeType: 'image/png',
    buffer: Buffer.alloc(0),
    status: 400,
    detail: '不是有效的图片文件',
  })
  await assertKeyUnclaimed()

  await page.getByRole('button', { name: '移除图片 1' }).click()
  const oversized = await submitRejectedFile({
    name: 'oversized.png',
    mimeType: 'image/png',
    buffer: Buffer.alloc(oversizedFileBytes, 0x41),
    status: 413,
    detail: '超过大小限制',
  })
  const oversizedHeaders = oversized.response.headers()
  const oversizedMeasurements = {
    limit_bytes: Number(oversizedHeaders['x-ac022-limit-bytes']),
    file_bytes_observed: Number(oversizedHeaders['x-ac022-file-bytes-observed']),
    file_bytes_buffered: Number(oversizedHeaders['x-ac022-file-bytes-buffered']),
    parser_spool_rolled: oversizedHeaders['x-ac022-parser-spool-rolled'],
    parser_spool_closed: oversizedHeaders['x-ac022-parser-spool-closed'],
    endpoint_file_read_bytes: Number(oversizedHeaders['x-ac022-endpoint-file-read-bytes']),
  }
  expect(oversizedMeasurements.limit_bytes).toBe(fileLimitBytes)
  expect(oversizedMeasurements.file_bytes_observed).toBeGreaterThan(fileLimitBytes)
  expect(oversizedMeasurements.file_bytes_observed).toBeLessThan(oversizedFileBytes)
  expect(oversizedMeasurements.file_bytes_buffered).toBeLessThanOrEqual(fileLimitBytes)
  expect(oversizedMeasurements.file_bytes_buffered).toBeLessThan(
    oversizedMeasurements.file_bytes_observed,
  )
  expect(oversizedMeasurements.parser_spool_rolled).toBe('true')
  expect(oversizedMeasurements.parser_spool_closed).toBe('true')
  expect(oversizedMeasurements.endpoint_file_read_bytes).toBe(0)
  await assertKeyUnclaimed()

  await page.getByRole('button', { name: '移除图片 1' }).click()
  await fileInput.setInputFiles({ name: 'corrected.png', mimeType: 'image/png', buffer: validPng })
  await page.evaluate(() => { window.__ac022SubmittedEntries = [] })
  const acceptedPromise = page.waitForResponse((response) =>
    pathOf(response.url()) === '/api/submit-jobs' && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '提交解析' }).click()
  const acceptedResponse = await acceptedPromise
  const accepted = await acceptedResponse.json()
  expect(acceptedResponse.status(), JSON.stringify(accepted)).toBe(202)
  expect(accepted.created).toBe(true)
  expect(accepted.idempotency_key).toBe(idempotencyKey)
  expect(postResults.map((entry) => entry.key)).toEqual([
    idempotencyKey,
    idempotencyKey,
    idempotencyKey,
    idempotencyKey,
  ])
  await expect(textarea).toHaveValue('')
  await page.evaluate(() => { window.__ac022CaptureFormData = false })
  const authorization = acceptedResponse.request().headers().authorization
  const replay = await page.evaluate(async ({ key, auth }) => {
    const form = new FormData()
    for (const [name, value] of window.__ac022SubmittedEntries) form.append(name, value)
    const response = await fetch('/api/submit-jobs', {
      method: 'POST',
      headers: {
        Authorization: auth,
        'X-Requested-With': 'XMLHttpRequest',
        'Idempotency-Key': key,
      },
      body: form,
    })
    return { status: response.status, body: await response.json() }
  }, { key: idempotencyKey, auth: authorization })
  expect(replay.status, JSON.stringify(replay.body)).toBe(202)
  expect(replay.body.import_id).toBe(accepted.import_id)
  expect(replay.body.created).toBe(false)

  const changedHash = await page.evaluate(async ({ key, auth, changedText }) => {
    const form = new FormData()
    for (const [name, value] of window.__ac022SubmittedEntries) {
      form.append(name, name === 'text' ? changedText : value)
    }
    const response = await fetch('/api/submit-jobs', {
      method: 'POST',
      headers: {
        Authorization: auth,
        'X-Requested-With': 'XMLHttpRequest',
        'Idempotency-Key': key,
      },
      body: form,
    })
    return { status: response.status, body: await response.json() }
  }, { key: idempotencyKey, auth: authorization, changedText: `${text} changed` })
  expect(changedHash.status, JSON.stringify(changedHash.body)).toBe(409)

  const lookupStatuses = byKeyResponses
    .filter((entry) => entry.key === idempotencyKey)
    .map((entry) => entry.status)
  expect(lookupStatuses.filter((status) => status === 404).length).toBeGreaterThanOrEqual(3)
  writeFileSync(tracePath, `${JSON.stringify({
    username,
    idempotency_key: idempotencyKey,
    rejected_statuses: [unsupported.response.status(), 400, 413],
    oversized_request_measurements: oversizedMeasurements,
    accepted_import_id: accepted.import_id,
    accepted_created: accepted.created,
    replay_import_id: replay.body.import_id,
    replay_created: replay.body.created,
    changed_hash_status: changedHash.status,
    submit_request_keys: postResults.map((entry) => entry.key),
    by_key_lookup_statuses: lookupStatuses,
    draft_preserved_after_rejection: true,
  }, null, 2)}\n`, { flag: 'wx' })
})
