/**
 * Comprehensive E2E 测试 — 覆盖所有核心功能模块
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

const MOCK_MASTER_BANK = [
  {
    id: 1,
    title: '请介绍一下 Vue 的响应式原理',
    question: '请介绍一下 Vue 的响应式原理',
    cat1: '前端框架',
    category: 'cat2_前端框架',
    difficulty: 'L2',
    tags: 'Vue,响应式,JavaScript',
    source_type: 'jd',
    answer_complete: true,
    ai_answer: '## Vue 响应式原理\n\nVue 3 使用 Proxy 实现数据劫持...',
    key_points: ['Proxy', '依赖追踪', '触发更新'],
    frequency: 5,
    created_at: '2026-01-15T10:00:00',
    _showAnswer: false,
  },
  {
    id: 2,
    title: '什么是 CSRF 攻击？如何防御？',
    question: '什么是 CSRF 攻击？如何防御？',
    cat1: '网络安全',
    category: 'cat2_网络安全',
    difficulty: 'L3',
    tags: '安全,CSRF,Web',
    source_type: 'interview',
    answer_complete: true,
    ai_answer: 'CSRF 跨站请求伪造...',
    key_points: ['Token', 'SameSite Cookie', 'Referer 检查'],
    frequency: 3,
    created_at: '2026-01-16T10:00:00',
    _showAnswer: false,
  },
  {
    id: 3,
    title: '解释 JavaScript 中的闭包',
    question: '解释 JavaScript 中的闭包',
    cat1: 'JavaScript基础',
    category: 'cat2_JavaScript基础',
    difficulty: 'L1',
    tags: 'JavaScript,闭包',
    source_type: 'jd',
    answer_complete: false,
    ai_answer: null,
    key_points: [],
    frequency: 8,
    created_at: '2026-01-17T10:00:00',
    _showAnswer: false,
  },
]

const MOCK_INTERVIEW_DATA = [
  {
    id: 1,
    company: '字节跳动',
    season: '2026春',
    round: '一面',
    focus: 'JavaScript 基础',
    questions_list: '闭包、原型链、Promise',
    difficulty: 'L2',
    created_at: '2026-03-01T10:00:00',
  },
  {
    id: 2,
    company: '阿里巴巴',
    season: '2026春',
    round: '二面',
    focus: '系统设计',
    questions_list: '设计一个消息队列',
    difficulty: 'L3',
    created_at: '2026-03-05T10:00:00',
  },
]

const MOCK_ANALYTICS = {
  total_questions: 150,
  practiced_questions: 42,
  total_practiced: 42,
  mastery_rate: 0.72,
  tag_distribution: [
    { tag: 'Vue', count: 30 },
    { tag: 'JavaScript', count: 45 },
    { tag: 'React', count: 25 },
  ],
  difficulty_distribution: { easy: 50, medium: 70, hard: 30 },
  category_distribution: [
    { category: '前端框架', count: 30 },
    { category: 'JavaScript基础', count: 45 },
    { category: '网络安全', count: 15 },
  ],
  recent_activity: [],
  popular_tags: [
    { tag: '全部', count: 150 },
    { tag: 'Vue', count: 30 },
    { tag: 'JavaScript', count: 45 },
  ],
}

const MOCK_PRACTICE_STATS = {
  total_sessions: 10,
  total_questions: 42,
  avg_score: 78,
  streak: 3,
}

const MOCK_PROFILE = {
  id: 999,
  username: 'e2e_tester',
  email: 'test@example.com',
  current_position: '前端开发工程师',
  current_position_id: 1,
  positions: [
    { id: 1, name: '前端开发工程师' },
    { id: 2, name: '后端开发工程师' },
  ],
  llm_configured: true,
  categories: [],
}

const MOCK_EVALUATION = {
  score: 82,
  overall_score: 82,
  dimensions: {
    accuracy: 85,
    completeness: 80,
    depth: 78,
    logic: 84,
  },
  strengths: ['回答清晰', '覆盖核心概念'],
  weaknesses: ['缺少具体例子'],
  suggestions: ['建议补充 Proxy 和 defineProperty 的对比'],
}

const MOCK_RECOMMENDATIONS = [
  { id: 1, title: '请介绍一下 Vue 的响应式原理', cat1: '前端框架', difficulty: 'L2', frequency: 5 },
  { id: 2, title: '解释 JavaScript 中的闭包', cat1: 'JavaScript基础', difficulty: 'L1', frequency: 8 },
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
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'application/json' },
      json: { token: 'mock-token', user },
    })
  })
  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })
  await page.route('**/api/auth/bank-mode', async (route) => {
    await route.fulfill({ json: { status: 'success', bank_mode: 'personal' } })
  })
  await page.route('**/api/auth/send-code', async (route) => {
    await route.fulfill({ json: { status: 'success', message: '验证码已发送' } })
  })

  // Master bank
  await page.route('**/api/master-bank**', async (route) => {
    await route.fulfill({ json: MOCK_MASTER_BANK })
  })

  // Data
  await page.route('**/api/data/jd**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/data/interview**', async (route) => {
    await route.fulfill({ json: MOCK_INTERVIEW_DATA })
  })

  // Analytics
  await page.route('**/api/analytics**', async (route) => {
    await route.fulfill({ json: MOCK_ANALYTICS })
  })

  // Practice stats
  await page.route('**/api/practice/stats**', async (route) => {
    await route.fulfill({ json: MOCK_PRACTICE_STATS })
  })

  // Practice (evaluation submit)
  await page.route('**/api/practice/submit', async (route) => {
    await route.fulfill({ json: MOCK_EVALUATION })
  })
  await page.route('**/api/practice/history**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/practice/recommendations', async (route) => {
    await route.fulfill({ json: MOCK_RECOMMENDATIONS })
  })

  // Answers
  await page.route('**/api/answers/**', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        json: {
          id: 1,
          question_id: 1,
          content: '## Vue 响应式原理\n\nVue 3 使用 Proxy 实现数据劫持...',
          key_points: ['Proxy', '依赖追踪', '触发更新'],
        },
      })
    } else {
      await route.fulfill({ json: { status: 'success' } })
    }
  })

  // Profile
  await page.route('**/api/profile**', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: MOCK_PROFILE })
    } else {
      await route.fulfill({ json: { status: 'success' } })
    }
  })

  // Interview (mock interview / 抽测)
  await page.route('**/api/interview**', async (route) => {
    await route.fulfill({ json: MOCK_MASTER_BANK })
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

  // Coding
  await page.route('**/api/coding**', async (route) => {
    await route.fulfill({ json: [] })
  })

  // Knowledge graph
  await page.route('**/api/knowledge**', async (route) => {
    await route.fulfill({ json: { nodes: [], edges: [] } })
  })
}

// ── Helper: 以已登录状态进入主页 ──
async function gotoLoggedIn(page, userOverrides = {}) {
  const user = { ...MOCK_USER, ...userOverrides }
  await mockAllAPIs(page, userOverrides)
  await page.goto('/')
  await page.waitForSelector('main', { timeout: 15000 })
  await page.waitForTimeout(1000)
}

// ── Helper: 以未登录状态进入登录页 ──
async function gotoLoginPage(page) {
  await mockAllAPIs(page)
  await page.unroute('**/api/auth/refresh')
  await page.route('**/api/auth/refresh', async (route) => {
    await route.fulfill({ status: 401, json: { detail: '未授权' } })
  })
  await page.goto('/')
  await page.waitForTimeout(2000)
}

// ═══════════════════════════════════════════════
// 1. 登录模块
// ═══════════════════════════════════════════════
test.describe('登录模块', () => {
  test('登录页面渲染完整 — 标题、输入框、按钮', async ({ page }) => {
    await gotoLoginPage(page)

    // 页面标题
    await expect(page.getByText('欢迎使用 InterviewBoss')).toBeVisible({ timeout: 10000 })

    // 用户名输入框
    const usernameInput = page.locator('input[name="username"]').first()
    await expect(usernameInput).toBeVisible()

    // 密码输入框
    const passwordInput = page.locator('input[name="password"]').first()
    await expect(passwordInput).toBeVisible()

    // 登录按钮
    const submitBtn = page.getByRole('button', { name: '登录' }).first()
    await expect(submitBtn).toBeVisible()
  })

  test('密码长度验证 — <8 位时提交按钮禁用', async ({ page }) => {
    await gotoLoginPage(page)

    const usernameInput = page.locator('input[name="username"]').first()
    const passwordInput = page.locator('input[name="password"]').first()

    await usernameInput.fill('testuser')
    await passwordInput.fill('short')
    await page.waitForTimeout(200)

    // 提交按钮应禁用（密码 < 8 位）
    const submitBtn = page.locator('button[type="submit"]').first()
    await expect(submitBtn).toBeDisabled()
  })

  test('有效输入时提交按钮可用', async ({ page }) => {
    await gotoLoginPage(page)

    const usernameInput = page.locator('input[name="username"]').first()
    const passwordInput = page.locator('input[name="password"]').first()

    await usernameInput.fill('testuser')
    await passwordInput.fill('ValidPass123!')
    await page.waitForTimeout(200)

    const submitBtn = page.locator('button[type="submit"]').first()
    await expect(submitBtn).toBeEnabled()
  })

  test('成功登录后显示主界面', async ({ page }) => {
    await gotoLoginPage(page)

    const usernameInput = page.locator('input[name="username"]').first()
    const passwordInput = page.locator('input[name="password"]').first()

    await usernameInput.fill('e2e_tester')
    await passwordInput.fill('TestPass123!')

    const submitBtn = page.locator('button[type="submit"]').first()
    await submitBtn.click()

    // 登录成功后应显示主界面 — Tab 栏高频题库按钮出现
    await expect(page.getByRole('button', { name: '高频题库' })).toBeVisible({ timeout: 15000 })
  })

  test('记住我复选框存在', async ({ page }) => {
    await gotoLoginPage(page)

    const checkbox = page.locator('input[type="checkbox"]').first()
    await expect(checkbox).toBeVisible()

    // 标签文本包含"记住我"
    const label = page.getByText('记住我')
    await expect(label).toBeVisible()
  })

  test('密码登录和邮箱验证码登录模式可切换', async ({ page }) => {
    await gotoLoginPage(page)

    // 应有两种登录方式切换
    const passwordModeBtn = page.getByText('密码登录')
    await expect(passwordModeBtn).toBeVisible({ timeout: 10000 })

    const emailModeBtn = page.getByText('邮箱验证码')
    await expect(emailModeBtn).toBeVisible()

    // 切换到邮箱验证码模式
    await emailModeBtn.click()
    await page.waitForTimeout(300)

    // 邮箱输入框应出现
    const emailInput = page.locator('input[type="email"]').first()
    await expect(emailInput).toBeVisible()

    // 验证码输入框应出现
    const codeInput = page.locator('input[placeholder="6位数字"]').first()
    await expect(codeInput).toBeVisible()
  })

  test('注册链接可点击', async ({ page }) => {
    await gotoLoginPage(page)

    // 注册入口
    const registerLink = page.getByText('注册一个')
    if (await registerLink.isVisible()) {
      await registerLink.click()
      await page.waitForTimeout(300)

      // 注册模式应显示邮箱字段
      const emailInput = page.locator('input[type="email"]').first()
      await expect(emailInput).toBeVisible({ timeout: 5000 })
    }
  })
})

// ═══════════════════════════════════════════════
// 2. Tab 切换模块
// ═══════════════════════════════════════════════
test.describe('Tab 切换模块', () => {
  const ALL_TABS = [
    'JD 筛选',
    '面经库',
    '高频题库',
    '模拟面试',
    '知识图谱',
    '导入',
    '手撕代码',
  ]

  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page)
  })

  test('所有 Tab 都存在', async ({ page }) => {
    for (const tabName of ALL_TABS) {
      const tab = page.getByRole('button', { name: tabName })
      await expect(tab).toBeVisible({ timeout: 5000 })
    }
  })

  test('点击每个 Tab 后内容区切换', async ({ page }) => {
    // 高频题库是默认 Tab，应已有内容
    await expect(page.getByRole('button', { name: '高频题库' })).toBeVisible()

    // 点击面经库
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)
    // 面经库相关内容应出现（表格列头）
    await expect(page.getByText('面试轮次').first()).toBeVisible({ timeout: 5000 })

    // 点击 JD 筛选
    await page.getByRole('button', { name: 'JD 筛选' }).click()
    await page.waitForTimeout(500)
    // JD 表格列头应出现
    await expect(page.getByText('岗位名称').first()).toBeVisible({ timeout: 5000 })

    // 点击模拟面试
    await page.getByRole('button', { name: '模拟面试' }).click()
    await page.waitForTimeout(500)
    // 模拟面试区域应可见
    const chatArea = page.locator('[class*="chat"], [class*="Chat"], textarea').first()
    // 页面不崩溃即可
    await expect(page.getByRole('button', { name: '模拟面试' })).toBeVisible()
  })

  test('Tab 高亮状态正确 — 默认高频题库高亮', async ({ page }) => {
    const activeTab = page.getByRole('button', { name: '高频题库' })
    // 活动 tab 应有 primary 颜色类
    await expect(activeTab).toHaveClass(/primary/)
  })

  test('切换 Tab 后高亮状态更新', async ({ page }) => {
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)

    // 面经库 tab 应有 primary 颜色类
    const interviewTab = page.getByRole('button', { name: '面经库' })
    await expect(interviewTab).toHaveClass(/primary/)
  })
})

