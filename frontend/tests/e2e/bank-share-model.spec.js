/**
 * 题库共享模型 E2E — 覆盖 filter tabs、分享按钮、设置页分享默认值、导入分享选项
 * 所有 API 均 mock，不依赖真实后端；使用真实 API 响应结构
 */
import { test, expect } from '@playwright/test'

const MOCK_USER = {
  id: 999,
  username: 'e2e_tester',
  is_admin: false,
  share_default: 'private',
  current_position_id: 1,
  current_position: '前端开发工程师',
}

const PUBLIC_QUESTION = {
  id: 1,
  question: '什么是 CSRF 攻击？如何防御？',
  cat1: '安全',
  cat2: '网络安全',
  tags: '安全,CSRF',
  difficulty: 'L2-中等',
  owner_id: null,
  is_personal: false,
  frequency: 12,
}

const MY_PRIVATE_QUESTION = {
  id: 2,
  question: '我导入的私有题',
  cat1: '数据库',
  cat2: 'Redis',
  tags: 'Redis',
  difficulty: 'L1-基础',
  owner_id: 999,
  is_personal: true,
  frequency: 1,
}

async function mockAllAPIs(page, { filterRequests = [] } = {}) {
  const user = { ...MOCK_USER }

  await page.route('**/api/auth/login**', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user } })
  })
  await page.route('**/api/auth/me**', async (route) => {
    await route.fulfill({ json: user })
  })
  await page.route('**/api/auth/refresh**', async (route) => {
    await route.fulfill({ json: { token: 'mock-token-refreshed', user } })
  })
  await page.route('**/api/auth/logout**', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })
  await page.route('**/api/auth/share-default**', async (route) => {
    await route.fulfill({ json: { status: 'success', share_default: 'share' } })
  })
  await page.route('**/api/data/jd**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/data/interview**', async (route) => {
    await route.fulfill({ json: [] })
  })

  // master-bank：按 filter 参数返回不同数据（真实结构）
  await page.route('**/api/master-bank**', async (route) => {
    const url = route.request().url()
    const parsed = new URL(url)
    const filter = parsed.searchParams.get('filter') || 'all'
    filterRequests.push(filter)

    let items = [PUBLIC_QUESTION]
    if (filter === 'all' || filter === 'mine') items = [PUBLIC_QUESTION, MY_PRIVATE_QUESTION]
    if (url.includes('/pending/mine')) {
      await route.fulfill({ json: { items: [], total: 0 } })
      return
    }
    await route.fulfill({ json: { items, total: items.length, overall_total: items.length } })
  })

  await page.route('**/api/analytics**', async (route) => {
    await route.fulfill({ json: { tech_trends: {} } })
  })
  await page.route('**/api/practice/stats**', async (route) => {
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/answers/**', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })
  await page.route('**/api/profile**', async (route) => {
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/interview**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/submit-jobs/active**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/positions**', async (route) => {
    await route.fulfill({ json: [] })
  })
}

async function loginAndGoto(page, path) {
  // 免登录体验 + refresh mock（模拟已登录状态）
  await page.route('**/api/auth/refresh**', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user: MOCK_USER } })
  })
  await page.goto(path)
  await page.waitForTimeout(2000)
}

test.describe('题库共享模型', () => {
  test('题库页有全部/公共/我的 tabs，切换触发 filter 参数', async ({ page }) => {
    const filterRequests = []
    await mockAllAPIs(page, { filterRequests })
    await loginAndGoto(page, '/master-bank')

    // tabs 存在
    await expect(page.getByRole('button', { name: '全部', exact: true }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: '公共', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '我的', exact: true })).toBeVisible()

    // 切到「我的」
    await page.getByRole('button', { name: '我的', exact: true }).click()
    await page.waitForTimeout(1000)

    // 请求应带 filter=mine，且私有题可见
    expect(filterRequests).toContain('mine')
    await expect(page.getByText('我导入的私有题')).toBeVisible()
  })

  test('我的私有题显示「私有」徽标和分享按钮，点击调 share API', async ({ page }) => {
    page.on('request', r => { if (r.url().includes('/share')) console.log('DBG_SHARE_REQ:', r.url()) })
    page.on('pageerror', e => console.log('DBG_PAGEERR:', String(e).slice(0, 200)))
    const shareCalls = []
    await mockAllAPIs(page)
    await page.route('**/api/master-bank/*/share**', async (route) => {
      shareCalls.push(route.request().url())
      await route.fulfill({ json: { result: 'pending', pending_id: 300 } })
    })
    await loginAndGoto(page, '/master-bank')

    // 私有题展示；展开 accordion 后查分享按钮 + 徽标
    await expect(page.getByText('我导入的私有题')).toBeVisible()
    await page.getByRole('button', { name: /我导入的私有题/ }).click()
    await page.waitForTimeout(500)

    const shareBtn = page.getByRole('button', { name: '分享到公共题库' }).first()
    await expect(shareBtn).toBeVisible()
    await shareBtn.click()
    await page.waitForTimeout(600)
    expect(shareCalls.length).toBeGreaterThan(0)

    // 「私有」徽标可见
    await expect(page.getByText('私有', { exact: true })).toBeVisible()
  })

  test('设置页显示分享默认值开关（share/private）', async ({ page }) => {
    await mockAllAPIs(page)
    await loginAndGoto(page, '/settings')
    await page.waitForTimeout(1000)

    await expect(page.getByText('分享默认值')).toBeVisible()
    await expect(page.getByText('分享到公共题库', { exact: true })).toBeVisible()
    await expect(page.getByText('仅自己可见', { exact: true })).toBeVisible()
  })

  test('导入页分享设置对非 admin 用户可见', async ({ page }) => {
    await mockAllAPIs(page)
    await loginAndGoto(page, '/import')
    await page.waitForTimeout(1000)

    // 非 admin 也能看到分享设置
    await expect(page.getByText('分享设置')).toBeVisible()
    // 点开 Select 可见两个分享选项
    await page.locator('[data-slot="select-trigger"]').last().click()
    await page.waitForTimeout(400)
    await expect(page.getByText('分享到公共题库', { exact: true })).toBeVisible()
    await expect(page.getByText('仅自己可见', { exact: true })).toBeVisible()
  })
})
