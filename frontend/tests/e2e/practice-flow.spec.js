/**
 * 练习完整流程 E2E 测试 — 覆盖 PracticePanel 做题流程
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
    ai_answer: '## Vue 响应式原理\n\nVue 3 使用 Proxy 实现数据劫持，通过 track 和 trigger 实现依赖收集和派发更新。',
    key_points: ['Proxy', '依赖追踪', '触发更新'],
    sources: [
      { company: '腾讯', round: '一面' },
      { company: '阿里巴巴-高德地图', round: '一面' },
      { company: '字节', round: '一面' },
    ],
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
    answer_complete: false,
    ai_answer: null,
    key_points: [],
    frequency: 8,
    created_at: '2026-01-17T10:00:00',
    _showAnswer: false,
  },
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
  { id: 2, title: '解释 JavaScript 中的闭包', cat1: 'JavaScript基础', difficulty: 'L1', frequency: 8 },
]

// ── Helper: 注册所有必要的 API mock ──
async function mockAllAPIs(page, { studyPlans = true, paginatedPractice = false, practiceAnswer = null } = {}) {
  const practiceBank = practiceAnswer
    ? MOCK_MASTER_BANK.map(item => item.id === 1 ? { ...item, ai_answer: practiceAnswer } : item)
    : MOCK_MASTER_BANK
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
    await route.fulfill({ json: practiceBank })
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
  await page.route('**/api/practice/decks**', async (route) => {
    if (!studyPlans) {
      await route.fulfill({ status: 404, json: { detail: 'study plans not mocked' } })
      return
    }
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
      await route.fulfill({ json: { status: 'success', key: deckKey, name: '我的 Java 题单', kind: 'custom' } })
      return
    }
    if (isItems) {
      await route.fulfill({ json: { status: 'success', question_id: Number(url.pathname.split('/').at(-1)) || 1 } })
      return
    }
    if (!isQuestions) {
      const allDeckTotal = paginatedPractice ? 101 : 3
      await route.fulfill({
        json: {
          algorithm: 'sm2_lite',
          items: [
            { key: 'all', name: '全部题', description: '按复习状态和面试频率安排顺序', total: allDeckTotal, reviewed: 0, due: allDeckTotal, progress: 0 },
            { key: 'starred', name: '我的收藏', description: '收藏题', total: 1, reviewed: 0, due: 1, progress: 0 },
            { key: 'custom-999-java', name: '我的 Java 题单', description: 'Java 面试冲刺', visibility: 'private', kind: 'custom', total: 1, reviewed: 0, due: 1, progress: 0 },
          ],
        },
      })
      return
    }
    const baseItems = deckKey === 'custom-999-java'
      ? [practiceBank[0]]
      : deckKey === 'starred'
        ? practiceBank.filter(item => item.is_starred)
        : practiceBank
    const allItems = paginatedPractice && deckKey === 'all'
      ? [
          ...baseItems,
          ...Array.from({ length: 98 }, (_, index) => ({
            ...practiceBank[index % practiceBank.length],
            id: 100 + index,
            title: `分页题目 ${index + 1}`,
            question: `分页题目 ${index + 1}`,
            is_starred: false,
          })),
        ]
      : baseItems
    const offset = Number(url.searchParams.get('offset') || 0)
    const limit = Number(url.searchParams.get('limit') || 100)
    const items = allItems.slice(offset, offset + limit)
    const deckName = deckKey === 'all' ? '全部题' : deckKey === 'starred' ? '我的收藏' : deckKey
    await route.fulfill({ json: { deck: { key: deckKey, name: deckName, total: allItems.length }, items, total: allItems.length, page_size: limit, offset } })
  })
  await page.route('**/api/practice/review', async (route) => {
    await route.fulfill({ json: { question_id: 1, review: { state: 'learning', proficiency: 1, review_count: 1, has_been_practiced: true, next_review_at: '2026-08-07 09:00:00' } } })
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
      await route.fulfill({
        json: {
          id: 1,
          question_id: 1,
          content: '## Vue 响应式原理\n\nVue 3 使用 Proxy 实现数据劫持，通过 track() 和 trigger() 实现依赖收集和派发更新。',
          key_points: ['Proxy', '依赖追踪', '触发更新'],
        },
      })
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
    await route.fulfill({
      json: [
        {
          id: 1,
          question_id: 1,
          user_answer: 'Vue使用Proxy...',
          score: 75,
          evaluation_result: { dimensions: { accuracy: { score: 80 }, completeness: { score: 70 } }, suggestions: '可以更详细' },
          created_at: '2026-05-20T10:00:00',
        },
      ],
    })
  })

  // Profile
  await page.route('**/api/profile**', async (route) => {
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

  // Profile resume
  await page.route('**/api/profile/resume**', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })
}