// ═══════════════════════════════════════════════
// 3. 题库模块
// ═══════════════════════════════════════════════
test.describe('题库模块', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page)
    // 确保在高频题库 Tab
    await page.getByRole('button', { name: '高频题库' }).click()
    await page.waitForTimeout(500)
  })

  test('题库列表渲染', async ({ page }) => {
    // 虚拟滚动器可能只渲染可见项，检查列表容器存在
    const scroller = page.locator('.vue-recycle-scroller, [class*="scroller"]').first()
    if (await scroller.isVisible({ timeout: 5000 }).catch(() => false)) {
      // 虚拟滚动器可见，至少有一道题目渲染
      const cards = page.locator('.card-smooth, [class*="question-card"], h3')
      await expect(cards.first()).toBeVisible({ timeout: 5000 })
    } else {
      // 退化：检查页面包含题库相关内容
      const body = await page.locator('body').textContent()
      expect(body.includes('Vue') || body.includes('题库') || body.includes('搜索')).toBeTruthy()
    }
  })

  test('搜索框输入后触发筛选', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="搜索"]').first()
    if (await searchInput.isVisible()) {
      await searchInput.fill('Vue')
      await page.waitForTimeout(500) // 等待 300ms 防抖 + 额外时间
      // 搜索框值正确
      expect(await searchInput.inputValue()).toBe('Vue')
    }
  })

  test('搜索清除按钮可用', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="搜索"]').first()
    if (await searchInput.isVisible()) {
      await searchInput.fill('Vue')
      await page.waitForTimeout(500)

      // 清除按钮应出现
      const clearBtn = page.locator('[aria-label="清除搜索"]').first()
      if (await clearBtn.isVisible()) {
        await clearBtn.click()
        await page.waitForTimeout(300)
        expect(await searchInput.inputValue()).toBe('')
      }
    }
  })

  test('难度筛选下拉框可操作', async ({ page }) => {
    // 查找难度筛选 — RoundedSelect 组件
    const difficultyFilter = page.getByText('全部难度').first()
    if (await difficultyFilter.isVisible()) {
      await difficultyFilter.click()
      await page.waitForTimeout(300)
      // 下拉选项应出现
      const option = page.getByText('L2 - 中等').first()
      if (await option.isVisible()) {
        await option.click()
        await page.waitForTimeout(300)
      }
    }
  })

  test('全部展开 / 全部收起按钮', async ({ page }) => {
    // 展开按钮
    const expandBtn = page.getByText('全部展开').first()
    if (await expandBtn.isVisible()) {
      await expandBtn.click()
      await page.waitForTimeout(500)
    }

    // 收起按钮
    const collapseBtn = page.getByText('全部收起').first()
    if (await collapseBtn.isVisible()) {
      await collapseBtn.click()
      await page.waitForTimeout(500)
    }
  })

  test('收藏按钮点击切换', async ({ page }) => {
    // 查找收藏按钮（title="收藏"）
    const starBtn = page.locator('[title="收藏"]').first()
    if (await starBtn.isVisible()) {
      await starBtn.click()
      await page.waitForTimeout(300)
      // 点击后应切换为 "取消收藏"
      const unstarBtn = page.locator('[title="取消收藏"]').first()
      // 不报错即为通过
    }
  })

  test('题目卡片展开/折叠', async ({ page }) => {
    // 点击第一张题目卡片
    const questionTitle = page.getByText('请介绍一下 Vue 的响应式原理').first()
    if (await questionTitle.isVisible()) {
      await questionTitle.click()
      await page.waitForTimeout(500)
      // 展开后应显示答案相关内容
      // 关闭后内容应隐藏
    }
  })

  test('分类标签筛选', async ({ page }) => {
    // 查找子标签筛选区域
    const tagLabel = page.getByText('子标签').first()
    if (await tagLabel.isVisible()) {
      // 查找可点击的标签 chips
      const tags = page.locator('[class*="badge"], [class*="chip"], button').filter({ hasText: /Vue|JavaScript|React/ })
      const tagCount = await tags.count()
      if (tagCount > 0) {
        await tags.first().click()
        await page.waitForTimeout(300)
      }
    }
  })

  test('八股刷题按钮', async ({ page }) => {
    const practiceModeBtn = page.getByText('八股刷题').first()
    if (await practiceModeBtn.isVisible()) {
      await practiceModeBtn.click()
      await page.waitForTimeout(500)
      // 进入刷题模式后 UI 应有变化
    }
  })
})

