/**
 * 今日复习（due 题单）E2E 测试 — 覆盖三个行为：
 * 1. /practice 默认进入今日复习题单 + 招聘状态行（距里程碑 N 天 / 阶段徽标 / 无偏好时隐藏）
 * 2. 复习（记得了）后当前卡从今日复习队列移除，索引补偿保证不跳卡
 * 3. 今日复习队列为空时展示「今日复习已经完成」完成态
 * 所有 API 均通过 page.route() mock，不依赖真实后端
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

const MOCK_DECKS = {
  algorithm: 'sm2_lite',
  items: [
    { key: 'due', name: '今日复习', description: '已到期和今日新题', kind: 'due', total: 3, reviewed: 1, due: 2, progress: 33 },
    { key: 'all', name: '全部题', description: '按复习状态和面试频率安排顺序', total: 3, reviewed: 0, due: 3, progress: 0 },
  ],
}

const DUE_QUESTION_SEEDS = [
  {
    id: 101,
    question: 'Q1 什么是 Vue 的响应式原理？',
    ai_answer: '## 参考答案\n\nVue 3 使用 Proxy 实现数据劫持，通过 track 收集依赖、trigger 派发更新。',
    cat1: '前端框架',
    category: 'cat2_前端框架',
    difficulty: 'L2',
    tags: 'Vue,响应式,JavaScript',
    frequency: 5,
    proficiency: 3,
    review_count: 2,
    attempt_count: 2,
    has_been_practiced: true,
    next_review_at: '2026-08-04 09:00:00',
    is_due: true,
    is_starred: false,
  },
  {
    id: 102,
    question: 'Q2 什么是 JavaScript 事件循环？',
    ai_answer: '## 参考答案\n\n事件循环是 JS 的异步调度机制，宏任务、微任务按顺序执行。',
    cat1: 'JavaScript基础',
    category: 'cat2_JavaScript基础',
    difficulty: 'L1',
    tags: 'JavaScript,事件循环',
    frequency: 8,
    proficiency: 1,
    review_count: 1,
    attempt_count: 1,
    has_been_practiced: true,
    next_review_at: '2026-08-03 09:00:00',
    is_due: true,
    is_starred: true,
  },
  {
    id: 103,
    question: 'Q3 浏览器重排与重绘有什么区别？',
    ai_answer: '## 参考答案\n\n重排影响布局，重绘只影响像素，两者都尽量合并和避免。',
    cat1: '浏览器原理',
    category: 'cat2_浏览器原理',
    difficulty: 'L3',
    tags: '浏览器,重排,重绘',
    frequency: 3,
    proficiency: 0,
    review_count: 0,
    attempt_count: 0,
    has_been_practiced: false,
    next_review_at: null,
    is_due: true,
    is_starred: false,
  },
  {
    id: 104,
    question: 'Q4 什么是闭包？',
    ai_answer: '## 参考答案\n\n闭包是函数与其词法作用域的组合，常用于数据私有化。',
    cat1: 'JavaScript基础',
    category: 'cat2_JavaScript基础',
    difficulty: 'L1',
    tags: 'JavaScript,闭包',
    frequency: 6,
    proficiency: 4,
    review_count: 3,
    attempt_count: 3,
    has_been_practiced: true,
    next_review_at: '2026-08-05 09:00:00',
    is_due: true,
    is_starred: false,
  },
]

const AUTUMN_RECRUITMENT = {
  graduation_year: 2027,
  batch: 'autumn',
  daily_capacity: 30,
  pace: 'standard',
  windows: [
    { name: '暑期实习', peak: '2026-03-15', weight: 0.67 },
    { name: '提前批', peak: '2026-08-15', weight: 0.5 },
    { name: '秋招正式批', peak: '2026-10-15', weight: 1.0 },
    { name: '春招主批', peak: '2027-04-15', weight: 0.83 },
  ],
  urgency: 0.43,
  current_window: { name: '提前批', peak: '2026-08-15', weight: 0.5 },
  next_window: { name: '秋招正式批', peak: '2026-10-15', days_left: 71 },
}

const EMPTY_RECRUITMENT = {
  graduation_year: null,
  batch: '',
  daily_capacity: 30,
  pace: 'standard',
  windows: [],
  urgency: 0.2,
  current_window: null,
  next_window: null,
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
    ai_answer: '## Vue 响应式原理\n\nVue 3 使用 Proxy 实现数据劫持。',
    key_points: ['Proxy', '依赖追踪'],
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
    key_points: ['Token', 'SameSite Cookie'],
    frequency: 3,
    is_starred: true,
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
    answer_complete: true,
    ai_answer: '闭包是函数与其词法作用域的组合。',
    key_points: [],
    frequency: 8,
    created_at: '2026-01-17T10:00:00',
    _showAnswer: false,
  },
]

const MOCK_ANALYTICS = {
  total_questions: 150,
  practiced_questions: 42,
  total_practiced: 42,
  mastery_rate: 0.72,
  tag_distribution: [{ tag: 'Vue', count: 30 }],
  difficulty_distribution: { easy: 50, medium: 70, hard: 30 },
  category_distribution: [{ category: '前端框架', count: 30 }],
  recent_activity: [],
  popular_tags: [{ tag: '全部', count: 150 }, { tag: 'Vue', count: 30 }],
}

const MOCK_PRACTICE_STATS = {
  total_sessions: 10,
  total_questions: 42,
  avg_score: 78,
  streak: 3,
  by_difficulty: {
    L1: { practiced: 15, total: 50, avg_score: 85 },
    L2: { practiced: 20, total: 70, avg_score: 75 },
    L3: { practiced: 7, total: 30, avg_score: 68 },
  },
}

const MOCK_RECOMMENDATIONS = [
  { id: 1, title: '请介绍一下 Vue 的响应式原理', cat1: '前端框架', difficulty: 'L2', frequency: 5 },
  { id: 3, title: '解释 JavaScript 中的闭包', cat1: 'JavaScript基础', difficulty: 'L1', frequency: 8 },
]

const MOCK_EVALUATION = {
  score: 82,
  overall_score: 82,
  dimensions: {
    accuracy: { score: 85, comment: '核心概念准确' },
    completeness: { score: 80, comment: '覆盖较全面' },
    depth: { score: 78, comment: '有一定深度' },
    logic: { score: 84, comment: '逻辑清晰' },
  },
  strengths: ['回答清晰', '覆盖核心概念'],
  weaknesses: ['缺少具体例子'],
  suggestions: ['建议补充 Proxy 和 defineProperty 的对比'],
}

// 后端返回的 next_review_at 是 UTC naive 时间（YYYY-MM-DD HH:MM:SS），
// 测试里用明天（UTC）保证复习后当前卡会被移出今日复习队列
function tomorrowUtcString() {
  const date = new Date(Date.now() + 86400000)
  return date.toISOString().slice(0, 19).replace('T', ' ')
}

// ── Helper: 注册所有必要的 API mock ──
async function mockAllAPIs(page, options = {}) {
  const {
    deckItems = MOCK_DECKS.items,
    deckQuestions = DUE_QUESTION_SEEDS.slice(0, 3),
    recruitment = AUTUMN_RECRUITMENT,
  } = options
  const tomorrow = tomorrowUtcString()

  // Auth
  await page.route('**/api/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'application/json' },
      json: { token: 'mock-token', user: MOCK_USER },
    })
  })
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: MOCK_USER })
  })
  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
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
    await route.fulfill({ json: [] })
  })

  // Analytics
  await page.route('**/api/analytics**', async (route) => {
    await route.fulfill({ json: MOCK_ANALYTICS })
  })

  // Practice stats
  await page.route('**/api/practice-stats**', async (route) => {
    await route.fulfill({ json: MOCK_PRACTICE_STATS })
  })

  // Practice decks + due queue
  await page.route('**/api/practice/decks**', async (route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    const parts = url.pathname.split('/').filter(Boolean)
    const deckKey = parts[3]
    const isQuestions = parts[4] === 'questions'
    const isItems = parts[4] === 'items'

    if (method === 'POST' && !deckKey) {
      await route.fulfill({ json: { key: 'custom-999-java', name: '我的 Java 题单', description: 'Java 面试冲刺', visibility: 'private', kind: 'custom', total: 0, reviewed: 0, due: 0, progress: 0 } })
      return
    }
    if (method === 'PUT' || (method === 'DELETE' && !isItems)) {
      await route.fulfill({ json: { status: 'success', key: deckKey, name: '今日复习', kind: 'due' } })
      return
    }
    if (isItems) {
      await route.fulfill({ json: { status: 'success', question_id: Number(url.pathname.split('/').at(-1)) || 1 } })
      return
    }
    if (!isQuestions) {
      await route.fulfill({ json: { algorithm: 'sm2_lite', items: deckItems } })
      return
    }
    const deck = deckItems.find(candidate => candidate.key === deckKey)
    const deckName = deck?.name || deckKey
    await route.fulfill({
      json: { deck: { key: deckKey, name: deckName, total: deckQuestions.length }, items: deckQuestions, total: deckQuestions.length, page_size: 100, offset: 0 },
    })
  })

  // Review — echo the reviewed question id, next_review_at 为明天（UTC）
  await page.route('**/api/practice/review', async (route) => {
    const body = JSON.parse(route.request().postData() || '{}')
    await route.fulfill({
      json: {
        question_id: body.question_id,
        review: { state: 'review', proficiency: 2, review_count: 1, next_review_at: tomorrow, interval_days: 3, has_been_practiced: true },
      },
    })
  })

  await page.route('**/api/practice/history**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/practice/recommendations', async (route) => {
    await route.fulfill({ json: MOCK_RECOMMENDATIONS })
  })
  await page.route('**/api/practice/submit', async (route) => {
    await route.fulfill({ json: MOCK_EVALUATION })
  })

  // Answers — generate answer
  await page.route('**/api/answers/**', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: { id: 1, question_id: 1, content: '## Vue 响应式原理\n\nVue 3 使用 Proxy。', key_points: ['Proxy'] } })
    } else {
      await route.fulfill({ json: { status: 'success', answer: '## Vue 响应式原理\n\n详细答案...' } })
    }
  })

  // Evaluate answer
  await page.route('**/api/evaluate-answer', async (route) => {
    await route.fulfill({ json: MOCK_EVALUATION })
  })

  // Practice history by question id
  await page.route('**/api/practice-history/**', async (route) => {
    await route.fulfill({ json: [] })
  })

  // Profile — recruitment 偏好单独分发
  await page.route('**/api/profile**', async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === '/api/profile/recruitment') {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON()
        await page.evaluate((payload) => { window.__lastRecruitmentPut = payload }, body)
        await route.fulfill({ json: { ...recruitment, ...body } })
        return
      }
      await route.fulfill({ json: recruitment })
      return
    }
    if (route.request().method() === 'GET') {
      await route.fulfill({
        json: {
          id: 999, username: 'e2e_tester', email: 'test@example.com',
          current_position: '前端开发工程师', current_position_id: 1,
          positions: [{ id: 1, name: '前端开发工程师' }],
          llm_configured: true, categories: [],
        },
      })
    } else {
      await route.fulfill({ json: { status: 'success' } })
    }
  })

  // Profile resume
  await page.route('**/api/profile/resume**', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })

  // Interview
  await page.route('**/api/interview**', async (route) => {
    await route.fulfill({ json: MOCK_MASTER_BANK })
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

  // Coding
  await page.route('**/api/coding**', async (route) => {
    await route.fulfill({ json: [] })
  })

  // Knowledge
  await page.route('**/api/knowledge', async (route) => {
    await route.fulfill({ json: { nodes: [], edges: [] } })
  })

  // Submit SSE
  await page.route('**/api/submit**', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })
}

