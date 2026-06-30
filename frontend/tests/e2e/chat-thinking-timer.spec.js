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

    const body = [
      'data: {"type":"thinking_start","content":""}',
      'data: {"type":"thinking","content":"分析候选人的项目经历"}',
      'data: {"type":"chunk","content":"我们先沿着你的缓存项目追问一下。"}',
      'data: {"type":"thinking_done","duration":2.4,"content":"分析候选人的项目经历"}',
      'data: {"type":"done"}',
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
  await expect(page.getByText('我们先沿着你的缓存项目追问一下。')).toBeVisible()
})
