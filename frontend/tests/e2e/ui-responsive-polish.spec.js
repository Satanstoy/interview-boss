import { test, expect } from '@playwright/test'

const preview = (path) => `${path}?preview=1`

async function gotoPreview(page, path, viewport = { width: 390, height: 844 }) {
  await page.setViewportSize(viewport)
  await page.goto(preview(path), { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('main', { timeout: 15000 })
  await page.waitForTimeout(700)
}

async function expectNoHorizontalOverflow(page) {
  const metrics = await page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.width + 1)
}

test.describe('UI responsive polish', () => {
  test('desktop sidebar uses grouped workflow order', async ({ page }) => {
    await gotoPreview(page, '/master-bank', { width: 1440, height: 900 })
    const sidebar = page.locator('aside')
    await expect(sidebar.getByText('高频题库')).toBeVisible()
    await expect(sidebar.getByText('训练')).toBeVisible()
    await expect(sidebar.getByText('素材')).toBeVisible()
    await expect(sidebar.getByText('洞察')).toBeVisible()

    const labels = await sidebar.locator('[data-sidebar-route], [data-sidebar-section]').evaluateAll((nodes) =>
      nodes.map((node) => node.textContent.trim().replace(/\s+/g, ' '))
    )
    expect(labels).toEqual([
      '高频题库 3',
      '训练',
      '模拟面试',
      '手撕代码',
      '素材',
      '导入',
      'JD 筛选 2',
      '面经库 2',
      '洞察',
      '知识图谱',
    ])
  })

  test('desktop sidebar logo returns to the master bank', async ({ page }) => {
    await gotoPreview(page, '/chat', { width: 1440, height: 900 })
    await page.getByRole('link', { name: /InterviewBoss/ }).click()
    await expect(page).toHaveURL(/\/master-bank\?preview=1/)
    await expect(page.getByRole('heading', { name: '高频题库' })).toBeVisible()
  })

  test('expanded sidebar brand matches navigation hover and centers its logo', async ({ page }) => {
    await gotoPreview(page, '/chat', { width: 1440, height: 900 })
    const sidebar = page.locator('aside')
    const brand = sidebar.getByTestId('sidebar-brand')
    const navItem = sidebar.locator('[data-sidebar-route]').filter({ hasText: '手撕代码' })

    const brandBox = await brand.boundingBox()
    const logoBox = await brand.locator('img').boundingBox()
    expect(Math.abs((logoBox.y + logoBox.height / 2) - (brandBox.y + brandBox.height / 2))).toBeLessThanOrEqual(1)

    await brand.hover()
    await page.waitForTimeout(550)
    const brandHover = await brand.evaluate((element) => {
      const style = getComputedStyle(element)
      return {
        backgroundColor: style.backgroundColor,
        boxShadow: style.boxShadow,
        transform: style.transform,
        backlightOpacity: getComputedStyle(element, '::before').opacity,
      }
    })

    await navItem.hover()
    await page.waitForTimeout(550)
    const navHover = await navItem.evaluate((element) => {
      const style = getComputedStyle(element)
      return {
        backgroundColor: style.backgroundColor,
        boxShadow: style.boxShadow,
        transform: style.transform,
        backlightOpacity: getComputedStyle(element, '::before').opacity,
      }
    })

    expect(brandHover).toEqual(navHover)
  })

  test('route changes animate and text fields use Xiaomi-safe font features', async ({ page }) => {
    await gotoPreview(page, '/chat', { width: 1440, height: 900 })

    const fontFeatures = await page.evaluate(() => {
      const textarea = document.createElement('textarea')
      document.body.appendChild(textarea)
      const result = {
        body: getComputedStyle(document.body).fontFeatureSettings,
        field: getComputedStyle(textarea).fontFeatureSettings,
        ligatures: getComputedStyle(textarea).fontVariantLigatures,
      }
      textarea.remove()
      return result
    })
    expect(fontFeatures.body).toBe('normal')
    expect(fontFeatures.field).toBe('normal')
    expect(fontFeatures.ligatures).toBe('none')

    const codingRoute = page.locator('aside [data-sidebar-route]').filter({ hasText: '手撕代码' })
    await codingRoute.click({ noWaitAfter: true })
    await expect(page.locator('.page-route-leave-active')).toBeAttached()
    await expect(page).toHaveURL(/\/coding\?preview=1/)
  })

  test('mobile shell navigation opens and switches routes', async ({ page }) => {
    await gotoPreview(page, '/master-bank')
    await page.getByRole('button', { name: '打开导航' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('button', { name: /导入/ }).click()
    await expect(page).toHaveURL(/\/import\?preview=1/)
    await expect(page.getByRole('heading', { name: '导入' })).toBeVisible()
    await expectNoHorizontalOverflow(page)
  })

  test('mobile JD and interview data render as cards, not compressed tables', async ({ page }) => {
    await gotoPreview(page, '/jd')
    await expect(page.locator('[data-mobile-row-card]').first()).toBeVisible()
    await expect(page.locator('table')).toBeHidden()
    await expect(page.getByText('Moonshot AI')).toBeVisible()
    await expectNoHorizontalOverflow(page)

    await gotoPreview(page, '/interview')
    await expect(page.locator('[data-mobile-row-card]').first()).toBeVisible()
    await expect(page.locator('table')).toBeHidden()
    await expect(page.getByText('腾讯')).toBeVisible()
    await expectNoHorizontalOverflow(page)
  })

  test('mobile chat keeps active conversation readable and switchable', async ({ page }) => {
    await gotoPreview(page, '/chat')
    await expect(page.getByRole('button', { name: '切换面试会话' })).toBeVisible()
    const main = page.locator('main')
    const box = await main.boundingBox()
    expect(box.width).toBeGreaterThanOrEqual(360)
    await expect(page.getByText('如果遇到一份格式很乱的面经')).toBeVisible()
    await expectNoHorizontalOverflow(page)
  })

  test('mobile coding keeps main content readable and problem list switchable', async ({ page }) => {
    await gotoPreview(page, '/coding')
    await expect(page.getByRole('button', { name: '选择题目' })).toBeVisible()
    await expect(page.getByText('开始编码练习')).toBeVisible()
    const main = page.locator('main')
    const box = await main.boundingBox()
    expect(box.width).toBeGreaterThanOrEqual(360)
    await expectNoHorizontalOverflow(page)
  })

  test('mobile master bank cards keep controls inside viewport', async ({ page }) => {
    await gotoPreview(page, '/master-bank')
    const practiceButton = page.getByRole('button', { name: '开始八股刷题' })
    await expect(practiceButton).toBeVisible()
    expect((await practiceButton.boundingBox()).height).toBeGreaterThanOrEqual(40)
    await expect(page.getByRole('button', { name: '全选' })).toBeHidden()

    await page.getByRole('button', { name: /管理/ }).click()
    await expect(page.getByRole('button', { name: '全选' })).toBeVisible()
    await page.getByRole('button', { name: /管理/ }).click()

    const firstQuestion = page.locator('[data-slot="accordion-trigger"]').first()
    await expect(firstQuestion.getByText('查看答案')).toBeVisible()
    await firstQuestion.click()
    await expect(firstQuestion.getByText('收起答案')).toBeVisible()
    await expect(page.getByRole('button', { name: '开始练习这道题' }).first()).toBeVisible()

    const viewportWidth = await page.evaluate(() => document.documentElement.clientWidth)
    const overflowingButtons = await page.locator('button').evaluateAll((buttons, width) =>
      buttons
        .map((button) => button.getBoundingClientRect())
        .filter((rect) => rect.width > 0 && (rect.left < -1 || rect.right > width + 1))
        .length,
      viewportWidth
    )
    expect(overflowingButtons).toBe(0)
    await expectNoHorizontalOverflow(page)
  })
})
