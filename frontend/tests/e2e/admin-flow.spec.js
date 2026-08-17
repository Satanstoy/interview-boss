/**
 * 管理员流程 E2E 测试 — AdminReview.vue + 管理员专属功能
 * 所有 API 均通过 page.route() mock
 */
import { test, expect } from '@playwright/test'

const MOCK_USER = {
  id: 999,
  username: 'e2e_tester',
  is_admin: false,
  bank_mode: 'public',
  current_position_id: 1,
  current_position: '前端开发工程师',
}

const MOCK_ADMIN = {
  ...MOCK_USER,
  is_admin: true,
}

const MOCK_PENDING_QUESTIONS = {
  items: [
    {
      id: 101,
      question: '请解释 React 的 Fiber 架构',
      cat1: '前端框架',
      difficulty: 'L3',
      submitted_by_name: 'user_a',
    },
    {
      id: 102,
      question: '如何实现前端性能监控？',
      cat1: '性能优化',
      difficulty: 'L2',
      submitted_by_name: 'user_b',
    },
    {
      id: 103,
      question: '什么是微前端？有哪些方案？',
      cat1: '架构设计',
      difficulty: 'L2',
      submitted_by_name: 'user_c',
    },
  ],
}

// ── Helper ──
async function mockAllAPIs(page, user) {
  await page.route('**/api/auth/refresh', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user } })
  })
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: user })
  })
  await page.route('**/api/auth/login', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user } })
  })
  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })
  await page.route('**/api/auth/bank-mode', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })

  await page.route('**/api/master-bank**', async (route) => {
    const url = route.request().url()
    if (url.includes('/pending')) {
      await route.fulfill({ json: MOCK_PENDING_QUESTIONS })
    } else if (url.includes('/approve')) {
      await route.fulfill({ json: { status: 'success' } })
    } else if (url.includes('/reject')) {
      await route.fulfill({ json: { status: 'success' } })
    } else {
      await route.fulfill({ json: [] })
    }
  })

  await page.route('**/api/data/**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/analytics**', async (route) => {
    await route.fulfill({ json: { total_questions: 0, practiced_questions: 0, tag_distribution: [], category_distribution: [] } })
  })
  await page.route('**/api/practice/**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/answers/**', async (route) => {
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/profile**', async (route) => {
    await route.fulfill({ json: { positions: [] } })
  })
  await page.route('**/api/interview**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/chat**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/health', async (route) => {
    await route.fulfill({ json: { status: 'ok' } })
  })
  await page.route('**/api/bank-build**', async (route) => {
    await route.fulfill({ json: { status: 'idle' } })
  })
  await page.route('**/api/coding/**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/knowledge**', async (route) => {
    await route.fulfill({ json: { nodes: [], edges: [] } })
  })
  await page.route('**/api/admin**', async (route) => {
    await route.fulfill({ json: [] })
  })
}

async function gotoLoggedIn(page, user = MOCK_ADMIN) {
  await mockAllAPIs(page, user)
  await page.goto('/')
  await page.waitForSelector('main', { timeout: 15000 })
  await page.waitForTimeout(1000)
}

// ═══════════════════════════════════════════════
// 测试套件
// ═══════════════════════════════════════════════

