import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

const OWNER_PASSWORD = 'Ac024-legacy-jd-real-stack-123!'
const ADMIN = 'real_stack_admin'
const ADMIN_PASSWORD = 'real-stack-admin-password-123'
const PRIVATE_COMPANY = 'AC024_PRIVATE_COMPANY_SENTINEL'
const PUBLIC_COMPANY = 'AC024_PUBLIC_REVIEW_COMPANY'
const SECRET_CONTACT = 'AC024_PRIVATE_CONTACT_SENTINEL'
const ORDINARY_INTERVIEW_MARKER = 'AC024_ORDINARY_INTERVIEW_REAL_STACK'
const ORDINARY_INTERVIEW_QUESTION = 'AC024_ORDINARY_INTERVIEW_QUESTION_MARKER'

function pathOf(value) {
  return new URL(value).pathname
}

async function login(page, username, password) {
  const responsePromise = page.waitForResponse((response) =>
    pathOf(response.url()) === '/api/auth/login' && response.request().method() === 'POST',
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
  const body = response.status() === 204 ? null : await response.json().catch(() => null)
  return { status: response.status(), body }
}

async function submitOrdinaryInterview(page, token, ownerId) {
  await page.goto('/import')
  await page.getByPlaceholder('粘贴面经或 JD 内容...').fill(
    `${ORDINARY_INTERVIEW_MARKER}\n公司：AC024_ORDINARY_INTERVIEW_COMPANY\n` +
      '面试轮次：AC024 legacy compatibility round\n' +
      `题目：${ORDINARY_INTERVIEW_QUESTION}: explain transaction isolation.`,
  )
  await page.getByRole('combobox').first().click()
  await page.getByRole('option', { name: '面经', exact: true }).click()
  await page.getByRole('combobox').last().click()
  await page.getByRole('option', { name: '仅自己可见', exact: true }).click()
  await page.getByRole('button', { name: '提交解析' }).click()
  await expect(page.locator('body')).toContainText('任务已提交，正在检查目标模型并后台处理')
  await expect.poll(async () => {
    const tasks = await api(page, token, 'GET', '/api/upload-imports?page=1&page_size=20')
    return tasks.body?.items?.find(
      (item) =>
        item.source_type === 'interview' &&
        item.target_intent === 'private' &&
        item.position_name === 'agent开发/大模型应用开发/大模型开发',
    )?.import_id
  }, { timeout: 30000, intervals: [250, 500, 1000] }).toBeTruthy()
  const taskList = await api(page, token, 'GET', '/api/upload-imports?page=1&page_size=20')
  const importId = taskList.body.items.find(
    (item) =>
      item.source_type === 'interview' &&
      item.target_intent === 'private' &&
      item.position_name === 'agent开发/大模型应用开发/大模型开发',
  )?.import_id
  expect(importId).toBeTruthy()

  await expect.poll(async () => {
    const snapshot = await api(page, token, 'GET', `/api/upload-imports/${encodeURIComponent(importId)}`)
    return snapshot.body?.status || `http-${snapshot.status}`
  }, { timeout: 180000, intervals: [500, 1000, 2000] }).toBe('completed')
  const snapshot = await api(page, token, 'GET', `/api/upload-imports/${encodeURIComponent(importId)}`)
  expect(snapshot.status).toBe(200)
  expect(snapshot.body.source_type).toBe('interview')
  expect(snapshot.body.resolved_type).toBe('interview')
  expect(snapshot.body.error).toBeNull()
  expect(snapshot.body.result?.interview_id).toBeTruthy()
  expect(snapshot.body.counts).toMatchObject({ extracted: 1, retained: 1, failed: 0, total: 1 })

  const ownerInterviews = await api(
    page,
    token,
    'GET',
    '/api/data/interview?scope=mine&page=1&page_size=100',
  )
  expect(ownerInterviews.status).toBe(200)
  const interview = ownerInterviews.body.items.find(
    (item) => item.id === snapshot.body.result.interview_id,
  )
  expect(interview, JSON.stringify(ownerInterviews.body.items)).toBeTruthy()
  expect(interview.owner_id).toBe(ownerId)
  expect(interview['公司']).toBe('AC024_ORDINARY_INTERVIEW_COMPANY')
  expect(interview['具体题目清单']).toContain(ORDINARY_INTERVIEW_QUESTION)
  return {
    import_id: importId,
    result: snapshot.body.result,
    interview,
    private_visible_for_owner: true,
  }
}

test('AC-024 legacy retry stays JD, reviewed projection is public, and old approved rows do not replay', async ({
  browser,
  page,
}) => {
  test.setTimeout(240000)
  test.skip(process.env.REAL_STACK_E2E !== '1', 'run through scripts/real_stack_smoke.sh')

  const seedPath = process.env.AC024_SEED_PATH
  const controlPrefix = process.env.AC024_CONTROL_PREFIX
  const tracePath = process.env.AC024_BROWSER_TRACE
  expect(seedPath).toBeTruthy()
  expect(controlPrefix).toBeTruthy()
  expect(tracePath).toBeTruthy()
  const seed = JSON.parse(readFileSync(seedPath, 'utf8'))

  const otherContext = await browser.newContext()
  const adminContext = await browser.newContext()
  const otherPage = await otherContext.newPage()
  const adminPage = await adminContext.newPage()
  try {
    const ownerToken = await login(page, seed.owner_username, OWNER_PASSWORD)
    const otherToken = await login(otherPage, seed.other_username, OWNER_PASSWORD)
    const adminToken = await login(adminPage, ADMIN, ADMIN_PASSWORD)

    const legacyJdRetryAsOther = await api(
      otherPage,
      otherToken,
      'POST',
      `/api/submit-jobs/${seed.old_job_id}/retry`,
      {},
    )
    expect(legacyJdRetryAsOther.status).toBe(404)
    const legacyJobReadAsOther = await api(
      otherPage,
      otherToken,
      'GET',
      `/api/jobs/${seed.old_job_id}`,
    )
    expect(legacyJobReadAsOther.status).toBe(404)

    await otherPage.goto('/jd')
    await expect(otherPage.getByRole('heading', { name: 'JD 库' })).toBeVisible()
    await expect(otherPage.locator('body')).toContainText('AC024_LEGACY_APPROVED_PUBLIC_JD')
    await expect(otherPage.locator('body')).not.toContainText(PRIVATE_COMPANY)
    await otherPage.goto('/interview')
    await expect(otherPage.getByRole('heading', { name: '面经库' })).toBeVisible()
    await expect(otherPage.locator('body')).toContainText('AC024_LEGACY_APPROVED_PUBLIC_INTERVIEW')

    const retry = await api(
      page,
      ownerToken,
      'POST',
      `/api/submit-jobs/${seed.old_job_id}/retry`,
      {},
    )
    expect(retry.status, JSON.stringify(retry.body)).toBe(200)
    expect(retry.body).toMatchObject({ status: 'queued', created: true })
    expect(retry.body.job_id).toBeTruthy()
    const retryJobId = retry.body.job_id

    await expect.poll(async () => {
      const status = await api(page, ownerToken, 'GET', `/api/jobs/${retryJobId}`)
      return status.body?.status || `http-${status.status}`
    }, { timeout: 180000, intervals: [500, 1000, 2000] }).toBe('completed')

    const ownerJds = await api(page, ownerToken, 'GET', '/api/data/jd?scope=mine&page=1&page_size=100')
    expect(ownerJds.status).toBe(200)
    const privateJd = ownerJds.body.items.find((item) => item['来源链接'] === seed.legacy_source_url)
    expect(privateJd, JSON.stringify(ownerJds.body.items)).toBeTruthy()
    expect(privateJd.owner_id).toBe(seed.owner_id)
    expect(privateJd['公司']).toBe(PRIVATE_COMPANY)

    const ownerContributions = await api(page, ownerToken, 'GET', '/api/public-contributions/mine')
    expect(ownerContributions.status).toBe(200)
    const request = ownerContributions.body.items.find(
      (item) => item.source_type === 'jd' && item.source_id === privateJd.id,
    )
    expect(request, JSON.stringify(ownerContributions.body.items)).toBeTruthy()
    const requestId = request.id

    const privateRequestReadAsOther = await api(
      otherPage,
      otherToken,
      'GET',
      `/api/public-contributions/${requestId}`,
    )
    expect(privateRequestReadAsOther.status).toBe(403)

    const pendingList = await api(
      adminPage,
      adminToken,
      'GET',
      '/api/admin/public-contributions?status=pending_review&source_type=jd',
    )
    expect(pendingList.status).toBe(200)
    expect(pendingList.body.items.some((item) => item.id === requestId && item.source_type === 'jd')).toBe(true)
    const adminPending = await api(
      adminPage,
      adminToken,
      'GET',
      `/api/admin/public-contributions/${requestId}`,
    )
    expect(adminPending.status).toBe(200)
    expect(adminPending.body.summary.job_title).toContain('AC024 Legacy JD')
    expect(JSON.stringify(adminPending.body)).not.toContain(SECRET_CONTACT)

    const rejectedReview = await api(
      adminPage,
      adminToken,
      'POST',
      `/api/admin/public-contributions/${requestId}/approve`,
      { review_fields: { source: { contact_email: SECRET_CONTACT } } },
    )
    expect(rejectedReview.status).toBe(422)
    const stillPending = await api(
      adminPage,
      adminToken,
      'GET',
      `/api/admin/public-contributions/${requestId}`,
    )
    expect(stillPending.body.status).toBe('pending_review')
    expect(stillPending.body.public_jd_id).toBeNull()

    const approval = await api(
      adminPage,
      adminToken,
      'POST',
      `/api/admin/public-contributions/${requestId}/approve`,
      {
        review_fields: {
          source: {
            company: PUBLIC_COMPANY,
            job_title: 'AC024 public platform engineer',
            tech_stack: 'AC024_PUBLIC_TECH_GO',
            bonus: 'AC024_PUBLIC_BONUS_SQL',
            position: 'agent开发/大模型应用开发/大模型开发',
            salary: null,
            source_url: seed.reviewed_public_url,
          },
        },
      },
    )
    expect(approval.status, JSON.stringify(approval.body)).toBe(200)
    expect(approval.body.status).toBe('published')
    expect(approval.body.public_jd_id).toBeTruthy()

    const ordinaryInterview = await submitOrdinaryInterview(page, ownerToken, seed.owner_id)

    writeFileSync(`${controlPrefix}.approved`, `${approval.body.public_jd_id}\n`, { flag: 'wx' })
    await expect.poll(() => existsSync(`${controlPrefix}.read-baseline-ready`), {
      timeout: 30000,
      intervals: [100, 250, 500],
    }).toBe(true)

    await otherPage.goto('/jd')
    await expect(otherPage.locator('body')).toContainText(PUBLIC_COMPANY)
    await expect(otherPage.locator('body')).not.toContainText(PRIVATE_COMPANY)
    await expect(otherPage.locator('body')).not.toContainText(SECRET_CONTACT)
    await otherPage.reload()
    await expect(otherPage.locator('body')).toContainText('AC024_LEGACY_APPROVED_PUBLIC_JD')
    await otherPage.goto('/interview')
    await expect(otherPage.locator('body')).toContainText('AC024_LEGACY_APPROVED_PUBLIC_INTERVIEW')
    await expect(otherPage.locator('body')).not.toContainText('AC024_LEGACY_JD_REAL_STACK')
    await otherPage.reload()
    await expect(otherPage.locator('body')).toContainText('AC024_LEGACY_INTERVIEW_QUESTION_MARKER')

    await page.goto('/jd')
    await expect(page.locator('body')).toContainText(PRIVATE_COMPANY)
    await expect(page.locator('body')).toContainText(PUBLIC_COMPANY)
    await page.reload()

    const publicJds = await api(
      otherPage,
      otherToken,
      'GET',
      '/api/data/jd?scope=public&page=1&page_size=100',
    )
    const publicInterviews = await api(
      otherPage,
      otherToken,
      'GET',
      '/api/data/interview?scope=public&page=1&page_size=100',
    )
    expect(publicJds.status).toBe(200)
    expect(publicInterviews.status).toBe(200)
    const publicProjection = publicJds.body.items.find((item) => item.id === approval.body.public_jd_id)
    expect(publicProjection).toBeTruthy()
    expect(publicProjection.owner_id).toBeNull()
    expect(publicProjection['公司']).toBe(PUBLIC_COMPANY)
    expect(publicProjection['岗位名称']).toBe('AC024 public platform engineer')
    expect(publicProjection['加分项']).toBe('AC024_PUBLIC_BONUS_SQL')
    expect(JSON.stringify(publicProjection)).not.toContain(PRIVATE_COMPANY)
    expect(JSON.stringify(publicProjection)).not.toContain(SECRET_CONTACT)
    expect(publicJds.body.items.some((item) => item.id === privateJd.id)).toBe(false)
    expect(publicJds.body.items.some((item) => item.id === seed.old_public_jd_id)).toBe(true)
    expect(publicInterviews.body.items.some((item) => item.id === seed.old_public_interview_id)).toBe(true)
    expect(JSON.stringify(publicInterviews.body)).not.toContain('AC024_LEGACY_JD_REAL_STACK')
    ordinaryInterview.public_absent_for_other = !publicInterviews.body.items.some(
      (item) => item.id === ordinaryInterview.interview.id,
    )
    expect(ordinaryInterview.public_absent_for_other).toBe(true)
    const privateRequestReadAfterApproval = await api(
      otherPage,
      otherToken,
      'GET',
      `/api/public-contributions/${requestId}`,
    )
    expect(privateRequestReadAfterApproval.status).toBe(403)

    writeFileSync(`${controlPrefix}.lists-refreshed`, 'JD/interview lists were refreshed twice\n', { flag: 'wx' })
    const finalAdminRequest = await api(
      adminPage,
      adminToken,
      'GET',
      `/api/admin/public-contributions/${requestId}`,
    )
    expect(finalAdminRequest.body.status).toBe('published')
    expect(finalAdminRequest.body.public_jd_id).toBe(approval.body.public_jd_id)

    writeFileSync(
      tracePath,
      `${JSON.stringify({
        old_job_id: seed.old_job_id,
        retry_job_id: retryJobId,
        retry_response: retry,
        other_retry_status: legacyJdRetryAsOther.status,
        other_job_read_status: legacyJobReadAsOther.status,
        private_request_read_status: privateRequestReadAsOther.status,
        retry_job_status: 'completed',
        private_jd_id: privateJd.id,
        contribution_request_id: requestId,
        ordinary_interview: ordinaryInterview,
        admin_pending_summary: adminPending.body.summary,
        disallowed_projection_status: rejectedReview.status,
        approval,
        public_jd: publicProjection,
        public_jd_ids: publicJds.body.items.map((item) => item.id),
        public_interview_ids: publicInterviews.body.items.map((item) => item.id),
        old_rows_visible: {
          jd: publicJds.body.items.some((item) => item.id === seed.old_public_jd_id),
          interview: publicInterviews.body.items.some((item) => item.id === seed.old_public_interview_id),
        },
        private_source_absent_for_other: !publicJds.body.items.some((item) => item.id === privateJd.id),
      }, null, 2)}\n`,
      { flag: 'wx' },
    )
  } finally {
    await Promise.allSettled([otherContext.close(), adminContext.close()])
  }
})