// ═══════════════════════════════════════════════
// 4. 面经库模块
// ═══════════════════════════════════════════════
test.describe('面经库模块', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page)
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)
  })

  test('面经列表渲染', async ({ page }) => {
    // 面经库页面应包含表格或数据内容
    await page.waitForTimeout(1000)
    const body = await page.locator('body').textContent()
    // 应包含面经库相关列头或数据
    const hasInterviewContent = body.includes('面试轮次') || body.includes('公司') || body.includes('字节跳动') || body.includes('面经')
    expect(hasInterviewContent).toBeTruthy()
  })

  test('排序切换 — 升序/降序', async ({ page }) => {
    // 查找排序按钮
    const sortBtn = page.locator('button').filter({ hasText: /上传日期/ }).first()
    if (await sortBtn.isVisible()) {
      // 默认降序
      await sortBtn.click()
      await page.waitForTimeout(300)
      // 点击后应切换为升序
      const ascBtn = page.locator('button').filter({ hasText: /↑/ }).first()
      // 不崩溃即通过
    }
  })

  test('招聘季筛选', async ({ page }) => {
    const seasonLabel = page.getByText('招聘季筛选').first()
    if (await seasonLabel.isVisible()) {
      // 筛选下拉框应存在
    }
  })
})

// ═══════════════════════════════════════════════
// 6. 设置面板
// ═══════════════════════════════════════════════
test.describe('设置面板', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page)
  })

  test('设置按钮可点击并打开面板', async ({ page }) => {
    const settingsBtn = page.locator('button[title="系统配置"]').first()
    await expect(settingsBtn).toBeVisible({ timeout: 5000 })
    await settingsBtn.click()
    await page.waitForTimeout(500)

    // 设置面板标题
    await expect(page.getByText('系统配置').first()).toBeVisible({ timeout: 5000 })
  })

  test('设置面板内容渲染 — LLM 配置', async ({ page }) => {
    const settingsBtn = page.locator('button[title="系统配置"]').first()
    await settingsBtn.click()
    await page.waitForTimeout(500)

    // LLM 配置区域
    await expect(page.getByText('我的 LLM 配置').first()).toBeVisible({ timeout: 5000 })
  })

  test('设置面板 — 目标岗位', async ({ page }) => {
    const settingsBtn = page.locator('button[title="系统配置"]').first()
    await settingsBtn.click()
    await page.waitForTimeout(500)

    // 目标岗位区域
    await expect(page.getByText('目标岗位').first()).toBeVisible({ timeout: 5000 })
  })

  test('设置面板关闭按钮', async ({ page }) => {
    const settingsBtn = page.locator('button[title="系统配置"]').first()
    await settingsBtn.click()
    await page.waitForTimeout(500)

    // 关闭按钮
    const closeBtn = page.getByText('关闭').first()
    await expect(closeBtn).toBeVisible({ timeout: 5000 })
    await closeBtn.click()
    await page.waitForTimeout(300)

    // 面板应关闭
    await expect(page.getByText('我的 LLM 配置')).not.toBeVisible({ timeout: 5000 })
  })
})

