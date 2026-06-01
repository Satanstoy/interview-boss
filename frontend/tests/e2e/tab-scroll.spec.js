/**
 * T-001 ~ T-004: Tab 切换滚动位置保持 + Crossfade 动画
 *
 * Playwright E2E 测试 — 通过 CSS 规则和打包内容验证实现。
 * 不依赖登录状态或真实数据。
 */
import { test, expect } from '@playwright/test'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const srcDir = resolve(import.meta.dirname, '../../src')

const readCSS = () => {
  const appVue = readFileSync(resolve(srcDir, 'App.vue'), 'utf-8')
  return appVue
}

test.describe('Tab Scroll Preservation', () => {

  // T-001: useTabScroll composable 存在
  test('T-001: useTabScroll composable is exported', async () => {
    const composablesDir = resolve(srcDir, 'composables')
    const files = readFileSync(resolve(composablesDir, 'useTabScroll.js'), 'utf-8')
    expect(files).toContain('export')
    expect(files).toContain('saveScroll')
    expect(files).toContain('prepareRestore')
    expect(files).toContain('restoreScroll')
  })

  // T-002: tab-fade 动画只用 opacity，无 translateY
  test('T-002: tab-fade uses opacity-only crossfade', async () => {
    const css = readCSS()
    const enterFromMatch = css.match(/\.tab-fade-enter-from\s*\{([^}]*)\}/)
    expect(enterFromMatch).not.toBeNull()
    expect(enterFromMatch[1]).toContain('opacity')
    expect(enterFromMatch[1]).not.toContain('translateY')
  })

  // T-003: tab content 使用 @after-enter hook
  test('T-003: Transition has @after-enter hook', async () => {
    const css = readCSS()
    expect(css).toContain('@after-enter')
  })

  // T-004: restoreScroll 使用 requestAnimationFrame 延迟恢复
  test('T-004: restoreScroll uses requestAnimationFrame', async () => {
    const composablesDir = resolve(srcDir, 'composables')
    const files = readFileSync(resolve(composablesDir, 'useTabScroll.js'), 'utf-8')
    expect(files).toContain('requestAnimationFrame')
  })
})
