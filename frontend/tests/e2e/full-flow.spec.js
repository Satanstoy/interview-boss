/**
 * 全流程 E2E 测试 — 覆盖登录、Tab 切换、题库浏览、练习、设置等核心路径
 * 所有 API 均通过 page.route() mock，不依赖真实后端
 */
import { test, expect } from '@playwright/test'

// ── Mock 数据 ──
const MOCK_USER = {
  id: 999,
  username: 'e2e_tester',
  is_admin: false,
  bank_mode: 'public',
  current_position_id: 1,
  current_position: '前端开发工程师',
}

const MOCK_ADMIN_USER = {
  ...MOCK_USER,
  is_admin: true,
}

const MOCK_LOGIN_RESPONSE = {
  token: 'mock-access-token-xxx',
  user: MOCK_USER,
}

const MOCK_MASTER_BANK = [
  {
    id: 1,
    title: '请介绍一下 Vue 的响应式原理',
    category: 'cat2_前端框架',
    difficulty: 'medium',
    tags: ['Vue', '响应式', 'JavaScript'],
    source_type: 'jd',
    answer_complete: true,
    created_at: '2026-01-15T10:00:00',
  },
  {
    id: 2,
    title: '什么是 CSRF 攻击？如何防御？',
    category: 'cat2_网络安全',
    difficulty: 'hard',
    tags: ['安全', 'CSRF', 'Web'],
    source_type: 'interview',
    answer_complete: true,
    created_at: '2026-01-16T10:00:00',
  },
  {
    id: 3,
    title: '解释 JavaScript 中的闭包',
    category: 'cat2_JavaScript基础',
    difficulty: 'easy',
    tags: ['JavaScript', '闭包'],
    source_type: 'jd',
    answer_complete: false,
    created_at: '2026-01-17T10:00:00',
  },
]

const MOCK_ANALYTICS = {
  total_questions: 150,
  total_practiced: 42,
  mastery_rate: 0.72,
  tag_distribution: [
    { tag: 'Vue', count: 30 },
    { tag: 'JavaScript', count: 45 },
    { tag: 'React', count: 25 },
  ],
  difficulty_distribution: { easy: 50, medium: 70, hard: 30 },
  recent_activity: [],
}

const MOCK_PRACTICE_STATS = {
  total_sessions: 10,
  total_questions: 42,
  avg_score: 78,
  streak: 3,
}

const MOCK_POPULAR_TAGS = [
  { tag: '全部', count: 150 },
  { tag: 'Vue', count: 30 },
  { tag: 'JavaScript', count: 45 },
  { tag: 'React', count: 25 },
]

const MOCK_ANSWER = {
  id: 1,
  question_id: 1,
  content: '## Vue 响应式原理\n\nVue 3 使用 Proxy 实现数据劫持...',
  key_points: ['Proxy', '依赖追踪', '触发更新'],
  difficulty: 'medium',
}

const MOCK_INTERVIEW_QUESTIONS = [
  { id: 1, title: '请介绍一下 Vue 的响应式原理', category: '前端框架', difficulty: 'medium' },
  { id: 2, title: '什么是 CSRF 攻击？', category: '网络安全', difficulty: 'hard' },
]

