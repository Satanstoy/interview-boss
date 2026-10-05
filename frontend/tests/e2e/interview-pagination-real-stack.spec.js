import { writeFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { configureDisposableUserModel } from '../_helpers/real-stack-model.js'

const USERNAME = 'ac001_ac002_u1'
const PASSWORD = 'Ac001-ac002-real-stack-123!'
const MARKER = 'AC001_AC002_FIXTURE'

function pathOf(value) {
  return new URL(value).pathname
}

test('real SQLite pagination and public share task target stay aligned', async ({ page, browser }) => {
  test.setTimeout(12 * 60 * 1000)
  test.skip(process.env.REAL_STACK_E2E !== '1', 'run through scripts/real_stack_smoke.sh')
  const tracePath = process.env.AC001_AC002_BROWSER_TRACE
  const dbTracePath = process.env.AC001_AC002_DB_TRACE
  expect(tracePath, 'the runner must retain browser/API evidence').toBeTruthy()
  expect(dbTracePath, 'the runner must retain SQLite relationship evidence').toBeTruthy()

  const responses = []
  const jdResponses = []
  page.on('response', async (response) => {
    const url = new URL(response.url())
    if (url.pathname === '/api/data/interview' && response.request().method() === 'GET') {
      try {
        responses.push({
          status: response.status(),
          query: Object.fromEntries(url.searchParams.entries()),
          body: await response.json(),
        })
      } catch {
        // The test assertions below report a missing/invalid response.
      }
    }
    if (url.pathname === '/api/data/jd' && response.request().method() === 'GET') {
      try {
        jdResponses.push({
          status: response.status(),
          query: Object.fromEntries(url.searchParams.entries()),
          body: await response.json(),
        })
      } catch {
        // The assertion below reports the response contract failure.
      }
    }
  })

  await page.goto('/login')
  await page.locator('input[name="username"]').fill(USERNAME)
  await page.locator('input[name="password"]').fill(PASSWORD)
  const loginResponsePromise = page.waitForResponse((response) =>
    pathOf(response.url()) === '/api/auth/login' && response.request().method() === 'POST',
  )
  await page.locator('button[type="submit"]').first().click()
  const loginResponse = await loginResponsePromise
  expect(loginResponse.status(), await loginResponse.text()).toBe(200)
  const login = await loginResponse.json()
  expect(login.user.username).toBe(USERNAME)

  await page.goto('/')
  await page.getByRole('button', { name: '面经库' }).click()
  await expect(page.getByRole('heading', { name: '面经库' })).toBeVisible()
  await expect(page.locator('[data-row-id]')).toHaveCount(20)
  await expect(page.getByText('共 121 条，第 1/7 页')).toBeVisible()

  await expect.poll(() => {
    const hit = responses.find((entry) =>
      entry.status === 200 && entry.query.page === '1' && entry.query.page_size === '20',
    )
    return hit ? hit.body.total : null
  }).toBe(121)
  const firstRequest = responses.find((entry) =>
    entry.query.page === '1' && entry.query.page_size === '20' && entry.query.position_id,
  )
  expect(firstRequest, 'authenticated page load must carry the resolved P1 filter').toBeTruthy()
  expect(firstRequest.query.sort).toBe('created_at_desc')
  expect(firstRequest.query.scope).toBe('all')
  expect(Number(firstRequest.query.position_id)).toBeGreaterThan(0)
  expect(firstRequest.body.items).toHaveLength(20)
  expect(firstRequest.body.items.every((row) => row.owner_id === login.user.id)).toBe(true)
  expect(firstRequest.body.items.some((row) => row['公司'].includes('U2_PRIVATE'))).toBe(false)
  expect(firstRequest.body.items.some((row) => row['公司'].includes('_P2_PUBLIC'))).toBe(false)
  const firstIds = firstRequest.body.items.map((row) => row.id)
  expect(firstIds).toEqual([...firstIds].sort((a, b) => b - a))
  expect(new Set(firstRequest.body.items.map((row) => row.created_at)).size).toBe(1)

  await page.locator('[data-slot="pagination-next"]').click()
  await expect(page.getByText('共 121 条，第 2/7 页')).toBeVisible()
  await expect.poll(() => responses.some((entry) =>
    entry.status === 200 && entry.query.page === '2' && entry.query.page_size === '20' &&
    entry.body.items?.length === 20 && entry.body.total === 121,
  )).toBe(true)
  const secondRequest = responses.find((entry) => entry.query.page === '2' && entry.query.page_size === '20')
  expect(secondRequest.body.items.every((row) => row.owner_id === login.user.id)).toBe(true)
  expect(secondRequest.body.items.some((row) => row['公司'].includes('_P2_PUBLIC'))).toBe(false)
  const secondIds = secondRequest.body.items.map((row) => row.id)
  expect(secondIds).toEqual([...secondIds].sort((a, b) => b - a))
  expect(secondIds).not.toEqual(firstIds)
  expect(secondIds.some((id) => firstIds.includes(id))).toBe(false)

  const seasonSelect = page.getByText('招聘季筛选：').locator('xpath=..').getByRole('combobox')
  await seasonSelect.click()
  await page.getByRole('option', { name: '2025秋招', exact: true }).click()
  await expect(page.getByText('共 61 条，第 1/4 页')).toBeVisible()
  await expect.poll(() => responses.some((entry) =>
    entry.status === 200 && entry.query.page === '1' && entry.query.page_size === '20' &&
    entry.query.season === '2025秋招' && entry.body.total === 61,
  )).toBe(true)

  await page.locator('button').filter({ hasText: '上传日期' }).click()
  await expect(page.getByText('共 61 条，第 1/4 页')).toBeVisible()
  await expect.poll(() => responses.some((entry) =>
    entry.status === 200 && entry.query.page === '1' && entry.query.page_size === '20' &&
    entry.query.season === '2025秋招' && entry.query.sort === 'created_at_asc' &&
    entry.body.total === 61,
  )).toBe(true)
  const ascending = responses.find((entry) =>
    entry.query.page === '1' && entry.query.page_size === '20' &&
    entry.query.season === '2025秋招' && entry.query.sort === 'created_at_asc',
  )
  const ascendingIds = ascending.body.items.map((row) => row.id)
  expect(ascendingIds).toEqual([...ascendingIds].sort((a, b) => a - b))
  expect(ascending.body.items.every((row) => row.owner_id === login.user.id)).toBe(true)

  await page.locator('[data-slot="pagination-next"]').click()
  await expect(page.getByText('共 61 条，第 2/4 页')).toBeVisible()
  const pageSizeSelect = page.locator('[data-slot="pagination"]').getByRole('combobox')
  await pageSizeSelect.click()
  await page.getByRole('option', { name: '50', exact: true }).click()
  await expect(page.getByText('共 61 条，第 1/2 页')).toBeVisible()
  await expect.poll(() => responses.some((entry) =>
    entry.status === 200 && entry.query.page === '1' && entry.query.page_size === '50' &&
    entry.query.season === '2025秋招' && entry.query.sort === 'created_at_asc' &&
    entry.body.total === 61 && entry.body.items?.length === 50,
  )).toBe(true)
  await page.locator('[data-slot="pagination-next"]').click()
  await expect(page.getByText('共 61 条，第 2/2 页')).toBeVisible()
  await pageSizeSelect.click()
  await page.getByRole('option', { name: '20', exact: true }).click()
  await expect(page.getByText('共 61 条，第 1/4 页')).toBeVisible()
  await expect.poll(() => responses.some((entry) =>
    entry.status === 200 && entry.query.page === '1' && entry.query.page_size === '20' &&
    entry.query.season === '2025秋招' && entry.query.sort === 'created_at_asc' &&
    entry.body.total === 61,
  )).toBe(true)

  const jdList = jdResponses.find((entry) =>
    entry.query.page_size === '100' && entry.body.total === 45,
  )
  expect(jdList, 'JD data keeps its legacy single-page-size request').toBeTruthy()
  expect(jdList.status).toBe(200)
  expect(jdList.body.items).toHaveLength(45)
  expect(jdList.body.items.every((row) => row.owner_id === login.user.id)).toBe(true)

  await page.getByRole('button', { name: 'JD 筛选' }).click()
  await expect(page.getByRole('heading', { name: 'JD 库' })).toBeVisible()
  await expect(page.getByText('共 45 条，第 1/3 页')).toBeVisible()
  const jdRows = page.locator('table tbody tr[data-row-id]').filter({ hasText: 'AC002_JD_CLIENT_PAGINATION_' })
  const jdPageOneIds = await jdRows.evaluateAll((rows) =>
    rows.map((row) => row.getAttribute('data-row-id')),
  )
  expect(jdPageOneIds).toHaveLength(20)
  const jdRequestCount = jdResponses.length
  await page.locator('[data-slot="pagination-next"]').click()
  await expect(page.getByText('共 45 条，第 2/3 页')).toBeVisible()
  await expect(jdRows).toHaveCount(20)
  const jdPageTwoIds = await jdRows.evaluateAll((rows) =>
    rows.map((row) => row.getAttribute('data-row-id')),
  )
  expect(jdPageTwoIds).toHaveLength(20)
  expect(jdPageTwoIds).not.toEqual(jdPageOneIds)
  expect(jdResponses).toHaveLength(jdRequestCount)

  await page.getByRole('button', { name: '面经库' }).click()
  await expect(page.getByRole('heading', { name: '面经库' })).toBeVisible()

  // A P2 public row is visible through the same real target-lookup endpoint;
  // U1's P1 list count above remains exactly 121 and excludes U2/P2 data.
  // Resolve the P2 position from the authenticated profile instead of trusting
  // fixture IDs, which are intentionally allocated by the disposable DB.
  const p2Profile = await page.request.get('/api/positions', {
    headers: { Authorization: `Bearer ${login.token}` },
  })
  expect(p2Profile.ok(), await p2Profile.text()).toBe(true)
  const positions = await p2Profile.json()
  const p2 = positions.positions.find((position) => position.name === 'AC001 数据 P2')
  expect(p2).toBeTruthy()
  const p2List = await page.request.get(
    `/api/data/interview?page=1&page_size=20&sort=created_at_desc&scope=public&position_id=${p2.id}`,
    { headers: { Authorization: `Bearer ${login.token}` } },
  )
  expect(p2List.ok(), await p2List.text()).toBe(true)
  const p2Body = await p2List.json()
  const target = p2Body.items.find((row) => row['公司'] === `${MARKER}_P2_PUBLIC`)
  expect(target).toBeTruthy()
  const locationResponse = await page.request.get(
    `/api/data/interview/${target.id}/location?sort=created_at_desc&page_size=20&position_id=${p2.id}&scope=public`,
    { headers: { Authorization: `Bearer ${login.token}` } },
  )
  expect(locationResponse.ok(), await locationResponse.text()).toBe(true)
  const location = await locationResponse.json()
  expect(location.interview_id).toBe(target.id)
  expect(location.page).toBe(1)
  expect(location.position_id).toBe(p2.id)
  expect(location.page_size).toBe(20)

  // Keep the owner on P1 page 2 while a second browser context submits a P2
  // public share and the admin/worker publish it in the background.
  await page.locator('[data-slot="pagination-next"]').click()
  await expect(page.getByText('共 61 条，第 2/4 页')).toBeVisible()
  const ownerPageUrl = page.url()
  const ownerP1Rows = page.locator('table tbody tr[data-row-id]').filter({ hasText: `${MARKER}_U1_` })
  await expect(ownerP1Rows).toHaveCount(20)
  const ownerP1PageTwoIds = await ownerP1Rows.evaluateAll((rows) =>
    rows.map((row) => row.getAttribute('data-row-id')),
  )

  let uploaderContext
  let adminContext
  try {
    uploaderContext = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL })
    const uploaderPage = await uploaderContext.newPage()
    await uploaderPage.goto('/login')
    await uploaderPage.locator('input[name="username"]').fill(USERNAME)
    await uploaderPage.locator('input[name="password"]').fill(PASSWORD)
    const uploaderLoginPromise = uploaderPage.waitForResponse((response) =>
      pathOf(response.url()) === '/api/auth/login' && response.request().method() === 'POST',
    )
    await uploaderPage.locator('button[type="submit"]').first().click()
    const uploaderLoginResponse = await uploaderLoginPromise
    expect(uploaderLoginResponse.status(), await uploaderLoginResponse.text()).toBe(200)
    const uploaderLogin = await uploaderLoginResponse.json()
    expect(uploaderLogin.user.id).toBe(login.user.id)
    await configureDisposableUserModel(uploaderPage)

    const setUploaderPosition = await uploaderPage.request.put('/api/profile/my-position', {
      headers: {
        Authorization: `Bearer ${uploaderLogin.token}`,
        'X-Requested-With': 'XMLHttpRequest',
      },
      data: { position: p2.name },
    })
    expect(setUploaderPosition.ok(), await setUploaderPosition.text()).toBe(true)

    const sharedCompany = 'AC001_TASK_LOCATOR_REAL_STACK 公司'
    const sharedQuestion = 'AC001_TASK_LOCATOR_REAL_STACK：系统怎样验证异步任务的幂等恢复？'
    await uploaderPage.goto('/import')
    await uploaderPage.getByPlaceholder('粘贴面经或 JD 内容...').fill(
      `AC001_TASK_LOCATOR_REAL_STACK\n公司：${sharedCompany}\n面试轮次：AC001 P2 一面\n1. ${sharedQuestion}`,
    )
    await uploaderPage.getByRole('combobox').nth(0).click()
    await uploaderPage.getByRole('option', { name: '面经', exact: true }).click()
    await uploaderPage.getByRole('combobox').nth(2).click()
    await uploaderPage.getByRole('option', { name: '分享到公共题库', exact: true }).click()
    const acceptedResponsePromise = uploaderPage.waitForResponse((response) =>
      pathOf(response.url()) === '/api/submit-jobs' && response.request().method() === 'POST',
    )
    await uploaderPage.getByRole('button', { name: '提交解析' }).click()
    const acceptedResponse = await acceptedResponsePromise
    expect(acceptedResponse.status(), await acceptedResponse.text()).toBe(202)
    const accepted = await acceptedResponse.json()
    const importId = accepted.import_id
    const uploaderToken = acceptedResponse.request().headers().authorization?.replace(/^Bearer /, '')
    expect(importId).toBeTruthy()
    expect(uploaderToken).toBeTruthy()

    const uploaderApi = async (method, path, data) => {
      const response = await uploaderPage.request.fetch(path, {
        method,
        headers: { Authorization: `Bearer ${uploaderToken}` },
        data,
      })
      const body = response.status() === 204 ? null : await response.json()
      return { response, body }
    }
    let uploadSnapshot
    await expect.poll(async () => {
      const result = await uploaderApi('GET', `/api/upload-imports/${encodeURIComponent(importId)}`)
      if (!result.response.ok()) return `HTTP ${result.response.status()}`
      uploadSnapshot = result.body
      if (['completed', 'failed', 'partial_failed', 'needs_action'].includes(uploadSnapshot.status)) {
        throw new Error(`share upload reached unexpected terminal state: ${uploadSnapshot.status}`)
      }
      return uploadSnapshot.status
    }, { timeout: 360000, intervals: [1000, 2000, 5000] }).toBe('waiting_review')
    const privateInterviewId = uploadSnapshot.result.interview_id
    const requestId = uploadSnapshot.contribution_request_id
    expect(privateInterviewId).toBeTruthy()
    expect(requestId).toBeTruthy()
    expect(uploadSnapshot.result_target).toEqual({
      entity_type: 'interview',
      entity_id: privateInterviewId,
      scope: 'private',
    })

    const publicBeforeReview = await uploaderApi(
      'GET',
      `/api/data/interview?scope=public&page=1&page_size=100&sort=created_at_desc&position_id=${p2.id}`,
    )
    expect(publicBeforeReview.response.ok(), JSON.stringify(publicBeforeReview.body)).toBe(true)
    expect(publicBeforeReview.body.items.some((row) => row['公司'] === sharedCompany)).toBe(false)

    adminContext = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL })
    const adminPage = await adminContext.newPage()
    await adminPage.goto('/login')
    await adminPage.locator('input[name="username"]').fill('real_stack_admin')
    await adminPage.locator('input[name="password"]').fill('real-stack-admin-password-123')
    const adminLoginPromise = adminPage.waitForResponse((response) =>
      pathOf(response.url()) === '/api/auth/login' && response.request().method() === 'POST',
    )
    await adminPage.locator('button[type="submit"]').first().click()
    const adminLoginResponse = await adminLoginPromise
    expect(adminLoginResponse.status(), await adminLoginResponse.text()).toBe(200)
    const adminLogin = await adminLoginResponse.json()
    expect(adminLogin.need_email_bind).not.toBe(true)
    expect(adminLogin.user.is_admin).toBe(true)
    const adminApi = async (method, path, data) => {
      const response = await adminPage.request.fetch(path, {
        method,
        headers: { Authorization: `Bearer ${adminLogin.token}` },
        data,
      })
      const body = response.status() === 204 ? null : await response.json()
      return { response, body }
    }
    const reviewBefore = await adminApi('GET', `/api/admin/public-contributions/${requestId}`)
    expect(reviewBefore.response.ok(), JSON.stringify(reviewBefore.body)).toBe(true)
    expect(reviewBefore.body.status).toBe('pending_review')
    expect(reviewBefore.body.items).toHaveLength(1)
    const approval = await adminApi(
      'POST',
      `/api/admin/public-contributions/${requestId}/approve`,
      {
        excluded_item_ids: [],
        review_fields: { source: { company: null, round: null, source_url: null }, items: [] },
      },
    )
    expect(approval.response.status(), JSON.stringify(approval.body)).toBe(200)

    let publishedDetail
    await expect.poll(async () => {
      const result = await adminApi('GET', `/api/admin/public-contributions/${requestId}`)
      if (!result.response.ok()) return `HTTP ${result.response.status()}`
      publishedDetail = result.body
      return publishedDetail.items?.[0]?.status
    }, { timeout: 360000, intervals: [1000, 2000, 5000] }).toBe('published')
    expect(publishedDetail.public_interview_id).toBeTruthy()
    const publicInterviewId = publishedDetail.public_interview_id
    expect(publicInterviewId).not.toBe(privateInterviewId)

    let publishedSnapshot
    await expect.poll(async () => {
      const result = await uploaderApi('GET', `/api/upload-imports/${encodeURIComponent(importId)}`)
      if (!result.response.ok()) return `HTTP ${result.response.status()}`
      publishedSnapshot = result.body
      return publishedSnapshot.result_target?.scope || 'not_published'
    }, { timeout: 60000, intervals: [1000, 2000, 5000] }).toBe('public')
    expect(publishedSnapshot.result_target).toEqual({
      entity_type: 'interview',
      entity_id: publicInterviewId,
      scope: 'public',
    })

    const secondUserLogin = await page.request.post('/api/auth/login', {
      data: { username: 'ac001_ac002_u2', password: PASSWORD },
    })
    expect(secondUserLogin.status(), await secondUserLogin.text()).toBe(200)
    const secondUserToken = (await secondUserLogin.json()).token
    const publicForSecondUser = await page.request.get(
      `/api/data/interview?scope=public&page=1&page_size=100&sort=created_at_desc&position_id=${p2.id}`,
      { headers: { Authorization: `Bearer ${secondUserToken}` } },
    )
    expect(publicForSecondUser.ok(), await publicForSecondUser.text()).toBe(true)
    const secondUserPublicBody = await publicForSecondUser.json()
    expect(secondUserPublicBody.items.some((row) => row.id === publicInterviewId)).toBe(true)
    const publicInterview = secondUserPublicBody.items.find((row) => row.id === publicInterviewId)
    expect(publicInterview['公司']).toBe('')
    expect(publicInterview['公司']).not.toBe(sharedCompany)
    const privateForSecondUser = await page.request.get(
      '/api/data/interview?scope=mine&page=1&page_size=100&sort=created_at_desc',
      { headers: { Authorization: `Bearer ${secondUserToken}` } },
    )
    expect(privateForSecondUser.ok(), await privateForSecondUser.text()).toBe(true)
    expect((await privateForSecondUser.json()).items.some((row) => row.id === privateInterviewId)).toBe(false)
    const otherUserRoot = await page.request.get(`/api/upload-imports/${encodeURIComponent(importId)}`, {
      headers: { Authorization: `Bearer ${secondUserToken}` },
    })
    expect(otherUserRoot.status()).toBe(404)

    // Approval and worker publication must not change the owner's open P1 page.
    await expect(page).toHaveURL(ownerPageUrl)
    await expect(page.getByText('共 61 条，第 2/4 页')).toBeVisible()
    expect(await page.locator('table tbody tr[data-row-id]').filter({ hasText: `${MARKER}_U1_` }).evaluateAll((rows) =>
      rows.map((row) => row.getAttribute('data-row-id')),
    )).toEqual(ownerP1PageTwoIds)

    // The task points to the public interview after publication, not the private
    // source interview created by extraction.
    const snapshot = publishedSnapshot
    await page.getByRole('button', { name: '上传任务中心' }).click()
    const task = page.locator('li').filter({ hasText: importId })
    await expect(task).toBeVisible()
    await expect(task.getByRole('button', { name: '查看结果' })).toBeVisible()
    const uiLocationPromise = page.waitForResponse((response) =>
      /^\/api\/data\/interview\/\d+\/location$/.test(pathOf(response.url())),
    )
    const positionSwitchPromise = page.waitForResponse((response) =>
      pathOf(response.url()) === '/api/profile/my-position' && response.request().method() === 'PUT',
    )
    await task.getByRole('button', { name: '查看结果' }).click()
    const uiLocationResponse = await uiLocationPromise
    expect(uiLocationResponse.status(), await uiLocationResponse.text()).toBe(200)
    const uiLocation = await uiLocationResponse.json()
    expect(uiLocation.interview_id).toBe(publicInterviewId)
    expect(new URL(uiLocationResponse.url()).searchParams.get('page_size')).toBe('20')
    expect(uiLocation.position_id).toBe(p2.id)
    expect(uiLocation.position_name).toBe(p2.name)
    const positionSwitch = await positionSwitchPromise
    expect(positionSwitch.status(), await positionSwitch.text()).toBe(200)
    expect(positionSwitch.request().postDataJSON().position).toBe(p2.name)
    await expect(page.locator(`table tbody tr[data-row-id="${publicInterviewId}"]`)).toBeVisible()
    await expect(page.locator(`table tbody tr[data-row-id="${publicInterviewId}"]`)).toHaveClass(/highlight-row/)
    await expect(page.getByText(`已切换到岗位：${p2.name}`)).toBeVisible()

    const tracePayload = {
      user_id: login.user.id,
      p1_position_id: firstRequest.query.position_id,
      p2_position_id: p2.id,
      p1_total: firstRequest.body.total,
      equal_timestamp_first_page_ids: firstIds,
      p1_page_two_ids: secondRequest.body.items.map((row) => row.id),
      season_total: ascending.body.total,
      ascending_first_page_ids: ascendingIds,
      hidden_u2_marker_present: false,
      hidden_p2_marker_in_p1_list: false,
      target_location: location,
      clicked_task_location: uiLocation,
      task_result_target: snapshot.result_target,
      import_id: importId,
      contribution_request_id: requestId,
      private_interview_id: privateInterviewId,
      public_interview_id: publicInterviewId,
      shared_question: sharedQuestion,
      jd_legacy_response: jdResponses.find((entry) => entry.query.page_size === '100'),
    }
    writeFileSync(tracePath, `${JSON.stringify(tracePayload, null, 2)}\n`, { flag: 'wx' })
  } finally {
    await adminContext?.close().catch(() => {})
    await uploaderContext?.close().catch(() => {})
  }

  expect(jdResponses.every((entry) => entry.status === 200)).toBe(true)
})
