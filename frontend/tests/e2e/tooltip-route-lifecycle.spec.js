import { expect, test } from '@playwright/test'

test.describe('Tooltip route lifecycle', () => {
  test.beforeEach(async ({ page }) => {
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'mocked unauthorized' }),
      })
    })

    await page.addInitScript(() => {
      localStorage.removeItem('sidebar-collapsed')
    })
  })

  test('does not keep a route tooltip mounted after navigating away and back', async ({ page }) => {
    await page.goto('/master-bank?preview=1')

    const collapseSidebarButton = page.getByRole('button', { name: '收起侧栏' })
    await expect(collapseSidebarButton).toBeVisible()

    await collapseSidebarButton.hover()
    await expect(page.locator('[data-slot="tooltip-content"]')).toBeVisible()

    await page.evaluate(() => {
      const target = [...document.querySelectorAll('[data-sidebar-route]')]
        .find(element => element.textContent.includes('模拟面试'))
      target?.click()
    })
    await expect(page).toHaveURL(/\/chat\?preview=1$/)

    await page.evaluate(() => {
      const target = [...document.querySelectorAll('[data-sidebar-route]')]
        .find(element => element.textContent.includes('高频题库'))
      target?.click()
    })
    await expect(page).toHaveURL(/\/master-bank\?preview=1$/)

    await expect(page.locator('[data-slot="tooltip-content"]')).toHaveCount(0)
  })
})
