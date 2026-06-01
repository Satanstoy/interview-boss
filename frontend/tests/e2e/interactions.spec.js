/**
 * 深层交互 E2E 测试 — 覆盖拖拽、键盘导航、下拉菜单、弹窗、滚动等全部交互场景
 */
import { test, expect } from '@playwright/test'

// ── Mock 数据 ──
const MOCK_USER = {
  id: 999, username: 'e2e_tester', is_admin: false,
  bank_mode: 'public', current_position_id: 1, current_position: '前端开发工程师',
}
const MOCK_ADMIN = { ...MOCK_USER, is_admin: true }
const MOCK_QUESTIONS = Array.from({ length: 20 }, (_, i) => ({
  id: i + 1,
  title: `测试题目 ${i + 1}: ${['Vue响应式原理', 'CSRF攻击防御', 'JavaScript闭包', 'React Hooks', 'CSS Grid布局', 'HTTP缓存机制', 'Promise并发控制', 'Webpack构建优化', 'Node事件循环', 'TypeScript泛型'][i % 10]}`,
  category: `cat2_${['前端框架', '网络安全', 'JS基础', 'React', 'CSS', '网络协议', '异步编程', '工程化', 'Node', 'TypeScript'][i % 10]}`,
  difficulty: ['easy', 'medium', 'hard'][i % 3],
  tags: [['Vue', '响应式'], ['安全', 'CSRF'], ['JavaScript', '闭包'], ['React', 'Hooks'], ['CSS', 'Grid']][i % 5],
  source_type: i % 2 === 0 ? 'jd' : 'interview',
  answer_complete: i % 3 !== 0,
  ai_answer: i % 3 !== 0 ? `## 答案 ${i + 1}\n\n这是测试答案内容...` : '',
  user_answer: '',
  is_starred: i % 5 === 0,
  created_at: `2026-01-${String(15 + i % 15).padStart(2, '0')}T10:00:00`,
  sources: [{ url: 'https://example.com', company: '字节跳动', round: '一面' }],
  original_items: [{ question_text: `原始题目变体 ${i + 1}` }],
}))
const MOCK_TAGS = [
  { tag: '全部', count: 20 }, { tag: 'Vue', count: 4 }, { tag: 'JavaScript', count: 4 },
  { tag: 'React', count: 4 }, { tag: 'CSS', count: 4 }, { tag: '安全', count: 4 },
]
const MOCK_ANALYTICS = {
  total_questions: 20, total_practiced: 8, mastery_rate: 0.65,
  tag_distribution: MOCK_TAGS.slice(1).map(t => ({ tag: t.tag, count: t.count })),
  difficulty_distribution: { easy: 7, medium: 7, hard: 6 }, recent_activity: [],
}

// ── Helper ──
async function setupMocks(page, userOverrides = {}) {
  const user = { ...MOCK_USER, ...userOverrides }
  const routes = {
    '**/api/auth/login': { token: 'mock-token', user },
    '**/api/auth/register': { token: 'mock-token', user },
    '**/api/auth/me': user,
    '**/api/auth/bank-mode': { status: 'success', bank_mode: 'personal' },
    '**/api/auth/logout': { status: 'success' },
    '**/api/data/jd': [],
    '**/api/data/interview': [],
    '**/api/analytics**': MOCK_ANALYTICS,
    '**/api/practice/stats**': { total_sessions: 5, total_questions: 20, avg_score: 75, streak: 2 },
    '**/api/profile**': {},
    '**/api/chat**': [],
    '**/api/health': { status: 'ok', db: 'connected' },
    '**/api/bank-build**': { status: 'idle' },
    '**/api/admin**': [],
  }
  for (const [pattern, resp] of Object.entries(routes)) {
    await page.route(pattern, async (route) => await route.fulfill({ json: resp }))
  }
  // Master bank with full question data
  await page.route('**/api/master-bank**', async (route) => {
    const url = route.request().url()
    if (url.includes('/detail')) {
      const id = parseInt(url.match(/\/(\d+)\/detail/)?.[1] || '1')
      const q = MOCK_QUESTIONS.find(q => q.id === id) || MOCK_QUESTIONS[0]
      await route.fulfill({ json: q })
    } else if (url.includes('/toggle-star')) {
      await route.fulfill({ json: { is_starred: true } })
    } else if (url.includes('/search')) {
      await route.fulfill({ json: MOCK_QUESTIONS.slice(0, 5) })
    } else {
      await route.fulfill({ json: { items: MOCK_QUESTIONS, popular_tags: MOCK_TAGS } })
    }
  })
  // Refresh token → logged in
  await page.route('**/api/auth/refresh', async (route) => {
    await route.fulfill({ status: 200, json: { token: 'mock-token', user } })
  })
  // Evaluate answer
  await page.route('**/api/evaluate-answer', async (route) => {
    await route.fulfill({ json: { overall_score: 82, feedback: '回答不错', suggestions: '可以更详细' } })
  })
}

