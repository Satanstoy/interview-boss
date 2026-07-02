import { expect, test } from '@playwright/test'

async function mockAuthenticatedShell(page) {
  await page.route('**/api/auth/refresh', async route => {
    await route.fulfill({
      json: {
        token: 'mock-token',
        user: { id: 1, username: 'tester', role: 'user', bank_mode: 'public' },
      },
    })
  })
  await page.route('**/api/auth/me', async route => {
    await route.fulfill({ json: { id: 1, username: 'tester', role: 'user', bank_mode: 'public' } })
  })
  await page.route('**/api/auth/bank-mode', async route => {
    await route.fulfill({ json: { status: 'success', bank_mode: 'public' } })
  })
  await page.route('**/api/profile**', async route => {
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/positions**', async route => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/master-bank**', async route => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/data/**', async route => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/analytics**', async route => {
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/practice/**', async route => {
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/practice-stats', async route => {
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/submit-jobs/active', async route => {
    await route.fulfill({ json: { status: 'success', data: [] } })
  })
  await page.route('**/api/interview**', async route => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/health', async route => {
    await route.fulfill({ json: { status: 'ok' } })
  })
}

async function mockChatThinkingStream(page) {
  await page.route('**/api/chat/conversations?status=active', async route => {
    await route.fulfill({
      json: {
        status: 'success',
        data: [{ id: 'conv-1', title: '模拟面试', mode: 'free_practice', updated_at: new Date().toISOString() }],
      },
    })
  })
  await page.route('**/api/chat/conversations/conv-1/messages', async route => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        json: {
          status: 'success',
          data: [
            {
              id: 1,
              role: 'assistant',
              content: '请先简单做一下自我介绍吧。',
              created_at: new Date().toISOString(),
              metadata: {},
            },
          ],
        },
      })
      return
    }

    const finalMetadata = {
      thinking_duration: 2.4,
      reasoning_trace: {
        summary: ['分析候选人的项目经历', '检索题库，获取本轮追问依据'],
        duration_ms: 2400,
        steps: [
          { step: 'load_skill', label: '加载策略', message: '加载项目深挖策略', reason: '候选人正在介绍项目经历', status: 'done' },
          { step: 'search_questions', label: '检索题库', message: '检索 Redis 相关面试题', reason: '需要基于真实题库追问缓存项目', status: 'done' },
        ],
        tool_count: 1,
        skill_count: 1,
      },
      tool_calls_trace: [
        {
          tool_name: 'search_questions',
          label: '检索题库',
          status: 'success',
          elapsed_ms: 86,
          result_count: 1,
          args: { keywords: ['Redis'], limit: 5 },
          result_preview: [
            {
              id: 101,
              question: 'Redis 缓存穿透怎么处理？',
              cat1: '中间件',
              cat2: '缓存',
              company: '腾讯',
              round: '一面',
            },
          ],
          summary: '命中 1 道 Redis 缓存题',
        },
      ],
      skill_trace: [
        {
          skill_name: 'project-deep-dive',
          label: '项目深挖策略',
          reason: '候选人正在介绍项目，需要追问职责、架构和取舍',
          status: 'loaded',
        },
      ],
    }

    const body = [
      'data: {"type":"thinking_start","content":""}',
      'data: {"type":"thinking","content":"分析候选人的项目经历"}',
      'data: {"type":"step","step":"load_skill","message":"加载项目深挖策略","reason":"候选人正在介绍项目经历"}',
      'data: {"type":"tool_step","data":{"step":"search_questions","tool_name":"search_questions","message":"正在检索题库...","elapsed_ms":86,"result_count":1}}',
      'data: {"type":"chunk","content":"我们先沿着你的缓存项目追问一下。"}',
      'data: {"type":"thinking_done","duration":2.4,"content":"分析候选人的项目经历"}',
      `data: ${JSON.stringify({ type: 'done', metadata: finalMetadata })}`,
    ].join('\n') + '\n'

    await new Promise(resolve => setTimeout(resolve, 1200))
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
      body,
    })
  })
}

test('chat thinking timeline shows live seconds while streaming and final duration after done', async ({ page }) => {
  await mockAuthenticatedShell(page)
  await mockChatThinkingStream(page)

  await page.goto('/chat', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('main')
  await page.getByText('自由练习 · 刚刚').click()
  await page.getByRole('textbox').fill('我主要做后端，负责订单查询和 Redis 缓存优化。')
  await page.keyboard.press('Enter')

  await expect(page.getByText(/思考中 \d+ 秒/)).toBeVisible({ timeout: 2500 })
  await expect(page.getByText('思考了 2.4 秒')).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: /思考了 2\.4 秒/ }).click()
  await expect(page.getByText('项目深挖策略', { exact: true })).toBeVisible()
  await expect(page.getByText('检索题库').first()).toBeVisible()

  await page.getByRole('button', { name: /检索题库/ }).click()
  await expect(page.getByText('Redis 缓存穿透怎么处理？')).toBeVisible()
  await expect(page.getByText('Redis').first()).toBeVisible()
  await expect(page.getByText('我们先沿着你的缓存项目追问一下。')).toBeVisible()
})
