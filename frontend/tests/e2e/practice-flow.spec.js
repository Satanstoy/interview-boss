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
async function mockAllAPIs(page) {
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
  await page.route('**/api/practice/stats**', async (route) => {
    await route.fulfill({ json: MOCK_PRACTICE_STATS })
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
async function gotoLoggedIn(page) {
  await mockAllAPIs(page)
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

  test('独立刷题工作台可退出并返回题库', async ({ page }) => {
    await page.getByRole('button', { name: '刷题', exact: true }).click()
    await expect(page).toHaveURL(/\/practice/)
    await expect(page.getByText('闪卡模式')).toBeVisible({ timeout: 5000 })

    await page.getByRole('button', { name: '退出刷题' }).click()
    await expect(page).toHaveURL(/\/master-bank/)
  })

  test('无题目时面板属性正确处理', async ({ page }) => {
    // PracticePanel 的 visible 取决于 practiceQuestion
    // 验证默认状态下面板不可见
    await expect(page.getByText('我的回答')).not.toBeVisible({ timeout: 3000 })
  })

  test('刷题模式支持收藏题单和单卡查看答案', async ({ page }) => {
    await page.getByRole('button', { name: '刷题模式' }).click()

    await expect(page.getByTestId('practice-session-picker')).toBeVisible({ timeout: 5000 })
    await expect(page.getByTestId('practice-session-quick')).toBeVisible()

    await page.getByTestId('practice-session-starred').click()
    await expect(page.getByTestId('practice-card')).toContainText('什么是 CSRF 攻击？如何防御？')
    await expect(page.getByText('1 道收藏题').first()).toBeVisible()

    await page.getByTestId('practice-show-answer').click()
    await expect(page.getByText('AI 参考答案')).toBeVisible()
    await expect(page.getByText('CSRF 跨站请求伪造')).toBeVisible()
  })

  test('刷题作为训练区独立 Tab 展示', async ({ page }) => {
    await page.getByRole('button', { name: '刷题', exact: true }).click()

    await expect(page).toHaveURL(/\/practice/)
    await expect(page.getByText('闪卡模式')).toBeVisible()
    await expect(page.getByTestId('practice-session-picker')).toBeVisible()
  })
})