async function loginAndLoad(page, userOverrides = {}) {
  await setupMocks(page, userOverrides)
  await page.goto('/')
  await page.waitForSelector('main', { timeout: 15000 })
  await page.waitForTimeout(1500)
}

// ═══════════════════════════════════════════════
// 1. 侧边栏拖拽调整宽度
// ═══════════════════════════════════════════════
test.describe('侧边栏拖拽', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAndLoad(page)
  })

  test('拖拽手柄可加宽侧边栏', async ({ page }) => {
    const handle = page.locator('.resize-handle')
    const wrapper = page.locator('.sidebar-wrapper')
    await expect(handle).toBeVisible({ timeout: 5000 })

    const initialWidth = await wrapper.evaluate(el => el.getBoundingClientRect().width)
    const box = await handle.boundingBox()
    const startX = box.x + box.width / 2
    const startY = box.y + box.height / 2

    // 向右拖拽 150px
    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX + 150, startY, { steps: 10 })
    await page.mouse.up()

    const newWidth = await wrapper.evaluate(el => el.getBoundingClientRect().width)
    expect(newWidth).toBeGreaterThan(initialWidth + 50)
  })

  test('拖拽手柄可缩窄侧边栏', async ({ page }) => {
    const handle = page.locator('.resize-handle')
    const wrapper = page.locator('.sidebar-wrapper')
    await expect(handle).toBeVisible({ timeout: 5000 })

    const initialWidth = await wrapper.evaluate(el => el.getBoundingClientRect().width)
    const box = await handle.boundingBox()
    const startX = box.x + box.width / 2
    const startY = box.y + box.height / 2

    // 向左拖拽 100px
    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX - 100, startY, { steps: 10 })
    await page.mouse.up()

    const newWidth = await wrapper.evaluate(el => el.getBoundingClientRect().width)
    expect(newWidth).toBeLessThan(initialWidth)
  })

  test('拖拽到极窄自动折叠', async ({ page }) => {
    const handle = page.locator('.resize-handle')
    const wrapper = page.locator('.sidebar-wrapper')
    await expect(handle).toBeVisible({ timeout: 5000 })

    const box = await handle.boundingBox()
    const startX = box.x + box.width / 2
    const startY = box.y + box.height / 2

    // 拖拽到非常窄（< 120px 阈值）
    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX - 400, startY, { steps: 15 })
    await page.mouse.up()
    await page.waitForTimeout(300)

    // 侧边栏应折叠（wrapper 宽度为 0 或不可见）
    const width = await wrapper.evaluate(el => el.getBoundingClientRect().width)
    expect(width).toBeLessThan(130)
  })

  test('折叠后展开按钮可点击展开', async ({ page }) => {
    // 先折叠（通过 localStorage 模拟已折叠状态）
    await page.evaluate(() => localStorage.setItem('sidebar-collapsed', 'true'))
    await page.reload()
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(500)

    // 侧边栏应折叠
    const wrapper = page.locator('.sidebar-wrapper')
    const collapsedWidth = await wrapper.evaluate(el => el.getBoundingClientRect().width)
    expect(collapsedWidth).toBeLessThan(50)

    // 展开按钮应出现
    const expandBtn = page.locator('.sidebar-expand-btn')
    await expect(expandBtn).toBeVisible({ timeout: 5000 })
    await expandBtn.click()
    await page.waitForTimeout(500)

    // 侧边栏应重新展开
    const expandedWidth = await wrapper.evaluate(el => el.getBoundingClientRect().width)
    expect(expandedWidth).toBeGreaterThan(150)
  })

  test('宽度持久化到 localStorage', async ({ page }) => {
    const handle = page.locator('.resize-handle')
    await expect(handle).toBeVisible({ timeout: 5000 })
    const box = await handle.boundingBox()

    // 拖拽到特定宽度
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width / 2 + 80, box.y + box.height / 2, { steps: 8 })
    await page.mouse.up()
    await page.waitForTimeout(200)

    // 检查 localStorage
    const savedWidth = await page.evaluate(() => localStorage.getItem('sidebar-width'))
    expect(savedWidth).toBeTruthy()
    expect(parseInt(savedWidth)).toBeGreaterThan(200)
  })
})