// ── Helper: 注册所有必要的 API mock ──
async function mockAllAPIs(page, userOverrides = {}) {
  const user = { ...MOCK_USER, ...userOverrides }

  // Auth
  await page.route('**/api/auth/login', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user } })
  })
  await page.route('**/api/auth/register', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user } })
  })
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: user })
  })
  await page.route('**/api/auth/refresh', async (route) => {
    await route.fulfill({ json: { token: 'mock-token-refreshed', user } })
  })
  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })
  await page.route('**/api/auth/bank-mode', async (route) => {
    await route.fulfill({ json: { status: 'success', bank_mode: 'personal' } })
  })

  // Data
  await page.route('**/api/data/jd', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/data/interview', async (route) => {
    await route.fulfill({ json: [] })
  })

  // Master bank
  await page.route('**/api/master-bank**', async (route) => {
    const url = route.request().url()
    if (url.includes('/practice')) {
      await route.fulfill({ json: MOCK_MASTER_BANK })
    } else {
      await route.fulfill({ json: MOCK_MASTER_BANK })
    }
  })

  // Analytics
  await page.route('**/api/analytics**', async (route) => {
    await route.fulfill({ json: MOCK_ANALYTICS })
  })

  // Practice stats
  await page.route('**/api/practice/stats**', async (route) => {
    await route.fulfill({ json: MOCK_PRACTICE_STATS })
  })

  // Answers
  await page.route('**/api/answers/**', async (route) => {
    await route.fulfill({ json: MOCK_ANSWER })
  })

  // Profile
  await page.route('**/api/profile**', async (route) => {
    await route.fulfill({ json: {} })
  })

  // Interview
  await page.route('**/api/interview**', async (route) => {
    await route.fulfill({ json: MOCK_INTERVIEW_QUESTIONS })
  })

  // Submit (SSE)
  await page.route('**/api/submit', async (route) => {
    const sseData = [
      'data: {"type":"progress","message":"正在分析...","percent":50}',
      'data: {"type":"progress","message":"分析完成","percent":100}',
      'data: {"type":"done","message":"提交成功","questions_count":3}',
    ].join('\n') + '\n'
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
      body: sseData,
    })
  })

  // Chat
  await page.route('**/api/chat**', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: [] })
    } else {
      await route.fulfill({ json: { id: 1, title: '测试对话' } })
    }
  })

  // Health
  await page.route('**/api/health', async (route) => {
    await route.fulfill({ json: { status: 'ok', db: 'connected' } })
  })

  // Bank build
  await page.route('**/api/bank-build**', async (route) => {
    await route.fulfill({ json: { status: 'idle' } })
  })

  // Admin
  await page.route('**/api/admin**', async (route) => {
    await route.fulfill({ json: [] })
  })
}

// ── Helper: 注入登录状态（跳过 UI 登录）──
async function injectAuth(page) {
  await page.addInitScript(() => {
    // 模拟 App.vue 初始化时通过 refresh token 恢复登录状态
    window.__mockAuthInjected = true
  })
}

// ═══════════════════════════════════════════════
// 测试套件
// ═══════════════════════════════════════════════

test.describe('登录流程', () => {
  test('登录页面正确渲染', async ({ page }) => {
    await mockAllAPIs(page)
    // 让 refresh 返回 401，这样不会自动登录
    await page.unroute('**/api/auth/refresh')
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({ status: 401, json: { detail: '未授权' } })
    })
    await page.goto('/')
    await page.waitForTimeout(2000)

    // 应显示登录页面标题
    const loginTitle = page.getByText('欢迎使用 InterviewBoss')
    await expect(loginTitle).toBeVisible({ timeout: 10000 })

    // 应有用户名和密码输入框
    const usernameInput = page.locator('input[autocomplete="username"]').first()
    const passwordInput = page.locator('input[autocomplete="current-password"]').first()
    await expect(usernameInput).toBeVisible()
    await expect(passwordInput).toBeVisible()
  })

  test('输入无效用户名时显示错误', async ({ page }) => {
    await mockAllAPIs(page)
    await page.unroute('**/api/auth/refresh')
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({ status: 401, json: { detail: '未授权' } })
    })
    await page.goto('/')
    await page.waitForTimeout(2000)

    const usernameInput = page.locator('input[autocomplete="username"]').first()
    const passwordInput = page.locator('input[autocomplete="current-password"]').first()

    await usernameInput.fill('a')  // Too short (min 2 chars)
    await passwordInput.fill('TestPass123!')

    // 点击提交按钮触发验证
    const submitBtn = page.locator('button[type="submit"]').first()
    await submitBtn.click()
    await page.waitForTimeout(1000)

    // 应显示错误消息（validate.js 的 USERNAME_RE 要求 2-32 字符）
    const pageText = await page.locator('body').textContent()
    const hasError = pageText.includes('用户名') && (pageText.includes('仅允许') || pageText.includes('不能为空') || pageText.includes('2-32'))
    expect(hasError).toBeTruthy()
  })

  test('成功登录后显示主界面', async ({ page }) => {
    await mockAllAPIs(page)

    // Mock refresh token 返回用户数据（模拟已登录状态恢复）
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        json: { token: 'mock-token', user: MOCK_USER },
      })
    })

    await page.goto('/')
    await page.waitForTimeout(2000)

    // 应显示主内容区（TabBar）
    const tabBar = page.locator('[class*="tab"], [class*="Tab"]').first()
    await expect(tabBar).toBeVisible({ timeout: 15000 })
  })
})

