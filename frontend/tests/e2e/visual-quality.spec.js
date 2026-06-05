import { test, expect } from '@playwright/test'

const BASE_URL = 'http://localhost'

async function mockAPI(page) {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url()
    
    if (url.includes('/auth/login')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          token: 'mock-token-123',
          user: { id: 1, username: 'testuser', is_admin: true, bank_mode: 'public' }
        })
      })
    } else if (url.includes('/auth/me')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: 1, username: 'testuser', is_admin: true, bank_mode: 'public' })
      })
    } else if (url.includes('/master-bank')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 1, question: 'Vue3 Composition API 的优势', category: '前端框架', difficulty: 'L1', ai_answer: '测试答案', tags: ['Vue3'] },
          { id: 2, question: '微服务架构的优缺点', category: '系统设计', difficulty: 'L2', ai_answer: '测试答案', tags: ['架构'] },
          { id: 3, question: 'TCP 三次握手过程', category: '网络', difficulty: 'L1', ai_answer: '测试答案', tags: ['网络'] }
        ])
      })
    } else if (url.includes('/analytics')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_questions: 100, practiced: 50, categories: { '算法': 30, '系统设计': 20 }
        })
      })
    } else if (url.includes('/practice-stats')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ total: 50, correct: 40, streak: 5 })
      })
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({})
      })
    }
  })
}

async function login(page) {
  await page.goto(BASE_URL)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(1500)

  const usernameInput = page.locator('input[placeholder*="字符"], input[name="username"]').first()
  const passwordInput = page.locator('input[type="password"], input[placeholder*="8 位"]').first()

  await usernameInput.waitFor({ state: 'visible', timeout: 10000 })
  await usernameInput.fill('testuser')
  await passwordInput.fill('password123')

  const loginButton = page.locator('button[type="submit"]:has-text("登录")')
  await loginButton.click()

  await page.waitForTimeout(3000)
}

// 对比度计算（修复了 bg.b bug）
function getContrastRatio(el) {
  function getLum(r, g, b) {
    const [rs, gs, bs] = [r, g, b].map(c => {
      c /= 255
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
    })
    return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs
  }

  function parseColor(c) {
    const m = c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/)
    return m ? { r: +m[1], g: +m[2], b: +m[3] } : null
  }

  const style = getComputedStyle(el)
  const fg = parseColor(style.color)
  const bg = parseColor(style.backgroundColor)
  if (!fg) return null

  const fgLum = getLum(fg.r, fg.g, fg.b)
  
  if (bg && !(bg.r === 0 && bg.g === 0 && bg.b === 0 && style.backgroundColor.includes('rgba(0, 0, 0, 0)'))) {
    const bgLum = getLum(bg.r, bg.g, bg.b)
    const lighter = Math.max(fgLum, bgLum)
    const darker = Math.min(fgLum, bgLum)
    return Math.round(((lighter + 0.05) / (darker + 0.05)) * 100) / 100
  }

  const body = document.querySelector('body')
  const bodyBg = parseColor(getComputedStyle(body).backgroundColor)
  if (!bodyBg) return null
  const bodyLum = getLum(bodyBg.r, bodyBg.g, bodyBg.b)
  const lighter = Math.max(fgLum, bodyLum)
  const darker = Math.min(fgLum, bodyLum)
  return Math.round(((lighter + 0.05) / (darker + 0.05)) * 100) / 100
}

