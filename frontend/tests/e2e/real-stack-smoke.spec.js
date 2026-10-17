import { expect, test } from '@playwright/test'
import { configureDisposableUserModel } from '../_helpers/real-stack-model.js'

test.describe('disposable real stack', () => {
  // The Compose stack injects a stubbed provider; no real LLM credentials are used.
  test.skip(process.env.REAL_STACK_E2E !== '1', 'run through scripts/real_stack_smoke.sh')

  test('routes auth, queue, worker persistence, and browser rendering through the stack', async ({ page }) => {
    const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
    const username = `real_e2e_${suffix}`
    const email = `${username}@example.test`
    const password = 'real-stack-password-123'

    await page.goto('/login')
    await page.getByRole('button', { name: '立即注册' }).click()
    await page.getByLabel('用户名').fill(username)
    await page.getByLabel('密码').fill(password)
    await page.getByLabel('邮箱').fill(email)
    await page.getByRole('button', { name: '注册', exact: true }).click()
    await expect(page).toHaveURL(/\/master-bank/, { timeout: 30000 })
    await configureDisposableUserModel(page)

    const interviewListResponsePromise = page.waitForResponse((response) => {
      const requestUrl = new URL(response.url())
      return requestUrl.pathname === '/api/data/interview' && response.request().method() === 'GET'
    })
    await page.goto('/jd')
    const interviewListResponse = await interviewListResponsePromise
    expect(new URL(interviewListResponse.url()).searchParams.get('sort')).toBe('created_at_desc')
    // This response belongs to a page navigation. Reading its body after the
    // navigation has completed can lose the CDP response id; the smoke only
    // needs to verify the routed request and status here.
    expect(interviewListResponse.status()).toBe(200)

    await page.goto('/import')
    await expect(page.getByText('文本内容')).toBeVisible()
    await page.getByText('自动识别', { exact: true }).click()
    await page.getByRole('option', { name: 'JD', exact: true }).click()
    await page.getByPlaceholder('粘贴面经或 JD 内容...').fill(
      '职位描述\n公司：InterviewBoss Stub\n岗位：后端工程师\n职位要求：Python、SQLite。',
    )
    const acceptedResponse = page.waitForResponse((response) => {
      const requestUrl = new URL(response.url())
      return requestUrl.pathname === '/api/submit-jobs' && response.request().method() === 'POST'
    })
    await page.getByRole('button', { name: '提交解析' }).click()
    const accepted = await acceptedResponse
    expect(accepted.status()).toBe(202)
    const acceptedBody = await accepted.json()
    const authorization = accepted.request().headers().authorization
    expect(authorization).toMatch(/^Bearer /)
    const statusResponse = await page.request.get(new URL(acceptedBody.status_url, accepted.url()).href, {
      headers: { authorization },
    })
    expect(statusResponse.status()).toBe(200)
    expect((await statusResponse.json()).resolved_type).toBe('jd')
    const { import_id: importId } = acceptedBody

    await page.getByRole('button', { name: '上传任务中心' }).click()
    const task = page.locator('li').filter({ hasText: importId })
    await expect(task).toContainText('已完成', { timeout: 180000 })

    await page.goto('/jd')
    await expect(page.getByText('InterviewBoss Stub')).toBeVisible({ timeout: 30000 })

    // This is an intentional client-visible failure assertion（失败可观察）。It proves the
    // stack does not silently accept invalid source input.
    await page.goto('/import')
    await page.getByPlaceholder('粘贴面经或 JD 内容...').fill('failure visibility check')
    await page.getByPlaceholder('https://...').fill('not-a-url')
    await page.getByRole('button', { name: '提交解析' }).click()
    await expect(page.getByTestId('submit-error')).toContainText('请输入有效的 URL')
  })

  test('recovers the same accepted upload after the browser loses the POST response', async ({ page }) => {
    const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
    const username = `lost_response_${suffix}`
    const password = 'real-stack-lost-response-123'
    const text = `AC021_LOST_RESPONSE_${suffix}\n公司：隔离网络恢复演练\n面试轮次：一面\n题目：解释数据库事务隔离级别。`
    const postKeys = []
    const recoveredSnapshots = []
    let acceptedSnapshot = null
    let postCount = 0

    await page.goto('/login')
    await page.getByRole('button', { name: '立即注册' }).click()
    await page.getByLabel('用户名').fill(username)
    await page.getByLabel('密码').fill(password)
    await page.getByLabel('邮箱').fill(`${username}@example.test`)
    await page.getByRole('button', { name: '注册', exact: true }).click()
    await expect(page).toHaveURL(/\/master-bank/, { timeout: 30000 })
    await configureDisposableUserModel(page)

    await page.route('**/api/upload-imports/by-key/**', async (route) => {
      const response = await route.fetch()
      if (response.status() === 200) recoveredSnapshots.push(await response.json())
      await route.fulfill({ response })
    })
    await page.route('**/api/submit-jobs', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      postCount += 1
      postKeys.push(route.request().headers()['idempotency-key'])

      // Send the real multipart POST to the disposable API. Let it commit and
      // capture its 202, then make the browser observe a dropped connection.
      const response = await route.fetch()
      expect(response.status(), await response.text()).toBe(202)
      acceptedSnapshot = await response.json()
      if (postCount === 1) return route.abort('failed')
      await route.fulfill({ response })
    })

    await page.goto('/import')
    const textarea = page.getByPlaceholder('粘贴面经或 JD 内容...')
    await textarea.fill(text)
    await page.getByRole('button', { name: '提交解析' }).click()

    await expect(page.getByText('已提交成功，任务正在后台处理。可继续提交或离开页面，右上角显示进度。')).toBeVisible({ timeout: 30000 })
    await expect(textarea).toHaveValue('')
    await expect.poll(() => recoveredSnapshots.length).toBe(1)
    expect(acceptedSnapshot?.import_id).toBeTruthy()
    expect(recoveredSnapshots[0].import_id).toBe(acceptedSnapshot.import_id)
    expect(postCount).toBe(1)
    expect(postKeys).toHaveLength(1)
    expect(postKeys[0]).toBeTruthy()
  })
})
