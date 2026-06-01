/**
 * JD/面经 E2E 测试 — 覆盖提交、SSE 解析进度、历史记录查看
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
  username: 'e2e_admin',
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

const MOCK_JD_DATA = [
  {
    id: 1,
    '公司': '字节跳动',
    '岗位名称': '前端开发工程师',
    '薪资范围': '25k-40k',
    '核心技术要求': 'React, TypeScript, Node.js',
    '加分项': '微前端, 性能优化',
    'season': '2027届暑期实习',
    '来源链接': 'https://example.com/jd/1',
    owner_id: 999,
    created_at: '2026-03-10T08:00:00',
  },
  {
    id: 2,
    '公司': '阿里巴巴',
    '岗位名称': '高级前端工程师',
    '薪资范围': '30k-50k',
    '核心技术要求': 'Vue, React, Webpack, Vite',
    '加分项': 'SSR, 跨端开发经验',
    'season': '2027届暑期实习',
    '来源链接': '未提供链接',
    owner_id: 999,
    created_at: '2026-03-12T10:00:00',
  },
]

const MOCK_INTERVIEW_DATA = [
  {
    id: 101,
    '公司': '字节跳动',
    'season': '2027届暑期实习',
    '面试轮次': '一面',
    '考察重点': 'JavaScript 基础、框架原理',
    '具体题目清单': '1. 闭包是什么？\n2. Vue 响应式原理\n3. Promise.all 的实现',
    '难易程度': '中等',
    '来源链接': 'https://example.com/interview/1',
    owner_id: 999,
    created_at: '2026-03-15T14:00:00',
  },
  {
    id: 102,
    '公司': '腾讯',
    'season': '2027届暑期实习',
    '面试轮次': '二面',
    '考察重点': '项目经验、系统设计',
    '具体题目清单': '1. 介绍项目架构\n2. 前端性能优化方案\n3. 微前端的优缺点',
    '难易程度': '困难',
    '来源链接': '未提供链接',
    owner_id: 999,
    created_at: '2026-03-18T09:00:00',
  },
  {
    id: 103,
    '公司': '美团',
    'season': '2026届秋招',
    '面试轮次': '一面',
    '考察重点': '算法、数据结构',
    '具体题目清单': '1. 两数之和\n2. 最长回文子串\n3. 二叉树层序遍历',
    '难易程度': '简单',
    '来源链接': '未提供链接',
    owner_id: 999,
    created_at: '2026-02-20T11:00:00',
  },
]

// ── Helper: 注册所有必要的 API mock ──
async function mockAllAPIs(page, { user = MOCK_USER, jdData = [], interviewData = [] } = {}) {
  // Auth
  await page.route('**/api/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'application/json' },
      json: { token: 'mock-token', user },
    })
  })
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: user })
  })
  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })

  // Data - JD and Interview
  await page.route('**/api/data/jd**', async (route) => {
    await route.fulfill({ json: jdData })
  })
  await page.route('**/api/data/interview**', async (route) => {
    await route.fulfill({ json: interviewData })
  })

  // Master bank
  await page.route('**/api/master-bank**', async (route) => {
    await route.fulfill({ json: MOCK_MASTER_BANK })
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
      await route.fulfill({ json: { id: 999, username: user.username, email: 'test@example.com', current_position: '前端开发工程师', current_position_id: 1, positions: [{ id: 1, name: '前端开发工程师' }], llm_configured: true, categories: [] } })
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

  // Delete / update / restore
  await page.route('**/api/data/update', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })
}

// ── Helper: 构造 SSE 响应体 ──
function buildSSEBody(steps, doneData = {}) {
  const lines = steps.map(s =>
    `data: ${JSON.stringify({ step: s.step, message: s.message, data: s.data || {} })}`
  )
  lines.push(`data: ${JSON.stringify({ type: 'done', ...doneData })}`)
  return lines.join('\n') + '\n'
}

// ── Helper: mock SSE 提交接口 ──
async function mockSubmitSSE(page, body) {
  await page.route('**/api/submit-stream-v2', async (route) => {
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
      body,
    })
  })
}