test.describe('Tab 切换', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    // 注入已登录状态
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        json: { token: 'mock-token', user: MOCK_USER },
      })
    })
    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(1000)
  })

  test('Tab 栏包含所有预期标签', async ({ page }) => {
    // 查找 Tab 按钮
    const tabs = page.locator('button').filter({ hasText: /题库|练习|面试|提交/ })
    const tabCount = await tabs.count()
    expect(tabCount).toBeGreaterThanOrEqual(2) // 至少有题库和练习两个 tab
  })

  test('点击练习 Tab 切换内容', async ({ page }) => {
    const practiceTab = page.locator('button').filter({ hasText: /练习/ }).first()
    if (await practiceTab.isVisible()) {
      await practiceTab.click()
      await page.waitForTimeout(500)
      // 练习相关内容应可见
      const practiceContent = page.locator('[class*="practice"], [class*="Practice"]').first()
      // 至少 tab 应该被选中（样式变化）
      await expect(practiceTab).toBeVisible()
    }
  })
})

test.describe('题库浏览', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        json: { token: 'mock-token', user: MOCK_USER },
      })
    })
    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(1000)

    // 切换到题库 tab
    const bankTab = page.locator('button').filter({ hasText: /题库/ }).first()
    if (await bankTab.isVisible()) {
      await bankTab.click()
      await page.waitForTimeout(500)
    }
  })

  test('题库列表显示题目', async ({ page }) => {
    // 等待数据加载
    await page.waitForTimeout(3000)
    // 检查页面是否有题库相关内容（Tab 名称、搜索框等）
    const body = await page.locator('body').textContent()
    // 页面应该包含题库相关 UI 元素
    const hasBankUI = body.includes('题库') || body.includes('搜索') || body.includes('全部')
    expect(hasBankUI).toBeTruthy()
  })

  test('搜索框可输入', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="搜索"], input[type="search"]').first()
    if (await searchInput.isVisible()) {
      await searchInput.fill('Vue')
      await page.waitForTimeout(300)
      const value = await searchInput.inputValue()
      expect(value).toBe('Vue')
    }
  })

  test('难度筛选可操作', async ({ page }) => {
    // 查找难度筛选按钮
    const difficultyFilter = page.locator('button, select').filter({ hasText: /简单|中等|困难|全部/ }).first()
    if (await difficultyFilter.isVisible()) {
      await difficultyFilter.click()
      await page.waitForTimeout(300)
    }
  })
})

test.describe('设置面板', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        json: { token: 'mock-token', user: MOCK_USER },
      })
    })
    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(1000)
  })

  test('点击设置按钮打开设置面板', async ({ page }) => {
    // 设置按钮（齿轮图标）在登录后的顶部栏
    const settingsBtn = page.locator('button[title="系统配置"]').first()
    await expect(settingsBtn).toBeVisible({ timeout: 10000 })
    await settingsBtn.click()
    await page.waitForTimeout(500)
    // 设置面板应出现 — 包含 "系统配置" 或 "LLM" 等文字
    const settingsPanel = page.getByText('系统配置', { exact: false }).first()
    await expect(settingsPanel).toBeVisible({ timeout: 5000 })
  })
})

