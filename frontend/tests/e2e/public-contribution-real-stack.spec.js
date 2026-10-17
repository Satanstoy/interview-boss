import { existsSync, writeFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { configureDisposableUserModel } from '../_helpers/real-stack-model.js'

const ROOT_QUESTIONS = [
  [10, 'Agent 与普通工作流的核心区别是什么？'],
  [20, '多智能体系统如何设计任务协作？'],
  [30, 'RAG 检索结果不相关时如何定位问题？'],
  [40, 'Agent 执行链路出现死循环如何自动恢复？'],
  [50, 'MCP 与 Function Calling 有哪些区别？'],
]
const EXPECTED_EXTRACTED_QUESTIONS = ROOT_QUESTIONS.map(([ordinal, question]) =>
  ordinal === 40 ? `${question} AC029_FAIL_PUBLIC_ORDINAL_40` : question,
)
const EDITED_QUESTION = 'AC029 管理员修订后的题面'

function endpointPath(value) {
  return new URL(value).pathname
}

async function registerUser(page, prefix) {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
  const username = `${prefix}_${suffix}`
  const registration = page.waitForResponse((response) =>
    endpointPath(response.url()) === '/api/auth/register' && response.request().method() === 'POST',
  )
  await page.goto('/login')
  await page.getByRole('button', { name: '立即注册' }).click()
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill('Ac029-public-real-stack-123!')
  await page.getByLabel('邮箱').fill(`${username}@example.test`)
  await page.getByRole('button', { name: '注册', exact: true }).click()
  const response = await registration
  expect(response.status(), await response.text()).toBe(200)
  const body = await response.json()
  await expect(page).toHaveURL(/\/master-bank/, { timeout: 30000 })
  return { username, token: body.token, user: body.user }
}

async function api(page, token, method, path, data) {
  const response = await page.request.fetch(path, {
    method,
    headers: { Authorization: `Bearer ${token}` },
    data,
  })
  return { response, body: response.status() === 204 ? null : await response.json() }
}

async function readJson(page, token, path, expectedStatus = 200) {
  const result = await api(page, token, 'GET', path)
  expect(result.response.status(), JSON.stringify(result.body)).toBe(expectedStatus)
  return result.body
}

test('real upload → admin redacted review → one failed public item recovery preserves item identity', async ({ page, browser }) => {
  test.setTimeout(22 * 60 * 1000)
  expect(process.env.REAL_STACK_E2E).toBe('1')
  const signalPrefix = process.env.AC029_WORKER_CONTROL_PREFIX
  const tracePath = process.env.AC029_BROWSER_RESULT_TRACE
  expect(signalPrefix).toBeTruthy()
  expect(tracePath).toBeTruthy()

  let adminContext
  let secondUserContext
  try {
    const uploader = await registerUser(page, 'ac029_u1')
    expect(uploader.token).toBeTruthy()
    await configureDisposableUserModel(page)

    await page.goto('/import')
    await page.getByPlaceholder('粘贴面经或 JD 内容...').fill(
      `AC029_PUBLIC_SHARE_REAL_STACK\n公司：AC029 隔离公司\n面试轮次：AC029 一面\n${ROOT_QUESTIONS.map(([ordinal, question]) => `${ordinal}. ${question}`).join('\n')}`,
    )
    await page.getByRole('combobox').nth(0).click()
    await page.getByRole('option', { name: '面经', exact: true }).click()
    await page.getByRole('combobox').nth(2).click()
    await page.getByRole('option', { name: '分享到公共题库', exact: true }).click()

    const acceptedResponsePromise = page.waitForResponse((response) =>
      endpointPath(response.url()) === '/api/submit-jobs' && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '提交解析' }).click()
    const acceptedResponse = await acceptedResponsePromise
    expect(acceptedResponse.status(), await acceptedResponse.text()).toBe(202)
    const accepted = await acceptedResponse.json()
    const importId = accepted.import_id
    const idempotencyKey = acceptedResponse.request().headers()['idempotency-key']
    const uploaderAuthorization = acceptedResponse.request().headers().authorization
    expect(importId).toBeTruthy()
    expect(idempotencyKey).toBeTruthy()
    expect(uploaderAuthorization).toMatch(/^Bearer /)
    uploader.token = uploaderAuthorization.slice('Bearer '.length)

    let uploadSnapshot
    await expect.poll(async () => {
      const result = await api(page, uploader.token, 'GET', `/api/upload-imports/${encodeURIComponent(importId)}`)
      if (!result.response.ok()) return `HTTP ${result.response.status()}`
      uploadSnapshot = result.body
      return uploadSnapshot.status
    }, { timeout: 360000, intervals: [1000, 2000, 5000] }).toBe('waiting_review')
    const privateInterviewId = uploadSnapshot.result.interview_id
    const requestId = uploadSnapshot.contribution_request_id
    const privateRows = await readJson(
      page,
      uploader.token,
      '/api/data/interview?scope=mine&page=1&page_size=100&sort=created_at_desc',
    )
    const privateInterview = privateRows.items.find((item) => item.id === privateInterviewId)
    expect(privateInterview).toBeTruthy()
    expect(ROOT_QUESTIONS.every(([, question]) => privateInterview['具体题目清单'].includes(question))).toBe(true)

    const publicBeforeReview = await readJson(
      page,
      uploader.token,
      '/api/data/interview?scope=public&page=1&page_size=100&sort=created_at_desc',
    )
    expect(publicBeforeReview.items.some((item) => item.id === privateInterviewId)).toBe(false)
    const bankBeforeReview = await readJson(
      page,
      uploader.token,
      '/api/master-bank?filter=public&page=1&page_size=100&compact=true',
    )
    const existingCanonical = bankBeforeReview.items.find((item) => item.question === ROOT_QUESTIONS[1][1])
    expect(existingCanonical).toBeTruthy()
    expect(existingCanonical.frequency).toBe(1)
    expect(existingCanonical.sources).toEqual([
      expect.objectContaining({
        url: 'https://ac029.example/preexisting-public-source',
        company: 'AC029 保留来源',
        round: '历史一面',
      }),
    ])

    secondUserContext = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL })
    const secondUserPage = await secondUserContext.newPage()
    const secondUser = await registerUser(secondUserPage, 'ac029_u2')
    const otherUserRoot = await api(secondUserPage, secondUser.token, 'GET', `/api/upload-imports/${encodeURIComponent(importId)}`)
    expect(otherUserRoot.response.status()).toBe(404)
    const otherUserByKey = await api(
      secondUserPage,
      secondUser.token,
      'GET',
      `/api/upload-imports/by-key/${encodeURIComponent(idempotencyKey)}`,
    )
    expect(otherUserByKey.response.status()).toBe(404)
    const otherUserInterviews = await readJson(
      secondUserPage,
      secondUser.token,
      '/api/data/interview?scope=mine&page=1&page_size=100&sort=created_at_desc',
    )
    expect(otherUserInterviews.items.some((item) => item.id === privateInterviewId)).toBe(false)

    adminContext = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL })
    const adminPage = await adminContext.newPage()
    const loginResponsePromise = adminPage.waitForResponse(
      (response) => endpointPath(response.url()) === '/api/auth/login' && response.request().method() === 'POST',
      { timeout: 15000 },
    )
    await adminPage.goto('/login')
    await adminPage.getByLabel('用户名').fill('real_stack_admin')
    await adminPage.getByLabel('密码').fill('real-stack-admin-password-123')
    await adminPage.getByRole('button', { name: '登录', exact: true }).click()
    const loginResponse = await loginResponsePromise
    expect(loginResponse.status(), await loginResponse.text()).toBe(200)
    const adminLogin = await loginResponse.json()
    expect(adminLogin.user.is_admin).toBeTruthy()
    const adminToken = adminLogin.token
    await expect(adminPage).toHaveURL(/\/master-bank/, { timeout: 30000 })

    const adminListResponsePromise = adminPage.waitForResponse((response) =>
      endpointPath(response.url()) === '/api/admin/public-contributions' && response.request().method() === 'GET',
    )
    await adminPage.getByRole('button', { name: 'real_stack_admin' }).click()
    await adminPage.getByRole('button', { name: '审核题库' }).click()
    const adminListResponse = await adminListResponsePromise
    expect(adminListResponse.status()).toBe(200)
    const adminList = await adminListResponse.json()
    const listedRequest = adminList.items.find((item) => Number(item.id) === Number(requestId))
    expect(listedRequest).toBeTruthy()
    expect(listedRequest.summary.item_count).toBe(5)
    expect(listedRequest.summary.question_previews.map((item) => item.question)).toEqual(
      EXPECTED_EXTRACTED_QUESTIONS,
    )

    const adminRoot = await api(adminPage, adminToken, 'GET', `/api/upload-imports/${encodeURIComponent(importId)}`)
    expect(adminRoot.response.status()).toBe(404)
    const detailPromise = adminPage.waitForResponse(response =>
      endpointPath(response.url()) === `/api/admin/public-contributions/${requestId}` && response.request().method() === 'GET')
    const requestCard = adminPage.locator(`[data-review-key="contribution-${requestId}"]`)
    await expect(requestCard).toBeVisible({ timeout: 30000 })
    await expect(requestCard).toContainText(ROOT_QUESTIONS[0][1])
    await requestCard.getByRole('button', { name: '通过', exact: true }).click()
    const detailResponse = await detailPromise
    expect(detailResponse.status()).toBe(200)
    const adminDetail = await detailResponse.json()
    expect(adminDetail.snapshot.items).toHaveLength(5)
    const editedIndex = adminDetail.items.findIndex(item => item.snapshot.source_ordinal === 10)
    const excludedIndex = adminDetail.items.findIndex(item => item.snapshot.source_ordinal === 50)
    expect(editedIndex).toBeGreaterThanOrEqual(0)
    expect(excludedIndex).toBeGreaterThanOrEqual(0)
    const excludedItem = adminDetail.items[excludedIndex]
    await adminPage.getByLabel(`题干 ${editedIndex + 1}`, { exact: true }).fill(EDITED_QUESTION)
    await adminPage.getByLabel(`排除题目 ${excludedIndex + 1}`, { exact: true }).check()
    await expect(adminPage.getByLabel('公开公司')).toHaveValue('')
    await expect(adminPage.getByLabel('公开轮次')).toHaveValue('')
    await expect(adminPage.getByLabel('公开来源 URL')).toHaveValue('')
    const previewPromise = adminPage.waitForResponse(response => endpointPath(response.url()) === `/api/admin/public-contributions/${requestId}/preview`)
    await adminPage.getByRole('button', { name: '预览公开内容', exact: true }).click()
    const previewResponse = await previewPromise
    expect(previewResponse.status()).toBe(200)
    const projectionPreview = await previewResponse.json()
    expect(projectionPreview.projection.items).toHaveLength(4)
    await expect(adminPage.getByTestId('review-projection-preview')).toContainText(EDITED_QUESTION)
    const approvalPromise = adminPage.waitForResponse(response => endpointPath(response.url()) === `/api/admin/public-contributions/${requestId}/approve`)
    await adminPage.getByRole('button', { name: '确认通过', exact: true }).click()
    const approvalResponse = await approvalPromise
    expect(approvalResponse.status()).toBe(200)
    const approvedBody = approvalResponse.request().postDataJSON()
    expect(approvedBody.expected_revision).toBe(adminDetail.revision)
    expect(approvedBody.excluded_item_ids).toEqual([adminDetail.items[excludedIndex].id])
    await expect.poll(async () => {
      const result = await api(adminPage, adminToken, 'GET', `/api/admin/public-contributions/${requestId}`)
      if (!result.response.ok()) return `HTTP ${result.response.status()}`
      const failed = result.body.items.filter((item) => item.status === 'failed')
      const published = result.body.items.filter((item) => item.status === 'published')
      if (failed.length === 1 && published.length === 3) return 'partial'
      if (failed.length === 1) return `failed:${published.length}`
      return result.body.status
    }, { timeout: 420000, intervals: [1000, 2000, 5000] }).toBe('partial')

    const failedDetail = await readJson(
      adminPage,
      adminToken,
      `/api/admin/public-contributions/${requestId}`,
    )
    const failedItems = failedDetail.items.filter((item) => item.status === 'failed')
    const firstPassPublished = failedDetail.items
      .filter((item) => item.status === 'published')
      .map((item) => ({ id: item.id, public_detail_id: item.public_detail_id }))
    expect(failedItems).toHaveLength(1)
    expect(failedItems[0].snapshot.source_ordinal).toBe(40)
    expect(firstPassPublished).toHaveLength(3)
    const publicBeforeRecovery = await readJson(
      secondUserPage,
      secondUser.token,
      '/api/data/interview?scope=public&page=1&page_size=100&sort=created_at_desc',
    )
    const partialPublic = publicBeforeRecovery.items.find((item) => item.id === failedDetail.public_interview_id)
    expect(partialPublic).toBeTruthy()
    expect(partialPublic['具体题目清单'].split('\n').filter(Boolean)).toHaveLength(3)
    expect(partialPublic['具体题目清单']).not.toContain(ROOT_QUESTIONS[3][1])
    expect(partialPublic['具体题目清单']).not.toContain(ROOT_QUESTIONS[4][1])

    // Stop the real disposable worker at the failed-item recovery boundary.
    writeFileSync(`${signalPrefix}.stop`, `${requestId}\n`, { flag: 'wx' })
    await expect.poll(() => existsSync(`${signalPrefix}.stopped`), { timeout: 90000 }).toBe(true)
    const retry = await api(
      adminPage,
      adminToken,
      'POST',
      `/api/admin/public-contributions/${requestId}/retry`,
      {},
    )
    expect(retry.response.status(), JSON.stringify(retry.body)).toBe(200)
    expect(retry.body.reprocessed_item_ids).toEqual([failedItems[0].id])
    const retryState = await readJson(
      adminPage,
      adminToken,
      `/api/admin/public-contributions/${requestId}`,
    )
    for (const firstPass of firstPassPublished) {
      const stillPublished = retryState.items.find((item) => item.id === firstPass.id)
      expect(stillPublished.status).toBe('published')
      expect(stillPublished.public_detail_id).toBe(firstPass.public_detail_id)
    }

    writeFileSync(`${signalPrefix}.restart`, `${requestId}\n`, { flag: 'wx' })
    await expect.poll(() => existsSync(`${signalPrefix}.done`), { timeout: 90000 }).toBe(true)
    await expect.poll(async () => {
      const result = await api(adminPage, adminToken, 'GET', `/api/admin/public-contributions/${requestId}`)
      if (!result.response.ok()) return `HTTP ${result.response.status()}`
      return result.body.items.filter((item) => item.status === 'published').length
    }, { timeout: 420000, intervals: [1000, 2000, 5000] }).toBe(4)

    const finalDetail = await readJson(
      adminPage,
      adminToken,
      `/api/admin/public-contributions/${requestId}`,
    )
    expect(finalDetail.status).toBe('partially_published')
    expect(finalDetail.items.filter((item) => item.status === 'published')).toHaveLength(4)
    expect(finalDetail.items.find((item) => item.id === excludedItem.id).status).toBe('rejected')
    for (const firstPass of firstPassPublished) {
      const finalItem = finalDetail.items.find((item) => item.id === firstPass.id)
      expect(finalItem.public_detail_id).toBe(firstPass.public_detail_id)
    }
    const recovered = finalDetail.items.find((item) => item.snapshot.source_ordinal === 40)
    expect(recovered.status).toBe('published')

    const publicAfterRecovery = await readJson(
      secondUserPage,
      secondUser.token,
      '/api/data/interview?scope=public&page=1&page_size=100&sort=created_at_desc',
    )
    const finalPublic = publicAfterRecovery.items.find((item) => item.id === finalDetail.public_interview_id)
    expect(finalPublic).toBeTruthy()
    const finalLines = finalPublic['具体题目清单'].split('\n').filter(Boolean)
    expect(finalLines).toHaveLength(4)
    expect(finalPublic['具体题目清单']).toContain(EDITED_QUESTION)
    expect(finalPublic['具体题目清单']).not.toContain(ROOT_QUESTIONS[4][1])
    expect(finalPublic['具体题目清单']).toContain(ROOT_QUESTIONS[3][1])

    const privateAfterRecovery = await readJson(
      page,
      uploader.token,
      '/api/data/interview?scope=mine&page=1&page_size=100&sort=created_at_desc',
    )
    const privateStillOriginal = privateAfterRecovery.items.find((item) => item.id === privateInterviewId)
    expect(privateStillOriginal['具体题目清单']).toContain(ROOT_QUESTIONS[0][1])
    expect(privateStillOriginal['具体题目清单']).not.toContain(EDITED_QUESTION)

    const trace = {
      import_id: importId,
      private_interview_id: privateInterviewId,
      contribution_request_id: requestId,
      public_interview_id: finalDetail.public_interview_id,
      source_ordinals: ROOT_QUESTIONS.map(([ordinal]) => ordinal),
      failed_source_ordinal: 40,
      excluded_source_ordinal: 50,
      first_pass_published: firstPassPublished,
      final_published_items: finalDetail.items
        .filter((item) => item.status === 'published')
        .map((item) => ({ id: item.id, source_ordinal: item.snapshot.source_ordinal, public_detail_id: item.public_detail_id })),
      public_question_count: finalLines.length,
    }
    writeFileSync(tracePath, `${JSON.stringify(trace, null, 2)}\n`, { flag: 'wx' })
  } finally {
    await adminContext?.close()
    await secondUserContext?.close()
  }
})