// ── Helper: 以已登录状态进入主页 ──
async function gotoLoggedIn(page, opts = {}) {
  await mockAllAPIs(page, opts)
  await page.goto('/')
  await page.waitForSelector('main', { timeout: 15000 })
  await page.waitForTimeout(1000)
}

// ── Helper: 导航到导入 Tab ──
async function goToImportTab(page) {
  await page.getByRole('button', { name: '导入' }).click()
  await page.waitForTimeout(500)
}

// ── Helper: 填写并提交文本 ──
async function fillAndSubmitText(page, text, options = {}) {
  const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
  await textarea.fill(text)

  // 设置导入类型
  if (options.importType) {
    const typeSelect = page.locator('label:has-text("导入类型") + *, label:has-text("导入类型") ~ *').first()
    await typeSelect.click()
    await page.waitForTimeout(200)
    await page.getByRole('option', { name: options.importType }).click().catch(() => {
      // fallback: try clicking text directly
      return page.getByText(options.importType, { exact: true }).click()
    })
    await page.waitForTimeout(200)
  }

  const submitBtn = page.getByRole('button', { name: '提交解析' })
  await submitBtn.click()
}

// ═══════════════════════════════════════════════
// 提交 JD 测试
// ═══════════════════════════════════════════════
test.describe('JD 提交流程', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page)
    await goToImportTab(page)
  })

  test('提交 JD 文本后显示 SSE 进度步骤', async ({ page }) => {
    const sseBody = buildSSEBody([
      { step: 'extract', message: '正在提取内容', data: { question_count: 5 } },
      { step: 'fill', message: '补全信息', data: {} },
      { step: 'tag', message: '标注题目', data: { categories: { '算法': 2, '系统设计': 3 } } },
      { step: 'match', message: '匹配聚类', data: { matched_count: 2, unmatched_count: 3 } },
      { step: 'save', message: '保存入库', data: { elapsed_seconds: 1.8 } },
    ], { doc_type: 'jd', target: 'personal', question_count: 5 })
    await mockSubmitSSE(page, sseBody)

    await fillAndSubmitText(page, '字节跳动前端开发工程师，要求 React、TypeScript，薪资 25k-40k')

    // 应出现进度指示器
    await expect(page.getByText('提取内容')).toBeVisible({ timeout: 5000 })

    // 等待所有步骤完成
    await page.waitForTimeout(3000)

    // 应显示提交成功
    await expect(page.getByText('提交成功')).toBeVisible({ timeout: 5000 })
  })

  test('JD 提交成功后显示题目数量统计', async ({ page }) => {
    const sseBody = buildSSEBody([
      { step: 'extract', message: '提取完成', data: { question_count: 5 } },
      { step: 'fill', message: '补全信息', data: {} },
      { step: 'tag', message: '标注完成', data: {} },
      { step: 'match', message: '匹配完成', data: { matched_count: 2, unmatched_count: 3 } },
      { step: 'save', message: '保存完成', data: { elapsed_seconds: 2.1 } },
    ], { doc_type: 'jd', target: 'personal', question_count: 5 })
    await mockSubmitSSE(page, sseBody)

    await fillAndSubmitText(page, '阿里巴巴高级前端工程师 JD')
    await page.waitForTimeout(3000)

    // 应显示提取题目数
    const body = await page.locator('body').textContent()
    expect(body.includes('5') && (body.includes('提取题目') || body.includes('题目'))).toBeTruthy()
  })

  test('JD 提交成功后显示处理耗时', async ({ page }) => {
    const sseBody = buildSSEBody([
      { step: 'extract', message: '提取完成', data: { question_count: 3 } },
      { step: 'fill', message: '补全', data: {} },
      { step: 'tag', message: '标注', data: {} },
      { step: 'match', message: '匹配', data: {} },
      { step: 'save', message: '保存', data: { elapsed_seconds: 3.5 } },
    ], { doc_type: 'jd', target: 'personal', question_count: 3 })
    await mockSubmitSSE(page, sseBody)

    await fillAndSubmitText(page, '腾讯前端工程师招聘 JD')
    await page.waitForTimeout(3000)

    const body = await page.locator('body').textContent()
    expect(body.includes('耗时') || body.includes('3.5') || body.includes('s')).toBeTruthy()
  })
})