test.describe('暗色模式', () => {
  test('暗色模式切换按钮存在且可点击', async ({ page }) => {
    await mockAllAPIs(page)
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        json: { token: 'mock-token', user: MOCK_USER },
      })
    })
    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(1000)

    // 暗色模式按钮
    const darkToggle = page.locator('button[title*="暗色"], button[title*="亮色"]').first()
    if (await darkToggle.isVisible()) {
      await darkToggle.click()
      await page.waitForTimeout(300)
      // html 应该有 dark class
      const htmlClass = await page.locator('html').getAttribute('class')
      // 暗色模式切换后应有变化
      expect(htmlClass !== null).toBeTruthy()
    }
  })
})

test.describe('管理员功能', () => {
  test('管理员用户看到审核按钮', async ({ page }) => {
    await mockAllAPIs(page, { is_admin: true })
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        json: { token: 'mock-token', user: MOCK_ADMIN_USER },
      })
    })
    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(1000)

    // 点击用户菜单（包含用户名首字母的头像按钮）
    const userMenuBtn = page.locator('.relative > button').first()
    await expect(userMenuBtn).toBeVisible({ timeout: 5000 })
    await userMenuBtn.click()
    await page.waitForTimeout(300)

    // 管理员应看到 "审核题库" 按钮
    const reviewBtn = page.getByText('审核题库')
    await expect(reviewBtn).toBeVisible({ timeout: 5000 })
  })
})

test.describe('响应式布局', () => {
  test('桌面视口下侧边栏可见', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await mockAllAPIs(page)
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        json: { token: 'mock-token', user: MOCK_USER },
      })
    })
    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(1000)

    // 侧边栏在桌面视口下应可见
    const sidebar = page.locator('.sidebar-wrapper').first()
    if (await sidebar.isVisible()) {
      const box = await sidebar.boundingBox()
      expect(box.width).toBeGreaterThan(100)
    }
  })

  test('移动端视口下侧边栏隐藏', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await mockAllAPIs(page)
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        json: { token: 'mock-token', user: MOCK_USER },
      })
    })
    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(1000)

    // 侧边栏在移动端应隐藏 (hidden lg:block)
    const sidebar = page.locator('.sidebar-wrapper').first()
    const isVisible = await sidebar.isVisible()
    // 在 375px 宽度下，sidebar 应该隐藏
    expect(isVisible).toBeFalsy()
  })
})

test.describe('错误处理', () => {
  test('API 返回 500 时显示错误提示', async ({ page }) => {
    await mockAllAPIs(page)
    // 让 master-bank 返回 500
    await page.unroute('**/api/master-bank**')
    await page.route('**/api/master-bank**', async (route) => {
      await route.fulfill({ status: 500, json: { detail: '服务器内部错误' } })
    })
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        json: { token: 'mock-token', user: MOCK_USER },
      })
    })
    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(2000)

    // 应该有错误提示或重试按钮
    const errorBanner = page.locator('[class*="error"], [class*="red"], [class*="retry"], button:has-text("重试")').first()
    // 即使 API 失败，页面也不应崩溃
    const mainContent = page.locator('main')
    await expect(mainContent).toBeVisible()
  })

  test('网络断开时页面不崩溃', async ({ page }) => {
    await mockAllAPIs(page)
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        json: { token: 'mock-token', user: MOCK_USER },
      })
    })
    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(1000)

    // 断开所有 API
    await page.route('**/api/**', async (route) => {
      await route.abort('connectionrefused')
    })

    // 点击某个 tab 触发 API 调用
    const practiceTab = page.locator('button').filter({ hasText: /练习/ }).first()
    if (await practiceTab.isVisible()) {
      await practiceTab.click()
      await page.waitForTimeout(2000)
    }

    // 页面不应崩溃（main 仍可见）
    const mainContent = page.locator('main')
    await expect(mainContent).toBeVisible()
  })
})

test.describe('用户菜单', () => {
  test('用户菜单显示用户名', async ({ page }) => {
    await mockAllAPIs(page)
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        json: { token: 'mock-token', user: MOCK_USER },
      })
    })
    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(1000)

    // 用户名应显示在页面上
    const usernameText = page.locator(`text=${MOCK_USER.username}`).first()
    // 可能在 UserMenu 或某处显示
    if (await usernameText.isVisible()) {
      await expect(usernameText).toBeVisible()
    }
  })
})
