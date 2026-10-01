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

    await page.goto('/import')
    await expect(page.getByText('文本内容')).toBeVisible()
    await page.getByPlaceholder('粘贴面经或 JD 内容...').fill(
      '职位描述\n公司：InterviewBoss Stub\n岗位：后端工程师\n职位要求：Python、SQLite。',
    )
    const acceptedResponse = page.waitForResponse((response) => {
      const requestUrl = new URL(response.url())
      return requestUrl.pathname === '/api/submit-jobs' && response.request().method() === 'POST'
    })
    await page.getByRole('button', { name: '提交解析' }).click()
    const accepted = await acceptedResponse
    expect(accepted.status(), await accepted.text()).toBe(202)
    const { import_id: importId } = await accepted.json()

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
})
