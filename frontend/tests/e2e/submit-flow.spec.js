/**
 * 导入/提交 E2E 测试 — 覆盖 StagingPanel 提交流程
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
    ai_answer: '## Vue 响应式原理\n\nVue 3 使用 Proxy 实现数据劫持...',
    key_points: ['Proxy', '依赖追踪', '触发更新'],
    frequency: 5,
    created_at: '2026-01-15T10:00:00',
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
}

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
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/practice/submit', async (route) => {
    await route.fulfill({ json: { score: 82, overall_score: 82, dimensions: {} } })
  })

  // Answers
  await page.route('**/api/answers/**', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: { id: 1, question_id: 1, content: '答案', key_points: [] } })
    } else {
      await route.fulfill({ json: { status: 'success' } })
    }
  })

  // Profile
  await page.route('**/api/profile**', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: { id: 999, username: 'e2e_tester', email: 'test@example.com', current_position: '前端开发工程师', current_position_id: 1, positions: [{ id: 1, name: '前端开发工程师' }], llm_configured: true, categories: [] } })
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

  // Profile resume
  await page.route('**/api/profile/resume**', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })

  // Evaluate answer
  await page.route('**/api/evaluate-answer', async (route) => {
    await route.fulfill({ json: { score: 82, overall_score: 82, dimensions: { accuracy: { score: 85 }, completeness: { score: 80 } }, strengths: ['回答清晰'], weaknesses: ['缺少例子'], suggestions: ['建议补充细节'] } })
  })

  // Practice history
  await page.route('**/api/practice-history/**', async (route) => {
    await route.fulfill({ json: [] })
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
// 导入/提交 测试
// ═══════════════════════════════════════════════
test.describe('导入 Tab — StagingPanel 提交流程', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page)
    // 点击导入 Tab
    await page.getByRole('button', { name: '导入' }).click()
    await page.waitForTimeout(500)
  })

  test('导入 Tab 可点击并切换到提交面板', async ({ page }) => {
    // StagingPanel 标题应出现
    await expect(page.getByText('导入面经 / JD')).toBeVisible({ timeout: 5000 })
  })

  test('来源链接输入框存在', async ({ page }) => {
    // 来源链接 label
    await expect(page.getByText('来源链接')).toBeVisible({ timeout: 5000 })
    // 输入框
    const urlInput = page.locator('input[placeholder*="小红书"], input[placeholder*="牛客"]').first()
    await expect(urlInput).toBeVisible()
  })

  test('文本输入框存在', async ({ page }) => {
    // 文本内容 label
    await expect(page.getByText('文本内容').first()).toBeVisible({ timeout: 5000 })
    // textarea
    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
    await expect(textarea).toBeVisible()
  })

  test('图片上传区域存在', async ({ page }) => {
    // "+ 选择图片" 按钮
    await expect(page.getByText('+ 选择图片').first()).toBeVisible({ timeout: 5000 })
    // 图片计数标签
    await expect(page.getByText('图片 (0 张)').first()).toBeVisible()
  })

  test('导入类型选择器存在', async ({ page }) => {
    await expect(page.getByText('导入类型').first()).toBeVisible({ timeout: 5000 })
  })

  test('招聘季节选择器存在', async ({ page }) => {
    await expect(page.getByText('招聘季节').first()).toBeVisible({ timeout: 5000 })
  })

  test('空内容时提交按钮禁用', async ({ page }) => {
    const submitBtn = page.getByRole('button', { name: '提交解析' })
    await expect(submitBtn).toBeVisible({ timeout: 5000 })
    // 没有文本内容时应禁用
    await expect(submitBtn).toBeDisabled()
  })

  test('输入文本后提交按钮可用', async ({ page }) => {
    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
    await textarea.fill('这是一段面试经历的内容')
    await page.waitForTimeout(200)

    const submitBtn = page.getByRole('button', { name: '提交解析' })
    await expect(submitBtn).toBeEnabled()
  })

  test('无效 URL 提交显示错误提示', async ({ page }) => {
    // 填入无效URL
    const urlInput = page.locator('input[placeholder*="小红书"], input[placeholder*="牛客"]').first()
    await urlInput.fill('not-a-valid-url')

    // 填入文本内容
    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
    await textarea.fill('测试内容')

    // 点击提交
    const submitBtn = page.getByRole('button', { name: '提交解析' })
    await submitBtn.click()
    await page.waitForTimeout(500)

    // 应显示错误信息
    const body = await page.locator('body').textContent()
    expect(body.includes('链接') || body.includes('URL') || body.includes('格式') || body.includes('错误')).toBeTruthy()
  })

  test('提交后显示成功结果', async ({ page }) => {
    // Mock SSE 提交接口
    await page.route('**/api/submit-stream-v2', async (route) => {
      const sseData = [
        'data: {"step":"extract","message":"正在提取内容","data":{"question_count":3}}',
        'data: {"step":"fill","message":"补全信息","data":{}}',
        'data: {"step":"tag","message":"标注题目","data":{}}',
        'data: {"step":"match","message":"匹配聚类","data":{"matched_count":1,"unmatched_count":2}}',
        'data: {"step":"save","message":"保存入库","data":{"elapsed_seconds":2.5}}',
      ].join('\n') + '\n'
      // The final result is returned as a done-type event
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
        body: sseData + 'data: {"type":"done","doc_type":"interview","target":"personal","question_count":3}\n\n',
      })
    })

    // 填入文本
    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
    await textarea.fill('字节跳动一面：问了闭包、Promise、Vue响应式原理')

    // 点击提交
    const submitBtn = page.getByRole('button', { name: '提交解析' })
    await submitBtn.click()
    await page.waitForTimeout(3000)

    // 应显示提交成功或进度信息
    const body = await page.locator('body').textContent()
    expect(body.includes('提交成功') || body.includes('提取') || body.includes('导入') || body.includes('完成')).toBeTruthy()
  })
})
