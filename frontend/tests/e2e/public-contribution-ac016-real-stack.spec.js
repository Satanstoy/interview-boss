import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

const SOURCE_URL = 'https://ac016.example/interview/shared'
const QUESTION_A = 'AC016 question A: how does a distributed lock prevent stale writes?'
const QUESTION_B = 'AC016_FAIL_PUBLIC_B: how should a queue consumer enforce idempotency?'

function endpointPath(value) {
  return new URL(value).pathname
}

async function login(page, username, password) {
  const responsePromise = page.waitForResponse((response) =>
    endpointPath(response.url()) === '/api/auth/login' && response.request().method() === 'POST',
  )
  await page.goto('/login')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  const response = await responsePromise
  expect(response.status(), await response.text()).toBe(200)
  const body = await response.json()
  await expect(page).toHaveURL(/\/master-bank/, { timeout: 30000 })
  return body.token
}

async function api(page, token, method, path, data) {
  const response = await page.request.fetch(path, {
    method,
    headers: { Authorization: `Bearer ${token}` },
    data,
  })
  const body = response.status() === 204 ? null : await response.json()
  return { response, body }
}

async function readContribution(page, token, requestId) {
  const result = await api(
    page,
    token,
    'GET',
    `/api/admin/public-contributions/${requestId}`,
  )
  expect(result.response.status(), JSON.stringify(result.body)).toBe(200)
  return result.body
}

async function approve(page, token, requestId) {
  const result = await api(
    page,
    token,
    'POST',
    `/api/admin/public-contributions/${requestId}/approve`,
    {
      excluded_item_ids: [],
      review_fields: {
        source: { company: null, round: null, source_url: SOURCE_URL },
        items: [],
      },
    },
  )
  expect(result.response.status(), JSON.stringify(result.body)).toBe(200)
  return result.body
}

