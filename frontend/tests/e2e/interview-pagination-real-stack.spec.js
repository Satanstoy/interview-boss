import { writeFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

const USERNAME = 'ac001_ac002_u1'
const PASSWORD = 'Ac001-ac002-real-stack-123!'
const MARKER = 'AC001_AC002_FIXTURE'

function pathOf(value) {
  return new URL(value).pathname
}

test('real SQLite pagination keeps scope, filters and target location aligned', async ({ page }) => {
  test.setTimeout(90000)
  test.skip(process.env.REAL_STACK_E2E !== '1', 'run through scripts/real_stack_smoke.sh')
  const tracePath = process.env.AC001_AC002_BROWSER_TRACE
  expect(tracePath, 'the runner must retain browser/API evidence').toBeTruthy()

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
  expect(secondRequest.body.items.map((row) => row.id)).not.toEqual(firstIds)

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

  const importId = 'imp-ac001-ac002-public-result'
  const snapshotResponse = await page.request.get(
    `/api/upload-imports/${encodeURIComponent(importId)}`,
    { headers: { Authorization: `Bearer ${login.token}` } },
  )
  expect(snapshotResponse.ok(), await snapshotResponse.text()).toBe(true)
  const snapshot = await snapshotResponse.json()
  expect(snapshot.result.interview_id).not.toBe(snapshot.result_target.entity_id)
  expect(snapshot.result_target).toEqual({
    entity_type: 'interview',
    entity_id: target.id,
    scope: 'public',
  })

  // Keep the user on P1 page 2 with a season filter. Clicking the real task
  // uses its public target, clears the conflicting list state, and switches to P2.
  await page.locator('[data-slot="pagination-next"]').click()
  await expect(page.getByText('共 61 条，第 2/4 页')).toBeVisible()
  await page.getByRole('button', { name: '上传任务中心' }).click()
  const task = page.locator('li').filter({ hasText: importId })
  await expect(task).toContainText('已完成')
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
  expect(uiLocation.interview_id).toBe(target.id)
  expect(new URL(uiLocationResponse.url()).searchParams.get('page_size')).toBe('20')
  expect(new URL(uiLocationResponse.url()).searchParams.get('position_id')).toBe(String(p2.id))
  const positionSwitch = await positionSwitchPromise
  expect(positionSwitch.status(), await positionSwitch.text()).toBe(200)
  expect(positionSwitch.request().postDataJSON().position).toBe(p2.name)
  await expect(page.locator(`[data-row-id="${target.id}"]`)).toBeVisible()
  await expect(page.locator(`[data-row-id="${target.id}"]`)).toHaveClass(/highlight-row/)
  await expect(page.getByText(`已切换到岗位：${p2.name}`)).toBeVisible()

  expect(jdResponses.some((entry) =>
    entry.status === 200 && entry.body && Array.isArray(entry.body.items) &&
    typeof entry.body.total === 'number' && entry.query.page_size === '100',
  )).toBe(true)
  expect(jdResponses.every((entry) => entry.status === 200)).toBe(true)

  writeFileSync(tracePath, `${JSON.stringify({
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
    jd_legacy_response: jdResponses.find((entry) => entry.query.page_size === '100'),
  }, null, 2)}\n`, { flag: 'wx' })
})