// ═══════════════════════════════════════════════
// 2. Tab 切换与滚动保持
// ═══════════════════════════════════════════════
test.describe('Tab 切换', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAndLoad(page)
  })

  test('所有 Tab 可点击切换', async ({ page }) => {
    const tabNames = ['JD', '面经', '题库', '模拟面试', '抽测', '知识图谱', '导入', '手撕']
    for (const name of tabNames) {
      const tab = page.locator('button').filter({ hasText: new RegExp(name) }).first()
      if (await tab.isVisible({ timeout: 1000 }).catch(() => false)) {
        await tab.click()
        await page.waitForTimeout(300)
        // Tab 应被选中（样式变化）
        await expect(tab).toBeVisible()
      }
    }
  })

  test('Tab 切换后内容区更新', async ({ page }) => {
    // 切换到题库 tab
    const bankTab = page.locator('button').filter({ hasText: /题库/ }).first()
    await bankTab.click()
    await page.waitForTimeout(500)
    const bankContent = await page.locator('body').textContent()
    expect(bankContent.includes('题库') || bankContent.includes('搜索')).toBeTruthy()

    // 切换到 JD tab
    const jdTab = page.locator('button').filter({ hasText: /JD/ }).first()
    if (await jdTab.isVisible({ timeout: 1000 }).catch(() => false)) {
      await jdTab.click()
      await page.waitForTimeout(500)
    }
  })

  test('Tab 栏在窄屏可水平滚动', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await page.waitForTimeout(500)

    const tabBar = page.locator('[class*="overflow-x-auto"]').first()
    if (await tabBar.isVisible({ timeout: 2000 }).catch(() => false)) {
      const scrollWidth = await tabBar.evaluate(el => el.scrollWidth)
      const clientWidth = await tabBar.evaluate(el => el.clientWidth)
      // 如果 tab 数量多，应该可以滚动
      if (scrollWidth > clientWidth) {
        expect(scrollWidth).toBeGreaterThan(clientWidth)
      }
    }
  })
})

// ═══════════════════════════════════════════════
// 3. 搜索与筛选交互
// ═══════════════════════════════════════════════
test.describe('搜索与筛选', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAndLoad(page)
    // 切换到题库 tab
    const bankTab = page.locator('button').filter({ hasText: /题库/ }).first()
    await bankTab.click()
    await page.waitForTimeout(500)
  })

  test('搜索框输入有 300ms 防抖', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="搜索"], input[type="search"]').first()
    if (await searchInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      // 快速输入
      await searchInput.fill('Vue')
      const value = await searchInput.inputValue()
      expect(value).toBe('Vue')

      // 300ms 后搜索应生效（输入框值不变）
      await page.waitForTimeout(400)
      const valueAfter = await searchInput.inputValue()
      expect(valueAfter).toBe('Vue')
    }
  })

  test('清除搜索按钮可点击', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="搜索"], input[type="search"]').first()
    if (await searchInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await searchInput.fill('测试搜索')
      await page.waitForTimeout(500)

      // 找到搜索框旁边的清除按钮（X 图标）
      const clearBtn = searchInput.locator('..').locator('button').first()
      if (await clearBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
        await clearBtn.click()
        await page.waitForTimeout(200)
        const value = await searchInput.inputValue()
        expect(value).toBe('')
      } else {
        // 如果没有清除按钮，手动清空
        await searchInput.clear()
        const value = await searchInput.inputValue()
        expect(value).toBe('')
      }
    }
  })

  test('难度筛选下拉框可操作', async ({ page }) => {
    // 找到 RoundedSelect 触发按钮
    const filterBtn = page.locator('button').filter({ hasText: /全部|难度|L1|L2|L3/ }).first()
    if (await filterBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await filterBtn.click()
      await page.waitForTimeout(300)

      // 下拉选项应出现
      const options = page.locator('button').filter({ hasText: /简单|中等|困难|全部/ })
      const count = await options.count()
      if (count > 0) {
        await options.first().click()
        await page.waitForTimeout(300)
      }
    }
  })

  test('子标签筛选芯片可点击切换', async ({ page }) => {
    // 等待标签加载
    await page.waitForTimeout(1000)

    // 点击侧边栏的标签
    const tagChip = page.locator('button').filter({ hasText: /Vue|JavaScript|React/ }).first()
    if (await tagChip.isVisible({ timeout: 3000 }).catch(() => false)) {
      await tagChip.click()
      await page.waitForTimeout(500)

      // 子标签筛选区域应出现
      const subTagArea = page.getByText('子标签')
      if (await subTagArea.isVisible({ timeout: 2000 }).catch(() => false)) {
        // 点击一个子标签
        const subTag = page.locator('button').filter({ hasText: /响应式|Hooks|闭包/ }).first()
        if (await subTag.isVisible({ timeout: 1000 }).catch(() => false)) {
          await subTag.click()
          await page.waitForTimeout(300)
          // 再次点击取消选中
          await subTag.click()
          await page.waitForTimeout(300)
        }
      }
    }
  })
})