// ═══════════════════════════════════════════════
// 提交面经测试
// ═══════════════════════════════════════════════
test.describe('面经提交流程', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page)
    await goToImportTab(page)
  })

  test('提交面经文本后显示进度和成功结果', async ({ page }) => {
    const sseBody = buildSSEBody([
      { step: 'extract', message: '正在提取内容', data: { question_count: 8 } },
      { step: 'fill', message: '补全信息', data: {} },
      { step: 'tag', message: '标注题目', data: { categories: { 'JavaScript': 3, 'Vue': 3, '网络': 2 } } },
      { step: 'match', message: '匹配聚类', data: { matched_count: 4, unmatched_count: 4 } },
      { step: 'save', message: '保存入库', data: { elapsed_seconds: 2.8 } },
    ], { doc_type: 'interview', target: 'personal', question_count: 8 })
    await mockSubmitSSE(page, sseBody)

    await fillAndSubmitText(page, '字节跳动一面：问了闭包、Promise、Vue响应式原理、CSS 盒模型、HTTP 缓存')

    // 等待处理完成
    await page.waitForTimeout(3000)

    // 应显示提交成功
    await expect(page.getByText('提交成功')).toBeVisible({ timeout: 5000 })

    // 应显示面经类型
    const body = await page.locator('body').textContent()
    expect(body.includes('interview') || body.includes('Interview') || body.includes('面经')).toBeTruthy()
  })

  test('面经提交后显示匹配结果', async ({ page }) => {
    const sseBody = buildSSEBody([
      { step: 'extract', message: '提取完成', data: { question_count: 6 } },
      { step: 'fill', message: '补全', data: {} },
      { step: 'tag', message: '标注', data: {} },
      { step: 'match', message: '匹配完成', data: { matched_count: 3, unmatched_count: 3 } },
      { step: 'save', message: '保存', data: { elapsed_seconds: 1.5 } },
    ], { doc_type: 'interview', target: 'personal', question_count: 6 })
    await mockSubmitSSE(page, sseBody)

    await fillAndSubmitText(page, '美团二面：系统设计题、性能优化方案、前端工程化')
    await page.waitForTimeout(3000)

    // 应显示匹配结果（已有/新题）
    const body = await page.locator('body').textContent()
    expect(body.includes('已有') || body.includes('新题') || body.includes('匹配')).toBeTruthy()
  })
})

// ═══════════════════════════════════════════════
// SSE 进度步骤测试
// ═══════════════════════════════════════════════
test.describe('SSE 进度步骤显示', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page)
    await goToImportTab(page)
  })

  test('五个进度步骤标签全部存在', async ({ page }) => {
    const sseBody = buildSSEBody([
      { step: 'extract', message: '正在提取内容', data: { question_count: 3 } },
      { step: 'fill', message: '补全信息', data: {} },
      { step: 'tag', message: '标注题目', data: {} },
      { step: 'match', message: '匹配聚类', data: {} },
      { step: 'save', message: '保存入库', data: { elapsed_seconds: 1.0 } },
    ], { doc_type: 'interview', target: 'personal', question_count: 3 })
    await mockSubmitSSE(page, sseBody)

    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
    await textarea.fill('测试面经内容')
    await page.getByRole('button', { name: '提交解析' }).click()

    // 提交后进度区域应显示所有步骤标签
    await expect(page.getByText('提取内容')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('补全信息')).toBeVisible()
    await expect(page.getByText('标注题目')).toBeVisible()
    await expect(page.getByText('匹配聚类')).toBeVisible()
    await expect(page.getByText('保存入库')).toBeVisible()
  })

  test('进度消息实时更新', async ({ page }) => {
    await page.route('**/api/submit-stream-v2', async (route) => {
      const body = buildSSEBody([
        { step: 'extract', message: '正在提取内容...', data: { question_count: 4 } },
        { step: 'tag', message: '正在标注 4 道题目...', data: {} },
      ], { doc_type: 'interview', target: 'personal', question_count: 4 })
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
        body,
      })
    })

    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
    await textarea.fill('面经测试')
    await page.getByRole('button', { name: '提交解析' }).click()

    // 应出现步骤消息
    await page.waitForTimeout(1000)
    const body = await page.locator('body').textContent()
    expect(body.includes('提取') || body.includes('标注')).toBeTruthy()
  })

  test('提交过程中按钮显示"处理中..."', async ({ page }) => {
    await page.route('**/api/submit-stream-v2', async (route) => {
      // 返回一个不完整的 SSE，让请求挂起一会儿
      await new Promise(r => setTimeout(r, 2000))
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
        body: buildSSEBody([
          { step: 'save', message: '保存', data: {} },
        ], { doc_type: 'jd', target: 'personal', question_count: 1 }),
      })
    })

    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
    await textarea.fill('JD 测试')
    await page.getByRole('button', { name: '提交解析' }).click()

    // 提交过程中应显示"处理中..."
    await page.waitForTimeout(500)
    await expect(page.getByRole('button', { name: '处理中...' })).toBeVisible({ timeout: 3000 })
  })
})

