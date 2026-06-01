/**
 * 登录注册完整 E2E 测试
 * 覆盖：邮箱登录、验证码发送、注册流程、错误处理（空邮箱、错误验证码等）
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

// ── Helper: mock 所有 API ──
async function mockAllAPIs(page) {
  await page.route('**/api/auth/login', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user: MOCK_USER } })
  })
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: MOCK_USER })
  })
  await page.route('**/api/auth/refresh', async (route) => {
    await route.fulfill({ status: 401, json: { detail: '未授权' } })
  })
  await page.route('**/api/auth/register', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user: { ...MOCK_USER, username: 'newuser' } } })
  })
  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({ json: { status: 'success' } })
  })
  await page.route('**/api/auth/send-code', async (route) => {
    await route.fulfill({ json: { status: 'success', message: '验证码已发送' } })
  })
  await page.route('**/api/auth/login-with-email', async (route) => {
    await route.fulfill({ json: { token: 'mock-token', user: MOCK_USER } })
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
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/practice/**', async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/api/answers/**', async (route) => {
    await route.fulfill({ json: {} })
  })
  await page.route('**/api/profile**', async (route) => {
    await route.fulfill({ json: { positions: [] } })
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
}

async function gotoLoginPage(page) {
  await mockAllAPIs(page)
  await page.goto('/')
  await page.waitForTimeout(2000)
  await expect(page.locator('input[name="username"]').first()).toBeVisible({ timeout: 10000 })
}

async function switchToEmailMode(page) {
  const emailModeBtn = page.getByText('邮箱验证码')
  await expect(emailModeBtn).toBeVisible()
  await emailModeBtn.click()
  await page.waitForTimeout(300)
}

async function switchToPasswordMode(page) {
  const pwdModeBtn = page.getByText('密码登录')
  await pwdModeBtn.click()
  await page.waitForTimeout(300)
}

async function switchToRegister(page) {
  const registerLink = page.getByText('注册一个')
  await expect(registerLink).toBeVisible()
  await registerLink.click()
  await page.waitForTimeout(500)
}

// ═══════════════════════════════════════════════
// 一、密码登录
// ═══════════════════════════════════════════════

test.describe('密码登录', () => {
  test('正确用户名密码登录成功，跳转主界面', async ({ page }) => {
    await gotoLoginPage(page)

    await page.locator('input[name="username"]').first().fill('e2e_tester')
    await page.locator('input[name="password"]').first().fill('TestPass123!')
    await page.locator('button[type="submit"]').first().click()

    // 成功后显示主界面 Tab
    await expect(page.getByRole('button', { name: '高频题库' })).toBeVisible({ timeout: 15000 })
  })

  test('错误密码登录失败，显示错误提示', async ({ page }) => {
    await gotoLoginPage(page)

    // 覆盖 login API 返回 401
    await page.unroute('**/api/auth/login')
    await page.route('**/api/auth/login', async (route) => {
      await route.fulfill({ status: 401, json: { detail: '用户名或密码错误' } })
    })

    await page.locator('input[name="username"]').first().fill('e2e_tester')
    await page.locator('input[name="password"]').first().fill('WrongPass!')
    await page.locator('button[type="submit"]').first().click()
    await page.waitForTimeout(3000)

    // 仍在登录页
    await expect(page.locator('input[name="username"]').first()).toBeVisible()
    // 主界面未出现
    const mainVisible = await page.getByRole('button', { name: '高频题库' }).isVisible().catch(() => false)
    expect(mainVisible).toBeFalsy()
    // 错误提示
    const errorText = page.locator('.text-red-500, .text-red-400, [class*="text-red"]').first()
    const hasError = await errorText.isVisible().catch(() => false)
    expect(hasError).toBeTruthy()
  })

  test('用户名为空时登录按钮禁用', async ({ page }) => {
    await gotoLoginPage(page)
    await page.locator('input[name="password"]').first().fill('TestPass123!')
    await page.waitForTimeout(200)
    await expect(page.locator('button[type="submit"]').first()).toBeDisabled()
  })

  test('密码为空时登录按钮禁用', async ({ page }) => {
    await gotoLoginPage(page)
    await page.locator('input[name="username"]').first().fill('testuser')
    await page.waitForTimeout(200)
    await expect(page.locator('button[type="submit"]').first()).toBeDisabled()
  })

  test('密码少于 8 位时登录按钮禁用', async ({ page }) => {
    await gotoLoginPage(page)
    await page.locator('input[name="username"]').first().fill('testuser')
    await page.locator('input[name="password"]').first().fill('short')
    await page.waitForTimeout(200)
    await expect(page.locator('button[type="submit"]').first()).toBeDisabled()
  })

  test('服务器 422 错误，停留在登录页', async ({ page }) => {
    await gotoLoginPage(page)

    await page.unroute('**/api/auth/login')
    await page.route('**/api/auth/login', async (route) => {
      await route.fulfill({ status: 422, json: { detail: '参数错误' } })
    })

    await page.locator('input[name="username"]').first().fill('e2e_tester')
    await page.locator('input[name="password"]').first().fill('TestPass123!')
    await page.locator('button[type="submit"]').first().click()
    await page.waitForTimeout(3000)

    await expect(page.locator('input[name="username"]').first()).toBeVisible()
    const mainVisible = await page.getByRole('button', { name: '高频题库' }).isVisible().catch(() => false)
    expect(mainVisible).toBeFalsy()
  })
})

// ═══════════════════════════════════════════════
// 二、邮箱验证码登录
// ═══════════════════════════════════════════════

test.describe('邮箱验证码登录', () => {
  test('切换到邮箱验证码模式，UI 元素正确显示', async ({ page }) => {
    await gotoLoginPage(page)
    await switchToEmailMode(page)

    // 邮箱输入框
    await expect(page.locator('input[type="email"]').first()).toBeVisible()
    // 验证码输入框
    await expect(page.locator('input[placeholder="6位数字"]').first()).toBeVisible()
    // 发送验证码按钮
    await expect(page.getByText('发送验证码')).toBeVisible()
  })

  test('有效邮箱 + 正确验证码登录成功', async ({ page }) => {
    await gotoLoginPage(page)
    await switchToEmailMode(page)

    await page.locator('input[type="email"]').first().fill('test@example.com')
    await page.locator('input[placeholder="6位数字"]').first().fill('123456')
    await page.waitForTimeout(200)

    // 提交按钮应可点击
    const submitBtn = page.locator('button[type="submit"]').first()
    await expect(submitBtn).toBeEnabled()

    await submitBtn.click()
    // 成功后显示主界面
    await expect(page.getByRole('button', { name: '高频题库' })).toBeVisible({ timeout: 15000 })
  })

  test('发送验证码后按钮进入倒计时', async ({ page }) => {
    await gotoLoginPage(page)
    await switchToEmailMode(page)

    await page.locator('input[type="email"]').first().fill('test@example.com')
    await page.waitForTimeout(200)

    const sendBtn = page.getByText('发送验证码')
    await expect(sendBtn).toBeEnabled()
    await sendBtn.click()
    await page.waitForTimeout(500)

    // 按钮应显示倒计时（如 "59s"）
    const cooldownText = page.locator('button:has-text("s")').first()
    await expect(cooldownText).toBeVisible()
  })

  test('验证码少于 6 位时提交按钮禁用', async ({ page }) => {
    await gotoLoginPage(page)
    await switchToEmailMode(page)

    await page.locator('input[type="email"]').first().fill('test@example.com')
    await page.locator('input[placeholder="6位数字"]').first().fill('123')
    await page.waitForTimeout(200)

    await expect(page.locator('button[type="submit"]').first()).toBeDisabled()
  })

  test('邮箱为空时发送验证码按钮禁用', async ({ page }) => {
    await gotoLoginPage(page)
    await switchToEmailMode(page)

    // 邮箱留空
    await page.waitForTimeout(200)
    const sendBtn = page.getByText('发送验证码')
    await expect(sendBtn).toBeDisabled()
  })

  test('无效邮箱格式时发送验证码按钮禁用', async ({ page }) => {
    await gotoLoginPage(page)
    await switchToEmailMode(page)

    await page.locator('input[type="email"]').first().fill('not-an-email')
    await page.waitForTimeout(200)

    const sendBtn = page.getByText('发送验证码')
    await expect(sendBtn).toBeDisabled()
  })

  test('错误验证码登录失败', async ({ page }) => {
    await gotoLoginPage(page)

    // 覆盖 email login API 返回 401
    await page.unroute('**/api/auth/login-with-email')
    await page.route('**/api/auth/login-with-email', async (route) => {
      await route.fulfill({ status: 401, json: { detail: '验证码错误或已过期' } })
    })

    await switchToEmailMode(page)

    await page.locator('input[type="email"]').first().fill('test@example.com')
    await page.locator('input[placeholder="6位数字"]').first().fill('000000')
    await page.waitForTimeout(200)

    await page.locator('button[type="submit"]').first().click()
    await page.waitForTimeout(3000)

    // 仍在登录页
    await expect(page.locator('input[type="email"]').first()).toBeVisible()
    const mainVisible = await page.getByRole('button', { name: '高频题库' }).isVisible().catch(() => false)
    expect(mainVisible).toBeFalsy()

    // 错误消息
    const errorText = page.locator('.text-red-500, .text-red-400, [class*="text-red"]').first()
    const hasError = await errorText.isVisible().catch(() => false)
    expect(hasError).toBeTruthy()
  })

  test('发送验证码 API 失败时显示错误', async ({ page }) => {
    await gotoLoginPage(page)

    // 覆盖 send-code API 返回 429（频率限制）
    await page.unroute('**/api/auth/send-code')
    await page.route('**/api/auth/send-code', async (route) => {
      await route.fulfill({ status: 429, json: { detail: '发送过于频繁，请稍后再试' } })
    })

    await switchToEmailMode(page)
    await page.locator('input[type="email"]').first().fill('test@example.com')
    await page.waitForTimeout(200)

    const sendBtn = page.getByText('发送验证码')
    await sendBtn.click()
    await page.waitForTimeout(2000)

    // 错误消息应显示
    const errorText = page.locator('.text-red-500, .text-red-400, [class*="text-red"]').first()
    const hasError = await errorText.isVisible().catch(() => false)
    expect(hasError).toBeTruthy()
  })

  test('从邮箱模式切换回密码模式', async ({ page }) => {
    await gotoLoginPage(page)
    await switchToEmailMode(page)

    // 邮箱模式元素存在
    await expect(page.locator('input[type="email"]').first()).toBeVisible()

    // 切换回密码模式
    await switchToPasswordMode(page)

    // 用户名输入框恢复
    await expect(page.locator('input[name="username"]').first()).toBeVisible()
  })
})

// ═══════════════════════════════════════════════
// 三、注册流程
// ═══════════════════════════════════════════════

test.describe('注册流程', () => {
  test('切换到注册模式，UI 正确显示', async ({ page }) => {
    await gotoLoginPage(page)

    await switchToRegister(page)

    // 注册模式标题
    const title = page.getByText('创建账号')
    await expect(title).toBeVisible()

    // 密码模式下注册有邮箱字段
    // 用户名 + 密码 + 邮箱 都应存在
    await expect(page.locator('input[name="username"]').first()).toBeVisible()
    await expect(page.locator('input[name="password"]').first()).toBeVisible()
  })

  test('注册模式下密码少于 8 位按钮禁用', async ({ page }) => {
    await gotoLoginPage(page)
    await switchToRegister(page)

    await page.locator('input[name="username"]').first().fill('newuser')

    // 邮箱字段（注册模式下有）
    const emailInput = page.locator('input[type="email"]').first()
    if (await emailInput.isVisible()) {
      await emailInput.fill('new@example.com')
    }

    await page.locator('input[name="password"]').first().fill('short')
    await page.waitForTimeout(200)

    await expect(page.locator('button[type="submit"]').first()).toBeDisabled()
  })

  test('注册模式下用户名为空按钮禁用', async ({ page }) => {
    await gotoLoginPage(page)
    await switchToRegister(page)

    // 用户名留空
    const emailInput = page.locator('input[type="email"]').first()
    if (await emailInput.isVisible()) {
      await emailInput.fill('new@example.com')
    }

    await page.locator('input[name="password"]').first().fill('ValidPass123!')
    await page.waitForTimeout(200)

    await expect(page.locator('button[type="submit"]').first()).toBeDisabled()
  })

  test('完整注册流程成功', async ({ page }) => {
    await gotoLoginPage(page)
    await switchToRegister(page)

    await page.locator('input[name="username"]').first().fill('newuser')

    const emailInput = page.locator('input[type="email"]').first()
    if (await emailInput.isVisible()) {
      await emailInput.fill('new@example.com')
    }

    await page.locator('input[name="password"]').first().fill('NewPass123!')
    await page.waitForTimeout(200)

    const submitBtn = page.locator('button[type="submit"]').first()
    await expect(submitBtn).toBeEnabled()
    await submitBtn.click()

    // 注册成功后跳转主界面
    await expect(page.getByRole('button', { name: '高频题库' })).toBeVisible({ timeout: 15000 })
  })

  test('注册 API 返回 409 用户名已存在', async ({ page }) => {
    await gotoLoginPage(page)

    // 覆盖 register API 返回 409
    await page.unroute('**/api/auth/register')
    await page.route('**/api/auth/register', async (route) => {
      await route.fulfill({ status: 409, json: { detail: '用户名已存在' } })
    })

    await switchToRegister(page)

    await page.locator('input[name="username"]').first().fill('existinguser')

    const emailInput = page.locator('input[type="email"]').first()
    if (await emailInput.isVisible()) {
      await emailInput.fill('new@example.com')
    }

    await page.locator('input[name="password"]').first().fill('ValidPass123!')
    await page.waitForTimeout(200)

    await page.locator('button[type="submit"]').first().click()
    await page.waitForTimeout(3000)

    // 仍在注册页
    const title = page.getByText('创建账号')
    await expect(title).toBeVisible()

    // 错误消息
    const errorText = page.locator('.text-red-500, .text-red-400, [class*="text-red"]').first()
    const hasError = await errorText.isVisible().catch(() => false)
    expect(hasError).toBeTruthy()
  })

  test('从注册模式切换回登录模式', async ({ page }) => {
    await gotoLoginPage(page)
    await switchToRegister(page)

    // 在注册模式
    await expect(page.getByText('创建账号')).toBeVisible()

    // 切换回登录
    const loginLink = page.getByText('去登录')
    await loginLink.click()
    await page.waitForTimeout(500)

    // 回到登录模式
    await expect(page.getByText('欢迎回来')).toBeVisible()
  })
})

// ═══════════════════════════════════════════════
// 四、错误处理综合
// ═══════════════════════════════════════════════

test.describe('错误处理综合', () => {
  test('网络超时时页面不崩溃', async ({ page }) => {
    await gotoLoginPage(page)

    // 覆盖 login API 为超时
    await page.unroute('**/api/auth/login')
    await page.route('**/api/auth/login', async (route) => {
      await route.abort('timedout')
    })

    await page.locator('input[name="username"]').first().fill('e2e_tester')
    await page.locator('input[name="password"]').first().fill('TestPass123!')
    await page.locator('button[type="submit"]').first().click()
    await page.waitForTimeout(5000)

    // 页面不应崩溃，登录表单仍在
    await expect(page.locator('input[name="username"]').first()).toBeVisible()
  })

  test('500 服务器错误时页面不崩溃', async ({ page }) => {
    await gotoLoginPage(page)

    await page.unroute('**/api/auth/login')
    await page.route('**/api/auth/login', async (route) => {
      await route.fulfill({ status: 500, json: { detail: 'Internal Server Error' } })
    })

    await page.locator('input[name="username"]').first().fill('e2e_tester')
    await page.locator('input[name="password"]').first().fill('TestPass123!')
    await page.locator('button[type="submit"]').first().click()
    await page.waitForTimeout(5000)

    await expect(page.locator('input[name="username"]').first()).toBeVisible()
    const mainVisible = await page.getByRole('button', { name: '高频题库' }).isVisible().catch(() => false)
    expect(mainVisible).toBeFalsy()
  })

  test('邮箱验证码模式下提交空邮箱 + 空验证码，按钮禁用', async ({ page }) => {
    await gotoLoginPage(page)
    await switchToEmailMode(page)

    // 全部留空
    await page.waitForTimeout(200)
    await expect(page.locator('button[type="submit"]').first()).toBeDisabled()
  })

  test('邮箱登录 API 返回 423 账号被锁定', async ({ page }) => {
    await gotoLoginPage(page)

    await page.unroute('**/api/auth/login-with-email')
    await page.route('**/api/auth/login-with-email', async (route) => {
      await route.fulfill({ status: 423, json: { detail: '账号已被锁定，请稍后再试' } })
    })

    await switchToEmailMode(page)

    await page.locator('input[type="email"]').first().fill('test@example.com')
    await page.locator('input[placeholder="6位数字"]').first().fill('123456')
    await page.waitForTimeout(200)

    await page.locator('button[type="submit"]').first().click()
    await page.waitForTimeout(3000)

    // 仍在登录页
    await expect(page.locator('input[type="email"]').first()).toBeVisible()
    const errorText = page.locator('.text-red-500, .text-red-400, [class*="text-red"]').first()
    const hasError = await errorText.isVisible().catch(() => false)
    expect(hasError).toBeTruthy()
  })

  test('注册时邮箱为空，密码模式下注册按钮不禁用（已知前端缺陷）', async ({ page }) => {
    // NOTE: LoginModal.vue 密码模式注册的 :disabled 未检查 email 字段
    // :disabled="loading || !username.trim() || password.length < 8"
    // 应该加上 || (isRegister && !email.trim())
    await gotoLoginPage(page)
    await switchToRegister(page)

    await page.locator('input[name="username"]').first().fill('newuser')
    await page.locator('input[name="password"]').first().fill('ValidPass123!')

    // 邮箱留空
    const emailInput = page.locator('input[type="email"]').first()
    if (await emailInput.isVisible()) {
      await page.waitForTimeout(200)
      // 当前行为：按钮仍为 enabled（缺陷），提交后后端应返回 422
      const submitBtn = page.locator('button[type="submit"]').first()
      await expect(submitBtn).toBeEnabled()

      // 覆盖 register API 返回 422
      await page.unroute('**/api/auth/register')
      await page.route('**/api/auth/register', async (route) => {
        await route.fulfill({ status: 422, json: { detail: '邮箱不能为空' } })
      })

      await submitBtn.click()
      await page.waitForTimeout(3000)

      // 错误消息应显示
      const errorText = page.locator('.text-red-500, .text-red-400, [class*="text-red"]').first()
      const hasError = await errorText.isVisible().catch(() => false)
      expect(hasError).toBeTruthy()
    }
  })

  test('注册 API 返回 422 邮箱格式错误', async ({ page }) => {
    await gotoLoginPage(page)

    await page.unroute('**/api/auth/register')
    await page.route('**/api/auth/register', async (route) => {
      await route.fulfill({ status: 422, json: { detail: '邮箱格式不正确' } })
    })

    await switchToRegister(page)

    await page.locator('input[name="username"]').first().fill('newuser')

    const emailInput = page.locator('input[type="email"]').first()
    if (await emailInput.isVisible()) {
      await emailInput.fill('bad-email')
    }

    await page.locator('input[name="password"]').first().fill('ValidPass123!')
    await page.waitForTimeout(200)

    // 如果前端有邮箱格式校验，按钮应禁用；否则提交后显示错误
    const submitBtn = page.locator('button[type="submit"]').first()
    const isEnabled = await submitBtn.isEnabled().catch(() => false)
    if (isEnabled) {
      await submitBtn.click()
      await page.waitForTimeout(3000)
      const errorText = page.locator('.text-red-500, .text-red-400, [class*="text-red"]').first()
      const hasError = await errorText.isVisible().catch(() => false)
      expect(hasError).toBeTruthy()
    }
  })
})
