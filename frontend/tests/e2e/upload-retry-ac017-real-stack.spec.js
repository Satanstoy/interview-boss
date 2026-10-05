import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

const IMPORT_ID = 'imp-ac017-cross-generation-retry'
const OWNER = 'ac017_owner'
const PASSWORD = 'Ac017-cross-generation-retry-real-stack-123!'
const RUNNING_MESSAGE = '已有恢复任务正在继续处理未完成步骤'

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
  return { status: response.status(), body: await response.json() }
}

test('AC-017 old A/B IDs converge on active C and distinct answer keys run in parallel', async ({
  browser,
  page,
}) => {
  test.setTimeout(300000)
  test.skip(process.env.REAL_STACK_E2E !== '1', 'run through scripts/real_stack_smoke.sh')
  const seedPath = process.env.AC017_SEED_PATH
  const controlPrefix = process.env.AC017_CONTROL_PREFIX
  const tracePath = process.env.AC017_BROWSER_TRACE
  expect(seedPath).toBeTruthy()
  expect(controlPrefix).toBeTruthy()
  expect(tracePath).toBeTruthy()
  const seed = JSON.parse(readFileSync(seedPath, 'utf8'))

  const secondContext = await browser.newContext()
  const secondPage = await secondContext.newPage()
  try {
    const token = await login(page, OWNER, PASSWORD)
    const secondToken = await login(secondPage, OWNER, PASSWORD)

    const oldA = await api(
      page,
      token,
      'POST',
      `/api/submit-jobs/${seed.job_ids.A}/retry`,
      {},
    )
    const oldB = await api(
      secondPage,
      secondToken,
      'POST',
      `/api/submit-jobs/${seed.job_ids.B}/retry`,
      {},
    )
    for (const [label, response] of [['A', oldA], ['B', oldB]]) {
      expect(response.status, `${label} retry: ${JSON.stringify(response.body)}`).toBe(200)
      expect(response.body.job_id).toBe(seed.job_ids.C)
      expect(response.body.created).toBe(false)
    }

    const rootPath = `/api/upload-imports/${encodeURIComponent(IMPORT_ID)}/retry`
    const [firstRootRetry, secondRootRetry] = await Promise.all([
      api(page, token, 'POST', rootPath, {}),
      api(secondPage, secondToken, 'POST', rootPath, {}),
    ])
    for (const response of [firstRootRetry, secondRootRetry]) {
      expect(response.status, JSON.stringify(response.body)).toBe(200)
      expect(response.body.import_id).toBe(IMPORT_ID)
      expect(response.body.attempt_no).toBe(3)
      expect(response.body.created_attempt).toBe(false)
    }

    await page.goto('/')
    await page.getByRole('button', { name: '上传任务中心' }).click()
    const task = page.locator('li').filter({ hasText: IMPORT_ID })
    await expect(task).toContainText('部分失败')
    const uiRetryResponse = page.waitForResponse((response) =>
      pathOf(response.url()) === rootPath && response.request().method() === 'POST',
    )
    await task.getByRole('button', { name: '重试失败步骤' }).click()
    const uiResponse = await uiRetryResponse
    const uiBody = await uiResponse.json()
    expect(uiResponse.status(), JSON.stringify(uiBody)).toBe(200)
    expect(uiBody.created_attempt).toBe(false)
    await expect(page.getByText(RUNNING_MESSAGE, { exact: true })).toBeVisible()

    writeFileSync(`${controlPrefix}.retry-actions-done`, 'retry actions verified\n', { flag: 'wx' })
    await expect.poll(() => existsSync(`${controlPrefix}.parallel-answers-inflight`), {
      timeout: 90000,
      intervals: [100, 250, 500],
    }).toBe(true)
    const overlapRetries = await Promise.all([
      api(page, token, 'POST', rootPath, {}),
      api(secondPage, secondToken, 'POST', rootPath, {}),
    ])
    for (const response of overlapRetries) {
      expect(response.status, JSON.stringify(response.body)).toBe(200)
      expect(response.body.import_id).toBe(IMPORT_ID)
      expect(response.body.attempt_no).toBe(3)
      expect(response.body.created_attempt).toBe(false)
    }
    writeFileSync(
      `${controlPrefix}.parallel-retries.json`,
      `${JSON.stringify(overlapRetries.map((response) => ({
        status: response.status,
        import_id: response.body.import_id,
        attempt_no: response.body.attempt_no,
        created_attempt: response.body.created_attempt,
      })), null, 2)}\n`,
      { flag: 'wx' },
    )
    writeFileSync(`${controlPrefix}.parallel-retries-done`, 'workers held in provider while retry ran\n', {
      flag: 'wx',
    })
    await expect.poll(() => existsSync(`${controlPrefix}.answers-complete`), {
      timeout: 210000,
      intervals: [500, 1000, 2000],
    }).toBe(true)

    const finalSnapshot = await api(
      page,
      token,
      'GET',
      `/api/upload-imports/${encodeURIComponent(IMPORT_ID)}`,
    )
    expect(finalSnapshot.status, JSON.stringify(finalSnapshot.body)).toBe(200)
    expect(finalSnapshot.body.import_id).toBe(IMPORT_ID)
    writeFileSync(
      tracePath,
      `${JSON.stringify({
        import_id: IMPORT_ID,
        job_ids: seed.job_ids,
        old_id_retries: [
          { source: 'A', status: oldA.status, job_id: oldA.body.job_id, created: oldA.body.created },
          { source: 'B', status: oldB.status, job_id: oldB.body.job_id, created: oldB.body.created },
        ],
        concurrent_root_retries: [
          {
            status: firstRootRetry.status,
            attempt_no: firstRootRetry.body.attempt_no,
            created_attempt: firstRootRetry.body.created_attempt,
          },
          {
            status: secondRootRetry.status,
            attempt_no: secondRootRetry.body.attempt_no,
            created_attempt: secondRootRetry.body.created_attempt,
          },
        ],
        task_center_retry: {
          status: uiResponse.status(),
          attempt_no: uiBody.attempt_no,
          created_attempt: uiBody.created_attempt,
          message: RUNNING_MESSAGE,
        },
        retries_while_two_workers_in_provider: JSON.parse(
          readFileSync(`${controlPrefix}.parallel-retries.json`, 'utf8'),
        ),
        final_root_status: finalSnapshot.body.status,
      }, null, 2)}\n`,
      { flag: 'wx' },
    )
  } finally {
    await secondContext.close()
  }
})