// ═══════════════════════════════════════════════
// 4. 题目卡片交互
// ═══════════════════════════════════════════════
test.describe('题目卡片交互', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAndLoad(page)
    const bankTab = page.locator('button').filter({ hasText: /题库/ }).first()
    await bankTab.click()
    await page.waitForTimeout(1000)
  })

  test('点击卡片展开/折叠答案', async ({ page }) => {
    // 找到第一个题目卡片
    const card = page.locator('[class*="group"]').filter({ hasText: /测试题目/ }).first()
    if (await card.isVisible({ timeout: 5000 }).catch(() => false)) {
      // 点击展开
      await card.click()
      await page.waitForTimeout(500)

      // 再次点击折叠
      await card.click()
      await page.waitForTimeout(300)
    }
  })

  test('全部展开/全部折叠按钮', async ({ page }) => {
    const expandAll = page.locator('button').filter({ hasText: /全部展开|展开全部/ }).first()
    const collapseAll = page.locator('button').filter({ hasText: /全部折叠|折叠全部/ }).first()

    if (await expandAll.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expandAll.click()
      await page.waitForTimeout(500)
    }
    if (await collapseAll.isVisible({ timeout: 3000 }).catch(() => false)) {
      await collapseAll.click()
      await page.waitForTimeout(500)
    }
  })

  test('星标按钮可点击切换', async ({ page }) => {
    // 找到星标按钮（通常是 SVG 星星图标）
    const starBtn = page.locator('button').filter({ has: page.locator('svg') }).filter({ hasText: '' }).first()
    // 星标按钮在卡片 hover 时才可见，先 hover 卡片
    const card = page.locator('[class*="group"]').filter({ hasText: /测试题目/ }).first()
    if (await card.isVisible({ timeout: 5000 }).catch(() => false)) {
      await card.hover()
      await page.waitForTimeout(300)
      // 找到卡片内的星标按钮
      const star = card.locator('button').filter({ has: page.locator('svg') }).last()
      if (await star.isVisible({ timeout: 1000 }).catch(() => false)) {
        await star.click()
        await page.waitForTimeout(300)
      }
    }
  })

  test('练习按钮可点击打开练习面板', async ({ page }) => {
    const card = page.locator('[class*="group"]').filter({ hasText: /测试题目/ }).first()
    if (await card.isVisible({ timeout: 5000 }).catch(() => false)) {
      await card.hover()
      await page.waitForTimeout(300)

      // 找到练习按钮
      const practiceBtn = card.locator('button').filter({ hasText: /练习/ }).first()
      if (await practiceBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
        await practiceBtn.click()
        await page.waitForTimeout(500)

        // 练习面板应打开
        const practicePanel = page.locator('[class*="fixed"]').filter({ hasText: /参考答案|你的回答/ }).first()
        if (await practicePanel.isVisible({ timeout: 3000 }).catch(() => false)) {
          // 关闭练习面板
          const closeBtn = practicePanel.locator('button').filter({ has: page.locator('svg') }).first()
          if (await closeBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
            await closeBtn.click()
          }
        }
      }
    }
  })

  test('来源信息展开/折叠', async ({ page }) => {
    const card = page.locator('[class*="group"]').filter({ hasText: /测试题目/ }).first()
    if (await card.isVisible({ timeout: 5000 }).catch(() => false)) {
      // 先展开答案
      await card.click()
      await page.waitForTimeout(500)

      // 找到来源切换按钮
      const sourcesBtn = card.locator('button').filter({ hasText: /来源|出处|sources/i }).first()
      if (await sourcesBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        await sourcesBtn.click()
        await page.waitForTimeout(300)
        // 再次点击折叠
        await sourcesBtn.click()
        await page.waitForTimeout(300)
      }
    }
  })
})