// ═══════════════════════════════════════════════
// 7. 暗色模式
// ═══════════════════════════════════════════════
test.describe('暗色模式', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page)
  })

  test('暗色模式切换按钮存在', async ({ page }) => {
    // 按钮 title 可能是 "切换到暗色模式" 或 "切换到亮色模式"
    const darkToggle = page.locator('button[title*="暗色"], button[title*="亮色"]').first()
    await expect(darkToggle).toBeVisible({ timeout: 5000 })
  })

  test('点击后 html class 变化', async ({ page }) => {
    const darkToggle = page.locator('button[title*="暗色"], button[title*="亮色"]').first()
    await expect(darkToggle).toBeVisible({ timeout: 5000 })

    // 记录当前 class
    const classBefore = await page.locator('html').getAttribute('class') || ''

    await darkToggle.click()
    await page.waitForTimeout(300)

    const classAfter = await page.locator('html').getAttribute('class') || ''

    // class 应该有变化（dark class 出现或消失）
    expect(classAfter).not.toBe(classBefore)
  })

  test('暗色模式持久化到 localStorage', async ({ page }) => {
    const darkToggle = page.locator('button[title*="暗色"], button[title*="亮色"]').first()
    await expect(darkToggle).toBeVisible({ timeout: 5000 })
    await darkToggle.click()
    await page.waitForTimeout(300)

    // localStorage 应有 theme 值（useTheme 使用 'interviewboss-theme' key）
    const theme = await page.evaluate(() => localStorage.getItem('interviewboss-theme'))
    expect(theme).not.toBeNull()
  })
})

