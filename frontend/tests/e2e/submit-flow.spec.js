/**
 * 导入/提交 E2E 测试 — 覆盖 StagingPanel 提交流程
 * 所有 API 均通过 page.route() mock，不依赖真实后端
 *
 * 覆盖：
 * - 面板基本结构（文本/图片/来源链接/类型/季节）
 * - 提交按钮禁用/可用状态
 * - URL 前端校验错误
 * - 后台 Job 实时进度列表（SSE）
 * - 分享设置对所有用户可选（share/private）
 * - 非图片文件忽略提示
 * - 清空非空内容需确认
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

  // Profile — 先注册通用 profile，再覆盖更具体的 llm-status（后注册优先匹配）
  await page.route('**/api/profile**', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: { id: 999, username: 'e2e_tester', email: 'test@example.com', current_position: '前端开发工程师', current_position_id: 1, positions: [{ id: 1, name: '前端开发工程师' }], llm_configured: true, categories: [] } })
    } else {
      await route.fulfill({ json: { status: 'success' } })
    }
  })
  // 模型预检守卫：configured + connected 都必须为 true，否则提交会被 ModelGuard 拦截
  await page.route('**/api/profile/llm/status**', async (route) => {
    await route.fulfill({ json: { configured: true, connected: true, model: 'mock-model' } })
  })

  // Submit jobs — 页面加载时 restoreActiveJobs 会请求 active 列表
  await page.route('**/api/submit-jobs/active', async (route) => {
    await route.fulfill({ json: [] })
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

// ── Helper: 以已登录状态进入导入页 ──
async function gotoImportTab(page) {
  await mockAllAPIs(page)
  await page.goto('/')
  await page.waitForSelector('main', { timeout: 15000 })
  await page.getByRole('button', { name: '导入' }).click()
  await page.waitForTimeout(500)
}

// ═══════════════════════════════════════════════
// 导入/提交 测试
// ═══════════════════════════════════════════════
test.describe('导入 Tab — StagingPanel 提交流程', () => {
  test.beforeEach(async ({ page }) => {
    await gotoImportTab(page)
  })

  test('导入 Tab 可点击并切换到提交面板', async ({ page }) => {
    await expect(page.getByText('提交后由后台任务完成提取和归档')).toBeVisible({ timeout: 5000 })
  })

  test('来源链接输入框存在', async ({ page }) => {
    await expect(page.getByText('来源链接（可选）')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('input[placeholder="https://..."]')).toBeVisible()
  })

  test('文本输入框存在', async ({ page }) => {
    await expect(page.getByText('文本内容').first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator('textarea[placeholder*="粘贴面经"]')).toBeVisible()
  })

  test('图片上传区域存在', async ({ page }) => {
    await expect(page.getByText('拖拽图片到此处，或点击选择')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('0 / 20')).toBeVisible()
  })

  test('类型选择器存在', async ({ page }) => {
    await expect(page.getByText('类型').first()).toBeVisible({ timeout: 5000 })
  })

  test('季节选择器存在', async ({ page }) => {
    await expect(page.getByText('季节').first()).toBeVisible({ timeout: 5000 })
  })

  test('分享设置对所有用户可选 — 非管理员默认仅自己可见', async ({ page }) => {
    // 非管理员（MOCK_USER.is_admin=false）下拉不应显示为空值
    await expect(page.getByText('仅自己可见').first()).toBeVisible({ timeout: 5000 })
  })

  test('分享设置对所有用户可选 — 非管理员可选择分享到公共题库', async ({ page }) => {
    // reka-ui SelectTrigger 是 role="combobox"，直接点击 trigger 上的值文本打开下拉
    await page.getByText('仅自己可见').first().click()
    await page.waitForTimeout(300)
    await expect(page.getByRole('option', { name: '分享到公共题库' })).toBeVisible()
    await expect(page.getByRole('option', { name: '仅自己可见' })).toBeVisible()
    await page.getByRole('option', { name: '分享到公共题库' }).click()
    await page.waitForTimeout(300)
    // 选中后 trigger 应显示新值（旧 bug：非 admin 被强制为非法值 'personal' 导致空白）
    await expect(page.getByText('分享到公共题库').first()).toBeVisible()
  })

  test('空内容时提交按钮禁用', async ({ page }) => {
    const submitBtn = page.getByRole('button', { name: '提交解析' })
    await expect(submitBtn).toBeVisible({ timeout: 5000 })
    await expect(submitBtn).toBeDisabled()
  })

  test('输入文本后提交按钮可用', async ({ page }) => {
    const textarea = page.locator('textarea[placeholder*="粘贴面经"]')
    await textarea.fill('这是一段面试经历的内容')
    await page.waitForTimeout(200)
    const submitBtn = page.getByRole('button', { name: '提交解析' })
    await expect(submitBtn).toBeEnabled()
  })

  test('无效 URL 提交显示错误提示', async ({ page }) => {
    await page.locator('input[placeholder="https://..."]').fill('not-a-valid-url')
    const textarea = page.locator('textarea[placeholder*="粘贴面经"]')
    await textarea.fill('测试内容')
    await page.getByRole('button', { name: '提交解析' }).click()
    await page.waitForTimeout(500)
    const body = await page.locator('body').textContent()
    expect(body.includes('链接') || body.includes('URL') || body.includes('格式') || body.includes('错误')).toBeTruthy()
  })

  test('提交后显示实时任务进度列表', async ({ page }) => {
    // Mock 后台 Job 创建 + SSE 进度流
    await page.route('**/api/submit-jobs', async (route) => {
      await route.fulfill({ status: 200, json: { job_id: 321, status: 'pending', message: '上传任务已创建' } })
    })
    await page.route('**/api/jobs/321/stream', async (route) => {
      // 不发送 done 事件，让任务停在 running 状态，进度中间态可稳定断言
      const sseBody = [
        'data: {"type":"progress","status":"running","current":1,"total":6,"message":"正在提取内容"}\n\n',
        'data: {"type":"progress","status":"running","current":2,"total":6,"message":"正在提取面试题"}\n\n',
      ].join('')
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
        body: sseBody,
      })
    })

    const textarea = page.locator('textarea[placeholder*="粘贴面经"]')
    await textarea.fill('字节跳动一面：问了闭包、Promise、Vue响应式原理')
    await page.getByRole('button', { name: '提交解析' }).click()

    // 任务进度条目出现，带阶段文案和百分比（SiteHeader 顶栏也有全局任务按钮，需在条目内精确定位）
    await expect(page.locator('[data-testid="import-job-item"]')).toHaveCount(1, { timeout: 5000 })
    await expect(page.getByTestId('import-job-item').getByText('正在提取面试题')).toBeVisible()
    await expect(page.getByTestId('import-job-item').getByText('33%')).toBeVisible()
    // 头部徽标显示处理中数量
    await expect(page.getByText('1 个任务处理中')).toBeVisible()
  })

  test('拖入非图片文件提示忽略', async ({ page }) => {
    await page.locator('input[type="file"]').setInputFiles({
      name: 'notes.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('hello world'),
    })
    await page.waitForTimeout(500)
    await expect(page.getByText('已忽略非图片文件：notes.txt')).toBeVisible({ timeout: 5000 })
  })

  test('清空非空内容需确认', async ({ page }) => {
    const textarea = page.locator('textarea[placeholder*="粘贴面经"]')
    await textarea.fill('测试内容')

    // 第一次点击清空 → 出现确认框，取消则内容保留
    await page.getByRole('button', { name: '清空' }).click()
    const dialog = page.getByRole('alertdialog')
    await expect(dialog).toBeVisible({ timeout: 5000 })
    await expect(dialog.getByText('确认清空')).toBeVisible()
    await dialog.getByRole('button', { name: '取消' }).click()
    await page.waitForTimeout(300)
    await expect(textarea).toHaveValue('测试内容')

    // 第二次点击清空 → 确认后清空
    await page.getByRole('button', { name: '清空' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: '清空' }).click()
    await page.waitForTimeout(300)
    await expect(textarea).toHaveValue('')
  })
})