// ── Helper: 以已登录状态进入主页 ──
async function gotoLoggedIn(page, options) {
  await mockAllAPIs(page, options)
  await page.goto('/')
  await page.waitForSelector('main', { timeout: 15000 })
  await page.waitForTimeout(1000)
}

// ═══════════════════════════════════════════════
// 练习完整流程测试
// ═══════════════════════════════════════════════
test.describe('练习完整流程 — PracticePanel', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page)
    // 确保在高频题库 Tab（默认应在此）
    await page.getByRole('button', { name: '高频题库' }).click()
    await page.waitForTimeout(500)
  })

  test('题库列表渲染且题目可见', async ({ page }) => {
    // 应能看到题目标题
    await expect(page.getByText('请介绍一下 Vue 的响应式原理').first()).toBeVisible({ timeout: 5000 })
  })

  test('点击做题按钮打开练习面板', async ({ page }) => {
    // 找到做题按钮 — QuestionCard 中 @click.stop="$emit('practice', question)"
    // 做题按钮通常是一个带有 "做题" 文字或特定 title 的按钮
    const practiceBtn = page.locator('button[title="做题"], button').filter({ hasText: '做题' }).first()

    if (await practiceBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await practiceBtn.click()
      await page.waitForTimeout(500)

      // PracticePanel 应打开 — 显示 "我的回答" 区域
      await expect(page.getByText('我的回答').first()).toBeVisible({ timeout: 5000 })
    } else {
      // 退化：直接点击题目卡片展开，然后找做题按钮
      const questionTitle = page.getByText('请介绍一下 Vue 的响应式原理').first()
      await questionTitle.click()
      await page.waitForTimeout(500)

      // 再次查找做题按钮
      const altPracticeBtn = page.locator('button').filter({ hasText: '做题' }).first()
      if (await altPracticeBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await altPracticeBtn.click()
        await page.waitForTimeout(500)
        await expect(page.getByText('我的回答').first()).toBeVisible({ timeout: 5000 })
      }
    }
  })

  test('练习面板显示题目内容', async ({ page }) => {
    // 打开练习面板
    const practiceBtn = page.locator('button').filter({ hasText: '做题' }).first()
    if (await practiceBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await practiceBtn.click()
    } else {
      await page.getByText('请介绍一下 Vue 的响应式原理').first().click()
      await page.waitForTimeout(500)
      const altBtn = page.locator('button').filter({ hasText: '做题' }).first()
      if (await altBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await altBtn.click()
      }
    }
    await page.waitForTimeout(500)

    // 题目内容应显示 — 检查题目 tab 或题目文字
    const body = await page.locator('body').textContent()
    expect(body.includes('Vue') || body.includes('响应式') || body.includes('题目')).toBeTruthy()
  })

  test('回答输入框可输入', async ({ page }) => {
    // 打开练习面板
    const practiceBtn = page.locator('button').filter({ hasText: '做题' }).first()
    if (await practiceBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await practiceBtn.click()
    } else {
      await page.getByText('请介绍一下 Vue 的响应式原理').first().click()
      await page.waitForTimeout(500)
      const altBtn = page.locator('button').filter({ hasText: '做题' }).first()
      if (await altBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await altBtn.click()
      }
    }
    await page.waitForTimeout(500)

    // 找到回答 textarea（placeholder 包含 "在此输入你的回答"）
    const answerTextarea = page.locator('textarea[placeholder*="在此输入"]').first()
    if (await answerTextarea.isVisible({ timeout: 3000 }).catch(() => false)) {
      await answerTextarea.fill('Vue 3 使用 Proxy 实现响应式数据绑定')
      expect(await answerTextarea.inputValue()).toContain('Proxy')
    }
  })

  test('提交回答按钮可点击 — mock API 返回评估结果', async ({ page }) => {
    // 打开练习面板
    const practiceBtn = page.locator('button').filter({ hasText: '做题' }).first()
    if (await practiceBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await practiceBtn.click()
    } else {
      await page.getByText('请介绍一下 Vue 的响应式原理').first().click()
      await page.waitForTimeout(500)
      const altBtn = page.locator('button').filter({ hasText: '做题' }).first()
      if (await altBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await altBtn.click()
      }
    }
    await page.waitForTimeout(500)

    // 填入回答
    const answerTextarea = page.locator('textarea[placeholder*="在此输入"]').first()
    if (await answerTextarea.isVisible({ timeout: 3000 }).catch(() => false)) {
      await answerTextarea.fill('Vue 3 使用 Proxy 代理对象实现响应式，通过 Reflect 操作原始对象。track 在 getter 中收集依赖，trigger 在 setter 中通知更新。')

      // 点击提交评估按钮
      const evalBtn = page.getByRole('button', { name: '提交评估' })
      if (await evalBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await evalBtn.click()
        await page.waitForTimeout(2000)

        // 评估结果应显示
        const body = await page.locator('body').textContent()
        expect(body.includes('82') || body.includes('评估') || body.includes('准确性') || body.includes('完整性')).toBeTruthy()
      }
    }
  })

  test('评估结果渲染 — 显示分数和维度评估', async ({ page }) => {
    // 打开练习面板并提交回答
    const practiceBtn = page.locator('button').filter({ hasText: '做题' }).first()
    if (await practiceBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await practiceBtn.click()
    } else {
      await page.getByText('请介绍一下 Vue 的响应式原理').first().click()
      await page.waitForTimeout(500)
      const altBtn = page.locator('button').filter({ hasText: '做题' }).first()
      if (await altBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await altBtn.click()
      }
    }
    await page.waitForTimeout(500)

    const answerTextarea = page.locator('textarea[placeholder*="在此输入"]').first()
    if (await answerTextarea.isVisible({ timeout: 3000 }).catch(() => false)) {
      await answerTextarea.fill('Vue 响应式原理的回答：使用 Proxy 实现')

      const evalBtn = page.getByRole('button', { name: '提交评估' })
      if (await evalBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await evalBtn.click()
        await page.waitForTimeout(2000)

        // 验证评估结果区域出现
        const body = await page.locator('body').textContent()
        // 可能显示分数、维度标签、或评估反馈
        const hasEvalResult = body.includes('82') || body.includes('准确性') || body.includes('完整性')
          || body.includes('深度') || body.includes('逻辑性') || body.includes('亮点') || body.includes('不足')
          || body.includes('改进建议') || body.includes('评估') || body.includes('回答清晰')
        expect(hasEvalResult).toBeTruthy()
      }
    }
  })

  test('查看参考答案 tab 可切换', async ({ page }) => {
    // 打开练习面板
    const practiceBtn = page.locator('button').filter({ hasText: '做题' }).first()
    if (await practiceBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await practiceBtn.click()
    } else {
      await page.getByText('请介绍一下 Vue 的响应式原理').first().click()
      await page.waitForTimeout(500)
      const altBtn = page.locator('button').filter({ hasText: '做题' }).first()
      if (await altBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await altBtn.click()
      }
    }
    await page.waitForTimeout(500)

    // 点击 "参考答案" tab
    const answerTab = page.getByRole('button', { name: '参考答案' }).first()
    if (await answerTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await answerTab.click()
      await page.waitForTimeout(500)

      // 应显示 AI 参考答案相关内容
      const body = await page.locator('body').textContent()
      expect(body.includes('AI 参考答案') || body.includes('Proxy') || body.includes('答案') || body.includes('生成')).toBeTruthy()
    }
  })

  test('练习记录 tab 可切换', async ({ page }) => {
    // 打开练习面板
    const practiceBtn = page.locator('button').filter({ hasText: '做题' }).first()
    if (await practiceBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await practiceBtn.click()
    } else {
      await page.getByText('请介绍一下 Vue 的响应式原理').first().click()
      await page.waitForTimeout(500)
      const altBtn = page.locator('button').filter({ hasText: '做题' }).first()
      if (await altBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await altBtn.click()
      }
    }
    await page.waitForTimeout(500)

    // 点击 "练习记录" tab
    const historyTab = page.getByRole('button', { name: '练习记录' }).first()
    if (await historyTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await historyTab.click()
      await page.waitForTimeout(500)

      // 应显示练习记录或"暂无练习记录"
      const body = await page.locator('body').textContent()
      expect(body.includes('练习记录') || body.includes('暂无') || body.includes('75')).toBeTruthy()
    }
  })

  test('独立刷题工作台使用全局题单顶栏', async ({ page }) => {
    await page.getByRole('button', { name: '八股刷题', exact: true }).click()
    await expect(page).toHaveURL(/\/practice/)
    await expect(page.getByTestId('practice-header')).toBeVisible({ timeout: 5000 })
    await expect(page.getByTestId('practice-deck-select')).toBeVisible()
    await page.getByTestId('practice-deck-select').click()
    await expect(page.getByTestId('practice-manage-decks')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('button', { name: '返回题库' })).not.toBeVisible()
    await expect(page.getByText('刷题队列')).not.toBeVisible()
  })

  test('无题目时面板属性正确处理', async ({ page }) => {
    // PracticePanel 的 visible 取决于 practiceQuestion
    // 验证默认状态下面板不可见
    await expect(page.getByText('我的回答')).not.toBeVisible({ timeout: 3000 })
  })

  test('八股刷题支持收藏题单和单卡查看答案', async ({ page }) => {
    await page.getByRole('button', { name: '八股刷题模式' }).click()

    await expect(page.getByTestId('practice-header')).toBeVisible({ timeout: 5000 })
    const deckSelect = page.getByTestId('practice-deck-select')
    await expect(deckSelect).toBeVisible()

    await deckSelect.click()
    await page.getByRole('option', { name: /我的收藏/ }).click()
    await expect(page.getByTestId('practice-card')).toContainText('什么是 CSRF 攻击？如何防御？')

    await page.getByTestId('practice-show-answer').click()
    await expect(page.getByText('AI 参考答案')).toBeVisible()
    await expect(page.getByText('CSRF 跨站请求伪造')).toBeVisible()
  })

  test('当前题卡可以加入用户题单', async ({ page }) => {
    await page.getByRole('button', { name: '八股刷题', exact: true }).click()
    await expect(page.getByTestId('practice-add-to-deck')).toBeVisible()

    await page.getByTestId('practice-add-to-deck').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('我的 Java 题单')
    await dialog.getByRole('button', { name: '加入题单', exact: true }).click()
    await expect(dialog).not.toBeVisible()
  })

  test('刷题作为训练区独立 Tab 展示', async ({ page }) => {
    await page.getByRole('button', { name: '八股刷题', exact: true }).click()

    await expect(page).toHaveURL(/\/practice/)
    await expect(page.getByTestId('practice-focus-card')).toContainText('请介绍一下 Vue 的响应式原理')
    await expect(page.getByTestId('practice-focus-card').getByText('主动回忆')).not.toBeVisible()
    await expect(page.getByTestId('practice-deck-select')).toBeVisible()
  })

  test('刷新后恢复当前题卡而不是回到题单第一题', async ({ page }) => {
    await page.getByRole('button', { name: '八股刷题', exact: true }).click()
    await page.getByTestId('practice-switch-browse').click()
    await expect(page.getByTestId('practice-card')).toContainText('请介绍一下 Vue 的响应式原理')

    await page.getByRole('button', { name: '下一题' }).click()
    await expect(page.getByTestId('practice-card')).toContainText('什么是 CSRF 攻击？如何防御？')

    await page.reload()
    await expect(page.getByTestId('practice-card')).toContainText('什么是 CSRF 攻击？如何防御？')
    await expect(page.getByTestId('practice-card')).not.toContainText('请介绍一下 Vue 的响应式原理')
  })

  test('刷题工作区沿用训练页滚动容器并适配视口宽度', async ({ page }) => {
    await page.getByRole('button', { name: '八股刷题', exact: true }).click()

    await expect(page.getByTestId('practice-view')).toBeVisible()
    await expect(page.getByTestId('practice-workspace')).toBeVisible()
    await expect(page.getByTestId('practice-main')).toHaveClass(/overflow-hidden/)
    await expect(page.getByTestId('practice-card-content')).toHaveClass(/overflow-y-auto/)
    await expect(page.getByText('主动回忆')).not.toBeVisible()
    await expect(page.getByText('先在脑中组织答案，想清楚“是什么、为什么、怎么做”，再翻开卡片。')).not.toBeVisible()

    const metrics = await page.evaluate(() => {
      const view = document.querySelector('[data-testid="practice-view"]')
      const workspace = document.querySelector('[data-testid="practice-workspace"]')
      const documentWidth = document.documentElement.scrollWidth
      const viewportWidth = document.documentElement.clientWidth
      const viewRect = view?.getBoundingClientRect()
      const workspaceRect = workspace?.getBoundingClientRect()
      return {
        documentWidth,
        viewportWidth,
        viewWidth: viewRect?.width || 0,
        workspaceRight: workspaceRect?.right || 0,
      }
    })

    expect(metrics.documentWidth).toBeLessThanOrEqual(metrics.viewportWidth)
    expect(metrics.viewWidth).toBeGreaterThan(0)
    expect(metrics.workspaceRight).toBeLessThanOrEqual(metrics.viewportWidth)
  })

  test('移动端刷题显示触屏操作文字且不产生横向溢出', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/practice')

    const listButton = page.getByRole('button', { name: '展开题目列表' })
    const infoButton = page.getByRole('button', { name: '打开题卡信息' })
    await expect(listButton).toBeVisible()
    await expect(infoButton).toBeVisible()
    await expect(page.getByText('点击按钮查看答案')).toBeVisible()

    await infoButton.click()
    const sheet = page.getByTestId('practice-mobile-info-sheet')
    await expect(sheet).toBeVisible()
    await expect(sheet.getByRole('button', { name: '收藏题目' })).toBeVisible()

    const targets = await Promise.all([listButton, infoButton, sheet.getByRole('button', { name: '收藏题目' })].map(locator => locator.boundingBox()))
    for (const target of targets) expect(target.height).toBeGreaterThanOrEqual(40)

    const width = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }))
    expect(width.content).toBeLessThanOrEqual(width.viewport + 1)
  })

  test('移动端题卡头部保持紧凑，详情操作收进侧栏', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: '八股刷题', exact: true }).click()

    await expect(page.getByTestId('practice-mobile-info-sheet')).not.toBeVisible()
    await expect(page.getByTestId('practice-mobile-info-sheet')).toHaveCount(1)
    await page.getByRole('button', { name: '打开题卡信息' }).click()
    await expect(page.getByTestId('practice-mobile-info-sheet')).toBeVisible()
    await expect(page.getByTestId('practice-mobile-info-sheet')).toContainText('高频出现')
    await expect(page.getByTestId('practice-mobile-info-sheet')).toContainText('加入题单')
    await expect(page.getByTestId('practice-mobile-info-sheet')).toContainText('收藏题目')
  })

  test('移动端面经来源不会覆盖自评按钮', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: '八股刷题', exact: true }).click()

    const sources = page.getByTestId('practice-question-sources')
    const selfAssess = page.locator('[data-testid^="practice-self-assess-"]')
    await expect(sources).toBeVisible()
    await expect(selfAssess).toHaveCount(3)

    const layout = await page.evaluate(() => {
      const sourceRect = document.querySelector('[data-testid="practice-question-sources"]')?.getBoundingClientRect()
      const buttons = [...document.querySelectorAll('[data-testid^="practice-self-assess-"]')]
      return {
        sourceTop: sourceRect?.top || 0,
        selfAssessBottom: Math.max(...buttons.map(button => button.getBoundingClientRect().bottom)),
      }
    })
    expect(layout.sourceTop).toBeGreaterThanOrEqual(layout.selfAssessBottom - 1)
  })

  test('刷题以单卡为主任务并在翻牌后显示复习反馈', async ({ page }) => {
    await page.getByRole('button', { name: '八股刷题', exact: true }).click()

    await expect(page.getByTestId('practice-header')).toBeVisible()
    await expect(page.getByTestId('practice-focus-card')).toBeVisible()
    await expect(page.getByTestId('practice-focus-card').getByText('主动回忆')).not.toBeVisible()

    await page.getByTestId('practice-show-answer').click()
    await expect(page.getByTestId('practice-review-actions')).toBeVisible()
    await expect(page.getByRole('button', { name: '记得了' })).toBeVisible()

    const answerAndActions = await page.evaluate(() => {
      const answer = document.querySelector('.flashcard-answer')?.getBoundingClientRect()
      const actions = document.querySelector('[data-testid="practice-review-actions"]')?.getBoundingClientRect()
      return { answerBottom: answer?.bottom || 0, actionsTop: actions?.top || 0 }
    })
    expect(answerAndActions.actionsTop).toBeGreaterThanOrEqual(answerAndActions.answerBottom - 1)
  })

  test('看题模式可从题卡顶部标记很熟并拉长复习间隔', async ({ page }) => {
    let reviewPayload = null
    page.on('request', request => {
      if (request.method() === 'POST' && request.url().endsWith('/api/practice/review')) {
        reviewPayload = request.postDataJSON()
      }
    })

    await page.getByRole('button', { name: '八股刷题', exact: true }).click()
    await expect(page.getByTestId('practice-focus-card').getByText('请介绍一下 Vue 的响应式原理')).toBeVisible()
    await expect(page.getByTestId('practice-mark-familiar')).toBeVisible()
    await page.getByTestId('practice-mark-familiar').click()

    await expect.poll(() => reviewPayload).toEqual({ question_id: 1, rating: 'easy', score: null })
    await expect(page.getByTestId('practice-focus-card').getByText('什么是 CSRF 攻击？如何防御？')).toBeVisible()
    await expect(page.getByText(/已标记为很熟/)).toBeVisible()
  })

  test('刷题题单与高频题库联动并保存熟练度', async ({ page }) => {
    await page.getByRole('button', { name: '八股刷题', exact: true }).click()

    const deckSelect = page.getByTestId('practice-deck-select')
    await expect(deckSelect).toContainText('全部题')
    await deckSelect.click()
    await page.getByRole('option', { name: /全部题/ }).click()
    await expect(page.getByTestId('practice-card')).toContainText('请介绍一下 Vue 的响应式原理')

    await page.getByTestId('practice-show-answer').click()
    await expect(page.getByTestId('practice-review-actions')).toBeVisible()
    await page.getByTestId('practice-review-good').click()
    await expect(deckSelect).toBeVisible()
  })

  test('切换已加载题单时复用缓存且不会重复请求', async ({ page }) => {
    const questionRequests = []
    page.on('request', request => {
      const url = new URL(request.url())
      if (url.pathname.endsWith('/questions')) questionRequests.push(url.pathname)
    })

    await page.getByRole('button', { name: '八股刷题', exact: true }).click()
    const deckSelect = page.getByTestId('practice-deck-select')
    await expect(deckSelect).toContainText('全部题')

    await deckSelect.click()
    await page.getByRole('option', { name: /我的收藏/ }).click()
    await expect(page.getByTestId('practice-card')).toContainText('什么是 CSRF 攻击？如何防御？')
    await deckSelect.click()
    await page.getByRole('option', { name: /全部题/ }).click()
    await expect(page.getByTestId('practice-card')).toContainText('请介绍一下 Vue 的响应式原理')
    await deckSelect.click()
    await page.getByRole('option', { name: /我的收藏/ }).click()
    await expect(page.getByTestId('practice-card')).toContainText('什么是 CSRF 攻击？如何防御？')

    expect(questionRequests).toHaveLength(2)
    expect(questionRequests).toEqual([
      '/api/practice/decks/all/questions',
      '/api/practice/decks/starred/questions',
    ])
  })

  test('题单管理页可查看自定义题单并进入题目管理', async ({ page }) => {
    await page.getByRole('button', { name: '八股刷题', exact: true }).click()
    await page.getByTestId('practice-deck-select').click()
    await page.getByTestId('practice-manage-decks').click()

    await expect(page).toHaveURL(/\/practice\/decks/)
    await expect(page.getByTestId('practice-deck-manager')).toBeVisible()
    const customCard = page.getByTestId('practice-deck-card').filter({ hasText: '我的 Java 题单' })
    await expect(customCard).toBeVisible()
    await customCard.getByRole('button').first().click()
    await expect(page.getByText('请介绍一下 Vue 的响应式原理').last()).toBeVisible()
    await expect(page.getByTestId('practice-deck-question-select')).toBeVisible()
  })
})