// ── Helper: 以已登录状态直接进入 /practice ──
async function gotoPractice(page, options) {
  await mockAllAPIs(page, options)
  await page.goto('/practice')
  await page.waitForSelector('[data-testid="practice-view"]', { timeout: 15000 })
}

// ═══════════════════════════════════════════════
// 1. 今日复习默认入口 + 招聘状态行
// ═══════════════════════════════════════════════
test.describe('今日复习默认入口与招聘状态行', () => {
  test('默认选中今日复习题单并渲染距里程碑倒计时与阶段徽标', async ({ page }) => {
    await gotoPractice(page)

    // 顶栏题单选择器默认选中今日复习（列表第一项）
    const deckSelect = page.getByTestId('practice-deck-select')
    await expect(deckSelect).toContainText('今日复习', { timeout: 5000 })

    // 招聘状态行：当前窗口 + 阶段徽标 + 容量
    const statusBar = page.getByTestId('recruitment-status')
    await expect(statusBar).toContainText('提前批窗口', { timeout: 5000 })
    await expect(statusBar).toContainText('冲刺中')
    await expect(statusBar).toContainText('容量 30 题')

    // 今日复习队列已加载，第一张卡展示
    await expect(page.getByTestId('practice-focus-card').getByText(DUE_QUESTION_SEEDS[0].question)).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('1 / 3')).toBeVisible()
  })

  test('无招聘偏好（batch 为空）时不渲染状态行', async ({ page }) => {
    await gotoPractice(page, { recruitment: EMPTY_RECRUITMENT })

    // 等题单加载完成，确保 recruitment 请求已经返回
    await expect(page.getByTestId('practice-deck-select')).toContainText('今日复习', { timeout: 5000 })
    await page.waitForTimeout(500)
    await expect(page.getByTestId('recruitment-status')).not.toBeVisible()
  })
})