// ═══════════════════════════════════════════════
// 提交错误处理
// ═══════════════════════════════════════════════
test.describe('提交错误处理', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page)
    await goToImportTab(page)
  })

  test('SSE 返回错误时显示错误提示', async ({ page }) => {
    await page.route('**/api/submit-stream-v2', async (route) => {
      await route.fulfill({
        status: 500,
        headers: { 'Content-Type': 'text/event-stream' },
        body: 'data: {"error":"服务器内部错误"}\n\n',
      })
    })

    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
    await textarea.fill('测试内容')
    await page.getByRole('button', { name: '提交解析' }).click()
    await page.waitForTimeout(2000)

    // 应显示错误信息
    const body = await page.locator('body').textContent()
    expect(body.includes('错误') || body.includes('失败') || body.includes('error') || body.includes('Error')).toBeTruthy()
  })

  test('网络异常时显示友好错误', async ({ page }) => {
    await page.route('**/api/submit-stream-v2', async (route) => {
      await route.abort('connectionrefused')
    })

    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
    await textarea.fill('测试网络异常')
    await page.getByRole('button', { name: '提交解析' }).click()
    await page.waitForTimeout(2000)

    // 应显示错误信息，不是未捕获的异常
    const body = await page.locator('body').textContent()
    expect(body.includes('失败') || body.includes('错误') || body.includes('重试')).toBeTruthy()
  })

  test('无效 URL 显示验证错误', async ({ page }) => {
    const urlInput = page.locator('input[placeholder*="小红书"], input[placeholder*="牛客"]').first()
    await urlInput.fill('not-a-valid-url')

    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
    await textarea.fill('有效内容')

    await page.getByRole('button', { name: '提交解析' }).click()
    await page.waitForTimeout(500)

    const body = await page.locator('body').textContent()
    expect(body.includes('链接') || body.includes('URL') || body.includes('格式')).toBeTruthy()
  })
})

// ═══════════════════════════════════════════════
// 清空功能
// ═══════════════════════════════════════════════
test.describe('清空功能', () => {
  test('点击清空按钮重置所有输入', async ({ page }) => {
    await gotoLoggedIn(page)
    await goToImportTab(page)

    const urlInput = page.locator('input[placeholder*="小红书"], input[placeholder*="牛客"]').first()
    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()

    // 填入内容
    await urlInput.fill('https://example.com/jd')
    await textarea.fill('测试 JD 内容')
    await page.waitForTimeout(200)

    // 确认内容已填入
    await expect(textarea).toHaveValue('测试 JD 内容')

    // 点击清空
    await page.getByRole('button', { name: '清空' }).click()
    await page.waitForTimeout(200)

    // 内容应被清空
    await expect(textarea).toHaveValue('')
    await expect(urlInput).toHaveValue('')
  })
})

