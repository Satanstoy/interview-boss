/**
 * 模型可用性守卫 E2E — 覆盖：
 * 1. 模型未配置时，Chat 发送消息前弹 Dialog 并引导到 /settings?section=ai
 * 2. 模型配置了但连接失败时，弹 Dialog 展示失败原因
 * 3. /settings?section=ai 直达 AI 配置区
 * 所有 API 均 mock，不依赖真实后端
 */
import { test, expect } from '@playwright/test'

const MOCK_USER = {
  id: 999,
  username: 'e2e_tester',
  is_admin: false,
  share_default: 'private',
  current_position_id: 1,
  current_position: '前端开发工程师',
}

async function mockAllAPIs(page) {
  const user = { ...MOCK_USER }

  await page.route('**/api/auth/login**', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user } })
  })
  await page.route('**/api/auth/me**', async (route) => {
    await route.fulfill({ json: user })
  })
  await page.route('**/api/auth/refresh**', async (route) => {
    await route.fulfill({ json: { token: 'mock-token-refreshed', user } })
  })
  await page.route('**/api/auth/logout**', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })
  await page.route('**/api/data/jd**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/data/interview**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/master-bank**', async (route) => {
    await route.fulfill({ json: { items: [], total: 0, overall_total: 0 } })
  })
  await page.route('**/api/analytics**', async (route) => {
    await route.fulfill({ json: { tech_trends: {} } })
  })
  await page.route('**/api/practice/stats**', async (route) => {
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/answers/**', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })
  await page.route('**/api/profile**', async (route) => {
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/profile/llm**', async (route) => {
    await route.fulfill({ json: { configured: false, settings: {} } })
  })
  await page.route('**/api/profile/llm/models**', async (route) => {
    await route.fulfill({ json: { models: [], current_model: '', error: null } })
  })
  await page.route('**/api/interview**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/submit-jobs/active**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/positions**', async (route) => {
    await route.fulfill({ json: [] })
  })
  // Chat API 通配符 mock，防止请求泄露到真实后端
  await page.route('**/api/chat**', async (route) => {
    const url = route.request().url()
    const method = route.request().method()

    if (url.includes('/conversations') && method === 'GET') {
      await route.fulfill({ json: { data: [{ id: 'conv-1', title: '模拟面试', mode: 'free_practice', updated_at: '2026-08-01T00:00:00Z' }] } })
    } else if (url.includes('/messages') && method === 'GET') {
      await route.fulfill({ json: { data: [] } })
    } else {
      await route.fulfill({ json: { status: 'success', data: [] } })
    }
  })
}

async function loginAndGoto(page, path) {
  await page.route('**/api/auth/refresh**', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user: MOCK_USER } })
  })
  await page.goto(path)
  await page.waitForTimeout(2000)
}

async function openChatInput(page) {
  // 选择 mock 对话后输入框才出现（避免与侧栏导航同名按钮混淆，用会话列表标题 div）
  await page.locator('div.truncate').filter({ hasText: '模拟面试' }).click()
  await page.waitForTimeout(600)
  const input = page.getByPlaceholder(/回答面试问题/)
  await expect(input).toBeVisible()
  await input.fill('你好')
  await page.keyboard.press('Enter')
  await page.waitForTimeout(600)
}

test.describe('模型可用性守卫', () => {
  test('模型未配置时 Chat 发送被拦截，Dialog 引导到设置页 AI 配置', async ({ page }) => {
    await mockAllAPIs(page)
    await page.route('**/api/profile/llm/status**', async (route) => {
      await route.fulfill({ json: { configured: false, connected: false, error: null, model: null } })
    })
    await loginAndGoto(page, '/chat')

    // 输入消息并发送（守卫应在发送前拦截）
    await openChatInput(page)

    // 守卫 Dialog 出现，且包含去配置按钮
    await expect(page.getByText('尚未配置 AI 模型')).toBeVisible()
    const goBtn = page.getByRole('button', { name: '去配置' })
    await expect(goBtn).toBeVisible()

    // 点击去配置 → 跳转 /settings?section=ai，显示 AI 配置区
    await goBtn.click()
    await page.waitForTimeout(1000)
    expect(new URL(page.url()).pathname).toBe('/settings')
    expect(new URL(page.url()).searchParams.get('section')).toBe('ai')
    await expect(page.getByRole('heading', { name: 'AI 配置' })).toBeVisible()
  })

  test('模型配置了但连接失败时 Dialog 展示失败原因', async ({ page }) => {
    await mockAllAPIs(page)
    await page.route('**/api/profile/llm/status**', async (route) => {
      await route.fulfill({ json: { configured: true, connected: false, error: '认证失败：请检查 API Key 是否正确', model: 'gpt-4o' } })
    })
    await loginAndGoto(page, '/chat')

    await openChatInput(page)

    await expect(page.getByText('模型服务未接通')).toBeVisible()
    await expect(page.getByText(/请检查 API Key 是否正确/)).toBeVisible()
  })

  test('/settings?section=ai 直达 AI 配置区', async ({ page }) => {
    await mockAllAPIs(page)
    await loginAndGoto(page, '/settings?section=ai')
    await page.waitForTimeout(1000)

    await expect(page.getByRole('heading', { name: 'AI 配置' }).first()).toBeVisible()
    await expect(page.getByText('配置大语言模型 API 连接参数')).toBeVisible()
  })
})