// ═══════════════════════════════════════════════
// 2. 复习后从今日复习队列移除（不跳卡）
// ═══════════════════════════════════════════════
test.describe('今日复习队列复习出队不跳卡', () => {
  test('记得了复习 Q1 后队列移除 Q1 并显示 Q2，连续复习不跳卡', async ({ page }) => {
    const seeds = DUE_QUESTION_SEEDS.slice(0, 4)
    await gotoPractice(page, { deckQuestions: seeds })

    const card = page.getByTestId('practice-focus-card')
    const sidebar = page.getByTestId('practice-queue-sidebar')

    // 初始：当前卡 Q1，侧栏含 Q1，队列 4 张
    await expect(card.getByText(seeds[0].question)).toBeVisible({ timeout: 5000 })
    await expect(sidebar.getByText(seeds[0].question)).toBeVisible()
    await expect(page.getByText('1 / 4')).toBeVisible()

    // 复习 Q1：翻答案 → 记得了
    await page.getByTestId('practice-show-answer').click()
    await expect(page.getByTestId('practice-review-actions')).toBeVisible()
    await page.getByTestId('practice-review-good').click()

    // Q1 从侧栏队列移除；当前卡为 Q2（索引补偿，不跳过）；剩余 3 张
    await expect(sidebar.getByText(seeds[0].question)).not.toBeVisible()
    await expect(card.getByText(seeds[1].question)).toBeVisible()
    await expect(page.getByText('1 / 3')).toBeVisible()

    // 复习 Q2：翻答案 → 记得了 → 当前卡为 Q3
    await page.getByTestId('practice-show-answer').click()
    await expect(page.getByTestId('practice-review-actions')).toBeVisible()
    await page.getByTestId('practice-review-good').click()

    await expect(sidebar.getByText(seeds[1].question)).not.toBeVisible()
    await expect(card.getByText(seeds[2].question)).toBeVisible()
    await expect(page.getByText('1 / 2')).toBeVisible()
  })
})

