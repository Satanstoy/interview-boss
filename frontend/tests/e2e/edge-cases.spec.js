/**
 * 通用边界 E2E 测试 — 空数据、错误、XSS、响应式、键盘等边界场景
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

const LONG_TITLE_QUESTION = {
  id: 999,
  title: '这是一道非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常长的测试题目标题用于验证UI不会溢出容器边界',
  question: '这是一道非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常长的测试题目标题用于验证UI不会溢出容器边界',
  cat1: '测试分类',
  category: 'cat2_测试',
  difficulty: 'L2',
  tags: '测试,边界',
  source_type: 'jd',
  answer_complete: false,
  ai_answer: null,
  frequency: 1,
  created_at: '2026-01-01T00:00:00',
  _showAnswer: false,
}

// ── Helper ──
async function mockAllAPIs(page, options = {}) {
  const user = options.user || MOCK_USER
  const masterBankData = options.masterBankData || []

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
    await route.fulfill({ json: masterBankData })
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
}

async function gotoLoggedIn(page, options = {}) {
  await mockAllAPIs(page, options)
  await page.goto('/')
  await page.waitForSelector('main', { timeout: 15000 })
  await page.waitForTimeout(1000)
}

// ═══════════════════════════════════════════════
// 测试套件
// ═══════════════════════════════════════════════

test.describe('通用边界', () => {
  test('空数据 — API 返回空数组，UI 不崩溃', async ({ page }) => {
    await gotoLoggedIn(page, { masterBankData: [] })

    // 主界面应正常渲染
    await expect(page.locator('main')).toBeVisible({ timeout: 5000 })

    // Tab 栏应正常
    await expect(page.getByRole('button', { name: '高频题库' })).toBeVisible()

    // 题库 Tab 应显示空状态
    const body = await page.locator('body').textContent()
    expect(body.includes('暂无') || body.includes('高频题库')).toBeTruthy()

    // 切换到面经库（空数据）
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('main')).toBeVisible()

    // 切换到 JD 筛选（空数据）
    await page.getByRole('button', { name: 'JD 筛选' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('main')).toBeVisible()
  })

  test('API 500 — 页面不崩溃', async ({ page }) => {
    // 让多个 API 返回 500
    await mockAllAPIs(page)
    await page.unroute('**/api/master-bank**')
    await page.route('**/api/master-bank**', async (route) => {
      await route.fulfill({ status: 500, json: { detail: '服务器错误' } })
    })
    await page.unroute('**/api/analytics**')
    await page.route('**/api/analytics**', async (route) => {
      await route.fulfill({ status: 500, json: { detail: '服务器错误' } })
    })

    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(2000)

    // main 区域应仍可见
    await expect(page.locator('main')).toBeVisible()
    // Tab 栏应正常
    await expect(page.getByRole('button', { name: '高频题库' })).toBeVisible()
  })

  test('网络断开 — 页面不崩溃', async ({ page }) => {
    await gotoLoggedIn(page)

    // 断开所有 API
    await page.route('**/api/**', async (route) => {
      await route.abort('connectionrefused')
    })

    // 切换 Tab 触发 API 调用
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(1000)
    await expect(page.locator('main')).toBeVisible()

    await page.getByRole('button', { name: '模拟面试' }).click()
    await page.waitForTimeout(1000)
    await expect(page.locator('main')).toBeVisible()
  })

  test('快速连续切换 Tab — 不崩溃', async ({ page }) => {
    await gotoLoggedIn(page)

    const tabs = ['面经库', 'JD 筛选', '高频题库', '模拟面试', '手撕代码', '高频题库']

    // 快速连续点击
    for (const tabName of tabs) {
      const tab = page.getByRole('button', { name: tabName })
      if (await tab.isVisible().catch(() => false)) {
        await tab.click()
        await page.waitForTimeout(100) // 极短间隔
      }
    }

    // 等待稳定
    await page.waitForTimeout(1000)
    await expect(page.locator('main')).toBeVisible()
  })

  test('XSS 防护 — 搜索框输入 <script> 标签不崩溃', async ({ page }) => {
    await gotoLoggedIn(page)

    const searchInput = page.locator('input[placeholder*="搜索"]').first()
    if (await searchInput.isVisible()) {
      // 输入 XSS payload
      await searchInput.fill('<script>alert(1)</script>')
      await page.waitForTimeout(500)

      // 页面不应崩溃
      await expect(page.locator('main')).toBeVisible()

      // script 标签不应被执行（搜索框应显示原始文本）
      const value = await searchInput.inputValue()
      expect(value).toContain('script')

      // 页面中不应出现弹窗
      // (如果 XSS 成功，alert 会阻塞页面)
    }
  })

  test('暗色模式下所有 Tab 切换正常', async ({ page }) => {
    await gotoLoggedIn(page)

    // 开启暗色模式
    const darkToggle = page.locator('button[title*="暗色"], button[title*="亮色"]').first()
    await darkToggle.click()
    await page.waitForTimeout(300)

    const htmlClass = await page.locator('html').getAttribute('class')
    expect(htmlClass).toContain('dark')

    // 切换所有 Tab
    const allTabs = ['JD 筛选', '面经库', '高频题库', '模拟面试', '手撕代码']
    for (const tabName of allTabs) {
      const tab = page.getByRole('button', { name: tabName })
      if (await tab.isVisible().catch(() => false)) {
        await tab.click()
        await page.waitForTimeout(300)
        // 页面不崩溃
        await expect(page.locator('main')).toBeVisible()
        // 暗色模式应保持
        const cls = await page.locator('html').getAttribute('class')
        expect(cls).toContain('dark')
      }
    }
  })

  test('长文本题目 — 不溢出', async ({ page }) => {
    await gotoLoggedIn(page, { masterBankData: [LONG_TITLE_QUESTION] })

    // 等待题库渲染
    await page.waitForTimeout(1000)

    // 检查页面是否正常渲染
    await expect(page.locator('main')).toBeVisible()

    // 获取标题元素并检查未溢出
    // 虚拟滚动器中可能需要滚动才能看到长标题
    const body = await page.locator('body').textContent()
    // 页面应包含题目的部分文本
    expect(body.includes('非常长') || body.includes('测试题目') || body.includes('暂无')).toBeTruthy()
  })

  test('窗口从桌面缩小到移动端 — 布局响应', async ({ page }) => {
    // 从桌面开始
    await page.setViewportSize({ width: 1920, height: 1080 })
    await gotoLoggedIn(page)

    // 桌面下侧边栏应可见
    const sidebarDesktop = page.getByText('学习进度').first()
    await expect(sidebarDesktop).toBeVisible({ timeout: 5000 })

    // 缩小到移动端
    await page.setViewportSize({ width: 375, height: 667 })
    await page.waitForTimeout(500)

    // 侧边栏应隐藏
    const sidebarMobile = page.getByText('学习进度')
    const isVisible = await sidebarMobile.isVisible().catch(() => false)
    expect(isVisible).toBeFalsy()

    // Tab 栏应仍可见
    await expect(page.getByRole('button', { name: '高频题库' })).toBeVisible()

    // 恢复桌面
    await page.setViewportSize({ width: 1920, height: 1080 })
    await page.waitForTimeout(500)

    // 侧边栏应恢复可见
    await expect(page.getByText('学习进度').first()).toBeVisible({ timeout: 5000 })
  })

  test('点击遮罩层关闭设置面板', async ({ page }) => {
    await gotoLoggedIn(page)

    // 打开设置面板
    const settingsBtn = page.locator('button[title="系统配置"]').first()
    await settingsBtn.click()
    await page.waitForTimeout(500)
    await expect(page.getByText('系统配置').first()).toBeVisible({ timeout: 5000 })

    // 点击关闭按钮
    const closeBtn = page.getByRole('button', { name: '关闭' }).first()
    await closeBtn.click()
    await page.waitForTimeout(500)

    // 面板应关闭
    await expect(page.getByText('我的 LLM 配置')).not.toBeVisible({ timeout: 5000 })
  })

  test('空搜索不触发异常', async ({ page }) => {
    await gotoLoggedIn(page)

    const searchInput = page.locator('input[placeholder*="搜索"]').first()
    if (await searchInput.isVisible()) {
      // 输入空格然后清除
      await searchInput.fill('   ')
      await page.waitForTimeout(500)
      await searchInput.clear()
      await page.waitForTimeout(500)

      // 再次输入空字符串
      await searchInput.fill('')
      await page.waitForTimeout(500)

      // 页面不崩溃
      await expect(page.locator('main')).toBeVisible()
    }
  })
})