test('AC-016 real same-source append keeps the public projection cumulative and private source intact', async ({
  page,
  browser,
}) => {
  test.setTimeout(12 * 60 * 1000)
  expect(process.env.REAL_STACK_E2E).toBe('1')
  const seedPath = process.env.AC016_SEED_PATH
  const controlPrefix = process.env.AC016_WORKER_CONTROL_PREFIX
  const tracePath = process.env.AC016_BROWSER_RESULT_TRACE
  expect(seedPath).toBeTruthy()
  expect(controlPrefix).toBeTruthy()
  expect(tracePath).toBeTruthy()
  const seed = JSON.parse(readFileSync(seedPath, 'utf8'))

  let adminContext
  try {
    const ownerToken = await login(page, 'ac016_owner', 'Ac016-append-projection-real-stack-123!')
    adminContext = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL })
    const adminPage = await adminContext.newPage()
    const adminToken = await login(adminPage, 'real_stack_admin', 'real-stack-admin-password-123')

    const firstCreate = await api(page, ownerToken, 'POST', '/api/public-contributions', {
      source_type: 'interview',
      source_id: seed.interview_id,
    })
    expect(firstCreate.response.status(), JSON.stringify(firstCreate.body)).toBe(200)
    const firstRequestId = firstCreate.body.id
    const firstPending = await readContribution(adminPage, adminToken, firstRequestId)
    expect(firstPending.items).toHaveLength(1)
    const firstItemId = firstPending.items[0].id
    expect(firstPending.items[0].snapshot.question).toBe(QUESTION_A)

    const firstApproval = await approve(adminPage, adminToken, firstRequestId)
    const firstPublicInterviewId = firstApproval.public_interview_id
    await expect.poll(async () => {
      const state = await readContribution(adminPage, adminToken, firstRequestId)
      return state.items[0]?.status
    }, { timeout: 360000, intervals: [1000, 2000, 5000] }).toBe('published')
    const firstPublished = await readContribution(adminPage, adminToken, firstRequestId)
    const firstPublicDetailId = firstPublished.items[0].public_detail_id

    writeFileSync(`${controlPrefix}.append-b`, `${seed.interview_id}\n`, { flag: 'wx' })
    await expect.poll(() => existsSync(`${controlPrefix}.source-updated`), { timeout: 30000 }).toBe(true)

    const secondCreate = await api(page, ownerToken, 'POST', '/api/public-contributions', {
      source_type: 'interview',
      source_id: seed.interview_id,
    })
    expect(secondCreate.response.status(), JSON.stringify(secondCreate.body)).toBe(200)
    const secondRequestId = secondCreate.body.id
    expect(secondRequestId).not.toBe(firstRequestId)
    const secondPending = await readContribution(adminPage, adminToken, secondRequestId)
    expect(secondPending.summary.item_count).toBe(1)
    expect(secondPending.items).toHaveLength(1)
    const failedCandidateItem = secondPending.items[0]
    expect(failedCandidateItem.id).not.toBe(firstItemId)
    expect(failedCandidateItem.source_item_id).not.toBe(firstPending.items[0].source_item_id)
    expect(failedCandidateItem.snapshot.question).toBe(QUESTION_B)

    const secondApproval = await approve(adminPage, adminToken, secondRequestId)
    expect(secondApproval.public_interview_id).toBe(firstPublicInterviewId)
    const secondApproved = await readContribution(adminPage, adminToken, secondRequestId)
    const secondPublicDetailId = secondApproved.items[0].public_detail_id
    expect(secondPublicDetailId).toBeTruthy()

    await expect.poll(async () => {
      const state = await readContribution(adminPage, adminToken, secondRequestId)
      return state.items[0]?.status
    }, { timeout: 360000, intervals: [1000, 2000, 5000] }).toBe('failed')
    const failedSecond = await readContribution(adminPage, adminToken, secondRequestId)
    const injectedFailure = failedSecond.items[0].error_message
    expect(injectedFailure).toContain('AC016_PUBLIC_ITEM_FAILURE')

    const publicBeforeRetryResult = await api(
      page,
      ownerToken,
      'GET',
      '/api/data/interview?scope=public&page=1&page_size=100&sort=created_at_desc',
    )
    expect(publicBeforeRetryResult.response.status()).toBe(200)
    const publicBeforeRetry = publicBeforeRetryResult.body.items.find(
      (item) => item.id === firstPublicInterviewId,
    )
    expect(publicBeforeRetry).toBeTruthy()
    expect(publicBeforeRetry['来源链接']).toBe(SOURCE_URL)
    expect(publicBeforeRetry['具体题目清单'].split('\n').filter(Boolean)).toHaveLength(1)
    expect(publicBeforeRetry['具体题目清单']).toContain(QUESTION_A)
    expect(publicBeforeRetry['具体题目清单']).not.toContain(QUESTION_B)

    writeFileSync(`${controlPrefix}.stop`, `${secondRequestId}\n`, { flag: 'wx' })
    await expect.poll(() => existsSync(`${controlPrefix}.restarted`), { timeout: 90000 }).toBe(true)
    const afterWorkerRestart = await readContribution(adminPage, adminToken, secondRequestId)
    expect(afterWorkerRestart.items[0]?.status).toBe('failed')
    expect(afterWorkerRestart.items[0]?.error_message).toContain('AC016_PUBLIC_ITEM_FAILURE')
    const publicAfterRestartResult = await api(
      page,
      ownerToken,
      'GET',
      '/api/data/interview?scope=public&page=1&page_size=100&sort=created_at_desc',
    )
    expect(publicAfterRestartResult.response.status()).toBe(200)
    const publicAfterRestart = publicAfterRestartResult.body.items.find(
      (item) => item.id === firstPublicInterviewId,
    )
    expect(publicAfterRestart).toBeTruthy()
    expect(publicAfterRestart['具体题目清单']).toContain(QUESTION_A)
    expect(publicAfterRestart['具体题目清单']).not.toContain(QUESTION_B)
    const retry = await api(
      adminPage,
      adminToken,
      'POST',
      `/api/admin/public-contributions/${secondRequestId}/retry`,
      {},
    )
    expect(retry.response.status(), JSON.stringify(retry.body)).toBe(200)
    expect(retry.body.reprocessed_item_ids).toEqual([failedCandidateItem.id])

    writeFileSync(`${controlPrefix}.restart`, `${secondRequestId}\n`, { flag: 'wx' })
    await expect.poll(() => existsSync(`${controlPrefix}.done`), { timeout: 90000 }).toBe(true)
    await expect.poll(async () => {
      const state = await readContribution(adminPage, adminToken, secondRequestId)
      return state.items[0]?.status
    }, { timeout: 360000, intervals: [1000, 2000, 5000] }).toBe('published')

    const finalFirst = await readContribution(adminPage, adminToken, firstRequestId)
    const finalSecond = await readContribution(adminPage, adminToken, secondRequestId)
    expect(finalFirst.items[0].status).toBe('published')
    expect(finalFirst.items[0].public_detail_id).toBe(firstPublicDetailId)
    expect(finalSecond.items[0].public_detail_id).toBe(secondPublicDetailId)

    const publicAfterResult = await api(
      page,
      ownerToken,
      'GET',
      '/api/data/interview?scope=public&page=1&page_size=100&sort=created_at_desc',
    )
    expect(publicAfterResult.response.status()).toBe(200)
    const publicAfter = publicAfterResult.body.items.find(
      (item) => item.id === firstPublicInterviewId,
    )
    expect(publicAfter).toBeTruthy()
    const publicLines = publicAfter['具体题目清单'].split('\n').filter(Boolean)
    expect(publicLines).toHaveLength(2)
    expect(publicAfter['具体题目清单'].indexOf(QUESTION_A)).toBeLessThan(
      publicAfter['具体题目清单'].indexOf(QUESTION_B),
    )
    expect(publicLines.filter((line) => line.includes(QUESTION_A))).toHaveLength(1)
    expect(publicLines.filter((line) => line.includes(QUESTION_B))).toHaveLength(1)

    const privateAfterResult = await api(
      page,
      ownerToken,
      'GET',
      '/api/data/interview?scope=mine&page=1&page_size=100&sort=created_at_desc',
    )
    expect(privateAfterResult.response.status()).toBe(200)
    const privateAfter = privateAfterResult.body.items.find((item) => item.id === seed.interview_id)
    expect(privateAfter).toBeTruthy()
    expect(privateAfter['来源链接']).toBe(SOURCE_URL)
    expect(privateAfter['具体题目清单']).toContain(QUESTION_A)
    expect(privateAfter['具体题目清单']).toContain(QUESTION_B)
    expect(privateAfter['公司']).toBe('AC016 private company sentinel')

    writeFileSync(tracePath, `${JSON.stringify({
      source_interview_id: seed.interview_id,
      source_detail_a_id: seed.source_detail_a_id,
      first_request_id: firstRequestId,
      first_item_id: firstItemId,
      first_public_detail_id: firstPublicDetailId,
      second_request_id: secondRequestId,
      second_item_id: failedCandidateItem.id,
      second_source_item_id: failedCandidateItem.source_item_id,
      second_public_detail_id: secondPublicDetailId,
      public_interview_id: firstPublicInterviewId,
      source_url: SOURCE_URL,
      question_a: QUESTION_A,
      question_b: QUESTION_B,
      public_questions_before_retry: publicBeforeRetry['具体题目清单'],
      public_questions_after_worker_restart: publicAfterRestart['具体题目清单'],
      public_questions_after_retry: publicAfter['具体题目清单'],
      private_questions_after_retry: privateAfter['具体题目清单'],
      failed_before_retry: true,
      injected_failure_error_message: injectedFailure,
      worker_restarted_before_admin_retry: existsSync(`${controlPrefix}.restarted`),
      final_request_statuses: [finalFirst.status, finalSecond.status],
    }, null, 2)}\n`, { flag: 'wx' })
  } finally {
    await adminContext?.close()
  }
})
