import { test } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'
const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

test('debug panel height', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 }).catch(() => {})
  await page.waitForSelector('.card-smooth', { timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(1000)
  
  const info = await page.evaluate(() => {
    const panel = document.querySelector('.overflow-hidden.rounded-2xl')
    const wrapper = panel?.querySelector('[class*="p-3"]')
    const container = wrapper?.querySelector('.space-y-4')
    const scroller = container?.querySelector('.virtual-scroller')
    return {
      panel: panel ? { ch: panel.clientHeight, oh: panel.offsetHeight, rect: panel.getBoundingClientRect(), computed: getComputedStyle(panel).height } : null,
      wrapper: wrapper ? { ch: wrapper.clientHeight, pt: getComputedStyle(wrapper).paddingTop, pb: getComputedStyle(wrapper).paddingBottom, rect: wrapper.getBoundingClientRect() } : null,
      container: container ? { ch: container.clientHeight, cssVar: getComputedStyle(container).getPropertyValue('--scroller-h') } : null,
      scroller: scroller ? { ch: scroller.clientHeight, height: getComputedStyle(scroller).height } : null,
    }
  })
  console.log('DEBUG:', JSON.stringify(info, null, 2))
})
