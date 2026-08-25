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

test('login button keeps a stable disabled visual when hovered', async ({ page }) => {
  await page.goto('/login')

  const button = page.getByRole('button', { name: /^登录$/ })
  await expect(button).toBeDisabled()

  await page.mouse.move(20, 20)
  const beforeHover = await button.evaluate((element) => {
    const styles = getComputedStyle(element)
    return { background: styles.backgroundColor, boxShadow: styles.boxShadow }
  })

  await button.hover()
  const afterHover = await button.evaluate((element) => {
    const styles = getComputedStyle(element)
    return { background: styles.backgroundColor, boxShadow: styles.boxShadow }
  })

  expect(afterHover.background).toBe(beforeHover.background)
  expect(afterHover.boxShadow).toMatch(/none|rgba\(0, 0, 0, 0\)/)
})

test('login fields expose their visible labels', async ({ page }) => {
  await page.goto('/login')

  await expect(page.getByLabel('用户名')).toHaveCount(1)
  await expect(page.getByLabel('密码')).toHaveCount(1)
})

test('auth shell only uses same-origin theme and font resources', async ({ page }) => {
  const externalFontRequests = []
  page.on('request', (request) => {
    if (/fonts\.(googleapis|gstatic)\.com/.test(request.url())) {
      externalFontRequests.push(request.url())
    }
  })

  await page.goto('/login')

  await expect(page.locator('script[src="/theme-init.js"]')).toHaveCount(1)
  expect(externalFontRequests).toEqual([])
})

test('data table row checkboxes expose a row-specific name', async ({ page }) => {
  await page.goto('/jd?preview=1')

  const checkbox = page.locator('input[type="checkbox"]').first()
  await expect(checkbox).toBeVisible()
  await expect(checkbox).toHaveAttribute('aria-label', /选择第\s*\d+\s*行/)
})

test('mobile controls keep accessible names when text is hidden', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  await page.goto('/coding?preview=1')
  await expect(page.getByRole('button', { name: 'AI 导入', exact: true })).toHaveCount(1)

  await page.goto('/settings?preview=1')
  await expect(page.getByRole('switch', { name: '默认收起侧栏' })).toHaveCount(1)
})

test('practice page distinguishes deck loading failure from an empty deck', async ({ page }) => {
  await page.route(/\/api\/auth\/refresh$/, async route => {
    await route.fulfill({
      json: {
        token: 'mock-token',
        user: { id: 1, username: 'uiux-user', is_admin: false, bank_mode: 'public' },
      },
    })
  })
  await page.route(/\/api\/practice\/decks/, async route => {
    await route.fulfill({ status: 500, json: { detail: '题单服务暂时不可用' } })
  })
  await page.goto('/practice')

  await expect(page.getByTestId('practice-deck-error')).toBeVisible({ timeout: 10000 })
  await expect(page.getByRole('button', { name: '重新加载题单' })).toBeVisible()
})

test('chat attachment action extracts a PDF into the composer', async ({ page }) => {
  await page.route('**/api/chat/extract-pdf', async route => {
    await route.fulfill({ json: { status: 'success', text: '附件中的面试重点' } })
  })
  await page.goto('/chat?preview=1')

  const fileInput = page.locator('input[type="file"][accept*=".pdf"]')
  await expect(fileInput).toHaveCount(1)
  await fileInput.setInputFiles({
    name: '面试资料.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 fake test fixture'),
  })

  await expect(page.locator('textarea')).toHaveValue(/附件中的面试重点/)
})

test('tooltip closes when the browser page becomes hidden', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/coding?preview=1')

  const trigger = page.locator('button[aria-label="收起题目列表"]')
  await trigger.hover()
  const tooltip = page.locator('[role="tooltip"]').last()
  await expect(tooltip).toBeVisible()

  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
  })

  await expect(tooltip).toBeHidden()
})
