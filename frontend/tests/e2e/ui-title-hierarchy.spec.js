import { expect, test } from '@playwright/test'

async function openPreview(page, path, width = 1280) {
  await page.setViewportSize({ width, height: 900 })
  await page.goto(`${path}?preview=1`)
  await page.locator('main').waitFor()
}

test.describe('页面标题与导航层级', () => {
  for (const width of [390, 700, 1280]) {
    test(`面经页在 ${width}px 只显示一个页面主标题`, async ({ page }) => {
      await openPreview(page, '/interview', width)

      const appHeader = page.locator('main > header')
      await expect(appHeader.getByText('面经库', { exact: true })).toHaveCount(0)
      await expect(page.getByRole('heading', { name: '面经库', exact: true })).toBeVisible()
      await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
    })
  }

  test('面经和 JD 页不显示复述页面用途的副标题', async ({ page }) => {
    await openPreview(page, '/interview')
    await expect(page.getByText('浏览和管理面试经验数据', { exact: true })).toHaveCount(0)

    await openPreview(page, '/jd')
    await expect(page.getByText('管理岗位描述和招聘信息', { exact: true })).toHaveCount(0)

    await openPreview(page, '/insights/overview')
    await expect(page.getByText('把岗位、题库和个人练习证据整理成下一步准备任务。', { exact: true })).toHaveCount(0)
    await expect(page.locator('main > header').getByText('总览', { exact: true })).toHaveCount(0)
  })

  test('评测结果页不重复渲染侧栏已有的面包屑层级', async ({ page }) => {
    await openPreview(page, '/admin/evals/results')

    await expect(page.getByRole('heading', { name: '评测结果', exact: true })).toBeVisible()
    await expect(page.locator('nav[aria-label="breadcrumb"]')).toHaveCount(0)
    await expect(page.locator('main > header').getByText('评测结果', { exact: true })).toHaveCount(0)
    await expect(page.getByText('先看哪些 Case 没达标，再进入评测详情查看执行表现和业务结果。', { exact: true })).toHaveCount(0)
  })

  test('题单管理页不显示练习页专用的全局题单控件', async ({ page }) => {
    await openPreview(page, '/practice/decks')

    await expect(page.getByRole('heading', { name: '题单管理', exact: true })).toBeVisible()
    await expect(page.locator('[data-testid="practice-header"]')).toHaveCount(0)
  })

  test('练习页保留全局题单控件和管理入口', async ({ page }) => {
    await openPreview(page, '/practice')

    await expect(page.locator('[data-testid="practice-header"]')).toBeVisible()
    await expect(page.locator('[data-testid="practice-deck-select"]')).toBeVisible()
  })

  test('没有内容区主标题的题库工作台仍显示顶栏当前位置', async ({ page }) => {
    await openPreview(page, '/master-bank')

    await expect(page.locator('main > header').getByText('高频题库', { exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(0)
  })

  test('移动端设置页不在工具栏重复当前栏目标题', async ({ page }) => {
    await openPreview(page, '/settings', 390)

    await expect(page.getByRole('heading', { name: '个人信息', exact: true })).toBeVisible()
    await expect(page.locator('button[aria-label="切换设置菜单"] + span')).toHaveCount(0)
    await page.getByRole('button', { name: '切换设置菜单' }).click()
    await expect(page.getByRole('button', { name: /面试偏好/ })).toBeVisible()
  })
})