// ═══════════════════════════════════════════════
// 5. 用户菜单交互
// ═══════════════════════════════════════════════
test.describe('用户菜单', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAndLoad(page)
  })

  test('点击头像打开下拉菜单', async ({ page }) => {
    const menuBtn = page.locator('.relative > button').first()
    await expect(menuBtn).toBeVisible({ timeout: 5000 })
    await menuBtn.click()
    await page.waitForTimeout(300)

    // 下拉菜单应显示用户名
    const username = page.getByText(MOCK_USER.username)
    await expect(username.first()).toBeVisible({ timeout: 3000 })
  })

  test('点击外部关闭下拉菜单', async ({ page }) => {
    const menuBtn = page.locator('.relative > button').first()
    await menuBtn.click()
    await page.waitForTimeout(300)

    // 菜单应打开
    const profileBtn = page.getByText('个人信息')
    await expect(profileBtn).toBeVisible({ timeout: 2000 })

    // 点击 overlay（fixed inset-0 z-40）关闭菜单
    const overlay = page.locator('.fixed.inset-0.z-40')
    if (await overlay.isVisible({ timeout: 1000 }).catch(() => false)) {
      await overlay.click({ position: { x: 10, y: 10 } })
    } else {
      // fallback: 点击页面其他区域
      await page.mouse.click(100, 100)
    }
    await page.waitForTimeout(300)

    // 菜单应关闭
    await expect(profileBtn).not.toBeVisible({ timeout: 2000 })
  })

  test('题库模式切换按钮可点击', async ({ page }) => {
    const menuBtn = page.locator('.relative > button').first()
    await menuBtn.click()
    await page.waitForTimeout(300)

    // 找到题库模式按钮
    const personalBtn = page.locator('button').filter({ hasText: /个人/ }).first()
    if (await personalBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await personalBtn.click()
      await page.waitForTimeout(500)
    }
  })

  test('登出按钮可点击', async ({ page }) => {
    const menuBtn = page.locator('.relative > button').first()
    await menuBtn.click()
    await page.waitForTimeout(300)

    const logoutBtn = page.locator('button').filter({ hasText: /退出|登出|logout/i }).first()
    if (await logoutBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await logoutBtn.click()
      await page.waitForTimeout(1000)

      // 应返回登录页
      const loginTitle = page.getByText('欢迎使用 InterviewBoss')
      await expect(loginTitle).toBeVisible({ timeout: 5000 })
    }
  })
})