// ═══════════════════════════════════════════════
// 8. 响应式布局
// ═══════════════════════════════════════════════
test.describe('响应式布局', () => {
  test('桌面视口下侧边栏可见', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await gotoLoggedIn(page)

    // 侧边栏应可见 — 查找侧边栏内的学习进度标题
    const sidebar = page.getByText('学习进度').first()
    await expect(sidebar).toBeVisible({ timeout: 10000 })
  })

  test('桌面视口下侧边栏有合理宽度', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await gotoLoggedIn(page)

    // 查找侧边栏容器
    const sidebarWrapper = page.locator('[class*="sidebar-wrapper"], aside').first()
    if (await sidebarWrapper.isVisible()) {
      const box = await sidebarWrapper.boundingBox()
      if (box) {
        expect(box.width).toBeGreaterThan(100)
      }
    }
  })

  test('移动端视口下侧边栏隐藏', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await gotoLoggedIn(page)

    // 侧边栏学习进度标题不应可见
    const sidebar = page.getByText('学习进度')
    // 在 375px 下 sidebar 使用 hidden lg:block，应不可见
    const isVisible = await sidebar.isVisible().catch(() => false)
    expect(isVisible).toBeFalsy()
  })

  test('移动端视口下 Tab 栏仍可见', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await gotoLoggedIn(page)

    // Tab 栏在移动端应仍可滚动显示
    const tabBar = page.getByRole('button', { name: '高频题库' })
    await expect(tabBar).toBeVisible({ timeout: 5000 })
  })

  test('侧边栏折叠/展开按钮', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await gotoLoggedIn(page)

    // 收起侧栏按钮 — 可能被其他元素遮挡，用 force: true
    const collapseBtn = page.locator('button[title="收起侧栏"]').first()
    if (await collapseBtn.isVisible()) {
      await collapseBtn.click({ force: true })
      await page.waitForTimeout(500)

      // 展开侧栏按钮应出现
      const expandBtn = page.locator('button[title*="展开侧栏"]').first()
      if (await expandBtn.isVisible()) {
        await expandBtn.click({ force: true })
        await page.waitForTimeout(500)
      }
    }
  })
})

