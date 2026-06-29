import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'mocked unauthorized' }),
    })
  })
})

test('quality gate smoke: login route renders without real backend', async ({ page }) => {
  await page.goto('/login')

  await expect(page.getByTestId('login-page')).toBeVisible()
  await expect(page.getByTestId('login-brand')).toContainText('InterviewBoss')
  await expect(page.getByTestId('login-panel')).toBeVisible()
  await expect(page.getByRole('button', { name: /^登录$/ })).toBeVisible()
})