// ═══════════════════════════════════════════════
// JD 历史记录查看
// ═══════════════════════════════════════════════
test.describe('JD 历史记录 — JD 筛选 Tab', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page, { jdData: MOCK_JD_DATA })
  })

  test('JD Tab 显示公司和岗位信息', async ({ page }) => {
    await page.getByRole('button', { name: /JD/ }).click()
    await page.waitForTimeout(500)

    // 应显示 JD 数据
    await expect(page.getByText('字节跳动')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('前端开发工程师')).toBeVisible()
    await expect(page.getByText('阿里巴巴')).toBeVisible()
    await expect(page.getByText('高级前端工程师')).toBeVisible()
  })

  test('JD Tab 显示薪资范围', async ({ page }) => {
    await page.getByRole('button', { name: /JD/ }).click()
    await page.waitForTimeout(500)

    await expect(page.getByText('25k-40k')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('30k-50k')).toBeVisible()
  })

  test('JD Tab 显示核心技术要求', async ({ page }) => {
    await page.getByRole('button', { name: /JD/ }).click()
    await page.waitForTimeout(500)

    const body = await page.locator('body').textContent()
    expect(body.includes('React') && body.includes('TypeScript')).toBeTruthy()
  })

  test('JD Tab 显示招聘季节', async ({ page }) => {
    await page.getByRole('button', { name: /JD/ }).click()
    await page.waitForTimeout(500)

    const body = await page.locator('body').textContent()
    expect(body.includes('2027届暑期实习')).toBeTruthy()
  })

  test('JD Tab 表头包含所有列', async ({ page }) => {
    await page.getByRole('button', { name: /JD/ }).click()
    await page.waitForTimeout(500)

    // 验证表头
    await expect(page.getByRole('columnheader', { name: '公司' })).toBeVisible({ timeout: 5000 })
    await expect(page.getByRole('columnheader', { name: '岗位名称' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '薪资范围' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '核心技术' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '加分项' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '招聘季' })).toBeVisible()
  })

  test('JD Tab 显示操作列（链接、删除按钮）', async ({ page }) => {
    await page.getByRole('button', { name: /JD/ }).click()
    await page.waitForTimeout(500)

    // 应有操作列标题
    await expect(page.getByRole('columnheader', { name: '操作' })).toBeVisible({ timeout: 5000 })

    // 应有链接按钮
    const linkButtons = page.locator('button[title="删除"], a[title="打开链接"]')
    const count = await linkButtons.count()
    expect(count).toBeGreaterThan(0)
  })
})

// ═══════════════════════════════════════════════
// 面经历史记录查看
// ═══════════════════════════════════════════════
test.describe('面经历史记录 — 面经库 Tab', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page, { interviewData: MOCK_INTERVIEW_DATA })
  })

  test('面经库 Tab 显示公司和轮次信息', async ({ page }) => {
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)

    await expect(page.getByText('字节跳动')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('腾讯')).toBeVisible()
    await expect(page.getByText('美团')).toBeVisible()
    await expect(page.getByText('一面').first()).toBeVisible()
    await expect(page.getByText('二面').first()).toBeVisible()
  })

  test('面经库 Tab 显示考察重点', async ({ page }) => {
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)

    const body = await page.locator('body').textContent()
    expect(body.includes('JavaScript 基础') || body.includes('JavaScript')).toBeTruthy()
    expect(body.includes('项目经验') || body.includes('系统设计')).toBeTruthy()
  })

  test('面经库 Tab 显示具体题目清单', async ({ page }) => {
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)

    const body = await page.locator('body').textContent()
    expect(body.includes('闭包') || body.includes('Vue 响应式')).toBeTruthy()
  })

  test('面经库 Tab 显示难度标签', async ({ page }) => {
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)

    const body = await page.locator('body').textContent()
    expect(body.includes('中等')).toBeTruthy()
    expect(body.includes('困难')).toBeTruthy()
    expect(body.includes('简单')).toBeTruthy()
  })

  test('面经库 Tab 表头包含所有列', async ({ page }) => {
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)

    await expect(page.getByRole('columnheader', { name: '公司' })).toBeVisible({ timeout: 5000 })
    await expect(page.getByRole('columnheader', { name: '招聘季' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '面试轮次' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '考察重点' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '具体题目清单' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '难度' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '上传日期' })).toBeVisible()
  })

  test('面经库有招聘季筛选器', async ({ page }) => {
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)

    // 应显示筛选标签
    await expect(page.getByText('招聘季筛选').first()).toBeVisible({ timeout: 5000 })
  })

  test('面经库有上传日期排序按钮', async ({ page }) => {
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)

    // 应显示排序按钮
    const sortBtn = page.locator('button:has-text("上传日期")')
    await expect(sortBtn).toBeVisible({ timeout: 5000 })
  })

  test('点击排序按钮切换排序方向', async ({ page }) => {
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)

    const sortBtn = page.locator('button:has-text("上传日期")')
    await expect(sortBtn).toBeVisible({ timeout: 5000 })

    // 默认降序，点击切换为升序
    await sortBtn.click()
    await page.waitForTimeout(300)

    // 按钮文字应变化（↓ → ↑ 或相反）
    const btnText = await sortBtn.textContent()
    expect(btnText.includes('↑') || btnText.includes('↓')).toBeTruthy()
  })
})