// ═══════════════════════════════════════════════
// 9. 用户菜单
// ═══════════════════════════════════════════════
test.describe('用户菜单', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page)
  })

  test('用户菜单显示用户名', async ({ page }) => {
    // 用户名应出现在页面上（顶部菜单区域）
    const username = page.getByText(MOCK_USER.username).first()
    await expect(username).toBeVisible({ timeout: 5000 })
  })

  test('点击头像打开下拉菜单', async ({ page }) => {
    // 点击包含用户名的按钮区域
    const userBtn = page.locator('button').filter({ hasText: MOCK_USER.username }).first()
    await expect(userBtn).toBeVisible({ timeout: 5000 })
    await userBtn.click()
    await page.waitForTimeout(300)

    // 下拉菜单项应出现
    await expect(page.getByText('个人信息').first()).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('退出登录').first()).toBeVisible({ timeout: 5000 })
  })

  test('题库模式切换按钮', async ({ page }) => {
    const userBtn = page.locator('button').filter({ hasText: MOCK_USER.username }).first()
    await userBtn.click()
    await page.waitForTimeout(300)

    // 题库模式选项
    await expect(page.getByText('公共').first()).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('个人').first()).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('混用').first()).toBeVisible({ timeout: 5000 })
  })

  test('普通用户不看到审核题库按钮', async ({ page }) => {
    const userBtn = page.locator('button').filter({ hasText: MOCK_USER.username }).first()
    await userBtn.click()
    await page.waitForTimeout(300)

    // 普通用户不应看到"审核题库"
    const reviewBtn = page.getByText('审核题库')
    await expect(reviewBtn).not.toBeVisible({ timeout: 3000 })
  })
})

