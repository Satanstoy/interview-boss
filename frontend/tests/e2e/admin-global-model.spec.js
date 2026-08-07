/**
 * 管理员全局模型配置 E2E — SettingsGlobalModel.vue
 * 所有 API 均通过 page.route() mock
 */
import { test, expect } from '@playwright/test'

const MOCK_USER = {
  id: 999,
  username: 'e2e_admin',
  is_admin: true,
  bank_mode: 'public',
  current_position_id: 1,
  current_position: '前端开发工程师',
}

const MOCK_PROFILE = {
  id: 999,
  username: 'e2e_admin',
  current_position: '前端开发工程师',
  current_position_id: 1,
  positions: [{ id: 1, name: '前端开发工程师' }],
  llm_configured: true,
  categories: [],
  settings: {
    llm_model: 'gpt-4o',
    llm_base_url: 'https://api.openai.com/v1',
    llm_api_key: 'sk-****abcd',
    llm_api_key_set: true,
    llm_timeout: '120',
  },
}

const MOCK_EMBEDDING = {
  settings: {
    backend: 'siliconflow',
    api_model: 'BAAI/bge-m3',
    api_key: 'sk-****abcd',
    api_key_set: true,
    dimension: '1024',
  },
}

async function mockAllAPIs(page) {
  await page.route('**/api/auth/refresh', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user: MOCK_USER } })
  })
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: MOCK_USER })
  })
  await page.route('**/api/auth/login', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user: MOCK_USER } })
  })
  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })

  await page.route('**/api/master-bank**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/data/**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/analytics**', async (route) => {
    await route.fulfill({ json: { total_questions: 0, practiced_questions: 0, tag_distribution: [], category_distribution: [] } })
  })
  await page.route('**/api/practice/**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/interview**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/chat**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/health', async (route) => {
    await route.fulfill({ json: { status: 'ok' } })
  })
  await page.route('**/api/bank-build**', async (route) => {
    await route.fulfill({ json: { status: 'idle' } })
  })
  await page.route('**/api/coding/**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/positions**', async (route) => {
    await route.fulfill({ json: MOCK_PROFILE.positions })
  })
  await page.route('**/api/practice-stats', async (route) => {
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/submit-jobs/active', async (route) => {
    await route.fulfill({ json: [] })
  })

  // 全局 profile 配置（含 embedding / 全局 LLM 测试连接，按 URL 分发）
  await page.route('**/api/profile**', async (route) => {
    const method = route.request().method()
    const url = route.request().url()
    if (url.includes('/embedding')) {
      if (method === 'PUT') {
        await route.fulfill({ json: { status: 'success', recompute_triggered: false, recompute_job_id: null } })
      } else {
        await route.fulfill({ json: MOCK_EMBEDDING })
      }
    } else if (url.includes('/llm/test-global')) {
      await route.fulfill({ json: { configured: true, connected: true, error: null, model: 'gpt-4o' } })
    } else {
      await route.fulfill({ json: MOCK_PROFILE })
    }
  })
}

async function gotoLoggedIn(page) {
  await mockAllAPIs(page)
  await page.goto('/')
  await page.waitForSelector('main', { timeout: 15000 })
  await page.waitForTimeout(1000)
}

async function openAdminSettings(page) {
  const settingsBtn = page.getByRole('button', { name: '设置' }).first()
  await expect(settingsBtn).toBeVisible({ timeout: 5000 })
  await settingsBtn.click()
  await page.waitForTimeout(500)
  await page.getByText('管理员设置').click()
  await page.waitForTimeout(500)
}

test.describe('管理员全局模型配置', () => {
  test('管理员设置出现模型配置 tab', async ({ page }) => {
    await gotoLoggedIn(page)
    await openAdminSettings(page)
    await expect(page.getByText('模型配置')).toBeVisible({ timeout: 5000 })
  })

  test('模型配置 tab 显示全局 LLM 和 embedding 表单', async ({ page }) => {
    await gotoLoggedIn(page)
    await openAdminSettings(page)
    await page.getByText('模型配置').click()
    await page.waitForTimeout(500)
    await expect(page.getByText('全局 LLM 配置')).toBeVisible()
    await expect(page.getByText('Embedding 配置')).toBeVisible()
    await expect(page.getByPlaceholder('gpt-4o')).toBeVisible()
  })

  test('embedding 后端切换显示对应字段', async ({ page }) => {
    await gotoLoggedIn(page)
    await openAdminSettings(page)
    await page.getByText('模型配置').click()
    await page.waitForTimeout(500)
    // siliconflow 模式显示模型名/API Key
    await expect(page.getByPlaceholder('BAAI/bge-m3')).toBeVisible()
    // 切到 ONNX 显示模型目录
    await page.locator('[role="combobox"]').first().click()
    await page.getByText('ONNX 本地模型').click()
    await expect(page.getByText('模型目录')).toBeVisible()
  })
})