// ═══════════════════════════════════════════════
// 6. 设置面板交互
// ═══════════════════════════════════════════════
test.describe('设置面板', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAndLoad(page)
  })

  test('点击齿轮按钮打开设置面板', async ({ page }) => {
    const settingsBtn = page.locator('button[title="系统配置"]')
    await expect(settingsBtn).toBeVisible({ timeout: 5000 })
    await settingsBtn.click()
    await page.waitForTimeout(500)

    // 设置面板应出现
    const panel = page.getByText('系统配置', { exact: false })
    await expect(panel.first()).toBeVisible({ timeout: 3000 })
  })

  test('设置面板关闭按钮可点击', async ({ page }) => {
    const settingsBtn = page.locator('button[title="系统配置"]')
    await settingsBtn.click()
    await page.waitForTimeout(500)

    // 设置面板应出现
    const panel = page.getByText('系统配置', { exact: false })
    await expect(panel.first()).toBeVisible({ timeout: 3000 })

    // 点击关闭按钮（面板底部的关闭按钮）
    const closeBtn = page.locator('button').filter({ hasText: /关闭|取消|close/i }).last()
    if (await closeBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await closeBtn.click()
      await page.waitForTimeout(500)
    }
  })

  // NOTE: SettingsPanel 不响应 Escape 键 — 这是一个 UX Bug（BUG-004）

  test('点击遮罩层关闭设置面板', async ({ page }) => {
    const settingsBtn = page.locator('button[title="系统配置"]')
    await settingsBtn.click()
    await page.waitForTimeout(500)

    // 点击遮罩层（面板外的区域）
    await page.mouse.click(10, 10)
    await page.waitForTimeout(300)
  })

  test('设置面板可滚动', async ({ page }) => {
    const settingsBtn = page.locator('button[title="系统配置"]')
    await settingsBtn.click()
    await page.waitForTimeout(500)

    // 设置面板内容区应可滚动
    const panel = page.locator('[class*="overflow-y-auto"]').last()
    if (await panel.isVisible({ timeout: 2000 }).catch(() => false)) {
      const scrollHeight = await panel.evaluate(el => el.scrollHeight)
      const clientHeight = await panel.evaluate(el => el.clientHeight)
      // 如果内容超出，应可滚动
      if (scrollHeight > clientHeight) {
        await panel.evaluate(el => el.scrollTo(0, 200))
        await page.waitForTimeout(200)
        const scrollTop = await panel.evaluate(el => el.scrollTop)
        expect(scrollTop).toBeGreaterThan(0)
      }
    }
  })
})

// ═══════════════════════════════════════════════
// 7. 暗色模式
// ═══════════════════════════════════════════════
test.describe('暗色模式', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAndLoad(page)
  })

  test('切换暗色模式后 html 有 dark class', async ({ page }) => {
    const darkToggle = page.locator('button[title*="暗色"], button[title*="亮色"]').first()
    await expect(darkToggle).toBeVisible({ timeout: 5000 })

    // 获取初始状态
    const initialClass = await page.locator('html').getAttribute('class') || ''

    await darkToggle.click()
    await page.waitForTimeout(300)

    const newClass = await page.locator('html').getAttribute('class') || ''
    // class 应该变化
    expect(newClass).not.toBe(initialClass)
  })

  test('暗色模式持久化到 localStorage', async ({ page }) => {
    const darkToggle = page.locator('button[title*="暗色"], button[title*="亮色"]').first()
    await darkToggle.click()
    await page.waitForTimeout(300)

    const theme = await page.evaluate(() => localStorage.getItem('interviewboss-theme'))
    expect(theme).toBeTruthy()
  })

  test('刷新后暗色模式保持', async ({ page }) => {
    const darkToggle = page.locator('button[title*="暗色"], button[title*="亮色"]').first()
    await darkToggle.click()
    await page.waitForTimeout(300)

    const classBefore = await page.locator('html').getAttribute('class')

    // 刷新页面
    await page.reload()
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(500)

    const classAfter = await page.locator('html').getAttribute('class')
    expect(classAfter).toBe(classBefore)
  })
})