// ═══════════════════════════════════════════════
// 3. 空今日复习队列 → 完成态
// ═══════════════════════════════════════════════
test.describe('今日复习空队列', () => {
  test('今日复习队列为空时展示完成态', async ({ page }) => {
    const doneDeck = { ...MOCK_DECKS.items[0], reviewed: 3, due: 0, progress: 100 }
    await gotoPractice(page, {
      deckItems: [doneDeck, MOCK_DECKS.items[1]],
      deckQuestions: [],
    })

    await expect(page.getByText('今日复习已经完成')).toBeVisible({ timeout: 5000 })
    await expect(page.getByRole('button', { name: '切换到全部题' })).toBeVisible()
  })
})

// ═══════════════════════════════════════════════
// 4. 已掌握题抽查（保持手感徽标）
// ═══════════════════════════════════════════════
test.describe('已掌握题抽查', () => {
  test('抽查题显示保持手感徽标，复习后仍为已掌握状态', async ({ page }) => {
    const masteredQ = {
      ...DUE_QUESTION_SEEDS[0],
      is_checkin: true,
      state: 'mastered',
      proficiency: 5,
    }
    await gotoPractice(page, { deckQuestions: [masteredQ] })

    // 题卡带「保持手感」徽标
    await expect(page.getByTestId('checkin-badge')).toContainText('保持手感', { timeout: 5000 })
    await expect(page.getByText('1 / 1')).toBeVisible()
  })
})

// ═══════════════════════════════════════════════
// 5. 设置页复习节奏档位
// ═══════════════════════════════════════════════
test.describe('设置页面试时间偏好', () => {
  test('选择冲刺节奏并保存后 PUT 携带 pace=hard', async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/settings?section=interview')
    await page.getByTestId('pace-hard').waitFor({ timeout: 15000 })

    await page.getByTestId('pace-hard').click()
    await page.getByRole('button', { name: '保存', exact: true }).click()

    await expect.poll(() => page.evaluate(() => window.__lastRecruitmentPut || null)).not.toBeNull()
    const payload = await page.evaluate(() => window.__lastRecruitmentPut)
    expect(payload.pace).toBe('hard')
  })
})
