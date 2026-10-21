import { existsSync, writeFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { configureDisposableUserModel } from '../_helpers/real-stack-model.js'

const PASSWORD = 'Ac009-two-owner-isolation-123!'

async function register(page, username) {
  await page.goto('/login')
  await page.getByRole('button', { name: '立即注册' }).click()
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(PASSWORD)
  await page.getByLabel('邮箱').fill(`${username}@example.test`)
  await page.getByRole('button', { name: '注册', exact: true }).click()
  await expect(page).toHaveURL(/\/master-bank/, { timeout: 30000 })
  return configureDisposableUserModel(page)
}

async function submitInterview(page, marker, company, question) {
  await page.goto('/import')
  await page.getByPlaceholder('粘贴面经或 JD 内容...').fill(
    `${marker}\n公司：${company}\n面试轮次：隔离验收\n题目：${question}`,
  )
  const acceptedPromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return url.pathname === '/api/submit-jobs' && response.request().method() === 'POST'
  })
  await page.getByRole('button', { name: '提交解析' }).click()
  const accepted = await acceptedPromise
  const body = await accepted.json()
  expect(accepted.status(), JSON.stringify(body)).toBe(202)
  return body.import_id
}

async function snapshotFor(page, importId, token) {
  return page.evaluate(async ({ id, token }) => {
    const response = await fetch(`/api/upload-imports/${encodeURIComponent(id)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    return { status: response.status, body: await response.json() }
  }, { id: importId, token })
}

async function observeOwnResult(page, importId, token, otherMarker, question) {
  const ownSnapshot = await snapshotFor(page, importId, token)
  expect(ownSnapshot.status).toBe(200)
  expect(ownSnapshot.body.status).toBe('completed')
  expect(ownSnapshot.body.result?.interview_id).toBeTruthy()

  await page.getByRole('button', { name: '上传任务中心' }).click()
  await page.getByRole('button', { name: '刷新' }).click()
  const task = page.locator('li').filter({ hasText: importId })
  await expect(task).toContainText('已完成', { timeout: 30000 })
  await expect(page.locator('body')).not.toContainText(otherMarker)
  await task.getByRole('button', { name: '查看结果' }).click()
  await expect(page).toHaveURL(/\/interview(?:\?|$)/)
  await expect(page.getByText(question, { exact: false })).toBeVisible({ timeout: 30000 })
  await expect(page.locator('body')).not.toContainText(otherMarker)
  return ownSnapshot.body.result.interview_id
}

test('near-simultaneous owners keep every real worker result and read path isolated', async ({ browser, page }) => {
  test.setTimeout(420000)
  test.skip(process.env.REAL_STACK_E2E !== '1', 'run through scripts/real_stack_smoke.sh')
  const handshake = process.env.AC009_WORKER_START_SIGNAL
  const tracePath = process.env.AC009_BROWSER_TRACE
  expect(handshake, 'the runner must hold and start both disposable workers').toBeTruthy()
  expect(tracePath, 'the runner must retain browser/API evidence').toBeTruthy()

  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
  const userA = `ac009_a_${suffix}`
  const userB = `ac009_b_${suffix}`
  const contextB = await browser.newContext({
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:18081',
  })
  const pageB = await contextB.newPage()

  try {
    const [tokenA, tokenB] = await Promise.all([register(page, userA), register(pageB, userB)])

    const [importA, importB] = await Promise.all([
      submitInterview(
        page,
        'AC009_USER_A_REAL_STACK',
        'AC009_USER_A 公司',
        'AC009_USER_A 专属问题：解释事务隔离。',
      ),
      submitInterview(
        pageB,
        'AC009_USER_B_REAL_STACK',
        'AC009_USER_B 公司',
        'AC009_USER_B 专属问题：解释消息幂等。',
      ),
    ])
    expect(importA).toBeTruthy()
    expect(importB).toBeTruthy()
    expect(importA).not.toBe(importB)

    // The runner fixes both accepted roots to the exact same created_at before
    // starting two separate ARQ processes, making the old same-second edge repeatable.
    writeFileSync(handshake, JSON.stringify({ import_ids: [importA, importB] }), { flag: 'wx' })
    await expect.poll(() => existsSync(`${handshake}.done`), { timeout: 90000 }).toBe(true)

    await Promise.all([
      expect.poll(async () => (await snapshotFor(page, importA, tokenA)).body?.status, { timeout: 300000 })
        .toBe('completed'),
      expect.poll(async () => (await snapshotFor(pageB, importB, tokenB)).body?.status, { timeout: 300000 })
        .toBe('completed'),
    ])
    const [snapshotA, snapshotB] = await Promise.all([
      snapshotFor(page, importA, tokenA), snapshotFor(pageB, importB, tokenB),
    ])
    expect(snapshotA.status).toBe(200)
    expect(snapshotB.status).toBe(200)
    expect(snapshotA.body.status).toBe('completed')
    expect(snapshotB.body.status).toBe('completed')

    const [crossA, crossB] = await Promise.all([
      snapshotFor(page, importB, tokenA),
      snapshotFor(pageB, importA, tokenB),
    ])
    expect(crossA.status).toBe(404)
    expect(crossB.status).toBe(404)

    const [interviewA, interviewB] = await Promise.all([
      observeOwnResult(
        page,
        importA,
        tokenA,
        'AC009_USER_B_REAL_STACK',
        'AC009_USER_A 专属问题：解释事务隔离。',
      ),
      observeOwnResult(
        pageB,
        importB,
        tokenB,
        'AC009_USER_A_REAL_STACK',
        'AC009_USER_B 专属问题：解释消息幂等。',
      ),
    ])
    expect(interviewA).not.toBe(interviewB)

    writeFileSync(tracePath, `${JSON.stringify({
      users: [userA, userB],
      imports: [importA, importB],
      interviews: [interviewA, interviewB],
      fixed_same_second: true,
      cross_owner_snapshot_statuses: [crossA.status, crossB.status],
      own_results_opened: true,
    }, null, 2)}\n`, { flag: 'wx' })
  } finally {
    await contextB.close()
  }
})
