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
  // Mock all chat API requests to prevent leaking to real backend
  await page.route('**/api/chat**', async route => {
    const url = route.request().url()
    const method = route.request().method()

    // GET /api/chat/conversations?status=active
    if (url.includes('/conversations') && url.includes('status=active') && method === 'GET') {
      await route.fulfill({
        json: {
          status: 'success',
          data: [{ id: 'conv-1', title: '模拟面试', mode: 'free_practice', updated_at: new Date().toISOString() }],
        },
      })
      return
    }

    // GET /api/chat/conversations/conv-1/messages
    if (url.includes('/conversations/conv-1/messages') && method === 'GET') {
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

    // POST /api/chat/conversations (create conversation)
    if (url.includes('/conversations') && !url.includes('/messages') && method === 'POST') {
      await route.fulfill({
        json: { status: 'success', data: { id: 'mock-new-conv', title: '新对话' } },
      })
      return
    }

    // POST /api/chat/conversations/conv-1/messages (send message - SSE)
    if (url.includes('/conversations/conv-1/messages') && method === 'POST') {
      const finalMetadata = {
        thinking_duration: 2.4,
        reasoning_trace: {
          source: 'model_reasoning',
          summary: ['分析候选人的项目经历', '检索题库，获取本轮追问依据'],
          duration_ms: 2400,
          steps: [
            { step: 'loading', label: '加载历史', message: '正在加载对话历史...', status: 'done' },
            { step: 'context', label: '加载画像', message: '正在加载个人画像...', status: 'done' },
            { step: 'load_skill', label: '加载策略', message: '加载项目深挖策略', reason: '候选人正在介绍项目经历', status: 'done' },
            { step: 'search_questions', label: '检索题库', message: '检索 Redis 相关面试题', reason: '需要基于真实题库追问缓存项目', status: 'done' },
          ],
          tool_count: 1,
          skill_count: 1,
        },
        thinking: [
          {
            chunks: ['候选人提到了 Redis，需要检索缓存相关题目。'],
            duration_ms: 2400,
          },
        ],
        tool_calls_trace: [
          {
            tool_name: 'search_questions',
            label: '检索题库',
            status: 'success',
            elapsed_ms: 86,
            result_count: 5,
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
              { id: 102, question: 'Redis 分布式锁如何实现？', cat1: '中间件', cat2: '缓存', company: '腾讯', round: '二面' },
              { id: 103, question: 'Redis 缓存击穿怎么处理？', cat1: '中间件', cat2: '缓存', company: '美团', round: '三面' },
              { id: 104, question: 'Redis 持久化策略有哪些？', cat1: '中间件', cat2: '缓存', company: '阿里', round: '四面' },
              { id: 105, question: 'Redis 大 key 怎么治理？', cat1: '中间件', cat2: '缓存', company: '字节', round: '五面' },
            ],
            summary: '命中 5 道 Redis 缓存题',
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
        'data: {"type":"thinking","content":"候选人提到了 Redis，需要检索缓存相关题目。"}',
        'data: {"type":"step","step":"loading","message":"正在加载对话历史..."}',
        'data: {"type":"step","step":"context","message":"正在加载个人画像..."}',
        'data: {"type":"step","step":"load_skill","message":"加载项目深挖策略","reason":"候选人正在介绍项目经历"}',
        'data: {"type":"tool_step","data":{"step":"search_questions","tool_name":"search_questions","message":"正在检索题库...","elapsed_ms":86,"result_count":5}}',
        'data: {"type":"chunk","content":"我们先沿着你的缓存项目追问一下。"}',
        'data: {"type":"thinking_done","duration":2.4,"content":"候选人提到了 Redis，需要检索缓存相关题目。"}',
        `data: ${JSON.stringify({ type: 'done', metadata: finalMetadata })}`,
      ].join('\n') + '\n'

      await new Promise(resolve => setTimeout(resolve, 1200))
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
        body,
      })
      return
    }

    // Default: catch any other chat API requests
    await route.fulfill({ json: { status: 'success', data: [] } })
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

  await expect(page.getByText(/面试官推理中 \d+ 秒/)).toBeVisible({ timeout: 2500 })
  await expect(page.getByText('面试官推理了 2.4 秒')).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: /面试官推理了 2\.4 秒/ }).click()
  await expect(page.getByText('正在加载对话历史...')).toHaveCount(0)
  await expect(page.getByText('正在加载个人画像...')).toHaveCount(0)
  await expect(page.getByText('候选人提到了 Redis，需要检索缓存相关题目。')).toBeVisible()
  await expect(page.getByText('项目深挖策略', { exact: true })).toBeVisible()
  await expect(page.getByText('检索题库').first()).toBeVisible()
  const connector = page.locator('.reasoning-timeline-connector').first()
  await expect(connector).toBeVisible()
  const timelineMarker = connector.locator('xpath=following-sibling::span[1]')
  const centerDelta = await connector.evaluate((line) => {
    const marker = line.nextElementSibling
    if (!marker) return Number.NaN
    const lineRect = line.getBoundingClientRect()
    const markerRect = marker.getBoundingClientRect()
    return Math.abs((lineRect.left + lineRect.width / 2) - (markerRect.left + markerRect.width / 2))
  })
  await expect(timelineMarker).toBeVisible()
  expect(centerDelta).toBeLessThan(0.5)

  await page.getByRole('button', { name: /检索题库/ }).click()
  await expect(page.getByText('Redis 缓存穿透怎么处理？')).toBeVisible()
  await expect(page.getByText('Redis 大 key 怎么治理？')).toBeVisible()
  await expect(page.getByText('Redis').first()).toBeVisible()
  await expect(page.getByText('我们先沿着你的缓存项目追问一下。')).toBeVisible()
})