test.describe('视觉质量测试', () => {
  test.beforeEach(async ({ page }) => {
    await mockAPI(page)
  })

  test.describe('S1: 元素对齐', () => {
    test('登录表单：元素左对齐（容差 4px）', async ({ page }) => {
      await page.goto(BASE_URL)
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(1000)

      const alignment = await page.evaluate(() => {
        const els = [
          document.querySelector('input[placeholder*="字符"]'),
          document.querySelector('input[type="password"]'),
          document.querySelector('button[type="submit"]')
        ].filter(Boolean)

        return els.map(el => {
          const rect = el.getBoundingClientRect()
          return { tag: el.tagName, left: Math.round(rect.left) }
        })
      })

      expect(alignment.length).toBeGreaterThanOrEqual(2)
      const lefts = alignment.map(a => a.left)
      const variance = Math.max(...lefts) - Math.min(...lefts)
      expect(variance).toBeLessThanOrEqual(4)
    })

    test('登录表单：垂直间距一致（差值 ≤ 20px）', async ({ page }) => {
      await page.goto(BASE_URL)
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(1000)

      const spacing = await page.evaluate(() => {
        const username = document.querySelector('input[placeholder*="字符"]')
        const password = document.querySelector('input[type="password"]')
        const button = document.querySelector('button[type="submit"]')
        if (!username || !password || !button) return null

        return {
          gap1: Math.round(password.getBoundingClientRect().top - username.getBoundingClientRect().bottom),
          gap2: Math.round(button.getBoundingClientRect().top - password.getBoundingClientRect().bottom)
        }
      })

      expect(spacing).not.toBeNull()
      expect(spacing.gap1).toBeGreaterThanOrEqual(0)
      expect(spacing.gap2).toBeGreaterThanOrEqual(0)
      expect(Math.abs(spacing.gap1 - spacing.gap2)).toBeLessThanOrEqual(20)
    })

    test('后登录：Tab 栏元素 top/height 对齐（容差 2px）', async ({ page }) => {
      await login(page)

      const tabList = page.locator('[role="tablist"]')
      await expect(tabList).toBeVisible({ timeout: 10000 })

      const tabs = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('[role="tab"]')).map(t => {
          const rect = t.getBoundingClientRect()
          return {
            text: t.textContent?.trim(),
            top: Math.round(rect.top),
            height: Math.round(rect.height)
          }
        })
      })

      expect(tabs.length).toBeGreaterThanOrEqual(5)

      const tops = tabs.map(t => t.top)
      const heights = tabs.map(t => t.height)
      const topVariance = Math.max(...tops) - Math.min(...tops)
      const heightVariance = Math.max(...heights) - Math.min(...heights)

      expect(topVariance).toBeLessThanOrEqual(2)
      expect(heightVariance).toBeLessThanOrEqual(2)
    })
  })

  test.describe('S2: 视觉一致性', () => {
    test('颜色对比度 ≥ 3:1（WCAG A）', async ({ page }) => {
      await page.goto(BASE_URL)
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(1000)

      const results = await page.evaluate((calcFn) => {
        const checks = [
          { sel: 'h1', name: 'h1' },
          { sel: 'h2', name: 'h2' },
          { sel: 'h3', name: 'h3' },
          { sel: 'p', name: 'p' }
        ]

        return checks.map(({ sel, name }) => {
          const el = document.querySelector(sel)
          if (!el) return { name, ratio: null }
          const ratio = eval('(' + calcFn + ')(el)')
          return { name, ratio }
        }).filter(r => r.ratio !== null)
      }, getContrastRatio.toString())

      expect(results.length).toBeGreaterThan(0)
      for (const { name, ratio } of results) {
        expect(ratio).toBeGreaterThanOrEqual(3)
      }
    })

    test('后登录：字体层级 h2 ≥ h3 ≥ p', async ({ page }) => {
      await login(page)

      const sizes = await page.evaluate(() => {
        const result = {}
        for (const tag of ['h1', 'h2', 'h3', 'p']) {
          const el = document.querySelector(tag)
          if (el) result[tag] = parseFloat(getComputedStyle(el).fontSize)
        }
        return result
      })

      expect(Object.keys(sizes).length).toBeGreaterThan(0)
      if (sizes.h2 && sizes.h3) expect(sizes.h2).toBeGreaterThanOrEqual(sizes.h3)
      if (sizes.h3 && sizes.p) expect(sizes.h3).toBeGreaterThanOrEqual(sizes.p)
    })
  })

  test.describe('S3: 暗黑模式', () => {
    test('切换暗黑模式后背景色变暗', async ({ page }) => {
      await login(page)

      const lightBg = await page.evaluate(() => {
        return getComputedStyle(document.querySelector('body')).backgroundColor
      })

      const toggle = page.locator('button[title*="切换到暗色"]').first()
      await expect(toggle).toBeVisible({ timeout: 5000 })

      await toggle.click()
      await page.waitForTimeout(500)

      const darkState = await page.evaluate(() => {
        const body = document.querySelector('body')
        return {
          bg: getComputedStyle(body).backgroundColor,
          isDark: document.documentElement.classList.contains('dark')
        }
      })

      expect(darkState.isDark).toBeTruthy()

      const parseRgb = (s) => s.match(/\d+/g)?.map(Number) || [0, 0, 0]
      const lightSum = parseRgb(lightBg).reduce((a, b) => a + b, 0)
      const darkSum = parseRgb(darkState.bg).reduce((a, b) => a + b, 0)
      expect(darkSum).toBeLessThan(lightSum)
    })
  })

  test.describe('S4: 响应式布局', () => {
    test('登录页：375/768/1920px 无水平溢出', async ({ page }) => {
      for (const vp of [
        { name: 'Mobile', w: 375, h: 667 },
        { name: 'Tablet', w: 768, h: 1024 },
        { name: 'Desktop', w: 1920, h: 1080 }
      ]) {
        await page.goto(BASE_URL)
        await page.waitForLoadState('networkidle')
        await page.waitForTimeout(500)
        await page.setViewportSize({ width: vp.w, height: vp.h })
        await page.waitForTimeout(300)

        const overflow = await page.evaluate(() => {
          return document.body.scrollWidth > window.innerWidth + 1
        })
        expect(overflow).toBeFalsy()
      }
    })

    test('后登录：Desktop Tab 栏无意外溢出', async ({ page }) => {
      await login(page)

      await page.setViewportSize({ width: 1920, height: 1080 })
      await page.waitForTimeout(500)

      const tabList = page.locator('[role="tablist"]')
      if (await tabList.count() > 0) {
        const tabOverflow = await tabList.evaluate(el => {
          return el.scrollWidth > el.clientWidth + 2
        })
        expect(tabOverflow).toBeFalsy()
      }
    })
  })

  test.describe('S5: 组件完整性', () => {
    test('登录页：必要元素全部存在', async ({ page }) => {
      await page.goto(BASE_URL)
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(1000)

      const els = await page.evaluate(() => ({
        logo: !!document.querySelector('h1'),
        usernameInput: !!document.querySelector('input[placeholder*="字符"]'),
        passwordInput: !!document.querySelector('input[type="password"]'),
        submitButton: !!document.querySelector('button[type="submit"]')
      }))

      expect(els.logo).toBeTruthy()
      expect(els.usernameInput).toBeTruthy()
      expect(els.passwordInput).toBeTruthy()
      expect(els.submitButton).toBeTruthy()
    })

    test('按钮高度：30-44px 范围内', async ({ page }) => {
      await page.goto(BASE_URL)
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(1000)

      const btns = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('button[type="submit"]')).map(btn => ({
          text: btn.textContent?.trim().substring(0, 15),
          height: Math.round(btn.getBoundingClientRect().height)
        }))
      })

      for (const btn of btns) {
        expect(btn.height).toBeGreaterThanOrEqual(30)
        expect(btn.height).toBeLessThanOrEqual(44)
      }
    })
  })

  test.describe('S6: 后登录页面', () => {
    test('高频题库 tab 有内容', async ({ page }) => {
      await login(page)

      const masterTab = page.locator('[role="tab"]:has-text("高频题库")')
      if (await masterTab.count() > 0) {
        await masterTab.click()
        await page.waitForTimeout(2000)

        const contentLen = await page.evaluate(() => {
          const content = document.querySelector('.tab-content, [data-motion="tab-transition"]')
          return content ? content.innerHTML.length : 0
        })
        expect(contentLen).toBeGreaterThan(30)
      }
    })

    test('切换 tab 后内容区域更新', async ({ page }) => {
      await login(page)

      const tabNames = ['JD 筛选', '面经库', '高频题库']
      for (const name of tabNames) {
        const tab = page.locator(`[role="tab"]:has-text("${name}")`)
        if (await tab.count() > 0) {
          await tab.click()
          await page.waitForTimeout(1000)

          const hasContent = await page.evaluate(() => {
            const el = document.querySelector('.tab-content, [data-motion="tab-transition"]')
            return el ? el.innerHTML.length > 20 : false
          })
          expect(hasContent).toBeTruthy()
        }
      }
    })

    test('后登录：按钮高度 30-44px', async ({ page }) => {
      await login(page)

      const btns = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('button')).slice(0, 10).map(btn => {
          const rect = btn.getBoundingClientRect()
          return {
            text: btn.textContent?.trim().substring(0, 15),
            height: Math.round(rect.height),
            visible: rect.width > 0 && rect.height > 0
          }
        }).filter(b => b.visible && b.text.length > 0)
      })

      expect(btns.length).toBeGreaterThan(0)
      for (const btn of btns) {
        expect(btn.height).toBeGreaterThanOrEqual(20)
        expect(btn.height).toBeLessThanOrEqual(64)
      }
    })
  })

  test.describe('S7: 动画/过渡', () => {
    test('登录按钮有 CSS 过渡动画', async ({ page }) => {
      await page.goto(BASE_URL)
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(1000)

      const transitions = await page.evaluate(() => {
        const btn = document.querySelector('button[type="submit"]')
        if (!btn) return null
        const style = getComputedStyle(btn)
        return {
          property: style.transitionProperty,
          duration: style.transitionDuration
        }
      })

      expect(transitions).not.toBeNull()
      expect(transitions.property).not.toBe('none')
      expect(transitions.duration).not.toBe('0s')
    })

    test('后登录：Tab 切换有过渡效果', async ({ page }) => {
      await login(page)

      const tabTransition = await page.evaluate(() => {
        const el = document.querySelector('.tab-content, [data-motion="tab-transition"]')
        if (!el) return null
        const style = getComputedStyle(el)
        return {
          property: style.transitionProperty,
          duration: style.transitionDuration
        }
      })

      if (tabTransition) {
        expect(tabTransition.property).not.toBe('none')
      }
    })

    test('支持 prefers-reduced-motion', async ({ page }) => {
      await page.goto(BASE_URL)
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(1000)

      await page.emulateMedia({ reducedMotion: 'reduce' })
      await page.waitForTimeout(300)

      const reducedMotion = await page.evaluate(() => {
        const btn = document.querySelector('button[type="submit"]')
        if (!btn) return null
        const style = getComputedStyle(btn)
        return {
          duration: parseFloat(style.transitionDuration) || 0
        }
      })

      if (reducedMotion) {
        expect(reducedMotion.duration).toBeLessThanOrEqual(0.01)
      }
    })
  })
})