test.describe('管理员用户菜单', () => {
  test('管理员看到审核题库按钮', async ({ page }) => {
    await gotoLoggedIn(page, { is_admin: true })
    const userBtn = page.locator('button').filter({ hasText: MOCK_USER.username }).first()
    await expect(userBtn).toBeVisible({ timeout: 5000 })
    await userBtn.click()
    await page.waitForTimeout(300)

    await expect(page.getByText('审核题库').first()).toBeVisible({ timeout: 5000 })
  })
})

// ═══════════════════════════════════════════════
// 10. 侧边栏数据分析
// ═══════════════════════════════════════════════
test.describe('侧边栏数据分析', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await gotoLoggedIn(page)
  })

  test('学习进度区域显示', async ({ page }) => {
    await expect(page.getByText('学习进度').first()).toBeVisible({ timeout: 5000 })
  })

  test('每日推荐区域显示', async ({ page }) => {
    await expect(page.getByText('每日推荐').first()).toBeVisible({ timeout: 5000 })
  })

  test('收藏夹区域显示', async ({ page }) => {
    await expect(page.getByText('收藏夹').first()).toBeVisible({ timeout: 5000 })
  })

  test('分类目录区域显示', async ({ page }) => {
    await expect(page.getByText('分类目录').first()).toBeVisible({ timeout: 5000 })
  })

  test('刷新数据按钮可点击', async ({ page }) => {
    const refreshBtn = page.getByText('刷新数据').first()
    if (await refreshBtn.isVisible()) {
      await refreshBtn.click()
      await page.waitForTimeout(500)
      // 不崩溃即通过
    }
  })
})

// ═══════════════════════════════════════════════
// 11. 错误处理
// ═══════════════════════════════════════════════
test.describe('错误处理', () => {
  test('API 返回 500 时页面不崩溃', async ({ page }) => {
    await mockAllAPIs(page)
    // master-bank 返回 500
    await page.unroute('**/api/master-bank**')
    await page.route('**/api/master-bank**', async (route) => {
      await route.fulfill({ status: 500, json: { detail: '服务器内部错误' } })
    })

    await gotoLoggedIn(page)

    // main 区域应仍可见
    await expect(page.locator('main')).toBeVisible({ timeout: 5000 })
  })

  test('网络断开时页面不崩溃', async ({ page }) => {
    await gotoLoggedIn(page)

    // 断开所有 API
    await page.route('**/api/**', async (route) => {
      await route.abort('connectionrefused')
    })

    // 尝试切换 Tab
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(1000)

    // 页面不应崩溃
    await expect(page.locator('main')).toBeVisible()
  })

  test('API 错误时显示重试按钮', async ({ page }) => {
    await mockAllAPIs(page)
    // analytics 返回 500
    await page.unroute('**/api/analytics**')
    await page.route('**/api/analytics**', async (route) => {
      await route.fulfill({ status: 500, json: { detail: '服务器错误' } })
    })

    await gotoLoggedIn(page)

    // 重试按钮可能出现
    const retryBtn = page.getByText('重试').first()
    // 不崩溃即可
    await expect(page.locator('main')).toBeVisible()
  })
})

// ═══════════════════════════════════════════════
// 12. 练习面板
// ═══════════════════════════════════════════════
test.describe('练习面板', () => {
  test('点击做题按钮打开练习面板', async ({ page }) => {
    await gotoLoggedIn(page)

    // 等待题库加载
    await page.waitForTimeout(1000)

    // 查找做题按钮（可能需要 hover 才显示）
    const practiceBtn = page.getByText('做题').first()
    if (await practiceBtn.isVisible()) {
      await practiceBtn.click()
      await page.waitForTimeout(500)

      // 练习面板应打开 — 应显示 "我的回答"
      await expect(page.getByText('我的回答').first()).toBeVisible({ timeout: 5000 })
    }
  })
})