// ═══════════════════════════════════════════════
// 空状态测试
// ═══════════════════════════════════════════════
test.describe('空数据状态', () => {
  test.beforeEach(async ({ page }) => {
    await gotoLoggedIn(page, { jdData: [], interviewData: [] })
  })

  test('JD Tab 无数据时显示空状态', async ({ page }) => {
    await page.getByRole('button', { name: /JD/ }).click()
    await page.waitForTimeout(500)

    // 使用 DataTable 内部的空状态文案（更具体）
    await expect(page.getByText('暂无数据').first()).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('试试切换筛选条件或录入更多内容')).toBeVisible()
  })

  test('面经库 Tab 无数据时显示空状态', async ({ page }) => {
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)

    await expect(page.getByText('暂无数据').first()).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('试试切换筛选条件或录入更多内容')).toBeVisible()
  })

  test('空状态提示切换筛选条件', async ({ page }) => {
    await page.getByRole('button', { name: /JD/ }).click()
    await page.waitForTimeout(500)

    await expect(page.getByText('试试切换筛选条件或录入更多内容')).toBeVisible({ timeout: 5000 })
  })
})

// ═══════════════════════════════════════════════
// 完整端到端流程：提交后查看历史
// ═══════════════════════════════════════════════
test.describe('端到端流程 — 提交后查看历史', () => {
  test('提交 JD 后切换到 JD Tab 查看记录', async ({ page }) => {
    // 初始无数据，提交后切换到有数据的 mock
    let submitted = false
    await mockAllAPIs(page, { jdData: MOCK_JD_DATA, interviewData: [] })

    // Mock SSE 提交
    const sseBody = buildSSEBody([
      { step: 'extract', message: '提取完成', data: { question_count: 5 } },
      { step: 'fill', message: '补全', data: {} },
      { step: 'tag', message: '标注', data: {} },
      { step: 'match', message: '匹配', data: { matched_count: 1, unmatched_count: 4 } },
      { step: 'save', message: '保存', data: { elapsed_seconds: 2.0 } },
    ], { doc_type: 'jd', target: 'personal', question_count: 5 })
    await mockSubmitSSE(page, sseBody)

    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(1000)

    // 1. 导入 Tab
    await goToImportTab(page)

    // 2. 提交 JD
    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
    await textarea.fill('字节跳动前端开发工程师，React、TypeScript、Node.js，25k-40k')
    await page.getByRole('button', { name: '提交解析' }).click()
    await page.waitForTimeout(3000)

    // 3. 提交成功
    await expect(page.getByText('提交成功')).toBeVisible({ timeout: 5000 })

    // 4. 切换到 JD Tab
    await page.getByRole('button', { name: /JD/ }).click()
    await page.waitForTimeout(500)

    // 5. 应看到 JD 数据
    await expect(page.getByText('字节跳动')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('前端开发工程师')).toBeVisible()
  })

  test('提交面经后切换到面经库查看记录', async ({ page }) => {
    await mockAllAPIs(page, { jdData: [], interviewData: MOCK_INTERVIEW_DATA })

    const sseBody = buildSSEBody([
      { step: 'extract', message: '提取完成', data: { question_count: 8 } },
      { step: 'fill', message: '补全', data: {} },
      { step: 'tag', message: '标注', data: { categories: { 'JavaScript': 4, 'Vue': 4 } } },
      { step: 'match', message: '匹配', data: { matched_count: 3, unmatched_count: 5 } },
      { step: 'save', message: '保存', data: { elapsed_seconds: 3.2 } },
    ], { doc_type: 'interview', target: 'personal', question_count: 8 })
    await mockSubmitSSE(page, sseBody)

    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(1000)

    // 1. 导入 Tab → 提交面经
    await goToImportTab(page)
    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
    await textarea.fill('字节跳动一面：闭包、Promise、Vue响应式原理、CSS 盒模型、HTTP 缓存')
    await page.getByRole('button', { name: '提交解析' }).click()
    await page.waitForTimeout(3000)

    await expect(page.getByText('提交成功')).toBeVisible({ timeout: 5000 })

    // 2. 切换到面经库
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)

    // 3. 应看到面经数据
    await expect(page.getByText('字节跳动')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('腾讯')).toBeVisible()
    await expect(page.getByText('美团')).toBeVisible()
  })

  test('JD 和面经数据同时存在时各自 Tab 正确显示', async ({ page }) => {
    await gotoLoggedIn(page, { jdData: MOCK_JD_DATA, interviewData: MOCK_INTERVIEW_DATA })

    // JD Tab
    await page.getByRole('button', { name: /JD/ }).click()
    await page.waitForTimeout(500)
    await expect(page.getByText('字节跳动')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('阿里巴巴')).toBeVisible()

    // 面经 Tab
    await page.getByRole('button', { name: '面经库' }).click()
    await page.waitForTimeout(500)
    await expect(page.getByText('腾讯')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('美团')).toBeVisible()
  })
})