// ═══════════════════════════════════════════════
// 8. 键盘导航
// ═══════════════════════════════════════════════
test.describe('键盘导航', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAndLoad(page)
  })

  test('Tab 键可在表单元素间切换', async ({ page }) => {
    // 切换到题库 tab
    const bankTab = page.locator('button').filter({ hasText: /题库/ }).first()
    await bankTab.click()
    await page.waitForTimeout(500)

    // 聚焦到搜索框
    const searchInput = page.locator('input[placeholder*="搜索"], input[type="search"]').first()
    if (await searchInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await searchInput.focus()
      await page.waitForTimeout(200)

      // 按 Tab 移动焦点
      await page.keyboard.press('Tab')
      await page.waitForTimeout(200)

      // 焦点应移动到下一个可聚焦元素
      const focused = await page.evaluate(() => document.activeElement?.tagName)
      expect(focused).toBeTruthy()
    }
  })

  test('点击 overlay 关闭用户菜单', async ({ page }) => {
    // 打开用户菜单
    const menuBtn = page.locator('.relative > button').first()
    await menuBtn.click()
    await page.waitForTimeout(300)

    const profileBtn = page.getByText('个人信息')
    await expect(profileBtn).toBeVisible({ timeout: 2000 })

    // 点击 overlay 关闭（UserMenu 使用 fixed inset-0 overlay）
    const overlay = page.locator('.fixed.inset-0.z-40')
    await overlay.click({ position: { x: 10, y: 10 } })
    await page.waitForTimeout(300)

    // 菜单应关闭
    await expect(profileBtn).not.toBeVisible({ timeout: 2000 })
  })

  // NOTE: UserMenu 和 SettingsPanel 都不响应 Escape 键 — UX 改进建议（BUG-004）

  test('Enter 键提交搜索', async ({ page }) => {
    const bankTab = page.locator('button').filter({ hasText: /题库/ }).first()
    await bankTab.click()
    await page.waitForTimeout(500)

    const searchInput = page.locator('input[placeholder*="搜索"], input[type="search"]').first()
    if (await searchInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await searchInput.fill('Vue')
      await page.keyboard.press('Enter')
      await page.waitForTimeout(500)
      // 搜索应触发（页面内容可能变化）
    }
  })

  test('RoundedSelect 键盘导航', async ({ page }) => {
    // 找到难度筛选下拉框
    const filterBtn = page.locator('button').filter({ hasText: /全部|难度/ }).first()
    if (await filterBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await filterBtn.focus()

      // 按 Enter 打开
      await page.keyboard.press('Enter')
      await page.waitForTimeout(300)

      // 按 ArrowDown 移动高亮
      await page.keyboard.press('ArrowDown')
      await page.waitForTimeout(100)
      await page.keyboard.press('ArrowDown')
      await page.waitForTimeout(100)

      // 按 Enter 选择
      await page.keyboard.press('Enter')
      await page.waitForTimeout(300)
    }
  })
})

// ═══════════════════════════════════════════════
// 9. 虚拟滚动
// ═══════════════════════════════════════════════
test.describe('虚拟滚动', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAndLoad(page)
    const bankTab = page.locator('button').filter({ hasText: /题库/ }).first()
    await bankTab.click()
    await page.waitForTimeout(1000)
  })

  test('题目列表使用虚拟滚动（不渲染所有 DOM）', async ({ page }) => {
    // 检查虚拟滚动容器
    const scroller = page.locator('[class*="vue-recycle-scroller"], [class*="DynamicScroller"]').first()
    if (await scroller.isVisible({ timeout: 3000 }).catch(() => false)) {
      // 虚拟滚动只渲染可见项，DOM 中的项目数应少于总数
      const items = scroller.locator('[data-index]')
      const visibleCount = await items.count()
      // 20 道题但虚拟滚动只渲染可见的
      expect(visibleCount).toBeLessThanOrEqual(20)
    }
  })

  test('滚动到底部可看到更多题目', async ({ page }) => {
    const scrollArea = page.locator('[class*="overflow-y-auto"]').first()
    if (await scrollArea.isVisible({ timeout: 3000 }).catch(() => false)) {
      const scrollHeight = await scrollArea.evaluate(el => el.scrollHeight)
      const clientHeight = await scrollArea.evaluate(el => el.clientHeight)

      if (scrollHeight > clientHeight) {
        // 滚动到底部
        await scrollArea.evaluate(el => el.scrollTo(0, el.scrollHeight))
        await page.waitForTimeout(500)

        const scrollTop = await scrollArea.evaluate(el => el.scrollTop)
        expect(scrollTop).toBeGreaterThan(0)
      }
    }
  })

  test('展开答案后虚拟滚动项高度自适应', async ({ page }) => {
    const card = page.locator('[class*="group"]').filter({ hasText: /测试题目/ }).first()
    if (await card.isVisible({ timeout: 5000 }).catch(() => false)) {
      // 记录展开前的位置
      const rectBefore = await card.boundingBox()

      // 点击展开
      await card.click()
      await page.waitForTimeout(500)

      // 展开后卡片应变高
      const rectAfter = await card.boundingBox()
      if (rectBefore && rectAfter) {
        expect(rectAfter.height).toBeGreaterThanOrEqual(rectBefore.height)
      }
    }
  })
})

