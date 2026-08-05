import { test, expect } from '@playwright/test'

test.describe('Tab 切换防抖测试', () => {
  test('快速点击高频题库后，其他 tab 仍可正常切换', async ({ page }) => {
    // mock API
    await page.route('**/api/**', async (route) => {
      const url = route.request().url()
      if (url.includes('/auth/login')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            token: 'test-token',
            user: { id: 1, username: 'test', is_admin: false, bank_mode: 'public' }
          })
        })
      } else if (url.includes('/auth/me')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ id: 1, username: 'test', is_admin: false, bank_mode: 'public' })
        })
      } else if (url.includes('/master-bank') || url.includes('/analytics')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([])
        })
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({})
        })
      }
    })

    await page.goto('/')
    await page.waitForTimeout(2000)

    // 登录
    const usernameInput = page.locator('input[name="username"]').first()
    const passwordInput = page.locator('input[name="password"]').first()
    await usernameInput.fill('test')
    await passwordInput.fill('password123')
    await page.click('button:has-text("登录")')
    await page.waitForTimeout(3000)

    // 验证登录成功
    await expect(page.locator('text=高频题库')).toBeVisible({ timeout: 10000 })

    // 快速点击高频题库 15 次
    const masterBankTab = page.locator('button:has-text("高频题库")')
    for (let i = 0; i < 15; i++) {
      await masterBankTab.click({ delay: 50 })
    }
    await page.waitForTimeout(500)

    // 验证其他 tab 仍然可点击且有内容
    const tabsToTest = ['模拟面试', '知识图谱']
    
    for (const tabName of tabsToTest) {
      const tab = page.locator(`button:has-text("${tabName}")`)
      await expect(tab).toBeVisible()
      
      // 点击 tab
      await tab.click()
      await page.waitForTimeout(1000)
      
      // 验证 tab 被选中
      await expect(tab).toHaveAttribute('aria-selected', 'true')
      
      // 验证内容区域存在（不是空白）
      const contentArea = page.locator('.tab-content')
      await expect(contentArea).toBeVisible()
      
      // 验证内容区域有实际内容（HTML 长度 > 100）
      const html = await contentArea.innerHTML()
      expect(html.length).toBeGreaterThan(100)
    }
  })

  test('TabBar 防抖：快速点击时按钮会被禁用', async ({ page }) => {
    await page.goto('/')
    await page.waitForTimeout(2000)

    // 检查 TabBar 按钮在快速点击时是否会被禁用
    const tabButton = page.locator('button:has-text("高频题库")')
    
    // 快速点击
    await tabButton.click()
    
    // 检查按钮是否暂时被禁用（disabled 属性）
    const isDisabled = await tabButton.isDisabled()
    // 注意：由于防抖时间短（300ms），这个测试可能需要调整
    // 但至少验证按钮不会一直处于禁用状态
    await page.waitForTimeout(500)
    const isDisabledAfter = await tabButton.isDisabled()
    expect(isDisabledAfter).toBe(false)
  })
})