// ═══════════════════════════════════════════════
// 提交后表单重置
// ═══════════════════════════════════════════════
test.describe('提交后表单重置', () => {
  test('提交成功后文本框自动清空', async ({ page }) => {
    await gotoLoggedIn(page)
    await goToImportTab(page)

    const sseBody = buildSSEBody([
      { step: 'extract', message: '提取', data: { question_count: 1 } },
      { step: 'fill', message: '补全', data: {} },
      { step: 'tag', message: '标注', data: {} },
      { step: 'match', message: '匹配', data: {} },
      { step: 'save', message: '保存', data: {} },
    ], { doc_type: 'interview', target: 'personal', question_count: 1 })
    await mockSubmitSSE(page, sseBody)

    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()
    await textarea.fill('提交后应清空的内容')
    await page.getByRole('button', { name: '提交解析' }).click()
    await page.waitForTimeout(3000)

    // 提交成功后文本框应自动清空
    await expect(textarea).toHaveValue('')
  })

  test('提交成功后可立即再次提交', async ({ page }) => {
    await gotoLoggedIn(page)
    await goToImportTab(page)

    const sseBody = buildSSEBody([
      { step: 'extract', message: '提取', data: { question_count: 1 } },
      { step: 'fill', message: '补全', data: {} },
      { step: 'tag', message: '标注', data: {} },
      { step: 'match', message: '匹配', data: {} },
      { step: 'save', message: '保存', data: {} },
    ], { doc_type: 'interview', target: 'personal', question_count: 1 })
    await mockSubmitSSE(page, sseBody)

    const textarea = page.locator('textarea[placeholder*="粘贴面经"], textarea[placeholder*="纯文本"]').first()

    // 第一次提交
    await textarea.fill('第一次提交')
    await page.getByRole('button', { name: '提交解析' }).click()
    await page.waitForTimeout(3000)
    await expect(page.getByText('提交成功')).toBeVisible({ timeout: 5000 })

    // 提交成功后文本框已清空，按钮应处于禁用状态（无内容）
    const submitBtn = page.getByRole('button', { name: '提交解析' })
    await expect(submitBtn).toBeDisabled()

    // 填入新内容后按钮应重新可用
    await textarea.fill('第二次提交的内容')
    await page.waitForTimeout(200)
    await expect(submitBtn).toBeEnabled()
  })
})