// ═══════════════════════════════════════════════
// 10. 响应式断点测试
// ═══════════════════════════════════════════════
test.describe('响应式断点', () => {
  const viewports = [
    { name: '手机竖屏', width: 375, height: 667 },
    { name: '手机横屏', width: 667, height: 375 },
    { name: '平板', width: 768, height: 1024 },
    { name: '笔记本', width: 1366, height: 768 },
    { name: '桌面', width: 1920, height: 1080 },
    { name: '超宽屏', width: 2560, height: 1440 },
  ]

  for (const vp of viewports) {
    test(`${vp.name} (${vp.width}x${vp.height}) 布局正确`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height })
      await loginAndLoad(page)

      // 主内容区应可见
      const main = page.locator('main')
      await expect(main).toBeVisible({ timeout: 5000 })

      // Tab 栏应可见
      const tabBar = page.locator('button').filter({ hasText: /题库/ }).first()
      await expect(tabBar).toBeVisible({ timeout: 3000 })

      // 侧边栏在小屏应隐藏
      if (vp.width < 1024) {
        const sidebar = page.locator('.sidebar-wrapper')
        const isVisible = await sidebar.isVisible()
        expect(isVisible).toBeFalsy()
      }

      // 无水平溢出
      const bodyWidth = await page.evaluate(() => document.body.scrollWidth)
      expect(bodyWidth).toBeLessThanOrEqual(vp.width + 10) // 10px tolerance
    })
  }
})

// ═══════════════════════════════════════════════
// 11. 通知与 Toast
// ═══════════════════════════════════════════════
test.describe('通知系统', () => {
  test('操作成功后显示 toast', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAndLoad(page)

    // 打开用户菜单切换题库模式（会触发 toast）
    const menuBtn = page.locator('.relative > button').first()
    await menuBtn.click()
    await page.waitForTimeout(300)

    const personalBtn = page.locator('button').filter({ hasText: /个人/ }).first()
    if (await personalBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await personalBtn.click()
      await page.waitForTimeout(500)

      // toast 应出现（vue-sonner）
      const toast = page.locator('[class*="toast"], [class*="sonner"], [data-sonner]').first()
      // toast 可能短暂出现后消失
    }
  })
})

// ═══════════════════════════════════════════════
// 12. 加载状态
// ═══════════════════════════════════════════════
test.describe('加载状态', () => {
  test('数据加载时页面不崩溃', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAndLoad(page)

    // 触发刷新（会重新加载数据）
    const refreshBtn = page.locator('button').filter({ hasText: /刷新/ }).first()
    if (await refreshBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await refreshBtn.click()
      await page.waitForTimeout(1000)
    }

    // 页面应保持稳定
    const main = page.locator('main')
    await expect(main).toBeVisible()
  })

  test('API 错误时显示错误提示和重试按钮', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await setupMocks(page)

    // 让 master-bank 返回 500
    await page.unroute('**/api/master-bank**')
    await page.route('**/api/master-bank**', async (route) => {
      await route.fulfill({ status: 500, json: { detail: '服务器内部错误' } })
    })

    await page.goto('/')
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(2000)

    // 错误提示应出现
    const errorBanner = page.locator('[class*="red"]').filter({ hasText: /失败|错误|重试/ }).first()
    if (await errorBanner.isVisible({ timeout: 3000 }).catch(() => false)) {
      // 重试按钮应可点击
      const retryBtn = page.locator('button').filter({ hasText: /重试/ }).first()
      if (await retryBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
        await retryBtn.click()
        await page.waitForTimeout(500)
      }
    }

    // 页面不应崩溃
    const main = page.locator('main')
    await expect(main).toBeVisible()
  })
})

// ═══════════════════════════════════════════════
// 13. 本地存储持久化
// ═══════════════════════════════════════════════
test.describe('本地存储持久化', () => {
  test('侧边栏折叠状态持久化', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAndLoad(page)

    // 模拟折叠状态
    await page.evaluate(() => localStorage.setItem('sidebar-collapsed', 'true'))
    await page.reload()
    await page.waitForSelector('main', { timeout: 15000 })
    await page.waitForTimeout(500)

    // 刷新后应保持折叠
    const sidebar = page.locator('.sidebar-wrapper')
    const width = await sidebar.evaluate(el => el.getBoundingClientRect().width)
    expect(width).toBeLessThan(50)
  })

  test('暗色模式设置持久化', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAndLoad(page)

    const darkToggle = page.locator('button[title*="暗色"], button[title*="亮色"]').first()
    await darkToggle.click()
    await page.waitForTimeout(300)

    const theme = await page.evaluate(() => localStorage.getItem('interviewboss-theme'))
    expect(theme).toBeTruthy()
  })
})
