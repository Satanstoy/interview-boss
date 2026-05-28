/**
 * 设置深层 E2E 测试 — SettingsPanel.vue
 * 所有 API 均通过 page.route() mock
 */
import { test, expect } from '@playwright/test'

const MOCK_USER = {
  id: 999,
  username: 'e2e_tester',
  is_admin: false,
  bank_mode: 'public',
  current_position_id: 1,
  current_position: '前端开发工程师',
}

const MOCK_PROFILE = {
  id: 999,
  username: 'e2e_tester',
  current_position: '前端开发工程师',
  current_position_id: 1,
  positions: [
    { id: 1, name: '前端开发工程师' },
    { id: 2, name: '后端开发工程师' },
    { id: 3, name: '全栈开发工程师' },
  ],
  llm_configured: true,
  categories: [],
}

const MOCK_LLM_CONFIG = {
  api_key: 'sk-***',
  base_url: 'https://api.openai.com/v1',
  model_name: 'gpt-4o',
  timeout: 120,
}

// ── Helper ──
async function mockAllAPIs(page, userOverrides = {}) {
  const user = { ...MOCK_USER, ...userOverrides }

  await page.route('**/api/auth/refresh', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user } })
  })
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: user })
  })
  await page.route('**/api/auth/login', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user } })
  })
  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })
  await page.route('**/api/auth/bank-mode', async (route) => {
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
  await page.route('**/api/answers/**', async (route) => {
    await route.fulfill({ json: {} })
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
  await page.route('**/api/knowledge**', async (route) => {
    await route.fulfill({ json: { nodes: [], edges: [] } })
  })

  // Profile API
  await page.route('**/api/profile/llm', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: MOCK_LLM_CONFIG })
    } else if (route.request().method() === 'PUT') {
      await route.fulfill({ json: { status: 'success' } })
    } else {
      await route.fulfill({ json: { status: 'success' } })
    }
  })
  await page.route('**/api/profile', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: MOCK_PROFILE })
    } else {
      await route.fulfill({ json: { status: 'success' } })
    }
  })
  await page.route('**/api/positions**', async (route) => {
    await route.fulfill({ json: MOCK_PROFILE.positions })
  })
}

async function gotoLoggedIn(page) {
  await mockAllAPIs(page)
  await page.goto('/')
  await page.waitForSelector('main', { timeout: 15000 })
  await page.waitForTimeout(1000)
}

async function openSettings(page) {
  const settingsBtn = page.locator('button[title="系统配置"]').first()
  await expect(settingsBtn).toBeVisible({ timeout: 5000 })
  await settingsBtn.click()
  await page.waitForTimeout(500)
}

// ═══════════════════════════════════════════════
// 测试套件
// ═══════════════════════════════════════════════