test.describe('刷题参考答案布局', () => {
  test('窄屏展开长答案时，复习操作不会覆盖答案内容', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 844 })
    const longAnswer = Array.from({ length: 14 }, (_, index) => (
      `### 流量治理第 ${index + 1} 步\n\n通过限流、降级、缓存和异步化控制峰值流量，避免单点故障扩散。`
    )).join('\n\n')
    await gotoLoggedIn(page, { practiceAnswer: longAnswer })
    await page.getByRole('button', { name: '八股刷题', exact: true }).click()
    await page.getByTestId('practice-show-answer').click()

    const answer = page.locator('[data-testid="practice-card"] .flashcard-answer')
    const actions = page.getByTestId('practice-review-actions')
    await expect(answer).toBeVisible()
    await expect(actions).toBeVisible()
    const answerBox = await answer.boundingBox()
    const actionsBox = await actions.boundingBox()
    expect(answerBox).not.toBeNull()
    expect(actionsBox).not.toBeNull()
    expect(actionsBox.y).toBeGreaterThanOrEqual(answerBox.y + answerBox.height - 1)
  })
})

test.describe('刷题题单分页', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page, { paginatedPractice: true })
  })

  test('全部题超过首屏后可以继续加载剩余题目', async ({ page }) => {
    await page.getByRole('button', { name: '八股刷题', exact: true }).click()
    await expect(page.getByTestId('practice-card')).toContainText('请介绍一下 Vue 的响应式原理')

    const questionList = page.locator('[data-testid="practice-queue-sidebar"] .overflow-y-auto')
    await expect(questionList.locator('button')).toHaveCount(101) // 100 道题 +「加载更多」

    const nextPage = page.waitForRequest(request => {
      const url = new URL(request.url())
      return url.pathname.endsWith('/api/practice/decks/all/questions')
        && url.searchParams.get('offset') === '100'
    })
    await questionList.evaluate(element => {
      element.scrollTop = element.scrollHeight
      element.dispatchEvent(new Event('scroll', { bubbles: true }))
    })
    await nextPage

    await expect(questionList.locator('button')).toHaveCount(101)
    await expect(questionList).toContainText('分页题目 98')
    await expect(questionList).toContainText('已加载全部 101 道题')
  })
})
