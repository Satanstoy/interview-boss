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
      '题目抽测',
      '手撕代码',
      '素材',
      '导入',
      'JD 筛选 2',
      '面经库 2',
      '洞察',
      '知识图谱',
    ])
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
