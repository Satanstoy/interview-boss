import { existsSync, writeFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { configureDisposableUserModel } from '../_helpers/real-stack-model.js'

test.describe('upload recovery against the disposable real stack', () => {
  test.skip(process.env.REAL_STACK_E2E !== '1', 'run through scripts/real_stack_smoke.sh')

  test('a queued personal interview survives worker restart and opens its exact result', async ({ page }) => {
    const restartSignal = process.env.AC028_WORKER_RESTART_SIGNAL
    expect(restartSignal, 'the real-stack runner must provide a worker restart handshake').toBeTruthy()
    expect(process.env.AC028_BROWSER_RESULT_SCREENSHOT).toBeTruthy()

    const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
    const username = `ac028_${suffix}`
    const question = 'AC028 恢复后结果题'

    await page.goto('/login')
    await page.getByRole('button', { name: '立即注册' }).click()
    await page.getByLabel('用户名').fill(username)
    await page.getByLabel('密码').fill('Ac028-upload-recovery-123!')
    await page.getByLabel('邮箱').fill(`${username}@example.test`)
    await page.getByRole('button', { name: '注册', exact: true }).click()
    await expect(page).toHaveURL(/\/master-bank/, { timeout: 30000 })
    await configureDisposableUserModel(page)

    await page.goto('/import')
    await page.getByPlaceholder('粘贴面经或 JD 内容...').fill(
      `AC028_UPLOAD_RECOVERY_REAL_STACK\n公司：AC028 隔离恢复演练\n面试轮次：一面\n题目：${question}`,
    )
    const acceptedResponse = page.waitForResponse((response) => {
      const requestUrl = new URL(response.url())
      return requestUrl.pathname === '/api/submit-jobs' && response.request().method() === 'POST'
    })
    await page.getByRole('button', { name: '提交解析' }).click()
    const accepted = await acceptedResponse
    expect(accepted.status(), await accepted.text()).toBe(202)
    const { import_id: importId } = await accepted.json()
    expect(importId).toBeTruthy()

    await page.getByRole('button', { name: '上传任务中心' }).click()
    const task = page.locator('li').filter({ hasText: importId })
    await expect(task).toContainText('排队中', { timeout: 30000 })

    // The shell runner has already stopped the disposable worker. Signal only
    // after the browser sees its durable queued task, then wait for that same
    // worker container to restart before observing completion.
    writeFileSync(restartSignal, `${importId}\n`, { flag: 'wx' })
    await expect.poll(() => existsSync(`${restartSignal}.done`), { timeout: 90000 }).toBe(true)

    await expect(task).toContainText('已完成', { timeout: 180000 })
    const locationResponse = page.waitForResponse((response) =>
      /\/api\/data\/interview\/\d+\/location/.test(new URL(response.url()).pathname),
    )
    await task.getByRole('button', { name: '查看结果' }).click()
    const location = await locationResponse
    expect(location.ok(), await location.text()).toBe(true)
    const locationBody = await location.json()
    expect(locationBody.interview_id).toBeTruthy()
    await expect(page).toHaveURL(/\/interview(?:\?|$)/)
    await expect(page.getByText(question, { exact: false })).toBeVisible({ timeout: 30000 })
    writeFileSync(
      process.env.AC028_BROWSER_RESULT_TRACE,
      JSON.stringify({
        import_id: importId,
        status: 'completed',
        interview_id: locationBody.interview_id,
        location: {
          page: locationBody.page,
          position_id: locationBody.position_id,
        },
        visible_question: question,
      }, null, 2),
      { flag: 'wx' },
    )
    await page.screenshot({ path: process.env.AC028_BROWSER_RESULT_SCREENSHOT, fullPage: true })
  })
})
