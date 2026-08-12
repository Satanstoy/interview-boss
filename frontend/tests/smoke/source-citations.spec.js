import { expect, test } from '@playwright/test'

test('source citations render as visible cards with favicon and original URL', async ({ page }) => {
  await page.goto('/login')

  const result = await page.evaluate(async () => {
    const { createApp } = await import('/node_modules/vue/dist/vue.esm-browser.js')
    const { default: SourceList } = await import('/src/components/common/SourceList.vue')
    const root = document.createElement('div')
    document.body.appendChild(root)
    const app = createApp(SourceList, {
      sources: [{
        title: 'Vue 官方文档',
        url: 'https://vuejs.org/guide/introduction.html',
        snippet: 'Vue 是用于构建用户界面的渐进式框架。',
      }],
      open: true,
      testId: 'citation-smoke',
    })
    app.mount(root)
    await new Promise(resolve => requestAnimationFrame(resolve))

    const card = root.querySelector('[data-testid="citation-smoke"]')
    const link = card?.querySelector('a')
    const favicon = card?.querySelector('img')
    const result = {
      cardVisible: Boolean(card),
      linkHref: link?.getAttribute('href') || '',
      linkTarget: link?.getAttribute('target') || '',
      cardClass: link?.className || '',
      faviconSrc: favicon?.getAttribute('src') || '',
      text: card?.textContent || '',
    }
    app.unmount()
    root.remove()
    return result
  })

  expect(result.cardVisible).toBe(true)
  expect(result.linkHref).toBe('https://vuejs.org/guide/introduction.html')
  expect(result.linkTarget).toBe('_blank')
  expect(result.cardClass).toContain('source-card')
  expect(result.faviconSrc).toContain('google.com/s2/favicons')
  expect(result.text).toContain('Vue 官方文档')
  expect(result.text).toContain('vuejs.org')
  expect(result.text).toContain('Vue 是用于构建用户界面的渐进式框架')
})