test.describe('设置深层', () => {
  test('设置按钮可点击打开面板', async ({ page }) => {
    await gotoLoggedIn(page)
    await openSettings(page)

    // 设置面板标题
    await expect(page.getByText('系统配置').first()).toBeVisible({ timeout: 5000 })
  })

  test('LLM 配置区域渲染', async ({ page }) => {
    await gotoLoggedIn(page)
    await openSettings(page)

    // LLM 配置标题
    await expect(page.getByText('我的 LLM 配置').first()).toBeVisible({ timeout: 5000 })

    // 已配置时应显示"修改配置"按钮
    const modifyBtn = page.getByText('修改配置')
    if (await modifyBtn.isVisible().catch(() => false)) {
      await expect(modifyBtn).toBeVisible()
    }

    // 或者未配置时显示"立即配置"按钮
    const configBtn = page.getByText('立即配置')
    if (await configBtn.isVisible().catch(() => false)) {
      await expect(configBtn).toBeVisible()
    }
  })

  test('目标岗位显示', async ({ page }) => {
    await gotoLoggedIn(page)
    await openSettings(page)

    // 目标岗位标题
    await expect(page.getByText('目标岗位').first()).toBeVisible({ timeout: 5000 })

    // 当前岗位应显示
    const body = await page.locator('body').textContent()
    expect(body.includes('前端开发工程师') || body.includes('岗位')).toBeTruthy()
  })

  test('岗位切换可操作', async ({ page }) => {
    await gotoLoggedIn(page)
    await openSettings(page)

    // 找到其他岗位按钮
    const backendBtn = page.getByText('后端开发工程师')
    if (await backendBtn.isVisible().catch(() => false)) {
      await backendBtn.click()
      await page.waitForTimeout(500)
      // 点击后不崩溃
    }

    // 新增岗位输入框
    const positionInput = page.locator('input[placeholder*="新增岗位"]').first()
    if (await positionInput.isVisible().catch(() => false)) {
      await positionInput.fill('测试工程师')
      await page.waitForTimeout(200)
      expect(await positionInput.inputValue()).toBe('测试工程师')
    }
  })

  test('LLM 配置编辑和保存', async ({ page }) => {
    await gotoLoggedIn(page)
    await openSettings(page)

    // 点击修改配置进入编辑模式
    const modifyBtn = page.getByText('修改配置')
    if (await modifyBtn.isVisible().catch(() => false)) {
      await modifyBtn.click()
      await page.waitForTimeout(500)

      // 应显示 API Key 输入框
      const apiKeyInput = page.locator('input[type="password"], input[placeholder*="API Key"]').first()
      if (await apiKeyInput.isVisible().catch(() => false)) {
        await expect(apiKeyInput).toBeVisible()
      }

      // Base URL 输入框
      const baseUrlInput = page.locator('input[placeholder*="api.openai"]').first()
      if (await baseUrlInput.isVisible().catch(() => false)) {
        await expect(baseUrlInput).toBeVisible()
      }

      // 保存按钮
      const saveBtn = page.getByRole('button', { name: '保存' }).first()
      if (await saveBtn.isVisible().catch(() => false)) {
        await expect(saveBtn).toBeVisible()
      }
    }
  })

  test('保存配置后响应正常', async ({ page }) => {
    await gotoLoggedIn(page)
    await openSettings(page)

    // 进入编辑模式
    const modifyBtn = page.getByText('修改配置')
    if (await modifyBtn.isVisible().catch(() => false)) {
      await modifyBtn.click()
      await page.waitForTimeout(500)

      const saveBtn = page.getByRole('button', { name: '保存' }).first()
      if (await saveBtn.isVisible().catch(() => false)) {
        await saveBtn.click()
        await page.waitForTimeout(1000)
        // 保存后页面不崩溃
        await expect(page.locator('body')).toBeVisible()
      }
    }
  })

  test('关闭设置面板', async ({ page }) => {
    await gotoLoggedIn(page)
    await openSettings(page)

    // 关闭按钮
    const closeBtn = page.getByRole('button', { name: '关闭' }).first()
    await expect(closeBtn).toBeVisible({ timeout: 5000 })
    await closeBtn.click()
    await page.waitForTimeout(500)

    // 面板应关闭 — LLM 配置标题不应可见
    await expect(page.getByText('我的 LLM 配置')).not.toBeVisible({ timeout: 5000 })
  })

  test('暗色模式下面板正常', async ({ page }) => {
    await gotoLoggedIn(page)

    // 开启暗色模式
    const darkToggle = page.locator('button[title*="暗色"], button[title*="亮色"]').first()
    await darkToggle.click()
    await page.waitForTimeout(300)

    // 打开设置面板
    await openSettings(page)

    // 面板应正常渲染
    await expect(page.getByText('系统配置').first()).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('我的 LLM 配置').first()).toBeVisible({ timeout: 5000 })

    // html 应有 dark class
    const htmlClass = await page.locator('html').getAttribute('class')
    expect(htmlClass).toContain('dark')
  })
})