test.describe('管理员流程', () => {
  test('管理员登录后菜单显示审核题库', async ({ page }) => {
    await gotoLoggedIn(page, MOCK_ADMIN)

    // 打开用户菜单
    const userBtn = page.locator('button').filter({ hasText: MOCK_ADMIN.username }).first()
    await expect(userBtn).toBeVisible({ timeout: 5000 })
    await userBtn.click()
    await page.waitForTimeout(300)

    // 管理员应看到"审核题库"菜单项
    await expect(page.getByText('审核题库').first()).toBeVisible({ timeout: 5000 })
  })

  test('点击审核进入审核页面', async ({ page }) => {
    await gotoLoggedIn(page, MOCK_ADMIN)

    // 打开用户菜单并点击审核
    const userBtn = page.locator('button').filter({ hasText: MOCK_ADMIN.username }).first()
    await userBtn.click()
    await page.waitForTimeout(300)

    const reviewBtn = page.getByText('审核题库').first()
    await expect(reviewBtn).toBeVisible({ timeout: 5000 })
    await reviewBtn.click()
    await page.waitForTimeout(1000)

    // AdminReview 弹窗应打开
    await expect(page.getByText('待审核题目').first()).toBeVisible({ timeout: 5000 })
  })

  test('审核列表渲染', async ({ page }) => {
    await gotoLoggedIn(page, MOCK_ADMIN)

    // 打开审核面板
    const userBtn = page.locator('button').filter({ hasText: MOCK_ADMIN.username }).first()
    await userBtn.click()
    await page.waitForTimeout(300)
    await page.getByText('审核题库').first().click()
    await page.waitForTimeout(1000)

    // 应显示待审核题目
    await expect(page.getByText('请解释 React 的 Fiber 架构').first()).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('如何实现前端性能监控？').first()).toBeVisible({ timeout: 5000 })

    // 应显示审核数量
    const body = await page.locator('body').textContent()
    expect(body.includes('3') && body.includes('待审核')).toBeTruthy()
  })

  test('通过按钮可点击', async ({ page }) => {
    await gotoLoggedIn(page, MOCK_ADMIN)

    // 打开审核面板
    const userBtn = page.locator('button').filter({ hasText: MOCK_ADMIN.username }).first()
    await userBtn.click()
    await page.waitForTimeout(300)
    await page.getByText('审核题库').first().click()
    await page.waitForTimeout(1000)

    // 通过按钮应存在
    const approveBtn = page.getByRole('button', { name: '通过' }).first()
    await expect(approveBtn).toBeVisible({ timeout: 5000 })

    // 点击通过
    await approveBtn.click()
    await page.waitForTimeout(1000)

    // 题目应从列表移除（mock 返回 success）
    // 剩余 2 条
    const body = await page.locator('body').textContent()
    expect(body.includes('2') && body.includes('待审核')).toBeTruthy()
  })

  test('拒绝按钮可点击', async ({ page }) => {
    await gotoLoggedIn(page, MOCK_ADMIN)

    // 打开审核面板
    const userBtn = page.locator('button').filter({ hasText: MOCK_ADMIN.username }).first()
    await userBtn.click()
    await page.waitForTimeout(300)
    await page.getByText('审核题库').first().click()
    await page.waitForTimeout(1000)

    // 拒绝按钮应存在
    const rejectBtn = page.getByRole('button', { name: '拒绝' }).first()
    await expect(rejectBtn).toBeVisible({ timeout: 5000 })

    // 点击拒绝
    await rejectBtn.click()
    await page.waitForTimeout(1000)

    // 题目应从列表移除
    const body = await page.locator('body').textContent()
    expect(body.includes('2') && body.includes('待审核')).toBeTruthy()
  })

  test('非管理员看不到审核入口', async ({ page }) => {
    await gotoLoggedIn(page, MOCK_USER)

    // 打开用户菜单
    const userBtn = page.locator('button').filter({ hasText: MOCK_USER.username }).first()
    await expect(userBtn).toBeVisible({ timeout: 5000 })
    await userBtn.click()
    await page.waitForTimeout(300)

    // 普通用户不应看到"审核题库"
    const reviewBtn = page.getByText('审核题库')
    await expect(reviewBtn).not.toBeVisible({ timeout: 3000 })
  })

  test('知识图谱 Tab 存在', async ({ page }) => {
    await gotoLoggedIn(page, MOCK_ADMIN)

    // 知识图谱 Tab 应存在
    const kgTab = page.getByRole('button', { name: '知识图谱' })
    await expect(kgTab).toBeVisible({ timeout: 5000 })

    // 点击后不崩溃
    await kgTab.click()
    await page.waitForTimeout(1000)
    await expect(page.locator('main')).toBeVisible()
  })

  test('测评可视化使用独立的结果图标', async ({ page }) => {
    await gotoLoggedIn(page, MOCK_ADMIN)

    const evaluationTab = page.getByRole('button', { name: '测评可视化' })
    const insightsTab = page.getByRole('button', { name: '总览' }).first()
    await expect(evaluationTab).toBeVisible({ timeout: 5000 })
    await expect(insightsTab).toBeVisible({ timeout: 5000 })

    const evaluationIcon = await evaluationTab.locator('svg').first().getAttribute('class')
    const insightsIcon = await insightsTab.locator('svg').first().getAttribute('class')
    expect(evaluationIcon).toContain('lucide-chart-no-axes-combined')
    expect(insightsIcon).toContain('lucide-layout-dashboard')
    expect(evaluationIcon).not.toContain('lucide-layout-dashboard')
  })
})
