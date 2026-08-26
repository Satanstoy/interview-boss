import { expect, test } from '@playwright/test'

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

    await page.goto('/import')
    await expect(page.getByText('文本内容')).toBeVisible()
    await page.getByPlaceholder('粘贴面经或 JD 内容...').fill(
      '职位描述\n公司：InterviewBoss Stub\n岗位：后端工程师\n职位要求：Python、SQLite。',
    )
    await page.getByRole('button', { name: '提交解析' }).click()

    await expect(page.getByTestId('import-job-item')).toBeVisible({ timeout: 30000 })
    const progressToggle = page.getByTestId('job-progress-toggle')
    await expect(progressToggle).toBeVisible({ timeout: 30000 })
    await progressToggle.click()
    await expect(page.getByTestId('job-progress-panel')).toContainText('处理完成', { timeout: 120000 })

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
